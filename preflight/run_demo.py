#!/usr/bin/env python3
"""L6 pre-flight: one prompt across Qafiya, L2, L3, and L4.

Only frozen public interfaces are called. Inputs are copied before mutation.
"""
import sys

if sys.version_info < (3, 12):
    sys.exit(
        "L6 pre-flight requires Python 3.12+ (frozen under CPython 3.12.8); "
        f"found {sys.version.split()[0]}. Run: python3.12 preflight/run_demo.py"
    )

import hashlib
import json
import shutil
from pathlib import Path

P = Path(__file__).resolve().parent

def write_view_html(path, fragment, title="DeeWaanAI OS"):
    """Write a standalone, user-openable view as a FULL UTF-8 HTML document.

    The dvr renderer emits a clean-UTF-8 *fragment* (no doctype/head). Written bare to a
    .html file, browsers fall back to a legacy encoding and mangle non-ASCII characters
    (mojibake: 'Â£', 'â–¸'). Wrapping in a full document with an explicit charset fixes it.
    """
    doc = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
           "<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
           f"<title>{title}</title>\n</head>\n<body>\n{fragment}\n</body>\n</html>\n")
    Path(path).write_text(doc, encoding="utf-8")
    return Path(path)

V = P / "vendor"
INPUTS = P / "inputs"
sys.path.insert(0, str(V / "04-memory/prototype"))
sys.path.insert(0, str(V / "03-action-layer/prototype"))
sys.path.insert(0, str(V / "02-view-renderer/view-renderer"))
sys.path.insert(0, str(V / "02-view-renderer/qafiya-ref/qafiya-core"))

from dvr import affordance, edits, render, resolve, specval
from qafiya_core import engine as qafiya_engine, store as qafiya_store
from actionlayer.engine import ActionEngine
from actionlayer.gate import make_grant
from actionlayer import renderer as action_renderer
from memory import Store as MemoryStore, DATASETS as MEMORY_DATASETS

