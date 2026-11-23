#!/usr/bin/env python3
"""E4 — connection governance (brief §7.2 E4; CP2 clearance answer 4).

Purpose-built frozen fixtures exercising governance directly: the full
succession chain (add → privacy_change → undo → retire), a clean add-undo on a
still-active connection, a rejected operation under a narrow grant, a broken
entry that is NOT implicitly retired, and secrets-absent hygiene.

These are dedicated E4 fixtures — NOT a reuse of the e2e journey's mutation
ordering and NOT the ephemeral ``output/cp2/`` gate artifacts.

No live or paid provider call. The fake endpoint is a loopback URL with no
listener; a NetworkGuard asserts zero socket/urlopen calls.

Run under Python 3.12:

    python3.12 experiments/cp3/e4_connection_governance/run.py [--freeze]
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

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

from actionlayer.engine import ActionEngine  # noqa: E402
from actionlayer.gate import make_grant  # noqa: E402
from fake_transport import NetworkGuard  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402

BROKEN_ENV = "L6_SHELL_E4_BROKEN_KEY_ABSENT"
FAKE_CONFIG = {
    "label": "E4 fake local model",
    "connector": "openai_compatible",
    "base_url": _common.FAKE_ENDPOINT,
    "model": "e4-fake-model",
    "locus": "local",
    "privacy_class": "private",
    "prices": {"input": 0.0, "output": 0.0},
    "key_env": _common.SECRET_ENV,
}


def _new_conns(root: Path, *, agent: str = "l6-shell-e4") -> ShellConnections:
    l5root = root / "stores" / "l5"
    l3root = root / "stores" / "l3"
    _common.scaffold_l5_store(l5root)
    return ShellConnections(l5_root=l5root, l3_root=l3root,
                               frozen_l5_root=_common.FROZEN_L5_DATASETS,
                               user_id="e4", agent_id=agent)


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    os.environ[_common.SECRET_ENV] = _common.SECRET_VALUE
    os.environ.pop(BROKEN_ENV, None)
    net = NetworkGuard()
    try:
        with net:
            # ---- fixture 1: the full governance chain -------------------------
            chain_root = out / "governance_chain"
            conns = _new_conns(chain_root)
            add_res = conns.add(FAKE_CONFIG,
                                   intent_verbatim="E4: add fake connection",
                                   session_id="s_e4")
            allocated = add_res.allocated_id
            priv_res = conns.change_privacy(allocated, new_class="public",
                                               previous_class="private",
                                               intent_verbatim="E4: relax privacy",
                                               session_id="s_e4")
            successor = priv_res.successor_ref
            priv_undo = conns.engine.undo(priv_res.action_ref)
            restored = conns.ops.get_active_successor(successor)
            retire_res = conns.retire(restored, FAKE_CONFIG,
                                         intent_verbatim="E4: explicit retire",
                                         session_id="s_e4")
            _common.write_json(chain_root / "chain.json", {
                "allocated": allocated, "successor": successor, "restored": restored,
                "add_outcome": add_res.action_outcome,
                "privacy_outcome": priv_res.action_outcome,
                "privacy_undo": priv_undo,
                "retire_outcome": retire_res.action_outcome,
            })

            # ---- fixture 2: a clean add-undo on a still-active connection -----
            undo_root = out / "add_undo"
            conns_u = _new_conns(undo_root)
            add_u = conns_u.add(FAKE_CONFIG, intent_verbatim="E4: add then undo",
                                   session_id="s_e4_undo")
            alloc_u = add_u.allocated_id
            undo_u = conns_u.engine.undo(add_u.action_ref)
            rec_u = conns_u.store.get("models", alloc_u)
            _common.write_json(undo_root / "add_undo.json", {
                "allocated": alloc_u, "undo": undo_u,
                "record_status_after_undo": rec_u["status"] if rec_u else None,
            })

            # ---- fixture 3: rejected operation under a narrow grant -----------
            rej_root = out / "rejected_operation"
            conns_r = _new_conns(rej_root)
            add_r = conns_r.add(FAKE_CONFIG, intent_verbatim="E4: add for rejection test",
                                   session_id="s_e4_rej")
            alloc_r = add_r.allocated_id
            narrow_engine = ActionEngine(rej_root / "stores" / "l3_narrow",
                                            connection_ops=conns_r.ops)
            narrow_grant = narrow_engine.issue_grant(make_grant(
                user_id="e4", action_types=["connection.add"], target_pattern="mdl_*"))
            list_before = [r["id"] for r in conns_r.list_active()]
            rejected = narrow_engine.act(
                intent_verbatim="E4: retire without the retire grant",
                normalized={"action_type": "connection.retire",
                              "params": {"connection_id": alloc_r, "config": FAKE_CONFIG}},
                actor={"agent_id": "l6-shell-e4", "session_id": "s_e4_rej"},
                user_id="e4", grant_id=narrow_grant["_id"])
            list_after = [r["id"] for r in conns_r.list_active()]
            _common.write_json(rej_root / "rejected.json", {
                "rejected_outcome": rejected["outcome"],
                "list_before": list_before, "list_after": list_after,
                "list_unchanged": list_before == list_after,
            })

            # ---- fixture 4: no implicit retirement of a broken entry ----------
            broken_root = out / "no_implicit_retirement"
            conns_b = _new_conns(broken_root)
            broken_cfg = {**FAKE_CONFIG, "label": "E4 broken (no env)",
                             "model": "e4-broken-model", "key_env": BROKEN_ENV}
            broken_add = conns_b.add(broken_cfg,
                                         intent_verbatim="E4: declare a broken connection",
                                         session_id="s_e4_broken")
            broken_id = broken_add.allocated_id
            broken_status = conns_b.status(broken_id)
            broken_rec = conns_b.store.get("models", broken_id)
            _common.write_json(broken_root / "broken.json", {
                "broken_id": broken_id,
                "record_status": broken_rec["status"] if broken_rec else None,
                "status": broken_status,
            })

            # ---- fixture 5: secrets-absent hygiene ----------------------------
            hygiene = {
                "l5_leaks": _common.scan_tree_for_secret(
                    chain_root / "stores" / "l5", _common.SECRET_VALUE),
                "l3_leaks": _common.scan_tree_for_secret(
                    chain_root / "stores" / "l3", _common.SECRET_VALUE),
                "l3_narrow_leaks": _common.scan_tree_for_secret(
                    rej_root / "stores" / "l3_narrow", _common.SECRET_VALUE),
                "env_name_retained_in_l5":
                    _common.SECRET_ENV in json.dumps(
                        conns.store.records("models"), sort_keys=True),
                "env_name_retained_in_l3":
                    _common.SECRET_ENV in json.dumps(
                        conns.engine.records(), sort_keys=True),
            }
            _common.write_json(out / "secrets_hygiene.json", hygiene)

            # ---- L3 records for every mutation type ---------------------------
            mutation_types = [r["intent"]["normalized"]["action_type"]
                                 for r in conns.engine.records()]
            _common.write_json(out / "mutation_types.json", mutation_types)

            # ---- L5 models chain verifies -------------------------------------
            l5_ok, l5_detail = conns.store.verify_chain("models")
            _common.write_json(out / "l5_chain.json",
                                 {"ok": l5_ok, "detail": l5_detail})
    finally:
        os.environ.pop(_common.SECRET_ENV, None)

    _common.write_json(out / "network_calls.json", {"calls": net.calls})
    print(json.dumps({"experiment": "E4", "network_calls": net.calls,
                         "l5_chain_ok": l5_ok, "output": str(out)}, indent=2))

    if "--freeze" in sys.argv:
        manifest = _common.freeze_manifest(
            HERE, artifact_label="E4 connection governance (frozen inputs + scripts)")
        print(f"E4 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
