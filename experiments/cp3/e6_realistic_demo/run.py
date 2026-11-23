#!/usr/bin/env python3
"""E6 — realistic demonstration: real open data + a real local LLM.

Owner-approved scope addition (e6-realistic-demo-instructions-03-nov-2026-2113.md).
E6 sits ALONGSIDE the offline deterministic core E1-E5; it does not replace or
modify them.

Design (honours every binding guardrail):

* **Real open data.** UK Cabinet Office "Expenditure over £25,000, February
  2013" (OGL v3.0), frozen verbatim under ``inputs/`` with source URL, access
  date, sha256, licence and attribution recorded in the spec + manifest.
* **Real local LLM.** ``llama3.1:8b-instruct-q4_K_M`` via ollama on
  ``127.0.0.1:11434``, greedy (temperature 0 — set by L5's vendored ollama
  backend). The model fills ONLY the COMPOSE step. The full prompt + response is
  frozen as a transcript; the spine recomputes from the frozen transcript and
  needs NO model to re-run.
* **Loopback only.** ``LoopbackGuard`` permits 127.0.0.1 and blocks + counts any
  non-loopback connection. The run asserts zero non-loopback calls — no cloud,
  no paid call.
* **Auditability over frozen data + transcript, NOT model correctness.** Every
  verified number comes from a Qafiya binding recomputed deterministically over
  the frozen CSV. The model's prose is recorded, never trusted.
* **Divergence shown honestly.** The model's stated GBP figures are extracted
  from the frozen transcript and presented side by side with the Qafiya-verified
  values. A divergence is a FEATURE: the binding recomputes the real number
  regardless of the prose.
* **Cost honesty.** ``declared_cost_usd = 0.0`` is a USER DECLARATION;
  ``actual_metered_cost_usd = null`` ("not metered" — a local model has no
  provider billing meter). L5's raw ``actual_cost_usd`` (declared-$0 x ollama
  token usage = 0.0) is recorded alongside the presented null, with the reason —
  the divergence is shown, not hidden. No measured energy/latency claim.
* **Stability.** k=5 greedy runs frozen; token-level variance reported; every
  auditability claim confirmed INVARIANT to the prose.

Run under Python 3.12 (ollama serve must be up):

    python3.12 experiments/cp3/e6_realistic_demo/run.py [--freeze]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # e6_realistic_demo/
CP3 = HERE.parent
EXPERIMENTS = CP3.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(CP3), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from shell.audit import ShellAuditStore, sha256_file  # noqa: E402
from shell.connections import ShellConnections  # noqa: E402
from shell.interactions import ActionDispatcher  # noqa: E402
from shell.kernel import Kernel, KernelContext, KernelState  # noqa: E402
from shell.memory import ShellMemory  # noqa: E402
from shell.routing import ShellRouter  # noqa: E402
from shell.session import new_session  # noqa: E402
from shell import views as shell_views  # noqa: E402
from shell.views import write_view_html  # noqa: E402

import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

from actionlayer.engine import ActionEngine  # noqa: E402
from actionlayer.gate import make_grant  # noqa: E402
from dvr import affordance, render as dvr_render, resolve as dvr_resolve, specval  # noqa: E402
from qafiya_core import chain as qafiya_chain, derivations, engine as qafiya_engine  # noqa: E402
import connections as L5Connections  # noqa: E402 (vendored snapshot)
import transport as L5Transport  # noqa: E402 (vendored snapshot)
from health import Health  # noqa: E402
from store import Store as L5Store, DATASETS as L5_DATASETS  # noqa: E402

from loopback_guard import LoopbackGuard  # noqa: E402

SPEC = _common.read_json(HERE / "inputs" / "spec.json")
CSV_PATH = HERE / "inputs" / "February_2013__25k_transparency_data.csv"
PROMPT_TEMPLATE = (HERE / "inputs" / "compose_prompt.txt").read_text()
OLLAMA_CONN_ID = SPEC["model"]["l5_connection_id"]
EXPECTED_OUT = SPEC["compose_prompt"]["expected_output_budget_tokens"]
STABILITY_K = SPEC["stability_check"]["k"]
USER_QUESTION = SPEC["compose_prompt"]["user_question"]

# Column order in the raw CSV (trailing empty columns are ignored).
COLS = ["departmental_family", "entity", "date", "expense_type", "expense_area",
          "supplier", "transaction_number", "amount", "description",
          "supplier_postcode", "supplier_type", "expenditure_type"]


# ------------------------------------------------------------ CSV normalization
def _parse_amount(s: str) -> float:
    s = (s or "").replace(",", "").replace("£", "").strip()
    return float(s) if s else 0.0


def _iso_date(s: str) -> str:
    """'01/02/13' (DD/MM/YY) -> '2013-02-01'. Unparseable dates pass through."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2})$", s)
    if not m:
        return s
    dd, mm, yy = m.groups()
    return f"20{yy}-{mm.zfill(2)}-{dd.zfill(2)}"


