# TASK-2026-07-12-009：Reference Metadata Gap Apply

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-009-reference-metadata-gap-apply |
| 日期 | 2026-07-12 |
| 分支 | `codex/reference-metadata-gap-apply-plan` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/reference-metadata-gap-apply-plan` |
| Base | `TASK-2026-07-12-008-reference-metadata-gap-apply-plan` |
| 状态 | `DELIVERY_READY_STAGE_5B_REFERENCE_METADATA_GAP_CLOSED_QUALITY_WARNING_GATE` |

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
- 已写入/更新：`futures_continuous_contract_map` derived rows。
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
| `continuous_contract_map` direct SDK attempt | 546 | `no_data=546` | 当前 `rqdatac 3.2.5` runtime 不暴露 `futures.get_continuous_contracts`，无法直接获取 `front_month` / `next_month` |
| `continuous_contract_map` derived apply | 546 | `success=546` | `calls_rqdata=False`，不是 RQData SDK 直接接口验收 |

合约池四个批次：

- batch 01 `contract_universe 2020`：67 success，`rows_fetched=152650`。
- batch 02 `contract_universe 2021`：69 success，`rows_fetched=163278`。
- batch 03 `contract_universe 2022`：71 success，`rows_fetched=164609`。
- batch 04 `contract_universe 2023`：78 success。

Derived continuous map apply：

- 546 candidates / 546 success。
- `rows_fetched_sum=234812`。
- `calls_rqdata=False`。
- 该证据只能说明 derived metadata apply 已完成；不能写成 RQData SDK `futures.get_continuous_contracts` 直接接口已通过。

全部 apply ledger 安全列：

- `writes_parquet=False`
- `writes_market_data_files=False`
- `writes_quality_status=False`

## 验证结果

Reference reconcile after full reference metadata apply：

```text
needs_contract_universe_sync=0
needs_continuous_contract_sync=0
partial_year_rows=831
```

Target coverage after full reference metadata apply：

```text
covered_passed=17203
covered_warning=105
not_applicable=273
issue_register_rows=105
issue_type=quality_warning
```

Stage 5-B reference metadata gap 已收口。剩余 105 条 `quality_warning` 是独立后续 Gate，不属于 reference metadata gap 失败项，不得为覆盖率升级为 `passed`。

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
- `data/reports/reference_metadata_gap_apply_derived_continuous_contract_map_20260712/`
- `data/reports/reference_metadata_gap_reconcile_after_contract_universe_apply_20260712/`
- `data/reports/reference_metadata_gap_reconcile_after_continuous_contract_map_derived_20260712/`
- `data/reports/reference_metadata_gap_reconcile_after_reference_metadata_apply_full_20260712/`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_contract_universe_20260712/`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/`

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

Stage 5-B reference metadata gap 可以验收为 closed。后续 Gate 收敛为：

1. 保留 `quality_warning=105` 的消费边界任务，不得改成 passed。
2. Stage 9 前仍需 signal-event、actual-contract、trigger-price、metadata gate 和 notification gate 独立通过。
3. derived continuous map 的生成方法若进入上层消费，必须单独审查；本任务不声明 RQData SDK `get_continuous_contracts` 直接接口已可用。
