# EVOL — Formal Operational Semantics (v0.3)

**Scope.** This document is the executable truth about the language: an
operational semantics *derived from the actual implementation*
(`src/interp.rs`, `src/value.rs`, `src/parser.rs`, `src/types.rs` — the Rust
v0.3 core, golden-verified against the Python prototype). Where the
implementation has quirks, they are stated as semantics, not smoothed over;
unimplemented constructs are marked honestly. Every numbered rule is pinned
by a test — see the [trace table](#trace-table--spec--tests) at the end.

EVOL is **a model, not a general-purpose language**: one specification is
described → compiled → tested → visualized → exported. The machine below is
the "compiled" and "tested" part of that chain.

**Notation.** `σ ∈ Σ = Name ⇀ Value` is a finite map; `μ ∈ Value*` is a FIFO
queue; evaluation is written `⟦e⟧σ = v` (or `⊥err`); `⊎` is map override
union; `⧺` is list append. Rule IDs `[S#]` (structure/step), `[E#]`
(effects), `[X#]` (expressions), `[T#]` (termination), `[D#]` (determinism /
purity properties).

---

## 1. Values

A `Value` is one of:

| Value | Construction | Truthiness | Notes |
|---|---|---|---|
| `Int(i)` | integer literal | `i ≠ 0` | i64; division by zero is an error, not a wrap |
| `Bool(b)` | result of comparisons / `not` / `and` / `or` | `b` | Python-style subtype of `Int`: `True == 1`, arithmetic coerces to 0/1 |
| `Float(f)` | float literal | `f ≠ 0.0` | f64 |
| `Str(s)` | string literal, `"^…"` bootstrap | `s ≠ ""` | quoted in `repr` |
| `Sym(n)` | bare name in expression position, plain bootstrap string | always | self-quoting symbol `^n`; the language has **no boolean literals** — `true`/`false` are ordinary names, so unbound they evaluate to truthy Symbols `[E8]` |
| `List(vs)` | `[e, …]` | non-empty | immutable |
| `Tuple(vs)` | `(e, …)`, ADT constructor `Tag(args)` | non-empty | `(Sym tag, v1 … vn)` is the runtime shape of an ADT value |
| `Closure` | `fun (p, …) => body` | always | captures the store **by value** at creation `[X7]` |
| `None` | match fallthrough | falsy | Python `None` |

Equality `[X3]` is Python-structural: `True == 1`, `1 == 1.0`, containers
elementwise, `Sym ≠ Str` always, closures by identity. Ordering (`<` etc.)
is defined on numbers and strings only, else `⊥err`.

*Tests:* `value.rs` unit tests (`equality_python_semantics`, `truthiness`,
`repr_python_style`); `sem_s13`, `sem_s19`–`sem_s21`.

## 2. Configurations

A machine configuration is `C = (Σ, μ, Q, κ)`:

- `Σ` — the **store**: `name → value`. Pattern bindings enter it and
  persist `[S8]`.
- `μ` — the **message queue** (FIFO).
- `Q` — the **installed rules**: an ordered list of entries
  `(lib, name, pat, eff)` pointing into the rule table `T`.
- `κ` — the machine context: the step counter `s`, the PRNG state ρ
  (SplitMix64, seeded `0` at every run start), the console output buffer,
  and the `--enforce-types` flag.

The rule table `T` is built at load time `[S1–S3]`:

- top-level `rule r …` → `lib = ""`; `lib L { rule r … }` → `lib = L`;
- `import name` / `import "file.evol"` loads the module (resolution order:
  the importing file's directory, the working directory, `samples/`;
  `.evol` appended when missing). A seen-set guards against import cycles —
  a second import of the same file is skipped;
- a duplicate `(lib, name)` definition **replaces the earlier body at the
  first slot** `[S1]`;
- `import py "module"` is a **load-time error** in the Rust port (no Python
  host) `[S2]`; a missing module is a load-time error `[S3]`;
- `type Name = …` (ADT) declarations have **no runtime effect** — they are
  consumed by the static checker (`src/types.rs`).

Bootstrap `[S4]`: `Σ₀ = ∅`, `Q₀ = T` (table order), `μ₀ = [make_value(m) for
m in bootstrap]` where a plain string becomes `Sym(m)` and a `"^…"`-prefixed
string becomes `Str` (which no pattern can match, i.e. it is guaranteed to
be dropped).

*Tests:* `sem_s1`–`sem_s4`.

## 3. The step relation δ

One δ step (when `s < max_steps` and `μ = m·μ'`):

1. `s := s + 1` (visible as `sim.step()`).
2. `cand(Q, m)` — all installed rules whose pattern matches `m`, in `Q`
   order.
3. `cand = ∅` → **drop**: the message is discarded, the step still counts,
   the run continues `[S5, S7]`. The machine therefore has **no stuck
   state**: rejection is silent and local.
4. Otherwise the **first** candidate fires `[S6]` (rule priority is
   uniformly 0; selection is total order on `Q` — declaration order, with
   spawned installations appended at the end).
5. `β = match(pat, m)`; the body runs in `Σ ⊎ β` — bindings are ordinary
   store names and persist after the step `[S8]`.
6. Under `--enforce-types`, annotated message fields are checked before the
   body; a mismatch is an `Eval` error (halts the run; catchable by
   `try` *inside* the rule body only — the check itself happens before it).
7. The body's effect result `(Σ′, E, S, R)` is applied **after** the body
   completes:

   `C′ = (Σ′, μ′ ⧺ E, (Q ∖ names(R)) ⧺ resolve(S), κ)`

   emissions are appended in evaluation order (and also recorded in the
   run's emission log); a `retract` removes **all** installed copies of the
   named rule; a `spawn` appends one installation of the referenced rule —
   unresolved references are silently ignored at runtime (static checks
   reject them earlier). Since every table rule starts installed, an
   in-effect `spawn` is behaviorally a *re-installation*: inert while the
   rule is installed, meaningful after a `retract` `[E1–E4]`.

Pattern matching (rule `when`-patterns vs message):

- `when t` matches `Sym(t)`;
- `when (t, f1 … fn)` matches `(Sym(t), v1 … vn)` with equal arity and binds
  `fi ↦ vi`; **`_` is not special here** — it binds the store key `"_"` (a
  documented quirk);
- a `Sym` message never matches a tuple pattern and vice versa; `Str`,
  lists and closures match nothing.

*Tests:* `sem_s5`–`sem_s8`, `sem_s9`; golden corpus (`tests/golden.rs`)
pins whole-run traces for 15 sample programs.

## 4. Effects

`eval_eff : Eff → Σ → (Σ′, E, S, R) | ⊥err` — every construct is a total
function from a store snapshot to a store update plus machine mutations
(no effect mutates its input store).

- **[E1] Block** `{ e1 … en }`: thread `σi = ⟦ei⟧σ(i-1)`; `E, S, R`
  concatenate in evaluation order.
- **[E2] Assign** `x := e` (optionally `x : T := e`): `v = ⟦e⟧σ`; under
  `--enforce-types` a mismatch with `T` is an `Eval` error; `Σ′ = Σ[x ↦ v]`.
- **[E3] Emit** `emit e`: append `⟦e⟧σ` to `E`; `Σ` unchanged.
- **[E4] Spawn / Retract**: `S ⊳ (L?, n)` / `R ⊳ n`; `Σ` unchanged.
- **[E5] Seq** `seq(a, b)`: `b` runs in the store produced by `a`.
- **[E6] Par** `par(a, b)`: both branches run against the **same snapshot**,
  left then right (deterministic); the results merge key-wise — a key
  written to two different values is a hard `Interp` error naming the
  key (keys are iterated in sorted order, so which conflict is reported
  first is deterministic); emissions/spawns/retractions concatenate
  left-then-right.
- **[E7] Choice** `choice(a, b)`: `a` runs; `b` is a fallback for a
  `ChoiceFail` failure. **Nothing in the Rust port produces `ChoiceFail`**,
  so `choice(a, b)` currently *is* `a` and `b` is unreachable (verified by
  an unevaluated `1/0` inside `b`). Other errors propagate.
- **[E8] If** `if c then a else b`: Python truthiness of `⟦c⟧σ` picks the
  branch. Unbound names are truthy Symbols — there are no boolean literals.
- **[E9] Loop** `loop(g, b)`: the guard is re-evaluated before every
  iteration (a false guard skips the body entirely); more than `100 000`
  iterations raise a hard `Interp` error (`"loop: превышен лимит
  итераций"`) — the robustness bound for unbounded loops.
- **[E10] ForEach** `forall x in e { … }`: `⟦e⟧σ` must be a `List` (else
  `Interp` error); each item runs the body in `Σ ∪ {x ↦ item}`; afterwards
  every key **except** `x` is merged back — the loop variable never leaks,
  other assignments persist across and after iterations.
- **[E11] TryCatch** `try a catch x { c }`: catches **both** `Interp` and
  `Eval` errors and runs `c` in `Σ ∪ {x ↦ str(err)}`; (the currently
  unreachable) `ChoiceFail` would pass through uncaught.
- **[E12] Raise** `raise e`: `Eval` error carrying `str(⟦e⟧σ)`; outside any
  `try` it halts the whole run.
- **[E13] Call-as-effect** `console.print(…)`, `sim.set_seed(…)`, …: the
  call is evaluated for effect, the result is discarded, `Σ` is unchanged
  by the call itself. Side effects exist only where the stdlib declares
  them: `console` → output buffer, `random` → PRNG (an explicit part of
  `κ`), `sim` → step counter / reseed, `file`/`os` → **real host I/O** (the
  only escape from the machine — used by no property test), `math`,
  `string` → pure.

Note: `if`, `loop`, `emit`, … are **effects only** — there is no expression
level conditional (use `match` for that).

*Tests:* `sem_s9`–`sem_s18`, plus the battery in
`prop_purity_no_hidden_state_or_effects` (b).

## 5. Expressions

`⟦e⟧σ` is a pure read of `σ` (plus the declared stdlib effects above):

- **[X1] Literals**: `Int`, `Float`, `Str`; lists/tuples evaluate
  left-to-right.
- **[X2] Names & arithmetic**: an unbound name evaluates to its own `Sym`
  (`n := ghost` stores `^ghost` — there is no "undefined variable" error).
  Arithmetic follows the Python numeric tower (`Bool` = 0/1, `Float`
  contaminates); **`/` is floor division** (Python `//`; the transpiler
  emits `//`), division by zero is an `Interp` error; `*` repeats
  strings/lists; `+` concatenates strings/lists.
- **[X3] Equality & ordering**: structural Python equality; ordering on
  numbers and strings only, else error.
- **[X4] Logic**: `and` / `or` are **strict** — both operands are evaluated
  (an error on the right surfaces even when the left decides); results are
  `Bool`.
- **[X5] Indexing** `xs[i]`: lists/tuples, `Int` keys (`Bool` coerced),
  Python-style negative indices; out of range is an `Interp` error.
- **[X6] Match** `match e { pat => body; … }`: arms are tag patterns only —
  `Name` (tag or `_`) or `Tuple(Tag, fields…)`, never literal constants (a
  literal arm is a **parse error**); the first matching arm wins and binds
  fields; no arm matching yields `None`.
- **[X7] Functions**: `fun` captures the store by value; calls check arity
  (error on mismatch) and, under `--enforce-types`, parameter annotations.
  `Uppercase(args)` constructs an ADT value `(Sym name, args…)`. Builtins:
  `range(a, b)` (exclusive, `Int`), `len`, `abs`, `min`, `max`, `str`,
  `int`, `float`. Stdlib modules: `console`, `random`, `file`, `sim`,
  `math` (note: `math.sqrt`/`math.pow` return `Int`), `string`, `os`; `py.*`
  is an error in the Rust port.

*Tests:* `sem_s19`–`sem_s25`; the purity battery (b); golden corpus.

## 6. Termination

- **[T1] Normal termination**: `μ` is empty. The run returns
  `(steps, Σ, emission log, console output)`; every dispatched message —
  matched or dropped — counted as a step.
- **[T2] Budget termination**: `steps` reaches `max_steps` (CLI default
  `100 000`, `--max-steps N`) with `μ ≠ ∅`; the result carries
  `stopped_by_max_steps = true`.
- **[T3] Error halt**: any `Interp`/`Eval` error uncaught by `try` aborts
  the **entire** run with `Err` — no partial store is exposed.
- **[T4] Rejection / deadlock-freedom**: two levels. Program level: parse,
  load and type errors reject the program before the machine starts (the
  typechecker genuinely rejects: `src/types.rs`). Message level: an
  unmatched message is dropped and the run continues `[S7]`. Consequently a
  **stuck configuration is unreachable**: from any configuration the step
  relation either fires a rule, drops a message, or the queue is empty.
- **[T5] Robust termination & bounds**: every dispatch is bounded — effect
  trees are finite, `forall` is bounded by the list length, `loop` by the
  `100 000`-iteration limiter `[E9]`, and the number of dispatches by
  `max_steps` `[T2]`. Hence `run` terminates for **every** input within its
  budget, returning a value or a clean error. The single documented hole:
  recursion through stored closures is **not** depth-limited — a mutual
  recursion cycle (`a := fun(n) => b(n); b := fun(n) => a(n); a(0)`)
  overflows the host stack and aborts the process; `try` cannot intercept
  it. Generated-program tests avoid this class; production programs
  currently must too.
- **Conditional completion**: there is no `halt`. A process completes when
  the queue drains, and programs *encode completion* as a guarded choice of
  message: `if n < 5 then { emit (tick); … emit (run) } else { emit (done) }`
  (`samples/demo_counter.evol`). The static property prover (`evol check`,
  P1–P8) proves the completion-relevant facts: every rule reachable from
  `boot` (P4, no dead code) and every emitted tag covered by a handler (P5,
  no guaranteed drops) — otherwise branches end implicitly by `[S7]` drops.

*Tests:* `sem_s26`–`sem_s30`, `prop_termination_well_formed_programs`.

## 7. Determinism and purity (properties)

- **[D1] Determinism**: same (program, bootstrap, budget) → identical
  `(steps, Σ, emission log, console output, stop flag)`. Mechanism: the
  context `κ` is created fresh per run with a fixed seed; the queue is
  FIFO; rule selection is a total order on `Q`; the PRNG is an explicit
  part of `κ` (so even random-using programs replay identically per run;
  the sequences differ from CPython's Mersenne twister — a documented
  deviation). This release also fixes the one leak of host nondeterminism:
  the `par` conflict error iterated candidate keys in `HashSet` order, so
  *which* conflicting key an error named could vary between runs; keys are
  now visited in sorted order.
- **[D2] Purity**: a transition changes only the declared process state.
  Rule bodies are evaluated functionally — `evaluate` takes the store by
  shared reference, `eval_eff` returns a new store, and the machine applies
  the collected `(E, S, R)` only after the body completes; values are
  immutable; there is no mutable state outside `κ`, which is owned by the
  run. Consequently (a) the final store contains only names the program
  declared (assignments, pattern fields, catch variables — `forall`
  variables are excluded by construction), (b) expression evaluation gives
  the same value for the same store regardless of "hidden" context state,
  and (c) runs do not contaminate each other. The `file`/`os` modules are
  the designated exception (real I/O) and are excluded from the machine
  properties.
- **[D3] Termination on well-formed programs**: randomly generated
  well-formed programs (bounded effect/expr depth, counter-bounded loops,
  no closure recursion, no I/O) always terminate under a step budget —
  `run` returns a result or a clean error, and re-runs are stable.

*Tests:* `prop_determinism_same_config_same_result`,
`prop_purity_no_hidden_state_or_effects`,
`prop_termination_well_formed_programs` (in `tests/properties.rs`).

## 8. Known deviations & honest limitations

| # | Fact | Where |
|---|---|---|
| 1 | `choice(a, b)` reduces to `a`; the fallback is unreachable (`ChoiceFail` is never produced) | `[E7]` |
| 2 | No boolean literals; `true`/`false` are names → truthy Symbols | `[E8]`, `[X2]` |
| 3 | `/` is floor division (not real division) | `[X2]` |
| 4 | `and`/`or` are strict (no short-circuit) | `[X4]` |
| 5 | `_` in a `when`-pattern binds the store key `"_"` | §3 |
| 6 | Match-expr arms are tag-patterns only; a literal arm is a parse error; no match yields `None` | `[X6]` |
| 7 | Duplicate `(lib, name)` rule definition replaces the body at the first slot | `[S1]` |
| 8 | `math.sqrt`/`math.pow` return `Int` | `[X7]` |
| 9 | A `"^…"` bootstrap string matches nothing (guaranteed drop) | `[S4]` |
| 10 | Unresolved `spawn` is a runtime no-op (static checks reject it) | §3 |
| 11 | `import py` (FFI) is unavailable in the Rust port — load-time error | `[S2]` |
| 12 | Closure-recursion depth is unbounded → host stack overflow aborts the process (not catchable) | `[T5]` |
| 13 | `random.*` is SplitMix64, seeded 0 per run — same contract as the Python `random`, different numbers | `[D1]` |
| 14 | REPL, actor runtime and metrics tooling are **not ported** (roadmap) | README |

## Trace table — spec ⇄ tests

| Rule | Statement (abbreviated) | Tests |
|---|---|---|
| [S1] | duplicate rule def replaces body at first slot | `sem_s1_load_duplicate_rule_replaced_in_place` |
| [S2] | `import py` → load-time error | `sem_s2_load_py_import_unavailable`, `ffi_py_reports_unavailable` (golden) |
| [S3] | missing module → load-time error | `sem_s3_load_module_not_found` |
| [S4] | bootstrap: plain→Sym, `^`→Str (dropped) | `sem_s4_bootstrap_symbols_and_caret_strings` |
| [S5] | FIFO dispatch; every dispatch counts a step | `sem_s5_step_fifo_and_step_count` |
| [S6] | first matching rule in `Q` order fires | `sem_s6_step_first_matching_rule_wins`, golden P6 (tag conflicts) |
| [S7] | unmatched message dropped; run continues; no stuck state | `sem_s7_step_drop_unmatched_message` |
| [S8] | pattern bindings persist in the store | `sem_s8_step_bindings_persist_in_store`, golden `chat_router` store |
| [E1–E4] | block/assign/emit/spawn/retract | `sem_s9_eff_assign_emit_spawn_retract` |
| [E5] | `seq` threads the store | `sem_s10_eff_seq_threads_store` |
| [E6] | `par` snapshot-merge; conflict → deterministic error | `sem_s11_eff_par_merge_and_conflict` |
| [E7] | `choice` ≡ first branch (fallback unreachable) | `sem_s12_eff_choice_reduces_to_first_branch` |
| [E8] | `if` by truthiness; symbols truthy; no bool literals | `sem_s13_eff_if_truthiness` |
| [E9] | `loop` guard-first; 100 000-iteration bound | `sem_s14_eff_loop_guarded_and_bounded`, `sem_s29` |
| [E10] | `forall` list-only; loop var excluded from store | `sem_s15_eff_forall_scoping` |
| [E11] | `try/catch` intercepts Interp+Eval, binds message | `sem_s16_eff_try_catch_intercepts_errors` |
| [E12] | `raise` outside try halts the run | `sem_s17_eff_raise_aborts_run` |
| [E13] | call-as-effect discards result; console → buffer | `sem_s18_eff_call_discards_result` |
| [X1–X7] | expression semantics | `sem_s19`…`sem_s25` (`…_expr_*`), purity battery (b) |
| [T1] | normal termination on drain | `sem_s26_term_normal_drain`, golden run cases |
| [T2] | budget termination + `stopped_by_max_steps` | `sem_s27_term_max_steps_budget` |
| [T3] | error halt aborts the run | `sem_s28_term_error_halt_aborts` |
| [T4] | loop-iteration limiter as robustness bound | `sem_s29_term_loop_iteration_limit` |
| [T5] | conditional completion; drops end branches | `sem_s30_term_conditional_completion`, golden P4/P5 |
| [D1] | determinism (corpus + randomized, incl. errors) | `prop_determinism_same_config_same_result` |
| [D2] | purity: only declared state; functional eval; isolated runs | `prop_purity_no_hidden_state_or_effects` |
| [D3] | termination on generated well-formed programs | `prop_termination_well_formed_programs` |
| grammar | lexer/parser errors carry positions | `lexer.rs`/`parser.rs` unit tests, golden parse-error cases |
| transpiler | EVOL → Python byte-identical to prototype | `transpiler_matches_python_byte_for_byte` (golden) |

### Reproducing

```bash
cargo test                          # all 51 tests (golden + semantic + property)
evol run samples/demo_counter.evol boot     # the machine, live
evol check samples/tc_ok.evol               # static P1–P8 properties
```

Property tests are deterministic (fixed generator seeds); nothing in the
test suite touches the host filesystem (I/O-capable samples are excluded).
