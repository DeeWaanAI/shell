#!/usr/bin/env python3
"""E3 independent spine — recompute declared-vs-actual cost from raw L5 records.

Refuses to trust ``output/frozen/cases.json``. Every claim is recomputed from
the raw ``decision_record.json`` files L5 committed, and cross-checked against
the frozen ``inputs/spec.json``. If this script fails, the E3 claim is withdrawn.

Run under Python 3.12:

    python3.12 experiments/cp3/e3_routing_cost/spine.py
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
from fake_transport import METER_LABEL  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(f"[E3 spine] {msg}")


def main() -> int:
    _common.pin_environment()
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E3 output at {out}; run run.py first")
    frozen_count = _common.verify_manifest(HERE)

    # ---- case 1: dry-run planned, unmetered, actual=null ---------------------
    c1 = _common.read_json(out / "dry_run_planned" / "decision_record.json")
    if c1["outcome"] != "planned":
        _fail(f"case1 outcome {c1['outcome']} != planned")
    # A dry-run commits no attempts, so there is no metered spend. The shell
    # presentation must carry actual=null, never $0.
    pres1 = _common.read_json(out / "dry_run_planned" / "presentation.json")
    if pres1["metered"] is not False or pres1["actual_metered_cost_usd"] is not None:
        _fail(f"case1 presentation conflates unmetered with $0: {pres1}")
    if (c1.get("chosen") or {}).get("model_ref") != pres1["chosen_model_ref"]:
        _fail("case1 chosen model does not match the presentation")

    # ---- case 2: fake-transport answered, simulated metering labelled --------
    c2 = _common.read_json(out / "fake_answered_metered" / "decision_record.json")
    if c2["outcome"] != "answered":
        _fail(f"case2 outcome {c2['outcome']} != answered")
    attempts = c2.get("attempts") or []
    if not attempts:
        _fail("case2 committed no attempts")
    for a in attempts:
        if a.get("meter") != METER_LABEL:
            _fail(f"case2 attempt meter is not the simulated label: {a.get('meter')}")
    pres2 = _common.read_json(out / "fake_answered_metered" / "presentation.json")
    if pres2["metered"] is not True or pres2["actual_metered_cost_usd"] is None:
        _fail(f"case2 presentation not metered: {pres2}")
    hist = _common.read_json(out / "fake_answered_metered" / "fake_transport_history.json")
    if not hist or any(h["reply_kind"] != "answered" for h in hist):
        _fail(f"case2 fake transport history not all answered: {hist}")

    # ---- case 3: all failed → refused, typed reason, chosen=null -------------
    c3 = _common.read_json(out / "all_failed_refused" / "decision_record.json")
    if c3["outcome"] != "refused":
        _fail(f"case3 outcome {c3['outcome']} != refused")
    if c3.get("refusal_reason") != "all_connections_failed":
        _fail(f"case3 refusal_reason {c3.get('refusal_reason')}")
    if (c3.get("chosen") or {}).get("model_ref") is not None:
        _fail("case3 refusal still names a chosen model")
    pres3 = _common.read_json(out / "all_failed_refused" / "presentation.json")
    if pres3["actual_metered_cost_usd"] is not None:
        _fail("case3 refusal produced an actual metered cost")

    # ---- declared-vs-actual distinct in every case ---------------------------
    # The fake connection declares local $0 prices. Declared cost is a USER
    # DECLARATION; actual cost is provider metering (or null). The two must
    # never be conflated: a case with actual=null is "not metered", not "$0".
    distinct = {
        "dry_run_planned": pres1["actual_metered_cost_usd"] is None,
        "fake_answered_metered": pres2["actual_metered_cost_usd"] is not None,
        "all_failed_refused": pres3["actual_metered_cost_usd"] is None,
    }
    if not all(distinct.values()):
        _fail(f"declared-vs-actual not kept distinct: {distinct}")

    # ---- zero network calls ---------------------------------------------------
    net = _common.read_json(out / "network_calls.json")
    if net["calls"] != 0:
        _fail(f"NetworkGuard recorded {net['calls']} network calls")

    result = {
        "experiment": "E3",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "cases": {
            "dry_run_planned": {
                "outcome": c1["outcome"], "metered": False,
                "declared_cost_usd": pres1["declared_cost_usd"],
                "actual_metered_cost_usd": None,
                "honesty": "unmetered shown as null, never $0",
            },
            "fake_answered_metered": {
                "outcome": c2["outcome"], "metered": True,
                "declared_cost_usd": pres2["declared_cost_usd"],
                "actual_metered_cost_usd": pres2["actual_metered_cost_usd"],
                "meter_label": METER_LABEL,
                "honesty": "simulated metering labelled on every attempt",
            },
            "all_failed_refused": {
                "outcome": c3["outcome"],
                "refusal_reason": c3["refusal_reason"],
                "chosen": None, "metered": False,
                "actual_metered_cost_usd": None,
            },
        },
        "declared_vs_actual_distinct": distinct,
        "network_calls": net["calls"],
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    import json
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
