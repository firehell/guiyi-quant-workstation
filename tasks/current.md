# 当前任务：AD-EC-OP-WEEKLY-METADATA-ROW-COUNT-REPAIR

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair.md`

分支：`main`

状态：`DELIVERY_READY_METADATA_REPAIR`

## 目标

在 `TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile` 已确认 `ad.MAIN`、`ec.MAIN`、`op.MAIN` 三个 `20260707` 旧版本 `1w` 文件为 DB metadata stale 后，执行受控 PostgreSQL metadata row_count 修复。

本任务只允许更新 3 条 `market_data_files.row_count`，不写 Parquet、不改 manifest/checksum、不调用 RQData、不改 data_version/data_role/quality_status、不处理 provenance、missing DB registration 或 quality failed/warning。

## 执行结果

- [x] 新增受控修复 CLI：
  - `scripts/rqdata_weekly_metadata_row_count_repair.py`
- [x] 新增修复服务模块：
  - `services/quant-api/app/services/rqdata_ingest/weekly_metadata_row_count_repair.py`
- [x] 扩展只读对账模块以复用 DB metadata 字段：
  - `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- [x] 新增单元测试：
  - `services/quant-api/tests/test_weekly_metadata_row_count_repair.py`
- [x] 新增任务单：
  - `docs/tasks/TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair.md`
- [x] 生成修复报告：
  - `data/reports/ad_ec_op_weekly_metadata_repair_20260712/`
- [x] 生成修复后周线对账报告：
  - `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/`
- [x] 生成修复后目标覆盖矩阵报告：
  - `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`

## 本次修复结论

- dry-run：`ready_to_apply=True`。
- apply：`writes_database=True`。
- 仅更新 3 条 `market_data_files.row_count`：
  - `ad` / `db_file_id=44115`：47 -> 55。
  - `ec` / `db_file_id=44133`：134 -> 148。
  - `op` / `db_file_id=44159`：36 -> 42。
- 未写 raw / processed / canonical Parquet。
- 未修改 manifest、checksum、data_version、data_role、quality_status。
- 未调用 RQData 下载。
- 未新增 Alembic migration 或 schema。
- 未修改策略、回测、信号、live runtime、scheduler、企业微信或任何交易执行逻辑。

## 修复后验收

- 周线对账：`data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/`
  - 9 条记录全部 `matched`。
  - `old_version_metadata_stale` / `db_row_count_stale` 已清零。
- 目标覆盖矩阵：`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`
  - `issue_register_rows=2083`。
  - `row_count_mismatch` 已清零。
  - 剩余 issue：`source_interval_unverified=1039`、`missing_continuous_contract_map=546`、`missing_contract_universe=285`、`missing_db_registration=108`、`quality_failed=105`。

## 验证记录

已运行验证命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_weekly_metadata_row_count_repair.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_weekly_row_count_reconcile.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_metadata_row_count_repair.py --output-dir data/reports/ad_ec_op_weekly_metadata_repair_20260712
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_metadata_row_count_repair.py --apply --confirm-ad-ec-op-weekly-row-count-repair --output-dir data/reports/ad_ec_op_weekly_metadata_repair_20260712
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_row_count_reconcile.py --products ad ec op --period 1w --output-dir data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py --products-file data/universe/full_products_90.txt --output-dir data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair
```

结果：

- `test_weekly_metadata_row_count_repair.py`：5 passed。
- `test_weekly_row_count_reconcile.py`：4 passed。
- `test_target_coverage_audit.py`：5 passed。
- dry-run 修复报告：通过，`ready_to_apply=True`。
- apply 修复报告：通过，`writes_database=True`。
- after-repair weekly reconcile：9 matched。
- after-repair target coverage audit：`row_count_mismatch` 清零。

## 下一阶段

1. `source_interval_unverified` provenance metadata 修复 Plan。
2. `missing_db_registration` 的 `L/PP/V` 受控登记 dry-run 和人工确认写入。
3. `quality_failed/warning` 只读质量根因审查。
4. 参考元数据收口：continuous contract map、contract universe、交易参数、交易日历、交易时段、主力映射。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair.md`
- `scripts/rqdata_weekly_metadata_row_count_repair.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_metadata_row_count_repair.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- `services/quant-api/tests/test_weekly_metadata_row_count_repair.py`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/METADATA_REPAIR_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/metadata_repair_candidates.csv`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/metadata_repair_apply.csv`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/ROW_COUNT_RECONCILE_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/row_count_reconcile.csv`
- `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/coverage_summary.md`
- `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/issue_register.csv`
