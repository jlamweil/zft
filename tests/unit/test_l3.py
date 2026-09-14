"""C-27: L3 attestation projection — gate log over run-ledger events.

build_gate_log is a pure projection: it must tolerate events from any
producer (missing keys, non-dicts), keep only `l*` stage verdicts, and
label model dependence for the attestation (GATE-MODEL-INDEPENDENCE).
"""
import json

from zft.debug.ledger import RunLedger
from zft.gates.l3 import build_gate_log


def _log(events, producer="producer-dev", gate="gate-dev",
         judge_excluded=None, coverage="1/2"):
    return build_gate_log(events, producer_model=producer, gate_model=gate,
                          judge_excluded=judge_excluded or [],
                          deterministic_coverage=coverage)


def test_stage_verdicts_extracted_from_l_prefixed_events():
    events = [
        {"event": "l0", "ok": True},
        {"event": "l1_clause", "alias": "GATE-INV-01", "ok": True},
        {"event": "l2_fast", "ok": False},
    ]
    assert _log(events)["stages"] == {"l0": True, "l1_clause": True,
                                      "l2_fast": False}


def test_non_stage_events_are_excluded():
    events = [
        {"event": "mutant_verdict", "name": "m1", "ok": True},
        {"event": "campaign_summary", "ok": True},
        {"event": "run_start"},
        {"event": "cfp", "ok": True},
    ]
    assert _log(events)["stages"] == {}


def test_uppercase_stage_names_are_not_stage_events():
    # the projection matches the lowercase `l` prefix, not a case-insensitive one
    assert _log([{"event": "L0", "ok": True}])["stages"] == {}


def test_extra_event_fields_do_not_leak_into_stages():
    events = [{"event": "l2_fast", "ok": True, "alias": "A", "duration_ms": 12}]
    assert _log(events)["stages"] == {"l2_fast": True}


def test_duplicate_stage_events_last_write_wins():
    events = [
        {"event": "l1_clause", "ok": True},
        {"event": "l1_clause", "ok": False},
    ]
    assert _log(events)["stages"] == {"l1_clause": False}


def test_malformed_events_are_skipped_never_fatal():
    events = [
        None,
        "junk",
        42,
        {"event": 7, "ok": True},          # non-string event name
        {"event": "run_start"},            # stage-shaped but no `ok`
        {"ok": True},                      # no event name at all
        {"event": "l0", "ok": True},       # the one that counts
    ]
    assert _log(events)["stages"] == {"l0": True}


def test_empty_event_list_gives_empty_stages():
    assert _log([])["stages"] == {}


def test_judge_excluded_passed_through_in_order():
    excluded = ["GATE-STYLE-01", "GATE-AESTHETIC-02"]
    assert _log([], judge_excluded=excluded)["judge_excluded"] == excluded


def test_deterministic_coverage_passed_through_verbatim():
    assert _log([], coverage="23/24")["deterministic_coverage"] == "23/24"


# @trace("GATE-MODEL-INDEPENDENCE")
def test_model_dependence_labeled_from_producer_and_gate_models():
    log = _log([], producer="producer-dev", gate="gate-dev")
    assert log["models"] == {"producer": "producer-dev", "gate": "gate-dev"}
    assert log["model_dependent"] is False
    same = _log([], producer="m", gate="m")
    assert same["model_dependent"] is True


def test_unspecified_models_on_both_sides_count_as_dependent():
    # None == None — the log must not silently claim independence it cannot know
    log = _log([], producer=None, gate=None)
    assert log["models"] == {"producer": None, "gate": None}
    assert log["model_dependent"] is True


def test_unspecified_producer_alone_is_independent_of_named_gate():
    assert _log([], producer=None, gate="gate-dev")["model_dependent"] is False


def test_gate_log_is_json_serializable_for_the_check_report():
    events = [{"event": "l0", "ok": True}, {"event": "l2_fast", "ok": True}]
    dumped = json.dumps(_log(events, judge_excluded=["GATE-STYLE-01"]))
    assert json.loads(dumped)["stages"] == {"l0": True, "l2_fast": True}


def test_projection_over_a_real_ledger_run(tmp_path):
    root = tmp_path
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2-fast"},
                          repo=root)
    led.append({"event": "run_start", "tier": "fast"})
    led.append({"event": "l0", "ok": True})
    led.append({"event": "l1_clause", "alias": "GATE-INV-01", "ok": True})
    led.append({"event": "mutant_verdict", "name": "m1", "ok": True})
    events = RunLedger.load(tmp_path / "runs", led.run_id).events
    led.close()

    log = _log(events)
    assert log["stages"] == {"l0": True, "l1_clause": True}
    assert "mutant_verdict" not in log["stages"]


def test_projection_keys_are_stable():
    assert set(_log([])) == {"stages", "judge_excluded", "deterministic_coverage",
                             "models", "model_dependent"}
