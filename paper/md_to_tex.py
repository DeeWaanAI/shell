#!/usr/bin/env python3
"""Convert the frozen markdown draft to an Overleaf-ready LaTeX source.

The host has no working local LaTeX (tectonic is offline and cannot fetch
packages; the `svg` package would need inkscape, which is absent), so this
produces a .tex the owner compiles in Overleaf. Design choices for a clean
Overleaf build:

* pdfLaTeX-safe: ``inputenc``/``fontenc``/``textcomp``/``amssymb``, and every
  non-ASCII glyph in the draft is mapped to a LaTeX command (\\pounds,
  $\\rightarrow$, $\\triangleright$, ---, \\S, \\checkmark, $\\geq$, ...) so no
  exotic font is required.
* Figures use ``\\includegraphics{figures/figN.pdf}`` — the PDF siblings built
  from the SVG source of truth by headless Chrome — so no inkscape/shell-escape
  is needed on Overleaf.
* Tables use ``tabularx``; code blocks use ``fancyvrb`` Verbatim (the JSON
  examples are ASCII); blockquotes use the ``quote`` environment.
* Citations are kept as literal [n] tokens (matching the draft) rather than
  \\cite keys, so the file compiles standalone; the owner can convert to
  \\bibitem in Overleaf.

    python3.12 paper/md_to_tex.py     # -> capstone_v0.3.tex
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "capstone_draft_v0.3.md"
OUT = HERE / "capstone_v0.3.tex"

# Unicode glyph -> LaTeX. Applied AFTER escaping ASCII specials, so the commands
# (and any math $...$) are introduced literally and are not re-escaped.
UNICODE_MAP = [
    ("£", r"\pounds{}"),
    ("→", r"$\rightarrow$"),
    ("▸", r"$\triangleright$"),
    ("—", "---"),
    ("–", "--"),
    ("−", "$-$"),                 # U+2212 minus
    ("§", r"\S{}"),
    ("✓", r"\checkmark{}"),
    ("·", r"$\cdot$"),
    ("≥", r"$\geq$"),
    ("≤", r"$\leq$"),
    ("×", r"$\times$"),
    ("…", r"\ldots{}"),
    ("“", "``"), ("”", "''"),
    ("‘", "`"), ("’", "'"),
    ("€", r"\euro{}"),
]

PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{textcomp}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{longtable}
\usepackage{fvextra}
\usepackage{xcolor}
\usepackage[margin=2.4cm]{geometry}
\usepackage[hidelinks]{hyperref}
\usepackage{url}
\DefineVerbatimEnvironment{codeblock}{Verbatim}{fontsize=\small,breaklines=true,frame=single,framesep=6pt,rulecolor=\color{black!40}}
\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}

\title{\bfseries The Agentic OS Shell: One Surface for Prompt, View, Action, and Audit\\(DeeWaanAI OS Layer 6)}
\author{Youssef Hariri\\DeeWaanAI\\\texttt{github.com/DeeWaanAI}}
\date{November 2026}

\begin{document}
\maketitle
"""

POSTAMBLE = r"""
\end{document}
"""


def escape_specials(s: str) -> str:
    r"""Escape LaTeX ASCII specials. URLs are protected first and restored as
    \url{...} so their underscores/percent signs are not mangled."""
    urls: list[str] = []

    def _stash(m):
        urls.append(m.group(0))
        return f"\x00URL{len(urls)-1}\x00"

    s = re.sub(r"https?://[^\s\)\]>]+", _stash, s)
    s = (s.replace("\\", r"\textbackslash{}")
            .replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")
            .replace("_", r"\_").replace("{", r"\{").replace("}", r"\}")
            .replace("$", r"\$").replace("~", r"\textasciitilde{}")
            .replace("^", r"\textasciicircum{}"))
    for i, u in enumerate(urls):
        u_esc = u.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#") \
                  .replace("_", r"\_")
        s = s.replace(f"\x00URL{i}\x00", r"\url{" + u_esc + "}")
    return s


def apply_unicode(s: str) -> str:
    for ch, repl in UNICODE_MAP:
        s = s.replace(ch, repl)
    return s


