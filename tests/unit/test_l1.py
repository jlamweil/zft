"""C-22: L1 — execute property suites bound to clauses, with digest-keyed verdict cache.

Evidence rule (GATE-EVIDENCE-KIND): a property-kind clause accepts evidence only
from an executed suite bound to it via @trace.
"""
import json

import pytest

from traceagent.debug.ledger import RunLedger
from traceagent.gates.l1 import _cache_key, run_l1


def _seed_repo(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "GATE-INV-01", "domain": "g", "title": "expired -> err",
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [{"id": "GATE-INV-01", "statement": "WHEN expired THE SYSTEM SHALL reject",
                        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "gate-inv-01.json").write_text(json.dumps(node))
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert True\n"
    )
    oracle = tmp_path / "oracle_GATE-INV-01.py"
    oracle.write_text("def expired(t):\n    return t > 100\n")
    return tmp_path


# @trace("GATE-EVIDENCE-KIND")
def test_l1_green_passes_on_passing_suite(tmp_path):
    root = _seed_repo(tmp_path)
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L1"}, repo=root)
    verdict = run_l1(root, ledger=led)
    led.close()
    assert verdict.ok, verdict.rejection
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = [e for e in record.events if e["event"] == "l1_clause"]
    assert ev and ev[0]["alias"] == "GATE-INV-01" and ev[0]["ok"] is True


def test_l1_cache_hit_skips_execution(tmp_path):
    # no ledger: _seed_repo's workspace is tmp_path itself, and any write
    # inside it — ledger included — (correctly) invalidates the tree-digest key
    root = _seed_repo(tmp_path)
    v1 = run_l1(root)
    assert v1.executed == 1

    v2 = run_l1(root)
    assert v2.executed == 0, "second run must hit verdict cache"
    assert v2.ok is True


def test_cache_key_distinguishes_inputs():
    k1 = _cache_key("TR-A", "b1", "oracle1")
    k2 = _cache_key("TR-A", "b2", "oracle1")
    k3 = _cache_key("TR-A", "b1", "oracle2")
    assert k1 != k2 and k1 != k3


def test_l1_missing_bound_test_degrades_to_red(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "tests" / "test_bound.py").unlink()
    verdict = run_l1(root)
    assert verdict.ok is False
    assert any("GATE-INV-01" in f for f in verdict.failures)
    assert verdict.rejection["clause_ids"] == ["GATE-INV-01"]


def test_l1_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path):
    root = _seed_repo(tmp_path)
    cache = root / ".traceagent" / "cache" / "l1" / "GATE-INV-01.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{corrupt")
    verdict = run_l1(root)
    assert verdict.ok is True
    assert verdict.executed == 1, "corrupt cache must fall through to execution"


def test_l1_corrupt_store_degrades_to_red(tmp_path):
    root = _seed_repo(tmp_path)
    (root / ".zft" / "specs" / "g" / "gate-inv-01.json").write_text("{broken")
    verdict = run_l1(root)
    assert verdict.ok is False
    assert any("evidence collection failed" in f for f in verdict.failures)


def _add_second_bound_clause(root):
    spec = root / ".zft" / "specs" / "g"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000002",
        "alias": "GATE-INV-02", "domain": "g", "title": "locked -> ok",
        "status": "VALIDATED", "version": 1, "content_hash": "2" * 64,
        "invariants": [{"id": "GATE-INV-02", "statement": "WHEN locked THE SYSTEM SHALL allow",
                        "property": "forall t: locked(t) => validate(t) == ok",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "gate-inv-02.json").write_text(json.dumps(node))
    (root / "tests" / "test_bound_02.py").write_text(
        '# @trace("GATE-INV-02")\n'
        "def test_bound_02():\n    assert True\n"
    )
    oracle = root / "oracle_GATE-INV-02.py"
    oracle.write_text("def locked(t):\n    return t == 'locked'\n\n"
                      "def check():\n    assert locked('locked')\n")


# GATE-MUTATION-KILL: l1.py ok = result.ok and not result.timed_out (and -> or
# survived mutmut 3.7 campaign 2026-09-05: a red suite must red the gate)
def test_l1_red_when_bound_suite_fails(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert False\n"
    )
    verdict = run_l1(root)
    assert verdict.ok is False
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)
    assert verdict.rejection["clause_ids"] == ["GATE-INV-01"]


