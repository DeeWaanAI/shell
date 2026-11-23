#!/usr/bin/env python3
"""E3 — routing and cost audit (brief §7.2 E3; CP2 clearance answer 2).

Three frozen routing cases recomputed from the raw L5 decision records:
dry-run planned (unmetered, actual=null), fake-transport answered (metered,
simulated label on every attempt), and all-failed refused (typed refusal,
chosen=null). Declared-vs-actual cost is kept distinct in every case.

No live or paid provider call. The local fake transport runs under a
NetworkGuard that asserts zero socket/urlopen calls.

Run under Python 3.12:

    python3.12 experiments/cp3/e3_routing_cost/run.py [--freeze]
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
from shell.connections import ShellConnections  # noqa: E402
from shell.routing import ShellRouter  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

from health import Health  # noqa: E402
from store import Store as L5Store  # noqa: E402 (vendored snapshot)

import fake_transport as FT  # noqa: E402
from fake_transport import (ANSWERED, CALL_FAILED_CONNECTION, METER_LABEL,  # noqa: E402
                              FakeTransport, NetworkGuard)

FAKE_CONFIG = {
    "label": "E3 fake local model",
    "connector": "openai_compatible",
    "base_url": _common.FAKE_ENDPOINT,
    "model": "e3-fake-model",
    "locus": "local",
    "privacy_class": "private",
    "prices": {"input": 0.0, "output": 0.0},     # user-declared local $0
    "key_env": _common.SECRET_ENV,
}
PROMPT = "E3 routing audit: what is the Q3 expense total?"


def _declare(case_root: Path) -> tuple[str, ShellConnections]:
    """Scaffold a per-case L5 store and declare the fake connection THROUGH L3."""
    l5root = case_root / "stores" / "l5"
    l3root = case_root / "stores" / "l3"
    _common.scaffold_l5_store(l5root)
    conns = ShellConnections(l5_root=l5root, l3_root=l3root,
                               frozen_l5_root=_common.FROZEN_L5_DATASETS,
                               user_id="e3", agent_id="l6-shell-e3")
    res = conns.add(FAKE_CONFIG, intent_verbatim="E3: declare fake local connection",
                      session_id="s_e3")
    if res.action_outcome != "success":
        raise RuntimeError(f"E3 setup: connection.add failed: {res.detail}")
    return res.allocated_id, conns


def _route(case_root: Path, mdl_id: str, conns: ShellConnections, *,
             dry_run: bool, transport=None, run_label: str) -> dict:
    router = ShellRouter(L5Store(case_root / "stores" / "l5"),
                            health=Health(), policy_label=_common.POLICY_LABEL)
    if transport is not None:
        # Per-instance attribute swap on the Router the shell constructed;
        # the vendored L5 code is never edited.
        router._router.transport = transport
    pres = router.route({"text": PROMPT, "request_id": f"req_{run_label}"},
                           dry_run=dry_run, run=run_label,
                           allow_live_call=not dry_run)
    dec = L5Store(case_root / "stores" / "l5").get("decision_log", pres.decision_ref)
    _common.write_json(case_root / "presentation.json", pres.__dict__)
    _common.write_json(case_root / "decision_record.json", dec)
    return {"presentation": pres, "decision": dec}


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    os.environ[_common.SECRET_ENV] = _common.SECRET_VALUE
    net = NetworkGuard()
    cases = {}
    try:
        with net:
            # ---- case 1: dry-run planned -------------------------------------
            c1 = out / "dry_run_planned"
            mdl1, conns1 = _declare(c1)
            r1 = _route(c1, mdl1, conns1, dry_run=True, run_label="e3-dry")
            cases["dry_run_planned"] = {
                "model_ref": mdl1,
                "outcome": r1["presentation"].outcome,
                "metered": r1["presentation"].metered,
                "declared_cost_usd": r1["presentation"].declared_cost_usd,
                "actual_metered_cost_usd": r1["presentation"].actual_metered_cost_usd,
                "decision_ref": r1["presentation"].decision_ref,
            }

            # ---- case 2: fake-transport answered (simulated metering) --------
            c2 = out / "fake_answered_metered"
            mdl2, conns2 = _declare(c2)
            fake = FakeTransport(script={mdl2: ANSWERED}, default=ANSWERED)
            r2 = _route(c2, mdl2, conns2, dry_run=False, transport=fake,
                           run_label="e3-fake")
            _common.write_json(c2 / "fake_transport_history.json", fake.history)
            cases["fake_answered_metered"] = {
                "model_ref": mdl2,
                "outcome": r2["presentation"].outcome,
                "metered": r2["presentation"].metered,
                "declared_cost_usd": r2["presentation"].declared_cost_usd,
                "actual_metered_cost_usd": r2["presentation"].actual_metered_cost_usd,
                "meter_label": METER_LABEL,
                "simulated_metering_on_every_attempt":
                    all(a.get("meter") == METER_LABEL
                          for a in (r2["decision"].get("attempts") or [])),
                "fake_calls": len(fake.history),
                "decision_ref": r2["presentation"].decision_ref,
            }

            # ---- case 3: all fake calls fail → refused -----------------------
            c3 = out / "all_failed_refused"
            mdl3, conns3 = _declare(c3)
            failing = FakeTransport(default=CALL_FAILED_CONNECTION)
            r3 = _route(c3, mdl3, conns3, dry_run=False, transport=failing,
                           run_label="e3-fail")
            _common.write_json(c3 / "fake_transport_history.json", failing.history)
            cases["all_failed_refused"] = {
                "model_ref": mdl3,
                "outcome": r3["presentation"].outcome,
                "refusal_reason": r3["presentation"].refusal_reason,
                "chosen_model_ref": r3["presentation"].chosen_model_ref,
                "metered": r3["presentation"].metered,
                "actual_metered_cost_usd": r3["presentation"].actual_metered_cost_usd,
                "decision_ref": r3["presentation"].decision_ref,
            }
    finally:
        os.environ.pop(_common.SECRET_ENV, None)

    _common.write_json(out / "cases.json", cases)
    _common.write_json(out / "network_calls.json", {"calls": net.calls})
    print(json.dumps({"experiment": "E3", "cases": len(cases),
                         "network_calls": net.calls, "output": str(out)}, indent=2))

    if "--freeze" in sys.argv:
        manifest = _common.freeze_manifest(
            HERE, artifact_label="E3 routing and cost audit (frozen inputs + scripts)")
        print(f"E3 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
