//! EVOL AST. Nodes map one-to-one onto the Phase-1 grammar.

/// Type annotation AST (Phase 7).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TypeExpr {
    /// `Int`, `Str`, `Bool`, `Float`, `Sym`, `Top`, `List`, or a user type name.
    TyCon {
        name: String,
        line: usize,
        col: usize,
    },
    /// `List[T]`
    TyList {
        elem: Box<TypeExpr>,
        line: usize,
        col: usize,
    },
}

impl TypeExpr {
    pub fn pos(&self) -> (usize, usize) {
        match self {
            TypeExpr::TyCon { line, col, .. } | TypeExpr::TyList { line, col, .. } => (*line, *col),
        }
    }
}

/// A declaration: Lib, Rule, Import, PyImport or EnumDecl.
#[derive(Clone, Debug)]
pub enum Decl {
    Lib(Box<Lib>),
    Rule(Box<Rule>),
    Import(Import),
    PyImport(PyImport),
    EnumDecl(EnumDecl),
}

/// `type Name = V1 | V2(x:Int) | V3(a:Int, b:Int);`
#[derive(Clone, Debug)]
pub struct EnumDecl {
    pub name: String,
    pub variants: Vec<EnumVariant>,
    pub line: usize,
    pub col: usize,
}

/// ADT constructor: tag + named fields with annotations.
#[derive(Clone, Debug)]
pub struct EnumVariant {
    pub tag: String,
    /// field types (annotation may be omitted -> None)
    pub fields: Vec<Option<TypeExpr>>,
    pub line: usize,
    pub col: usize,
}

/// `lib Name { decl* }`
#[derive(Clone, Debug)]
pub struct Lib {
    pub name: String,
    pub decls: Vec<Decl>,
    pub line: usize,
    pub col: usize,
}

/// `rule Name = when pat => eff`
#[derive(Clone, Debug)]
pub struct Rule {
    pub name: String,
    pub pat: Expr,
    pub body: Eff,
    pub line: usize,
    pub col: usize,
}

/// `import name;` / `import "file.evol";`
#[derive(Clone, Debug)]
pub struct Import {
    pub target: String,
    pub is_path: bool,
    pub line: usize,
    pub col: usize,
}

/// `import py "math": sqrt, sin;` — Python FFI declaration.
#[derive(Clone, Debug)]
pub struct PyImport {
    pub module: String,
    /// None = import all public names
    pub funcs: Option<Vec<String>>,
    pub alias: String,
    pub line: usize,
    pub col: usize,
}

/// Effects (match the Phase-1 formal semantics).
#[derive(Clone, Debug)]
pub enum Eff {
    Block {
        stmts: Vec<Eff>,
        line: usize,
        col: usize,
    },
    Seq {
        a: Box<Eff>,
        b: Box<Eff>,
        line: usize,
        col: usize,
    },
    Par {
        a: Box<Eff>,
        b: Box<Eff>,
        line: usize,
        col: usize,
    },
    Choice {
        a: Box<Eff>,
        b: Box<Eff>,
        line: usize,
        col: usize,
    },
    Loop {
        guard: Expr,
        body: Box<Eff>,
        line: usize,
        col: usize,
    },
    Assign {
        name: String,
        value: Expr,
        ann: Option<TypeExpr>,
        line: usize,
        col: usize,
    },
    Emit {
        value: Expr,
        line: usize,
        col: usize,
    },
    Spawn {
        lib: Option<String>,
        name: String,
        line: usize,
        col: usize,
    },
    Retract {
        name: String,
        line: usize,
        col: usize,
    },
    If {
        cond: Expr,
        then_branch: Box<Eff>,
        else_branch: Box<Eff>,
        line: usize,
        col: usize,
    },
    ForEach {
        var: String,
        coll: Expr,
        body: Box<Eff>,
        line: usize,
        col: usize,
    },
    TryCatch {
        body: Box<Eff>,
        catch_var: String,
        catch_body: Box<Eff>,
        line: usize,
        col: usize,
    },
    Raise {
        message: Expr,
        line: usize,
        col: usize,
    },
    /// module call used as an effect (console.print(x), ...)
    Call { call: Expr },
}

