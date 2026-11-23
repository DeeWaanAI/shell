#!/usr/bin/env python3
"""E5 — shell limits (brief §7.2 E5; brief §8 honesty boundaries).

Reports the shell's provable limits as RESULTS, measured where a machine-checkable
proxy exists and stated plainly where none does. Negative and uncatchable results
are never hidden (PROJECT.md §2).

Three probe families:

1. **Expressibility ceiling** — the 6 original screen classes; 5 are expressible
   under dvr/1.1. The ceiling is ENFORCED, not merely documented: a probe asks
   ``dvr.specval.validate_view`` to accept an invented ``service_control`` role
   and confirms it raises ``SpecError``.
2. **Tamper / absence** — a naive tamper of a frozen chained artifact is
   detected by ``qafiya_core.chain.verify`` and by the manifest hash; a missing
   L5 dataset produces a typed ``StoreError`` rather than a silent pass.
3. **Uncatchable classes** — each limit from brief §8 is recorded; the
   ``trust_user`` proxy is demonstrated from a raw L5 decision record
   (``classifier_mode='trust_user'`` and ``privacy_class='public'`` by
   construction, not by computation).

Run under Python 3.12:

    python3.12 experiments/cp3/e5_shell_limits/run.py [--freeze]
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
from shell.audit import ShellAuditStore  # noqa: E402
from shell.connections import ShellConnections  # noqa: E402
from shell.kernel import Kernel, KernelContext, KernelState  # noqa: E402
from shell.routing import ShellRouter  # noqa: E402
from shell.session import new_session  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

from dvr import specval  # noqa: E402
from health import Health  # noqa: E402
from qafiya_core import chain as qafiya_chain  # noqa: E402
from store import Store as L5Store, StoreError  # noqa: E402 (vendored snapshot)

FAKE_CONFIG = {
    "label": "E5 fake local model", "connector": "openai_compatible",
    "base_url": _common.FAKE_ENDPOINT, "model": "e5-fake-model",
    "locus": "local", "privacy_class": "private",
    "prices": {"input": 0.0, "output": 0.0}, "key_env": _common.SECRET_ENV,
}


# ---------------------------------------------------- 1. expressibility ceiling
def probe_expressibility(out: Path) -> dict:
    """Confirm dvr/1.1 ENFORCES the ceiling: an invented service-control role is
    rejected by specval, so the connection-manager gap is real, not assumed."""
    invented_view = {
        "spec": "dvr/1.1", "id": "v_invented", "kind": "table",
        "title": {"text": "invented service-control screen"},
        "columns": [{"id": "col:status", "label": "Status", "source_field": "status"}],
        "nodes": [{"id": "svc:refresh", "role": "service_control",
                     "column": "col:status"}],
    }
    raised: str | None = None
    try:
        specval.validate_view(invented_view, set())
    except specval.SpecError as exc:
        raised = str(exc)
    _common.write_json(out / "expressibility_probe.json", {
        "invented_role": "service_control",
        "specval_rejected": raised is not None,
        "specval_error": raised,
    })
    return {"probe": "expressibility_ceiling",
              "specval_rejected_invented_role": raised is not None,
              "error": raised}


# --------------------------------------------------------- 2. tamper / absence
def probe_tamper(out: Path) -> dict:
    """A naive tamper of a chained artifact is detected by chain.verify and by
    the manifest hash. (An attacker who recomputes the WHOLE chain would verify
    — that uncatchable class is reported in probe 3, not hidden here.)"""
    # Build a small chained store, verify clean, tamper one record, re-verify.
    store_root = out / "tamper_store"
    audit = ShellAuditStore(store_root)
    session = new_session(user_id="e5-tamper")
    kernel = Kernel(session.id, audit, KernelContext())
    kernel.enter(KernelState.RECEIVED, notes="E5 tamper probe: clean event")
    kernel.enter(KernelState.ROUTED, notes="E5 tamper probe: clean event 2")
    clean_ok, clean_detail = audit.verify_chain()

    hist = store_root / "datasets" / "shell_audit" / "datasets"
    hist_path = store_root / "datasets" / "shell_audit" / "history.jsonl"
    rows = hist_path.read_text().splitlines()
    # Naive tamper: flip a character in the first entry WITHOUT recomputing hashes.
    tampered = list(rows)
    tampered[0] = tampered[0].replace("RECEIVED", "ROUTED", 1)
    hist_path.write_text("\n".join(tampered) + "\n")
    tamper_ok, tamper_detail = qafiya_chain.verify(hist_path)

    # Manifest detection: freeze a manifest over a clean file, change it, verify.
    man_root = out / "manifest_probe"
    man_root.mkdir(parents=True, exist_ok=True)
    (man_root / "inputs").mkdir(exist_ok=True)
    frozen_file = man_root / "inputs" / "frozen.txt"
    frozen_file.write_text("original frozen content\n")
    (man_root / "run.py").write_text("# placeholder run\n")
    (man_root / "spine.py").write_text("# placeholder spine\n")
    _common.freeze_manifest(man_root, artifact_label="E5 manifest tamper probe")
    clean_manifest_count = _common.verify_manifest(man_root)
    frozen_file.write_text("TAMPERED content\n")
    manifest_detected = False
    try:
        _common.verify_manifest(man_root)
    except AssertionError:
        manifest_detected = True

    _common.write_json(out / "tamper_probe.json", {
        "chain_clean_before": clean_ok,
        "chain_clean_detail": clean_detail,
        "chain_detected_naive_tamper": not tamper_ok,
        "chain_tamper_detail": tamper_detail,
        "manifest_clean_count": clean_manifest_count,
        "manifest_detected_tamper": manifest_detected,
    })
    return {"probe": "tamper_and_absence",
              "chain_clean_before": clean_ok,
              "chain_detected_naive_tamper": not tamper_ok,
              "manifest_detected_tamper": manifest_detected}


def probe_absence(out: Path) -> dict:
    """A missing L5 dataset produces a typed StoreError, not a silent pass."""
    absent_root = out / "absent_store"
    absent_root.mkdir(parents=True, exist_ok=True)
    # Scaffold only SOME datasets, so Store() must raise on the missing one.
    (absent_root / "datasets" / "models").mkdir(parents=True, exist_ok=True)
    raised: str | None = None
    raised_type: str | None = None
    try:
        L5Store(absent_root)
    except StoreError as exc:
        raised = str(exc)
        raised_type = "StoreError"
    except Exception as exc:                          # noqa: BLE001
        raised = str(exc)
        raised_type = type(exc).__name__
    _common.write_json(out / "absence_probe.json", {
        "missing_dataset_raises": raised is not None,
        "error_type": raised_type, "error": raised,
    })
    return {"probe": "absence", "typed_error_raised": raised is not None,
              "error_type": raised_type}


# ------------------------------------------------------- 3. uncatchable classes
def probe_uncatchable(out: Path) -> dict:
    """Report each uncatchable class as a result. Where a machine-checkable
    proxy exists, demonstrate it; otherwise state the boundary plainly."""
    spec = _common.read_json(HERE / "inputs" / "spec.json")
    limits = spec["uncatchable_classes"]

    # trust_user proxy: route under policy v13 (trust_user) and confirm the
    # decision record carries classifier_mode='trust_user' and
    # privacy_class='public' BY CONSTRUCTION, not by computation.
    os.environ[_common.SECRET_ENV] = _common.SECRET_VALUE
    try:
        tu_root = out / "trust_user_proxy"
        l5root = tu_root / "stores" / "l5"
        l3root = tu_root / "stores" / "l3"
        _common.scaffold_l5_store(l5root)
        conns = ShellConnections(l5_root=l5root, l3_root=l3root,
                                    frozen_l5_root=_common.FROZEN_L5_DATASETS,
                                    user_id="e5", agent_id="l6-shell-e5")
        add = conns.add(FAKE_CONFIG, intent_verbatim="E5: trust_user proxy connection",
                           session_id="s_e5")
        router = ShellRouter(L5Store(l5root), health=Health(),
                                policy_label=_common.POLICY_LABEL)
        pres = router.route({"text": "E5 trust_user proxy", "request_id": "req_e5_tu"},
                               dry_run=True, run="e5-trust-user")
        dec = L5Store(l5root).get("decision_log", pres.decision_ref)
        trust_user_proxy = {
            "classifier_mode": dec.get("classifier_mode"),
            "privacy_class": dec.get("privacy_class"),
            "mode_is_trust_user": dec.get("classifier_mode") == "trust_user",
            "privacy_public_by_construction": dec.get("privacy_class") == "public",
            "allocated": add.allocated_id,
        }
        _common.write_json(tu_root / "decision_record.json", dec)
        _common.write_json(tu_root / "trust_user_proxy.json", trust_user_proxy)
    finally:
        os.environ.pop(_common.SECRET_ENV, None)

    results = []
    for lim in limits:
        row = {"limit": lim["limit"], "proxy": lim["proxy"], "demonstrated": None}
        if "trust_user" in lim["limit"]:
            row["demonstrated"] = (trust_user_proxy["mode_is_trust_user"]
                                      and trust_user_proxy["privacy_public_by_construction"])
        results.append(row)

    _common.write_json(out / "uncatchable.json", {
        "classes": results,
        "trust_user_proxy": trust_user_proxy,
        "count": len(results),
        "demonstrated_count": sum(1 for r in results if r["demonstrated"] is True),
        "stated_only_count": sum(1 for r in results if r["demonstrated"] is None),
    })
    return {"probe": "uncatchable", "classes": len(results),
              "trust_user_demonstrated": trust_user_proxy["mode_is_trust_user"]
                                          and trust_user_proxy["privacy_public_by_construction"]}


def main() -> int:
    _common.pin_environment()
    out = HERE / "output" / "frozen"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    results = [
        probe_expressibility(out),
        probe_tamper(out),
        probe_absence(out),
        probe_uncatchable(out),
    ]
    _common.write_json(out / "probes.json", results)
    print(json.dumps({"experiment": "E5", "probes": len(results),
                         "output": str(out)}, indent=2))

    if "--freeze" in sys.argv:
        manifest = _common.freeze_manifest(
            HERE, artifact_label="E5 shell limits (frozen inputs + scripts)")
        print(f"E5 MANIFEST frozen: {manifest['file_count']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
