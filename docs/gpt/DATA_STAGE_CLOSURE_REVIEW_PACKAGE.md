# DATA STAGE CLOSURE REVIEW PACKAGE

生成时间：2026-07-13

用途：交给浏览器 GPT 做数据阶段收口审查和下一步任务规划。

## 1. 审查结论

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

本轮不是数据修复任务，而是只读审计与文档事实源整理。

## 2. 事实源优先级

本轮以以下文件为准：

1. `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`
2. `data/reports/data_layer_final_audit_phase3_20260712/`
3. `data/reports/data_stage_closure/data_stage_closure_summary.md`
4. `data/reports/data_stage_closure/*.csv`
5. `docs/DATA_CENTER.md`
6. `tasks/current.md`

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 保留为先前数据部分目标收口结论，但不能覆盖更新后的 `DATA_LAYER_PARTIAL` 封板验收结论。

## 3. 核心数字

Phase 3 DB 口径：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

本轮 `scripts/rqdata_data_layer_final_audit.py` 复跑降级为 `manifest_only`：

- PostgreSQL 缺密码：`fe_sendauth: no password supplied`
- API snapshot：`HTTP Error 502: Bad Gateway`
- 输出：`data/reports/data_stage_closure/final_audit/`

该复跑结果是环境 Gate 证据，不作为数据完成度唯一口径。

## 4. 新增或更新产物

- `scripts/data_stage_closure_audit.py`
- `services/quant-api/app/services/rqdata_ingest/data_stage_closure.py`
- `services/quant-api/tests/test_data_stage_closure_audit.py`
- `data/reports/data_stage_closure/asset_inventory.csv`
- `data/reports/data_stage_closure/product_period_coverage.csv`
- `data/reports/data_stage_closure/contract_role_matrix.csv`
- `data/reports/data_stage_closure/manifest_db_consistency.csv`
- `data/reports/data_stage_closure/duplicate_or_conflicting_assets.csv`
- `data/reports/data_stage_closure/document_inventory.csv`
- `data/reports/data_stage_closure/data_stage_closure_summary.md`
- `docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`

## 5. 不可升级的结论

请审查时特别避免以下误读：

- 不能宣称“全品种周线从上市以来完整”。
- 不能宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- 不能把 105 条 `quality_warning` 升级为 passed。
- 不能把本轮 `manifest_only` 复跑当成 DB 口径完成度证明。
- 不能由数据审计推导策略有效、模拟盘准入、实盘准入或企业微信发送授权。

## 6. 建议 GPT 审查问题

1. `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 与 `DATA_LAYER_PARTIAL` 的文档表达是否足够清楚？
2. `metadata_gap=1853` 是否应拆成 manifest 窗口更新、processed summary 对齐和 DB re-register 三个后续任务？
3. pre-2020 周线 34 品种缺口是否应先定义 `effective_listed=max(listed_date, 2000-01-04)` 口径，再决定补数据？
4. actual contract 45 条缺口是否应先按 `main_contract_mapping_audit.csv` 做只读分类？
5. `document_inventory.csv` 中的 `delete_candidate` 是否只做人工复核，不进入自动删除？

## 7. 建议下一步任务

P0：

- manifest / DB 对齐专项 Plan。
- pre-2020 周线 34 品种缺口专项 Plan。

P1：

- actual contract 45 条缺口专项 Plan。
- 文档清理人工复核。

P2：

- 如果上述数据封板补齐完成，再重新评估 Market / Backtest / Signal / Review 的 READY Gate。
