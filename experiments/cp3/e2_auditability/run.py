#!/usr/bin/env python3
"""E2 — auditability walkthrough (brief §7.2 E2; CP2 clearance answer 3).

Five PURPOSE-BUILT frozen variants — approve, reject, refuse, failure,
unresolved — each producing a typed visible state and an auditable trail in its
own ``ds:shell_audit`` store. These are dedicated E2 fixtures, NOT the
ephemeral ``output/cp2/`` gate artifacts.

Run under Python 3.12:

    python3.12 experiments/cp3/e2_auditability/run.py [--freeze]
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
from shell.audit import ShellAuditStore, sha256_file  # noqa: E402
from shell.kernel import Kernel, KernelContext, KernelState  # noqa: E402
from shell.session import new_session  # noqa: E402
from shell.views import write_view_html  # noqa: E402

import json  # noqa: E402
import shutil  # noqa: E402

from actionlayer.engine import ActionEngine  # noqa: E402
from actionlayer.gate import make_grant  # noqa: E402
from dvr import render as dvr_render, resolve as dvr_resolve, specval  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402


# --------------------------------------------------------------- approve variant
def variant_approve(root: Path) -> dict:
    """Approval executes only through L3; the audit graph carries the action ref
    and the written file's hash."""
    out = root / "approve"
    aroot = out / "stores" / "action"
    audit_root = out / "stores" / "shell_audit"
    engine = ActionEngine(aroot)
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="e2-approve")
    kernel = Kernel(session.id, audit, KernelContext())

    kernel.enter(KernelState.RECEIVED, notes="E2 approve: prompt received")
    kernel.enter(KernelState.ROUTED, notes="E2 approve: routed (no live call)")
    kernel.enter(KernelState.RECALLED, notes="E2 approve: nothing to recall")
    kernel.enter(KernelState.COMPOSED, notes="E2 approve: compose file.create intent")
    kernel.enter(KernelState.VIEW_VALIDATED, notes="E2 approve: confirmation view validated")
    kernel.enter(KernelState.RENDERED, notes="E2 approve: confirmation rendered")
    kernel.enter(KernelState.AWAITING_USER, notes="E2 approve: awaiting user choice")

    grant = engine.issue_grant(make_grant(
        user_id="e2", action_types=["file.create"], target_pattern="**",
        requires_confirmation=["file.create"]))
    record = engine.act(
        intent_verbatim="E2 approve: create the audit note",
        normalized={"action_type": "file.create",
                      "params": {"path": "e2/approved.txt", "content": "approved\n"}},
        actor={"agent_id": "e2", "session_id": session.id},
        user_id="e2", grant_id=grant["_id"], confirm_irreversible=True)
    written = Path(engine.store.files_path("e2/approved.txt"))
    kernel.ctx.action_refs = [record["action_id"]]
    kernel.enter(KernelState.ACTION_GATED,
                    notes=f"E2 approve: gate outcome={record['outcome']['status']}",
                    extra_checks={"action_outcome": record["outcome"]["status"]})
    kernel.enter(KernelState.EXECUTED,
                    notes="E2 approve: executed",
                    extra_hashes={"approved_file": sha256_file(written) if written.exists() else None})
    kernel.enter(KernelState.REMEMBERED, notes="E2 approve: remembered")
    kernel.enter(KernelState.CLOSED, notes="E2 approve: closed")

    _common.write_json(out / "action_record.json", record)
    _common.write_json(out / "file_sha.json",
                         {"path": str(written),
                            "exists": written.exists(),
                            "content": written.read_text() if written.exists() else None,
                            "sha256": sha256_file(written) if written.exists() else None})
    replay = audit.replay(session.id)
    _common.write_json(out / "replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"]})
    return {"variant": "approve", "outcome": record["outcome"]["status"],
              "file_written": written.exists(),
              "audit_events": len(replay["events"]),
              "chain_ok": replay["chain_ok"]}


