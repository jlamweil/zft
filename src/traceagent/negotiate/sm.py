"""Negotiation state machine (D6, V7 semantics).

States: DRAFT -> COUNTERED -> REVISED -> VALIDATED -> IMPLEMENTED
         DRAFT/REVISED -> REFUSED (pre-commitment, terminal)
         IMPLEMENTED -> REJECTED (gate) -> REVISED (bounded retry loop)
"""
from __future__ import annotations

import inspect

DEFAULT_RETRY_BUDGET = 3

_TRANSITIONS = {
    "DRAFT": {"counter", "validate", "refuse"},
    "COUNTERED": {"accept_counter", "refuse"},
    "REVISED": {"validate", "refuse"},
    "VALIDATED": {"implement"},
    "IMPLEMENTED": {"reject_gate"},
    "REJECTED": {"reopen"},
}

# every action name the table admits — the replay filter for ledger events
ACTIONS = set().union(*_TRANSITIONS.values())


class IllegalTransition(RuntimeError):
    """Transition not allowed by the negotiation protocol."""


def _check_replay_kwargs(sm: "NegotiationSM", action: str, kwargs: dict) -> None:
    """A ledger entry whose kwargs don't fit the action's signature is torn or
    forged (corruption, truncation, hand-editing) — fail typed here rather
    than TypeError mid-replay, so resumption never crashes untyped."""
    params = inspect.signature(getattr(sm, action)).parameters
    missing = [n for n, p in params.items()
               if p.default is p.empty and p.kind != p.VAR_POSITIONAL
               and n not in kwargs]
    unknown = ([k for k in kwargs if k not in params]
               if not any(p.kind is p.VAR_KEYWORD for p in params.values())
               else [])
    if missing or unknown:
        raise IllegalTransition(
            f"torn history at {action}: missing {missing}, unknown {unknown}")


class NegotiationSM:
    def __init__(self, state: str = "DRAFT", retry_budget: int = DEFAULT_RETRY_BUDGET,
                 retries: int = 0, history: list[dict] | None = None):
        self.state = state
        self.retry_budget = retry_budget
        self.retries = retries
        self.history = history or []

    @classmethod
    def start(cls, retry_budget: int = DEFAULT_RETRY_BUDGET) -> "NegotiationSM":
        return cls(retry_budget=retry_budget)

    @classmethod
    def replay(cls, history: list[dict],
               retry_budget: int = DEFAULT_RETRY_BUDGET) -> "NegotiationSM":
        """Rebuild a machine from persisted history entries (crash resumption).

        Each entry is a ledger record {action, from, to, **detail} — exactly
        the shape history appends. The chain is verified as it is replayed:
        an entry whose from/to disagrees with the transition the machine
        actually takes is forged or torn and fails typed, so resumption
        never silently trusts a log it did not earn. `reopen` re-spends the
        retry budget on replay, so a resumed machine is budget-faithful.
        """
        sm = cls(retry_budget=retry_budget)
        for entry in history:
            # raw ledger events ride alongside transitions (cfp, validated,
            # resumed) — an entry with no action of its own is not a step
            action = entry.get("action") or (
                entry["event"] if entry.get("event") in ACTIONS else None)
            if action is None:
                continue
            if action not in ACTIONS:
                raise IllegalTransition(f"cannot replay unknown action {action!r}")
            kwargs = {k: v for k, v in entry.items()
                      if k not in ("action", "from", "to", "event")}
            _check_replay_kwargs(sm, action, kwargs)
            prev = sm.state
            getattr(sm, action)(**kwargs)
            if entry.get("from") != prev or entry.get("to") != sm.state:
                raise IllegalTransition(
                    f"history mismatch at {action}: recorded "
                    f"{entry.get('from')}->{entry.get('to')}, replayed {prev}->{sm.state}"
                )
        return sm

    def _to(self, new_state: str, action: str, **detail) -> None:
        if new_state == self.state:
            raise IllegalTransition(f"self-loop {action} in {self.state}")
        allowed = _TRANSITIONS.get(self.state, set())
        if action not in allowed:
            raise IllegalTransition(f"{action} not allowed from {self.state}")
        prev, self.state = self.state, new_state
        self.history.append({"action": action, "from": prev, "to": new_state, **detail})

    def counter(self, terms: str) -> None:
        self._to("COUNTERED", "counter", terms=terms)

    def accept_counter(self) -> None:
        self._to("REVISED", "accept_counter")

    def validate(self) -> None:
        self._to("VALIDATED", "validate")

    def implement(self) -> None:
        self._to("IMPLEMENTED", "implement")

    def refuse(self, reason: str) -> None:
        self._to("REFUSED", "refuse", reason=reason)

    def reject_gate(self, clause_ids: list[str], fault: str) -> None:
        """Gate rejection: fault-attributed, budget-bounded re-open."""
        self._to("REJECTED", "reject_gate", clause_ids=clause_ids, fault=fault)

    def reopen(self) -> None:
        if self.retries >= self.retry_budget:
            raise IllegalTransition(
                f"retry budget exhausted ({self.retries}/{self.retry_budget})"
            )
        self._to("REVISED", "reopen")
        self.retries += 1  # only a successful re-open spends budget
