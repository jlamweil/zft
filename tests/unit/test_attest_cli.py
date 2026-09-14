"""C-29/C-30: attest CLI + export from attested manifests only (V8 semantics).

Invalid-payload cases run against throwaway roots only: corrupt attestation
files and an empty store must be refused with exit 1, never a half-export.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from securesystemslib.signer import CryptoSigner, Key

from traceagent.attest.dsse import parse_envelope, verify_attestation
from traceagent.attest.jcs import canonicalize

REPO = Path(os.environ.get("TRACEAGENT_REPO") or os.environ.get("ZFT_REPO")
            or Path(__file__).resolve().parents[2])


def _live_counts() -> tuple[int, int]:
    """(node count, milestone-scoped due count) derived from live store + contract."""
    from traceagent.gates.l2 import _current_milestone
    from traceagent.spec.store import Store, load_contract

    nodes = Store.load(REPO).nodes
    deferred = load_contract(REPO).get("meta", {}).get("target_milestone", {})
    milestone = _current_milestone(REPO)
    due = len({a for a in nodes if deferred.get(a, milestone) <= milestone})
    return len(nodes), due
PY = sys.executable


def _run(*args):
    return subprocess.run([PY, "-m", "traceagent.cli.main", *args],
                          capture_output=True, text=True)


def test_cli_attest_writes_envelope(tmp_path):
    keyfile = tmp_path / "dev.key"
    r = _run("attest", str(REPO), "--key-out", str(keyfile))
    assert r.returncode == 0, r.stdout + r.stderr
    env_path = REPO / ".traceagent" / "attest.json"
    assert env_path.exists()
    att = json.loads(env_path.read_text())
    assert att["payloadType"] == "application/vnd.in-toto+json"
    assert len(att["signatures"]) == 1
    assert keyfile.exists()
    env_path.unlink()


def test_cli_export_format_flag():
    env_path = REPO / ".traceagent" / "attest.json"
    r = _run("attest", str(REPO))
    assert r.returncode == 0, r.stdout + r.stderr
    try:
        r = _run("export", str(REPO), "--format", "summary")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "attestation summary" in r.stdout
        r = _run("export", str(REPO), "--format", "dsse")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["payloadType"] == "application/vnd.in-toto+json"
        r = _run("export", str(REPO), "--format", "bogus")
        assert r.returncode == 1, r.stdout
        assert "unknown export format" in r.stdout
    finally:
        env_path.unlink(missing_ok=True)


# @trace("ATT-EXPORTS-FROM-ATTESTATIONS")
def test_cli_export_refuses_without_attestation(tmp_path):
    r = _run("export", str(tmp_path))
    assert r.returncode == 1
    assert "no attestation" in r.stdout.lower() or "no attestation" in r.stderr.lower()


# --- invalid attestation payloads (all against throwaway roots) --------------

def _write_attestation(root: Path, envelope: dict) -> Path:
    att_dir = root / ".traceagent"
    att_dir.mkdir(parents=True, exist_ok=True)
    att_path = att_dir / "attest.json"
    att_path.write_text(json.dumps(envelope, indent=2))
    return att_path


def _signed_envelope(payload_bytes: bytes) -> dict:
    from securesystemslib.dsse import Envelope

    envelope = Envelope(payload=payload_bytes,
                        payload_type="application/vnd.in-toto+json", signatures={})
    envelope.sign(CryptoSigner.generate_ed25519())
    return envelope.to_dict()


def test_cli_export_refuses_corrupt_attestation_json(tmp_path):
    att_dir = tmp_path / ".traceagent"
    att_dir.mkdir(parents=True)
    (att_dir / "attest.json").write_text("{definitely not json")
    r = _run("export", str(tmp_path))
    assert r.returncode == 1
    assert "export refused" in r.stdout
    assert "not valid JSON" in r.stdout


def test_cli_export_refuses_structurally_broken_envelope(tmp_path):
    _write_attestation(tmp_path, {"payloadType": "application/vnd.in-toto+json"})
    r = _run("export", str(tmp_path))
    assert r.returncode == 1
    assert "export refused" in r.stdout
    assert "payload" in r.stdout


def test_cli_export_refuses_statement_missing_predicate_fields(tmp_path):
    statement = {"_type": "https://in-toto.io/Statement/v1",
                 "predicateType": "https://traceagent.dev/attestations/TraceManifest/v1",
                 "subject": [{"name": "clause:x.json", "digest": {"sha256": "0" * 64}}],
                 "predicate": {}}
    _write_attestation(tmp_path, _signed_envelope(canonicalize(statement)))
    r = _run("export", str(tmp_path))
    assert r.returncode == 1
    assert "export refused" in r.stdout
    assert "predicate is incomplete" in r.stdout


def test_cli_attest_refuses_store_without_clauses(tmp_path):
    r = _run("attest", str(tmp_path))
    assert r.returncode == 1, "empty store must not produce an empty attestation"
    assert "nothing to attest" in r.stderr
    assert not (tmp_path / ".traceagent" / "attest.json").exists()


# @trace("ATT-SIGNED-ACCEPTANCE")
def test_cli_attest_then_export_roundtrip_on_tmp_store(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "demo"
    spec.mkdir(parents=True)
    (spec / "demo-inv-01.json").write_text(json.dumps({
        "node_id": "018f3a2b-9e41-7100-8000-0000000000aa",
        "alias": "DEMO-INV-01", "domain": "demo", "title": "demo",
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [{"id": "DEMO-INV-01",
                        "statement": "THE SYSTEM SHALL demo",
                        "property": "demo(x) == true",
                        "check": {"kind": "test"}}],
        "external_links": [],
    }))
    # the gate fails closed: unsupplied model identity -> model_dependent true.
    # Supply two distinct identities to prove the independence seam.
    r = _run("attest", str(tmp_path), "--producer-model", "p", "--gate-model", "g")
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run("export", str(tmp_path), "--format", "matrix")
    assert r.returncode == 0, r.stdout + r.stderr
    matrix = json.loads(r.stdout)
    assert matrix["clauses"] == ["clause:demo-inv-01.json"]
    assert matrix["model_dependent"] is False


@pytest.mark.parametrize("payload", [None, 42, "text", [1]], ids=["null", "int", "str", "list"])
def test_cli_export_refuses_non_object_attestation_file(tmp_path, payload):
    att_dir = tmp_path / ".traceagent"
    att_dir.mkdir(parents=True)
    (att_dir / "attest.json").write_text(json.dumps(payload))
    r = _run("export", str(tmp_path))
    assert r.returncode == 1
    assert "export refused" in r.stdout


# @trace("ATT-SIGNED-ACCEPTANCE")
def test_cli_attest_sign_persist_verify_roundtrip_on_live_store(tmp_path):
    """Sign the live store via the CLI, persist its public key, verify offline.

    Full round trip over existing public seams only: `attest --key-out`
    persists the ed25519 public key next to the envelope; parse_envelope
    re-parses the stored envelope; the key is rebuilt via Key.from_dict
    (keyid re-bound from the envelope's own signature entry) and the payload
    is crypto-verified against subject digests recomputed from the live
    live clause store.
    """
    keyfile = tmp_path / "attest.pub"
    r = _run("attest", str(REPO), "--key-out", str(keyfile))
    assert r.returncode == 0, r.stdout + r.stderr
    att = json.loads((REPO / ".traceagent" / "attest.json").read_text())

    parse_envelope(att)  # structural parse of the persisted envelope

    key_dict = json.loads(keyfile.read_text())
    assert key_dict["keytype"] == "ed25519"
    key = Key.from_dict(att["signatures"][0]["keyid"], key_dict)

    expected = {
        f"clause:{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((REPO / ".zft" / "specs").rglob("*.json"))
    }
    n_nodes, n_due = _live_counts()
    assert len(expected) == n_nodes
    payload = verify_attestation(att, public_key=key, expected_subjects=expected)
    assert payload["predicateType"].endswith("TraceManifest/v1")
    assert len(payload["subject"]) == n_nodes
    covered, due = payload["predicate"]["coverage"]["clauses_covered"].split("/")
    assert 0 < int(covered) <= int(due) == n_due


# wave2 risk #3: sign -> persist key -> verify round trip against the live
# store; tampered payloads and drifted stores must both be refused.
def test_cli_verify_roundtrip_and_refusals(tmp_path):
    import base64

    keyfile = tmp_path / "dev.pub.json"
    env_path = REPO / ".traceagent" / "attest.json"
    env_path.unlink(missing_ok=True)
    r = _run("attest", str(REPO), "--key-out", str(keyfile))
    assert r.returncode == 0, r.stdout + r.stderr
    try:
        r = _run("verify", str(REPO), "--key-in", str(keyfile))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "signature ok" in r.stdout
        m = re.search(r"(\d+) clause subject", r.stdout)
        assert m and int(m.group(1)) >= 1

        # tampered payload bytes -> signature failure
        env = json.loads(env_path.read_text())
        raw = json.loads(base64.b64decode(env["payload"]))
        raw["predicateType"] = "https://example.com/evil"
        env["payload"] = base64.b64encode(
            json.dumps(raw).encode()).decode()
        env_path.write_text(json.dumps(env))
        r = _run("verify", str(REPO), "--key-in", str(keyfile))
        assert r.returncode == 1, r.stdout
        assert "verify failed" in r.stdout

        # honest signature but drifted store -> subject mismatch
        r = _run("attest", str(REPO), "--key-out", str(keyfile))
        assert r.returncode == 0, r.stdout + r.stderr
        (REPO / ".zft" / "specs" / "misc").mkdir(exist_ok=True)
        drift = REPO / ".zft" / "specs" / "misc" / "zz-drift-probe.json"
        drift.write_text('{"alias": "ZZ-DRIFT-PROBE"}')
        try:
            r = _run("verify", str(REPO), "--key-in", str(keyfile))
            assert r.returncode == 1, r.stdout
            assert "verify failed" in r.stdout
        finally:
            drift.unlink()
    finally:
        env_path.unlink(missing_ok=True)
def _store_copy(tmp_path):
    """Live .zft tree copied to a throwaway root — never attest the repo."""
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(REPO / ".zft", root / ".zft")
    return root


def test_cli_attest_persists_key_by_default(tmp_path):
    # no --key-out: the ephemeral signer would make the envelope unverifiable,
    # so the key must rotate alongside it (2026-09-05 live-store drift incident)
    root = _store_copy(tmp_path)
    r = _run("attest", str(root))
    assert r.returncode == 0, r.stdout + r.stderr
    default_key = root / ".traceagent" / "attest-key.pub.json"
    assert default_key.exists()
    att = json.loads((root / ".traceagent" / "attest.json").read_text())
    key = json.loads(default_key.read_text())
    assert key["keyid"] == att["signatures"][0]["keyid"]
    r = _run("verify", str(root), "--key-in", str(default_key))
    assert r.returncode == 0, r.stdout + r.stderr


def _payload(root):
    att = json.loads((root / ".traceagent" / "attest.json").read_text())
    return json.loads(base64.b64decode(att["payload"]))["predicate"]


def test_cli_attest_models_caller_supplied(tmp_path):
    root = _store_copy(tmp_path)
    r = _run("attest", str(root), "--producer-model", "prod-a",
             "--gate-model", "gate-b")
    assert r.returncode == 0, r.stdout + r.stderr
    pred = _payload(root)
    assert pred["models"] == {"producer": "prod-a", "gate": "gate-b"}
    assert pred["model_dependent"] is False


def test_cli_attest_models_unsupplied_stay_null_not_dev_names(tmp_path):
    """No identity flags or config envs: models stay null and the claim stays
    model-dependent (fail-closed) — never an invented dev name."""
    root = _store_copy(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TRACEAGENT_PRODUCER", "TRACEAGENT_GATE"))}
    r = subprocess.run([PY, "-m", "traceagent.cli.main", "attest", str(root)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    pred = _payload(root)
    assert pred["models"] == {"producer": None, "gate": None}
    assert pred["model_dependent"] is True


def test_cli_attest_models_env_config_fallback(tmp_path):
    root = _store_copy(tmp_path)
    env = os.environ | {"TRACEAGENT_PRODUCER_MODEL": "env-prod",
                        "TRACEAGENT_GATE_MODEL": "env-gate"}
    r = subprocess.run([PY, "-m", "traceagent.cli.main", "attest", str(root)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _payload(root)["models"] == {"producer": "env-prod", "gate": "env-gate"}
