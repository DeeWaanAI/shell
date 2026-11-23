"""L5 route calls + the declared-vs-metered cost separation (brief §3.3).

The shell NEVER selects a model, infers a price, or stores a secret. Routing is
delegated to L5's ``Router.route`` and the resulting decision record is the
authoritative artifact. This module wraps that call and reshapes its return
into what the route indicator must display, keeping the two cost numbers
apart:

* ``declared_cost_usd``    — L5's ``cost.list_price_estimate_usd`` (policy math
  on user-declared prices and estimated tokens).
* ``actual_metered_cost_usd`` — L5's ``cost.actual_spend_usd`` (provider usage
  result). ``None`` means "not metered", never ``$0``.

Only ``dry_run=True`` routing is used in CP1 (no paid or live provider call —
brief §10 exclusion; build instructions §Exclusions). The wrapper refuses a
non-dry-run call by default so an accidental live run cannot slip through.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

import decide as _decide            # L5 router (source, read-only)
from store import Store as _L5Store  # L5 router store


@dataclass(frozen=True)
class RoutePresentation:
    """The route indicator's payload — one field per visible quantity.

    ``metered`` is a bool (not ``None``) so the display can render the string
    "not metered" when it is False rather than showing ``$0`` (which would
    conflate an absence of measurement with a measured zero).
    """
    outcome: str                              # answered | escalated | planned | refused
    decision_ref: str
    binding_ref: str | None
    chosen_label: str | None
    chosen_locus: str | None                  # 'local' | 'cloud' | None
    chosen_model_ref: str | None
    refusal_reason: str | None
    privacy_warning: str | None
    privacy_class: str
    task_class: str
    feasible_count: int
    declared_cost_usd: float | None
    actual_metered_cost_usd: float | None
    metered: bool
    attempts: list[dict]
    answer: str | None


def _route_to_presentation(route_result: dict) -> RoutePresentation:
    cost = route_result.get("cost") or {}
    declared = cost.get("list_price_estimate_usd")
    actual = cost.get("actual_spend_usd")
    chosen = route_result.get("chosen") or {}
    return RoutePresentation(
        outcome=route_result.get("outcome"),
        decision_ref=route_result.get("decision_ref"),
        binding_ref=route_result.get("binding_ref"),
        chosen_label=chosen.get("label"),
        chosen_locus=chosen.get("locus"),
        chosen_model_ref=chosen.get("model_ref"),
        refusal_reason=route_result.get("refusal_reason"),
        privacy_warning=route_result.get("privacy_warning"),
        privacy_class=route_result.get("privacy_class"),
        task_class=route_result.get("task_class"),
        feasible_count=int(route_result.get("feasible_count") or 0),
        declared_cost_usd=declared,
        actual_metered_cost_usd=actual,
        metered=actual is not None,
        attempts=list(route_result.get("attempts") or []),
        answer=route_result.get("answer"),
    )


class ShellRouter:
    """Thin shell-side wrapper over L5's ``Router``.

    ``store`` is a per-journey L5 ``Store`` scaffolded by the shell on a temp
    root; the shell NEVER writes into L5's frozen ``datasets/`` tree. Routing
    is dry-run by default and the wrapper refuses ``dry_run=False`` unless the
    caller explicitly acknowledges the paid-call boundary.
    """

    def __init__(self, store: _L5Store, *, health=None, free_ram_gb: float | None = None,
                 policy_label: str | None = None):
        self.store = store
        self._router = _decide.Router(store=store, health=health,
                                       free_ram_gb=free_ram_gb,
                                       policy_label=policy_label)

    def route(self, request: dict, *, dry_run: bool = True,
              run: str | None = None,
              allow_live_call: bool = False) -> RoutePresentation:
        if not dry_run and not allow_live_call:
            raise PermissionError(
                "live (non-dry-run) routing requires owner approval + a spend cap "
                "(brief §10; build-instructions Exclusions). Pass "
                "allow_live_call=True ONLY when that approval is recorded.")
        result = self._router.route(request, dry_run=dry_run, run=run)
        return _route_to_presentation(result)
