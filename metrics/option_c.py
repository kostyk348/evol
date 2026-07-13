"""EVOL: опция C — Rust-baseline (второй baseline для M1) + M3 (синтакс. энтропия).

M1 требует >=2 baseline. Добавляем Rust как второй baseline (токены считаются
простым токенизатором; компиляция не нужна — метрика 1 мерит размер, не рантайм).
M3: энтропия Шеннона по распределению AST-продукций для 2+ независимых
реализаций одной семантики, относительно baseline (Python). Ниже baseline — хорошо.
"""

import sys
import os
import math
import ast as pyast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lexer import tokenize
from parser import parse
import ast_nodes as A


# ---------------- Rust baseline (генерация + токенизатор) ----------------

def rust_dispatcher(n):
    return (
        "fn dispatcher(n: i64) {\n"
        "    let mut queue: Vec<(String, i64)> = Vec::new();\n"
        f"    for i in 0..{n} {{ queue.push((\"e\".to_string(), i)); }}\n"
        "    while let Some(ev) = queue.pop() {\n"
        "        if ev.0 == \"e\" { let _y = ev.1; queue.push((\"done\".to_string(), 0)); }\n"
        "    }\n"
        "}\n"
    )


def rust_statemachine(n):
    """N-стояний FSM: dict с N ветвями match."""
    arms = []
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done";
        arms.append(f'        "{i}" => {{ x = {i}; if x < {n} {{ queue.push(("{nxt}",)); }} else {{ queue.push(("halt",)); }} }}')
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


def rust_pipeline(n):
    """N-стадийный pipeline: N функций + match dispatch."""
    arms = []
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done";
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


def rust_tokens(src):
    """Минимальный токенизатор Rust (идентификаторы/числа/строки/пунктуация)."""
    toks = []
    i, n = 0, len(src)
    punct = set("(){}[]<>,.;:+-*/%=!&|@#^?")
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c == '"':
            i += 1
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    i += 2
                else:
                    i += 1
            i += 1
            toks.append("STR")
            continue
        if c.isalpha() or c == "_":
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            toks.append("ID")
            continue
        if c.isdigit():
            while i < n and src[i].isdigit():
                i += 1
            toks.append("NUM")
            continue
        if c in punct:
            toks.append(c)
            i += 1
            continue
        i += 1
    return len(toks)


# ---------------- явные (explicit) генераторы для M3 (2-я вариация) ----------------

def evol_dispatcher_explicit(n):
    lines = ["lib dispatcher {", "  rule start = when boot => {", "    emit (e_0)", "  }"]
    for i in range(n):
        nxt = f"e_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule h_{i} = when e_{i} => {{", f"    y_{i} := {i}", f"    emit ({nxt})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def evol_statemachine_explicit(n):
    lines = ["lib sm {", "  rule init = when boot => {", "    emit (s_0)", "  }"]
    for i in range(n):
        nxt = f"s_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule st_{i} = when s_{i} => {{",
                  f"    x_{i} := {i}",
                  f"    if x_{i} < {n} then {{ emit ({nxt}) }} else {{ emit (halt) }}", "  }"]
    lines.append("}")
    return "\n".join(lines)


