# INTERFACES.md — the OS contract registry (monitor-maintained)

**Rule (PROJECT.md §contracts):** layers code against the versions listed here.
A contract is consumed only when **frozen**; drafts may be read for design only.
Version bumps are announced by editing this file (monitor) — never silently.

## Registry

| Contract | Version | Status | Lives in | Consumed by |
|---|---|---|---|---|
| Qafiya data model (bindings, stores, two-layer check) | v1.1 | **frozen** | `01-data-layer-qafiya/spec/spec.md` + github.com/DeeWaanAI/qafiya | L2 ✅, L3 ✅, L4 ✅ |
| Qafiya hash-chained history | v1.3 | **frozen** (integrated in qafiya-core v0.2.0, GitHub) | `spec/spec-v1.3-delta.md` + `qafiya_core/chain.py` | L3 ✅ adopted, L4 (guide ready) |
| View grammar (dvr) | 1.1 | **frozen** (2026-10-27: `action` role + binding discovery + `literal` addendum; cross-render of L4 view through L2 monitor-verified 2026-10-29) | `02-view-renderer/` | L3 (mock → real), L4 (mock → real), L6 |
| Action record + permission scope | v0.1 | **frozen** (2026-10-20 header; conformance monitor-verified) | `03-action-layer/` | L6 |
| Memory binding + read-path | v1.0 | **frozen** (2026-10-26 header; chain adopted from v1.3 substrate; tests 13/13, spine OK — monitor-verified) | `04-memory/` | L5, L6 |
| Model routing policy | v1.1 | **frozen** (2026-10-26; spec sha256 e009407e… matches `05-model-router/FREEZE-v1.1.md`) | `05-model-router/spec.md` | L6 |
| Runtime kernel loop | — | sketch only | `06-shell/` | all |

## Identity convention (one rule for the whole OS)

Adopted from Qafiya §1.1: **prefixed, sortable, immutable ids**; prefix declares the
owning layer (`r_*` records, `b_*` bindings, `v_*` views, `m_*` memory, `s_*`
sessions, `a_*` actions, `g_*` grants). ULID (or sortable uuid) as payload.
- **L3:** done (2026-10-20, monitor-verified). ~~replace bare uuid4~~ `action_id`/`grant_id` with `a_*`/`g_*`
  prefixed sortable ids. Mechanical change; paper text unaffected (it says "uuid-v4"
  — update to "prefixed sortable id (OS identity rule)" in the next revision).
- **L2/L4:** already compliant in spirit; verify prefixes in code.
- **L5 (registered 2026-10-26):** `mdl_*` (model connections), `cap_*` (capabilities),
  `pol_*` (policies), `rul_*` (rules), `dec_*` (decision log), `req_*` (requests).
  No prefix retired in the RC simplification.

## Storage convention (Qafiya §8 everywhere)

Every persistent dataset in any layer MUST use
`schema.json + data.jsonl + history.jsonl (chained from v1.3) + bindings.jsonl + SUPERSEDED.json`.
- **L4:** already conformant (verified 2026-10-20).
- **L4:** conformant (verified 2026-10-20).
- **L3:** conformant as of 2026-10-20 (monitor-verified: `datasets/action_log/` +
  `datasets/grants/` with full §8 filesets, adapter content at root per the guide).
