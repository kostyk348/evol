"""EVOL parser. Рекурсивный спуск; строит AST из токенов лексера.

Грамматика (Этап 1):
  prog  ::= decl*
  decl  ::= lib | rule
  lib   ::= "lib" NAME "{" decl* "}"
  rule  ::= "rule" NAME "=" "when" expr "=>" eff
  eff   ::= block | seq | par | choice | loop | if | emit | spawn | retract | assign
  block ::= "{" eff* "}"
  expr  ::= ... (чистые значения, с операторами)
"""

from lexer import tokenize, LexError, Token
import ast_nodes as A


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    # --- низкоуровневые помощники ---
    def peek(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def at(self, kind, text=None):
        t = self.peek()
        if t.kind != kind:
            return False
        if text is not None and t.text != text:
            return False
        return True

    def expect(self, kind, text=None):
        t = self.peek()
        if t.kind != kind or (text is not None and t.text != text):
            want = text if text else kind
            raise ParseError(
                f"ожидался {want}, получен {t.kind} {t.text!r} в {t.line}:{t.col}"
            )
        return self.next()

    def expect_name(self):
        t = self.expect("NAME")
        return t.text

    # --- программа / declarations ---
    def parse_program(self):
        decls = []
        while not self.at("EOF"):
            decls.append(self.parse_decl())
        return decls

    def parse_decl(self):
        t = self.peek()
        if t.kind == "LIB":
            return self.parse_lib()
        if t.kind == "RULE":
            return self.parse_rule()
        raise ParseError(f"ожидался decl (lib/rule), получен {t.kind} {t.text!r} в {t.line}:{t.col}")

    def parse_lib(self):
        t = self.expect("LIB")
        name = self.expect_name()
        self.expect("OP", "{")
        decls = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError(f"незакрытая библиотека {name!r} (нет '}}')")
            decls.append(self.parse_decl())
        self.expect("OP", "}")
        return A.Lib(name=name, decls=decls, line=t.line, col=t.col)

    def parse_rule(self):
        t = self.expect("RULE")
        name = self.expect_name()
        self.expect("OP", "=")
        self.expect("WHEN")
        pat = self.parse_expr()
        self.expect("OP", "=>")
        body = self.parse_eff()
        return A.Rule(name=name, pat=pat, body=body, line=t.line, col=t.col)

    # --- effects ---
    def parse_eff(self):
        t = self.peek()
        if t.kind == "OP" and t.text == "{":
            return self.parse_block()
        if t.kind == "SEQ":
            return self._parse_bin_eff("SEQ", A.Seq)
        if t.kind == "PAR":
            return self._parse_bin_eff("PAR", A.Par)
        if t.kind == "CHOICE":
            return self._parse_bin_eff("CHOICE", A.Choice)
        if t.kind == "LOOP":
            self.next()
            self.expect("OP", "(")
            guard = self.parse_expr()
            self.expect("OP", ",")
            body = self.parse_eff()
            self.expect("OP", ")")
            return A.Loop(guard=guard, body=body, line=t.line, col=t.col)
        if t.kind == "IF":
            self.next()
            cond = self.parse_expr()
            self.expect("THEN")
            then_b = self.parse_eff()
            self.expect("ELSE")
            else_b = self.parse_eff()
            return A.If(cond=cond, then_branch=then_b, else_branch=else_b, line=t.line, col=t.col)
        if t.kind == "EMIT":
            self.next()
            value = self.parse_expr()
            return A.Emit(value=value, line=t.line, col=t.col)
        if t.kind == "SPAWN":
            self.next()
            name = self.expect_name()
            return A.Spawn(name=name, line=t.line, col=t.col)
        if t.kind == "RETRACT":
            self.next()
            name = self.expect_name()
            return A.Retract(name=name, line=t.line, col=t.col)
        if t.kind == "FORALL":
            return self._parse_forall()
        # assign: NAME ":="
        if t.kind == "NAME" and self._peek2_is_assign():
            self.next()
            name = t.text
            self.expect("OP", ":=")
            value = self.parse_expr()
            return A.Assign(name=name, value=value, line=t.line, col=t.col)
        raise ParseError(
            f"ожидался eff, получен {t.kind} {t.text!r} в {t.line}:{t.col}"
        )

    def _peek2_is_assign(self):
        if self.pos + 1 >= len(self.toks):
            return False
        nxt = self.toks[self.pos + 1]
        return nxt.kind == "OP" and nxt.text == ":="

    def _parse_bin_eff(self, kw, cls):
        t = self.next()
        self.expect("OP", "(")
        a = self.parse_eff()
        self.expect("OP", ",")
        b = self.parse_eff()
        self.expect("OP", ")")
        return cls(a=a, b=b, line=t.line, col=t.col)

    def _parse_forall(self):
        t = self.next()  # FORALL
        var = self.expect_name()
        self.expect_name()  # "in"
        coll = self.parse_expr()
        self.expect("OP", "{")
        stmts = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError(f"незакрытый forall (нет '}}')")
            stmts.append(self.parse_eff())
        self.expect("OP", "}")
        body = A.Block(stmts=stmts, line=t.line, col=t.col)
        return A.ForEach(var=var, coll=coll, body=body, line=t.line, col=t.col)

    def parse_block(self):
        t = self.expect("OP", "{")
        stmts = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError(f"незакрытый блок (нет '}}')")
            stmts.append(self.parse_eff())
        self.expect("OP", "}")
        return A.Block(stmts=stmts, line=t.line, col=t.col)

    # --- expressions (чистые значения) ---
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("OR"):
            op = self.next().text
            right = self.parse_and()
            left = A.BinOp(op=op, left=left, right=right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.at("AND"):
            op = self.next().text
            right = self.parse_not()
            left = A.BinOp(op=op, left=left, right=right)
        return left

    def parse_not(self):
        if self.at("NOT"):
            op = self.next().text
            operand = self.parse_not()
            return A.UnaryOp(op=op, operand=operand)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_add()
        while self.at("OP") and self.peek().text in ("==", "!=", "<", ">", "<=", ">="):
            op = self.next().text
            right = self.parse_add()
            left = A.BinOp(op=op, left=left, right=right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.at("OP") and self.peek().text in ("+", "-"):
            op = self.next().text
            right = self.parse_mul()
            left = A.BinOp(op=op, left=left, right=right)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.at("OP") and self.peek().text in ("*", "/"):
            op = self.next().text
            right = self.parse_unary()
            left = A.BinOp(op=op, left=left, right=right)
        return left

    def parse_unary(self):
        if self.at("OP") and self.peek().text == "-":
            op = self.next().text
            operand = self.parse_unary()
            return A.UnaryOp(op=op, operand=operand)
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_primary()
        while True:
            if self.at("OP", "."):
                self.next()
                attr = self.expect_name()
                node = A.GetAttr(obj=node, attr=attr)
            elif self.at("OP", "["):
                self.next()
                key = self.parse_expr()
                self.expect("OP", "]")
                node = A.Index(obj=node, key=key)
            elif self.at("OP", "("):
                self.next()
                args = []
                if not self.at("OP", ")"):
                    args.append(self.parse_expr())
                    while self.at("OP", ","):
                        self.next()
                        args.append(self.parse_expr())
                self.expect("OP", ")")
                node = A.Call(func=node, args=args)
            else:
                break
        return node

    def parse_primary(self):
        t = self.peek()
        if t.kind == "INT":
            self.next()
            return A.Int(value=int(t.text), line=t.line, col=t.col)
        if t.kind == "STR":
            self.next()
            return A.Str(value=t.text, line=t.line, col=t.col)
        if t.kind == "NAME":
            self.next()
            return A.Name(value=t.text, line=t.line, col=t.col)
        if t.kind == "FUN":
            return self.parse_fun()
        if t.kind == "OP" and t.text == "(":
            self.next()
            if self.at("OP", ")"):
                self.next()
                return A.Tuple(items=[], line=t.line, col=t.col)
            first = self.parse_expr()
            if self.at("OP", ","):
                items = [first]
                while self.at("OP", ","):
                    self.next()
                    if self.at("OP", ")"):
                        break
                    items.append(self.parse_expr())
                self.expect("OP", ")")
                return A.Tuple(items=items, line=t.line, col=t.col)
            self.expect("OP", ")")
            return first  # просто скобки
        if t.kind == "OP" and t.text == "[":
            self.next()
            items = []
            if not self.at("OP", "]"):
                items.append(self.parse_expr())
                while self.at("OP", ","):
                    self.next()
                    items.append(self.parse_expr())
            self.expect("OP", "]")
            return A.List(items=items, line=t.line, col=t.col)
        raise ParseError(f"неожиданный токен {t.kind} {t.text!r} в {t.line}:{t.col}")

    def parse_fun(self):
        t = self.expect("FUN")
        self.expect("OP", "(")
        params = []
        if not self.at("OP", ")"):
            params.append(self.expect_name())
            while self.at("OP", ","):
                self.next()
                params.append(self.expect_name())
        self.expect("OP", ")")
        self.expect("OP", "=>")
        body = self.parse_expr()
        return A.Fun(params=params, body=body, line=t.line, col=t.col)


def parse(src, filename="<input>"):
    tokens = tokenize(src, filename)
    parser = Parser(tokens)
    ast = parser.parse_program()
    if not parser.at("EOF"):
        t = parser.peek()
        raise ParseError(f"лишний токен {t.kind} {t.text!r} в {t.line}:{t.col}")
    return ast
