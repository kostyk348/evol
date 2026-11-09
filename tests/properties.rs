//! Semantic unit tests + property tests for the δ-machine.
//!
//! Every `sem_*` test pins one numbered rule of `docs/semantics.md`
//! (the trace table at the end of that document references these tests by
//! name). The `prop_*` tests are randomized property tests with a
//! hand-rolled generator (zero dependencies, SplitMix64 via `evol::interp::Rng`).

use std::collections::BTreeSet;

use evol::ast::{Decl, Eff, Expr};
use evol::interp::{make_value, run, Ctx, EnforceTypes, Rng};
use evol::parser::parse;
use evol::value::Store;
use evol::value::Value;

// ---------------------------------------------------------------- helpers

fn samples_dir() -> String {
    format!("{}/samples", env!("CARGO_MANIFEST_DIR"))
}

fn sample_path(name: &str) -> String {
    format!("{}/samples/{}", env!("CARGO_MANIFEST_DIR"), name)
}

fn sample_names() -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(samples_dir())
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".evol"))
        .collect();
    names.sort();
    names
}

/// Programs calling the `file`/`os` modules touch the host filesystem —
/// they are the designated escape hatch to the real world and are excluded
/// from the machine-level properties (so tests never clobber repo files).
fn performs_io(src: &str) -> bool {
    src.contains("file.") || src.contains("os.")
}

/// Run a source string with a single `boot` bootstrap message.
fn run_src(src: &str) -> Result<evol::RunResult, evol::EError> {
    run_src_msgs(src, &["boot"], 100_000)
}

fn run_src_msgs(src: &str, msgs: &[&str], max_steps: u64) -> Result<evol::RunResult, evol::EError> {
    let ast = parse(src, "test.evol").expect("test source must parse");
    run(&ast, msgs, max_steps, EnforceTypes(false), ".")
}

/// Canonical rendering of a run result (store keys sorted, like the golden
/// harness) — used as the observable "hash" of the final configuration.
fn canonical(res: &evol::RunResult) -> String {
    let mut keys: Vec<&String> = res.store.keys().collect();
    keys.sort();
    let store: Vec<String> = keys
        .iter()
        .map(|k| format!("{}={}", k, res.store[*k].repr()))
        .collect();
    let em: Vec<String> = res.emitted.iter().map(|v| v.repr()).collect();
    format!(
        "steps={}; store=[{}]; emitted=[{}]; stopped={}; output={:?}",
        res.steps,
        store.join("; "),
        em.join(", "),
        res.stopped_by_max_steps,
        res.output
    )
}

/// Canonical rendering of a full `run` outcome, including the error case.
fn canonical_outcome(src: &str, msgs: &[&str], max_steps: u64, base_dir: &str) -> String {
    let ast = match parse(src, "test.evol") {
        Ok(ast) => ast,
        Err(e) => return format!("parse_err={}", e.0),
    };
    match run(&ast, msgs, max_steps, EnforceTypes(false), base_dir) {
        Ok(res) => canonical(&res),
        Err(e) => format!("err={e:?}"),
    }
}

fn err_of(src: &str) -> String {
    match run_src(src) {
        Ok(_) => panic!("expected a run error for:\n{src}"),
        Err(e) => e.to_string(),
    }
}

// ---------------------------------------------------------------- load & bootstrap

/// [S1] duplicate `(lib, name)` rule definition: the later body replaces the
/// earlier one at the first slot (same position, new behavior).
#[test]
fn sem_s1_load_duplicate_rule_replaced_in_place() {
    let src = r#"
lib t {
  rule r = when boot => { w := 1; emit (done) }
  rule r = when boot => { w := 2; emit (done) }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("w"), Some(&Value::Int(2)));
}

/// [S2] `import py "..."` fails at load time (no Python host in the Rust port).
#[test]
fn sem_s2_load_py_import_unavailable() {
    let src = std::fs::read_to_string(sample_path("concurrent_fanout.evol")).unwrap();
    let ast = parse(&src, "s.evol").unwrap();
    let e = run(&ast, &["boot"], 1000, EnforceTypes(false), ".").unwrap_err();
    assert!(e.to_string().contains("Python"), "{e}");
}

/// [S3] `import name` / `import "path"` of a missing module fails at load time.
#[test]
fn sem_s3_load_module_not_found() {
    let src = "import definitely_missing_module;";
    let e = err_of(src);
    assert!(e.contains("модуль не найден"), "{e}");
}

