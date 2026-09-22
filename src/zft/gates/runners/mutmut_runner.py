"""C-23 (final): scoped mutation campaign runner — plan-B micro-mutator.

Decision record (C-36, oracle review): mutmut 3.7's stats run collapses on
sandbox layouts that also carry oracle/package mirrors (it copies tests into
mutants/ before stats and collects both copies). Instead of fighting its
internals we implement the runner directly on the plan's terms:

  - one mutant per single-operator/constant mutation of the module source;
  - equivalent-suspect filtering at generation time (mutated text == original);
  - subprocess pytest per mutant (isolated, kill-on-first-failure); timeouts
    are their own verdict class — never counted as kills or survivors;
  - per-mutant verdict events -> run ledger (checkpoint/resume for free).
"""
from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.gates.runners.pytest_runner import run_pytest
from zft.gates.sandbox import gate_env

OPS = [
    (re.compile(r"=="), "!="),
    (re.compile(r"!="), "=="),
    (re.compile(r">"), "<"),
    (re.compile(r"<"), ">="),
    (re.compile(r"\+"), "-"),
    (re.compile(r"return True\b"), "return False"),
    (re.compile(r"return False\b"), "return True"),
]


@dataclass
class CampaignResult:
    ok: bool
    total_mutants: int
    executed: int
    killed: int
    survivors: list[str]
    survivor_names: list[str]
    duration_ms: int
    resumed: int = 0
    tail: str = ""
    in_scope_killed: int = 0
    in_scope_total: int = 0
    # a hang is not evidence of a caught mutant: timed-out mutants are
    # excluded from `killed` and reported as their own class (wave2 risk #1)
    timed_out: list[str] = field(default_factory=list)


