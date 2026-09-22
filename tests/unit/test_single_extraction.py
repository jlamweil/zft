"""A3 (P-006a): `check` must extract bindings exactly once.

Plan A3: `run_l2` extracts, the `run_l1` folded into `run_l2` extracts again,
and `cli/main.py` called a third `run_l1` after `run_l2` — three passes.
`run_l2` already folds L1 failures into its own `failures` and now surfaces
the L1 summary (`l1_ok` / `l1_executed`), so the pipeline must call
`extract_bindings` exactly once.
"""
import os
from pathlib import Path

import zft.lineage.extract as extract

REPO = Path(os.environ.get("ZFT_REPO")
       or Path(__file__).resolve().parents[2])


def test_check_extracts_exactly_once(monkeypatch):
    """In-process CLI seam: main(["check", REPO]) → one extraction, rc 0."""
    from zft.cli.main import main

    real = extract.extract_bindings
    calls: list[Path] = []

    def spy(root, *args, **kwargs):
        calls.append(root)
        return real(root, *args, **kwargs)

    monkeypatch.setattr(extract, "extract_bindings", spy)
    rc = main(["check", str(REPO)])
    assert rc == 0, "check must stay green on the live repo"
    assert len(calls) == 1, (
        f"extract_bindings called {len(calls)} times, expected exactly 1 "
        f"(run_l2 → folded run_l1 → dropped standalone run_l1)"
    )
