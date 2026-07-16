# 当前状态

更新时间：2026-07-16

## 总体结论

当前阶段是 V1 / V1-B 的可信研究闭环收口。仓库已具备数据中心、K 线工作台、策略回测、报告、复盘、信号事件、企业微信受控单条 smoke、runtime health 和工作站任务控制面的主要代码与文档基础。

但当前数据层最终封板仍是：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

不能宣称“全品种周线从上市以来完整”，不能宣称长期 live runtime ready，不能宣称企业微信自动长期发送 ready。

## 当前事实依据

| 事实面 | 当前状态 | 主要证据 |
|---|---|---|
| 数据层最终封板 | `DATA_LAYER_PARTIAL` | `tasks/current.md`、`docs/DATA_CENTER.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md` |
| 数据部分目标收口 | `DATA-PART-TARGET-CLOSURE DELIVERY_READY` | `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md` |
| JM 六周期 | `primary / passed` | `docs/DATA_CENTER.md`、`data/reports/jm_main_six_period_latest/` |
| 回测可信审计 | `report_id=14 / trust audit passed` | `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| 企业微信 | Stage 9-B2 historical replay single-send smoke | `docs/SIGNAL_EVENTS.md` |
| live runtime | 代码和模板具备，真实 T3/长稳 pending | `docs/tasks/JM-LIVE-GATE-EVIDENCE.md` |
| 工作站控制面 | `WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING`，业务 Gate 不变 | `docs/workstation/WORKSTATION_UPGRADE_ACCEPTANCE.md`、`docs/workstation/` |

## Phase 3 数据口径

当前数据层最终验收采用 Phase 3 DB 口径：

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

## 已具备能力

- RQData ingest、standard parquet、manifest、checksum、quality report 和 PostgreSQL metadata 登记。
- DuckDB active 读取和 Market K 线展示。
- vn.py 回测、报告、trade/order、equity/drawdown、K 线 marker。
- Stage 13 trust audit，复算 lineage、成本、曲线和指标。
- `packages/quant-core` 中 EMA validated，MACD/ATR draft，火天大有 observation-only。
- `signal_events`、Stage 9 Gate、企业微信 preview、受控发送记录和历史单条 smoke。
- Runtime health API、launchd/frp/nginx 模板和工作站 task dispatcher。
- WorkBuddy Unified V3 canonical / Skill / facade 已完成 Demo 前代码与文档收敛：GitHub 是事实源，TASK 是执行契约，WorkBuddy 对话和 memory 不是状态源，CodeBuddy 为 compatibility-only。当前状态为 `WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING`，仍需 Demo 和业务 Pilot 后才能 FROZEN。

## 未完成 Gate

- manifest / DB 对齐专项：解释或修复 `metadata_gap=1853`。
- pre-2020 周线 34 品种缺口专项：逐品种判定补数据或 N/A。
- actual contract 缺口专项：逐条判定补 bars、标记 N/A 或等待 mapping 修复。
- T3-real：需 JM 可交易时段和用户显式确认 live 表/checkpoint 写入。
- `LONG_RUNNING_READY`：需至少 5 个真实交易日长稳和 kill/recovery。
- 真实公网安全 smoke：TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复。
- OOS / walk-forward：需冻结配置后独立验证，不调参改善收益。

## 不可宣称

- 不可宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- 不可宣称全品种周线从上市以来完整。
- 不可宣称 `T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY`。
- 不可把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不可把 `report_id=14` trust audit passed 写成策略盈利或实盘准入。
