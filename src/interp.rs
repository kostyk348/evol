//! EVOL interpreter (Phase 3): AST-walking, direct implementation of δ(S) -> S'.
//!
//! Abstract machine S = (Σ, Μ, Q):
//!   Σ  — store: name -> value
//!   Μ  — message queue: ordered list of values
//!   Q  — installed rules: {id, lib, name, prio, pat, eff}
//!
//! Step δ:
//!   1. Μ empty -> stop.
//!   2. m = head(Μ); rest -> Μ'.
//!   3. pick matching rules from Q; max prio wins (stable: declaration order).
//!   4. no match -> m is dropped.
//!   5. evaluate eff in Σ + bindings; apply Σ mutations, emit -> Μ', spawn -> Q,
//!      retract -> Q.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fmt::Write as _;
use std::rc::Rc;

use crate::ast::*;
use crate::parser;
use crate::value::{floor_div_float, floor_div_int, py_float, py_int, ClosureV, Store, Value};

/// Interpreter errors. `Interp` is structural (division by zero, bad types),
/// `Eval` is a program-raised error (`raise`, FFI failures, annotation
/// mismatches). `try/catch` catches both; `choice` falls back on `ChoiceFail`.
#[derive(Clone, Debug, PartialEq)]
pub enum EError {
    Interp(String),
    Eval(String),
    ChoiceFail,
}

impl std::fmt::Display for EError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EError::Interp(m) | EError::Eval(m) => write!(f, "{m}"),
            EError::ChoiceFail => write!(f, "choice failed"),
        }
    }
}

impl std::error::Error for EError {}

/// Runtime-checked type annotations (Phase 7, `enforce_types=True`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EnforceTypes(pub bool);

fn ann_match(ann: &TypeExpr, value: &Value) -> bool {
    match ann {
        TypeExpr::TyCon { name, .. } => match name.as_str() {
            "Int" => value.is_int_like(),
            "Float" => value.as_num().is_some(),
            "Str" => matches!(value, Value::Str(_)),
            "Bool" => matches!(value, Value::Bool(_)),
            "Sym" => matches!(value, Value::Sym(_)),
            "List" => matches!(value, Value::List(_)),
            _ => true, // Top / unknown -> pass
        },
        TypeExpr::TyList { elem, .. } => match value {
            Value::List(items) => items.iter().all(|v| ann_match(elem, v)),
            _ => false,
        },
    }
}

/// Built-in functions (primitives available without declaration).
pub const BUILTINS: &[&str] = &["range", "len", "abs", "min", "max", "str", "int", "float"];

/// Standard-library module names (typed as dynamic: result Top).
pub const MODULE_NAMES: &[&str] = &[
    "console", "random", "file", "sim", "math", "string", "os", "py",
];

// ---------------------------------------------------------------- RNG
// Python's `random` module is a Mersenne twister; the port ships its own
// deterministic PRNG (SplitMix64). Sequences differ from CPython but the
// contract — seeded, reproducible per seed — is the same (documented in
// the PR; tests avoid exact-sequence assertions).

pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Rng {
        Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    pub fn randint(&mut self, a: i64, b: i64) -> i64 {
        if b <= a {
            return a;
        }
        a + (self.next_u64() % ((b - a + 1) as u64)) as i64
    }

    pub fn pick<'a, T>(&mut self, coll: &'a [T]) -> Option<&'a T> {
        if coll.is_empty() {
            return None;
        }
        Some(&coll[self.next_u64() as usize % coll.len()])
    }

    pub fn shuffle<T>(&mut self, coll: &mut [T]) {
        for i in (1..coll.len()).rev() {
            let j = self.next_u64() as usize % (i + 1);
            coll.swap(i, j);
        }
    }
}

// ---------------------------------------------------------------- context

/// Shared interpreter state (module-level globals in the Python original).
pub struct Ctx {
    pub sim_step: u64,
    pub rng: Rng,
    pub enforce: EnforceTypes,
    pub out: Rc<RefCell<String>>,
}

impl Ctx {
    pub fn new(enforce: EnforceTypes) -> Ctx {
        Ctx {
            sim_step: 0,
            rng: Rng::new(0),
            enforce,
            out: Rc::new(RefCell::new(String::new())),
        }
    }
}

// ---------------------------------------------------------------- builtins

fn call_builtin(_ctx: &mut Ctx, name: &str, args: &[Value]) -> Result<Value, EError> {
    match name {
        "range" => {
            if args.len() != 2 {
                return Err(EError::Interp("range ожидает 2 аргумента".into()));
            }
            let (a, b) = match (&args[0], &args[1]) {
                (Value::Int(a), Value::Int(b)) => (*a, *b),
                _ => return Err(EError::Interp("range ожидает целые аргументы".into())),
            };
            Ok(Value::list((a..b).map(Value::Int).collect()))
        }
        "len" => {
            if args.len() != 1 {
                return Err(EError::Interp("len ожидает 1 аргумент".into()));
            }
            match &args[0] {
                Value::List(l) => Ok(Value::Int(l.len() as i64)),
                Value::Tuple(t) => Ok(Value::Int(t.len() as i64)),
                Value::Str(s) => Ok(Value::Int(s.chars().count() as i64)),
                other => Err(EError::Interp(format!(
                    "object of type {:?} has no len()",
                    other.repr()
                ))),
            }
        }
        "abs" => {
            if args.len() != 1 {
                return Err(EError::Interp("abs ожидает 1 аргумент".into()));
            }
            match &args[0] {
                Value::Int(i) => Ok(Value::Int(i.abs())),
                Value::Bool(b) => Ok(Value::Int(*b as i64)),
                Value::Float(f) => Ok(Value::Float(f.abs())),
                other => Err(EError::Interp(format!("bad operand: {}", other.repr()))),
            }
        }
        "min" | "max" => {
            if args.len() < 2 {
                return Err(EError::Interp(format!("{name} ожидает 2+ аргумента")));
            }
            let mut best = 0usize;
            for i in 1..args.len() {
                let ord = py_compare(&args[i], &args[best])?;
                let better = if name == "min" {
                    ord == std::cmp::Ordering::Less
                } else {
                    ord == std::cmp::Ordering::Greater
                };
                if better {
                    best = i;
                }
            }
            Ok(args[best].clone())
        }
        "str" => {
            if args.len() != 1 {
                return Err(EError::Interp("str ожидает 1 аргумент".into()));
            }
            Ok(Value::str_val(args[0].str_repr()))
        }
        "int" => {
            if args.len() != 1 {
                return Err(EError::Interp("int ожидает 1 аргумент".into()));
            }
            py_int(&args[0])
                .map(Value::Int)
                .ok_or_else(|| EError::Interp(format!("int(): {}", args[0].repr())))
        }
        "float" => {
            if args.len() != 1 {
                return Err(EError::Interp("float ожидает 1 аргумент".into()));
            }
            py_float(&args[0])
                .map(Value::Float)
                .ok_or_else(|| EError::Interp(format!("float(): {}", args[0].repr())))
        }
        _ => Err(EError::Interp(format!("неизвестный builtin {name}"))),
    }
}

