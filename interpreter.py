"""EVOL интерпретатор (Этап 3). AST-walking, прямая реализация δ(S) -> S'.

Абстрактная машина S = (Σ, Μ, Q):
  Σ  — store:       name -> value
  Μ  — message queue: упорядоченный список значений (сообщений)
  Q  — установленные правила: {id, name, prio, pat, eff}

Шаг δ:
  1. если Μ пуст -> останов.
  2. m = head(Μ); остальное -> Μ'.
  3. среди Q взять правила, чей pat совпадает с m (match); выбрать max prio.
  4. нет совпадений -> m отброшено.
  5. иначе вычислить eff в Σ + bindings; применить мутации Σ, emit->Μ',
     spawn->Q, retract->Q.
"""

import sys
import os
import random as _random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ast_nodes import (
    Int, Float, Str, Name, List, Tuple, Fun, BinOp, UnaryOp, Call, GetAttr, Index,
    Block, Seq, Par, Choice, Loop, Assign, Emit, Spawn, Retract, If, ForEach,
    TryCatch, Raise, Rule, Lib, Import, PyImport, EnumDecl, EnumVariant,
    Match, MatchCase, TyCon, TyList,
)
from parser import parse


# Флаг runtime-проверки аннотаций (Этап 7). По умолчанию выключен:
# язык остаётся динамическим, аннотации влияют на статический тайпчекер.
_ENFORCE_TYPES = False


def set_enforce_types(on):
    global _ENFORCE_TYPES
    _ENFORCE_TYPES = bool(on)


def _ann_match(ann, value):
    """Проверка значения против аннотации типа (AST TypeExpr)."""
    if ann is None:
        return True
    if isinstance(ann, TyCon):
        n = ann.name
        if n == "Int":
            return isinstance(value, int) and not isinstance(value, bool)
        if n == "Float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if n == "Str":
            return isinstance(value, str)
        if n == "Bool":
            return isinstance(value, bool)
        if n == "Sym":
            return isinstance(value, Symbol)
        if n == "List":
            return isinstance(value, list)
        return True  # Top / неизвестный -> пропускаем
    if isinstance(ann, TyList):
        if not isinstance(value, list):
            return False
        return all(_ann_match(ann.elem, v) for v in value)
    return True


class Symbol:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Symbol) and other.name == self.name

    def __hash__(self):
        return hash(("Symbol", self.name))

    def __repr__(self):
        return f"^{self.name}"


def is_truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v != 0
    if isinstance(v, str):
        return len(v) > 0
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, tuple):
        return len(v) > 0
    if isinstance(v, Symbol):
        return True
    return v is not None


def make_value(v):
    """Поднимает Python-значения к EVOL-значениям (для bootstrap-сообщений)."""
    if isinstance(v, str) and not v.startswith("^"):
        return Symbol(v)
    return v


# Встроенные функции (примитивы, не требующие определения в программе)
BUILTINS = {"range", "len", "abs", "min", "max", "str", "int", "float"}


def call_builtin(name, args):
    if name == "range":
        if len(args) != 2:
            raise InterpreterError("range ожидает 2 аргумента")
        return list(range(args[0], args[1]))
    if name == "len":
        if len(args) != 1:
            raise InterpreterError("len ожидает 1 аргумент")
        return len(args[0])
    if name == "abs":
        if len(args) != 1:
            raise InterpreterError("abs ожидает 1 аргумент")
        return abs(args[0])
    if name == "min":
        if len(args) < 2:
            raise InterpreterError("min ожидает 2+ аргумента")
        return min(args)
    if name == "max":
        if len(args) < 2:
            raise InterpreterError("max ожидает 2+ аргумента")
        return max(args)
    if name == "str":
        if len(args) != 1:
            raise InterpreterError("str ожидает 1 аргумент")
        return str(args[0])
    if name == "int":
        if len(args) != 1:
            raise InterpreterError("int ожидает 1 аргумент")
        return int(args[0])
    if name == "float":
        if len(args) != 1:
            raise InterpreterError("float ожидает 1 аргумент")
        return float(args[0])
    raise InterpreterError(f"неизвестный builtin {name}")


