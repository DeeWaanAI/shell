#!/usr/bin/env python3
"""Cross-render integration check: L4 inspect_view() through L2's dvr renderer.
Per fix-addendum-27-oct-2026: L4 emits derivation='literal'; L2's resolver is
adding the literal branch. This test reports BOTH states honestly:
  (1) stock L2 resolver (literal branch not yet landed) -> documents the gap;
  (2) addendum-conformant resolver (literal rule applied per the addendum text)
      -> the acceptance check for L4's side: no UNRESOLVED, content renders.
Run: python3 test_cross_render.py  (exit 0 iff check (2) passes)"""
import sys, tempfile, shutil, json
from pathlib import Path

HERE = Path(__file__).parent
# canonical qafiya-core FIRST: L2's renderer needs qafiya_core.derivations/store;
# our vendored package (chain only) must not shadow it. memory.py's chain import
# resolves to the canonical module — same v1.3 content as our vendored copy.
sys.path.insert(0, "/Users/youssefhariri/Documents/ideas_2026 copy 2/DeewaanAI OS/02-view-renderer/qafiya-ref/qafiya-core")
sys.path.insert(1, str(HERE))
from memory import Store

L2 = "/Users/youssefhariri/Documents/ideas_2026 copy 2/DeewaanAI OS/02-view-renderer/view-renderer"
sys.path.insert(0, L2)
from dvr import render, resolve

d = tempfile.mkdtemp(prefix="memx_")
s = Store(d)
t = s.log_turn("s", 1, "user", "I prefer metric and tea.", 7, 0, "m")
s.add_preference("units", "metric", [t], "user-stated")
s.add_preference("beverage", "tea", [t], "inferred", 0.7)
s.add_note("User prefers metric units.", [t])
view = s.inspect_view()

def run(label):
    html = render.render(Path(d), view)
    unresolved = html.count("[unresolved:")
    print(f"\n--- {label} ---")
    print(f"UNRESOLVED nodes: {unresolved}")
    print(f"contains 'metric': {'metric' in html} | contains 'tea': {'tea' in html}")
    return html, unresolved

# (1) stock L2 resolver — literal branch status as found
h1, u1 = run("(1) stock L2 resolver")

# (2) addendum-conformant resolver: derivation='literal' returns binding.value
# verbatim (addendum rule; provenance/supersede checks unchanged)
_orig = resolve.resolve_binding
def addendum_resolve(root, binding):
    if binding.get("derivation") == "literal":
        artifact = binding.get("authoritative_artifact", "")
        from qafiya_core import store as qstore
        if artifact and artifact in qstore.superseded_set(root):
            return resolve.Unresolved(f"quarantined source: {artifact}"), "UNRESOLVED"
        if not binding.get("sources"):
            return resolve.Unresolved("literal binding without sources"), "UNRESOLVED"
        state = (binding.get("check") or {}).get("provenance", "PENDING")
        return binding.get("value"), state
    return _orig(root, binding)
resolve.resolve_binding = addendum_resolve
h2, u2 = run("(2) addendum-conformant resolver (literal rule applied)")
ok = u2 == 0 and "metric" in h2 and "tea" in h2
print(f"\n{'PASS' if ok else 'FAIL'}: L4 emission renders fully under the addendum rule"
      + ("" if u1 == 0 else f"  (stock L2 resolver still returns {u1} UNRESOLVED until L2 lands the literal branch)"))
shutil.rmtree(d)
sys.exit(0 if ok else 1)
