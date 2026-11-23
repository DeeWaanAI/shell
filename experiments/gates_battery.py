#!/usr/bin/env python3
"""CP2 functional-gates battery — F1..F8 as a standalone suite.

Each gate runs against fresh per-gate store roots and writes its raw artifacts
under ``experiments/output/cp2/<gate>/``. The battery's own ``summary.json`` is
a CONVENIENCE for the operator; the independent spine (``gates_spine.py``)
recomputes every headline number from the raw artifacts and refuses to trust
the summary.

Gates (brief §7.1):

* F1 kernel transitions       — one ordered audit event per allowed edge;
                                 illegal transitions raise ``IllegalTransition``
                                 and write NO event.
* F2 route presentation       — planned / answered (local fake transport) /
                                 refused, each matched against the L5 decision
                                 record; declared-vs-metered cost kept distinct;
                                 simulated metering is labelled, never
                                 presented as real provider metering.
* F3 view/edit round trip     — rendered values recompute; edits create history
                                 and visible invalidation before re-proof.
* F4 action authority         — approval executes only through L3; rejection
                                 and refusal produce no effect.
* F5 memory provenance        — inspection returns exactly active memory;
                                 evidence and source refs resolve.
* F6 connection governance    — LOCAL FAKE endpoint (loopback base_url, never
                                 called); add/retire/privacy_change produce L3
                                 records; undo paths exercised; a grant missing
                                 the action type refuses with the list
                                 unchanged; a broken connection is NOT
                                 implicitly retired; secrets absent.
* F7 audit replay             — every event reference resolves; sequences
                                 complete; all owned chains verify.
* F8 failure honesty          — routed refusal, L3 failure, unresolved view
                                 and unavailable connection each retain a typed
                                 visible state.

No live or paid provider call anywhere in this battery. ``NetworkGuard`` (from
``fake_transport``) wraps every gate that touches L5 routing and asserts zero
network calls at the end.

Run under Python 3.12 (matching the pinned interpreter):

    python3.12 experiments/gates_battery.py [output_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # 06-shell/experiments
L6 = HERE.parent
if str(L6) not in sys.path:
    sys.path.insert(0, str(L6))

from shell import _bootstrap  # noqa: F401,E402
from shell.audit import ShellAuditStore, sha256_file  # noqa: E402
from shell.connections import ShellConnections  # noqa: E402
from shell.interactions import ActionDispatcher, apply_cell_edit  # noqa: E402
from shell.kernel import (ALLOWED, IllegalTransition, Kernel,  # noqa: E402
                            KernelContext, KernelState, transition_table)
from shell.memory import ShellMemory  # noqa: E402
from shell.routing import ShellRouter  # noqa: E402
from shell.session import new_session  # noqa: E402
from shell import views as shell_views  # noqa: E402
from shell.views import write_view_html  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

# Frozen contracts, imported read-only.
from actionlayer.engine import ActionEngine  # noqa: E402
from actionlayer.gate import make_grant  # noqa: E402
from dvr import render as dvr_render, resolve as dvr_resolve, specval  # noqa: E402
from qafiya_core import chain as qafiya_chain, engine as qafiya_engine  # noqa: E402
from qafiya_core import store as qafiya_store  # noqa: E402
import connections as L5Connections  # noqa: E402
from health import Health  # noqa: E402

# CP2-local fake transport (never touches the network).
sys.path.insert(0, str(HERE))
import fake_transport as FT  # noqa: E402
from fake_transport import (ANSWERED, CALL_FAILED_CONNECTION,  # noqa: E402
                              METER_LABEL, FakeTransport, NetworkGuard)

PREFLIGHT_INPUTS = L6 / "preflight" / "inputs"
FROZEN_L5_ROOT = _bootstrap.L5_FROZEN_DATASETS_ROOT
POLICY_LABEL = "v13"

SECRET_ENV = "L6_SHELL_CP2_KEY"
SECRET_VALUE = "sk-L6-CP2-sentinel-MUST-NEVER-BE-RECORDED-4b7e1d"

FAKE_ENDPOINT = "http://127.0.0.1:9/v1"      # loopback, no listener, never called
FAKE_CONFIG = {
    "label": "CP2 fake local model",
    "connector": "openai_compatible",
    "base_url": FAKE_ENDPOINT,
    "model": "cp2-fake-model",
    "locus": "local",
    "privacy_class": "private",
    "prices": {"input": 0.0, "output": 0.0},
    "key_env": SECRET_ENV,
}

PROMPT = "CP2 gates: show the Q3 expense total."
EDIT_VALUE = 956.14
EXPECTED_Q3_AFTER = 10481.96


# --------------------------------------------------------------- small helpers
def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                                 ensure_ascii=False, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _scaffold_qafiya_copy(dst_root: Path) -> None:
    shutil.copytree(PREFLIGHT_INPUTS / "qafiya_corpus" / "datasets",
                     dst_root / "datasets")
    shutil.copy2(PREFLIGHT_INPUTS / "qafiya_corpus" / "bindings.jsonl",
                  dst_root / "bindings.jsonl")


def _load_frozen_view() -> dict:
    return json.loads((PREFLIGHT_INPUTS / "qafiya_corpus" / "views" /
                         "v_exp.view.json").read_text())


def _scan_tree(root: Path, needle: str) -> list[str]:
    leaks = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = Path(dirpath) / fn
            try:
                if needle in p.read_text(encoding="utf-8"):
                    leaks.append(str(p))
            except (UnicodeDecodeError, OSError):
                continue
    return leaks


# ============================================================ F1 kernel states
def gate_f1(out: Path) -> dict:
    """Every allowed edge emits exactly one ordered audit event; illegal edges
    raise ``IllegalTransition`` and write NO event."""
    out.mkdir(parents=True, exist_ok=True)
    audit = ShellAuditStore(out / "stores" / "shell_audit")
    session = new_session(user_id="cp2-f1")
    kernel = Kernel(session.id, audit, KernelContext(request_ref="req_f1"))

    # Walk one legal journey that touches every state at least once.
    legal_path = [
        KernelState.RECEIVED, KernelState.ROUTED, KernelState.RECALLED,
        KernelState.COMPOSED, KernelState.VIEW_VALIDATED, KernelState.RENDERED,
        KernelState.WRITE_BACK, KernelState.VIEW_VALIDATED, KernelState.RENDERED,
        KernelState.AWAITING_USER, KernelState.ACTION_GATED, KernelState.EXECUTED,
        KernelState.REMEMBERED, KernelState.CLOSED,
    ]
    events: list[dict] = []
    for state in legal_path:
        events.append(kernel.enter(state, notes=f"f1 legal walk -> {state}"))

    # Illegal transitions: probe every state pair NOT in ALLOWED. Each must
    # raise AND leave the audit event count unchanged.
    illegal_probes: list[dict] = []
    # A fresh kernel per probe so the "already CLOSED" guard does not mask the
    # edge-under-test.
    def probe(src: str, dst: str) -> dict:
        s = new_session(user_id="cp2-f1-probe")
        a = ShellAuditStore(out / "stores" / f"probe_{src}_{dst}")
        k = Kernel(s.id, a, KernelContext())
        # Walk to src legally (shortest prefix of legal_path ending at src).
        try:
            idx = legal_path.index(src)
        except ValueError:
            return {"src": src, "dst": dst, "raised": None,
                     "note": "src not on the legal walk"}
        for st in legal_path[: idx + 1]:
            k.enter(st)
        before = len(a.events(s.id))
        raised: str | None = None
        try:
            k.enter(dst)
        except IllegalTransition as exc:
            raised = str(exc)
        after = len(a.events(s.id))
        return {"src": src, "dst": dst, "raised": raised,
                 "events_before": before, "events_after": after,
                 "no_event_written": before == after and raised is not None}

    # A representative sample of illegal edges covering every family.
    illegal_pairs = [
        (KernelState.RECEIVED, KernelState.CLOSED),
        (KernelState.RECEIVED, KernelState.RENDERED),
        (KernelState.ROUTED, KernelState.EXECUTED),
        (KernelState.RENDERED, KernelState.EXECUTED),
        (KernelState.AWAITING_USER, KernelState.CLOSED),
        (KernelState.WRITE_BACK, KernelState.EXECUTED),
        (KernelState.EXECUTED, KernelState.VIEW_VALIDATED),
        (KernelState.REMEMBERED, KernelState.RENDERED),
    ]
    for src, dst in illegal_pairs:
        illegal_probes.append(probe(src, dst))

    # CLOSED is terminal: any further transition must raise.
    closed_probe = {
        "src": KernelState.CLOSED, "dst": KernelState.RENDERED,
        "raised": None, "events_before": len(audit.events(session.id)),
    }
    try:
        kernel.enter(KernelState.RENDERED)
    except IllegalTransition as exc:
        closed_probe["raised"] = str(exc)
    closed_probe["events_after"] = len(audit.events(session.id))
    closed_probe["no_event_written"] = (closed_probe["events_before"]
                                          == closed_probe["events_after"]
                                          and closed_probe["raised"] is not None)

    replay = audit.replay(session.id)
    _write_json(out / "events.json", replay["events"])
    _write_json(out / "illegal_probes.json",
                  {"probes": illegal_probes, "closed_probe": closed_probe})
    _write_json(out / "transition_table.json", transition_table())
    _write_json(out / "summary.json", {
        "gate": "F1",
        "legal_walk_length": len(legal_path),
        "events_written": len(replay["events"]),
        "sequences": replay["sequences"],
        "chain_ok": replay["chain_ok"],
        "illegal_probes": len(illegal_probes),
        "illegal_all_raised_and_wrote_no_event":
            all(p.get("no_event_written") for p in illegal_probes),
        "closed_terminal_probe": closed_probe,
    })
    return {"gate": "F1", "passed":
              len(replay["events"]) == len(legal_path)
              and replay["chain_ok"]
              and replay["sequences"] == list(range(1, len(legal_path) + 1))
              and all(p.get("no_event_written") for p in illegal_probes)
              and closed_probe["no_event_written"]}


# ========================================================= F2 route presentation
def _scaffold_l5_for_routing(l5_root: Path) -> None:
    """Same per-journey L5 scaffold ShellConnections uses, but without an L3
    engine — F2 only needs routing over a store with the fake connection
    already declared."""
    from store import DATASETS as L5_DATASETS  # L5
    for name in L5_DATASETS:
        src = FROZEN_L5_ROOT / "datasets" / name
        dst = l5_root / "datasets" / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / "schema.json", dst / "schema.json")
        if name in ("policy", "rules", "capabilities"):
            shutil.copyfile(src / "data.jsonl", dst / "data.jsonl")
        else:
            (dst / "data.jsonl").write_text("")
        (dst / "history.jsonl").write_text("")
        (dst / "bindings.jsonl").write_text("")
        (dst / "SUPERSEDED.json").write_text("[]\n")


def _declare_fake_connection(l5_root: Path, l3_root: Path) -> tuple[str, object, object]:
    """Declare the fake loopback connection through L3 (governed) and return
    (allocated_id, ShellConnections, ConnectionOperations)."""
    conns = ShellConnections(l5_root=l5_root, l3_root=l3_root,
                               frozen_l5_root=FROZEN_L5_ROOT,
                               user_id="cp2-f2", agent_id="l6-shell-cp2")
    res = conns.add(FAKE_CONFIG, intent_verbatim="F2: declare fake local connection",
                      session_id="s_f2")
    if res.action_outcome != "success":
        raise RuntimeError(f"F2 setup: connection.add failed: {res.detail}")
    return res.allocated_id, conns, conns.ops


def gate_f2(out: Path) -> dict:
    """Planned / answered (fake transport) / refused, each matched against the
    L5 decision record. Declared-vs-metered cost kept distinct; simulated
    metering is labelled."""
    out.mkdir(parents=True, exist_ok=True)
    os.environ[SECRET_ENV] = SECRET_VALUE
    net = NetworkGuard()
    cases: list[dict] = []
    try:
        with net:
            # -------- case A: dry_run → planned, metered=false ----------------
            l5a = out / "caseA" / "stores" / "l5"
            l3a = out / "caseA" / "stores" / "l3"
            mdl_a, conns_a, _ = _declare_fake_connection(l5a, l3a)
            from store import Store as L5Store  # L5
            router_a = ShellRouter(L5Store(l5a), health=Health(),
                                      policy_label=POLICY_LABEL)
            pres_a = router_a.route({"text": PROMPT, "request_id": "req_f2_a"},
                                       dry_run=True, run="cp2-f2-A")
            dec_a = L5Store(l5a).get("decision_log", pres_a.decision_ref)
            _write_json(out / "caseA" / "presentation.json", pres_a.__dict__)
            _write_json(out / "caseA" / "decision_record.json", dec_a)
            cases.append({
                "case": "A_planned", "outcome": pres_a.outcome,
                "decision_ref": pres_a.decision_ref,
                "chosen_model_ref": pres_a.chosen_model_ref,
                "declared_cost_usd": pres_a.declared_cost_usd,
                "actual_metered_cost_usd": pres_a.actual_metered_cost_usd,
                "metered": pres_a.metered,
                "meter_label": None,
                "record_outcome_matches": dec_a["outcome"] == pres_a.outcome,
                "record_decision_id_matches": dec_a["id"] == pres_a.decision_ref,
                "record_chosen_matches":
                    (dec_a.get("chosen") or {}).get("model_ref")
                    == pres_a.chosen_model_ref,
            })

            # -------- case B: fake transport → answered, metered (simulated) --
            l5b = out / "caseB" / "stores" / "l5"
            l3b = out / "caseB" / "stores" / "l3"
            mdl_b, conns_b, _ = _declare_fake_connection(l5b, l3b)
            fake = FakeTransport(script={mdl_b: ANSWERED}, default=ANSWERED)
            router_b = ShellRouter(L5Store(l5b), health=Health(),
                                      policy_label=POLICY_LABEL)
            # Reach into the L5 Router to swap in the fake transport. The shell
            # never edits L5 code; this is a per-instance attribute assignment
            # on the Router object the shell itself constructed.
            router_b._router.transport = fake
            pres_b = router_b.route({"text": PROMPT, "request_id": "req_f2_b"},
                                       dry_run=False, run="cp2-f2-B",
                                       allow_live_call=True)  # fake, not live
            dec_b = L5Store(l5b).get("decision_log", pres_b.decision_ref)
            _write_json(out / "caseB" / "presentation.json", pres_b.__dict__)
            _write_json(out / "caseB" / "decision_record.json", dec_b)
            _write_json(out / "caseB" / "fake_transport_history.json", fake.history)
            cases.append({
                "case": "B_answered_fake",
                "outcome": pres_b.outcome,
                "decision_ref": pres_b.decision_ref,
                "chosen_model_ref": pres_b.chosen_model_ref,
                "declared_cost_usd": pres_b.declared_cost_usd,
                "actual_metered_cost_usd": pres_b.actual_metered_cost_usd,
                "metered": pres_b.metered,
                "meter_label": METER_LABEL,
                "simulated_metering_labelled":
                    all(a.get("meter") == METER_LABEL
                          for a in (dec_b.get("attempts") or [])),
                "record_outcome_matches": dec_b["outcome"] == pres_b.outcome,
                "record_chosen_matches":
                    (dec_b.get("chosen") or {}).get("model_ref")
                    == pres_b.chosen_model_ref,
                "fake_calls": len(fake.history),
            })

            # -------- case C: every fake call fails → refused -----------------
            l5c = out / "caseC" / "stores" / "l5"
            l3c = out / "caseC" / "stores" / "l3"
            mdl_c, conns_c, _ = _declare_fake_connection(l5c, l3c)
            failing = FakeTransport(default=CALL_FAILED_CONNECTION)
            router_c = ShellRouter(L5Store(l5c), health=Health(),
                                      policy_label=POLICY_LABEL)
            router_c._router.transport = failing
            pres_c = router_c.route({"text": PROMPT, "request_id": "req_f2_c"},
                                       dry_run=False, run="cp2-f2-C",
                                       allow_live_call=True)
            dec_c = L5Store(l5c).get("decision_log", pres_c.decision_ref)
            _write_json(out / "caseC" / "presentation.json", pres_c.__dict__)
            _write_json(out / "caseC" / "decision_record.json", dec_c)
            cases.append({
                "case": "C_refused_all_failed",
                "outcome": pres_c.outcome,
                "refusal_reason": pres_c.refusal_reason,
                "decision_ref": pres_c.decision_ref,
                "chosen_model_ref": pres_c.chosen_model_ref,
                "declared_cost_usd": pres_c.declared_cost_usd,
                "actual_metered_cost_usd": pres_c.actual_metered_cost_usd,
                "metered": pres_c.metered,
                "record_outcome_matches": dec_c["outcome"] == pres_c.outcome,
                "record_refusal_reason_matches":
                    dec_c.get("refusal_reason") == pres_c.refusal_reason,
                "chosen_is_none": pres_c.chosen_model_ref is None,
            })
    finally:
        os.environ.pop(SECRET_ENV, None)

    _write_json(out / "cases.json", cases)
    a, b, c = cases
    passed = (
        a["outcome"] == "planned" and a["metered"] is False
        and a["actual_metered_cost_usd"] is None
        and a["record_outcome_matches"] and a["record_chosen_matches"]
        and b["outcome"] == "answered" and b["metered"] is True
        and b["actual_metered_cost_usd"] is not None
        and b["simulated_metering_labelled"]
        and b["record_outcome_matches"] and b["record_chosen_matches"]
        and c["outcome"] == "refused"
        and c["refusal_reason"] == "all_connections_failed"
        and c["chosen_is_none"]
        and c["record_outcome_matches"] and c["record_refusal_reason_matches"]
        and net.calls == 0
    )
    _write_json(out / "summary.json", {
        "gate": "F2", "cases": cases, "network_calls": net.calls,
        "passed": passed,
    })
    return {"gate": "F2", "passed": passed, "network_calls": net.calls}


# ==================================================== F3 view/edit round trip
def gate_f3(out: Path) -> dict:
    """Rendered values recompute; edits create history and visible invalidation
    before re-proof."""
    out.mkdir(parents=True, exist_ok=True)
    qroot = out / "stores" / "qafiya"
    _scaffold_qafiya_copy(qroot)
    view = _load_frozen_view()
    shell_views.validate_view(view, set(dvr_resolve.load_bindings(qroot)))
    initial_gate = qafiya_engine.provenance_gate(qroot)

    before_html = dvr_render.render(qroot, view)
    write_view_html(out / "qafiya_before.html", before_html)

    node = next(n for n in view["nodes"] if n["id"] == "cell:r_042")
    hist_before = _read_jsonl(qroot / "datasets" / "expenses" / "history.jsonl")
    # Call dvr.edits directly (NOT shell.interactions.apply_cell_edit, which
    # bundles refresh_values + provenance_gate). The gate must observe the
    # PENDING state BEFORE re-proof, exactly as the user would.
    from dvr import edits as dvr_edits
    edit_binding = dvr_edits.make_edit_binding(qroot, view["id"], node, EDIT_VALUE)
    updated_record, invalidated_count = dvr_edits.apply(qroot, edit_binding)
    hist_after = _read_jsonl(qroot / "datasets" / "expenses" / "history.jsonl")

    # Visible invalidation BEFORE re-proof: the bindings.jsonl now carries
    # PENDING checks for every binding the edit touched.
    bindings_after_edit = list(dvr_resolve.load_bindings(qroot).values())
    pending_after_edit = sum(1 for b in bindings_after_edit
                                if (b.get("check") or {}).get("provenance") == "PENDING")

    # Re-proof: refresh_values + provenance_gate → every binding PASS again.
    refreshed = qafiya_engine.refresh_values(qroot)
    final_gate = qafiya_engine.provenance_gate(qroot)
    after_html = dvr_render.render(qroot, view)
    write_view_html(out / "qafiya_after.html", after_html)

    records_after = _read_jsonl(qroot / "datasets" / "expenses" / "data.jsonl")
    q3_recomputed = round(sum(r["amount"] for r in records_after
                                  if r["period"] == "Q3"), 2)
    edited = next(r for r in records_after if r["id"] == "r_051")

    _write_json(out / "edit_result.json", {
        "edit_binding_id": edit_binding["id"],
        "updated_record": updated_record,
        "invalidated_count": invalidated_count,
    })
    _write_json(out / "history_delta.json", {
        "entries_before": len(hist_before),
        "entries_after": len(hist_after),
        "appended": hist_after[len(hist_before):],
    })
    _write_json(out / "invalidation.json", {
        "pending_after_edit_before_refresh": pending_after_edit,
        "refreshed_bindings": refreshed,
        "final_gate": final_gate,
    })
    _write_json(out / "summary.json", {
        "gate": "F3",
        "initial_gate": initial_gate,
        "history_grew_by": len(hist_after) - len(hist_before),
        "invalidated_count": invalidated_count,
        "pending_after_edit_before_refresh": pending_after_edit,
        "refreshed_bindings": refreshed,
        "final_gate": final_gate,
        "q3_recomputed_from_raw": q3_recomputed,
        "edited_record": edited,
        "before_html_has_old_total": "10346.71" in before_html,
        "after_html_has_new_total": "10481.96" in after_html,
        "after_html_clean": "UNRESOLVED" not in after_html,
    })
    passed = (
        initial_gate == 0
        and len(hist_after) - len(hist_before) >= 1
        and invalidated_count >= 1
        and pending_after_edit >= 1
        and refreshed >= 1
        and final_gate == 0
        and q3_recomputed == EXPECTED_Q3_AFTER
        and edited == {"id": "r_051", "date": "2026-08-09", "period": "Q3",
                         "amount": EDIT_VALUE, "category": "food"}
        and "10346.71" in before_html and "10481.96" in after_html
        and "UNRESOLVED" not in after_html
    )
    return {"gate": "F3", "passed": passed}


# ======================================================= F4 action authority
def gate_f4(out: Path) -> dict:
    """Approval executes only through L3; rejection and refusal produce no effect."""
    out.mkdir(parents=True, exist_ok=True)
    aroot = out / "stores" / "action"
    engine = ActionEngine(aroot)
    dispatcher = ActionDispatcher(engine)

    # --- approve path: grant + confirm_irreversible=True → executes ------------
    grant_ok = engine.issue_grant(make_grant(
        user_id="cp2", action_types=["file.create"], target_pattern="**",
        requires_confirmation=["file.create"]))
    approved = dispatcher.submit(
        intent_verbatim="F4 approve", normalized={
            "action_type": "file.create",
            "params": {"path": "f4/approved.txt", "content": "approved\n"}},
        actor={"agent_id": "cp2", "session_id": "s_f4"},
        user_id="cp2", grant_id=grant_ok["_id"], confirm_irreversible=True)
    approved_file = Path(engine.store.files_path("f4/approved.txt"))

    # --- reject-intent path: a DVR reject is recorded but does NOT execute -----
    # L3's receive_confirmation_intent records the intent on an existing record;
    # it never executes. We reuse the approved record and log a reject intent
    # against it — the file must remain exactly as the approved run wrote it.
    reject_intent = engine.receive_confirmation_intent(
        approved.action_ref, "reject", "cp2")
    approved_file_after_reject = approved_file.read_text() if approved_file.exists() else None

    # --- refusal path: no grant for the action type → refused, no file ---------
    grant_narrow = engine.issue_grant(make_grant(
        user_id="cp2", action_types=["file.create"], target_pattern="f4/approved.txt"))
    refused = dispatcher.submit(
        intent_verbatim="F4 refusal (grant too narrow)", normalized={
            "action_type": "file.create",
            "params": {"path": "f4/refused.txt", "content": "never written\n"}},
        actor={"agent_id": "cp2", "session_id": "s_f4"},
        user_id="cp2", grant_id=grant_narrow["_id"], confirm_irreversible=True)
    refused_file = Path(engine.store.files_path("f4/refused.txt"))

    # --- failure path: precondition fails (file.delete on a missing file) ------
    grant_delete = engine.issue_grant(make_grant(
        user_id="cp2", action_types=["file.delete"], target_pattern="**"))
    failed = dispatcher.submit(
        intent_verbatim="F4 failure (missing target)", normalized={
            "action_type": "file.delete",
            "params": {"path": "f4/does-not-exist.txt"}},
        actor={"agent_id": "cp2", "session_id": "s_f4"},
        user_id="cp2", grant_id=grant_delete["_id"], confirm_irreversible=True)

    _write_json(out / "approved_record.json", approved.record)
    _write_json(out / "refused_record.json", refused.record)
    _write_json(out / "failed_record.json", failed.record)
    _write_json(out / "reject_intent.json", reject_intent)
    _write_json(out / "summary.json", {
        "gate": "F4",
        "approved_outcome": approved.outcome,
        "approved_file_exists": approved_file.exists(),
        "approved_file_content": approved_file.read_text() if approved_file.exists() else None,
        "reject_intent_recorded": reject_intent.get("ok") is True,
        "reject_intent_did_not_undo_file":
            approved_file_after_reject == "approved\n",
        "refused_outcome": refused.outcome,
        "refused_reason": refused.reason,
        "refused_file_absent": not refused_file.exists(),
        "failed_outcome": failed.outcome,
        "failed_reason": failed.reason,
    })
    passed = (
        approved.outcome == "success" and approved_file.exists()
        and approved_file.read_text() == "approved\n"
        and reject_intent.get("ok") is True
        and approved_file_after_reject == "approved\n"
        and refused.outcome == "refused" and not refused_file.exists()
        and failed.outcome == "refused"
        and "preconditions_failed" in (failed.reason or "")
    )
    return {"gate": "F4", "passed": passed}


# ==================================================== F5 memory provenance
def gate_f5(out: Path) -> dict:
    """Inspection returns exactly active memory; evidence and source refs resolve."""
    out.mkdir(parents=True, exist_ok=True)
    mroot = out / "stores" / "memory"
    memory = ShellMemory(mroot)
    turn1 = memory.log_turn("s_f5", 1, "user", "F5 user prompt", 3, 0, "cp2-fake")
    turn2 = memory.log_turn("s_f5", 2, "agent", "F5 agent answer", 0, 4, "cp2-fake")
    note = memory.add_note("F5 note: both turns bound.", [turn1, turn2],
                              note_kind="summary")
    view = memory.inspect_view()
    specval.validate_view(view, memory.known_binding_ids())
    html = dvr_render.render(mroot, view)
    write_view_html(out / "memory_inspection.html", html)

    bindings = dvr_resolve.load_bindings(mroot)
    note_binding = next(b for b in bindings.values()
                          if b.get("target", {}).get("node") == f"node:{note}")
    from dvr import affordance
    evidence = affordance.evidence_panel(mroot, note_binding)
    _write_json(out / "memory_evidence.json", evidence)

    # "Exactly active memory": every row in every L4 dataset must be status=active,
    # and the inspection view must surface the note. The turn ids are NOT rendered
    # as text in the inspection view — they are bound as SOURCE refs on the note's
    # derived_from, which is the actual provenance link this gate must verify.
    note_rows = _read_jsonl(mroot / "datasets" / "longterm_notes" / "data.jsonl")
    note_row = next((r for r in note_rows if r["id"] == note), None)
    derived_from = list((note_row or {}).get("derived_from") or [])
    turns_bound_as_sources = turn1 in derived_from and turn2 in derived_from

    active_counts = {}
    for ds in memory.DATASETS:
        rows = _read_jsonl(mroot / "datasets" / ds / "data.jsonl")
        active_counts[ds] = {
            "total": len(rows),
            "active": sum(1 for r in rows if r.get("status") == "active"),
            "non_active": sum(1 for r in rows if r.get("status") != "active"),
        }
    chains = memory.verify_all_chains()

    _write_json(out / "active_counts.json", active_counts)
    _write_json(out / "chains.json", chains)
    _write_json(out / "note_provenance.json", {
        "note_id": note, "derived_from": derived_from,
        "turn1": turn1, "turn2": turn2,
        "turns_bound_as_sources": turns_bound_as_sources,
    })
    _write_json(out / "summary.json", {
        "gate": "F5",
        "turn1": turn1, "turn2": turn2, "note": note,
        "note_in_html": "F5 note: both turns bound." in html,
        "turns_bound_as_sources_on_note": turns_bound_as_sources,
        "html_clean": "UNRESOLVED" not in html,
        "evidence_binding_id_matches": evidence["binding_id"] == note_binding["id"],
        "evidence_source_row_is_note":
            evidence["source_rows"][0]["id"] == note,
        "evidence_source_rows_nonempty": len(evidence["source_rows"]) >= 1,
        "active_counts": active_counts,
        "chains": chains,
    })
    passed = (
        "F5 note: both turns bound." in html
        and turns_bound_as_sources
        and "UNRESOLVED" not in html
        and evidence["binding_id"] == note_binding["id"]
        and len(evidence["source_rows"]) >= 1
        and evidence["source_rows"][0]["id"] == note
        and all(v["non_active"] == 0 for v in active_counts.values())
        and all(chains.values())
    )
    return {"gate": "F5", "passed": passed}


# ============================================ F6 connection governance (fake)
def gate_f6(out: Path) -> dict:
    """LOCAL FAKE endpoint (loopback, never called). Add/retire/privacy_change
    produce L3 records; undo paths exercised; a grant missing the action type
    refuses with the list unchanged; a broken connection is NOT implicitly
    retired; secrets absent."""
    out.mkdir(parents=True, exist_ok=True)
    os.environ[SECRET_ENV] = SECRET_VALUE
    net = NetworkGuard()
    try:
        with net:
            l5root = out / "stores" / "l5"
            l3root = out / "stores" / "l3"
            conns = ShellConnections(l5_root=l5root, l3_root=l3root,
                                        frozen_l5_root=FROZEN_L5_ROOT,
                                        user_id="cp2-f6", agent_id="l6-shell-cp2")

            # -------- add (through L3) --------------------------------------
            add_res = conns.add(FAKE_CONFIG,
                                   intent_verbatim="F6: add fake connection",
                                   session_id="s_f6")
            allocated = add_res.allocated_id

            # -------- privacy_change → succession, undo restores prior class -
            priv_res = conns.change_privacy(allocated, new_class="public",
                                               previous_class="private",
                                               intent_verbatim="F6: relax privacy",
                                               session_id="s_f6")
            successor = priv_res.successor_ref
            priv_undo = conns.engine.undo(priv_res.action_ref)
            restored = conns.ops.get_active_successor(successor)

            # -------- undo(add) = retire the allocated id --------------------
            # The add record's undo recipe retires the allocated id, which is
            # already retired by the privacy succession. L3's undo will report
            # failure honestly (retire_connection returns False on an inactive
            # id) — the shell records that as a typed outcome, never hides it.
            add_undo = conns.engine.undo(add_res.action_ref)

            # -------- retire the restored connection (through L3) ------------
            retire_res = conns.retire(restored, FAKE_CONFIG,
                                         intent_verbatim="F6: explicit retire",
                                         session_id="s_f6")

            # -------- rejected operation: grant missing connection.retire ----
            # Build a SEPARATE engine whose grant covers only connection.add.
            l3_narrow = out / "stores" / "l3_narrow"
            narrow_engine = ActionEngine(l3_narrow, connection_ops=conns.ops)
            narrow_grant = narrow_engine.issue_grant(make_grant(
                user_id="cp2-f6", action_types=["connection.add"],
                target_pattern="mdl_*"))
            list_before_reject = [r["id"] for r in conns.list_active()]
            rejected = narrow_engine.act(
                intent_verbatim="F6: retire without grant",
                normalized={"action_type": "connection.retire",
                              "params": {"connection_id": restored,
                                           "config": FAKE_CONFIG}},
                actor={"agent_id": "l6-shell-cp2", "session_id": "s_f6"},
                user_id="cp2-f6", grant_id=narrow_grant["_id"])
            list_after_reject = [r["id"] for r in conns.list_active()]

            # -------- no implicit retirement of a broken connection ----------
            # Declare a connection whose key_env is NOT set in the environment.
            # L5's normalise() reports missing_env:<NAME> but the record stays
            # ACTIVE — the shell never auto-retires a broken entry.
            broken_env = "L6_SHELL_CP2_BROKEN_KEY_ABSENT"
            os.environ.pop(broken_env, None)
            broken_cfg = {**FAKE_CONFIG, "label": "CP2 broken (no env)",
                             "model": "cp2-broken-model", "key_env": broken_env}
            broken_add = conns.add(broken_cfg,
                                       intent_verbatim="F6: declare a broken connection",
                                       session_id="s_f6")
            broken_id = broken_add.allocated_id
            broken_status = conns.status(broken_id)
            broken_rec = conns.store.get("models", broken_id)

            # -------- secrets hygiene ----------------------------------------
            l5_leaks = _scan_tree(l5root, SECRET_VALUE)
            l3_leaks = _scan_tree(l3root, SECRET_VALUE)
            l3_narrow_leaks = _scan_tree(l3_narrow, SECRET_VALUE)
            l5_blob = json.dumps(conns.store.records("models"), sort_keys=True)
            l3_blob = json.dumps(conns.engine.records(), sort_keys=True)
            name_retained = SECRET_ENV in l5_blob and SECRET_ENV in l3_blob

            # -------- L3 records for every mutation --------------------------
            l3_records = conns.engine.records()
            mutation_types = [r["intent"]["normalized"]["action_type"]
                                 for r in l3_records]
    finally:
        os.environ.pop(SECRET_ENV, None)

    _write_json(out / "add_result.json",
                  {k: v for k, v in add_res.__dict__.items() if k != "record"})
    _write_json(out / "privacy_result.json",
                  {k: v for k, v in priv_res.__dict__.items() if k != "record"})
    _write_json(out / "privacy_undo.json", priv_undo)
    _write_json(out / "add_undo.json", add_undo)
    _write_json(out / "retire_result.json",
                  {k: v for k, v in retire_res.__dict__.items() if k != "record"})
    _write_json(out / "rejected_record.json", rejected)
    _write_json(out / "broken_status.json", broken_status)
    _write_json(out / "broken_record.json", broken_rec)
    _write_json(out / "mutation_types.json", mutation_types)
    _write_json(out / "secret_scan.json", {
        "l5_leaks": l5_leaks, "l3_leaks": l3_leaks,
        "l3_narrow_leaks": l3_narrow_leaks,
        "name_retained": name_retained,
    })
    _write_json(out / "list_before_reject.json", list_before_reject)
    _write_json(out / "list_after_reject.json", list_after_reject)

    l5_models_ok, l5_models_detail = conns.store.verify_chain("models")
    passed = (
        add_res.action_outcome == "success"
        and priv_res.action_outcome == "success"
        and isinstance(successor, str) and successor != allocated
        and priv_undo.get("ok") is True
        and isinstance(restored, str) and restored != successor
        and retire_res.action_outcome == "success"
        and rejected["outcome"]["status"] == "refused"
        and list_before_reject == list_after_reject
        and broken_rec is not None and broken_rec["status"] == "active"
        and broken_status["usable"] is False
        and any(f"missing_env:{broken_env}" in p for p in broken_status["problems"])
        and not l5_leaks and not l3_leaks and not l3_narrow_leaks
        and name_retained
        and "connection.add" in mutation_types
        and "connection.retire" in mutation_types
        and "connection.privacy_change" in mutation_types
        and l5_models_ok
        and net.calls == 0
    )
    _write_json(out / "summary.json", {
        "gate": "F6",
        "allocated": allocated, "successor": successor, "restored": restored,
        "add_undo": add_undo, "privacy_undo": priv_undo,
        "retire_outcome": retire_res.action_outcome,
        "rejected_outcome": rejected["outcome"],
        "list_unchanged_after_rejection": list_before_reject == list_after_reject,
        "broken_stays_active": broken_rec["status"] if broken_rec else None,
        "broken_problems": broken_status["problems"],
        "secret_leaks": {"l5": l5_leaks, "l3": l3_leaks,
                            "l3_narrow": l3_narrow_leaks},
        "env_name_retained": name_retained,
        "mutation_types_seen": sorted(set(mutation_types)),
        "l5_models_chain_ok": l5_models_ok,
        "network_calls": net.calls,
        "passed": passed,
    })
    return {"gate": "F6", "passed": passed, "network_calls": net.calls}


# ========================================================= F7 audit replay
def gate_f7(out: Path) -> dict:
    """Every event reference resolves; sequences complete; all owned chains verify."""
    out.mkdir(parents=True, exist_ok=True)
    # Re-run the CP1 journey on a fresh root inside F7's own output so the
    # replay has a real audit graph to resolve. Importing e2e_journey keeps a
    # single authoritative journey implementation.
    import e2e_journey
    journey_out = out / "journey"
    summary = e2e_journey.run(journey_out)
    session_id = summary["session_id"]

    audit_dir = journey_out / "stores" / "shell_audit" / "datasets" / "shell_audit"
    events = _read_jsonl(audit_dir / "data.jsonl")
    session_events = sorted((e for e in events if e["session_id"] == session_id),
                              key=lambda e: e["sequence"])
    ids = {e["id"] for e in session_events}
    unresolved_input_refs = [
        ref for e in session_events for ref in e.get("input_event_refs", [])
        if ref not in ids
    ]
    seqs = [e["sequence"] for e in session_events]
    sequences_complete = seqs == list(range(1, len(seqs) + 1))

    chains = {
        "shell_audit": qafiya_chain.verify(audit_dir / "history.jsonl"),
        "l5_models": qafiya_chain.verify(
            journey_out / "stores" / "l5" / "datasets" / "models" / "history.jsonl"),
        "l5_decision_log": qafiya_chain.verify(
            journey_out / "stores" / "l5" / "datasets" / "decision_log" / "history.jsonl"),
        "qafiya_expenses": qafiya_chain.verify(
            journey_out / "stores" / "qafiya" / "datasets" / "expenses" / "history.jsonl"),
    }
    for ds in ("session_log", "preference_store", "longterm_notes",
                 "correction_log", "deletion_log"):
        chains[f"l4_{ds}"] = qafiya_chain.verify(
            journey_out / "stores" / "memory" / "datasets" / ds / "history.jsonl")

    # Lower-layer references recorded on the audit graph must resolve in their
    # owning stores (decision_ref in L5 decision_log; action_refs in L3
    # action_log; memory_refs in L4 longterm_notes/session_log; connection_refs
    # and successor_ref in L5 models).
    l5_decisions = {r["id"] for r in _read_jsonl(
        journey_out / "stores" / "l5" / "datasets" / "decision_log" / "data.jsonl")}
    l5_models = {r["id"] for r in _read_jsonl(
        journey_out / "stores" / "l5" / "datasets" / "models" / "data.jsonl")}
    l3_actions = set()
    for store_name in ("action", "connection_actions"):
        p = journey_out / "stores" / store_name / "datasets" / "action_log" / "data.jsonl"
        if p.exists():
            for r in _read_jsonl(p):
                l3_actions.add(r.get("action_id") or r.get("_id"))
    l4_ids = set()
    for ds in ("session_log", "longterm_notes"):
        p = journey_out / "stores" / "memory" / "datasets" / ds / "data.jsonl"
        if p.exists():
            for r in _read_jsonl(p):
                l4_ids.add(r["id"])

    ref_resolution = {"decision_ref": [], "action_refs": [], "memory_refs": [],
                         "connection_refs": [], "successor_ref": []}
    for e in session_events:
        if e.get("decision_ref"):
            ref_resolution["decision_ref"].append(
                {"ref": e["decision_ref"],
                   "resolved": e["decision_ref"] in l5_decisions})
        for a in e.get("action_refs", []):
            ref_resolution["action_refs"].append(
                {"ref": a, "resolved": a in l3_actions})
        for m in e.get("memory_refs", []):
            ref_resolution["memory_refs"].append(
                {"ref": m, "resolved": m in l4_ids})
        for c in e.get("connection_refs", []):
            ref_resolution["connection_refs"].append(
                {"ref": c, "resolved": c in l5_models})
        if e.get("successor_ref"):
            ref_resolution["successor_ref"].append(
                {"ref": e["successor_ref"],
                   "resolved": e["successor_ref"] in l5_models})

    all_resolved = all(
        all(x["resolved"] for x in lst) for lst in ref_resolution.values())

    _write_json(out / "session_id.json", {"session_id": session_id})
    _write_json(out / "events.json", session_events)
    _write_json(out / "ref_resolution.json", ref_resolution)
    _write_json(out / "chains.json", {k: {"ok": v[0], "detail": v[1]}
                                         for k, v in chains.items()})
    _write_json(out / "summary.json", {
        "gate": "F7",
        "session_id": session_id,
        "event_count": len(session_events),
        "sequences_complete": sequences_complete,
        "unresolved_input_event_refs": unresolved_input_refs,
        "all_lower_layer_refs_resolved": all_resolved,
        "chains": {k: v[0] for k, v in chains.items()},
    })
    passed = (
        len(session_events) >= 12
        and sequences_complete
        and not unresolved_input_refs
        and all_resolved
        and all(v[0] for v in chains.values())
    )
    return {"gate": "F7", "passed": passed}


# ======================================================= F8 failure honesty
def _synthetic_unresolved_store(root: Path) -> Path:
    """Build a minimal, dvr/1.1-clean Qafiya store whose second binding is
    QUARANTINED via a root-level ``SUPERSEDED.json`` — a real Qafiya §9.1
    mechanism. ``dvr.resolve.resolve_binding`` then returns
    ``Unresolved("quarantined source: ...")`` for that binding and the renderer
    paints the cell as UNRESOLVED. The first binding resolves normally, so the
    fixture is not trivially all-unresolved.

    This is a purpose-built failure fixture; no frozen artifact is touched and
    no lower-layer JSON is mutated.
    """
    ds = root / "datasets" / "synthetic"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "schema.json").write_text(json.dumps({
        "dataset": "synthetic", "id_field": "id", "id_prefix": "r_",
        "fields": {"id": "id", "amount": "number", "label": "string"},
        "derivations": ["filter", "sum"],
    }, indent=1, sort_keys=True))
    (ds / "data.jsonl").write_text(
        json.dumps({"id": "r_001", "amount": 10.0, "label": "present"},
                     sort_keys=True) + "\n"
        + json.dumps({"id": "r_002", "amount": 20.0, "label": "quarantined"},
                       sort_keys=True) + "\n")
    (ds / "history.jsonl").write_text("")
    (ds / "bindings.jsonl").write_text("")
    (ds / "SUPERSEDED.json").write_text("[]\n")

    # Root-level bindings + SUPERSEDED (the layout dvr.resolve reads).
    present_binding = {
        "id": "b_present", "kind": "view",
        "target": {"view": "v_synthetic", "node": "cell:r_001"},
        "sources": [{"dataset": "ds:synthetic", "record": "r_001",
                       "field": "amount"}],
        "derivation": "sum(amount) where id='r_001'",
        "value": 10.0, "statistic": "sum", "device": "cp2-fixture",
        "authoritative_artifact": "datasets/synthetic/data.jsonl",
        "provenance": {"created_by": "cp2-f8-fixture"},
        "check": {"provenance": "PASS"},
    }
    quarantined_binding = {
        "id": "b_quarantined", "kind": "view",
        "target": {"view": "v_synthetic", "node": "cell:r_002"},
        "sources": [{"dataset": "ds:synthetic", "record": "r_002",
                       "field": "amount"}],
        "derivation": "sum(amount) where id='r_002'",
        "value": 20.0, "statistic": "sum", "device": "cp2-fixture",
        "authoritative_artifact": "datasets/synthetic/quarantined.jsonl",
        "provenance": {"created_by": "cp2-f8-fixture"},
        "check": {"provenance": "PENDING"},
    }
    (root / "bindings.jsonl").write_text(
        json.dumps(present_binding, sort_keys=True) + "\n"
        + json.dumps(quarantined_binding, sort_keys=True) + "\n")
    # Quarantine the SECOND binding's authoritative artifact. dvr.resolve
    # checks ``binding.authoritative_artifact in store.superseded_set(root)``
    # and returns Unresolved for a quarantined source.
    (root / "SUPERSEDED.json").write_text(json.dumps(
        {"superseded": ["datasets/synthetic/quarantined.jsonl"]},
        indent=1, sort_keys=True))

    view = {
        "spec": "dvr/1.1",
        "id": "v_synthetic",
        "kind": "table",
        "title": {"text": "F8 unresolved fixture (one quarantined binding)"},
        "columns": [{"id": "col:amount", "label": "Amount",
                       "source_field": "amount"}],
        "nodes": [
            {"id": "cell:r_001", "role": "value",
             "binding_ref": "b_present", "column": "col:amount"},
            {"id": "cell:r_002", "role": "value",
             "binding_ref": "b_quarantined", "column": "col:amount"},
        ],
    }
    (root / "views").mkdir(exist_ok=True)
    (root / "views" / "v_synthetic.view.json").write_text(
        json.dumps(view, indent=1, sort_keys=True))
    return root


def gate_f8(out: Path) -> dict:
    """Routed refusal, L3 failure, unresolved view and unavailable connection
    each retain a typed visible state."""
    out.mkdir(parents=True, exist_ok=True)
    os.environ[SECRET_ENV] = SECRET_VALUE
    net = NetworkGuard()
    try:
        with net:
            # -------- routed refusal (every fake call fails) -----------------
            l5r = out / "refusal" / "stores" / "l5"
            l3r = out / "refusal" / "stores" / "l3"
            mdl_r, conns_r, _ = _declare_fake_connection(l5r, l3r)
            failing = FakeTransport(default=CALL_FAILED_CONNECTION)
            from store import Store as L5Store
            router_r = ShellRouter(L5Store(l5r), health=Health(),
                                      policy_label=POLICY_LABEL)
            router_r._router.transport = failing
            pres_r = router_r.route({"text": PROMPT, "request_id": "req_f8_r"},
                                       dry_run=False, run="cp2-f8-refusal",
                                       allow_live_call=True)
            dec_r = L5Store(l5r).get("decision_log", pres_r.decision_ref)

            # -------- L3 failure (precondition fails) ------------------------
            l3f = out / "l3_failure" / "stores" / "action"
            engine_f = ActionEngine(l3f)
            grant_f = engine_f.issue_grant(make_grant(
                user_id="cp2", action_types=["file.delete"], target_pattern="**"))
            failed_f = engine_f.act(
                intent_verbatim="F8: delete a missing file",
                normalized={"action_type": "file.delete",
                              "params": {"path": "does/not/exist.txt"}},
                actor={"agent_id": "cp2-f8", "session_id": "s_f8"},
                user_id="cp2", grant_id=grant_f["_id"],
                confirm_irreversible=True)

            # -------- unresolved view (synthetic fixture) --------------------
            syn_root = out / "unresolved" / "stores" / "synthetic"
            _synthetic_unresolved_store(syn_root)
            syn_view = json.loads(
                (syn_root / "views" / "v_synthetic.view.json").read_text())
            syn_bindings = dvr_resolve.load_bindings(syn_root)
            # Validate is expected to pass (the binding exists; only its source
            # record is missing). The renderer must then show UNRESOLVED.
            specval.validate_view(syn_view, set(syn_bindings))
            syn_html = dvr_render.render(syn_root, syn_view)
            write_view_html(out / "unresolved" / "view.html", syn_html)

            # -------- unavailable connection (missing env var) ---------------
            broken_env = "L6_SHELL_CP2_F8_BROKEN_KEY_ABSENT"
            os.environ.pop(broken_env, None)
            broken_cfg = {**FAKE_CONFIG, "label": "F8 broken",
                             "model": "f8-broken-model", "key_env": broken_env}
            l5b = out / "unavailable" / "stores" / "l5"
            l3b = out / "unavailable" / "stores" / "l3"
            conns_b = ShellConnections(l5_root=l5b, l3_root=l3b,
                                          frozen_l5_root=FROZEN_L5_ROOT,
                                          user_id="cp2-f8", agent_id="l6-shell-cp2")
            broken_add = conns_b.add(broken_cfg,
                                         intent_verbatim="F8: declare a broken connection",
                                         session_id="s_f8")
            broken_id = broken_add.allocated_id
            broken_status = conns_b.status(broken_id)
            broken_rec = conns_b.store.get("models", broken_id)
    finally:
        os.environ.pop(SECRET_ENV, None)

    _write_json(out / "refusal_presentation.json", pres_r.__dict__)
    _write_json(out / "refusal_decision.json", dec_r)
    _write_json(out / "l3_failure_record.json", failed_f)
    _write_json(out / "unresolved_html_sha.json",
                  {"sha256": sha256_file(out / "unresolved" / "view.html")})
    _write_json(out / "unavailable_status.json", broken_status)
    _write_json(out / "unavailable_record.json", broken_rec)
    _write_json(out / "summary.json", {
        "gate": "F8",
        "refusal_outcome": pres_r.outcome,
        "refusal_reason": pres_r.refusal_reason,
        "refusal_chosen_none": pres_r.chosen_model_ref is None,
        "refusal_decision_record_matches":
            dec_r["outcome"] == pres_r.outcome
            and dec_r.get("refusal_reason") == pres_r.refusal_reason,
        "l3_failure_outcome": failed_f["outcome"],
        "l3_failure_reason_typed":
            "preconditions_failed" in (failed_f["outcome"].get("reason") or ""),
        "unresolved_html_contains_UNRESOLVED": "UNRESOLVED" in syn_html
            or "unresolved" in syn_html.lower(),
        "unavailable_connection_stays_active":
            broken_rec is not None and broken_rec["status"] == "active",
        "unavailable_connection_problems_typed":
            any(p.startswith("missing_env:") for p in broken_status["problems"]),
        "network_calls": net.calls,
    })
    passed = (
        pres_r.outcome == "refused"
        and pres_r.refusal_reason == "all_connections_failed"
        and pres_r.chosen_model_ref is None
        and dec_r["outcome"] == "refused"
        and dec_r.get("refusal_reason") == "all_connections_failed"
        and failed_f["outcome"]["status"] == "refused"
        and "preconditions_failed" in (failed_f["outcome"].get("reason") or "")
        and ("UNRESOLVED" in syn_html or "unresolved" in syn_html.lower())
        and broken_rec is not None and broken_rec["status"] == "active"
        and any(p.startswith("missing_env:") for p in broken_status["problems"])
        and net.calls == 0
    )
    return {"gate": "F8", "passed": passed}


# =================================================================== driver
GATES = [
    ("F1", gate_f1),
    ("F2", gate_f2),
    ("F3", gate_f3),
    ("F4", gate_f4),
    ("F5", gate_f5),
    ("F6", gate_f6),
    ("F7", gate_f7),
    ("F8", gate_f8),
]


def main() -> int:
    # Reproducibility: pin L5's HMAC key so decide.hmac_key() does not write a
    # random key into the frozen vendor snapshot and the prompt HMAC is stable.
    os.environ.setdefault("LOG_HMAC_KEY",
                            "l6-shell-deterministic-hmac-key-for-reproducibility")
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output" / "cp2"
    dest = dest.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    results: list[dict] = []
    for name, fn in GATES:
        gate_out = dest / name.lower()
        print(f"[battery] running {name} ...", flush=True)
        try:
            r = fn(gate_out)
        except Exception as exc:
            r = {"gate": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
            import traceback
            traceback.print_exc()
        results.append(r)
        print(f"[battery] {name}: {'PASS' if r.get('passed') else 'FAIL'}", flush=True)

    passed_count = sum(1 for r in results if r.get("passed"))
    summary = {
        "battery": "CP2 functional gates F1-F8",
        "python": sys.version.split()[0],
        "gates_run": len(results),
        "gates_passed": passed_count,
        "status": "PASS" if passed_count == len(results) else "FAIL",
        "results": results,
    }
    _write_json(dest / "battery-summary.json", summary)
    print(json.dumps({"status": summary["status"],
                         "gates_passed": f"{passed_count}/{len(results)}",
                         "output": str(dest)}, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
