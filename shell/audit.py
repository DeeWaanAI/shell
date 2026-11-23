"""``ds:shell_audit`` — the shell's own append-only, chained audit graph.

Full Qafiya §8 fileset (schema.json + data.jsonl + history.jsonl chained via
``qafiya_core.chain`` + bindings.jsonl + SUPERSEDED.json). Each event is an
``r_*`` record carrying:

* session id, monotonic per-session sequence, kernel state, timestamp;
* references to lower-layer records (req/dec/view/edit/action/memory/mdl);
* ``input_event_refs`` so causal order is explicit, not inferred from time;
* artifact hashes and check/coverage where applicable;
* ``successor_ref`` when a connection mutation superseded to a new ``mdl_*`` id
  (never assume a connection id is stable across a mutation — build
  instructions §hard-won fact 2);
* content only when the active L5 policy permits it.

The shell audit JOINS lower-layer records; it never rewrites or merges their
bindings. Replay starts from a session id and resolves the complete graph.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

from qafiya_core import chain as _chain  # frozen v1.3 chained history

DATASET = "shell_audit"
SPEC_REF = (
    "Qafiya v1.1 §8 layout; v1.3 chained history; "
    "L6 brief.md §4.2 (audit event graph)"
)

SCHEMA: dict = {
    "dataset": DATASET,
    "record_type": "shell_audit_event",
    "id_field": "id",
    "id_prefix": "r_",
    "spec_ref": SPEC_REF,
    "fields": {
        "id": "id",
        "created_at": "timestamp",
        "spec_version": "string",
        "status": "enum[active,retired,discredited]",
        "superseded_by": "id|null",
        "source_ref": "list<id>",
        "session_id": "id",
        "sequence": "number",
        "state": "string",
        "input_event_refs": "list<id>",
        "request_ref": "id|null",
        "decision_ref": "id|null",
        "view_refs": "list<id>",
        "edit_refs": "list<id>",
        "action_refs": "list<id>",
        "memory_refs": "list<id>",
        "connection_refs": "list<id>",
        "successor_ref": "id|null",
        "artifact_hashes": "object",
        "check_states": "object",
        "coverage": "object",
        "declared_cost_usd": "number|null",
        "actual_metered_cost_usd": "number|null",
        "content_policy": "object",
        "notes": "string|null",
    },
    "derivations": ["filter", "count", "groupby"],
}


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    """Prefixed sortable id (INTERFACES.md OS identity rule)."""
    return f"{prefix}_{int(time.time() * 1000):013d}{secrets.token_hex(3)}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


class ShellAuditStore:
    """Append-only audit store with a chained history (Qafiya §8 + v1.3).

    A separate store is instantiated per journey root so a run never writes
    into another run's artifacts, matching the pre-flight's per-run output
    directory discipline.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.dir = self.root / "datasets" / DATASET
        self.dir.mkdir(parents=True, exist_ok=True)
        self._init_fileset()
        self._seq: dict[str, int] = {}

    # ---------------------------------------------------------------- layout
    def _init_fileset(self) -> None:
        schema_path = self.dir / "schema.json"
        if not schema_path.exists():
            schema_path.write_text(json.dumps(SCHEMA, indent=1, sort_keys=True) + "\n")
        for name in ("data.jsonl", "history.jsonl", "bindings.jsonl"):
            p = self.dir / name
            if not p.exists():
                p.touch()
        sup = self.dir / "SUPERSEDED.json"
        if not sup.exists():
            sup.write_text("[]\n")

    # ---------------------------------------------------------------- writes
    def append_event(self, *, session_id: str, state: str,
                     input_event_refs: list[str] | None = None,
                     request_ref: str | None = None,
                     decision_ref: str | None = None,
                     view_refs: list[str] | None = None,
                     edit_refs: list[str] | None = None,
                     action_refs: list[str] | None = None,
                     memory_refs: list[str] | None = None,
                     connection_refs: list[str] | None = None,
                     successor_ref: str | None = None,
                     artifact_hashes: dict | None = None,
                     check_states: dict | None = None,
                     coverage: dict | None = None,
                     declared_cost_usd: float | None = None,
                     actual_metered_cost_usd: float | None = None,
                     content_policy: dict | None = None,
                     notes: str | None = None,
                     source_ref: list[str] | None = None) -> dict:
        """Append one ``r_*`` audit event and a chained history entry.

        Sequence numbers are monotonic per session and are allocated here so
        two callers cannot mint the same sequence for one session.
        """
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id is required")
        if not isinstance(state, str) or not state:
            raise ValueError("state is required")
        n = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = n
        event = {
            "id": new_id("r"),
            "created_at": _now(),
            "spec_version": "0.1",
            "status": "active",
            "superseded_by": None,
            "source_ref": list(source_ref or []),
            "session_id": session_id,
            "sequence": n,
            "state": state,
            "input_event_refs": list(input_event_refs or []),
            "request_ref": request_ref,
            "decision_ref": decision_ref,
            "view_refs": list(view_refs or []),
            "edit_refs": list(edit_refs or []),
            "action_refs": list(action_refs or []),
            "memory_refs": list(memory_refs or []),
            "connection_refs": list(connection_refs or []),
            "successor_ref": successor_ref,
            "artifact_hashes": dict(artifact_hashes or {}),
            "check_states": dict(check_states or {}),
            "coverage": dict(coverage or {}),
            "declared_cost_usd": declared_cost_usd,
            "actual_metered_cost_usd": actual_metered_cost_usd,
            "content_policy": dict(content_policy or {}),
            "notes": notes,
        }
        self._write_record(event)
        return event

    def append_binding(self, binding: dict) -> dict:
        """Append a Qafiya §7 binding for a value/claim the shell displayed.

        The shell keeps its own bindings separate from lower-layer bindings;
        this never rewrites or merges theirs (brief §5 boundary).
        """
        for f in ("id", "kind", "target", "derivation", "statistic",
                  "device", "authoritative_artifact", "sources", "value"):
            if f not in binding:
                raise ValueError(f"binding missing required field {f!r}")
        if not binding.get("sources"):
            raise ValueError("binding.sources MUST be non-empty (Qafiya I1)")
        with (self.dir / "bindings.jsonl").open("a") as fh:
            fh.write(_canon(binding) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _chain.append(self.dir / "history.jsonl",
                      {"op": "binding", "record": binding, "at": _now()})
        return binding

    def _write_record(self, event: dict) -> None:
        with (self.dir / "data.jsonl").open("a") as fh:
            fh.write(_canon(event) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _chain.append(self.dir / "history.jsonl",
                      {"op": "append", "record": event, "at": _now()})

    # ----------------------------------------------------------------- reads
    def events(self, session_id: str | None = None) -> list[dict]:
        rows = [json.loads(line)
                for line in (self.dir / "data.jsonl").read_text().splitlines()
                if line.strip()]
        if session_id is None:
            return rows
        return [r for r in rows if r.get("session_id") == session_id]

    def bindings(self) -> list[dict]:
        return [json.loads(line)
                for line in (self.dir / "bindings.jsonl").read_text().splitlines()
                if line.strip()]

    def superseded(self) -> list[dict]:
        return json.loads((self.dir / "SUPERSEDED.json").read_text() or "[]")

    def verify_chain(self) -> tuple[bool, str]:
        return _chain.verify(self.dir / "history.jsonl")

    # ---------------------------------------------------------------- replay
    def replay(self, session_id: str) -> dict:
        """Resolve one session's event graph and check every reference shape.

        Returns ``{"events": [...], "sequences": [...], "chain_ok": bool,
        "input_refs_resolved": int, "input_refs_missing": list[str],
        "successors": [(event_id, successor_ref), ...]}``. Lower-layer
        references (``decision_ref``/``action_refs``/...) are NOT resolved
        here — that is the shell spine's job against the owning stores, so a
        replay never depends on the shell holding another layer's data.
        """
        events = self.events(session_id)
        events.sort(key=lambda e: e["sequence"])
        ids = {e["id"] for e in events}
        missing: list[str] = []
        resolved = 0
        for e in events:
            for ref in e.get("input_event_refs", []):
                if ref in ids:
                    resolved += 1
                else:
                    missing.append(ref)
        successors = [(e["id"], e["successor_ref"]) for e in events
                      if e.get("successor_ref")]
        chain_ok, chain_detail = self.verify_chain()
        return {
            "session_id": session_id,
            "events": events,
            "sequences": [e["sequence"] for e in events],
            "chain_ok": chain_ok,
            "chain_detail": chain_detail,
            "input_refs_resolved": resolved,
            "input_refs_missing": missing,
            "successors": successors,
        }
