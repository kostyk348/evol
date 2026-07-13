"""Debug M3 Python AST parsing."""
import sys, os, ast as pyast
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus2 import *

for name, gen_fn, exp_fn in [
    ('dispatcher', gen_dispatcher_py2, py_dispatcher_explicit2),
    ('statemachine', gen_statemachine_py2, py_statemachine_explicit2),
    ('pipeline', gen_pipeline_py2, py_pipeline_explicit2),
    ('ratelimiter', gen_ratelimiter_py2, py_ratelimiter_explicit2),
    ('cache', gen_cache_py2, py_cache_explicit2),
]:
    n = 10
    for label, src in [('gen', gen_fn(n)), ('explicit', exp_fn(n))]:
        try:
            pyast.parse(src)
            print(f'  {name}/{label}: OK ({len(src)} chars)')
        except SyntaxError as e:
            print(f'  {name}/{label}: SYNTAX ERROR: {e}')
            lines = src.split('\n')
            for i, l in enumerate(lines[:5], 1):
                print(f'    {i}: {l}')
