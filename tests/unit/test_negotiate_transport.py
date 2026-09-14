"""A2A transport — the negotiation on the real SendMessage wire.

The client in these tests is a2a-sdk's own JsonRpcTransport: the server
speaks the protobuf-JSON shapes that SDK produces and parses, so the
interop claim is exercised literally rather than against a hand-rolled
twin. Runs against a copy of the repo's .zft tree, never the repo.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from google.protobuf.json_format import ParseDict

pytest.importorskip("a2a")

from a2a.client.transports.jsonrpc import JsonRpcTransport  # noqa: E402
from a2a.types import (  # noqa: E402
    AgentCard,
    GetTaskRequest,
    Message,
    SendMessageRequest,
    TaskState,
)
from a2a.utils.errors import (  # noqa: E402
    InvalidParamsError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from traceagent.debug.ledger import RunLedger  # noqa: E402
from traceagent.negotiate.terms import terms_digest, terms_string  # noqa: E402
from traceagent.negotiate.transport import A2aNegotiationServer  # noqa: E402
from traceagent.spec.store import load_contract  # noqa: E402

REPO = Path(os.environ.get("TRACEAGENT_REPO")
            or Path(__file__).resolve().parents[2])
TASK = "neg-001"


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(REPO / ".zft", root / ".zft")
    return root


def _started(tmp_path: Path) -> tuple[Path, A2aNegotiationServer]:
    root = _store(tmp_path)
    server = A2aNegotiationServer(root, task_id=TASK)
    server.start()
    return root, server


def _send(port: int, task_id: str = TASK, **metadata):
    """One SDK-client SendMessage turn (a real JSON-RPC round trip)."""

    async def go():
        async with httpx.AsyncClient() as hc:
            transport = JsonRpcTransport(hc, AgentCard(), f"http://127.0.0.1:{port}/")
            message = ParseDict({"messageId": f"m-{sorted(metadata.items())}",
                                 "role": "ROLE_USER", "taskId": task_id,
                                 "metadata": metadata}, Message())
            return await transport.send_message(SendMessageRequest(message=message))

    return asyncio.run(go())


def _raw(port: int, payload: dict) -> dict:
    async def go():
        async with httpx.AsyncClient() as hc:
            response = await hc.post(f"http://127.0.0.1:{port}/", json=payload)
            return response.json()

    return asyncio.run(go())


def _events(root: Path) -> list[str]:
    runs = sorted((root / ".traceagent" / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {[r.name for r in runs]}"
    return [e["event"] for e in RunLedger.load(runs[0].parent, runs[0].name).events]


# @trace("PRT-A2A-TRANSPORT")
def test_full_protocol_over_wire_with_official_sdk_client(tmp_path):
    root, server = _started(tmp_path)

    task = _send(server.port, action="cfp").task
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED, \
        "the canned producer counters inside the cfp turn — consumer input required"
    assert len(task.history) == 2, "the inbound message plus the producer ack"

    task = _send(server.port, action="accept_counter").task
    assert task.status.state == TaskState.TASK_STATE_WORKING

    task = _send(server.port, action="validate").task
    assert task.status.state == TaskState.TASK_STATE_WORKING
    assert [a.name for a in task.artifacts] == ["traceagent-contract"], \
        "PRT-A2A-ENVELOPE: the contract rides as an A2A artifact"
    artifact = task.artifacts[0].parts[0].data.struct_value.fields
    contract = load_contract(root)
    assert artifact["contract"].string_value == contract["name"]
    assert artifact["clauses"].number_value == len(contract["clause_ids"])
    assert artifact["version"].number_value == contract["version"] + 1, \
        "the validated marker announces the NEXT contract version"

    task = _send(server.port, action="implement").task
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert _events(root) == ["cfp", "counter", "accept_counter", "validate",
                             "validated", "implement"]
    server.stop()


def test_illegal_transition_is_unsupported_operation(tmp_path):
    root, server = _started(tmp_path)

    with pytest.raises(UnsupportedOperationError, match="implement not allowed from DRAFT"):
        _send(server.port, action="implement")

    assert _events(root) == [], "a refused turn invents no protocol events"
    server.stop()


def test_unknown_task_is_task_not_found(tmp_path):
    _, server = _started(tmp_path)

    with pytest.raises(TaskNotFoundError, match="no such task 'other'"):
        _send(server.port, task_id="other", action="cfp")
    server.stop()


def test_unknown_action_is_invalid_params(tmp_path):
    _, server = _started(tmp_path)

    with pytest.raises(InvalidParamsError, match="unknown action 'explode'"):
        _send(server.port, action="explode")
    server.stop()


def test_action_missing_required_key_names_the_keys(tmp_path):
    _, server = _started(tmp_path)

    _send(server.port, action="cfp")
    _send(server.port, action="accept_counter")
    with pytest.raises(InvalidParamsError,
                       match=r"requires metadata key\(s\) \['clause_ids', 'fault'\]"):
        _send(server.port, action="reject_gate")
    server.stop()


def test_gate_rejection_and_bounded_reopen_over_wire(tmp_path):
    root, server = _started(tmp_path)

    for action in ("cfp", "accept_counter", "validate", "implement"):
        _send(server.port, action=action)

    def gate_cycle():
        task = _send(server.port, action="reject_gate", clause_ids=["GATE-INV-01"],
                     fault="contract").task
        assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        task = _send(server.port, action="reopen").task
        assert task.status.state == TaskState.TASK_STATE_WORKING
        _send(server.port, action="validate")
        _send(server.port, action="implement")

    for _ in range(3):  # exactly the retry budget, not one more
        gate_cycle()
    with pytest.raises(UnsupportedOperationError, match="retry budget exhausted"):
        gate_cycle()

    assert _events(root).count("reopen") == 3
    server.stop()


def test_restart_resumes_same_run_under_same_task(tmp_path):
    root, server = _started(tmp_path)

    task = _send(server.port, action="cfp").task
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    first_run = server.run_id
    server.stop()

    restarted = A2aNegotiationServer(root, task_id=TASK)
    restarted.start()
    assert restarted.resumed, "an unfinished run must resume, not restart"
    assert restarted.run_id == first_run, "same run, not a new one"

    task = _send(restarted.port, action="accept_counter").task
    assert task.status.state == TaskState.TASK_STATE_WORKING
    assert _events(root) == ["cfp", "counter", "resumed", "accept_counter"]
    restarted.stop()


def test_finished_run_is_not_resumed(tmp_path):
    root, server = _started(tmp_path)

    for action in ("cfp", "accept_counter", "validate"):
        _send(server.port, action=action)
    server.stop()

    fresh = A2aNegotiationServer(root, task_id=TASK)
    fresh.start()
    assert not fresh.resumed, "a validated negotiation is finished, not resumable"
    fresh.stop()


def _get_task(port: int, task_id: str):
    async def go():
        async with httpx.AsyncClient() as hc:
            transport = JsonRpcTransport(hc, AgentCard(), f"http://127.0.0.1:{port}/")
            return await transport.get_task(GetTaskRequest(id=task_id))

    return asyncio.run(go())


def test_get_task_serves_the_slot_and_refuses_unknown_ids(tmp_path):
    _, server = _started(tmp_path)

    _send(server.port, action="cfp")
    task = _get_task(server.port, TASK)
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED, \
        "GetTask reports the replayed/envelope state, not a fresh DRAFT"
    with pytest.raises(TaskNotFoundError, match="no such task 'zzz'"):
        _get_task(server.port, "zzz")
    server.stop()


def test_wire_rejects_non_jsonrpc_and_unknown_methods(tmp_path):
    _, server = _started(tmp_path)

    assert _raw(server.port, {"id": 1, "method": "SendMessage"})["error"]["code"] == -32600
    assert _raw(server.port, {"jsonrpc": "2.0", "id": 2,
                              "method": "Bogus"})["error"]["code"] == -32601
    server.stop()


# --- the bargain on the wire ---------------------------------------------------

def _run_events(root: Path) -> list[dict]:
    runs = sorted((root / ".traceagent" / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {[r.name for r in runs]}"
    return RunLedger.load(runs[0].parent, runs[0].name).events


def test_accepting_an_external_counter_requires_its_sheet(tmp_path):
    """The wire rule matches the CLI's driver: nobody accepts blind what they
    cannot name — accept_counter must echo the recorded counter-proposal,
    and the validated outcome binds the sheet's digest."""
    root, server = _started(tmp_path)

    _send(server.port, action="cfp", terms="wire terms 42")
    with pytest.raises(UnsupportedOperationError, match="external term sheet"):
        _send(server.port, action="accept_counter")
    with pytest.raises(UnsupportedOperationError,
                       match="do not match the recorded counter-proposal"):
        _send(server.port, action="accept_counter", terms="different terms")

    _send(server.port, action="accept_counter", terms="wire terms 42")
    _send(server.port, action="validate")
    outcome = next(e for e in _run_events(root) if e["event"] == "validated")
    assert outcome["terms_digest"] == terms_digest("wire terms 42")
    assert outcome["decision"] == "accept"
    server.stop()