// ---------------------------------------------------------------- modules

fn call_module(ctx: &mut Ctx, module: &str, func: &str, args: &[Value]) -> Result<Value, EError> {
    match module {
        "console" => call_console(ctx, func, args),
        "random" => call_random(ctx, func, args),
        "file" => call_file(func, args),
        "sim" => call_sim(ctx, func, args),
        "math" => call_math(func, args),
        "string" => call_string(func, args),
        "os" => call_os(func, args),
        "py" => Err(EError::Interp(format!(
            "FFI: функция 'py.{func}' не зарегистрирована — добавьте 'import py \"<module>\": {func};'"
        ))),
        _ => Err(EError::Interp(format!("неизвестный модуль '{module}'"))),
    }
}

fn call_console(ctx: &mut Ctx, func: &str, args: &[Value]) -> Result<Value, EError> {
    if func == "print" || func == "println" {
        if args.is_empty() {
            return Err(EError::Interp(format!(
                "console.{func} ожидает 1+ аргументов"
            )));
        }
        let parts: Vec<String> = args
            .iter()
            .map(|a| match a {
                Value::Sym(n) => n.as_str().to_string(),
                other => other.str_repr(),
            })
            .collect();
        writeln!(ctx.out.borrow_mut(), "{}", parts.join(" ")).ok();
        return Ok(if args.len() == 1 {
            args[0].clone()
        } else {
            Value::tuple(args.to_vec())
        });
    }
    Err(EError::Interp(format!(
        "console: неизвестная функция '{func}'"
    )))
}

fn call_random(ctx: &mut Ctx, func: &str, args: &[Value]) -> Result<Value, EError> {
    match func {
        "int" => {
            if args.len() != 2 {
                return Err(EError::Interp(
                    "random.int(a, b) ожидает 2 аргумента".into(),
                ));
            }
            let (a, b) = match (&args[0], &args[1]) {
                (Value::Int(a), Value::Int(b)) => (*a, *b),
                _ => return Err(EError::Interp("random.int: целые ожидаются".into())),
            };
            Ok(Value::Int(ctx.rng.randint(a, b)))
        }
        "pick" => {
            if args.len() != 1 {
                return Err(EError::Interp(
                    "random.pick(list) ожидает 1 аргумент".into(),
                ));
            }
            match &args[0] {
                Value::List(l) if !l.is_empty() => {
                    let i = ctx.rng.next_u64() as usize % l.len();
                    Ok(l[i].clone())
                }
                Value::List(_) => Err(EError::Interp("random.pick: пустая коллекция".into())),
                _ => Err(EError::Interp("random.pick: список ожидался".into())),
            }
        }
        "shuffle" => {
            if args.len() != 1 {
                return Err(EError::Interp(
                    "random.shuffle(list) ожидает 1 аргумент".into(),
                ));
            }
            match &args[0] {
                Value::List(l) => {
                    let mut v = l.as_ref().clone();
                    ctx.rng.shuffle(&mut v);
                    Ok(Value::list(v))
                }
                _ => Err(EError::Interp("random.shuffle: список ожидался".into())),
            }
        }
        _ => Err(EError::Interp(format!(
            "random: неизвестная функция '{func}'"
        ))),
    }
}

fn call_file(func: &str, args: &[Value]) -> Result<Value, EError> {
    match func {
        "read" => {
            if args.len() != 1 {
                return Err(EError::Interp("file.read(path) ожидает 1 аргумент".into()));
            }
            let path = as_path(&args[0])?;
            std::fs::read_to_string(path)
                .map(Value::str_val)
                .map_err(|e| EError::Interp(format!("file.read: {e}")))
        }
        "write" => {
            if args.len() != 2 {
                return Err(EError::Interp(
                    "file.write(path, data) ожидает 2 аргумента".into(),
                ));
            }
            let path = as_path(&args[0])?;
            let data = args[1].str_repr();
            std::fs::write(path, data)
                .map(|_| args[1].clone())
                .map_err(|e| EError::Interp(format!("file.write: {e}")))
        }
        "exists" => {
            if args.len() != 1 {
                return Err(EError::Interp(
                    "file.exists(path) ожидает 1 аргумент".into(),
                ));
            }
            Ok(Value::Int(
                std::path::Path::new(as_path(&args[0])?).exists() as i64,
            ))
        }
        _ => Err(EError::Interp(format!(
            "file: неизвестная функция '{func}'"
        ))),
    }
}

fn as_path(v: &Value) -> Result<&str, EError> {
    match v {
        Value::Str(s) => Ok(s),
        other => Err(EError::Interp(format!(
            "путь должен быть строкой, получено {}",
            other.repr()
        ))),
    }
}

