"""dvr/1.1 grammar validation for Layer 3 (temporary local copy).

dvr/1.1 = dvr/1.0 (strict superset) + the `action` node role:
  - action node: MUST have action_ref + actions[]; MUST NOT have binding_ref/editable.
  - spec string is "dvr/1.1".

Layer 2 is implementing the frozen validator (see 02-view-renderer/dvr-1.1-delta.md).
When it ships, this module is replaced by an import of theirs. Until then this
implements the delta over the copied dvr/1.0 validator (integration/dvr/specval.py)
exactly as specified in the delta.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "integration"))
from dvr.specval import SpecError  # noqa: E402  (L2's dvr/1.0 error type)

KINDS = {"table", "list", "tree", "deck"}
ROLES = {"value", "label", "claim", "structure", "action"}
NODE_KEYS = {"id", "role", "binding_ref", "action_ref", "actions", "column",
             "row_key", "path", "slide", "slot", "text", "editable", "children"}
VIEW_KEYS = {"spec", "id", "kind", "title", "columns", "nodes"}
FORBIDDEN_NODE_KEYS = {"value", "data", "number", "amount", "result"}


def validate_view(view: dict, known_binding_ids=None) -> dict:
    """Validate a dvr/1.1 view spec. Returns it unchanged if valid; raises SpecError."""
    unknown = set(view) - VIEW_KEYS
    if unknown:
        raise SpecError(f"unknown view keys: {sorted(unknown)}")
    if view.get("spec") != "dvr/1.1":
        raise SpecError(f"spec must be 'dvr/1.1', got {view.get('spec')!r}")
    vid = view.get("id", "")
    if not (isinstance(vid, str) and vid.startswith("v_")):
        raise SpecError(f"view id must start with 'v_', got {vid!r}")
    if view.get("kind") not in KINDS:
        raise SpecError(f"kind must be one of {sorted(KINDS)}, got {view.get('kind')!r}")
    if view["kind"] == "table" and "columns" not in view:
        raise SpecError("kind=table requires columns[]")

    nodes = view.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise SpecError("nodes must be a non-empty list")

    seen = set()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            raise SpecError("node missing id")
        if nid in seen:
            raise SpecError(f"duplicate node id: {nid}")
        seen.add(nid)

        unknown = set(n) - NODE_KEYS
        if unknown & FORBIDDEN_NODE_KEYS:
            raise SpecError(f"node {nid}: embedded data values forbidden: {sorted(unknown & FORBIDDEN_NODE_KEYS)}")
        if unknown:
            raise SpecError(f"node {nid}: unknown keys: {sorted(unknown)}")

        role = n.get("role")
        if role not in ROLES:
            raise SpecError(f"node {nid}: role must be one of {sorted(ROLES)}, got {role!r}")

        # dvr/1.1 delta 1 — action role rules
        if role == "action":
            if "action_ref" not in n:
                raise SpecError(f"node {nid}: role=action requires action_ref")
            if "binding_ref" in n:
                raise SpecError(f"node {nid}: role=action must not carry binding_ref")
            if n.get("editable"):
                raise SpecError(f"node {nid}: role=action must not be editable")
            acts = n.get("actions")
            if not (isinstance(acts, list) and acts and all(isinstance(a, str) for a in acts)):
                raise SpecError(f"node {nid}: role=action requires non-empty actions[] of strings")
            continue
        if "action_ref" in n:
            raise SpecError(f"node {nid}: action_ref is only valid on role=action")

        has_ref = "binding_ref" in n
        if role in ("value", "claim") and not has_ref:
            raise SpecError(f"node {nid}: role={role} requires binding_ref")
        if role in ("label", "structure") and has_ref:
            raise SpecError(f"node {nid}: role={role} must not carry binding_ref")
        if role == "claim" and n.get("editable"):
            raise SpecError(f"node {nid}: claim nodes are never editable")
        if n.get("editable") and role != "value":
            raise SpecError(f"node {nid}: only value nodes may be editable")
        if has_ref and known_binding_ids is not None and n["binding_ref"] not in known_binding_ids:
            raise SpecError(f"node {nid}: binding_ref {n['binding_ref']!r} does not resolve to an existing binding")

    return view
