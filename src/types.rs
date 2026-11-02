//! EVOL typechecker + light property prover (Phase 4, metric M5).
//!
//! The checker really rejects incorrect programs. Types: Int, Str, Sym, Bool,
//! Float, Unit, List, Tuple, Fun, Top — gradual: unknown sides are skipped.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use crate::ast::*;
use crate::parser;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Type {
    Int,
    Str,
    Sym,
    Bool,
    Float,
    Unit,
    Top,
    List(std::rc::Rc<Type>),
    Tuple(Vec<Type>),
    Fun(Vec<Type>, std::rc::Rc<Type>),
}

impl std::fmt::Display for Type {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Type::Int => write!(f, "Int"),
            Type::Str => write!(f, "Str"),
            Type::Sym => write!(f, "Sym"),
            Type::Bool => write!(f, "Bool"),
            Type::Float => write!(f, "Float"),
            Type::Unit => write!(f, "Unit"),
            Type::Top => write!(f, "Top"),
            Type::List(e) => write!(f, "List[{e}]"),
            Type::Tuple(items) => write!(f, "Tuple[{:?}]", items),
            Type::Fun(args, ret) => write!(f, "Fun[{:?} -> {ret}]", args),
        }
    }
}

/// Annotation AST -> internal Type (unknown name -> Top).
pub fn conv_type(te: Option<&TypeExpr>) -> Type {
    let Some(te) = te else { return Type::Top };
    match te {
        TypeExpr::TyCon { name, .. } => match name.as_str() {
            "Int" => Type::Int,
            "Str" => Type::Str,
            "Bool" => Type::Bool,
            "Float" => Type::Float,
            "Sym" => Type::Sym,
            "Top" => Type::Top,
            "List" => Type::List(std::rc::Rc::new(Type::Top)),
            _ => Type::Top,
        },
        TypeExpr::TyList { elem, .. } => Type::List(std::rc::Rc::new(conv_type(Some(elem)))),
    }
}

fn builtin_type(name: &str) -> Option<Type> {
    match name {
        "range" => Some(Type::Fun(
            vec![Type::Int, Type::Int],
            std::rc::Rc::new(Type::List(std::rc::Rc::new(Type::Int))),
        )),
        "len" => Some(Type::Fun(
            vec![Type::List(std::rc::Rc::new(Type::Top))],
            std::rc::Rc::new(Type::Int),
        )),
        _ => None,
    }
}

fn is_numeric(t: &Type) -> bool {
    matches!(t, Type::Int | Type::Float | Type::Top)
}

/// Subtype: Top is the top type; Int <: Float; lists/tuples elementwise.
pub fn is_subtype(a: &Type, b: &Type) -> bool {
    if a == b {
        return true;
    }
    if *b == Type::Top {
        return true;
    }
    if *a == Type::Top {
        return *b == Type::Top;
    }
    if is_numeric(a) && is_numeric(b) {
        // Int <: Float, Float </: Int
        return !(*a == Type::Float && *b == Type::Int);
    }
    match (a, b) {
        (Type::List(x), Type::List(y)) => is_subtype(x, y),
        (Type::Tuple(xs), Type::Tuple(ys)) => {
            xs.len() == ys.len() && xs.iter().zip(ys).all(|(x, y)| is_subtype(x, y))
        }
        _ => false,
    }
}

fn truthy_type(t: &Type) -> bool {
    matches!(
        t,
        Type::Int | Type::Bool | Type::Sym | Type::List(_) | Type::Tuple(_)
    )
}

/// Python `repr(list_of_str)`: `['a', 'b']`.
fn py_list_repr(items: &[String]) -> String {
    let inner: Vec<String> = items.iter().map(|s| format!("'{s}'")).collect();
    format!("[{}]", inner.join(", "))
}

/// One typechecker error: `line:col message` (positions may be absent).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TcError(pub String);

