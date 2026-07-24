# 当前状态

更新时间：2026-07-22

## 工作站模式（并列）

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
POST_FREEZE_REAL_PILOT_PASSED
WORKSTATION_FINAL_CLEANUP_COMPLETE
GITHUB_ISSUE_PR_SINGLE_TASK_LIFECYCLE
CODEX_SINGLE_FORMAL_EXECUTOR
GPT_BROWSER_DESIGN_REVIEW_READY
MOBILE_CODEX_REMOTE_ENTRY_READY
```

工作站控制面已精简为 GitHub + GPT + Codex + 用户。正式工程入口：`scripts/engineering/*`。开发流程见 `docs/DEVELOPMENT.md`。`MOBILE_CODEX_REMOTE_ENTRY_READY` 仅表示手机可作为 Codex 远程入口，不代表无人值守远程自动化。`ENGINEERING_GATES_HARDENED` / `WORKSTATION_REPOSITORY_CLEANED` 表示工程 Gate 与仓库清理已完成。`POST_FREEZE_REAL_PILOT_PASSED` / `WORKSTATION_FINAL_CLEANUP_COMPLETE` 表示 Step 6 Pilot（Issue #43 / PR #44，runtime observation adapter）已合入并通过收尾标记。该工作站状态不替代下列独立业务 Gate；T3/T4 结论分别以真实 receipt 为准。

## 总体结论

当前阶段是 V1 / V1-B Stage 6 的 JM 实时、历史增量、通知与长稳运行前置同步。仓库已具备数据中心、K 线工作台、策略回测、报告、复盘、信号事件、企业微信受控单条 smoke、runtime health 的主要代码与文档基础。

当前已完成的是“可供 Market、Backtest、Signal、Review 使用的严格消费者数据契约”；全历史资产治理仍保留独立再审计清单。因此两个状态必须并列解释，不能互相替代：

```text
V1_DATA_CONTRACT_FROZEN
FULL_HISTORY_PHYSICAL_INVENTORY_READY
FULL_HISTORY_AUDIT_V2_READY
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
CURSOR_CANONICAL_SYNC_PREPARED
INDICATOR_REGISTRY_V1_READY
STRATEGY_INDICATOR_POLICY_READY
HTDY_STRICT_FORMAL_REPORT_READY
INDICATOR_CONTRACT_READY
STRATEGY_VALIDATION_PROTOCOL_FROZEN
STAGE4_COMPLETED
STRATEGY_EVALUATION_PIPELINE_READY
REJECTED_RESEARCH_CANDIDATE
STAGE5_CLOSEOUT_V2_READY
STAGE5_COMPLETED
READY_TO_ENTER_STAGE6
STAGE6_CANONICAL_SYNCED
JM_HISTORICAL_CATCHUP_READY
JM_REFERENCE_METADATA_FRESH
JM_LIVE_TARGET_FRESHNESS_READY
JM_LIVE_CONTEXT_READY
T3_REAL_PASSED
JM_ARCHIVE_PASSED
JM_EOD_AUTOMATION_CODE_COMPLETE
JM_EOD_AUTOMATION_SIMULATION_PASSED
JM_EOD_AUTOMATION_DEPLOYMENT_PASSED
REAL_ACCEPTANCE_BLOCKED_RECOVERY_APPROVAL_PENDING
WEB_V1_READY
WEB_V1_BROWSER_ACCEPTANCE_PASSED
WEB_V1_13_PARTIAL
```

`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已从合入后的主干独立复跑。direct PostgreSQL `READ ONLY` snapshot、真实 Parquet、49 条消费者矩阵和 13 个 Hard Gate 全部通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。report 14、历史消费者记录、行情资产和 live runtime 未修改。通过证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前同名非 rerun 目录继续作为失败历史快照保留。

`FULL_HISTORY_AUDIT_V2_READY` 表示动态矩阵引擎和 direct PostgreSQL 只读审计已可复查；`DATA_LAYER_REAUDIT_REQUIRED` 保留 provider-earliest、TradingCalendar、TradingSession 和全历史资产 residual 的独立治理边界。它不否定已通过的消费者契约，但仍禁止把该结论扩写为“所有全历史资产零 residual”或 live runtime Ready。

阶段 4/5 已完成，S6-03 至 S6-06 既有 Gate保持不变。S6-07 D1=`2026-07-22`正常自动归档已通过，`2026-07-23`第二次在线归档也通过；D2=`2026-07-24`停机补偿被 scheduler自动发现，但旧 Runtime 的 1w 聚合失败后 fail-closed。当前 Runtime仍为 `00668660`且独立 scheduler已禁用；PostgreSQL只读核验为 revision `0022`、checkpoint表缺失，而 D1六资产、七个 active binding与D2失败任务仍完整。恢复代码只允许基于这些不可变证据升级回 `0025`并恢复一个 blocked checkpoint，尚待新代码PR、精确 deployment approval和新 service approval。状态为 `REAL_ACCEPTANCE_BLOCKED_RECOVERY_APPROVAL_PENDING`，未发布 `JM_EOD_INCREMENTAL_AUTOMATION_READY`。

D4-00（`HTDY-SOURCE-XMA-AUDIT-400`）证据位于 `data/reports/indicator_contract_v1/`；任务执行完成且**不再重开**公式审计。original 的最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不得宣称 `HTDY_XMA_SEMANTICS_AUDITED`。

阶段 A Gate 已形成一致状态：

```text
V1_DATA_CONTRACT_FROZEN
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
POST_FREEZE_REAL_PILOT_PASSED
WORKSTATION_FINAL_CLEANUP_COMPLETE
CURSOR_CANONICAL_SYNC_PREPARED
```

## 当前事实依据

| 事实面 | 当前状态 | 主要证据 |
|---|---|---|
| V1 全历史数据契约 | `V1_DATA_CONTRACT_FROZEN` | `docs/DATA_CENTER.md`、`full_history_contract.py`、纯契约测试 |
| 全历史物理盘点 | `FULL_HISTORY_PHYSICAL_INVENTORY_READY` | `data/reports/full_history_audit_v2_20260710/inventory_summary.json` |
| Audit V2 引擎 | `FULL_HISTORY_AUDIT_V2_READY`；data Gate 仍为 `DATA_LAYER_REAUDIT_REQUIRED` | `audit_v2_summary.json`、`FULL_HISTORY_AUDIT_V2.md` |
| 数据层消费者契约 | `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`；全历史 residual 仍保留 `DATA_LAYER_REAUDIT_REQUIRED` | `STATUS.md`、`docs/DATA_CENTER.md`、Golden Query rerun |
| 全历史物理数据声明 | `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` | `data/manifests/rqdata_*_v2_history_*.csv`、actual-contract manifests、Profile 配置 |
| 数据部分目标收口 | `DATA-PART-TARGET-CLOSURE DELIVERY_READY` | `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md` |
| JM 六周期 | `primary / passed` | `docs/DATA_CENTER.md`、`data/reports/jm_main_six_period_latest/` |
| JM S6-03 historical catch-up | provider-final `2026-07-17`；三个 freshness Gate passed | `docs/tasks/JM-HISTORICAL-CATCHUP-S6-03.md` |
| JM S6-04 historical/live context | `JM_LIVE_CONTEXT_READY`；只读 preview、双来源 lineage、冲突 fail-closed | `docs/tasks/JM-LIVE-CONTEXT-S6-04.md` |
| 回测可信审计 | `report_id=14 / trust audit passed` | `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| 企业微信 | Stage 9-B2 historical replay single-send smoke | `docs/SIGNAL_EVENTS.md` |
| live runtime | T3 单次真实 Gate passed；长期 Runtime 与长稳仍 pending | `docs/tasks/JM-LIVE-T3-S6-05.md`、`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` |
| 工作站控制面 | `WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY` + `ENGINEERING_GATES_HARDENED` + `WORKSTATION_REPOSITORY_CLEANED` + `POST_FREEZE_REAL_PILOT_PASSED` + `WORKSTATION_FINAL_CLEANUP_COMPLETE` | `docs/DEVELOPMENT.md`、`scripts/engineering/*`、ADR-WS-002；Pilot：Issue #43 / PR #44 |
| D4-00 HTDY 源码/XMA 审计 | 证据落盘；最终 Gate `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` | `data/reports/indicator_contract_v1/` |
| 阶段 4 指标契约 | `INDICATOR_CONTRACT_READY` / `STAGE4_COMPLETED` | `INDICATOR_CONTRACT_ACCEPTANCE_X406.md`、X4-06 tests |
| 阶段 5 策略验证管道 | `STAGE5_COMPLETED` / `STRATEGY_EVALUATION_PIPELINE_READY`；HTDY 为 `REJECTED_RESEARCH_CANDIDATE` | `STAGE5_ACCEPTANCE_V2.json`、R45-05 final acceptance |
| Stage 6 canonical | `STAGE6_CANONICAL_SYNCED`；主线 Data Continuity → T3 → T4 → EOD → T5 → T6 → T7 | S6-00 文档同步（本地增量合入） |
| JM S6-05 T3 单次真实 live | `T3_REAL_PASSED`；`2026-07-21 / JM2609` 两次 bounded run，live/checkpoint 增量与幂等审计通过 | `data/reports/jm_live_t3_s6_05/main_28d667e6_20260720/t3_receipt.json` |
| JM S6-06 T4 盘后归档 | `JM_ARCHIVE_PASSED`；`2026-07-21 / JM2609` 六资产 `rqdata / primary / passed`、七个 Profile binding、旧资产 immutable、live reference-only reconciliation 和幂等复跑通过 | `data/reports/jm_after_market_archive_s6_06/s606_20260721_115101e3/completion_receipt.json` |
| JM S6-07 EOD automation | `REAL_ACCEPTANCE_BLOCKED_RECOVERY_APPROVAL_PENDING`；D1通过，D2 outage/失败证据完整，DB revision/checkpoint漂移须先受控恢复 | `docs/tasks/JM-EOD-INCREMENTAL-AUTOMATION-S6-07.md`、Issue #46 |
| Web V1 最终验收 | WEB-V1-12：`WEB_V1_READY / WEB_V1_BROWSER_ACCEPTANCE_PASSED` 历史 Gate 保留；WEB-V1-13：`WEB_V1_13_PARTIAL`，品牌/个人工作台与真实 GET-only Gate 通过，但真实库没有 SignalEvent→ReviewNote 关联样本，未发布新 Personal Workspace Ready | `docs/tasks/WEB-V1-FINAL-ACCEPTANCE.md`、`docs/tasks/WEB-V1-13-FINAL-ACCEPTANCE.md` |
| 业务下一入口 | S6-07 正常自动归档日与漏跑补偿验收；最终 Gate 尚未发布 | 不继承 T4 对 Runtime、SignalEvent、通知或自动交易的授权 |

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
- `packages/quant-core` 中 EMA validated；MACD/ATR compatibility-validated 且 formal consumer fail-closed；HTDY original observation-only、strict strategy_candidate/formal historical input。
- `signal_events`、Stage 9 Gate、企业微信 preview、受控发送记录和历史单条 smoke。
- Runtime health API、launchd/frp/nginx 模板；正式工程入口：`scripts/engineering/*`。
- 工作站正式模型：GitHub + GPT + Codex + 用户。旧多入口控制面已退出正式架构。

## 未完成 Gate

- HTDY XMA 语义完整关闭：XMA(6)/VAR23、直接内层与 provenance 仍缺失；保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计。
- Audit V2 residual triage：解释 90 个 calendar gap、90 个 session historical-scope gap、252 个 physical partial、6 warning 和 21 failed，再决定后续受控任务。
- 全历史 residual triage 仍需按 Audit V2 独立处理；不得把消费者 Ready 扩写为所有历史资产零 residual。
- EOD Automation：代码、模拟矩阵、真实 migration、hash-bound 启用和生产 label health 已通过；正常自动归档日与漏跑补偿仍待独立验收。
- `LONG_RUNNING_READY`：需至少 5 个真实交易日长稳和 kill/recovery。
- 真实公网安全 smoke：TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复。
- 阶段 6 JM 主线：S6-03 / S6-04 / S6-05 / S6-06 已通过；下一入口为 EOD Automation。后续 SignalEvent、企业微信单条真实发送和五交易日长稳均需独立 Plan、前置 Gate 与每次真实操作授权。阶段 5 的 HTDY rejection 不得通过调参重跑翻转。

## 非阻塞工作站支持 backlog

- 工作站精简已冻结：仅维护 `scripts/engineering/*` 与安全 Gate；不重建多入口控制面。
- 历史 Demo / 控制面 Issue / PR 清理可由人工按 GitHub 生命周期处理；旧清理建议文档已随文档树清理移除。
- 后续只修真实业务暴露的工程问题。

## 不可宣称

- 不可把 `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 写成全历史数据层验收完成。
- 不可把旧 Phase 3 的 `1853 / 34 / 45` 写成当前确定下载缺口。
- 不可把 `JM_ARCHIVE_PASSED` 扩写为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
- 不可把 S6-07 代码/模拟通过写成 `JM_EOD_INCREMENTAL_AUTOMATION_READY`；该 Gate 只在一个正常自动归档日和一次停机漏跑补偿均通过后发布。
- 不可把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不可把 `report_id=14` trust audit passed 写成策略盈利或实盘准入。
- 不可把 `REJECTED_RESEARCH_CANDIDATE` 写成阶段 5 工程失败；它表示可信验证管道成功淘汰了当前候选。
