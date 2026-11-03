<div align="center">

# EVOL — a state-transition language (proof of concept)

**An experimental language optimized for the speed of evolving engineering ideas:
every construct is a transition rule of an abstract machine δ(S) → S′, the
semantics is explicit, no "magic".**

[![Release](https://img.shields.io/github/v/release/kostyk348/evol?sort=semver&color=0ea5e9&label=release)](https://github.com/kostyk348/evol/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/kostyk348/evol/ci.yml?branch=master&label=CI)](https://github.com/kostyk348/evol/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-18%20passing%2C%20golden--verified-22c55e)](#the-rust-port-v03)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.80%2B-orange)](https://www.rust-lang.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

English · [Русский](README.ru.md)

</div>

---

The project follows the document chain `lang-design-spec` →
`lang-implementation-roadmap` → `lang-scaling-corpus` (roadmap phases 0–7).
Status: **phases 1–6 complete**, the language core has been ported to Rust
(v0.3, golden-verified against the Python prototype).

## What is implemented

| Phase | Module (Rust) | What it is |
|---|---|---|
| 1 | — (paper) | EBNF grammar + formal abstract-machine semantics (`δ(S)→S′`) |
| 2 | `src/lexer.rs`, `src/ast.rs`, `src/parser.rs` | Lexer + AST + recursive descent |
| 3 | `src/interp.rs`, `src/value.rs` | AST-walking interpreter (`Σ, Μ, Q`) |
| 4 | `src/types.rs` | Typechecker (really rejects errors) + property prover (M5) |
| Option A | `parser.rs`, `interp.rs` | `forall x in expr` + built-ins `range`, `len` — O(1) tokens in N |
| Option D | `interp.rs` | `import` of external modules + qualified `spawn Lib.Rule` |
| Float | `lexer.rs`..`compiler.rs` | `FLOAT` type (dynamic) across the whole stack |
| Error handling | `parser.rs`, `interp.rs` | `try/catch/raise` — catches InterpreterError + EvalError |
| Phase 7 | all modules | **Type annotations**: static checking (Int/Str/Bool/Float/Sym/List[T]/Top) + optional runtime enforcement via `--enforce-types` |
| ADT | `ast.rs`, `parser.rs`, `interp.rs`, `types.rs` | `type Name = A(x:T) \| B \| …`, constructors `Circle(3.0)`, tag matching |
| Transpiler | `src/compiler.rs` | EVOL → Python (same output as the prototype — golden-verified) |

## The Rust port (v0.3)

The prototype was Python 3.10+ (core ~2700 lines + REPL/metrics). The language
core — lexer, parser, interpreter, typechecker, transpiler — is ported to Rust
with zero dependencies. **Correctness is proven by golden tests against the
original**: `tests/golden.rs` runs the deterministic corpus from `samples/`
through both interpreters and requires bit-identical results (AM steps, store,
emitted log, console output), plus parser errors, typechecker properties and
transpiler output.

| | Python prototype | Rust 0.3 |
|---|---|---|
| dependencies | Python 3.10+ | Rust 1.80+, zero crates |
| tests | suites (z3-dependent ones failed) | 18, all green, golden-verified |
| FFI `import py` | Python callables, sandbox | unavailable (no Python host) — same "not registered" error |
| `random.*` | Mersenne (CPython) | own SplitMix64 — same contract (seed → deterministic sequence), but the numbers differ from CPython |
| REPL / actor runtime / metrics | `repl.py`, `runtime_concurrent.py`, `metrics/` | **not ported** — next step (see CHANGELOG) |

Build and run:

```bash
cargo build --release
evol run samples/demo_counter.evol boot     # execute (13 steps, n=5)
evol check samples/tc_ok.evol               # typechecker + proven properties
evol compile samples/valid1_dispatcher.evol # EVOL → Python
```

---

## Execution model

The abstract machine state is `S = (Σ, Μ, Q)`:
- `Σ` — the store (`name → value`);
- `Μ` — the message queue;
- `Q` — the set of installed rules `when <pat> => <eff>`.

A `δ` step: take the head message, find a matching rule (by pattern tag, max
priority), run the effect. Non-matching messages are dropped.

Effects:
`assign (x := e)` · `emit (m)` · `spawn Name` · `retract Name` ·
`if c then … else …` · `seq(a,b)` · `par(a,b)` (fails on name conflict) ·
`choice(a,b)` · `loop(guard, body)` · `forall x in expr { … }` · built-ins
`range`, `len`, `abs`, `min`, `max`, `str`, `int`, `float`.
`try { … } catch var { … }` · `raise expr` — catches InterpreterError + EvalError.

Stdlib modules: `console` (print), `random` (int/pick/shuffle),
`file` (read/write/exists), `sim` (step/set_seed), `math`
(sqrt/pow/sin/cos/pi/floor/ceil/log), `string`
(split/join/upper/lower/contains/replace/len/at/substr), `os`
(listdir/getcwd/path_exists/mkdir).

Imports: `import ModuleName` (from the file `modulename.evol`). Qualified
spawn: `spawn Lib.Rule` (checked by the typechecker, fires from the external
module).

Example (`samples/demo_counter.evol`):
```evol
lib demo {
  rule start = when boot => {
    n := 0
    emit (run)
  }
  rule step = when run => {
    if n < 5 then { emit (tick); n := n + 1; emit (run) }
             else { emit (done) }
  }
}
```

---

## Static typing (Phase 7)

Type annotations are **optional** and do not change the dynamic semantics —
they drive the static typechecker (`src/types.rs`) and, if requested, runtime
enforcement (`evol run --enforce-types`).

Types: `Int`, `Str`, `Bool`, `Float`, `Sym`, `List[T]`, `Top` (the top type).
Numeric compatibility: `Int <: Float` (an int can be assigned to a float).
The system is **gradual**: unannotated code is typed as `Top` and passes
checking; only positions where the type is known on both sides are checked.

Syntax:

```evol
lib t {
  rule start = when boot => {
    n : Int := 0                       # variable annotation
    xs : List[Int] := [1, 2, 3]        # list with an element type
    add := fun (a : Int, b : Int) -> Int => a + b   # parameter + return types
    total := add(n, 3)
    emit (go, total)
  }
  rule process = when (go, value : Int) => {   # annotation of an incoming message field
    emit (done)
  }
}
```

What gets rejected:
- assigning a value of an incompatible type (`x : Int := "s"`);
- a call argument not matching the annotated parameter (`f("s")` given `f(x:Int)`);
- a function result not matching `-> T`;
- incompatible operands of arithmetic/comparison.

Runtime enforcement (`--enforce-types`) catches the same mismatches at runtime
(including annotated message fields from `match`). It is off by default — the
language stays dynamic, as intended for a proof of concept.

## Property prover (M5)

`evol check` prints the properties automatically provable from a single
program definition (P1–P8): spawn/retract validity, type safety, reachability
of every rule from `boot` (no dead code), emit-tag coverage by handlers,
determinism of rule selection (no conflicting when-tags), exhaustive ADT
match, ADT constructor arity.

## Metric results (Python-prototype runs)

> Metrics M1–M5 and corpus #2 were measured on the Python prototype
> (`metrics/`, not ported). The language semantics did not change
> (golden-verified), so the results remain relevant to the grammar;
> runtime renumbering does not affect them.

### Run #1 (scaling corpus, leaked)

> Metric fairness (see caveat #2): the Python baseline comes in two flavors.
> **naive** — explicitly unrolling N dispatch branches; **idiomatic** — a
> `dict`/dispatcher function at O(1) tokens. M1 vs naive underestimates
> Python — look at **M1_fair**.

| Metric | Zone | Raw numbers | Shape M(N) |
|---|---|---|---|
| M1 vs naive-Py (unrolled) | excellent* | dispatcher=0.61, FSM=0.11, pipeline=0.18, fanout=0.19, router=0.18 | flat |
| **M1_fair vs idiomatic-Py (O(1))** | good (parity) | dispatcher=0.61, FSM=0.69, pipeline=0.69, fanout=**1.83**, router=0.69 | flat |
| M1 compression vs Rust | excellent | dispatcher=0.49, FSM=0.12, pipeline=0.24, fanout=0.21, router=0.23 | flat |
| M2 recombination | excellent | 100% of pairs compose | flat |
| M3 entropy | fair/good | ratio=0.70–0.80 vs Python | flat |
| M4 semantic compression | stable | 2–17 tokens per AM step | flat |
| M5 static inference depth (USP) | good | 6–8 properties per run | flat |
| M5-SMT (z3) | excellent | 0–2 per task | n/a |

\* M1 vs naive is inflated artificially (caveat #2).

### Run #2 (held-out corpus, no leakage)

Seeds fixed BEFORE the measurement: `20260713-1`..`20260713-5`. Grammar LOCKED.

| Task | M1_fair@10/100/1000/10000 | M2 | M3 | M5 | M5-SMT |
|--------|-------------------------------|-----|-----|-----|--------|
| dispatcher (DAG) | **0.94 / 0.94 / 0.94 / 0.94** | 100% | 0.682 | 3 | 2 |
| FSM (2 shared vars) | **0.66 / 0.66 / 0.66 / —** | 100% | 0.800 | 4 | 2 |
| pipeline (parallel) | **0.66 / 0.66 / 0.66 / —** | 100% | 0.706 | 4 | 2 |
| **ratelimiter** (NEW) | **0.67 / 0.67 / 0.67 / —** | 100% | 0.819 | 4 | 3 |
| **cache** (NEW) | **0.62 / 0.62 / 0.62 / —** | 100% | 0.666 | 4 | 2 |
| **httprouter** (control) | **0.94** (fixed 50) | 100% | — | 4 | 2 |

Honest conclusion: the hypothesis "EVOL scales without manual unrolling" is
**confirmed** (M1_fair is flat, no curve is superlinear, including N=10000).
But the claim "EVOL is several times more compact than Python" is **wrong**
against the idiomatic baseline — there it is parity. EVOL's value is in the
deterministic AM semantics and M5 inference, not in tokens.

---

## Important caveats

1. **Anti-Goodhart.** Run #1 used a corpus known to the agent-designer.
   Run #2 (corpus #2) is held-out, seeds fixed, grammar LOCKED.
2. **Two baselines, honestly.** M1_naive unrolls N dispatch branches — it
   underestimates Python. ALWAYS look at M1_fair against the idiomatic
   `dict` dispatcher. Both baselines were written by the same agent as EVOL —
   the honest conclusion is **parity with a reasonable baseline**.
3. **M3 entropy is NOT an independent measure.** Variants come from one generator.
4. **M3/M5 at small N.** M3 only for N≤100; M5-SMT for N≤1000 because of the z3 run.
5. **M6 learnability** is not measurable by an agent — it requires live humans.
6. **No main held-out corpus of 15–20 tasks** — the next priority.

---

## Structure

```
evol/
  src/lexer.rs        # tokenization (forall, import, try, raise, FLOAT, type/match, '|', ';')
  src/ast.rs          # AST nodes with positions (Import, PyImport, EnumDecl, Match, ForEach, TryCatch, Raise, Float, Spawn)
  src/parser.rs       # recursive descent -> AST (import, qualified spawn, Call as eff, try/catch/raise, type/match)
  src/value.rs        # values with Python semantics (repr/str, truthiness, numeric tower, floor division)
  src/interp.rs       # δ(S)->S′ + stdlib modules + import .evol (path resolution) + FFI error as in the original
  src/types.rs        # checks + proven_properties() for M5 (P1–P8)
  src/compiler.rs     # EVOL → Python transpilation (bit-identical to compiler.py)
  src/bin/evol.rs     # CLI: run / check / compile
  tests/golden.rs     # golden corpus against the Python prototype (18 tests)
  samples/            # .evol files (simulations, protocols, games, DI, typed_demo)
```

---

## Roadmap

Done:
- [x] Standard library (console, random, file, sim, math, string, os)
- [x] EVOL → Python transpilation
- [x] Error handling (try/catch/raise)
- [x] FLOAT type (dynamic)
- [x] **Types (annotations + static checking, optional runtime enforcement)** — Phase 7
- [x] **Core in Rust, golden-verified against Python** — v0.3

Not ported from Python (next steps):
- [ ] REPL with hot reload and checkpoints (`repl.py`)
- [ ] Actor runtime `runtime_concurrent.py` (content-addressed pub/sub) — the concurrency axis
- [ ] Metrics `metrics/` (corpus generators, z3-SMT)
- [ ] FFI (system calls, networking)
- [ ] Main held-out corpus of 15–20 tasks

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
