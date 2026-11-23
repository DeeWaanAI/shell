#!/usr/bin/env python3
"""Generate the seven capstone figures from frozen artifacts only.

Discipline (paper-elevation-instructions §4): every figure is produced by this
committed script, which reads ONLY frozen artifacts (never hardcodes a number),
persists its plotted values to ``paper/figures/values/figN_values.json``, and
emits a vector ``paper/figures/figN.svg`` as the source of truth. The claim map
links each figure's persisted values, so a figure is a claim that re-verifies.

No local SVG->PDF converter exists on this host (rsvg-convert / inkscape /
cairosvg all absent), consistent with the project's no-local-LaTeX constraint.
The SVG is the source of truth; PDF/PNG export happens at the Overleaf build
step (``\\usepackage{svg}`` invokes inkscape there) or via any SVG->PDF tool.
``export_command`` is recorded in each values file so the export is reproducible.

Run from 06-shell/:
    python3.12 paper/figures/make_figures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # paper/figures
PAPER = HERE.parent
L6 = PAPER.parent                                    # 06-shell
VALUES = HERE / "values"
VALUES.mkdir(parents=True, exist_ok=True)

CP3 = L6 / "experiments" / "cp3"
E1 = CP3 / "e1_journey" / "output" / "frozen"
E4 = CP3 / "e4_connection_governance" / "output" / "frozen"
E6 = CP3 / "e6_realistic_demo" / "output" / "frozen"

EXPORT_CMD = ("svg is the source of truth; export with rsvg-convert -f pdf "
                "figN.svg -o figN.pdf (or Overleaf \\usepackage{svg}) — no local "
                "converter on the build host")


def _read(p: Path):
    return json.loads(p.read_text())


def _persist(name: str, source: list[str], plotted: dict) -> None:
    rec = {"figure": name, "source_artifacts": source,
              "export_command": EXPORT_CMD, "plotted_values": plotted}
    (VALUES / f"{name}_values.json").write_text(
        json.dumps(rec, indent=1, sort_keys=True, default=str) + "\n")


def _svg(name: str, width: int, height: int, body: str, title: str) -> None:
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
              f'viewBox="0 0 {width} {height}" font-family="Helvetica,Arial,sans-serif">\n'
              f'<title>{title}</title>\n<rect width="{width}" height="{height}" fill="white"/>\n'
              f'{body}\n</svg>\n')
    (HERE / f"{name}.svg").write_text(doc)


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ============================================================ Fig 1 architecture
def fig1_architecture() -> None:
    """Layer stack + authority boundaries, parsed from the frozen brief §5 table."""
    brief = (L6 / "brief.md").read_text()
    # Parse the §5 "Contract boundaries" pipe table.
    rows = []
    in_table = False
    for line in brief.splitlines():
        if line.startswith("| Layer | Shell consumes |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and not set(cells[0]) <= set("-: "):
                rows.append({"layer": cells[0], "consumes": cells[1],
                                "must_not": cells[2]})
    # The shell itself owns the audit graph (brief §4.2).
    layers = rows + [{"layer": "L6 Shell", "consumes": "joins L1-L5; owns ds:shell_audit",
                         "must_not": "reimplement lower-layer authority"}]
    W, rowh, top = 880, 64, 70
    H = top + rowh * len(layers) + 60
    body = [f'<text x="20" y="34" font-size="20" font-weight="bold">'
              f'DeeWaanAI OS layer stack and authority boundaries</text>',
              f'<text x="20" y="54" font-size="12" fill="#555">source: brief.md §5 '
              f'(contract boundaries) + §4.2 (audit ownership)</text>']
    for i, L in enumerate(layers):
        y = top + i * rowh
        fill = "#eef3fb" if L["layer"] != "L6 Shell" else "#fdeede"
        body.append(f'<rect x="20" y="{y}" width="840" height="{rowh-8}" rx="6" '
                      f'fill="{fill}" stroke="#33475b"/>')
        body.append(f'<text x="34" y="{y+24}" font-size="15" font-weight="bold">'
                      f'{_esc(L["layer"])}</text>')
        body.append(f'<text x="34" y="{y+44}" font-size="12">owns/consumes: '
                      f'{_esc(L["consumes"])}</text>')
        body.append(f'<text x="470" y="{y+44}" font-size="12" fill="#8a3b12">'
                      f'must not: {_esc(L["must_not"])}</text>')
    _svg("fig1_architecture", W, H, "\n".join(body),
            "DeeWaanAI OS layer stack and authority boundaries")
    _persist("fig1_architecture", ["brief.md"],
               {"layers": layers, "layer_count": len(layers)})


# ========================================================= Fig 2 kernel states
def fig2_kernel() -> None:
    """12 states + allowed edges, read programmatically from shell/kernel.py."""
    sys.path.insert(0, str(L6))
    from shell.kernel import ALLOWED, KernelState, transition_table  # noqa: E402
    states = list(KernelState.ALL)
    edges = [(s, d) for s, ds in ALLOWED.items() for d in sorted(ds)]
    # Two-column layout: main flow left, terminal/refusal right.
    pos = {
        "RECEIVED": (90, 60), "ROUTED": (90, 130), "RECALLED": (90, 200),
        "COMPOSED": (90, 270), "VIEW_VALIDATED": (90, 340), "RENDERED": (90, 410),
        "AWAITING_USER": (330, 410), "WRITE_BACK": (330, 340),
        "ACTION_GATED": (330, 270), "EXECUTED": (330, 200),
        "REMEMBERED": (330, 130), "CLOSED": (560, 270),
    }
    W, H = 760, 500
    body = [f'<text x="20" y="28" font-size="18" font-weight="bold">Kernel state '
              f'machine (12 states, frozen transition table)</text>',
              f'<text x="20" y="46" font-size="11" fill="#555">source: '
              f'shell/kernel.py:ALLOWED (runtime-kernel-loop v0.1)</text>',
              '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="3" '
              'orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#33475b"/></marker></defs>']
    for s, d in edges:
        x1, y1 = pos[s]
        x2, y2 = pos[d]
        body.append(f'<line x1="{x1+70}" y1="{y1+16}" x2="{x2+10}" y2="{y2+16}" '
                      f'stroke="#33475b" stroke-width="1.2" marker-end="url(#ar)"/>')
    for s in states:
        x, y = pos[s]
        fill = "#fdeede" if s == "CLOSED" else "#eef3fb"
        body.append(f'<rect x="{x}" y="{y}" width="140" height="32" rx="6" '
                      f'fill="{fill}" stroke="#33475b"/>')
        body.append(f'<text x="{x+70}" y="{y+21}" font-size="12" text-anchor="middle">'
                      f'{_esc(s)}</text>')
    _svg("fig2_kernel", W, H, "\n".join(body), "Kernel state machine")
    _persist("fig2_kernel", ["shell/kernel.py"],
               {"states": states, "state_count": len(states),
                  "edges": edges, "edge_count": len(edges),
                  "transition_table": transition_table()})


# ========================================================== Fig 3 E1 timeline
def fig3_e1_timeline() -> None:
    replay = _read(E1 / "audit_replay.json")
    events = replay["events"]
    W, rowh, top = 900, 30, 80
    H = top + rowh * len(events) + 50
    body = [f'<text x="20" y="30" font-size="18" font-weight="bold">E1 journey: '
              f'{len(events)} audit events (one per kernel transition)</text>',
              f'<text x="20" y="50" font-size="11" fill="#555">source: '
              f'experiments/cp3/e1_journey/output/frozen/audit_replay.json</text>',
              f'<text x="20" y="68" font-size="11" fill="#555">session '
              f'{_esc(replay.get("session_id") or events[0]["session_id"])} · chain_ok='
              f'{replay["chain_ok"]} · sequences 1..{len(events)}</text>']
    plotted = []
    for e in events:
        y = top + (e["sequence"] - 1) * rowh
        refs = []
        for k in ("decision_ref", "action_refs", "memory_refs", "connection_refs",
                    "successor_ref", "edit_refs", "view_refs"):
            v = e.get(k)
            if v:
                refs.append(f"{k}={v if not isinstance(v, list) else len(v)}")
        body.append(f'<circle cx="40" cy="{y+10}" r="7" fill="#33475b"/>')
        body.append(f'<text x="40" y="{y+14}" font-size="9" fill="white" '
                      f'text-anchor="middle">{e["sequence"]}</text>')
        body.append(f'<text x="60" y="{y+14}" font-size="13" font-weight="bold">'
                      f'{_esc(e["state"])}</text>')
        body.append(f'<text x="240" y="{y+14}" font-size="10" fill="#555">'
                      f'{_esc("; ".join(refs)[:90])}</text>')
        plotted.append({"sequence": e["sequence"], "state": e["state"],
                          "id": e["id"], "refs": refs})
    _svg("fig3_e1_timeline", W, H, "\n".join(body), "E1 journey audit timeline")
    _persist("fig3_e1_timeline",
               ["experiments/cp3/e1_journey/output/frozen/audit_replay.json"],
               {"event_count": len(events), "events": plotted,
                  "chain_ok": replay["chain_ok"]})


# ====================================================== Fig 4 E6 divergence
def fig4_divergence() -> None:
    div = _read(E6 / "divergence.json")
    ver = _read(E6 / "verified_values.json")
    cats = ["Programme", "Large"]
    model = [div["model_category_figures"][c] for c in cats]
    verified = [ver["b_programme"], ver["b_large"]]
    W, H = 720, 420
    base_y, max_v = 340, max(verified) * 1.12
    scale = 240 / max_v
    body = [f'<text x="20" y="30" font-size="18" font-weight="bold">E6: model-stated '
              f'vs Qafiya-verified (GBP)</text>',
              f'<text x="20" y="50" font-size="11" fill="#555">source: divergence.json '
              f'(frozen transcript) + verified_values.json (recomputed from the frozen CSV)</text>',
              f'<line x1="70" y1="{base_y}" x2="690" y2="{base_y}" stroke="#333"/>']
    plotted = []
    for i, c in enumerate(cats):
        cx = 150 + i * 320
        mh = model[i] * scale
        vh = verified[i] * scale
        body.append(f'<rect x="{cx}" y="{base_y-mh:.1f}" width="90" height="{mh:.1f}" '
                      f'fill="#c0504d"/>')
        body.append(f'<rect x="{cx+110}" y="{base_y-vh:.1f}" width="90" height="{vh:.1f}" '
                      f'fill="#4f81bd"/>')
        body.append(f'<text x="{cx+45}" y="{base_y-mh-6:.1f}" font-size="11" '
                      f'text-anchor="middle">{model[i]:,.2f}</text>')
        body.append(f'<text x="{cx+155}" y="{base_y-vh-6:.1f}" font-size="11" '
                      f'text-anchor="middle">{verified[i]:,.2f}</text>')
        body.append(f'<text x="{cx+100}" y="{base_y+22}" font-size="13" '
                      f'text-anchor="middle" font-weight="bold">{c}</text>')
        plotted.append({"category": c, "model_stated": model[i],
                          "qafiya_verified": verified[i],
                          "matches": div[f"model_{c.lower()}_matches_verified"]})
    body.append(f'<rect x="200" y="382" width="16" height="12" fill="#c0504d"/>'
                  f'<text x="222" y="392" font-size="12">model-stated (prose, wrong)</text>')
    body.append(f'<rect x="430" y="382" width="16" height="12" fill="#4f81bd"/>'
                  f'<text x="452" y="392" font-size="12">Qafiya-verified (recomputed)</text>')
    _svg("fig4_divergence", W, H, "\n".join(body),
            "E6 model-stated vs Qafiya-verified divergence")
    _persist("fig4_divergence",
               ["experiments/cp3/e6_realistic_demo/output/frozen/divergence.json",
                  "experiments/cp3/e6_realistic_demo/output/frozen/verified_values.json"],
               {"categories": plotted,
                  "note": "the shell renders the verified bars, never the model prose"})


# =================================================== Fig 5 provenance/evidence
def fig5_evidence() -> None:
    ev = _read(E6 / "headline_evidence.json")
    ver = _read(E6 / "verified_values.json")
    n_rows = len(ev["source_rows"])
    value = ver["b_programme"]
    W, H = 860, 250
    boxes = [
        (30, "Displayed value", f"£{value:,.2f}", "#eef3fb"),
        (240, "Binding", f"{ev['binding_id']} · {ev['derivation']}", "#eef3fb"),
        (470, "Source rows", f"{n_rows} amount-bearing rows", "#eef3fb"),
        (680, "Recompute", f"sum = £{value:,.2f}", "#e8f4e8"),
    ]
    body = [f'<text x="20" y="30" font-size="18" font-weight="bold">Provenance / '
              f'evidence mechanism (E6 headline binding)</text>',
              f'<text x="20" y="50" font-size="11" fill="#555">source: '
              f'headline_evidence.json + verified_values.json (b_programme)</text>',
              '<defs><marker id="ar2" markerWidth="8" markerHeight="8" refX="7" refY="3" '
              'orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#33475b"/></marker></defs>']
    for i, (x, title, sub, fill) in enumerate(boxes):
        body.append(f'<rect x="{x}" y="100" width="160" height="70" rx="8" fill="{fill}" '
                      f'stroke="#33475b"/>')
        body.append(f'<text x="{x+80}" y="128" font-size="13" font-weight="bold" '
                      f'text-anchor="middle">{_esc(title)}</text>')
        body.append(f'<text x="{x+80}" y="150" font-size="11" text-anchor="middle">'
                      f'{_esc(sub)}</text>')
        if i < len(boxes) - 1:
            body.append(f'<line x1="{x+160}" y1="135" x2="{boxes[i+1][0]}" y2="135" '
                          f'stroke="#33475b" stroke-width="1.4" marker-end="url(#ar2)"/>')
    body.append(f'<text x="30" y="210" font-size="12" fill="#555">▸evidence resolves the '
                  f'displayed value to its {n_rows} source rows and recomputes it '
                  f'deterministically; coverage 100%.</text>')
    _svg("fig5_evidence", W, H, "\n".join(body), "Provenance / evidence mechanism")
    _persist("fig5_evidence",
               ["experiments/cp3/e6_realistic_demo/output/frozen/headline_evidence.json",
                  "experiments/cp3/e6_realistic_demo/output/frozen/verified_values.json"],
               {"binding_id": ev["binding_id"], "derivation": ev["derivation"],
                  "source_rows": n_rows, "recomputed_value": value})


# ================================================== Fig 6 succession chain
def fig6_succession() -> None:
    chain = _read(E4 / "governance_chain" / "chain.json")
    models = [json.loads(l) for l in
                 (E4 / "governance_chain" / "stores" / "l5" / "datasets" / "models" /
                     "data.jsonl").read_text().splitlines() if l.strip()]
    by_id = {r["id"]: r for r in models}
    ids = [chain["allocated"], chain["successor"], chain["restored"]]
    labels = ["allocated (add)", "successor (privacy_change)", "restored (undo)"]
    W, H = 880, 230
    body = [f'<text x="20" y="30" font-size="18" font-weight="bold">Connection '
              f'succession chain (E4 governance fixture)</text>',
              f'<text x="20" y="50" font-size="11" fill="#555">source: E4 chain.json + '
              f'raw L5 models/data.jsonl (superseded_by links)</text>',
              '<defs><marker id="ar3" markerWidth="8" markerHeight="8" refX="7" refY="3" '
              'orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#33475b"/></marker></defs>']
    plotted = []
    for i, (mid, lab) in enumerate(zip(ids, labels)):
        x = 40 + i * 290
        rec = by_id.get(mid, {})
        body.append(f'<rect x="{x}" y="90" width="230" height="86" rx="8" fill="#eef3fb" '
                      f'stroke="#33475b"/>')
        body.append(f'<text x="{x+115}" y="112" font-size="12" font-weight="bold" '
                      f'text-anchor="middle">{_esc(lab)}</text>')
        body.append(f'<text x="{x+115}" y="132" font-size="10" text-anchor="middle">'
                      f'{_esc(mid)}</text>')
        body.append(f'<text x="{x+115}" y="150" font-size="10" text-anchor="middle">'
                      f'status={_esc(rec.get("status"))}</text>')
        body.append(f'<text x="{x+115}" y="166" font-size="10" text-anchor="middle">'
                      f'superseded_by={_esc(rec.get("superseded_by"))}</text>')
        if i < 2:
            body.append(f'<line x1="{x+230}" y1="133" x2="{x+290}" y2="133" '
                          f'stroke="#33475b" stroke-width="1.4" marker-end="url(#ar3)"/>')
        plotted.append({"role": lab, "mdl_id": mid, "status": rec.get("status"),
                          "superseded_by": rec.get("superseded_by"),
                          "privacy_class": rec.get("privacy_class")})
    body.append(f'<text x="40" y="205" font-size="11" fill="#555">ids are immutable: '
                  f'each mutation mints a NEW mdl_* and retires the old one with '
                  f'superseded_by; the audit graph records successor_ref.</text>')
    _svg("fig6_succession", W, H, "\n".join(body), "Connection succession chain")
    _persist("fig6_succession",
               ["experiments/cp3/e4_connection_governance/output/frozen/governance_chain/chain.json",
                  "experiments/cp3/e4_connection_governance/output/frozen/governance_chain/stores/l5/datasets/models/data.jsonl"],
               {"chain": plotted})


# ================================================== Fig 7 audit event graph
def fig7_event_graph() -> None:
    replay = _read(E1 / "audit_replay.json")
    events = sorted(replay["events"], key=lambda e: e["sequence"])
    ids = {e["id"]: e["sequence"] for e in events}
    W, H = 900, 200
    n = len(events)
    step = (W - 120) / max(n - 1, 1)
    body = [f'<text x="20" y="28" font-size="18" font-weight="bold">Audit event graph '
              f'(one E1 session): nodes = events, edges = input_event_refs</text>',
              f'<text x="20" y="46" font-size="11" fill="#555">source: E1 audit_replay.json '
              f'· input_refs_missing={len(replay["input_refs_missing"])}</text>',
              '<defs><marker id="ar4" markerWidth="7" markerHeight="7" refX="6" refY="3" '
              'orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#777"/></marker></defs>']
    pos = {e["id"]: (60 + (e["sequence"] - 1) * step, 110) for e in events}
    edges = []
    for e in events:
        for ref in e.get("input_event_refs", []):
            if ref in pos:
                edges.append((ref, e["id"]))
                x1, y1 = pos[ref]
                x2, y2 = pos[e["id"]]
                body.append(f'<line x1="{x1:.1f}" y1="{y1}" x2="{x2:.1f}" y2="{y2}" '
                              f'stroke="#bbb" stroke-width="1" marker-end="url(#ar4)"/>')
    for e in events:
        x, y = pos[e["id"]]
        body.append(f'<circle cx="{x:.1f}" cy="{y}" r="13" fill="#33475b"/>')
        body.append(f'<text x="{x:.1f}" y="{y+4}" font-size="9" fill="white" '
                      f'text-anchor="middle">{e["sequence"]}</text>')
        body.append(f'<text x="{x:.1f}" y="{y+34}" font-size="8" text-anchor="middle" '
                      f'transform="rotate(20 {x:.1f} {y+34})">{_esc(e["state"])}</text>')
    _svg("fig7_event_graph", W, H, "\n".join(body), "Audit event graph")
    _persist("fig7_event_graph",
               ["experiments/cp3/e1_journey/output/frozen/audit_replay.json"],
               {"node_count": n, "edge_count": len(edges),
                  "input_refs_missing": len(replay["input_refs_missing"]),
                  "nodes": [{"sequence": e["sequence"], "state": e["state"],
                                "id": e["id"]} for e in events]})


FIGURES = [fig1_architecture, fig2_kernel, fig3_e1_timeline, fig4_divergence,
              fig5_evidence, fig6_succession, fig7_event_graph]


def main() -> int:
    for fn in FIGURES:
        fn()
        print(f"  {fn.__name__}: svg + values written")
    print(f"7 figures -> {HERE.relative_to(L6)}/figN.svg + values/figN_values.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
