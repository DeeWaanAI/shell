#!/usr/bin/env python3
"""E2 independent spine — recompute every variant's typed visible state from raw.

Refuses to trust ``output/frozen/variants.json`` or any run summary. Each
variant's claim is recomputed from its raw artifacts (L3 action records, file
hashes, audit replay, rendered HTML) and cross-checked against the frozen
``inputs/spec.json``. If this script fails, the E2 claim is withdrawn.

Run under Python 3.12:

    python3.12 experiments/cp3/e2_auditability/spine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CP3 = HERE.parent
EXPERIMENTS = CP3.parent
L6 = EXPERIMENTS.parent
for p in (str(L6), str(EXPERIMENTS), str(CP3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(f"[E2 spine] {msg}")


def _replay_ok(out: Path, variant: str) -> dict:
    """Recompute replay success + missing-ref count + chain verification for one
    variant from its raw audit store."""
    audit_dir = out / variant / "stores" / "shell_audit" / "datasets" / "shell_audit"
    ok, detail = qafiya_chain.verify(audit_dir / "history.jsonl")
    if not ok:
        _fail(f"{variant}: shell_audit chain broken: {detail}")
    events = _common.read_jsonl(audit_dir / "data.jsonl")
    # One session per variant store.
    sessions = {e["session_id"] for e in events}
    if len(sessions) != 1:
        _fail(f"{variant}: expected exactly one session, got {sorted(sessions)}")
    session_id = next(iter(sessions))
    seqs = sorted(e["sequence"] for e in events)
    if seqs != list(range(1, len(seqs) + 1)):
        _fail(f"{variant}: non-monotonic sequence {seqs}")
    ids = {e["id"] for e in events}
    missing = [ref for e in events for ref in e.get("input_event_refs", [])
                 if ref not in ids]
    if missing:
        _fail(f"{variant}: unresolved input_event_refs {missing}")
    return {"variant": variant, "session_id": session_id,
              "events": len(events), "sequences_complete": True,
              "missing_ref_count": 0, "chain_ok": True}


def main() -> int:
    _common.pin_environment()
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    out = HERE / "output" / "frozen"
    if not out.exists():
        _fail(f"no E2 output at {out}; run run.py first")
    frozen_count = _common.verify_manifest(HERE)

    replays = {r["variant"]: r for r in
                 [_replay_ok(out, v) for v in
                    ("approve", "reject", "refuse", "failure", "unresolved")]}

    # ---- approve: file written, content exact, EXECUTED event present --------
    ap = out / "approve"
    ap_file = _common.read_json(ap / "file_sha.json")
    if not ap_file["exists"] or ap_file["content"] != "approved\n":
        _fail(f"approve: file not written correctly: {ap_file}")
    ap_rec = _common.read_json(ap / "action_record.json")
    if ap_rec["outcome"]["status"] != "success":
        _fail(f"approve: outcome {ap_rec['outcome']}")
    ap_states = [e["state"] for e in _common.read_jsonl(
        ap / "stores" / "shell_audit" / "datasets" / "shell_audit" / "data.jsonl")]
    if "EXECUTED" not in ap_states:
        _fail("approve: no EXECUTED audit event")

    # ---- reject: intent recorded, file byte-identical, NO execution ----------
    rj = out / "reject"
    rj_intent = _common.read_json(rj / "reject_intent.json")
    if rj_intent.get("ok") is not True:
        _fail(f"reject: intent not recorded: {rj_intent}")
    rj_unchanged = _common.read_json(rj / "file_unchanged.json")
    if not rj_unchanged["unchanged"]:
        _fail("reject: the reject intent mutated the approved file")
    rj_states = [e["state"] for e in _common.read_jsonl(
        rj / "stores" / "shell_audit" / "datasets" / "shell_audit" / "data.jsonl")]
    if "EXECUTED" in rj_states:
        _fail("reject: an EXECUTED event was written despite the reject intent")

    # ---- refuse: typed refusal, no file written ------------------------------
    rf = out / "refuse"
    rf_rec = _common.read_json(rf / "action_record.json")
    if rf_rec["outcome"]["status"] != "refused":
        _fail(f"refuse: outcome {rf_rec['outcome']}")
    if not rf_rec["outcome"].get("reason"):
        _fail("refuse: no typed refusal reason")
    rf_absent = _common.read_json(rf / "file_absent.json")
    if rf_absent["exists"]:
        _fail("refuse: the refused action still wrote a file")

    # ---- failure: typed preconditions_failed ---------------------------------
    fl = out / "failure"
    fl_rec = _common.read_json(fl / "action_record.json")
    if fl_rec["outcome"]["status"] != "refused":
        _fail(f"failure: outcome {fl_rec['outcome']}")
    if "preconditions_failed" not in (fl_rec["outcome"].get("reason") or ""):
        _fail(f"failure: reason not typed preconditions_failed: {fl_rec['outcome'].get('reason')}")

    # ---- unresolved: UNRESOLVED visible in the rendered HTML -----------------
    ur = out / "unresolved"
    html = (ur / "view.html").read_text()
    assert '<meta charset="utf-8">' in html, "e2_view: missing charset meta"
    if "UNRESOLVED" not in html:
        _fail("unresolved: rendered HTML does not paint UNRESOLVED")
    ur_check = _common.read_json(ur / "render_check.json")
    if not ur_check["view_is_dvr11_clean"]:
        _fail("unresolved: the fixture view is not dvr/1.1-clean")

    result = {
        "experiment": "E2",
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "variants": sorted(replays.keys()),
        "replays": replays,
        "missing_ref_count_total": sum(r["missing_ref_count"] for r in replays.values()),
        "all_chains_verify": all(r["chain_ok"] for r in replays.values()),
        "typed_visible_states": {
            "approve": "success + EXECUTED event + file written",
            "reject": "intent recorded + file unchanged + no EXECUTED event",
            "refuse": "refused with typed reason + no file written",
            "failure": "refused with preconditions_failed",
            "unresolved": "UNRESOLVED painted in dvr/1.1-clean render",
        },
    }
    _common.write_json(HERE / "output" / "spine-result.json", result)
    import json
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