def inline(s: str) -> str:
    """Full inline transform: escape specials, map unicode, then bold / code."""
    s = escape_specials(s)
    s = apply_unicode(s)
    # inline code `x`  (backticks were not escaped)
    s = re.sub(r"`([^`]+?)`", lambda m: r"\texttt{" + m.group(1) + "}", s)
    # bold **x**
    s = re.sub(r"\*\*([^*]+?)\*\*", lambda m: r"\textbf{" + m.group(1) + "}", s)
    return s


def convert_table(rows: list[str]) -> str:
    cells = []
    for r in rows:
        r = r.strip()
        if re.match(r"^\|?[\s:|-]+\|?$", r):     # the |---|---| separator
            continue
        r = r.strip("|")
        cells.append([c.strip() for c in r.split("|")])
    if not cells:
        return ""
    ncol = max(len(c) for c in cells)
    header, *body = cells
    header += [""] * (ncol - len(header))
    colspec = "@{}>{\\raggedright\\arraybackslash}p{0.30\\linewidth}" + \
                "".join(["X"] * (ncol - 1)) + "@{}"
    out = [r"\begin{table}[htbp]\centering\small",
              r"\begin{tabularx}{\linewidth}{" + colspec + "}",
              r"\toprule"]
    out.append(" & ".join(inline(c) for c in header) + r" \\")
    out.append(r"\midrule")
    for b in body:
        b += [""] * (ncol - len(b))
        out.append(" & ".join(inline(c) for c in b) + r" \\")
    out += [r"\bottomrule", r"\end{tabularx}", r"\end{table}"]
    return "\n".join(out)


def main() -> int:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # fenced code block
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1                                       # skip closing fence
            # Verbatim is literal; the draft's code blocks are ASCII (the
            # £-bearing model response is a blockquote, not a code block), so
            # emit the raw lines with no escaping or unicode mapping.
            content = "\n".join(buf)
            out.append(r"\begin{codeblock}")
            out.append(content)
            out.append(r"\end{codeblock}")
            continue

        # table block
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|?[\s:|-]+\|", lines[i+1].strip()):
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(convert_table(tbl))
            continue

        # image (+ the following bold caption paragraph) -> figure env
        m = re.match(r"^!\[[^\]]*\]\(([^)]+)\)\s*$", stripped)
        if m:
            src = m.group(1)
            pdf = re.sub(r"\.svg$", ".pdf", src)
            i += 1
            caption = ""
            # look ahead for the caption paragraph
            j = i
            while j < n and lines[j].strip() == "":
                j += 1
            if j < n and lines[j].strip().startswith("**Figure"):
                caption = lines[j].strip()
                i = j + 1
            out.append(r"\begin{figure}[htbp]\centering")
            out.append(r"\includegraphics[width=0.92\linewidth]{" + pdf + "}")
            if caption:
                out.append(r"\caption{" + inline(caption) + "}")
            out.append(r"\end{figure}")
            continue

        # blockquote
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(r"\begin{quote}")
            out.append(inline(" ".join(b for b in buf if b)))
            out.append(r"\end{quote}")
            continue

        # headers
        if stripped.startswith("### "):
            out.append(r"\subsection*{" + inline(stripped[4:]) + "}")
            i += 1
            continue
        if stripped.startswith("## "):
            out.append(r"\section*{" + inline(stripped[3:]) + "}")
            i += 1
            continue
        if stripped.startswith("# "):
            # top-level title is already in \title; skip the duplicate H1
            i += 1
            continue

        # horizontal rule
        if stripped in ("---", "***", "___"):
            out.append(r"\vspace{4pt}\noindent\rule{\linewidth}{0.4pt}\vspace{4pt}")
            i += 1
            continue

        # blank
        if stripped == "":
            i += 1
            continue

        # paragraph (gather consecutive non-blank, non-special lines)
        buf = [stripped]
        i += 1
        while i < n:
            nx = lines[i].strip()
            if (nx == "" or nx.startswith("#") or nx.startswith("```")
                    or nx.startswith(">") or nx.startswith("|")
                    or re.match(r"^!\[[^\]]*\]\(", nx) or nx in ("---", "***", "___")):
                break
            buf.append(nx)
            i += 1
        para = " ".join(buf)
        # The author meta line lives in \author (preamble); do not duplicate it.
        if para.startswith("**Author:**"):
            out.append("")
            continue
        out.append(inline(para))
        out.append("")

    OUT.write_text(PREAMBLE + "\n".join(out) + "\n" + POSTAMBLE, encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent)} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
