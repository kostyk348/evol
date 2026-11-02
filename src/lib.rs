//! # EVOL — язык переходов состояний (Rust-порт ядра)
//!
//! Каждая конструкция — правило перехода абстрактной машины δ(S) → S′:
//!   Σ (store) + Μ (message queue) + Q (установленные правила).
//!
//! Модули:
//! - [`lexer`] — токены по грамматике Этапа 1
//! - [`ast`] — AST, узлы соответствуют грамматике
//! - [`parser`] — рекурсивный спуск
//! - [`value`] — значения с семантикой Python (truthiness, repr, числовая башня)
//! - [`interp`] — интерпретатор δ-машины: `evaluate` / `eval_eff` / `run`
//! - [`types`] — тайпчекер (постепенная типизация) + доказательщик свойств (M5)
//! - [`compiler`] — транспилятор EVOL → Python
//!
//! Вне порта (следующие шаги): интерактивный REPL с hot-reload, FFI к Python
//! (`import py`), метрики `metrics/` (z3-SMT, генераторы корпуса).

pub mod ast;
pub mod compiler;
pub mod interp;
pub mod lexer;
pub mod parser;
pub mod types;
pub mod value;

pub use ast::{Decl, Eff, Expr, Program, TypeExpr};
pub use interp::{run, EError, RunResult};
pub use lexer::{tokenize, LexError, Token};
pub use parser::{parse, ParseError};
pub use types::{proven_properties, typecheck, TcError, Type};
pub use value::Value;