# ---------------------------------------------------------------- reject variant
def variant_reject(root: Path) -> dict:
    """A DVR reject intent is recorded but does NOT execute or undo anything."""
    out = root / "reject"
    aroot = out / "stores" / "action"
    audit_root = out / "stores" / "shell_audit"
    engine = ActionEngine(aroot)
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="e2-reject")
    kernel = Kernel(session.id, audit, KernelContext())

    # First approve a file so there is something the reject intent could have
    # undone — the point of the variant is that it does NOT.
    grant = engine.issue_grant(make_grant(
        user_id="e2", action_types=["file.create"], target_pattern="**",
        requires_confirmation=["file.create"]))
    approved = engine.act(
        intent_verbatim="E2 reject: first approve a file",
        normalized={"action_type": "file.create",
                      "params": {"path": "e2/pre_existing.txt", "content": "pre-existing\n"}},
        actor={"agent_id": "e2", "session_id": session.id},
        user_id="e2", grant_id=grant["_id"], confirm_irreversible=True)
    pre_file = Path(engine.store.files_path("e2/pre_existing.txt"))
    pre_sha = sha256_file(pre_file)

    kernel.enter(KernelState.RECEIVED, notes="E2 reject: prompt received")
    kernel.enter(KernelState.ROUTED, notes="E2 reject: routed")
    kernel.enter(KernelState.RECALLED, notes="E2 reject: recalled")
    kernel.enter(KernelState.COMPOSED, notes="E2 reject: composed")
    kernel.enter(KernelState.VIEW_VALIDATED, notes="E2 reject: view validated")
    kernel.enter(KernelState.RENDERED, notes="E2 reject: rendered")
    kernel.enter(KernelState.AWAITING_USER, notes="E2 reject: awaiting user choice")

    # The user clicks REJECT on a *different* pending action. The intent is
    # recorded on the existing record; nothing executes.
    intent = engine.receive_confirmation_intent(approved["action_id"], "reject", "e2")
    post_sha = sha256_file(pre_file)
    kernel.ctx.action_refs = [approved["action_id"]]
    kernel.enter(KernelState.ACTION_GATED,
                    notes=f"E2 reject: intent recorded ({intent.get('detail')}); no execution",
                    extra_checks={"reject_intent_ok": intent.get("ok") is True,
                                    "file_unchanged": pre_sha == post_sha})
    # A reject produces no execution, so the journey closes from ACTION_GATED.
    kernel.enter(KernelState.CLOSED, notes="E2 reject: closed with no execution")

    _common.write_json(out / "reject_intent.json", intent)
    _common.write_json(out / "file_unchanged.json",
                         {"pre_sha": pre_sha, "post_sha": post_sha,
                            "unchanged": pre_sha == post_sha})
    replay = audit.replay(session.id)
    _common.write_json(out / "replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"]})
    return {"variant": "reject", "intent_ok": intent.get("ok") is True,
              "file_unchanged": pre_sha == post_sha,
              "audit_events": len(replay["events"]),
              "chain_ok": replay["chain_ok"]}


# ---------------------------------------------------------------- refuse variant
def variant_refuse(root: Path) -> dict:
    """A grant that does not cover the action → L3 refuses; no file is written."""
    out = root / "refuse"
    aroot = out / "stores" / "action"
    audit_root = out / "stores" / "shell_audit"
    engine = ActionEngine(aroot)
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="e2-refuse")
    kernel = Kernel(session.id, audit, KernelContext())

    kernel.enter(KernelState.RECEIVED, notes="E2 refuse: prompt received")
    kernel.enter(KernelState.ROUTED, notes="E2 refuse: routed")
    kernel.enter(KernelState.RECALLED, notes="E2 refuse: recalled")
    kernel.enter(KernelState.COMPOSED, notes="E2 refuse: composed")
    kernel.enter(KernelState.VIEW_VALIDATED, notes="E2 refuse: view validated")
    kernel.enter(KernelState.RENDERED, notes="E2 refuse: rendered")
    kernel.enter(KernelState.AWAITING_USER, notes="E2 refuse: awaiting user choice")

    narrow = engine.issue_grant(make_grant(
        user_id="e2", action_types=["file.create"],
        target_pattern="e2/allowed.txt"))     # does NOT cover e2/refused.txt
    record = engine.act(
        intent_verbatim="E2 refuse: create a file outside the grant",
        normalized={"action_type": "file.create",
                      "params": {"path": "e2/refused.txt", "content": "never written\n"}},
        actor={"agent_id": "e2", "session_id": session.id},
        user_id="e2", grant_id=narrow["_id"], confirm_irreversible=True)
    refused_file = Path(engine.store.files_path("e2/refused.txt"))
    kernel.ctx.action_refs = [record["action_id"]]
    kernel.enter(KernelState.ACTION_GATED,
                    notes=f"E2 refuse: gate outcome={record['outcome']['status']} "
                            f"reason={record['outcome'].get('reason')}",
                    extra_checks={"action_outcome": record["outcome"]["status"],
                                    "refusal_reason": record["outcome"].get("reason"),
                                    "file_absent": not refused_file.exists()})
    kernel.enter(KernelState.CLOSED, notes="E2 refuse: closed with typed refusal")

    _common.write_json(out / "action_record.json", record)
    _common.write_json(out / "file_absent.json",
                         {"path": str(refused_file), "exists": refused_file.exists()})
    replay = audit.replay(session.id)
    _common.write_json(out / "replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"]})
    return {"variant": "refuse", "outcome": record["outcome"]["status"],
              "reason": record["outcome"].get("reason"),
              "file_absent": not refused_file.exists(),
              "audit_events": len(replay["events"]),
              "chain_ok": replay["chain_ok"]}


