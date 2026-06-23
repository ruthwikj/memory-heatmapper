import click
from rich.console import Console
from rich.table import Table

console = Console()

def categorize(region_name, permissions):
    if '[heap]' in region_name:
        return 'Heap'
    elif '[stack]' in region_name:
        return 'Stack'
    elif region_name.endswith('.so') or '.so.' in region_name:
        return 'Shared Library'
    elif region_name and '[' not in region_name:
        return 'Memory-Mapped File'
    else:
        return 'Anonymous'

def parse_smaps(pid):
    regions = []
    current = None

    with open(f"/proc/{pid}/smaps") as f:
        for line in f:
            line = line.strip()
            # A new region starts with a hex address range like "aaaa1000-aaaa2000"
            if line and '-' in line.split()[0] and not line.startswith('VmFlags'):
                parts = line.split()
                try:
                    int(parts[0].split('-')[0], 16)
                    if current is not None:
                        regions.append(current)
                    current = {
                        'address': parts[0],
                        'permissions': parts[1] if len(parts) > 1 else '',
                        'name': parts[5] if len(parts) > 5 else '',
                        'rss': 0
                    }
                except (ValueError, IndexError):
                    pass
            elif line.startswith('Rss:') and current is not None:
                current['rss'] = int(line.split()[1])

    if current is not None:
        regions.append(current)

    return regions

def summarize(regions):
    totals = {}
    for r in regions:
        category = categorize(r['name'], r['permissions'])
        totals[category] = totals.get(category, 0) + r['rss']
    return totals

@click.command()
@click.option('--pid', required=True, type=int, help='PID of the process to inspect')
def main(pid):
    regions = parse_smaps(pid)
    totals = summarize(regions)

    table = Table(title=f"Memory Usage for PID {pid}")
    table.add_column("Category", style="cyan")
    table.add_column("RSS (kB)", justify="right", style="green")
    table.add_column("RSS (MB)", justify="right", style="yellow")

    for category, kb in sorted(totals.items(), key=lambda x: -x[1]):
        table.add_row(category, str(kb), f"{kb/1024:.1f}")

    console.print(table)

if __name__ == '__main__':
    main()