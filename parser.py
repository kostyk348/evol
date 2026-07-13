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


# Имена встроенных типов (Этап 7: аннотации)
TYPE_NAMES = {"Int", "Str", "Bool", "Float", "Sym", "Top", "List"}


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
        if t.kind == "IMPORT":
            return self.parse_import()
        if t.kind in ("TYPE", "ENUM"):
            return self.parse_enum()
        raise ParseError(f"ожидался decl (lib/rule/import/type), получен {t.kind} {t.text!r} в {t.line}:{t.col}")

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
        if self.at("OP", ";"):
            self.next()
        return A.Rule(name=name, pat=pat, body=body, line=t.line, col=t.col)

    def parse_import(self):
        t = self.next()  # IMPORT
        if self.at("NAME", "py"):
            self.next()
            mod = self.expect("STR").text
            alias = mod.split(".")[-1]
            funcs = None
            if self.at("OP", ":"):
                self.next()
                funcs = [self.expect_name()]
                while self.at("OP", ","):
                    self.next()
                    funcs.append(self.expect_name())
            self.expect("OP", ";")
            return A.PyImport(module=mod, funcs=funcs, alias=alias,
                              line=t.line, col=t.col)
        if self.at("STR"):
            target = self.next().text
            self.expect("OP", ";")
            return A.Import(target=target, is_path=True, line=t.line, col=t.col)
        name = self.expect_name()
        self.expect("OP", ";")
        return A.Import(target=name, is_path=False, line=t.line, col=t.col)

    def parse_enum(self):
        t = self.next()  # TYPE или ENUM
        name = self.expect_name()
        self.expect("OP", "=")
        variants = [self._parse_variant()]
        while self.at("OP", "|"):
            self.next()
            variants.append(self._parse_variant())
        self.expect("OP", ";")
        return A.EnumDecl(name=name, variants=variants, line=t.line, col=t.col)

    def _parse_variant(self):
        t = self.peek()
        tag = self.expect_name()
        fields = []
        if self.at("OP", "("):
            self.next()
            if not self.at("OP", ")"):
                nm, ann = self._parse_param()
                fields.append(ann)
                while self.at("OP", ","):
                    self.next()
                    nm, ann = self._parse_param()
                    fields.append(ann)
            self.expect("OP", ")")
        return A.EnumVariant(tag=tag, fields=fields, line=t.line, col=t.col)

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
            if self.at("NAME") and self.peek2_is_dot():
                lib = self.expect_name()
                self.expect("OP", ".")
                name = self.expect_name()
                return A.Spawn(lib=lib, name=name, line=t.line, col=t.col)
            name = self.expect_name()
            return A.Spawn(lib=None, name=name, line=t.line, col=t.col)
        if t.kind == "RETRACT":
            self.next()
            name = self.expect_name()
            return A.Retract(name=name, line=t.line, col=t.col)
        if t.kind == "FORALL":
            return self._parse_forall()
        if t.kind == "TRY":
            return self._parse_try_catch()
        if t.kind == "RAISE":
            self.next()
            msg = self.parse_expr()
            return A.Raise(message=msg, line=t.line, col=t.col)
        # assign: NAME ":="  |  NAME ":" Type ":="
        if t.kind == "NAME" and (self._peek2_is_assign() or self._peek2_is_colon_type()):
            self.next()
            name = t.text
            ann = None
            if self.at("OP", ":"):
                self.next()
                ann = self.parse_type_expr()
                self.expect("OP", ":=")
            else:
                self.expect("OP", ":=")
            value = self.parse_expr()
            return A.Assign(name=name, value=value, ann=ann, line=t.line, col=t.col)
        # module call as effect: console.print(x), file.write(p, d), ...
        if t.kind == "NAME":
            expr = self.parse_expr()
            if isinstance(expr, A.Call):
                return expr
            raise ParseError(
                f"ожидался eff, получен выражение {t.kind} {t.text!r} в {t.line}:{t.col}"
            )
        raise ParseError(
            f"ожидался eff, получен {t.kind} {t.text!r} в {t.line}:{t.col}"
        )

    def _peek2_is_assign(self):
        if self.pos + 1 >= len(self.toks):
            return False
        nxt = self.toks[self.pos + 1]
        return nxt.kind == "OP" and nxt.text == ":="

    def peek2_is_dot(self):
        if self.pos + 1 >= len(self.toks):
            return False
        nxt = self.toks[self.pos + 1]
        return nxt.kind == "OP" and nxt.text == "."

    def _peek2_is_colon_type(self):
        """NAME ':' <тип> — аннотированное имя (паттерн/параметр/LHS)."""
        if self.pos + 2 >= len(self.toks):
            return False
        a, b = self.toks[self.pos + 1], self.toks[self.pos + 2]
        return a.kind == "OP" and a.text == ":" and b.kind == "NAME" and b.text in TYPE_NAMES

    def _parse_annotated_name(self):
        if self._peek2_is_colon_type():
            t = self.peek()
            name = self.expect_name()
            self.next()  # ':'
            ann = self.parse_type_expr()
            return A.Name(value=name, ann=ann, line=t.line, col=t.col)
        t = self.expect("NAME")
        return A.Name(value=t.text, line=t.line, col=t.col)

    def parse_type_expr(self):
        t = self.peek()
        if t.kind != "NAME":
            raise ParseError(
                f"ожидался тип, получен {t.kind} {t.text!r} в {t.line}:{t.col}"
            )
        name = self.next().text
        if name == "List" and self.at("OP", "["):
            self.next()
            inner = self.parse_type_expr()
            self.expect("OP", "]")
            return A.TyList(elem=inner, line=t.line, col=t.col)
        return A.TyCon(name=name, line=t.line, col=t.col)

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

    def _parse_try_catch(self):
        t = self.next()  # TRY
        self.expect("OP", "{")
        stmts = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError("незакрытый try (нет '}}')")
            stmts.append(self.parse_eff())
        self.expect("OP", "}")
        self.expect("CATCH")
        catch_var = self.expect_name()
        self.expect("OP", "{")
        catch_stmts = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError("незакрытый catch (нет '}}')")
            catch_stmts.append(self.parse_eff())
        self.expect("OP", "}")
        body = A.Block(stmts=stmts, line=t.line, col=t.col)
        catch_body = A.Block(stmts=catch_stmts, line=t.line, col=t.col)
        return A.TryCatch(body=body, catch_var=catch_var, catch_body=catch_body,
                          line=t.line, col=t.col)

    def parse_block(self):
        t = self.expect("OP", "{")
        stmts = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError(f"незакрытый блок (нет '}}')")
            stmts.append(self.parse_eff())
            if self.at("OP", ";"):
                self.next()
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
                node = A.Call(func=node, args=args, line=node.line, col=node.col)
            else:
                break
        return node

    def parse_primary(self):
        t = self.peek()
        if t.kind == "MATCH":
            return self.parse_match()
        if t.kind == "INT":
            self.next()
            return A.Int(value=int(t.text), line=t.line, col=t.col)
        if t.kind == "FLOAT":
            self.next()
            return A.Float(value=float(t.text), line=t.line, col=t.col)
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

            def parse_item():
                if self.at("NAME") and self._peek2_is_colon_type():
                    return self._parse_annotated_name()
                return self.parse_expr()

            first = parse_item()
            if self.at("OP", ","):
                items = [first]
                while self.at("OP", ","):
                    self.next()
                    if self.at("OP", ")"):
                        break
                    items.append(parse_item())
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
        params, param_anns = [], []
        if not self.at("OP", ")"):
            nm, ann = self._parse_param()
            params.append(nm)
            param_anns.append(ann)
            while self.at("OP", ","):
                self.next()
                nm, ann = self._parse_param()
                params.append(nm)
                param_anns.append(ann)
        self.expect("OP", ")")
        ret_ann = None
        if self.at("OP", "->"):
            self.next()
            ret_ann = self.parse_type_expr()
        self.expect("OP", "=>")
        body = self.parse_expr()
        return A.Fun(params=params, body=body, param_anns=param_anns,
                     ret_ann=ret_ann, line=t.line, col=t.col)

    def _parse_param(self):
        if self._peek2_is_colon_type():
            name = self.expect_name()
            self.next()  # ':'
            ann = self.parse_type_expr()
            return name, ann
        return self.expect_name(), None

    # --- match-выражение (ADT / value dispatch) ---
    def parse_match(self):
        t = self.next()  # MATCH
        scrut = self.parse_expr()
        self.expect("OP", "{")
        cases = []
        while not self.at("OP", "}"):
            if self.at("EOF"):
                raise ParseError("незакрытый match (нет '}')")
            cases.append(self._parse_match_case())
        self.expect("OP", "}")
        return A.Match(scrut=scrut, cases=cases, line=t.line, col=t.col)

    def _parse_match_case(self):
        pat = self._parse_match_pat()
        self.expect("OP", "=>")
        body = self.parse_expr()
        if self.at("OP", ";"):
            self.next()
        return A.MatchCase(pat=pat, body=body, line=pat.line, col=pat.col)

    def _parse_match_pat(self):
        t = self.peek()
        if t.kind == "NAME" and t.text == "_":
            self.next()
            return A.Name(value="_", line=t.line, col=t.col)
        if t.kind == "NAME":
            self.next()
            if self.at("OP", "("):
                self.next()
                items = [A.Name(value=t.text, line=t.line, col=t.col)]
                if not self.at("OP", ")"):
                    items.append(self._parse_annotated_name())
                while self.at("OP", ","):
                    self.next()
                    items.append(self._parse_annotated_name())
                self.expect("OP", ")")
                return A.Tuple(items=items, line=t.line, col=t.col)
            return A.Name(value=t.text, line=t.line, col=t.col)
        raise ParseError(f"ожидался паттерн match, получен {t.kind} {t.text!r}")


def parse(src, filename="<input>"):
    tokens = tokenize(src, filename)
    parser = Parser(tokens)
    ast = parser.parse_program()
    if not parser.at("EOF"):
        t = parser.peek()
        raise ParseError(f"лишний токен {t.kind} {t.text!r} в {t.line}:{t.col}")
    return ast