/// [S4] bootstrap strings: plain → Sym (dispatchable), `^`-prefixed → Str
/// (no rule pattern can match a Str, so it is dropped).
#[test]
fn sem_s4_bootstrap_symbols_and_caret_strings() {
    assert!(matches!(make_value("boot"), Value::Sym(_)));
    assert!(matches!(make_value("^boot"), Value::Str(_)));
    let src = "lib t { rule r = when boot => emit (seen) }";
    let hit = run_src_msgs(src, &["boot"], 100).unwrap();
    assert_eq!(hit.steps, 2);
    let dropped = run_src_msgs(src, &["^boot"], 100).unwrap();
    assert_eq!(dropped.steps, 1);
    assert!(dropped.emitted.is_empty());
}

// ---------------------------------------------------------------- the δ step

/// [S5] FIFO order: messages are dispatched head-first; every dispatched
/// message (matched or dropped) counts as one step.
#[test]
fn sem_s5_step_fifo_and_step_count() {
    let src = r#"
lib t {
  rule go = when boot => { emit (a); emit (b); emit (c) }
  rule ha = when (a) => emit (a2)
  rule hb = when (b) => { }
}
"#;
    let res = run_src(src).unwrap();
    // dispatch order: boot, a, b, c, a2 — c and a2 are dropped
    let tags: Vec<String> = res.emitted.iter().map(|v| v.repr()).collect();
    assert_eq!(tags, vec!["^a", "^b", "^c", "^a2"]);
    assert_eq!(res.steps, 5);
}

/// [S6] rule selection: the FIRST matching rule in installation
/// (declaration) order fires; same-tag rules behind it never fire.
#[test]
fn sem_s6_step_first_matching_rule_wins() {
    let src = r#"
lib t {
  rule r1 = when boot => { w := 1; emit (done) }
  rule r2 = when boot => { w := 2 }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("w"), Some(&Value::Int(1)));
}

/// [S7] rejection: a message with no matching rule is dropped and the run
/// continues normally — the machine has no stuck/deadlock state.
#[test]
fn sem_s7_step_drop_unmatched_message() {
    let src = "lib t { rule r = when other => emit (x) }";
    let res = run_src_msgs(src, &["boot", "boot"], 100).unwrap();
    assert_eq!(res.steps, 2);
    assert!(res.emitted.is_empty());
    assert!(res.store.is_empty());
    assert!(!res.stopped_by_max_steps);
}

/// [S8] pattern bindings enter the store and persist after the step.
#[test]
fn sem_s8_step_bindings_persist_in_store() {
    let src = r#"
lib t {
  rule go = when boot => emit (rep, 5)
  rule hr = when (rep, m) => { z := m * 2; emit (done) }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("m"), Some(&Value::Int(5)));
    assert_eq!(res.store.get("z"), Some(&Value::Int(10)));
}

// ---------------------------------------------------------------- effects

/// [E1–E4] assign/emit/spawn/retract: σ-update, queue-append, rule
/// installation and removal; an unresolved spawn is silently ignored at
/// runtime (static checks reject it earlier); retract removes the rule.
#[test]
fn sem_s9_eff_assign_emit_spawn_retract() {
    let src = r#"
lib t {
  rule go = when boot => { x := 1; spawn nowhere; spawn hr; emit (done) }
  rule hd = when (done) => { y := x + 1; retract hr }
  rule hr = when (never) => emit (ghost)
  rule h2 = when (never) => emit (after_retract)
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("x"), Some(&Value::Int(1)));
    assert_eq!(res.store.get("y"), Some(&Value::Int(2)));
    // no (never) message was ever dispatched, and hr was retracted anyway
    let tags: BTreeSet<String> = res.emitted.iter().map(|v| v.repr()).collect();
    assert!(!tags.contains("^ghost"));
    assert!(!tags.contains("^after_retract"));
}

/// [E5] `seq(a, b)`: b sees the store produced by a.
#[test]
fn sem_s10_eff_seq_threads_store() {
    let src = r#"
lib t {
  rule go = when boot => seq(x := 1, seq(y := x + 1, emit (done)))
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("y"), Some(&Value::Int(2)));
}

/// [E6] `par(a, b)`: both branches run against the same snapshot
/// (left-to-right, deterministic); disjoint writes merge; a name written to
/// two different values is a hard error.
#[test]
fn sem_s11_eff_par_merge_and_conflict() {
    let ok_src = r#"
lib t {
  rule go = when boot => par(x := 1, y := 2)
}
"#;
    let res = run_src(ok_src).unwrap();
    assert_eq!(res.store.get("x"), Some(&Value::Int(1)));
    assert_eq!(res.store.get("y"), Some(&Value::Int(2)));

    let bad_src = r#"
lib t {
  rule go = when boot => par(x := 1, x := 2)
}
"#;
    let e = err_of(bad_src);
    assert!(e.contains("par: конфликт имён 'x'"), "{e}");
}

