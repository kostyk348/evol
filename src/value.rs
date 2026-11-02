//! EVOL values with Python semantics: truthiness, structural equality,
//! Python-style repr/str, numeric tower (Bool <: Int), floor division.

use std::collections::HashMap;
use std::rc::Rc;

use crate::ast::TypeExpr;

pub type Store = HashMap<String, Value>;

/// A closure: params + body + captured environment.
pub struct ClosureV {
    pub params: Vec<String>,
    pub body: Rc<crate::ast::Expr>,
    pub param_anns: Vec<Option<TypeExpr>>,
    pub env: Store,
}

#[derive(Clone)]
pub enum Value {
    Int(i64),
    /// Python bool: a subtype of int (`True == 1`), but not an `Int` for annotations.
    Bool(bool),
    Float(f64),
    Str(Rc<String>),
    Sym(Rc<String>),
    List(Rc<Vec<Value>>),
    Tuple(Rc<Vec<Value>>),
    Closure(Rc<ClosureV>),
    /// Python `None`.
    Unit,
}

impl std::fmt::Debug for Value {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.repr())
    }
}

impl PartialEq for Value {
    /// Python `==`: never errors; `True == 1`, `1 == 1.0`, structural containers.
    fn eq(&self, other: &Self) -> bool {
        use Value::*;
        match (self, other) {
            (Int(a), Int(b)) => a == b,
            (Bool(a), Bool(b)) => a == b,
            (Bool(a), Int(b)) | (Int(b), Bool(a)) => (*a as i64) == *b,
            (Int(a), Float(b)) | (Float(b), Int(a)) => (*a as f64) == *b,
            (Float(a), Float(b)) => a == b,
            (Bool(a), Float(b)) | (Float(b), Bool(a)) => (*a as i64 as f64) == *b,
            (Str(a), Str(b)) => a == b,
            (Sym(a), Sym(b)) => a == b,
            // Python: Symbol.__eq__(str) -> NotImplemented -> falls back -> False
            (List(a), List(b)) | (Tuple(a), Tuple(b)) => a == b,
            (Closure(a), Closure(b)) => Rc::ptr_eq(a, b),
            (Unit, Unit) => true,
            _ => false,
        }
    }
}

impl Value {
    pub fn str_val(s: impl Into<String>) -> Value {
        Value::Str(Rc::new(s.into()))
    }

    pub fn sym(s: impl Into<String>) -> Value {
        Value::Sym(Rc::new(s.into()))
    }

    pub fn list(v: Vec<Value>) -> Value {
        Value::List(Rc::new(v))
    }

    pub fn tuple(v: Vec<Value>) -> Value {
        Value::Tuple(Rc::new(v))
    }

    /// Python `is_truthy` (bool(v)).
    pub fn is_truthy(&self) -> bool {
        match self {
            Value::Bool(b) => *b,
            Value::Int(i) => *i != 0,
            Value::Float(f) => *f != 0.0,
            Value::Str(s) => !s.is_empty(),
            Value::List(l) => !l.is_empty(),
            Value::Tuple(t) => !t.is_empty(),
            Value::Sym(_) | Value::Closure(_) => true,
            Value::Unit => false,
        }
    }

    /// Python `str(v)` (console.print uses a variant: Symbol prints bare).
    pub fn str_repr(&self) -> String {
        match self {
            // Symbol defines only __repr__; str() falls back to it
            Value::Sym(n) => format!("^{n}"),
            Value::Str(s) => s.as_str().to_string(),
            other => other.repr(),
        }
    }

    /// Python `repr(v)`.
    pub fn repr(&self) -> String {
        match self {
            Value::Int(i) => i.to_string(),
            Value::Bool(true) => "True".into(),
            Value::Bool(false) => "False".into(),
            Value::Float(f) => py_float_repr(*f),
            Value::Str(s) => py_str_repr(s),
            Value::Sym(n) => format!("^{n}"),
            Value::List(items) => {
                let inner: Vec<String> = items.iter().map(|v| v.repr()).collect();
                format!("[{}]", inner.join(", "))
            }
            Value::Tuple(items) => {
                let inner: Vec<String> = items.iter().map(|v| v.repr()).collect();
                match inner.len() {
                    0 => "()".into(),
                    1 => format!("({},)", inner[0]),
                    _ => format!("({})", inner.join(", ")),
                }
            }
            Value::Closure(_) => "('closure', ...)".into(),
            Value::Unit => "None".into(),
        }
    }

