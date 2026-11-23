# L6 pre-flight — how to run

**Required interpreter: Python 3.12+** (frozen under CPython 3.12.8). `spine.py` and `run_demo.py`
now exit loudly on an older interpreter — the default macOS `python3` (3.9.x) is **not** sufficient and
will refuse rather than produce a false failure.

From `06-shell/`:

```bash
python3.12 preflight/spine.py            # verify frozen artifacts, re-run the journey, recompute every claim
python3.12 preflight/spine.py --freeze   # re-run AND rewrite MANIFEST.json (only after inputs/outputs change)
```

Expected on success:

```
status: PASS
journey_checks_recomputed: 12
bound_records: 7
q3_total_recomputed_from_raw: 10481.96
evidence_source_rows: 21
```

`spine-result.json` records the interpreter version that produced it (`"python": "3.12.x"`).

Note: interpreter pins are per-layer. L5 runs under its own `.venv` (py3.15); this 3.12 pin is specific
to the L6 pre-flight, whose frozen artifacts were produced under 3.12.