pub struct TypeChecker {
    pub rule_names: BTreeSet<String>,
    pub errors: Vec<TcError>,
    qualified: BTreeSet<(String, String)>,
    unqualified: BTreeSet<String>,
}

impl TypeChecker {
    pub fn new(rule_names: BTreeSet<String>) -> TypeChecker {
        TypeChecker {
            rule_names,
            errors: Vec::new(),
            qualified: BTreeSet::new(),
            unqualified: BTreeSet::new(),
        }
    }

    fn err(&mut self, pos: (usize, usize), msg: &str) {
        self.errors
            .push(TcError(format!("{}:{} {msg}", pos.0, pos.1)));
    }

    fn check_args(&mut self, pos: (usize, usize), args: &[Type], sig_args: &[Type]) {
        if args.len() != sig_args.len() {
            self.err(
                pos,
                &format!(
                    "арность вызова: ожидалось {}, дано {}",
                    sig_args.len(),
                    args.len()
                ),
            );
            return;
        }
        for (a, pt) in args.iter().zip(sig_args) {
            // gradual typing: only check when both sides are known
            if *a != Type::Top && *pt != Type::Top && !is_subtype(a, pt) {
                self.err(pos, &format!("аргумент {a} не совпадает с параметром {pt}"));
            }
        }
    }

    fn collect_names(&mut self, decls: &[Decl], lib: &str) {
        for d in decls {
            match d {
                Decl::Rule(r) => {
                    self.unqualified.insert(r.name.clone());
                    self.qualified.insert((lib.to_string(), r.name.clone()));
                }
                Decl::Lib(l) => {
                    for sub in &l.decls {
                        if let Decl::Rule(r) = sub {
                            self.unqualified.insert(r.name.clone());
                            self.qualified.insert((l.name.clone(), r.name.clone()));
                        }
                    }
                }
                Decl::Import(im) if im.is_path => {
                    if let Ok(src) = std::fs::read_to_string(&im.target) {
                        if let Ok(sub_ast) = parser::parse(&src, &im.target) {
                            let stem = std::path::Path::new(&im.target)
                                .file_stem()
                                .map(|s| s.to_string_lossy().into_owned())
                                .unwrap_or_default();
                            self.collect_names(&sub_ast, &stem);
                        }
                    }
                }
                _ => {}
            }
        }
    }

    pub fn check_program(&mut self, decls: &[Decl]) {
        self.qualified.clear();
        self.unqualified.clear();
        self.collect_names(decls, "");
        for d in decls {
            match d {
                Decl::Rule(r) => self.check_rule(r),
                Decl::Lib(l) => {
                    let sub: Vec<Decl> = l.decls.clone();
                    // Python recurses without touching the rule-name set
                    let saved_q = self.qualified.clone();
                    let saved_u = self.unqualified.clone();
                    self.collect_names(&sub, &l.name);
                    for sd in &sub {
                        if let Decl::Rule(sr) = sd {
                            self.check_rule(sr);
                        }
                    }
                    self.qualified = saved_q;
                    self.unqualified = saved_u;
                    let _ = self.unqualified.contains("");
                }
                _ => {}
            }
        }
    }

    fn bind_pattern(&self, pat: &Expr, env: &mut HashMap<String, Type>) {
        if let Expr::Tuple { items, .. } = pat {
            for item in items.iter().skip(1) {
                if let Expr::Name { value, ann, .. } = item {
                    env.insert(value.clone(), conv_type(ann.as_ref()));
                }
            }
        }
    }

    fn bind_match_pattern(&self, pat: &Expr, env: &mut HashMap<String, Type>) {
        match pat {
            Expr::Name { value, .. } if value != "_" => {
                env.insert(value.clone(), Type::Top);
            }
            Expr::Tuple { items, .. } if !items.is_empty() => {
                for item in items.iter().skip(1) {
                    if let Expr::Name { value, .. } = item {
                        if value != "_" {
                            env.insert(value.clone(), Type::Top);
                        }
                    }
                }
            }
            _ => {}
        }
    }

