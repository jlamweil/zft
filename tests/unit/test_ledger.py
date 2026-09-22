"""C-03: run ledger — every gate/negotiation run is crash-safe and reproducible.

Seams (plan §1): RunLedger.start() creates the run dir + manifest; append()
writes JSONL with periodic fsync; RunLedger.load() reads back runs, ignoring a
trailing partial line written by a crash (plan C-03).
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from zft.debug.ledger import RunLedger, _git_info


@pytest.fixture()
def runs_root(tmp_path):
    return tmp_path / "runs"


def _git_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@l", "-c", "user.name=t", "commit",
                    "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_start_creates_manifest_and_events(runs_root, tmp_path):
    commit = _git_commit(tmp_path)
    led = RunLedger.start(runs_root, manifest={"tool": "zft", "stage": "L0"},
                          repo=tmp_path)
    assert (Path(led.dir) / "manifest.json").exists()
    manifest = json.loads((Path(led.dir) / "manifest.json").read_text())
    assert manifest["tool"] == "zft"
    assert manifest["git_commit"] == commit
    assert manifest["dirty"] is False
    assert led.run_id in Path(led.dir).as_posix()


def test_append_and_load_round_trip(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"event": "clause_ok", "alias": "TR-FORWARD-COVERAGE"})
    led.append({"event": "verdict", "ok": True})
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest["run_id"] == led.run_id
    assert record.events == [
        {"event": "clause_ok", "alias": "TR-FORWARD-COVERAGE"},
        {"event": "verdict", "ok": True},
    ]


def test_load_ignores_trailing_partial_line(runs_root):
    """Crash-consistency (plan C-03): a torn final write must not poison the run."""
    led = RunLedger.start(runs_root, manifest={})
    led.append({"event": "ok"})
    with open(Path(led.dir) / "events.jsonl", "ab") as fh:
        fh.write(b'{"event": "to')  # torn write, no newline
    record = RunLedger.load(runs_root, led.run_id)
    assert record.events == [{"event": "ok"}]


def test_load_manifest_lost_mid_run_degrades_not_crashes(runs_root):
    """Round-trip proof of the 2026-09-07 check-pipeline incident: an external
    state tidy deleted a live run's manifest between start() and the gate
    pipeline's reload, crashing `check` on a bare FileNotFoundError. Events
    are the evidence and must read back intact; the manifest degrades to {}."""
    led = RunLedger.start(runs_root, manifest={"stage": "check", "tier": "fast"})
    led.append({"event": "l0", "ok": True})
    led.append({"event": "l1", "ok": True, "executed": 1})
    (Path(led.dir) / "manifest.json").unlink()
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest == {}
    assert record.events == [{"event": "l0", "ok": True},
                             {"event": "l1", "ok": True, "executed": 1}]
    # the .events property (the seam gates actually call) survives the same way
    assert led.events == record.events


def test_load_corrupt_manifest_degrades_not_crashes(runs_root):
    led = RunLedger.start(runs_root, manifest={"stage": "L0"})
    led.append({"event": "l0", "ok": False})
    (Path(led.dir) / "manifest.json").write_text('{"stage": "L0"')  # torn JSON
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest == {}
    assert record.events == [{"event": "l0", "ok": False}]


def test_load_vanished_run_still_raises(runs_root):
    """The events file decides existence: repro maps FileNotFoundError to
    no_such_run, so a vanished/never-started run must keep raising."""
    with pytest.raises(FileNotFoundError):
        RunLedger.load(runs_root, "no-such-run")


def test_fsync_every_n_events(runs_root):
    syncs = []
    led = RunLedger.start(runs_root, manifest={}, sync_every=2,
                          syncer=lambda fh: syncs.append(1))
    for i in range(5):
        led.append({"i": i})
    assert len(syncs) == 2, "fsync fires every 2nd event (and not on empty close)"


# --- kill pins, debug/ledger cut (2026-09-16 sitting) -----------------------
# Each pin names the suspect band it kills; the four reviewed equivalents of
# this cut (_default_syncer 1/2, resume 18/21) are waived on the sheet, not
# pinned.

def test_append_before_start_raises_exact_message(tmp_path):
    led = RunLedger(tmp_path / "never-started")
    with pytest.raises(RuntimeError, match=r"^RunLedger\.append before start\(\)$"):
        led.append({"e": 1})


def test_close_unstarted_is_a_noop(tmp_path):
    led = RunLedger(tmp_path / "never-started")
    led.close()


def test_append_after_close_raises_and_close_is_idempotent(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 1})
    led.close()
    with pytest.raises(RuntimeError, match=r"^RunLedger\.append before start\(\)$"):
        led.append({"n": 2})
    led.close()


def test_events_are_key_sorted_jsonl_bytes(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"z": 1, "a": 2})
    led.close()
    raw = (Path(led.dir) / "events.jsonl").read_bytes()
    assert raw == b'{"a": 2, "z": 1}\n'


def test_default_sync_cadence_is_50(runs_root, monkeypatch):
    syncs = []
    monkeypatch.setattr("zft.debug.ledger._default_syncer",
                        lambda fh: syncs.append(1))
    led = RunLedger.start(runs_root, manifest={})  # default sync_every
    for i in range(50):
        led.append({"i": i})
    assert len(syncs) == 1


def test_resume_syncs_on_the_same_default_cadence(runs_root, monkeypatch):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 0})
    led.close()
    syncs = []
    monkeypatch.setattr("zft.debug.ledger._default_syncer",
                        lambda fh: syncs.append(1))
    resumed = RunLedger.resume(runs_root, led.run_id)
    for i in range(50):
        resumed.append({"i": i})
    assert len(syncs) == 1


def test_run_id_is_12_lowercase_hex(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    assert re.fullmatch(r"[0-9a-f]{12}", led.run_id)


def test_manifest_file_is_indented_json_with_run_id(runs_root):
    led = RunLedger.start(runs_root, manifest={"stage": "X"})
    raw = (Path(led.dir) / "manifest.json").read_text()
    m = json.loads(raw)
    assert m["run_id"] == led.run_id
    assert m["stage"] == "X"
    assert raw == json.dumps(m, indent=2)


def test_resume_missing_run_raises_exact_message(runs_root):
    with pytest.raises(FileNotFoundError, match=r"^no such run: ghost$"):
        RunLedger.resume(runs_root, "ghost")


def test_torn_tail_is_truncated_and_its_size_recorded(runs_root):
    """The torn-byte count is contract surface: negotiate/resume.py:90 writes
    it verbatim into the resumed_torn_tail ledger event, so both the
    truncation point and the recorded size are pinned."""
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 1})
    led.append({"n": 2})
    torn = b'{"tor'
    with open(Path(led.dir) / "events.jsonl", "ab") as fh:
        fh.write(torn)
    assert RunLedger.load(runs_root, led.run_id).events == [{"n": 1}, {"n": 2}]
    resumed = RunLedger.resume(runs_root, led.run_id)
    assert resumed._torn_tail_bytes == len(torn)
    resumed.append({"n": 3})
    resumed.close()
    assert RunLedger.load(runs_root, resumed.run_id).events == [
        {"n": 1}, {"n": 2}, {"n": 3}]


def test_resume_intact_file_records_zero_torn_bytes(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 1})
    led.close()
    resumed = RunLedger.resume(runs_root, led.run_id)
    assert resumed._torn_tail_bytes == 0


def test_start_records_zero_torn_bytes(runs_root):
    """A fresh run never reports a torn tail (negotiate/resume.py:90 reads the
    count verbatim into the resumed_torn_tail event); resume() overwrites the
    init value, so this is the only path where it is observable."""
    led = RunLedger.start(runs_root, manifest={})
    assert led._torn_tail_bytes == 0


def test_load_skips_blank_lines_between_events(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 1})
    led.append({"n": 2})
    led.close()
    raw = (Path(led.dir) / "events.jsonl").read_bytes()
    lines = raw.splitlines(keepends=True)
    (Path(led.dir) / "events.jsonl").write_bytes(lines[0] + b"\n" + lines[1])
    assert RunLedger.load(runs_root, led.run_id).events == [{"n": 1}, {"n": 2}]


def test_load_record_carries_the_requested_run_id(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"n": 1})
    led.close()
    assert RunLedger.load(runs_root, led.run_id).run_id == led.run_id


def test_git_info_non_repo_falls_back_to_none_pair(tmp_path):
    assert _git_info(tmp_path) == {"git_commit": None, "dirty": None}


def test_git_info_corrupt_index_still_falls_back(tmp_path):
    """rev-parse HEAD survives a corrupt index; status does not — the whole
    call is best-effort, so the fallback pair is the contract either way."""
    _git_commit(tmp_path)
    (tmp_path / ".git" / "index").write_bytes(b"NOPE")
    assert _git_info(tmp_path) == {"git_commit": None, "dirty": None}


def test_git_info_unborn_head_falls_back(tmp_path):
    """A repo with no commits: rev-parse HEAD fails while status succeeds, so
    only a dropped check on the rev-parse call could skip the fallback — the
    pair must stay {None, None} either way."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert _git_info(tmp_path) == {"git_commit": None, "dirty": None}


