"""Edit + action intent dispatch (brief §4.1 WRITE_BACK / ACTION_GATED).

DVR emits interaction INTENT; the shell routes it to the authority below the
display. A cell edit goes through ``dvr.edits.apply`` (which writes through
qafiya-core). An action choice goes through L3's ``ActionEngine.act``; only
L3's deterministic gate can execute it.

This module never treats a rendered button as authority. If a caller tries to
execute an action without an L3 grant, L3 refuses; the shell records the
refusal on the audit graph and reports it honestly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

from actionlayer.engine import ActionEngine            # L3 (source, read-only)
from dvr import edits as dvr_edits                     # frozen dvr/1.1
from qafiya_core import engine as qafiya_engine        # frozen Qafiya


@dataclass
class EditResult:
    edit_binding_id: str
    updated_record: dict
    invalidated: int
    qafiya_gate_after: int


@dataclass
class ActionResult:
    action_ref: str
    outcome: str                              # success | refused | failed
    reversibility_class: str | None
    reason: str
    record: dict


def apply_cell_edit(qafiya_root: Path | str, view_id: str, node: dict,
                     new_value) -> EditResult:
    """One cell edit → DVR binding → qafiya-core write-back → recompute gate.

    The gate is refreshed after the write so a stale value cannot survive into
    the next render (brief §4.1 WRITE_BACK).
    """
    root = Path(qafiya_root)
    binding = dvr_edits.make_edit_binding(root, view_id, node, new_value)
    updated, invalidated = dvr_edits.apply(root, binding)
    qafiya_engine.refresh_values(root)
    gate = qafiya_engine.provenance_gate(root)
    return EditResult(edit_binding_id=binding["id"], updated_record=updated,
                       invalidated=int(invalidated), qafiya_gate_after=int(gate))


class ActionDispatcher:
    """Submit action intents to L3 and shape the outcome for the audit graph.

    The dispatcher NEVER executes anything itself. Every effect comes from
    ``ActionEngine.act`` with an explicit grant. If confirmation is required
    and not given, L3 refuses and the shell records the refusal as a result.
    """

    def __init__(self, engine: ActionEngine):
        self.engine = engine

    def submit(self, *, intent_verbatim: str, normalized: dict, actor: dict,
                 user_id: str, grant_id: str | None = None,
                 confirm_irreversible: bool = False) -> ActionResult:
        record = self.engine.act(
            intent_verbatim=intent_verbatim, normalized=normalized, actor=actor,
            user_id=user_id, grant_id=grant_id,
            confirm_irreversible=confirm_irreversible)
        outcome = record.get("outcome", {})
        return ActionResult(
            action_ref=record.get("action_id"),
            outcome=outcome.get("status", "unknown"),
            reversibility_class=record.get("reversibility_class"),
            reason=outcome.get("reason", ""),
            record=record,
        )

    def undo(self, action_id: str) -> dict:
        return self.engine.undo(action_id)

    def receive_confirmation_intent(self, action_id: str, choice: str,
                                      user_id: str) -> dict:
        """A DVR approve/reject intent — records the intent, does NOT execute."""
        return self.engine.receive_confirmation_intent(action_id, choice, user_id)
