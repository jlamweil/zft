"""A2A envelope adapter (plan C-32) — the ONLY module allowed to import a2a-sdk.

V7 semantics: gate rejection -> INPUT_REQUIRED (re-open); pre-commitment
refusal -> REJECTED. Contract + deliverable ride DataPart artifacts.
"""
from __future__ import annotations

import json

from google.protobuf.json_format import ParseDict

try:
    from a2a.types import Artifact, Message, Part, Role, Task, TaskState, TaskStatus
except ImportError as e:  # pragma: no cover - a2a extra not installed
    raise ImportError(
        "a2a-sdk is required for the negotiate transport (pip install zft[a2a])"
    ) from e

_Value = None  # set below (late bind to protobuf Value)


def _Value():
    from google.protobuf.struct_pb2 import Value

    return Value()


_WORKFLOW_TO_A2A = {
    "DRAFT": TaskState.TASK_STATE_SUBMITTED,
    "COUNTERED": TaskState.TASK_STATE_INPUT_REQUIRED,
    "REVISED": TaskState.TASK_STATE_WORKING,
    "VALIDATED": TaskState.TASK_STATE_WORKING,
    "IMPLEMENTED": TaskState.TASK_STATE_COMPLETED,
    "REFUSED": TaskState.TASK_STATE_REJECTED,
    "REJECTED": TaskState.TASK_STATE_INPUT_REQUIRED,
}


class AdapterError(ValueError):
    """Malformed payload or protocol violation at the transport seam."""


class A2aAdapter:
    def new_task(self, task_id: str) -> Task:
        return Task(id=task_id, context_id=task_id + "-ctx",
                    status=TaskStatus(state=_WORKFLOW_TO_A2A["DRAFT"]))

    def push_message(self, task: Task, text: str, role: str = "producer") -> None:
        role_part = Role.ROLE_AGENT if role == "producer" else Role.ROLE_USER
        task.history.append(Message(role=role_part, parts=[Part(text=text)]))

    def push_payload(self, task: Task, payload: str, role: str = "consumer") -> None:
        """Structured payload (JSON) transport — malformed payloads are typed errors."""
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as e:
            raise AdapterError(f"malformed payload: {e}") from e
        role_part = Role.ROLE_AGENT if role == "producer" else Role.ROLE_USER
        task.history.append(Message(role=role_part, parts=[Part(data=ParseDict(parsed, _Value()))]))

    def attach_artifact(self, task: Task, name: str, data: dict) -> None:
        task.artifacts.extend([Artifact(artifact_id=f"{task.id}-{name}", name=name,
                                        parts=[Part(data=ParseDict(data, _Value()))])])

    def apply_state(self, task: Task, state: str) -> None:
        if state not in _WORKFLOW_TO_A2A:
            raise AdapterError(f"unknown workflow state {state!r}")
        task.status.CopyFrom(TaskStatus(state=_WORKFLOW_TO_A2A[state]))

    def a2a_name(self, status: TaskStatus) -> str:
        """Canonical a2a state name (authoritative; reverse workflow map is lossy)."""
        return TaskState.DESCRIPTOR.values_by_number[status.state].name

    def to_workflow_state(self, status: TaskStatus) -> str:
        # lossy reverse map: later entries win (REJECTED beats COUNTERED for
        # INPUT_REQUIRED; VALIDATED beats REVISED for WORKING)
        for workflow, a2a_state in reversed(list(_WORKFLOW_TO_A2A.items())):
            if status.state == a2a_state:
                return workflow
        raise AdapterError(f"unmapped task state {status.state!r}")

    def serialize(self, task: Task) -> bytes:
        return task.SerializeToString()

    def deserialize(self, blob: bytes) -> Task:
        task = Task()
        task.ParseFromString(blob)
        return task