    fn check_rule(&mut self, rule: &Rule) {
        let mut env = HashMap::new();
        self.bind_pattern(&rule.pat, &mut env);
        self.check_eff(&rule.body, &mut env);
    }

    fn infer(&mut self, expr: &Expr, env: &mut HashMap<String, Type>) -> Type {
        match expr {
            Expr::Int { .. } => Type::Int,
            Expr::Float { .. } => Type::Float,
            Expr::Str { .. } => Type::Str,
            Expr::Name { value, .. } => env.get(value).cloned().unwrap_or(Type::Sym), // unbound name -> symbol
            Expr::List { items, .. } => {
                let mut elem = Type::Top;
                for i in items {
                    elem = self.infer(i, env); // last element wins (as in the original)
                }
                Type::List(std::rc::Rc::new(elem))
            }
            Expr::Tuple { items, .. } => {
                Type::Tuple(items.iter().map(|i| self.infer(i, env)).collect())
            }
            Expr::Fun {
                params,
                body,
                param_anns,
                ret_ann,
                ..
            } => {
                let mut local = env.clone();
                let mut pts = Vec::new();
                for (p, ann) in params.iter().zip(param_anns) {
                    let pt = conv_type(ann.as_ref());
                    local.insert(p.clone(), pt.clone());
                    pts.push(pt);
                }
                let ret = self.infer(body, &mut local);
                if let Some(ra) = ret_ann {
                    let expected = conv_type(Some(ra));
                    if !is_subtype(&ret, &expected) {
                        self.err(
                            expr.pos(),
                            &format!("тип результата функции {ret} не совпадает с {expected}"),
                        );
                    }
                }
                Type::Fun(pts, std::rc::Rc::new(ret))
            }
            Expr::UnaryOp { op, operand, .. } => {
                let v = self.infer(operand, env);
                match op.as_str() {
                    "-" => {
                        if v != Type::Int {
                            self.err(expr.pos(), &format!("'-' применим к Int, получен {v}"));
                        }
                        Type::Int
                    }
                    "not" => {
                        if !truthy_type(&v) {
                            self.err(
                                expr.pos(),
                                &format!("'not' применим к логическому, получен {v}"),
                            );
                        }
                        Type::Bool
                    }
                    _ => Type::Top,
                }
            }
            Expr::BinOp {
                op, left, right, ..
            } => self.infer_binop(op, left, right, env, expr.pos()),
            Expr::GetAttr { obj, attr, .. } => {
                let o = self.infer(obj, env);
                if attr == "kind" {
                    if matches!(o, Type::Sym | Type::Tuple(_)) {
                        return Type::Sym;
                    }
                    self.err(expr.pos(), &format!(".kind от {o}"));
                    return Type::Top;
                }
                if let Expr::Name { value, .. } = obj.as_ref() {
                    if crate::interp::MODULE_NAMES.contains(&value.as_str()) {
                        return Type::Top; // stdlib module attribute
                    }
                }
                self.err(expr.pos(), &format!("неизвестный атрибут .{attr}"));
                Type::Top
            }
            Expr::Index { obj, key, .. } => {
                let o = self.infer(obj, env);
                self.infer(key, env);
                match &o {
                    Type::List(elem) => (**elem).clone(),
                    Type::Tuple(_) => Type::Top,
                    _ => {
                        self.err(expr.pos(), &format!("индексация от {o}"));
                        Type::Top
                    }
                }
            }
            Expr::Call { func, args, .. } => {
                if let Expr::Name { value, .. } = func.as_ref() {
                    if let Some(sig) = builtin_type(value) {
                        let targs: Vec<Type> = args.iter().map(|a| self.infer(a, env)).collect();
                        let Type::Fun(sargs, ret) = sig else {
                            unreachable!()
                        };
                        self.check_args(expr.pos(), &targs, &sargs);
                        return (*ret).clone();
                    }
                    if value.chars().next().is_some_and(|c| c.is_uppercase()) {
                        // ADT constructor: dynamic type
                        for a in args {
                            self.infer(a, env);
                        }
                        return Type::Top;
                    }
                }
                if let Expr::GetAttr { obj, .. } = func.as_ref() {
                    if let Expr::Name { value, .. } = obj.as_ref() {
                        if crate::interp::MODULE_NAMES.contains(&value.as_str()) {
                            for a in args {
                                self.infer(a, env);
                            }
                            return Type::Top; // stdlib call: dynamic
                        }
                    }
                }
                let f = self.infer(func, env);
                let targs: Vec<Type> = args.iter().map(|a| self.infer(a, env)).collect();
                if let Type::Fun(fargs, ret) = &f {
                    self.check_args(expr.pos(), &targs, fargs);
                    return (**ret).clone();
                }
                self.err(expr.pos(), &format!("вызов не-функции: {f}"));
                Type::Top
            }
            Expr::Match { scrut, cases, .. } => {
                self.infer(scrut, env);
                for case in cases {
                    let mut local = env.clone();
                    self.bind_match_pattern(&case.pat, &mut local);
                    self.infer(&case.body, &mut local);
                }
                Type::Top
            }
        }
    }