def test_git_info_dirty_repo_reports_true(tmp_path):
    _git_commit(tmp_path)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    info = _git_info(tmp_path)
    assert info["dirty"] is True
    assert info["git_commit"]


# GATE-MUTATION-KILL: append-before-start must raise the typed RuntimeError
# with its exact message (append 2/3/4/5), and a fresh ledger's handle
# sentinel must be None — "" (__init__ 4) is falsy but not None, skips the
# check, and dies on AttributeError at the write instead
def test_append_before_start_is_a_typed_runtime_error(runs_root):
    led = RunLedger(runs_root / "never-started")
    assert led._fh is None
    with pytest.raises(RuntimeError) as excinfo:
        led.append({"event": "x"})
    assert str(excinfo.value) == "RunLedger.append before start()"
# GATE-MUTATION-KILL: a fresh ledger's torn-tail counter is exactly 0
# (__init__ 7/8: None / 1)
def test_fresh_ledger_torn_tail_counter_is_zero(runs_root):
    led = RunLedger(runs_root / "fresh")
    assert led._torn_tail_bytes == 0
# GATE-MUTATION-KILL: events are canonical JSONL — sort_keys=True and the
# trailing newline are contractual, checked as raw bytes (append 9/11/12)
def test_events_are_canonical_sorted_jsonl(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"b": 1, "a": 2})
    raw = (Path(led.dir) / "events.jsonl").read_bytes()
    assert raw == b'{"a": 2, "b": 1}\n'
