"""Native L5-backed connection surface (brief §3.4).

Read-only ``list`` and measured ``status`` remain L5 operations with their own
evidence — they are NOT actions. **Every mutating operation** (add, retire,
privacy_change) is submitted as an intent to L3, which runs its deterministic
gate + confirmation and produces an ``a_*`` record that joins ``ds:shell_audit``.

Hard-won integration facts (build-instructions §1 and §2):

* L5's ``ConnectionOperations(Store)`` is handed to L3 as
  ``ActionEngine(root, connection_ops=<that object>)``. The shell never calls
  ``add_connection`` / ``retire_connection`` / ``set_privacy_class`` directly;
  it goes through ``ActionEngine.act`` so the L3 record exists.
* ``connection.retire`` and ``connection.privacy_change`` are COMPENSABLE and
  supersede to a NEW ``mdl_*`` id (L5 spec v1.1: ids are immutable, changes
  happen by succession). After the L3 action succeeds, the successor id is read
  from ``ops.get_active_successor(old_id)`` or ``ops.last_successor_id`` and
  recorded on the shell's audit event as ``successor_ref``. A connection id is
  NEVER assumed stable across a mutation.
* ``connection.add -> str`` (the allocated id). Undo of add = retire that id.

Secrets stay out of the record. The shell forwards a config whose ``key_env``
is a bare env-var NAME; L5 refuses a value, and L3 refuses any secret-shaped
field. Defence in depth is on both sides of the boundary.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

from actionlayer.engine import ActionEngine          # L3 (source, read-only)
from actionlayer.gate import make_grant              # L3
from connection_ops import ConnectionOperations      # L5 (source, read-only)
from store import Store as L5Store, DATASETS as L5_DATASETS  # L5
import connections as L5Connections                  # L5 read-only surface


CONNECTION_ACTION_TYPES = ("connection.add", "connection.retire",
                            "connection.privacy_change")


@dataclass
class ConnectionMutationResult:
    """What the shell records after an L3-gated connection mutation.

    ``successor_ref`` is populated for retire (the retired id) and
    privacy_change (the newly minted active id). It is NEVER inferred from the
    original id — the shell asks L5's accessors after execute succeeds.
    """
    action_ref: str
    action_outcome: str                    # success | refused | failed
    reversibility_class: str | None
    original_id: str | None
    successor_ref: str | None
    allocated_id: str | None               # only for connection.add
    detail: str = ""
    record: dict = field(default_factory=dict)


class ShellConnections:
    """Native L5-backed connection surface, mutations submitted to L3.

    ``l5_root`` holds the shell's per-journey L5 store (schemas copied from
    the frozen L5 datasets, empty data). ``l3_root`` holds the L3 action store
    for the same journey. The frozen L5 datasets are never written to.
    """

    def __init__(self, *, l5_root: Path | str, l3_root: Path | str,
                 frozen_l5_root: Path | str, user_id: str = "youssef",
                 agent_id: str = "l6-shell"):
        self.l5_root = Path(l5_root)
        self.l3_root = Path(l3_root)
        self.user_id = user_id
        self.agent_id = agent_id
        self.store = self._scaffold_l5_store(Path(frozen_l5_root))
        self.ops = ConnectionOperations(self.store)
        # The one and only wiring: L5's public ops object handed to L3.
        self.engine = ActionEngine(self.l3_root, connection_ops=self.ops)
        self._grant_id: str | None = None

    # ------------------------------------------------------------------ grants
    def ensure_grant(self) -> str:
        """Issue (once) the connection-mutation grant for this shell user."""
        if self._grant_id is not None:
            return self._grant_id
        grant = self.engine.issue_grant(make_grant(
            user_id=self.user_id,
            action_types=list(CONNECTION_ACTION_TYPES),
            target_pattern="mdl_*"))
        self._grant_id = grant["_id"]
        return self._grant_id

    # ------------------------------------------------------- read-only surface
    def list_active(self) -> list[dict]:
        """Read-only listing of ACTIVE connections (L5 op, not an action).

        Returns the raw L5 records so the display can render label, connector,
        locus, privacy_class, price.source and status without shell-side
        inference.
        """
        return [r for r in self.store.records("models", status="active")
                if "connector" in r]

    def status(self, mdl_id: str) -> dict:
        """Measured/declared status for one connection (L5 op, not an action).

        Uses L5's own ``connections.normalise`` to expose the same problems the
        router sees (missing env-var NAME reported, never resolved to a
        placeholder). This is a declaration-time check, not a live probe.
        """
        rec = self.store.get("models", mdl_id)
        if rec is None:
            return {"id": mdl_id, "found": False}
        conn, problems = L5Connections.normalise(rec)
        return {
            "id": mdl_id, "found": True, "status": rec.get("status"),
            "superseded_by": rec.get("superseded_by"),
            "locus": rec.get("locus"),
            "privacy_class": rec.get("privacy_class"),
            "usable": conn is not None,
            "problems": problems,
            "warnings": (conn or {}).get("warnings", []),
        }

    def active_successor(self, mdl_id: str) -> str | None:
        """Follow ``superseded_by`` to the active successor (L5 accessor)."""
        return self.ops.get_active_successor(mdl_id)

    # ------------------------------------------------------- mutating surface
    def add(self, config: dict, *, intent_verbatim: str,
             session_id: str) -> ConnectionMutationResult:
        """Submit a ``connection.add`` intent through L3.

        ``config`` carries the env-var NAME under ``key_env`` — never a value.
        L3's adapter validates the config against CONFIG_FIELDS and refuses
        any SECRET_FIELDS entry before invoking L5.
        """
        grant_id = self.ensure_grant()
        record = self.engine.act(
            intent_verbatim=intent_verbatim,
            normalized={"action_type": "connection.add",
                        "params": {"config": dict(config), "target": "mdl_new"}},
            actor={"agent_id": self.agent_id, "session_id": session_id},
            user_id=self.user_id, grant_id=grant_id)
        return self._shape(record, original_id=None, is_add=True)

    def retire(self, mdl_id: str, config: dict, *, intent_verbatim: str,
                session_id: str) -> ConnectionMutationResult:
        """Submit a ``connection.retire`` intent through L3 (COMPENSABLE)."""
        grant_id = self.ensure_grant()
        record = self.engine.act(
            intent_verbatim=intent_verbatim,
            normalized={"action_type": "connection.retire",
                        "params": {"connection_id": mdl_id, "config": dict(config)}},
            actor={"agent_id": self.agent_id, "session_id": session_id},
            user_id=self.user_id, grant_id=grant_id)
        return self._shape(record, original_id=mdl_id, is_add=False)

    def change_privacy(self, mdl_id: str, *, new_class: str, previous_class: str,
                        intent_verbatim: str,
                        session_id: str) -> ConnectionMutationResult:
        """Submit ``connection.privacy_change`` through L3 (COMPENSABLE, succession).

        On success L5 mints a NEW ``mdl_*`` id and retires the old one with
        ``superseded_by = new_id``. The successor id is read from L5's
        accessors and returned as ``successor_ref`` — never assumed stable.
        """
        grant_id = self.ensure_grant()
        record = self.engine.act(
            intent_verbatim=intent_verbatim,
            normalized={"action_type": "connection.privacy_change",
                        "params": {"connection_id": mdl_id,
                                    "new_class": new_class,
                                    "previous_class": previous_class}},
            actor={"agent_id": self.agent_id, "session_id": session_id},
            user_id=self.user_id, grant_id=grant_id)
        return self._shape(record, original_id=mdl_id, is_add=False,
                             is_privacy=True)

    # ------------------------------------------------------------------ helpers
    def _shape(self, record: dict, *, original_id: str | None,
                 is_add: bool, is_privacy: bool = False) -> ConnectionMutationResult:
        outcome = record.get("outcome", {}).get("status", "unknown")
        allocated: str | None = None
        successor: str | None = None
        detail = ""
        if outcome == "success":
            if is_add:
                # The L3 adapter puts the allocated id in the late undo recipe.
                recipe = record.get("undo_recipe") or {}
                for op in recipe.get("ops", []):
                    if op.get("op") == "connection_retire":
                        allocated = op.get("connection_id")
                        break
                successor = allocated  # for add, the new id IS the successor
                detail = f"allocated {allocated}"
            elif is_privacy:
                # Ask L5 for the active successor of the retired id.
                successor = (self.ops.get_active_successor(original_id)
                              if original_id else None) or self.ops.last_successor_id
                detail = f"succession {original_id} -> {successor}"
            else:
                # retire: no successor is minted; the id stays retired.
                successor = None
                detail = f"retired {original_id}"
        else:
            detail = record.get("outcome", {}).get("reason", "")
        return ConnectionMutationResult(
            action_ref=record.get("action_id"),
            action_outcome=outcome,
            reversibility_class=record.get("reversibility_class"),
            original_id=original_id,
            successor_ref=successor,
            allocated_id=allocated,
            detail=detail,
            record=record,
        )

    # ------------------------------------------------------ per-journey scaffold
    def _scaffold_l5_store(self, frozen_l5_root: Path) -> L5Store:
        """Create the shell's writable L5 store on ``self.l5_root``.

        Schemas are copied read-only from the frozen L5 datasets; ``models``
        and ``decision_log`` start EMPTY so the shell never writes into a copy
        of the real decision history; ``policy``, ``rules`` and ``capabilities``
        are seeded from the frozen data so ``Router.route(dry_run=True)`` has
        the inputs it needs. Bindings/history/SUPERSEDED start empty for every
        dataset — the shell's writes chain from genesis.

        The frozen L5 root is READ ONLY here. Nothing is written back.
        """
        for name in L5_DATASETS:
            src = frozen_l5_root / "datasets" / name
            dst = self.l5_root / "datasets" / name
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / "schema.json", dst / "schema.json")
            seed = name in ("policy", "rules", "capabilities")
            if seed:
                shutil.copyfile(src / "data.jsonl", dst / "data.jsonl")
            else:
                (dst / "data.jsonl").write_text("")
            (dst / "history.jsonl").write_text("")
            (dst / "bindings.jsonl").write_text("")
            (dst / "SUPERSEDED.json").write_text("[]\n")
        return L5Store(self.l5_root)
