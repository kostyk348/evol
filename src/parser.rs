//! EVOL parser: recursive descent over the lexer tokens (Phase-1 grammar).
//!
//! ```text
//! prog  ::= decl*
//! decl  ::= lib | rule | import | enum
//! lib   ::= "lib" NAME "{" decl* "}"
//! rule  ::= "rule" NAME "=" "when" expr "=>" eff
//! eff   ::= block | seq | par | choice | loop | if | emit | spawn | retract | ...
//! ```

use crate::ast::*;
use crate::lexer::{py_quote, tokenize, Token};

/// Names of the built-in types (Phase 7 annotations).
pub const TYPE_NAMES: &[&str] = &["Int", "Str", "Bool", "Float", "Sym", "Top", "List"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParseError(pub String);

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for ParseError {}

pub struct Parser {
    toks: Vec<Token>,
    pos: usize,
}

/// Parse a whole program.
pub fn parse(src: &str, filename: &str) -> Result<Program, ParseError> {
    let tokens = tokenize(src, filename).map_err(|e| ParseError(e.0))?;
    let mut p = Parser {
        toks: tokens,
        pos: 0,
    };
    let ast = p.parse_program()?;
    if !p.at("EOF", None) {
        let t = p.peek();
        return Err(ParseError(format!(
            "лишний токен {} {} в {}:{}",
            t.kind,
            py_quote(&t.text),
            t.line,
            t.col
        )));
    }
    Ok(ast)
}

impl Parser {
    fn peek(&self) -> &Token {
        &self.toks[self.pos.min(self.toks.len() - 1)]
    }

    fn next(&mut self) -> Token {
        let t = self.toks[self.pos.min(self.toks.len() - 1)].clone();
        if self.pos < self.toks.len() - 1 {
            self.pos += 1;
        }
        t
    }

    fn at(&self, kind: &str, text: Option<&str>) -> bool {
        let t = self.peek();
        t.kind == kind && text.map_or(true, |x| t.text == x)
    }

    fn expect(&mut self, kind: &str, text: Option<&str>) -> Result<Token, ParseError> {
        let t = self.peek().clone();
        if t.kind != kind || (text.is_some() && t.text != text.unwrap()) {
            let want = text.unwrap_or(kind);
            return Err(ParseError(format!(
                "ожидался {want}, получен {} {} в {}:{}",
                t.kind,
                py_quote(&t.text),
                t.line,
                t.col
            )));
        }
        Ok(self.next())
    }

    fn expect_name(&mut self) -> Result<String, ParseError> {
        Ok(self.expect("NAME", None)?.text)
    }

    // --- program / declarations ---
    pub fn parse_program(&mut self) -> Result<Program, ParseError> {
        let mut decls = Vec::new();
        while !self.at("EOF", None) {
            decls.push(self.parse_decl()?);
        }
        Ok(decls)
    }

    fn parse_decl(&mut self) -> Result<Decl, ParseError> {
        let t = self.peek().clone();
        match t.kind.as_str() {
            "LIB" => self.parse_lib(),
            "RULE" => self.parse_rule(),
            "IMPORT" => self.parse_import(),
            "TYPE" | "ENUM" => self.parse_enum(),
            _ => Err(ParseError(format!(
                "ожидался decl (lib/rule/import/type), получен {} {} в {}:{}",
                t.kind,
                py_quote(&t.text),
                t.line,
                t.col
            ))),
        }
    }

    fn parse_lib(&mut self) -> Result<Decl, ParseError> {
        let t = self.expect("LIB", None)?;
        let name = self.expect_name()?;
        self.expect("OP", Some("{"))?;
        let mut decls = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError(format!(
                    "незакрытая библиотека {name:?} (нет '}}')"
                )));
            }
            decls.push(self.parse_decl()?);
        }
        self.expect("OP", Some("}"))?;
        Ok(Decl::Lib(Box::new(Lib {
            name,
            decls,
            line: t.line,
            col: t.col,
        })))
    }

    fn parse_rule(&mut self) -> Result<Decl, ParseError> {
        let t = self.expect("RULE", None)?;
        let name = self.expect_name()?;
        self.expect("OP", Some("="))?;
        self.expect("WHEN", None)?;
        let pat = self.parse_expr()?;
        self.expect("OP", Some("=>"))?;
        let body = self.parse_eff()?;
        if self.at("OP", Some(";")) {
            self.next();
        }
        Ok(Decl::Rule(Box::new(Rule {
            name,
            pat,
            body,
            line: t.line,
            col: t.col,
        })))
    }

    fn parse_import(&mut self) -> Result<Decl, ParseError> {
        let t = self.next(); // IMPORT
        if self.at("NAME", Some("py")) {
            self.next();
            let module = self.expect("STR", None)?.text;
            let alias = module.rsplit('.').next().unwrap_or(&module).to_string();
            let mut funcs = None;
            if self.at("OP", Some(":")) {
                self.next();
                let mut fs = vec![self.expect_name()?];
                while self.at("OP", Some(",")) {
                    self.next();
                    fs.push(self.expect_name()?);
                }
                funcs = Some(fs);
            }
            self.expect("OP", Some(";"))?;
            return Ok(Decl::PyImport(PyImport {
                module,
                funcs,
                alias,
                line: t.line,
                col: t.col,
            }));
        }
        if self.at("STR", None) {
            let target = self.next().text;
            self.expect("OP", Some(";"))?;
            return Ok(Decl::Import(Import {
                target,
                is_path: true,
                line: t.line,
                col: t.col,
            }));
        }
        let name = self.expect_name()?;
        self.expect("OP", Some(";"))?;
        Ok(Decl::Import(Import {
            target: name,
            is_path: false,
            line: t.line,
            col: t.col,
        }))
    }

    fn parse_enum(&mut self) -> Result<Decl, ParseError> {
        let t = self.next(); // TYPE or ENUM
        let name = self.expect_name()?;
        self.expect("OP", Some("="))?;
        let mut variants = vec![self.parse_variant()?];
        while self.at("OP", Some("|")) {
            self.next();
            variants.push(self.parse_variant()?);
        }
        self.expect("OP", Some(";"))?;
        Ok(Decl::EnumDecl(EnumDecl {
            name,
            variants,
            line: t.line,
            col: t.col,
        }))
    }

    fn parse_variant(&mut self) -> Result<EnumVariant, ParseError> {
        let t = self.peek().clone();
        let tag = self.expect_name()?;
        let mut fields = Vec::new();
        if self.at("OP", Some("(")) {
            self.next();
            if !self.at("OP", Some(")")) {
                let (_, ann) = self.parse_param()?;
                fields.push(ann);
                while self.at("OP", Some(",")) {
                    self.next();
                    let (_, ann) = self.parse_param()?;
                    fields.push(ann);
                }
            }
            self.expect("OP", Some(")"))?;
        }
        Ok(EnumVariant {
            tag,
            fields,
            line: t.line,
            col: t.col,
        })
    }

    // --- effects ---
    fn parse_eff(&mut self) -> Result<Eff, ParseError> {
        let t = self.peek().clone();
        if t.kind == "OP" && t.text == "{" {
            return self.parse_block();
        }
        if t.kind == "SEQ" {
            return self.parse_bin_eff("SEQ", false);
        }
        if t.kind == "PAR" {
            return self.parse_bin_eff("PAR", false);
        }
        if t.kind == "CHOICE" {
            return self.parse_bin_eff("CHOICE", true);
        }
        if t.kind == "LOOP" {
            self.next();
            self.expect("OP", Some("("))?;
            let guard = self.parse_expr()?;
            self.expect("OP", Some(","))?;
            let body = self.parse_eff()?;
            self.expect("OP", Some(")"))?;
            return Ok(Eff::Loop {
                guard,
                body: Box::new(body),
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "IF" {
            self.next();
            let cond = self.parse_expr()?;
            self.expect("THEN", None)?;
            let then_branch = self.parse_eff()?;
            self.expect("ELSE", None)?;
            let else_branch = self.parse_eff()?;
            return Ok(Eff::If {
                cond,
                then_branch: Box::new(then_branch),
                else_branch: Box::new(else_branch),
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "EMIT" {
            self.next();
            let value = self.parse_expr()?;
            return Ok(Eff::Emit {
                value,
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "SPAWN" {
            self.next();
            if self.at("NAME", None) && self.peek2_is_dot() {
                let lib = self.expect_name()?;
                self.expect("OP", Some("."))?;
                let name = self.expect_name()?;
                return Ok(Eff::Spawn {
                    lib: Some(lib),
                    name,
                    line: t.line,
                    col: t.col,
                });
            }
            let name = self.expect_name()?;
            return Ok(Eff::Spawn {
                lib: None,
                name,
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "RETRACT" {
            self.next();
            let name = self.expect_name()?;
            return Ok(Eff::Retract {
                name,
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "FORALL" {
            return self.parse_forall();
        }
        if t.kind == "TRY" {
            return self.parse_try_catch();
        }
        if t.kind == "RAISE" {
            self.next();
            let message = self.parse_expr()?;
            return Ok(Eff::Raise {
                message,
                line: t.line,
                col: t.col,
            });
        }
        // assign: NAME ":="  |  NAME ":" Type ":="
        if t.kind == "NAME" && (self.peek2_is_assign() || self.peek2_is_colon_type()) {
            self.next();
            let name = t.text.clone();
            let mut ann = None;
            if self.at("OP", Some(":")) {
                self.next();
                ann = Some(self.parse_type_expr()?);
                self.expect("OP", Some(":="))?;
            } else {
                self.expect("OP", Some(":="))?;
            }
            let value = self.parse_expr()?;
            return Ok(Eff::Assign {
                name,
                value,
                ann,
                line: t.line,
                col: t.col,
            });
        }
        // module call as effect: console.print(x), file.write(p, d), ...
        if t.kind == "NAME" {
            let expr = self.parse_expr()?;
            if let Expr::Call { .. } = expr {
                return Ok(Eff::Call { call: expr });
            }
            return Err(ParseError(format!(
                "ожидался eff, получен выражение {} {} в {}:{}",
                t.kind,
                py_quote(&t.text),
                t.line,
                t.col
            )));
        }
        Err(ParseError(format!(
            "ожидался eff, получен {} {} в {}:{}",
            t.kind,
            py_quote(&t.text),
            t.line,
            t.col
        )))
    }

    fn peek2_is_assign(&self) -> bool {
        self.toks
            .get(self.pos + 1)
            .is_some_and(|t| t.kind == "OP" && t.text == ":=")
    }

    fn peek2_is_dot(&self) -> bool {
        self.toks
            .get(self.pos + 1)
            .is_some_and(|t| t.kind == "OP" && t.text == ".")
    }

    fn peek2_is_colon_type(&self) -> bool {
        match (self.toks.get(self.pos + 1), self.toks.get(self.pos + 2)) {
            (Some(a), Some(b)) => {
                a.kind == "OP"
                    && a.text == ":"
                    && b.kind == "NAME"
                    && TYPE_NAMES.contains(&b.text.as_str())
            }
            _ => false,
        }
    }

    fn parse_annotated_name(&mut self) -> Result<Expr, ParseError> {
        let t = self.peek().clone();
        if self.peek2_is_colon_type() {
            let name = self.expect_name()?;
            self.next(); // ':'
            let ann = self.parse_type_expr()?;
            return Ok(Expr::Name {
                value: name,
                ann: Some(ann),
                line: t.line,
                col: t.col,
            });
        }
        let name = self.expect_name()?;
        Ok(Expr::Name {
            value: name,
            ann: None,
            line: t.line,
            col: t.col,
        })
    }

    fn parse_type_expr(&mut self) -> Result<TypeExpr, ParseError> {
        let t = self.peek().clone();
        if t.kind != "NAME" {
            return Err(ParseError(format!(
                "ожидался тип, получен {} {} в {}:{}",
                t.kind,
                py_quote(&t.text),
                t.line,
                t.col
            )));
        }
        let name = self.next().text;
        if name == "List" && self.at("OP", Some("[")) {
            self.next();
            let inner = self.parse_type_expr()?;
            self.expect("OP", Some("]"))?;
            return Ok(TypeExpr::TyList {
                elem: Box::new(inner),
                line: t.line,
                col: t.col,
            });
        }
        Ok(TypeExpr::TyCon {
            name,
            line: t.line,
            col: t.col,
        })
    }

    fn parse_bin_eff(&mut self, kw: &str, is_choice: bool) -> Result<Eff, ParseError> {
        let t = self.next();
        self.expect("OP", Some("("))?;
        let a = self.parse_eff()?;
        self.expect("OP", Some(","))?;
        let b = self.parse_eff()?;
        self.expect("OP", Some(")"))?;
        let (a, b) = (Box::new(a), Box::new(b));
        Ok(match (kw, is_choice) {
            ("SEQ", _) => Eff::Seq {
                a,
                b,
                line: t.line,
                col: t.col,
            },
            ("PAR", _) => Eff::Par {
                a,
                b,
                line: t.line,
                col: t.col,
            },
            _ => Eff::Choice {
                a,
                b,
                line: t.line,
                col: t.col,
            },
        })
    }

    fn parse_forall(&mut self) -> Result<Eff, ParseError> {
        let t = self.next(); // FORALL
        let var = self.expect_name()?;
        self.expect_name()?; // "in"
        let coll = self.parse_expr()?;
        self.expect("OP", Some("{"))?;
        let mut stmts = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError("незакрытый forall (нет '}')".into()));
            }
            stmts.push(self.parse_eff()?);
        }
        self.expect("OP", Some("}"))?;
        Ok(Eff::ForEach {
            var,
            coll,
            body: Box::new(Eff::Block {
                stmts,
                line: t.line,
                col: t.col,
            }),
            line: t.line,
            col: t.col,
        })
    }

    fn parse_try_catch(&mut self) -> Result<Eff, ParseError> {
        let t = self.next(); // TRY
        self.expect("OP", Some("{"))?;
        let mut stmts = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError("незакрытый try (нет '}')".into()));
            }
            stmts.push(self.parse_eff()?);
        }
        self.expect("OP", Some("}"))?;
        self.expect("CATCH", None)?;
        let catch_var = self.expect_name()?;
        self.expect("OP", Some("{"))?;
        let mut catch_stmts = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError("незакрытый catch (нет '}')".into()));
            }
            catch_stmts.push(self.parse_eff()?);
        }
        self.expect("OP", Some("}"))?;
        Ok(Eff::TryCatch {
            body: Box::new(Eff::Block {
                stmts,
                line: t.line,
                col: t.col,
            }),
            catch_var,
            catch_body: Box::new(Eff::Block {
                stmts: catch_stmts,
                line: t.line,
                col: t.col,
            }),
            line: t.line,
            col: t.col,
        })
    }

    fn parse_block(&mut self) -> Result<Eff, ParseError> {
        let t = self.expect("OP", Some("{"))?;
        let mut stmts = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError(format!(
                    "незакрытый блок (нет '}}') в {}:{}",
                    t.line, t.col
                )));
            }
            stmts.push(self.parse_eff()?);
            if self.at("OP", Some(";")) {
                self.next();
            }
        }
        self.expect("OP", Some("}"))?;
        Ok(Eff::Block {
            stmts,
            line: t.line,
            col: t.col,
        })
    }

    // --- expressions (pure values) ---
    pub fn parse_expr(&mut self) -> Result<Expr, ParseError> {
        self.parse_or()
    }

    fn parse_or(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_and()?;
        while self.at("OR", None) {
            let t = self.next();
            let right = self.parse_and()?;
            left = Expr::BinOp {
                op: t.text,
                left: Box::new(left),
                right: Box::new(right),
                line: t.line,
                col: t.col,
            };
        }
        Ok(left)
    }

    fn parse_and(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_not()?;
        while self.at("AND", None) {
            let t = self.next();
            let right = self.parse_not()?;
            left = Expr::BinOp {
                op: t.text,
                left: Box::new(left),
                right: Box::new(right),
                line: t.line,
                col: t.col,
            };
        }
        Ok(left)
    }

    fn parse_not(&mut self) -> Result<Expr, ParseError> {
        if self.at("NOT", None) {
            let t = self.next();
            let operand = self.parse_not()?;
            return Ok(Expr::UnaryOp {
                op: t.text,
                operand: Box::new(operand),
                line: t.line,
                col: t.col,
            });
        }
        self.parse_cmp()
    }

    fn parse_cmp(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_add()?;
        while self.at("OP", None)
            && matches!(
                self.peek().text.as_str(),
                "==" | "!=" | "<" | ">" | "<=" | ">="
            )
        {
            let t = self.next();
            let right = self.parse_add()?;
            left = Expr::BinOp {
                op: t.text,
                left: Box::new(left),
                right: Box::new(right),
                line: t.line,
                col: t.col,
            };
        }
        Ok(left)
    }

    fn parse_add(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_mul()?;
        while self.at("OP", None) && matches!(self.peek().text.as_str(), "+" | "-") {
            let t = self.next();
            let right = self.parse_mul()?;
            left = Expr::BinOp {
                op: t.text,
                left: Box::new(left),
                right: Box::new(right),
                line: t.line,
                col: t.col,
            };
        }
        Ok(left)
    }

    fn parse_mul(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_unary()?;
        while self.at("OP", None) && matches!(self.peek().text.as_str(), "*" | "/") {
            let t = self.next();
            let right = self.parse_unary()?;
            left = Expr::BinOp {
                op: t.text,
                left: Box::new(left),
                right: Box::new(right),
                line: t.line,
                col: t.col,
            };
        }
        Ok(left)
    }

    fn parse_unary(&mut self) -> Result<Expr, ParseError> {
        if self.at("OP", Some("-")) {
            let t = self.next();
            let operand = self.parse_unary()?;
            return Ok(Expr::UnaryOp {
                op: t.text,
                operand: Box::new(operand),
                line: t.line,
                col: t.col,
            });
        }
        self.parse_postfix()
    }

    fn parse_postfix(&mut self) -> Result<Expr, ParseError> {
        let mut node = self.parse_primary()?;
        loop {
            if self.at("OP", Some(".")) {
                self.next();
                let attr = self.expect_name()?;
                let (line, col) = node.pos();
                node = Expr::GetAttr {
                    obj: Box::new(node),
                    attr,
                    line,
                    col,
                };
            } else if self.at("OP", Some("[")) {
                self.next();
                let key = self.parse_expr()?;
                self.expect("OP", Some("]"))?;
                let (line, col) = node.pos();
                node = Expr::Index {
                    obj: Box::new(node),
                    key: Box::new(key),
                    line,
                    col,
                };
            } else if self.at("OP", Some("(")) {
                self.next();
                let mut args = Vec::new();
                if !self.at("OP", Some(")")) {
                    args.push(self.parse_expr()?);
                    while self.at("OP", Some(",")) {
                        self.next();
                        args.push(self.parse_expr()?);
                    }
                }
                self.expect("OP", Some(")"))?;
                let (line, col) = node.pos();
                node = Expr::Call {
                    func: Box::new(node),
                    args,
                    line,
                    col,
                };
            } else {
                break;
            }
        }
        Ok(node)
    }

    fn parse_primary(&mut self) -> Result<Expr, ParseError> {
        let t = self.peek().clone();
        match t.kind.as_str() {
            "MATCH" => self.parse_match(),
            "INT" => {
                self.next();
                Ok(Expr::Int {
                    value: t.text.parse().map_err(|_| {
                        ParseError(format!("плохое число {:?} в {}:{}", t.text, t.line, t.col))
                    })?,
                    line: t.line,
                    col: t.col,
                })
            }
            "FLOAT" => {
                self.next();
                Ok(Expr::Float {
                    value: t.text.parse().map_err(|_| {
                        ParseError(format!("плохое число {:?} в {}:{}", t.text, t.line, t.col))
                    })?,
                    line: t.line,
                    col: t.col,
                })
            }
            "STR" => {
                self.next();
                Ok(Expr::Str {
                    value: t.text,
                    line: t.line,
                    col: t.col,
                })
            }
            "NAME" => {
                self.next();
                Ok(Expr::Name {
                    value: t.text,
                    ann: None,
                    line: t.line,
                    col: t.col,
                })
            }
            "FUN" => self.parse_fun(),
            "OP" if t.text == "(" => {
                self.next();
                if self.at("OP", Some(")")) {
                    self.next();
                    return Ok(Expr::Tuple {
                        items: vec![],
                        line: t.line,
                        col: t.col,
                    });
                }
                let first = self.parse_tuple_item()?;
                if self.at("OP", Some(",")) {
                    let mut items = vec![first];
                    while self.at("OP", Some(",")) {
                        self.next();
                        if self.at("OP", Some(")")) {
                            break;
                        }
                        items.push(self.parse_tuple_item()?);
                    }
                    self.expect("OP", Some(")"))?;
                    return Ok(Expr::Tuple {
                        items,
                        line: t.line,
                        col: t.col,
                    });
                }
                self.expect("OP", Some(")"))?;
                Ok(first) // plain parentheses
            }
            "OP" if t.text == "[" => {
                self.next();
                let mut items = Vec::new();
                if !self.at("OP", Some("]")) {
                    items.push(self.parse_expr()?);
                    while self.at("OP", Some(",")) {
                        self.next();
                        items.push(self.parse_expr()?);
                    }
                }
                self.expect("OP", Some("]"))?;
                Ok(Expr::List {
                    items,
                    line: t.line,
                    col: t.col,
                })
            }
            _ => Err(ParseError(format!(
                "неожиданный токен {} {} в {}:{}",
                t.kind,
                py_quote(&t.text),
                t.line,
                t.col
            ))),
        }
    }

    fn parse_tuple_item(&mut self) -> Result<Expr, ParseError> {
        if self.at("NAME", None) && self.peek2_is_colon_type() {
            return self.parse_annotated_name();
        }
        self.parse_expr()
    }

    fn parse_fun(&mut self) -> Result<Expr, ParseError> {
        let t = self.expect("FUN", None)?;
        self.expect("OP", Some("("))?;
        let (mut params, mut param_anns) = (Vec::new(), Vec::new());
        if !self.at("OP", Some(")")) {
            let (nm, ann) = self.parse_param()?;
            params.push(nm);
            param_anns.push(ann);
            while self.at("OP", Some(",")) {
                self.next();
                let (nm, ann) = self.parse_param()?;
                params.push(nm);
                param_anns.push(ann);
            }
        }
        self.expect("OP", Some(")"))?;
        let mut ret_ann = None;
        if self.at("OP", Some("->")) {
            self.next();
            ret_ann = Some(self.parse_type_expr()?);
        }
        self.expect("OP", Some("=>"))?;
        let body = self.parse_expr()?;
        Ok(Expr::Fun {
            params,
            body: Box::new(body),
            param_anns,
            ret_ann,
            line: t.line,
            col: t.col,
        })
    }

    fn parse_param(&mut self) -> Result<(String, Option<TypeExpr>), ParseError> {
        if self.peek2_is_colon_type() {
            let name = self.expect_name()?;
            self.next(); // ':'
            let ann = self.parse_type_expr()?;
            return Ok((name, Some(ann)));
        }
        Ok((self.expect_name()?, None))
    }

    // --- match expression (ADT / value dispatch) ---
    fn parse_match(&mut self) -> Result<Expr, ParseError> {
        let t = self.next(); // MATCH
        let scrut = self.parse_expr()?;
        self.expect("OP", Some("{"))?;
        let mut cases = Vec::new();
        while !self.at("OP", Some("}")) {
            if self.at("EOF", None) {
                return Err(ParseError("незакрытый match (нет '}')".into()));
            }
            cases.push(self.parse_match_case()?);
        }
        self.expect("OP", Some("}"))?;
        Ok(Expr::Match {
            scrut: Box::new(scrut),
            cases,
            line: t.line,
            col: t.col,
        })
    }

    fn parse_match_case(&mut self) -> Result<MatchCase, ParseError> {
        let pat = self.parse_match_pat()?;
        self.expect("OP", Some("=>"))?;
        let body = self.parse_expr()?;
        if self.at("OP", Some(";")) {
            self.next();
        }
        let (line, col) = pat.pos();
        Ok(MatchCase {
            pat,
            body,
            line,
            col,
        })
    }

    fn parse_match_pat(&mut self) -> Result<Expr, ParseError> {
        let t = self.peek().clone();
        if t.kind == "NAME" && t.text == "_" {
            self.next();
            return Ok(Expr::Name {
                value: "_".into(),
                ann: None,
                line: t.line,
                col: t.col,
            });
        }
        if t.kind == "NAME" {
            self.next();
            if self.at("OP", Some("(")) {
                self.next();
                let mut items = vec![Expr::Name {
                    value: t.text,
                    ann: None,
                    line: t.line,
                    col: t.col,
                }];
                if !self.at("OP", Some(")")) {
                    items.push(self.parse_annotated_name()?);
                }
                while self.at("OP", Some(",")) {
                    self.next();
                    items.push(self.parse_annotated_name()?);
                }
                self.expect("OP", Some(")"))?;
                return Ok(Expr::Tuple {
                    items,
                    line: t.line,
                    col: t.col,
                });
            }
            return Ok(Expr::Name {
                value: t.text,
                ann: None,
                line: t.line,
                col: t.col,
            });
        }
        Err(ParseError(format!(
            "ожидался паттерн match, получен {} {}",
            t.kind,
            py_quote(&t.text)
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_full_rule() {
        let src = r#"rule greet = when boot => emit hello;"#;
        let ast = parse(src, "t").unwrap();
        assert_eq!(ast.len(), 1);
        match &ast[0] {
            Decl::Rule(r) => {
                assert_eq!(r.name, "greet");
                assert!(matches!(r.pat, Expr::Name { ref value, .. } if value == "boot"));
                assert!(matches!(r.body, Eff::Emit { .. }));
            }
            _ => panic!("expected rule"),
        }
    }

    #[test]
    fn parses_nested_lib_and_precedence() {
        let src = "lib M { rule r = when boot => seq(emit 1 + 2 * 3, par(emit 4, emit 5)); }";
        let ast = parse(src, "t").unwrap();
        let Decl::Lib(l) = &ast[0] else { panic!() };
        assert_eq!(l.name, "M");
        assert_eq!(l.decls.len(), 1);
    }

    #[test]
    fn parses_annotations_and_match() {
        let src = "rule r = when boot => {\n x: Int := 1;\n y := match (Circle(2.0)) { Circle(v) => v; _ => 0.0 };\n }";
        let ast = parse(src, "t").unwrap();
        assert_eq!(ast.len(), 1);
    }

    #[test]
    fn error_has_position() {
        let e = parse("rule = when boot => emit 1;", "f").unwrap_err();
        assert!(e.0.contains("в 1:6"), "{}", e.0);
    }
}
