"""C-32: a2a adapter — V7 semantics on the real protobuf SDK + negative tests."""
import pytest

from traceagent.negotiate.a2a_adapter import A2aAdapter, AdapterError

pytest.importorskip("a2a")

from traceagent.negotiate.sm import NegotiationSM  # noqa: E402


# @trace("PRT-A2A-ENVELOPE")
def test_wire_roundtrip_with_history_and_artifacts(tmp_path):
    sm = NegotiationSM.start()
    sm.counter("producer counter-terms")
    sm.accept_counter()
    sm.validate()
    adapter = A2aAdapter()
    task = adapter.new_task("neg-001")
    adapter.push_message(task, "cfp: contract v0", role="consumer")
    adapter.push_message(task, "counter: raise examples", role="producer")
    adapter.attach_artifact(task, "zft-contract", {"clauses": 26})
    adapter.apply_state(task, sm.state)
    blob = adapter.serialize(task)

    reloaded = adapter.deserialize(blob)
    assert len(reloaded.history) == 2
    assert adapter.to_workflow_state(reloaded.status) == "VALIDATED"
    assert reloaded.artifacts[0].name == "zft-contract"


def test_malformed_payload_raises_typed_error(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-002")
    with pytest.raises(AdapterError, match="malformed"):
        adapter.push_payload(task, "not-json{")


def test_gate_rejection_maps_to_input_required(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-003")
    sm = NegotiationSM.start()
    sm.validate()
    sm.implement()
    adapter.apply_state(task, sm.state)
    assert adapter.a2a_name(task.status) == "TASK_STATE_COMPLETED"
    sm.reject_gate(["GATE-INV-01"], fault="contract")
    adapter.apply_state(task, sm.state)
    assert adapter.a2a_name(task.status) == "TASK_STATE_INPUT_REQUIRED"