# GATE-MUTATION-KILL: l1.py emit_clause(False, ...) -> emit_clause(True, ...)
# survived the campaign: the red clause event itself must reach the ledger
def test_l1_no_bound_test_emits_red_clause_event(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "tests" / "test_bound.py").unlink()
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L1"}, repo=root)
    verdict = run_l1(root, ledger=led)
    led.close()
    assert verdict.ok is False
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = [e for e in record.events if e["event"] == "l1_clause"]
    assert ev and ev[0]["alias"] == "GATE-INV-01" and ev[0]["ok"] is False
    assert ev[0]["reason"] == "no bound test"


# GATE-MUTATION-KILL: l1.py executed += 1 -> executed = 1 survived the campaign
def test_l1_executed_counts_each_bound_suite(tmp_path):
    root = _seed_repo(tmp_path)
    _add_second_bound_clause(root)
    verdict = run_l1(root)
    assert verdict.ok is True
    assert verdict.executed == 2, "each executed bound suite counts once"


def _add_manual_clause(root, alias="AAA-MANUAL-00"):
    spec = root / ".zft" / "specs" / "g"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-00000000000a",
        "alias": alias, "domain": "g", "title": "manual review",
        "status": "VALIDATED", "version": 1, "content_hash": "a" * 64,
        "invariants": [{"id": alias, "statement": "WHEN flagged THE SYSTEM SHALL review",
                        "check": {"kind": "manual"}}],
        "external_links": [],
    }
    (spec / "aaa-manual-00.json").write_text(json.dumps(node))


def _add_unbound_property_clause(root, alias="AAA-PROP-00"):
    spec = root / ".zft" / "specs" / "g"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-00000000000b",
        "alias": alias, "domain": "g", "title": "unbound property",
        "status": "VALIDATED", "version": 1, "content_hash": "b" * 64,
        "invariants": [{"id": alias, "statement": "WHEN expired THE SYSTEM SHALL reject",
                        "property": "forall t: expired(t) => validate(t) == err('X')",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "aaa-prop-00.json").write_text(json.dumps(node))


# GATE-MUTATION-KILL: l1.py _cache_key `str(seed)` -> `str(None)` survived the
# campaign: a changed seed must not collide onto the previous verdict entry
def test_cache_key_distinguishes_seed():
    assert _cache_key("TR-A", "b", "o", seed=0) != _cache_key("TR-A", "b", "o", seed=1)


def test_cache_key_distinguishes_tree():
    assert _cache_key("TR-A", "b", "o", tree_digest="t1") != \
        _cache_key("TR-A", "b", "o", tree_digest="t2")


# CACHE-3 unit half: hidden/stateful trees hold caches and runs, not evidence —
# writing the verdict cache itself must not perturb the tree digest, or no
# entry could ever be served twice
def test_tree_digest_ignores_stateful_state(tmp_path):
    from traceagent.gates.l1 import _tree_digest

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return True\n")
    d1 = _tree_digest(tmp_path)
    cache = tmp_path / ".traceagent" / "cache" / "l1"
    cache.mkdir(parents=True)
    (cache / "GATE-INV-01.json").write_text('{"key": "x", "ok": true}')
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "impl.cpython-313.pyc").write_bytes(b"pyc")
    assert _tree_digest(tmp_path) == d1, "cache/bytecode writes must not invalidate"
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return False\n")
    assert _tree_digest(tmp_path) != d1, "a source edit must invalidate"


