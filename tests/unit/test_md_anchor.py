"""WP-D3: first-class Markdown @trace anchors.

A line `<!-- @trace("ALIAS") -->` immediately above an ATX heading
(`#` .. `######`) yields a binding `{alias, file, line, symbol}` where
`line` is the comment line (1-based) and `symbol` is the GitHub-style
slug of the heading text. The comment is the anchor's identity: a heading
rename changes only `symbol`, not `alias`/`file`. Fence-aware: anchors
and headings inside fenced code blocks (``` / ~~~) are not extracted.
"""
from pathlib import Path

from traceagent.lineage.extract import extract_bindings

REPO = Path(__file__).resolve().parents[2]

DOC = """\
# Title

<!-- @trace("ALPHA") -->
## Alpha Section

Some prose.
"""

# Baseline captured at WP-D3 (HEAD 90875a7): every binding the repo's
# Python sources produce, as (file, line, alias, symbol). The Markdown
# feature must not change any of them.
BASELINE_PY_BINDINGS = {
    ('src/traceagent/lineage/matrix.py', 122,
     'TR-REVERSE-COVERAGE', 'new_unbound_elements'),
    ('tests/e2e/test_negotiate_resumption.py', 48,
     'CON-CRASH-RESUME', 'test_kill9_mid_protocol_resumes_same_run'),
    ('tests/e2e/test_negotiate_transport_resumption.py', 81,
     'PRT-A2A-TRANSPORT', 'test_kill9_mid_wire_protocol_resumes_same_run'),
    ('tests/unit/test_a2a_adapter.py', 11,
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
    ('tests/unit/test_canon.py', 51,
     'ID-CONTENT-CHANGE', 'test_meaning_changes_move_hash'),
    ('tests/unit/test_delta_conflicts.py', 34,
     'CON-AMEND-VIA-DELTAS', 'test_modified_requires_matching_old_hash'),
    ('tests/unit/test_delta_conflicts.py', 55,
     'ID-CONFLICT-HALT', 'test_concurrent_edit_conflict_detected'),
    ('tests/unit/test_driver_gate.py', 64,
     'DRIVER-GATE-GREEN', 'test_driver_gate_green_on_seeded_workspace'),
    ('tests/unit/test_gherkin_gen.py', 39,
     'TR-FORWARD-COVERAGE', 'test_all_clauses_collect_and_pass'),
    ('tests/unit/test_impact.py', 15,
     'TR-IMPACT-QUERY', 'test_file_level_match'),
    ('tests/unit/test_impact.py', 23,
     'TR-IMPACT-QUERY', 'test_symbol_narrowing'),
    ('tests/unit/test_impact.py', 32,
     'TR-IMPACT-QUERY', 'test_suffix_match'),
    ('tests/unit/test_impact.py', 38,
     'TR-IMPACT-QUERY', 'test_impact_from_root'),
    ('tests/unit/test_impact_cli.py', 13,
     'TR-IMPACT-QUERY', 'test_impact_cli_func'),
    ('tests/unit/test_impact_cli.py', 18,
     'TR-IMPACT-QUERY', '_run_impact'),
    ('tests/unit/test_impact_cli.py', 27,
     'TR-IMPACT-QUERY', 'test_file_path_impact'),
    ('tests/unit/test_impact_cli.py', 36,
     'TR-IMPACT-QUERY', 'test_symbol_narrowing'),
    ('tests/unit/test_impact_cli.py', 46,
     'TR-IMPACT-QUERY', 'test_unknown_target'),
    ('tests/unit/test_impact_cli.py', 53,
     'TR-IMPACT-QUERY', 'test_base_flag_honest_rejection'),
    ('tests/unit/test_l0.py', 31,
     'CON-TYPED-REJECTIONS', 'test_l0_failure_is_typed'),
    ('tests/unit/test_l1.py', 38,
     'GATE-EVIDENCE-KIND', 'test_l1_green_passes_on_passing_suite'),
    ('tests/unit/test_l2.py', 42,
     'GATE-JUDGE-QUARANTINE', 'test_l2_fast_green_on_mini_repo'),
    ('tests/unit/test_l2.py', 106,
     'GATE-MODEL-INDEPENDENCE', 'test_gate_log_labels_model_dependence'),
    ('tests/unit/test_l3.py', 84,
     'GATE-MODEL-INDEPENDENCE', 'test_model_dependence_labeled_from_producer_and_gate_models'),
    ('tests/unit/test_lineage_extract.py', 49,
     'TR-DETERMINISTIC-EXTRACTION', 'test_extraction_is_deterministic'),
    ('tests/unit/test_lint_store.py', 23,
     'GATE-L0-HASH-VERIFY', 'test_torn_trailing_hash_line_detected'),
    ('tests/unit/test_lint_store.py', 39,
     'GATE-DUPLICATE-CLAUSES', 'test_duplicate_clause_detection'),
    ('tests/unit/test_mutmut_runner.py', 119,
     'GATE-MUTATION-ATTRIBUTION', 'test_campaign_kills_and_classifies'),
    ('tests/unit/test_negotiate_flow.py', 20,
     'CON-COUNTER-RECORDED', 'test_negotiate_flow_runs_on_own_contract'),
    ('tests/unit/test_negotiate_transport.py', 89,
     'PRT-A2A-TRANSPORT', 'test_full_protocol_over_wire_with_official_sdk_client'),
    ('tests/unit/test_negotiation.py', 47,
     'PRT-TYPED-REFUSAL', 'test_pre_commitment_refusal'),
    ('tests/unit/test_negotiation.py', 56,
     'CON-VALIDATED-OR-NO-START', 'test_illegal_transitions_blocked'),
    ('tests/unit/test_predicate.py', 204,
     'DSL-COMPILE-GENERATORS', 'test_golden_all_26_compile'),
    ('tests/unit/test_predicate.py', 205,
     'DSL-TRIGGER-PREDICATE-ENFORCEMENT', 'test_golden_all_26_compile'),
    ('tests/unit/test_schema_identity.py', 33,
     'ID-UUIDV7-ALIAS', 'test_new_uuid7_is_v7_canonical'),
    ('tests/unit/test_strategies_oracle.py', 191,
     'DSL-JUDGE-ESCAPE-HATCH', 'test_judge_clause_has_no_compile_requirement'),
    ('tests/unit/test_symbols.py', 29,
     'TR-IMPACT-QUERY', 'test_symbol_anchor_tracks_rename'),
    ('tests/unit/test_symbols.py', 39,
     'TR-UNRESOLVED-BINDINGS-FAIL', 'test_unresolvable_alias_reported'),
    ('tests/unit/test_symbols.py', 52,
     'TR-REVERSE-COVERAGE', 'test_reverse_coverage_flags_unbound_elements'),
    ('tests/unit/test_taskgate.py', 19,
     'ENF-WRITER-REQUIRES-CONTRACT', 'test_writer_without_contract_blocks'),
    ('tests/unit/test_taskgate.py', 29,
     'ENF-WRITER-REQUIRES-CONTRACT', 'test_writer_with_contract_allowed'),
    ('tests/unit/test_taskgate.py', 39,
     'ENF-READONLY-EXEMPT', 'test_readonly_lane_exempt'),
    ('tests/unit/test_taskgate.py', 48,
     'ENF-CONTRACT-VERDICT', 'test_after_verdict_covered_then_missing'),
    ('tests/unit/test_taskgate.py', 84,
     'ENF-AUDIT-LOGGED', 'test_override_decision_audited_ungated'),
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
    bindings = extract_bindings(REPO)
    md = [b for b in bindings if b["file"].endswith(".md")]
    assert not md, f"unexpected Markdown-sourced bindings: {md!r}"
    got = {(b["file"], b["line"], b["alias"], b["symbol"]) for b in bindings}
    assert got == BASELINE_PY_BINDINGS, "Python bindings must be unchanged"