# --------------------------------------------------------------- failure variant
def variant_failure(root: Path) -> dict:
    """A precondition failure (file.delete on a missing file) → typed refusal."""
    out = root / "failure"
    aroot = out / "stores" / "action"
    audit_root = out / "stores" / "shell_audit"
    engine = ActionEngine(aroot)
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="e2-failure")
    kernel = Kernel(session.id, audit, KernelContext())

    kernel.enter(KernelState.RECEIVED, notes="E2 failure: prompt received")
    kernel.enter(KernelState.ROUTED, notes="E2 failure: routed")
    kernel.enter(KernelState.RECALLED, notes="E2 failure: recalled")
    kernel.enter(KernelState.COMPOSED, notes="E2 failure: composed")
    kernel.enter(KernelState.VIEW_VALIDATED, notes="E2 failure: view validated")
    kernel.enter(KernelState.RENDERED, notes="E2 failure: rendered")
    kernel.enter(KernelState.AWAITING_USER, notes="E2 failure: awaiting user choice")

    grant = engine.issue_grant(make_grant(
        user_id="e2", action_types=["file.delete"], target_pattern="**"))
    record = engine.act(
        intent_verbatim="E2 failure: delete a file that does not exist",
        normalized={"action_type": "file.delete",
                      "params": {"path": "e2/does-not-exist.txt"}},
        actor={"agent_id": "e2", "session_id": session.id},
        user_id="e2", grant_id=grant["_id"], confirm_irreversible=True)
    kernel.ctx.action_refs = [record["action_id"]]
    kernel.enter(KernelState.ACTION_GATED,
                    notes=f"E2 failure: gate outcome={record['outcome']['status']} "
                            f"reason={record['outcome'].get('reason')}",
                    extra_checks={"action_outcome": record["outcome"]["status"],
                                    "failure_reason": record["outcome"].get("reason")})
    kernel.enter(KernelState.CLOSED, notes="E2 failure: closed with typed failure")

    _common.write_json(out / "action_record.json", record)
    replay = audit.replay(session.id)
    _common.write_json(out / "replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"]})
    return {"variant": "failure", "outcome": record["outcome"]["status"],
              "reason": record["outcome"].get("reason"),
              "audit_events": len(replay["events"]),
              "chain_ok": replay["chain_ok"]}


