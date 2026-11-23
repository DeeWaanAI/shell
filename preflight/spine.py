#!/usr/bin/env python3
"""Re-run the L6 journey and recompute its claims from raw artifacts.

Usage:
  python preflight/spine.py           # verify frozen files, then rerun
  python preflight/spine.py --freeze  # rerun and write MANIFEST.json
"""
import sys

if sys.version_info < (3, 12):
    sys.exit(
        "L6 pre-flight requires Python 3.12+ (frozen under CPython 3.12.8); "
        f"found {sys.version.split()[0]}. Run: python3.12 preflight/spine.py"
    )

import hashlib
import json
from pathlib import Path

from run_demo import run, read_jsonl

P = Path(__file__).resolve().parent
MANIFEST = P / "MANIFEST.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_files():
    files = [P / "run_demo.py", P / "spine.py"]
    for root in (P / "inputs", P / "output/frozen"):
        files.extend(p for p in root.rglob("*") if p.is_file())
    return sorted(set(files))


def verify_manifest():
    if not MANIFEST.exists():
        return 0
    entries = json.loads(MANIFEST.read_text())["files"]
    for rel, expected in entries.items():
        path = P / rel
        assert path.is_file(), f"missing frozen artifact: {rel}"
        actual = digest(path)
        assert actual == expected, f"frozen artifact changed: {rel}"
    return len(entries)


def main():
    frozen_count = verify_manifest()
    out = P / "output/verification"
    summary = run(out)
    assert summary["status"] == "PASS"
    assert summary["checks_passed"] == 12
    assert summary["bound_records"] == 7
    assert summary["values"] == {
        "edited_record": "r_051", "edited_amount": 956.14,
        "q3_total_after": 10481.96, "evidence_rows": 21,
    }

    records = read_jsonl(out / "stores/qafiya/datasets/expenses/data.jsonl")
    q3_total = round(sum(r["amount"] for r in records if r["period"] == "Q3"), 2)
    assert q3_total == 10481.96, q3_total
    edited = next(r for r in records if r["id"] == "r_051")
    assert edited == {"id": "r_051", "date": "2026-08-09", "period": "Q3",
                      "amount": 956.14, "category": "food"}

    evidence = json.loads((out / "qafiya_evidence.json").read_text())
    assert len(evidence["source_rows"]) == 21
    assert evidence["focus"]["sides"]["Q3"]["value"] == 21.0
    memory_evidence = json.loads((out / "memory_evidence.json").read_text())
    assert memory_evidence["source_rows"][0]["id"] == summary["refs"]["memory"]
    action = json.loads((out / "action_record.json").read_text())
    assert action["outcome"]["status"] == "success"
    assert len(action["confirmations"]) == 1

    required_html = ["qafiya_before.html", "qafiya_after.html", "battery_confirmation.html",
                     "battery_audit.html", "action_confirmation.html", "action_audit.html",
                     "memory_inspection.html"]
    for name in required_html:
        text = (out / name).read_text()
        assert text and "UNRESOLVED" not in text, name
        assert '<meta charset="utf-8">' in text, f"{name}: missing charset meta"
    assert "▸evidence" in (out / "qafiya_before.html").read_text()
    assert "▸evidence" in (out / "memory_inspection.html").read_text()
    assert "data-choice=\"approve\"" in (out / "action_confirmation.html").read_text()
    assert len(read_jsonl(out / "journey.jsonl")) == 7

    result = {
        "status": "PASS",
        "python": sys.version.split()[0],
        "frozen_files_verified": frozen_count,
        "journey_checks_recomputed": summary["checks_passed"],
        "bound_records": summary["bound_records"],
        "q3_total_recomputed_from_raw": q3_total,
        "evidence_source_rows": len(evidence["source_rows"]),
        "memory_evidence_record": memory_evidence["source_rows"][0]["id"],
        "action_status": action["outcome"]["status"],
        "verification_output": "output/verification",
    }
    (P / "spine-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    if "--freeze" in sys.argv:
        entries = {str(p.relative_to(P)): digest(p) for p in artifact_files()}
        MANIFEST.write_text(json.dumps({
            "artifact": "L6 pre-flight cross-layer demo",
            "algorithm": "sha256",
            "files": entries,
        }, indent=2, sort_keys=True) + "\n")
        result["manifest_files"] = len(entries)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
