# Memory Heatmap

A real-time terminal memory profiler that visualizes a Linux process's memory usage as an interactive treemap.

![demo](demo.gif)

## Why

Tools like `top` and `htop` show you a single RSS number. But a process's memory is made up of many regions — heap, stack, shared libraries, memory-mapped files, anonymous pages — and knowing *where* the memory lives is what matters when you're debugging a leak or optimizing footprint.

Memory Heatmap reads `/proc/<pid>/smaps` and renders a live, color-coded treemap so you can see at a glance what's eating RAM.

## Features

- **Live treemap** — squarified layout, 256-color palette, updates every second
- **4 metrics** — toggle between RSS, PSS, Private, and Swap in real time
- **Leak detection** — watches Private memory over a rolling window; flags regions that keep growing with a red border and banner
- **Detail table** — lists every region with size and percentage, even ones too small to label in the treemap
- **Help overlay** — press `h` for a quick reference on what each metric means
- **Zero dependencies** — just Python 3 and `click` (no curses, no rich, no external TUI library)

## Quick start

```bash
# Install
pip install click

# Run against any process
python3 heatmap.py --pid <PID>

# Or use the included demo process
python3 demo_process.py & python3 heatmap.py --pid $!
```

## Usage

```
python3 heatmap.py --pid <PID> [--interval 1.0] [--metric rss]
```

| Option       | Default | Description                          |
|--------------|---------|--------------------------------------|
| `--pid`      | required| PID of the process to inspect        |
| `--interval` | `1.0`   | Refresh interval in seconds          |
| `--metric`   | `rss`   | Starting metric (`rss`, `pss`, `private`, `swap`) |

## Keybindings

| Key | Action                              |
|-----|-------------------------------------|
| `r` | View RSS (physical RAM)             |
| `p` | View PSS (proportional shared cost) |
| `o` | View Private (exclusively owned)    |
| `s` | View Swap (paged to disk)           |
| `h` | Toggle help overlay                 |
| `q` | Quit                                |

## What the metrics mean

| Metric    | One-liner                                          |
|-----------|----------------------------------------------------|
| **RSS**   | Physical RAM footprint (shared + private)          |
| **PSS**   | True cost per process (shared / users + private)   |
| **Private** | Memory owned exclusively (grows = likely leak)   |
| **Swap**  | Paged out to disk (high = memory pressure)         |

## Leak detection

Switch to Private view (`o`) and watch. The `LeakDetector` tracks each region's Private memory over a rolling window of 15 samples. If a region's Private memory:
- grew by more than 1 MB
- grew by more than 5%
- was mostly rising across the window (70%+ of samples increasing)

...it gets flagged with a red border in the treemap and a `LEAK` banner in the header.

Try it with the included leaky process:

```bash
python3 leaky_process.py & python3 heatmap.py --pid $! --metric private
```

This leaks ~2 MB/sec into the heap. After ~10 seconds you should see the heap region get a red warning border.

## Demo processes

| File | What it does |
|------|-------------|
| `demo_process.py` | Allocates 40 MB heap (malloc), 30 MB mmap file, 20 MB anonymous mmap — shows all memory categories |
| `leaky_process.py` | Leaks ~2 MB/sec into the heap via malloc — triggers leak detection |

## How it works

1. **Parse** `/proc/<pid>/smaps` — extract per-region RSS, PSS, Private, Swap
2. **Group** regions by display label (e.g., all `libc.so.6` segments merge)
3. **Squarify** — Bruls et al. 2000 algorithm to lay out proportional rectangles
4. **Render** — paint colored rectangles onto a character grid with ANSI escape codes
5. **Repeat** — non-blocking keyboard input via `select.select`, refresh on interval

## Requirements

- Linux (depends on `/proc` filesystem)
- Python 3.8+
- `click` (`pip install click`)

## License

MIT
