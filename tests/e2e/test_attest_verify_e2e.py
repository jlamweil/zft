"""E2E: sign -> --key-out persist -> verify round-trip against the live store.

attest + verify run as real subprocesses over a copy of the repo's .zft tree
(the live clause store), never against the repo itself. The signing key is
ephemeral (discarded in-process), so --key-out is the only verification path.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from traceagent.attest.dsse import clause_subjects

REPO = Path(os.environ.get("TRACEAGENT_REPO") or Path(__file__).resolve().parents[2])
PY = sys.executable
N_CLAUSES = len(clause_subjects(REPO))


def _run(*args):
    return subprocess.run([PY, "-m", "traceagent.cli.main", *args],
                          capture_output=True, text=True)


def _store_copy(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(REPO / ".zft", root / ".zft")
    return root


def _attest(root: Path, keyfile: Path) -> dict:
    r = _run("attest", str(root), "--key-out", str(keyfile))
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((root / ".traceagent" / "attest.json").read_text())


def test_sign_persist_verify_roundtrip(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    env = _attest(root, keyfile)

    assert len(env["signatures"]) == 1
    key = json.loads(keyfile.read_text())
    assert key["keyid"] == env["signatures"][0]["keyid"], \
        "persisted key must carry the keyid the envelope was signed with"
    payload = json.loads(base64.b64decode(env["payload"]))
    assert payload["_type"] == "https://in-toto.io/Statement/v1"
    live = {s["name"] for s in clause_subjects(REPO)}
    assert {s["name"] for s in payload["subject"]} == live
    assert len(live) == N_CLAUSES, "live store schema: one node per clause"

    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 0, r.stdout + r.stderr
    assert str(N_CLAUSES) in r.stdout


def test_verify_flag_order_both_ways(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    _attest(root, keyfile)
    # --key-in is a KNOWN_FLAGS entry: its value must never be taken for root
    assert _run("verify", str(root), "--key-in", str(keyfile)).returncode == 0
    assert _run("verify", "--key-in", str(keyfile), str(root)).returncode == 0


def test_verify_rejects_tampered_payload(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    env = _attest(root, keyfile)
    raw = bytearray(base64.b64decode(env["payload"]))
    raw[-1] ^= 0x01
    env["payload"] = base64.b64encode(bytes(raw)).decode()
    (root / ".traceagent" / "attest.json").write_text(json.dumps(env))
    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 1
    assert "signature verification failed" in r.stdout


def test_verify_rejects_subject_drift(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    _attest(root, keyfile)
    spec = sorted((root / ".zft" / "specs").rglob("*.json"))[0]
    spec.write_text(spec.read_text() + "\n")  # digest now differs
    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 1
    assert "digests do not match" in r.stdout
    assert spec.name in r.stdout, "rejection must name the drifted clause"


def test_verify_rejects_wrong_key(tmp_path):
    root = _store_copy(tmp_path)
    k1, k2 = tmp_path / "k1.json", tmp_path / "k2.json"
    _attest(root, k1)
    _attest(root, k2)  # second ephemeral signer
    r = _run("verify", str(root), "--key-in", str(k1))
    assert r.returncode == 1
    assert "signature verification failed" in r.stdout


def test_verify_usage_and_missing_artifacts(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    assert _run("verify", str(root)).returncode == 2           # no --key-in
    assert "requires --key-in" in _run("verify", str(root)).stdout
    r = _run("verify", str(root), "--key-in", "nope.json")
    assert r.returncode == 2
    assert "key file not found" in r.stdout, "missing key file must be its own typed refusal"
    (tmp_path / "junk.json").write_text("{definitely not json")
    r = _run("verify", str(root), "--key-in", str(tmp_path / "junk.json"))
    assert r.returncode == 2 and "unusable key file" in r.stdout
    _attest(root, keyfile)  # valid key in hand...
    (root / ".traceagent" / "attest.json").unlink()  # ...but no attestation
    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 1 and "no attestation" in r.stdout.lower()

def test_verify_reports_all_envelope_problems_at_once(tmp_path):
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    _attest(root, keyfile)
    (root / ".traceagent" / "attest.json").write_text(json.dumps({"signatures": []}))
    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 1
    assert "'payload'" in r.stdout and "'payloadType'" in r.stdout


def test_verify_replay_after_store_growth_names_clause(tmp_path):
    """Replay + subject-count mismatch at the CLI: the same envelope and key
    verify twice against the unchanged store (verifier is stateless), then
    a clause ADDED to the store makes the same envelope fail — and the
    rejection names the clause that the signature never covered."""
    root = _store_copy(tmp_path)
    keyfile = tmp_path / "pub.json"
    _attest(root, keyfile)
    assert _run("verify", str(root), "--key-in", str(keyfile)).returncode == 0
    assert _run("verify", str(root), "--key-in", str(keyfile)).returncode == 0
    domain = sorted((root / ".zft" / "specs").iterdir())[0]
    (domain / "zz-post-signing-clause.json").write_text(json.dumps({
        "node_id": "018f3a2b-9e41-7100-8000-0000000000bb",
        "alias": "ZZ-POST-SIGNING-01", "domain": "demo", "title": "late clause",
        "status": "DRAFT", "version": 1, "content_hash": "0" * 64,
        "invariants": [], "external_links": [],
    }))
    r = _run("verify", str(root), "--key-in", str(keyfile))
    assert r.returncode == 1
    assert "digests do not match" in r.stdout
    assert "clause:zz-post-signing-clause.json" in r.stdout, r.stdout
    assert "subject-count mismatch" in r.stdout, r.stdout


def test_verify_expect_keyid_pin_refuses_substituted_key(tmp_path):
    """KEY-13 wiring through the CLI: --expect-keyid catches a
    wholesale-substituted key file BEFORE any cryptographic work, and the
    honest pin still verifies."""
    root = _store_copy(tmp_path)
    k_other, k_honest = tmp_path / "k-other.json", tmp_path / "k-honest.json"
    _attest(root, k_other)
    _attest(root, k_honest)  # signs the envelope the store now holds
    honest_keyid = json.loads(k_honest.read_text())["keyid"]
    r = _run("verify", str(root), "--key-in", str(k_other),
             "--expect-keyid", honest_keyid)
    assert r.returncode == 1
    assert "keyid pin mismatch" in r.stdout, r.stdout
    r = _run("verify", str(root), "--key-in", str(k_honest),
             "--expect-keyid", honest_keyid)
    assert r.returncode == 0, r.stdout + r.stderr