PROMPT = "Change the 9 August Q3 food expense to 956.14, create an audit note, and remember what happened."
EDIT_VALUE = 956.14
EXPECTED_Q3_AFTER = 10481.96


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(out):
    out = Path(out).resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    checks = []
    log_path = out / "journey.jsonl"
    log_rows = []

    def check(name, condition, detail):
        checks.append({"name": name, "pass": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    def bound(step, value, sources):
        row = {
            "id": f"b_journey_{len(log_rows) + 1:02d}",
            "kind": "journey",
            "derivation": "literal",
            "value": value,
            "sources": [{"artifact": s} for s in sources],
            "provenance": {"created_by": "l6-preflight", "step": step},
        }
        log_rows.append(row)
        log_path.write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in log_rows))
        return row

    # 1. Prompt and the frozen, real Qafiya corpus.
    bound("prompt", {"verbatim": PROMPT}, ["inputs/qafiya_corpus/manifest.json"])
    qroot = out / "stores/qafiya"
    shutil.copytree(INPUTS / "qafiya_corpus/datasets", qroot / "datasets")
    shutil.copy2(INPUTS / "qafiya_corpus/bindings.jsonl", qroot / "bindings.jsonl")
    view = json.loads((INPUTS / "qafiya_corpus/views/v_exp.view.json").read_text())
    specval.validate_view(view, set(resolve.load_bindings(qroot)))
    check("frozen_input_intact", sha256(INPUTS / "qafiya_corpus/datasets/expenses/data.jsonl") ==
          "1cb5f2ad614b683e2065ddcd482ea6da7515a6b646cf33e9edb1a4725c197341", "Qafiya data hash")
    check("initial_gate", qafiya_engine.provenance_gate(qroot) == 0, "all fixture bindings recompute")
    before_html = render.render(qroot, view)
    write_view_html(out / "qafiya_before.html", before_html)
    check("qafiya_render", "10346.71" in before_html and "coverage: 100%" in before_html,
          "L2 renders the real expense view at full provenance coverage")
    bound("qafiya_render", {"view_id": view["id"], "artifact": "qafiya_before.html"}, ["b_tot_q3"])

    # 2. The claim's one-click evidence payload, resolved live.
    bindings = resolve.load_bindings(qroot)
    evidence = affordance.evidence_panel(qroot, bindings["b_count"])
    write_json(out / "qafiya_evidence.json", evidence)
    check("evidence_affordance", evidence["binding_id"] == "b_count" and
          len(evidence["source_rows"]) == 21 and evidence["focus"]["sides"]["Q3"]["value"] == 21.0,
          "binding, check, and 21 verbatim Q3 rows returned")
    bound("evidence", {"binding_ref": "b_count", "source_rows": 21}, ["b_count"])

    # 3. A real cell edit through dvr edits -> qafiya-core write-back.
    node = next(n for n in view["nodes"] if n["id"] == "cell:r_042")
    edit = edits.make_edit_binding(qroot, view["id"], node, EDIT_VALUE)
    updated, invalidated = edits.apply(qroot, edit)
    qafiya_engine.refresh_values(qroot)
    check("edit_gate", qafiya_engine.provenance_gate(qroot) == 0, "edited values recompute")
    after_html = render.render(qroot, view)
    write_view_html(out / "qafiya_after.html", after_html)
    history = read_jsonl(qroot / "datasets/expenses/history.jsonl")
    check("cell_writeback", updated["id"] == "r_051" and updated["amount"] == EDIT_VALUE and
          updated["category"] == "food" and updated["date"] == "2026-08-09" and
          invalidated >= 1 and history[-1]["edit_binding"] == edit["id"],
          "r_051 amount changed atomically with chained history and invalidation")
    check("edited_rerender", "10481.96" in after_html and "coverage: 100%" in after_html,
          "Q3 total recomputed to 10481.96 after the edit")
    bound("cell_edit", {"edit_binding": edit["id"], "record_id": "r_051", "new_value": EDIT_VALUE,
                        "invalidated": invalidated}, [edit["id"], "b_cell_r42"])

    # 4. Render L3's frozen battery record through the real L2 renderer.
    battery_root = out / "stores/frozen_battery"
    shutil.copytree(INPUTS / "l3_battery/A40", battery_root)
    battery_engine = ActionEngine(battery_root)
    battery_record = battery_engine.records()[0]
    battery_confirmation = action_renderer.render_confirmation(battery_record, battery_engine.store)
    battery_audit = action_renderer.render_audit_view(battery_record, battery_engine.store)
    specval.validate_view(battery_confirmation, set(resolve.load_bindings(battery_root)))
    specval.validate_view(battery_audit, set(resolve.load_bindings(battery_root)))
    battery_confirmation_html = render.render(battery_root, battery_confirmation)
    battery_audit_html = render.render(battery_root, battery_audit)
    write_view_html(out / "battery_confirmation.html", battery_confirmation_html)
    write_view_html(out / "battery_audit.html", battery_audit_html)
    battery_evidence = affordance.evidence_for_action(battery_root, battery_record["action_id"])
    write_json(out / "battery_action_evidence.json", battery_evidence)
    check("frozen_action_confirmation", "UNRESOLVED" not in battery_confirmation_html and
          battery_record["intent"]["verbatim"] in battery_confirmation_html and
          "data-choice=\"approve\"" in battery_confirmation_html,
          "A40 frozen action record renders with approve/reject controls")
    check("frozen_action_audit", "UNRESOLVED" not in battery_audit_html and
          battery_record["action_id"] in battery_audit_html and battery_evidence["found"],
          "A40 audit and full-record evidence resolve")
    bound("frozen_action_views", {"action_ref": battery_record["action_id"],
                                  "confirmation_view": battery_confirmation["id"],
                                  "audit_view": battery_audit["id"]}, [battery_record["action_id"]])

    # 5. Journey action: L3 invokes its DVR confirmation; its gate executes only after approval.
    aroot = out / "stores/action"
    action_engine = ActionEngine(aroot)
    action_renderer.CALLS.clear()
    grant = action_engine.issue_grant(make_grant(
        user_id="youssef", action_types=["file.create"], target_pattern="**",
        requires_confirmation=["file.create"]))
    note_content = (f"Q3 expense r_051 changed to {EDIT_VALUE:.2f}; "
                    f"Q3 total recomputed to {EXPECTED_Q3_AFTER:.2f}.\n")
    action = action_engine.act(
        intent_verbatim=PROMPT,
        normalized={"action_type": "file.create", "params": {
            "path": "audit/q3-expense-edit.txt", "content": note_content}},
        actor={"agent_id": "l6-preflight", "session_id": "s_l6_preflight"},
        user_id="youssef", grant_id=grant["_id"], confirm_irreversible=True)
    confirmation = action_renderer.render_confirmation(action, action_engine.store)
    audit = action_renderer.render_audit_view(action, action_engine.store)
    confirmation_html = render.render(aroot, confirmation)
    audit_html = render.render(aroot, audit)
    write_view_html(out / "action_confirmation.html", confirmation_html)
    write_view_html(out / "action_audit.html", audit_html)
    write_json(out / "action_record.json", action)
    action_evidence = affordance.evidence_for_action(aroot, action["action_id"])
    write_json(out / "action_evidence.json", action_evidence)
    check("action_confirmed", ("render_confirmation", action["action_id"]) in action_renderer.CALLS and
          action["outcome"]["status"] == "success" and len(action["confirmations"]) == 1 and
          Path(action_engine.store.files_path("audit/q3-expense-edit.txt")).read_text() == note_content,
          "rendered confirmation path ran and the deterministic gate executed the approved action")
    check("action_views", "UNRESOLVED" not in confirmation_html and "UNRESOLVED" not in audit_html and
          "data-choice=\"approve\"" in confirmation_html and action_evidence["found"],
          "journey confirmation, audit, and action evidence all resolve")
    bound("confirmed_action", {"action_ref": action["action_id"], "grant_ref": grant["_id"],
                               "status": action["outcome"]["status"]},
          [action["action_id"], grant["_id"], edit["id"]])

    # 6. L4 stores the journey as provenance-carrying turns and a derived note.
    mroot = out / "stores/memory"
    memory = MemoryStore(mroot)
    user_turn = memory.log_turn("s_l6_preflight", 1, "user", PROMPT, 22, 0, "l6-preflight")
    agent_text = (f"Edited r_051 to {EDIT_VALUE:.2f}; confirmed action {action['action_id']} "
                  f"created audit/q3-expense-edit.txt.")
    agent_turn = memory.log_turn("s_l6_preflight", 2, "agent", agent_text, 0, 31, "l6-preflight")
    note = (f"Pre-flight journey: edit {edit['id']} set r_051 to {EDIT_VALUE:.2f}; "
            f"action {action['action_id']} succeeded after confirmation.")
    memory_note = memory.add_note(note, [user_turn, agent_turn], "summary")
    memory_view = memory.inspect_view()
    specval.validate_view(memory_view, memory.known_binding_ids())
    memory_html = render.render(mroot, memory_view)
    write_view_html(out / "memory_inspection.html", memory_html)
    memory_bindings = resolve.load_bindings(mroot)
    memory_binding = next(b for b in memory_bindings.values()
                          if b.get("target", {}).get("node") == f"node:{memory_note}")
    memory_evidence = affordance.evidence_panel(mroot, memory_binding)
    write_json(out / "memory_evidence.json", memory_evidence)
    check("memory_inspection", note in memory_html and "UNRESOLVED" not in memory_html and
          "▸evidence" in memory_html and memory_evidence["source_rows"][0]["id"] == memory_note and
          all(memory.verify_chain(ds) for ds in MEMORY_DATASETS),
          "L4 note and provenance render through L2; all memory chains verify")
    bound("memory", {"memory_ref": memory_note, "session_refs": [user_turn, agent_turn],
                     "inspection_view": memory_view["id"]},
          [memory_note, user_turn, agent_turn, action["action_id"]])

    summary = {
        "journey": PROMPT,
        "status": "PASS",
        "checks_passed": len(checks),
        "checks": checks,
        "refs": {"edit": edit["id"], "action": action["action_id"], "memory": memory_note,
                 "battery_action": battery_record["action_id"]},
        "values": {"edited_record": "r_051", "edited_amount": EDIT_VALUE,
                   "q3_total_after": EXPECTED_Q3_AFTER, "evidence_rows": 21},
        "bound_records": len(log_rows),
    }
    write_json(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else P / "output/frozen"
    result = run(destination)
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"],
                      "bound_records": result["bound_records"], "output": str(destination)}, indent=2))
