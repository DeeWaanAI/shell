#!/usr/bin/env python3
"""Two-way claim-map verifier for the capstone draft (adapted from the
research-paper-rigor skeleton, v2.1). Exit 0 = every datapoint re-verified
against its frozen raw artifact, every paper claim resolves, statistic/device
tuples match, every verbatim quote appears in the current draft, document links
point at real files, and no claim seeds from a quarantined artifact.

Run from 06-shell/:
    python3.12 paper/claim_map/verify_two_way.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # paper/claim_map
PAPER = HERE.parent
L6 = PAPER.parent                                    # 06-shell (ROOT)
dp = json.loads((HERE / "datapoints.json").read_text())
pm = json.loads((HERE / "paper-claims.json").read_text())
# The draft path comes from the claim map's "paper" field, so a version bump
# (v0.1 -> v0.2 -> ...) only requires editing paper-claims.json, not this file.
DRAFT = L6 / pm["paper"]
draft = DRAFT.read_text()
fails: list[tuple] = []

# Quarantine list (SUPERSEDED). The capstone has none yet; the guard is wired so
# a future retired artifact cannot silently seed a claim.
SUPERSEDED = HERE / "SUPERSEDED.json"
quarantined: set[str] = set()
if SUPERSEDED.exists():
    quarantined = {e["file"] for e in json.loads(SUPERSEDED.read_text())}


def get_by_segments(obj, segs):
    for s in segs:
        obj = obj[int(s)] if isinstance(obj, list) else obj[s]
    return obj


def values_equal(raw, mapped) -> bool:
    """Type-aware equality: numeric tolerance for numbers, exact for the rest
    (strings, booleans, null, lists)."""
    if isinstance(raw, bool) or isinstance(mapped, bool):
        return raw == mapped
    if isinstance(raw, (int, float)) and isinstance(mapped, (int, float)):
        a, b = float(raw), float(mapped)
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) <= 1e-9
    return raw == mapped


# ---- Direction 1: every datapoint re-verified against its frozen raw file ----
for d in dp["datapoints"]:
    src = d["source_file"]
    if src in quarantined:
        fails.append((d["dp_id"], "source is quarantined (SUPERSEDED.json)"))
        continue
    path = L6 / src
    if not path.exists():
        fails.append((d["dp_id"], f"missing source {src}"))
        continue
    if d["kind"] == "text-match":
        if d["verbatim_excerpt"] not in path.read_text():
            fails.append((d["dp_id"], f"text {d['verbatim_excerpt']!r} not in {src}"))
        continue
    data = json.loads(path.read_text())
    try:
        raw = get_by_segments(data, d["key_segments"])
    except Exception:                                   # noqa: BLE001
        fails.append((d["dp_id"], f"key path not found: {d['key_path']}"))
        continue
    if d.get("extract") == "len":
        raw = len(raw)
    if not values_equal(raw, d["value"]):
        fails.append((d["dp_id"], f"value mismatch raw={raw!r} map={d['value']!r}"))

# ---- Direction 2: every paper claim resolves + appears in the draft ----------
ids = {d["dp_id"]: d for d in dp["datapoints"]}
for m in pm["mentions"]:
    mid = m["mention_id"]
    # verbatim quote must appear in the CURRENT draft (prose is the drifting side)
    q = m.get("verbatim_quote", "")
    if q and q not in draft:
        fails.append((mid, f"verbatim quote not in draft: {q[:60]!r}"))
    if m.get("dp_id"):
        if m["dp_id"] not in ids:
            fails.append((mid, f"dp_id missing: {m['dp_id']}"))
            continue
        d = ids[m["dp_id"]]
        if d["source_file"] in quarantined:
            fails.append((mid, "claim seeds from a quarantined file"))
        # tuple check: statistic + device must match the DP (false-link guard)
        for field in ("statistic", "device"):
            claimed, dpv = m.get(f"claimed_{field}"), d.get(field)
            if (claimed and dpv and claimed not in ("n/a", None)
                    and dpv not in ("n/a", None) and claimed != dpv):
                fails.append((mid, f"{field} mismatch prose={claimed} dp={dpv}"))
    elif m.get("link_status") == "document":
        for f in (m.get("curation") or {}).get("files", []):
            if not (L6 / f).exists():
                fails.append((mid, f"document-link file missing: {f}"))
    else:
        fails.append((mid, "neither dp_id nor a document curation"))

# ---- Direction 3: citation integrity (every cited work is verified) ----------
import re as _re
refs_path = HERE / "references-verified.json"
if not refs_path.exists():
    fails.append(("refs", "references-verified.json missing"))
else:
    refs = json.loads(refs_path.read_text())
    if refs["summary"]["unresolved"] != 0:
        fails.append(("refs", f"{refs['summary']['unresolved']} unresolved references: "
                                 f"{refs['summary']['unresolved_keys']}"))
    verified_ids = set()
    for r in refs["verified"]:
        rid = r.get("resolved_id") or ""
        verified_ids.add(rid)
        verified_ids.add(r.get("queried", ""))
        if rid.startswith("arXiv:"):
            verified_ids.add(rid.split("v")[0])      # strip a version suffix
    # Every arXiv id / DOI cited in the draft must be in the verified set.
    cited_arxiv = set(_re.findall(r"arXiv:(\d{4}\.\d{4,5})", draft))
    cited_doi = set(_re.findall(r"doi\.org/(10\.\d{4,9}/[^\s]+)", draft))
    for aid in cited_arxiv:
        if not any(aid in v for v in verified_ids):
            fails.append(("refs", f"cited arXiv:{aid} is not in references-verified.json"))
    for d in cited_doi:
        d = d.rstrip(".,")
        if not any(d in v for v in verified_ids):
            fails.append(("refs", f"cited doi:{d} is not in references-verified.json"))

# ---- report ------------------------------------------------------------------
if fails:
    for f in fails:
        print("FAIL", *f)
    print(f"\n{len(fails)} failure(s); {dp['count']} datapoints, {pm['count']} mentions")
    sys.exit(1)
print(f"OK: {dp['count']} datapoints re-verified against frozen artifacts; "
        f"{pm['count']} paper mentions resolved (quotes present, tuples consistent, "
        f"document links exist, nothing quarantined); citations verified "
        f"({len(cited_arxiv)} arXiv + {len(cited_doi)} DOI, 0 unresolved)")
sys.exit(0)
