#!/usr/bin/env python3
"""Build the capstone HTML + PDF from the frozen markdown draft.

The PDF is produced with headless Chrome (the host has no pandoc/weasyprint/
pdflatex, and tectonic is offline so it cannot fetch packages). Chrome renders
UTF-8 and the SVG figures natively, so £, ▸ and — appear correctly.

    python3.12 paper/build_outputs.py            # -> capstone_v0.3.html + .pdf

Markdown parsing uses markdown-it-py (CommonMark + tables). Figures are embedded
as the SVG source of truth; the sibling figN.pdf files (built by
figures/svg_to_pdf via Chrome) are what the LaTeX uses.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent            # paper
L6 = HERE.parent
SRC = HERE / "capstone_draft_v0.3.md"
HTML_OUT = HERE / "capstone_v0.3.html"
# The PRIMARY paper PDF is capstone_v0.3.pdf, rendered by tectonic from the .tex
# (it matches what Overleaf produces). This Chrome/HTML build is an alternative
# view; it writes a distinct name so it never clobbers the LaTeX PDF.
PDF_OUT = HERE / "capstone_v0.3_html.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 20mm 18mm; }
html { -webkit-print-color-adjust: exact; }
body { font-family: "Times New Roman", Times, Georgia, serif; font-size: 11pt;
       line-height: 1.45; color: #111; max-width: 100%; }
h1 { font-size: 19pt; text-align: center; line-height: 1.25; margin: 0 0 6px; }
h2 { font-size: 14pt; margin: 18px 0 6px; border-bottom: 1px solid #bbb; padding-bottom: 2px; }
h3 { font-size: 12pt; margin: 12px 0 4px; }
p { margin: 6px 0; text-align: justify; }
strong { font-weight: 700; }
code { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
       font-size: 9.5pt; background: #f4f4f4; padding: 0 3px; border-radius: 3px; }
pre { background: #f6f6f6; border: 1px solid #ddd; border-radius: 4px;
      padding: 8px 10px; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 9pt; line-height: 1.3; }
blockquote { margin: 8px 0 8px 18px; padding: 4px 12px; border-left: 3px solid #999;
             color: #333; font-style: italic; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt;
        page-break-inside: avoid; }
th, td { border: 1px solid #999; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #ececec; font-weight: 700; }
img { max-width: 100%; height: auto; display: block; margin: 8px auto; }
hr { border: none; border-top: 1px solid #ccc; margin: 14px 0; }
a { color: #1a4b8c; text-decoration: none; }
.meta { text-align: center; font-size: 10pt; color: #333; }
"""


def build_html(md_text: str) -> str:
    md = MarkdownIt("commonmark").enable("table")
    body = md.render(md_text)
    # The leading H1 + the bold meta lines render fine; wrap the document.
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>The Agentic OS Shell: One Surface for Prompt, View, Action, and Audit (DeeWaanAI OS Layer 6)</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def main() -> int:
    if not SRC.exists():
        sys.exit(f"missing draft: {SRC}")
    md_text = SRC.read_text(encoding="utf-8")
    HTML_OUT.write_text(build_html(md_text), encoding="utf-8")
    print(f"wrote {HTML_OUT.relative_to(L6)} ({HTML_OUT.stat().st_size} bytes)")

    r = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={PDF_OUT}", HTML_OUT.as_uri()],
        capture_output=True, text=True, timeout=120)
    if not PDF_OUT.exists() or PDF_OUT.stat().st_size < 2000:
        sys.exit(f"PDF generation failed: {r.stderr[-300:]}")
    print(f"wrote {PDF_OUT.relative_to(L6)} ({PDF_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
