import os
import sys
import time
import select
import termios
import tty
import shutil
from collections import deque
import click

# 256-color palette: (bg color index, fg color index)
CATEGORY_STYLE = {
    'Heap':               (167, 255),  # muted coral
    'Shared Library':     (72,  255),  # teal
    'Memory-Mapped File': (68,  255),  # steel blue
    'Stack':              (179, 236),  # warm sand
    'Anonymous':          (133, 255),  # muted plum
    'other':              (241, 250),  # dim grey
}

def _bg(color):
    return f'48;5;{color}'

def _fg(color):
    return f'38;5;{color}'

METRICS = {
    'rss':     'RSS (physical RAM)',
    'pss':     'PSS (shared cost)',
    'private': 'Private (owned)',
    'swap':    'Swap (on disk)',
}

# one-liners for the [h]elp overlay — what a dev actually cares about
METRIC_HELP = {
    'rss':     'physical RAM footprint (shared + private)',
    'pss':     'true cost per process (shared / users + private)',
    'private': 'memory owned exclusively (grows = likely leak)',
    'swap':    'paged out to disk (high = memory pressure)',
}


# ---------------------------------------------------------------------------
# 1. PARSING — read smaps into individual regions
# ---------------------------------------------------------------------------
def label_and_category(name):
    if name == '[heap]':
        return 'heap', 'Heap'
    if name == '[stack]':
        return 'stack', 'Stack'
    if name.endswith('.so') or '.so.' in name:
        return os.path.basename(name), 'Shared Library'
    if name.startswith('['):
        return name.strip('[]'), 'Anonymous'
    if name:
        return os.path.basename(name), 'Memory-Mapped File'
    return 'anonymous', 'Anonymous'


def parse_smaps(pid):
    regions = []
    current = None
    with open(f"/proc/{pid}/smaps") as f:
        for line in f:
            line = line.rstrip()
            stripped = line.strip()
            if stripped and '-' in stripped.split()[0] and not stripped.startswith('VmFlags'):
                parts = stripped.split()
                try:
                    int(parts[0].split('-')[0], 16)
                    if current is not None:
                        regions.append(current)
                    name = parts[5] if len(parts) > 5 else ''
                    label, category = label_and_category(name)
                    current = {'label': label, 'category': category,
                               'rss': 0, 'pss': 0, 'private': 0, 'swap': 0}
                    continue
                except (ValueError, IndexError):
                    pass
            if current is not None:
                if stripped.startswith('Rss:'):
                    current['rss'] = int(stripped.split()[1])
                elif stripped.startswith('Pss:'):
                    current['pss'] = int(stripped.split()[1])
                elif stripped.startswith('Private_Clean:'):
                    current['private'] += int(stripped.split()[1])
                elif stripped.startswith('Private_Dirty:'):
                    current['private'] += int(stripped.split()[1])
                elif stripped.startswith('Swap:'):
                    current['swap'] = int(stripped.split()[1])
    if current is not None:
        regions.append(current)
    return regions


def group_regions(regions):
    """Merge all regions that share a display label (e.g. all libc segments)."""
    groups = {}
    for r in regions:
        g = groups.setdefault(r['label'], {'label': r['label'], 'category': r['category'],
                                           'rss': 0, 'pss': 0, 'private': 0, 'swap': 0})
        for k in ('rss', 'pss', 'private', 'swap'):
            g[k] += r[k]
    return list(groups.values())


# ---------------------------------------------------------------------------
# 1b. LEAK DETECTION — track per-region Private memory growth over time
# ---------------------------------------------------------------------------
class LeakDetector:
    """Watches each region's Private memory and flags sustained growth.

    Leaks show up as private (owned) memory that keeps climbing, so we keep a
    rolling window of samples per region and report any that have grown
    meaningfully and mostly-monotonically across the window.
    """

    def __init__(self, window=15):
        self.window = window
        self.history = {}  # label -> deque[(timestamp, private_kb)]

    def update(self, groups):
        now = time.time()
        seen = set()
        for g in groups:
            seen.add(g['label'])
            dq = self.history.setdefault(g['label'], deque(maxlen=self.window))
            dq.append((now, g['private']))
        for label in list(self.history):
            if label not in seen:
                del self.history[label]

    def leaks(self):
        """Return [(label, rate_mb_per_min, delta_kb)] for growing regions, worst first."""
        out = []
        for label, dq in self.history.items():
            if len(dq) < 5:
                continue
            (t0, v0), (t1, v1) = dq[0], dq[-1]
            dt = t1 - t0
            delta = v1 - v0
            if dt <= 0:
                continue
            # meaningful (>1 MB and >5%) and mostly rising across the window
            if delta > 1024 and v1 > v0 * 1.05 and self._mostly_rising(dq):
                rate = (delta / 1024) / (dt / 60)  # MB per minute
                out.append((label, rate, delta))
        out.sort(key=lambda x: -x[1])
        return out

    @staticmethod
    def _mostly_rising(dq):
        vals = [v for _, v in dq]
        ups = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
        return ups >= 0.7 * (len(vals) - 1)


