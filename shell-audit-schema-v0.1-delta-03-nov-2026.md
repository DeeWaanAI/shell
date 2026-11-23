# `ds:shell_audit` — schema v0.1 delta (for monitor review; NOT frozen by L6)

**From:** L6 layer agent
**To:** Monitor
**Date:** 03 Nov 2026
**Status:** DRAFT v0.1 — sent for the monitor to register in `INTERFACES.md` per the CP2
clearance answer 4. **L6 has not frozen this and will not.** The authoritative reference
implementation is `06-shell/shell/audit.py` (`ShellAuditStore`), exercised by CP1 (36 checks),
CP2 F1/F7, and CP3 E1/E2.

This delta promotes the L6 audit event graph from the "runtime kernel loop — sketch only" row
in `INTERFACES.md` to a frozen contract. It covers: event fields; id conventions; Qafiya §8
fileset + v1.3 chained-history conformance; and the replay contract.

---

## 1. What `ds:shell_audit` is

The shell owns ONE append-only, hash-chained dataset: `ds:shell_audit`. Each kernel transition
(brief §4.1) appends exactly one `r_*` event. The graph JOINS lower-layer records by reference;
it never rewrites, merges, or duplicates their bindings or histories (brief §5 boundary). Lower
layer records stay in their owning stores (L3 `action_log`, L4 memory datasets, L5
`decision_log`/`models`, Qafiya `expenses`). Replay starts from a session id and resolves the
complete graph.

## 2. Storage conformance (Qafiya §8 + v1.3)

`ds:shell_audit` uses the full Qafiya §8 fileset under
`<store_root>/datasets/shell_audit/`:

```
schema.json  data.jsonl  history.jsonl  bindings.jsonl  SUPERSEDED.json
```

* `history.jsonl` is **chained from the Qafiya v1.3 substrate** — `qafiya_core.chain.append`
  writes `prev_hash`/`entry_hash` per entry; `qafiya_core.chain.verify` recomputes the chain and
  never repairs it. The shell does not reimplement chaining.
* `bindings.jsonl` carries Qafiya §7 bindings for any value or claim the shell displays, kept
  separate from lower-layer bindings (never merged).
* `SUPERSEDED.json` is the quarantine list (§9.1); a binding whose `authoritative_artifact` is
  quarantined resolves to `Unresolved` by construction.
* Records are written with `canon` (sorted-key, compact JSON) + `fsync`, matching L5's
  `store.append` discipline.

## 3. Event fields (v0.1)

Every event is an `r_*` record. Required fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | id (`r_*`) | Prefixed sortable id (OS identity rule, INTERFACES.md). Immutable. |
| `created_at` | timestamp | UTC, `%Y-%m-%dT%H:%M:%SZ`. |
| `spec_version` | string | `"0.1"` for this delta. |
| `status` | enum[active,retired,discredited] | Lifecycle; events are normally `active`. |
| `superseded_by` | id\|null | Null for an append-only event graph. |
| `source_ref` | list<id> | Provenance refs the event was derived from. |
| `session_id` | id (`s_*`) | The journey this event belongs to. |
| `sequence` | number | **Monotonic per session**, allocated by the store so two callers cannot mint the same sequence. Complete: 1..N with no gaps. |
| `state` | string | The kernel state entered (brief §4.1; see §5). |
| `input_event_refs` | list<id (`r_*`)> | Causal order made explicit, not inferred from timestamps. |
| `request_ref` | id\|null (`req_*`) | The prompt/request that opened the journey. |
| `decision_ref` | id\|null (`dec_*`) | L5 routing decision record. |
| `view_refs` | list<id (`v_*`)> | L2 views rendered/validated. |
| `edit_refs` | list<id (`b_*`)> | DVR edit bindings applied. |
| `action_refs` | list<id (`a_*`)> | L3 action records gated/executed. |
| `memory_refs` | list<id (`m_*`)> | L4 turns/notes bound. |
| `connection_refs` | list<id (`mdl_*`)> | L5 connection records referenced. |
| `successor_ref` | id\|null (`mdl_*`) | **The NEW id when a connection mutation superseded.** Never assume a connection id is stable across a mutation (build-instructions §hard-won fact 2). |
| `artifact_hashes` | object | sha256 of artifacts needed to replay the transition. |
| `check_states` | object | Gate/check outcomes (e.g. `route_outcome`, `action_gate_outcome`). |
| `coverage` | object | Provenance coverage shown to the user (e.g. `qafiya_before: "coverage: 100%"`). |
| `declared_cost_usd` | number\|null | L5 policy calculation from **user-declared** prices + estimated tokens. A local `$0` is a declaration, not a measured zero. |
| `actual_metered_cost_usd` | number\|null | Provider usage result. **`null` means "not metered", never `$0`.** |
| `content_policy` | object | The active L5 logging policy in force for this event. |
| `notes` | string\|null | Human-readable transition note. No secrets. |