fn call_sim(ctx: &mut Ctx, func: &str, args: &[Value]) -> Result<Value, EError> {
    match func {
        "step" => Ok(Value::Int(ctx.sim_step as i64)),
        "set_seed" => {
            if args.len() != 1 {
                return Err(EError::Interp("sim.set_seed(n) ожидает 1 аргумент".into()));
            }
            let seed = match &args[0] {
                Value::Int(i) => *i as u64,
                _ => return Err(EError::Interp("sim.set_seed: целое ожидалось".into())),
            };
            ctx.rng = Rng::new(seed);
            Ok(args[0].clone())
        }
        _ => Err(EError::Interp(format!("sim: неизвестная функция '{func}'"))),
    }
}

fn call_math(func: &str, args: &[Value]) -> Result<Value, EError> {
    let need = |n: usize| -> Result<(), EError> {
        if args.len() != n {
            Err(EError::Interp(format!("math.{func}: арность")))
        } else {
            Ok(())
        }
    };
    let x = |i: usize| -> Result<f64, EError> {
        args[i]
            .as_num()
            .ok_or_else(|| EError::Interp(format!("math.{func}: число ожидалось")))
    };
    match func {
        "sqrt" => {
            need(1)?;
            Ok(Value::Int(x(0)?.sqrt() as i64))
        }
        "pow" => {
            need(2)?;
            Ok(Value::Int(x(0)?.powf(x(1)?) as i64))
        }
        "sin" => {
            need(1)?;
            Ok(Value::Float(x(0)?.sin()))
        }
        "cos" => {
            need(1)?;
            Ok(Value::Float(x(0)?.cos()))
        }
        "pi" => Ok(Value::Float(std::f64::consts::PI)),
        "floor" => {
            need(1)?;
            Ok(Value::Int(x(0)?.floor() as i64))
        }
        "ceil" => {
            need(1)?;
            Ok(Value::Int(x(0)?.ceil() as i64))
        }
        "log" => {
            need(1)?;
            Ok(Value::Float(x(0)?.ln()))
        }
        _ => Err(EError::Interp(format!(
            "math: неизвестная функция '{func}'"
        ))),
    }
}

fn call_string(func: &str, args: &[Value]) -> Result<Value, EError> {
    let s = |i: usize| -> Result<String, EError> { Ok(args[i].str_repr()) };
    match func {
        "split" => {
            if args.len() < 2 {
                return Err(EError::Interp("string.split(s, delim)".into()));
            }
            Ok(Value::list(
                s(0)?.split(&s(1)?).map(Value::str_val).collect::<Vec<_>>(),
            ))
        }
        "join" => {
            if args.len() < 2 {
                return Err(EError::Interp("string.join(list, delim)".into()));
            }
            let delim = s(1)?;
            let items: Vec<String> = match &args[0] {
                Value::List(l) => l.iter().map(|v| v.str_repr()).collect(),
                other => vec![other.str_repr()],
            };
            Ok(Value::str_val(items.join(&delim)))
        }
        "upper" => {
            if args.len() != 1 {
                return Err(EError::Interp("string.upper(s)".into()));
            }
            Ok(Value::str_val(s(0)?.to_uppercase()))
        }
        "lower" => {
            if args.len() != 1 {
                return Err(EError::Interp("string.lower(s)".into()));
            }
            Ok(Value::str_val(s(0)?.to_lowercase()))
        }
        "contains" => {
            if args.len() != 2 {
                return Err(EError::Interp("string.contains(s, sub)".into()));
            }
            Ok(Value::Int(s(0)?.contains(&s(1)?) as i64))
        }
        "replace" => {
            if args.len() != 3 {
                return Err(EError::Interp("string.replace(s, old, new)".into()));
            }
            Ok(Value::str_val(s(0)?.replace(&s(1)?, &s(2)?)))
        }
        "len" => {
            if args.len() != 1 {
                return Err(EError::Interp("string.len(s)".into()));
            }
            Ok(Value::Int(s(0)?.chars().count() as i64))
        }
        "at" => {
            if args.len() != 2 {
                return Err(EError::Interp("string.at(s, i)".into()));
            }
            let st = s(0)?;
            let idx = match &args[1] {
                Value::Int(i) => *i,
                _ => return Err(EError::Interp("string.at: индекс — целое".into())),
            };
            let chars: Vec<char> = st.chars().collect();
            let i = if idx < 0 {
                chars.len() as i64 + idx
            } else {
                idx
            };
            chars
                .get(i as usize)
                .map(|c| Value::str_val(c.to_string()))
                .ok_or_else(|| EError::Interp("string.at: вне диапазона".into()))
        }
        "substr" => {
            if args.len() < 2 {
                return Err(EError::Interp("string.substr(s, start[, end])".into()));
            }
            let st = s(0)?;
            let chars: Vec<char> = st.chars().collect();
            let n = chars.len() as i64;
            let cvt = |v: &Value| -> Result<i64, EError> {
                match v {
                    Value::Int(i) => Ok(*i),
                    _ => Err(EError::Interp("string.substr: целые индексы".into())),
                }
            };
            let mut start = cvt(&args[1])?;
            if start < 0 {
                start += n;
            }
            let mut end = if args.len() > 2 { cvt(&args[2])? } else { n };
            if end < 0 {
                end += n;
            }
            let start = start.clamp(0, n) as usize;
            let end = (end.clamp(0, n) as usize).max(start);
            Ok(Value::str_val(chars[start..end].iter().collect::<String>()))
        }
        _ => Err(EError::Interp(format!(
            "string: неизвестная функция '{func}'"
        ))),
    }
}

fn call_os(func: &str, args: &[Value]) -> Result<Value, EError> {
    match func {
        "listdir" => {
            if args.len() != 1 {
                return Err(EError::Interp("os.listdir(path)".into()));
            }
            let path = as_path(&args[0])?;
            let mut names: Vec<String> = std::fs::read_dir(path)
                .map_err(|e| EError::Interp(format!("os.listdir: {e}")))?
                .filter_map(|e| e.ok())
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .collect();
            names.sort();
            Ok(Value::list(names.into_iter().map(Value::str_val).collect()))
        }
        "getcwd" => Ok(Value::str_val(
            std::env::current_dir()
                .map_err(|e| EError::Interp(format!("os.getcwd: {e}")))?
                .to_string_lossy()
                .into_owned(),
        )),
        "path_exists" => {
            if args.len() != 1 {
                return Err(EError::Interp("os.path_exists(path)".into()));
            }
            Ok(Value::Int(
                std::path::Path::new(as_path(&args[0])?).exists() as i64,
            ))
        }
        "mkdir" => {
            if args.len() != 1 {
                return Err(EError::Interp("os.mkdir(path)".into()));
            }
            let path = as_path(&args[0])?;
            std::fs::create_dir_all(path).map_err(|e| EError::Interp(format!("os.mkdir: {e}")))?;
            Ok(args[0].clone())
        }
        _ => Err(EError::Interp(format!("os: неизвестная функция '{func}'"))),
    }
}

