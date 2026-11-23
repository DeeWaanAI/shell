#!/usr/bin/env python3
"""Direct L3 confirmation -> L2 render contract probe; no adapters."""
import shutil
import sys
from pathlib import Path

P = Path(__file__).resolve().parent
V = P / "vendor"
sys.path.insert(0, str(V / "02-view-renderer/qafiya-ref/qafiya-core"))
sys.path.insert(0, str(V / "02-view-renderer/view-renderer"))
sys.path.insert(0, str(V / "03-action-layer/prototype"))

from actionlayer.engine import ActionEngine
from actionlayer.gate import make_grant
from actionlayer import renderer as l3_renderer
from dvr import render as l2_render

root = P / "probe-output/l3-l2"
shutil.rmtree(root, ignore_errors=True)
engine = ActionEngine(root)
engine.issue_grant(make_grant(user_id="preflight", action_types=["file.create"], target_pattern="**"))
record = engine.act(
    intent_verbatim="Create a pre-flight note",
    normalized={"action_type": "file.create", "params": {"path": "note.txt", "content": "hello\n"}},
    actor={"agent_id": "preflight", "session_id": "s_preflight"},
    user_id="preflight",
)
view = l3_renderer.render_confirmation(record, engine.store)
html = l2_render.render(root, view)
print(html)
assert "UNRESOLVED" not in html, "L3 confirmation contains unresolved nodes in L2"
assert record["intent"]["verbatim"] in html, "L2 did not render the requested action text"
