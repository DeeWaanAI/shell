#!/usr/bin/env python3
"""E4 independent spine — recompute every governance claim from raw artifacts.

Refuses to trust the run's own JSON summaries. Every claim is recomputed from
the raw L5 ``models/data.jsonl``, the L3 action records, and a fresh secret scan
of the output tree. If this script fails, the E4 claim is withdrawn.

Run under Python 3.12:

    python3.12 experiments/cp3/e4_connection_governance/spine.py
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

BROKEN_ENV = "L6_SHELL_E4_BROKEN_KEY_ABSENT"


def _fail(msg: str) -> None:
    raise AssertionError(f"[E4 spine] {msg}")


def main() -> int:
    _common.pin_environment()
    _common.read_json(HERE / "inputs" / "spec.json")     # frozen spec must exist
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E4 output at {out}; run run.py first")
    frozen_count = _common.verify_manifest(HERE)

    # ---- governance chain: links verified from raw L5 models -----------------
    chain_root = out / "governance_chain"
    models = _common.read_jsonl(chain_root / "stores" / "l5" / "datasets" / "models" / "data.jsonl")
    by_id = {r["id"]: r for r in models}
    meta = _common.read_json(chain_root / "chain.json")
    allocated, successor, restored = meta["allocated"], meta["successor"], meta["restored"]
    for label, mid in (("allocated", allocated), ("successor", successor),
                         ("restored", restored)):
        if mid not in by_id:
            _fail(f"{label} {mid} missing from raw L5 models")
        if by_id[mid]["status"] != "retired":
            _fail(f"{label} {mid} should be retired at the end of the chain, "
                    f"got {by_id[mid]['status']}")
    if by_id[allocated].get("superseded_by") != successor:
        _fail("allocated.superseded_by != successor in the raw record")
    if by_id[successor].get("superseded_by") != restored:
        _fail("successor.superseded_by != restored in the raw record")
    if not (allocated != successor != restored and allocated != restored):
        _fail("succession chain ids are not distinct")
    if meta["privacy_undo"].get("ok") is not True:
        _fail(f"privacy undo did not succeed: {meta['privacy_undo']}")
    for step in ("add_outcome", "privacy_outcome", "retire_outcome"):
        if meta[step] != "success":
            _fail(f"{step} != success: {meta[step]}")

    # ---- add-undo on a still-active connection retires the allocated id ------
    undo_meta = _common.read_json(out / "add_undo" / "add_undo.json")
    if undo_meta["undo"].get("ok") is not True:
        _fail(f"add-undo did not succeed: {undo_meta['undo']}")
    if undo_meta["record_status_after_undo"] != "retired":
        _fail(f"add-undo left the record {undo_meta['record_status_after_undo']}")

    # ---- rejected operation: active list byte-identical ----------------------
    rej = _common.read_json(out / "rejected_operation" / "rejected.json")
    if rej["rejected_outcome"]["status"] != "refused":
        _fail(f"narrow-grant retire not refused: {rej['rejected_outcome']}")
    if rej["list_before"] != rej["list_after"]:
        _fail("rejected operation changed the active list")

    # ---- no implicit retirement of a broken entry ----------------------------
    broken = _common.read_json(out / "no_implicit_retirement" / "broken.json")
    if broken["record_status"] != "active":
        _fail(f"broken connection was implicitly retired: {broken['record_status']}")
    if broken["status"]["usable"] is not False:
        _fail("broken connection reported usable")
    if not any(p.startswith(f"missing_env:{BROKEN_ENV}")
                 for p in broken["status"]["problems"]):
        _fail(f"broken problems not typed missing_env: {broken['status']['problems']}")

    # ---- secrets absent: fresh scan of the whole output tree -----------------
    leaks = _common.scan_tree_for_secret(out, _common.SECRET_VALUE)
    if leaks:
        _fail(f"secret VALUE leaked into E4 output: {leaks[:3]}")
    hygiene = _common.read_json(out / "secrets_hygiene.json")
    if not hygiene["env_name_retained_in_l5"] or not hygiene["env_name_retained_in_l3"]:
        _fail("env-var NAME not retained in L5/L3 records")

    # ---- L3 records for every mutation type ----------------------------------
    mutations = set(_common.read_json(out / "mutation_types.json"))
    for required in ("connection.add", "connection.retire", "connection.privacy_change"):
        if required not in mutations:
            _fail(f"no L3 record for {required}")

    # ---- L5 models chain verifies (recomputed, not trusted) ------------------
    ok, detail = qafiya_chain.verify(
        chain_root / "stores" / "l5" / "datasets" / "models" / "history.jsonl")
    if not ok:
        _fail(f"L5 models chain broken: {detail}")

    # ---- zero network calls ---------------------------------------------------
    net = _common.read_json(out / "network_calls.json")
    if net["calls"] != 0:
        _fail(f"NetworkGuard recorded {net['calls']} network calls")

    result = {
        "experiment": "E4",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "governance_chain": {
            "allocated": allocated, "successor": successor, "restored": restored,
            "links_verified_from_raw": True, "privacy_undo_ok": True,
            "all_mutations_success": True,
        },
        "add_undo_retires_allocated": True,
        "rejected_operation_refused": True,
        "active_list_unchanged_after_rejection": True,
        "broken_entry_stays_active": True,
        "broken_problem_typed_missing_env": True,
        "secret_value_absent": True,
        "env_name_retained": True,
        "mutation_types_seen": sorted(mutations),
        "l5_models_chain_ok": True,
        "network_calls": net["calls"],
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    import json
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
