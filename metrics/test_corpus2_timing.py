"""Timing test for corpus2 at N=100 and N=1000."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus2 import *
from parser import parse
from interpreter import run

for n in [100, 1000]:
    print(f"\n=== N={n} ===")
    for name, fn in [('dispatcher', gen_dispatcher_ev2),
                     ('statemachine', gen_statemachine_ev2),
                     ('pipeline', gen_pipeline_ev2),
                     ('ratelimiter', gen_ratelimiter_ev2),
                     ('cache', gen_cache_ev2)]:
        t0 = time.time()
        src = fn(n)
        te = evol_tokens(src)
        py_src = {
            'dispatcher': gen_dispatcher_py2,
            'statemachine': gen_statemachine_py2,
            'pipeline': gen_pipeline_py2,
            'ratelimiter': gen_ratelimiter_py2,
            'cache': gen_cache_py2,
        }[name](n)
        tp = python_tokens(py_src)
        t_gen = time.time() - t0

        t1 = time.time()
        ast = parse(src, name)
        r = run(ast, ['boot'])
        t_run = time.time() - t1
        print(f'  {name:14s}: gen={t_gen:.2f}s tokens={te}/{tp}={te/tp:.3f} run={t_run:.2f}s steps={r["steps"]}')

print('\nTIMING OK')
