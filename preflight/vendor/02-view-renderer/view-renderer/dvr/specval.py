#!/usr/bin/env python3
"""dvr/1.0 + dvr/1.1 grammar validator — spec §2 + dvr-1.1-delta §1.
Fail loud, never guess. dvr/1.1 is a strict superset: every valid 1.0 spec is valid 1.1.
1.1 adds the `action` role (binds to an L3 action record; the view emits intent, never executes)."""
KINDS = {"table", "list", "tree", "deck"}
SPECS = {"dvr/1.0", "dvr/1.1"}
ROLES = {"value", "label", "claim", "structure"}
ROLES_11 = ROLES | {"action"}
NODE_KEYS = {"id", "role", "binding_ref", "column", "row_key", "path", "slide",
             "slot", "text", "editable", "children", "action_ref", "actions"}
VIEW_KEYS = {"spec", "id", "kind", "title", "columns", "nodes"}
# data-bearing literals forbidden on nodes (spec §2.3 rule 3)
FORBIDDEN_NODE_KEYS = {"value", "data", "number", "amount", "result"}


class SpecError(ValueError):
    pass


def validate_view(view: dict, known_binding_ids=None) -> dict:
    """Validate a view spec. Returns the view unchanged if valid; raises SpecError otherwise.
    known_binding_ids: optional set of existing binding ids for reference checking."""
    unknown = set(view) - VIEW_KEYS
    if unknown:
        raise SpecError(f"unknown view keys: {sorted(unknown)}")
    spec = view.get("spec")
    if spec not in SPECS:
        raise SpecError(f"spec must be one of {sorted(SPECS)}, got {spec!r}")
    roles = ROLES_11 if spec == "dvr/1.1" else ROLES
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
        if role not in roles:
            raise SpecError(f"node {nid}: role must be one of {sorted(roles)}, got {role!r}"
                            + ("" if spec == "dvr/1.1" else " (dvr/1.1 adds 'action')"))

        has_ref = "binding_ref" in n
        has_action = "action_ref" in n
        if role in ("value", "claim") and not has_ref:
            raise SpecError(f"node {nid}: role={role} requires binding_ref")
        if role in ("label", "structure") and has_ref:
            raise SpecError(f"node {nid}: role={role} must not carry binding_ref")

        # dvr/1.1 action-role rules (delta §1)
        if role == "action":
            if not has_action:
                raise SpecError(f"node {nid}: role=action requires action_ref")
            if has_ref:
                raise SpecError(f"node {nid}: action nodes must not carry binding_ref")
            if n.get("editable"):
                raise SpecError(f"node {nid}: action nodes are never editable")
            acts = n.get("actions")
            if not (isinstance(acts, list) and acts and all(isinstance(a, str) for a in acts)):
                raise SpecError(f"node {nid}: action nodes require a non-empty actions list")
        elif has_action:
            raise SpecError(f"node {nid}: action_ref is only valid on role=action")

        if role == "claim" and n.get("editable"):
            raise SpecError(f"node {nid}: claim nodes are never editable")
        if n.get("editable") and role != "value":
            raise SpecError(f"node {nid}: only value nodes may be editable")

        if has_ref and known_binding_ids is not None and n["binding_ref"] not in known_binding_ids:
            raise SpecError(f"node {nid}: binding_ref {n['binding_ref']!r} does not resolve to an existing binding")

    return view

# dvr/1.1 addendum (2026-10-27): "literal" is a legal derivation value on bindings
# (memory content is evidence, not a computation). This validates BINDINGS,
# complementing validate_view for view specs.
def validate_binding(binding: dict) -> dict:
    """Accept a Qafiya binding for rendering. Raises SpecError on violation."""
    der = binding.get("derivation")
    if der is None:
        raise SpecError(f"binding {binding.get('id')}: missing derivation")
    if der == "literal":
        if not binding.get("sources"):
            raise SpecError(f"binding {binding.get('id')}: literal requires non-empty sources")
        if "value" not in binding:
            raise SpecError(f"binding {binding.get('id')}: literal requires a value")
        return binding
    # derived bindings must use the Qafiya closed derivation set
    from qafiya_core import derivations
    try:
        derivations.parse(der)
    except derivations.DerivationError as e:
        raise SpecError(f"binding {binding.get('id')}: {e}")
    return binding
