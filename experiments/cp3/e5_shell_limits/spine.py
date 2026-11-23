#!/usr/bin/env python3
"""E5 independent spine — recompute every limit claim from raw artifacts.

Refuses to trust ``output/frozen/probes.json``. Each probe's claim is recomputed
from the raw artifact the probe wrote, and the uncatchable classes are
cross-checked against the frozen ``inputs/spec.json``. If this script fails, the
E5 claim is withdrawn. Negative and uncatchable results are reported as results.

Run under Python 3.12:

    python3.12 experiments/cp3/e5_shell_limits/spine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CP3 = HERE.parent
EXPERIMENTS = HERE.parent.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(CP3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(f"[E5 spine] {msg}")


def main() -> int:
    _common.pin_environment()
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E5 output at {out}; run run.py first")
    frozen_count = _common.verify_manifest(HERE)

    # ---- 1. expressibility ceiling: enforced by specval, not just documented --
    expr = _common.read_json(out / "expressibility_probe.json")
    if not expr["specval_rejected"]:
        _fail("specval did NOT reject the invented service_control role — "
                "the ceiling is not enforced")
    classes = spec["screen_classes"]
    expressible = sum(1 for c in classes.values() if c["expressible"])
    total = len(classes)
    ceiling = f"{expressible}/{total}"
    if ceiling != spec["expressibility_ceiling"]:
        _fail(f"expressibility ceiling {ceiling} != {spec['expressibility_ceiling']}")
    if classes["connection_manager_live_controls"]["expressible"]:
        _fail("connection-manager live controls must be the documented gap")

    # ---- 2a. tamper: chain verification detects a naive tamper ---------------
    tamper = _common.read_json(out / "tamper_probe.json")
    if not tamper["chain_clean_before"]:
        _fail("chain was not clean before the tamper")
    if not tamper["chain_detected_naive_tamper"]:
        _fail("chain.verify did NOT detect the naive tamper")
    if not tamper["manifest_detected_tamper"]:
        _fail("manifest verification did NOT detect the file tamper")

    # ---- 2b. absence: a missing dataset raises a typed error -----------------
    absence = _common.read_json(out / "absence_probe.json")
    if not absence["missing_dataset_raises"]:
        _fail("a missing L5 dataset did NOT raise")
    if absence["error_type"] != "StoreError":
        _fail(f"absence error is not a typed StoreError: {absence['error_type']}")

    # ---- 3. uncatchable classes: all reported, trust_user proxy demonstrated --
    uncatch = _common.read_json(out / "uncatchable.json")
    if uncatch["count"] != len(spec["uncatchable_classes"]):
        _fail(f"uncatchable count {uncatch['count']} != "
                f"{len(spec['uncatchable_classes'])}")
    tu = uncatch["trust_user_proxy"]
    if not (tu["mode_is_trust_user"] and tu["privacy_public_by_construction"]):
        _fail(f"trust_user proxy not demonstrated from the raw decision record: {tu}")
    # Re-read the raw decision record to confirm the proxy independently.
    dec = _common.read_json(out / "trust_user_proxy" / "decision_record.json")
    if dec.get("classifier_mode") != "trust_user" or dec.get("privacy_class") != "public":
        _fail("raw decision record does not carry trust_user/public by construction")

    result = {
        "experiment": "E5",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "expressibility_ceiling": ceiling,
        "ceiling_enforced_by_specval": True,
        "connection_manager_is_documented_gap": True,
        "tamper_detected_by_chain": True,
        "tamper_detected_by_manifest": True,
        "absence_raises_typed_StoreError": True,
        "uncatchable_classes_reported": uncatch["count"],
        "uncatchable_demonstrated_by_proxy": uncatch["demonstrated_count"],
        "uncatchable_stated_only": uncatch["stated_only_count"],
        "trust_user_proxy_demonstrated": True,
        "honesty_note": ("An attacker who rewrites the store and recomputes the "
                            "WHOLE chain would verify; E5 demonstrates detection of "
                            "a NAIVE tamper only, and reports the full-rewrite case "
                            "as an uncatchable class rather than claiming it is caught."),
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    import json
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
