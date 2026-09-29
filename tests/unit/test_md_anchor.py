"""WP-D3: first-class Markdown @trace anchors.

A line `<!-- @trace("ALIAS") -->` immediately above an ATX heading
(`#` .. `######`) yields a binding `{alias, file, line, symbol}` where
`line` is the comment line (1-based) and `symbol` is the GitHub-style
slug of the heading text. The comment is the anchor's identity: a heading
rename changes only `symbol`, not `alias`/`file`. Fence-aware: anchors
and headings inside fenced code blocks (``` / ~~~) are not extracted.
"""
from pathlib import Path

from zft.lineage.extract import extract_bindings

REPO = Path(__file__).resolve().parents[2]


def _shipped() -> set[str]:
    """Top-level prefixes that ship publicly, parsed from the export guard's
    ALLOWLIST (tools/export-cut-check.sh) — the one source of truth. The
    binding snapshot must track the *shipped* repo: committed-but-internal
    trees (examples/, paper/) do not ship, so their bindings would desync
    the moment the same tests run against the public cut."""
    here = Path(__file__).resolve().parents[2] / "tools" / "export-cut-check.sh"
    entries, in_list = [], False
    for line in here.read_text().splitlines():
        if line.startswith("ALLOWLIST=("):
            in_list = True
            continue
        if in_list:
            if line.strip() == ")":
                break
            entries.extend(line.strip().strip('"').split())
    return set(entries)


def _shipped_bindings(repo: Path) -> list:
    """Bindings from files the repo actually ships."""
    prefixes = _shipped()
    out = []
    for b in extract_bindings(repo):
        if any(b["file"] == p or b["file"].startswith(p + "/") for p in prefixes):
            out.append(b)
    return out

DOC = """\
# Title

<!-- @trace("ALPHA") -->
## Alpha Section

Some prose.
"""

