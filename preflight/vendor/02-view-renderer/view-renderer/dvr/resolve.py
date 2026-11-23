#!/usr/bin/env python3
"""Resolution — spec §3. Every displayed value is recomputed from current data
via qafiya-core derivations.evaluate. binding.value is never printed without
recompute. Unresolvable bindings produce an explicit UNRESOLVED state."""
import json
from pathlib import Path

from qafiya_core import derivations, store


class Unresolved:
    """Marker: rendered visibly, never silently (spec §3.3, invariant 8)."""
    def __init__(self, reason):
        self.reason = reason
    def __repr__(self):
        return f"Unresolved({self.reason})"


def load_bindings(root: Path):
    """dvr/1.1 delta §2: merge store-level <root>/bindings.jsonl with every
    per-dataset <root>/datasets/<name>/bindings.jsonl (Qafiya §8). Per-dataset
    bindings override root bindings on id collision (they are more specific)."""
    merged = {b["id"]: b for b in store.read_jsonl(root / store.BINDINGS)}
    ds_root = root / "datasets"
    if ds_root.is_dir():
        for ds in sorted(ds_root.iterdir()):
            per = ds / store.BINDINGS
            if per.exists():
                for b in store.read_jsonl(per):
                    merged[b["id"]] = b
    return merged


def find_record(root: Path, record_id: str):
    """Locate a Qafiya record by identity across all datasets (used for action nodes).
    dvr/1.1 addendum 2 (2026-10-29): resolve by each dataset's declared identity —
    read schema.json's id_field; if no schema, fall back to id, action_id, _id
    (L3's action records legitimately identify by action_id)."""
    ds_root = root / "datasets"
    if not ds_root.is_dir():
        return None
    for ds in sorted(ds_root.iterdir()):
        schema_p = ds / "schema.json"
        id_field = None
        if schema_p.exists():
            try:
                id_field = json.loads(schema_p.read_text()).get("id_field")
            except Exception:
                id_field = None
        candidates = [id_field] if id_field else ["id", "action_id", "_id"]
        _, records = store.load_dataset(root, ds.name)
        for r in records:
            for f in candidates:
                if f and r.get(f) == record_id:
                    return r
    return None


def resolve_binding(root: Path, binding: dict):
    """Recompute the binding's derivation over current data.
    Returns (value_or_Unresolved, state).
    dvr/1.1 addendum (2026-10-27): derivation == "literal" returns binding.value
    verbatim — memory content is evidence, not a computation; the derivation
    parser is never invoked. Quarantine/superseded handling unchanged."""
    if not binding.get("derivation"):
        return Unresolved("binding has no derivation"), "UNRESOLVED"
    artifact = binding.get("authoritative_artifact", "")
    if artifact and artifact in store.superseded_set(root):
        return Unresolved(f"quarantined source: {artifact}"), "UNRESOLVED"
    if binding["derivation"] == "literal":
        # sources MUST be non-empty and resolvable (addendum rule)
        try:
            ds = binding["sources"][0]["dataset"].removeprefix("ds:")
            store.load_dataset(root, ds)
        except (KeyError, IndexError, FileNotFoundError):
            return Unresolved("literal binding with no resolvable source"), "UNRESOLVED"
        state = (binding.get("check") or {}).get("provenance", "PASS")
        return binding.get("value"), state
    try:
        dataset = binding["sources"][0]["dataset"].removeprefix("ds:")
        _, records = store.load_dataset(root, dataset)
        value = derivations.evaluate(binding["derivation"], records)
    except (KeyError, IndexError) as e:
        return Unresolved(f"missing source: {e}"), "UNRESOLVED"
    except derivations.DerivationError as e:
        return Unresolved(str(e)), "UNRESOLVED"
    state = (binding.get("check") or {}).get("provenance", "PENDING")
    return value, state


def check_state(binding: dict) -> str:
    """Badge state for a node: semantic FLAG outranks provenance for claims."""
    chk = binding.get("check") or {}
    prov = chk.get("provenance", "PENDING")
    sem = chk.get("semantic")
    if binding.get("kind") == "claim" and sem == "FLAG":
        return "FLAG"
    return prov


def coverage(resolved_nodes) -> float:
    """Share of data-bearing nodes that resolved AND passed Layer 1 (spec §3.5)."""
    data_nodes = [n for n in resolved_nodes if n["role"] in ("value", "claim")]
    if not data_nodes:
        return 1.0
    ok = sum(1 for n in data_nodes if n["resolved_ok"] and n["state"] == "PASS")
    return ok / len(data_nodes)