# ---------------------------------------------------------------------------
# 2. SQUARIFIED TREEMAP ALGORITHM 
# ---------------------------------------------------------------------------
def normalize_sizes(sizes, dx, dy):
    total = sum(sizes)
    area = dx * dy
    return [s * area / total for s in sizes]


def layoutrow(sizes, x, y, dy):
    width = sum(sizes) / dy
    rects, cy = [], y
    for s in sizes:
        rects.append((x, cy, width, s / width))
        cy += s / width
    return rects


def layoutcol(sizes, x, y, dx):
    height = sum(sizes) / dx
    rects, cx = [], x
    for s in sizes:
        rects.append((cx, y, s / height, height))
        cx += s / height
    return rects


def layout(sizes, x, y, dx, dy):
    return layoutrow(sizes, x, y, dy) if dx >= dy else layoutcol(sizes, x, y, dx)


def leftover(sizes, x, y, dx, dy):
    if dx >= dy:
        width = sum(sizes) / dy
        return (x + width, y, dx - width, dy)
    height = sum(sizes) / dx
    return (x, y + height, dx, dy - height)


def worst_ratio(sizes, x, y, dx, dy):
    return max(max(w / h, h / w) for (_, _, w, h) in layout(sizes, x, y, dx, dy))


def squarify(sizes, x, y, dx, dy):
    sizes = list(map(float, sizes))
    if not sizes:
        return []
    if len(sizes) == 1:
        return layout(sizes, x, y, dx, dy)
    i = 1
    while i < len(sizes) and worst_ratio(sizes[:i], x, y, dx, dy) >= worst_ratio(sizes[:i + 1], x, y, dx, dy):
        i += 1
    current, remaining = sizes[:i], sizes[i:]
    lx, ly, ldx, ldy = leftover(current, x, y, dx, dy)
    return layout(current, x, y, dx, dy) + squarify(remaining, lx, ly, ldx, ldy)


