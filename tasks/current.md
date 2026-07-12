# 当前任务：REFERENCE-METADATA-GAP-APPLY

生成时间：2026-07-12

任务单：`docs/tasks/TASK-2026-07-12-009-reference-metadata-gap-apply.md`

分支：`codex/reference-metadata-gap-apply-plan`

状态：`PARTIAL_DELIVERY_CONTRACT_UNIVERSE_APPLIED_CONTINUOUS_BLOCKED`

## 目标

承接 `TASK-2026-07-12-008` 的 831 条 reference metadata apply candidates，执行 Stage 5-B metadata-only apply，目标是补齐：

- `futures_contract_universe`：285 条 product/year gap。
- `futures_continuous_contract_map`：546 条 product/year gap。

## 执行结果

- [x] 新增 metadata-only apply runner：
  - `services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py`
  - `scripts/rqdata_reference_metadata_gap_apply.py`
  - `services/quant-api/tests/test_reference_metadata_gap_apply.py`
- [x] 默认 dry-run / no-write；真实写入必须显式传入 `--apply --confirm-metadata-only`。
- [x] dry-run smoke：`candidate_count=2`，`planned=2`，未调用 RQData，未写 DB。
- [x] full dry-run：`candidate_count=831`，`planned=831`，未调用 RQData，未写 DB。
- [x] pilot apply：`batch_01_contract_universe_2020 --limit 1` 成功，`a/2020` 从 0 行写入 1458 行。
- [x] `contract_universe` 四个批次全部完成：
  - 2020：67 success。
  - 2021：69 success。
  - 2022：71 success。
  - 2023：78 success。
- [x] 合约池 apply 合计：285 candidates / 285 success / `rows_fetched_sum=652928`。
- [x] `continuous_contract_map` 七个批次已尝试，但全部为 `no_data`：
  - 当前 `rqdatac 3.2.5` runtime 不暴露文档要求的 `futures.get_continuous_contracts`。
  - 不得用 `get_dominant` 或主力映射硬替代 `front_month` / `next_month`。
- [x] 修正 runner 防误报：0 行 apply 且 DB row count 未变化时标记 `no_data`，不再误报 `success`。

## 当前验收状态

Reference reconcile：

```text
needs_contract_universe_sync=0
needs_continuous_contract_sync=546
partial_year_rows=285
```

Target coverage：

```text
covered_passed=17203
covered_warning=105
metadata_gap=546
missing_continuous_contract_map=546
quality_warning=105
missing_contract_universe=0
```

## 安全边界

- 本任务写入了 PostgreSQL reference metadata 表 `futures_contract_universe`。
- 本任务没有写 K 线 Parquet。
- 本任务没有写 `market_data_files`。
- 本任务没有写 `data_quality_reports`。
- 本任务没有修改 `quality_status`。
- 本任务没有修改策略、回测、信号、Review、live runtime、scheduler、企业微信或交易执行。
- 本任务没有打印或写入 RQData 凭据、webhook、token、password、secret。

## 关键报告

- `data/reports/reference_metadata_gap_apply_dry_run_20260712/`
- `data/reports/reference_metadata_gap_apply_pilot_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_01_contract_universe_2020_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_02_contract_universe_2021_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_03_contract_universe_2022_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_04_contract_universe_2023_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_05_continuous_contract_map_2020_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_06_continuous_contract_map_2021_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_07_continuous_contract_map_2022_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_08_continuous_contract_map_2023_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_09_continuous_contract_map_2024_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_10_continuous_contract_map_2025_20260712/`
- `data/reports/reference_metadata_gap_apply_batch_11_continuous_contract_map_2026_20260712/`
- `data/reports/reference_metadata_gap_reconcile_after_contract_universe_apply_20260712/`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_contract_universe_20260712/`

## 测试

- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_reference_metadata_gap_apply.py`：4 passed。
- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_reference_metadata_gap_apply.py services/quant-api/tests/test_reference_metadata_gap_apply_plan.py`：5 passed。
- `uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py scripts/rqdata_reference_metadata_gap_apply.py services/quant-api/tests/test_reference_metadata_gap_apply.py`：All checks passed。
- `python -m py_compile services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py scripts/rqdata_reference_metadata_gap_apply.py`：通过。
- `git diff --check`：通过。

## 当前阻塞

Stage 5-B 未完全完成，阻塞项是：

```text
missing_continuous_contract_map=546
```

根因：

- 本地 `rqdatac 3.2.5` 的 `rqdatac.futures` 只有 `get_contracts`、`get_dominant`、`get_dominant_price`、`get_contract_multiplier`。
- 文档要求的 `futures.get_continuous_contracts(underlying_symbol, start_date, end_date, type='front_month')` 在当前 runtime 不存在。
- `get_dominant` 返回主力/次主力，不等价于近月/次月连续合约，不能用作 fallback。

## 下一步

1. 先确认 RQData SDK/API 能否提供 `futures.get_continuous_contracts`。
2. 若可用，重跑 `continuous_contract_map` 7 个批次并复跑 target coverage。
3. 若不可用，进入 Stage 6-A 时必须把 `continuous_contract_map` 标为明确 unavailable，不允许各上层模块自建 fallback。
4. 另开任务处理 105 条 `quality_warning` 的消费边界。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-12-009-reference-metadata-gap-apply.md`
- `docs/DATA_CENTER.md`
- `docs/gpt/CURRENT_STATE.md`
- `services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py`
- `scripts/rqdata_reference_metadata_gap_apply.py`
- `services/quant-api/tests/test_reference_metadata_gap_apply.py`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_contract_universe_20260712/coverage_summary.md`
- `data/reports/reference_metadata_gap_reconcile_after_contract_universe_apply_20260712/REFERENCE_METADATA_GAP_RECONCILE.md`
