# Task 5 Read-Only Inventory and Canonical Docs Report

## Status

CODE_COMPLETE_EXTERNAL_GATE_PENDING.  The task branch contains the read-only
derived/reference inventory and canonical-document boundary updates; it is not
merged to `develop`.  No real PostgreSQL, data root, Runtime, RQData, live
notification, migration, rebuild, deletion, or trading operation was run.

## Inventory contract

- New CLI: `scripts/derived_reference_inventory.py`.
- New service: `app.services.derived_reference_inventory`.
- Stable JSON stdout uses `schema_version=1` and fixed category order:
  `indicator_cache`, `backtest`, `signal_review`, `live_eod_sample`,
  `permanent_derived_periods`, `duplicate_bar_layers`,
  `profile_binding_legacy_lineage`, and `report_14_15_references`.
- Each category reports its reason, exact matching DB table/count/IDs,
  read/stat/SHA-256 filesystem evidence, and report-14/15 source/document
  reference locations. Missing roots and no configured DB remain stable empty
  evidence, not errors.
- PostgreSQL starts `BEGIN` then `SET TRANSACTION READ ONLY`; SQLite enables
  `PRAGMA query_only`. The collector has no RQData import or call, no write,
  delete, apply, repair, or ambiguous destructive mode. Database URLs are
  injected only as an option and are never printed.

## TDD evidence

1. Service RED: the initial test failed collection with
   `ModuleNotFoundError: app.services.derived_reference_inventory`.
2. Service GREEN: minimal collector made deterministic DB/filesystem/reference
   assertions pass.
3. CLI RED: after intentionally removing the new thin wrapper, its integration
   test failed with exit code 2 because the script file did not exist.
4. CLI GREEN: restoring the wrapper made deterministic stdout/no-stderr tests
   pass.

`services/quant-api/tests/test_derived_reference_inventory.py` now covers all
eight categories, deterministic repeated output, exact fixture table/count/ID
and SHA-256/stat evidence, SQLite query-only trace with no DML/DDL/commit,
fake PostgreSQL `SET TRANSACTION READ ONLY` with no commit, CLI stdout/stderr,
rejected `--delete`, and injected database URL redaction.

## Canonical-document decision

Only trusted historical bars plus minimal Catalog/Manifest/Gap/MainContractMap
metadata are migration assets. Old indicators/cache, Backtest, Signal/Review,
live/EOD/Sample, permanent derived periods, duplicate bar layers, and
Profile/Binding/legacy lineage are rebuild-only or compatibility-only.
Backtest, Signal, and Review active input is `canonical_consumer_input_v1`
through `MarketDataService`, not an active Profile/Binding selector. Report
14/15 remain immutable Git-traceable historical snapshots, not active
regression/Gate material. Task 07 deletion remains blocked pending an exact
deletion manifest, zero active references, independent Sol Review, and owner
exact-scope approval.

## Validation

```text
focused inventory tests: 5 passed
consumer regression: 34 passed
full backend: 2420 passed, 36 skipped
task scoped ruff: passed
Web tests: 185 passed, 1 skipped
Web production build: passed
engineering/docs gates: passed (192 engineering tests)
secret scan: passed (9340 files)
git diff --check: passed
```

Full-repository ruff remains blocked only by a pre-existing unused `sys` import
in `scripts/engineering/worktree_flow.py`; this task did not modify that file.

## External gate and rollback

Run the CLI later only with explicit injected real database/data-root settings
under the dedicated read-only Gate. It does not grant any migration, rebuild,
delete, Runtime, notification, or trading action. Rollback is the single task
commit; no external state was changed.
