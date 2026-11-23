"""Interpreter pin + sys.path wiring for the shell prototype.

The shell consumes ONLY frozen contracts (INTERFACES.md). As of CP3 every
imported layer is a frozen snapshot under ``06-shell/``:

* ``qafiya_core``   — pre-flight vendor (L1 substrate, frozen v1.1 + v1.3 chain)
* ``dvr``           — pre-flight vendor (L2, frozen dvr/1.1)
* ``memory``        — pre-flight vendor (L4, frozen memory-binding v1.0)
* ``actionlayer``   — ``shell/vendor/03-action-layer/prototype/actionlayer``
  (L3, frozen action-record v0.1 + connection-actions v0.2)
* ``store`` / ``connection_ops`` / ``decide`` / ... —
  ``shell/vendor/05-model-router/router`` (L5, frozen model-routing v1.1)

The L3/L5 snapshot was cut at CP3 freeze time per the monitor's CP2 clearance
answer 1: a sha256 list proves *which* version ran, and a vendor snapshot lets a
reviewer *re-run* it even if the live source later changes. The per-file sha256
list lives at ``shell/vendor/SNAPSHOT_SHA256.json`` and is verified on every
import — drift raises ``SnapshotIntegrityError`` loudly rather than silently
running against a changed layer.

The shell never edits another layer's code and never writes into another
layer's frozen dataset. Per-journey L5 stores are scaffolded on a temp root
with the schemas copied read-only from L5's frozen datasets (same pattern the
L5 acceptance battery uses in ``router/test_connection_ops.py``).

Reproducibility note: L5's ``decide.py`` derives an HMAC key from
``$LOG_HMAC_KEY`` or a gitignored ``.secrets/log_hmac_key`` file under its
package root. Frozen experiment runners MUST set ``LOG_HMAC_KEY`` to a
deterministic value so the key is reproducible and no file is written into the
vendor snapshot.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MIN_PY = (3, 12)
PINNED_PY = "3.12"

HERE = Path(__file__).resolve().parent            # 06-shell/shell
L6 = HERE.parent                                   # 06-shell
OS_ROOT = L6.parent                                # DeewaanAI OS/
PREFLIGHT_VENDOR = L6 / "preflight" / "vendor"
SHELL_VENDOR = HERE / "vendor"

# Frozen layers already vendored by the pre-flight (never re-fetched).
QAFIYA_CORE = PREFLIGHT_VENDOR / "02-view-renderer" / "qafiya-ref" / "qafiya-core"
DVR = PREFLIGHT_VENDOR / "02-view-renderer" / "view-renderer"
L4_PROTO = PREFLIGHT_VENDOR / "04-memory" / "prototype"

# CP3 frozen vendor snapshot of L3 + L5 (cut from the live source trees).
L3_PROTO = SHELL_VENDOR / "03-action-layer" / "prototype"
L5_ROUTER = SHELL_VENDOR / "05-model-router" / "router"
L5_ROOT = SHELL_VENDOR / "05-model-router"
SNAPSHOT_MANIFEST = SHELL_VENDOR / "SNAPSHOT_SHA256.json"

# The vendor snapshot carries CODE only. L5's frozen DATASETS (schemas + the
# seeded policy/rules/capabilities rows the router needs at route time) stay in
# the live L5 tree and are READ ONLY — the shell never writes into them.
# Per-journey L5 stores are scaffolded on a temp/output root with the schemas
# copied from here (same pattern L5's own acceptance battery uses).
L5_FROZEN_DATASETS_ROOT = OS_ROOT / "05-model-router"


class SnapshotIntegrityError(RuntimeError):
    """Raised when the frozen L3/L5 vendor snapshot has drifted from its manifest."""


def _guard_interpreter() -> None:
    if sys.version_info < MIN_PY:
        raise SystemExit(
            "L6 shell requires Python "
            f"{PINNED_PY}+ (frozen pre-flight is pinned to CPython 3.12.8); "
            f"found {sys.version.split()[0]}. Run: python3.12 -m shell...."
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot() -> int:
    """Re-hash every file in the frozen L3/L5 snapshot against its manifest.

    Returns the number of files verified. Raises ``SnapshotIntegrityError`` on
    any missing file or hash mismatch — the shell refuses to run against a
    drifted layer rather than silently producing non-reproducible artifacts.
    """
    if not SNAPSHOT_MANIFEST.exists():
        raise SnapshotIntegrityError(
            f"snapshot manifest missing: {SNAPSHOT_MANIFEST}")
    manifest = json.loads(SNAPSHOT_MANIFEST.read_text())
    entries = manifest.get("files") or {}
    if not entries:
        raise SnapshotIntegrityError("snapshot manifest carries no file entries")
    missing: list[str] = []
    drifted: list[tuple[str, str, str]] = []
    for rel, expected in entries.items():
        p = SHELL_VENDOR / rel
        if not p.is_file():
            missing.append(rel)
            continue
        actual = _sha256(p)
        if actual != expected:
            drifted.append((rel, expected, actual))
    if missing or drifted:
        detail = []
        if missing:
            detail.append(f"missing={missing[:5]}{'…' if len(missing) > 5 else ''}")
        if drifted:
            detail.append(
                "drifted=" + ", ".join(f"{r}({e[:8]}!={a[:8]})" for r, e, a in drifted[:5])
                + ("…" if len(drifted) > 5 else ""))
        raise SnapshotIntegrityError(
            f"frozen L3/L5 vendor snapshot failed integrity check: {'; '.join(detail)}")
    return len(entries)


# Insert order matters: each ``sys.path.insert(0, ...)`` puts the newest entry
# at index 0, so the LAST path inserted ends up FIRST. We want the frozen
# pre-flight vendor paths (qafiya_core, dvr) to sit ahead of the L3/L5 snapshot,
# and we ALSO pre-import them below so that L3's ``dvr11.py`` — which does its
# own ``sys.path.insert(0, .../integration)`` on import — cannot shadow the
# frozen vendor packages by re-searching sys.path.
_PATHS_INSERT_ORDER: tuple[Path, ...] = (
    # Inserted first → ends up LAST on sys.path.
    L5_ROOT,      # so ``import router...`` works if a caller prefers packages
    L5_ROUTER,    # L5's own layout: modules import each other flat (``import connections``)
    L3_PROTO,
    L4_PROTO,
    DVR,
    QAFIYA_CORE,  # Inserted last → ends up at index 0.
)


def _preload_frozen_contracts() -> None:
    """Cache ``qafiya_core`` and ``dvr`` from the frozen pre-flight vendor.

    Without this, importing ``actionlayer`` first triggers
    ``actionlayer/dvr11.py``'s ``sys.path.insert(0, .../integration)``, which
    puts L3's internal dvr/1.0 shim ahead of the frozen L2 vendor. A later
    ``from dvr import ...`` then loads the shim, whose ``affordance.py`` asks
    ``qafiya_core`` for ``derivations``/``store`` modules that L5's minimal
    vendored ``qafiya_core`` does not carry — and the import fails.

    Pre-importing pins ``sys.modules['qafiya_core']`` and ``sys.modules['dvr']``
    to the frozen vendor copies. Submodule imports (``dvr.specval``,
    ``qafiya_core.chain``) resolve inside those cached packages, matching how
    the frozen pre-flight itself loads (``run_demo.py`` imports dvr before
    actionlayer for exactly this reason).
    """
    import qafiya_core  # noqa: F401  (frozen v1.1 + v1.3 chain)
    import qafiya_core.chain  # noqa: F401
    import qafiya_core.engine  # noqa: F401
    import dvr  # noqa: F401  (frozen dvr/1.1)
    import dvr.specval  # noqa: F401
    import dvr.render  # noqa: F401
    import dvr.resolve  # noqa: F401
    import dvr.edits  # noqa: F401
    import dvr.affordance  # noqa: F401


def setup() -> None:
    """Install the interpreter guard, verify the snapshot, wire sys.path, and
    pin the frozen packages. Idempotent: safe to call from every shell module.
    """
    _guard_interpreter()
    verify_snapshot()
    for p in _PATHS_INSERT_ORDER:
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    _preload_frozen_contracts()


setup()
