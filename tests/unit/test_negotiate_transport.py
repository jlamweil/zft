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

import builtins
import signal
import socket

from a2a.client.transports.jsonrpc import JsonRpcTransport  # noqa: E402
from a2a.types import (  # noqa: E402  # noqa: E402
    AgentCard,
    GetTaskRequest,
    Message,
    Role,
    SendMessageRequest,
    TaskState,
)
from a2a.utils.errors import (  # noqa: E402
    InvalidParamsError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from zft.debug.ledger import RunLedger  # noqa: E402
from zft.negotiate import transport as transport_module
from zft.negotiate.a2a_adapter import AdapterError
from zft.negotiate.resume import CANNED_COUNTER_TERMS
from zft.negotiate.sm import (  # noqa: E402
    DEFAULT_RETRY_BUDGET,
    IllegalTransition,
    NegotiationSM,
)
from zft.negotiate.terms import terms_digest, terms_string  # noqa: E402
from zft.negotiate.transport import (  # noqa: E402
    A2aNegotiationServer,  # noqa: E402
    _fault_for,
    _RpcFault,
)
from zft.spec.store import load_contract  # noqa: E402

REPO = Path(os.environ.get("ZFT_REPO")
            or Path(__file__).resolve().parents[2])
TASK = "neg-001"


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(
        REPO / ".zft", root / ".zft",
        ignore=shutil.ignore_patterns("runs", "sandbox*", "cache"),
    )
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
    runs = sorted((root / ".zft" / "runs").iterdir())
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
    assert [a.name for a in task.artifacts] == ["zft-contract"], \
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
    runs = sorted((root / ".zft" / "runs").iterdir())
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
    env = os.environ | {"ZFT_NEGOTIATE_KILL_AFTER": "counter"}
    killed = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "negotiate", str(root),
         "--counter-terms", str(sheet)],
        capture_output=True, text=True, env=env)
    assert killed.returncode == -9, "the CLI dies at the counter seam"
    runs = sorted((root / ".zft" / "runs").iterdir())
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


_KNOWN_ACTIONS_SORTED = ("['accept_counter', 'cfp', 'counter', 'implement', "
                         "'refuse', 'reject_gate', 'reopen', 'validate']")
def _direct_msg(action, **extra):
    metadata = {"action": action, **extra}
    return {"message": {"messageId": f"m-{action}-{sorted(extra.items())}",
                        "role": "ROLE_USER", "taskId": TASK, "metadata": metadata}}
