# TASK-2026-07-12-009：Reference Metadata Gap Apply

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-009-reference-metadata-gap-apply |
| 日期 | 2026-07-12 |
| 分支 | `codex/reference-metadata-gap-apply-plan` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/reference-metadata-gap-apply-plan` |
| Base | `TASK-2026-07-12-008-reference-metadata-gap-apply-plan` |
| 状态 | `PARTIAL_DELIVERY_CONTRACT_UNIVERSE_APPLIED_CONTINUOUS_BLOCKED` |

## 目标

承接 TASK-008 的 831 条 reference metadata apply candidates，执行 Stage 5-B metadata-only apply：

- 补齐 `futures_contract_universe`。
- 尝试补齐 `futures_continuous_contract_map`。
- 每批生成 apply ledger。
- 每批保留 rows before/after 与安全列。
- 复跑 reference metadata gap reconcile 与 target coverage audit。

## 安全边界

本任务只允许写 reference metadata 表：

- 允许：`futures_contract_universe`。
- 尝试但未写入有效行：`futures_continuous_contract_map`。
- 禁止：K 线 Parquet、raw/canonical bar 文件、`market_data_files`、`data_quality_reports`、`quality_status`、策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

新增 apply runner 默认 no-write；真实 apply 必须同时传入：

```bash
--apply --confirm-metadata-only
```

## 实现内容

- 新增 `scripts/rqdata_reference_metadata_gap_apply.py`。
- 新增 `services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py`。
- 新增 `services/quant-api/tests/test_reference_metadata_gap_apply.py`。
- 修正 runner 状态判定：apply 返回 0 行且 DB row count 未变化时，必须标记为 `no_data`，不能误报 `success`。

## Apply 结果

| dataset | candidates | result | 说明 |
|---|---:|---|---|
| `contract_universe` | 285 | `success=285` | 已写入/更新 `futures_contract_universe` |
| `continuous_contract_map` | 546 | `no_data=546` | 当前 `rqdatac 3.2.5` runtime 不暴露 `futures.get_continuous_contracts`，无法获取 `front_month` / `next_month` |

合约池四个批次：

- batch 01 `contract_universe 2020`：67 success，`rows_fetched=152650`。
- batch 02 `contract_universe 2021`：69 success，`rows_fetched=163278`。
- batch 03 `contract_universe 2022`：71 success，`rows_fetched=164609`。
- batch 04 `contract_universe 2023`：78 success。

全部 apply ledger 安全列：

- `writes_parquet=False`
- `writes_market_data_files=False`
- `writes_quality_status=False`

## 验证结果

Reference reconcile after contract universe apply：

```text
needs_contract_universe_sync=0
needs_continuous_contract_sync=546
partial_year_rows=285
```

Target coverage after contract universe apply：

```text
covered_passed=17203
covered_warning=105
metadata_gap=546
missing_continuous_contract_map=546
quality_warning=105
missing_contract_universe=0
```

`missing_contract_universe` 已从 285 清零。`missing_continuous_contract_map` 未完成，阻塞原因是本地 RQData SDK runtime 缺少文档要求接口；不得用 `get_dominant` 或主力映射硬替代近月/次月连续合约。

## 关键证据

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

## 测试命令

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_reference_metadata_gap_apply.py \
  services/quant-api/tests/test_reference_metadata_gap_apply_plan.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py \
  scripts/rqdata_reference_metadata_gap_apply.py \
  services/quant-api/tests/test_reference_metadata_gap_apply.py

python -m py_compile \
  services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply.py \
  scripts/rqdata_reference_metadata_gap_apply.py
```

## 后续 Gate

下一步不能直接进入 Stage 6 全量统一访问契约的最终实现。必须先处理 continuous map 外部 API gate：

1. 确认 RQData SDK 是否需要升级或启用包含 `futures.get_continuous_contracts` 的版本。
2. 若不能获取 `front_month` / `next_month`，则调整 Stage 6 契约，将 `continuous_contract_map` 标为 unavailable，不能 fallback 到 `get_dominant`。
3. 保留 `quality_warning=105` 的消费边界任务，不得改成 passed。