    fn infer_binop(
        &mut self,
        op: &str,
        left: &Expr,
        right: &Expr,
        env: &mut HashMap<String, Type>,
        pos: (usize, usize),
    ) -> Type {
        let l = self.infer(left, env);
        let r = self.infer(right, env);
        match op {
            "+" | "-" | "*" | "/" => {
                if !(is_numeric(&l) && is_numeric(&r)) {
                    self.err(
                        pos,
                        &format!("арифметика требует числовой тип, получено {l} {op} {r}"),
                    );
                }
                if l == Type::Float || r == Type::Float {
                    Type::Float
                } else {
                    Type::Int
                }
            }
            "==" | "!=" | "<" | ">" | "<=" | ">=" => {
                if !(is_subtype(&l, &r) || is_subtype(&r, &l) || is_numeric(&l) && is_numeric(&r)) {
                    self.err(pos, &format!("сравнение несопоставимых: {l} {op} {r}"));
                }
                Type::Bool
            }
            "and" | "or" => {
                if !(truthy_type(&l) && truthy_type(&r)) {
                    self.err(
                        pos,
                        &format!("логика требует логический тип, получено {l} {op} {r}"),
                    );
                }
                Type::Bool
            }
            _ => {
                self.err(pos, &format!("неизвестный оператор {op}"));
                Type::Top
            }
        }
    }