# CACHE-1 (round trip): green -> poisoned under the live key -> healed ->
# fast-path. A cached failure is re-executed, never replayed; the re-run
# overwrites the poison and the healed entry serves the next check.
def test_l1_poisoned_cache_reheals_roundtrip(tmp_path):
    root = _seed_repo(tmp_path)
    assert run_l1(root).executed == 1
    cache = root / ".traceagent" / "cache" / "l1" / "GATE-INV-01.json"
    entry = json.loads(cache.read_text())
    entry["ok"] = False
    cache.write_text(json.dumps(entry))

    healed = run_l1(root)
    assert healed.ok is True
    assert healed.executed == 1, "a cached failure must re-run, never replay"
    assert json.loads(cache.read_text())["ok"] is True, "re-run must overwrite poison"
    assert run_l1(root).executed == 0, "healed entry fast-paths again"


# CACHE-2: red verdicts are never persisted — a failing suite leaves no cache
# entry behind, so the next check re-executes it (self-healing reds)
def test_l1_red_verdict_is_not_cached(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert False\n"
    )
    assert run_l1(root).ok is False
    cache = root / ".traceagent" / "cache" / "l1" / "GATE-INV-01.json"
    assert not cache.exists(), "a red verdict must not poison later checks"
    assert run_l1(root).executed == 1, "an uncached red re-runs on every check"


# CACHE-3 (round trip): a lying producer (A2) edits the implementation and
# leaves the bound test files untouched — the tree digest invalidates the
# cached green, the regression reds uncached, and reverting replays the
# original green entry for the byte-identical tree.
def test_l1_implementation_change_invalidates_cached_green(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "impl.py").write_text("def f():\n    return True\n")
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "from impl import f\n"
        "def test_bound():\n    assert f() is True\n"
    )
    assert run_l1(root).executed == 1

    (root / "impl.py").write_text("def f():\n    return False\n")
    regressed = run_l1(root)
    assert regressed.executed == 1, "source edit must invalidate the verdict cache"
    assert regressed.ok is False, "regression hidden from suite digests must surface"

    (root / "impl.py").write_text("def f():\n    return True\n")
    reverted = run_l1(root)
    assert reverted.ok is True
    assert reverted.executed == 0, "reverted tree replays the original green entry"


# GATE-MUTATION-KILL: run-level companion to the seed cache-key kill — a seed
# change re-executes the bound suite; the same seed keeps hitting the cache
def test_l1_seed_change_reexecutes_not_cache_hit(tmp_path):
    root = _seed_repo(tmp_path)
    assert run_l1(root, seed=0).executed == 1
    assert run_l1(root, seed=1).executed == 1, "seed is part of the cache key"
    assert run_l1(root, seed=1).executed == 0, "same seed must still cache-hit"


# GATE-MUTATION-KILL: l1.py `continue` -> `break` on the non-property skip
# survived the campaign: a manual clause sorted first must not stop the
# property scan for later clauses
def test_l1_non_property_clause_does_not_stop_property_scan(tmp_path):
    root = _seed_repo(tmp_path)
    _add_manual_clause(root)  # AAA-MANUAL-00 sorts before GATE-INV-01
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert False\n"
    )
    verdict = run_l1(root)
    assert verdict.ok is False
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)


# GATE-MUTATION-KILL: l1.py `continue` -> `break` after the "no bound test"
# emission survived the campaign: an unbound property clause must not mask a
# later bound clause's failure
def test_l1_unbound_clause_does_not_mask_later_bound_failure(tmp_path):
    root = _seed_repo(tmp_path)
    _add_unbound_property_clause(root)  # AAA-PROP-00 sorts before GATE-INV-01
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert False\n"
    )
    verdict = run_l1(root)
    assert verdict.ok is False
    assert any("AAA-PROP-00" in f and "no bound test" in f for f in verdict.failures)
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)


# GATE-MUTATION-KILL: l1.py sorted(bound, key=...) -> key=None survived the
# campaign: multiple bindings for one alias must digest deterministically, not
# crash on dict comparison
def test_l1_multiple_bindings_digest_deterministic(tmp_path):
    root = _seed_repo(tmp_path)
    (root / "tests" / "test_bound_1b.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound_1b():\n    assert True\n"
    )
    verdict = run_l1(root)
    assert verdict.ok is True
    assert verdict.executed == 1


