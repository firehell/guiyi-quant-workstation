# TASK-2026-07-12-002：AD/EC/OP 周线 Metadata Row Count 受控修复

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair |
| Branch | main |
| Status | DELIVERY_READY_METADATA_REPAIR |
| Source Task | TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile |
| Source Report | data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/ |
| Repair Report | data/reports/ad_ec_op_weekly_metadata_repair_20260712/ |
| After Reconcile Report | data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/ |
| After Target Coverage Report | data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/ |

## 1. 任务类型

PostgreSQL metadata row_count 受控修复 / 数据质量 Gate 收敛 / 不重建 Parquet。

## 2. 背景

上一阶段只读四层对账确认 `ad.MAIN`、`ec.MAIN`、`op.MAIN` 三个 `20260707` 旧版本 `1w` 文件存在 DB `market_data_files.row_count` stale：

| product | db_file_id | old row_count | target row_count | file |
|---|---:|---:|---:|---|
| ad | 44115 | 47 | 55 | ad_MAIN_1w_20230103_20260707_v2.parquet |
| ec | 44133 | 134 | 148 | ec_MAIN_1w_20230103_20260707_v2.parquet |
| op | 44159 | 36 | 42 | op_MAIN_1w_20230103_20260707_v2.parquet |

manifest、processed summary、DuckDB 实读一致，且 `duplicate_datetime_count=0`；后续 `20260710/20260711` sibling 文件均为 matched。

## 3. 目标

1. 生成 dry-run metadata 修复候选。
2. 使用显式确认开关受控更新 3 条 `market_data_files.row_count`。
3. 不修改 Parquet、manifest、checksum、data_version、data_role、quality_status。
4. 修复后重跑周线对账和目标覆盖矩阵审计。
5. 验证 `row_count_mismatch` 从目标覆盖 issue register 中清零。

## 4. 允许修改范围

- `scripts/rqdata_weekly_metadata_row_count_repair.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_metadata_row_count_repair.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- `services/quant-api/tests/test_weekly_metadata_row_count_repair.py`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair.md`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/`
- `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`

## 5. 禁止修改范围

- 不写 raw / processed / canonical Parquet。
- 不修改 manifest 或 checksum。
- 不调用 RQData 下载。
- 不新增 Alembic migration 或 schema。
- 不修改 `data_version`、`data_role`、`quality_status`。
- 不处理 `source_interval_unverified`、`missing_db_registration`、`quality_failed/warning` 或参考元数据缺口。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信或任何交易执行逻辑。
- 不读取或打印 `.env`、DB/RQData/Webhook 凭据。

## 6. 执行摘要

新增受控 CLI：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_metadata_row_count_repair.py --output-dir data/reports/ad_ec_op_weekly_metadata_repair_20260712
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_metadata_row_count_repair.py --apply --confirm-ad-ec-op-weekly-row-count-repair --output-dir data/reports/ad_ec_op_weekly_metadata_repair_20260712
```

写入保护条件同时匹配：

```text
id + provider=rqdata + data_type=bars + period=1w + instrument_symbol
+ exact file_path + old row_count
```

## 7. 修复结果

- dry-run：`ready_to_apply=True`。
- apply：`writes_database=True`。
- 实际只更新 3 条 `market_data_files.row_count`：
  - `ad`：47 -> 55。
  - `ec`：134 -> 148。
  - `op`：36 -> 42。
- 未写 Parquet、manifest、checksum、data_version、data_role、quality_status。

## 8. 修复后对账

`data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/`：

| classification | count |
|---|---:|
| matched | 9 |

三条旧版本文件和六条 sibling 文件均为 `matched`。

## 9. 修复后目标覆盖矩阵

`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`：

- `target_catalog_rows`：17689。
- `physical_inventory_rows`：15164。
- `issue_register_rows`：2083。
- `db_snapshot_source`：database。
- `row_count_mismatch`：已清零。

剩余 issue：

| issue_type | count |
|---|---:|
| source_interval_unverified | 1039 |
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| missing_db_registration | 108 |
| quality_failed | 105 |

## 10. 测试与验证

已运行：

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
- metadata repair dry-run：通过，`ready_to_apply=True`。
- metadata repair apply：通过，`writes_database=True`。
- after-repair weekly reconcile：9 matched。
- after-repair target coverage audit：`row_count_mismatch` 清零。

## 11. 结论边界

- 本任务完成的是 3 条旧版本周线 DB metadata row_count 受控修复。
- 本任务不是 provenance metadata 修复。
- 本任务不是 `missing_db_registration` 登记。
- 本任务不是 `quality_failed/warning` 修复。
- 本任务不改变 active 数据入口、不授权 Stage 9、不影响企业微信发送边界。

## 12. 下一步建议

1. 另开 `source_interval_unverified` provenance metadata 修复 Plan。
2. 另开 `L/PP/V` missing DB registration dry-run 和人工确认写入。
3. 另开 `quality_failed/warning` 只读质量根因审查。
4. 另开参考元数据收口 Plan，处理 continuous contract map、contract universe、交易参数、交易日历、交易时段和主力映射。
