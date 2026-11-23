"""L2 view validation, rendering and evidence calls (brief §5 boundary).

The shell never adds a dvr role/kind and never merges bindings locally. Every
rendered value must resolve through its binding; ``validate`` is the gate.
"""
from __future__ import annotations

from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

from dvr import affordance, edits, render, resolve, specval  # frozen dvr/1.1


def validate_view(view: dict, binding_ids: set[str]) -> None:
    """Raise ``specval`` errors if the view or a binding ref is not dvr/1.1-clean."""
    specval.validate_view(view, set(binding_ids))


def render_view(store_root: Path | str, view: dict) -> str:
    return render.render(Path(store_root), view)


def load_bindings(store_root: Path | str) -> dict[str, dict]:
    return resolve.load_bindings(Path(store_root))


def evidence_panel(store_root: Path | str, binding: dict) -> dict:
    return affordance.evidence_panel(Path(store_root), binding)


def evidence_for_action(store_root: Path | str, action_id: str) -> dict:
    return affordance.evidence_for_action(Path(store_root), action_id)


def make_edit_binding(store_root: Path | str, view_id: str, node: dict,
                       new_value) -> dict:
    return edits.make_edit_binding(Path(store_root), view_id, node, new_value)


def apply_edit(store_root: Path | str, edit_binding: dict) -> tuple[dict, int]:
    return edits.apply(Path(store_root), edit_binding)


def write_view_html(path, fragment, title="DeeWaanAI OS"):
    """Write a standalone, user-openable view as a FULL UTF-8 HTML document.

    The dvr renderer emits a clean-UTF-8 *fragment* (no doctype/head). Written bare to a
    .html file, browsers fall back to a legacy encoding and mangle non-ASCII characters
    (mojibake: 'Â£', 'â–¸'). Wrapping in a full document with an explicit charset fixes it.
    """
    doc = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
           "<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
           f"<title>{title}</title>\n</head>\n<body>\n{fragment}\n</body>\n</html>\n")
    Path(path).write_text(doc, encoding="utf-8")
    return Path(path)
