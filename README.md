# DeeWaanAI OS — Layer 6: The Agentic OS Shell

Companion code and frozen artifacts for the paper:

**The Agentic OS Shell: One Surface for Prompt, View, Action, and Audit (DeeWaanAI OS Layer 6)**
Youssef Hariri · DeeWaanAI · Zenodo DOI [10.5281/zenodo.24474610](https://doi.org/10.5281/zenodo.24474610)

The shell is the sixth layer of the DeeWaanAI OS: one user surface that joins the five frozen
lower layers (Qafiya data model, view renderer, action layer, verifiable memory, model router)
into a single auditable journey from prompt to view to action to memory. It adds no authority of
its own. Every kernel transition appends exactly one event to an append-only, hash-chained audit
graph (`ds:shell_audit`); every displayed value resolves to a record through a binding; every
effect passes the permissioned action layer. The headline result: on real open data, a local
model stated confident but incorrect expenditure figures, the bindings recomputed the correct
ones, and the shell displayed the recomputed values and recorded the divergence as evidence.

This repository is a research prototype companion to the paper, not a product. Limitations and
negative outcomes are reported as first-class findings in the paper (Sections 8–10).

## Contents

| Path | What it holds |
|---|---|
| `shell/` | The runtime: kernel, session, audit graph, connections, routing, memory, views, interactions. `shell/vendor/` is the frozen snapshot of the imported Layer 3 / Layer 5 source, verified per-file against `SNAPSHOT_SHA256.json` on every import. |
| `experiments/` | CP1 integration-journey spine (`shell_spine.py`, 36 checks), CP2 functional-gate battery (`gates_battery.py`, `gates_spine.py`, 8 gates), and `cp3/` with the six frozen experiments E1–E6 (inputs, outputs, per-experiment spines) plus the master spine `cp3/cp3_spine.py`. |
| `preflight/` | The frozen pre-flight: `MANIFEST.json` (sha256 of every frozen input), `spine.py` (12/12 checks), `run_demo.py` (live demo over a fake transport), and the vendored Layer 2–4 code the demo imports. |
| `paper/` | Markdown source of truth, LaTeX source, the PDF, figures (SVG source of truth + PDF exports + persisted plotted values), and `claim_map/` — the claim-to-evidence map with its executable gate `verify_two_way.py`. |
| `brief.md`, `sketch.md` | Owner-confirmed design brief and sketch. |
| `shell-audit-schema-v0.1-delta-03-nov-2026.md` | Frozen `ds:shell_audit` v0.1 schema delta. |

## Reproducing the paper's numbers

Python 3.12, standard library only for the spines:

```
python3.12 experiments/cp3/cp3_spine.py     # master spine: snapshot 31 files, E1-E6,
                                            # preflight 12/12, CP1 36 checks, CP2 8/8 gates
python3.12 paper/claim_map/verify_two_way.py  # claim-to-evidence gate, exit 0
```

The master spine recomputes every headline number from the raw frozen artifacts; if any spine
fails, the corresponding claim is withdrawn and the script exits non-zero. E6 needs no model and
no network to re-verify: its spine reads the frozen transcript. Rebuilding the paper PDF needs
`markdown-it-py` and tectonic (or Overleaf): `python3.12 paper/md_to_tex.py` then
`tectonic paper/capstone_v0.3.tex`.

## The lower layers

Each layer is a module and a paper with its own companion repository:

- Layer 1 — [qafiya](https://github.com/DeeWaanAI/qafiya): provenance-first data model
- Layer 2 — [rawi](https://github.com/DeeWaanAI/rawi): verifiable generative views
- Layer 3 — [khatt](https://github.com/DeeWaanAI/khatt): permissioned, reversible actions
- Layer 4 — [verifiable-memory](https://github.com/DeeWaanAI/verifiable-memory): provenance-carrying recall
- Layer 5 — [model-router](https://github.com/DeeWaanAI/model-router): auditable model routing

## Data attribution

The E6 dataset is the UK Cabinet Office "Expenditure over £25,000", February 2013, used under the
Open Government Licence v3.0:

> Contains public sector information licensed under the Open Government Licence v3.0.

Licence: https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/.
The data is non-PII (payments to organisations only). No model weights are bundled anywhere in
this repository; the frozen E6 transcript was produced with a local model and re-verification
reads the transcript, not the model.

## Licence

Code and companion artifacts: GNU Affero General Public License v3.0 (AGPL-3.0), see `LICENSE`.
A commercial dual-licence is intended. The paper text is deposited on Zenodo under CC-BY-4.0.