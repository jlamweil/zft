"""E2E: the kill-9 negotiation resumption proof, over the A2A wire.

A transport server subprocess takes real wire turns and is then
SIGKILLed (exit -9, no unwinding). The next plain server start must
find the unfinished run, replay its durable prefix, and finish the
SAME run with the same consumer — the ledger holds one gapless
protocol, and the wire answers stay SDK-parseable across the restart.
Runs against a copy of the repo's .zft tree, never the repo itself.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest
from google.protobuf.json_format import ParseDict

pytest.importorskip("a2a")

from a2a.client.transports.jsonrpc import JsonRpcTransport  # noqa: E402
from a2a.types import AgentCard, Message, SendMessageRequest, TaskState  # noqa: E402

from traceagent.debug.ledger import RunLedger  # noqa: E402

REPO = Path(os.environ.get("TRACEAGENT_REPO")
            or Path(__file__).resolve().parents[2])
PY = sys.executable
TASK = "neg-001"
PORT_LINE = re.compile(r"port=(\d+) task=\S+ resumed=(True|False)")


def _store_copy(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(REPO / ".zft", root / ".zft")
    return root


def _start(root: Path) -> tuple[subprocess.Popen, int, bool]:
    """Start a server subprocess; returns (proc, port, resumed)."""
    proc = subprocess.Popen(
        [PY, "-m", "traceagent.negotiate.transport", "--root", str(root),
         "--task-id", TASK],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line: list[str] = []
    reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()),
                              daemon=True)
    reader.start()
    reader.join(timeout=15)
    if not line:
        proc.kill()
        raise AssertionError(f"server printed no port line: {proc.stderr.read()!r}")
    match = PORT_LINE.search(line[0])
    assert match, f"unparsable server banner: {line[0]!r}"
    return proc, int(match.group(1)), match.group(2) == "True"


def _send(port: int, **metadata):
    async def go():
        async with httpx.AsyncClient() as hc:
            transport = JsonRpcTransport(hc, AgentCard(), f"http://127.0.0.1:{port}/")
            message = ParseDict({"messageId": f"m-{sorted(metadata.items())}",
                                 "role": "ROLE_USER", "taskId": TASK,
                                 "metadata": metadata}, Message())
            return await transport.send_message(SendMessageRequest(message=message))

    return asyncio.run(go())


def _sole_run_events(root: Path) -> list[dict]:
    runs = sorted((root / ".traceagent" / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {[r.name for r in runs]}"
    return RunLedger.load(runs[0].parent, runs[0].name).events


# @trace("PRT-A2A-TRANSPORT")
def test_kill9_mid_wire_protocol_resumes_same_run(tmp_path):
    root = _store_copy(tmp_path)

    # phase 1: real wire turns, then the real kill (exit -9, no unwinding)
    proc, port, resumed = _start(root)
    assert not resumed
    task = _send(port, action="cfp").task
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED, \
        "the canned producer counters inside the cfp turn"
    proc.kill()
    proc.wait()
    assert proc.returncode == -9, \
        f"the server must die by SIGKILL, got rc={proc.returncode}"
    events = _sole_run_events(root)
    assert [e["event"] for e in events] == ["cfp", "counter"], \
        "durable prefix only — nothing after the kill may exist"

    # phase 2: a plain server start resumes the SAME run over the wire
    proc2, port2, resumed2 = _start(root)
    try:
        assert resumed2, "the unfinished run must resume, not restart"
        task = _send(port2, action="accept_counter").task
        assert task.status.state == TaskState.TASK_STATE_WORKING
        task = _send(port2, action="validate").task
        assert [a.name for a in task.artifacts] == ["traceagent-contract"]
        events = _sole_run_events(root)
        assert [e["event"] for e in events] == \
            ["cfp", "counter", "resumed", "accept_counter", "validate", "validated"], \
            "one gapless protocol: durable prefix + ledgered resume + the finish"
        resumed_event = next(e for e in events if e["event"] == "resumed")
        assert resumed_event["replayed"] == 1 and resumed_event["state"] == "COUNTERED"
    finally:
        proc2.terminate()
        proc2.wait()