def generate_mutants(source: str, filename: str = "module.py") -> list[tuple[str, str, str]]:
    """One single-op mutant per matched line: (name, mutated_source, function)."""
    fn_ranges = []
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # class-body methods must attribute to <Class>.<method>: mapping
            # them to <module> makes them unscopeable and mislabels survivors
            # (triage T-2 — the whole predicate parser P was invisible).
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_ranges.append(
                        (sub.lineno, sub.end_lineno or sub.lineno,
                         f"{node.name}.{sub.name}"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_ranges.append((node.lineno, node.end_lineno or node.lineno, node.name))

    def fn_for(line_no: int) -> str:
        for start, end, name in fn_ranges:
            if start <= line_no <= end:
                return name
        return "<module>"

    mutants = []
    lines = source.splitlines(keepends=True)
    for lineno, line in enumerate(lines, 1):
        if re.match(r"\s*#", line):
            continue
        for pattern, repl in OPS:
            if not pattern.search(line):
                continue
            mutated = pattern.sub(repl, line, count=1)  # one op per mutant
            if mutated == line:
                continue
            new_src = "".join(lines[: lineno - 1]) + mutated + "".join(lines[lineno:])
            try:
                ast.parse(new_src)
            except SyntaxError:
                continue
            fn = fn_for(lineno)
            name = f"{filename}::fn:{fn}::line:{lineno}::{pattern.pattern}->{repl.strip()}"
            mutants.append((name, new_src, fn))
    return mutants


def run_campaign(
    sandbox: Path,
    test_paths: list[str] | None = None,
    scope_functions: set[str] | None = None,
    timeout_s: int = 300,
    ledger: RunLedger | None = None,
    resume: bool = False,
    repo_root: Path | None = None,
    max_mutants: int | None = None,
    fail_fast: bool = False,
) -> CampaignResult:
    """Run a scoped mutation campaign (plan C-23/C-24), resumable via ledger.

    WP-C3 adds bounded execution controls:
      max_mutants — caps the number of mutants actually executed; once
        reached, remaining mutants are skipped and are neither executed nor
        treated as survivors.
      fail_fast — stops the campaign after the first in-scope survivor.

    Scope note: true multi-process parallelism is deferred. The runner
    mutates one shared module file, so concurrent workers would clobber it.
    """
    sandbox = Path(sandbox)
    t0 = time.perf_counter()
    module_path = sandbox / _mutate_paths(sandbox)[0]
    original = module_path.read_text()

    mutants = generate_mutants(original, module_path.name)
    prior: dict[str, bool] = {}
    checkpoint = sandbox / ".zft" / "cache" / "mutants.json"
    if resume and checkpoint.exists():
        prior = json.loads(checkpoint.read_text())

    killed = executed = resumed = 0
    survivors: list[str] = []
    timed_out: list[str] = []
    in_scope_killed = in_scope_total = 0

    for name, src_text, fn in mutants:
        # scope entries are bare names (CLI --scope f1,f2): a qualified class
        # method matches its bare method name so scoping sees class bodies
        in_scope = (scope_functions is None or fn in scope_functions
                    or fn.rsplit(".", 1)[-1] in scope_functions)
        if in_scope:
            in_scope_total += 1
        else:
            # Wave C / WP-C1: scope is an execution filter, not
            # attribution-only. Out-of-scope mutants are attributed to
            # total_mutants but never written or executed (and thus never
            # resumed, cached, or reported).
            continue
        if max_mutants is not None and executed >= max_mutants:
            # WP-C3: the mutation budget is reached; remaining mutants are
            # not executed and are not counted as survivors.
            break
        if resume and name in prior:
            resumed += 1
            outcome = _outcome(prior[name])
            if outcome == "killed":
                killed += 1
                in_scope_killed += 1  # C4: resumed in-scope kills are preserved
            elif outcome == "timeout":
                timed_out.append(name)
            else:
                survivors.append(name)
            continue
        module_path.write_text(src_text)
        result = _run_pytest_env(sandbox, test_paths, timeout_s, repo_root)
        executed += 1
        if result.timed_out:
            outcome = "timeout"
            timed_out.append(name)
        elif result.ok:
            outcome = "survived"
            survivors.append(name)
        else:
            outcome = "killed"
            killed += 1
            in_scope_killed += 1  # out-of-scope mutants are skipped above
        if ledger:
            ledger.append({"event": "mutant_verdict", "name": name, "ok": result.ok,
                           "function": fn, "in_scope": in_scope,
                           "timed_out": result.timed_out,
                           "duration_ms": result.duration_ms})
        cache_dir = sandbox / ".zft" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "mutants.json"
        state = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        # C4: store outcome + scope so a resumed run can recompute in-scope
        # counts correctly (legacy bare bool/str entries still load).
        state[name] = {"outcome": outcome, "in_scope": in_scope}
        cache_file.write_text(json.dumps(state, sort_keys=True))
        if fail_fast and in_scope and result.ok:
            # WP-C3: stop after the first in-scope survivor.
            break

    module_path.write_text(original)
    final_ok = _run_pytest_env(sandbox, test_paths, timeout_s, repo_root).ok
    # Wave C / WP-C2 — exact ok rule:
    #   ok = final_ok and no in-scope survivors
    # Since WP-C1 skips out-of-scope mutants before execution (above), every
    # entry in `survivors` is in-scope (with scope_functions=None, all mutants
    # are in-scope), so `survivors` IS the in-scope survivor set. An in-scope
    # survivor means the suite cannot distinguish the mutation (refinement
    # signal) and must red the campaign. Timed-out mutants are neither killed
    # nor survivors (wave2 risk #1) and do not affect ok; equivalent-suspect
    # mutants are filtered at generation time and never reach this rule.
    ok = final_ok and not survivors
    duration_ms = int((time.perf_counter() - t0) * 1000)
    return CampaignResult(
        ok=ok,
        total_mutants=len(mutants),
        executed=executed,
        killed=killed,
        survivors=survivors,
        survivor_names=survivors,
        duration_ms=duration_ms,
        resumed=resumed,
        in_scope_killed=in_scope_killed,
        in_scope_total=in_scope_total,
        timed_out=timed_out,
    )


def _outcome(cached: object) -> str:
    """Classify a checkpoint entry; legacy checkpoints store booleans/strings."""
    if isinstance(cached, dict):
        cached = cached.get("outcome")
    if cached == "timeout":
        return "timeout"
    if cached is False or cached == "killed":
        return "killed"
    return "survived"


def _run_pytest_env(sandbox, test_paths, timeout_s, repo_root):
    """Run pytest under the gate-isolation env (gates.sandbox.gate_env), with
    ZFT_REPO pointing at the real repo (location-independent tests)."""
    extra = {"ZFT_REPO": str(Path(repo_root))} if repo_root is not None else None
    return run_pytest(sandbox, list(test_paths or []), timeout_s=timeout_s,
                      env=gate_env(extra))


def _mutate_paths(sandbox: Path) -> list[str]:
    import tomllib

    data = tomllib.loads((sandbox / "pyproject.toml").read_text())
    return data["tool"]["mutmut"]["paths_to_mutate"]


def parse_results(sandbox: Path):
    """Recover verdicts from the campaign checkpoint file, if present.

    Returns (survivors, total, killed); timeout entries count in `total`
    only — a hang is attributable, not a kill.
    """
    led_file = sandbox / ".zft" / "cache" / "mutants.json"
    if not led_file.exists():
        return [], 0, 0
    data = json.loads(led_file.read_text())
    survivors = [name for name, v in data.items() if _outcome(v) == "survived"]
    killed = sum(1 for v in data.values() if _outcome(v) == "killed")
    return survivors, len(data), killed