# ------------------------------------------------------------ unresolved variant
def _synthetic_unresolved_store(root: Path) -> Path:
    """Same quarantine-based fixture as CP2's F8, rebuilt here as a dedicated
    E2 frozen input (purpose-built, not reused from the ephemeral gate output)."""
    ds = root / "datasets" / "synthetic"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "schema.json").write_text(json.dumps({
        "dataset": "synthetic", "id_field": "id", "id_prefix": "r_",
        "fields": {"id": "id", "amount": "number", "label": "string"},
        "derivations": ["filter", "sum"],
    }, indent=1, sort_keys=True))
    (ds / "data.jsonl").write_text(
        json.dumps({"id": "r_001", "amount": 10.0, "label": "present"}, sort_keys=True) + "\n"
        + json.dumps({"id": "r_002", "amount": 20.0, "label": "quarantined"}, sort_keys=True) + "\n")
    (ds / "history.jsonl").write_text("")
    (ds / "bindings.jsonl").write_text("")
    (ds / "SUPERSEDED.json").write_text("[]\n")
    present = {
        "id": "b_present", "kind": "view",
        "target": {"view": "v_synthetic", "node": "cell:r_001"},
        "sources": [{"dataset": "ds:synthetic", "record": "r_001", "field": "amount"}],
        "derivation": "sum(amount) where id='r_001'",
        "value": 10.0, "statistic": "sum", "device": "e2-fixture",
        "authoritative_artifact": "datasets/synthetic/data.jsonl",
        "provenance": {"created_by": "e2-unresolved-fixture"},
        "check": {"provenance": "PASS"},
    }
    quarantined = {
        "id": "b_quarantined", "kind": "view",
        "target": {"view": "v_synthetic", "node": "cell:r_002"},
        "sources": [{"dataset": "ds:synthetic", "record": "r_002", "field": "amount"}],
        "derivation": "sum(amount) where id='r_002'",
        "value": 20.0, "statistic": "sum", "device": "e2-fixture",
        "authoritative_artifact": "datasets/synthetic/quarantined.jsonl",
        "provenance": {"created_by": "e2-unresolved-fixture"},
        "check": {"provenance": "PENDING"},
    }
    (root / "bindings.jsonl").write_text(
        json.dumps(present, sort_keys=True) + "\n"
        + json.dumps(quarantined, sort_keys=True) + "\n")
    (root / "SUPERSEDED.json").write_text(json.dumps(
        {"superseded": ["datasets/synthetic/quarantined.jsonl"]}, indent=1, sort_keys=True))
    view = {
        "spec": "dvr/1.1", "id": "v_synthetic", "kind": "table",
        "title": {"text": "E2 unresolved fixture (one quarantined binding)"},
        "columns": [{"id": "col:amount", "label": "Amount", "source_field": "amount"}],
        "nodes": [
            {"id": "cell:r_001", "role": "value", "binding_ref": "b_present", "column": "col:amount"},
            {"id": "cell:r_002", "role": "value", "binding_ref": "b_quarantined", "column": "col:amount"},
        ],
    }
    (root / "views").mkdir(exist_ok=True)
    (root / "views" / "v_synthetic.view.json").write_text(
        json.dumps(view, indent=1, sort_keys=True))
    return root


def variant_unresolved(root: Path) -> dict:
    """A quarantined binding renders as UNRESOLVED — a typed visible state."""
    out = root / "unresolved"
    syn_root = out / "stores" / "synthetic"
    audit_root = out / "stores" / "shell_audit"
    _synthetic_unresolved_store(syn_root)
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="e2-unresolved")
    kernel = Kernel(session.id, audit, KernelContext())

    view = json.loads((syn_root / "views" / "v_synthetic.view.json").read_text())
    bindings = dvr_resolve.load_bindings(syn_root)
    specval.validate_view(view, set(bindings))     # the view IS dvr/1.1-clean

    kernel.enter(KernelState.RECEIVED, notes="E2 unresolved: prompt received")
    kernel.enter(KernelState.ROUTED, notes="E2 unresolved: routed")
    kernel.enter(KernelState.RECALLED, notes="E2 unresolved: recalled")
    kernel.enter(KernelState.COMPOSED, notes="E2 unresolved: composed")
    kernel.ctx.view_refs = [view["id"]]
    kernel.enter(KernelState.VIEW_VALIDATED, notes="E2 unresolved: view validated (dvr/1.1-clean)")
    html = dvr_render.render(syn_root, view)
    write_view_html(out / "view.html", html)
    kernel.enter(KernelState.RENDERED,
                    notes="E2 unresolved: rendered; quarantined cell painted UNRESOLVED",
                    extra_hashes={"view_html": sha256_file(out / "view.html")},
                    extra_checks={"unresolved_visible": "UNRESOLVED" in html})
    kernel.enter(KernelState.REMEMBERED, notes="E2 unresolved: remembered as a typed negative")
    kernel.enter(KernelState.CLOSED, notes="E2 unresolved: closed")

    _common.write_json(out / "render_check.json",
                         {"unresolved_in_html": "UNRESOLVED" in html,
                            "present_value_resolved": "10" in html,
                            "view_is_dvr11_clean": True})
    replay = audit.replay(session.id)
    _common.write_json(out / "replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"]})
    return {"variant": "unresolved", "unresolved_visible": "UNRESOLVED" in html,
              "view_dvr11_clean": True,
              "audit_events": len(replay["events"]),
              "chain_ok": replay["chain_ok"]}


VARIANTS = [variant_approve, variant_reject, variant_refuse,
              variant_failure, variant_unresolved]


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    results = [fn(out) for fn in VARIANTS]
    _common.write_json(out / "variants.json", results)
    print(json.dumps({"experiment": "E2", "variants": len(results),
                         "all_chains_ok": all(r["chain_ok"] for r in results),
                         "output": str(out)}, indent=2))

    if "--freeze" in sys.argv:
        manifest = _common.freeze_manifest(
            HERE, artifact_label="E2 auditability walkthrough (frozen inputs + scripts)")
        print(f"E2 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