// ---------------------------------------------------------------- expressions

fn py_compare(l: &Value, r: &Value) -> Result<std::cmp::Ordering, EError> {
    use std::cmp::Ordering;
    match (l, r) {
        (Value::Str(a), Value::Str(b)) => Ok(a.cmp(b)),
        _ => {
            let (Some(a), Some(b)) = (l.as_num(), r.as_num()) else {
                return Err(EError::Interp(format!(
                    "'<' not supported between instances of {} and {}",
                    l.repr(),
                    r.repr()
                )));
            };
            Ok(a.partial_cmp(&b).unwrap_or(Ordering::Equal))
        }
    }
}

fn eval_binop(op: &str, l: &Value, r: &Value) -> Result<Value, EError> {
    use Value::*;
    match op {
        "+" => match (l, r) {
            (Int(a), Int(b)) => Ok(Int(a + b)),
            (Bool(a), Int(b)) => Ok(Int(*a as i64 + b)),
            (Int(a), Bool(b)) => Ok(Int(a + *b as i64)),
            (Bool(a), Bool(b)) => Ok(Int(*a as i64 + *b as i64)),
            (Float(a), Float(b)) => Ok(Float(a + b)),
            (Float(a), Int(b)) => Ok(Float(a + *b as f64)),
            (Int(a), Float(b)) => Ok(Float(*a as f64 + b)),
            (Float(a), Bool(b)) => Ok(Float(a + *b as i64 as f64)),
            (Bool(a), Float(b)) => Ok(Float(*a as i64 as f64 + b)),
            (Str(a), Str(b)) => Ok(Value::str_val(format!("{a}{b}"))),
            (List(a), List(b)) => {
                let mut v = a.as_ref().clone();
                v.extend(b.iter().cloned());
                Ok(Value::list(v))
            }
            _ => Err(EError::Interp(format!(
                "unsupported operand type(s) for +: {} and {}",
                l.repr(),
                r.repr()
            ))),
        },
        "-" | "*" | "/" => {
            // str/list repetition for *
            if op == "*" {
                if let (Str(a), Int(n)) | (Int(n), Str(a)) = (l, r) {
                    return Ok(Value::str_val(a.repeat((*n).max(0) as usize)));
                }
                if let (List(a), Int(n)) | (Int(n), List(a)) = (l, r) {
                    let mut v = Vec::with_capacity(a.len() * (*n).max(0) as usize);
                    for _ in 0..(*n).max(0) {
                        v.extend(a.iter().cloned());
                    }
                    return Ok(Value::list(v));
                }
            }
            let (Some(a), Some(b)) = (l.as_num(), r.as_num()) else {
                return Err(EError::Interp(format!(
                    "unsupported operand type(s) for {op}: {} and {}",
                    l.repr(),
                    r.repr()
                )));
            };
            let is_float = matches!(l, Float(_)) || matches!(r, Float(_));
            if op == "/" {
                let val = if is_float {
                    floor_div_float(a, b).ok_or_else(|| EError::Interp("деление на 0".into()))?
                } else {
                    let (ai, bi) = (a as i64, b as i64);
                    floor_div_int(ai, bi).ok_or_else(|| EError::Interp("деление на 0".into()))?
                        as f64
                };
                return Ok(if is_float {
                    Float(val)
                } else {
                    Int(val as i64)
                });
            }
            let val = if op == "-" { a - b } else { a * b };
            Ok(if is_float {
                Float(val)
            } else {
                Int(val as i64)
            })
        }
        "==" => Ok(Bool(l == r)),
        "!=" => Ok(Bool(l != r)),
        "<" | ">" | "<=" | ">=" => {
            let ord = py_compare(l, r)?;
            Ok(Bool(match op {
                "<" => ord == std::cmp::Ordering::Less,
                ">" => ord == std::cmp::Ordering::Greater,
                "<=" => ord != std::cmp::Ordering::Greater,
                _ => ord != std::cmp::Ordering::Less,
            }))
        }
        "and" => Ok(Bool(l.is_truthy() && r.is_truthy())),
        "or" => Ok(Bool(l.is_truthy() || r.is_truthy())),
        _ => Err(EError::Interp(format!(
            "неизвестный бинарный оператор {op}"
        ))),
    }
}

/// Make a bootstrap value: plain strings become Symbols (unless "^"-prefixed).
pub fn make_value(v: &str) -> Value {
    if !v.starts_with('^') {
        Value::sym(v)
    } else {
        Value::str_val(v)
    }
}

