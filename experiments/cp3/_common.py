"""Shared helpers for the CP3 frozen experiments (E1–E5).

Every experiment follows the same Qafiya discipline (PROJECT.md §2):

* frozen inputs precede runs;
* an independent ``spine.py`` recomputes every headline number from raw
  artifacts and refuses to trust the run's own summary;
* if the spine fails, the claim is withdrawn;
* negative and uncatchable results are reported as results, never hidden.

This module centralises the mechanics so each experiment's ``run.py`` and
``spine.py`` stay short and auditable:

* deterministic environment pinning (``LOG_HMAC_KEY``) so L5's prompt HMAC is
  reproducible and nothing is written into the frozen vendor snapshot;
* per-experiment L5 store scaffolding (schemas + policy/rules/capabilities
  seeds copied READ-ONLY from L5's frozen datasets; ``models`` and
  ``decision_log`` start empty so the experiment never writes into a copy of
  the real decision history);
* manifest freezing + verification (sha256 over every frozen input + the run
  and spine scripts);
* small JSON/JSONL readers that tolerate a missing file (the frozen Qafiya
  corpus ships no ``history.jsonl`` for ``expenses``);
* a secret-scanner used by E4's hygiene claim.

Nothing here edits another layer's code or writes into another layer's frozen
dataset.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # 06-shell/experiments/cp3
EXPERIMENTS = HERE.parent                            # 06-shell/experiments
L6 = EXPERIMENTS.parent                              # 06-shell
if str(L6) not in sys.path:
    sys.path.insert(0, str(L6))

from shell import _bootstrap  # noqa: F401,E402

PREFLIGHT_INPUTS = L6 / "preflight" / "inputs"
FROZEN_L5_DATASETS = _bootstrap.L5_FROZEN_DATASETS_ROOT
FROZEN_QAFIYA_CORPUS = PREFLIGHT_INPUTS / "qafiya_corpus"

# Deterministic HMAC key so L5's decide.hmac_key() never writes a random key
# into the frozen vendor snapshot and the prompt HMAC is reproducible.
DETERMINISTIC_HMAC_KEY = "l6-shell-cp3-deterministic-hmac-key"

POLICY_LABEL = "v13"          # frozen L5 default: trust_user, allow_flagged
SECRET_ENV = "L6_SHELL_CP3_KEY"
SECRET_VALUE = "sk-L6-CP3-sentinel-MUST-NEVER-BE-RECORDED-2c8f4a"
FAKE_ENDPOINT = "http://127.0.0.1:9/v1"     # loopback, no listener, never called


def pin_environment() -> None:
    """Pin the deterministic environment every CP3 experiment relies on."""
    os.environ.setdefault("LOG_HMAC_KEY", DETERMINISTIC_HMAC_KEY)


# --------------------------------------------------------------------- io
def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                                 ensure_ascii=False, default=str) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_tree_for_secret(root: Path, needle: str) -> list[str]:
    leaks = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = Path(dirpath) / fn
            try:
                if needle in p.read_text(encoding="utf-8"):
                    leaks.append(str(p))
            except (UnicodeDecodeError, OSError):
                continue
    return leaks


# ------------------------------------------------- per-experiment L5 scaffold
def scaffold_l5_store(dst_root: Path, *, seed_datasets=("policy", "rules",
                                                          "capabilities")) -> Path:
    """Create a writable L5 store on ``dst_root``.

    Schemas are copied READ-ONLY from L5's frozen datasets. ``seed_datasets``
    also have their ``data.jsonl`` copied (the router needs an active policy +
    rules + capabilities to route). ``models`` and ``decision_log`` start EMPTY
    so the experiment never writes into a copy of the real decision history.
    Bindings/history/SUPERSEDED start empty for every dataset — the
    experiment's writes chain from genesis.

    The frozen L5 root is READ ONLY here. Nothing is written back.
    """
    from store import DATASETS as L5_DATASETS  # L5 (vendored snapshot)
    for name in L5_DATASETS:
        src = FROZEN_L5_DATASETS / "datasets" / name
        dst = dst_root / "datasets" / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / "schema.json", dst / "schema.json")
        if name in seed_datasets:
            shutil.copyfile(src / "data.jsonl", dst / "data.jsonl")
        else:
            (dst / "data.jsonl").write_text("")
        (dst / "history.jsonl").write_text("")
        (dst / "bindings.jsonl").write_text("")
        (dst / "SUPERSEDED.json").write_text("[]\n")
    return dst_root


def copy_qafiya_corpus(dst_root: Path) -> Path:
    """Copy the frozen Qafiya expense corpus before mutation (never in place)."""
    shutil.copytree(FROZEN_QAFIYA_CORPUS / "datasets", dst_root / "datasets")
    shutil.copy2(FROZEN_QAFIYA_CORPUS / "bindings.jsonl", dst_root / "bindings.jsonl")
    return dst_root


def load_frozen_view() -> dict:
    return json.loads((FROZEN_QAFIYA_CORPUS / "views" / "v_exp.view.json").read_text())


# ---------------------------------------------------------------- manifest
def freeze_manifest(experiment_root: Path, *, extra_files: list[Path] | None = None,
                      extra_metadata: dict | None = None,
                      artifact_label: str) -> dict:
    """Write ``MANIFEST.json`` over the experiment's frozen inputs + scripts.

    The manifest covers everything a reviewer needs to re-run the experiment:
    the ``inputs/`` tree, ``run.py``, ``spine.py``, and any extra files the
    caller names. Output artifacts are NOT frozen here unless the caller names
    them in ``extra_files`` (E6 freezes its model transcripts this way).

    ``extra_metadata`` is merged into the manifest top level — E6 uses it to
    carry the dataset source URL, access date, sha256, licence and the required
    OGL attribution line directly in ``MANIFEST.json``.
    """
    files: list[Path] = []
    inputs = experiment_root / "inputs"
    if inputs.exists():
        files.extend(p for p in inputs.rglob("*") if p.is_file())
    for name in ("run.py", "spine.py"):
        p = experiment_root / name
        if p.exists():
            files.append(p)
    files.extend(extra_files or [])
    entries = {str(p.relative_to(experiment_root)): sha256_file(p)
                 for p in sorted(set(files))}
    manifest = {
        "artifact": artifact_label,
        "algorithm": "sha256",
        "file_count": len(entries),
        "files": entries,
    }
    if extra_metadata:
        manifest.update(extra_metadata)
    (experiment_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_manifest(experiment_root: Path) -> int:
    """Re-hash every frozen file against ``MANIFEST.json``. Raises on drift."""
    manifest_path = experiment_root / "MANIFEST.json"
    if not manifest_path.exists():
        raise AssertionError(f"missing manifest: {manifest_path}")
    entries = json.loads(manifest_path.read_text())["files"]
    for rel, expected in entries.items():
        p = experiment_root / rel
        if not p.is_file():
            raise AssertionError(f"missing frozen artifact: {rel}")
        actual = sha256_file(p)
        if actual != expected:
            raise AssertionError(f"frozen artifact changed: {rel} "
                                    f"(expected {expected[:12]}, got {actual[:12]})")
    return len(entries)
