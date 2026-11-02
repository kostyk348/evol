//! EVOL -> Python transpiler (same output as the original compiler.py).
//!
//! Generates a self-contained Python script implementing δ(S) -> S'.

use crate::ast::TypeExpr;
use crate::ast::*;

pub struct Compiler {
    indent: usize,
    lines: Vec<String>,
    rule_counter: usize,
    closure_params: Vec<String>,
}

impl Default for Compiler {
    fn default() -> Self {
        Self::new()
    }
}

fn render_ann(ann: &TypeExpr) -> String {
    match ann {
        TypeExpr::TyCon { name, .. } => name.clone(),
        TypeExpr::TyList { elem, .. } => format!("List[{}]", render_ann(elem)),
    }
}

impl Compiler {
    pub fn new() -> Compiler {
        Compiler {
            indent: 0,
            lines: Vec::new(),
            rule_counter: 0,
            closure_params: Vec::new(),
        }
    }

    fn emit(&mut self, line: &str) {
        self.lines
            .push(format!("{}{}", "    ".repeat(self.indent), line));
    }

    pub fn compile(mut self, ast: &[Decl]) -> String {
        self.emit("# Auto-generated from EVOL — do not edit");
        self.emit("import random as _random");
        self.emit("import os as _os");
        self.emit("_noop = lambda *a: None");
        self.emit("");
        self.emit("store = {}");
        self.emit("queue = []");
        self.emit("rules = []");
        self.emit("_sim_step = 0");
        self.emit("");

        for decl in ast {
            if let Decl::Lib(l) = decl {
                self.compile_lib(l);
            }
        }

        self.emit("");
        self.emit("def match_tag(msg, tag):");
        self.emit("    if isinstance(msg, tuple) and len(msg) > 0:");
        self.emit("        return getattr(msg[0], 'name', msg[0]) == tag");
        self.emit("    if isinstance(msg, str):");
        self.emit("        return msg == tag");
        self.emit("    return False");
        self.emit("");
        self.emit("def match_tuple(msg, tag, n):");
        self.emit("    if not isinstance(msg, tuple) or len(msg) < n + 1:");
        self.emit("        return None");
        self.emit("    t = getattr(msg[0], 'name', msg[0]) if hasattr(msg[0], 'name') else msg[0]");
        self.emit("    if t != tag:");
        self.emit("        return None");
        self.emit("    return msg[1:n+1]");
        self.emit("");

        self.emit("def dispatch(msg):");
        self.emit("    global _sim_step");
        self.emit("    _sim_step += 1");
        self.emit("    for rule_fn in rules:");
        self.emit("        result = rule_fn(msg)");
        self.emit("        if result is not None:");
        self.emit("            return");
        self.emit("");

        self.emit("def run_evol(bootstrap):");
        self.emit("    global store, queue");
        self.emit("    store = {}");
        self.emit("    queue = list(bootstrap)");
        self.emit("    _sim_step = 0");
        self.emit("    while queue:");
        self.emit("        msg = queue.pop(0)");
        self.emit("        dispatch(msg)");
        self.emit("");

        self.emit("if __name__ == '__main__':");
        self.indent = 1;
        self.emit("run_evol(['boot'])");
        self.emit("print('Store:', store)");
        self.emit("print('Steps:', _sim_step)");
        self.indent = 0;

        self.lines.join("\n")
    }

    fn compile_lib(&mut self, lib: &Lib) {
        for decl in &lib.decls {
            if let Decl::Rule(r) = decl {
                self.compile_rule(&lib.name, r);
            }
        }
    }

    fn compile_rule(&mut self, lib_name: &str, rule: &Rule) {
        self.rule_counter += 1;
        let fn_name = format!("rule_{}_{}_{}", lib_name, rule.name, self.rule_counter);
        let pat = &rule.pat;

        self.emit(&format!("def {fn_name}(msg):"));
        self.indent = 1;

        match pat {
            Expr::Name { value: tag, .. } => {
                self.emit(&format!("    if not match_tag(msg, '{tag}'):"));
                self.emit("        return None");
            }
            Expr::Tuple { items, .. } if !items.is_empty() => {
                if let Expr::Name { value: tag, .. } = &items[0] {
                    let n = items.len() - 1;
                    if n == 0 {
                        self.emit(&format!("    if not match_tag(msg, '{tag}'):"));
                        self.emit("        return None");
                    } else {
                        let bindings: Vec<String> = (0..n).map(|i| format!("v{i}")).collect();
                        self.emit(&format!("    _b = match_tuple(msg, '{tag}', {n})"));
                        self.emit("    if _b is None:");
                        self.emit("        return None");
                        for (i, bn) in bindings.iter().enumerate() {
                            self.emit(&format!("    {bn} = _b[{i}]"));
                        }
                    }
                }
            }
            _ => {}
        }

        self.compile_eff(&rule.body);
        self.emit("    return True");
        self.indent = 0;
        self.emit("");
        self.emit(&format!("rules.append({fn_name})"));
        self.emit("");
    }

