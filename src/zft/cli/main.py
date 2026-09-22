"""zft CLI entrypoint — thin dispatch over package seams.

Commands (plan §2): lint, extract, check, gate, gate-campaign, repro,
attest, verify, export, negotiate, create.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KNOWN_FLAGS = {
    "--module", "--tests", "--scope", "--oracle", "--conftest", "--sandbox",
    "--key-out", "--key-in", "--alias", "--domain", "--title", "--statement",
    "--property", "--kind", "--producer-model", "--gate-model", "--format",
    "--key-expires", "--expect-keyid", "--counter-terms",
    "--waivers", "--source-root",
}


def _val(argv: list[str], flag: str):
    """Flag helper: returns value after `flag`, else None.

    A flag-shaped token is never a value: `--key-out --alias x` must yield
    None for --key-out, not swallow --alias as the key path.
    """
    if flag in argv:
        i = argv.index(flag) + 1
        if i < len(argv) and not argv[i].startswith("--"):
            return argv[i]
    return None


# Value-less flags (no following argument): never a flag value and never a
# positional root (zft lineage BOOLEAN_FLAGS, unioned 2026-09-12).
BOOLEAN_FLAGS = {"--resume"}


def _split_root(argv: list[str]) -> tuple[list[str], Path]:
    """Separate known flags (flag+value) from positionals; return (rest, root)."""
    rest: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in KNOWN_FLAGS:
            skip_next = True
            continue
        if arg in BOOLEAN_FLAGS:
            rest.append(arg)
            continue
        rest.append(arg)
    positionals = [a for a in rest if a not in BOOLEAN_FLAGS]
    # resolve absolute here — sandboxed subprocesses receive it via
    # ZFT_REPO and would otherwise resolve a relative root against the
    # sandbox cwd (zft lineage wave2 risk #2)
    root = Path(positionals[0]).resolve() if positionals else Path.cwd()
    return rest, root


_ABSOLUTE_ROOT_CMDS = ("gate", "gate-campaign", "attest", "repro", "driver-gate")


def _abs_root(cmd: str, root: Path) -> Path:
    """gate/attest/repro hand root to sandboxed subprocesses (pytest runs with
    cwd=sandbox) or write artifacts under root — bind it absolute at the
    boundary so a later chdir cannot re-point a relative root."""
    return root.resolve() if cmd in _ABSOLUTE_ROOT_CMDS else root


def _model_identity(argv: list[str]) -> tuple[str | None, str | None]:
    """Caller-supplied (producer, gate) identity: --producer-model/--gate-model
    first, then the ZFT_*_MODEL config envs driver-gate reads.

    No default name: an unsupplied identity stays None (null in the gate log
    and attestation payload), which fails closed — model_dependent stays true
    until the caller supplies two identities and proves them different
    (GATE-MODEL-INDEPENDENCE).
    """
    import os

    from zft.gates.driver_gate import GATE_MODEL_ENV, PRODUCER_MODEL_ENV

    producer = _val(argv, "--producer-model") or os.environ.get(PRODUCER_MODEL_ENV)
    gate = _val(argv, "--gate-model") or os.environ.get(GATE_MODEL_ENV)
    return producer, gate


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: zft <lint|extract|check|impact|gate|repro|attest|verify|export|"
              "negotiate|create|baseline|driver-gate|mutation-bar|task-gate> [root]")
        return 2
    # Global help flags
    if argv[0] in ("-h", "--help"):
        print("usage: zft <lint|extract|check|impact|gate|repro|attest|verify|export|"
              "negotiate|create|baseline|driver-gate|mutation-bar|task-gate> [root]")
        return 0
    cmd = argv[0]
    if argv[-1] in KNOWN_FLAGS:  # dangling flag: _val would index past argv
        print(f"missing value for {argv[-1]}")
        return 2
    rest, root = _split_root(argv[1:])
    root = _abs_root(cmd, root)

    if cmd == "lint":
        from zft.spec.findings import partition, render_finding
        from zft.spec.lint import collect_findings

        denies, warns = partition(collect_findings(root))
        n_nodes = len(list((root / ".zft" / "specs").rglob("*.json")))
        if denies:
            print(f"L0 FAILED — {len(denies)} error(s), {len(warns)} warning(s), "
                  f"{n_nodes} nodes checked")
            for f in denies:
                print(f"  ✗ {render_finding(f)}")
            for f in warns:
                print(f"  ⚠ {render_finding(f)}")
            return 1
        suffix = f", {len(warns)} warning(s)" if warns else ""
        print(f"L0 PASSED — {n_nodes} clause nodes checked{suffix}")
        for f in warns:
            print(f"  ⚠ {render_finding(f)}")
        return 0

    if cmd == "extract":
        from zft.lineage.extract import extract_bindings

        print(json.dumps(extract_bindings(root)))
        return 0

    if cmd == "impact":
        # Impact query: which clauses are affected by a changed file[:symbol]
        # Usage: zft impact <target> [--base REF] [root]
        # <target> is path or path:symbol (single colon accepted, converted to ::).
        if not rest:
            print("usage: zft impact <target> [--base REF] [root]")
            return 2
        target = rest[0]
        # Optional base flag (not supported yet)
        base_val = _val(argv, "--base")
        if base_val is not None:
            print("--base not supported yet")
            return 2
        # Determine repository root: default cwd, unless a second positional is given
        if len(rest) > 1 and not rest[1].startswith("-"):
            repo_root = Path(rest[1]).resolve()
        else:
            repo_root = Path.cwd()
        # Convert single-colon separator to double-colon for the impact API
        change = target.replace(":", "::", 1) if ":" in target and "::" not in target else target
        from zft.lineage.impact import impact_from_root
        result = impact_from_root(repo_root, [change])
        if not result.get("aliases"):
            print(f"{target}: no bindings")
            return 0
        # Build symbol -> set(alias) mapping
        sym_to_aliases: dict[str, set[str]] = {}
        for alias, refs in result.get("affected", {}).items():
            for ref in refs:
                sym = ref.get("symbol") or ref.get("file")
                sym_to_aliases.setdefault(sym, set()).add(alias)
        for sym in sorted(sym_to_aliases):
            aliases = sorted(sym_to_aliases[sym])
            print(f"{sym} — binds: {' '.join(aliases)}")
        return 0

    if cmd == "mutation-bar":
        from zft.gates.mutation_bar import evaluate, load_shard, load_waivers

        shard_dirs = [Path(d) for d in rest]
        if not shard_dirs:
            print("mutation-bar requires at least one results-mut-* directory")
            return 2
        waivers_path = _val(argv, "--waivers")
        waivers = load_waivers(waivers_path) if waivers_path else {}
        source_root = Path(_val(argv, "--source-root") or ".")
        report = evaluate([load_shard(d, source_root) for d in shard_dirs],
                          waivers=waivers)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if cmd == "create":
        from zft.spec.canon import canonical_hash
        from zft.spec.identity import new_uuid7

        alias = _val(argv, "--alias")
        if not alias:
            print("create requires --alias")
            return 2
        domain = _val(argv, "--domain") or "misc"
        title = _val(argv, "--title") or alias
        inv = {
            "id": f"{alias}-INV-01",
            "statement": _val(argv, "--statement") or "",
            "property": _val(argv, "--property") or "",
            "check": {"kind": _val(argv, "--kind") or "test"},
        }
        node = {
            "node_id": new_uuid7(), "alias": alias, "domain": domain,
            "title": title, "status": "DRAFT", "version": 1,
            "content_hash": canonical_hash({"domain": domain, "title": title,
                                            "invariants": [inv]}),
            "invariants": [inv], "external_links": [],
        }
        out_dir = root / ".zft" / "specs" / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{alias.lower()}.json").write_text(json.dumps(node, indent=2) + "\n")
        print(f"created {alias} (DRAFT) -> {out_dir / (alias.lower() + '.json')}")
        return 0

    if cmd == "baseline":
        # the seeding act for TR-REVERSE-COVERAGE's grandfathering direction:
        # one real extraction, written where run_l2 reads the baseline. A
        # re-seed re-baselines (grandfathering restarts from the new set).
        from zft.lineage.matrix import list_all_elements

        elements = list_all_elements(root)
        out_dir = root / ".zft" / "baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "elements.json").write_text(
            json.dumps({"version": 1, "elements": elements}, indent=2) + "\n")
        out: dict = {"baseline": str(out_dir / "elements.json"),
                     "elements": len(elements)}
        if not elements:
            out["warning"] = ("extraction found no elements — an empty "
                              "baseline grandfathers nothing (every future "
                              "element is new); check the working tree")
        print(json.dumps(out))
        return 0

    if cmd == "check":
        from zft.codegen.gherkin_gen import gherkin_fallback_green
        from zft.debug.ledger import RunLedger
        from zft.gates.l0 import run_l0
        from zft.gates.l2 import run_l2
        from zft.gates.l3 import build_gate_log
        from zft.gates.runners.pytest_runner import run_pytest
        from zft.spec.store import Store, load_contract

        led = RunLedger.start(root / ".zft" / "runs",
                              manifest={"stage": "check", "tier": "fast"}, repo=root)
        v0 = run_l0(root, ledger=led)
        if not v0.ok:
            led.close()
            print(json.dumps(v0.rejection, indent=2))
            return 1
        v2 = run_l2(root, tier="fast", ledger=led)
        v1 = v2.l1  # A3 (zft lineage): L1 is folded into L2 — one extraction pass
        failures = list(v2.failures)
        ledger_events = RunLedger.load(root / ".zft" / "runs", led.run_id).events
        led.close()

        store = Store.load(root)
        try:
            deferred_map = load_contract(root).get("meta", {}).get("target_milestone", {})
        except (FileNotFoundError, json.JSONDecodeError):
            deferred_map = {}
        deferred = sorted(a for a in store.nodes
                          if deferred_map.get(a, "v0") > "v0")
        due = len(store.nodes) - len(deferred)


        # gherkin fallback stage: every clause renders + collects (C-14 wiring)
        gh_dir = root / ".zft" / "gherkin"
        gh_dir.mkdir(parents=True, exist_ok=True)
        gherkin_ok = gherkin_fallback_green(
            [node for node in store.nodes.values()], gh_dir, run_pytest)
        if not gherkin_ok:
            v2.ok = False
            failures = list(v2.failures)
            failures.append("gherkin fallback stage failed")
        v2.coverage["gherkin_scenarios"] = len(store.nodes)
        v2.coverage["gherkin_ok"] = gherkin_ok

        producer_model, gate_model = _model_identity(argv)
        gate_log = build_gate_log(
            ledger_events, producer_model=producer_model, gate_model=gate_model,
            judge_excluded=v2.coverage.get("judge_excluded", []),
            deterministic_coverage=v2.coverage.get("coverage", ""),
            l0_warnings=v0.warnings,
        )
        print(json.dumps({
            "stage": "L2-FAST",
            "ok": v2.ok and v1.ok,
            "due": due,
            "deferred": deferred,
            "l0_warnings": v0.warnings,
            "l2_warnings": v2.warnings,
            "l1": {"executed": v1.executed, "ok": v1.ok},
            "gate_log": gate_log,
            "coverage": v2.coverage,
            "failures": failures,
        }, indent=2))
        return 0 if (v2.ok and v1.ok) else 1

    if cmd == "driver-gate":
        from zft.gates.driver_gate import run_driver_gate

        producer_model, gate_model = _model_identity(argv)
        verdict = run_driver_gate(root, producer_model=producer_model,
                                  gate_model=gate_model)
        print(verdict.payload)
        return 0 if verdict.ok else 1

    if cmd in ("gate", "gate-campaign"):
        from zft.debug.ledger import RunLedger
        from zft.gates.runners.mutmut_runner import run_campaign
        from zft.gates.sandbox import place_tests, prepare_sandbox

        module_arg = _val(argv, "--module")
        tests_arg = _val(argv, "--tests")
        if not module_arg or not tests_arg:
            print("gate requires --module <path> --tests <path> "
                  "[--scope f1,f2] [--oracle <path>] [--conftest <path>] "
                  "[--sandbox <dir>] [root]")
            return 2
        if not root.exists():
            print(f"gate: root does not exist: {root}")
            return 2
        module = Path(module_arg)
        tests = Path(tests_arg)
        scope_raw = _val(argv, "--scope")
        scope = set(scope_raw.split(",")) if scope_raw else None
        sandbox_dir = Path(_val(argv, "--sandbox") or ".zft/sandbox")

        # WP-C4 (zft lineage): preserve the resume checkpoint across sandbox
        # re-preparation (prepare_sandbox recreates the sandbox, which would
        # otherwise drop it).
        resume = "--resume" in argv
        checkpoint = sandbox_dir / ".zft" / "cache" / "mutants.json"
        saved_checkpoint = checkpoint.read_text() if (resume and checkpoint.exists()) else None

        led = RunLedger.start(root / ".zft" / "runs",
                              manifest={"stage": "L2-fast", "module": module.name},
                              repo=root)
        sandbox = prepare_sandbox(sandbox_dir, mutate_paths=[module],
                                  also_copy=[c for c in (_oracle_path(argv),
                                                         _conftest_path(argv))
                                             if c is not None]
                                  + ([tests] if tests.is_dir() else []))
        if saved_checkpoint is not None:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(saved_checkpoint)
        in_sandbox = place_tests(sandbox, tests, root)
        result = run_campaign(sandbox, test_paths=[str(in_sandbox.relative_to(sandbox))],
                              scope_functions=scope, timeout_s=120, ledger=led,
                              repo_root=root, resume=resume)
        led.append({"event": "campaign_summary", "ok": result.ok,
                    "total": result.total_mutants, "killed": result.killed,
                    "in_scope_killed": result.in_scope_killed,
                    "in_scope_total": result.in_scope_total,
                    "resumed": result.resumed,
                    "timed_out": len(result.timed_out)})
        led.close()
        print(json.dumps({"ok": result.ok, "total": result.total_mutants,
                          "killed": result.killed,
                          "in_scope_killed": result.in_scope_killed,
                          "in_scope_total": result.in_scope_total,
                          "resumed": result.resumed,
                          "timed_out": len(result.timed_out),
                          "survivors": result.survivor_names}, indent=1))
        return 0 if result.ok else 1

    if cmd == "repro":
        from zft.debug.repro import repro as repro_run

        if not rest:
            print("usage: zft repro <run_id> [root]")
            return 2
        run_id = rest[0]  # positional
        if run_id.startswith("--"):
            print("usage: zft repro <run_id> [root]")
            return 2
        try:
            # _split_root misreads rest[0] (the run id) as root, so rebind
            # here: root is rest[1] when given, else cwd (zft lineage fix)
            root = Path(rest[1]).resolve() if len(rest) > 1 else Path.cwd()
            if not root.exists():
                print(f"repro: root does not exist: {root}")
                return 2
            result = repro_run(root, root / ".zft" / "runs", run_id)
        except (FileNotFoundError, KeyError):
            print(json.dumps({"code": "no_such_run", "repro": run_id}, indent=2))
            return 1
        print(json.dumps(result.__dict__, indent=2))
        return 0 if result.recovered else 1

    if cmd == "attest":
        from securesystemslib.signer import CryptoSigner

        from zft.attest.dsse import attest_contract
        from zft.attest.keys import parse_timestamp

        signer = CryptoSigner.generate_ed25519()
        producer_model, gate_model = _model_identity(argv)
        envelope = attest_contract(root, producer_model=producer_model,
                                   gate_model=gate_model, signer=signer)
        out_dir = root / ".zft"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "attest.json").write_text(json.dumps(envelope, indent=2))
        # the signer is ephemeral — an envelope without its key is unverifiable,
        # so the key rotates alongside by default; --key-out overrides.
        key_out = Path(_val(argv, "--key-out") or out_dir / "attest-key.pub.json")
        pub = signer.public_key
        # keyid is not part of to_dict() but DSSE verify matches by it —
        # persist it so --key-in can rebuild the Key standalone. --key-expires
        # publishes a validity window into the same document (verify enforces).
        key_doc = {**pub.to_dict(), "keyid": pub.keyid}
        if (expires_raw := _val(argv, "--key-expires")) is not None:
            try:
                key_doc["expires"] = parse_timestamp(expires_raw, "--key-expires").isoformat()
            except ValueError as e:  # KeyValidationError ⊂ ValueError
                print(f"unusable --key-expires {expires_raw!r}: {e}")
                return 2
        key_out.write_text(json.dumps(key_doc))
        print(f"attestation written: {out_dir / 'attest.json'}")
        print(f"verification key written: {key_out}")
        return 0

    if cmd == "export":
        from zft.attest.export import export_attestation

        try:
            out = export_attestation(root, _val(argv, "--format") or "matrix")
        except (FileNotFoundError, ValueError) as e:
            # AttestationError ⊂ ValueError; ValueError also covers unknown formats
            print(f"export refused: {e}")
            return 1
        print(out if isinstance(out, str) else json.dumps(out, indent=2))
        return 0

    if cmd == "verify":
        from zft.attest import dsse
        from zft.attest.export import load_envelope
        from zft.attest.keys import KeyDocument

        key_in = _val(argv, "--key-in")
        if not key_in:
            print("verify requires --key-in <public-key.json>")
            return 2
        key_path = Path(key_in)
        if not key_path.exists():
            print(f"key file not found: {key_in}")
            return 2
        try:
            key_document = KeyDocument.load(key_path)
        except (OSError, ValueError) as e:  # KeyValidationError ⊂ ValueError
            print(f"unusable key file {key_in}: {e}")
            return 2
        try:
            payload = dsse.verify_attestation(
                load_envelope(root),
                expected_subjects={s["name"]: s["digest"]["sha256"]
                                   for s in dsse.clause_subjects(root)},
                key_document=key_document,
                expect_keyid=_val(argv, "--expect-keyid"))
        except FileNotFoundError as e:
            print(f"verify refused: {e}")
            return 1
        except dsse.AttestationError as e:
            print(f"verify failed: {e}")
            return 1
        print(f"verified: signature ok, {len(payload['subject'])} "
              f"clause subject(s) match store")
        return 0

    if cmd == "negotiate":
        import os

        from zft.debug.ledger import RunLedger
        from zft.negotiate.resume import advance_to_validated, resume
        from zft.negotiate.sm import DEFAULT_RETRY_BUDGET, IllegalTransition, NegotiationSM
        from zft.negotiate.terms import CounterTermsError, parse_counter_terms, terms_digest
        from zft.spec.store import load_contract

        sheet = _val(argv, "--counter-terms")
        try:
            if sheet is None:
                terms = None
            else:
                raw = sys.stdin.buffer.read() if sheet == "-" \
                    else Path(sheet).read_bytes()
                terms = parse_counter_terms(raw)
        except (OSError, CounterTermsError) as e:
            print(f"counter-terms refused: {e}")
            return 2

        contract = load_contract(root)
        resumed = resume(root / ".zft" / "runs")
        if resumed is not None:
            led, sm = resumed
            print(f"resuming negotiation run {led.run_id} from {sm.state} "
                  f"({len(sm.history)} transition(s) replayed)")
        else:
            led = RunLedger.start(root / ".zft" / "runs",
                                  manifest={"stage": "negotiate",
                                            "retry_budget": DEFAULT_RETRY_BUDGET},
                                  repo=root)
            sm = NegotiationSM.start()
            led.append({"event": "cfp", "contract": contract["name"],
                        "clauses": len(contract["clause_ids"])})
        # every transition lands in the ledger as it happens: a kill -9 leaves
        # a durable protocol prefix that the next invocation resumes (kill seam
        # below is the demo's deterministic trigger, not a product code path).
        try:
            advance_to_validated(sm, led,
                                 kill_after=os.environ.get(
                                     "ZFT_NEGOTIATE_KILL_AFTER"),
                                 terms=terms)
        except IllegalTransition as e:
            led.close()  # run stays unfinished — still resumable with its sheet
            print(f"negotiation rejected: {e}")
            return 1
        if sm.state == "REFUSED":
            led.close()
            reason = sm.history[-1].get("reason", "")
            print(f"negotiation refused: REFUSED — {reason} (see run {led.run_id})")
            return 1
        outcome = {"event": "validated", "version": contract["version"] + 1}
        if terms is not None:  # a real bargain: bind the outcome to its terms
            outcome["terms_digest"] = terms_digest(terms.terms)
            outcome["decision"] = terms.decision
        led.append(outcome)
        led.close()
        print(f"negotiation complete: {sm.state} (see run {led.run_id})")
        return 0

    if cmd == "task-gate":
        from zft.taskgate import gate_after, gate_before

        # parse directly from argv: _split_root would misread the phase
        # positional ("before"/"after") as the root
        phase = argv[1] if len(argv) > 1 else None
        subagent = _val(argv, "--subagent") or ""
        description = _val(argv, "--description") or ""
        root = Path.cwd()
        if phase == "before":
            code, payload = gate_before(subagent, description, root)
        elif phase == "after":
            code, payload = gate_after(subagent, description, root)
        else:
            print("usage: zft task-gate <before|after> --subagent <type> "
                  "--description <text>")
            return 2
        print(json.dumps(payload, indent=2))
        return code

    print(f"unknown command: {cmd}")
    return 2


def _oracle_path(argv: list[str]) -> Path | None:
    val = _val(argv, "--oracle")
    return Path(val) if val else None


def _conftest_path(argv: list[str]) -> Path | None:
    val = _val(argv, "--conftest")
    return Path(val) if val else None


if __name__ == "__main__":
    sys.exit(main())
