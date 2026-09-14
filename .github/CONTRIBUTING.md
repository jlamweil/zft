# Contributing to ZFT

Thank you for your interest in contributing to ZFT (Zero‑Friction Traceability).
We follow a developer‑first, test‑driven workflow and expect contributions to
maintain the project's rigorous, deterministic standards.

## Getting the development environment

```bash
# Clone the repository and cd into it
git clone <repo-url>
cd traceagent

# Install the package in editable mode with dev extras
pip install -e .[dev]
```

The `dev` extra pulls in:

- `ruff` – static analysis and auto‑formatting.
- `pre-commit` – git hooks to enforce linting and the full `zft check` gate.

After installation, set up the pre‑commit hooks:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

## Running the test suite

All tests live under the `tests/` directory and use `pytest`.

```bash
pytest tests -q
```

The test suite is run on every pull request, and the `zft check` gate is
executed as a pre‑push hook to ensure full verification before pushes.

## Code style

We use `ruff` for linting and formatting. The configured rules are defined
in `pyproject.toml` (line‑length 100, selectors E, F, I, W). Run the linter
locally with:

```bash
ruff check src tests
ruff format src tests   # optional auto‑format
```

## Contribution workflow

1. **Branch** – Create a short‑lived branch from `main` for each feature or
   fix (`git checkout -b feat/my‑new‑feature`).
2. **Commit** – Use **Conventional Commits** for clear history:
   - `feat:` new functionality
   - `fix:` bug fix
   - `test:` add or modify tests
   - `docs:` documentation changes
   - `chore:` maintenance tasks (refactoring, CI config, etc.)
   - `release:` version bump / release preparation
3. **Pull Request** – Open a PR against `main` and fill in the template.
   The PR must:
   - Pass all CI checks (lint, test, `zft check`).
   - Include tests that cover new or changed behavior.
   - Update documentation if the public interface changes.
   - Ensure any new clause(s) are added to the appropriate `.zft/specs/`
     and covered by the trace manifest.
4. **Review** – At least one reviewer must approve. Reviewers check for:
   - Deterministic verification (no flaky tests).
   - Complete clause‑to‑element coverage (100% forward and reverse).
   - Adherence to the architecture decisions in `designs/ARCHITECTURE.md`.

## Release process

Releases are performed by the maintainers. The version is bumped according
to Semantic Versioning (`MAJOR.MINOR.PATCH`) and a git tag is created. The
release artefacts are published to PyPI under the `zft` name.

---

*The ZFT project is governed by the Apache 2.0 license. By contributing you
authorize us to distribute your contributions under the same license.*
