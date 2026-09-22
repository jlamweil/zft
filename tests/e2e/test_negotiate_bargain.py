"""E2E: the bargain is real — counter-terms arrive from outside the process.

`zft negotiate --counter-terms <file|->` takes the counter-party's
term sheet as JSON, from a file path or stdin. The sheet's terms become the
recorded counter-proposal, the sheet's decision picks the terminal state
(accept → VALIDATED with the outcome bound to the terms' digest; refuse →
REFUSED with its reason — a terminal state the canned path can never reach),
and a run that countered with a sheet can only be finished by that same
sheet: a plain invocation refuses to invent the counter-party's decision.

Runs against a copy of the repo's .zft tree, never the repo itself.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.negotiate.terms import terms_digest, terms_string

REPO = Path(os.environ.get("ZFT_REPO")
            or Path(__file__).resolve().parents[2])
PY = sys.executable

ACCEPT_SHEET = {"terms": {"budget": "raise timeout to 90s",
                          "clauses": ["GATE-L0"]},
                "decision": "accept"}
REFUSE_SHEET = {"terms": "drop the mutation gate",
                "decision": "refuse", "reason": "outside v0 scope"}


def _store_copy(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(
        REPO / ".zft", root / ".zft",
        ignore=shutil.ignore_patterns("runs", "sandbox*", "cache"),
    )
    return root


def _negotiate(root: Path, *flags, stdin: str | None = None,
               kill_after: str | None = None):
    env = os.environ | ({"ZFT_NEGOTIATE_KILL_AFTER": kill_after}
                        if kill_after else {})
    return subprocess.run(
        [PY, "-m", "zft.cli.main", "negotiate", str(root), *flags],
        input=stdin, capture_output=True, text=True, env=env)


def _sole_run(root: Path) -> list[dict]:
    runs = sorted((root / ".zft" / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {[r.name for r in runs]}"
    return RunLedger.load(runs[0].parent, runs[0].name).events


def test_counter_terms_file_drives_a_real_bargain(tmp_path):
    """A JSON file outside the process: its terms are the recorded counter
    (not the canned sheet) and the validated outcome binds to their digest."""
    root = _store_copy(tmp_path)
    sheet = root / "counter-terms.json"
    sheet.write_text(json.dumps(ACCEPT_SHEET))

    r = _negotiate(root, "--counter-terms", str(sheet))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "negotiation complete: VALIDATED" in r.stdout

    events = _sole_run(root)
    assert [e["event"] for e in events] == \
        ["cfp", "counter", "accept_counter", "validate", "validated"]
    assert events[1]["terms"] == terms_string(ACCEPT_SHEET["terms"]), \
        "the recorded counter-proposal is the sheet's terms"
    outcome = events[-1]
    assert outcome["terms_digest"] == terms_digest(ACCEPT_SHEET["terms"])
    assert outcome["decision"] == "accept"


def test_counter_terms_from_stdin(tmp_path):
    """`--counter-terms -` reads the sheet from stdin — a pipeline, not a file."""
    root = _store_copy(tmp_path)
    r = _negotiate(root, "--counter-terms", "-",
                   stdin=json.dumps(ACCEPT_SHEET))
    assert r.returncode == 0, r.stdout + r.stderr

    events = _sole_run(root)
    assert events[1]["terms"] == terms_string(ACCEPT_SHEET["terms"])
    assert events[-1]["terms_digest"] == terms_digest(ACCEPT_SHEET["terms"])


def test_refuse_decision_ends_refused(tmp_path):
    """The canned protocol never refuses; the sheet's decision must — and a
    refused bargain records its reason instead of a validated outcome."""
    root = _store_copy(tmp_path)
    sheet = root / "counter-terms.json"
    sheet.write_text(json.dumps(REFUSE_SHEET))

    r = _negotiate(root, "--counter-terms", str(sheet))
    assert r.returncode == 1
    assert f"negotiation refused: REFUSED — {REFUSE_SHEET['reason']}" in r.stdout

    events = _sole_run(root)
    assert [e["event"] for e in events] == ["cfp", "counter", "refuse"]
    assert events[1]["terms"] == REFUSE_SHEET["terms"]
    assert events[-1]["reason"] == REFUSE_SHEET["reason"]
    assert not any(e["event"] == "validated" for e in events)


def test_killed_bargain_needs_its_own_sheet_to_finish(tmp_path):
    """A sheet-countered run killed mid-protocol is half a bargain: a plain
    invocation may not invent the counter-party's decision (typed rejection,
    run stays resumable); feeding the same sheet finishes the SAME run."""
    root = _store_copy(tmp_path)
    sheet = root / "counter-terms.json"
    sheet.write_text(json.dumps(REFUSE_SHEET))

    killed = _negotiate(root, "--counter-terms", str(sheet),
                        kill_after="counter")
    assert killed.returncode == -9, "the seam dies by SIGKILL"
    events = _sole_run(root)
    assert [e["event"] for e in events] == ["cfp", "counter"]
    assert events[-1]["terms"] == REFUSE_SHEET["terms"]

    bare = _negotiate(root)
    assert bare.returncode == 1
    assert "invent the counter-party's decision" in bare.stdout
    assert "--counter-terms" in bare.stdout
    events = _sole_run(root)
    assert [e["event"] for e in events] == ["cfp", "counter", "resumed"], \
        "the rejected invocation leaves the run unfinished and resumable"

    resumed = _negotiate(root, "--counter-terms", str(sheet))
    assert resumed.returncode == 1, "the sheet's decision is refuse"
    assert "negotiation refused" in resumed.stdout
    events = _sole_run(root)
    assert [e["event"] for e in events] == \
        ["cfp", "counter", "resumed", "resumed", "refuse"], \
        "the same run is continued to the sheet's terminal state, not restarted"


def test_swapped_sheet_on_resume_is_a_typed_rejection(tmp_path):
    """Resuming with a different sheet must not silently bargain over new
    terms — it is a different bargain, rejected, run left unfinished."""
    root = _store_copy(tmp_path)
    sheet_a = root / "sheet-a.json"
    sheet_a.write_text(json.dumps(ACCEPT_SHEET))
    sheet_b = root / "sheet-b.json"
    sheet_b.write_text(json.dumps({**ACCEPT_SHEET,
                                   "terms": "entirely different terms"}))

    killed = _negotiate(root, "--counter-terms", str(sheet_a),
                        kill_after="counter")
    assert killed.returncode == -9

    swapped = _negotiate(root, "--counter-terms", str(sheet_b))
    assert swapped.returncode == 1
    assert "does not match the recorded counter-proposal" in swapped.stdout
    events = _sole_run(root)
    assert [e["event"] for e in events] == ["cfp", "counter", "resumed"]

    original = _negotiate(root, "--counter-terms", str(sheet_a))
    assert original.returncode == 0, original.stdout + original.stderr


def test_malformed_sheet_is_refused_before_any_run_exists(tmp_path):
    """A document that is not a bargain never opens a run: parse errors are
    usage-level (exit 2), before the ledger or protocol starts."""
    root = _store_copy(tmp_path)
    sheet = root / "counter-terms.json"
    sheet.write_text('{"terms": "x", "decision": "maybe"}')

    r = _negotiate(root, "--counter-terms", str(sheet))
    assert r.returncode == 2
    assert "counter-terms refused" in r.stdout
    assert not (root / ".zft" / "runs").exists()

    absent = _negotiate(root, "--counter-terms", str(root / "no-such.json"))
    assert absent.returncode == 2
    assert "counter-terms refused" in absent.stdout
    assert not (root / ".zft" / "runs").exists()