/// Expressions (pure values).
#[derive(Clone, Debug)]
pub enum Expr {
    Int {
        value: i64,
        line: usize,
        col: usize,
    },
    Float {
        value: f64,
        line: usize,
        col: usize,
    },
    Str {
        value: String,
        line: usize,
        col: usize,
    },
    Name {
        value: String,
        ann: Option<TypeExpr>,
        line: usize,
        col: usize,
    },
    List {
        items: Vec<Expr>,
        line: usize,
        col: usize,
    },
    Tuple {
        items: Vec<Expr>,
        line: usize,
        col: usize,
    },
    Fun {
        params: Vec<String>,
        body: Box<Expr>,
        param_anns: Vec<Option<TypeExpr>>,
        ret_ann: Option<TypeExpr>,
        line: usize,
        col: usize,
    },
    BinOp {
        op: String,
        left: Box<Expr>,
        right: Box<Expr>,
        line: usize,
        col: usize,
    },
    UnaryOp {
        op: String,
        operand: Box<Expr>,
        line: usize,
        col: usize,
    },
    Call {
        func: Box<Expr>,
        args: Vec<Expr>,
        line: usize,
        col: usize,
    },
    GetAttr {
        obj: Box<Expr>,
        attr: String,
        line: usize,
        col: usize,
    },
    Index {
        obj: Box<Expr>,
        key: Box<Expr>,
        line: usize,
        col: usize,
    },
    Match {
        scrut: Box<Expr>,
        cases: Vec<MatchCase>,
        line: usize,
        col: usize,
    },
}

/// One match arm: `Pat => expr`.
#[derive(Clone, Debug)]
pub struct MatchCase {
    /// pattern: Name (tag or `_`) or Tuple(tag, fields...)
    pub pat: Expr,
    pub body: Expr,
    pub line: usize,
    pub col: usize,
}

/// `decl ::= Lib | Rule | Import | PyImport | EnumDecl` — a whole program.
pub type Program = Vec<Decl>;

impl Expr {
    pub fn pos(&self) -> (usize, usize) {
        match self {
            Expr::Int { line, col, .. }
            | Expr::Float { line, col, .. }
            | Expr::Str { line, col, .. }
            | Expr::Name { line, col, .. }
            | Expr::List { line, col, .. }
            | Expr::Tuple { line, col, .. }
            | Expr::Fun { line, col, .. }
            | Expr::BinOp { line, col, .. }
            | Expr::UnaryOp { line, col, .. }
            | Expr::Call { line, col, .. }
            | Expr::GetAttr { line, col, .. }
            | Expr::Index { line, col, .. }
            | Expr::Match { line, col, .. } => (*line, *col),
        }
    }

    /// The pattern tag of an expression used as a pattern (for facts).
    pub fn pattern_tag(&self) -> Option<String> {
        match self {
            Expr::Name { value, .. } => Some(value.clone()),
            Expr::Tuple { items, .. } => match items.first() {
                Some(Expr::Name { value, .. }) => Some(value.clone()),
                _ => None,
            },
            _ => None,
        }
    }
}

impl Eff {
    pub fn pos(&self) -> (usize, usize) {
        match self {
            Eff::Block { line, col, .. }
            | Eff::Seq { line, col, .. }
            | Eff::Par { line, col, .. }
            | Eff::Choice { line, col, .. }
            | Eff::Loop { line, col, .. }
            | Eff::Assign { line, col, .. }
            | Eff::Emit { line, col, .. }
            | Eff::Spawn { line, col, .. }
            | Eff::Retract { line, col, .. }
            | Eff::If { line, col, .. }
            | Eff::ForEach { line, col, .. }
            | Eff::TryCatch { line, col, .. }
            | Eff::Raise { line, col, .. } => (*line, *col),
            Eff::Call { call } => call.pos(),
        }
    }
}