# Состояние симуляции (общее для всех модулей)
_sim_state = {"step": 0}

# FFI-реестр: имя функции -> Python-callable (заполняется import py ...)
_py_ffi = {}

# Корень проекта и каталог samples для разрешения модулей
_ROOT = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(_ROOT, "samples")


# Модули стандартной библиотеки
def _call_module(mod, func, args):
    if mod == "console":
        return _call_console(func, args)
    if mod == "random":
        return _call_random(func, args)
    if mod == "file":
        return _call_file(func, args)
    if mod == "sim":
        return _call_sim(func, args)
    if mod == "math":
        return _call_math(func, args)
    if mod == "string":
        return _call_string(func, args)
    if mod == "os":
        return _call_os(func, args)
        raise InterpreterError(f"неизвестный модуль '{mod}'")


# --- FFI к Python (sandboxed) ---
_FFI_BANNED = {"eval", "exec", "open", "__import__", "compile", "input", "exit", "quit"}


def _call_ffi(func, args):
    if func not in _py_ffi:
        raise InterpreterError(
            f"FFI: функция 'py.{func}' не зарегистрирована — добавьте "
            f"'import py \"<module>\": {func};'"
        )
    try:
        return _py_ffi[func](*args)
    except Exception as e:
        raise EvalError(f"FFI py.{func}: {e}")


def _call_console(func, args):
    if func == "print":
        if len(args) < 1:
            raise InterpreterError("console.print ожидает 1+ аргументов")
        parts = []
        for a in args:
            if isinstance(a, Symbol):
                parts.append(a.name)
            else:
                parts.append(str(a))
        print(" ".join(parts))
        return args[0] if len(args) == 1 else tuple(args)
    if func == "println":
        if len(args) < 1:
            raise InterpreterError("console.println ожидает 1+ аргументов")
        parts = []
        for a in args:
            if isinstance(a, Symbol):
                parts.append(a.name)
            else:
                parts.append(str(a))
        print(" ".join(parts))
        return args[0] if len(args) == 1 else tuple(args)
    raise InterpreterError(f"console: неизвестная функция '{func}'")


def _call_random(func, args):
    if func == "int":
        if len(args) != 2:
            raise InterpreterError("random.int(a, b) ожидает 2 аргумента")
        return _random.randint(args[0], args[1])
    if func == "pick":
        if len(args) != 1:
            raise InterpreterError("random.pick(list) ожидает 1 аргумент")
        coll = args[0]
        if not isinstance(coll, list) or len(coll) == 0:
            raise InterpreterError("random.pick: пустая коллекция")
        return _random.choice(coll)
    if func == "shuffle":
        if len(args) != 1:
            raise InterpreterError("random.shuffle(list) ожидает 1 аргумент")
        coll = list(args[0])
        _random.shuffle(coll)
        return coll
    raise InterpreterError(f"random: неизвестная функция '{func}'")