/// [E7] `choice(a, b)`: the first branch runs; the second is a fallback for
/// a `ChoiceFail` failure, which nothing in the Rust port produces — so `b`
/// is never evaluated (verified by the 1/0 inside `b`).
#[test]
fn sem_s12_eff_choice_reduces_to_first_branch() {
    let src = r#"
lib t {
  rule go = when boot => choice(emit (a), x := 1/0)
  rule ha = when (a) => emit (done)
}
"#;
    let res = run_src(src).unwrap();
    let tags: Vec<String> = res.emitted.iter().map(|v| v.repr()).collect();
    assert_eq!(tags, vec!["^a", "^done"]);
}

/// [E8] `if c then a else b`: Python truthiness picks the branch. Note:
/// EVOL has no boolean literals — `true`/`false` are ordinary names, and an
/// unbound name evaluates to a Symbol, which is truthy.
#[test]
fn sem_s13_eff_if_truthiness() {
    let src = r#"
lib t {
  rule go = when boot => {
    if 0 then { a := "zero" } else { a := "nonzero" }
    if "" then { b := "empty" } else { b := "nonempty" }
    if -1 then { c := "neg" } else { c := "other" }
    if not 0 then { d := 1 } else { d := 0 }
    if unbound_sym then { e := "sym-truthy" } else { e := "sym-falsy" }
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    let get = |k: &str| res.store[k].repr();
    assert_eq!(get("a"), "'nonzero'");
    assert_eq!(get("b"), "'nonempty'");
    assert_eq!(get("c"), "'neg'");
    assert_eq!(get("d"), "1");
    assert_eq!(get("e"), "'sym-truthy'");
}

/// [E9] `loop(g, b)`: the guard is re-evaluated before every iteration; a
/// false guard skips the body; a never-false guard is cut off by the
/// internal 100_000-iteration limit (hard error, run aborts).
#[test]
fn sem_s14_eff_loop_guarded_and_bounded() {
    let src = r#"
lib t {
  rule go = when boot => {
    i := 0
    loop(i < 4, { i := i + 1 })
    loop(0, raise "unreachable")
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("i"), Some(&Value::Int(4)));

    // a false guard skips the body entirely: `0` is falsy (`false` would NOT
    // be — it is an unbound name, i.e. a truthy Symbol)
    let skipped_ok = r#"
lib t { rule go = when boot => { loop(0, raise "unreachable"); emit (done) } }
"#;
    let res2 = run_src(skipped_ok).unwrap();
    let tags: Vec<String> = res2.emitted.iter().map(|v| v.repr()).collect();
    assert_eq!(tags, vec!["^done"]);

    let inf = r#"lib t { rule go = when boot => loop(1, emit (t)) }"#;
    let e = err_of(inf);
    assert!(e.contains("превышен лимит итераций"), "{e}");
}

/// [E10] `forall x in coll { … }`: list collections only; the loop variable
/// does not leak into the store, but other assignments persist across and
/// after iterations.
#[test]
fn sem_s15_eff_forall_scoping() {
    let src = r#"
lib t {
  rule go = when boot => {
    acc := 0
    forall i in range(0, 3) {
      acc := acc + i
      i := 999
    }
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("acc"), Some(&Value::Int(3)));
    assert!(!res.store.contains_key("i"));

    let bad = r#"lib t { rule go = when boot => forall i in 5 { } }"#;
    let e = err_of(bad);
    assert!(e.contains("коллекция не список"), "{e}");
}

/// [E11] `try a catch x { c }`: catches Interp AND Eval errors and binds
/// the message text to x; the (currently unreachable) ChoiceFail would
/// pass through uncaught.
#[test]
fn sem_s16_eff_try_catch_intercepts_errors() {
    let src = r#"
lib t {
  rule go = when boot => {
    try { x := 1/0 } catch e { msg := e }
    try { raise "boom" } catch e2 { msg2 := e2 }
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("msg").unwrap().repr(), "'деление на 0'");
    assert_eq!(res.store.get("msg2").unwrap().repr(), "'boom'");
}

/// [E12] `raise e` outside try/catch halts the whole run with an error.
#[test]
fn sem_s17_eff_raise_aborts_run() {
    let src = r#"lib t { rule go = when boot => { x := 1; raise "boom"; y := 2 } }"#;
    assert_eq!(err_of(src), "boom");
}

/// [E13] call-as-effect: the expression is evaluated for its effect
/// (console.print lands in the captured output), the result is discarded
/// and the store is untouched by the call itself.
#[test]
fn sem_s18_eff_call_discards_result() {
    let src = r#"
lib t {
  rule go = when boot => {
    console.print("hello", 1, 2)
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.output, "hello 1 2\n");
    assert!(!res.store.contains_key("console"));
}

// ---------------------------------------------------------------- expressions

/// [X1] an unbound name evaluates to its own Symbol (no "undefined" error).
#[test]
fn sem_s19_expr_unbound_name_is_symbol() {
    let src = r#"lib t { rule go = when boot => { n := ghost; emit (done) } }"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("n"), Some(&Value::sym("ghost")));
}

/// [X2] numeric tower: Bool acts as 0/1 (there are no boolean literals —
/// Bools come from comparisons); `/` is Python floor division; Float
/// contaminates to Float; `*` repeats str/list; `+` concatenates.
#[test]
fn sem_s20_expr_numeric_tower_and_floor_division() {
    let src = r#"
lib t {
  rule go = when boot => {
    a := (1 == 1) + 1
    b := 7 / 2
    c := -7 / 2
    d := 7.0 / 2
    e := "ab" * 3
    f := [1] + [2]
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    let get = |k: &str| res.store[k].repr();
    assert_eq!(get("a"), "2");
    assert_eq!(get("b"), "3");
    assert_eq!(get("c"), "-4");
    assert_eq!(get("d"), "3.0");
    assert_eq!(get("e"), "'ababab'");
    assert_eq!(get("f"), "[1, 2]");
    // division by zero is a hard error
    assert_eq!(
        err_of(r#"lib t { rule go = when boot => x := 1/0 }"#),
        "деление на 0"
    );
}

/// [X3] equality is Python-structural (True == 1, 1 == 1.0, Sym ≠ Str);
/// ordering is defined on numbers and strings only.
#[test]
fn sem_s21_expr_equality_and_ordering() {
    let src = r#"
lib t {
  rule go = when boot => {
    a := (1 == 1) == 1
    b := 1 == 1.0
    c := boot == "boot"
    d := "a" < "b"
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    let get = |k: &str| res.store[k].repr();
    assert_eq!(get("a"), "True");
    assert_eq!(get("b"), "True");
    assert_eq!(get("c"), "False");
    assert_eq!(get("d"), "True");
    // comparing a symbol with a number is a type error
    let bad = r#"lib t { rule go = when boot => x := unbound < 2 }"#;
    let e = err_of(bad);
    assert!(e.contains("'<' not supported"), "{e}");
}

/// [X4] `and`/`or` are strict: both operands are evaluated, so an error on
/// the right side surfaces even when the left side already decides.
#[test]
fn sem_s22_expr_and_or_strict() {
    let src = r#"lib t { rule go = when boot => x := 1/0 == 1 and false }"#;
    assert_eq!(err_of(src), "деление на 0");
    let src2 = r#"lib t { rule go = when boot => x := false or 1/0 == 1 }"#;
    assert_eq!(err_of(src2), "деление на 0");
}

/// [X5] indexing is Python-like (negative indices), out-of-range is an error.
#[test]
fn sem_s23_expr_indexing() {
    let src = r#"
lib t {
  rule go = when boot => {
    xs := [10, 20, 30]
    a := xs[-1]
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("a"), Some(&Value::Int(30)));
    let bad = r#"lib t { rule go = when boot => { xs := [1]; x := xs[5] } }"#;
    assert_eq!(err_of(bad), "index out of range");
}

/// [X6] `match` picks the first arm whose tag pattern fits and binds fields;
/// the pattern grammar admits only tags/tuples/`_` (a literal-int arm is a
/// parse error); a non-matching scrutinee yields None (Unit).
#[test]
fn sem_s24_expr_match_arms_and_none() {
    // a literal-int arm is not part of the pattern grammar
    let bad = r#"
lib t {
  rule go = when boot => {
    w := match (5) { 99 => 1 }
    emit (done)
  }
}
"#;
    assert!(parse(bad, "t").is_err());

    let src = r#"
lib t {
  rule go = when boot => {
    v := match (Circle(2.5)) { Circle(r) => r; _ => 0 }
    w := match (5) { _ => 7 }
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("v"), Some(&Value::Float(2.5)));
    assert_eq!(res.store.get("w"), Some(&Value::Int(7)));
}

/// [X7] closures capture the store by value; arity mismatches are errors.
#[test]
fn sem_s25_expr_closures() {
    let src = r#"
lib t {
  rule go = when boot => {
    k := 10
    f := fun (a, b) => a + b + k
    v := f(1, 2)
    emit (done)
  }
  rule hd = when (done) => { }
}
"#;
    let res = run_src(src).unwrap();
    assert_eq!(res.store.get("v"), Some(&Value::Int(13)));
    let bad = r#"lib t { rule go = when boot => { f := fun (a) => a; x := f(1, 2) } }"#;
    let e = err_of(bad);
    assert!(e.contains("arity mismatch"), "{e}");
}

// ---------------------------------------------------------------- termination

/// [T1] normal termination: the queue drains; steps/emitted are consistent.
#[test]
fn sem_s26_term_normal_drain() {
    let src = std::fs::read_to_string(sample_path("demo_counter.evol")).unwrap();
    let res = run_src(&src).unwrap();
    assert_eq!(res.steps, 13);
    assert_eq!(res.emitted.len(), 12);
    assert!(!res.stopped_by_max_steps);
    assert_eq!(res.store.get("n"), Some(&Value::Int(5)));
}

/// [T2] budget termination: `max_steps` bounds the number of dispatches;
/// the flag `stopped_by_max_steps` reports it.
#[test]
fn sem_s27_term_max_steps_budget() {
    let src = r#"
lib t {
  rule go = when boot => emit (lp)
  rule hl = when (lp) => emit (lp)
}
"#;
    let res = run_src_msgs(src, &["boot"], 7).unwrap();
    assert_eq!(res.steps, 7);
    assert!(res.stopped_by_max_steps);
}

/// [T3] error halt: an uncaught error aborts the entire run (no partial
/// result is returned), even with messages left in the queue.
#[test]
fn sem_s28_term_error_halt_aborts() {
    let src = r#"
lib t {
  rule go = when boot => { emit (a); raise "boom"; emit (b) }
  rule ha = when (a) => emit (c)
}
"#;
    assert_eq!(err_of(src), "boom");
}

/// [T4] the loop-iteration limit is the robustness bound for unbounded
/// loops (a clean error, not a hang).
#[test]
fn sem_s29_term_loop_iteration_limit() {
    let src = r#"lib t { rule go = when boot => loop(1, emit (t)) }"#;
    let e = err_of(src);
    assert!(e.contains("превышен лимит итераций"), "{e}");
}

/// [T5] conditional completion: there is no explicit halt — a run completes
/// when the queue drains, and programs encode "done vs continue" as a
/// guarded choice of which message to emit (demo_counter: `run` while
/// n < 5, then `done`). An emitted tag with no handler is silently dropped,
/// which terminates that branch of the process.
#[test]
fn sem_s30_term_conditional_completion() {
    let src = std::fs::read_to_string(sample_path("demo_counter.evol")).unwrap();
    let res = run_src(&src).unwrap();
    // the completion signal `done` is emitted exactly when the guard fails
    assert_eq!(
        res.emitted.last().map(|v| v.repr()),
        Some("^done".to_string())
    );
    // an uncovered tag terminates the branch by being dropped
    let orphan = r#"lib t { rule go = when boot => emit (orphan_tag) }"#;
    let res2 = run_src(orphan).unwrap();
    assert_eq!(res2.steps, 2);
    assert_eq!(res2.emitted.len(), 1); // logged, but nothing handled it
}

// ---------------------------------------------------------------- generator

/// SplitMix64-backed generator state (deterministic per seed).
struct Gen {
    rng: Rng,
    /// monotonically increasing id for unique loop-counter names
    next_counter: usize,
    /// how many aux rules the current program declares (spawn/retract targets)
    n_rules: usize,
}

impl Gen {
    fn new(seed: u64) -> Gen {
        Gen {
            rng: Rng::new(seed),
            next_counter: 0,
            n_rules: 0,
        }
    }

    fn below(&mut self, n: usize) -> usize {
        if n <= 1 {
            0
        } else {
            self.rng.randint(0, n as i64 - 1) as usize
        }
    }

    fn int(&mut self, lo: i64, hi: i64) -> i64 {
        self.rng.randint(lo, hi)
    }
}

/// Small vocabulary of variables, tags and rule names shared by the generator.
const GEN_VARS: [&str; 5] = ["v0", "v1", "v2", "v3", "v4"];
const GEN_TAGS: [&str; 6] = ["t0", "t1", "t2", "t3", "t4", "t5"];
const GEN_RULES: [&str; 4] = ["aux0", "aux1", "aux2", "aux3"];

/// A random well-formed EVOL program: parses, every spawn/retract targets a
/// declared rule, loops are counter-bounded, no recursion through closures,
/// no I/O or FFI modules. Guaranteed to terminate under a step budget.
fn gen_program(g: &mut Gen) -> String {
    let mut src = String::from("lib g {\n");

    // boot rule: initialize every variable, then emit a few tags
    src.push_str("  rule boot = when boot => {\n");
    for v in GEN_VARS {
        src.push_str(&format!("    {v} := {}\n", g.int(0, 9)));
    }
    for _ in 0..(1 + g.below(3)) {
        let t = GEN_TAGS[g.below(GEN_TAGS.len())];
        src.push_str(&format!("    emit ({t})\n"));
    }
    src.push_str("  }\n");

    // 2-4 auxiliary rules with (possibly tuple) patterns
    g.n_rules = 2 + g.below(GEN_RULES.len() - 1);
    for name in GEN_RULES.iter().take(g.n_rules) {
        let t = GEN_TAGS[g.below(GEN_TAGS.len())];
        let pat = if g.below(2) == 0 {
            t.to_string()
        } else {
            format!("({t}, m)")
        };
        src.push_str(&format!("  rule {name} = when {pat} => "));
        src.push_str(&gen_effect(g, 0, None));
        src.push('\n');
    }
    src.push_str("}\n");
    src
}

/// Pick a variable from the pool, never `skip`.
fn pick_var(g: &mut Gen, skip: Option<&str>) -> String {
    loop {
        let v = GEN_VARS[g.below(GEN_VARS.len())];
        if Some(v) != skip {
            return v.to_string();
        }
    }
}

/// Generate one effect wrapped in a block. `skip` forbids assigning to that
/// variable (used to keep loop counters monotone).
fn gen_effect(g: &mut Gen, depth: usize, skip: Option<&str>) -> String {
    // at max depth stick to simple statements
    let kind = if depth >= 2 { g.below(3) } else { g.below(11) };
    match kind {
        0..=3 => {
            let v = pick_var(g, skip);
            let e = gen_expr(g, depth);
            format!("{{ {v} := {e} }}")
        }
        4 => {
            let t = GEN_TAGS[g.below(GEN_TAGS.len())];
            format!("{{ emit ({t}) }}")
        }
        5 => {
            let t = GEN_TAGS[g.below(GEN_TAGS.len())];
            let n = g.int(0, 20);
            format!("{{ emit ({t}, {n}) }}")
        }
        6 => {
            let a = gen_effect(g, depth + 1, skip);
            let b = gen_effect(g, depth + 1, skip);
            let c = gen_cond(g, depth);
            format!("{{ if {c} then {a} else {b} }}")
        }
        7 => {
            let a = gen_effect(g, depth + 1, skip);
            let b = gen_effect(g, depth + 1, skip);
            format!("{{ seq({a}, {b}) }}")
        }
        8 => {
            // par over disjoint variables: keeps the merge well-defined
            let v1 = pick_var(g, skip);
            let mut v2 = pick_var(g, skip);
            while v2 == v1 {
                v2 = pick_var(g, skip);
            }
            let n1 = g.int(0, 50);
            let n2 = g.int(0, 50);
            format!("{{ par({v1} := {n1}, {v2} := {n2}) }}")
        }
        9 => {
            // counter-bounded loop with a globally unique counter name
            let c = format!("c{}", g.next_counter);
            g.next_counter += 1;
            let bound = g.int(1, 6);
            let body = gen_effect(g, depth + 1, Some(&c));
            format!("{{ {c} := 0; loop({c} < {bound}, {{ {c} := {c} + 1; {body} }}) }}")
        }
        10 => {
            let name = GEN_RULES[g.below(g.n_rules)];
            if g.below(2) == 0 {
                format!("{{ spawn {name} }}")
            } else {
                format!("{{ retract {name} }}")
            }
        }
        _ => {
            // try/catch around a possibly-failing expression assignment
            let v = pick_var(g, skip);
            let e = gen_expr(g, depth);
            format!("{{ try {{ {v} := {e} }} catch err {{ {v} := 0 }} }}")
        }
    }
}

/// A comparison expression (used for `if` guards).
fn gen_cond(g: &mut Gen, depth: usize) -> String {
    let l = gen_expr(g, depth);
    let r = gen_expr(g, depth);
    let ops = ["<", ">", "==", "!=", "<=", ">="];
    format!("{l} {} {r}", ops[g.below(ops.len())])
}

/// A random (mostly arithmetic) expression over the variable pool.
fn gen_expr(g: &mut Gen, depth: usize) -> String {
    if depth >= 2 {
        return match g.below(3) {
            0 => GEN_VARS[g.below(GEN_VARS.len())].to_string(),
            1 => g.int(0, 20).to_string(),
            _ => format!("\"s{}\"", g.below(3)),
        };
    }
    match g.below(10) {
        0..=3 => {
            let ops = ["+", "-", "*", "/"];
            let l = gen_expr(g, depth + 1);
            let r = gen_divisor(g, depth + 1);
            format!("({l} {} {r})", ops[g.below(ops.len())])
        }
        4 => GEN_VARS[g.below(GEN_VARS.len())].to_string(),
        5 => g.int(0, 20).to_string(),
        6 => format!("len([{}, {}])", g.int(0, 9), g.int(0, 9)),
        7 => format!("abs({})", g.int(-9, 9)),
        8 => {
            let fns = ["min", "max"];
            let f = fns[g.below(fns.len())];
            format!("{f}({}, {})", g.int(0, 9), g.int(0, 9))
        }
        _ => format!("\"s{}\"", g.below(3)),
    }
}

/// Divisor expression: either a nonzero literal or a variable (a zero value
/// there surfaces as a clean runtime error, which is an allowed outcome).
fn gen_divisor(g: &mut Gen, depth: usize) -> String {
    if g.below(2) == 0 {
        return g.int(1, 9).to_string();
    }
    gen_expr(g, depth)
}

// ---------------------------------------------------------------- properties

/// Names a program actually declares for the store: assigned names, rule
/// pattern fields, catch variables. (A `forall` variable is NOT included:
/// it is filtered out of the store after every iteration.)
fn declared_names(src: &str) -> Option<BTreeSet<String>> {
    let ast = parse(src, "t").ok()?;
    let mut names = BTreeSet::new();

    fn walk_pat(expr: &Expr, names: &mut BTreeSet<String>) {
        if let Expr::Tuple { items, .. } = expr {
            for item in items.iter().skip(1) {
                if let Expr::Name { value, .. } = item {
                    names.insert(value.clone());
                }
            }
        }
    }

    fn walk_eff(e: &Eff, names: &mut BTreeSet<String>) {
        match e {
            Eff::Assign { name, .. } => {
                names.insert(name.clone());
            }
            Eff::ForEach { body, .. } => {
                // the loop variable itself never reaches the store, but the
                // body may declare other names
                walk_eff(body, names);
            }
            Eff::TryCatch {
                body,
                catch_var,
                catch_body,
                ..
            } => {
                names.insert(catch_var.clone());
                walk_eff(body, names);
                walk_eff(catch_body, names);
            }
            Eff::Block { stmts, .. } => {
                for s in stmts {
                    walk_eff(s, names);
                }
            }
            Eff::Seq { a, b, .. } | Eff::Par { a, b, .. } | Eff::Choice { a, b, .. } => {
                walk_eff(a, names);
                walk_eff(b, names);
            }
            Eff::Loop { body, .. } => walk_eff(body, names),
            Eff::If {
                then_branch,
                else_branch,
                ..
            } => {
                walk_eff(then_branch, names);
                walk_eff(else_branch, names);
            }
            _ => {}
        }
    }

    fn walk_decls(decls: &[Decl], names: &mut BTreeSet<String>) {
        for d in decls {
            match d {
                Decl::Rule(r) => {
                    walk_pat(&r.pat, names);
                    walk_eff(&r.body, names);
                }
                Decl::Lib(l) => walk_decls(&l.decls, names),
                // imported modules would contribute their own names; the
                // purity property below skips such programs explicitly
                _ => {}
            }
        }
    }

    walk_decls(&ast, &mut names);
    Some(names)
}

/// Property: determinism — the same initial configuration and input sequence
/// produce the identical final configuration (rendered as a canonical hash
/// string), across the whole sample corpus and randomized programs, including
/// error outcomes.
#[test]
fn prop_determinism_same_config_same_result() {
    // 1) the whole sample corpus. Every `run` re-seeds its context, so even
    //    random-using samples must be deterministic run-to-run.
    let names = sample_names();
    assert!(names.len() >= 25, "expected the full sample corpus");
    for name in &names {
        let path = sample_path(name);
        let src = std::fs::read_to_string(&path).unwrap();
        if performs_io(&src) {
            continue; // file/os samples touch the host filesystem
        }
        let first = canonical_outcome(&src, &["boot"], 2000, &samples_dir());
        let second = canonical_outcome(&src, &["boot"], 2000, &samples_dir());
        assert_eq!(first, second, "{name}: run-to-run mismatch");
        // for the samples that finish within the budget, a longer budget
        // must not change the result (the trace up to the stop is the same)
        if first.starts_with("steps=") && !first.contains("stopped=true") {
            let longer = canonical_outcome(&src, &["boot"], 100_000, &samples_dir());
            assert_eq!(first, longer, "{name}: budget-sensitive result");
        }
    }

    // 2) randomized programs with randomized bootstrap sequences
    for seed in 0..30u64 {
        let mut g = Gen::new(seed ^ 0xA5A5_5A5A);
        let src = gen_program(&mut g);
        let n_msgs = 1 + g.below(3);
        let msgs: Vec<String> = (0..n_msgs)
            .map(|_| {
                if g.below(4) == 0 {
                    format!("^{}", GEN_TAGS[g.below(GEN_TAGS.len())])
                } else {
                    GEN_TAGS[g.below(GEN_TAGS.len())].to_string()
                }
            })
            .collect();
        let refs: Vec<&str> = msgs.iter().map(String::as_str).collect();
        let first = canonical_outcome(&src, &refs, 2000, ".");
        let second = canonical_outcome(&src, &refs, 2000, ".");
        assert_eq!(first, second, "seed {seed}: run-to-run mismatch\n{src}");
    }
}

/// Property: purity — a transition changes only the declared process state,
/// there are no hidden global effects.
#[test]
fn prop_purity_no_hidden_state_or_effects() {
    // (a) the final store contains only names the program declared
    let names = sample_names();
    for name in &names {
        let path = sample_path(name);
        let src = std::fs::read_to_string(&path).unwrap();
        if performs_io(&src) {
            continue; // file/os samples touch the host filesystem
        }
        // skip programs with imports: imported modules contribute their own
        // declared names (only concurrent_fanout.evol, which errors at load)
        let has_import = src.lines().any(|l| l.trim_start().starts_with("import "));
        if has_import {
            continue;
        }
        let Some(want) = declared_names(&src) else {
            continue; // invalid samples are rejected before the machine starts
        };
        let Ok(ast) = parse(&src, &path) else {
            continue;
        };
        let Ok(res) = run(&ast, &["boot"], 2000, EnforceTypes(false), &samples_dir()) else {
            continue; // error-halting samples never expose a store
        };
        for k in res.store.keys() {
            assert!(
                want.contains(k),
                "{name}: store key {k:?} was never declared by the program"
            );
        }
    }

    // (b) evaluation is functional: same (expr, store) -> same value, the
    // store snapshot is unchanged, and the result does not depend on hidden
    // context state (a fresh context vs an RNG-dirtied, step-advanced one).
    let sigma: Store = [
        ("x", Value::Int(3)),
        ("y", Value::str_val("s")),
        ("xs", Value::list(vec![Value::Int(1), Value::Int(2)])),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect();
    let exprs = [
        "x + 4 * 2",
        "len(xs) + x",
        "[x, x + 1, y]",
        "(x, y)",
        "min(x, 10) - abs(-x)",
        "x / 2",
        "-x",
        "not x",
        "x < 5 and y == \"s\"",
        "match (Wrap(x)) { Wrap(v) => v * 2; _ => 0 }",
    ];
    for expr in exprs {
        let wrapped = format!("rule r = when boot => z := ({expr})");
        let ast = parse(&wrapped, "t").unwrap();
        let Decl::Rule(r) = &ast[0] else {
            panic!("rule expected")
        };
        let Eff::Assign { value, .. } = &r.body else {
            panic!("assign expected")
        };
        let snapshot = sigma.clone();
        let mut ctx_fresh = Ctx::new(EnforceTypes(false));
        let mut ctx_dirty = Ctx::new(EnforceTypes(false));
        ctx_dirty.rng.randint(0, 1_000_000); // consume hidden RNG state
        ctx_dirty.sim_step = 777;
        let v1 = evol::interp::evaluate(value, &sigma, &mut ctx_fresh).unwrap();
        let v2 = evol::interp::evaluate(value, &sigma, &mut ctx_dirty).unwrap();
        assert_eq!(v1.repr(), v2.repr(), "hidden state leaked into {expr:?}");
        assert_eq!(sigma, snapshot, "evaluation mutated the store: {expr:?}");
    }

    // (c) interleaved runs do not contaminate each other (fresh context per
    // run; the random-using sample must replay identically)
    let a = std::fs::read_to_string(sample_path("dice_game.evol")).unwrap();
    let b = std::fs::read_to_string(sample_path("epidemic_sim.evol")).unwrap();
    let a1 = canonical_outcome(&a, &["boot"], 100_000, &samples_dir());
    let _b = canonical_outcome(&b, &["boot"], 100_000, &samples_dir());
    let a2 = canonical_outcome(&a, &["boot"], 100_000, &samples_dir());
    assert_eq!(a1, a2, "a previous run changed the result of another run");
}

/// Property: termination — every randomly generated well-formed program
/// terminates under a step budget: `run` always returns (a result or a
/// clean error), the step count respects the budget, and the outcome is
/// stable across a re-run.
#[test]
fn prop_termination_well_formed_programs() {
    for seed in 0..60u64 {
        let mut g = Gen::new(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
        let src = gen_program(&mut g);
        let ast = parse(&src, "gen.evol")
            .unwrap_or_else(|e| panic!("seed {seed}: must parse: {e}\n{src}"));
        let outcome = run(&ast, &["boot"], 500, EnforceTypes(false), ".");
        match &outcome {
            Ok(r) => {
                assert!(r.steps <= 500, "seed {seed}: steps {} over budget", r.steps);
                assert_eq!(
                    r.stopped_by_max_steps,
                    r.steps == 500,
                    "seed {seed}: stop flag inconsistent"
                );
            }
            Err(e) => {
                // a clean error is a terminating outcome
                assert!(
                    matches!(e, evol::EError::Interp(_) | evol::EError::Eval(_)),
                    "seed {seed}: unexpected error kind {e:?}"
                );
            }
        }
        let describe = |r: &Result<evol::RunResult, evol::EError>| match r {
            Ok(r) => canonical(r),
            Err(e) => format!("err={e:?}"),
        };
        let outcome2 = run(&ast, &["boot"], 500, EnforceTypes(false), ".");
        assert_eq!(
            describe(&outcome),
            describe(&outcome2),
            "seed {seed}: unstable outcome\n{src}"
        );
    }
}
