# Task 02 Implementation Plan — Historical Catalog, Manifest, and Gap Metadata

## Global Constraints

- Work only in `<LOCAL_VOLUME>/GuiyiWorktrees/tasks/data-core-metadata` on
  `feature/data-core-metadata`, based on `develop`.
- Do not connect to or migrate the production database.
- Do not read or write canonical Parquet, manifest files, Profile/Binding rows,
  Runtime state, notifications, or trading state.
- The Alembic revision is schema-only: no legacy `market_data_files` backfill.
- Reuse the existing singular `main_contract_map` table through
  `load_strict_main_contract_mapping`; do not change its schema or rows.
- The catalog main-contract path is restricted to
  `provider=rqdata`, `rule=volume_open_interest`, and `rank=1`.
- Follow TDD: add a behavior test, run it and record the expected RED failure,
  then add the minimum implementation and record GREEN.
- PostgreSQL migration tests must require
  `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` and the existing database/OID safety
  guard. SQLite must not count as migration acceptance.
- Do not push, merge, deploy, or clean the task worktree during implementation.

## Task 1: Implement Catalog Models and Create-Only Service

Create `services/quant-api/app/models/data_core.py`,
`services/quant-api/app/data_core/__init__.py`, and
`services/quant-api/app/data_core/catalog.py`; update the model package exports.

Implement:

- `MarketDataset` with a unique DatasetKey composed of
  `provider`, `data_type`, `instrument_symbol`, `contract_code`, and `period`.
- `MarketPartition` with a half-open coverage window, immutable manifest/file
  identity, SHA-256 digest/checksum, row count, and optional controlled overlap
  reason.
- `DataGap` uniquely located by dataset plus exact half-open gap window.
- Frozen value objects `DatasetKey`, `PartitionManifest`, and `GapWindow`.
- `HistoricalCatalog.get_or_create_dataset`, `register_partition`,
  `record_gap`, `list_partitions`, `list_gaps`, and strict rank-1 main-contract
  lookup delegated to the existing helper.
- Stable fail-closed catalog errors. Repeating identical create-only input is
  idempotent; an exact-identity conflict with different immutable facts fails.
- Allowed overlap reasons are exactly `version_replacement`,
  `repair_overlay`, and `rollover_transition`.

Add `services/quant-api/tests/data_core/test_catalog.py` covering normalization,
DatasetKey uniqueness, idempotency, immutable conflicts, digest/checksum
validation, exact gap uniqueness, stable ordering, and strict rank-1 lookup.

Use portable ORM constraints for unit tests. PostgreSQL-only exclusion and
trigger behavior belongs to Task 2.

## Task 2: Add Alembic Revision and Isolated PostgreSQL Migration Tests

Before creating the revision, run `alembic heads` and bind
`down_revision` to the single actual head at execution time.

Create one Alembic revision and
`services/quant-api/tests/alembic/test_data_core_migration.py`.

The revision must:

- Create only `market_datasets`, `market_partitions`, and `data_gaps`, their
  indexes, checks, foreign keys, PostgreSQL coverage exclusion, and immutable
  partition trigger/function.
- Enforce lower-case 64-character SHA-256 values, positive windows, nonnegative
  row counts, unique DatasetKey, exact partition identity, and exact gap window.
- Treat coverage windows as `[start, end)`: touching boundaries are allowed;
  unexplained overlaps fail; rows carrying one of the three controlled
  `overlap_reason` values are auditable exceptions.
- Avoid requiring `btree_gist`; use built-in PostgreSQL range/GiST expressions.
- Prevent updates to partition dataset/window/version/URI/digest/checksum.
- Leave `main_contract_map`, legacy market metadata, Profile/Binding rows, and
  all files untouched.
- Downgrade only the new trigger/function and three new tables in dependency
  order.

Migration tests must use the existing isolated PostgreSQL safety guard and
cover:

- empty database `upgrade head -> downgrade parent -> upgrade head`;
- upgrade from the current parent revision;
- table/constraint/index/trigger presence;
- unique/check/SHA-256/immutability/coverage behavior;
- touching coverage success, unexplained overlap failure, explained overlap
  success;
- Profile/Binding and rank-1/rank-2 main-contract rows unchanged;
- a filesystem sentinel unchanged across downgrade/upgrade.

Run focused catalog and migration tests, migration guard tests, `alembic heads`,
`alembic check`, targeted Ruff, backend health tests, secret scan, and
`git diff --check`. Commit the implementation after all required checks.
