#!/usr/bin/env python3
"""E6 independent spine — recompute every claim from the FROZEN data + transcript.

Needs NO model and NO network: it reads the frozen CSV and the frozen transcripts
and recomputes every auditability claim with its OWN independent CSV parser (it
does not import or trust ``run.py``'s normalization). If this script fails, the
E6 claim is withdrawn (PROJECT.md §2).

Recomputes:

* the verified aggregates from the frozen CSV (independent parser), cross-checked
  against ``inputs/spec.json`` AND the frozen Qafiya binding values;
* the headline evidence panel resolves to its source rows and recomputes;
* the Qafiya spend dataset chain verifies;
* the model-vs-verified divergence, recomputed from the FROZEN transcript prose
  (the model's stated figures vs the Qafiya-verified values);
* the rendered view shows the VERIFIED number, NOT the model's prose figure;
* the stability variance from the k FROZEN transcripts, and that every
  auditability claim is INVARIANT to the prose;
* the audit graph: chain, monotonic sequences, replay completeness;
* cost honesty: declared = $0 (user declaration), presented actual = null
  ("not metered"), with L5's raw actual_cost_usd recorded alongside;
* the LoopbackGuard proved zero non-loopback calls;
* the licence + attribution are present in the frozen spec and manifest.

Run under Python 3.12:

    python3.12 experiments/cp3/e6_realistic_demo/spine.py
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CP3 = HERE.parent
EXPERIMENTS = HERE.parent.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(CP3), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from qafiya_core import chain as qafiya_chain, derivations  # noqa: E402
from dvr import affordance, resolve as dvr_resolve  # noqa: E402

CSV_PATH = HERE / "inputs" / "February_2013__25k_transparency_data.csv"
COLS = ["departmental_family", "entity", "date", "expense_type", "expense_area",
          "supplier", "transaction_number", "amount", "description",
          "supplier_postcode", "supplier_type", "expenditure_type"]


def _fail(msg: str) -> None:
    raise AssertionError(f"[E6 spine] {msg}")


# ------------------------------------------------- INDEPENDENT CSV re-derivation
def _independent_aggregates(path: Path) -> dict:
    """Parse the frozen CSV with the spine's OWN parser (cp1252, independent of
    run.py) and recompute every headline aggregate from scratch. Also counts n
    precisely (monitor Fix 2): source records, amount-bearing records, and the
    entirely-empty rows that are reported but not dropped."""
    text = path.read_bytes().decode("cp1252")
    rows = list(csv.reader(io.StringIO(text)))
    body = rows[1:]
    data = [r for r in body if r and r[0].strip()]
    empty = [r for r in body if (not r) or all((c or "").strip() == "" for c in r)]

    def amt(r):
        s = (r[7] or "").replace(",", "").replace("£", "").strip()
        return float(s) if s else 0.0

    def total_where(idx, val):
        return round(sum(amt(r) for r in data if r[idx].strip() == val), 2)

    amounts = [amt(r) for r in data]
    return {
        "source_records": len(body),
        "amount_bearing_records": len(data),
        "empty_rows": len(empty),
        "rows": len(data),
        "b_total": round(sum(amounts), 2),
        "b_programme": total_where(11, "Programme"),
        "b_admin": total_where(11, "Admin"),
        "b_grants": total_where(11, "Grants"),
        "b_large": total_where(10, "Large"),
        "b_sme": total_where(10, "SME"),
        "b_count": float(len(data)),
        "b_max": round(max(amounts), 2),
        "b_min": round(min(amounts), 2),
    }


# Category nouns, matched case-sensitively longest-first (independent of run.py).
_CATEGORY_NOUNS = ["Government Department", "Gov Dept", "Programme", "Grants",
                     "Admin", "Large", "SME"]


def _extract_category_figures(text: str) -> dict:
    """Independent re-implementation of the response->category association
    (monitor Fix 1): each £ figure is attached to the LAST category noun that
    appears before it in the prose."""
    text = text or ""
    figures = [(m.start(), float(m.group(1).replace(",", "")))
                 for m in re.finditer(r"£\s?([\d][\d,]*(?:\.\d+)?)", text)]
    out: dict = {}
    for pos, val in figures:
        preceding = text[:pos]
        last_cat, last_idx = None, -1
        for cat in _CATEGORY_NOUNS:
            idx = preceding.rfind(cat)
            if idx > last_idx:
                last_idx, last_cat = idx, cat
        if last_cat is not None:
            out.setdefault(last_cat, val)
    return out


def _extract_gbp(text: str) -> list[float]:
    """Independent re-implementation of the prose figure extraction (does not
    import run.py)."""
    out: list[float] = []
    for m in re.finditer(r"£\s?([\d][\d,]*(?:\.\d+)?)\s*(million|m\b)?", text or "", re.IGNORECASE):
        try:
            v = float(m.group(1).replace(",", ""))
            if m.group(2):
                v *= 1_000_000
            out.append(v)
        except ValueError:
            pass
    return sorted(set(out))


def main() -> int:
    _common.pin_environment()
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E6 output at {out}; run run.py first (needs ollama serve)")
    frozen_count = _common.verify_manifest(HERE)

    # ---- 1. dataset provenance: sha256 + licence + attribution ---------------
    csv_sha = _common.sha256_file(CSV_PATH)
    if csv_sha != spec["dataset"]["sha256"]:
        _fail(f"frozen CSV sha256 drift: {csv_sha} != {spec['dataset']['sha256']}")
    if spec["dataset"]["licence"] != "Open Government Licence v3.0":
        _fail("licence is not OGL v3.0")
    attribution = "Contains public sector information licensed under the Open Government Licence v3.0."
    if spec["dataset"]["attribution_required"] != attribution:
        _fail("attribution line missing/incorrect in the frozen spec")
    manifest = _common.read_json(HERE / "MANIFEST.json")
    if attribution not in json.dumps(manifest) and attribution not in json.dumps(spec):
        _fail("attribution line not carried in the manifest/spec")

    # ---- 2. verified aggregates recomputed independently from the frozen CSV --
    indep = _independent_aggregates(CSV_PATH)
    # Precise n (monitor Fix 2): 143 source records, 129 amount-bearing, 14 empty.
    if indep["source_records"] != spec["dataset"]["source_records"]:
        _fail(f"source_records {indep['source_records']} != "
                f"{spec['dataset']['source_records']}")
    if indep["amount_bearing_records"] != spec["dataset"]["amount_bearing_records"]:
        _fail(f"amount_bearing_records {indep['amount_bearing_records']} != "
                f"{spec['dataset']['amount_bearing_records']}")
    if indep["empty_rows"] != spec["dataset"]["empty_rows"]:
        _fail(f"empty_rows {indep['empty_rows']} != {spec['dataset']['empty_rows']}")
    if indep["source_records"] != indep["amount_bearing_records"] + indep["empty_rows"]:
        _fail("source_records != amount_bearing + empty")
    src_rec = _common.read_json(out / "source_records.json")
    if (src_rec["source_records"], src_rec["amount_bearing_records"],
          src_rec["empty_rows_reported_not_dropped"]) != \
       (indep["source_records"], indep["amount_bearing_records"], indep["empty_rows"]):
        _fail(f"run's source_records.json disagrees with the independent parse: {src_rec}")
    if not src_rec["empty_rows_remain_in_frozen_csv"]:
        _fail("empty rows were not kept in the frozen CSV")
    verified = _common.read_json(out / "verified_values.json")
    for b in spec["qafiya_bindings"]["bindings"]:
        bid, expected = b["id"], b["expected"]
        if round(indep[bid], 2) != round(expected, 2):
            _fail(f"{bid}: independent recompute {indep[bid]} != spec expected {expected}")
        if round(verified[bid], 2) != round(expected, 2):
            _fail(f"{bid}: run verified_values {verified[bid]} != spec expected {expected}")
    # b_count counts AMOUNT-BEARING records (129), not source records (143).
    if round(verified["b_count"]) != indep["amount_bearing_records"]:
        _fail(f"b_count {verified['b_count']} != amount-bearing {indep['amount_bearing_records']}")

    # ---- 3. the frozen Qafiya binding values match the independent recompute --
    qroot = out / "stores" / "qafiya"
    bindings = dvr_resolve.load_bindings(qroot)
    spend_records = _common.read_jsonl(qroot / "datasets" / "spend" / "data.jsonl")
    for b in spec["qafiya_bindings"]["bindings"]:
        bid = b["id"]
        if bid not in bindings:
            _fail(f"binding {bid} missing from the frozen Qafiya store")
        recomputed = round(derivations.evaluate(bindings[bid]["derivation"], spend_records), 2)
        if recomputed != round(b["expected"], 2):
            _fail(f"binding {bid} derivation recomputes to {recomputed}, expected {b['expected']}")
        if round(float(bindings[bid]["value"]), 2) != round(b["expected"], 2):
            _fail(f"binding {bid} stored value != expected")
    ok, detail = qafiya_chain.verify(qroot / "datasets" / "spend" / "history.jsonl")
    # history may be empty (no edit in E6); an empty chain verifies trivially.
    if not ok:
        _fail(f"spend dataset chain broken: {detail}")

    # ---- 4. headline evidence panel resolves + recomputes --------------------
    headline = spec["qafiya_bindings"]["headline_binding"]
    ev = affordance.evidence_panel(qroot, bindings[headline])
    ev_rows = ev["source_rows"]
    ev_sum = round(sum(float(r["amount"]) for r in ev_rows), 2)
    if ev_sum != round(spec["qafiya_bindings"]["headline_value"], 2):
        _fail(f"headline evidence rows sum {ev_sum} != {spec['qafiya_bindings']['headline_value']}")
    if len(ev_rows) < 1:
        _fail("headline evidence panel resolved no source rows")

    # ---- 5. divergence recomputed from the FROZEN transcript prose -----------
    transcript = _common.read_json(out / "transcript_main.json")
    prose = transcript["response_text"] or ""
    model_figures = _extract_gbp(prose)
    prog_verified = spec["qafiya_bindings"]["headline_value"]
    large_verified = round(indep["b_large"], 2)
    div = _common.read_json(out / "divergence.json")

    # Fix 1: the spine independently associates each £ figure with the category
    # noun the model attached it to, and checks the run did the same.
    spine_cats = _extract_category_figures(prose)
    run_cats = div.get("model_category_figures") or {}
    if {k: round(v, 2) for k, v in spine_cats.items()} != \
       {k: round(v, 2) for k, v in run_cats.items()}:
        _fail(f"run's category map {run_cats} != spine recompute {spine_cats}")
    spine_prog = spine_cats.get("Programme")
    spine_large = spine_cats.get("Large")
    if div["model_programme_figure"] is not None and spine_prog is not None \
            and round(div["model_programme_figure"], 2) != round(spine_prog, 2):
        _fail("run's model_programme_figure disagrees with the spine recompute")
    if div["model_large_figure"] is not None and spine_large is not None \
            and round(div["model_large_figure"], 2) != round(spine_large, 2):
        _fail("run's model_large_figure disagrees with the spine recompute")
    # The bug duplicated the Programme figure onto Large; assert they are distinct
    # whenever the prose stated both categories.
    if spine_prog is not None and spine_large is not None and spine_prog == spine_large:
        _fail("model_programme_figure and model_large_figure are identical — "
                "the per-category mapping regressed")

    def _cat_match(stated, target, tol=0.005):
        if stated is None:
            return False
        return abs(stated - target) / max(abs(target), 1e-9) <= tol
    spine_prog_match = _cat_match(spine_prog, prog_verified)
    spine_large_match = _cat_match(spine_large, large_verified)
    if div["model_programme_matches_verified"] != spine_prog_match:
        _fail("run's programme-match verdict disagrees with the spine recompute")
    if div["model_large_matches_verified"] != spine_large_match:
        _fail("run's large-match verdict disagrees with the spine recompute")
    if sorted(div["model_stated_gbp_figures"]) != model_figures:
        _fail("run's extracted model figures disagree with the spine recompute")

    # ---- 6. the rendered view shows the VERIFIED number, NOT the model prose --
    html = (out / "spend_view.html").read_text()
    assert '<meta charset="utf-8">' in html, "spend_view: missing charset meta"
    if f"{prog_verified:.2f}" not in html and str(prog_verified) not in html:
        _fail("rendered view does not show the Qafiya-verified Programme total")
    # The model's (wrong) prose figure must NOT be presented as a verified value.
    wrong_figures = [f for f in model_figures
                       if abs(f - prog_verified) / max(prog_verified, 1e-9) > 0.005]
    for wf in wrong_figures:
        if f"{wf:.2f}" in html:
            _fail(f"rendered view presents the model's divergent figure {wf} as a value")
    if "UNRESOLVED" in html:
        _fail("rendered view carries UNRESOLVED bindings")

    # ---- 7. stability: variance from the k FROZEN transcripts + invariance ----
    k = spec["stability_check"]["k"]
    responses = []
    for i in range(1, k + 1):
        t = _common.read_json(out / f"transcript_stability_{i:02d}.json")
        responses.append(t["response_text"] or "")
    if len(responses) != k:
        _fail(f"expected {k} frozen stability transcripts")
    distinct = sorted(set(responses))
    var = _common.read_json(out / "stability_variance.json")
    if var["distinct_responses"] != len(distinct):
        _fail("stability distinct-response count disagrees with the frozen transcripts")
    # INVARIANCE: the verified aggregates are recomputed from the CSV above and do
    # not depend on ANY transcript. Confirm the run recorded no prose-dependent claim.
    inv = _common.read_json(out / "invariance.json")
    if inv["claims_that_would_change_with_prose"]:
        _fail(f"a verified claim depends on the prose: {inv['claims_that_would_change_with_prose']}")
    if not inv["verified_values_invariant_to_prose"]:
        _fail("run did not assert verified-value invariance")

    # ---- 8. audit graph: chain, sequences, replay ----------------------------
    audit_dir = out / "stores" / "shell_audit" / "datasets" / "shell_audit"
    aok, adetail = qafiya_chain.verify(audit_dir / "history.jsonl")
    if not aok:
        _fail(f"shell_audit chain broken: {adetail}")
    events = _common.read_jsonl(audit_dir / "data.jsonl")
    seqs = sorted(e["sequence"] for e in events)
    if seqs != list(range(1, len(seqs) + 1)):
        _fail(f"non-monotonic audit sequence: {seqs}")
    ids = {e["id"] for e in events}
    missing = [r for e in events for r in e.get("input_event_refs", []) if r not in ids]
    if missing:
        _fail(f"unresolved input_event_refs: {missing}")
    states = [e["state"] for e in sorted(events, key=lambda e: e["sequence"])]
    for required in ("RECEIVED", "ROUTED", "COMPOSED", "RENDERED", "EXECUTED", "CLOSED"):
        if required not in states:
            _fail(f"audit graph missing state {required}")

    # ---- 9. cost honesty ------------------------------------------------------
    pres = _common.read_json(out / "route_presentation.json")
    dec = _common.read_json(out / "decision_record.json")
    if pres["outcome"] != "answered":
        _fail(f"route outcome {pres['outcome']} != answered (the local call did not answer)")
    if dec.get("chosen", {}).get("locus") != "local" and pres.get("chosen_locus") != "local":
        _fail("the routed connection is not local")
    summary = _common.read_json(out / "summary.json")
    route = summary["route"]
    if route["declared_cost_usd"] != 0.0:
        _fail(f"declared cost {route['declared_cost_usd']} != 0.0 (local user declaration)")
    if route["presented_actual_metered_cost_usd"] is not None:
        _fail("presented actual_metered_cost_usd must be null for a local model (not metered)")
    # L5's raw value is recorded for transparency (declared-$0 x token usage).
    if "l5_raw_actual_cost_usd" not in route:
        _fail("L5 raw actual_cost_usd not recorded alongside the presented null")
    # The audit events must carry declared=0.0 and actual=null, never a fake metered cost.
    for e in events:
        if e.get("actual_metered_cost_usd") is not None:
            _fail(f"audit event {e['id']} carries a non-null actual_metered_cost_usd")

    # ---- 10. loopback-only proof ---------------------------------------------
    guard = _common.read_json(out / "loopback_guard.json")
    if guard["non_loopback_calls"] != 0:
        _fail(f"LoopbackGuard recorded {guard['non_loopback_calls']} non-loopback calls")
    if not guard["only_loopback_touched"]:
        _fail("guard did not confirm only-loopback")
    if guard["loopback_call_count"] < 1:
        _fail("no loopback call recorded — was the local model actually called?")
    if 11434 not in guard["loopback_ports_touched"]:
        _fail(f"ollama port 11434 not among loopback ports touched: {guard['loopback_ports_touched']}")

    # ---- 11. the model filled ONLY COMPOSE ------------------------------------
    comp = _common.read_json(out / "composition.json")
    if comp["model_fills_only"] != "COMPOSE":
        _fail("composition does not record that the model fills only COMPOSE")
    # No verified value may equal a model-only figure: the verified values come
    # from the bindings (checked above), independent of the prose.
    transcript_sha = _common.sha256_file(out / "transcript_main.json")
    if transcript["prompt_sha256"] != _common.sha256_file(out / "compose_prompt_full.txt"):
        _fail("transcript prompt sha does not match the frozen full prompt")

    result = {
        "experiment": "E6",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "dataset": {"sha256": csv_sha,
                      "source_records": indep["source_records"],
                      "amount_bearing_records": indep["amount_bearing_records"],
                      "empty_rows_reported_not_dropped": indep["empty_rows"],
                      "n_statement": (f"{indep['source_records']} source records, of which "
                                         f"{indep['amount_bearing_records']} carry an amount "
                                         f"({indep['empty_rows']} empty rows reported, not dropped)"),
                      "b_count_label": "count of amount-bearing records",
                      "licence": spec["dataset"]["licence"],
                      "attribution_present": True},
        "verified_aggregates_recomputed_independently": {
            k2: indep[k2] for k2 in
            ("b_total", "b_programme", "b_admin", "b_grants", "b_large", "b_sme",
             "b_count", "b_max", "b_min")},
        "headline_binding": headline,
        "headline_evidence_rows": len(ev_rows),
        "headline_evidence_recomputes": ev_sum,
        "model_prose_figures": model_figures,
        "model_category_figures": spine_cats,
        "model_programme_figure": spine_prog,
        "model_large_figure": spine_large,
        "model_programme_matches_verified": spine_prog_match,
        "model_large_matches_verified": spine_large_match,
        "divergence_reported_honestly": True,
        "rendered_view_shows_verified_not_prose": True,
        "stability": {"k": k, "distinct_responses": len(distinct),
                        "all_identical": len(distinct) <= 1,
                        "mean_token_position_agreement": var["mean_token_position_agreement"]},
        "claims_invariant_to_prose": True,
        "audit_events": len(events), "audit_chain_ok": True,
        "sequences_complete": True, "replay_refs_resolved": True,
        "cost_honesty": {"declared_cost_usd": 0.0,
                            "presented_actual_metered_cost_usd": None,
                            "l5_raw_actual_cost_usd": route["l5_raw_actual_cost_usd"],
                            "meaning": "not metered — no provider billing meter for a local model"},
        "loopback_only": True, "non_loopback_calls": 0,
        "loopback_ports_touched": guard["loopback_ports_touched"],
        "model_fills_only_compose": True,
        "transcript_sha256": transcript_sha,
        "needs_no_model_to_rerun": True,
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
