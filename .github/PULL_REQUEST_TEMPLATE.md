## What this changes

<!-- One paragraph. Link the issue if there is one: "Closes #12" -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] CI / build / tooling
- [ ] Refactor (no behaviour change)

## Output compatibility

- [ ] Golden corpus untouched (byte-identical semantics)
- [ ] Goldens regenerated on purpose (semantic change — explain, bump minor)

## Checks

- [ ] `cargo fmt --check`
- [ ] `cargo clippy --all-targets -- -D warnings`
- [ ] `cargo test` (golden corpus green)
- [ ] `evol run` / `evol check` smoke on a samples/ program