def evol_pipeline_explicit(n):
    """Явный pipeline: N правил (каждое emit(next))."""
    lines = ["lib pipe {", "  rule init = when boot => {", "    emit (stage_0)", "  }"]
    for i in range(n):
        nxt = f"stage_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule st_{i} = when stage_{i} => {{",
                  f"    emit ({nxt})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_dispatcher_explicit(n):
    helpers = ["def start():", "    queue.append(('e_0',))"]
    arms = []
    for i in range(n):
        nxt = f"e_{i+1}" if i + 1 < n else "done"
        helpers += [f"def h_{i}():", f"    y_{i} = {i}", f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'e_{i}':", f"            h_{i}()"]
    lines = helpers + ["", "def dispatcher():", "    start()", "    while queue:",
                       "        ev = queue.pop(0)"] + arms + ["        else:", "            pass"]
    return "\n".join(lines)


def py_statemachine_explicit(n):
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


def py_pipeline_explicit(n):
    """Явный pipeline: N функций-обработчиков + dispatch loop."""
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
    return "\n".join(lines[1:]    )


def rust_fanout(n):
    """Fan-out: N ветвей через match."""
    arms = []
    for i in range(n):
        nxt = f"work_{i+1}" if i + 1 < n else "done"
        arms.append(f'        "{i}" => {{ workers.push("w_{i}"); queue.push(("{nxt}",)); }}')
    body = "\n".join(arms)
    return (
        "fn fanout(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        "    let mut workers: Vec<&str> = Vec::new();\n"
        "    queue.push((\"work_0\", 0));\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        f"        match ev.0 {{\n"
        f"{body}\n"
        "            _ => {}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def rust_priority_router(n):
    """Priority router: N маршрутов через match."""
    arms = []
    for i in range(n):
        arms.append(f'        "{i}" => {{ queue.push(("routed_{i}",)); }}')
    body = "\n".join(arms)
    return (
        "fn run(n: i64) {\n"
        "    let mut queue: Vec<(&str, i64)> = Vec::new();\n"
        "    queue.push((\"msg_0\", 0));\n"
        "    while !queue.is_empty() {\n"
        "        let ev = queue.remove(0);\n"
        f"        match ev.0 {{\n"
        f"{body}\n"
        "            _ => {}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

def evol_ast_hist(src):
    ast = parse(src, "<evol>")
    hist = {}
    def walk(node):
        hist[type(node).__name__] = hist.get(type(node).__name__, 0) + 1
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
    return hist


def py_ast_hist(src):
    tree = pyast.parse(src)
    hist = {}
    for node in pyast.walk(tree):
        name = type(node).__name__
        hist[name] = hist.get(name, 0) + 1
    return hist


def shannon(hist):
    total = sum(hist.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in hist.values():
        p = c / total
        if p > 0:
            h -= p * math.log2(p)
    return h


def metric3(evol_srcs, py_srcs):
    """Возвращает (H_cand, H_base, ratio). ratio<1 — кандидат менее энтропиен (хорошо)."""
    hc = sum(shannon(evol_ast_hist(s)) for s in evol_srcs) / len(evol_srcs)
    hb = sum(shannon(py_ast_hist(s)) for s in py_srcs) / len(py_srcs)
    ratio = hc / hb if hb > 0 else float("inf")
    return hc, hb, ratio


def evol_fanout_explicit(n):
    """Явный fan-out: N правил spawn."""
    lines = ["lib fanout {", "  rule init = when boot => {", "    emit (work_0)", "  }"]
    for i in range(n):
        nxt = f"work_{i+1}" if i + 1 < n else "done"
        lines += [f"  rule fan_{i} = when work_{i} => {{",
                  f"    spawn Worker", f"    emit ({nxt})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_fanout_explicit(n):
    """Явный fan-out: N функций + dispatch loop."""
    lines = ["", "def init():", "    queue.append(('work_0',))"]
    arms = []
    for i in range(n):
        nxt = f"work_{i+1}" if i + 1 < n else "done"
        lines += [f"def work_{i}():",
                  f"    workers.append('worker_{i}')",
                  f"    queue.append(('{nxt}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'work_{i}':", f"            work_{i}()"]
    lines += ["", "def run():", "    workers = []",
              "    init()",
              "    while queue:", "        ev = queue.pop(0)"] + arms + \
             ["        else:", "            pass"]
    return "\n".join(lines[1:])


def evol_priority_router_explicit(n):
    """Явный priority router: N правил."""
    lines = ["lib router {", "  rule init = when boot => {", "    emit (msg_0)", "  }"]
    for i in range(n):
        lines += [f"  rule route_{i} = when msg_{i} => {{",
                  f"    emit (routed_{i})", "  }"]
    lines.append("}")
    return "\n".join(lines)


def py_priority_router_explicit(n):
    """Явный priority router: N функций + dispatch loop."""
    lines = ["", "def init():", "    queue.append(('msg_0',))"]
    arms = []
    for i in range(n):
        lines += [f"def route_{i}():",
                  f"    queue.append(('routed_{i}',))"]
        kw = "if" if i == 0 else "elif"
        arms += [f"        {kw} ev[0] == 'msg_{i}':", f"            route_{i}()"]
    lines += ["", "def run():", "    init()",
              "    while queue:", "        ev = queue.pop(0)"] + arms + \
             ["        else:", "            pass"]
    return "\n".join(lines[1:])


# Явные (explicit) генераторы, сгруппированные по задачам, для M3
EXPLICIT = {
    "dispatcher": (evol_dispatcher_explicit, py_dispatcher_explicit),
    "statemachine": (evol_statemachine_explicit, py_statemachine_explicit),
    "pipeline": (evol_pipeline_explicit, py_pipeline_explicit),
    "fanout": (evol_fanout_explicit, py_fanout_explicit),
    "priority_router": (evol_priority_router_explicit, py_priority_router_explicit),
}

RUST = {
    "dispatcher": rust_dispatcher,
    "statemachine": rust_statemachine,
    "pipeline": rust_pipeline,
    "fanout": rust_fanout,
    "priority_router": rust_priority_router,
}
