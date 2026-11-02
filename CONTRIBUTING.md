# Contributing to EVOL

Short rules for a language implementation where the Python prototype is the
reference semantics.

## Ground truth

- **The golden corpus is the contract.** `tests/golden.rs` pins the behaviour
  of the lexer, parser, interpreter, typechecker and transpiler to the original
  Python prototype: steps, store, emitted log, console output, parse errors,
  property lists, transpiled Python. If your change breaks a golden, that is a
  semantic change — regenerate deliberately (`python3 scripts/evol_golden.py &&
  python3 scripts/evol_make_golden_tests.py`), say so loudly in the PR, and
  bump the minor version.
- **Python semantics in the value model is intentional.** `True == 1`,
  `0 == False`, floor division `-7 // 2 == -4`, `str()` falls back to `repr`
  for symbols. Do not "fix" these without regenerating the goldens.
- Deterministic everything: no floats in control flow, no wall-clock in the
  machine step, `random` isolated behind `sim.set_seed`.

## Dev environment

A stable Rust toolchain (1.80+), no other dependencies:

```bash
cargo test
```

Regenerating the goldens additionally needs Python 3.10+ (the reference
interpreter).

## Before you open a PR

- [ ] `cargo fmt --check`
- [ ] `cargo clippy --all-targets -- -D warnings`
- [ ] `cargo test` (goldens green — or regenerated on purpose)
- [ ] New language behaviour has a test (a `samples/*.evol` case is often enough)
- [ ] README updated if the grammar, stdlib or CLI changed

## PR style

Small, single-purpose PRs with a conventional-commit title (`feat:`, `fix:`,
`docs:`, `ci:`, `refactor:`). The PR template asks for the type and the
output-compatibility impact — fill it in and you are done.
