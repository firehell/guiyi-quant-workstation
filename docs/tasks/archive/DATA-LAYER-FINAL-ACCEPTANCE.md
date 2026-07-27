# DATA LAYER FINAL ACCEPTANCE

生成时间：2026-07-12

## 最终状态

```text
DATA_LAYER_PARTIAL
```

Phase 2 受控补齐与 Phase 3 验收已执行，但 manifest/DB 对齐与部分历史周线仍未达到 READY Gate。

## Phase 2 执行摘要

| Step | 结果 |
|---|---|
| 2A duplicate active supersede | `2559+72+2570` 行标记 `superseded`；`duplicate_active_rows=0` |
| 2A re-elect widest primary | 修正 end_time 相同时误选窄窗口；按 `end_time↓, start_time↑` 重选 winner |
| 2B orphan register | 8/8 登记完成；warning 品种保持 `quality_status=warning` |
| 2C weekly pre-2020 | 63 品种 RQData prepend+register 完成 |

证据目录：

- `data/reports/data_layer_phase2_supersede_20260712/`
- `data/reports/data_layer_phase2_orphan_register_20260712/`
- `data/reports/data_layer_phase2_weekly_pre2020_20260712/`
- `data/reports/data_layer_phase2_supersede_reelect_20260712/`

## Phase 3 审计 Gate（`data/reports/data_layer_final_audit_phase3_20260712/`）

| Gate | 目标 | 实际 | 通过 |
|---|---|---|:---:|
| duplicate active | 0 | 0 | Y |
| orphan files | 0 | 0 | Y |
| weekly direct present | 90/90 | 90/90 | Y |
| pre-2020 weekly | 63/63 | 29/63 | N |
| 1m 架构口径 2023+ | confirmed | rejected (metadata_gap) | N |
| 1d 2020+ | confirmed | partial 491/546 | N |
| 1w 2020+ | confirmed | partial 70/90 | N |
| dominant main | 90/90 | 0/90 | N |
| actual contract | 1244/1244 | 1199/1244 | N |
| quality_warning 边界 | 105 不升级 | 105 `covered_warning` | Y |
| JM 六周期 | active_passed | audit_pending（manifest 漂移） | N |

## 剩余问题与影响

1. **manifest / processed summary 与 re-elect 后 primary 路径漂移**（`metadata_gap=1853`）
   - 影响：target coverage / Stage 8.6 矩阵统计；不影响 `MarketDataReader` 直接读 DB primary 路径。
   - 下一步：受控 manifest 窗口更新或 dominant_v2 全量 re-register 对齐任务。

2. **pre-2020 周线 34 品种仍缺**（含 RQData `2000-01-04` 下限前上市品种）
   - 影响：claim_4 不能 confirmed。
   - 下一步：文档化 RQData 下限例外，或接受 `effective_listed=max(listed, 2000-01-04)` 口径（审计器已部分采用）。

3. **actual contract 45 条缺口**（1244→1199）
   - 影响：主力映射审计、Stage 9 全品种准入。
   - 下一步：按 `main_contract_mapping_audit.csv` 逐条补 bars 或标记 N/A。

## 上层读取回归

- `MarketDataReader` / `market_workbench` / Backtest / Signal / Review / live evaluator 仍走统一 active 规则。
- 新增 `test_data_layer_consumer_consistency.py`：Market 与 Reader 对同一 fixture 返回相同 `data_version`。

## 测试清单

| 命令 | 结果 |
|---|---|
| Phase 3 专项 pytest（17 文件） | **76 passed** |
| 后端全量 `pytest services/quant-api/tests/` | **486 passed, 2 skipped** |
| `ruff check`（本任务新增文件） | passed |
| `git diff --check` | passed |
| `make workstation-test` | 未跑（main 上 strict doctor 已知非阻断） |
| `apps/quant-web npm run build` | **失败**（`chart.vue` / `market.ts` 既有 TS 错误，非本任务引入） |
| `npm run test:indicators` | passed |

详细日志：`.ai/results/TASK-2026-07-12-026/test_report.md`

## 不代表

- 策略盈利、自动交易、live 长稳、企业微信、云/Mac mini 验收。

## 任务文档

- [TASK-2026-07-12-025](TASK-2026-07-12-025-data-layer-phase2-remediation.md)
- [TASK-2026-07-12-026](TASK-2026-07-12-026-data-layer-phase3-final-acceptance.md)
