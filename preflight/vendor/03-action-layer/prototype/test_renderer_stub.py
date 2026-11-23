#!/usr/bin/env python3
"""Test: dvr/1.1 renderer contract (fix instructions 27 Oct 2026, item 3).

Asserts:
1. render_confirmation returns a GRAMMAR-VALID dvr/1.1 spec with one action node
   (action_ref, actions=["approve","reject"]) and summary label/value nodes whose
   bindings resolve.
2. render_audit_view returns a grammar-valid dvr/1.1 spec covering the full record.
3. The grammar rejects violations (action_ref on non-action role; binding_ref on
   an action node).
4. Authority does not move: approve intent reaches the engine and is recorded,
   but execution still requires the gate + explicit confirmation parameter.
"""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from actionlayer.engine import ActionEngine
from actionlayer.gate import make_grant
from actionlayer import renderer, dvr11

def main():
    root = tempfile.mkdtemp(prefix="khatt-dvr11-test-")
    try:
        eng = ActionEngine(root)
        eng.issue_grant(make_grant(
            user_id="u", action_types=["email.draft_create", "email.send"],
            target_pattern="**", requires_confirmation=["IRREVERSIBLE"]))
        actor = {"agent_id": "t", "session_id": "t"}
        d = eng.act(intent_verbatim="draft", normalized={
            "action_type": "email.draft_create",
            "params": {"to": "sam@example.com", "subject": "s", "body": "b"}},
            actor=actor, user_id="u")
        from actionlayer.adapters import _mail_load
        did = next(iter(_mail_load(eng.store)["drafts"]))

        # 1. confirmation spec: grammar-valid, one action node, bindings resolve
        renderer.CALLS.clear()
        s = eng.act(intent_verbatim="send it", normalized={
            "action_type": "email.send", "params": {"draft_id": did}},
            actor=actor, user_id="u", confirm_irreversible=True)
        assert s["outcome"]["status"] == "success", s["outcome"]
        assert ("render_confirmation", s["action_id"]) in renderer.CALLS
        spec = renderer.render_confirmation(s, eng.store)
        dvr11.validate_view(spec, known_binding_ids=renderer._known_bindings(eng.store))
        action_nodes = [n for n in spec["nodes"] if n["role"] == "action"]
        assert len(action_nodes) == 1 and action_nodes[0]["action_ref"] == s["action_id"]
        assert action_nodes[0]["actions"] == ["approve", "reject"]
        assert "binding_ref" not in action_nodes[0] and not action_nodes[0].get("editable")
        val_nodes = [n for n in spec["nodes"] if n["role"] == "value"]
        assert val_nodes and all("binding_ref" in n for n in val_nodes), "summary must be bound values"

        # 2. audit view: grammar-valid, covers the full record
        av = renderer.render_audit_view(s, eng.store)
        dvr11.validate_view(av, known_binding_ids=renderer._known_bindings(eng.store))
        bound_fields = {n["id"] for n in av["nodes"] if n["role"] == "value"}
        for needed in ("val:permission_scope", "val:preconditions", "val:outcome",
                       "val:undo_status", "val:undo_recipe"):
            assert needed in bound_fields, f"audit view missing {needed}"

        # 3. grammar rejects violations
        for bad in (
            {"spec": "dvr/1.1", "id": "v_x", "kind": "list", "nodes": [
                {"id": "n1", "role": "value", "action_ref": "a_1", "binding_ref": "b_1"}]},
            {"spec": "dvr/1.1", "id": "v_x", "kind": "list", "nodes": [
                {"id": "n1", "role": "action", "action_ref": "a_1", "actions": ["approve"],
                 "binding_ref": "b_1"}]},
        ):
            try:
                dvr11.validate_view(bad)
                raise AssertionError(f"grammar accepted invalid spec: {bad['nodes'][0]}")
            except dvr11.SpecError:
                pass

        # 4. authority does not move: intent reaches engine, execution still gated
        d2 = eng.act(intent_verbatim="draft2", normalized={
            "action_type": "email.draft_create",
            "params": {"to": "sam@example.com", "subject": "s", "body": "b"}},
            actor=actor, user_id="u")
        did2 = next(k for k in _mail_load(eng.store)["drafts"] if k != did)
        pend = eng.act(intent_verbatim="send without confirming", normalized={
            "action_type": "email.send", "params": {"draft_id": did2}},
            actor=actor, user_id="u")
        assert pend["outcome"]["status"] == "refused"  # gate: confirmation required
        r = eng.receive_confirmation_intent(pend["action_id"], "approve", "u")
        assert r["ok"] and "no execution" in r["detail"]
        rec = next(x for x in eng.records() if x["action_id"] == pend["action_id"])
        assert rec["confirmations"][-1]["choice"] == "approve"
        assert rec["outcome"]["status"] == "refused", \
            "approve intent must NOT execute — execution requires act() + gate"
        from actionlayer.adapters import _mail_load as ml
        assert len(ml(eng.store)["sent"]) == 1, "only the confirmed send may exist"

        print("PASS: dvr/1.1 confirmation + audit specs valid; violations rejected; "
              "intent path recorded without executing")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
