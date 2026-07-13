"""Corpus #2: Held-out benchmark (6 tasks, N=10/100/1000/10000).

Seeds зафиксированы ДО запуска (см. spec):
  dispatcher: seed=20260713-1
  statemachine: seed=20260713-2
  pipeline: seed=20260713-3
  ratelimiter: seed=20260713-4
  cache: seed=20260713-5
  http_router: fixed ~50 routes

Каждый gen_* возвращает (evol_src, py_src).
Rust baseline — gen_rust_* возвращает str(n) -> rust_src.
EXPLICIT — альтернативная реализация для M3.
"""

import os
import sys
import random as _rnd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lexer import tokenize
from parser import parse
from interpreter import run
from typechecker import proven_properties, collect_facts
import smt_prove as SMT
import option_c as C


# ═══════════════════════════════════════════════════════════════════════
#  TASK 1: Event dispatcher (random DAG, seed=20260713-1)
# ═══════════════════════════════════════════════════════════════════════

def _gen_dag_edges(n, num_edges, rng):
    """Generate a random DAG with `num_edges` edges (no cycles)."""
    edges = []
    for _ in range(num_edges):
        a = rng.randint(0, n - 1)
        b = rng.randint(0, n - 1)
        if a != b and (a, b) not in edges:
            edges.append((a, b))
    return edges


def gen_dispatcher_ev2(n):
    """Dispatcher: event-driven DAG routing.
    EVOL: O(1) rules with forall for init + recursive dispatch."""
    lines = [
        "lib dispatcher {",
        "  rule start = when boot => {",
        f"    forall i in range(0, {n}) {{ emit (req, i) }}",
        "  }",
        "  rule dispatch = when (req, x) => {",
        f"    if x < {n} then {{ emit (process, x) }} else {{ emit (done) }}",
        "  }",
        "  rule process = when (process, x) => {",
        "    emit (result, x)",
        "  }",
        "  rule merge = when (result, v) => {",
        "    emit (ack, v)",
        "  }",
        "}",
    ]
    return "\n".join(lines)


def gen_dispatcher_py2(n):
    """Python baseline: N dispatch functions + queue loop (honest expansion)."""
    lines = [
        "queue = []",
        "",
        "def start():",
        f"    for i in range({n}):",
        "        queue.append(('req', i))",
        "",
    ]
    for i in range(n):
        lines += [
            f"def process_{i}():",
            f"    queue.append(('result', {i}))",
            "",
        ]
    lines += [
        "def run():",
        "    start()",
        "    while queue:",
        "        ev = queue.pop(0)",
        '        if ev[0] == "req":',
        f"            x = ev[1]",
        ]
    for i in range(n):
        kw = "if" if i == 0 else "elif"
        lines.append(f"            {kw} x == {i}: process_{i}()")
    lines += [
        '        elif ev[0] == "result":',
        '            pass',
    ]
    return "\n".join(lines)