### 3.1 Honesty fields (explicit, per CP2 clearance answer 4)

* `declared_cost_usd` and `actual_metered_cost_usd` are **two separate fields, never
  conflated** (L5 RC-3.5). A dry-run or refused route leaves `actual_metered_cost_usd = null`;
  the display renders "not metered", not `$0`.
* A simulated meter (the CP2/CP3 local fake transport) labels every attempt
  `meter = "simulated_local_fake"`. A simulated number is never recorded as real provider
  metering.
* `content_policy` records whether prompt/response content may be stored. **Secrets never enter
  an event.** Only an env-var NAME (`key_env`) crosses the boundary; the VALUE is refused by
  both L3 and L5 and scanned for by every spine.

## 4. Id conventions (one rule for the whole OS)

`ds:shell_audit` references lower-layer ids by their frozen prefixes (INTERFACES.md identity
convention). The shell mints only `r_*` (events), `s_*` (sessions) and `req_*` (requests); every
other ref is owned by its layer:

| Prefix | Owner | Referenced on the event as |
|---|---|---|
| `r_*` | L6 shell_audit | `id`, `input_event_refs` |
| `s_*` | L6 session | `session_id` |
| `req_*` | L6 request | `request_ref` |
| `dec_*` | L5 decision_log | `decision_ref` |
| `mdl_*` | L5 models | `connection_refs`, `successor_ref` |
| `a_*` | L3 action_log | `action_refs` |
| `g_*` | L3 grants | (inside the L3 record, not duplicated here) |
| `m_*` | L4 memory | `memory_refs` |
| `v_*` | L2 view | `view_refs` |
| `b_*` | Qafiya/L2 binding | `edit_refs`, bindings.jsonl |

All ids are prefixed, sortable, immutable. The shell never re-mints a lower-layer id.

## 5. Kernel states (the `state` vocabulary)

Frozen from brief §4.1 / sketch §3.1. The transition table is enforced by
`shell/kernel.py:ALLOWED`; an edge not in the table raises `IllegalTransition` and writes NO
event (CP2 F1).

`RECEIVED, ROUTED, RECALLED, COMPOSED, VIEW_VALIDATED, RENDERED, AWAITING_USER, WRITE_BACK,
ACTION_GATED, EXECUTED, REMEMBERED, CLOSED`

Allowed edges (v0.1):

```
RECEIVED       -> ROUTED
ROUTED         -> RECALLED | CLOSED            (routing refusal skips composition)
RECALLED       -> COMPOSED
COMPOSED       -> VIEW_VALIDATED
VIEW_VALIDATED -> RENDERED
RENDERED       -> AWAITING_USER | WRITE_BACK | REMEMBERED
AWAITING_USER  -> ACTION_GATED | WRITE_BACK | REMEMBERED
WRITE_BACK     -> VIEW_VALIDATED               (edit -> invalidate -> re-prove -> re-render)
ACTION_GATED   -> EXECUTED | CLOSED            (refused/rejected action produces no execution)
EXECUTED       -> REMEMBERED | CLOSED
REMEMBERED     -> CLOSED
CLOSED         -> (terminal)
```

