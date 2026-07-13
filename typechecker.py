"""EVOL тайпчекер + лёгкий доказательщик свойств (Этап 4).

Цель по roadmap: тайпчекер должен РЕАЛЬНО отклонять некорректные программы
(не просто пропускать всё). Плюс — для метрики 5 (глубина вывода) —
перечислять свойства, автоматически доказуемые из одного определения
программы (без SMT-солвера; статический анализ структуры).

Типы: TInt, TStr, TSym, TBool, TUnit, TList, TTuple, TFun, TTop.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ast_nodes import (
    Int, Str, Name, List, Tuple, Fun, BinOp, UnaryOp, Call, GetAttr, Index,
    Block, Seq, Par, Choice, Loop, Assign, Emit, Spawn, Retract, If, ForEach,
    Rule, Lib,
)


class Type:
    def __eq__(self, other):
        return type(self) is type(other) and self._key() == other._key()

    def __hash__(self):
        return hash((type(self), self._key()))

    def _key(self):
        return ()


class TInt(Type):
    def __repr__(self):
        return "Int"


class TStr(Type):
    def __repr__(self):
        return "Str"


class TSym(Type):
    def __repr__(self):
        return "Sym"


class TBool(Type):
    def __repr__(self):
        return "Bool"


class TUnit(Type):
    def __repr__(self):
        return "Unit"


class TTop(Type):
    def __repr__(self):
        return "Top"


class TList(Type):
    def __init__(self, elem):
        self.elem = elem

    def _key(self):
        return (id(self.elem),)

    def __repr__(self):
        return f"List[{self.elem}]"


class TTuple(Type):
    def __init__(self, items):
        self.items = items

    def _key(self):
        return tuple(id(i) for i in self.items)

    def __repr__(self):
        return f"Tuple[{self.items}]"


class TFun(Type):
    def __init__(self, args, ret):
        self.args = args
        self.ret = ret

    def _key(self):
        return (tuple(id(a) for a in self.args), id(self.ret))

    def __repr__(self):
        return f"Fun[{self.args} -> {self.ret}]"


TINT, TSTR, TSYM, TBOOL, TUNIT, TTOP = TInt(), TStr(), TSym(), TBool(), TUnit(), TTop()


def builtin_type(name):
    """Тип встроенной функции (соответствует interpreter.BUILTINS)."""
    if name == "range":
        return TFun((TINT, TINT), TList(TINT))
    if name == "len":
        return TFun((TList(TTOP),), TINT)
    return None


class TypeError(Exception):
    pass


def truthy_type(t):
    return isinstance(t, (TInt, TBool, TSym, TList, TTuple))


class TypeChecker:
    def __init__(self, rule_names):
        self.rule_names = set(rule_names)
        self.errors = []
        self.fun_env = {}  # name -> TFun (для вызовов по имени, если будут)

    def err(self, node, msg):
        self.errors.append(f"{node.line}:{node.col} {msg}")

    def check_program(self, decls):
        for d in decls:
            if isinstance(d, Rule):
                self.check_rule(d)
            elif isinstance(d, Lib):
                self.check_program(d.decls)
        return self.errors

    def check_rule(self, rule):
        env = {}
        self.check_eff(rule.body, env)

    def infer(self, expr, env):
        t = type(expr)
        if t is Int:
            return TINT
        if t is Str:
            return TSTR
        if t is Name:
            if expr.value in env:
                return env[expr.value]
            return TSYM  # несвязанное имя в паттерне/символ
        if t is List:
            elem = TTOP
            for i in expr.items:
                ti = self.infer(i, env)
                elem = ti
            return TList(elem)
        if t is Tuple:
            return TTuple([self.infer(i, env) for i in expr.items])
        if t is Fun:
            local = dict(env)
            params = []
            for p in expr.params:
                local[p] = TTOP
                params.append(TTOP)
            ret = self.infer(expr.body, local)
            return TFun(tuple(params), ret)
        if t is UnaryOp:
            v = self.infer(expr.operand, env)
            if expr.op == "-":
                if not isinstance(v, TInt):
                    self.err(expr, f"'-' применим к Int, получен {v}")
                return TINT
            if expr.op == "not":
                if not truthy_type(v):
                    self.err(expr, f"'not' применим к логическому, получен {v}")
                return TBOOL
        if t is BinOp:
            return self.infer_binop(expr, env)
        if t is GetAttr:
            obj = self.infer(expr.obj, env)
            if expr.attr == "kind":
                if isinstance(obj, (TSym, TTuple)):
                    return TSYM
                self.err(expr, f".kind от {obj}")
                return TTOP
            self.err(expr, f"неизвестный атрибут .{expr.attr}")
            return TTOP
        if t is Index:
            obj = self.infer(expr.obj, env)
            self.infer(expr.key, env)
            if isinstance(obj, TList):
                return obj.elem
            if isinstance(obj, TTuple):
                return TTOP
            self.err(expr, f"индексация от {obj}")
            return TTOP
        if t is Call:
            if isinstance(expr.func, Name) and builtin_type(expr.func.value) is not None:
                sig = builtin_type(expr.func.value)
                args = [self.infer(a, env) for a in expr.args]
                if len(args) != len(sig.args):
                    self.err(expr, f"арность вызова {expr.func.value}: ожидалось {len(sig.args)}, дано {len(args)}")
                return sig.ret
            func = self.infer(expr.func, env)
            args = [self.infer(a, env) for a in expr.args]
            if isinstance(func, TFun):
                if len(args) != len(func.args):
                    self.err(expr, f"арность вызова: ожидалось {len(func.args)}, дано {len(args)}")
                return func.ret
            self.err(expr, f"вызов не-функции: {func}")
            return TTOP
        self.err(expr, f"неизвестный expr {t}")
        return TTOP

    def infer_binop(self, node, env):
        l = self.infer(node.left, env)
        r = self.infer(node.right, env)
        op = node.op
        if op in ("+", "-", "*", "/"):
            if not (isinstance(l, TInt) and isinstance(r, TInt)):
                self.err(node, f"арифметика требует Int, получено {l} {op} {r}")
            return TINT
        if op in ("==", "!=", "<", ">", "<=", ">="):
            if type(l) != type(r) and not (isinstance(l, (TInt, TStr)) and isinstance(r, (TInt, TStr))):
                self.err(node, f"сравнение несопоставимых: {l} {op} {r}")
            return TBOOL
        if op in ("and", "or"):
            if not (truthy_type(l) and truthy_type(r)):
                self.err(node, f"логика требует логический тип, получено {l} {op} {r}")
            return TBOOL
        self.err(node, f"неизвестный оператор {op}")
        return TTOP

    def check_eff(self, node, env):
        t = type(node)
        if t is Block:
            for s in node.stmts:
                self.check_eff(s, env)
        elif t is Assign:
            v = self.infer(node.value, env)
            env[node.name] = v
        elif t is Emit:
            self.infer(node.value, env)
        elif t is Spawn:
            if node.name not in self.rule_names:
                self.err(node, f"spawn несуществующего правила '{node.name}'")
        elif t is Retract:
            if node.name not in self.rule_names:
                self.err(node, f"retract несуществующего правила '{node.name}'")
        elif t is If:
            c = self.infer(node.cond, env)
            if not truthy_type(c):
                self.err(node, f"условие if не логического типа: {c}")
            self.check_eff(node.then_branch, env)
            self.check_eff(node.else_branch, env)
        elif t is Seq:
            self.check_eff(node.a, env)
            self.check_eff(node.b, env)
        elif t is Par:
            self.check_eff(node.a, env)
            self.check_eff(node.b, env)
        elif t is Choice:
            self.check_eff(node.a, env)
            self.check_eff(node.b, env)
        elif t is Loop:
            g = self.infer(node.guard, env)
            if not truthy_type(g):
                self.err(node, f"guard цикла не логического типа: {g}")
            self.check_eff(node.body, env)
        elif t is ForEach:
            coll = self.infer(node.coll, env)
            if not isinstance(coll, TList):
                self.err(node, f"forall: коллекция не список: {coll}")
            local = dict(env)
            local[node.var] = coll.elem if isinstance(coll, TList) else TTOP
            self.check_eff(node.body, local)
        else:
            self.err(node, f"неизвестный eff {t}")


# ---------- Доказательщик свойств (метрика 5) ----------

def collect_facts(decls, acc=None):
    if acc is None:
        acc = {"rules": set(), "when_tags": set(), "emit_tags": set(),
               "spawns": set(), "retracts": set(), "edges": {}, "tag_count": {},
               "rule_tag": {}}
    for d in decls:
        if isinstance(d, Rule):
            acc["rules"].add(d.name)
            tag = pattern_tag(d.pat)
            if tag:
                acc["when_tags"].add(tag)
                acc["tag_count"][tag] = acc["tag_count"].get(tag, 0) + 1
                acc["rule_tag"][d.name] = tag
            etags = emitted_tags(d.body)
            for tg in etags:
                acc["emit_tags"].add(tg)
            acc.setdefault("edges", {})[d.name] = etags
        elif isinstance(d, Lib):
            collect_facts(d.decls, acc)
    return acc


def pattern_tag(pat):
    if isinstance(pat, Name):
        return pat.value
    if isinstance(pat, Tuple) and pat.items and isinstance(pat.items[0], Name):
        return pat.items[0].value
    return None


def emitted_tags(node):
    tags = []
    t = type(node)
    if t is Block:
        for s in node.stmts:
            tags += emitted_tags(s)
    elif t is Emit:
        tg = pattern_tag(node.value)
        if tg:
            tags.append(tg)
    elif t is Seq:
        tags += emitted_tags(node.a) + emitted_tags(node.b)
    elif t is Par:
        tags += emitted_tags(node.a) + emitted_tags(node.b)
    elif t is Choice:
        tags += emitted_tags(node.a) + emitted_tags(node.b)
    elif t is Loop:
        tags += emitted_tags(node.body)
    elif t is If:
        tags += emitted_tags(node.then_branch) + emitted_tags(node.else_branch)
    return tags


def proven_properties(decls):
    """Возвращает (список доказанных свойств, список проваленных)."""
    tc = TypeChecker([])
    # сначала собираем имена правил
    facts0 = collect_facts(decls)
    tc = TypeChecker(facts0["rules"])
    tc.check_program(decls)
    type_ok = len(tc.errors) == 0

    facts = collect_facts(decls)
    proven, failed = [], []

    # P1: все spawn указывают на объявленные правила
    if all(s in facts["rules"] for s in facts["spawns"]):
        proven.append("все spawn -> объявленные правила")
    else:
        failed.append("spawn несуществующего правила")

    # P2: все retract указывают на объявленные правила
    if all(r in facts["rules"] for r in facts["retracts"]):
        proven.append("все retract -> объявленные правила")
    else:
        failed.append("retract несуществующего правила")

    # P3: типизация прошла без ошибок
    if type_ok:
        proven.append("программа типобезопасна (без ошибок тайпчекера)")
    else:
        failed.append("ошибки типизации")

    # P4: достижимость — из правил, чей when-тег == 'boot', по edges всё достижимо
    starts = [name for name, tag in facts["rule_tag"].items() if tag == "boot"]
    reachable = set()
    if starts:
        # обратный индекс тег -> правила
        tag_to_rules = {}
        for name, tag in facts["rule_tag"].items():
            tag_to_rules.setdefault(tag, []).append(name)
        stack = list(starts)
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            for tg in facts["edges"].get(cur, []):
                for rn in tag_to_rules.get(tg, []):
                    if rn not in reachable:
                        stack.append(rn)
        dead = facts["rules"] - reachable
        if not dead:
            proven.append("все правила достижимы из boot (нет dead-кода)")
        else:
            failed.append(f"недостижимые правила: {sorted(dead)}")
    else:
        failed.append("нет правила с when-тегом 'boot' (недостижимость не проверяема)")

    # P5: покрытие emit-тегов обработчиками (нет гарантированно дропаемых)
    uncovered = facts["emit_tags"] - facts["when_tags"]
    if not uncovered:
        proven.append("все emit-теги покрыты обработчиком when (нет гарантированного drop)")
    else:
        failed.append(f"непокрытые emit-теги: {sorted(uncovered)}")

    # P6: детерминизм тегов — нет двух правил с одним when-тегом
    # (иначе δ выбирает по prio; при равенстве — недетерминизм)
    clashes = {t: c for t, c in facts["tag_count"].items() if c > 1}
    if not clashes:
        proven.append("нет конфликта тегов (детерминизм выбора правила)")
    else:
        failed.append(f"конфликт тегов: {clashes}")

    return proven, failed


def typecheck(ast):
    facts = collect_facts(ast)
    tc = TypeChecker(facts["rules"])
    errors = tc.check_program(ast)
    return errors


if __name__ == "__main__":
    pass
