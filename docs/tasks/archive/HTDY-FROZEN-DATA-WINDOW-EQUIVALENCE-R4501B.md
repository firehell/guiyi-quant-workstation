# HTDY Frozen Data Window Equivalence R4501B

## Status

`COMPLETED / HTDY_FROZEN_DATA_WINDOW_EQUIVALENT`

## Scope and boundaries

Only the R4501B completion module, fixed `--data-root` CLI, tests, current-task/R45 task records, and versioned evidence were changed. The method is `immutable_base_plus_versioned_completion`: immutable old 15m base plus exactly fifteen independently re-aggregated passed 1m bars.

No protocol, Parquet, manifest, DB, Profile binding, report14/15, X5 packet, strategy, RQData, or notification operation was modified or run. Existing R45 failure packet `142de03ada02555ce2d734e532cee097b5c23e4d91b6f92d62121b8e771b4c47` remains retained and hash-bound.

## Acceptance

- Old base: `19366` bars; completion: exactly `15` bars from `2026-07-10T09:15:00` through `2026-07-10T15:00:00`.
- Revalidated result: `19381/19381`, `difference_count=0`, ordered hash `c32df4e6b52e9efa0c71c6851d04cc9e0abd2a39f204776729b9a35037f6eba0`.
- Gate: `HTDY_FROZEN_DATA_WINDOW_EQUIVALENT`.
- Pointer binds the R45-00 baseline, original failure, completion, and revalidated pass packet hashes.

## TDD evidence

Red: `PYTHONPATH=services/quant-api:packages/quant-core /private/tmp/guiyi-htdy-frozen-data-identity-drift-triage-r4501a/services/quant-api/.venv/bin/python -m pytest -q services/quant-api/tests/test_htdy_frozen_data_completion_r4501b.py` exited 2 with `ModuleNotFoundError: app.backtest.htdy_frozen_data_completion`.

Green: the same command passed after implementation. The fixed-scope CLI also completed against `/Volumes/扩展盘/guiyi-quant-workstation` and wrote only the R4501B evidence paths.

## Rollback

Remove only the new R4501B code, task record, and versioned evidence. Do not delete or edit the original failed packet or any canonical asset.
