#!/usr/bin/env python3
"""Layer-wide charset regression check (fix-html-charset-05-nov-2026-1822.md §After).

Asserts that EVERY standalone, user-openable ``.html`` file written by this layer
carries ``<meta charset="utf-8">`` in its head, so the mojibake defect cannot
silently return anywhere — including files whose own experiment spine does not
re-assert it (e.g. E1's reused journey output) and any file added later.

The per-experiment spines already assert the charset on the views they render;
this is the belt-and-braces layer-wide gate. It walks ``06-shell/`` and skips the
vendored layer trees (``*/vendor/*``), which are frozen other-layer code and may
legitimately contain embeddable fragments or test fixtures.

It also confirms each file actually decodes as valid UTF-8. (The original defect
was not corrupted bytes — the renderer always emitted correct UTF-8 — but a
missing charset meta, which made browsers guess windows-1252 and display the
correct bytes as mojibake. So the two robust checks are: the charset meta is
present, and the file is valid UTF-8.)

Run from 06-shell/:
    python3.12 experiments/cp3/check_html_charset.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # experiments/cp3
L6 = HERE.parent.parent                              # 06-shell

CHARSET_META = '<meta charset="utf-8">'


def _is_vendored(p: Path) -> bool:
    # Vendored layers and compiler-generated build output are not L6 user views.
    return any(part in {"vendor", "target"} for part in p.parts)


def main() -> int:
    html_files = sorted(p for p in L6.rglob("*.html") if not _is_vendored(p))
    if not html_files:
        print("no standalone .html files found — nothing to check")
        return 0
    missing_charset: list[str] = []
    not_utf8: list[str] = []
    for p in html_files:
        raw = p.read_bytes()
        rel = str(p.relative_to(L6))
        # The charset meta must appear in the head (first 400 bytes).
        if CHARSET_META.encode("utf-8") not in raw[:400]:
            missing_charset.append(rel)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            not_utf8.append(rel)

    ok = not (missing_charset or not_utf8)
    print(f"checked {len(html_files)} standalone .html files under 06-shell/ (vendor excluded)")
    if missing_charset:
        print(f"FAIL: {len(missing_charset)} file(s) missing {CHARSET_META!r}:")
        for f in missing_charset[:20]:
            print(f"  - {f}")
    if not_utf8:
        print(f"FAIL: {len(not_utf8)} file(s) are not valid UTF-8:")
        for f in not_utf8[:20]:
            print(f"  - {f}")
    if ok:
        print(f"OK: all {len(html_files)} standalone views carry the charset meta "
                f"and decode as valid UTF-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
