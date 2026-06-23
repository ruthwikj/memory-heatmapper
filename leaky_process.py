"""A process that leaks heap memory on purpose.

Every second it mallocs (and touches, so the pages are really resident) ~2 MB
of fresh memory and never frees it. We allocate in 64 KB chunks so they stay
under glibc's mmap threshold and land on the real brk heap — that way the leak
shows up under the "[heap]" region rather than as anonymous mmaps.

Point heatmap.py at its PID and switch to the Private view ([o]) to watch the
heap region climb and trip leak detection (red ⚠ border + LEAK banner).
"""
import ctypes
import os
import time

libc = ctypes.CDLL("libc.so.6")
libc.malloc.restype = ctypes.c_void_p

print(f"PID: {os.getpid()}")
print("Leaking ~2 MB/sec into the heap. Watch [o]Private grow and the")
print("region get a red ⚠ border in heatmap.py. Ctrl-C to stop.")

CHUNK = 64 * 1024            # 64 KB — under glibc's 128 KB mmap threshold
CHUNKS_PER_SEC = 32         # 32 * 64 KB = 2 MB/sec
leaked = []  # keep references so nothing is ever reclaimed
try:
    while True:
        for _ in range(CHUNKS_PER_SEC):
            ptr = libc.malloc(CHUNK)
            if ptr:
                ctypes.memset(ptr, 0x7F, CHUNK)  # touch every page so RSS rises
                leaked.append(ptr)
        time.sleep(1)
except KeyboardInterrupt:
    leaked_mb = len(leaked) * CHUNK / 1024 / 1024
    print(f"\nStopped after leaking {leaked_mb:.0f} MB.")