pub fn evaluate(expr: &Expr, sigma: &Store, ctx: &mut Ctx) -> Result<Value, EError> {
    match expr {
        Expr::Int { value, .. } => Ok(Value::Int(*value)),
        Expr::Float { value, .. } => Ok(Value::Float(*value)),
        Expr::Str { value, .. } => Ok(Value::str_val(value.clone())),
        Expr::Name { value, .. } => match sigma.get(value) {
            Some(v) => Ok(v.clone()),
            None => Ok(Value::sym(value.clone())),
        },
        Expr::List { items, .. } => {
            let mut out = Vec::with_capacity(items.len());
            for i in items {
                out.push(evaluate(i, sigma, ctx)?);
            }
            Ok(Value::list(out))
        }
        Expr::Tuple { items, .. } => {
            let mut out = Vec::with_capacity(items.len());
            for i in items {
                out.push(evaluate(i, sigma, ctx)?);
            }
            Ok(Value::tuple(out))
        }
        Expr::Fun {
            params,
            body,
            param_anns,
            ..
        } => Ok(Value::Closure(Rc::new(ClosureV {
            params: params.clone(),
            body: Rc::new((**body).clone()),
            param_anns: param_anns.clone(),
            env: sigma.clone(),
        }))),
        Expr::UnaryOp { op, operand, .. } => {
            let val = evaluate(operand, sigma, ctx)?;
            match op.as_str() {
                "-" => match &val {
                    Value::Int(i) => Ok(Value::Int(-i)),
                    Value::Bool(b) => Ok(Value::Int(-(*b as i64))),
                    Value::Float(f) => Ok(Value::Float(-f)),
                    other => Err(EError::Interp(format!(
                        "bad operand for unary -: {}",
                        other.repr()
                    ))),
                },
                "not" => Ok(Value::Bool(!val.is_truthy())),
                other => Err(EError::Interp(format!(
                    "неизвестный унарный оператор {other}"
                ))),
            }
        }
        Expr::BinOp {
            op, left, right, ..
        } => {
            let l = evaluate(left, sigma, ctx)?;
            let r = evaluate(right, sigma, ctx)?;
            eval_binop(op, &l, &r)
        }
        Expr::GetAttr { obj, attr, .. } => {
            // py.<fn> FFI is Python-host specific; the port reports the same
            // "not registered" error the Python runtime gives without an import
            if let Expr::Name { value, .. } = obj.as_ref() {
                if value == "py" {
                    return Err(EError::Interp(format!(
                        "FFI: 'py.{attr}' не зарегистрирован (import py ...: {attr})"
                    )));
                }
            }
            let o = evaluate(obj, sigma, ctx)?;
            if attr == "kind" {
                return match &o {
                    Value::Tuple(t) if !t.is_empty() => Ok(t[0].clone()),
                    Value::Sym(_) => Ok(o),
                    other => Err(EError::Interp(format!(".kind от {}", other.repr()))),
                };
            }
            Err(EError::Interp(format!("неизвестный атрибут .{attr}")))
        }
        Expr::Index { obj, key, .. } => {
            let o = evaluate(obj, sigma, ctx)?;
            let k = evaluate(key, sigma, ctx)?;
            let idx = match &k {
                Value::Int(i) => *i,
                Value::Bool(b) => *b as i64,
                _ => {
                    return Err(EError::Interp(format!(
                        "indices must be integers, not {}",
                        k.repr()
                    )))
                }
            };
            match &o {
                Value::List(l) => {
                    let n = l.len() as i64;
                    let i = if idx < 0 { n + idx } else { idx };
                    if i < 0 || i >= n {
                        return Err(EError::Interp("index out of range".into()));
                    }
                    Ok(l[i as usize].clone())
                }
                Value::Tuple(t) => {
                    let n = t.len() as i64;
                    let i = if idx < 0 { n + idx } else { idx };
                    if i < 0 || i >= n {
                        return Err(EError::Interp("index out of range".into()));
                    }
                    Ok(t[i as usize].clone())
                }
                other => Err(EError::Interp(format!(
                    "индексация неприменима к {}",
                    other.repr()
                ))),
            }
        }
        Expr::Match { scrut, cases, .. } => {
            let val = evaluate(scrut, sigma, ctx)?;
            for case in cases {
                let mut bindings = Store::new();
                if match_value(&case.pat, &val, &mut bindings) {
                    let mut local = sigma.clone();
                    for (k, v) in bindings {
                        local.insert(k, v);
                    }
                    return evaluate(&case.body, &local, ctx);
                }
            }
            Ok(Value::Unit)
        }
        Expr::Call { func, args, .. } => {
            // module call: console.print(x), sim.step(), ...
            if let Expr::GetAttr { obj, attr, .. } = func.as_ref() {
                if let Expr::Name {
                    value: mod_name, ..
                } = obj.as_ref()
                {
                    let func_name = attr.as_str();
                    let mut vals = Vec::with_capacity(args.len());
                    for a in args {
                        vals.push(evaluate(a, sigma, ctx)?);
                    }
                    if mod_name == "py" {
                        return Err(EError::Interp(format!(
                            "FFI: функция 'py.{func_name}' не зарегистрирована — добавьте 'import py \"<module>\": {func_name};'"
                        )));
                    }
                    return call_module(ctx, mod_name, func_name, &vals);
                }
            }
            // builtins by name
            if let Expr::Name { value, .. } = func.as_ref() {
                if BUILTINS.contains(&value.as_str()) {
                    let mut vals = Vec::with_capacity(args.len());
                    for a in args {
                        vals.push(evaluate(a, sigma, ctx)?);
                    }
                    return call_builtin(ctx, value, &vals);
                }
                // ADT constructor: Circle(3.0) -> (Symbol("Circle"), 3.0)
                if value.chars().next().is_some_and(|c| c.is_uppercase()) {
                    let mut vals = vec![Value::sym(value.clone())];
                    for a in args {
                        vals.push(evaluate(a, sigma, ctx)?);
                    }
                    return Ok(Value::tuple(vals));
                }
            }
            // closure call
            let f = evaluate(func, sigma, ctx)?;
            match &f {
                Value::Closure(c) => {
                    let mut vals = Vec::with_capacity(args.len());
                    for a in args {
                        vals.push(evaluate(a, sigma, ctx)?);
                    }
                    if vals.len() != c.params.len() {
                        return Err(EError::Interp(format!(
                            "arity mismatch: {} vs {}",
                            c.params.len(),
                            vals.len()
                        )));
                    }
                    if ctx.enforce.0 {
                        for (a, ann) in vals.iter().zip(c.param_anns.iter()) {
                            if let Some(ann) = ann {
                                if !ann_match(ann, a) {
                                    return Err(EError::Eval(format!(
                                        "аргумент {} не соответствует аннотации {:?}",
                                        a.repr(),
                                        ann
                                    )));
                                }
                            }
                        }
                    }
                    let mut local = c.env.clone();
                    for (p, a) in c.params.iter().zip(vals) {
                        local.insert(p.clone(), a);
                    }
                    evaluate(&c.body, &local, ctx)
                }
                other => Err(EError::Interp(format!(
                    "вызов не-функции: {}",
                    other.repr()
                ))),
            }
        }
    }
}

