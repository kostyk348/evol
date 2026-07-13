"""EVOL AST. Узлы однозначно соответствуют грамматике Этапа 1.

decl  ::= Lib | Rule
eff   ::= Block | Seq | Par | Choice | Loop | Assign | Emit | Spawn | Retract | If
expr  ::= Int | Str | Name | List | Tuple | Fun | BinOp | UnaryOp | Call | GetAttr | Index
"""


class Node:
    _fields = ()

    def __init__(self, **kw):
        for f in self._fields:
            setattr(self, f, kw.get(f))
        self.line = kw.get("line")
        self.col = kw.get("col")

    def __repr__(self):
        inner = ", ".join(f"{f}={getattr(self, f)!r}" for f in self._fields)
        return f"{type(self).__name__}({inner})"


# --- declarations ---
class Lib(Node):
    _fields = ("name", "decls")


class Rule(Node):
    _fields = ("name", "pat", "body")  # body: eff


# --- effects (соответствуют формальной семантике Этапа 1) ---
class Block(Node):
    _fields = ("stmts",)  # list[eff]


class Seq(Node):
    _fields = ("a", "b")


class Par(Node):
    _fields = ("a", "b")


class Choice(Node):
    _fields = ("a", "b")


class Loop(Node):
    _fields = ("guard", "body")


class Assign(Node):
    _fields = ("name", "value")


class Emit(Node):
    _fields = ("value",)


class Spawn(Node):
    _fields = ("name",)


class Retract(Node):
    _fields = ("name",)


class If(Node):
    _fields = ("cond", "then_branch", "else_branch")


# --- expressions (чистые значения) ---
class Int(Node):
    _fields = ("value",)


class Str(Node):
    _fields = ("value",)


class Name(Node):
    _fields = ("value",)


class List(Node):
    _fields = ("items",)


class Tuple(Node):
    _fields = ("items",)


class Fun(Node):
    _fields = ("params", "body")  # body: expr


class BinOp(Node):
    _fields = ("op", "left", "right")


class UnaryOp(Node):
    _fields = ("op", "operand")


class Call(Node):
    _fields = ("func", "args")


class GetAttr(Node):
    _fields = ("obj", "attr")


class Index(Node):
    _fields = ("obj", "key")
