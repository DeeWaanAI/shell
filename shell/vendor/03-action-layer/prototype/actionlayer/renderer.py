"""Layer-2 renderer binding — dvr/1.1 (fix instructions 27 Oct 2026, option A).

Implements the interface the action layer consumes from the view renderer:

    render_confirmation(record, store) -> dvr/1.1 view spec
    render_audit_view(record, store)   -> dvr/1.1 view spec

Rules honored:
- The view only emits intent. Execution still requires the engine's explicit
  confirmation parameter and the deterministic gate (authority does not move).
- Confirmation spec contains one `action` node (action_ref = action record id,
  actions = ["approve", "reject"]) plus the action summary as label/value nodes
  whose values live behind bindings (dvr rule: no data literals on nodes).
- Action records are Qafiya records, so the evidence affordance (full record:
  intent, scope, preconditions, undo recipe) works unchanged.
- CALLS is a test-visible log so tests can assert the interface is invoked.

Bindings are registered idempotently in datasets/action_log/bindings.jsonl
(Qafiya §8) so L2's loader discovers them (dvr/1.1 delta 2).
"""
import hashlib, json, os
from . import dvr11

CALLS = []

def _binding_id(action_id, field):
    h = hashlib.sha256(f"{action_id}:{field}".encode()).hexdigest()[:10]
    return f"b_{h}"

def _field_value(record, dotpath):
    """Resolve a dot-path (e.g. 'intent.verbatim') against the record at emission."""
    cur = record
    for seg in dotpath.split("."):
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur

def _ensure_binding(store, record, field):
    """Qafiya-shaped binding (dvr/1.1 addendum 2): kind=view, sources non-empty,
    derivation='literal', value = field content resolved at emission. The value
    is refreshed when the record's field changes (records evolve over lifecycle)."""
    bp = os.path.join(store._dataset_dir("action_log"), "bindings.jsonl")
    aid = record["action_id"]
    bid = _binding_id(aid, field)
    rec = {"id": bid, "kind": "view",
           "sources": [{"dataset": "ds:action_log", "field": field}],
           "derivation": "literal", "value": _field_value(record, field)}
    bindings = []
    if os.path.exists(bp):
        bindings = [json.loads(l) for l in open(bp) if l.strip()]
    bindings = [b for b in bindings if b.get("id") != bid]
    bindings.append(rec)
    with open(bp, "w") as f:
        for b in bindings:
            f.write(json.dumps(b, sort_keys=True) + "\n")
    return bid

def _lv(store, record, field, label):
    """A label node + a value node bound to the record field."""
    bid = _ensure_binding(store, record, field)
    return [{"id": f"lbl:{field}", "role": "label", "text": label},
            {"id": f"val:{field}", "role": "value", "binding_ref": bid}]

def render_confirmation(record, store):
    """dvr/1.1 confirmation spec for a pending action. Display path only."""
    CALLS.append(("render_confirmation", record["action_id"]))
    aid = record["action_id"]
    nodes = []
    nodes += _lv(store, record, "intent.verbatim", "Requested")
    nodes += _lv(store, record, "intent.normalized", "Parsed action")
    nodes += _lv(store, record, "reversibility_class", "Reversibility")
    nodes += _lv(store, record, "authority.user_id", "On authority of")
    nodes.append({"id": f"confirm:{aid}", "role": "action",
                  "action_ref": aid, "actions": ["approve", "reject"]})
    spec = {"spec": "dvr/1.1", "id": f"v_confirm_{aid[-12:]}", "kind": "list",
            "title": {"text": "Confirm action"}, "nodes": nodes}
    return dvr11.validate_view(spec, known_binding_ids=_known_bindings(store))

def render_audit_view(record, store):
    """dvr/1.1 audit view spec: the full action record, evidence-afforded."""
    CALLS.append(("render_audit_view", record["action_id"]))
    aid = record["action_id"]
    fields = [("intent.verbatim", "Requested"), ("intent.normalized", "Parsed action"),
              ("authority.user_id", "On authority of"),
              ("permission_scope", "Permission scope"),
              ("preconditions", "Preconditions"),
              ("reversibility_class", "Reversibility"),
              ("undo_recipe", "Undo recipe"),
              ("execution_log", "Execution log"),
              ("outcome", "Outcome"), ("undo_status", "Undo status")]
    nodes = []
    for f, label in fields:
        nodes += _lv(store, record, f, label)
    spec = {"spec": "dvr/1.1", "id": f"v_audit_{aid[-12:]}", "kind": "list",
            "title": {"text": f"Action record {aid}"}, "nodes": nodes}
    return dvr11.validate_view(spec, known_binding_ids=_known_bindings(store))

def _known_bindings(store):
    bp = os.path.join(store._dataset_dir("action_log"), "bindings.jsonl")
    if not os.path.exists(bp):
        return set()
    return {json.loads(l)["id"] for l in open(bp) if l.strip()}
