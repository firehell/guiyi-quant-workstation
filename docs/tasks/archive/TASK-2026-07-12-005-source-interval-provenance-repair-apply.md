# TASK-2026-07-12-005：source_interval provenance repair apply

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-005-source-interval-provenance-repair-apply |
| Branch | main |
| Status | DELIVERY_READY_APPLY_COMPLETED |
| Input Candidates | data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv |
| Pilot Output | data/reports/source_interval_provenance_repair_apply_pilot_20260712/ |
| Full Output | data/reports/source_interval_provenance_repair_apply_full_20260712/ |

## 1. 任务类型

数据 provenance 受控写入 / Parquet metadata column repair / manifest checksum sync / processed summary checksum sync / PostgreSQL metadata checksum sync。

## 2. 目标

对 dry-run 阶段确认的 276 个 eligible Parquet candidates 补充 `source_interval=1m`，并同步更新 checksum/file size 相关证据。

## 3. 本次变更

- 扩展服务：`services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py`。
- 扩展 CLI：`scripts/rqdata_source_interval_provenance_repair.py`。
- 扩展测试：`services/quant-api/tests/test_source_interval_provenance_repair.py`。
- 新增 pilot/full apply 报告、post-apply dry-run 报告和 post-apply target coverage audit 报告。

## 4. 写入范围

本任务允许写入：

- 276 个 canonical Parquet：新增 `source_interval=1m`。
- 对应 manifest：更新 checksum，若字段存在则更新 file size。
- 已存在的 processed summary：更新 checksum，若字段存在则更新 file size。
- DB `market_data_files`：按 id/file_path/row_count/checksum/file_size/data_role/quality_status 条件更新 `checksum` 和 `file_size_bytes`。

本任务禁止写入：

- RQData 下载。
- Alembic migration / schema。
- `row_count`、`data_version`、`data_role`、`quality_status`。
- `missing_db_registration`。
- `quality_failed`。
- reference metadata gaps。
- 策略、回测、信号、live runtime、scheduler、企业微信和交易执行逻辑。

## 5. 执行结果

Pilot apply：

| 指标 | 结果 |
|---|---:|
| selected_candidate_count | 5 |
| applied_candidate_count | 5 |
| skipped_candidate_count | 0 |
| blocked_candidate_count | 0 |

Pilot 后 target coverage：

| issue_type | before | after |
|---|---:|---:|
| source_interval_unverified | 1039 | 1019 |

Full apply：

| 指标 | 结果 |
|---|---:|
| selected_candidate_count | 276 |
| applied_candidate_count | 271 |
| skipped_candidate_count | 5 |
| blocked_candidate_count | 0 |
| processed_summary_updates | 61 |

Full 后 dry-run：

| status | count |
|---|---:|
| already_source_interval_1m | 276 |

Full 后 target coverage：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| missing_db_registration | 108 |
| quality_failed | 105 |

`source_interval_unverified` 已清零。

## 6. 关键报告

- `data/reports/source_interval_provenance_repair_apply_pilot_20260712/source_interval_apply_ledger.csv`
- `data/reports/source_interval_provenance_repair_apply_full_20260712/source_interval_apply_ledger.csv`
- `data/reports/source_interval_provenance_repair_dry_run_after_full_20260712/candidate_files.csv`
- `data/reports/target_coverage_audit_20260712_after_source_interval_full/coverage_summary.md`
- `data/reports/target_coverage_audit_20260712_after_source_interval_full/issue_register.csv`

## 7. 测试与验证

- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：7 passed。
- `python -m py_compile services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py`
  - 结果：通过。
- `uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：All checks passed。
- Pilot apply：
  - 结果：5 applied / 0 blocked。
- Pilot 后 target coverage：
  - 结果：`source_interval_unverified=1019`。
- Full apply：
  - 结果：271 applied / 5 skipped / 0 blocked。
- Full 后 dry-run：
  - 结果：276 files 均为 `already_source_interval_1m`。
- Full 后 target coverage：
  - 结果：`source_interval_unverified=0`，issue_register_rows=1044。

## 8. 后续 Gate

下一步不要继续在本任务中混写其他数据修复：

- `missing_db_registration` 进入独立受控 DB 登记任务。
- `quality_failed` 进入只读根因审查。
- `missing_continuous_contract_map` / `missing_contract_universe` 进入 reference metadata gap 任务。
