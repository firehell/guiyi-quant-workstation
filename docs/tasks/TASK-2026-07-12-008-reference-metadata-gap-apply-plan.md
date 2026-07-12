# TASK-2026-07-12-008：Reference Metadata Gap Apply Plan

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-008-reference-metadata-gap-apply-plan |
| 日期 | 2026-07-12 |
| 分支 | `codex/reference-metadata-gap-apply-plan` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/reference-metadata-gap-apply-plan` |
| Base | `codex/residual-data-risk-closeout@7392bce3` |
| 状态 | `DELIVERY_READY_APPLY_PLAN_NO_WRITE` |

## 目标

承接 `TASK-2026-07-12-007` 的 reference metadata gap dry-run 结果，对 831 条 gap 生成后续 metadata-only apply 计划：

1. 将 gap ledger 转成 product/year/dataset 级 apply candidate rows。
2. 将候选按 dataset/year 分批，形成可人工审批的执行顺序。
3. 生成 dry-run/apply 命令清单，但不执行命令。
4. 明确安全边界和人工 Gate：批准前不得调用 RQData 或写 PostgreSQL。

## 输入

- `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`

只接受以下 classification 进入 apply plan：

- `needs_contract_universe_sync`
- `needs_continuous_contract_sync`

## 输出

- `data/reports/reference_metadata_gap_apply_plan_20260712/REFERENCE_METADATA_GAP_APPLY_PLAN.md`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_candidate_rows.csv`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_batches.csv`

## 实现内容

- 新增 `reference_metadata_gap_apply_plan` 服务：
  - 输入 reference gap ledger。
  - 过滤 apply classification。
  - 输出 candidate rows 和 dataset/year batches。
  - 写出 Markdown summary 与 CSV ledger。
- 新增 CLI：
  - `scripts/rqdata_reference_metadata_gap_apply_plan.py`
  - 默认输入 TASK-007 reference metadata gap ledger。
  - 默认输出 TASK-008 apply plan 目录。
- 新增单元测试：
  - 覆盖 classification 过滤。
  - 覆盖 batch 顺序。
  - 覆盖 no-write safety flags。

## 计划结果

- `candidate_rows=831`
- `batch_count=11`
- `needs_contract_universe_sync=285`
- `needs_continuous_contract_sync=546`

批次顺序：

| batch | dataset | year | candidate_rows |
|---|---|---:|---:|
| 1 | contract_universe | 2020 | 67 |
| 2 | contract_universe | 2021 | 69 |
| 3 | contract_universe | 2022 | 71 |
| 4 | contract_universe | 2023 | 78 |
| 5 | continuous_contract_map | 2020 | 67 |
| 6 | continuous_contract_map | 2021 | 69 |
| 7 | continuous_contract_map | 2022 | 71 |
| 8 | continuous_contract_map | 2023 | 78 |
| 9 | continuous_contract_map | 2024 | 81 |
| 10 | continuous_contract_map | 2025 | 90 |
| 11 | continuous_contract_map | 2026 | 90 |

## 安全边界

本任务强制为 no-write apply plan：

- `writes_database=False`
- `writes_parquet=False`
- `writes_manifest=False`
- `calls_rqdata=False`

本任务不执行生成的 dry-run/apply 命令。

后续若人工批准 apply，只允许：

- 写 `futures_contract_universe`。
- 写 `futures_continuous_contract_map`。
- 写相关 task / raw manifest metadata。

后续 apply 仍禁止：

- 写 K 线 Parquet。
- 修改 `market_data_files`。
- 修改 `data_quality_reports`。
- 修改 `quality_status`。
- 修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

## 执行命令

```bash
uv run --project services/quant-api python scripts/rqdata_reference_metadata_gap_apply_plan.py \
  --gap-ledger data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv \
  --output-dir data/reports/reference_metadata_gap_apply_plan_20260712
```

## 测试命令

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_reference_metadata_gap_apply_plan.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply_plan.py \
  scripts/rqdata_reference_metadata_gap_apply_plan.py \
  services/quant-api/tests/test_reference_metadata_gap_apply_plan.py

python -m py_compile \
  services/quant-api/app/services/rqdata_ingest/reference_metadata_gap_apply_plan.py \
  scripts/rqdata_reference_metadata_gap_apply_plan.py

git diff --check
```

## 验收结论

- 831 条 reference metadata gaps 已全部进入候选计划。
- 11 个 dataset/year batch 已生成。
- 报告和命令清单不包含数据库凭据、RQData 凭据、webhook 或 token。
- 本任务未写 DB、未调用 RQData、未改 Parquet/manifest。

## 后续 Gate

若进入真实 metadata-only sync/apply，应另开任务并要求人工明确确认。推荐最小 pilot 是：

1. 先审查 `batch_01_contract_universe_2020`。
2. 只执行 generated dry-run command，不直接 apply。
3. dry-run 通过后，再人工决定是否允许该 batch 的 metadata-only apply。
4. 每个 dataset/year batch 后复跑 `reference_metadata_gap_reconcile` 与 `target_coverage_audit`。