## 6. Replay contract

`ShellAuditStore.replay(session_id)` is the frozen replay entry point. It MUST:

1. return the session's events ordered by `sequence`;
2. verify the chained history (`qafiya_core.chain.verify`) and report `chain_ok`;
3. resolve every `input_event_ref` against the session's own event ids and report
   `input_refs_missing` (must be empty for a complete graph);
4. expose `successors` — every `(event_id, successor_ref)` pair — so a reviewer can confirm a
   connection supersession is recorded and never assumed stable.

Replay does NOT resolve lower-layer refs (`decision_ref`, `action_refs`, `memory_refs`,
`connection_refs`) against their owning stores — that is the **spine's** job, so a replay never
depends on the shell holding another layer's data. The CP3 E1/E2/F7 spines perform that
cross-store resolution and assert every ref resolves in its owning store.

### 6.1 Invariants a conformant store MUST hold

* **I-A (one event per transition):** every allowed transition appends exactly one event; an
  illegal transition appends none and raises.
* **I-B (monotonic sequence):** `sequence` is 1..N per session with no gaps and no duplicates.
* **I-C (chain integrity):** `history.jsonl` verifies; a naive tamper is detected.
* **I-D (succession recorded):** when a connection mutation supersedes, `successor_ref` carries
  the NEW `mdl_*` id on that event and every subsequent event of the session.
* **I-E (no secrets):** no event, binding, or note contains a secret VALUE; only an env-var NAME
  may appear.
* **I-F (declared ≠ metered):** `declared_cost_usd` and `actual_metered_cost_usd` are separate;
  an unmetered route records `actual_metered_cost_usd = null`, never `0`.

## 7. Reference implementation + evidence

* `06-shell/shell/audit.py` — `ShellAuditStore` (append_event, append_binding, events,
  bindings, superseded, verify_chain, replay).
* `06-shell/shell/kernel.py` — `Kernel`, `KernelState`, `ALLOWED`, `IllegalTransition`,
  `transition_table()`.
* Evidence this delta is built on, all green under Python 3.12.8:
  * CP1 `experiments/shell_spine.py` — 36 checks; 14 events; all 12 states; chain ok; successor
    recorded.
  * CP2 `experiments/gates_spine.py` — F1 (transitions + illegal probes), F7 (replay: sequences
    complete, every lower-layer ref resolves in its owning store, 9 owned chains verify).
  * CP3 `experiments/cp3/{e1_journey,e2_auditability}/spine.py` — E1 journey replay; E2 five
    negative variants each replayed with missing-ref count 0 and chains verified.

## 8. What v0.1 does NOT cover (honest boundaries)

* No multi-user / concurrent-session semantics beyond the per-session monotonic sequence and
  the `flock`-free single-writer assumption of one shell process per journey store.
* No event compaction, rotation, or archival policy.
* No cross-session graph queries (replay is per-session by construction).
* The hash chain detects modification, **not** an attacker who rewrites the store and recomputes
  every hash (reported as an uncatchable class in CP3 E5, not claimed as caught).
* `successor_ref` records ONE successor per event. A multi-hop succession chain is reconstructed
  by following `superseded_by` in the owning L5 store, not by duplicating the chain here.

## 9. Requested monitor action

1. Register `ds:shell_audit` schema v0.1 in `INTERFACES.md` as a frozen contract, consumed by
   the capstone paper.
2. Update the "Runtime kernel loop — sketch only" row to reflect the built kernel (states +
   transition table + audit graph), pointing at this delta and `shell/kernel.py` /
   `shell/audit.py`.
3. Confirm the honesty fields (§3.1) and invariants (§6.1) match what you will audit at the
   capstone gate.

L6 will not freeze this delta and will not edit `INTERFACES.md`. Awaiting monitor registration
before the capstone paper (brief §9 step 5).
