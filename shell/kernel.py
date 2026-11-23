"""Kernel states + the transition table (brief §4.1, sketch §3.1–3.2).

The kernel owns NO lower-layer authority. Every transition appends exactly one
ordered ``ds:shell_audit`` event; illegal transitions raise ``IllegalTransition``
rather than being silently repaired (functional gate F1). Terminal states are
final — a journey that reaches ``CLOSED`` cannot transition again.

Refusal paths are first-class: ``ROUTED -> CLOSED`` (typed routing refusal) and
``ACTION_GATED -> CLOSED`` (L3 refused the action) both produce a complete,
auditable journey with no execution effect. ``EXECUTED -> CLOSED`` covers an
execution failure that still ends the journey honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .audit import ShellAuditStore


class KernelState:
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    RECALLED = "RECALLED"
    COMPOSED = "COMPOSED"
    VIEW_VALIDATED = "VIEW_VALIDATED"
    RENDERED = "RENDERED"
    AWAITING_USER = "AWAITING_USER"
    WRITE_BACK = "WRITE_BACK"
    ACTION_GATED = "ACTION_GATED"
    EXECUTED = "EXECUTED"
    REMEMBERED = "REMEMBERED"
    CLOSED = "CLOSED"

    ALL: tuple[str, ...] = (
        RECEIVED, ROUTED, RECALLED, COMPOSED, VIEW_VALIDATED, RENDERED,
        AWAITING_USER, WRITE_BACK, ACTION_GATED, EXECUTED, REMEMBERED, CLOSED,
    )
    TERMINAL: frozenset[str] = frozenset({CLOSED})


# Allowed edges. Any pair not listed here is illegal by construction and
# raises IllegalTransition rather than being logged as a "recovery".
ALLOWED: dict[str, frozenset[str]] = {
    KernelState.RECEIVED:       frozenset({KernelState.ROUTED}),
    KernelState.ROUTED:         frozenset({KernelState.RECALLED, KernelState.CLOSED}),
    KernelState.RECALLED:       frozenset({KernelState.COMPOSED}),
    KernelState.COMPOSED:       frozenset({KernelState.VIEW_VALIDATED}),
    KernelState.VIEW_VALIDATED: frozenset({KernelState.RENDERED}),
    KernelState.RENDERED:       frozenset({KernelState.AWAITING_USER,
                                            KernelState.WRITE_BACK,
                                            KernelState.REMEMBERED}),
    KernelState.AWAITING_USER:  frozenset({KernelState.ACTION_GATED,
                                            KernelState.WRITE_BACK,
                                            KernelState.REMEMBERED}),
    KernelState.WRITE_BACK:     frozenset({KernelState.VIEW_VALIDATED}),
    KernelState.ACTION_GATED:   frozenset({KernelState.EXECUTED, KernelState.CLOSED}),
    KernelState.EXECUTED:       frozenset({KernelState.REMEMBERED, KernelState.CLOSED}),
    KernelState.REMEMBERED:     frozenset({KernelState.CLOSED}),
    KernelState.CLOSED:         frozenset(),
}


class IllegalTransition(RuntimeError):
    """Raised when the kernel is asked for an edge not in ``ALLOWED``.

    The failure is loud: the audit event is NOT written, so a rejected
    transition cannot pollute the graph. Callers that need a refusal path
    should transition through the explicit refusal edges above.
    """


@dataclass
class KernelContext:
    """Cross-transition state that the audit graph joins but does not own.

    Only references live here — no lower-layer payloads. Anything the shell
    displays must resolve back to a lower-layer record through these refs.
    """
    request_ref: str | None = None
    decision_ref: str | None = None
    view_refs: list[str] = field(default_factory=list)
    edit_refs: list[str] = field(default_factory=list)
    action_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    connection_refs: list[str] = field(default_factory=list)
    # Successor id (mdl_*) recorded whenever a connection mutation superseded.
    successor_ref: str | None = None
    declared_cost_usd: float | None = None
    actual_metered_cost_usd: float | None = None
    content_policy: dict = field(default_factory=dict)
    artifact_hashes: dict = field(default_factory=dict)
    check_states: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)


class Kernel:
    """Named-transition runtime; every transition appends ONE audit event."""

    def __init__(self, session_id: str, audit: ShellAuditStore,
                 ctx: KernelContext | None = None):
        if session_id not in {session_id} or not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id is required")
        self.session_id = session_id
        self.audit = audit
        self.ctx = ctx or KernelContext()
        self.state: str | None = None
        self.history: list[dict] = []      # the audit events this kernel emitted
        self._closed = False

    # -------------------------------------------------------------- transitions
    def enter(self, state: str, *, input_event_refs: list[str] | None = None,
              notes: str | None = None,
              extra_hashes: dict | None = None,
              extra_checks: dict | None = None,
              extra_coverage: dict | None = None,
              request_ref: str | None = None,
              decision_ref: str | None = None,
              view_refs: list[str] | None = None,
              edit_refs: list[str] | None = None,
              action_refs: list[str] | None = None,
              memory_refs: list[str] | None = None,
              connection_refs: list[str] | None = None,
              successor_ref: str | None = None) -> dict:
        """Move to ``state`` and append the audit event. Returns the event.

        Reference-list kwargs are overrides for this ONE event; they also
        persist onto ``self.ctx`` so subsequent events inherit them (the shell
        accumulates refs across a journey rather than repeating them).
        """
        if self._closed:
            raise IllegalTransition(
                f"session {self.session_id} is CLOSED; no further transitions")
        if state not in KernelState.ALL:
            raise IllegalTransition(f"unknown state {state!r}")
        if self.state is None:
            if state != KernelState.RECEIVED:
                raise IllegalTransition(
                    f"first transition must be RECEIVED (got {state!r})")
        else:
            allowed = ALLOWED.get(self.state, frozenset())
            if state not in allowed:
                raise IllegalTransition(
                    f"illegal transition {self.state} -> {state} "
                    f"(allowed: {sorted(allowed)})")

        # Fold any overrides onto the context before writing the event.
        if request_ref is not None:
            self.ctx.request_ref = request_ref
        if decision_ref is not None:
            self.ctx.decision_ref = decision_ref
        if view_refs is not None:
            self.ctx.view_refs = list(view_refs)
        if edit_refs is not None:
            self.ctx.edit_refs = list(edit_refs)
        if action_refs is not None:
            self.ctx.action_refs = list(action_refs)
        if memory_refs is not None:
            self.ctx.memory_refs = list(memory_refs)
        if connection_refs is not None:
            self.ctx.connection_refs = list(connection_refs)
        if successor_ref is not None:
            self.ctx.successor_ref = successor_ref

        hashes = dict(self.ctx.artifact_hashes)
        if extra_hashes:
            hashes.update(extra_hashes)
        checks = dict(self.ctx.check_states)
        if extra_checks:
            checks.update(extra_checks)
        coverage = dict(self.ctx.coverage)
        if extra_coverage:
            coverage.update(extra_coverage)

        event = self.audit.append_event(
            session_id=self.session_id,
            state=state,
            input_event_refs=list(input_event_refs or []),
            request_ref=self.ctx.request_ref,
            decision_ref=self.ctx.decision_ref,
            view_refs=list(self.ctx.view_refs),
            edit_refs=list(self.ctx.edit_refs),
            action_refs=list(self.ctx.action_refs),
            memory_refs=list(self.ctx.memory_refs),
            connection_refs=list(self.ctx.connection_refs),
            successor_ref=self.ctx.successor_ref,
            artifact_hashes=hashes,
            check_states=checks,
            coverage=coverage,
            declared_cost_usd=self.ctx.declared_cost_usd,
            actual_metered_cost_usd=self.ctx.actual_metered_cost_usd,
            content_policy=dict(self.ctx.content_policy),
            notes=notes,
        )
        self.state = state
        self.history.append(event)
        if state == KernelState.CLOSED:
            self._closed = True
        return event

    # ------------------------------------------------------------ graph queries
    def last_event_id(self) -> str | None:
        return self.history[-1]["id"] if self.history else None

    def event_ids(self) -> list[str]:
        return [e["id"] for e in self.history]


def transition_table() -> dict[str, list[str]]:
    """Serialisable view of ``ALLOWED`` for the spine and the paper appendix."""
    return {k: sorted(v) for k, v in ALLOWED.items()}