    fn compile_eff(&mut self, eff: &Eff) {
        match eff {
            Eff::Block { stmts, .. } => {
                for stmt in stmts {
                    self.compile_eff(stmt);
                }
            }
            Eff::Seq { a, b, .. } => {
                self.compile_eff(a);
                self.compile_eff(b);
            }
            Eff::Assign {
                name, value, ann, ..
            } => {
                if let Expr::Fun { params, body, .. } = value {
                    let fn_name = format!("fun_{}_{}", name, self.rule_counter);
                    self.rule_counter += 1;
                    let params_j = params.join(", ");
                    self.emit(&format!("    def {fn_name}({params_j}):"));
                    self.indent += 1;
                    let saved = std::mem::replace(&mut self.closure_params, params.to_vec());
                    let body_expr = self.compile_expr(body);
                    self.closure_params = saved;
                    self.emit(&format!("    return {body_expr}"));
                    self.indent -= 1;
                    self.emit(&format!("    store['{name}'] = {fn_name}"));
                } else {
                    let val = self.compile_expr(value);
                    let comment = ann
                        .as_ref()
                        .map(|a| format!("  # : {}", render_ann(a)))
                        .unwrap_or_default();
                    self.emit(&format!("    store['{name}'] = {val}{comment}"));
                }
            }
            Eff::Emit { value, .. } => {
                let val = self.compile_expr(value);
                self.emit(&format!("    queue.append({val})"));
            }
            Eff::If {
                cond,
                then_branch,
                else_branch,
                ..
            } => {
                let cond = self.compile_expr(cond);
                self.emit(&format!("    if {cond}:"));
                self.indent += 1;
                self.compile_eff(then_branch);
                self.indent -= 1;
                self.emit("    else:");
                self.indent += 1;
                self.compile_eff(else_branch);
                self.indent -= 1;
            }
            Eff::ForEach {
                var, coll, body, ..
            } => {
                let coll = self.compile_expr(coll);
                self.emit(&format!("    for {var} in {coll}:"));
                self.indent += 1;
                self.compile_eff(body);
                self.indent -= 1;
            }
            Eff::Loop { guard, body, .. } => {
                let guard = self.compile_expr(guard);
                self.emit(&format!("    while {guard}:"));
                self.indent += 1;
                self.compile_eff(body);
                self.indent -= 1;
            }
            Eff::TryCatch {
                body,
                catch_var,
                catch_body,
                ..
            } => {
                self.emit("    try:");
                self.indent += 1;
                self.compile_eff(body);
                self.indent -= 1;
                self.emit(&format!("    except Exception as {catch_var}:"));
                self.indent += 1;
                self.compile_eff(catch_body);
                self.indent -= 1;
            }
            Eff::Raise { message, .. } => {
                let msg = self.compile_expr(message);
                self.emit(&format!("    raise Exception({msg})"));
            }
            Eff::Par { a, b, .. } => {
                self.compile_eff(a);
                self.compile_eff(b);
            }
            Eff::Choice { a, .. } => {
                self.compile_eff(a);
            }
            Eff::Call { call } => {
                let expr = self.compile_expr(call);
                self.emit(&format!("    {expr}"));
            }
            Eff::Spawn { .. } | Eff::Retract { .. } => {}
        }
    }

