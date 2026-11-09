# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Formal operational semantics** — `docs/semantics.md`: configurations
  `(Σ, μ, Q, κ)`, the δ step relation, effect and expression rules,
  termination (normal, budget, error halt, rejection/drop,
  deadlock-freedom), conditional completion, determinism and purity —
  derived from the actual implementation (honest about quirks, e.g. no
  boolean literals, `choice` fallback unreachable, floor division), with a
  spec ⇄ test trace table.
- **Semantic + property test suite** — `tests/properties.rs` (33 tests):
  - `sem_s*` unit tests pinning every rule of the trace table;
  - `prop_determinism_same_config_same_result` — same configuration and
    input sequence → identical final configuration (full sample corpus +
    randomized programs with randomized bootstraps, including error
    outcomes);
  - `prop_purity_no_hidden_state_or_effects` — a transition changes only
    the declared process state (final store keys ⊆ declared names;
    functional evaluation independent of hidden context state; no
    cross-run contamination);
  - `prop_termination_well_formed_programs` — randomized well-formed
    programs (hand-rolled generator, zero new dependencies) terminate
    under a step budget with stable outcomes.

### Fixed

- `par` name-conflict errors are now deterministic: the reported key was
  picked in `HashSet` iteration order (varies between runs); keys are now
  visited in sorted order. Found by the new determinism property; golden
  outputs are unaffected.

### Changed

- Test count 18 → 51 (18 golden + 33 semantic/property); README badge and
  structure updated; repositioning section ("DSL for stateful processes —
  a model, not a general-purpose language") added to both READMEs.

## [0.3.0] — 2026-11-02

### Added — Rust port of the language core (replaces the Python implementation)

- Rust crate `evol` (lib + `evol` CLI) with zero dependencies: lexer, AST,
  recursive-descent parser, Python-semantics value model, δ-machine interpreter,
  gradual typechecker with the P1–P8 property prover, and the EVOL → Python
  transpiler.
- CLI: `evol run <file.evol> [msg...] [--enforce-types] [--max-steps N]`,
  `evol check <file.evol>` (typecheck + proven properties),
  `evol compile <file.evol> [-o out.py]`.
- **Golden verification against the Python prototype** (18 tests):
  - 15 deterministic `samples/` programs produce byte-identical steps, store,
    emitted log and console output through both interpreters;
  - 4 invalid programs fail to parse with the same error messages
    (Python-style quoting and positions);
  - 5 typechecker cases agree on error counts and proven/failed properties;
  - the transpiler reproduces `compiler.py` output byte for byte;
  - the golden generator lives in the maintainer scripts (`evol_golden.py`,
    `evol_make_golden_tests.py`) and can be re-run against any future change.

### Changed (documented deviations from the Python original)

- `random.*` uses the port's own SplitMix64 PRNG: same contract (seeded,
  deterministic per seed, `sim.set_seed` reseeds), but the number sequences
  differ from CPython's Mersenne twister. Random-using samples
  (`dice_game`, `data_pipeline`, `reliable_channel`, `tcp_handshake`) are
  excluded from the golden corpus for that reason.
- `import py "module"` (Python FFI) reports the same "не зарегистрирован /
  Python host недоступен" error the Python runtime gives without a host —
  a Rust-host FFI is future work.
- Closure `repr` is normalized to `('closure', ...)`: the Python repr was a
  dump of host AST objects with no language semantics.
- Typechecker error messages carry real `line:col` positions for every node
  (the Python AST left them `None` on composite nodes).

### Removed

- The Python sources (`*.py`, `metrics/`, `repl.py`, `runtime_concurrent.py`,
  `test_*.py`, `output_log.txt`) — replaced by the Rust crate. `samples/` is
  kept: it is the golden corpus the tests run against.
- Not ported yet (roadmap in README): interactive REPL with hot reload and
  checkpoints, the concurrent actor runtime (`runtime_concurrent.py`), the
  metrics tooling (`metrics/`, z3-SMT).

[0.3.0]: https://github.com/kostyk348/evol/releases/tag/v0.3.0
