# Memory Heatmapper

A lightweight, real-time terminal memory profiler that visualizes a Linux process's memory usage as an interactive treemap.

## What it does
- Reads `/proc/<pid>/smaps` to get per-region memory stats
- Parses and groups regions by name and category
- Renders a live-updating treemap in the terminal using ANSI escape codes
- Lets the user toggle between RSS, PSS, Private, and Swap metrics in real time

## How to run
```bash
python3 heatmap.py --pid <PID>
python3 heatmap.py --pid <PID> --interval 2.0
```

## Keybindings
- `r` — view RSS (physical RAM)
- `p` — view PSS (shared cost)
- `o` — view Private (exclusively owned)
- `s` — view Swap (on disk)
- `q` — quit

## Project structure
- `heatmap.py` — main file, contains everything
- `demo_process.py` — test process that allocates memory for profiling

## Key implementation details
- Squarified treemap algorithm (Bruls et al. 2000) for rectangle layout
- ANSI escape codes for color rendering, no external TUI library
- `select.select` for non-blocking keyboard input between refresh cycles
- Regions under 0.4% of total are lumped into an "(other)" bucket
- Large Python allocations appear as "anonymous" not "heap" due to mmap behavior
- Private metric sums both Private_Clean and Private_Dirty from smaps
- Treemap is centered (horizontally and vertically) with `─` borders
- Full screen clear (`\033[2J`) + erase-to-EOL (`\033[K`) each frame to prevent resize artifacts

## Environment
- Runs inside a Docker container (Ubuntu 22.04)
- Python 3.10
- Linux only — depends on /proc filesystem
- Dependencies: click

## What's next
- Add leak detection (watch Private memory grow over time)
- Add a leaky demo process
- Write a README with a demo GIF
- Benchmark CPU overhead