    fn compile_expr(&mut self, expr: &Expr) -> String {
        match expr {
            Expr::Int { value, .. } => value.to_string(),
            Expr::Float { value, .. } => crate::value::py_float_repr(*value),
            Expr::Str { value, .. } => crate::value::py_str_repr_public(value),
            Expr::Name { value, .. } => {
                if value == "true" || value == "True" {
                    "True".into()
                } else if value == "false" || value == "False" {
                    "False".into()
                } else if self.closure_params.iter().any(|p| p == value) {
                    value.clone()
                } else {
                    format!("store.get('{value}', 0)")
                }
            }
            Expr::List { items, .. } => {
                let items: Vec<String> = items.iter().map(|i| self.compile_expr(i)).collect();
                format!("[{}]", items.join(", "))
            }
            Expr::Tuple { items, .. } => {
                let items: Vec<String> = items.iter().map(|i| self.compile_expr(i)).collect();
                match items.len() {
                    0 => "()".into(),
                    1 => format!("({},)", items[0]),
                    _ => format!("({})", items.join(", ")),
                }
            }
            Expr::BinOp {
                op, left, right, ..
            } => {
                let l = self.compile_expr(left);
                let r = self.compile_expr(right);
                match op.as_str() {
                    "/" => format!("({l} // {r})"),
                    "and" => format!("({l} and {r})"),
                    "or" => format!("({l} or {r})"),
                    _ => format!("({l} {op} {r})"),
                }
            }
            Expr::UnaryOp { op, operand, .. } => {
                let val = self.compile_expr(operand);
                if op == "not" {
                    format!("(not {val})")
                } else {
                    format!("(-{val})")
                }
            }
            Expr::GetAttr { obj, attr, .. } => {
                let obj = self.compile_expr(obj);
                format!("{obj}.{attr}")
            }
            Expr::Call { func, args, .. } => {
                if let Expr::GetAttr { obj, attr, .. } = func.as_ref() {
                    if let Expr::Name { value: module, .. } = obj.as_ref() {
                        let args: Vec<String> = args.iter().map(|a| self.compile_expr(a)).collect();
                        return self.compile_module_call(module, attr, &args.join(", "));
                    }
                }
                if let Expr::Name { value: name, .. } = func.as_ref() {
                    let args: Vec<String> = args.iter().map(|a| self.compile_expr(a)).collect();
                    let args = args.join(", ");
                    match name.as_str() {
                        "range" => return format!("list(range({args}))"),
                        "len" => return format!("len({args})"),
                        "abs" => return format!("abs({args})"),
                        "min" => return format!("min({args})"),
                        "max" => return format!("max({args})"),
                        "str" => return format!("str({args})"),
                        "int" => return format!("int({args})"),
                        "float" => return format!("float({args})"),
                        _ => return format!("store.get('{name}', _noop)({args})"),
                    }
                }
                let f = self.compile_expr(func);
                let args: Vec<String> = args.iter().map(|a| self.compile_expr(a)).collect();
                format!("{f}({})", args.join(", "))
            }
            Expr::Index { obj, key, .. } => {
                let obj = self.compile_expr(obj);
                let key = self.compile_expr(key);
                format!("{obj}[{key}]")
            }
            Expr::Match { .. } | Expr::Fun { .. } => "0  # unsupported".into(),
        }
    }

    fn compile_module_call(&mut self, module: &str, func: &str, args: &str) -> String {
        match module {
            "console" => {
                if func == "print" || func == "println" {
                    return format!("print({args})");
                }
            }
            "random" => match func {
                "int" => return format!("_random.randint({args})"),
                "pick" => return format!("_random.choice({args})"),
                "shuffle" => {
                    return format!("list(_random.sample({args}, len({args})))");
                }
                _ => {}
            },
            "file" => match func {
                "read" => return format!("open({args}, encoding='utf-8').read()"),
                "write" => {
                    let mut it = args.splitn(2, ',');
                    let p = it.next().unwrap_or("");
                    let d = it.next().unwrap_or("").trim();
                    return format!("open({p}, 'w', encoding='utf-8').write({d})");
                }
                "exists" => return format!("(1 if _os.path.exists({args}) else 0)"),
                _ => {}
            },
            "sim" => match func {
                "step" => return "_sim_step".into(),
                "set_seed" => return format!("_random.seed({args})"),
                _ => {}
            },
            _ => {}
        }
        format!("{module}.{func}({args})")
    }
}

/// Transpile a parsed program to Python source.
pub fn compile_evol(ast: &[Decl]) -> String {
    Compiler::new().compile(ast)
}