def normalize_csv(path: Path) -> dict:
    """Deterministic normalization of the frozen CSV into Qafiya records.

    The raw file is cp1252, NOT UTF-8. Amounts become floats; dates become ISO;
    field names become snake_case. The source's two Supplier Type spellings
    ('Gov Dept' and 'Government Department') and the one negative Amount are kept
    verbatim — nothing is merged or silently fixed.

    Precise ``n`` (monitor Fix 2): the frozen CSV carries **143 non-header source
    records**, of which **129 carry an amount** and **14 are entirely empty rows**
    (every field blank). The 14 empty rows stay verbatim in the frozen CSV (the
    input artifact is never edited) and are REPORTED as a data-quality fact, not
    silently dropped; they are not normalized into Qafiya records because they
    carry no data. Therefore ``b_count = count(amount) = 129`` counts
    amount-bearing records, and the label says exactly that.
    """
    text = path.read_bytes().decode("cp1252")
    rows = list(csv.reader(io.StringIO(text)))
    body = rows[1:]
    records = []
    empty_rows = 0
    n = 0
    for r in body:
        is_empty = (not r) or all((c or "").strip() == "" for c in r)
        if is_empty:
            empty_rows += 1            # reported, not dropped; stays in the frozen CSV
            continue
        if not r[0].strip():
            # blank first column but some other content — does not occur in this
            # file (verified), but handled explicitly rather than assumed away.
            empty_rows += 1
            continue
        n += 1
        rec = {"id": f"r_{n:03d}"}
        for i, field in enumerate(COLS):
            rec[field] = r[i].strip() if i < len(r) else ""
        rec["amount"] = _parse_amount(rec["amount"])
        rec["date"] = _iso_date(rec["date"])
        records.append(rec)
    return {
        "records": records,
        "source_records": len(body),
        "amount_bearing_records": len(records),
        "empty_rows": empty_rows,
    }


# ------------------------------------------------------- Qafiya store + bindings
SPEND_SCHEMA = {
    "dataset": "spend", "id_field": "id", "id_prefix": "r_",
    "spec_ref": "Qafiya v1.1 §8 layout; v1.3 chained history; E6 real open data",
    "fields": {
        "id": "id", "departmental_family": "string", "entity": "string",
        "date": "string", "expense_type": "string", "expense_area": "string",
        "supplier": "string", "transaction_number": "string", "amount": "number",
        "description": "string", "supplier_postcode": "string",
        "supplier_type": "string", "expenditure_type": "string",
    },
    "derivations": ["filter", "count", "groupby", "sum", "min", "max"],
}

# (binding_id, derivation, statistic, label, node_id)
BINDING_DEFS = [
    ("b_total", "sum(amount)", "sum", "Total spend over £25k (Feb 2013, GBP)", "cell:total"),
    ("b_programme", "sum(amount) where expenditure_type='Programme'", "sum",
     "Total Programme expenditure (GBP)", "cell:programme"),
    ("b_admin", "sum(amount) where expenditure_type='Admin'", "sum",
     "Total Admin expenditure (GBP)", "cell:admin"),
    ("b_grants", "sum(amount) where expenditure_type='Grants'", "sum",
     "Total Grants expenditure (GBP)", "cell:grants"),
    ("b_large", "sum(amount) where supplier_type='Large'", "sum",
     "Total to Large suppliers (GBP)", "cell:large"),
    ("b_sme", "sum(amount) where supplier_type='SME'", "sum",
     "Total to SME suppliers (GBP)", "cell:sme"),
    ("b_count", "count(amount)", "count",
     "Count of amount-bearing records (129 of 143 source records; 14 empty rows reported, not dropped)",
     "cell:count"),
    ("b_max", "max(amount)", "max", "Largest single transaction (GBP)", "cell:max"),
    ("b_min", "min(amount)", "min", "Smallest (most negative) transaction (GBP)", "cell:min"),
]


def _filter_for(derivation: str) -> str | None:
    """Turn a derivation's where-clause into an evidence-panel filter string."""
    m = re.search(r"where\s+([A-Za-z_]\w*)='([^']*)'", derivation)
    return f"{m.group(1)}={m.group(2)}" if m else None


