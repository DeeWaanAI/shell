#!/usr/bin/env python3
"""E1 independent spine — recompute every headline number from raw artifacts.

Refuses to trust ``output/run-summary.json`` or the journey's own ``summary.json``.
Every claim is recomputed from the raw files under ``output/frozen/stores/`` and
cross-checked against the frozen ``inputs/spec.json``. If this script fails, the
E1 claim is withdrawn (PROJECT.md §2).

Run under Python 3.12:

    python3.12 experiments/cp3/e1_journey/spine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CP3 = HERE.parent
EXPERIMENTS = CP3.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(CP3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(f"[E1 spine] {msg}")


def main() -> int:
    _common.pin_environment()
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    expected = spec["expected"]
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E1 output at {out}; run run.py first")

    # Verify the frozen inputs + scripts have not drifted.
    frozen_count = _common.verify_manifest(HERE)

    summary = _common.read_json(out / "summary.json")
    session_id = summary["session_id"]

    # --- Q3 recomputed from raw data.jsonl -----------------------------------
    records = _common.read_jsonl(
        out / "stores" / "qafiya" / "datasets" / "expenses" / "data.jsonl")
    q3 = round(sum(r["amount"] for r in records if r["period"] == "Q3"), 2)
    if q3 != expected["q3_total_after"]:
        _fail(f"Q3 recomputed {q3} != {expected['q3_total_after']}")
    edited = next((r for r in records if r["id"] == "r_051"), None)
    if edited != expected["edited_record"]:
        _fail(f"r_051 mismatch: {edited}")

    # --- audit graph: sequences, states, chain, successor --------------------
    audit_dir = out / "stores" / "shell_audit" / "datasets" / "shell_audit"
    ok, detail = qafiya_chain.verify(audit_dir / "history.jsonl")
    if not ok:
        _fail(f"shell_audit chain broken: {detail}")
    events = _common.read_jsonl(audit_dir / "data.jsonl")
    session_events = sorted((e for e in events if e["session_id"] == session_id),
                              key=lambda e: e["sequence"])
    seqs = [e["sequence"] for e in session_events]
    if seqs != list(range(1, len(seqs) + 1)):
        _fail(f"non-monotonic sequence: {seqs}")
    if len(session_events) != expected["audit_event_count"]:
        _fail(f"event count {len(session_events)} != {expected['audit_event_count']}")
    states = [e["state"] for e in session_events]
    if states != expected["kernel_states"]:
        _fail(f"kernel state walk mismatch:\n  got      {states}\n  expected {expected['kernel_states']}")

    successors = [(e["id"], e["successor_ref"]) for e in session_events
                    if e.get("successor_ref")]
    if not successors:
        _fail("no successor_ref recorded on any audit event")
    recorded_successor = successors[-1][1]

    # --- L5 models: allocated retired, successor active, chain verifies ------
    l5_models = _common.read_jsonl(
        out / "stores" / "l5" / "datasets" / "models" / "data.jsonl")
    by_id = {r["id"]: r for r in l5_models}
    if recorded_successor not in by_id:
        _fail(f"successor {recorded_successor} missing from L5 models")
    if by_id[recorded_successor]["status"] != "active":
        _fail(f"successor {recorded_successor} not active")
    allocated = next((r["id"] for r in l5_models
                        if r.get("superseded_by") == recorded_successor), None)
    if allocated is None:
        _fail(f"no retired record supersedes to {recorded_successor}")
    if by_id[allocated]["status"] != "retired":
        _fail(f"allocated {allocated} not retired")
    if allocated == recorded_successor:
        _fail("successor not distinct from allocated")
    l5_ok, l5_detail = qafiya_chain.verify(
        out / "stores" / "l5" / "datasets" / "models" / "history.jsonl")
    if not l5_ok:
        _fail(f"L5 models chain broken: {l5_detail}")

    # --- route: declared-vs-metered distinct on a dry-run --------------------
    route = _common.read_json(out / "route_presentation.json")
    if route["outcome"] != expected["route_outcome"]:
        _fail(f"route outcome {route['outcome']} != {expected['route_outcome']}")
    if route["metered"] is not expected["route_metered"]:
        _fail(f"route metered {route['metered']} != {expected['route_metered']}")
    if route["actual_metered_cost_usd"] != expected["actual_metered_cost_usd"]:
        _fail("dry-run produced an actual metered cost — must be null")

    # --- action: EXACT, success, note file written ---------------------------
    action = _common.read_json(out / "action_record.json")
    if action["outcome"]["status"] != expected["action_outcome"]:
        _fail(f"action outcome {action['outcome']}")
    if action["reversibility_class"] != expected["action_reversibility_class"]:
        _fail(f"action class {action['reversibility_class']}")
    note_file = out / "stores" / "action" / "files" / "audit" / "q3-expense-edit-cp1.txt"
    if not note_file.exists():
        _fail("audit note file missing")
    if recorded_successor not in note_file.read_text():
        _fail("audit note does not mention the successor id")

    # --- memory: all L4 chains verify ----------------------------------------
    for ds in ("session_log", "preference_store", "longterm_notes",
                 "correction_log", "deletion_log"):
        mok, mdetail = qafiya_chain.verify(
            out / "stores" / "memory" / "datasets" / ds / "history.jsonl")
        if not mok:
            _fail(f"L4 {ds} chain broken: {mdetail}")

    # --- evidence rows --------------------------------------------------------
    evidence = _common.read_json(out / "qafiya_evidence.json")
    if len(evidence["source_rows"]) != expected["evidence_source_rows"]:
        _fail(f"evidence rows {len(evidence['source_rows'])} != "
                f"{expected['evidence_source_rows']}")

    # --- secret hygiene -------------------------------------------------------
    leaks = _common.scan_tree_for_secret(out / "stores", _common.SECRET_VALUE)
    if leaks:
        _fail(f"secret VALUE leaked into: {leaks[:3]}")

    result = {
        "experiment": "E1",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "session_id": session_id,
        "audit_events": len(session_events),
        "kernel_states": states,
        "q3_total_recomputed_from_raw": q3,
        "edited_record": edited,
        "connection_allocated": allocated,
        "connection_successor": recorded_successor,
        "route_outcome": route["outcome"],
        "route_metered": route["metered"],
        "declared_cost_usd": route["declared_cost_usd"],
        "actual_metered_cost_usd": route["actual_metered_cost_usd"],
        "action_outcome": action["outcome"]["status"],
        "action_reversibility_class": action["reversibility_class"],
        "evidence_source_rows": len(evidence["source_rows"]),
        "memory_chains_ok": True,
        "secret_value_absent": True,
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    import json
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