# Baseline captured at WP-D3 (HEAD 90875a7): every binding the repo's
# Python sources produce, as (file, line, alias, symbol). The Markdown
# feature must not change any of them.
# Re-derived 2026-09-21 at the fleet fold (zft adoption merge): the three
# negotiate anchors shifted 48->51 / 81->84 / ->109 on the merged tree.
# Re-derived 2026-09-27 (gate baseline-verdict surfacing): test_cli_wiring
# anchors +1 line (the baseline_ok JSON pin), and the campaign's red-baseline
# guard adds one GATE-MUTATION-ATTRIBUTION binding (test_mutmut_runner:143).
# Re-derived 2026-09-28 (changeset-scoped after-gate, ENF-CHANGESET-VERDICT):
# fourteen new test anchors (8 + the git-diagnostic test in test_taskgate,
# 5 in test_cli_wiring); taskgate's classify anchors +1 line (subprocess
# import), the reason-noise test shifts test_since_ref_without_git 345 -> 363.
# The negotiate manifest guard adds a src anchor (CON-VALIDATED-OR-NO-START).
BASELINE_PY_BINDINGS = {
    ('src/zft/spec/store.py', 50,
     'CON-VALIDATED-OR-NO-START', 'require_contract_keys'),
    ('src/zft/lineage/matrix.py', 125, 'TR-REVERSE-COVERAGE', 'new_unbound_elements'),
    ('src/zft/taskgate.py', 61, 'ENF-CAPABILITY-CLASSIFICATION', 'classify'),
    ('src/zft/taskgate.py', 79, 'ENF-CAPABILITY-CLASSIFICATION', 'classify_trace'),
    ('tests/e2e/test_negotiate_resumption.py', 51,
     'CON-CRASH-RESUME', 'test_kill9_mid_protocol_resumes_same_run'),
    ('tests/e2e/test_negotiate_transport_resumption.py', 84,
     'PRT-A2A-TRANSPORT', 'test_kill9_mid_wire_protocol_resumes_same_run'),
    ('tests/unit/test_a2a_adapter.py', 14,
     'PRT-A2A-ENVELOPE', 'test_wire_roundtrip_with_history_and_artifacts'),
    ('tests/unit/test_attest.py', 45,
     'ATT-SIGNED-ACCEPTANCE', 'test_sign_and_verify_real_contract'),
    ('tests/unit/test_attest.py', 213,
     'ATT-SIGNED-ACCEPTANCE', 'test_mock_signer_roundtrip_through_attest_contract'),
    ('tests/unit/test_attest_cli.py', 75,
     'ATT-EXPORTS-FROM-ATTESTATIONS', 'test_cli_export_refuses_without_attestation'),
    ('tests/unit/test_attest_cli.py', 138,
     'ATT-SIGNED-ACCEPTANCE', 'test_cli_attest_then_export_roundtrip_on_tmp_store'),
    ('tests/unit/test_attest_cli.py', 173,
     'ATT-SIGNED-ACCEPTANCE', 'test_cli_attest_sign_persist_verify_roundtrip_on_live_store'),
    ('tests/unit/test_canon.py', 51, 'ID-CONTENT-CHANGE', 'test_meaning_changes_move_hash'),
    ('tests/unit/test_cli_wiring.py', 84,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_task_gate_capability_json_classifies_writer'),
    ('tests/unit/test_cli_wiring.py', 99,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_task_gate_capability_json_classifies_readonly'),
    ('tests/unit/test_cli_wiring.py', 113,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_task_gate_malformed_capability_falls_back_to_name'),
    ('tests/unit/test_cli_wiring.py', 127,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_task_gate_explain_classifies_without_enforcing'),
    ('tests/unit/test_cli_wiring.py', 155,
     'ENF-CHANGESET-VERDICT', 'test_task_gate_after_changed_flag_scopes'),
    ('tests/unit/test_cli_wiring.py', 171,
     'ENF-CHANGESET-VERDICT', 'test_task_gate_after_scope_changeset_without_paths'),
    ('tests/unit/test_cli_wiring.py', 188,
     'ENF-CHANGESET-VERDICT', 'test_task_gate_after_default_is_tree_scope'),
    ('tests/unit/test_cli_wiring.py', 201,
     'ENF-CHANGESET-VERDICT', 'test_task_gate_after_since_ref_forwarded'),
    ('tests/unit/test_cli_wiring.py', 216,
     'ENF-CHANGESET-VERDICT', 'test_task_gate_usage_documents_changeset_flags'),
    ('tests/unit/test_delta_conflicts.py', 34,
     'CON-AMEND-VIA-DELTAS', 'test_modified_requires_matching_old_hash'),
    ('tests/unit/test_delta_conflicts.py', 55,
     'ID-CONFLICT-HALT', 'test_concurrent_edit_conflict_detected'),
    ('tests/unit/test_driver_gate.py', 72,
     'DRIVER-GATE-GREEN', 'test_driver_gate_green_on_seeded_workspace'),
    ('tests/unit/test_gherkin_gen.py', 39,
     'TR-FORWARD-COVERAGE', 'test_all_clauses_collect_and_pass'),
    ('tests/unit/test_impact.py', 15, 'TR-IMPACT-QUERY', 'test_file_level_match'),
    ('tests/unit/test_impact.py', 23, 'TR-IMPACT-QUERY', 'test_symbol_narrowing'),
    ('tests/unit/test_impact.py', 32, 'TR-IMPACT-QUERY', 'test_suffix_match'),
    ('tests/unit/test_impact.py', 38, 'TR-IMPACT-QUERY', 'test_impact_from_root'),
    ('tests/unit/test_impact_cli.py', 13, 'TR-IMPACT-QUERY', 'test_impact_cli_func'),
    ('tests/unit/test_impact_cli.py', 18, 'TR-IMPACT-QUERY', '_run_impact'),
    ('tests/unit/test_impact_cli.py', 27, 'TR-IMPACT-QUERY', 'test_file_path_impact'),
    ('tests/unit/test_impact_cli.py', 36, 'TR-IMPACT-QUERY', 'test_symbol_narrowing'),
    ('tests/unit/test_impact_cli.py', 46, 'TR-IMPACT-QUERY', 'test_unknown_target'),
    ('tests/unit/test_impact_cli.py', 53, 'TR-IMPACT-QUERY', 'test_base_flag_honest_rejection'),
    ('tests/unit/test_l0.py', 31, 'CON-TYPED-REJECTIONS', 'test_l0_failure_is_typed'),
    ('tests/unit/test_l1.py', 43, 'GATE-EVIDENCE-KIND', 'test_l1_green_passes_on_passing_suite'),
    ('tests/unit/test_l2.py', 50, 'GATE-JUDGE-QUARANTINE', 'test_l2_fast_green_on_mini_repo'),
    ('tests/unit/test_l2.py', 114,
     'GATE-MODEL-INDEPENDENCE', 'test_gate_log_labels_model_dependence'),
    ('tests/unit/test_l3.py', 84,
     'GATE-MODEL-INDEPENDENCE', 'test_model_dependence_labeled_from_producer_and_gate_models'),
    ('tests/unit/test_lineage_extract.py', 49,
     'TR-DETERMINISTIC-EXTRACTION', 'test_extraction_is_deterministic'),
    ('tests/unit/test_lint_store.py', 23,
     'GATE-L0-HASH-VERIFY', 'test_torn_trailing_hash_line_detected'),
    ('tests/unit/test_lint_store.py', 39,
     'GATE-DUPLICATE-CLAUSES', 'test_duplicate_clause_detection'),
    ('tests/unit/test_mutmut_runner.py', 123,
     'GATE-MUTATION-ATTRIBUTION', 'test_campaign_kills_and_classifies'),
    ('tests/unit/test_mutmut_runner.py', 143,
     'GATE-MUTATION-ATTRIBUTION', 'test_baseline_red_is_surfaced_not_silent'),
    ('tests/unit/test_negotiate_flow.py', 20,
     'CON-COUNTER-RECORDED', 'test_negotiate_flow_runs_on_own_contract'),
    ('tests/unit/test_negotiate_transport.py', 109,
     'PRT-A2A-TRANSPORT', 'test_full_protocol_over_wire_with_official_sdk_client'),
    ('tests/unit/test_negotiation.py', 47, 'PRT-TYPED-REFUSAL', 'test_pre_commitment_refusal'),
    ('tests/unit/test_negotiation.py', 56,
     'CON-VALIDATED-OR-NO-START', 'test_illegal_transitions_blocked'),
    ('tests/unit/test_predicate.py', 204, 'DSL-COMPILE-GENERATORS', 'test_golden_all_26_compile'),
    ('tests/unit/test_predicate.py', 205,
     'DSL-TRIGGER-PREDICATE-ENFORCEMENT', 'test_golden_all_26_compile'),
    ('tests/unit/test_schema_identity.py', 33, 'ID-UUIDV7-ALIAS', 'test_new_uuid7_is_v7_canonical'),
    ('tests/unit/test_strategies_oracle.py', 191,
     'DSL-JUDGE-ESCAPE-HATCH', 'test_judge_clause_has_no_compile_requirement'),
    ('tests/unit/test_symbols.py', 29, 'TR-IMPACT-QUERY', 'test_symbol_anchor_tracks_rename'),
    ('tests/unit/test_symbols.py', 39,
     'TR-UNRESOLVED-BINDINGS-FAIL', 'test_unresolvable_alias_reported'),
    ('tests/unit/test_symbols.py', 52,
     'TR-REVERSE-COVERAGE', 'test_reverse_coverage_flags_unbound_elements'),
    ('tests/unit/test_taskgate.py', 19,
     'ENF-WRITER-REQUIRES-CONTRACT', 'test_writer_without_contract_blocks'),
    ('tests/unit/test_taskgate.py', 29,
     'ENF-WRITER-REQUIRES-CONTRACT', 'test_writer_with_contract_allowed'),
    ('tests/unit/test_taskgate.py', 39, 'ENF-READONLY-EXEMPT', 'test_readonly_lane_exempt'),
    ('tests/unit/test_taskgate.py', 48,
     'ENF-CONTRACT-VERDICT', 'test_after_verdict_covered_then_missing'),
    ('tests/unit/test_taskgate.py', 84,
     'ENF-AUDIT-LOGGED', 'test_override_decision_audited_ungated'),
    ('tests/unit/test_taskgate.py', 135,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_both_denied_is_readonly'),
    ('tests/unit/test_taskgate.py', 141,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_no_rules_means_producer'),
    ('tests/unit/test_taskgate.py', 149,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_catchall_allow_from_defaults'),
    ('tests/unit/test_taskgate.py', 158,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_ask_is_a_capability'),
    ('tests/unit/test_taskgate.py', 165,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_later_rule_wins_over_earlier'),
    ('tests/unit/test_taskgate.py', 176,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_edit_synonyms_count'),
    ('tests/unit/test_taskgate.py', 186,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_granular_allow_is_producer'),
    ('tests/unit/test_taskgate.py', 198,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_capability_name_fallback_when_no_ruleset'),
    ('tests/unit/test_taskgate.py', 206,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_classify_trace_records_source_and_rules'),
    ('tests/unit/test_taskgate.py', 219,
     'ENF-CAPABILITY-CLASSIFICATION', 'test_gate_before_uses_capability_ruleset'),
    ('tests/unit/test_taskgate.py', 257,
     'ENF-CHANGESET-VERDICT', 'test_changeset_scope_counts_only_changed_paths'),
    ('tests/unit/test_taskgate.py', 272,
     'ENF-CHANGESET-VERDICT', 'test_changeset_empty_reports_everything_missing'),
    ('tests/unit/test_taskgate.py', 283,
     'ENF-CHANGESET-VERDICT', 'test_changeset_directory_prefix_and_relative_paths'),
    ('tests/unit/test_taskgate.py', 296,
     'ENF-CHANGESET-VERDICT', 'test_unscoped_after_stays_tree_mode'),
    ('tests/unit/test_taskgate.py', 305,
     'ENF-CHANGESET-VERDICT', 'test_since_ref_covers_tracked_and_untracked'),
    ('tests/unit/test_taskgate.py', 321,
     'ENF-CHANGESET-VERDICT', 'test_since_ref_and_changed_union'),
    ('tests/unit/test_taskgate.py', 334,
     'ENF-CHANGESET-VERDICT', 'test_since_ref_unresolvable_is_error_not_inflated'),
    ('tests/unit/test_taskgate.py', 349,
     'ENF-CHANGESET-VERDICT', 'test_since_ref_reason_names_fatal_not_usage_outside_repo'),
    ('tests/unit/test_taskgate.py', 363,
     'ENF-CHANGESET-VERDICT', 'test_since_ref_without_git_is_error'),
}


def test_md_anchor_yields_binding_with_slug_symbol(tmp_path):
    (tmp_path / "doc.md").write_text(DOC)
    bindings = extract_bindings(tmp_path)
    assert len(bindings) == 1, f"exactly one anchor must bind: {bindings!r}"
    b = bindings[0]
    assert b["alias"] == "ALPHA"
    assert b["file"] == "doc.md"
    assert b["line"] == 3, "`line` is the comment line, 1-based"
    assert b["symbol"] == "alpha-section", "GitHub-style slug of the heading"
    # Deterministic output.
    assert extract_bindings(tmp_path) == bindings


def test_md_anchor_stable_across_heading_rename(tmp_path):
    (tmp_path / "doc.md").write_text(DOC)
    before = extract_bindings(tmp_path)[0]
    # Rename the heading; the comment (the anchor) is unchanged. The rewrite
    # also appends a blank line so the (mtime_ns, size) cache key cannot
    # alias the two versions on filesystems with coarse timestamp granularity.
    (tmp_path / "doc.md").write_text(
        DOC.replace("## Alpha Section", "## Renamed Alpha") + "\n")
    after = extract_bindings(tmp_path)[0]
    assert after["symbol"] == "renamed-alpha"
    assert after["alias"] == before["alias"] == "ALPHA"
    assert after["file"] == before["file"] == "doc.md"
    assert after["line"] == before["line"] == 3


# Tilde fence on purpose: the inner backtick fence lines are *content*, and
# the trailing backtick fence must not close the tilde fence. The comment
# directly above the fence open is not above a heading, so it binds nothing.
FENCED = """\
# Title

<!-- @trace("ABOVE-FENCE") -->
~~~
<!-- @trace("IN-FENCE") -->
## Fenced Heading
```
still inside the tilde fence
```
~~~

## Real Heading
"""


def test_md_anchors_inside_fences_ignored(tmp_path):
    (tmp_path / "fenced.md").write_text(FENCED)
    bindings = extract_bindings(tmp_path)
    assert bindings == [], \
        f"no md anchor may bind inside or adjacent to a fence: {bindings!r}"
    aliases = {b["alias"] for b in extract_bindings(tmp_path)}
    assert "ABOVE-FENCE" not in aliases
    assert "IN-FENCE" not in aliases


def test_real_repo_has_no_markdown_bindings():
    bindings = _shipped_bindings(REPO)
    md = [b for b in bindings if b["file"].endswith(".md")]
    assert not md, f"unexpected Markdown-sourced bindings: {md!r}"
    got = {(b["file"], b["line"], b["alias"], b["symbol"]) for b in bindings}
    assert got == BASELINE_PY_BINDINGS, "Python bindings must be unchanged"