/// match-expression pattern vs a runtime value; binds into `bindings`.
pub fn match_value(pat: &Expr, val: &Value, bindings: &mut Store) -> bool {
    match (pat, val) {
        (Expr::Name { value, .. }, _) => {
            if value == "_" {
                return true;
            }
            match val {
                Value::Sym(n) => n.as_str() == value,
                Value::Tuple(t) if !t.is_empty() => {
                    matches!(&t[0], Value::Sym(n) if n.as_str() == value)
                }
                _ => false,
            }
        }
        (Expr::Tuple { items, .. }, Value::Tuple(t)) => {
            if items.len() != t.len() || items.is_empty() {
                return false;
            }
            let tag_ok = matches!(
                (&items[0], &t[0]),
                (Expr::Name { value, .. }, Value::Sym(n)) if n.as_str() == value
            );
            if !tag_ok {
                return false;
            }
            for (item, v) in items[1..].iter().zip(t[1..].iter()) {
                if let Expr::Name { value, .. } = item {
                    if value != "_" {
                        bindings.insert(value.clone(), v.clone());
                    }
                }
            }
            true
        }
        _ => false,
    }
}

// ---------------------------------------------------------------- effects

/// Result of evaluating an effect: new store plus the machine mutations.
pub struct EffResult {
    pub sigma: Store,
    pub emits: Vec<Value>,
    pub spawned: Vec<Spawn>,
    pub retracted: HashSet<String>,
}

#[derive(Clone, Debug)]
pub struct Spawn {
    pub lib: Option<String>,
    pub name: String,
}

fn eval_eff(node: &Eff, sigma: &Store, ctx: &mut Ctx) -> Result<EffResult, EError> {
    let empty = |s: Store| EffResult {
        sigma: s,
        emits: vec![],
        spawned: vec![],
        retracted: HashSet::new(),
    };
    match node {
        Eff::Block { stmts, .. } => {
            let mut cur = sigma.clone();
            let mut emits = Vec::new();
            let mut spawned = Vec::new();
            let mut retracted = HashSet::new();
            for stmt in stmts {
                let r = eval_eff(stmt, &cur, ctx)?;
                cur = r.sigma;
                emits.extend(r.emits);
                spawned.extend(r.spawned);
                retracted.extend(r.retracted);
            }
            Ok(EffResult {
                sigma: cur,
                emits,
                spawned,
                retracted,
            })
        }
        Eff::Assign {
            name, value, ann, ..
        } => {
            let mut cur = sigma.clone();
            let val = evaluate(value, sigma, ctx)?;
            if ctx.enforce.0 {
                if let Some(ann) = ann {
                    if !ann_match(ann, &val) {
                        return Err(EError::Eval(format!(
                            "присваивание '{name}': значение {} не соответствует аннотации",
                            val.repr()
                        )));
                    }
                }
            }
            cur.insert(name.clone(), val);
            Ok(empty(cur))
        }
        Eff::Emit { value, .. } => {
            let v = evaluate(value, sigma, ctx)?;
            Ok(EffResult {
                sigma: sigma.clone(),
                emits: vec![v],
                spawned: vec![],
                retracted: HashSet::new(),
            })
        }
        Eff::Spawn { lib, name, .. } => Ok(EffResult {
            sigma: sigma.clone(),
            emits: vec![],
            spawned: vec![Spawn {
                lib: lib.clone(),
                name: name.clone(),
            }],
            retracted: HashSet::new(),
        }),
        Eff::Retract { name, .. } => {
            let mut r = HashSet::new();
            r.insert(name.clone());
            Ok(EffResult {
                sigma: sigma.clone(),
                emits: vec![],
                spawned: vec![],
                retracted: r,
            })
        }
        Eff::If {
            cond,
            then_branch,
            else_branch,
            ..
        } => {
            if evaluate(cond, sigma, ctx)?.is_truthy() {
                eval_eff(then_branch, sigma, ctx)
            } else {
                eval_eff(else_branch, sigma, ctx)
            }
        }
        Eff::Seq { a, b, .. } => {
            let r1 = eval_eff(a, sigma, ctx)?;
            let r2 = eval_eff(b, &r1.sigma, ctx)?;
            let mut emits = r1.emits;
            emits.extend(r2.emits);
            let mut spawned = r1.spawned;
            spawned.extend(r2.spawned);
            let mut retracted = r1.retracted;
            retracted.extend(r2.retracted);
            Ok(EffResult {
                sigma: r2.sigma,
                emits,
                spawned,
                retracted,
            })
        }
        Eff::Par { a, b, .. } => {
            // both effects apply to the same Σ independently; name conflict -> fail
            let ra = eval_eff(a, sigma, ctx)?;
            let rb = eval_eff(b, sigma, ctx)?;
            let mut merged = sigma.clone();
            let keys: HashSet<&String> = ra.sigma.keys().chain(rb.sigma.keys()).collect();
            for k in keys {
                let va = ra.sigma.get(k);
                let vb = rb.sigma.get(k);
                match (va, vb) {
                    (Some(va), Some(vb)) if va != vb => {
                        return Err(EError::Interp(format!(
                            "par: конфликт имён '{k}' ({} vs {})",
                            va.repr(),
                            vb.repr()
                        )));
                    }
                    (Some(va), _) => {
                        merged.insert(k.clone(), va.clone());
                    }
                    (_, Some(vb)) => {
                        merged.insert(k.clone(), vb.clone());
                    }
                    _ => {}
                }
            }
            let mut emits = ra.emits;
            emits.extend(rb.emits);
            let mut spawned = ra.spawned;
            spawned.extend(rb.spawned);
            let mut retracted = ra.retracted;
            retracted.extend(rb.retracted);
            Ok(EffResult {
                sigma: merged,
                emits,
                spawned,
                retracted,
            })
        }
        Eff::Choice { a, b, .. } => match eval_eff(a, sigma, ctx) {
            Ok(r) => Ok(r),
            Err(EError::ChoiceFail) => eval_eff(b, sigma, ctx),
            Err(other) => Err(other),
        },
        Eff::Loop { guard, body, .. } => {
            let mut cur = sigma.clone();
            let mut emits = Vec::new();
            let mut spawned = Vec::new();
            let mut retracted = HashSet::new();
            let mut guard_count = 0u64;
            while evaluate(guard, &cur, ctx)?.is_truthy() {
                guard_count += 1;
                if guard_count > 100_000 {
                    return Err(EError::Interp(
                        "loop: превышен лимит итераций (возможно, бесконечный цикл)".into(),
                    ));
                }
                let r = eval_eff(body, &cur, ctx)?;
                cur = r.sigma;
                emits.extend(r.emits);
                spawned.extend(r.spawned);
                retracted.extend(r.retracted);
            }
            Ok(EffResult {
                sigma: cur,
                emits,
                spawned,
                retracted,
            })
        }
        Eff::ForEach {
            var, coll, body, ..
        } => {
            let coll_v = evaluate(coll, sigma, ctx)?;
            let items = match &coll_v {
                Value::List(l) => l.as_ref().clone(),
                other => {
                    return Err(EError::Interp(format!(
                        "forall: коллекция не список: {}",
                        other.repr()
                    )))
                }
            };
            let mut cur = sigma.clone();
            let mut emits = Vec::new();
            let mut spawned = Vec::new();
            let mut retracted = HashSet::new();
            for item in items {
                let mut local = cur.clone();
                local.insert(var.clone(), item);
                let r = eval_eff(body, &local, ctx)?;
                r.sigma
                    .into_iter()
                    .filter(|(k, _)| k != var)
                    .for_each(|(k, v)| {
                        cur.insert(k, v);
                    });
                emits.extend(r.emits);
                spawned.extend(r.spawned);
                retracted.extend(r.retracted);
            }
            Ok(EffResult {
                sigma: cur,
                emits,
                spawned,
                retracted,
            })
        }
        Eff::TryCatch {
            body,
            catch_var,
            catch_body,
            ..
        } => match eval_eff(body, sigma, ctx) {
            Ok(r) => Ok(r),
            Err(e @ (EError::Interp(_) | EError::Eval(_))) => {
                let mut local = sigma.clone();
                local.insert(catch_var.clone(), Value::str_val(e.to_string()));
                eval_eff(catch_body, &local, ctx)
            }
            Err(EError::ChoiceFail) => Err(EError::ChoiceFail),
        },
        Eff::Raise { message, .. } => {
            let msg = evaluate(message, sigma, ctx)?;
            Err(EError::Eval(msg.str_repr()))
        }
        Eff::Call { call } => {
            evaluate(call, sigma, ctx)?;
            Ok(empty(sigma.clone()))
        }
    }
}

