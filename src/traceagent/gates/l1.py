"""L1 gate (plan C-22): property suites bound to clauses, digest-keyed verdict cache.

State transition (all gates): collect failures -> ok computed once at the end ->
typed rejection -> one summary ledger event (plus per-clause l1_clause events).
L1 never raises: missing/corrupt evidence, an unreadable store or a broken
verdict cache each degrade to a typed red verdict for the affected clause.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from traceagent.debug.ledger import RunLedger
from traceagent.dsl.predicate import DSL_VERSION
from traceagent.gates.runners.pytest_runner import run_pytest

# Fingerprint of this gate's source code to bind cache entries to the gate implementation.
_GATE_FINGERPRINT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass
class L1Verdict:
    stage: str
    ok: bool
    executed: int = 0
    failures: list = field(default_factory=list)
    rejection: dict | None = None
    evidence_refs: list = field(default_factory=list)


def _cache_key(
    alias: str,
    tests_digest: str,
    oracle_digest: str,
    seed: int = 0,
    contract_sha: str | None = None,
    tree_digest: str = "",
) -> str:
    h = hashlib.sha256()
    for chunk in (alias, tests_digest, oracle_digest, str(seed),
                   _GATE_FINGERPRINT, DSL_VERSION, tree_digest):
        h.update(chunk.encode())
        h.update(b"\x00")
    if contract_sha:
        h.update(contract_sha.encode())
        h.update(b"\x00")
    return h.hexdigest()


def _read_cache(cache_file: Path) -> dict | None:
    """Tolerant cache read: a corrupt or unreadable entry is a miss, not a crash."""
    try:
        data = json.loads(cache_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None



def _tree_digest(root: Path) -> str:
    """Content digest of every reviewable file in the tree.

    Bound suites import the implementation under test, so a cached verdict is
    only honest while the workspace is byte-identical — test-file digests alone
    let an edited implementation hide behind a stale verdict (internal cache
    incidents CACHE-1/2/3, unioned 2026-09-12). Hidden trees and `mutants/` are excluded with the
    extractor's skip policy; `.traceagent` in particular, or writing the cache
    would perturb the very key it is stored under.
    """
    from traceagent.lineage.extract import skipped_dir

    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        parts = path.relative_to(root).parts
        name = parts[-1]
        if (any(skipped_dir(p) or p == "__pycache__" for p in parts[:-1])
                or skipped_dir(name) or path.suffix == ".pyc"):
            continue
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\x00")
        try:
            h.update(path.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\x00")
    return h.hexdigest()


def run_l1(root: Path | str, ledger: RunLedger | None = None,
           seed: int = 0, examples_timeout_s: int = 300,
           bindings: list[dict] | None = None,
           write_cache: bool = True) -> L1Verdict:
    """Execute property suites bound to property-kind clauses (plan §4 L1).

    write_cache=False keeps the run read-only: cached greens may still be
    served, but new green verdicts are never persisted (driver-gate contract).
    """
    root = Path(root)
    from traceagent.spec.store import Store

    failures: list[str] = []
    pin_failures: list[str] = []
    oracle_missing: list[str] = []
    oracle_exec_fails: list[str] = []
    executed = 0
    store_nodes: dict[str, dict] = {}
    try:
        store_nodes = Store.load(root).nodes
        if bindings is None:
            from traceagent.lineage.extract import extract_bindings
            bindings = extract_bindings(root, write_cache=write_cache)
    except Exception as e:  # noqa: BLE001 — evidence collection must red the gate, not crash it
        failures.append(f"L1: evidence collection failed ({e!r})")
        bindings = []  # ensure downstream loops have a list

    by_alias: dict[str, list[dict]] = {}
    for b in bindings:
        if b["alias"] in store_nodes:
            by_alias.setdefault(b["alias"], []).append(b)

    # Evidence references collected for this L1 run
    evidence_refs: list[dict] = []
    batch: list[dict] = []
    contract_sha: str | None = None
    tree_digest = _tree_digest(root)
    # Contract entry (best-effort)
    try:
        from traceagent.spec.store import load_contract
        contract = load_contract(root)
        contract_sha = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        evidence_refs.append({
            "kind": "contract",
            "sha256": contract_sha,
        })
    except Exception:
        pass
    cache_dir = root / ".traceagent" / "cache" / "l1"

    def emit_clause(ok: bool, **fields) -> None:
        if ledger:
            ledger.append({"event": "l1_clause", "ok": ok, **fields})

    for alias, node in sorted(store_nodes.items()):
        kinds = {inv["check"]["kind"] for inv in node["invariants"]}
        if "property" not in kinds:
            continue
        bound = by_alias.get(alias, [])
        if not bound:
            failures.append(f"{alias}: property clause has no bound test (evidence missing)")
            emit_clause(False, alias=alias, reason="no bound test")
            continue
        test_files = [b["file"] for b in sorted(bound, key=lambda x: x["file"])]
        try:
            tests_digest = hashlib.sha256(
                "\n".join((root / f).read_text() for f in test_files).encode()
            ).hexdigest()
        except OSError as e:
            failures.append(f"{alias}: bound evidence unreadable ({e})")
            emit_clause(False, alias=alias, reason="evidence unreadable")
            continue
        # Record tests evidence for this clause
        evidence_refs.append({
            "kind": "tests",
            "alias": alias,
            "files": test_files,
            "sha256": tests_digest,
        })
        # Determine oracle path & digest
        if "oracle_sha256" in node:
            # Contract-pinned oracle verification
            oracle_path = root / node.get("oracle_file", f"oracle_{alias}.py")
            try:
                oracle_digest = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
            except OSError:
                pin_failures.append(
                    f"{alias}: pinned oracle missing or unreadable ({oracle_path.name})")
                failures.append(f"{alias}: pinned oracle missing or unreadable")
                emit_clause(False, alias=alias, reason="oracle pin missing")
                continue
            if oracle_digest != node["oracle_sha256"]:
                pin_failures.append(
                    f"{alias}: oracle digest {oracle_digest} != pinned {node['oracle_sha256']}")
                failures.append(f"{alias}: oracle pin mismatch")
                emit_clause(False, alias=alias, reason="oracle pin mismatch")
                continue
        else:
            oracle_path = root / f"oracle_{alias}.py"
            if not oracle_path.exists():
                oracle_missing.append(f"{alias}: oracle missing")
                failures.append(f"{alias}: oracle missing")
                emit_clause(False, alias=alias, reason="oracle missing")
                continue
            try:
                oracle_digest = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
            except OSError as e:
                failures.append(f"{alias}: oracle unreadable ({e})")
                emit_clause(False, alias=alias, reason="oracle unreadable")
                continue
        # Cache lookup
        key = _cache_key(alias, tests_digest, oracle_digest, seed, contract_sha, tree_digest)
        cache_file = cache_dir / f"{alias}.json"
        cached = _read_cache(cache_file)
        if cached is not None and cached.get("ok") is True and cached.get("key") == key:
            # CACHE-1/2: only green verdicts are served; a cached failure is
            # re-run, never replayed — a red must be re-earned.
            emit_clause(True, alias=alias, cached=True)
            continue
        # Queue for batched oracle execution
        batch.append({
            "alias": alias,
            "safe_alias": alias.replace('-', '_'),
            "oracle_path": oracle_path,
            "oracle_digest": oracle_digest,
            "key": key,
            "cache_file": cache_file,
            "tests": test_files,
            "tests_digest": tests_digest,
        })


    # Process batched oracle executions
    if batch:
        # Build temporary test module with one test per oracle
        tmp_oracle_path = root / ".traceagent" / "tmp_oracle_batch.py"
        lines = []
        for entry in batch:
            alias = entry["alias"]
            safe_alias = entry["safe_alias"]
            module_name = (
                entry["oracle_path"]
                .relative_to(root)
                .with_suffix('')
                .as_posix()
                .replace('/', '.')
            )
            lines.append(
                f"def test_oracle_{safe_alias}():\n"
                f"    import importlib\n"
                f"    mod = importlib.import_module('{module_name}')\n"
                f"    check = getattr(mod, 'check', None)\n"
                f"    if check is not None:\n"
                f"        check()"
            )
        # The batch module lives OUTSIDE root (system temp): a read-only gate
        # (write_cache=False, driver-gate contract) must leave no trace in the
        # gated workspace, and the generated module bootstraps sys.path with
        # root so the oracle modules still import by dotted name.
        batch_dir = Path(tempfile.mkdtemp(prefix="zft-oracle-batch-"))
        bootstrap = f"import sys; sys.path.insert(0, {str(root)!r})\n"
        tmp_oracle_path = batch_dir / "tmp_oracle_batch.py"
        tmp_oracle_path.write_text(bootstrap + "\n\n".join(lines))
        junit_path = batch_dir / "tmp_oracle_batch.xml"
        # Run batched oracle tests. The driver lives outside root: without a
        # pinned collection boundary pytest resolves its rootdir to the common
        # ancestor of the workspace and batch_dir (e.g. /tmp when the workspace
        # is under /tmp) and walks that ancestor during collection. On hosts
        # whose /tmp holds unstat-able entries the walk dies, the driver is
        # never collected, and the batch run is vacuous (always green) —
        # proven by the vacuity probe of 2026-09-15. confcutdir=batch_dir
        # confines the walk to the batch dir; the driver is collected and
        # executed regardless of where root lives.
        run_pytest(
            root, [str(tmp_oracle_path)],
            timeout_s=examples_timeout_s, junit_xml=junit_path, fail_fast=False,
            confcutdir=batch_dir,
        )
        # Parse JUnit XML for failures
        failed_aliases = set()
        if junit_path.exists():
            tree = ET.parse(junit_path)
            for testcase in tree.iter('testcase'):
                name = testcase.get('name')
                if name and name.startswith('test_oracle_'):
                    alias_name = name[len('test_oracle_'):]
                    if testcase.find('failure') is not None:
                        failed_aliases.add(alias_name)
        # Process each clause's oracle result
        for entry in batch:
            alias = entry["alias"]
            oracle_path = entry["oracle_path"]
            oracle_digest = entry["oracle_digest"]
            key = entry["key"]
            cache_file = entry["cache_file"]
            test_files = entry["tests"]
            # Record oracle evidence reference
            evidence_refs.append({
                "kind": "oracle",
                "alias": alias,
                "file": oracle_path.name,
                "sha256": oracle_digest,
            })
            if entry["safe_alias"] in failed_aliases:
                oracle_exec_fails.append(f"{alias}: oracle execution failed")
                failures.append(f"{alias}: oracle failed")
                emit_clause(False, alias=alias, reason="oracle execution failed")
                # CACHE-3: failures are never persisted — the verdict is in
                # the ledger; re-running re-earns it.
                continue
            # Oracle succeeded; run bound test suite
            result = run_pytest(root, test_files, timeout_s=examples_timeout_s)
            executed += 1
            ok = result.ok and not result.timed_out
            emit_clause(ok, alias=alias, duration_ms=result.duration_ms)
            if ok and write_cache:
                try:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(
                        {"key": key, "ok": ok, "duration_ms": result.duration_ms}
                    ))
                except OSError:
                    pass  # cache is an optimization; the verdict is already in the ledger
            if not ok:
                failures.append(f"{alias}: bound suite failed")
        # Cleanup temporary files
        tmp_oracle_path.unlink(missing_ok=True)
        junit_path.unlink(missing_ok=True)

    ok = not failures
    rejection = None
    if failures:
        if pin_failures:
            code, fault, expected, detail = (
                "L1_ORACLE_PIN_MISMATCH", "producer",
                "oracle file matches the contract pin (oracle_sha256)",
                pin_failures,
            )
        elif oracle_missing:
            code, fault, expected, detail = (
                "L1_ORACLE_REQUIRED", "producer",
                "oracle file must be present for property clause",
                oracle_missing,
            )
        elif oracle_exec_fails:
            code, fault, expected, detail = (
                "L1_ORACLE_FAIL", "producer",
                "oracle check must pass",
                oracle_exec_fails,
            )
        else:
            code, fault, expected, detail = (
                "L1_PROPERTY_EVIDENCE", "implementation",
                "bound property suites pass",
                failures,
            )
        rejection = {
            "code": code,
            "clause_ids": sorted({f.split(":")[0] for f in detail}),
            "fault": fault,
            "expected": expected,
            "actual": detail,
            "evidence_refs": evidence_refs,
        }
    if ledger:
        ledger.append({"event": "l1", "ok": ok, "executed": executed,
                       "failures": failures})
    return L1Verdict(stage="L1", ok=ok, executed=executed, failures=failures,
                     rejection=rejection, evidence_refs=evidence_refs)
