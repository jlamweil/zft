"""C-32: a2a adapter — V7 semantics on the real protobuf SDK + negative tests."""
import pytest

from zft.negotiate.a2a_adapter import A2aAdapter, AdapterError

pytest.importorskip("a2a")

from a2a.types import Role, TaskState, TaskStatus  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402

from zft.negotiate.sm import NegotiationSM  # noqa: E402


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




# --- kill-shard pins (2026-09-15 sitting): envelope bytes are contract --------

def test_new_task_envelope_is_exact():
    """The freshly opened task carries the negotiated id, the derived context,
    and the DRAFT mapping (TASK_STATE_SUBMITTED) — every field byte-exact."""
    task = A2aAdapter().new_task("neg-100")
    assert task.id == "neg-100"
    assert task.context_id == "neg-100-ctx"
    assert task.status.state == TaskState.TASK_STATE_SUBMITTED


def test_push_message_pins_role_and_text_part():
    """role routing is tri-modal: the 'producer' default is AGENT, 'consumer'
    is USER, and an explicit 'producer' stays AGENT — plus the message lands
    with exactly one text part carrying the payload verbatim."""
    adapter = A2aAdapter()
    task = adapter.new_task("neg-101")
    adapter.push_message(task, "cfp: hello")
    assert task.history[0].role == Role.ROLE_AGENT
    assert len(task.history[0].parts) == 1
    assert task.history[0].parts[0].text == "cfp: hello"
    adapter.push_message(task, "from user", role="consumer")
    assert task.history[1].role == Role.ROLE_USER
    adapter.push_message(task, "from producer", role="producer")
    assert task.history[2].role == Role.ROLE_AGENT


def test_push_payload_pins_role_and_structured_part():
    """Payload transport: default role is USER, JSON lands as one DataPart
    (protobuf Value struct), and malformed JSON stays a typed error."""
    adapter = A2aAdapter()
    task = adapter.new_task("neg-102")
    adapter.push_payload(task, '{"a": 1}')
    msg = task.history[0]
    assert msg.role == Role.ROLE_USER
    assert len(msg.parts) == 1
    assert msg.parts[0].data.struct_value["a"] == 1
    adapter.push_payload(task, '{"b": 2}', role="producer")
    assert task.history[1].role == Role.ROLE_AGENT
    with pytest.raises(AdapterError, match="malformed payload"):
        adapter.push_payload(task, "not-json{")


def test_attach_artifact_pins_id_name_and_data():
    """The artifact id is the task-scoped '<task.id>-<name>' key — contract
    surface for cross-references — and the data rides a structured part."""
    adapter = A2aAdapter()
    task = adapter.new_task("neg-103")
    adapter.attach_artifact(task, "zft-contract", {"clauses": 26})
    art = task.artifacts[0]
    assert art.artifact_id == "neg-103-zft-contract"
    assert art.name == "zft-contract"
    assert art.parts[0].data.struct_value["clauses"] == 26


def test_apply_state_unknown_state_is_typed():
    """An unmapped workflow state is a typed refusal naming the input, never a
    KeyError or a silent no-op."""
    task = A2aAdapter().new_task("neg-104")
    with pytest.raises(AdapterError) as ei:
        A2aAdapter().apply_state(task, "BOGUS")
    assert str(ei.value) == "unknown workflow state 'BOGUS'"


def test_to_workflow_state_unmapped_is_typed():
    """A2A states with no workflow reading (FAILED et al.) refuse typed — the
    lossy reverse map must not guess."""
    status = TaskStatus(state=TaskState.TASK_STATE_FAILED)
    with pytest.raises(AdapterError) as ei:
        A2aAdapter().to_workflow_state(status)
    assert str(ei.value) == f"unmapped task state {status.state!r}"

# --- envelope contract pins (kill shard: a2a_adapter cut) --------------------

def test_new_task_wires_id_context_and_submitted_state():
    task = A2aAdapter().new_task("neg-100")
    assert task.id == "neg-100"
    assert task.context_id == "neg-100-ctx", "context_id is task_id + '-ctx'"
    assert task.status.state == TaskState.TASK_STATE_SUBMITTED, \
        "a new task opens in the DRAFT-side a2a state"


def test_push_message_role_and_text_land_in_history():
    adapter = A2aAdapter()
    task = adapter.new_task("neg-101")
    adapter.push_message(task, "raise examples", role="producer")
    adapter.push_message(task, "cfp: contract v0", role="consumer")
    producer_msg, consumer_msg = task.history
    assert producer_msg.role == Role.ROLE_AGENT and producer_msg.parts[0].text == \
        "raise examples"
    assert consumer_msg.role == Role.ROLE_USER and consumer_msg.parts[0].text == \
        "cfp: contract v0"
    assert len(consumer_msg.parts) == 1


