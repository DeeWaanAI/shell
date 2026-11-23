#!/usr/bin/env python3
"""Cross-render acceptance test (fix-addendum-2-29-oct-2026).

Runs L3's real render_confirmation AND render_audit_view through L2's REAL
renderer (integration/dvr — copied from 02-view-renderer). Required:
no exception, no UNRESOLVED, real action content visible.
"""
import os, shutil, sys, tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "integration"))
sys.path.insert(0, os.path.join(ROOT, "integration", "qafiya_core", "qafiya-core"))

from actionlayer.engine import ActionEngine
from actionlayer.gate import make_grant
from actionlayer import renderer
from dvr.render import render as l2_render

def main():
    root = tempfile.mkdtemp(prefix="khatt-xrender-")
    try:
        eng = ActionEngine(root)
        eng.issue_grant(make_grant(
            user_id="u", action_types=["file.edit", "file.create", "email.draft_create",
                                       "email.send"],
            target_pattern="**", requires_confirmation=["IRREVERSIBLE"]))
        actor = {"agent_id": "t", "session_id": "t"}
        os.makedirs(eng.store.files_path("reports"), exist_ok=True)
        open(eng.store.files_path("reports/q3.txt"), "w").write("Q3 v1\n")
        rec = eng.act(intent_verbatim="fix the Q3 numbers",
                      normalized={"action_type": "file.edit",
                                  "params": {"path": "reports/q3.txt",
                                             "content": "Q3 v2\n"}},
                      actor=actor, user_id="u")
        assert rec["outcome"]["status"] == "success"

        for spec_fn in (renderer.render_confirmation, renderer.render_audit_view):
            spec = spec_fn(rec, eng.store)
            html = l2_render(Path(eng.store.root), spec)  # the real L2 renderer
            assert "[unresolved" not in html and "UNRESOLVED" not in html, \
                f"{spec_fn.__name__}: UNRESOLVED in output"
            assert "fix the Q3 numbers" in html, "verbatim intent not visible"
            assert rec["action_id"] in html, "action id not visible"
        av = l2_render(Path(eng.store.root), renderer.render_audit_view(rec, eng.store))
        assert "success" in av, "outcome not visible in audit view"
        print("PASS: L3 confirmation + audit specs render through L2's real renderer —")
        print("      no exception, no UNRESOLVED, intent/action id/outcome visible")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
