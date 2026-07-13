"""Quick validation of all corpus2 generators at N=10."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus2 import *
from parser import parse
from interpreter import run

for name, fn, n in [('dispatcher', gen_dispatcher_ev2, 10),
                     ('statemachine', gen_statemachine_ev2, 10),
                     ('pipeline', gen_pipeline_ev2, 10),
                     ('ratelimiter', gen_ratelimiter_ev2, 10),
                     ('cache', gen_cache_ev2, 10),
                     ('httprouter', gen_httprouter_ev2, None)]:
    src = fn() if n is None else fn(n)
    ast = parse(src, name)
    r = run(ast, ['boot'])
    te = evol_tokens(src)
    print(f'{name}: {te} tokens, {r["steps"]} steps, store_keys={len(r["store"])}')
print('ALL GENERATORS OK')
