"""A2A wire transport: the endpoint that actually sends envelopes.

FOCUS's prune verdict on the envelope adapter names its own re-entry
condition — "re-introduce when something actually sends an envelope."
This module is that condition, satisfied: a producer endpoint speaking
the A2A 1.0 SendMessage JSON-RPC binding over real HTTP, with the
negotiation riding NegotiationSM and its run ledger underneath.

The venv carries httpx but no server stack, so the HTTP layer is stdlib
http.server; the wire dialect is not homegrown — requests and responses
use exactly the protobuf-JSON shapes a2a-sdk's own JsonRpcTransport
sends and parses (SendMessage in, SendMessageResponse{task} out, A2A
error codes from a2a.utils.errors), so the official SDK client is the
interop proof and no second wire dialect exists.

Protocol roles on the wire: the consumer drives the state machine by
sending messages whose metadata carries {"action": ...}; the one
producer action the canned policy owns is `counter`, applied inside the
consumer's `cfp` turn. The bargain rules span paths: a run that countered
with an external term sheet can only be accepted by echoing that sheet
(accept_counter metadata terms), and a validated outcome binds the sheet's
digest — the same rules, and the same digest, the CLI enforces and binds.
Every applied action is appended to the run
ledger before the response is written, so a killed server leaves the
same durable protocol prefix the CLI negotiate leaves — and a restarted
server resumes the SAME run through resume() (a CLI-created run is
resumable over the wire and vice versa; the ledger is the only truth).
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from google.protobuf.json_format import MessageToDict, ParseDict

try:
    from a2a.types import Message, Part, Role, SendMessageResponse, Task
except ImportError as e:  # pragma: no cover - a2a extra not installed
    raise ImportError(
        "a2a-sdk is required for the negotiate transport (pip install traceagent[a2a])"
    ) from e

from traceagent.debug.ledger import RunLedger
from traceagent.negotiate.a2a_adapter import A2aAdapter, AdapterError
from traceagent.negotiate.resume import CANNED_COUNTER_TERMS, recorded_counter_terms, resume
from traceagent.negotiate.sm import (
    ACTIONS,
    DEFAULT_RETRY_BUDGET,
    IllegalTransition,
    NegotiationSM,
)
from traceagent.negotiate.terms import digest_from_recorded, terms_string
from traceagent.spec.store import load_contract

# A2A / JSON-RPC 2.0 error codes — a2a.utils.errors.JSON_RPC_ERROR_CODE_MAP
# maps these numbers to the SDK client's typed A2AError subclasses.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603
_TASK_NOT_FOUND = -32001
_UNSUPPORTED_OPERATION = -32004

# wire method -> handler name on this server (the SDK speaks PascalCase)
_METHODS = {"SendMessage", "GetTask"}

# action -> metadata keys consumed as its keyword arguments; everything else
# in the metadata dict rides along unread
_ACTION_PARAMS: dict[str, tuple[str, ...]] = {
    "counter": ("terms",),
    "refuse": ("reason",),
    "reject_gate": ("clause_ids", "fault"),
}
_KNOWN_ACTIONS = ACTIONS | {"cfp"}


class A2aNegotiationServer:
    """One negotiation task behind an A2A SendMessage endpoint.

    The run ledger is created lazily on the first wire turn — a server
    no consumer ever calls leaves no run at all. On start() an unfinished
    run in the store is resumed (state replayed, ledger reopened), so
    restart-after-kill continues the same run under the same task id.
    """

    def __init__(self, root: Path | str, task_id: str = "neg-001",
                 host: str = "127.0.0.1", port: int = 0):
        self._root = Path(root)
        self._task_id = task_id
        self._host = host
        self._requested_port = port
        self._adapter = A2aAdapter()
        self._lock = threading.Lock()
        self._http: _NegotiationHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._sm: NegotiationSM | None = None
        self._led: RunLedger | None = None
        self._task: Task | None = None
        self.resumed = False

    @property
    def port(self) -> int:
        if self._http is None:
            raise RuntimeError("server not started")
        return self._http.server_address[1]

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def run_id(self) -> str:
        if self._led is None:
            raise RuntimeError("no negotiation run yet (no wire turn taken)")
        return self._led.run_id

    def start(self) -> int:
        """Bind, resume any unfinished run, and serve; returns the bound port."""
        resumed_ = resume(self._root / ".traceagent" / "runs")
        if resumed_ is not None:
            self._led, self._sm = resumed_
            self.resumed = True
        self._task = self._adapter.new_task(self._task_id)
        if self._sm is not None:
            self._adapter.apply_state(self._task, self._sm.state)
        self._http = _NegotiationHTTPServer((self._host, self._requested_port),
                                            _Handler, negotiation=self)
        self._thread = threading.Thread(target=self._http.serve_forever,
                                        name="traceagent-a2a-transport", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()
            self._http = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def wait(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.join()

    def _ensure_run(self) -> None:
        if self._led is not None:
            return
        self._led = RunLedger.start(
            self._root / ".traceagent" / "runs",
            manifest={"stage": "negotiate", "retry_budget": DEFAULT_RETRY_BUDGET,
                      "transport": "a2a", "task_id": self._task_id},
            repo=self._root)
        self._sm = NegotiationSM.start()

    def _contract_facts(self) -> tuple[str, int, int]:
        contract = load_contract(self._root)
        return contract["name"], len(contract["clause_ids"]), contract["version"] + 1

    # -- wire methods -------------------------------------------------------

    def rpc_send(self, params: dict) -> dict:
        """One SendMessage turn: validate, apply, ledger, answer with the Task."""
        if not isinstance(params, dict) or not isinstance(params.get("message"), dict):
            raise _RpcFault(_INVALID_REQUEST, "params.message (object) is required")
        inbound = params["message"]
        wire_task_id = inbound.get("taskId")
        if wire_task_id and wire_task_id != self._task_id:
            raise _RpcFault(_TASK_NOT_FOUND,
                            f"no such task {wire_task_id!r} (serving {self._task_id!r})")
        metadata = inbound.get("metadata")
        if not isinstance(metadata, dict):
            raise _RpcFault(_INVALID_PARAMS, "message.metadata (object) is required")
        action = metadata.get("action")
        if not action:
            raise _RpcFault(_INVALID_PARAMS, "message.metadata.action is required")
        if action not in _KNOWN_ACTIONS:
            raise _RpcFault(_INVALID_PARAMS,
                            f"unknown action {action!r} (known: {sorted(_KNOWN_ACTIONS)})")

        try:
            proto = ParseDict(inbound, Message())
        except Exception as e:
            raise _RpcFault(_INVALID_PARAMS, f"malformed message: {e}") from e

        with self._lock:
            self._ensure_run()
            try:
                self._apply(action, metadata)
            except IllegalTransition as e:
                raise _RpcFault(_UNSUPPORTED_OPERATION, str(e)) from e
            self._task.history.extend([proto, self._ack()])
            self._adapter.apply_state(self._task, self._sm.state)
            return MessageToDict(SendMessageResponse(task=self._task))

    def rpc_get_task(self, params: dict) -> dict:
        if not isinstance(params, dict):
            raise _RpcFault(_INVALID_REQUEST, "params (object) is required")
        wanted = params.get("id")
        if wanted and wanted != self._task_id:
            raise _RpcFault(_TASK_NOT_FOUND, f"no such task {wanted!r}")
        if self._task is None:
            raise _RpcFault(_TASK_NOT_FOUND,
                            f"no negotiation yet on task {self._task_id!r}")
        return MessageToDict(self._task)

    # -- the canned producer policy -----------------------------------------

    def _apply(self, action: str, metadata: dict) -> None:
        name, clause_count, next_version = self._contract_facts()
        if action == "cfp":
            if self._sm.state != "DRAFT":
                raise IllegalTransition(f"cfp not allowed from {self._sm.state}")
            self._led.append({"event": "cfp", "contract": name, "clauses": clause_count})
            terms = metadata.get("terms", CANNED_COUNTER_TERMS)
            self._sm.counter(terms_string(terms))
            self._led.append({"event": "counter", **self._sm.history[-1]})
            return
        if action == "accept_counter":
            self._require_sheet(metadata)
        missing = [k for k in _ACTION_PARAMS.get(action, ()) if k not in metadata]
        if missing:
            raise AdapterError(f"action {action!r} requires metadata key(s) "
                               f"{missing}")
        kwargs = {k: metadata[k] for k in _ACTION_PARAMS.get(action, ())}
        getattr(self._sm, action)(**kwargs)
        self._led.append({"event": action, **self._sm.history[-1]})
        if self._sm.state == "VALIDATED":
            self._adapter.attach_artifact(
                self._task, "traceagent-contract",
                {"contract": name, "clauses": clause_count, "version": next_version})
            outcome = {"event": "validated", "version": next_version}
            recorded = recorded_counter_terms(self._sm)
            if recorded and recorded[-1] != CANNED_COUNTER_TERMS:
                # a real bargain: bind the outcome to the recorded sheet, the
                # same digest the CLI binds (the ledger is the only truth)
                outcome["terms_digest"] = digest_from_recorded(recorded[-1])
                outcome["decision"] = "accept"
            self._led.append(outcome)

    def _require_sheet(self, metadata: dict) -> None:
        """A bargain may only be accepted by presenting its sheet: a run that
        countered with external terms requires the accept_counter turn to echo
        the recorded counter-proposal — nobody accepts blind what they cannot
        name. The CLI enforces the same rule in advance_to_validated; canned
        runs stay parameterless (the sheet is protocol history, not a secret)."""
        recorded = recorded_counter_terms(self._sm)
        if not recorded or recorded[-1] == CANNED_COUNTER_TERMS:
            return
        if "terms" not in metadata:
            raise IllegalTransition(
                "this run countered with an external term sheet; accept_counter "
                "must echo it as metadata terms (the recorded counter-proposal)")
        echoed = terms_string(metadata["terms"])
        if echoed != recorded[-1]:
            raise IllegalTransition(
                "accept_counter terms do not match the recorded "
                f"counter-proposal {recorded[-1]!r}")

    def _ack(self) -> Message:
        return Message(role=Role.ROLE_AGENT,
                       parts=[Part(text=f"ack: state={self._sm.state}")],
                       task_id=self._task_id)


class _RpcFault(Exception):
    """A domain failure with a wire representation (JSON-RPC error object)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_FAULT_CODES: list[tuple[type[Exception], int]] = [
    (IllegalTransition, _UNSUPPORTED_OPERATION),
    (AdapterError, _INVALID_PARAMS),
]