# GATE-MUTATION-KILL: close() must actually close (close 1 inverts the
# guard and leaves the handle writable) and stay closed — close 2 sets
# _fh to "" (falsy, not None), so the idempotent second close crashes
# flushing "" instead of no-oping
def test_close_closes_and_is_idempotent(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"event": "ok"})
    led.close()
    led.close()
    # the None-handle guard reads the same after close as before start
    with pytest.raises(RuntimeError) as excinfo:
        led.append({"event": "after-close"})
    assert str(excinfo.value) == "RunLedger.append before start()"
# GATE-MUTATION-KILL: load() skips blank lines but must KEEP READING —
# 'continue' -> 'break' (load 17) silently drops every event after a
# blank line; and the record carries the run id it was asked for
# (load 21 / RunRecord 1)
def test_load_skips_blank_lines_keeps_reading_and_carries_run_id(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"i": 1})
    led.append({"i": 2})
    path = Path(led.dir) / "events.jsonl"
    raw = path.read_bytes()
    first_nl = raw.index(b"\n") + 1
    path.write_bytes(raw[:first_nl] + b"\n" + raw[first_nl:])
    record = RunLedger.load(runs_root, led.run_id)
    assert record.run_id == led.run_id
    assert record.events == [{"i": 1}, {"i": 2}]
