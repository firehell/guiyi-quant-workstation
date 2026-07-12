# 当前任务：RESIDUAL-DATA-RISK-CLOSEOUT-DRY-RUN

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-007-residual-data-risk-closeout-dry-run.md`

分支：`codex/residual-data-risk-closeout`

状态：`DELIVERY_READY_DRY_RUN_NO_WRITE`

## 目标

对 `TASK-006` 后剩余的数据风险做只读收口：`quality_failed` 根因、`L2609F` 同路径多版本、reference metadata gaps。

## 执行结果

- [x] 新增 `quality_failed_root_cause_audit` dry-run service / CLI / tests。
- [x] 新增 `duplicate_path_version_reconcile` dry-run service / CLI / tests。
- [x] 新增 `reference_metadata_gap_reconcile` dry-run service / CLI / tests。
- [x] 修正 `target_coverage_audit` 质量状态合并口径：DB/manifest 当前 active 状态优先，processed summary 只做辅助证据。
- [x] 105 条 `quality_failed` 去重为 15 个唯一文件。
- [x] 15 个文件全部为 `stale_processed_summary_failed`，当前 DB/manifest/quality report 均为 `warning`。
- [x] `L2609F` 六周期同路径多版本全部输出 current/superseded 对照，未做 DB 修改。
- [x] 831 条 reference metadata gaps 输出候选清单：`needs_contract_universe_sync=285`、`needs_continuous_contract_sync=546`。
- [x] target coverage full rerun：`quality_failed=0`，`quality_warning=105`，`missing_db_registration=0`。

## 边界

- 未写 PostgreSQL、Parquet 或 manifest。
- 未调用 RQData。
- 未改 `data_version/data_role/quality_status/checksum`。
- 未删除、合并、归档或修改 `L2609F` 历史重复版本。
- 未修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

## 测试

- `pytest`：10 passed。
- `ruff check`：All checks passed。
- `py_compile`：通过。
- 真实 dry-run：三份 reconcile 均通过，DB 计数不变。
- target coverage full rerun：通过，`db_snapshot_source=database`，使用主工程完整数据根。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-007-residual-data-risk-closeout-dry-run.md`
- `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
- `services/quant-api/app/services/rqdata_ingest/quality_failed_root_cause_audit.py`
- `services/quant-api/app/services/rqdata_ingest/duplicate_path_version_reconcile.py`
- `services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_reconcile.py`
- `scripts/rqdata_quality_failed_root_cause_audit.py`
- `scripts/rqdata_duplicate_path_version_reconcile.py`
- `scripts/rqdata_reference_metadata_gap_reconcile.py`
- `scripts/rqdata_target_coverage_audit.py`
- `services/quant-api/tests/test_target_coverage_audit.py`
- `services/quant-api/tests/test_quality_failed_root_cause_audit.py`
- `services/quant-api/tests/test_duplicate_path_version_reconcile.py`
- `services/quant-api/tests/test_reference_metadata_gap_reconcile.py`
- `data/reports/quality_failed_root_cause_audit_20260712/QUALITY_FAILED_ROOT_CAUSE_AUDIT.md`
- `data/reports/quality_failed_root_cause_audit_20260712/quality_failed_root_cause_ledger.csv`
- `data/reports/duplicate_path_version_reconcile_20260712/DUPLICATE_PATH_VERSION_RECONCILE.md`
- `data/reports/duplicate_path_version_reconcile_20260712/duplicate_path_version_ledger.csv`
- `data/reports/reference_metadata_gap_reconcile_20260712/REFERENCE_METADATA_GAP_RECONCILE.md`
- `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`
- `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_sync_commands.csv`
- `data/reports/target_coverage_audit_20260712_after_residual_closeout/coverage_summary.md`
- `data/reports/target_coverage_audit_20260712_after_residual_closeout/issue_register.csv`