def test_structured_sheet_records_canonically_and_binds_same_digest(tmp_path):
    """Structured terms land in the ledger exactly as the CLI records them,
    and the digest binds the structured value, not its wire encoding."""
    root, server = _started(tmp_path)
    sheet = {"budget": "90s", "clauses": ["GATE-L0"]}

    _send(server.port, action="cfp", terms=sheet)
    events = _run_events(root)
    assert events[1]["terms"] == terms_string(sheet)

    _send(server.port, action="accept_counter", terms=sheet)
    _send(server.port, action="validate")
    outcome = next(e for e in _run_events(root) if e["event"] == "validated")
    assert outcome["terms_digest"] == terms_digest(sheet)
    server.stop()


def test_cli_half_bargain_finishes_over_wire_with_same_digest(tmp_path):
    """A CLI run killed right after counting with an external sheet resumes
    over the wire: the wire may finish it only by presenting the same sheet,
    and binds the same digest the CLI would have — the ledger is the only
    truth, whichever path speaks."""
    root = _store(tmp_path)
    sheet = root / "counter-terms.json"
    sheet.write_text(json.dumps({"terms": "sheet terms 7", "decision": "accept"}))
    env = os.environ | {"TRACEAGENT_NEGOTIATE_KILL_AFTER": "counter"}
    killed = subprocess.run(
        [sys.executable, "-m", "traceagent.cli.main", "negotiate", str(root),
         "--counter-terms", str(sheet)],
        capture_output=True, text=True, env=env)
    assert killed.returncode == -9, "the CLI dies at the counter seam"
    runs = sorted((root / ".traceagent" / "runs").iterdir())
    assert len(runs) == 1
    cli_run_id = runs[0].name

    server = A2aNegotiationServer(root, task_id=TASK)
    server.start()
    assert server.resumed and server.run_id == cli_run_id, \
        "the wire continues the CLI's run, not a new one"

    with pytest.raises(UnsupportedOperationError, match="external term sheet"):
        _send(server.port, action="accept_counter")
    _send(server.port, action="accept_counter", terms="sheet terms 7")
    _send(server.port, action="validate")

    events = _run_events(root)
    outcome = next(e for e in events if e["event"] == "validated")
    assert outcome["terms_digest"] == terms_digest("sheet terms 7"), \
        "the wire binds the same digest the CLI's sheet parses to"
    assert outcome["decision"] == "accept"
    server.stop()
