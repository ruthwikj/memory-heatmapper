import ctypes
import mmap
import os
import tempfile
import time

print(f"PID: {os.getpid()}")

# 1. Heap via ctypes malloc (~40MB) — shows as [heap]
libc = ctypes.CDLL("libc.so.6")
libc.malloc.restype = ctypes.c_void_p
heap_ptrs = []
for _ in range(40):
    ptr = libc.malloc(1024 * 1024)
    ctypes.memset(ptr, 0x41, 1024 * 1024)
    heap_ptrs.append(ptr)
print("  40 MB heap (malloc)")

# 2. Memory-mapped file (~30MB) — shows as Memory-Mapped File
tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mmap')
tmp.write(b'\x00' * 30 * 1024 * 1024)
tmp.flush()
mm = mmap.mmap(tmp.fileno(), 30 * 1024 * 1024)
mm[:] = b'B' * 30 * 1024 * 1024
print(f"  30 MB mmap file ({tmp.name})")

# 3. Anonymous mmap (~20MB) — shows as Anonymous
anon_maps = []
for _ in range(20):
    m = mmap.mmap(-1, 1024 * 1024)
    m[:] = b'C' * 1024 * 1024
    anon_maps.append(m)
print("  20 MB anonymous mmap")

print(f"\nTotal ~90 MB allocated. Sleeping...")
time.sleep(300)
