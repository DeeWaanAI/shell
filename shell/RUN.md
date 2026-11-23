# L6 shell prototype — how to run

**Required interpreter: Python 3.12+** (frozen pre-flight is pinned to CPython 3.12.8;
the shell matches that pin — build-instructions §hard-won fact 3). ``shell/_bootstrap.py``
raises ``SystemExit`` on an older interpreter rather than producing a false failure.

From `06-shell/`:

```bash
# CP1: run ONE end-to-end journey (prompt -> route -> recall -> render -> edit
# write-back -> gated action -> memory) with a connection mutation whose
# successor id lands on the audit graph. Writes under experiments/output/cp1/.
python3.12 experiments/e2e_journey.py

# Independent spine: recompute every CP1 headline number from raw artifacts.
python3.12 experiments/shell_spine.py

# Regression baseline (must stay PASS 12/12, Q3 total 10481.96):
python3.12 preflight/spine.py
```

## Interpreter standardisation

The shell standardises on **CPython 3.12** (the same interpreter the frozen pre-flight
requires). The monitor's acceptance battery previously imported L3 under L5's own
`.venv` (3.15) and that also worked, but the shell pins ONE interpreter so a decision
record, an audit event and a rendered view all resolve against the same runtime.

Verified imports under python3.12:

* L1 `qafiya_core` (pre-flight vendor)
* L2 `dvr` (pre-flight vendor)
* L3 `actionlayer` + `adapters/connection` (source, read-only) — required because the
  pre-flight vendor snapshot predates connection-actions v0.2 and has no
  `adapters/connection.py`
* L4 `memory` (pre-flight vendor)
* L5 `store`, `connection_ops`, `connections`, `decide`, `classify`, `gates`, `cost`,
  `tokens`, `transport`, `health`, `verifier` (source, read-only)

## Boundaries observed

* The shell NEVER writes into another layer's frozen dataset. Per-journey L5 and L4
  stores are scaffolded on temp/output roots; the frozen L5 `datasets/` tree is read
  only for its schemas + `policy`/`rules`/`capabilities` seeds.
* Connection mutations go THROUGH L3 (`ActionEngine(root, connection_ops=<L5 ops>)`).
  Read-only `list` / `status` stay L5 operations with their own evidence — they are
  NOT actions (brief §3.4).
* `connection.retire` and `connection.privacy_change` are COMPENSABLE and supersede
  to a NEW `mdl_*` id. The shell records the successor via
  `ops.get_active_successor(old_id)` / `ops.last_successor_id` on the audit event as
  `successor_ref` — never assuming a connection id is stable across a mutation.
* No paid or live provider call. `ShellRouter.route(dry_run=True)` is the default and
  a live call raises `PermissionError` unless `allow_live_call=True` is passed with a
  recorded owner approval.