# GATE-MUTATION-KILL: l1.py `continue` -> `break` on the verdict-cache hit
# survived the campaign: serving cached evidence for one clause must not stop
# the scan; a later clause's uncached red still re-executes. (Tree-digest
# semantics: the suite edit below invalidates ALL cached verdicts for run 2 —
# the per-clause granularity this test used to pin is gone by design, CACHE-3.)
def test_l1_cache_hit_does_not_stop_later_reexecution(tmp_path):
    root = _seed_repo(tmp_path)
    _add_second_bound_clause(root)
    assert run_l1(root).executed == 2, "first run executes both bound suites"
    (root / "tests" / "test_bound_02.py").write_text(
        '# @trace("GATE-INV-02")\n'
        "def test_bound_02():\n    assert False\n"
    )
    assert run_l1(root).executed == 2, "a workspace edit re-executes every suite"
    # unchanged tree: INV-01 cache-hits, but INV-02's red was never cached and
    # must still re-execute — the hit for INV-01 must not `break` the scan
    verdict = run_l1(root)
    assert verdict.ok is False
    assert verdict.executed == 1, "only the uncached red suite re-executes"
    assert any("GATE-INV-02: bound suite failed" in f for f in verdict.failures)


# --- GATE-MUTATION-KILL (mut-gates-lineage shard 2026-09-07) -----------------
# Baseline: 12 _tree_digest + 3 _cache_key + 68 run_l1 survivors. The digest
# skip-policy tests below kill the logic-bearing ones; the b"\x00" separator
# mutants (_cache_key_7, _tree_digest_28/34) are equivalent in context — every
# non-alias chunk is hex/decimal, so no colliding stream is constructible.

# GATE-MUTATION-KILL: `_tree_digest_10` or->and, `_22` suffix "XX.pycXX",
# `_16/18/19` __pycache__ dir-part scan (literal, [:1], [:-2]) all survived:
# bytecode artifacts and pycache dirs at ANY depth must stay out of the digest
def test_tree_digest_excludes_pyc_and_pycache_dirs_at_any_depth(tmp_path):
    from traceagent.gates.l1 import _tree_digest

    (tmp_path / "src" / "sub").mkdir(parents=True)
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return True\n")
    (tmp_path / "src" / "sub" / "more.py").write_text("x = 1\n")
    baseline = _tree_digest(tmp_path)

    (tmp_path / "impl.pyc").write_bytes(b"stale bytecode")
    assert _tree_digest(tmp_path) == baseline, "a .pyc at the root is not reviewable"

    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "notes.txt").write_text("junk")
    assert _tree_digest(tmp_path) == baseline, "shallow __pycache__ is not reviewable"

    (tmp_path / "src" / "sub" / "__pycache__").mkdir()
    (tmp_path / "src" / "sub" / "__pycache__" / "notes.txt").write_text("junk")
    assert _tree_digest(tmp_path) == baseline, "deep __pycache__ is not reviewable"


# GATE-MUTATION-KILL: `_17` "__PYCACHE__" and `_23` ".PYC" survived: on a
# case-sensitive filesystem those names are NOT CPython's artifacts — they are
# reviewable content, and the digest must see them (byte-identical tree rule)
def test_tree_digest_is_case_sensitive_by_design(tmp_path):
    from traceagent.gates.l1 import _tree_digest

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return True\n")
    baseline = _tree_digest(tmp_path)

    (tmp_path / "src" / "__PYCACHE__").mkdir()
    (tmp_path / "src" / "__PYCACHE__" / "notes.txt").write_text("real content")
    assert _tree_digest(tmp_path) != baseline, "__PYCACHE__ is ordinary content here"

    without_pyc_case = _tree_digest(tmp_path)
    (tmp_path / "src" / "other.PYC").write_bytes(b"not python bytecode")
    assert _tree_digest(tmp_path) != without_pyc_case, ".PYC is ordinary content here"


