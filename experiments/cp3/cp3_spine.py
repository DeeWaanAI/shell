#!/usr/bin/env python3
"""CP3 master spine — run every experiment spine + every regression, aggregate.

This is the single command a reviewer runs to confirm the whole CP3 freeze is
green. It invokes, as subprocesses under the pinned interpreter:

* the vendor-snapshot integrity check (``shell._bootstrap.verify_snapshot``);
* each experiment's independent spine (E1–E5), which recomputes its headline
  numbers from raw artifacts and verifies its own frozen manifest;
* the three regressions that must stay green throughout:
  ``preflight/spine.py`` (12/12, Q3 10481.96), CP1 ``experiments/shell_spine.py``
  (36 checks), CP2 ``experiments/gates_spine.py`` (8/8 gates).

If ANY spine fails, the corresponding claim is withdrawn and this script exits
non-zero. Run under Python 3.12:

    python3.12 experiments/cp3/cp3_spine.py
"""
from __future__ import annotations

import json
import subprocess
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

PY = sys.executable                                # the pinned 3.12 interpreter

EXPERIMENT_SPINES = [
    ("E1", HERE / "e1_journey" / "spine.py"),
    ("E2", HERE / "e2_auditability" / "spine.py"),
    ("E3", HERE / "e3_routing_cost" / "spine.py"),
    ("E4", HERE / "e4_connection_governance" / "spine.py"),
    ("E5", HERE / "e5_shell_limits" / "spine.py"),
    # E6's spine recomputes from the FROZEN transcript + dataset — it makes NO
    # model call and NO network call, so the master spine stays deterministic.
    ("E6", HERE / "e6_realistic_demo" / "spine.py"),
]

REGRESSIONS = [
    ("preflight", L6 / "preflight" / "spine.py"),
    ("cp1_shell_spine", EXPERIMENTS / "shell_spine.py"),
    ("cp2_gates_spine", EXPERIMENTS / "gates_spine.py"),
]

# Layer-wide hygiene gates, reported separately from the three spine regressions
# so the regression count (and the paper's "three regressions") stays exact.
LAYER_CHECKS = [
    # Every standalone .html this layer writes must carry <meta charset="utf-8">
    # and decode as UTF-8 (fix-html-charset-05-nov-2026-1822.md).
    ("html_charset", HERE / "check_html_charset.py"),
]


def _run(label: str, script: Path) -> dict:
    proc = subprocess.run([PY, str(script)], capture_output=True, text=True,
                            cwd=str(L6))
    ok = proc.returncode == 0
    # Each spine writes a JSON result; pull the status line out of stdout when
    # present, but never TRUST it — the return code is the authoritative signal.
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-1:] or [""]
    return {"label": label, "script": str(script.relative_to(L6)),
              "returncode": proc.returncode, "ok": ok,
              "last_line": tail[0][:200],
              "stderr_tail": (proc.stderr or "").strip()[-300:]}


def main() -> int:
    _common.pin_environment()

    # 0. Vendor snapshot integrity (in-process; raises on drift).
    snapshot_files = _bootstrap.verify_snapshot()

    results = {"snapshot_files_verified": snapshot_files,
                 "experiments": [], "regressions": [], "layer_checks": []}
    for label, script in EXPERIMENT_SPINES:
        results["experiments"].append(_run(label, script))
    for label, script in REGRESSIONS:
        results["regressions"].append(_run(label, script))
    for label, script in LAYER_CHECKS:
        results["layer_checks"].append(_run(label, script))

    all_ok = (all(r["ok"] for r in results["experiments"])
                and all(r["ok"] for r in results["regressions"])
                and all(r["ok"] for r in results["layer_checks"]))
    results["status"] = "PASS" if all_ok else "FAIL"
    results["python"] = sys.version.split()[0]

    _common.write_json(HERE / "cp3-spine-result.json", results)
    print(json.dumps({
        "status": results["status"],
        "snapshot_files_verified": snapshot_files,
        "experiments": {r["label"]: "PASS" if r["ok"] else f"FAIL({r['returncode']})"
                          for r in results["experiments"]},
        "regressions": {r["label"]: "PASS" if r["ok"] else f"FAIL({r['returncode']})"
                          for r in results["regressions"]},
        "layer_checks": {r["label"]: "PASS" if r["ok"] else f"FAIL({r['returncode']})"
                          for r in results["layer_checks"]},
    }, indent=2))
    if not all_ok:
        for r in (results["experiments"] + results["regressions"]
                    + results["layer_checks"]):
            if not r["ok"]:
                print(f"\n--- {r['label']} FAILED ---\n{r['stderr_tail']}",
                        file=sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