    fn check_eff(&mut self, node: &Eff, env: &mut HashMap<String, Type>) {
        match node {
            Eff::Block { stmts, .. } => {
                for s in stmts {
                    self.check_eff(s, env);
                }
            }
            Eff::Assign {
                name, value, ann, ..
            } => {
                let v = self.infer(value, env);
                if let Some(ann) = ann {
                    let expected = conv_type(Some(ann));
                    if !is_subtype(&v, &expected) {
                        self.err(
                            node.pos(),
                            &format!("присваивание '{name}': ожидался {expected}, получен {v}"),
                        );
                    }
                    env.insert(name.clone(), expected);
                } else {
                    env.insert(name.clone(), v);
                }
            }
            Eff::Emit { value, .. } => {
                self.infer(value, env);
            }
            Eff::Spawn { lib, name, .. } => {
                if let Some(lib) = lib {
                    if !self.qualified.contains(&(lib.clone(), name.clone())) {
                        self.err(
                            node.pos(),
                            &format!("spawn несуществующего правила '{lib}.{name}'"),
                        );
                    }
                } else if !self.unqualified.contains(name) {
                    self.err(
                        node.pos(),
                        &format!("spawn несуществующего правила '{name}'"),
                    );
                }
            }
            Eff::Retract { name, .. } => {
                if !self.rule_names.contains(name) {
                    self.err(
                        node.pos(),
                        &format!("retract несуществующего правила '{name}'"),
                    );
                }
            }
            Eff::If {
                cond,
                then_branch,
                else_branch,
                ..
            } => {
                let c = self.infer(cond, env);
                if !truthy_type(&c) {
                    self.err(node.pos(), &format!("условие if не логического типа: {c}"));
                }
                self.check_eff(then_branch, env);
                self.check_eff(else_branch, env);
            }
            Eff::Seq { a, b, .. } | Eff::Par { a, b, .. } | Eff::Choice { a, b, .. } => {
                self.check_eff(a, env);
                self.check_eff(b, env);
            }
            Eff::Loop { guard, body, .. } => {
                let g = self.infer(guard, env);
                if !truthy_type(&g) {
                    self.err(node.pos(), &format!("guard цикла не логического типа: {g}"));
                }
                self.check_eff(body, env);
            }
            Eff::ForEach {
                var, coll, body, ..
            } => {
                let c = self.infer(coll, env);
                if let Type::List(elem) = &c {
                    let mut local = env.clone();
                    local.insert(var.clone(), (**elem).clone());
                    self.check_eff(body, &mut local);
                } else {
                    self.err(node.pos(), &format!("forall: коллекция не список: {c}"));
                    let mut local = env.clone();
                    local.insert(var.clone(), Type::Top);
                    self.check_eff(body, &mut local);
                }
            }
            Eff::Call { call } => {
                self.infer(call, env);
            }
            Eff::TryCatch {
                body, catch_body, ..
            } => {
                self.check_eff(body, env);
                self.check_eff(catch_body, env);
            }
            Eff::Raise { message, .. } => {
                self.infer(message, env);
            }
        }
    }
}

/// Run only the typechecker: list of errors.
pub fn typecheck(decls: &[Decl]) -> Vec<TcError> {
    let facts = collect_facts(decls);
    let mut tc = TypeChecker::new(facts.rules);
    tc.check_program(decls);
    tc.errors
}

// ------------------------------------------------- property prover (metric 5)

#[derive(Default)]
pub struct Facts {
    pub rules: BTreeSet<String>,
    pub qualified: BTreeSet<(String, String)>,
    pub when_tags: BTreeSet<String>,
    pub emit_tags: BTreeSet<String>,
    pub spawns: BTreeSet<(String, String)>,
    pub retracts: BTreeSet<String>,
    pub edges: BTreeMap<String, Vec<String>>,
    pub tag_count: BTreeMap<String, u64>,
    pub rule_tag: BTreeMap<String, String>,
    pub enums: BTreeMap<String, BTreeMap<String, usize>>,
    pub variant_arity: BTreeMap<String, usize>,
    pub matches: Vec<Expr>,
    pub ctors: Vec<(String, usize)>,
}

fn scan_eff(node: &Eff, facts: &mut Facts) {
    match node {
        Eff::Spawn { lib, name, .. } => {
            facts
                .spawns
                .insert((lib.clone().unwrap_or_default(), name.clone()));
        }
        Eff::Retract { name, .. } => {
            facts.retracts.insert(name.clone());
        }
        Eff::Block { stmts, .. } => {
            for s in stmts {
                scan_eff(s, facts);
            }
        }
        Eff::Seq { a, b, .. } | Eff::Par { a, b, .. } | Eff::Choice { a, b, .. } => {
            scan_eff(a, facts);
            scan_eff(b, facts);
        }
        Eff::Loop { body, .. } | Eff::ForEach { body, .. } => scan_eff(body, facts),
        Eff::If {
            then_branch,
            else_branch,
            ..
        } => {
            scan_eff(then_branch, facts);
            scan_eff(else_branch, facts);
        }
        Eff::TryCatch {
            body, catch_body, ..
        } => {
            scan_eff(body, facts);
            scan_eff(catch_body, facts);
        }
        Eff::Raise { .. } => {}
        _ => {}
    }
}

