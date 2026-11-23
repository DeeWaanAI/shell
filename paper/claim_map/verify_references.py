#!/usr/bin/env python3
"""Verify every capstone reference resolves, and record the evidence.

Citation integrity is a hard requirement: a fabricated reference is a fatal
defect. This script checks each candidate reference against a real database —
the arXiv API for arXiv ids, Crossref for DOIs and title lookups, and an HTTP
HEAD/GET for specification/web references — and writes the resolved record
(id, title, year, access date, method, status) to references-verified.json.

It NEVER invents an identifier: for arXiv/DOI entries it queries the exact id;
for title-only entries it queries Crossref ``query.bibliographic`` and records
what actually resolves (or marks UNRESOLVED). The arXiv API may 429, so it
retries with backoff.

Run from 06-shell/:
    python3.12 paper/claim_map/verify_references.py
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

# Python's urllib on this host does not use the macOS system trust store, so the
# default context raises CERTIFICATE_VERIFY_FAILED. Build a context from the
# certifi bundle — TLS is still fully validated (no insecure workaround).
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

HERE = Path(__file__).resolve().parent
OUT = HERE / "references-verified.json"
ACCESS_DATE = time.strftime("%Y-%m-%d", time.gmtime())
UA = "DeeWaanAI-OS-capstone/0.3 (reference verification; mailto:research@deewaanai.example)"


def _get(url: str, *, tries: int = 4, timeout: int = 30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 503):
                time.sleep(2.0 * (i + 1))
                continue
            return e.code, ""
        except Exception as e:                          # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (i + 1))
    return None, last or "unreachable"


def check_arxiv(arxiv_id: str) -> dict:
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    status, body = _get(url)
    rec = {"method": "arxiv-api", "queried": arxiv_id, "access_date": ACCESS_DATE}
    if status != 200 or "<entry>" not in body:
        rec["status"] = "UNRESOLVED"
        rec["detail"] = body if isinstance(body, str) else str(body)
        return rec
    # Parse the Atom entry minimally (no external deps).
    import re
    title = re.search(r"<entry>.*?<title>(.*?)</title>", body, re.S)
    published = re.search(r"<published>(\d{4})", body)
    aid = re.search(r"<id>http://arxiv.org/abs/([^<]+)</id>", body)
    authors = re.findall(r"<name>([^<]+)</name>", body)
    rec.update({
        "status": "verified",
        "resolved_id": f"arXiv:{aid.group(1)}" if aid else f"arXiv:{arxiv_id}",
        "title": (title.group(1).strip().replace("\n", " ") if title else None),
        "year": int(published.group(1)) if published else None,
        "authors": authors[:6],
    })
    return rec


def check_doi(doi: str) -> dict:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    status, body = _get(url)
    rec = {"method": "crossref-doi", "queried": doi, "access_date": ACCESS_DATE}
    if status != 200 or not body:
        rec["status"] = "UNRESOLVED"
        rec["detail"] = body if isinstance(body, str) else str(body)
        return rec
    try:
        msg = json.loads(body)["message"]
    except Exception:                                   # noqa: BLE001
        rec["status"] = "UNRESOLVED"
        return rec
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        dp = (msg.get(key) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            year = dp[0][0]
            break
    rec.update({
        "status": "verified",
        "resolved_id": f"doi:{msg.get('DOI', doi)}",
        "title": (msg.get("title") or [None])[0],
        "year": year,
        "authors": [f"{a.get('family','')}, {a.get('given','')}".strip(", ")
                      for a in (msg.get("author") or [])][:6],
        "container": (msg.get("container-title") or [None])[0],
    })
    return rec


def check_crossref_title(query: str) -> dict:
    q = urllib.parse.urlencode({"query.bibliographic": query, "rows": 3,
                                   "mailto": "research@deewaanai.example"})
    url = f"https://api.crossref.org/works?{q}"
    status, body = _get(url)
    rec = {"method": "crossref-title", "queried": query, "access_date": ACCESS_DATE}
    if status != 200 or not body:
        rec["status"] = "UNRESOLVED"
        rec["detail"] = body if isinstance(body, str) else str(body)
        return rec
    try:
        items = json.loads(body)["message"]["items"]
    except Exception:                                   # noqa: BLE001
        rec["status"] = "UNRESOLVED"
        return rec
    if not items:
        rec["status"] = "UNRESOLVED"
        return rec
    msg = items[0]
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        dp = (msg.get(key) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            year = dp[0][0]
            break
    rec.update({
        "status": "verified",
        "resolved_id": f"doi:{msg.get('DOI')}",
        "title": (msg.get("title") or [None])[0],
        "year": year,
        "authors": [f"{a.get('family','')}, {a.get('given','')}".strip(", ")
                      for a in (msg.get("author") or [])][:6],
        "container": (msg.get("container-title") or [None])[0],
        "candidates": [(it.get("DOI"), (it.get("title") or [None])[0], it.get("score"))
                          for it in items],
    })
    return rec


def check_url(url: str) -> dict:
    status, _ = _get(url, tries=2, timeout=20)
    return {"method": "http", "queried": url, "access_date": ACCESS_DATE,
              "status": "verified" if status == 200 else "UNRESOLVED",
              "http_status": status, "resolved_id": url}


# ------------------------------------------------------------------ the list
# Corrected after re-verification: arXiv:2604.09874 resolves to a DIFFERENT
# paper ("Simulating Organized Group Behavior"), so the Peng et al. citation uses
# its real id 2604.09876; arXiv:2004.04530 resolves to an astronomy paper, so
# DataHub uses its real id 1409.0798. Model Cards / Datasheets are cited by their
# published DOIs (not the arXiv preprints). The "W7 provenance model" reference
# is DROPPED: no clean verifiable record resolved for it, and citation integrity
# forbids keeping an unverifiable reference.
ARXIV = [
    ("2410.11843", "From Commands to Prompts: LLM-based Semantic File System for AIOS"),
    ("2403.16971", "AIOS: LLM Agent Operating System"),
    ("2508.19227", "Generative Interfaces for Language Models"),
    ("2604.09876", "Efficient Personalization of Generative User Interfaces"),
    ("2608.04293", "LEGOUI: Designing with UI-DSL Bricks"),
    ("2603.21334", "Software as Content"),
    ("1803.05355", "FEVER: a large-scale dataset for Fact Extraction and VERification"),
    ("2202.03629", "Survey of Hallucination in Natural Language Generation"),
    ("1409.0798", "DataHub: Collaborative Data Science & Dataset Version Management at Scale"),
]
DOIS = [
    ("10.1145/3715668.3736365", "Lee — Towards a Working Definition of Designing Generative UI"),
    ("10.1007/3-540-44503-X_20", "Buneman et al. — Why and Where (ICDT 2001)"),
    ("10.1145/365230.365252", "Dennis & Van Horn — Programming semantics (capability security)"),
    ("10.1145/3287560.3287596", "Mitchell et al. — Model Cards (FAT* 2019)"),
    ("10.1145/3458723", "Gebru et al. — Datasheets for Datasets (CACM 2021)"),
    ("10.1145/38714.38742", "Garcia-Molina & Salem — Sagas (1987)"),
    ("10.1093/bioinformatics/bth361", "Oinn et al. — Taverna (2004)"),
    ("10.1109/escience.2012.6404482", "Why workflows break — retrospective provenance (2012)"),
]
TITLE_QUERIES: list[str] = []
URLS = [
    ("https://www.w3.org/TR/prov-o/", "W3C PROV-O Recommendation"),
    ("https://c2pa.org/", "C2PA content authenticity specification"),
    ("https://openlineage.io/", "OpenLineage specification"),
    ("https://www.commonwl.org/", "Common Workflow Language specification"),
    ("https://github.com/amundsen-io/amundsen", "Amundsen data catalog"),
]


def main() -> int:
    results = {"access_date": ACCESS_DATE, "verified": [], "unresolved": []}

    def record(key: str, label: str, rec: dict):
        rec = {"key": key, "label": label, **rec}
        (results["verified"] if rec["status"] == "verified"
            else results["unresolved"]).append(rec)
        mark = "OK " if rec["status"] == "verified" else "!! "
        print(f"{mark}{key:14s} {rec['status']:10s} "
                f"{(rec.get('title') or rec.get('detail') or '')[:70]}")

    for aid, label in ARXIV:
        record(f"arXiv:{aid}", label, check_arxiv(aid))
        time.sleep(1.0)                       # be polite to the arXiv API
    for doi, label in DOIS:
        record(f"doi:{doi}", label, check_doi(doi))
        time.sleep(0.5)
    for q in TITLE_QUERIES:
        record("title:" + q[:24], q, check_crossref_title(q))
        time.sleep(0.5)
    for url, label in URLS:
        record(url, label, check_url(url))
        time.sleep(0.3)

    results["summary"] = {
        "total": len(results["verified"]) + len(results["unresolved"]),
        "verified": len(results["verified"]),
        "unresolved": len(results["unresolved"]),
        "unresolved_keys": [r["key"] for r in results["unresolved"]],
    }
    OUT.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print(f"\nwrote {OUT.relative_to(HERE.parent.parent)} — "
            f"{results['summary']['verified']} verified, "
            f"{results['summary']['unresolved']} unresolved")
    if results["unresolved"]:
        print("UNRESOLVED (must be removed or replaced in the draft):")
        for r in results["unresolved"]:
            print(f"  - {r['key']}: {r['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
