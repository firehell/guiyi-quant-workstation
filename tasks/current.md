# 当前任务：REFERENCE-METADATA-GAP-APPLY-PLAN

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-008-reference-metadata-gap-apply-plan.md`

分支：`codex/reference-metadata-gap-apply-plan`

状态：`DELIVERY_READY_APPLY_PLAN_NO_WRITE`

## 目标

承接 `TASK-2026-07-12-007` 的 831 条 reference metadata gaps，只生成 metadata-only 后续 apply 计划与候选命令清单，不执行 RQData 调用，不写 PostgreSQL，不写 Parquet，不改 manifest。

## 执行结果

- [x] 新增 `reference_metadata_gap_apply_plan` service / CLI / tests。
- [x] 输入 `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`。
- [x] 831 条 gap 全部进入 apply candidate rows：
  - `needs_contract_universe_sync=285`。
  - `needs_continuous_contract_sync=546`。
- [x] 生成 11 个 dataset/year 批次：
  - `contract_universe`：2020、2021、2022、2023。
  - `continuous_contract_map`：2020、2021、2022、2023、2024、2025、2026。
- [x] 输出 one product-year command per candidate 的 dry-run/apply 命令列。
- [x] 明确 `writes_database=False`、`writes_parquet=False`、`writes_manifest=False`、`calls_rqdata=False`。
- [x] 明确后续 apply 必须人工 Gate，批准前不得执行生成的 apply 命令。

## 边界

- 本任务没有调用 RQData。
- 本任务没有写 PostgreSQL、Parquet 或 manifest。
- 本任务没有修改 `market_data_files`、`data_quality_reports`、K 线、checksum、`data_version`、`data_role` 或 `quality_status`。
- 本任务没有修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。
- 后续若获批执行，只允许 metadata-only 写入：
  - `futures_contract_universe`。
  - `futures_continuous_contract_map`。
  - 相关 task / raw manifest metadata。

## 输出

- `data/reports/reference_metadata_gap_apply_plan_20260712/REFERENCE_METADATA_GAP_APPLY_PLAN.md`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_candidate_rows.csv`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_batches.csv`

## 测试

- `pytest`：1 passed。
- `ruff check`：All checks passed。
- `py_compile`：通过。
- 真实 apply-plan 生成：通过，`candidate_rows=831`，`batch_count=11`。
- `git diff --check`：通过。
- 报告敏感信息扫描：未发现凭据 URL、token、password、secret、webhook。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-12-008-reference-metadata-gap-apply-plan.md`
- `services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply_plan.py`
- `scripts/rqdata_reference_metadata_gap_apply_plan.py`
- `services/quant-api/tests/test_reference_metadata_gap_apply_plan.py`
- `data/reports/reference_metadata_gap_apply_plan_20260712/REFERENCE_METADATA_GAP_APPLY_PLAN.md`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_candidate_rows.csv`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_batches.csv`
