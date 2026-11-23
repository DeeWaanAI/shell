#!/usr/bin/env python3
"""CP3 master manifest builder — pin the vendored L3/L5 snapshot + every
experiment's frozen inputs in one integrity artifact.

Per the monitor's CP2 clearance answer 1, the manifest records BOTH:

* a per-file sha256 list of the frozen L3/L5 vendor snapshot
  (``shell/vendor/SNAPSHOT_SHA256.json``), so a reviewer can prove which exact
  layer versions the frozen experiments ran against; and
* each experiment's own ``MANIFEST.json`` (frozen inputs + run.py + spine.py),
  so a reviewer can re-run every experiment from its frozen artifacts.

Run under Python 3.12:

    python3.12 experiments/cp3/build_manifest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # experiments/cp3
EXPERIMENTS = HERE.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from shell import _bootstrap  # noqa: E402

EXPERIMENT_DIRS = [
    ("E1", "e1_journey"),
    ("E2", "e2_auditability"),
    ("E3", "e3_routing_cost"),
    ("E4", "e4_connection_governance"),
    ("E5", "e5_shell_limits"),
    ("E6", "e6_realistic_demo"),
]


def main() -> int:
    _common.pin_environment()
    # Verify the vendor snapshot integrity first — the whole CP3 freeze depends
    # on the imported L3/L5 code matching its sha256 manifest.
    snapshot_files = _bootstrap.verify_snapshot()
    snapshot_manifest = json.loads(_bootstrap.SNAPSHOT_MANIFEST.read_text())

    experiments = {}
    real_data_provenance = None
    for label, dirname in EXPERIMENT_DIRS:
        exp_root = HERE / dirname
        man_path = exp_root / "MANIFEST.json"
        if not man_path.exists():
            raise SystemExit(f"{label}: missing MANIFEST.json — run "
                               f"`python3.12 experiments/cp3/{dirname}/run.py --freeze` first")
        man = json.loads(man_path.read_text())
        # Re-verify every experiment manifest against its frozen files.
        count = _common.verify_manifest(exp_root)
        experiments[label] = {
            "dir": dirname,
            "artifact": man["artifact"],
            "algorithm": man["algorithm"],
            "file_count": man["file_count"],
            "verified_now": count,
            "files": man["files"],
        }
        # Surface E6's real-open-data provenance + OGL attribution at the top level.
        if man.get("dataset_provenance"):
            real_data_provenance = {
                "experiment": label,
                "dataset_provenance": man["dataset_provenance"],
                "model_provenance": man.get("model_provenance"),
                "attribution_required_in_paper": man.get("attribution_required_in_paper"),
            }

    # CP3 addendum (20:52 clearance): pin a sha256 of every LIVE L5 dataset file
    # the experiments actually consume, so drift in the live L5 tree is detected at
    # re-run. The vendored CODE snapshot is the primary pin; this is the
    # belt-and-braces pin on the live frozen datasets (themselves frozen by
    # model-routing v1.1). Consumed = the five schema.json (copied by every
    # scaffold) + the data.jsonl for models (E6 filters the ollama connection),
    # policy/rules/capabilities (seeded read-only). decision_log/data.jsonl is
    # never read (scaffolded empty), so it is not pinned.
    live_l5 = _bootstrap.L5_FROZEN_DATASETS_ROOT
    consumed = []
    for ds in ("models", "capabilities", "policy", "rules", "decision_log"):
        consumed.append(live_l5 / "datasets" / ds / "schema.json")
    for ds in ("models", "capabilities", "policy", "rules"):
        consumed.append(live_l5 / "datasets" / ds / "data.jsonl")
    live_l5_pins = {}
    for p in consumed:
        if not p.is_file():
            raise SystemExit(f"live L5 dataset file missing: {p}")
        live_l5_pins[str(p.relative_to(live_l5.parent))] = _common.sha256_file(p)

    manifest = {
        "artifact": "L6 CP3 frozen experiments E1-E6 + vendored L3/L5 snapshot",
        "algorithm": "sha256",
        "python_pin": _bootstrap.PINNED_PY,
        "vendor_snapshot": {
            "path": "shell/vendor/",
            "source_trees": snapshot_manifest["source_trees"],
            "excluded": snapshot_manifest["excluded"],
            "file_count": snapshot_manifest["file_count"],
            "files": snapshot_manifest["files"],
        },
        "live_l5_dataset_pins": {
            "note": ("sha256 of every live L5 dataset file the experiments consume; "
                       "frozen by model-routing v1.1, pinned here as a drift check"),
            "root": str(live_l5),
            "file_count": len(live_l5_pins),
            "files": live_l5_pins,
        },
        "experiments": experiments,
        "real_open_data": real_data_provenance,
        "regressions_that_must_stay_green": [
            "preflight/spine.py (12/12, Q3 10481.96)",
            "experiments/shell_spine.py (CP1, 36 checks)",
            "experiments/gates_spine.py (CP2, 8/8 gates)",
        ],
    }
    out = HERE / "cp3_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    total_files = (manifest["vendor_snapshot"]["file_count"]
                     + sum(e["file_count"] for e in experiments.values()))
    print(json.dumps({
        "cp3_manifest": str(out),
        "snapshot_files_verified": snapshot_files,
        "experiments": {k: v["verified_now"] for k, v in experiments.items()},
        "total_pinned_files": total_files,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