def test_push_message_default_role_is_producer():
    task = A2aAdapter().new_task("neg-102")
    A2aAdapter().push_message(task, "counter: x")
    assert task.history[0].role == Role.ROLE_AGENT, \
        "push_message defaults to the producer role"
    assert task.history[0].parts[0].text == "counter: x"


def test_push_payload_parses_json_into_data_part():
    adapter = A2aAdapter()
    task = adapter.new_task("neg-103")
    adapter.push_payload(task, '{"clauses": 26, "ok": true}')
    msg = task.history[0]
    assert msg.role == Role.ROLE_USER, "payload default role is consumer"
    assert len(msg.parts) == 1
    data = msg.parts[0].data
    assert data.struct_value.fields["clauses"].number_value == 26
    assert data.struct_value.fields["ok"].bool_value is True
    from_producer = adapter.new_task("neg-104")
    adapter.push_payload(from_producer, '{"a": 1}', role="producer")
    assert from_producer.history[0].role == Role.ROLE_AGENT


def test_push_payload_error_prefix_is_exact():
    task = A2aAdapter().new_task("neg-105")
    with pytest.raises(AdapterError) as excinfo:
        A2aAdapter().push_payload(task, "not-json{")
    assert str(excinfo.value).startswith("malformed payload: ")


def test_attach_artifact_composite_id_name_and_data():
    adapter = A2aAdapter()
    task = adapter.new_task("neg-106")
    adapter.attach_artifact(task, "zft-sheet", {"terms": "examples=50"})
    artifact = task.artifacts[0]
    assert artifact.artifact_id == "neg-106-zft-sheet", \
        "artifact_id is task-id + '-' + name"
    assert artifact.name == "zft-sheet"
    assert artifact.parts[0].data.struct_value.fields["terms"].string_value == \
        "examples=50"


def test_apply_state_unknown_message_is_exact():
    task = A2aAdapter().new_task("neg-107")
    with pytest.raises(AdapterError) as excinfo:
        A2aAdapter().apply_state(task, "BOGUS")
    assert str(excinfo.value) == "unknown workflow state 'BOGUS'"


def test_to_workflow_state_unmapped_message_is_exact():
    status = TaskStatus(state=TaskState.TASK_STATE_FAILED)  # no workflow state maps here
    with pytest.raises(AdapterError) as excinfo:
        A2aAdapter().to_workflow_state(status)
    assert str(excinfo.value) == "unmapped task state 4"


# --- kill-shard pins (2026-09-15 night, killproof-a2a) ------------------------
#
# Pins for the 42 killable suspects off the scoped killproof-a2a baseline
# (65 mutants: 21 killed by the three tests above, 44 survived). The two
# push_payload default-literal mutants are reviewed equivalents — the default
# only feeds the `role == "producer"` test, so every non-"producer" spelling
# maps to ROLE_USER identically — waived on the sheet, not killed.

def test_new_task_pins_the_envelope_shape(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-010")
    assert task.id == "neg-010"
    assert task.context_id == "neg-010-ctx"
    assert adapter.a2a_name(task.status) == "TASK_STATE_SUBMITTED"


def test_push_message_roles_and_text_roundtrip(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-011")
    adapter.push_message(task, "cfp: contract v0")
    producer_msg = task.history[-1]
    assert producer_msg.role == Role.ROLE_AGENT
    assert producer_msg.parts[0].text == "cfp: contract v0"
    adapter.push_message(task, "counter: raise examples", role="consumer")
    consumer_msg = task.history[-1]
    assert consumer_msg.role == Role.ROLE_USER
    assert consumer_msg.parts[0].text == "counter: raise examples"
    assert len(task.history) == 2


def test_push_payload_data_roundtrip_and_roles(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-012")
    adapter.push_payload(task, '{"zft": "contract v0"}')
    consumer_msg = task.history[-1]
    assert consumer_msg.role == Role.ROLE_USER
    assert MessageToDict(consumer_msg.parts[0].data) == {"zft": "contract v0"}
    adapter.push_payload(task, '{"sig": "jlam"}', role="producer")
    producer_msg = task.history[-1]
    assert producer_msg.role == Role.ROLE_AGENT
    assert MessageToDict(producer_msg.parts[0].data) == {"sig": "jlam"}
    assert len(task.history) == 2




def test_apply_state_refuses_unknown_workflow_state_by_name(tmp_path):
    adapter = A2aAdapter()
    task = adapter.new_task("neg-014")
    with pytest.raises(AdapterError, match="unknown workflow state 'NOT-A-STATE'"):
        adapter.apply_state(task, "NOT-A-STATE")


def test_to_workflow_state_refuses_unmapped_a2a_state_by_name(tmp_path):
    adapter = A2aAdapter()
    status = TaskStatus(state=TaskState.TASK_STATE_FAILED)
    # the refusal renders the raw proto enum number (status.state!r), hence '4'
    with pytest.raises(AdapterError, match="unmapped task state 4"):
        adapter.to_workflow_state(status)