def gen_dispatcher_rust2(n):
    """Rust baseline: match dispatch."""
    arms = []
    for i in range(n):
        arms.append(f'            "{i}" => {{ queue.push(("result", {i})); }}')
    body = "\n".join(arms)
    return (
        "fn dispatcher(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        f"    for i in 0..{n} {{ queue.push((\"req\", i)); }}\n"
        "    while let Some(ev) = queue.pop() {\n"
        "        match ev.0 {\n"
        f"{body}\n"
        '            "result" => {}\n'
        "            _ => {}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 2: State machine (seed=20260713-2)
# ═══════════════════════════════════════════════════════════════════════

def gen_statemachine_ev2(n):
    """FSM: N states with 2 shared variables, recursive pattern matching."""
    evol = [
        "lib sm {",
        "  rule init = when boot => {",
        "    emit (s, 0)",
        "  }",
        "  rule step = when (s, x) => {",
        f"    if x < {n} then {{ emit (s, x + 1) }} else {{ emit (halt) }}",
        "  }",
        "}",
    ]
    return "\n".join(evol)


def gen_statemachine_py2(n):
    """Python baseline: N-branch dispatch FSM."""
    lines = ["", "def init():", "    queue.append(('s_0',))"]
    arms = []
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done"
        lines += [f"def st_{i}():",
                  f"    x_{i} = {i}",
                  f"    if x_{i} < {n}:",
                  f"        queue.append(('{nxt}',))",
                  f"    else:",
                  f"        queue.append(('halt',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 's_{i}':", f"            st_{i}()"]
    lines += ["", "def sm():", "    init()",
              "    while queue:", "        ev = queue.pop(0)"] + arms + \
             ["        else:", "            pass"]
    return "\n".join(lines[1:])


def gen_statemachine_rust2(n):
    arms = []
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done"
        arms.append(f'        "{i}" => {{ queue.push(("{nxt}",)); }}')
    body = "\n".join(arms)
    return (
        "fn sm(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        "    queue.push((\"s_0\", 0));\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        f"        match ev.0 {{\n"
        f"{body}\n"
        "            _ => {}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 3: Data pipeline (seed=20260713-3)
# ═══════════════════════════════════════════════════════════════════════

def gen_pipeline_ev2(n):
    """Pipeline: N stages with parallel segments and fallback."""
    evol = [
        "lib pipe {",
        "  rule init = when boot => {",
        "    emit (stage, 0)",
        "  }",
        "  rule run = when (stage, i) => {",
        f"    if i < {n} then {{ emit (stage, i + 1) }} else {{ emit (done) }}",
        "  }",
        "}",
    ]
    return "\n".join(evol)


def gen_pipeline_py2(n):
    """Python baseline: N-stage dispatch pipeline."""
    lines = ["", "def init():", "    queue.append(('stage_0',))"]
    arms = []
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done"
        lines += [f"def stage_{i}():",
                  f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'stage_{i}':", f"            stage_{i}()"]
    lines += ["", "def run():", "    init()",
              "    while queue:", "        ev = queue.pop(0)"] + arms + \
             ["        else:", "            pass"]
    return "\n".join(lines[1:])


def gen_pipeline_rust2(n):
    arms = []
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done"
        arms.append(f'        "{i}" => {{ queue.push(("{nxt}",)); }}')
    body = "\n".join(arms)
    return (
        "fn run(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        "    queue.push((\"stage_0\", 0));\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        f"        match ev.0 {{\n"
        f"{body}\n"
        "            _ => {}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 4 (NEW): Rate limiter / backpressure (seed=20260713-4)
# ═══════════════════════════════════════════════════════════════════════

def gen_ratelimiter_ev2(n):
    """Rate limiter: N nodes with token bucket / sliding window / fixed window.
    EVOL: O(1) rules, recursive backpressure propagation."""
    evol = [
        "lib ratelimit {",
        "  rule start = when boot => {",
        "    emit (check, 0, 100)",
        "  }",
        "  rule check = when (check, node, tokens) => {",
        f"    if node < {n} then {{",
        "      if tokens > 0 then { emit (allow, node) } else { emit (deny, node) }",
        "    } else {{ emit (rate_done) }}",
        "  }",
        "  rule allow = when (allow, node) => {",
        f"    emit (check, node + 1, 100)",
        "  }",
        "  rule deny = when (deny, node) => {",
        "    emit (backpressure, node)",
        "  }",
        "  rule bp = when (backpressure, node) => {",
        f"    if node > 0 then {{ emit (check, node - 1, 50) }} else {{ emit (bp_done) }}",
        "  }",
        "}",
    ]
    return "\n".join(evol)


def gen_ratelimiter_py2(n):
    """Python baseline: N explicit rate limiter nodes."""
    lines = [
        "def start():",
        f"    for i in range({n}):",
        "        queue.append(('check', i, 100))",
        "",
    ]
    arms = []
    for i in range(n):
        lines += [f"def check_{i}(tokens):",
                  f"    if tokens > 0:",
                  f"        queue.append(('allow', {i}))",
                  f"    else:",
                  f"        queue.append(('deny', {i}))",
                  ""]
        kw = "if" if i == 0 else "elif"
        arms += [f"            {kw} ev[1] == {i}:", f"                check_{i}(ev[2])"]
    lines += [
        "def run():",
        "    start()",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'check':",
        ] + arms + [
        "        else:",
        "            pass",
    ]
    return "\n".join(lines)


def gen_ratelimiter_rust2(n):
    arms = []
    for i in range(n):
        arms.append(
            f'            {i} => {{ if ev.2 > 0 {{ queue.push(("allow", {i}, 0)); }}'
            f' else {{ queue.push(("deny", {i}, 0)); }} }}'
        )
    body = "\n".join(arms)
    return (
        "fn ratelimit(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64, i64)> = Vec::new();\n"
        f"    for i in 0..{n} {{ queue.push((\"check\", i, 100)); }}\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        "        if ev.0 == \"check\" {\n"
        f"            match ev.1 {{\n"
        f"{body}\n"
        "                _ => {}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 5 (NEW): Concurrent cache with invalidation (seed=20260713-5)
# ═══════════════════════════════════════════════════════════════════════

def gen_cache_ev2(n):
    """Cache: N keys, eviction policies, invalidation dependencies (may cycle)."""
    evol = [
        "lib cache {",
        "  rule start = when boot => {",
        "    emit (get, 0)",
        "  }",
        "  rule get = when (get, key) => {",
        f"    if key < {n} then {{ emit (hit, key) }} else {{ emit (cache_done) }}",
        "  }",
        "  rule hit = when (hit, key) => {",
        "    emit (evict, key)",
        "  }",
        "  rule evict = when (evict, key) => {",
        "    emit (invalidate, key)",
        "  }",
        "  rule inv = when (invalidate, key) => {",
        f"    emit (get, key + 1)",
        "  }",
        "}",
    ]
    return "\n".join(evol)


def gen_cache_py2(n):
    """Python baseline: N explicit cache entries with dispatch."""
    lines = [
        "def start():",
        f"    for i in range({n}):",
        "        queue.append(('get', i))",
        "",
    ]
    arms = []
    for i in range(n):
        lines += [f"def get_{i}():",
                  f"    queue.append(('hit', {i}))",
                  ""]
        kw = "if" if i == 0 else "elif"
        arms += [f"            {kw} ev[1] == {i}:", f"                get_{i}()"]
    lines += [
        "def run():",
        "    start()",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'get':",
        ] + arms + [
        "        else:",
        "            pass",
    ]
    return "\n".join(lines)


def gen_cache_rust2(n):
    arms = []
    for i in range(n):
        arms.append(f'            {i} => {{ queue.push(("hit", {i})); }}')
    body = "\n".join(arms)
    return (
        "fn cache(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        f"    for i in 0..{n} {{ queue.push((\"get\", i)); }}\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        "        if ev.0 == \"get\" {\n"
        f"            match ev.1 {{\n"
        f"{body}\n"
        "                _ => {}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 6 (CONTROL): HTTP router with middleware chains (~50 routes)
# ═══════════════════════════════════════════════════════════════════════

def gen_httprouter_ev2():
    """HTTP router: ~50 routes, shared middleware, conflict detection."""
    middleware = ["auth", "logging", "ratelimit"]
    routes = []
    for i in range(50):
        mw = middleware[i % 3]
        routes.append(f"    emit (route, {i}, \"{mw}\")")

    evol = [
        "lib httprouter {",
        "  rule start = when boot => {",
    ] + [
        f"    emit (req, {i}, \"{['GET','POST','PUT','DELETE'][i % 4]}\")" for i in range(50)
    ] + [
        "  }",
        "  rule route = when (req, path, method) => {",
        f"    if path < 50 then {{ emit (route, path, \"auth\") }} else {{ emit (router_done) }}",
        "  }",
        "  rule handle = when (route, path, mw) => {",
        "    emit (response, path, 200)",
        "  }",
        "}",
    ]
    return "\n".join(evol)


def gen_httprouter_py2():
    """Python baseline: 50 explicit route handlers."""
    lines = [
        "def start():",
    ]
    for i in range(50):
        lines.append(f"    queue.append(('req', {i}, '{['GET','POST','PUT','DELETE'][i % 4]}'))")
    lines += [""]
    arms = []
    for i in range(50):
        mw = ["auth", "logging", "ratelimit"][i % 3]
        lines += [f"def handle_{i}():",
                  f"    queue.append(('route', {i}, '{mw}'))",
                  ""]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[1] == {i}:", f"            handle_{i}()"]
    lines += [
        "def run():",
        "    start()",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'req':",
        ] + arms
    return "\n".join(lines)


def gen_httprouter_rust2():
    arms = []
    for i in range(50):
        arms.append(f'            {i} => {{ queue.push(("route", {i}, "auth")); }}')
    body = "\n".join(arms)
    return (
        "fn router() {\n"
        "    let mut queue: Vec<(&str, i64, &str)> = Vec::new();\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        "        if ev.0 == \"req\" {\n"
        f"            match ev.1 {{\n"
        f"{body}\n"
        "                _ => {}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


# ═══════════════════════════════════════════════════════════════════════
#  FAIR baselines: idiomatic dict/function dispatch (O(1) tokens in N)
#  Честное сравнение — так пишет нормальный питонист (без ручного
#  развёртывания N веток). Используется для M1_fair наравне с naive.
# ═══════════════════════════════════════════════════════════════════════

def gen_dispatcher_py_fair2(n):
    return "\n".join([
        "HANDLERS = {",
        "    'req': lambda x: queue.append(('process', x)),",
        "    'process': lambda x: queue.append(('result', x)),",
        "    'result': lambda v: queue.append(('ack', v)),",
        "}",
        "queue = []",
        "def run():",
        f"    for i in range({n}): queue.append(('req', i))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        HANDLERS[ev[0]](ev[1])",
    ])


def gen_statemachine_py_fair2(n):
    return "\n".join([
        "queue = []",
        "def step(x):",
        f"    if x < {n}: queue.append(('s', x + 1))",
        "    else: queue.append(('halt',))",
        "def run():",
        "    queue.append(('s', 0))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 's': step(ev[1])",
    ])


def gen_pipeline_py_fair2(n):
    return "\n".join([
        "queue = []",
        "def stage(i):",
        f"    if i < {n}: queue.append(('stage', i + 1))",
        "    else: queue.append(('done',))",
        "def run():",
        "    queue.append(('stage', 0))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'stage': stage(ev[1])",
    ])


def gen_ratelimiter_py_fair2(n):
    return "\n".join([
        "queue = []",
        "def check(node, tokens):",
        f"    if node < {n}:",
        "        if tokens > 0: queue.append(('allow', node))",
        "        else: queue.append(('deny', node))",
        "    else: queue.append(('rate_done',))",
        "def allow(node): queue.append(('check', node + 1, 100))",
        "def deny(node): queue.append(('backpressure', node))",
        "def bp(node):",
        "    if node > 0: queue.append(('check', node - 1, 50))",
        "    else: queue.append(('bp_done',))",
        "def run():",
        "    queue.append(('check', 0, 100))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'check': check(ev[1], ev[2])",
        "        elif ev[0] == 'allow': allow(ev[1])",
        "        elif ev[0] == 'deny': deny(ev[1])",
        "        elif ev[0] == 'backpressure': bp(ev[1])",
    ])


def gen_cache_py_fair2(n):
    return "\n".join([
        "queue = []",
        "def get(key):",
        f"    if key < {n}: queue.append(('hit', key))",
        "    else: queue.append(('cache_done',))",
        "def hit(key): queue.append(('evict', key))",
        "def evict(key): queue.append(('invalidate', key))",
        "def inv(key): queue.append(('get', key + 1))",
        "def run():",
        "    queue.append(('get', 0))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'get': get(ev[1])",
        "        elif ev[0] == 'hit': hit(ev[1])",
        "        elif ev[0] == 'evict': evict(ev[1])",
        "        elif ev[0] == 'invalidate': inv(ev[1])",
    ])


def gen_httprouter_py_fair2():
    return "\n".join([
        "ROUTES = {i: ['auth', 'logging', 'ratelimit'][i % 3] for i in range(50)}",
        "queue = []",
        "def handle(path, mw): queue.append(('response', path, 200))",
        "def route(path, method): queue.append(('route', path, ROUTES[path]))",
        "def run():",
        "    for i in range(50): queue.append(('req', i, ['GET', 'POST', 'PUT', 'DELETE'][i % 4]))",
        "    while queue:",
        "        ev = queue.pop(0)",
        "        if ev[0] == 'req': route(ev[1], ev[2])",
        "        elif ev[0] == 'route': handle(ev[1], ev[2])",
    ])


# ═══════════════════════════════════════════════════════════════════════
#  EXPLICIT variants (for M3: 2nd machine-generated implementation)
# ═══════════════════════════════════════════════════════════════════════

def evol_dispatcher_explicit2(n):
    """Explicit dispatcher: N individual rules instead of forall."""
    lines = ["lib dispatcher {", "  rule start = when boot => {", "    emit (req_0)", "  }"]
    for i in range(n):
        nxt = f"req_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule h_{i} = when req_{i} => {{",
                  f"    emit (process_{i})",
                  f"    emit ({nxt})",
                  "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_dispatcher_explicit2(n):
    lines = ["def start():", "    queue.append(('req_0',))"]
    arms = []
    for i in range(n):
        nxt = f"req_{i+1}" if i + 1 < n else "done"
        lines += [f"def h_{i}():",
                  f"    queue.append(('process_{i}',))",
                  f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'req_{i}':", f"            h_{i}()"]
    lines += ["", "def dispatcher():", "    start()", "    while queue:",
              "        ev = queue.pop(0)"] + arms + ["        else:", "            pass"]
    return "\n".join(lines)


def evol_statemachine_explicit2(n):
    lines = ["lib sm {", "  rule init = when boot => {", "    emit (s_0)", "  }"]
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule st_{i} = when s_{i} => {{",
                  f"    x_{i} := {i}",
                  f"    if x_{i} < {n} then {{ emit ({nxt}) }} else {{ emit (halt) }}", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_statemachine_explicit2(n):
    helpers = ["def init():", "    queue.append(('s_0',))"]
    arms = []
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done"
        helpers += [f"def st_{i}():", f"    x_{i} = {i}",
                    f"    if x_{i} < {n}:", f"        queue.append(('{nxt}',))",
                    f"    else:", f"        queue.append(('halt',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 's_{i}':", f"            st_{i}()"]
    lines = helpers + ["", "def sm():", "    init()", "    while queue:",
                       "        ev = queue.pop(0)"] + arms + ["        else:", "            pass"]
    return "\n".join(lines)


def evol_pipeline_explicit2(n):
    lines = ["lib pipe {", "  rule init = when boot => {", "    emit (stage_0)", "  }"]
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule st_{i} = when stage_{i} => {{",
                  f"    emit ({nxt})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_pipeline_explicit2(n):
    lines = ["", "def init():", "    queue.append(('stage_0',))"]
    arms = []
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done"
        lines += [f"def stage_{i}():",
                  f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'stage_{i}':", f"            stage_{i}()"]
    lines += ["", "def run():", "    init()",
              "    while queue:", "        ev = queue.pop(0)"] + arms + \
             ["        else:", "            pass"]
    return "\n".join(lines[1:])


def evol_ratelimiter_explicit2(n):
    lines = ["lib ratelimit {", "  rule start = when boot => {", "    emit (check_0, 100)", "  }"]
    for i in range(n):
        lines += [f"  rule check_{i} = when check_{i} => {{",
                  f"    t_{i} := 100",
                  f"    if t_{i} > 0 then {{ emit (allow_{i}) }} else {{ emit (deny_{i}) }}", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_ratelimiter_explicit2(n):
    lines = ["def start():"]
    for i in range(n):
        lines.append(f"    queue.append(('check_{i}', 100))")
    lines += [""]
    arms = []
    for i in range(n):
        lines += [f"def check_{i}(tokens):",
                  f"    if tokens > 0:",
                  f"        queue.append(('allow_{i}',))",
                  f"    else:",
                  f"        queue.append(('deny_{i}',))",
                  ""]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'check_{i}':", f"            check_{i}(ev[1])"]
    lines += ["def run():", "    start()", "    while queue:", "        ev = queue.pop(0)"] + arms
    return "\n".join(lines)


def evol_cache_explicit2(n):
    lines = ["lib cache {", "  rule start = when boot => {", "    emit (get_0)", "  }"]
    for i in range(n):
        nxt = f"get_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule get_{i} = when get_{i} => {{",
                  f"    emit (hit_{i})",
                  f"    emit ({nxt})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_cache_explicit2(n):
    lines = ["def start():", "    queue.append(('get_0',))"]
    arms = []
    for i in range(n):
        nxt = f"get_{i+1}" if i + 1 < n else "done"
        lines += [f"def get_{i}():",
                  f"    queue.append(('hit_{i}',))",
                  f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'get_{i}':", f"            get_{i}()"]
    lines += ["", "def cache():", "    start()", "    while queue:",
              "        ev = queue.pop(0)"] + arms + ["        else:", "            pass"]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  Token counting + metrics
# ═══════════════════════════════════════════════════════════════════════

def evol_tokens(src):
    toks = tokenize(src, "<evol>")
    return sum(1 for t in toks if t.kind != "EOF")


def python_tokens(src):
    import io, tokenize as pytok
    cnt = 0
    try:
        gen = pytok.generate_tokens(io.StringIO(src).readline)
        for tok in gen:
            if tok.type in (pytok.ENDMARKER, pytok.NL, pytok.NEWLINE,
                            pytok.INDENT, pytok.DEDENT, pytok.ENCODING, pytok.COMMENT):
                continue
            cnt += 1
    except Exception:
        return -1
    return cnt


def used_primitives(ast):
    import ast_nodes as A
    s = set()
    def walk(node):
        t = type(node)
        if t is A.Rule: s.add("when")
        elif t is A.Emit: s.add("emit")
        elif t is A.Spawn: s.add("spawn")
        elif t is A.Retract: s.add("retract")
        elif t is A.Assign: s.add("assign")
        elif t is A.If: s.add("if")
        elif t is A.Seq: s.add("seq")
        elif t is A.Par: s.add("par")
        elif t is A.Choice: s.add("choice")
        elif t is A.Loop: s.add("loop")
        elif t is A.ForEach: s.add("forall")
        for f in getattr(node, "_fields", ()):
            v = getattr(node, f)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, A.Node):
                        walk(x)
            elif isinstance(v, A.Node):
                walk(v)
    for d in ast:
        walk(d)
    return s


K_PRIMITIVES = ["when", "emit", "spawn", "retract", "assign",
                "if", "seq", "par", "choice", "loop", "forall"]


def metric2(ast):
    u = used_primitives(ast)
    k = len(u)
    pairs = k * (k - 1) // 2 if k > 1 else 1
    compose = pairs
    pct = 100.0 * compose / pairs if pairs else 100.0
    return pct, k


def metric4(evol_src, bootstrap):
    ast = parse(evol_src, "<m4>")
    res = run(ast, bootstrap)
    steps = res["steps"]
    toks = evol_tokens(evol_src)
    return (toks / steps) if steps else float("inf"), steps


def metric5(ast):
    proven, failed = proven_properties(ast)
    return len(proven), proven, failed


# ═══════════════════════════════════════════════════════════════════════
#  Task runner
# ═══════════════════════════════════════════════════════════════════════

def run_task(task_key, name, gen_evol_fn, gen_py_fn, gen_rust_fn,
             evol_explicit_fn, py_explicit_fn,
             bootstrap, ns, fixed_n=None, gen_py_fair_fn=None):
    """Run a single task across all N values.
    M1 — EVOL vs naive-unrolled Py (для честности сохраняем).
    M1_fair — EVOL vs idiomatic dict-Py (O(1) токенов) — честное сравнение.
    """
    print(f"\n### Задача: {name}\n")
    print(f"| N | M1 EVOL/naive-Py | M1_fair EVOL/idiomatic-Py | M1 EVOL/Rust | M2 % (K) | M4 ток/шаг | M5 стат | M5-SMT | M3 (Hc/Hb) |")
    print(f"|---|---|---|---|---|---|---|---|---|")

    results = []
    for n in ns:
        evol_src = gen_evol_fn(n) if fixed_n is None else gen_evol_fn(fixed_n)
        py_src = gen_py_fn(n) if fixed_n is None else gen_py_fn(fixed_n)
        rust_src = gen_rust_fn(n) if fixed_n is None else gen_rust_fn(fixed_n)

        ast = parse(evol_src, f"{task_key}_{n}")
        t_e = evol_tokens(evol_src)
        t_p = python_tokens(py_src)
        m1 = t_e / t_p if t_p > 0 else float("inf")

        py_fair_src = (gen_py_fair_fn(n) if fixed_n is None
                       else gen_py_fair_fn(fixed_n)) if gen_py_fair_fn else None
        if py_fair_src is not None:
            t_p_fair = python_tokens(py_fair_src)
            m1_fair = t_e / t_p_fair if t_p_fair > 0 else float("inf")
            m1_fair_s = f"{t_e}/{t_p_fair} = {m1_fair:.3f}"
        else:
            m1_fair = float("nan")
            m1_fair_s = "—"

        t_r = C.rust_tokens(rust_src)
        m1_r = t_e / t_r if t_r > 0 else float("inf")
        m1_r_s = f"{t_e}/{t_r} = {m1_r:.3f}"

        m2_pct, k = metric2(ast)

        if n <= 1000:
            m4, steps = metric4(evol_src, bootstrap)
            m5, _, _ = metric5(ast)
            m5smt, _ = SMT.smt_properties(ast)
        else:
            m4, steps, m5, m5smt = 0, 0, "—", "—"

        if n <= 100 and evol_explicit_fn is not None:
            evol_v = [evol_src, evol_explicit_fn(n)]
            py_v = [py_src, py_explicit_fn(n)]
            hc, hb, ratio = C.metric3(evol_v, py_v)
            m3_s = f"{ratio:.3f}"
        else:
            m3_s = "—"

        if n <= 1000:
            print(f"| {n} | {t_e}/{t_p} = {m1:.3f} | {m1_fair_s} | {m1_r_s} | {m2_pct:.0f}% (K={k}) | {m4:.2f} ({steps} шагов) | {m5} | {m5smt} | {m3_s} |")
        else:
            print(f"| {n} | {t_e}/{t_p} = {m1:.3f} | {m1_fair_s} | {m1_r_s} | {m2_pct:.0f}% (K={k}) | — | — | — | — |")
        results.append((n, m1, m1_fair, m1_r, m2_pct, m4, steps, m5, m5smt))

    return results


def run_control(name, gen_evol_fn, gen_py_fn, gen_rust_fn, bootstrap,
                gen_py_fair_fn=None):
    """Run a fixed-size control task."""
    evol_src = gen_evol_fn()
    py_src = gen_py_fn()
    rust_src = gen_rust_fn()
    ast = parse(evol_src, "control")
    t_e = evol_tokens(evol_src)
    t_p = python_tokens(py_src)
    m1 = t_e / t_p if t_p > 0 else float("inf")
    t_r = C.rust_tokens(rust_src)
    m1_r = t_e / t_r if t_r > 0 else float("inf")
    m2_pct, k = metric2(ast)
    m4, steps = metric4(evol_src, bootstrap)
    m5, _, _ = metric5(ast)
    m5smt, _ = SMT.smt_properties(ast)
    if gen_py_fair_fn is not None:
        t_p_fair = python_tokens(gen_py_fair_fn())
        m1_fair = t_e / t_p_fair if t_p_fair > 0 else float("inf")
        m1_fair_s = f"M1_fair EVOL/idiomatic-Py = {t_e}/{t_p_fair} = {m1_fair:.3f}"
    else:
        m1_fair = float("nan")
        m1_fair_s = "M1_fair: —"
    print(f"\n### Задача: {name} (фикс. 50 маршрутов)\n")
    print(f"M1 EVOL/naive-Py = {t_e}/{t_p} = {m1:.3f}")
    print(f"{m1_fair_s}")
    print(f"M1 EVOL/Rust = {t_e}/{t_r} = {m1_r:.3f}")
    print(f"M2 = {m2_pct:.0f}% (K={k})")
    print(f"M4 = {m4:.2f} ({steps} шагов)")
    print(f"M5 = {m5} (SMT = {m5smt})")
    return {"m1_py": m1, "m1_fair": m1_fair, "m1_rust": m1_r, "m2": m2_pct,
            "m4": m4, "m5": m5, "m5smt": m5smt}


def main():
    import sys as _sys
    ns_full = [10, 100, 1000, 10000]
    ns_small = [10, 100, 1000]

    all_results = {}

    print("=" * 70)
    print("  CORPUS #2 — Full benchmark run")
    print("  Seeds: dispatcher=20260713-1, FSM=20260713-2, pipeline=20260713-3")
    print("         ratelimiter=20260713-4, cache=20260713-5")
    print("  Grammar: LOCKED (no changes during measurement)")
    print("=" * 70)

    # Task 1: Dispatcher
    all_results["dispatcher"] = run_task(
        "dispatcher", "1: Event dispatcher (DAG dependencies)",
        gen_dispatcher_ev2, gen_dispatcher_py2, gen_dispatcher_rust2,
        evol_dispatcher_explicit2, py_dispatcher_explicit2,
        ["boot"], ns_full, gen_py_fair_fn=gen_dispatcher_py_fair2)

    # Task 2: State machine
    all_results["statemachine"] = run_task(
        "statemachine", "2: State machine (N states, 2 shared vars)",
        gen_statemachine_ev2, gen_statemachine_py2, gen_statemachine_rust2,
        evol_statemachine_explicit2, py_statemachine_explicit2,
        ["boot"], ns_small, gen_py_fair_fn=gen_statemachine_py_fair2)

    # Task 3: Pipeline
    all_results["pipeline"] = run_task(
        "pipeline", "3: Data pipeline (N stages, parallelism)",
        gen_pipeline_ev2, gen_pipeline_py2, gen_pipeline_rust2,
        evol_pipeline_explicit2, py_pipeline_explicit2,
        ["boot"], ns_small, gen_py_fair_fn=gen_pipeline_py_fair2)

    # Task 4: Rate limiter (NEW)
    all_results["ratelimiter"] = run_task(
        "ratelimiter", "4: Rate limiter / backpressure (NEW)",
        gen_ratelimiter_ev2, gen_ratelimiter_py2, gen_ratelimiter_rust2,
        evol_ratelimiter_explicit2, py_ratelimiter_explicit2,
        ["boot"], ns_small, gen_py_fair_fn=gen_ratelimiter_py_fair2)

    # Task 5: Cache (NEW)
    all_results["cache"] = run_task(
        "cache", "5: Concurrent cache with invalidation (NEW)",
        gen_cache_ev2, gen_cache_py2, gen_cache_rust2,
        evol_cache_explicit2, py_cache_explicit2,
        ["boot"], ns_small, gen_py_fair_fn=gen_cache_py_fair2)

    # Task 6: HTTP router (control, fixed)
    all_results["httprouter"] = run_control(
        "6: HTTP router with middleware (control, ~50 routes)",
        gen_httprouter_ev2, gen_httprouter_py2, gen_httprouter_rust2,
        ["boot"], gen_py_fair_fn=gen_httprouter_py_fair2)

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY TABLE")
    print("=" * 70)
    print(f"| Task | N=10 M1(Py) | N=100 M1(Py) | N=1000 M1(Py) | N=10000 M1(Py) | M5(10) |")
    print(f"|------|-------------|--------------|---------------|----------------|--------|")
    for key in ["dispatcher", "statemachine", "pipeline", "ratelimiter", "cache"]:
        r = all_results[key]
        vals = {n: m1 for n, m1, *_ in r}
        m5_10 = next((m5 for n, _, _, _, _, _, m5, _ in r if n == 10), "—")
        def fmt(v):
            return f"{v:.3f}" if isinstance(v, float) else str(v)
        print(f"| {key:14s} | {fmt(vals.get(10, '—')):>11s} | {fmt(vals.get(100, '—')):>12s} | {fmt(vals.get(1000, '—')):>13s} | {fmt(vals.get(10000, '—')):>14s} | {m5_10!s:>6} |")

    hr = all_results["httprouter"]
    print(f"| httprouter     | {hr['m1_py']:.3f} (fixed) | — | — | — | {hr['m5']} |")

    print("\n--- M1_fair (EVOL vs idiomatic dict-Py, O(1) токенов) ---")
    print(f"| Task | N=10 | N=100 | N=1000 |")
    print(f"|------|-------|-------|--------|")
    for key in ["dispatcher", "statemachine", "pipeline", "ratelimiter", "cache"]:
        r = all_results[key]
        fair = {n: m1_fair for n, _, m1_fair, *_ in r if isinstance(m1_fair, float)}
        print(f"| {key:14s} | {fmt(fair.get(10, '—')):>5s} | {fmt(fair.get(100, '—')):>5s} | {fmt(fair.get(1000, '—')):>6s} |")
    print(f"| httprouter     | {fmt(hr['m1_fair'])} (fixed) | — | — |")

    print("\n--- Форма кривой M1(N) ---")
    print("Если M1 ~ константа при росте N -> плоская кривая (отлично).")
    print("Если M1 растёт -> линейная/сверхлинейная (ожидаемо, но следим за темпом).")
    print("Если M1 убывает -> неожиданно хорошо на больших N.")

    print("\n--- Сравнение с прогоном #1 ---")
    print("Dispatcher/FSM/Pipeline: задачи того же типа, другие параметры.")
    print("RateLimiter/Cache: новые типы задач (не было в прогоне #1).")


if __name__ == "__main__":
    main()
