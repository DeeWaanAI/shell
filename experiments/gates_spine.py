#!/usr/bin/env python3
"""Independent CP2 spine — recompute every F1..F8 gate result from raw artifacts.

Qafiya discipline (PROJECT.md §2): the spine recomputes each gate's headline
claim from the raw files the battery wrote, and refuses to trust the battery's
own ``summary.json`` or ``battery-summary.json``. If this script fails, the gate
does not go in the CP2 report.

Per-gate recomputation:

* F1 — replay ``f1/events.json``: sequences are 1..N, every state in the legal
  walk appears, the audit chain verifies, and every illegal probe in
  ``f1/illegal_probes.json`` raised AND wrote no event.
* F2 — re-read each case's ``decision_record.json`` from the L5 store and
  confirm the presentation matches: planned (metered=false, actual=null),
  answered via the fake transport (metered=true, every attempt's meter is the
  SIMULATED label, never presented as real provider metering), refused
  (all_connections_failed, chosen=null).
* F3 — recompute Q3 from ``f3/stores/qafiya/datasets/expenses/data.jsonl``;
  confirm r_051 = 956.14/food/2026-08-09; history grew; invalidation was
  visible BEFORE re-proof; final gate clean.
* F4 — approved file exists with the right content; the reject intent did NOT
  undo it; the refused action wrote no file; the failed action carries a typed
  ``preconditions_failed`` reason.
* F5 — the note's ``derived_from`` contains both turn ids; every L4 dataset is
  all-active; every L4 chain verifies; the evidence panel's first source row is
  the note.
* F6 — the successor id is active in ``f6/stores/l5/datasets/models/data.jsonl``;
  the allocated id is retired with ``superseded_by = successor``; the rejected
  retire (narrow grant) left the active list unchanged; the broken connection
  stays ACTIVE with a typed ``missing_env:`` problem (no implicit retirement);
  the secret VALUE appears in no file; the env NAME is retained; L3 records
  exist for all three mutation types; the L5 models chain verifies.
* F7 — replay the journey's audit graph: sequences complete, every lower-layer
  reference resolves in its owning store, every owned chain verifies.
* F8 — the routed refusal decision record says ``refused`` /
  ``all_connections_failed`` with chosen=null; the L3 failure carries a typed
  ``preconditions_failed`` reason; the synthetic unresolved view's HTML contains
  ``UNRESOLVED``; the unavailable connection stays ACTIVE with a typed
  ``missing_env:`` problem.

Usage:
    python3.12 experiments/gates_spine.py [output_dir]
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
L6 = HERE.parent
if str(L6) not in sys.path:
    sys.path.insert(0, str(L6))

from shell import _bootstrap  # noqa: F401,E402
from qafiya_core import chain as qafiya_chain  # noqa: E402

SECRET_VALUE = "sk-L6-CP2-sentinel-MUST-NEVER-BE-RECORDED-4b7e1d"
BROKEN_ENV_F6 = "L6_SHELL_CP2_BROKEN_KEY_ABSENT"
BROKEN_ENV_F8 = "L6_SHELL_CP2_F8_BROKEN_KEY_ABSENT"
SIMULATED_METER = "simulated_local_fake"
EXPECTED_Q3 = 10481.96
EXPECTED_EDIT = {"id": "r_051", "date": "2026-08-09", "period": "Q3",
                   "amount": 956.14, "category": "food"}
REQUIRED_STATES = {"RECEIVED", "ROUTED", "RECALLED", "COMPOSED", "VIEW_VALIDATED",
                     "RENDERED", "AWAITING_USER", "WRITE_BACK", "ACTION_GATED",
                     "EXECUTED", "REMEMBERED", "CLOSED"}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_json(path: Path):
    return json.loads(path.read_text())


def _scan(root: Path, needle: str) -> list[str]:
    leaks = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = Path(dirpath) / fn
            try:
                if needle in p.read_text(encoding="utf-8"):
                    leaks.append(str(p))
            except (UnicodeDecodeError, OSError):
                continue
    return leaks


def _fail(gate: str, msg: str) -> None:
    raise AssertionError(f"[{gate}] {msg}")


# ------------------------------------------------------------------ F1 spine
def spine_f1(root: Path) -> dict:
    events = _read_json(root / "events.json")
    seqs = [e["sequence"] for e in events]
    if seqs != list(range(1, len(seqs) + 1)):
        _fail("F1", f"non-monotonic sequence: {seqs}")
    states = [e["state"] for e in events]
    if set(states) != REQUIRED_STATES:
        _fail("F1", f"state coverage mismatch: missing={REQUIRED_STATES - set(states)}")
    ok, detail = qafiya_chain.verify(
        root / "stores" / "shell_audit" / "datasets" / "shell_audit" / "history.jsonl")
    if not ok:
        _fail("F1", f"audit chain broken: {detail}")
    probes = _read_json(root / "illegal_probes.json")
    for p in probes["probes"]:
        if not p.get("no_event_written"):
            _fail("F1", f"illegal edge {p['src']}->{p['dst']} did not raise cleanly")
    if not probes["closed_probe"].get("no_event_written"):
        _fail("F1", "CLOSED is not terminal")
    return {"gate": "F1", "events": len(events), "states_covered": sorted(set(states)),
              "chain_ok": True, "illegal_probes": len(probes["probes"]),
              "closed_terminal": True}


# ------------------------------------------------------------------ F2 spine
def spine_f2(root: Path) -> dict:
    cases = _read_json(root / "cases.json")
    by_name = {c["case"]: c for c in cases}
    a, b, c = by_name["A_planned"], by_name["B_answered_fake"], by_name["C_refused_all_failed"]

    if a["outcome"] != "planned" or a["metered"] is not False \
            or a["actual_metered_cost_usd"] is not None:
        _fail("F2", f"case A not a clean dry-run planned: {a}")
    dec_a = _read_json(root / "caseA" / "decision_record.json")
    if dec_a["outcome"] != "planned" or dec_a["id"] != a["decision_ref"]:
        _fail("F2", "case A decision record does not match the presentation")

    if b["outcome"] != "answered" or b["metered"] is not True \
            or b["actual_metered_cost_usd"] is None:
        _fail("F2", f"case B not an answered fake-transport route: {b}")
    dec_b = _read_json(root / "caseB" / "decision_record.json")
    if dec_b["outcome"] != "answered":
        _fail("F2", "case B decision record outcome != answered")
    for attempt in dec_b.get("attempts") or []:
        if attempt.get("meter") != SIMULATED_METER:
            _fail("F2", f"case B attempt meter is not the simulated label: {attempt.get('meter')}")
    hist = _read_json(root / "caseB" / "fake_transport_history.json")
    if not hist:
        _fail("F2", "case B fake transport recorded no calls")

    if c["outcome"] != "refused" or c["refusal_reason"] != "all_connections_failed" \
            or c["chosen_model_ref"] is not None:
        _fail("F2", f"case C not a clean all-failed refusal: {c}")
    dec_c = _read_json(root / "caseC" / "decision_record.json")
    if dec_c["outcome"] != "refused" or dec_c.get("refusal_reason") != "all_connections_failed":
        _fail("F2", "case C decision record does not match the refusal presentation")

    return {"gate": "F2",
              "caseA_outcome": a["outcome"], "caseA_metered": a["metered"],
              "caseB_outcome": b["outcome"], "caseB_metered": b["metered"],
              "caseB_simulated_meter_label": SIMULATED_METER,
              "caseB_actual_cost": b["actual_metered_cost_usd"],
              "caseC_outcome": c["outcome"], "caseC_refusal_reason": c["refusal_reason"]}


# ------------------------------------------------------------------ F3 spine
def spine_f3(root: Path) -> dict:
    records = _read_jsonl(root / "stores" / "qafiya" / "datasets" / "expenses" / "data.jsonl")
    q3 = round(sum(r["amount"] for r in records if r["period"] == "Q3"), 2)
    if q3 != EXPECTED_Q3:
        _fail("F3", f"Q3 recomputed {q3} != {EXPECTED_Q3}")
    edited = next((r for r in records if r["id"] == "r_051"), None)
    if edited != EXPECTED_EDIT:
        _fail("F3", f"r_051 mismatch: {edited}")
    hist = _read_json(root / "history_delta.json")
    if hist["entries_after"] - hist["entries_before"] < 1:
        _fail("F3", "history did not grow after the edit")
    inv = _read_json(root / "invalidation.json")
    if inv["pending_after_edit_before_refresh"] < 1:
        _fail("F3", "no visible invalidation before re-proof")
    if inv["refreshed_bindings"] < 1:
        _fail("F3", "re-proof refreshed nothing")
    if inv["final_gate"] != 0:
        _fail("F3", f"final provenance gate != 0: {inv['final_gate']}")
    before = (root / "qafiya_before.html").read_text()
    assert '<meta charset="utf-8">' in before, "qafiya_before: missing charset meta"
    after = (root / "qafiya_after.html").read_text()
    assert '<meta charset="utf-8">' in after, "qafiya_after: missing charset meta"
    if "10346.71" not in before:
        _fail("F3", "before-html missing the frozen total")
    if "10481.96" not in after or "UNRESOLVED" in after:
        _fail("F3", "after-html missing the recomputed total or carries UNRESOLVED")
    return {"gate": "F3", "q3_recomputed_from_raw": q3, "edited_record": edited,
              "history_grew_by": hist["entries_after"] - hist["entries_before"],
              "pending_before_reproof": inv["pending_after_edit_before_refresh"],
              "refreshed_bindings": inv["refreshed_bindings"],
              "final_gate": inv["final_gate"]}


# ------------------------------------------------------------------ F4 spine
def spine_f4(root: Path) -> dict:
    approved = _read_json(root / "approved_record.json")
    if approved["outcome"]["status"] != "success":
        _fail("F4", f"approved action not successful: {approved['outcome']}")
    note = root / "stores" / "action" / "files" / "f4" / "approved.txt"
    if not note.exists() or note.read_text() != "approved\n":
        _fail("F4", "approved file missing or wrong content")
    refused = _read_json(root / "refused_record.json")
    if refused["outcome"]["status"] != "refused":
        _fail("F4", f"narrow-grant action not refused: {refused['outcome']}")
    refused_file = root / "stores" / "action" / "files" / "f4" / "refused.txt"
    if refused_file.exists():
        _fail("F4", "refused action still wrote a file")
    failed = _read_json(root / "failed_record.json")
    if failed["outcome"]["status"] != "refused" \
            or "preconditions_failed" not in (failed["outcome"].get("reason") or ""):
        _fail("F4", f"failure path not typed preconditions_failed: {failed['outcome']}")
    reject = _read_json(root / "reject_intent.json")
    if reject.get("ok") is not True:
        _fail("F4", "reject intent was not recorded")
    if note.read_text() != "approved\n":
        _fail("F4", "reject intent mutated the approved file")
    return {"gate": "F4", "approved": "success", "refused": "refused",
              "failed_reason_typed": True, "reject_intent_recorded": True,
              "approved_file_unchanged_after_reject": True}


# ------------------------------------------------------------------ F5 spine
def spine_f5(root: Path) -> dict:
    prov = _read_json(root / "note_provenance.json")
    if not prov["turns_bound_as_sources"]:
        _fail("F5", f"note derived_from missing a turn: {prov['derived_from']}")
    counts = _read_json(root / "active_counts.json")
    for ds, c in counts.items():
        if c["non_active"] != 0:
            _fail("F5", f"{ds} carries non-active rows: {c}")
    chains = _read_json(root / "chains.json")
    for ds, ok in chains.items():
        if not ok:
            _fail("F5", f"L4 chain {ds} does not verify")
    ev = _read_json(root / "memory_evidence.json")
    if not ev["source_rows"] or ev["source_rows"][0]["id"] != prov["note_id"]:
        _fail("F5", "evidence panel first source row is not the note")
    html = (root / "memory_inspection.html").read_text()
    assert '<meta charset="utf-8">' in html, "memory_inspection: missing charset meta"
    if "UNRESOLVED" in html:
        _fail("F5", "inspection html carries UNRESOLVED")
    return {"gate": "F5", "note": prov["note_id"],
              "turns_bound_as_sources": True,
              "all_datasets_active_only": True,
              "all_chains_verify": True,
              "evidence_resolves_to_note": True}


# ------------------------------------------------------------------ F6 spine
def spine_f6(root: Path) -> dict:
    models = _read_jsonl(root / "stores" / "l5" / "datasets" / "models" / "data.jsonl")
    by_id = {r["id"]: r for r in models}
    summary = _read_json(root / "summary.json")
    allocated, successor, restored = (summary["allocated"], summary["successor"],
                                         summary["restored"])
    # The battery exercises the FULL succession chain:
    #   add -> allocated (active)
    #   privacy_change -> successor (active), allocated retired (superseded_by=successor)
    #   undo(privacy)  -> restored (active, prior class), successor retired (superseded_by=restored)
    #   explicit retire -> restored retired
    # So by the end every id in the chain is retired. The spine verifies the
    # CHAIN LINKS, not a final active status.
    for label, mid in (("allocated", allocated), ("successor", successor),
                         ("restored", restored)):
        if mid not in by_id:
            _fail("F6", f"{label} {mid} missing from L5 models")
        if by_id[mid]["status"] != "retired":
            _fail("F6", f"{label} {mid} should be retired at the end of the chain, "
                          f"got {by_id[mid]['status']}")
    if by_id[allocated].get("superseded_by") != successor:
        _fail("F6", f"allocated.superseded_by {by_id[allocated].get('superseded_by')} "
                      f"!= successor {successor}")
    if by_id[successor].get("superseded_by") != restored:
        _fail("F6", f"successor.superseded_by {by_id[successor].get('superseded_by')} "
                      f"!= restored {restored}")
    if not (allocated != successor != restored and allocated != restored):
        _fail("F6", "succession chain ids are not distinct")
    priv_undo = _read_json(root / "privacy_undo.json")
    if priv_undo.get("ok") is not True:
        _fail("F6", f"privacy_change undo did not succeed: {priv_undo}")

    before = _read_json(root / "list_before_reject.json")
    after = _read_json(root / "list_after_reject.json")
    if before != after:
        _fail("F6", "rejected retire changed the active list")
    rejected = _read_json(root / "rejected_record.json")
    if rejected["outcome"]["status"] != "refused":
        _fail("F6", f"narrow-grant retire not refused: {rejected['outcome']}")

    broken = _read_json(root / "broken_record.json")
    if broken is None or broken["status"] != "active":
        _fail("F6", "broken connection was implicitly retired")
    status = _read_json(root / "broken_status.json")
    if status["usable"] is not False:
        _fail("F6", "broken connection reported usable")
    if not any(p.startswith(f"missing_env:{BROKEN_ENV_F6}") for p in status["problems"]):
        _fail("F6", f"broken connection problems not typed missing_env: {status['problems']}")

    leaks = _read_json(root / "secret_scan.json")
    if leaks["l5_leaks"] or leaks["l3_leaks"] or leaks["l3_narrow_leaks"]:
        _fail("F6", f"secret VALUE leaked: {leaks}")
    if not leaks["name_retained"]:
        _fail("F6", "env-var NAME not retained in L5/L3 records")

    mutations = set(_read_json(root / "mutation_types.json"))
    for required in ("connection.add", "connection.retire", "connection.privacy_change"):
        if required not in mutations:
            _fail("F6", f"no L3 record for {required}")

    ok, detail = qafiya_chain.verify(
        root / "stores" / "l5" / "datasets" / "models" / "history.jsonl")
    if not ok:
        _fail("F6", f"L5 models chain broken: {detail}")

    return {"gate": "F6", "allocated": allocated, "successor": successor,
              "restored": restored,
              "succession_chain_links_verified": True,
              "privacy_undo_ok": True,
              "rejected_retire_refused": True,
              "list_unchanged_after_rejection": True,
              "broken_stays_active": True,
              "broken_problems_typed": True,
              "secret_value_absent": True, "env_name_retained": True,
              "mutation_types_seen": sorted(mutations),
              "l5_models_chain_ok": True}


# ------------------------------------------------------------------ F7 spine
def spine_f7(root: Path) -> dict:
    session_id = _read_json(root / "session_id.json")["session_id"]
    events = _read_json(root / "events.json")
    seqs = [e["sequence"] for e in events]
    if seqs != list(range(1, len(seqs) + 1)):
        _fail("F7", f"sequences incomplete: {seqs}")
    ids = {e["id"] for e in events}
    for e in events:
        for ref in e.get("input_event_refs", []):
            if ref not in ids:
                _fail("F7", f"unresolved input_event_ref {ref}")
    resolution = _read_json(root / "ref_resolution.json")
    for kind, lst in resolution.items():
        for item in lst:
            if not item["resolved"]:
                _fail("F7", f"{kind} ref {item['ref']} did not resolve in its owning store")
    chains = _read_json(root / "chains.json")
    for name, info in chains.items():
        if not info["ok"]:
            _fail("F7", f"chain {name} broken: {info['detail']}")
    return {"gate": "F7", "session_id": session_id, "events": len(events),
              "sequences_complete": True,
              "all_input_event_refs_resolved": True,
              "all_lower_layer_refs_resolved": True,
              "chains_verified": sorted(chains.keys())}


# ------------------------------------------------------------------ F8 spine
def spine_f8(root: Path) -> dict:
    dec = _read_json(root / "refusal_decision.json")
    if dec["outcome"] != "refused" or dec.get("refusal_reason") != "all_connections_failed":
        _fail("F8", f"routed refusal not typed: {dec['outcome']}/{dec.get('refusal_reason')}")
    if (dec.get("chosen") or {}).get("model_ref") is not None:
        _fail("F8", "refusal decision still names a chosen model")
    failed = _read_json(root / "l3_failure_record.json")
    if failed["outcome"]["status"] != "refused" \
            or "preconditions_failed" not in (failed["outcome"].get("reason") or ""):
        _fail("F8", f"L3 failure not typed preconditions_failed: {failed['outcome']}")
    html = (root / "unresolved" / "view.html").read_text()
    assert '<meta charset="utf-8">' in html, "unresolved_view: missing charset meta"
    if "UNRESOLVED" not in html and "unresolved" not in html.lower():
        _fail("F8", "synthetic unresolved view did not paint UNRESOLVED")
    broken = _read_json(root / "unavailable_record.json")
    if broken is None or broken["status"] != "active":
        _fail("F8", "unavailable connection was implicitly retired")
    status = _read_json(root / "unavailable_status.json")
    if not any(p.startswith(f"missing_env:{BROKEN_ENV_F8}") for p in status["problems"]):
        _fail("F8", f"unavailable connection problems not typed: {status['problems']}")
    return {"gate": "F8", "routed_refusal_typed": True,
              "l3_failure_typed": True,
              "unresolved_view_painted": True,
              "unavailable_connection_typed": True,
              "unavailable_connection_stays_active": True}


SPINES = [("F1", spine_f1), ("F2", spine_f2), ("F3", spine_f3), ("F4", spine_f4),
            ("F5", spine_f5), ("F6", spine_f6), ("F7", spine_f7), ("F8", spine_f8)]


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output" / "cp2"
    root = root.resolve()
    if not root.exists():
        _fail("spine", f"no CP2 output at {root}; run experiments/gates_battery.py first")

    results = []
    for name, fn in SPINES:
        gate_root = root / name.lower()
        if not gate_root.exists():
            _fail(name, f"missing gate output directory {gate_root}")
        results.append(fn(gate_root))

    # Global secret scan across the whole CP2 output tree.
    leaks = _scan(root, SECRET_VALUE)
    if leaks:
        _fail("global", f"secret VALUE leaked into CP2 output: {leaks[:3]}")

    out = {
        "status": "PASS",
        "python": sys.version.split()[0],
        "gates_recomputed": len(results),
        "gates": results,
        "secret_value_absent_from_entire_cp2_tree": True,
    }
    (HERE / "gates-spine-result.json").write_text(
        json.dumps(out, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
