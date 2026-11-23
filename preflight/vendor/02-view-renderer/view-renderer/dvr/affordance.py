#!/usr/bin/env python3
"""Evidence affordance — spec §4. Everything resolved live at click time:
the binding, the verbatim source rows, the last check result."""
from pathlib import Path

from qafiya_core import derivations, store


def evidence_panel(root: Path, binding: dict) -> dict:
    """Assemble the ▸evidence payload for a claim/value binding.
    'focus' shows ONLY the lines that matter: what the claim says, what the
    data actually says, the correct value, and the deciding rows."""
    rows = []
    for s in binding.get("sources", []):
        dataset = s["dataset"].removeprefix("ds:")
        _, records = store.load_dataset(root, dataset)
        where = {}
        if binding.get("derivation"):
            try:
                _, _, where = derivations.parse(binding["derivation"])
            except derivations.DerivationError:
                where = {}
        src_filter = s.get("filter")
        if src_filter:
            col, _, val = src_filter.partition("=")
            where.setdefault(col.strip(), val.strip())
        rows.extend(r for r in records if derivations.matches(r, where))
    chk = binding.get("check") or {}
    focus = build_focus(root, binding)
    return {
        "binding_id": binding.get("id"),
        "kind": binding.get("kind"),
        "derivation": binding.get("derivation"),
        "tuple": {
            "statistic": binding.get("statistic"),
            "device": binding.get("device"),
            "authoritative_artifact": binding.get("authoritative_artifact"),
        },
        "assertion": binding.get("assertion"),
        "focus": focus,
        "source_rows": rows,
        "check": {
            "provenance": chk.get("provenance", "PENDING"),
            "semantic": chk.get("semantic"),
            "checked_at": chk.get("checked_at"),
            "detail": chk.get("detail"),
        },
    }


def evidence_for_action(root: Path, action_id: str) -> dict:
    """dvr/1.1 delta §1: action records are Qafiya records, so ▸evidence shows
    the full action record (intent, scope, preconditions, undo recipe)."""
    from . import resolve
    rec = resolve.find_record(root, action_id)
    return {"action_ref": action_id, "record": rec,
            "found": rec is not None}


def build_focus(root: Path, binding: dict) -> dict:
    """The lines that matter. For a flagged claim: claim vs data, both sides
    recomputed, the correct value, and exactly which record(s) changed."""
    a = binding.get("assertion") or {}
    sides = a.get("both_sides") or {}
    focus = {"claim_says": a.get("statement"), "expected": a.get("expected"),
             "correct_value": None, "sides": {}, "changed_records": []}
    if not binding.get("sources"):
        return focus
    dataset = binding["sources"][0]["dataset"].removeprefix("ds:")
    _, records = store.load_dataset(root, dataset)
    if len(sides) == 2:
        vals = {}
        for label, side in sorted(sides.items()):
            try:
                v = derivations.evaluate(side["derivation"], records)
            except derivations.DerivationError:
                v = None
            vals[label] = v
            if side.get("derivation"):
                try:
                    _, _, w = derivations.parse(side["derivation"])
                    focus["sides"][label] = {
                        "value": v,
                        "rows": [r for r in records if derivations.matches(r, w)]}
                except derivations.DerivationError:
                    focus["sides"][label] = {"value": v, "rows": []}
        (k1, v1), (k2, v2) = sorted(vals.items())
        if v1 and v2 is not None:
            focus["correct_value"] = round((v2 - v1) / v1, 4)
    else:
        # single-value claim: correct value is the recomputed derivation
        try:
            focus["correct_value"] = derivations.evaluate(binding["derivation"], records)
        except derivations.DerivationError:
            focus["correct_value"] = None
    # which records were edited (the history trail — the 'where the error is')
    # dvr/1.1 addendum 3: tolerant lookups — L4's chained history uses
    # op/record/at rather than record_id/field; omit missing details, never raise.
    ds_dir = root / "datasets" / dataset
    hist = store.read_jsonl(ds_dir / store.HISTORY)
    changed = []
    for h in hist:
        entry = {}
        rid = h.get("record_id", h.get("record"))
        if rid is not None:
            entry["record_id"] = rid
        if h.get("field") is not None:
            entry["field"] = h["field"]
        if "prior" in h:
            entry["prior"] = h["prior"]
        if "new" in h:
            entry["new"] = h["new"]
        entry["at"] = h.get("ts", h.get("at"))
        changed.append(entry)
    focus["changed_records"] = changed
    return focus
