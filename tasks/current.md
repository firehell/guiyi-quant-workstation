# 当前任务：AD-EC-OP-WEEKLY-ROW-COUNT-RECONCILE

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile.md`

分支：`main`

状态：`DELIVERY_READY_READONLY_RECONCILE`

## 目标

在 `TASK-2026-07-11-005-target-coverage-gap-triage` 已确认 `row_count_mismatch` 集中于 `ad.MAIN`、`ec.MAIN`、`op.MAIN` 三个 `1w` 旧版本文件后，执行只读四层对账：

- PostgreSQL `market_data_files`
- manifest CSV
- processed summary JSON
- DuckDB 实读 Parquet

本任务只做 row_count reconciliation，不做 provenance metadata 修复，不写 PostgreSQL、不写 Parquet、不调用 RQData、不修改 Alembic。

## 执行结果

- [x] 新增只读对账 CLI：
  - `scripts/rqdata_weekly_row_count_reconcile.py`
- [x] 新增对账服务模块：
  - `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- [x] 新增单元测试：
  - `services/quant-api/tests/test_weekly_row_count_reconcile.py`
- [x] 新增只读报告目录：
  - `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/`
- [x] 生成对账产物：
  - `ROW_COUNT_RECONCILE_SUMMARY.md`
  - `row_count_reconcile.csv`

## 本次对账结论

- DB 只读连接状态：`available`。
- `20260707` 旧版本周线文件：
  - `ad.MAIN`：DB row_count 47，manifest / processed summary / DuckDB 均为 55。
  - `ec.MAIN`：DB row_count 134，manifest / processed summary / DuckDB 均为 148。
  - `op.MAIN`：DB row_count 36，manifest / processed summary / DuckDB 均为 42。
  - 三者 `duplicate_datetime_count=0`，分类均为 `old_version_metadata_stale`。
- 后续同品种同周期 sibling 文件：
  - `20260710` / `20260711` 共 6 条均为 `matched`。

## 硬边界

- 未写 PostgreSQL。
- 未写 raw / processed / canonical Parquet。
- 未修改 manifest 或 checksum。
- 未调用 RQData 下载。
- 未新增 Alembic migration 或 schema。
- 未修改 `source_interval` provenance metadata。
- 未修改策略、回测、信号、live runtime、scheduler、企业微信或任何交易执行逻辑。
- 未读取或打印 `.env`、DB/RQData/Webhook 凭据。

## 验证记录

已运行验证命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_weekly_row_count_reconcile.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_row_count_reconcile.py --products ad ec op --period 1w --output-dir data/reports/ad_ec_op_weekly_row_count_reconcile_20260711
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
git diff --check
```

结果：

- `test_weekly_row_count_reconcile.py`：4 passed。
- `rqdata_weekly_row_count_reconcile.py`：通过，`db_status=available`。
- `test_target_coverage_audit.py`：5 passed。
- `git diff --check`：通过。

## 下一阶段

1. 若要消除旧版本 `20260707` mismatch，可另开受控 metadata 修复 Plan，只更新 DB row_count 或按版本归档旧记录；本任务不执行写入。
2. `source_interval_unverified` 仍需另开 provenance metadata 修复 Plan，本任务没有处理。
3. `missing_db_registration` 与 `quality_failed` 仍保持原 gate，不在本任务扩大。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/tasks/TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile.md`
- `scripts/rqdata_weekly_row_count_reconcile.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- `services/quant-api/tests/test_weekly_row_count_reconcile.py`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/ROW_COUNT_RECONCILE_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/row_count_reconcile.csv`
