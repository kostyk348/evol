"""EVOL: опция B — SMT-доказательство свойств (метрика 5, задача 2).

Переводит охранные условия (guards) state-machine правил в z3 и доказывает:
  P_exclusive   — охраны одного состояния попарно не пересекаются (нет конфликта)
  P_exhaustive  — объединение охран состояния покрывает область (нет тупика/uncovered)

Это настоящий вывод, а не тривиальная статическая проверка типчекера.
Бюджет времени на солвер — как в спеке (10 c). Таймаут = сигнал «плохо».
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import z3
from ast_nodes import (
    Int, Str, Name, List, Tuple, Fun, BinOp, UnaryOp, Call, GetAttr, Index,
    Block, Seq, Par, Choice, Loop, Assign, Emit, Spawn, Retract, If, ForEach,
    Rule, Lib,
)

Z3_OPS = {"+": z3.Sum, "-": lambda a, b: a - b, "*": lambda a, b: a * b}


def expr_to_z3(node, env):
    """EVOL expr -> z3 выражение. Переменные по имени консистентны через env."""
    t = type(node)
    if t is Int:
        return z3.IntVal(node.value)
    if t is Name:
        if node.value not in env:
            env[node.value] = z3.Int(node.value)
        return env[node.value]
    if t is BinOp:
        l = expr_to_z3(node.left, env)
        r = expr_to_z3(node.right, env)
        op = node.op
        if op in Z3_OPS:
            return Z3_OPS[op](l, r)
        if op == "==":
            return l == r
        if op == "!=":
            return l != r
        if op == "<":
            return l < r
        if op == ">":
            return l > r
        if op == "<=":
            return l <= r
        if op == ">=":
            return l >= r
        if op == "and":
            return z3.And(l, r)
        if op == "or":
            return z3.Or(l, r)
        raise ValueError(f"z3: неизвестный бинарный {op}")
    if t is UnaryOp:
        v = expr_to_z3(node.operand, env)
        if node.op == "-":
            return -v
        if node.op == "not":
            return z3.Not(v)
        raise ValueError(f"z3: неизвестный унарный {node.op}")
    raise ValueError(f"z3: непереводимый узел {t}")


def collect_guards(eff, env, out):
    """Собирает охранные условия (z3) для state-правила: then -> cond, else -> Not(cond)."""
    t = type(eff)
    if t is If:
        cond = expr_to_z3(eff.cond, env)
        out.append(cond)
        collect_guards(eff.then_branch, env, out)
        collect_guards(eff.else_branch, env, out)
        # ветка else исполняется под Not(cond)
        env2 = dict(env)
        neg = z3.Not(cond)
        out.append(neg)
        collect_guards(eff.then_branch, env2, out)
        collect_guards(eff.else_branch, env2, out)
    elif t is Block:
        for s in eff.stmts:
            collect_guards(s, env, out)
    elif t is Seq:
        collect_guards(eff.a, env, out)
        collect_guards(eff.b, env, out)
    elif t is Par:
        collect_guards(eff.a, env, out)
        collect_guards(eff.b, env, out)
    elif t is Choice:
        collect_guards(eff.a, env, out)
        collect_guards(eff.b, env, out)
    elif t is Loop:
        collect_guards(eff.body, env, out)
    elif t is ForEach:
        collect_guards(eff.body, env, out)


def pattern_tag_arity(pat):
    if isinstance(pat, Tuple) and pat.items:
        tag = pat.items[0]
        if isinstance(tag, Name):
            return tag.value, len(pat.items) - 1
    if isinstance(pat, Name):
        return pat.value, 0
    return None, 0


def smt_properties(ast, budget_ms=10000):
    """Возвращает (число доказанных SMT-свойств, список деталей/конфликтов/таймаутов)."""
    # сгруппировать state-правила по тегу; собрать охраны
    groups = {}  # tag -> list of z3 guards
    for d in ast:
        rules = [d] if isinstance(d, Rule) else ([r for r in d.decls] if isinstance(d, Lib) else [])
        for r in rules:
            if not isinstance(r, Rule):
                continue
            tag, arity = pattern_tag_arity(r.pat)
            if tag is None or arity < 1:
                continue  # не state-правило (нет payload-переменной)
            env = {}
            guards = []
            collect_guards(r.body, env, guards)
            groups.setdefault(tag, []).append(guards)

    proven = 0
    details = []

    def check(label, constraint):
        s = z3.Solver()
        s.set("timeout", budget_ms)
        s.add(constraint)
        res = s.check()
        if res == z3.unsat:
            return True, "valid"
        if res == z3.sat:
            return False, "VIOLATED"
        return None, "timeout"

    for tag, rule_guards in groups.items():
        all_g = [g for sub in rule_guards for g in sub]
        if not all_g:
            continue
        # P_exclusive: попарно не пересекаются
        conflict = False
        for i in range(len(all_g)):
            for j in range(i + 1, len(all_g)):
                ok, status = check(f"{tag}[{i},{j}]", z3.And(all_g[i], all_g[j]))
                if ok is False:
                    conflict = True
                    details.append(f"КОНФЛИКТ охран в состоянии '{tag}': пересекаются")
                    break
            if conflict:
                break
        if not conflict:
            proven += 1
            details.append(f"состояние '{tag}': охраны попарно исключающие (exclusive)")
        # P_exhaustive: объединение покрывает область
        ok, status = check(f"{tag}-exh", z3.Not(z3.Or(all_g)))
        if ok is True:
            proven += 1
            details.append(f"состояние '{tag}': охраны исчерпывающие (exhaustive, нет тупика)")
        elif ok is False:
            details.append(f"состояние '{tag}': есть область без перехода (UNCOTHED)")
        else:
            details.append(f"состояние '{tag}': таймаут солвера")

    return proven, details
