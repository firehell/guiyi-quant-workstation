# 当前任务：SOURCE-INTERVAL-PROVENANCE-REPAIR-APPLY

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-005-source-interval-provenance-repair-apply.md`

分支：`main`

状态：`DELIVERY_READY_APPLY_COMPLETED`

## 目标

将上一阶段 `source_interval_provenance_repair_dry_run` 生成的 276 个 eligible Parquet candidates 进入受控写入：

- 只补派生资产 Parquet 字段：`source_interval=1m`。
- 同步更新 Parquet checksum / file size。
- 同步 manifest checksum。
- 同步已有 processed summary checksum。
- 同步 DB `market_data_files.checksum` / `file_size_bytes`。

## 输入

- `data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv`

## 执行结果

- [x] 扩展受控 apply 服务：
  - `services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py`
- [x] 扩展 CLI：
  - `scripts/rqdata_source_interval_provenance_repair.py`
- [x] 扩展测试：
  - `services/quant-api/tests/test_source_interval_provenance_repair.py`
- [x] 执行 5 文件 pilot apply：
  - `data/reports/source_interval_provenance_repair_apply_pilot_20260712/`
- [x] pilot 后复审：
  - `data/reports/source_interval_provenance_repair_dry_run_after_pilot_20260712/`
  - `data/reports/target_coverage_audit_20260712_after_source_interval_pilot/`
- [x] 执行 full apply：
  - `data/reports/source_interval_provenance_repair_apply_full_20260712/`
- [x] full 后复审：
  - `data/reports/source_interval_provenance_repair_dry_run_after_full_20260712/`
  - `data/reports/target_coverage_audit_20260712_after_source_interval_full/`
- [x] 新增任务单：
  - `docs/tasks/TASK-2026-07-12-005-source-interval-provenance-repair-apply.md`

## 关键结果

Pilot apply：

- selected_candidate_count=5。
- applied_candidate_count=5。
- skipped_candidate_count=0。
- blocked_candidate_count=0。
- `source_interval_unverified`：1039 -> 1019。

Full apply：

- selected_candidate_count=276。
- applied_candidate_count=271。
- skipped_candidate_count=5，即 pilot 已处理的 5 个候选。
- blocked_candidate_count=0。
- writes_database=True。
- writes_parquet=True。
- writes_manifest=True。
- writes_processed_summary=True。
- processed summary updates=61。

Full 后 dry-run 复审：

- `source_interval_status=already_source_interval_1m`：276 files。
- `apply_eligible=False`：276 files。
- manifest checksum：276 matched。
- processed summary checksum：61 matched / 215 not_found。

Full 后 target coverage audit：

- `source_interval_unverified`：1039 -> 0。
- issue_register_rows：2083 -> 1044。
- covered_passed：16164 -> 17203。
- remaining issue types：
  - `missing_continuous_contract_map=546`
  - `missing_contract_universe=285`
  - `missing_db_registration=108`
  - `quality_failed=105`

## 边界

- 本任务未调用 RQData。
- 本任务未新增 Alembic migration 或 schema。
- 本任务未修改 `row_count`、`data_version`、`data_role`、`quality_status`。
- 本任务未补 `missing_db_registration`。
- 本任务未修 `quality_failed`。
- 本任务未处理 reference metadata gaps。
- 本任务未触碰策略、回测、信号、live runtime、scheduler、企业微信或交易执行逻辑。

## 测试与验证

- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：7 passed。
- `python -m py_compile services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py`
  - 结果：通过。
- `uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：All checks passed。
- `uv run --project services/quant-api python scripts/rqdata_source_interval_provenance_repair.py --candidate-files data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv --apply --limit 5 --confirm-source-interval-provenance-repair --output-dir data/reports/source_interval_provenance_repair_apply_pilot_20260712`
  - 结果：5 applied / 0 blocked。
- `uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py --output-dir data/reports/target_coverage_audit_20260712_after_source_interval_pilot`
  - 结果：`source_interval_unverified=1019`，DB snapshot source=`database`。
- `uv run --project services/quant-api python scripts/rqdata_source_interval_provenance_repair.py --candidate-files data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv --apply --confirm-source-interval-provenance-repair --output-dir data/reports/source_interval_provenance_repair_apply_full_20260712`
  - 结果：271 applied / 5 skipped / 0 blocked。
- `uv run --project services/quant-api python scripts/rqdata_source_interval_provenance_repair.py --output-dir data/reports/source_interval_provenance_repair_dry_run_after_full_20260712`
  - 结果：276 files 均为 `already_source_interval_1m`。
- `uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py --output-dir data/reports/target_coverage_audit_20260712_after_source_interval_full`
  - 结果：`source_interval_unverified` 清零，remaining issue_register_rows=1044。

## 下一步

建议下一步不要继续混写数据修复。按剩余 Gate 分开推进：

- `missing_db_registration`：另开 `lpv_actual_contract_registration_dry_run` / 受控 DB 登记任务。
- `quality_failed`：另开只读根因审查，禁止直接改为 passed/warning。
- reference metadata gaps：另开 `missing_continuous_contract_map` / `missing_contract_universe` 只读或受控同步任务。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-005-source-interval-provenance-repair-apply.md`
- `services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py`
- `scripts/rqdata_source_interval_provenance_repair.py`
- `services/quant-api/tests/test_source_interval_provenance_repair.py`
- `data/reports/source_interval_provenance_repair_apply_pilot_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_APPLY.md`
- `data/reports/source_interval_provenance_repair_apply_full_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_APPLY.md`
- `data/reports/source_interval_provenance_repair_dry_run_after_full_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md`
- `data/reports/target_coverage_audit_20260712_after_source_interval_full/coverage_summary.md`
