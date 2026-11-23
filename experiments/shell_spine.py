#!/usr/bin/env python3
"""Independent CP1 spine — recompute every headline number from raw artifacts.

Qafiya discipline (PROJECT.md §2): a spine recomputes each claim from the raw
files rather than trusting the run's own summary. If this script fails, the
number does not go in the report.

Recomputes:

* Q3 total from ``stores/qafiya/datasets/expenses/data.jsonl`` (must be 10481.96)
* edited record ``r_051`` fields (amount 956.14, category food, date 2026-08-09)
* audit chain over ``stores/shell_audit/datasets/shell_audit/history.jsonl``
* per-session monotonic sequences (1..N, no gaps)
* successor id: the ``mdl_*`` recorded on the audit graph must be the ACTIVE
  successor of the allocated id in ``stores/l5/datasets/models/data.jsonl``
* L5 ``models`` chain integrity
* route outcome + declared-vs-metered separation from ``route_presentation.json``
  (metered must be False for a dry-run — never conflated with $0)
* secret hygiene: the sentinel VALUE must appear in NO file under ``stores/``
* every HTML render is present and free of ``UNRESOLVED``
* kernel state coverage: every state in brief §4.1 appears at least once

Usage:
    python3.12 experiments/shell_spine.py [output_dir]
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # 06-shell/experiments
L6 = HERE.parent
if str(L6) not in sys.path:
    sys.path.insert(0, str(L6))

from shell import _bootstrap  # noqa: F401,E402
from qafiya_core import chain as _chain  # noqa: E402

SECRET_VALUE = "sk-L6-CP1-sentinel-MUST-NEVER-BE-RECORDED-9f3a7c"
EXPECTED_Q3 = 10481.96
EXPECTED_EDIT = {"id": "r_051", "date": "2026-08-09", "period": "Q3",
                   "amount": 956.14, "category": "food"}
REQUIRED_STATES = {"RECEIVED", "ROUTED", "RECALLED", "COMPOSED", "VIEW_VALIDATED",
                     "RENDERED", "AWAITING_USER", "WRITE_BACK", "ACTION_GATED",
                     "EXECUTED", "REMEMBERED", "CLOSED"}
REQUIRED_HTML = ("qafiya_before.html", "qafiya_after.html", "memory_inspection.html")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output" / "cp1"
    if not out.exists():
        _fail(f"no CP1 output at {out}; run experiments/e2e_journey.py first")

    summary = json.loads((out / "summary.json").read_text())
    session_id = summary["session_id"]

    # --- Q3 recomputed from raw data.jsonl (never trusted from the summary) ---
    records = _read_jsonl(out / "stores" / "qafiya" / "datasets" / "expenses" / "data.jsonl")
    q3 = round(sum(r["amount"] for r in records if r["period"] == "Q3"), 2)
    if q3 != EXPECTED_Q3:
        _fail(f"Q3 recomputed {q3} != {EXPECTED_Q3}")
    edited = next((r for r in records if r["id"] == "r_051"), None)
    if edited != EXPECTED_EDIT:
        _fail(f"r_051 mismatch: {edited}")

    # --- audit chain + sequences (recomputed from raw history.jsonl) ---------
    audit_dir = out / "stores" / "shell_audit" / "datasets" / "shell_audit"
    ok, detail = _chain.verify(audit_dir / "history.jsonl")
    if not ok:
        _fail(f"shell_audit chain broken: {detail}")
    events = _read_jsonl(audit_dir / "data.jsonl")
    session_events = sorted((e for e in events if e["session_id"] == session_id),
                              key=lambda e: e["sequence"])
    seqs = [e["sequence"] for e in session_events]
    if seqs != list(range(1, len(seqs) + 1)):
        _fail(f"non-monotonic sequence: {seqs}")
    states = {e["state"] for e in session_events}
    missing_states = REQUIRED_STATES - states
    if missing_states:
        _fail(f"missing kernel states in audit: {sorted(missing_states)}")

    # --- successor id: audit graph must match L5's models dataset -------------
    successors = [(e["id"], e["successor_ref"]) for e in session_events
                    if e.get("successor_ref")]
    if not successors:
        _fail("no successor_ref recorded on any audit event")
    l5_models = _read_jsonl(out / "stores" / "l5" / "datasets" / "models" / "data.jsonl")
    by_id = {r["id"]: r for r in l5_models}
    recorded_successor = successors[-1][1]
    if recorded_successor not in by_id:
        _fail(f"successor {recorded_successor} not present in L5 models")
    succ_rec = by_id[recorded_successor]
    if succ_rec["status"] != "active":
        _fail(f"successor {recorded_successor} is not active (status={succ_rec['status']})")
    # Find the allocated id: the retired record whose superseded_by points at the successor.
    allocated = next((r["id"] for r in l5_models
                        if r.get("superseded_by") == recorded_successor), None)
    if allocated is None:
        _fail(f"no retired record supersedes to {recorded_successor}")
    if by_id[allocated]["status"] != "retired":
        _fail(f"allocated id {allocated} is not retired")
    if summary["refs"]["connection_allocated"] != allocated:
        _fail(f"summary allocated {summary['refs']['connection_allocated']} != {allocated}")
    if summary["refs"]["connection_successor"] != recorded_successor:
        _fail("summary successor does not match the audit graph")
    l5_ok, l5_detail = _chain.verify(out / "stores" / "l5" / "datasets" / "models" /
                                       "history.jsonl")
    if not l5_ok:
        _fail(f"L5 models chain broken: {l5_detail}")

    # --- route: declared-vs-metered must stay distinct on a dry-run -----------
    route = json.loads((out / "route_presentation.json").read_text())
    if route["outcome"] not in ("planned", "answered", "escalated", "refused"):
        _fail(f"unknown route outcome {route['outcome']!r}")
    if route["outcome"] == "planned" and route["metered"] is not False:
        _fail("a dry-run 'planned' route must NOT be metered (declared != actual)")
    if route["actual_metered_cost_usd"] is not None and route["outcome"] == "planned":
        _fail("dry-run produced an actual metered cost — impossible without a live call")

    # --- action outcome + audit-note file -------------------------------------
    action = json.loads((out / "action_record.json").read_text())
    if action["outcome"]["status"] != "success":
        _fail(f"action not successful: {action['outcome']}")
    if action["reversibility_class"] != "EXACT":
        _fail(f"file.create should be EXACT, got {action['reversibility_class']}")
    note_file = out / "stores" / "action" / "files" / "audit" / "q3-expense-edit-cp1.txt"
    if not note_file.exists():
        _fail(f"audit note file missing: {note_file}")
    if recorded_successor not in note_file.read_text():
        _fail("audit note does not mention the successor id")

    # --- memory chain (all L4 datasets) ---------------------------------------
    for ds in ("session_log", "preference_store", "longterm_notes",
                 "correction_log", "deletion_log"):
        mok, mdetail = _chain.verify(out / "stores" / "memory" / "datasets" / ds /
                                       "history.jsonl")
        if not mok:
            _fail(f"L4 {ds} chain broken: {mdetail}")

    # --- HTML renders present and free of UNRESOLVED --------------------------
    for name in REQUIRED_HTML:
        p = out / name
        if not p.exists():
            _fail(f"missing render: {name}")
        text = p.read_text()
        if "UNRESOLVED" in text:
            _fail(f"{name} contains UNRESOLVED bindings")
        if '<meta charset="utf-8">' not in text:
            _fail(f"{name} missing charset meta")

    # --- secret hygiene: sentinel VALUE appears in NO file under stores/ ------
    leaks = []
    for dirpath, _, files in os.walk(out / "stores"):
        for fn in files:
            p = Path(dirpath) / fn
            try:
                if SECRET_VALUE in p.read_text(encoding="utf-8"):
                    leaks.append(str(p))
            except (UnicodeDecodeError, OSError):
                continue
    if leaks:
        _fail(f"secret VALUE leaked into: {leaks[:3]}")

    # --- summary.json internal consistency ------------------------------------
    if summary["status"] != "PASS":
        _fail(f"summary status {summary['status']!r} != PASS")
    if summary["values"]["q3_total_recomputed_from_raw"] != EXPECTED_Q3:
        _fail("summary Q3 does not match the recomputed value")
    if summary["audit"]["chain_ok"] is not True:
        _fail("summary reports audit chain not ok")

    result = {
        "status": "PASS",
        "python": sys.version.split()[0],
        "session_id": session_id,
        "audit_events": len(session_events),
        "kernel_states_covered": sorted(states),
        "sequence_monotonic": True,
        "q3_total_recomputed_from_raw": q3,
        "edited_record": edited,
        "connection_allocated": allocated,
        "connection_successor": recorded_successor,
        "successor_active": True,
        "l5_models_chain_ok": True,
        "shell_audit_chain_ok": True,
        "route_outcome": route["outcome"],
        "route_metered": route["metered"],
        "declared_cost_usd": route["declared_cost_usd"],
        "actual_metered_cost_usd": route["actual_metered_cost_usd"],
        "action_status": action["outcome"]["status"],
        "action_reversibility_class": action["reversibility_class"],
        "memory_chains_ok": True,
        "html_renders_clean": list(REQUIRED_HTML),
        "secret_value_absent": True,
        "summary_checks_passed": summary["checks_passed"],
    }
    (HERE / "shell-spine-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
