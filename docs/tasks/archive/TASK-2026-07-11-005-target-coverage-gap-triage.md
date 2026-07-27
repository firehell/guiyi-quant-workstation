# TASK-2026-07-11-005：目标覆盖缺口只读根因收口

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-005-target-coverage-gap-triage |
| Branch | main |
| Status | DELIVERY_READY_READONLY_TRIAGE |
| Source Task | TASK-2026-07-11-002-data-target-coverage-audit |
| Source Report | data/reports/target_coverage_audit_20260711/ |
| Output Report | data/reports/target_coverage_gap_triage_20260711/ |

## 1. 任务类型

数据质量检查 / 目标覆盖矩阵缺口 triage / 只读根因分析

## 2. 背景

`TASK-2026-07-11-002-data-target-coverage-audit` 已在主工程复跑目标覆盖矩阵，报告记录：

- `db_snapshot_source=database`
- `target_asset_catalog.csv`：17689 rows
- `asset_physical_inventory.csv`：15164 rows
- `target_coverage_matrix.csv`：17689 rows
- `metadata_consistency_matrix.csv`：3780 rows
- `issue_register.csv`：2091 rows

主要 issue 为：

| issue_type | count |
|---|---:|
| source_interval_unverified | 1039 |
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| missing_db_registration | 108 |
| quality_failed | 105 |
| row_count_mismatch | 8 |

本任务只对这些 issue 做进一步分类，不修复数据、不登记 DB、不升级质量状态。

## 3. 目标

1. 确认当前任务状态文件不再保留 merge conflict。
2. 对 `source_interval_unverified` 判断是数据损坏还是 provenance metadata 缺口。
3. 对 `row_count_mismatch` 判断是否存在重复 datetime 或周线尾部异常。
4. 对 `missing_db_registration` 产出受控登记候选清单。
5. 对 `quality_failed` 产出只读质量根因入口，不覆盖 failed 状态。
6. 对元数据缺口输出后续 metadata plan 输入。

## 4. 允许修改范围

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/tasks/TASK-2026-07-11-005-target-coverage-gap-triage.md`
- `data/reports/target_coverage_gap_triage_20260711/`

## 5. 禁止修改范围

- 不写 PostgreSQL。
- 不写 raw / processed / canonical Parquet。
- 不修改 manifest 或 checksum。
- 不调用 RQData 下载。
- 不新增 Alembic migration 或 schema。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信。
- 不读取或打印 `.env`、DB/RQData/Webhook 凭据。

## 6. 执行摘要

本任务读取既有目标覆盖审计 CSV，并对本地 Parquet 做只读列检查和 DuckDB 行数检查。

输出：

- `TRIAGE_SUMMARY.md`
- `source_interval_unverified_triage.csv`
- `row_count_mismatch_triage.csv`
- `missing_db_registration_candidates.csv`
- `quality_failed_readonly_triage.csv`
- `metadata_gap_triage.csv`

## 7. 本次根因结论

### source_interval_unverified

- 1039 target rows。
- 276 unique Parquet files。
- 覆盖 `1d/5m/15m/30m/60m` dominant-main 派生目标。
- 所有复核行均为 `source_interval_column_missing`。
- 初步结论：这是派生资产 provenance metadata column gap，不是 OHLCV 行本身损坏的证据。

### row_count_mismatch

- 8 target rows。
- 3 unique weekly dominant-main files。

| symbol | metadata row_count | DuckDB row_count | delta | duplicate datetime |
|---|---:|---:|---:|---:|
| ad.MAIN | 47 | 55 | 8 | 0 |
| ec.MAIN | 134 | 148 | 14 | 0 |
| op.MAIN | 36 | 42 | 6 | 0 |

初步结论：DuckDB 实读行数大于 DB/manifest row_count，且没有重复 datetime；下一步优先核对 DB/manifest row_count 是否旧或不完整。

### missing_db_registration

- 108 target rows。
- `l` 46、`pp` 31、`v` 31。
- 本任务仅输出 candidate-only 清单，不执行 DB 写入。

### quality_failed

- 105 target rows。
- 涉及 `bb.MAIN`、`fb.MAIN`、`jr.MAIN`、`pm.MAIN`、`ri.MAIN`、`rs.MAIN`、`wh.MAIN`、`wr.MAIN`、`zc.MAIN`。
- 保留 failed 状态，不为提高覆盖率改状态。

### metadata gaps

- 831 rows。
- `missing_continuous_contract_map` 546。
- `missing_contract_universe` 285。

## 8. 测试与验证

已运行：

```bash
git diff --check
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
```

结果：

- `git diff --check`：通过。
- `test_target_coverage_audit.py`：5 passed。
- `test_full_universe_active_gate.py`：8 passed。

## 9. 结论边界

- 本任务完成的是只读根因分类，不是数据修复。
- `source_interval_unverified` 不能直接等同于数据损坏。
- `row_count_mismatch` 暂不判断为 Parquet 必须重建，需先核对 DB/manifest row_count。
- `missing_db_registration` 必须另开受控写入 Plan。
- `quality_failed` 必须另开质量报告根因审查。

## 10. 下一步建议

1. 开 `source_interval` provenance metadata 修复 Plan。
2. 开 `ad/ec/op` 周线 row_count 对账任务。
3. 开 `L/PP/V` actual contract 受控 DB 登记 dry-run。
4. 开 `quality_failed` 只读质量报告审查。