fn emitted_tags(node: &Eff, out: &mut Vec<String>) {
    match node {
        Eff::Block { stmts, .. } => {
            for s in stmts {
                emitted_tags(s, out);
            }
        }
        Eff::Emit { value, .. } => {
            if let Some(tag) = value.pattern_tag() {
                out.push(tag);
            }
        }
        Eff::Seq { a, b, .. } | Eff::Par { a, b, .. } | Eff::Choice { a, b, .. } => {
            emitted_tags(a, out);
            emitted_tags(b, out);
        }
        Eff::Loop { body, .. } | Eff::ForEach { body, .. } => emitted_tags(body, out),
        Eff::If {
            then_branch,
            else_branch,
            ..
        } => {
            emitted_tags(then_branch, out);
            emitted_tags(else_branch, out);
        }
        _ => {}
    }
}

fn collect_facts(decls: &[Decl]) -> Facts {
    let mut facts = Facts::default();
    fn walk(decls: &[Decl], facts: &mut Facts) {
        for d in decls {
            match d {
                Decl::Rule(r) => {
                    facts.rules.insert(r.name.clone());
                    facts.qualified.insert((String::new(), r.name.clone()));
                    if let Some(tag) = r.pat.pattern_tag() {
                        facts.when_tags.insert(tag.clone());
                        *facts.tag_count.entry(tag.clone()).or_insert(0) += 1;
                        facts.rule_tag.insert(r.name.clone(), tag);
                    }
                    let mut etags = Vec::new();
                    emitted_tags(&r.body, &mut etags);
                    for tg in &etags {
                        facts.emit_tags.insert(tg.clone());
                    }
                    facts.edges.insert(r.name.clone(), etags);
                    scan_eff(&r.body, facts);
                }
                Decl::Lib(l) => {
                    for sub in &l.decls {
                        if let Decl::Rule(sr) = sub {
                            facts.rules.insert(sr.name.clone());
                            facts.qualified.insert((l.name.clone(), sr.name.clone()));
                            if let Some(tag) = sr.pat.pattern_tag() {
                                facts.when_tags.insert(tag.clone());
                                *facts.tag_count.entry(tag.clone()).or_insert(0) += 1;
                                facts
                                    .rule_tag
                                    .insert(format!("('{}', '{}')", l.name, sr.name), tag);
                            }
                            let mut etags = Vec::new();
                            emitted_tags(&sr.body, &mut etags);
                            for tg in &etags {
                                facts.emit_tags.insert(tg.clone());
                            }
                            facts
                                .edges
                                .insert(format!("('{}', '{}')", l.name, sr.name), etags);
                            scan_eff(&sr.body, facts);
                        } else if let Decl::EnumDecl(ed) = sub {
                            let mut vars = BTreeMap::new();
                            for v in &ed.variants {
                                vars.insert(v.tag.clone(), v.fields.len());
                                facts.variant_arity.insert(v.tag.clone(), v.fields.len());
                            }
                            facts.enums.insert(ed.name.clone(), vars);
                        }
                    }
                }
                Decl::EnumDecl(ed) => {
                    let mut vars = BTreeMap::new();
                    for v in &ed.variants {
                        vars.insert(v.tag.clone(), v.fields.len());
                        facts.variant_arity.insert(v.tag.clone(), v.fields.len());
                    }
                    facts.enums.insert(ed.name.clone(), vars);
                }
                _ => {}
            }
        }
    }
    walk(decls, &mut facts);

    // collect match expressions and ADT constructor calls
    fn walk_eff(node: &Eff, facts: &mut Facts) {
        match node {
            Eff::Block { stmts, .. } => {
                for s in stmts {
                    walk_eff(s, facts);
                }
            }
            Eff::Seq { a, b, .. } | Eff::Par { a, b, .. } | Eff::Choice { a, b, .. } => {
                walk_eff(a, facts);
                walk_eff(b, facts);
            }
            Eff::Loop { body, .. } | Eff::ForEach { body, .. } => walk_eff(body, facts),
            Eff::If {
                then_branch,
                else_branch,
                ..
            } => {
                walk_eff(then_branch, facts);
                walk_eff(else_branch, facts);
            }
            Eff::TryCatch {
                body, catch_body, ..
            } => {
                walk_eff(body, facts);
                walk_eff(catch_body, facts);
            }
            Eff::Assign { value, .. }
            | Eff::Emit { value, .. }
            | Eff::Raise { message: value, .. } => {
                walk_expr(value, facts);
            }
            Eff::Call { call } => walk_expr(call, facts),
            _ => {}
        }
    }
    fn walk_expr(node: &Expr, facts: &mut Facts) {
        if let Expr::Match { .. } = node {
            facts.matches.push(node.clone());
        }
        match node {
            Expr::List { items, .. } | Expr::Tuple { items, .. } => {
                for i in items {
                    walk_expr(i, facts);
                }
            }
            Expr::BinOp { left, right, .. } => {
                walk_expr(left, facts);
                walk_expr(right, facts);
            }
            Expr::UnaryOp { operand, .. } => walk_expr(operand, facts),
            Expr::Call { func, args, .. } => {
                if let Expr::Name { value, .. } = func.as_ref() {
                    if value.chars().next().is_some_and(|c| c.is_uppercase()) {
                        facts.ctors.push((value.clone(), args.len()));
                    }
                }
                walk_expr(func, facts);
                for a in args {
                    walk_expr(a, facts);
                }
            }
            Expr::GetAttr { obj, .. } => walk_expr(obj, facts),
            Expr::Fun { body, .. } => walk_expr(body, facts),
            _ => {}
        }
    }
    for d in decls {
        match d {
            Decl::Rule(r) => walk_eff(&r.body, &mut facts),
            Decl::Lib(l) => {
                for sub in &l.decls {
                    if let Decl::Rule(sr) = sub {
                        walk_eff(&sr.body, &mut facts);
                    }
                }
            }
            _ => {}
        }
    }
    facts
}

