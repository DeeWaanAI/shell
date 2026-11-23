#!/usr/bin/env python3
"""E1 — end-to-end user journey (brief §7.2 E1).

Reuses the ONE authoritative journey implementation (``experiments/e2e_journey.py``)
rather than duplicating it, per the monitor's CP2 clearance answer 3 ("reuse the
implementation … but freeze dedicated E1 inputs + expected outputs with a
manifest + spine"). The frozen inputs live in ``inputs/spec.json``; the spine
cross-checks the run's raw artifacts against that spec.

Run under Python 3.12:

    python3.12 experiments/cp3/e1_journey/run.py [--freeze]

``--freeze`` rewrites ``MANIFEST.json`` over the frozen inputs + scripts. Do NOT
freeze while the run is in progress; freeze only after a clean run.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # e1_journey/
CP3 = HERE.parent                                    # experiments/cp3
EXPERIMENTS = CP3.parent                             # experiments/
L6 = EXPERIMENTS.parent                              # 06-shell/
for p in (str(L6), str(EXPERIMENTS), str(CP3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
import e2e_journey  # noqa: E402  (the ONE authoritative journey implementation)


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    summary = e2e_journey.run(out)
    # Mirror the run summary next to the frozen inputs so the spine can
    # cross-check the raw artifacts against inputs/spec.json without trusting
    # this file.
    _common.write_json(HERE / "output" / "run-summary.json", summary)
    print(f"E1 run complete: {summary['checks_passed']} checks, "
            f"session {summary['session_id']}, output {out}")

    if "--freeze" in sys.argv:
        manifest = _common.freeze_manifest(
            HERE, artifact_label="E1 end-to-end user journey (frozen inputs + scripts)")
        print(f"E1 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
