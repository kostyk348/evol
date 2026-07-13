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
    return (
        "fn sm(n: i64) {\n"
        "    let mut x: i64 = 0;\n"
        f"    while x < {n} {{ x = x + 1; }}\n"
        "}\n"
    )


def rust_pipeline(n):
    return (
        "fn run(n: i64) {\n"
        "    let mut queue: Vec<(String, i64)> = Vec::new();\n"
        f"    for i in 0..{n} {{ queue.push((\"stage\".to_string(), i)); }}\n"
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
    emits = "\n    ".join(f"emit (stage_{i})" for i in range(n))
    return f"lib pipe {{\n  rule run = when boot => {{\n    {emits}\n  }}\n}}"


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
    lines = ["def run():"]
    for i in range(n):
        lines.append(f"    queue.append(('stage_{i}',))")
    return "\n".join(lines)


# ---------------- M3: энтропия AST-продукций ----------------

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


# Явные (explicit) генераторы, сгруппированные по задачам, для M3
EXPLICIT = {
    "dispatcher": (evol_dispatcher_explicit, py_dispatcher_explicit),
    "statemachine": (evol_statemachine_explicit, py_statemachine_explicit),
    "pipeline": (evol_pipeline_explicit, py_pipeline_explicit),
}

RUST = {
    "dispatcher": rust_dispatcher,
    "statemachine": rust_statemachine,
    "pipeline": rust_pipeline,
}