def _fault_for(exc: Exception) -> _RpcFault:
    for exc_type, code in _FAULT_CODES:
        if isinstance(exc, exc_type):
            return _RpcFault(code, str(exc))
    return _RpcFault(_INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")


class _NegotiationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, negotiation: A2aNegotiationServer):
        self.negotiation = negotiation
        super().__init__(address, handler)


class _Handler(BaseHTTPRequestHandler):
    @property
    def negotiation(self) -> A2aNegotiationServer:
        return self.server.negotiation  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            req = json.loads(body)
            assert isinstance(req, dict)
        except (json.JSONDecodeError, AssertionError) as e:
            self._reply(None, error={"code": _PARSE_ERROR, "message": f"parse error: {e}"})
            return
        req_id = req.get("id")
        if req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            self._reply(req_id, error={"code": _INVALID_REQUEST,
                                       "message": "jsonrpc 2.0 request with a method is required"})
            return
        try:
            if req["method"] not in _METHODS:
                raise _RpcFault(_METHOD_NOT_FOUND, f"unknown method {req['method']!r}")
            params = req.get("params") or {}
            if req["method"] == "SendMessage":
                result = self.negotiation.rpc_send(params)
            else:
                result = self.negotiation.rpc_get_task(params)
            self._reply(req_id, result=result)
        except _RpcFault as e:
            self._reply(req_id, error={"code": e.code, "message": e.message})
        except Exception as e:  # the wire must always carry a typed envelope
            fault = _fault_for(e)
            self._reply(req_id, error={"code": fault.code, "message": fault.message})

    def _reply(self, req_id, result: dict | None = None, error: dict | None = None) -> None:
        payload: dict = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass  # wire traffic is ledgered, not logged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m traceagent.negotiate.transport",
        description="serve one negotiation task on the A2A SendMessage JSON-RPC binding")
    parser.add_argument("--root", default=".", help="contract store root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = ephemeral")
    parser.add_argument("--task-id", default="neg-001")
    args = parser.parse_args(argv)

    server = A2aNegotiationServer(args.root, task_id=args.task_id,
                                  host=args.host, port=args.port)
    port = server.start()
    print(f"traceagent-a2a-transport port={port} task={server.task_id} "
          f"resumed={server.resumed}", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    signal.signal(signal.SIGINT, lambda *_: server.stop())
    server.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
