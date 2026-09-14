## Description

<!-- Briefly describe the change and motivation. Reference issues (e.g. Closes #12). -->

## Change type

<!-- Tick the applicable Conventional Commit category that best describes this PR: -->
- [ ] feat
- [ ] fix
- [ ] test
- [ ] docs
- [ ] chore
- [ ] release

## Gate impact

<!--
  ZFT is verification-bound. For every PR, describe:
  - New or modified clause(s) in `.zft/specs/` (alias + UUIDv7, or note "none").
  - Whether forward/reverse coverage of affected clauses stays at 100%.
  - Whether this PR crosses a trust boundary (attestation, DSSE, mutation engine).
-->

## Verification

- [ ] `ruff check src tests` passes
- [ ] `zft lint` passes (L0 static integrity)
- [ ] `zft check` passes (full L2 + Gherkin fallback)
- [ ] New behaviour covered by tests (`pytest tests -q`)
- [ ] Deterministic: the gate result is stable across two consecutive runs
- [ ] No subjective/LLM judgment was used to pass an objective clause

## Documentation

- [ ] Public interface changes reflected in `README.md`
- [ ] Clause schemas / DSL changes captured in `designs/ARCHITECTURE.md`

## Security & provenance

- [ ] No secrets, tokens, or PII introduced
- [ ] No generated/attributed artefacts (`.zft/`, `.zft` runs) committed