# GATE-MUTATION-KILL: `_10` or->and on (skipped_dir(name) or suffix == ".pyc")
# survived: a dot-file has a skipped NAME but no .pyc suffix — the name rule
# alone must exclude it
def test_tree_digest_excludes_dot_files_by_name(tmp_path):
    from traceagent.gates.l1 import _tree_digest

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return True\n")
    baseline = _tree_digest(tmp_path)
    (tmp_path / ".hidden.txt").write_text("tool workspace, not evidence")
    assert _tree_digest(tmp_path) == baseline, "dot-files are excluded by name"


# GATE-MUTATION-KILL: `_30` b"<unreadable>" -> h.update(None) survived: an
# unreadable file must degrade to the stable marker, never crash the digest
def test_tree_digest_unreadable_file_degrades_not_crashes(tmp_path):
    import os

    from traceagent.gates.l1 import _tree_digest

    if os.geteuid() == 0:  # root reads anything; the scenario needs a real EACCES
        pytest.skip("unreadable-file scenario requires a non-root tester")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "impl.py").write_text("def f():\n    return True\n")
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"cannot be read")
    secret.chmod(0o000)
    try:
        digest = _tree_digest(tmp_path)
    finally:
        secret.chmod(0o644)  # let tmp_path cleanup unlink happily
    assert len(digest) == 64


# GATE-MUTATION-KILL: `run_l1_1` default seed 0 -> 1 survived: the documented
# seed=0 default is the cache contract — a default call and an explicit
# seed=0 call must share verdict entries
def test_l1_default_seed_zero_matches_explicit_seed_zero_cache(tmp_path):
    root = _seed_repo(tmp_path)
    assert run_l1(root).executed == 1
    assert run_l1(root, seed=0).executed == 0, "default seed is 0 — entry must hit"


# GATE-MUTATION-KILL: the "bound evidence unreadable" branch survived whole
# (run_l1_90..100): failures.append(None) crashes rejection building (L1 must
# degrade, never raise), `continue`->`break` stops the clause scan, and the
# l1_clause ledger event flipped ok/alias/reason unnoticed. read #1 of the
# bound file is the binding scan (must succeed); read #2 is the digest step
# (simulated EACCES — the TOCTOU window the branch exists for).
def test_l1_unreadable_evidence_degrades_red_and_scans_on(tmp_path, monkeypatch):
    import pathlib

    root = _seed_repo(tmp_path)
    spec = root / ".zft" / "specs" / "g"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-00000000000b",
        "alias": "GATE-INV-02", "domain": "g", "title": "unbound property",
        "status": "VALIDATED", "version": 1, "content_hash": "b" * 64,
        "invariants": [{"id": "GATE-INV-02", "statement": "WHEN expired THE SYSTEM SHALL reject",
                        "property": "forall t: expired(t) => validate(t) == err('X')",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "gate-inv-02.json").write_text(json.dumps(node))

    reads = {"n": 0}
    original = pathlib.Path.read_text

    def selective_eaccs(self, *args, **kwargs):
        if self.name == "test_bound.py":
            reads["n"] += 1
            if reads["n"] >= 2:  # 1st: binding scan; 2nd: tests_digest step
                raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", selective_eaccs)

    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L1"}, repo=root)
    verdict = run_l1(root, ledger=led)
    led.close()
    assert verdict.ok is False
    # degrade, never raise: the failure string lands in the verdict intact
    assert any("GATE-INV-01: bound evidence unreadable" in f for f in verdict.failures)
    # the scan continues past the unreadable clause to the unbound one
    assert any("GATE-INV-02" in f and "no bound test" in f for f in verdict.failures)
    assert verdict.rejection["code"] == "L1_PROPERTY_EVIDENCE"
    assert verdict.rejection["clause_ids"] == ["GATE-INV-01", "GATE-INV-02"]
    # per-clause ledger events carry ok=False and the typed reason
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = {e["alias"]: e for e in record.events if e["event"] == "l1_clause"}
    assert ev["GATE-INV-01"]["ok"] is False
    assert ev["GATE-INV-01"]["reason"] == "evidence unreadable"
    assert ev["GATE-INV-02"]["ok"] is False
    assert ev["GATE-INV-02"]["reason"] == "no bound test"