// ---------------------------------------------------------------- rule table

#[derive(Clone, Debug)]
pub struct RuleEntry {
    pub lib: String,
    pub name: String,
    pub pat: Expr,
    pub body: Eff,
}

/// Resolve a .evol file: absolute, next to the importer, cwd, samples/.
fn resolve_module(target: &str, base_dir: &str) -> Option<std::path::PathBuf> {
    let p = std::path::Path::new(target);
    let mut candidates = Vec::new();
    if p.is_absolute() {
        candidates.push(p.to_path_buf());
    } else {
        candidates.push(std::path::Path::new(base_dir).join(target));
        candidates.push(std::env::current_dir().unwrap_or_default().join(target));
        candidates.push(std::path::Path::new("samples").join(target));
        if !target.ends_with(".evol") {
            candidates.push(std::path::Path::new(base_dir).join(format!("{target}.evol")));
            candidates.push(
                std::env::current_dir()
                    .unwrap_or_default()
                    .join(format!("{target}.evol")),
            );
            candidates.push(std::path::Path::new("samples").join(format!("{target}.evol")));
        }
    }
    candidates.into_iter().find(|c| c.exists())
}

/// Build the rule table. `import "file.evol"` / `import name` load external
/// modules; `import py ...` is reported as unavailable (no Python host).
pub fn collect_rule_table(
    decls: &[Decl],
    base_lib: &str,
    base_dir: &str,
    seen: &mut HashSet<std::path::PathBuf>,
) -> Result<Vec<RuleEntry>, EError> {
    // index: (lib, name) -> position; Python dict keeps the first insert slot
    struct Table {
        entries: Vec<RuleEntry>,
        index: HashMap<(String, String), usize>,
    }
    fn push(t: &mut Table, e: RuleEntry) {
        let key = (e.lib.clone(), e.name.clone());
        match t.index.get(&key) {
            Some(&i) => t.entries[i] = e,
            None => {
                t.index.insert(key, t.entries.len());
                t.entries.push(e);
            }
        }
    }
    fn walk(
        decls: &[Decl],
        base_lib: &str,
        base_dir: &str,
        seen: &mut HashSet<std::path::PathBuf>,
        t: &mut Table,
    ) -> Result<(), EError> {
        for d in decls {
            match d {
                Decl::Rule(r) => push(
                    t,
                    RuleEntry {
                        lib: base_lib.to_string(),
                        name: r.name.clone(),
                        pat: r.pat.clone(),
                        body: r.body.clone(),
                    },
                ),
                Decl::Lib(l) => {
                    for sub in &l.decls {
                        if let Decl::Rule(r) = sub {
                            push(
                                t,
                                RuleEntry {
                                    lib: l.name.clone(),
                                    name: r.name.clone(),
                                    pat: r.pat.clone(),
                                    body: r.body.clone(),
                                },
                            );
                        }
                    }
                }
                Decl::EnumDecl(_) => {} // types are the typechecker's business
                Decl::PyImport(pi) => {
                    return Err(EError::Interp(format!(
                        "FFI: не удалось импортировать Python-модуль '{}': Python host недоступен в Rust-порте",
                        pi.module
                    )));
                }
                Decl::Import(im) => {
                    let path = if im.is_path {
                        resolve_module(&im.target, base_dir)
                    } else {
                        resolve_module(&format!("{}.evol", im.target), base_dir)
                    };
                    let Some(path) = path else {
                        let want = if im.is_path {
                            im.target.clone()
                        } else {
                            format!("{}.evol", im.target)
                        };
                        return Err(EError::Interp(format!("модуль не найден: {want}")));
                    };
                    if seen.contains(&path) {
                        continue; // import cycle protection
                    }
                    seen.insert(path.clone());
                    let src = std::fs::read_to_string(&path)
                        .map_err(|e| EError::Interp(format!("import {}: {e}", path.display())))?;
                    let sub_ast = parser::parse(&src, &path.to_string_lossy())
                        .map_err(|e| EError::Interp(e.0))?;
                    let stem = path
                        .file_stem()
                        .map(|s| s.to_string_lossy().into_owned())
                        .unwrap_or_default();
                    walk(
                        &sub_ast,
                        &stem,
                        &path
                            .parent()
                            .unwrap_or(std::path::Path::new(""))
                            .to_string_lossy(),
                        seen,
                        t,
                    )?;
                }
            }
        }
        Ok(())
    }
    let mut t = Table {
        entries: Vec::new(),
        index: HashMap::new(),
    };
    walk(decls, base_lib, base_dir, seen, &mut t)?;
    Ok(t.entries)
}

