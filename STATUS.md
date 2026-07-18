# 当前状态

更新时间：2026-07-18

## 总体结论

当前阶段是 V1 / V1-B 的可信研究闭环收口。仓库已具备数据中心、K 线工作台、策略回测、报告、复盘、信号事件、企业微信受控单条 smoke、runtime health 和工作站任务控制面的主要代码与文档基础。

但当前数据层最终封板已进入全历史重审状态：

```text
V1_DATA_CONTRACT_FROZEN
FULL_HISTORY_PHYSICAL_INVENTORY_READY
FULL_HISTORY_AUDIT_V2_READY
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
```

`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已从合入后的主干独立复跑。direct PostgreSQL `READ ONLY` snapshot、真实 Parquet、49 条消费者矩阵和 13 个 Hard Gate 全部通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。report 14、历史消费者记录、行情资产和 live runtime 未修改。通过证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前同名非 rerun 目录继续作为失败历史快照保留。

`FULL_HISTORY_AUDIT_V2_READY` 表示动态矩阵引擎和 direct PostgreSQL 只读审计已可复查，不等于数据层 Gate 通过。当前 provider earliest 只有 physical support、TradingCalendar 只到 `2026-07-07`、TradingSession 缺少历史有效期，且 physical/quality/Profile 未全部严格通过，因此仍不能宣称“全历史数据层封板完成”。

阶段 A Gate 已形成一致状态：

```text
V1_DATA_CONTRACT_FROZEN
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

## 当前事实依据

| 事实面 | 当前状态 | 主要证据 |
|---|---|---|
| V1 全历史数据契约 | `V1_DATA_CONTRACT_FROZEN` | `docs/DATA_CENTER.md`、`full_history_contract.py`、纯契约测试 |
| 全历史物理盘点 | `FULL_HISTORY_PHYSICAL_INVENTORY_READY` | `data/reports/full_history_audit_v2_20260710/inventory_summary.json` |
| Audit V2 引擎 | `FULL_HISTORY_AUDIT_V2_READY`；data Gate 仍为 `DATA_LAYER_REAUDIT_REQUIRED` | `audit_v2_summary.json`、`FULL_HISTORY_AUDIT_V2.md` |
| 数据层消费者契约 | `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`；全历史 residual 仍保留 `DATA_LAYER_REAUDIT_REQUIRED` | `tasks/current.md`、`docs/DATA_CENTER.md`、Golden Query rerun |
| 全历史物理数据声明 | `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` | `data/manifests/rqdata_*_v2_history_*.csv`、actual-contract manifests、Profile 配置 |
| 数据部分目标收口 | `DATA-PART-TARGET-CLOSURE DELIVERY_READY` | `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md` |
| JM 六周期 | `primary / passed` | `docs/DATA_CENTER.md`、`data/reports/jm_main_six_period_latest/` |
| 回测可信审计 | `report_id=14 / trust audit passed` | `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| 企业微信 | Stage 9-B2 historical replay single-send smoke | `docs/SIGNAL_EVENTS.md` |
| live runtime | 代码和模板具备，真实 T3/长稳 pending | `docs/tasks/JM-LIVE-GATE-EVIDENCE.md` |
| 工作站控制面 | `WORKBUDDY_V3_CONTROL_PLANE_FIX_MERGED` + `WORKSTATION_NON_BLOCKING_SUPPORT_MODE` | `d54e0198`、`docs/workstation/`、定向 workstation tests |

## 旧 Phase 3 数据口径

以下数字来自 `data/reports/data_layer_final_audit_phase3_20260712/`，现在仅作为旧审计模型下的历史快照保留，不再作为当前确定下载缺口或批量修复清单：

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

当前暂停基于旧 `metadata_gap=1853`、`pre_2020_weekly_missing=34` 和 actual contract 旧固定 gap 的批量修复。B2-01 inventory 与 B2-02 Audit V2 已完成；下一轮只按 V2 gap register 设计只读 residual triage，不直接写 DB 或下载。

## 已具备能力

- V1 全历史 expected start/end、首个完成周、actual rank=1、派生周期、五层状态和 formal consumer 准入纯契约。
- RQData ingest、standard parquet、manifest、checksum、quality report 和 PostgreSQL metadata 登记。
- DuckDB active 读取和 Market K 线展示。
- vn.py 回测、报告、trade/order、equity/drawdown、K 线 marker。
- Stage 13 trust audit，复算 lineage、成本、曲线和指标。
- `packages/quant-core` 中 EMA validated，MACD/ATR draft，火天大有 observation-only。
- `signal_events`、Stage 9 Gate、企业微信 preview、受控发送记录和历史单条 smoke。
- Runtime health API、launchd/frp/nginx 模板和工作站 task dispatcher。
- WorkBuddy 控制面修复已合并到 `main`：GitHub 是事实源，TASK 是执行契约，WorkBuddy 对话和 memory 不是状态源，CodeBuddy 为 compatibility-only。当前为 `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`；Demo 和业务 Pilot 仍是支持轨验收项，但不再阻塞 V1 数据重审。

## 未完成 Gate

- Audit V2 residual triage：解释 90 个 calendar gap、90 个 session historical-scope gap、252 个 physical partial、6 warning 和 21 failed，再决定后续受控任务。
- 全历史 residual triage 仍需按 Audit V2 独立处理；不得把消费者 Ready 扩写为所有历史资产零 residual。
- T3-real：需 JM 可交易时段和用户显式确认 live 表/checkpoint 写入。
- `LONG_RUNNING_READY`：需至少 5 个真实交易日长稳和 kill/recovery。
- 真实公网安全 smoke：TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复。
- OOS / walk-forward：需冻结配置后独立验证，不调参改善收益。

## 非阻塞工作站支持 backlog

- Issue #27 / Draft PR #28 的 WorkBuddy Demo 可继续，但不得成为全历史盘点或 Audit V2 的前置 Gate。
- 已合并的控制面 Issue #29、历史 Demo Issue / PR 只生成关闭或归档建议，由用户人工处理。
- 后续只修复真实业务 Task 可复现暴露的控制面问题；不继续扩展多项目、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟。

## 不可宣称

- 不可把 `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 写成全历史数据层验收完成。
- 不可把旧 Phase 3 的 `1853 / 34 / 45` 写成当前确定下载缺口。
- 不可宣称 `T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY`。
- 不可把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不可把 `report_id=14` trust audit passed 写成策略盈利或实盘准入。