def _raw_socket(port: int, payload: bytes) -> tuple[list[str], bytes]:
    """One raw HTTP/1.0 round trip; returns (head_lines, body)."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            part = s.recv(65536)
            if not part:
                break
            chunks.append(part)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return head.decode("latin-1").split("\r\n"), body
def test_unstarted_server_invariants(tmp_path):
    server = A2aNegotiationServer(tmp_path)
    assert server.task_id == "neg-001"
    assert server.resumed is False
    assert server._http is None
    assert server._thread is None
    assert server._task is None
    with pytest.raises(RuntimeError, match=r"^server not started$"):
        server.port
    with pytest.raises(RuntimeError,
                       match=r"^no negotiation run yet \(no wire turn taken\)$"):
        server.run_id
    server.wait()  # no thread: a no-op, not a crash
def test_thread_identity_and_stop_lifecycle(tmp_path):
    server = A2aNegotiationServer(_store(tmp_path), task_id=TASK)
    server.start()
    assert server._thread.name == "zft-a2a-transport"
    assert server._thread.daemon is True
    assert server.port > 0
    server.stop()
    assert server._http is None
    assert server._thread is None
    with pytest.raises(RuntimeError, match=r"^server not started$"):
        server.port
    server.stop()  # idempotent
def test_wait_joins_the_server_thread(tmp_path):
    class _Stub:
        joined = False

        def join(self, timeout=None):
            self.joined = True

    server = A2aNegotiationServer(_store(tmp_path), task_id=TASK)
    stub = _Stub()
    server._thread = stub
    server.wait()
    assert stub.joined
def test_rpc_send_fault_ladder_is_byte_exact(tmp_path):
    root, server = _started(tmp_path)
    faults = [
        (("not a dict",), (-32600, "params.message (object) is required")),
        (({},), (-32600, "params.message (object) is required")),
        (({"message": "no"},), (-32600, "params.message (object) is required")),
        (({"message": {"messageId": "m", "taskId": TASK}},),
         (-32602, "message.metadata (object) is required")),
        (({"message": {"messageId": "m", "taskId": TASK, "metadata": "x"}},),
         (-32602, "message.metadata (object) is required")),
        (({"message": {"messageId": "m", "taskId": TASK, "metadata": {}}},),
         (-32602, "message.metadata.action is required")),
        ((_direct_msg("explode"),),
         (-32602, f"unknown action 'explode' (known: {_KNOWN_ACTIONS_SORTED})")),
        (({"message": {"messageId": ["x"], "taskId": TASK,
                       "metadata": {"action": "cfp"}}},),
         (-32602, "malformed message: Failed to parse messageId field: "
                  "expected string or bytes-like object, got 'list'.")),
    ]
    for argv, (code, message) in faults:
        with pytest.raises(_RpcFault) as ei:
            server.rpc_send(*argv)
        assert (ei.value.code, ei.value.message) == (code, message)
        # str(_RpcFault) is its message: it rides the wire as the error text
        assert str(ei.value) == message
    runs = root / ".zft" / "runs"
    assert not runs.exists() or not any(runs.iterdir()), \
        "a refused turn creates no run"
    server.stop()
def test_rpc_get_task_fault_ladder_is_byte_exact(tmp_path):
    root, server = _started(tmp_path)
    with pytest.raises(_RpcFault) as ei:
        server.rpc_get_task("nope")
    assert (ei.value.code, ei.value.message) == (-32600, "params (object) is required")
    server.stop()
    # the no-negotiation fault needs a server that never started: start()
    # creates the task slot, so only an unstarted object has _task None
    fresh = A2aNegotiationServer(root, task_id=TASK)
    with pytest.raises(_RpcFault) as ei:
        fresh.rpc_get_task({"id": "neg-001"})
    assert (ei.value.code, ei.value.message) == (
        -32001, "no negotiation yet on task 'neg-001'")
def test_first_turn_pins_ack_manifest_and_cfp_event(tmp_path):
    root, server = _started(tmp_path)
    server.rpc_send(_direct_msg("cfp"))
    ack = server._task.history[1]
    assert ack.role == Role.ROLE_AGENT
    assert ack.task_id == TASK
    assert len(ack.parts) == 1
    assert ack.parts[0].text == "ack: state=COUNTERED"

    runs = sorted((root / ".zft" / "runs").iterdir())
    assert len(runs) == 1
    manifest = json.loads((runs[0] / "manifest.json").read_text())
    assert manifest["run_id"] == runs[0].name
    assert manifest["stage"] == "negotiate"
    assert manifest["retry_budget"] == DEFAULT_RETRY_BUDGET
    assert manifest["transport"] == "a2a"
    assert manifest["task_id"] == TASK
    assert "git_commit" in manifest and "dirty" in manifest, \
        "the wire run carries the same provenance the CLI writes"

    led = RunLedger.load(runs[0].parent, runs[0].name)
    contract = load_contract(root)
    assert led.events[0] == {"event": "cfp", "contract": contract["name"],
                             "clauses": len(contract["clause_ids"])}
    server.stop()
def test_second_cfp_refusal_names_the_state(tmp_path):
    _, server = _started(tmp_path)
    server.rpc_send(_direct_msg("cfp"))
    with pytest.raises(_RpcFault) as ei:
        server.rpc_send(_direct_msg("cfp"))
    assert (ei.value.code, ei.value.message) == (
        -32004, "cfp not allowed from COUNTERED")
    server.stop()
def test_canned_run_ledger_event_dicts_are_exact(tmp_path):
    root, server = _started(tmp_path)
    _send(server.port, action="cfp")
    _send(server.port, action="accept_counter")
    _send(server.port, action="validate")
    events = _run_events(root)
    contract = load_contract(root)
    assert events[0] == {"event": "cfp", "contract": contract["name"],
                         "clauses": len(contract["clause_ids"])}
    # the turn events mirror the state machine's own history record —
    # indexing the wrong element lands a foreign dict here
    sm = NegotiationSM.start()
    sm.counter(terms_string(CANNED_COUNTER_TERMS))
    assert events[1] == {"event": "counter", **sm.history[-1]}
    sm.accept_counter()
    assert events[2] == {"event": "accept_counter", **sm.history[-1]}
    sm.validate()
    assert events[3] == {"event": "validate", **sm.history[-1]}
    # a canned outcome binds no sheet: exactly the two protocol keys
    assert events[-1] == {"event": "validated",
                          "version": contract["version"] + 1}
    server.stop()
def test_external_sheet_refusal_messages_byte_exact(tmp_path):
    _, server = _started(tmp_path)
    _send(server.port, action="cfp", terms="wire terms 9")
    with pytest.raises(UnsupportedOperationError, match=(
            r"^this run countered with an external term sheet; "
            r"accept_counter must echo it as metadata terms "
            r"\(the recorded counter-proposal\)$")):
        _send(server.port, action="accept_counter")
    with pytest.raises(UnsupportedOperationError, match=(
            r"^accept_counter terms do not match the recorded "
            r"counter-proposal 'wire terms 9'$")):
        _send(server.port, action="accept_counter", terms="other")
    server.stop()
def test_fault_translation_ladder_is_byte_exact():
    f = _fault_for(IllegalTransition("boom-a"))
    assert (f.code, f.message) == (-32004, "boom-a")
    assert str(f) == "boom-a"
    f = _fault_for(AdapterError("boom-b"))
    assert (f.code, f.message) == (-32602, "boom-b")
    f = _fault_for(ValueError("boom-c"))
    assert (f.code, f.message) == (-32603, "ValueError: boom-c")
def test_wire_parse_error_is_typed_and_exact(tmp_path):
    _, server = _started(tmp_path)
    # no Content-Length header: the read-default's only reachable branch
    # (httpx always sends the header), and a body — read(0) vs read(1)
    # then fail parse DIFFERENTLY, which is the observable
    req = (b"POST / HTTP/1.0\r\nHost: x\r\n\r\n"
           b'{"jsonrpc": "2.0", "id": 7, "method": "SendMessage"}')
    head, body = _raw_socket(server.port, req)
    assert head[0] == "HTTP/1.0 200 OK"
    assert "Content-Type: application/json" in head
    assert f"Content-Length: {len(body)}" in head
    assert json.loads(body) == {
        "jsonrpc": "2.0", "id": None,
        "error": {"code": -32700,
                  "message": "parse error: "
                             "Expecting value: line 1 column 1 (char 0)"}}
    server.stop()
def test_wire_error_replies_echo_id_and_are_exact(tmp_path):
    _, server = _started(tmp_path)
    assert _raw(server.port, {"id": "abc-42", "method": "SendMessage"}) == {
        "jsonrpc": "2.0", "id": "abc-42",
        "error": {"code": -32600,
                  "message": "jsonrpc 2.0 request with a method is required"}}
    assert _raw(server.port, {"jsonrpc": "2.0", "id": 2, "method": "Bogus"}) == {
        "jsonrpc": "2.0", "id": 2,
        "error": {"code": -32601, "message": "unknown method 'Bogus'"}}
    assert _raw(server.port, {"jsonrpc": "2.0", "id": 3,
                              "method": "SendMessage", "params": {}}) == {
        "jsonrpc": "2.0", "id": 3,
        "error": {"code": -32600, "message": "params.message (object) is required"}}
    server.stop()
def test_untyped_faults_become_internal_errors(tmp_path):
    store = tmp_path / "empty-store"
    store.mkdir()
    server = A2aNegotiationServer(store, task_id=TASK)
    server.start()
    resp = _raw(server.port, {"jsonrpc": "2.0", "id": 9, "method": "SendMessage",
                              "params": {"message": {"messageId": "m",
                                                     "role": "ROLE_USER",
                                                     "taskId": TASK,
                                                     "metadata": {"action": "cfp"}}}})
    assert resp["error"]["code"] == -32603
    assert resp["error"]["message"] == ("FileNotFoundError: "
                                        "no contract manifest under .zft/contracts")
    assert resp["id"] == 9
    server.stop()
def test_result_reply_headers_are_exact(tmp_path):
    _, server = _started(tmp_path)
    body = json.dumps({"jsonrpc": "2.0", "id": "rid-1", "method": "SendMessage",
                       "params": {"message": {"messageId": "m",
                                              "role": "ROLE_USER",
                                              "taskId": TASK,
                                              "metadata": {"action": "cfp"}}}}).encode()
    head, resp_body = _raw_socket(
        server.port,
        b"POST / HTTP/1.0\r\nHost: x\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    assert head[0] == "HTTP/1.0 200 OK"
    assert "Content-Type: application/json" in head
    assert f"Content-Length: {len(resp_body)}" in head
    parsed = json.loads(resp_body)
    assert parsed["id"] == "rid-1"
    assert "error" not in parsed
    assert parsed["result"]["task"]["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    server.stop()
def test_main_help_is_pinned(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        transport_module.main(["--help"])
    out = capsys.readouterr().out
    assert "usage: python -m zft.negotiate.transport" in out
    assert ("serve one negotiation task on the A2A SendMessage JSON-RPC "
            "binding") in out
    assert "contract store root" in out
    assert "0 = ephemeral" in out
    assert "XX" not in out, "no mutant placeholder may reach the help text"
def _run_main_wired(monkeypatch, root):
    """Run main() in-process with signals, wait, and print instrumented."""
    calls, holder, printed = {}, {}, {}
    monkeypatch.setattr(transport_module.signal, "signal",
                        lambda sig, handler: calls.setdefault(sig, handler))
    monkeypatch.setattr(transport_module.A2aNegotiationServer, "wait",
                        lambda self: holder.setdefault("server", self))
    monkeypatch.setattr(builtins, "print",
                        lambda *a, **k: printed.update(text=" ".join(map(str, a)),
                                                       **k))
    rc = transport_module.main(["--root", str(root)])
    return rc, calls, holder, printed
def test_main_defaults_pin_full_wiring(monkeypatch, tmp_path):
    root = _store(tmp_path)
    rc, calls, holder, printed = _run_main_wired(monkeypatch, root)
    assert rc == 0
    server = holder["server"]
    assert server.task_id == "neg-001"
    assert server._host == "127.0.0.1"
    assert server._requested_port == 0
    assert server._root == Path(root)
    assert not server.resumed
    assert printed["text"] == (f"zft-a2a-transport port={server.port} "
                               f"task=neg-001 resumed=False")
    assert printed.get("flush") is True, "the banner is a machine-readiness signal"
    assert set(calls) == {signal.SIGTERM, signal.SIGINT}
    server.stop()
def test_main_sigterm_handler_stops_the_server(monkeypatch, tmp_path):
    root = _store(tmp_path)
    _, calls, holder, _ = _run_main_wired(monkeypatch, root)
    calls[signal.SIGTERM](signal.SIGTERM, None)
    with pytest.raises(RuntimeError, match=r"^server not started$"):
        holder["server"].port
def test_main_sigint_handler_stops_the_server(monkeypatch, tmp_path):
    root = _store(tmp_path)
    _, calls, holder, _ = _run_main_wired(monkeypatch, root)
    calls[signal.SIGINT](signal.SIGINT, None)
    with pytest.raises(RuntimeError, match=r"^server not started$"):
        holder["server"].port
def test_main_default_root_is_the_cwd_store(monkeypatch, tmp_path):
    holder = {}
    resume_paths = []
    monkeypatch.setattr(transport_module, "resume",
                        lambda p: resume_paths.append(p) and None)
    monkeypatch.setattr(transport_module.A2aNegotiationServer, "wait",
                        lambda self: holder.setdefault("server", self))
    monkeypatch.setattr(builtins, "print", lambda *a, **k: None)
    assert transport_module.main([]) == 0
    server = holder["server"]
    assert server._root == Path(".")
    assert resume_paths == [Path(".zft/runs")], \
        "the default root is the CWD store, and only its runs were probed"
    server.stop()
def test_main_explicit_flags_reach_the_server(monkeypatch, tmp_path):
    root = _store(tmp_path)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port_no = probe.getsockname()[1]
    probe.close()
    holder = {}
    monkeypatch.setattr(transport_module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(transport_module.A2aNegotiationServer, "wait",
                        lambda self: holder.setdefault("server", self))
    assert transport_module.main(["--root", str(root), "--host", "localhost",
                                  "--port", str(port_no),
                                  "--task-id", "neg-custom"]) == 0
    server = holder["server"]
    assert server.task_id == "neg-custom"
    assert server._host == "localhost"
    assert server._requested_port == port_no
    assert server.port == port_no
    assert server._root == Path(root)
    server.stop()
