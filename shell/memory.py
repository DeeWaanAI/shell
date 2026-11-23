"""L4 memory binding calls (brief §5 boundary: no direct memory / history edits).

The shell only invokes L4's public binding: ``log_turn``, ``add_note``,
``inspect_view``, ``verify_chain`` and ``known_binding_ids``. Corrections and
deletions remain L4 protocols; the shell never rewrites memory JSON.
"""
from __future__ import annotations

from pathlib import Path

from . import _bootstrap  # noqa: F401  (sys.path + interpreter guard)

from memory import Store as MemoryStore, DATASETS as MEMORY_DATASETS  # frozen L4


class ShellMemory:
    """Shell-side view of L4's binding.

    ``root`` is a per-journey L4 store, scaffolded by ``MemoryStore(root)`` on
    first use. Nothing here mutates L4's frozen prototype datasets.
    """

    DATASETS = tuple(MEMORY_DATASETS)

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.store = MemoryStore(self.root)

    # ------------------------------------------------------------------ writes
    def log_turn(self, session_id: str, turn_index: int, role: str, content: str,
                 tokens_in: int, tokens_out: int, model_id: str) -> str:
        """Append a session turn through L4's binding. Returns the ``m_*`` id."""
        return self.store.log_turn(session_id, turn_index, role, content,
                                    tokens_in, tokens_out, model_id)

    def add_note(self, note: str, derived_from: list[str],
                 note_kind: str = "summary") -> str:
        return self.store.add_note(note, list(derived_from), note_kind=note_kind)

    # ------------------------------------------------------------------- reads
    def inspect_view(self) -> dict:
        return self.store.inspect_view()

    def known_binding_ids(self) -> set[str]:
        return self.store.known_binding_ids()

    def verify_all_chains(self) -> dict[str, bool]:
        """Verify every L4 dataset's chained history. Returns ``{ds: ok}``.

        L4's ``Store.verify_chain`` returns a plain bool (it discards the
        detail string from ``qafiya_core.chain.verify``), so this dict maps
        each dataset name to ``True``/``False`` — do NOT try to unpack it as
        a tuple.
        """
        return {ds: self.store.verify_chain(ds) for ds in self.DATASETS}