fn spawn_resolves(key: &(String, String), facts: &Facts) -> bool {
    let (lib, name) = key;
    if !lib.is_empty() {
        facts.qualified.contains(key)
    } else {
        facts.rules.contains(name)
    }
}

/// Proven properties (M5): returns (proven, failed) — human-readable strings.
pub fn proven_properties(decls: &[Decl]) -> (Vec<String>, Vec<String>) {
    let facts0 = collect_facts(decls);
    let mut tc = TypeChecker::new(facts0.rules);
    tc.check_program(decls);
    let type_ok = tc.errors.is_empty();

    let facts = collect_facts(decls);
    let mut proven = Vec::new();
    let mut failed = Vec::new();

    // P1: every spawn points to a declared rule
    if facts.spawns.iter().all(|s| spawn_resolves(s, &facts)) {
        proven.push("все spawn -> объявленные правила".into());
    } else {
        failed.push("spawn несуществующего правила".into());
    }

    // P2: every retract points to a declared rule
    if facts.retracts.iter().all(|r| facts.rules.contains(r)) {
        proven.push("все retract -> объявленные правила".into());
    } else {
        failed.push("retract несуществующего правила".into());
    }

    // P3: typing passes without errors
    if type_ok {
        proven.push("программа типобезопасна (без ошибок тайпчекера)".into());
    } else {
        failed.push("ошибки типизации".into());
    }

    // P4: reachability — from rules whose when-tag is 'boot' via emit edges
    let starts: Vec<String> = facts
        .rule_tag
        .iter()
        .filter(|(_, tag)| tag.as_str() == "boot")
        .map(|(name, _)| name.clone())
        .collect();
    let mut reachable = BTreeSet::new();
    if !starts.is_empty() {
        let mut tag_to_rules: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
        for (name, tag) in &facts.rule_tag {
            tag_to_rules.entry(tag.as_str()).or_default().push(name);
        }
        let mut stack = starts.clone();
        while let Some(cur) = stack.pop() {
            if !reachable.insert(cur.clone()) {
                continue;
            }
            if let Some(edges) = facts.edges.get(&cur) {
                for tg in edges {
                    if let Some(rns) = tag_to_rules.get(tg.as_str()) {
                        for rn in rns {
                            if !reachable.contains(*rn) {
                                stack.push((*rn).to_string());
                            }
                        }
                    }
                }
            }
        }
        let dead: Vec<String> = facts
            .rule_tag
            .keys()
            .filter(|k| !reachable.contains(*k))
            .cloned()
            .collect();
        if dead.is_empty() {
            proven.push("все правила достижимы из boot (нет dead-кода)".into());
        } else {
            // keys are already in Python-repr form ('name' or ('lib', 'name'))
            failed.push(format!("недостижимые правила: [{}]", dead.join(", ")));
        }
    } else {
        failed.push("нет правила с when-тегом 'boot' (недостижимость не проверяема)".into());
    }

    // P5: every emitted tag has a when-handler (no guaranteed drops)
    let uncovered: Vec<String> = facts
        .emit_tags
        .difference(&facts.when_tags)
        .cloned()
        .collect();
    if uncovered.is_empty() {
        proven.push("все emit-теги покрыты обработчиком when (нет гарантированного drop)".into());
    } else {
        failed.push(format!(
            "непокрытые emit-теги: {}",
            py_list_repr(&uncovered)
        ));
    }

    // P6: tag determinism — no two rules share a when-tag
    let clashes: Vec<(&String, &u64)> = facts.tag_count.iter().filter(|(_, c)| **c > 1).collect();
    if clashes.is_empty() {
        proven.push("нет конфликта тегов (детерминизм выбора правила)".into());
    } else {
        let inner: Vec<String> = clashes.iter().map(|(t, c)| format!("'{t}': {c}")).collect();
        failed.push(format!("конфликт тегов: {{{}}}", inner.join(", ")));
    }

    // P7: exhaustive pattern-matching over ADTs
    for m in &facts.matches {
        if let Expr::Match { cases, .. } = m {
            let mut tags = BTreeSet::new();
            let mut has_wild = false;
            for c in cases {
                match &c.pat {
                    Expr::Name { value, .. } if value == "_" => has_wild = true,
                    Expr::Name { value, .. } => {
                        tags.insert(value.clone());
                    }
                    Expr::Tuple { items, .. } if !items.is_empty() => {
                        if let Some(Expr::Name { value, .. }) = items.first() {
                            tags.insert(value.clone());
                        }
                    }
                    _ => {}
                }
            }
            for (en, variants) in &facts.enums {
                if tags.iter().any(|t| variants.contains_key(t)) {
                    let missing: Vec<&String> =
                        variants.keys().filter(|v| !tags.contains(*v)).collect();
                    if !missing.is_empty() && !has_wild {
                        let names: Vec<String> = missing.iter().map(|s| s.to_string()).collect();
                        failed.push(format!(
                            "match по enum '{en}': непокрыты варианты {}",
                            py_list_repr(&names)
                        ));
                    } else {
                        proven.push(format!("исчерпывающий match по enum '{en}'"));
                    }
                }
            }
        }
    }

    // P8: ADT constructor arity matches the variant declaration
    let mut ctor_bad = false;
    for (name, argc) in &facts.ctors {
        if let Some(&arity) = facts.variant_arity.get(name) {
            if *argc != arity {
                failed.push(format!(
                    "конструктор {name}({argc} арг.) != вариант ADT ({arity} арг.)"
                ));
                ctor_bad = true;
            }
        }
    }
    if !facts.ctors.is_empty() && !ctor_bad {
        proven.push("все ADT-конструкторы согласованы по арности с объявлением".into());
    }

    (proven, failed)
}
