#!/usr/bin/env python3
"""CP1 end-to-end journey — the shell prototype's first auditable run.

Grows the frozen pre-flight rather than replacing it: same Qafiya corpus, same
cell edit, same L3 file.create action, same L4 note. Adds what CP1 requires
beyond the pre-flight:

* an ``r_*`` event graph in ``ds:shell_audit`` for every kernel transition;
* L5 routing through ``Router.route(dry_run=True)`` (no live provider call);
* L5 ``ConnectionOperations`` wired into L3 ``ActionEngine(connection_ops=...)``;
* a connection mutation whose NEW ``mdl_*`` successor id lands on the audit
  graph as ``successor_ref`` — never assuming an id is stable across a mutation.

Run under Python 3.12 (matching the pre-flight pin):

    python3.12 experiments/e2e_journey.py [output_dir]

Writes ``summary.json`` + ``journey.jsonl`` + per-step artifacts under
``experiments/output/cp1/`` (default) so ``shell_spine.py`` can recompute every
headline number from raw files.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # 06-shell/experiments
L6 = HERE.parent                                    # 06-shell
if str(L6) not in sys.path:
    sys.path.insert(0, str(L6))

# The bootstrap pins the interpreter, wires sys.path and pre-imports the frozen
# vendor packages BEFORE anything else can shadow them.
from shell import _bootstrap  # noqa: F401,E402
from shell.audit import ShellAuditStore, sha256_file  # noqa: E402
from shell.connections import ShellConnections  # noqa: E402
from shell.interactions import ActionDispatcher, apply_cell_edit  # noqa: E402
from shell.kernel import Kernel, KernelContext, KernelState, transition_table  # noqa: E402
from shell.memory import ShellMemory  # noqa: E402
from shell.routing import ShellRouter  # noqa: E402
from shell.session import new_session  # noqa: E402
from shell import views as shell_views  # noqa: E402
from shell.views import write_view_html  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

from actionlayer.engine import ActionEngine  # noqa: E402  L3 (source, read-only)
from actionlayer.gate import make_grant  # noqa: E402
from actionlayer import renderer as action_renderer  # noqa: E402
from qafiya_core import engine as qafiya_engine  # noqa: E402
from dvr import affordance, render, resolve, specval  # noqa: E402

PREFLIGHT_INPUTS = L6 / "preflight" / "inputs"
FROZEN_L5_ROOT = _bootstrap.L5_FROZEN_DATASETS_ROOT

PROMPT = ("Change the 9 August Q3 food expense to 956.14, create an audit note, "
          "and remember what happened.")
EDIT_VALUE = 956.14
EXPECTED_Q3_AFTER = 10481.96
POLICY_LABEL = "v13"                # frozen L5 default policy: trust_user, allow_flagged

SECRET_ENV = "L6_SHELL_CP1_KEY"
SECRET_VALUE = "sk-L6-CP1-sentinel-MUST-NEVER-BE-RECORDED-9f3a7c"

FAKE_CONNECTION_CONFIG = {
    "label": "L6 CP1 fake local model",
    "connector": "openai_compatible",
    "base_url": "http://127.0.0.1:9/v1",     # loopback, no listener; dry-run only
    "model": "l6-cp1-fake-model",
    "locus": "local",
    "privacy_class": "private",
    "prices": {"input": 0.0, "output": 0.0},  # user-declared local $0
    "key_env": SECRET_ENV,
}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(out_root: Path) -> dict:
    out_root = Path(out_root).resolve()
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    # Per-journey store roots (frozen inputs are copied, never mutated in place).
    qafiya_root = out_root / "stores" / "qafiya"
    l3_file_root = out_root / "stores" / "action"
    l3_conn_root = out_root / "stores" / "connection_actions"
    l4_root = out_root / "stores" / "memory"
    l5_root = out_root / "stores" / "l5"
    audit_root = out_root / "stores" / "shell_audit"

    # ------------------- frozen Qafiya corpus, copied before mutation ----------
    shutil.copytree(PREFLIGHT_INPUTS / "qafiya_corpus" / "datasets",
                     qafiya_root / "datasets")
    shutil.copy2(PREFLIGHT_INPUTS / "qafiya_corpus" / "bindings.jsonl",
                  qafiya_root / "bindings.jsonl")
    view = json.loads((PREFLIGHT_INPUTS / "qafiya_corpus" / "views" /
                        "v_exp.view.json").read_text())
    shell_views.validate_view(view, set(resolve.load_bindings(qafiya_root)))
    qafiya_data_hash = sha256_file(qafiya_root / "datasets" / "expenses" / "data.jsonl")
    # Match the pre-flight's order: run the deterministic provenance gate BEFORE
    # any render or edit so every binding's ``check.provenance`` is PASS. The
    # subsequent ``invalidate()`` inside ``edits.apply`` then flips those PASS
    # bindings to PENDING and returns a count >= 1 (the pre-flight's
    # ``cell_writeback`` check depends on this ordering).
    initial_gate = qafiya_engine.provenance_gate(qafiya_root)

    checks: list[dict] = []

    def _jsonable(v):
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, (list, tuple)):
            return [_jsonable(x) for x in v]
        if isinstance(v, dict):
            return {k: _jsonable(x) for k, x in v.items()}
        return v

    def check(name: str, condition, detail="") -> None:
        checks.append({"name": name, "pass": bool(condition),
                        "detail": _jsonable(detail)})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    check("qafiya_initial_gate_clean", initial_gate == 0,
            f"pre-edit provenance_gate returned {initial_gate}")

    # ------------------------------- shell scaffolding ------------------------
    audit = ShellAuditStore(audit_root)
    session = new_session(user_id="youssef")
    request = session.new_request(PROMPT)
    ctx = KernelContext(request_ref=request.id,
                          content_policy={"store_prompt_content": "never",
                                            "store_response_content": "never"})
    kernel = Kernel(session.id, audit, ctx)

    # Sentinel env var — only the NAME ever crosses the boundary; the VALUE
    # must never appear in any L3, L5 or shell record (checked at the end).
    os.environ[SECRET_ENV] = SECRET_VALUE

    connections = ShellConnections(l5_root=l5_root, l3_root=l3_conn_root,
                                     frozen_l5_root=FROZEN_L5_ROOT,
                                     user_id="youssef", agent_id="l6-shell-cp1")
    memory = ShellMemory(l4_root)
    router = ShellRouter(connections.store, policy_label=POLICY_LABEL)
    file_engine = ActionEngine(l3_file_root)
    dispatcher = ActionDispatcher(file_engine)

    # ------------------------------------------------------------------ RECEIVED
    ev = kernel.enter(KernelState.RECEIVED, notes=f"prompt received: {request.id}",
                        extra_hashes={"qafiya_expenses_data": qafiya_data_hash})
    check("kernel_received", ev["state"] == "RECEIVED" and ev["sequence"] == 1,
            f"first event sequence={ev['sequence']}")

    # -------- connection mutation FIRST so ROUTED has a real connection --------
    # (add + privacy_change demonstrate succession; the successor id must appear
    # on the audit graph as successor_ref — build-instructions §hard-won fact 2.)
    add_result = connections.add(
        FAKE_CONNECTION_CONFIG,
        intent_verbatim="L6 CP1: declare a local fake model connection",
        session_id=session.id)
    check("conn_add_success", add_result.action_outcome == "success",
            add_result.detail or add_result.record.get("outcome"))
    allocated_id = add_result.allocated_id
    check("conn_add_allocated_mdl", isinstance(allocated_id, str)
            and allocated_id.startswith("mdl_"), allocated_id)

    # Privacy change on the freshly added connection → succession → NEW mdl_* id.
    priv_result = connections.change_privacy(
        allocated_id, new_class="public", previous_class="private",
        intent_verbatim="L6 CP1: relax privacy on the fake local connection",
        session_id=session.id)
    check("conn_privacy_success", priv_result.action_outcome == "success",
            priv_result.detail or priv_result.record.get("outcome"))
    successor_id = priv_result.successor_ref
    check("conn_privacy_successor_distinct",
            isinstance(successor_id, str) and successor_id.startswith("mdl_")
            and successor_id != allocated_id,
            f"{allocated_id} -> {successor_id}")
    check("conn_privacy_original_retired",
            connections.store.get("models", allocated_id)["status"] == "retired")
    check("conn_privacy_successor_active",
            connections.store.get("models", successor_id)["status"] == "active")
    check("conn_privacy_get_active_successor",
            connections.active_successor(allocated_id) == successor_id)

    # Fold the connection refs + successor onto the kernel context so every
    # subsequent audit event carries them (the graph must never lose the fact
    # that a mutation superseded to a NEW id).
    ctx.connection_refs = [allocated_id, successor_id]
    ctx.successor_ref = successor_id

    # -------------------------------------------------------------------- ROUTED
    route_request = {"text": PROMPT, "request_id": request.id}
    route = router.route(route_request, dry_run=True, run="cp1-e2e")
    ctx.decision_ref = route.decision_ref
    if route.declared_cost_usd is not None:
        ctx.declared_cost_usd = float(route.declared_cost_usd)
    if route.actual_metered_cost_usd is not None:
        ctx.actual_metered_cost_usd = float(route.actual_metered_cost_usd)
    _write_json(out_root / "route_presentation.json", route.__dict__)
    ev = kernel.enter(KernelState.ROUTED,
                        notes=(f"outcome={route.outcome} "
                                 f"decision={route.decision_ref} "
                                 f"chosen={route.chosen_label or 'none'} "
                                 f"metered={route.metered}"),
                        extra_checks={"route_outcome": route.outcome,
                                        "route_metered": route.metered})
    check("kernel_routed_recorded_decision",
            ev["decision_ref"] == route.decision_ref, ev["decision_ref"])
    check("route_declared_vs_metered_distinct",
            (route.declared_cost_usd is None) != (route.actual_metered_cost_usd is None)
            or route.actual_metered_cost_usd is None,
            f"declared={route.declared_cost_usd} actual={route.actual_metered_cost_usd}")

    # ------------------------------------------------------------------ RECALLED
    # L4 emits context only through its binding; the shell records the m_* ids
    # and a context hash but never reads the memory JSON directly.
    user_turn_id = memory.log_turn(session.id, 1, "user", PROMPT,
                                     tokens_in=len(PROMPT.split()),
                                     tokens_out=0,
                                     model_id=(route.chosen_label or "l5-dry-run"))
    ctx.memory_refs = [user_turn_id]
    ev = kernel.enter(KernelState.RECALLED,
                        notes=f"user turn bound: {user_turn_id}",
                        extra_hashes={"prompt_context": sha256_file(
                            audit.dir / "data.jsonl")})
    check("kernel_recalled_memory_ref", user_turn_id in ev["memory_refs"], ev["memory_refs"])

    # ------------------------------------------------------------------ COMPOSED
    composition = {
        "session_id": session.id,
        "request_ref": request.id,
        "decision_ref": route.decision_ref,
        "route_outcome": route.outcome,
        "planned_edit": {"record_id": "r_051", "new_value": EDIT_VALUE},
        "planned_action": {"action_type": "file.create",
                              "path": "audit/q3-expense-edit-cp1.txt"},
        "planned_memory_note": "CP1 journey: edit + confirmed action + connection succession",
    }
    _write_json(out_root / "composition.json", composition)
    ev = kernel.enter(KernelState.COMPOSED, notes="composition recorded",
                        extra_hashes={"composition":
                                        sha256_file(out_root / "composition.json")})
    check("kernel_composed_hash_present",
            "composition" in ev["artifact_hashes"], ev["artifact_hashes"])

    # -------------------------------------------------------------- VIEW_VALIDATED
    shell_views.validate_view(view, set(resolve.load_bindings(qafiya_root)))
    ev = kernel.enter(KernelState.VIEW_VALIDATED,
                        view_refs=[view["id"]],
                        notes=f"validated {view['id']} against dvr/1.1")
    ctx.view_refs = [view["id"]]
    check("kernel_view_validated_ref", ev["view_refs"] == [view["id"]], ev["view_refs"])

    # ------------------------------------------------------------------- RENDERED
    before_html = render.render(qafiya_root, view)
    write_view_html(out_root / "qafiya_before.html", before_html)
    evidence = affordance.evidence_panel(qafiya_root,
                                            resolve.load_bindings(qafiya_root)["b_count"])
    _write_json(out_root / "qafiya_evidence.json", evidence)
    ev = kernel.enter(KernelState.RENDERED,
                        notes=f"rendered before; coverage=100%; evidence rows={len(evidence['source_rows'])}",
                        extra_hashes={"qafiya_before_html":
                                        sha256_file(out_root / "qafiya_before.html")},
                        extra_checks={"render_before_clean":
                                        "UNRESOLVED" not in before_html},
                        extra_coverage={"qafiya_before": "coverage: 100%"})
    check("render_before_clean", "UNRESOLVED" not in before_html
            and "10346.71" in before_html, "before-html shows the frozen total")
    check("evidence_rows_21", len(evidence["source_rows"]) == 21,
            len(evidence["source_rows"]))

    # ------------------------------------------------------------------ WRITE_BACK
    node = next(n for n in view["nodes"] if n["id"] == "cell:r_042")
    edit_result = apply_cell_edit(qafiya_root, view["id"], node, EDIT_VALUE)
    ctx.edit_refs = [edit_result.edit_binding_id]
    ev = kernel.enter(KernelState.WRITE_BACK,
                        edit_refs=[edit_result.edit_binding_id],
                        notes=(f"edit {edit_result.edit_binding_id} applied; "
                                 f"invalidated={edit_result.invalidated}; "
                                 f"gate={edit_result.qafiya_gate_after}"),
                        extra_checks={"qafiya_gate_after_edit":
                                        edit_result.qafiya_gate_after})
    check("edit_writeback_r051",
            edit_result.updated_record["id"] == "r_051"
            and edit_result.updated_record["amount"] == EDIT_VALUE
            and edit_result.updated_record["category"] == "food"
            and edit_result.updated_record["date"] == "2026-08-09",
            edit_result.updated_record)
    check("edit_gate_clean", edit_result.qafiya_gate_after == 0,
            edit_result.qafiya_gate_after)
    check("edit_invalidated_present", edit_result.invalidated >= 1,
            edit_result.invalidated)

    # -------- re-validate + re-render (loop back through VIEW_VALIDATED) --------
    shell_views.validate_view(view, set(resolve.load_bindings(qafiya_root)))
    kernel.enter(KernelState.VIEW_VALIDATED, notes="revalidated after edit")
    after_html = render.render(qafiya_root, view)
    write_view_html(out_root / "qafiya_after.html", after_html)
    kernel.enter(KernelState.RENDERED,
                    notes="re-rendered after edit",
                    extra_hashes={"qafiya_after_html":
                                    sha256_file(out_root / "qafiya_after.html")},
                    extra_coverage={"qafiya_after": "coverage: 100%"})
    check("render_after_recomputed",
            "10481.96" in after_html and "coverage: 100%" in after_html
            and "UNRESOLVED" not in after_html, "after-html shows the recomputed total")

    # -------- independent recompute of Q3 from the raw data.jsonl --------------
    records_after = _read_jsonl(qafiya_root / "datasets" / "expenses" / "data.jsonl")
    q3_total_recomputed = round(sum(r["amount"] for r in records_after
                                       if r["period"] == "Q3"), 2)
    check("q3_recomputed_from_raw",
            q3_total_recomputed == EXPECTED_Q3_AFTER, q3_total_recomputed)

    # ---------------------------------------------------------------- AWAITING_USER
    kernel.enter(KernelState.AWAITING_USER,
                    notes="user must approve the audit-note action")

    # ---------------------------------------------------------------- ACTION_GATED
    file_grant = file_engine.issue_grant(make_grant(
        user_id="youssef", action_types=["file.create"], target_pattern="**",
        requires_confirmation=["file.create"]))
    note_content = (f"CP1: Q3 expense r_051 changed to {EDIT_VALUE:.2f}; "
                      f"Q3 total recomputed to {EXPECTED_Q3_AFTER:.2f}; "
                      f"connection {allocated_id} superseded by {successor_id}.\n")
    action_result = dispatcher.submit(
        intent_verbatim=PROMPT,
        normalized={"action_type": "file.create",
                      "params": {"path": "audit/q3-expense-edit-cp1.txt",
                                    "content": note_content}},
        actor={"agent_id": "l6-shell-cp1", "session_id": session.id},
        user_id="youssef", grant_id=file_grant["_id"],
        confirm_irreversible=True)
    ctx.action_refs = [action_result.action_ref]
    ev = kernel.enter(KernelState.ACTION_GATED,
                        action_refs=[action_result.action_ref],
                        notes=f"L3 gate: outcome={action_result.outcome} "
                                 f"class={action_result.reversibility_class}",
                        extra_checks={"action_gate_outcome": action_result.outcome})
    check("action_gated_success", action_result.outcome == "success",
            action_result.reason or action_result.record.get("outcome"))
    check("action_reversibility_class_exact",
            action_result.reversibility_class == "EXACT",
            action_result.reversibility_class)

    # ------------------------------------------------------------------- EXECUTED
    action_evidence = affordance.evidence_for_action(l3_file_root,
                                                        action_result.action_ref)
    _write_json(out_root / "action_evidence.json", action_evidence)
    _write_json(out_root / "action_record.json", action_result.record)
    audit_note_path = Path(file_engine.store.files_path(
        "audit/q3-expense-edit-cp1.txt"))
    check("action_file_written", audit_note_path.exists()
            and audit_note_path.read_text() == note_content,
            audit_note_path)
    kernel.enter(KernelState.EXECUTED,
                    notes=f"executed {action_result.action_ref}",
                    extra_hashes={"action_note_file": sha256_file(audit_note_path)},
                    extra_checks={"action_evidence_found": action_evidence["found"]})

    # ----------------------------------------------------------------- REMEMBERED
    agent_text = (f"CP1: edited r_051 to {EDIT_VALUE:.2f}; "
                    f"action {action_result.action_ref} succeeded after confirmation; "
                    f"connection {allocated_id} superseded by {successor_id}.")
    agent_turn_id = memory.log_turn(session.id, 2, "agent", agent_text,
                                       tokens_in=0, tokens_out=len(agent_text.split()),
                                       model_id=(route.chosen_label or "l5-dry-run"))
    note_text = (f"CP1 journey: edit {edit_result.edit_binding_id} set r_051 to "
                   f"{EDIT_VALUE:.2f}; action {action_result.action_ref} succeeded "
                   f"after confirmation; connection {allocated_id} superseded by "
                   f"{successor_id}.")
    memory_note_id = memory.add_note(note_text, [user_turn_id, agent_turn_id],
                                         note_kind="summary")
    memory_view = memory.inspect_view()
    specval.validate_view(memory_view, memory.known_binding_ids())
    memory_html = render.render(l4_root, memory_view)
    write_view_html(out_root / "memory_inspection.html", memory_html)
    ctx.memory_refs = [user_turn_id, agent_turn_id, memory_note_id]
    kernel.enter(KernelState.REMEMBERED,
                    memory_refs=[user_turn_id, agent_turn_id, memory_note_id],
                    view_refs=[view["id"], memory_view["id"]],
                    notes=f"L4 note bound: {memory_note_id}",
                    extra_hashes={"memory_inspection_html":
                                    sha256_file(out_root / "memory_inspection.html")},
                    extra_checks={"memory_chain_all_verified":
                                    all(memory.verify_all_chains().values())})
    check("memory_inspection_clean",
            note_text in memory_html and "UNRESOLVED" not in memory_html
            and "▸evidence" in memory_html, "L4 note renders through L2")
    check("memory_chains_verify",
            all(memory.verify_all_chains().values()),
            memory.verify_all_chains())

    # --------------------------------------------------------------------- CLOSED
    kernel.enter(KernelState.CLOSED, notes="journey closed; replay exposed")

    # -------- verify the audit graph chain and successor visibility ------------
    replay = audit.replay(session.id)
    _write_json(out_root / "audit_replay.json",
                  {"events": [{k: v for k, v in e.items()} for e in replay["events"]],
                    "sequences": replay["sequences"],
                    "chain_ok": replay["chain_ok"],
                    "chain_detail": replay["chain_detail"],
                    "input_refs_resolved": replay["input_refs_resolved"],
                    "input_refs_missing": replay["input_refs_missing"],
                    "successors": replay["successors"]})
    check("audit_chain_verifies", replay["chain_ok"], replay["chain_detail"])
    check("audit_sequences_monotonic",
            replay["sequences"] == list(range(1, len(replay["sequences"]) + 1)),
            replay["sequences"])
    check("audit_successor_ref_recorded",
            any(succ == successor_id for _, succ in replay["successors"]),
            replay["successors"])
    check("audit_states_cover_journey",
            {e["state"] for e in replay["events"]} >= {
                "RECEIVED", "ROUTED", "RECALLED", "COMPOSED", "VIEW_VALIDATED",
                "RENDERED", "AWAITING_USER", "WRITE_BACK", "ACTION_GATED",
                "EXECUTED", "REMEMBERED", "CLOSED"},
            sorted({e["state"] for e in replay["events"]}))

    # -------- secret hygiene: the VALUE must never appear in any record --------
    def scan(root: Path) -> list[str]:
        leaks = []
        for dirpath, _, files in os.walk(root):
            for fn in files:
                p = Path(dirpath) / fn
                try:
                    if SECRET_VALUE in p.read_text(encoding="utf-8"):
                        leaks.append(str(p))
                except (UnicodeDecodeError, OSError):
                    continue
        return leaks

    all_leaks = (scan(out_root / "stores"))
    check("secret_value_absent_from_all_stores", not all_leaks, all_leaks[:3])
    l5_blob = json.dumps(connections.store.records("models"), sort_keys=True)
    l3_conn_blob = json.dumps(connections.engine.records(), sort_keys=True)
    l3_file_blob = json.dumps(file_engine.records(), sort_keys=True)
    audit_blob = json.dumps(audit.events(), sort_keys=True)
    check("secret_value_absent_from_l5_records", SECRET_VALUE not in l5_blob)
    check("secret_value_absent_from_l3_records",
            SECRET_VALUE not in l3_conn_blob and SECRET_VALUE not in l3_file_blob)
    check("secret_value_absent_from_audit_records", SECRET_VALUE not in audit_blob)
    check("secret_env_name_retained_in_l5", SECRET_ENV in l5_blob)

    # -------- L5 chain integrity (models dataset carries the succession) -------
    l5_models_ok, l5_models_detail = connections.store.verify_chain("models")
    check("l5_models_chain_verifies", l5_models_ok, l5_models_detail)

    summary = {
        "journey": PROMPT,
        "status": "PASS",
        "session_id": session.id,
        "request_ref": request.id,
        "kernel_states_visited": [e["state"] for e in replay["events"]],
        "transition_table": transition_table(),
        "checks_passed": len(checks),
        "checks": checks,
        "refs": {
            "decision": route.decision_ref,
            "route_outcome": route.outcome,
            "edit": edit_result.edit_binding_id,
            "action": action_result.action_ref,
            "memory_note": memory_note_id,
            "user_turn": user_turn_id,
            "agent_turn": agent_turn_id,
            "connection_allocated": allocated_id,
            "connection_successor": successor_id,
        },
        "values": {
            "edited_record": "r_051",
            "edited_amount": EDIT_VALUE,
            "q3_total_after": EXPECTED_Q3_AFTER,
            "q3_total_recomputed_from_raw": q3_total_recomputed,
            "evidence_rows": len(evidence["source_rows"]),
            "route_metered": route.metered,
            "declared_cost_usd": route.declared_cost_usd,
            "actual_metered_cost_usd": route.actual_metered_cost_usd,
        },
        "audit": {
            "event_count": len(replay["events"]),
            "chain_ok": replay["chain_ok"],
            "sequences": replay["sequences"],
            "successors": replay["successors"],
        },
    }
    _write_json(out_root / "summary.json", summary)
    return summary


def main() -> int:
    # Reproducibility: L5's decide.hmac_key() falls back to a random key written
    # under its package root when $LOG_HMAC_KEY is unset. Pin a deterministic
    # value so the prompt HMAC is reproducible and nothing is written into the
    # frozen vendor snapshot.
    os.environ.setdefault("LOG_HMAC_KEY",
                            "l6-shell-deterministic-hmac-key-for-reproducibility")
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output" / "cp1"
    summary = run(dest)
    print(json.dumps({
        "status": summary["status"],
        "checks_passed": summary["checks_passed"],
        "session_id": summary["session_id"],
        "kernel_states": summary["kernel_states_visited"],
        "successor_ref": summary["refs"]["connection_successor"],
        "q3_total_recomputed": summary["values"]["q3_total_recomputed_from_raw"],
        "route_outcome": summary["refs"]["route_outcome"],
        "route_metered": summary["values"]["route_metered"],
        "output": str(dest),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        os.environ.pop(SECRET_ENV, None)
