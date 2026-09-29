"""Task gate (ENF clauses): pre-dispatch enforcement + post-task coverage verdict.

Writer lanes may only be dispatched against a contract that exists on file
(`[contract: NAME]` in the task description resolving to
.zft/contracts/NAME.json); read-only lanes are exempt. An ungated override
(`[ungated: reason]` or a truthy ZFT_ALLOW_UNGATED) allows a writer
dispatch but is flagged `gated: False` in the audit log. Every decision —
allowed, blocked, verdict, error — appends exactly one JSONL record to
<zft-root>/.zft/audit.log.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

READONLY_LANES: set[str] = {
    "explorer", "explore", "code-explorer", "librarian", "oracle",
    "analyst", "councillor", "vision", "vision-consultant", "researcher",
}

# opencode treats edit/write/apply_patch as one permission group
# (permission/index.ts disabled()); a rule for any of them counts for both.
EDIT_PERMS: set[str] = {"edit", "write", "apply_patch"}
BASH_PERMS: set[str] = {"bash"}

CONTRACT_RE = re.compile(r"\[contract:\s*([A-Za-z0-9._-]+)\]")
OVERRIDE_RE = re.compile(r"\[ungated:\s*([^\]]+)\]")


def _wildcard_match(value: str, pattern: str) -> bool:
    """opencode Wildcard.match: '*' and '?' globs over the value."""
    if pattern == "*":
        return True
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, value) is not None


def _is_capable(rules: list[dict], perms: set[str]) -> bool:
    """Mirrors opencode's own disabled() heuristic: the agent is incapable of
    a mutation iff the LAST rule whose permission name matches is a catch-all
    ('*') deny. No matching rule at all means opencode's default action
    ('ask'), which can still run after approval — hence capable.

    merge() concatenates with no dedup, so later rules win; scanning for any
    allow/ask would be fooled by a later override.
    """
    last = None
    for rule in rules:
        if any(_wildcard_match(p, rule.get("permission", "")) for p in perms):
            last = rule
    if last is not None and last.get("pattern") == "*" and last.get("action") == "deny":
        return False
    return True


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def classify(subagent: str, rules: list[dict] | None = None) -> str:
    """Lane classification.

    With a resolved permission ruleset (opencode's PermissionRule[]), the lane
    follows the capability: producer iff it can edit or run bash, read-only iff
    both are catch-all denied. Without one, the lane name decides — unknown
    subagent types default to writer (safe side).

    Case-insensitive: harnesses capitalize agent types (zcode's `Explore`),
    opencode uses lowercase — same lane either way.
    """
    if rules is not None:
        capable = _is_capable(rules, EDIT_PERMS) or _is_capable(rules, BASH_PERMS)
        return "writer" if capable else "readonly"
    return "readonly" if subagent.strip().lower() in READONLY_LANES else "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def classify_trace(subagent: str, rules: list[dict] | None = None) -> dict:
    """Single debug record for one classification decision.

    source: "capability" (ruleset decided), "name" (lane-name fallback hit the
    read-only list), "default" (name fallback, unknown name -> writer).
    found: whether a ruleset was supplied at all (i.e. the agent was resolved
    by the harness).
    """
    lane = classify(subagent, rules)
    if rules is not None:
        source = "capability"
    elif lane == "readonly":
        source = "name"
    else:
        source = "default"
    return {"lane": lane, "source": source, "rules": rules, "found": rules is not None}


def parse_contract(description: str) -> str | None:
    """Extract the contract reference from `[contract: NAME]`, else None."""
    m = CONTRACT_RE.search(description)
    return m.group(1) if m else None


def parse_override(description: str) -> str | None:
    """Extract the ungated-override reason from `[ungated: text]`, else None."""
    m = OVERRIDE_RE.search(description)
    return m.group(1) if m else None


def append_audit(root: Path, record: dict) -> None:
    """Append one JSONL record to root/.zft/audit.log (mkdir parents)."""
    path = Path(root) / ".zft" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_override() -> str | None:
    """ZFT_ALLOW_UNGATED with a truthy value authorizes an ungated dispatch."""
    val = os.environ.get("ZFT_ALLOW_UNGATED", "").strip().lower()
    return val if val in {"1", "true", "yes", "on"} else None


def _audit(root: Path, lane: str, subagent: str, **fields) -> None:
    append_audit(root, {"ts": _now(), "subagent": subagent, "lane": lane, **fields})


def _o1_timing(since_ms: int | None, dispatch_id: str | None, t0: float) -> dict:
    """Optional O1 instrumentation fields for one audit record (gates-bench
    v3 §1): the caller-supplied dispatch identity verbatim plus the core's
    own compute time, measured at audit moment. With no identity supplied the
    record stays byte-compatible with the pre-instrumentation schema."""
    if since_ms is None and dispatch_id is None:
        return {}
    fields: dict = {}
    if since_ms is not None:
        fields["since_ms"] = since_ms
    if dispatch_id is not None:
        fields["dispatch_id"] = dispatch_id
    fields["gate_ms"] = int((time.monotonic() - t0) * 1000)
    return fields


def gate_before(subagent: str, description: str, root: Path,
                 rules: list[dict] | None = None, *,
                 since_ms: int | None = None,
                 dispatch_id: str | None = None) -> tuple[int, dict]:
    """Pre-dispatch enforcement (ENF-WRITER-REQUIRES-CONTRACT, ENF-READONLY-EXEMPT,
    ENF-AUDIT-LOGGED): block writer lanes without a contract reference, exempt
    read-only lanes, always audit. since_ms/dispatch_id (plugin-supplied) and
    the measured gate_ms are stamped on the audit record when supplied."""
    t0 = time.monotonic()

    def o1() -> dict:
        return _o1_timing(since_ms, dispatch_id, t0)

    trace = classify_trace(subagent, rules)
    lane = trace["lane"]
    if lane == "readonly":
        _audit(root, lane, subagent, phase="before", gated=False, contract=None,
               override=False, reason="read-only lane", classification=trace,
               **o1())
        return 0, {"allow": True, "gated": False, "lane": "readonly",
                   "contract": None, "reason": "read-only lane", "override": False,
                   "classification": trace}

    contract = parse_contract(description)
    override = parse_override(description) or _env_override()
    if override:
        _audit(root, lane, subagent, phase="before", gated=False, contract=contract,
               override=True, reason=override, classification=trace, **o1())
        return 0, {"allow": True, "gated": False, "lane": "writer",
                   "contract": contract, "reason": override, "override": True,
                   "classification": trace}

    contract_path = (Path(root) / ".zft" / "contracts" / f"{contract}.json"
                     if contract else None)
    if contract_path is not None and contract_path.exists():
        _audit(root, lane, subagent, phase="before", gated=True, contract=contract,
               override=False, reason="contract on file", classification=trace,
               **o1())
        return 0, {"allow": True, "gated": True, "lane": "writer",
                   "contract": contract, "reason": "contract on file", "override": False,
                   "classification": trace}

    reason = (f"writer lane requires an existing [contract: ...] reference "
              f"({contract})" if contract
              else "writer lane requires a [contract: <name>] reference — none given")
    _audit(root, lane, subagent, phase="before", gated=False, contract=contract,
           override=False, reason=reason, classification=trace, **o1())
    return 1, {"allow": False, "gated": False, "lane": "writer", "contract": contract,
               "reason": reason, "override": False,
               "code": "ENF_WRITER_REQUIRES_CONTRACT", "classification": trace}


def _resolve_changeset(root: Path, changed: list[str] | None,
                       since_ref: str | None) -> tuple[list[str], str | None]:
    """Resolve a declared changeset to root-relative posix paths.

    Returns (paths, None) on success, ([], reason) when the changeset cannot
    be resolved — an unresolvable changeset must surface as an error verdict,
    never silently degrade to (inflated) whole-tree coverage.

    `since_ref` contributes `git diff --name-only <ref>` (tracked modifications
    and commits after ref) plus untracked files (`git ls-files --others`), so
    newly created files with bindings count. Paths outside root are dropped —
    extraction never walks them, so they cannot bind anything.
    """
    raw = list(changed or [])
    if since_ref is not None:
        try:
            diff = subprocess.run(
                ["git", "diff", "--name-only", "-z", since_ref, "--"],
                cwd=str(root), capture_output=True, text=True)
        except OSError as e:  # git not installed
            return [], f"changeset unresolvable (since-ref {since_ref!r}): {e}"
        if diff.returncode != 0:
            return [], (f"changeset unresolvable (since-ref {since_ref!r}): "
                        f"{_git_detail(diff)}")
        raw += [p for p in diff.stdout.split("\0") if p]
        try:
            un = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=str(root), capture_output=True, text=True)
        except OSError as e:
            return [], f"changeset unresolvable (since-ref {since_ref!r}): {e}"
        if un.returncode != 0:
            return [], (f"changeset unresolvable (since-ref {since_ref!r}): "
                        f"{_git_detail(un)}")
        raw += [p for p in un.stdout.split("\0") if p]
    norm: set[str] = set()
    for p in raw:
        target = Path(p) if Path(p).is_absolute() else Path(root) / p
        rel = os.path.relpath(target, root)
        if rel == os.curdir or rel.startswith(".."):
            continue  # outside the store: never extractable, never binding
        norm.add(Path(rel).as_posix())
    return sorted(norm), None


def _git_detail(result) -> str:
    """The diagnostic line of a failed git command: a fatal:/error:/warning:
    line when present (git dumps its usage block AFTER the diagnostic, so the
    tail is an option table), else the first line, else its exit code."""
    text = "\n".join(
        part for part in ((result.stderr or "").strip(), (result.stdout or "").strip())
        if part)
    if text:
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(("fatal:", "error:", "warning:")):
                return s
        return text.splitlines()[0].strip()
    return f"exit {result.returncode}"


def gate_after(subagent: str, description: str, root: Path,
               rules: list[dict] | None = None, *,
               changed: list[str] | None = None,
               since_ref: str | None = None,
               scope: str | None = None,
               since_ms: int | None = None,
               dispatch_id: str | None = None) -> tuple[int, dict]:
    """Post-task verdict (ENF-CONTRACT-VERDICT): forward coverage of the
    contract's due clauses against mechanically extracted bindings.

    due = clause_ids minus clauses deferred to a milestone after
    meta.current_milestone (mirrors gates/l2.py).

    Changeset scoping (ENF-CHANGESET-VERDICT): when `changed`, `since_ref`,
    or scope="changeset" is given, coverage counts only bindings inside those
    paths — the evidence this subagent actually produced. An empty changeset
    therefore reports every due clause missing (no inherited coverage), and
    an unresolvable `since_ref` is an error verdict (exit 2), never a
    silently unscoped one. Without any of the three, behavior is unchanged:
    whole-tree coverage (scope.mode "tree").

    since_ms/dispatch_id (plugin-supplied) and the measured gate_ms — here
    dominated by extract_bindings compute, vs the plugin's spawn-wait
    durationMs — are stamped on the audit record when supplied (O1, v3 §1).
    """
    t0 = time.monotonic()

    def o1() -> dict:
        return _o1_timing(since_ms, dispatch_id, t0)

    trace = classify_trace(subagent, rules)
    lane = trace["lane"]
    if lane == "readonly":
        _audit(root, lane, subagent, phase="after", gated=True, contract=None,
               verdict="n/a", missing=[], classification=trace, **o1())
        return 0, {"verdict": "n/a", "lane": "readonly", "contract": None,
                   "missing": [], "classification": trace}

    contract = parse_contract(description)
    if not contract:
        _audit(root, lane, subagent, phase="after", gated=True, contract=None,
               verdict="error", missing=[], classification=trace, **o1())
        return 2, {"verdict": "error", "contract": None,
                   "reason": "no [contract: <name>] reference in description",
                   "classification": trace}

    cpath = Path(root) / ".zft" / "contracts" / f"{contract}.json"
    try:
        c = json.loads(cpath.read_text())
    except (OSError, json.JSONDecodeError) as e:
        _audit(root, lane, subagent, phase="after", gated=True, contract=contract,
               verdict="error", missing=[], classification=trace, **o1())
        return 2, {"verdict": "error", "contract": contract,
                   "reason": f"contract unreadable: {e}", "classification": trace}

    meta = c.get("meta") or {}
    current = meta.get("current_milestone") or "v0"
    deferred = meta.get("target_milestone") or {}
    clause_ids = set(c.get("clause_ids") or [])
    due = clause_ids - {k for k, v in deferred.items() if v > current}

    if scope is not None and scope != "changeset":
        reason = f"unknown scope {scope!r} (expected 'changeset')"
        _audit(root, lane, subagent, phase="after", gated=True, contract=contract,
               verdict="error", missing=[], classification=trace, reason=reason,
               **o1())
        return 2, {"verdict": "error", "contract": contract, "reason": reason,
                   "classification": trace}

    scoped = scope == "changeset" or changed is not None or since_ref is not None
    scope_desc = {"mode": "tree", "paths": None, "since_ref": None}
    if scoped:
        paths, err = _resolve_changeset(root, changed, since_ref)
        if err is not None:
            scope_desc = {"mode": "changeset", "paths": None,
                          "since_ref": since_ref}
            _audit(root, lane, subagent, phase="after", gated=True,
                   contract=contract, verdict="error", missing=[],
                   classification=trace, scope=scope_desc, reason=err, **o1())
            return 2, {"verdict": "error", "contract": contract, "reason": err,
                       "scope": scope_desc, "classification": trace}
        scope_desc = {"mode": "changeset", "paths": len(paths),
                      "since_ref": since_ref}

    from zft.lineage.extract import extract_bindings

    bindings = extract_bindings(root)
    if scoped:
        rels = set(paths)
        bound = {b["alias"] for b in bindings
                 if b["file"] in rels
                 or any(b["file"].startswith(p + "/") for p in rels)}
    else:
        bound = {b["alias"] for b in bindings}
    missing = sorted(due - bound)
    covered = sorted(due & bound)
    verdict = "covered" if not missing else "missing"
    _audit(root, lane, subagent, phase="after", gated=True, contract=contract,
           verdict=verdict, missing=missing, classification=trace,
           scope=scope_desc, **o1())
    return (0 if not missing else 1), {"verdict": verdict, "contract": contract,
                                       "due": sorted(due), "covered": covered,
                                       "missing": missing, "scope": scope_desc,
                                       "classification": trace}
