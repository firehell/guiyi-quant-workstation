# 数据阶段收口审计汇总

生成时间：`2026-07-13T00:36:54.371986+00:00`

## 结论

当前结论：`DATA_LAYER_PARTIAL`。本轮是只读收口审计与文档事实源整理，不代表数据层最终封板完成。

关键边界：`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论；更新的 Phase 3 数据层验收仍显示 manifest/DB 对齐、pre-2020 周线和 actual contract 缺口，因此不得宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。

## 覆盖统计

- covered_passed: `15350`
- covered_warning: `105`
- missing_db_registration: `0`
- metadata_gap: `1853`
- not_applicable: `1943`
- other_status_rows: `0`
- quality_warning: `105`（不升级为 passed）
- duplicate/conflicting rows: `0`

## 周线完整性

- direct 1w present products: `90`
- pre-2020 applicable products: `63`
- pre-2020 covered products: `29`

逐品种明细见 `product_period_coverage.csv`、`contract_role_matrix.csv` 和上游 `weekly_history_audit.csv`。当前不能宣称“全品种周线从上市以来完整”。

## 合约角色

- dominant_main covered_passed rows: `870`
- actual_contract covered_passed rows: `14480`

主连、主力和实际合约仍需以 `contract_role_matrix.csv` 与 `main_contract_mapping_audit.csv` 为准，不得把研究连续合约当成可交易合约。

## 输出文件

- `asset_inventory.csv`
- `product_period_coverage.csv`
- `contract_role_matrix.csv`
- `manifest_db_consistency.csv`
- `duplicate_or_conflicting_assets.csv`
- `document_inventory.csv`
- `data_stage_closure_summary.md`

## 安全声明

- writes_database=False
- writes_parquet=False
- writes_manifest=False
- calls_rqdata=False
- 不涉及策略、回测参数、live scheduler、企业微信或自动交易。
