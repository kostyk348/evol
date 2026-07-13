"""Debug ratelimiter and cache gen output."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus2 import *

for name, fn in [('ratelimiter', gen_ratelimiter_py2), ('cache', gen_cache_py2)]:
    src = fn(10)
    lines = src.split('\n')
    print(f"\n=== {name} ===")
    for i, l in enumerate(lines, 1):
        print(f"{i:3d}: {l}")