fn resolve_spawn<'a>(table: &'a [RuleEntry], sp: &Spawn) -> Option<&'a RuleEntry> {
    if let Some(lib) = &sp.lib {
        return table.iter().find(|r| &r.lib == lib && r.name == sp.name);
    }
    if let Some(r) = table.iter().find(|r| r.lib.is_empty() && r.name == sp.name) {
        return Some(r);
    }
    table.iter().find(|r| r.name == sp.name)
}

// ---------------------------------------------------------------- machine

fn match_rule(pat: &Expr, msg: &Value) -> Option<Store> {
    match (pat, msg) {
        (Expr::Name { value, .. }, Value::Sym(n)) => {
            if n.as_str() == value {
                Some(Store::new())
            } else {
                None
            }
        }
        (Expr::Tuple { items, .. }, Value::Tuple(t)) => {
            if items.is_empty() || !matches!(items[0], Expr::Name { .. }) {
                return None;
            }
            let Expr::Name { value: tag, .. } = &items[0] else {
                return None;
            };
            let Value::Sym(sym0) = &t[0] else {
                return None;
            };
            if t.is_empty() || sym0.as_str() != tag || t.len() - 1 != items.len() - 1 {
                return None;
            }
            let mut bindings = Store::new();
            for (item, v) in items[1..].iter().zip(t[1..].iter()) {
                if let Expr::Name { value, .. } = item {
                    bindings.insert(value.clone(), v.clone());
                }
            }
            Some(bindings)
        }
        _ => None,
    }
}

/// Result of `run`: final store, step count, emission log.
#[derive(Debug)]
pub struct RunResult {
    pub steps: u64,
    pub store: Store,
    pub emitted: Vec<Value>,
    pub stopped_by_max_steps: bool,
    /// console.print output captured during the run
    pub output: String,
}

/// Run the δ machine over `ast` with `bootstrap` messages.
pub fn run(
    ast: &[Decl],
    bootstrap: &[&str],
    max_steps: u64,
    enforce: EnforceTypes,
    base_dir: &str,
) -> Result<RunResult, EError> {
    let mut ctx = Ctx::new(enforce);
    let mut seen = HashSet::new();
    let table = collect_rule_table(ast, "", base_dir, &mut seen)?;
    let mut q: Vec<&RuleEntry> = table.iter().collect();
    let mut sigma: Store = HashMap::new();
    let mut queue: VecDeque<Value> = bootstrap.iter().map(|m| make_value(m)).collect();
    let mut steps = 0u64;
    let mut emitted_log = Vec::new();
    while let Some(m) = queue.pop_front() {
        if steps >= max_steps {
            break;
        }
        steps += 1;
        ctx.sim_step = steps;
        let mut cands: Vec<(&&RuleEntry, Store)> = Vec::new();
        for r in &q {
            if let Some(b) = match_rule(&r.pat, &m) {
                cands.push((r, b));
            }
        }
        if cands.is_empty() {
            continue;
        }
        // prio is 0 for every rule; stable sort keeps declaration order
        let (r, bindings) = cands.remove(0);
        let mut local = sigma.clone();
        for (k, v) in bindings {
            local.insert(k, v);
        }
        if ctx.enforce.0 {
            if let Expr::Tuple { items, .. } = &r.pat {
                for item in items.iter().skip(1) {
                    if let Expr::Name {
                        value,
                        ann: Some(ann),
                        ..
                    } = item
                    {
                        if let Some(v) = local.get(value) {
                            if !ann_match(ann, v) {
                                return Err(EError::Eval(format!(
                                    "сообщение: поле '{value}' {} не соответствует аннотации",
                                    v.repr()
                                )));
                            }
                        }
                    }
                }
            }
        }
        let res = eval_eff(&r.body, &local, &mut ctx)?;
        let EffResult {
            sigma: new_sigma,
            emits,
            spawned,
            retracted,
        } = res;
        sigma = new_sigma;
        for v in &emits {
            queue.push_back(v.clone());
            emitted_log.push(v.clone());
        }
        for sp in &spawned {
            if let Some(node) = resolve_spawn(&table, sp) {
                q.push(node);
            }
        }
        if !retracted.is_empty() {
            q.retain(|x| !retracted.contains(&x.name));
        }
    }
    let output = ctx.out.borrow().clone();
    Ok(RunResult {
        steps,
        store: sigma,
        emitted: emitted_log,
        stopped_by_max_steps: steps >= max_steps,
        output,
    })
}
