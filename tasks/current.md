# 当前任务：LPV-ACTUAL-CONTRACT-REGISTRATION-DRY-RUN

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run.md`

分支：`codex/lpv-actual-contract-registration-dry-run`

状态：`DELIVERY_READY_DRY_RUN_NO_DB_WRITE`

## 目标

对 target coverage 中 108 条 `missing_db_registration` 做只读 reconcile，判断是真实 DB 缺口还是审计匹配误报。

## 执行结果

- [x] 新增只读 reconcile service 和 CLI。
- [x] 新增 dry-run 单元测试。
- [x] 修正 actual-contract manifest 中 `l_f/pp_f/v_f` 产品解析。
- [x] 108 target rows 去重为 93 unique paths。
- [x] `already_registered=87`。
- [x] `duplicate_path_versions=6`，仅报告 `L2609F` 六周期历史版本。
- [x] `eligible_for_registration=0`。
- [x] `blocked_metadata_mismatch=0`。
- [x] DB 计数不变：`market_data_files 71098 -> 71098`，`data_quality_reports 65466 -> 65466`。
- [x] target coverage full rerun：`target_catalog_rows=17581`、`covered_passed=17203`、`issue_register_rows=936`、`missing_db_registration=0`。

## 人工 Gate 结论

`eligible_for_registration=0`，因此不需要且不授权 DB 写入。本任务不增加 apply 入口。

## 边界

- 未写 PostgreSQL、Parquet 或 manifest。
- 未调用 RQData。
- 未改 `data_version/data_role/quality_status/checksum`。
- 未删除、合并、归档或修改六条同路径历史版本。
- 未修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

## 测试

- `pytest`：10 passed。
- `ruff check`：All checks passed。
- `py_compile`：通过。
- 真实 dry-run：通过，`database_counts_unchanged=True`。
- target coverage full rerun：通过，`db_snapshot_source=database`，并使用主工程完整 `data/processed` 事实源。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run.md`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_registration_reconcile.py`
- `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
- `scripts/rqdata_actual_contract_registration_reconcile.py`
- `services/quant-api/tests/test_actual_contract_registration_reconcile.py`
- `services/quant-api/tests/test_target_coverage_audit.py`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/registration_reconcile_ledger.csv`
- `data/reports/target_coverage_audit_20260712_after_lpv_reconcile/coverage_summary.md`