# GATE-MUTATION-KILL: resume() is the crash-recovery seam — the torn-tail
# truncation, its recorded byte count, the restored sync cadence, and the
# unknown-run message are all contractual (resume 9/13/16/21/26)
def test_resume_truncates_torn_tail_and_counts_it(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"i": 1})
    led.append({"i": 2})
    with open(Path(led.dir) / "events.jsonl", "ab") as fh:
        fh.write(b'{"i": 3')  # torn write
    led2 = RunLedger.resume(runs_root, led.run_id)
    assert led2._torn_tail_bytes == len(b'{"i": 3')
    assert led2._sync_every == 50
    led2.append({"i": 3})
    record = RunLedger.load(runs_root, led.run_id)
    assert record.events == [{"i": 1}, {"i": 2}, {"i": 3}]
def test_resume_clean_run_is_a_no_op(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"i": 1})
    led2 = RunLedger.resume(runs_root, led.run_id)
    assert led2._torn_tail_bytes == 0
    led2.append({"i": 2})
    assert RunLedger.load(runs_root, led.run_id).events == [{"i": 1}, {"i": 2}]
def test_resume_unknown_run_message_is_exact(runs_root):
    with pytest.raises(FileNotFoundError) as excinfo:
        RunLedger.resume(runs_root, "no-such-run")
    assert str(excinfo.value) == "no such run: no-such-run"
# GATE-MUTATION-KILL: the torn-tail count measures from the LAST newline
# (resume 26: rfind -> find) — the find variant truncates every complete
# line after the first on a multi-line run
def test_resume_torn_tail_uses_last_newline(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    for i in range(1, 4):
        led.append({"i": i})
    with open(Path(led.dir) / "events.jsonl", "ab") as fh:
        fh.write(b'{"i": 4')
    RunLedger.resume(runs_root, led.run_id)
    assert RunLedger.load(runs_root, led.run_id).events == [
        {"i": 1}, {"i": 2}, {"i": 3}]
# GATE-MUTATION-KILL: start()'s defaults are contractual — sync cadence 50
# (start 1) and the 12-char run id (start 11)
def test_start_defaults_sync_every_and_run_id_shape(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    assert led._sync_every == 50
    assert len(led.run_id) == 12
# GATE-MUTATION-KILL: the manifest file is written in the canonical
# indent=2 form, byte-exact (start 28/30/31) — run manifests are committed
# evidence and churn diffs depend on their byte stability; the dict itself
# is the exact four-key merge (start-line and _git_info happy path)
def test_manifest_is_canonical_indent_two_json(runs_root, tmp_path):
    commit = _git_commit(tmp_path)
    led = RunLedger.start(runs_root, manifest={"stage": "L0"}, repo=tmp_path)
    text = (Path(led.dir) / "manifest.json").read_text()
    parsed = json.loads(text)
    assert text == json.dumps(parsed, indent=2)
    assert parsed == {"git_commit": commit, "dirty": False,
                      "stage": "L0", "run_id": led.run_id}
# GATE-MUTATION-KILL: outside a repo the best-effort git info degrades to
# explicit nulls under the exact keys (_git_info 47-50)
def test_git_info_degrades_to_nulls_outside_a_repo(runs_root, tmp_path):
    led = RunLedger.start(runs_root, manifest={}, repo=tmp_path)
    manifest = json.loads((Path(led.dir) / "manifest.json").read_text())
    assert manifest["git_commit"] is None
    assert manifest["dirty"] is None
    assert set(manifest) == {"git_commit", "dirty", "run_id"}
# GATE-MUTATION-KILL: a dirty repo must read back dirty=True (_git_info
# 23/28: dropping the status cwd makes git run in the process CWD — in any
# tree whose checkout differs from the fixture repo the manifest degrades
# to the null dict and the commit disappears)
def test_manifest_reads_dirty_true_for_dirty_repo(runs_root, tmp_path):
    commit = _git_commit(tmp_path)
    (tmp_path / "uncommitted.txt").write_text("dirty")
    led = RunLedger.start(runs_root, manifest={}, repo=tmp_path)
    manifest = json.loads((Path(led.dir) / "manifest.json").read_text())
    assert manifest == {"git_commit": commit, "dirty": True,
                        "run_id": led.run_id}