# ---------------------------------------------------------------------------
# 3. CANVAS — a grid of colored cells we paint rectangles onto
# ---------------------------------------------------------------------------
class Canvas:
    def __init__(self, width, height):
        self.w, self.h = width, height
        self.cells = [[(' ', '') for _ in range(width)] for _ in range(height)]

    def fill(self, x, y, w, h, label, value_str, pct_str, category):
        bg_c, fg_c = CATEGORY_STYLE.get(category, CATEGORY_STYLE['other'])
        bg = _bg(bg_c)
        fg_bold = f'1;{_fg(fg_c)};{bg}'
        fg_dim = f'2;{_fg(fg_c)};{bg}'
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.w, x1), min(self.h, y1)
        # draw border cells with dim style, inner cells with bg
        for ry in range(y0, y1):
            for rx in range(x0, x1):
                is_edge = (ry == y0 or ry == y1 - 1 or rx == x0 or rx == x1 - 1)
                if is_edge:
                    self.cells[ry][rx] = (' ', f'2;{bg}')
                else:
                    self.cells[ry][rx] = (' ', bg)
        box_w = x1 - x0
        box_h = y1 - y0
        inner_w = box_w - 2
        if inner_w >= 3 and box_h >= 2:
            text = label[:inner_w]
            for j, ch in enumerate(text):
                self.cells[y0 + 1][x0 + 1 + j] = (ch, fg_bold)
        if inner_w >= 3 and box_h >= 3:
            text = f'{value_str}  {pct_str}'[:inner_w]
            for j, ch in enumerate(text):
                self.cells[y0 + 2][x0 + 1 + j] = (ch, fg_dim)

    def render(self):
        lines = []
        for row in self.cells:
            out, cur = [], None
            for ch, sgr in row:
                if sgr != cur:
                    out.append('\033[0m')
                    if sgr:
                        out.append(f'\033[{sgr}m')
                    cur = sgr
                out.append(ch)
            out.append('\033[0m')
            lines.append(''.join(out))
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 4. HELPERS
# ---------------------------------------------------------------------------
def get_proc_name(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            data = f.read().replace(b'\x00', b' ').strip()
            if data:
                return data.decode(errors='replace')[:40]
    except OSError:
        pass
    return '?'


def human(kb):
    mb = kb / 1024
    if mb >= 1024:
        return f'{mb / 1024:.2f} GB'
    return f'{mb:.1f} MB'


def build_frame(pid, metric, width, height):
    regions = parse_smaps(pid)
    groups = group_regions(regions)
    total = sum(g[metric] for g in groups)

    header = (f'\033[1m PID {pid}\033[0m  {get_proc_name(pid)}  '
              f'\033[2m│\033[0m  {METRICS[metric].split(" (")[0]}: \033[1m{human(total)}\033[0m')

    legend = '  '.join(f'\033[{_bg(bg)}m  \033[0m \033[2m{cat}\033[0m'
                       for cat, (bg, _) in CATEGORY_STYLE.items() if cat != 'other')
    keys = ('\033[2m[r]RSS [p]PSS [o]Private [s]Swap [q]quit\033[0m   '
            f'\033[1mviewing: {METRICS[metric]}\033[0m')

    border_top = '╭' + '─' * (width - 2) + '╮'
    border_bot = '╰' + '─' * (width - 2) + '╯'

    if total <= 0:
        msg = f'\n  No "{metric}" data for this process (all zero).\n'
        return header + '\n' + border_top + '\n' + msg + '\n' + border_bot + '\n' + legend + '\n' + keys

    threshold = total * 0.004
    big = [g for g in groups if g[metric] >= threshold and g[metric] > 0]
    small = [g for g in groups if 0 < g[metric] < threshold]
    if small:
        big.append({'label': '(other)', 'category': 'other',
                    metric: sum(g[metric] for g in small)})
    big.sort(key=lambda g: -g[metric])

    sizes = normalize_sizes([g[metric] for g in big], width, height)
    rects = squarify(sizes, 0, 0, width, height)

    canvas = Canvas(width, height)
    for g, (x, y, w, h) in zip(big, rects):
        pct = f'{g[metric] / total * 100:.0f}%'
        canvas.fill(x, y, w, h, g['label'], human(g[metric]), pct, g['category'])

    return header + '\n' + border_top + '\n' + canvas.render() + '\n' + border_bot + '\n' + legend + '\n' + keys


# ---------------------------------------------------------------------------
# 5. MAIN LOOP with live keyboard toggle
# ---------------------------------------------------------------------------
@click.command()
@click.option('--pid', required=True, type=int, help='PID of the process to inspect')
@click.option('--interval', default=1.0, help='Refresh interval in seconds')
@click.option('--metric', default='rss', type=click.Choice(list(METRICS)), help='Starting metric')
def main(pid, interval, metric):
    interactive = sys.stdin.isatty()
    old = termios.tcgetattr(sys.stdin) if interactive else None
    if interactive:
        tty.setcbreak(sys.stdin.fileno())
    sys.stdout.write('\033[?25l\033[2J')  # hide cursor, clear screen
    try:
        while True:
            size = shutil.get_terminal_size((80, 24))
            cw = max(40, size.columns // 2)
            ch = max(5, size.lines // 2)
            try:
                frame = build_frame(pid, metric, cw, ch)
            except FileNotFoundError:
                sys.stdout.write('\033[2J\033[H')
                print(f'Process {pid} not found or has exited.')
                break
            frame_lines = frame.split('\n')
            pad_left = ' ' * ((size.columns - cw) // 2)
            pad_top = max(0, (size.lines - len(frame_lines)) // 2)
            padded_frame = '\n' * pad_top + '\n'.join(pad_left + line + '\033[K' for line in frame_lines)
            sys.stdout.write('\033[H' + padded_frame + '\033[J')
            sys.stdout.flush()

            if interactive:
                r, _, _ = select.select([sys.stdin], [], [], interval)
                if r:
                    c = sys.stdin.read(1)
                    if c == 'q':
                        break
                    elif c == 'r': metric = 'rss'
                    elif c == 'p': metric = 'pss'
                    elif c == 'o': metric = 'private'
                    elif c == 's': metric = 'swap'
            else:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write('\033[?25h\033[0m\n')  # show cursor
        if old:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


if __name__ == '__main__':
    main()