    /// Numeric view for arithmetic: Python bool acts as 0/1.
    pub fn as_num(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::Bool(b) => Some(*b as i64 as f64),
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }

    pub fn is_int_like(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Bool(_))
    }
}

/// Python `repr(float)`: always a decimal point for integral values.
pub fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let s = format!("{f}");
    if s.contains('.') || s.contains('e') || s.contains("inf") || s.contains("nan") {
        s
    } else {
        format!("{s}.0")
    }
}

/// Python `repr(str)`: single quotes preferred, double if the content has one.
fn py_str_repr(s: &str) -> String {
    let has_sq = s.contains('\'');
    let has_dq = s.contains('"');
    let (q, other) = if has_sq && !has_dq {
        ('"', '"')
    } else {
        ('\'', '\'')
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(q);
    for c in s.chars() {
        match c {
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\\' => out.push_str("\\\\"),
            _ if c == other => {
                out.push('\\');
                out.push(c);
            }
            _ => out.push(c),
        }
    }
    out.push(q);
    out
}

/// Public access for the transpiler's string literal rendering.
pub fn py_str_repr_public(s: &str) -> String {
    py_str_repr(s)
}

/// Python `//` floor division for integers.
pub fn floor_div_int(a: i64, b: i64) -> Option<i64> {
    if b == 0 {
        return None;
    }
    let q = a / b;
    let r = a % b;
    Some(if r != 0 && ((r < 0) != (b < 0)) {
        q - 1
    } else {
        q
    })
}

/// Python `//` floor division for floats (result is a float).
pub fn floor_div_float(a: f64, b: f64) -> Option<f64> {
    if b == 0.0 {
        return None;
    }
    Some((a / b).floor())
}

/// Python `int(v)`: truncates floats toward zero, parses strings, bool -> 0/1.
pub fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Int(i) => Some(*i),
        Value::Bool(b) => Some(*b as i64),
        Value::Float(f) => Some(f.trunc() as i64),
        Value::Str(s) => s.trim().parse::<i64>().ok(),
        _ => None,
    }
}

/// Python `float(v)`.
pub fn py_float(v: &Value) -> Option<f64> {
    match v {
        Value::Int(i) => Some(*i as f64),
        Value::Bool(b) => Some(*b as i64 as f64),
        Value::Float(f) => Some(*f),
        Value::Str(s) => s.trim().parse::<f64>().ok(),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equality_python_semantics() {
        assert_eq!(Value::Bool(true), Value::Int(1));
        assert_eq!(Value::Int(1), Value::Float(1.0));
        assert_eq!(Value::Int(0), Value::Bool(false), "Python: 0 == False");
    }

    #[test]
    fn zero_equals_false() {
        assert_eq!(Value::Int(0), Value::Bool(false));
    }

    #[test]
    fn truthiness() {
        assert!(!Value::Unit.is_truthy());
        assert!(!Value::Int(0).is_truthy());
        assert!(Value::sym("x").is_truthy());
        assert!(!Value::list(vec![]).is_truthy());
    }

    #[test]
    fn repr_python_style() {
        assert_eq!(Value::Float(2.0).repr(), "2.0");
        assert_eq!(Value::Float(1.5).repr(), "1.5");
        assert_eq!(Value::Bool(true).repr(), "True");
        assert_eq!(Value::str_val("it's").repr(), "\"it's\"");
        assert_eq!(Value::str_val("ok").repr(), "'ok'");
        assert_eq!(Value::tuple(vec![Value::Int(1)]).repr(), "(1,)");
        assert_eq!(
            Value::list(vec![Value::Int(1), Value::str_val("a")]).repr(),
            "[1, 'a']"
        );
        assert_eq!(Value::sym("boot").str_repr(), "^boot");
        assert_eq!(Value::Int(5).str_repr(), "5");
    }

    #[test]
    fn floor_division() {
        assert_eq!(floor_div_int(-7, 2), Some(-4));
        assert_eq!(floor_div_int(-7, -2), Some(3));
        assert_eq!(floor_div_int(7, 2), Some(3));
        assert_eq!(floor_div_int(1, 0), None);
        assert_eq!(floor_div_float(-7.5, 2.0), Some(-4.0));
    }

    #[test]
    fn conversions() {
        assert_eq!(py_int(&Value::Float(2.7)), Some(2));
        assert_eq!(py_int(&Value::str_val("42")), Some(42));
        assert_eq!(py_float(&Value::Bool(true)), Some(1.0));
        assert_eq!(py_int(&Value::sym("x")), None);
    }
}
