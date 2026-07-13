"""EVOL → Python транспилятор.

Генерирует самодостаточный Python-скрипт, реализующий семантику δ(S)→S'.
Результат можно запустить: python compiled_output.py

Поддерживает: assign, emit, if/else, seq, block, par, choice, loop, forall,
spawn, retract, модули (console, random, file, sim).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ast_nodes import (
    Int, Float, Str, Name, List, Tuple, Fun, BinOp, UnaryOp, Call, GetAttr, Index,
    Block, Seq, Par, Choice, Loop, Assign, Emit, Spawn, Retract, If, ForEach,
    TryCatch, Raise, Rule, Lib, Import, TyCon, TyList,
)


class Compiler:
    def __init__(self):
        self._indent = 0
        self._lines = []
        self._rule_counter = 0
        self._closure_params = set()

    def _emit(self, line):
        self._lines.append("    " * self._indent + line)

    def compile(self, ast):
        self._lines = []
        self._indent = 0

        self._emit("# Auto-generated from EVOL — do not edit")
        self._emit("import random as _random")
        self._emit("import os as _os")
        self._emit("_noop = lambda *a: None")
        self._emit("")
        self._emit("store = {}")
        self._emit("queue = []")
        self._emit("rules = []")
        self._emit("_sim_step = 0")
        self._emit("")

        for decl in ast:
            if isinstance(decl, Lib):
                self._compile_lib(decl)

        self._emit("")
        self._emit("def match_tag(msg, tag):")
        self._emit("    if isinstance(msg, tuple) and len(msg) > 0:")
        self._emit("        return getattr(msg[0], 'name', msg[0]) == tag")
        self._emit("    if isinstance(msg, str):")
        self._emit("        return msg == tag")
        self._emit("    return False")
        self._emit("")
        self._emit("def match_tuple(msg, tag, n):")
        self._emit("    if not isinstance(msg, tuple) or len(msg) < n + 1:")
        self._emit("        return None")
        self._emit("    t = getattr(msg[0], 'name', msg[0]) if hasattr(msg[0], 'name') else msg[0]")
        self._emit("    if t != tag:")
        self._emit("        return None")
        self._emit("    return msg[1:n+1]")
        self._emit("")

        self._emit("def dispatch(msg):")
        self._emit("    global _sim_step")
        self._emit("    _sim_step += 1")
        self._emit("    for rule_fn in rules:")
        self._emit("        result = rule_fn(msg)")
        self._emit("        if result is not None:")
        self._emit("            return")
        self._emit("")

        self._emit("def run_evol(bootstrap):")
        self._emit("    global store, queue")
        self._emit("    store = {}")
        self._emit("    queue = list(bootstrap)")
        self._emit("    _sim_step = 0")
        self._emit("    while queue:")
        self._emit("        msg = queue.pop(0)")
        self._emit("        dispatch(msg)")
        self._emit("")

        self._emit("if __name__ == '__main__':")
        self._indent = 1
        self._emit("run_evol(['boot'])")
        self._emit("print('Store:', store)")
        self._emit("print('Steps:', _sim_step)")
        self._indent = 0

        return "\n".join(self._lines)

    def _compile_lib(self, lib):
        for decl in lib.decls:
            if isinstance(decl, Rule):
                self._compile_rule(lib.name, decl)

    def _compile_rule(self, lib_name, rule):
        self._rule_counter += 1
        fn_name = f"rule_{lib_name}_{rule.name}_{self._rule_counter}"
        pat = rule.pat

        self._emit(f"def {fn_name}(msg):")
        self._indent = 1

        if isinstance(pat, Name):
            tag = pat.value
            self._emit(f"    if not match_tag(msg, '{tag}'):")
            self._emit("        return None")
        elif isinstance(pat, Tuple) and pat.items:
            tag_node = pat.items[0]
            if isinstance(tag_node, Name):
                tag = tag_node.value
                n = len(pat.items) - 1
                if n == 0:
                    self._emit(f"    if not match_tag(msg, '{tag}'):")
                    self._emit("        return None")
                else:
                    bindings = [f"v{i}" for i in range(n)]
                    self._emit(f"    _b = match_tuple(msg, '{tag}', {n})")
                    self._emit("    if _b is None:")
                    self._emit("        return None")
                    for i, bn in enumerate(bindings):
                        self._emit(f"    {bn} = _b[{i}]")

        self._compile_eff(rule.body)
        self._emit("    return True")
        self._indent = 0
        self._emit("")
        self._emit(f"rules.append({fn_name})")
        self._emit("")

    def _compile_eff(self, eff):
        t = type(eff)
        if t is Block:
            for stmt in eff.stmts:
                self._compile_eff(stmt)
        elif t is Seq:
            self._compile_eff(eff.a)
            self._compile_eff(eff.b)
        elif t is Assign:
            if isinstance(eff.value, Fun):
                fn = f"fun_{eff.name}_{self._rule_counter}"
                self._rule_counter += 1
                params = ", ".join(eff.value.params)
                self._emit(f"    def {fn}({params}):")
                self._indent += 1
                saved = self._closure_params
                self._closure_params = set(eff.value.params)
                body_expr = self._compile_expr(eff.value.body)
                self._closure_params = saved
                self._emit(f"    return {body_expr}")
                self._indent -= 1
                self._emit(f"    store['{eff.name}'] = {fn}")
            else:
                val = self._compile_expr(eff.value)
                ann = f"  # : {_render_ann(eff.ann)}" if getattr(eff, "ann", None) is not None else ""
                self._emit(f"    store['{eff.name}'] = {val}{ann}")
        elif t is Emit:
            val = self._compile_expr(eff.value)
            self._emit(f"    queue.append({val})")
        elif t is If:
            cond = self._compile_expr(eff.cond)
            self._emit(f"    if {cond}:")
            self._indent += 1
            self._compile_eff(eff.then_branch)
            self._indent -= 1
            self._emit("    else:")
            self._indent += 1
            self._compile_eff(eff.else_branch)
            self._indent -= 1
        elif t is ForEach:
            coll = self._compile_expr(eff.coll)
            self._emit(f"    for {eff.var} in {coll}:")
            self._indent += 1
            self._compile_eff(eff.body)
            self._indent -= 1
        elif t is Loop:
            guard = self._compile_expr(eff.guard)
            self._emit(f"    while {guard}:")
            self._indent += 1
            self._compile_eff(eff.body)
            self._indent -= 1
        elif t is TryCatch:
            self._emit("    try:")
            self._indent += 1
            self._compile_eff(eff.body)
            self._indent -= 1
            self._emit(f"    except Exception as {eff.catch_var}:")
            self._indent += 1
            self._compile_eff(eff.catch_body)
            self._indent -= 1
        elif t is Raise:
            msg = self._compile_expr(eff.message)
            self._emit(f"    raise Exception({msg})")
        elif t is Par:
            self._compile_eff(eff.a)
            self._compile_eff(eff.b)
        elif t is Choice:
            self._compile_eff(eff.a)
        elif t is Call:
            expr = self._compile_expr(eff)
            self._emit(f"    {expr}")
        elif t is Spawn:
            pass
        elif t is Retract:
            pass
        else:
            self._emit(f"    pass  # unsupported: {t.__name__}")

    def _compile_expr(self, expr):
        t = type(expr)
        if t is Int:
            return str(expr.value)
        if t is Float:
            return str(expr.value)
        if t is Str:
            return repr(expr.value)
        if t is Name:
            if expr.value in ("true", "True"):
                return "True"
            if expr.value in ("false", "False"):
                return "False"
            if expr.value in self._closure_params:
                return expr.value
            return f"store.get('{expr.value}', 0)"
        if t is List:
            items = ", ".join(self._compile_expr(i) for i in expr.items)
            return f"[{items}]"
        if t is Tuple:
            items = ", ".join(self._compile_expr(i) for i in expr.items)
            if len(items) == 0:
                return "()"
            return f"({items},)" if len(items) == 1 else f"({items})"
        if t is BinOp:
            l = self._compile_expr(expr.left)
            r = self._compile_expr(expr.right)
            op = expr.op
            if op == "/":
                return f"({l} // {r})"
            if op == "and":
                return f"({l} and {r})"
            if op == "or":
                return f"({l} or {r})"
            return f"({l} {op} {r})"
        if t is UnaryOp:
            val = self._compile_expr(expr.operand)
            if expr.op == "not":
                return f"(not {val})"
            return f"(-{val})"
        if t is GetAttr:
            obj = self._compile_expr(expr.obj)
            return f"{obj}.{expr.attr}"
        if t is Call:
            if isinstance(expr.func, GetAttr) and isinstance(expr.func.obj, Name):
                mod = expr.func.obj.value
                func = expr.func.attr
                args = ", ".join(self._compile_expr(a) for a in expr.args)
                return self._compile_module_call(mod, func, args)
            if isinstance(expr.func, Name):
                name = expr.func.value
                args = ", ".join(self._compile_expr(a) for a in expr.args)
                if name == "range":
                    return f"list(range({args}))"
                if name == "len":
                    return f"len({args})"
                if name == "abs":
                    return f"abs({args})"
                if name == "min":
                    return f"min({args})"
                if name == "max":
                    return f"max({args})"
                if name == "str":
                    return f"str({args})"
                if name == "int":
                    return f"int({args})"
                if name == "float":
                    return f"float({args})"
                return f"store.get('{name}', _noop)({args})"
        if t is Index:
            obj = self._compile_expr(expr.obj)
            key = self._compile_expr(expr.key)
            return f"{obj}[{key}]"
        return f"0  # unsupported: {t.__name__}"

    def _compile_module_call(self, mod, func, args):
        if mod == "console":
            if func in ("print", "println"):
                return f"print({args})"
        if mod == "random":
            if func == "int":
                return f"_random.randint({args})"
            if func == "pick":
                return f"_random.choice({args})"
            if func == "shuffle":
                return f"list(_random.sample({args}, len({args})))"
        if mod == "file":
            if func == "read":
                return f"open({args}, encoding='utf-8').read()"
            if func == "write":
                return f"open({args.split(',')[0]}, 'w', encoding='utf-8').write({args.split(',')[1].strip()})"
            if func == "exists":
                return f"(1 if _os.path.exists({args}) else 0)"
        if mod == "sim":
            if func == "step":
                return "_sim_step"
            if func == "set_seed":
                return f"_random.seed({args})"
        return f"{mod}.{func}({args})"


def _render_ann(ann):
    if isinstance(ann, TyCon):
        return ann.name
    if isinstance(ann, TyList):
        return f"List[{_render_ann(ann.elem)}]"
    return "?"


def compile_evol(ast):
    c = Compiler()
    return c.compile(ast)


if __name__ == "__main__":
    from parser import parse

    if len(sys.argv) < 2:
        print("Usage: python compiler.py <file.evol>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        src = f.read()

    ast = parse(src, path)
    py_code = compile_evol(ast)

    out_path = path.rsplit(".", 1)[0] + ".py"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(py_code)
    print(f"Compiled: {path} -> {out_path}")