def _call_file(func, args):
    if func == "read":
        if len(args) != 1:
            raise InterpreterError("file.read(path) ожидает 1 аргумент")
        path = args[0]
        if not isinstance(path, str):
            raise InterpreterError(f"file.read: путь должен быть строкой, получено {path!r}")
        with open(path, encoding="utf-8") as f:
            return f.read()
    if func == "write":
        if len(args) != 2:
            raise InterpreterError("file.write(path, data) ожидает 2 аргумента")
        path, data = args[0], args[1]
        if not isinstance(path, str):
            raise InterpreterError(f"file.write: путь должен быть строкой, получено {path!r}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(data))
        return data
    if func == "exists":
        if len(args) != 1:
            raise InterpreterError("file.exists(path) ожидает 1 аргумент")
        return 1 if os.path.exists(args[0]) else 0
    raise InterpreterError(f"file: неизвестная функция '{func}'")


def _call_sim(func, args):
    if func == "step":
        return _sim_state["step"]
    if func == "set_seed":
        if len(args) != 1:
            raise InterpreterError("sim.set_seed(n) ожидает 1 аргумент")
        _random.seed(args[0])
        return args[0]
    raise InterpreterError(f"sim: неизвестная функция '{func}'")


def _call_math(func, args):
    import math as _math
    if func == "sqrt":
        if len(args) != 1: raise InterpreterError("math.sqrt(x)")
        return int(_math.sqrt(args[0]))
    if func == "pow":
        if len(args) != 2: raise InterpreterError("math.pow(x, y)")
        return int(_math.pow(args[0], args[1]))
    if func == "sin":
        if len(args) != 1: raise InterpreterError("math.sin(x)")
        return _math.sin(args[0])
    if func == "cos":
        if len(args) != 1: raise InterpreterError("math.cos(x)")
        return _math.cos(args[0])
    if func == "pi":
        return _math.pi
    if func == "floor":
        if len(args) != 1: raise InterpreterError("math.floor(x)")
        return int(_math.floor(args[0]))
    if func == "ceil":
        if len(args) != 1: raise InterpreterError("math.ceil(x)")
        return int(_math.ceil(args[0]))
    if func == "log":
        if len(args) != 1: raise InterpreterError("math.log(x)")
        return _math.log(args[0])
    raise InterpreterError(f"math: неизвестная функция '{func}'")


def _call_string(func, args):
    if func == "split":
        if len(args) < 2: raise InterpreterError("string.split(s, delim)")
        return args[0].split(args[1])
    if func == "join":
        if len(args) < 2: raise InterpreterError("string.join(list, delim)")
        return args[1].join(str(x) for x in args[0])
    if func == "upper":
        if len(args) != 1: raise InterpreterError("string.upper(s)")
        return str(args[0]).upper()
    if func == "lower":
        if len(args) != 1: raise InterpreterError("string.lower(s)")
        return str(args[0]).lower()
    if func == "contains":
        if len(args) != 2: raise InterpreterError("string.contains(s, sub)")
        return 1 if str(args[1]) in str(args[0]) else 0
    if func == "replace":
        if len(args) != 3: raise InterpreterError("string.replace(s, old, new)")
        return str(args[0]).replace(str(args[1]), str(args[2]))
    if func == "len":
        if len(args) != 1: raise InterpreterError("string.len(s)")
        return len(str(args[0]))
    if func == "at":
        if len(args) != 2: raise InterpreterError("string.at(s, i)")
        return str(args[0])[args[1]]
    if func == "substr":
        if len(args) < 2: raise InterpreterError("string.substr(s, start[, end])")
        s = str(args[0])
        start = args[1]
        end = args[2] if len(args) > 2 else len(s)
        return s[start:end]
    raise InterpreterError(f"string: неизвестная функция '{func}'")


def _call_os(func, args):
    if func == "listdir":
        if len(args) != 1: raise InterpreterError("os.listdir(path)")
        return os.listdir(args[0])
    if func == "getcwd":
        return os.getcwd()
    if func == "path_exists":
        if len(args) != 1: raise InterpreterError("os.path_exists(path)")
        return 1 if os.path.exists(args[0]) else 0
    if func == "mkdir":
        if len(args) != 1: raise InterpreterError("os.mkdir(path)")
        os.makedirs(args[0], exist_ok=True)
        return args[0]
    raise InterpreterError(f"os: неизвестная функция '{func}'")


class InterpreterError(Exception):
    pass


class EvalError(Exception):
    """Ошибка выполнения EVOL-программы (ловится try/catch)."""
    def __init__(self, message, var_name=None):
        super().__init__(message)
        self.var_name = var_name


class ChoiceFail(Exception):
    pass


def evaluate(expr, sigma):
    t = type(expr)
    if t is Int:
        return expr.value
    if t is Float:
        return expr.value
    if t is Str:
        return expr.value
    if t is Name:
        if expr.value in sigma:
            return sigma[expr.value]
        return Symbol(expr.value)
    if t is List:
        return [evaluate(i, sigma) for i in expr.items]
    if t is Tuple:
        return tuple(evaluate(i, sigma) for i in expr.items)
    if t is Fun:
        return ("closure", expr.params, expr.body, expr.param_anns, dict(sigma))
    if t is UnaryOp:
        op = expr.op
        val = evaluate(expr.operand, sigma)
        if op == "-":
            return -val
        if op == "not":
            return not is_truthy(val)
        raise InterpreterError(f"неизвестный унарный оператор {op}")
    if t is BinOp:
        return eval_binop(expr.op, evaluate(expr.left, sigma), evaluate(expr.right, sigma))
    if t is GetAttr:
        obj = evaluate(expr.obj, sigma)
        if isinstance(expr.obj, Name) and expr.obj.value == "py":
            if expr.attr not in _py_ffi:
                raise InterpreterError(
                    f"FFI: 'py.{expr.attr}' не зарегистрирован (import py ...: {expr.attr})"
                )
            return _py_ffi[expr.attr]
        if expr.attr == "kind":
            if isinstance(obj, tuple) and len(obj) >= 1:
                return obj[0]
            if isinstance(obj, Symbol):
                return obj
            raise InterpreterError(f".kind от {obj!r}")
        raise InterpreterError(f"неизвестный атрибут .{expr.attr}")
    if t is Index:
        obj = evaluate(expr.obj, sigma)
        key = evaluate(expr.key, sigma)
        if isinstance(obj, (list, tuple)):
            return obj[key]
        raise InterpreterError(f"индексация неприменима к {obj!r}")
    if t is Match:
        val = evaluate(expr.scrut, sigma)
        for case in expr.cases:
            b = {}
            if match_value(case.pat, val, b) is not None:
                local = dict(sigma)
                local.update(b)
                return evaluate(case.body, local)
        return None
    if t is Call:
        if isinstance(expr.func, GetAttr) and isinstance(expr.func.obj, Name):
            mod_name = expr.func.obj.value
            func_name = expr.func.attr
            args = [evaluate(a, sigma) for a in expr.args]
            if mod_name == "py":
                return _call_ffi(func_name, args)
            return _call_module(mod_name, func_name, args)
        func = evaluate(expr.func, sigma)
        if isinstance(expr.func, Name) and expr.func.value in BUILTINS:
            args = [evaluate(a, sigma) for a in expr.args]
            return call_builtin(expr.func.value, args)
        if isinstance(expr.func, Name) and expr.func.value[:1].isupper():
            # ADT-конструктор: Circle(3.0) -> (Symbol("Circle"), 3.0)
            args = [evaluate(a, sigma) for a in expr.args]
            return tuple([Symbol(expr.func.value)] + args)
        if isinstance(func, tuple) and func[0] == "closure":
            params, body, param_anns, env = func[1], func[2], func[3], func[4]
            args = [evaluate(a, sigma) for a in expr.args]
            if len(args) != len(params):
                raise InterpreterError(f"arity mismatch: {len(params)} vs {len(args)}")
            if _ENFORCE_TYPES and param_anns and any(param_anns):
                for a, ann in zip(args, param_anns):
                    if ann is not None and not _ann_match(ann, a):
                        raise EvalError(f"аргумент {a!r} не соответствует аннотации {ann}")
            local = dict(env)
            local.update(zip(params, args))
            return evaluate(body, local)
        raise InterpreterError(f"вызов не-функции: {func!r}")
    raise InterpreterError(f"неизвестный expr-узел {t}")


def eval_binop(op, l, r):
    if op == "+":
        return l + r
    if op == "-":
        return l - r
    if op == "*":
        return l * r
    if op == "/":
        if r == 0:
            raise InterpreterError("деление на 0")
        return l // r
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
        return is_truthy(l) and is_truthy(r)
    if op == "or":
        return is_truthy(l) or is_truthy(r)
    raise InterpreterError(f"неизвестный бинарный оператор {op}")


def eval_eff(node, sigma):
    """Возвращает (new_sigma, emits, spawned, retracted)."""
    t = type(node)
    if t is Block:
        cur = sigma
        emits, spawned, retracted = [], [], set()
        for stmt in node.stmts:
            cur, e, s, r = eval_eff(stmt, cur)
            emits += e
            spawned += s
            retracted |= r
        return cur, emits, spawned, retracted
    if t is Assign:
        cur = dict(sigma)
        val = evaluate(node.value, sigma)
        if _ENFORCE_TYPES and node.ann is not None and not _ann_match(node.ann, val):
            raise EvalError(f"присваивание '{node.name}': значение {val!r} не соответствует аннотации {node.ann}")
        cur[node.name] = val
        return cur, [], [], set()
    if t is Emit:
        return sigma, [evaluate(node.value, sigma)], [], set()
    if t is Spawn:
        return sigma, [], [node], set()
    if t is Retract:
        return sigma, [], [], {node.name}
    if t is If:
        if is_truthy(evaluate(node.cond, sigma)):
            return eval_eff(node.then_branch, sigma)
        return eval_eff(node.else_branch, sigma)
    if t is Seq:
        s1, e1, sp1, r1 = eval_eff(node.a, sigma)
        s2, e2, sp2, r2 = eval_eff(node.b, s1)
        return s2, e1 + e2, sp1 + sp2, r1 | r2
    if t is Par:
        # оба эффекта применяются к одному Σ независимо; конфликт имён -> fail
        sa, ea, spa, ra = eval_eff(node.a, sigma)
        sb, eb, spb, rb = eval_eff(node.b, sigma)
        merged = dict(sigma)
        for k in set(sa) | set(sb):
            va, vb = sa.get(k), sb.get(k)
            if va is not None and vb is not None and va != vb:
                raise InterpreterError(f"par: конфликт имён '{k}' ({va!r} vs {vb!r})")
            merged[k] = va if va is not None else vb
        return merged, ea + eb, spa + spb, ra | rb
    if t is Choice:
        try:
            return eval_eff(node.a, sigma)
        except ChoiceFail:
            return eval_eff(node.b, sigma)
    if t is Loop:
        cur = sigma
        emits, spawned, retracted = [], [], set()
        guard_count = 0
        while is_truthy(evaluate(node.guard, cur)):
            guard_count += 1
            if guard_count > 100000:
                raise InterpreterError("loop: превышен лимит итераций (возможно, бесконечный цикл)")
            cur, e, s, r = eval_eff(node.body, cur)
            emits += e
            spawned += s
            retracted |= r
        return cur, emits, spawned, retracted
    if t is ForEach:
        coll = evaluate(node.coll, sigma)
        if not isinstance(coll, list):
            raise InterpreterError(f"forall: коллекция не список: {coll!r}")
        cur = sigma
        emits, spawned, retracted = [], [], set()
        for e in coll:
            local = dict(cur)
            local[node.var] = e
            nxt, e2, s2, r2 = eval_eff(node.body, local)
            cur = {k: v for k, v in nxt.items() if k != node.var}
            emits += e2
            spawned += s2
            retracted |= r2
        return cur, emits, spawned, retracted
    if t is TryCatch:
        try:
            return eval_eff(node.body, sigma)
        except (InterpreterError, EvalError) as e:
            local = dict(sigma)
            local[node.catch_var] = str(e)
            return eval_eff(node.catch_body, local)
    if t is Raise:
        msg = evaluate(node.message, sigma)
        raise EvalError(str(msg))
    if t is Call:
        evaluate(node, sigma)
        return sigma, [], [], set()
    raise InterpreterError(f"неизвестный eff-узел {t}")


def match(pat, msg):
    """Возвращает dict bindings или None."""
    if isinstance(pat, Name):
        tag = pat.value
        if isinstance(msg, Symbol) and msg.name == tag:
            return {}
        return None
    if isinstance(pat, Tuple):
        if not pat.items:
            return None
        tag_node = pat.items[0]
        if not isinstance(tag_node, Name):
            return None
        tag = tag_node.value
        if not isinstance(msg, tuple):
            return None
        if len(msg) == 0 or not isinstance(msg[0], Symbol) or msg[0].name != tag:
            return None
        if len(msg) - 1 != len(pat.items) - 1:
            return None
        bindings = {}
        for i, item in enumerate(pat.items[1:], start=1):
            if isinstance(item, Name):
                bindings[item.value] = msg[i]
        return bindings
    return None


def match_value(pat, val, bindings):
    """Сопоставление значения (tuple/Symbol) с паттерном match-выражения.
    Возвращает bindings или None."""
    if isinstance(pat, Name):
        if pat.value == "_":
            return bindings
        if isinstance(val, Symbol) and val.name == pat.value:
            return bindings
        if (isinstance(val, tuple) and len(val) >= 1
                and isinstance(val[0], Symbol) and val[0].name == pat.value):
            return bindings
        return None
    if isinstance(pat, Tuple):
        if not isinstance(val, tuple) or len(pat.items) != len(val):
            return None
        tag = pat.items[0]
        if not isinstance(tag, Name):
            return None
        if not (isinstance(val[0], Symbol) and val[0].name == tag.value):
            return None
        for item, v in zip(pat.items[1:], val[1:]):
            if isinstance(item, Name) and item.value != "_":
                bindings[item.value] = v
        return bindings
    return None


def _resolve_module(target, base_dir):
    """Ищет .evol-файл: абсолютный, рядом с импортирующим файлом, в cwd, в samples/."""
    candidates = []
    if os.path.isabs(target):
        candidates.append(target)
    else:
        candidates.append(os.path.join(base_dir, target))
        candidates.append(os.path.join(os.getcwd(), target))
        candidates.append(os.path.join(SAMPLES_DIR, target))
        if not target.endswith(".evol"):
            candidates.append(os.path.join(base_dir, target + ".evol"))
            candidates.append(os.path.join(os.getcwd(), target + ".evol"))
            candidates.append(os.path.join(SAMPLES_DIR, target + ".evol"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _register_pyimport(d):
    try:
        if "." in d.module:
            parts = d.module.split(".")
            mod = __import__(parts[0], fromlist=["__name__"])
            for p in parts[1:]:
                mod = getattr(mod, p)
        else:
            mod = __import__(d.module)
    except Exception as e:
        raise InterpreterError(
            f"FFI: не удалось импортировать Python-модуль '{d.module}': {e}"
        )
    names = d.funcs if d.funcs else [n for n in dir(mod) if not n.startswith("_")]
    for fn in names:
        if fn in _FFI_BANNED:
            raise InterpreterError(f"FFI: вызов '{fn}' запрещён (sandbox)")
        if not hasattr(mod, fn):
            raise InterpreterError(f"FFI: '{d.module}.{fn}' не найдено")
        _py_ffi[fn] = getattr(mod, fn)


def collect_rule_table(decls, table=None, base_lib="", base_dir=".", _seen=None):
    """Возвращает {(libname, rulename): RuleNode}.
    import "файл.evol" / import name — подгружает внешний модуль (поиск путей).
    import py "mod": f, g — регистрирует FFI-функции."""
    if table is None:
        table = {}
    if _seen is None:
        _seen = set()
    for d in decls:
        if isinstance(d, Rule):
            table[(base_lib, d.name)] = d
        elif isinstance(d, Lib):
            for sub in d.decls:
                if isinstance(sub, Rule):
                    table[(d.name, sub.name)] = sub
        elif isinstance(d, EnumDecl):
            pass  # типы проверяются тайпчекером; в рантайме не нужны
        elif isinstance(d, PyImport):
            _register_pyimport(d)
        elif isinstance(d, Import):
            if d.is_path:
                path = _resolve_module(d.target, base_dir)
                if path is None:
                    raise InterpreterError(f"модуль не найден: {d.target}")
            else:
                path = _resolve_module(d.target + ".evol", base_dir)
                if path is None:
                    raise InterpreterError(f"модуль не найден: {d.target}.evol")
            if path in _seen:
                continue  # защита от циклов
            _seen.add(path)
            with open(path, encoding="utf-8") as f:
                sub_ast = parse(f.read(), path)
            stem = os.path.splitext(os.path.basename(path))[0]
            collect_rule_table(sub_ast, table, base_lib=stem,
                               base_dir=os.path.dirname(path), _seen=_seen)
    return table


def resolve_spawn(table, sp):
    """Разрешает spawn(lib, name) в RuleNode. Квалифицированный — точно; неквалифицированный — default lib, иначе любой."""
    if sp.lib is not None:
        return table.get((sp.lib, sp.name))
    if ("", sp.name) in table:
        return table[("", sp.name)]
    for (lb, nm), node in table.items():
        if nm == sp.name:
            return node
    return None


def run(ast, bootstrap, max_steps=100000, enforce_types=False, base_dir="."):
    set_enforce_types(enforce_types)
    _sim_state["step"] = 0
    _py_ffi.clear()
    table = collect_rule_table(ast, base_dir=base_dir)
    q = []
    rid = 0
    for (lib, name), node in table.items():
        q.append({"id": rid, "name": name, "lib": lib, "prio": 0,
                  "pat": node.pat, "eff": node.body})
        rid += 1
    sigma = {}
    queue = [make_value(m) for m in bootstrap]
    steps = 0
    emitted_log = []
    while queue and steps < max_steps:
        steps += 1
        _sim_state["step"] = steps
        m = queue.pop(0)
        cands = []
        for r in q:
            b = match(r["pat"], m)
            if b is not None:
                cands.append((r, b))
        if not cands:
            continue
        cands.sort(key=lambda rb: rb[0]["prio"], reverse=True)
        r, bindings = cands[0]
        local = dict(sigma)
        local.update(bindings)
        if _ENFORCE_TYPES and isinstance(r["pat"], Tuple):
            for item in r["pat"].items[1:]:
                if isinstance(item, Name) and item.ann is not None:
                    v = local.get(item.value)
                    if not _ann_match(item.ann, v):
                        raise EvalError(
                            f"сообщение: поле '{item.value}' {v!r} не соответствует аннотации {item.ann}"
                        )
        new_sigma, emits, spawned, retracted = eval_eff(r["eff"], local)
        sigma = new_sigma
        for v in emits:
            queue.append(v)
            emitted_log.append(v)
        for sp in spawned:
            node = resolve_spawn(table, sp)
            if node is not None:
                q.append({"id": rid, "name": sp.name, "lib": sp.lib, "prio": 0,
                          "pat": node.pat, "eff": node.body})
                rid += 1
        if retracted:
            q = [x for x in q if x["name"] not in retracted]
    return {
        "steps": steps,
        "store": sigma,
        "emitted": emitted_log,
        "stopped_by_max_steps": steps >= max_steps,
    }


def run_file(path, bootstrap, enforce_types=False):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    ast = parse(src, path)
    return run(ast, bootstrap, enforce_types=enforce_types,
               base_dir=os.path.dirname(os.path.abspath(path)))