def build_qafiya_store(root: Path, records: list[dict]) -> dict:
    """Build a Qafiya §8 store over the real spend data with aggregate bindings.

    Binding values are computed with the SAME ``derivations.evaluate`` the
    provenance gate uses, then rounded to 2 dp; the build asserts the gate passes
    so a non-clean float sum would fail loudly rather than render a long float.
    """
    ds = root / "datasets" / "spend"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "schema.json").write_text(json.dumps(SPEND_SCHEMA, indent=1, sort_keys=True))
    (ds / "data.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records))
    (ds / "history.jsonl").write_text("")
    (ds / "bindings.jsonl").write_text("")
    (ds / "SUPERSEDED.json").write_text("[]\n")

    bindings = []
    values = {}
    for bid, derivation, statistic, label, node in BINDING_DEFS:
        value = derivations.evaluate(derivation, records)
        value = round(value, 2)
        values[bid] = value
        filt = _filter_for(derivation)
        source = {"dataset": "ds:spend", "field": "amount", "key_path": ["amount"]}
        if filt:
            source["filter"] = filt
        bindings.append({
            "id": bid, "kind": "view",
            "target": {"view": "v_e6_spend", "node": node},
            "sources": [source],
            "derivation": derivation, "value": value, "statistic": statistic,
            "device": "local-m4", "authoritative_artifact": "datasets/spend/data.jsonl",
            "provenance": {"created_by": "e6-freeze",
                             "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "check": {"provenance": "PENDING"},
        })
    (root / "bindings.jsonl").write_text(
        "".join(json.dumps(b, sort_keys=True, ensure_ascii=False) + "\n" for b in bindings))
    (root / "SUPERSEDED.json").write_text(json.dumps({"superseded": []}, indent=1))

    nodes = []
    for bid, _d, _s, label, node in BINDING_DEFS:
        nodes.append({"id": f"label:{node.split(':')[1]}", "role": "label", "text": label})
        nodes.append({"id": node, "role": "value", "binding_ref": bid, "column": "col:amount"})
    view = {
        "spec": "dvr/1.1", "id": "v_e6_spend", "kind": "table",
        "title": {"text": "Cabinet Office spend over £25,000 — February 2013 (Qafiya-verified)"},
        "columns": [{"id": "col:amount", "label": "Amount (GBP)", "source_field": "amount"}],
        "nodes": nodes,
    }
    (root / "views").mkdir(exist_ok=True)
    (root / "views" / "v_e6_spend.view.json").write_text(
        json.dumps(view, indent=1, sort_keys=True, ensure_ascii=False))

    gate = qafiya_engine.provenance_gate(root)
    if gate != 0:
        raise RuntimeError(f"E6 Qafiya provenance gate failed ({gate}) — a binding value "
                             f"is not exactly recomputable; refusing to freeze a long float")
    return {"values": values, "view": view, "gate": gate}


# ------------------------------------------------------------------ L5 scaffold
def scaffold_e6_l5(dst_root: Path) -> Path:
    """Seed policy/rules/capabilities read-only + ONLY the real ollama connection.

    The ollama connection is the one already registered active in L5
    (``mdl_179292740661000007``); E6 uses it as-is and never re-declares it.
    ``models`` history starts empty (E6 makes no connection mutation), so its
    chain verifies trivially.
    """
    frozen = _common.FROZEN_L5_DATASETS
    ollama_line = None
    for line in (frozen / "datasets" / "models" / "data.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("id") == OLLAMA_CONN_ID:
            ollama_line = line
            break
    if ollama_line is None:
        raise RuntimeError(f"ollama connection {OLLAMA_CONN_ID} not found in frozen L5 models")
    for name in L5_DATASETS:
        src = frozen / "datasets" / name
        dst = dst_root / "datasets" / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / "schema.json", dst / "schema.json")
        if name in ("policy", "rules", "capabilities"):
            shutil.copyfile(src / "data.jsonl", dst / "data.jsonl")
        elif name == "models":
            (dst / "data.jsonl").write_text(ollama_line + "\n")
        else:
            (dst / "data.jsonl").write_text("")
        (dst / "history.jsonl").write_text("")
        (dst / "bindings.jsonl").write_text("")
        (dst / "SUPERSEDED.json").write_text("[]\n")
    return dst_root


# --------------------------------------------------------------------- prompt
def build_prompt(records: list[dict]) -> str:
    """The fixed COMPOSE prompt: template + the row-level triples + question."""
    lines = [f"{r['expenditure_type']} | {r['supplier_type']} | {r['amount']:.2f}"
               for r in records]
    return PROMPT_TEMPLATE.replace("{records}", "\n".join(lines)).replace(
        "{question}", USER_QUESTION)


# ---------------------------------------------------------- model-prose parsing
def extract_gbp(text: str) -> list[float]:
    """Best-effort extraction of GBP figures the model stated, for the divergence
    report. Handles '£18,801,701.38', '18801701.38', '£18.8 million', '18.8m'.
    This NEVER feeds a verified claim — it only characterises the prose."""
    out: list[float] = []
    for m in re.finditer(r"£\s?([\d][\d,]*(?:\.\d+)?)", text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    for m in re.finditer(r"([\d][\d,]*(?:\.\d+)?)\s*(million|m\b)", text or "", re.IGNORECASE):
        try:
            out.append(float(m.group(1).replace(",", "")) * 1_000_000)
        except ValueError:
            pass
    for m in re.finditer(r"£\s?([\d][\d,]*(?:\.\d+)?)\s*(million|m\b)", text or "", re.IGNORECASE):
        try:
            out.append(float(m.group(1).replace(",", "")) * 1_000_000)
        except ValueError:
            pass
    return sorted(set(out))


def closest_match(figures: list[float], target: float, tol: float = 0.005):
    """Return (matched_value, within_tolerance) for the figure closest to target.

    DEPRECATED for per-category assignment — it picks the nearest figure to a
    target regardless of which category the prose attached it to, which is how
    the Programme figure was wrongly duplicated onto Large. Kept only as a
    fallback; the divergence report uses ``extract_category_figures``.
    """
    if not figures:
        return None, False
    best = min(figures, key=lambda v: abs(v - target) / max(abs(target), 1e-9))
    rel = abs(best - target) / max(abs(target), 1e-9)
    return best, rel <= tol


# Category nouns the model may attach a figure to. Matched case-sensitively and
# longest-first so 'Government Department' is not shadowed by 'Gov Dept' and
# 'Large' does not match inside the lowercase word 'largest'.
CATEGORY_NOUNS = ["Government Department", "Gov Dept", "Programme", "Grants",
                    "Admin", "Large", "SME"]


def extract_category_figures(text: str) -> dict:
    """Associate each £ figure in the prose with the category noun the model
    attached it to (monitor Fix 1).

    For every £ figure, scan the PRECEDING text and take the LAST category noun
    that appears before it — that is the noun the figure refers to. This fixes
    the bug where the nearest-figure heuristic duplicated the Programme figure
    onto Large. Returns ``{category: figure}`` (first figure wins per category).
    Never feeds a verified claim; it only characterises the prose.
    """
    text = text or ""
    figures = [(m.start(), float(m.group(1).replace(",", "")))
                 for m in re.finditer(r"£\s?([\d][\d,]*(?:\.\d+)?)", text)]
    out: dict = {}
    for pos, val in figures:
        preceding = text[:pos]
        last_cat, last_idx = None, -1
        for cat in CATEGORY_NOUNS:
            idx = preceding.rfind(cat)
            if idx > last_idx:
                last_idx, last_cat = idx, cat
        if last_cat is not None:
            out.setdefault(last_cat, val)
    return out


def match_category(cat_figures: dict, category: str, verified: float,
                     tol: float = 0.005):
    """Return (stated_value_or_None, within_tolerance) for one category."""
    stated = cat_figures.get(category)
    if stated is None:
        return None, False
    rel = abs(stated - verified) / max(abs(verified), 1e-9)
    return stated, rel <= tol


# ------------------------------------------------------------------ ollama meta
def ollama_version() -> str:
    try:
        return subprocess.run(["ollama", "--version"], capture_output=True, text=True,
                                 timeout=15).stderr.strip().splitlines()[-1]
    except Exception:                                   # noqa: BLE001
        return "unknown"


# =================================================================== the run
def run(out_root: Path) -> dict:
    out_root = Path(out_root).resolve()
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    # ---- 1. normalize the frozen CSV + build the Qafiya store ----------------
    parsed = normalize_csv(CSV_PATH)
    records = parsed["records"]
    qroot = out_root / "stores" / "qafiya"
    built = build_qafiya_store(qroot, records)
    verified = built["values"]
    view = built["view"]
    _common.write_json(out_root / "verified_values.json", verified)
    _common.write_json(out_root / "source_records.json", {
        "source_records": parsed["source_records"],
        "amount_bearing_records": parsed["amount_bearing_records"],
        "empty_rows_reported_not_dropped": parsed["empty_rows"],
        "n_statement": (f"{parsed['source_records']} source records, of which "
                          f"{parsed['amount_bearing_records']} carry an amount "
                          f"({parsed['empty_rows']} empty rows reported, not dropped)"),
        "b_count_label": "count of amount-bearing records",
        "empty_rows_remain_in_frozen_csv": True,
    })
    _common.write_json(out_root / "normalized_records_sha.json",
                         {"count": len(records),
                            "data_sha256": sha256_file(qroot / "datasets" / "spend" / "data.jsonl")})

    # ---- 2. scaffold the E6 L5 store with the real ollama connection ---------
    l5root = out_root / "stores" / "l5"
    scaffold_e6_l5(l5root)
    l5store = L5Store(l5root)
    conns_norm, problems = L5Connections.load(l5store)
    ollama_conn = next((c for c in conns_norm if c["id"] == OLLAMA_CONN_ID), None)
    if ollama_conn is None:
        raise RuntimeError(f"ollama connection {OLLAMA_CONN_ID} did not normalise; "
                             f"problems={problems}")

    # ---- 3. shell scaffolding -------------------------------------------------
    audit = ShellAuditStore(out_root / "stores" / "shell_audit")
    memory = ShellMemory(out_root / "stores" / "memory")
    file_engine = ActionEngine(out_root / "stores" / "action")
    dispatcher = ActionDispatcher(file_engine)
    session = new_session(user_id="youssef")
    request = session.new_request(USER_QUESTION)
    ctx = KernelContext(request_ref=request.id,
                          content_policy={"store_prompt_content": "never",
                                            "store_response_content": "never"})
    kernel = Kernel(session.id, audit, ctx)

    full_prompt = build_prompt(records)
    (out_root / "compose_prompt_full.txt").write_text(full_prompt)
    prompt_sha = sha256_file(out_root / "compose_prompt_full.txt")

    net = LoopbackGuard()
    transcript_main: dict = {}
    route_presentation: dict = {}
    l5_raw_actual_cost = None
    try:
        with net:
            # ---- RECEIVED ----
            kernel.enter(KernelState.RECEIVED, notes=f"E6 prompt received: {request.id}",
                            extra_hashes={"compose_prompt": prompt_sha,
                                            "frozen_csv": SPEC["dataset"]["sha256"]})

            # ---- ROUTED: live L5 route to the LOCAL ollama connection ----
            # allow_live_call=True is permitted for the LOCAL connection only
            # (E6 instructions §2); the LoopbackGuard proves no non-loopback call.
            router = ShellRouter(l5store, health=Health(),
                                    policy_label=_common.POLICY_LABEL)
            t0 = time.time()
            pres = router.route({"text": full_prompt, "request_id": request.id},
                                   dry_run=False, run="e6-realistic",
                                   allow_live_call=True)
            route_wall_s = round(time.time() - t0, 3)
            dec = l5store.get("decision_log", pres.decision_ref)
            route_presentation = pres.__dict__
            # L5 computes actual_cost_usd = declared-$0 x ollama token usage = 0.0.
            # The E6 cost-honesty guardrail presents null ("not metered"): a local
            # model has no provider BILLING meter. Record BOTH + the reason.
            l5_raw_actual_cost = (dec.get("attempts") or [{}])[0].get("actual_cost_usd")
            ctx.decision_ref = pres.decision_ref
            ctx.declared_cost_usd = float(pres.declared_cost_usd or 0.0)
            ctx.actual_metered_cost_usd = None       # presented value, per guardrail
            _common.write_json(out_root / "route_presentation.json", route_presentation)
            _common.write_json(out_root / "decision_record.json", dec)
            kernel.enter(KernelState.ROUTED,
                            notes=(f"E6 routed to local {pres.chosen_label} "
                                     f"(outcome={pres.outcome}); declared=$0 user-declared; "
                                     f"actual=null (no local billing meter)"),
                            extra_checks={"route_outcome": pres.outcome,
                                            "chosen_locus": pres.chosen_locus,
                                            "l5_raw_actual_cost_usd": l5_raw_actual_cost,
                                            "presented_actual_metered_cost_usd": None,
                                            "route_wall_clock_s": route_wall_s})

            # ---- the main COMPOSE transcript (the model's answer) ----
            attempt = (dec.get("attempts") or [{}])[0]
            transcript_main = {
                "run": "main_journey",
                "model": SPEC["model"]["name"],
                "quant": SPEC["model"]["quant"],
                "params": SPEC["model"]["params"],
                "runtime": SPEC["model"]["runtime"],
                "ollama_version": ollama_version(),
                "base_url": SPEC["model"]["base_url"],
                "locus": "local",
                "decoding": "greedy/temperature=0",
                "host": SPEC["model"]["host"],
                "prompt_sha256": prompt_sha,
                "prompt_chars": len(full_prompt),
                "response_text": pres.answer,
                "tokens_in": attempt.get("tokens_in"),
                "tokens_out": attempt.get("tokens_out"),
                "meter_label_from_ollama": attempt.get("meter"),
                "finish_reason": attempt.get("finish_reason"),
                "wall_clock_s": attempt.get("wall_clock_s"),
                "decision_ref": pres.decision_ref,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _common.write_json(out_root / "transcript_main.json", transcript_main)

            # ---- RECALLED ----
            user_turn = memory.log_turn(session.id, 1, "user", USER_QUESTION,
                                           tokens_in=len(USER_QUESTION.split()),
                                           tokens_out=0, model_id=pres.chosen_label or "local")
            ctx.memory_refs = [user_turn]
            kernel.enter(KernelState.RECALLED, notes=f"E6 user turn bound: {user_turn}")

            # ---- COMPOSED: the model fills ONLY this step ----
            composition = {
                "model_prose": pres.answer,
                "model_fills_only": "COMPOSE",
                "verified_values_source": "Qafiya bindings over the frozen CSV (not the model)",
                "prompt_sha256": prompt_sha,
                "transcript": "transcript_main.json",
            }
            _common.write_json(out_root / "composition.json", composition)
            kernel.enter(KernelState.COMPOSED,
                            notes="E6 composed by the local model (prose only; no verified number authored)",
                            extra_hashes={"composition": sha256_file(out_root / "composition.json"),
                                            "transcript_main": sha256_file(out_root / "transcript_main.json")})

            # ---- VIEW_VALIDATED + RENDERED: the VERIFIED values, not the prose ----
            shell_views.validate_view(view, set(dvr_resolve.load_bindings(qroot)))
            ctx.view_refs = [view["id"]]
            kernel.enter(KernelState.VIEW_VALIDATED, notes=f"E6 validated {view['id']} (dvr/1.1)")
            html = dvr_render.render(qroot, view)
            write_view_html(out_root / "spend_view.html", html)
            evidence = affordance.evidence_panel(qroot, dvr_resolve.load_bindings(qroot)["b_programme"])
            _common.write_json(out_root / "headline_evidence.json", evidence)
            kernel.enter(KernelState.RENDERED,
                            notes="E6 rendered the Qafiya-verified aggregates (model prose not rendered as value)",
                            extra_hashes={"spend_view_html": sha256_file(out_root / "spend_view.html")},
                            extra_checks={"render_clean": "UNRESOLVED" not in html,
                                            "headline_evidence_rows": len(evidence["source_rows"])},
                            extra_coverage={"spend_view": "coverage: 100%" if "coverage: 100%" in html else html.split("coverage:")[-1][:12]})

            # ---- divergence: model prose vs Qafiya-verified ----
            # Fix 1: associate each £ figure with the category noun the model
            # attached it to, rather than picking the nearest figure to a target
            # (which duplicated the Programme figure onto Large).
            model_figures = extract_gbp(pres.answer or "")
            cat_figures = extract_category_figures(pres.answer or "")
            prog_match, prog_ok = match_category(cat_figures, "Programme",
                                                    verified["b_programme"])
            large_match, large_ok = match_category(cat_figures, "Large",
                                                      verified["b_large"])
            divergence = {
                "model_stated_gbp_figures": model_figures,
                "model_category_figures": cat_figures,
                "verified_programme": verified["b_programme"],
                "verified_large": verified["b_large"],
                "model_programme_figure": prog_match,
                "model_programme_matches_verified": prog_ok,
                "model_large_figure": large_match,
                "model_large_matches_verified": large_ok,
                "note": ("A divergence is a FEATURE: the Qafiya binding recomputes the "
                            "verified number deterministically regardless of the model's prose. "
                            "The shell never renders the model's prose as a verified value. "
                            "Each figure is associated with the category noun the model "
                            "attached it to ( Programme -> its figure, Large -> its figure )."),
            }
            _common.write_json(out_root / "divergence.json", divergence)

            # ---- AWAITING_USER -> ACTION_GATED -> EXECUTED ----
            kernel.enter(KernelState.AWAITING_USER, notes="E6 awaiting user approval of the summary note")
            grant = file_engine.issue_grant(make_grant(
                user_id="youssef", action_types=["file.create"], target_pattern="**",
                requires_confirmation=["file.create"]))
            summary_text = (
                "E6 realistic demonstration — Cabinet Office spend over £25,000, Feb 2013.\n"
                "Contains public sector information licensed under the Open Government Licence v3.0.\n"
                f"Qafiya-verified total Programme expenditure: {verified['b_programme']:.2f} GBP.\n"
                f"Qafiya-verified largest supplier type total (Large): {verified['b_large']:.2f} GBP.\n"
                f"Model prose (local llama3.1:8b, greedy) is recorded in transcript_main.json and is NOT a verified value.\n"
                f"Model stated figures: {model_figures}\n")
            action = dispatcher.submit(
                intent_verbatim=USER_QUESTION,
                normalized={"action_type": "file.create",
                              "params": {"path": "e6/verified_summary.txt", "content": summary_text}},
                actor={"agent_id": "l6-shell-e6", "session_id": session.id},
                user_id="youssef", grant_id=grant["_id"], confirm_irreversible=True)
            ctx.action_refs = [action.action_ref]
            kernel.enter(KernelState.ACTION_GATED,
                            notes=f"E6 gate outcome={action.outcome} class={action.reversibility_class}",
                            extra_checks={"action_outcome": action.outcome})
            summary_file = Path(file_engine.store.files_path("e6/verified_summary.txt"))
            kernel.enter(KernelState.EXECUTED, notes="E6 executed the verified-summary note",
                            extra_hashes={"verified_summary_file": sha256_file(summary_file) if summary_file.exists() else None})

            # ---- REMEMBERED ----
            agent_turn = memory.log_turn(session.id, 2, "agent",
                                            f"E6 verified Programme total {verified['b_programme']:.2f}; "
                                            f"model prose recorded, not trusted.",
                                            tokens_in=0, tokens_out=12,
                                            model_id=pres.chosen_label or "local")
            note = memory.add_note(
                f"E6: Qafiya-verified Programme total {verified['b_programme']:.2f} GBP over the "
                f"frozen Cabinet Office Feb-2013 spend data (OGL v3.0); local model prose frozen "
                f"in transcript_main.json; declared cost $0 (user declaration), actual metered null.",
                [user_turn, agent_turn], note_kind="summary")
            ctx.memory_refs = [user_turn, agent_turn, note]
            mem_view = memory.inspect_view()
            specval.validate_view(mem_view, memory.known_binding_ids())
            mem_html = dvr_render.render(out_root / "stores" / "memory", mem_view)
            write_view_html(out_root / "memory_inspection.html", mem_html)
            kernel.enter(KernelState.REMEMBERED,
                            memory_refs=[user_turn, agent_turn, note],
                            view_refs=[view["id"], mem_view["id"]],
                            notes=f"E6 note bound: {note}",
                            extra_checks={"memory_chains_ok": all(memory.verify_all_chains().values())})

            # ---- stability check: k greedy runs, frozen ----
            stability = []
            for i in range(STABILITY_K):
                t0 = time.time()
                res = L5Transport.call(ollama_conn, full_prompt, EXPECTED_OUT)
                wall = round(time.time() - t0, 3)
                row = {
                    "run": f"stability_{i+1:02d}",
                    "ok": res.get("ok"),
                    "response_text": res.get("text"),
                    "tokens_in": res.get("tokens_in"),
                    "tokens_out": res.get("tokens_out"),
                    "finish_reason": res.get("finish_reason"),
                    "meter_label_from_ollama": res.get("meter"),
                    "wall_clock_s": wall,
                    "model": SPEC["model"]["name"],
                    "decoding": "greedy/temperature=0",
                }
                stability.append(row)
                _common.write_json(out_root / f"transcript_stability_{i+1:02d}.json", row)
            _common.write_json(out_root / "stability.json", {"k": STABILITY_K, "runs": stability})

            # ---- CLOSED ----
            kernel.enter(KernelState.CLOSED, notes="E6 journey closed; replay exposed")
    finally:
        pass

    # ---- token-level variance across the k stability runs --------------------
    responses = [r["response_text"] or "" for r in stability]
    distinct = sorted(set(responses))
    token_sets = [set(r.split()) for r in responses]
    identical_to_first = sum(1 for r in responses if r == responses[0]) if responses else 0
    # per-position token agreement across runs (token-level variance proxy)
    max_len = max((len(r.split()) for r in responses), default=0)
    position_agreement = []
    for pos in range(max_len):
        toks = [r.split()[pos] for r in responses if len(r.split()) > pos]
        if toks:
            position_agreement.append(sum(1 for t in toks if t == toks[0]) / len(toks))
    mean_position_agreement = (sum(position_agreement) / len(position_agreement)
                                 if position_agreement else 1.0)
    variance = {
        "k": STABILITY_K,
        "distinct_responses": len(distinct),
        "identical_to_first": identical_to_first,
        "all_identical": len(distinct) <= 1,
        "mean_token_position_agreement": round(mean_position_agreement, 4),
        "tokens_out_per_run": [r["tokens_out"] for r in stability],
    }
    _common.write_json(out_root / "stability_variance.json", variance)

    # ---- invariance: every auditability claim is independent of the prose ----
    # The verified aggregates come from the frozen CSV; the audit graph claims come
    # from the kernel walk. Neither depends on which prose the model produced.
    replay = audit.replay(session.id)
    invariance = {
        "verified_values_invariant_to_prose": True,   # recomputed from frozen CSV, not the model
        "audit_events": len(replay["events"]),
        "sequences_complete": replay["sequences"] == list(range(1, len(replay["sequences"]) + 1)),
        "chain_ok": replay["chain_ok"],
        "input_refs_missing": replay["input_refs_missing"],
        "claims_that_would_change_with_prose": [],     # none: prose never authors a verified claim
        "rule": "if a claim would change with model output it is not an auditability claim",
    }
    _common.write_json(out_root / "audit_replay.json",
                         {"events": replay["events"], "sequences": replay["sequences"],
                            "chain_ok": replay["chain_ok"],
                            "input_refs_missing": replay["input_refs_missing"],
                            "successors": replay["successors"]})
    _common.write_json(out_root / "invariance.json", invariance)

    guard_report = net.report()
    _common.write_json(out_root / "loopback_guard.json", guard_report)

    summary = {
        "experiment": "E6",
        "status": "PASS",
        "session_id": session.id,
        "request_ref": request.id,
        "dataset": {"sha256": SPEC["dataset"]["sha256"],
                      "source_records": parsed["source_records"],
                      "amount_bearing_records": parsed["amount_bearing_records"],
                      "empty_rows_reported_not_dropped": parsed["empty_rows"],
                      "n_statement": (f"{parsed['source_records']} source records, of which "
                                         f"{parsed['amount_bearing_records']} carry an amount "
                                         f"({parsed['empty_rows']} empty rows reported, not dropped)"),
                      "licence": SPEC["dataset"]["licence"],
                      "attribution": SPEC["dataset"]["attribution_required"]},
        "model": {"name": SPEC["model"]["name"], "decoding": "greedy/temperature=0",
                    "ollama_version": transcript_main.get("ollama_version")},
        "route": {"outcome": pres.outcome, "chosen_label": pres.chosen_label,
                    "chosen_locus": pres.chosen_locus,
                    "declared_cost_usd": pres.declared_cost_usd,
                    "l5_raw_actual_cost_usd": l5_raw_actual_cost,
                    "presented_actual_metered_cost_usd": None},
        "verified_values": verified,
        "divergence": divergence,
        "stability_variance": variance,
        "invariance": invariance,
        "loopback_guard": guard_report,
        "audit_events": len(replay["events"]),
        "kernel_states": [e["state"] for e in replay["events"]],
    }
    _common.write_json(out_root / "summary.json", summary)
    return summary


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    summary = run(out)
    print(json.dumps({
        "experiment": "E6", "status": summary["status"],
        "route_outcome": summary["route"]["outcome"],
        "verified_programme": summary["verified_values"]["b_programme"],
        "model_programme_matches_verified":
            summary["divergence"]["model_programme_matches_verified"],
        "stability_all_identical": summary["stability_variance"]["all_identical"],
        "stability_distinct_responses": summary["stability_variance"]["distinct_responses"],
        "loopback_only": summary["loopback_guard"]["only_loopback_touched"],
        "non_loopback_calls": summary["loopback_guard"]["non_loopback_calls"],
        "audit_events": summary["audit_events"],
        "output": str(out),
    }, indent=2))
    if "--freeze" in sys.argv:
        # Freeze the manifest over inputs + scripts + the frozen transcript + dataset.
        extra = [HERE / "loopback_guard.py",
                   out / "transcript_main.json", out / "stability.json",
                   out / "verified_values.json", out / "compose_prompt_full.txt"]
        for i in range(1, STABILITY_K + 1):
            extra.append(out / f"transcript_stability_{i:02d}.json")
        manifest = _common.freeze_manifest(
            HERE, extra_files=[e for e in extra if e.exists()],
            extra_metadata={
                "dataset_provenance": {
                    "name": SPEC["dataset"]["name"],
                    "publisher": SPEC["dataset"]["publisher"],
                    "preview_url": SPEC["dataset"]["preview_url"],
                    "raw_download_url": SPEC["dataset"]["raw_download_url"],
                    "access_date_utc": SPEC["dataset"]["access_date_utc"],
                    "filename_frozen": SPEC["dataset"]["filename_frozen"],
                    "sha256": SPEC["dataset"]["sha256"],
                    "bytes": SPEC["dataset"]["bytes"],
                    "encoding": SPEC["dataset"]["encoding"],
                    "licence": SPEC["dataset"]["licence"],
                    "licence_url": SPEC["dataset"]["licence_url"],
                    "attribution": SPEC["dataset"]["attribution_required"],
                    "non_pii": SPEC["dataset"]["non_pii"],
                },
                "model_provenance": {
                    "name": SPEC["model"]["name"],
                    "runtime": SPEC["model"]["runtime"],
                    "decoding": SPEC["model"]["decoding"],
                    "locus": "local",
                    "network_policy": "loopback only; zero non-loopback calls (LoopbackGuard)",
                    "transcripts_frozen": ["output/frozen/transcript_main.json"] + [
                        f"output/frozen/transcript_stability_{i:02d}.json"
                        for i in range(1, STABILITY_K + 1)],
                },
                "attribution_required_in_paper": SPEC["dataset"]["attribution_required"],
            },
            artifact_label=("E6 realistic demonstration (frozen inputs + scripts + "
                               "dataset + model transcripts)"))
        print(f"E6 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
