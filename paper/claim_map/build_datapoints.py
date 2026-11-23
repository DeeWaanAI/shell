#!/usr/bin/env python3
"""Build the capstone claim-map datapoint registry, DATA-FIRST.

Walks the frozen spine-result artifacts (the authoritative recomputed-number
files for each experiment + the regressions) and emits one DP-NNNN per scalar
the capstone draft cites. Values are read from the frozen files, never typed by
hand, so a datapoint cannot drift from its source. Two HTML-embedded numbers
(the pre-edit quarter total and the post-edit quarter total in the E1 renders)
are registered as text-match datapoints against the frozen rendered artifacts.

Run from 06-shell/:
    python3.12 paper/claim_map/build_datapoints.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # paper/claim_map
PAPER = HERE.parent                                 # paper
L6 = PAPER.parent                                   # 06-shell
OUT = HERE / "datapoints.json"


def _read(rel: Path):
    return json.loads((L6 / rel).read_text())


def _get(obj, segments):
    for s in segments:
        obj = obj[int(s)] if isinstance(obj, list) else obj[s]
    return obj


# (dp_id, source_file_rel, key_segments, statistic, device, note)
JSON_SCALARS = [
    # --- pre-flight regression (frozen cross-layer demo) ---
    ("DP-0001", "preflight/spine-result.json", ["q3_total_recomputed_from_raw"], "sum", "local-m4", "pre-flight Q3 total after the frozen edit"),
    ("DP-0002", "preflight/spine-result.json", ["evidence_source_rows"], "count", "local-m4", "evidence source rows for the count binding"),
    ("DP-0003", "preflight/spine-result.json", ["journey_checks_recomputed"], "count", "local-m4", "pre-flight journey checks"),
    ("DP-0004", "preflight/spine-result.json", ["frozen_files_verified"], "count", "local-m4", "pre-flight frozen manifest files"),
    # --- E1 end-to-end journey ---
    ("DP-0005", "experiments/cp3/e1_journey/output/spine-result.json", ["audit_events"], "count", "local-m4", "E1 audit events"),
    ("DP-0006", "experiments/cp3/e1_journey/output/spine-result.json", ["q3_total_recomputed_from_raw"], "sum", "local-m4", "E1 Q3 total recomputed from raw"),
    ("DP-0007", "experiments/cp3/e1_journey/output/spine-result.json", ["edited_record", "amount"], "n/a", "local-m4", "E1 edited cell value"),
    ("DP-0008", "experiments/cp3/e1_journey/output/spine-result.json", ["route_outcome"], "n/a", "local-m4", "E1 route outcome (dry-run)"),
    # --- CP1 integration journey spine (36 checks) ---
    ("DP-0009", "experiments/shell-spine-result.json", ["summary_checks_passed"], "count", "local-m4", "CP1 journey spine checks"),
    # --- CP2 functional-gate battery ---
    ("DP-0010", "experiments/gates-spine-result.json", ["gates_recomputed"], "count", "local-m4", "CP2 gates recomputed (F1-F8)"),
    # --- E2 auditability ---
    ("DP-0011", "experiments/cp3/e2_auditability/output/spine-result.json", ["missing_ref_count_total"], "count", "local-m4", "E2 unresolved references across all variants"),
    # --- E5 shell limits ---
    ("DP-0012", "experiments/cp3/e5_shell_limits/output/spine-result.json", ["expressibility_ceiling"], "n/a", "local-m4", "E5 dvr expressibility ceiling"),
    ("DP-0013", "experiments/cp3/e5_shell_limits/output/spine-result.json", ["uncatchable_classes_reported"], "count", "local-m4", "E5 uncatchable classes reported"),
    # --- E6 realistic demonstration ---
    ("DP-0014", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["dataset", "source_records"], "count", "local-m4", "E6 source records in the frozen CSV"),
    ("DP-0015", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["dataset", "amount_bearing_records"], "count", "local-m4", "E6 amount-bearing records"),
    ("DP-0016", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["dataset", "empty_rows_reported_not_dropped"], "count", "local-m4", "E6 empty rows reported, not dropped"),
    ("DP-0017", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["verified_aggregates_recomputed_independently", "b_total"], "sum", "local-m4", "E6 verified total spend"),
    ("DP-0018", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["verified_aggregates_recomputed_independently", "b_programme"], "sum", "local-m4", "E6 verified Programme total (headline)"),
    ("DP-0019", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["verified_aggregates_recomputed_independently", "b_large"], "sum", "local-m4", "E6 verified Large-supplier total"),
    ("DP-0020", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["verified_aggregates_recomputed_independently", "b_count"], "count", "local-m4", "E6 count of amount-bearing records"),
    ("DP-0021", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["verified_aggregates_recomputed_independently", "b_min"], "min", "local-m4", "E6 most negative amount (credit)"),
    ("DP-0022", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["headline_evidence_rows"], "count", "local-m4", "E6 headline evidence source rows"),
    ("DP-0023", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["model_category_figures", "Programme"], "n/a", "local-m4", "E6 model-stated Programme figure (prose)"),
    ("DP-0024", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["model_category_figures", "Large"], "n/a", "local-m4", "E6 model-stated Large figure (prose)"),
    ("DP-0025", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["model_programme_matches_verified"], "n/a", "local-m4", "E6 Programme prose matches verified?"),
    ("DP-0026", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["model_large_matches_verified"], "n/a", "local-m4", "E6 Large prose matches verified?"),
    ("DP-0027", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["stability", "k"], "count", "local-m4", "E6 stability runs k"),
    ("DP-0028", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["stability", "distinct_responses"], "count", "local-m4", "E6 distinct responses across k greedy runs"),
    ("DP-0029", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["non_loopback_calls"], "count", "local-m4", "E6 non-loopback network calls (must be 0)"),
    ("DP-0030", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["loopback_ports_touched"], "n/a", "local-m4", "E6 loopback ports touched"),
    ("DP-0031", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["cost_honesty", "declared_cost_usd"], "n/a", "local-m4", "E6 declared cost (user declaration)"),
    ("DP-0032", "experiments/cp3/e6_realistic_demo/output/spine-result.json", ["cost_honesty", "presented_actual_metered_cost_usd"], "n/a", "local-m4", "E6 presented actual metered cost (null = not metered)"),
    # --- CP3 master spine ---
    ("DP-0033", "experiments/cp3/cp3-spine-result.json", ["snapshot_files_verified"], "count", "local-m4", "CP3 vendored snapshot files verified"),
]

# (dp_id, source_file_rel, verbatim_text_must_appear, note)
TEXT_MATCHES = [
    ("DP-0034", "experiments/cp3/e1_journey/output/frozen/qafiya_before.html", "10346.71", "E1 pre-edit quarter total in the frozen render"),
    ("DP-0035", "experiments/cp3/e1_journey/output/frozen/qafiya_after.html", "10481.96", "E1 post-edit quarter total in the frozen render"),
    ("DP-0036", "experiments/cp3/e6_realistic_demo/output/frozen/spend_view.html", "18801701.38", "E6 rendered view shows the verified Programme total, not the model prose"),
]


def main() -> int:
    datapoints = []
    for dp_id, src, segments, statistic, device, note in JSON_SCALARS:
        data = _read(Path(src))
        value = _get(data, segments)
        datapoints.append({
            "dp_id": dp_id, "kind": "json-scalar",
            "value": value, "statistic": statistic, "device": device,
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": ".".join(segments),
            "key_segments": segments,
            "verbatim_excerpt": json.dumps({segments[-1]: value}),
            "note": note,
        })
    # Count datapoints: the length of a frozen list/dict (structural counts the
    # draft cites). The verifier recomputes len() over the navigated value.
    COUNTS = [
        ("DP-0037", "experiments/cp3/e2_auditability/output/spine-result.json",
         ["variants"], "E2 negative variants (approve/reject/refuse/failure/unresolved)"),
        ("DP-0038", "experiments/cp3/e3_routing_cost/output/spine-result.json",
         ["cases"], "E3 routing cases (planned/answered/refused)"),
        ("DP-0039", "experiments/cp3/e6_realistic_demo/inputs/spec.json",
         ["qafiya_bindings", "bindings"], "E6 Qafiya bindings over the amount column"),
        ("DP-0044", "experiments/cp3/cp3-spine-result.json",
         ["experiments"], "frozen experiments the master spine runs (E1-E6)"),
        ("DP-0045", "experiments/cp3/cp3-spine-result.json",
         ["regressions"], "regressions the master spine keeps green (preflight, CP1, CP2)"),
    ]
    for dp_id, src, segments, note in COUNTS:
        data = _read(Path(src))
        value = len(_get(data, segments))
        datapoints.append({
            "dp_id": dp_id, "kind": "json-len",
            "value": value, "statistic": "count", "device": "local-m4",
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": ".".join(segments),
            "key_segments": segments, "extract": "len",
            "verbatim_excerpt": json.dumps({segments[-1]: value}),
            "note": note,
        })
    # Boolean governance flags (E4) — negatives/booleans are first-class claims.
    BOOLS = [
        ("DP-0040", "experiments/cp3/e4_connection_governance/output/spine-result.json",
         ["rejected_operation_refused"], "E4 a grant missing the action type refuses the operation"),
        ("DP-0041", "experiments/cp3/e4_connection_governance/output/spine-result.json",
         ["active_list_unchanged_after_rejection"], "E4 the rejected operation left the active list byte-identical"),
        ("DP-0042", "experiments/cp3/e4_connection_governance/output/spine-result.json",
         ["broken_entry_stays_active"], "E4 a broken entry is never implicitly retired"),
        ("DP-0043", "experiments/cp3/e4_connection_governance/output/spine-result.json",
         ["secret_value_absent"], "E4 no secret value appears in any record"),
    ]
    for dp_id, src, segments, note in BOOLS:
        data = _read(Path(src))
        value = _get(data, segments)
        datapoints.append({
            "dp_id": dp_id, "kind": "json-scalar",
            "value": value, "statistic": "n/a", "device": "local-m4",
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": ".".join(segments),
            "key_segments": segments,
            "verbatim_excerpt": json.dumps({segments[-1]: value}),
            "note": note,
        })
    # ---- v0.3: implementation metrics, citation counts, figure values ----
    METRICS = [
        ("DP-0046", "experiments/cp3/implementation_metrics.json", ["shell_owned_loc"], "sum", "shell-owned Python LOC"),
        ("DP-0047", "experiments/cp3/implementation_metrics.json", ["vendored_loc"], "sum", "vendored snapshot Python LOC"),
        ("DP-0048", "experiments/cp3/implementation_metrics.json", ["total_python_loc"], "sum", "total Python LOC"),
        ("DP-0049", "experiments/cp3/implementation_metrics.json", ["snapshot_files_pinned"], "count", "vendored snapshot files pinned"),
        ("DP-0050", "experiments/cp3/implementation_metrics.json", ["cp3_manifest_pinned_files"], "count", "cp3 manifest pinned files"),
        ("DP-0051", "experiments/cp3/implementation_metrics.json", ["cp3_live_l5_dataset_pins"], "count", "live L5 dataset pins"),
        ("DP-0052", "experiments/cp3/implementation_metrics.json", ["groups", "0", "loc"], "sum", "shell modules LOC"),
        ("DP-0053", "experiments/cp3/implementation_metrics.json", ["groups", "0", "files"], "count", "shell module files"),
        ("DP-0054", "experiments/cp3/implementation_metrics.json", ["groups", "1", "loc"], "sum", "top-level experiments LOC"),
        ("DP-0055", "experiments/cp3/implementation_metrics.json", ["groups", "1", "files"], "count", "top-level experiment files"),
        ("DP-0056", "experiments/cp3/implementation_metrics.json", ["groups", "2", "loc"], "sum", "CP3 experiments LOC"),
        ("DP-0057", "experiments/cp3/implementation_metrics.json", ["groups", "2", "files"], "count", "CP3 experiment files"),
        ("DP-0058", "experiments/cp3/implementation_metrics.json", ["groups", "3", "loc"], "sum", "preflight LOC"),
        ("DP-0059", "experiments/cp3/implementation_metrics.json", ["groups", "3", "files"], "count", "preflight files"),
        ("DP-0060", "experiments/cp3/implementation_metrics.json", ["groups", "4", "loc"], "sum", "vendored snapshot LOC"),
        ("DP-0061", "experiments/cp3/implementation_metrics.json", ["groups", "4", "files"], "count", "vendored snapshot Python files"),
        ("DP-0062", "paper/claim_map/references-verified.json", ["summary", "verified"], "count", "external references verified to resolve"),
        ("DP-0063", "paper/claim_map/references-verified.json", ["summary", "unresolved"], "count", "external references unresolved (must be 0)"),
        ("DP-0064", "paper/figures/values/fig2_kernel_values.json", ["plotted_values", "edge_count"], "count", "Fig 2 allowed kernel edges"),
        ("DP-0065", "paper/figures/values/fig2_kernel_values.json", ["plotted_values", "state_count"], "count", "Fig 2 kernel states"),
        ("DP-0066", "paper/figures/values/fig3_e1_timeline_values.json", ["plotted_values", "event_count"], "count", "Fig 3 E1 audit events"),
        ("DP-0067", "paper/figures/values/fig7_event_graph_values.json", ["plotted_values", "node_count"], "count", "Fig 7 audit-graph nodes"),
        ("DP-0068", "paper/figures/values/fig5_evidence_values.json", ["plotted_values", "source_rows"], "count", "Fig 5 evidence source rows"),
    ]
    for dp_id, src, segments, statistic, note in METRICS:
        data = _read(Path(src))
        value = _get(data, segments)
        datapoints.append({
            "dp_id": dp_id, "kind": "json-scalar",
            "value": value, "statistic": statistic, "device": "local-m4",
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": ".".join(segments),
            "key_segments": segments,
            "verbatim_excerpt": json.dumps({segments[-1]: value}),
            "note": note,
        })
    # Fig 6 succession chain length (json-len over the persisted chain list).
    fig6 = _read(Path("paper/figures/values/fig6_succession_values.json"))
    datapoints.append({
        "dp_id": "DP-0069", "kind": "json-len", "value": len(fig6["plotted_values"]["chain"]),
        "statistic": "count", "device": "local-m4",
        "authoritative_artifact": "paper/figures/values/fig6_succession_values.json",
        "superseded_by": [], "source_file": "paper/figures/values/fig6_succession_values.json",
        "key_path": "plotted_values.chain", "key_segments": ["plotted_values", "chain"],
        "extract": "len", "verbatim_excerpt": json.dumps({"chain_len": len(fig6["plotted_values"]["chain"])}),
        "note": "Fig 6 succession chain links (allocated, successor, restored)",
    })
    # Table 3 file-count totals (persisted as real scalars in the metrics file).
    for dp_id, segments, note in [
        ("DP-0077", ["shell_owned_files"], "shell-owned Python files (Table 3 total)"),
        ("DP-0078", ["total_python_files"], "total Python files (Table 3 total)"),
    ]:
        data = _read(Path("experiments/cp3/implementation_metrics.json"))
        value = _get(data, segments)
        datapoints.append({
            "dp_id": dp_id, "kind": "json-scalar", "value": value,
            "statistic": "count", "device": "local-m4",
            "authoritative_artifact": "experiments/cp3/implementation_metrics.json",
            "superseded_by": [], "source_file": "experiments/cp3/implementation_metrics.json",
            "key_path": ".".join(segments), "key_segments": segments,
            "verbatim_excerpt": json.dumps({segments[-1]: value}),
            "note": note,
        })
    # ---- v0.3: verbatim example strings quoted inline in the draft ----
    VERBATIM = [
        ("DP-0070", "experiments/cp3/e2_auditability/output/frozen/failure/action_record.json",
         "preconditions_failed:target_exists", "E2 typed failure reason (quoted in RQ2)"),
        ("DP-0071", "experiments/cp3/e2_auditability/output/frozen/reject/reject_intent.json",
         "intent recorded: reject (no execution)", "E2 reject-intent detail (quoted in RQ2)"),
        ("DP-0072", "experiments/cp3/e4_connection_governance/output/frozen/rejected_operation/rejected.json",
         "action_type_not_granted:connection.retire", "E4 rejected-operation reason (quoted in RQ4)"),
        ("DP-0073", "experiments/cp3/e4_connection_governance/output/frozen/no_implicit_retirement/broken.json",
         "missing_env:L6_SHELL_E4_BROKEN_KEY_ABSENT", "E4 typed broken-connection problem (quoted in RQ4)"),
        ("DP-0074", "experiments/cp3/e3_routing_cost/output/frozen/fake_answered_metered/decision_record.json",
         "simulated_local_fake", "E3 simulated-meter label (quoted in RQ3)"),
        ("DP-0075", "experiments/cp3/e6_realistic_demo/output/frozen/transcript_main.json",
         "The total Programme expenditure is \u00a314,111,919.19.", "E6 model response opening (quoted verbatim in RQ6)"),
        ("DP-0076", "experiments/cp3/e4_connection_governance/output/frozen/governance_chain/chain.json",
         "mdl_179372748462100001", "E4 real allocated mdl_* id (quoted in RQ4)"),
    ]
    for dp_id, src, needle, note in VERBATIM:
        text = (L6 / src).read_text()
        if needle not in text:
            sys.exit(f"FATAL: verbatim {needle!r} not in frozen artifact {src}")
        datapoints.append({
            "dp_id": dp_id, "kind": "text-match",
            "value": needle, "statistic": "n/a", "device": "local-m4",
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": None, "key_segments": [],
            "verbatim_excerpt": needle, "note": note,
        })
    for dp_id, src, needle, note in TEXT_MATCHES:
        text = (L6 / src).read_text()
        if needle not in text:
            sys.exit(f"FATAL: {needle} not in frozen artifact {src}")
        datapoints.append({
            "dp_id": dp_id, "kind": "text-match",
            "value": needle, "statistic": "n/a", "device": "local-m4",
            "authoritative_artifact": src, "superseded_by": [],
            "source_file": src, "key_path": None, "key_segments": [],
            "verbatim_excerpt": needle, "note": note,
        })
    registry = {
        "schema": "datapoints-v2",
        "generated": "2026-11-05",
        "paper": "paper/capstone_draft_v0.3.md",
        "root": "06-shell/",
        "count": len(datapoints),
        "datapoints": datapoints,
    }
    OUT.write_text(json.dumps(registry, indent=1, sort_keys=True) + "\n")
    print(f"built {len(datapoints)} datapoints -> {OUT.relative_to(L6)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
