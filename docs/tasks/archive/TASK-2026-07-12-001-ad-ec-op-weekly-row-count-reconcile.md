# TASK-2026-07-12-001：AD/EC/OP 周线 Row Count 只读对账

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile |
| Branch | main |
| Status | DELIVERY_READY_READONLY_RECONCILE |
| Source Task | TASK-2026-07-11-005-target-coverage-gap-triage |
| Source Report | data/reports/target_coverage_gap_triage_20260711/ |
| Output Report | data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/ |

## 1. 任务类型

数据质量检查 / 周线 row_count metadata 对账 / 只读根因确认

## 2. 背景

`TASK-2026-07-11-005-target-coverage-gap-triage` 已确认 `row_count_mismatch` 只涉及 3 个 unique weekly dominant-main files：

| symbol | metadata row_count | DuckDB row_count | delta | duplicate datetime |
|---|---:|---:|---:|---:|
| ad.MAIN | 47 | 55 | 8 | 0 |
| ec.MAIN | 134 | 148 | 14 | 0 |
| op.MAIN | 36 | 42 | 6 | 0 |

本任务继续只读对账 DB、manifest、processed summary 与 DuckDB，不执行任何修复。

## 3. 目标

1. 对 `ad.MAIN`、`ec.MAIN`、`op.MAIN` 的 `1w` 文件输出逐文件 row_count 对账。
2. 区分 DB metadata stale、manifest/summary stale、Parquet row issue 与 DB unavailable partial。
3. 检查是否存在后续同品种同周期 matched sibling 文件。
4. 保持 `source_interval` provenance metadata 修复在本任务之外。

## 4. 允许修改范围

- `scripts/rqdata_weekly_row_count_reconcile.py`
- `services/quant-api/app/services/rqdata_ingest/weekly_row_count_reconcile.py`
- `services/quant-api/tests/test_weekly_row_count_reconcile.py`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/tasks/TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/`

## 5. 禁止修改范围

- 不写 PostgreSQL。
- 不写 raw / processed / canonical Parquet。
- 不修改 manifest 或 checksum。
- 不调用 RQData 下载。
- 不新增 Alembic migration 或 schema。
- 不修改 `source_interval` provenance metadata。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信。
- 不读取或打印 `.env`、DB/RQData/Webhook 凭据。

## 6. 执行摘要

新增窄口径只读 CLI：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_row_count_reconcile.py --products ad ec op --period 1w --output-dir data/reports/ad_ec_op_weekly_row_count_reconcile_20260711
```

输出：

- `ROW_COUNT_RECONCILE_SUMMARY.md`
- `row_count_reconcile.csv`

## 7. 本次对账结论

- DB 只读连接状态：`available`。
- 共输出 9 条对账记录。
- 分类结果：

| classification | count |
|---|---:|
| matched | 6 |
| old_version_metadata_stale | 3 |

### 20260707 旧版本文件

| symbol | DB row_count | manifest row_count | processed summary row_count | DuckDB row_count | duplicate datetime | classification |
|---|---:|---:|---:|---:|---:|---|
| ad.MAIN | 47 | 55 | 55 | 55 | 0 | old_version_metadata_stale |
| ec.MAIN | 134 | 148 | 148 | 148 | 0 | old_version_metadata_stale |
| op.MAIN | 36 | 42 | 42 | 42 | 0 | old_version_metadata_stale |

### 后续 sibling 文件

- `ad/ec/op` 的 `20260710` 和 `20260711` 周线 sibling 文件均为 `matched`。
- 因此本轮不支持“Parquet 需要重建”的结论；更优先指向旧版本 DB metadata row_count stale。

## 8. 测试与验证

已运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_weekly_row_count_reconcile.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/rqdata_weekly_row_count_reconcile.py --products ad ec op --period 1w --output-dir data/reports/ad_ec_op_weekly_row_count_reconcile_20260711
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
git diff --check
```

结果：

- `test_weekly_row_count_reconcile.py`：4 passed。
- CLI：通过，`db_status=available`。
- `test_target_coverage_audit.py`：5 passed。
- `git diff --check`：通过。

## 9. 结论边界

- 本任务完成的是 row_count evidence reconciliation，不是 metadata 修复。
- 本任务不修改 `source_interval`，不处理 provenance metadata column gap。
- 本任务不写 DB，不覆盖旧 row_count，不归档旧 market_data_files。
- 本任务不改变 active 数据入口，不影响回测、信号或 Web 默认读取。

## 10. 下一步建议

1. 若要消除旧版本 `20260707` mismatch，另开受控 metadata 修复 Plan，先决定是更新旧 DB row_count，还是将旧版本记录标记为 superseded/archived。
2. 另开 `source_interval` provenance metadata 修复 Plan，避免与 row_count 任务混做。
3. `missing_db_registration` 与 `quality_failed` 仍需分别按原 gate 处理。
