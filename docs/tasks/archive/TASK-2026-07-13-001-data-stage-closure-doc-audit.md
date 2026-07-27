# TASK-2026-07-13-001 data stage closure doc audit

生成时间：2026-07-13

状态：`DELIVERY_READY_READONLY_DOC_AUDIT`

## 1. 目标

完成“数据阶段收口审计 + 文档事实源整理”：

- 盘点 Phase 3 数据层验收结果。
- 生成统一收口输出目录。
- 修正 `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 与 `DATA_LAYER_PARTIAL` 的事实源冲突表达。
- 输出可交给浏览器 GPT 审查的 review package。

## 2. 安全边界

本任务只读数据资产：

- `writes_database=False`
- `writes_parquet=False`
- `writes_manifest=False`
- `calls_rqdata=False`

本任务不做：

- 不下载 RQData。
- 不修改 DB schema / Alembic。
- 不修改 quality status。
- 不删除原始数据。
- 不硬删除文档。
- 不改策略、回测参数、live scheduler、企业微信或自动交易。

## 3. 当前结论

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 保留为先前数据部分目标收口结论，但更新后的数据层封板验收以 `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md` 和 `data/reports/data_layer_final_audit_phase3_20260712/` 为准。

## 4. 关键数字

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

105 条 `quality_warning` 保持 warning，不升级为 passed。

## 5. 输出文件

统一输出目录：

```text
data/reports/data_stage_closure/
```

产物：

- `asset_inventory.csv`
- `product_period_coverage.csv`
- `contract_role_matrix.csv`
- `manifest_db_consistency.csv`
- `duplicate_or_conflicting_assets.csv`
- `document_inventory.csv`
- `data_stage_closure_summary.md`
- `final_audit/`

GPT 审查包：

```text
docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md
```

## 6. 本轮复跑记录

命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir /Volumes/扩展盘/guiyi-parallel/data-stage-closure-doc-audit/data/reports/data_stage_closure/final_audit
```

结果：

- `db_snapshot_source=manifest_only`
- PostgreSQL：`fe_sendauth: no password supplied`
- API snapshot：`HTTP Error 502: Bad Gateway`

解释：这是本轮环境 Gate 证据，不作为数据完成度唯一口径。

## 7. 测试记录

已运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_data_stage_closure_audit.py
```

结果：`3 passed`

完整测试结果以最终回复为准。

## 8. 后续建议

1. P0：manifest / DB 对齐专项 Plan，解释或修复 `metadata_gap=1853`。
2. P0：pre-2020 周线 34 品种缺口专项 Plan。
3. P1：actual contract 45 条缺口专项 Plan。
4. P1：人工复核 `document_inventory.csv`，再决定是否归档或删除候选文档。
