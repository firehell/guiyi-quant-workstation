# 当前状态

更新时间：2026-07-26

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
JM_EOD_INCREMENTAL_AUTOMATION_READY
HTDY_REALTIME_EXCEPTION_CONTRACT_FROZEN
HTDY_ORIGINAL_PRODUCTION_KERNEL_READY
HTDY_REALTIME_REPAINTING_POLICY_READY
HTDY_REALTIME_15M_SNAPSHOT_READY
HTDY_FIRST_SEEN_CANDIDATE_EVALUATOR_READY
HTDY_FIRST_SEEN_EVENT_WRITER_READY
HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY
NO_SIGNAL_WRITE_PATH_ENABLED
FORMAL_BACKTEST_POLICY_UNCHANGED
OLD_S6_08_AUTHORIZATION_REVOKED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
WEB_V1_READY
WEB_V1_BROWSER_ACCEPTANCE_PASSED
WEB_V1_13_PARTIAL
```

`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已从合入后的主干独立复跑。direct PostgreSQL `READ ONLY` snapshot、真实 Parquet、49 条消费者矩阵和 13 个 Hard Gate 全部通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。report 14、历史消费者记录、行情资产和 live runtime 未修改。通过证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前同名非 rerun 目录继续作为失败历史快照保留。

`FULL_HISTORY_AUDIT_V2_READY` 表示动态矩阵引擎和 direct PostgreSQL 只读审计已可复查；`DATA_LAYER_REAUDIT_REQUIRED` 保留 provider-earliest、TradingCalendar、TradingSession 和全历史资产 residual 的独立治理边界。它不否定已通过的消费者契约，但仍禁止把该结论扩写为“所有全历史资产零 residual”或 live runtime Ready。

阶段 4/5 已完成，S6-03 至 S6-06 既有 Gate 保持不变。S6-07 D1=`2026-07-22` 正常自动归档通过；`2026-07-23` 第二次在线归档作为连续性证据保留；D2=`2026-07-24` 在 scheduler 停机漏跑后由独立调度器自动发现。旧 Runtime 的 1w 聚合失败曾 fail-closed，随后经精确 recovery deployment、service enable 和显式同日 retry 授权恢复；没有手工调用单日 archive CLI。D2 最终生成 7 个 primary/passed 资产（含 1w）、7 行 manifest、8 条 consumer binding，watermark 与 required binding end 均到 `2026-07-24`，四类禁写 counter 增量为 0。最终 create-only receipt 已发布 `JM_EOD_INCREMENTAL_AUTOMATION_READY`；该 Gate 不代表 Runtime 长稳、SignalEvent、通知或自动交易 Ready。

2026-07-26 已完成 HTDY Step 0 合同冻结和旧 S6-08 授权收口。旧
`jm_v1b_daily_direction_fast_entry/v1b.0` schema-v2 packet 文件保留为历史证据，但 Runtime
已是 SignalEvent flag=false、packet/hash 空、autosend=false；只重启 live scheduler 后
Runtime/live/EOD health fresh/ok，受控表计数、Profile hash、EOD watermark 与 DB revision
均无漂移。新目标只冻结为 exact `jm + 当日 rank=1 实际主力 + 15m +
htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting` 观察例外。Step 1 已冻结纯 production
kernel、exact fail-closed policy、Python/Web golden 与 24-horizon/27-zone evidence；schema-v3 Gate、
Runtime、部署、真实事件和通知仍未实现或授权。

同日 Step 2 的纯只读 session-aware 15m snapshot 与 27-bar candidate evaluator 已完成
code/test checkpoint：canonical active-entry Profile 与独立 primary/passed/1m lineage、DCE market wall-clock、
target calendar、strict actual-contract mapping、exact `jm.MAIN` continuous identity、完整
Profile/binding/file provenance、上一 DCE 交易日 warm-up identity、confirmation chronology、immutable
mapping/snapshot hash，以及按 `as_of` 已完成 1m cutoff 重建的 resolver-compatible public ingress
均 fail-closed。JM session geometry 复用单一只读 canonical contract：
`night 21:00–23:00 / day_am_1 09:00–10:15 / day_am_2 10:30–11:30 /
day_pm 13:30–15:00`；15m snapshot 不生成或跨越 10:15–10:30 休市桶，单交易日最多 23 个 live bucket。
candidate/block 本身不写 historical canonical、`StrategySignal`、SignalEvent 或通知。Step 3
另行完成未接 Runtime 的 first-seen writer code/test checkpoint：复用既有 `strategy_signals` 与
`signal_events`，写入 `signal_review_lineage_v2` 冻结首次 snapshot，同桶后续 revision、消失、
反向或重绘均不更新且禁止 `signal_changed`；`signal_notifications` 保持零写入，未新增 migration
或平行通知链。Step 4 schema-v3 Gate、Runtime、真实 PostgreSQL Gate、部署、真实事件、通知与
外部 Gate 仍 pending；这些 checkpoint 不代表盈利、Runtime 或交易 Ready。

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
| JM S6-07 EOD automation | `JM_EOD_INCREMENTAL_AUTOMATION_READY`；D1正常自动归档与D2停机漏跑自动补偿均通过，四类禁写 counter 零增量 | `docs/tasks/JM-EOD-INCREMENTAL-AUTOMATION-S6-07.md`、`data/reports/jm_eod_incremental_automation_s6_07/real_acceptance_20260724_19e6ca31/completion_receipt.json`、Issue #46 |
| Web V1 最终验收 | WEB-V1-12：`WEB_V1_READY / WEB_V1_BROWSER_ACCEPTANCE_PASSED` 历史 Gate 保留；WEB-V1-13：`WEB_V1_13_PARTIAL`，品牌/个人工作台与真实 GET-only Gate 通过，但真实库没有 SignalEvent→ReviewNote 关联样本，未发布新 Personal Workspace Ready | `docs/tasks/WEB-V1-FINAL-ACCEPTANCE.md`、`docs/tasks/WEB-V1-13-FINAL-ACCEPTANCE.md` |
| 业务下一入口 | HTDY Step 3 first-seen writer/lineage v2 code/test checkpoint 已完成；随后完成 Step 4 S6-08 schema-v3 Gate | `HTDY_FIRST_SEEN_EVENT_WRITER_READY / HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY / FORMAL_BACKTEST_POLICY_UNCHANGED`；writer 未接 Runtime，旧 S6-08 已撤权，不代表真实 SignalEvent、通知、Runtime 或长稳 Ready |

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
- `LONG_RUNNING_READY`：需至少 5 个真实交易日长稳和 kill/recovery。
- 真实公网安全 smoke：TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复。
- 阶段 6 JM 主线：S6-03 至 S6-07 已通过。HTDY exact realtime exception 已完成 Step 0 合同冻结、
  Step 1 production kernel/policy/Web golden、Step 2 snapshot/evaluator 及 Step 3 first-seen writer/lineage v2 code/test checkpoint；Step 4 Gate、S6-08 真实事件、S6-09 企业微信单条发送和 S6-10 五交易日长稳仍须
  串行完成各自前置与精确批准。阶段 5 的 HTDY rejection 不得通过实时例外、调参或重跑翻转。

## 非阻塞工作站支持 backlog

- 工作站精简已冻结：仅维护 `scripts/engineering/*` 与安全 Gate；不重建多入口控制面。
- 历史 Demo / 控制面 Issue / PR 清理可由人工按 GitHub 生命周期处理；旧清理建议文档已随文档树清理移除。
- 后续只修真实业务暴露的工程问题。

## 不可宣称

- 不可把 `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 写成全历史数据层验收完成。
- 不可把旧 Phase 3 的 `1853 / 34 / 45` 写成当前确定下载缺口。
- 不可把 `JM_ARCHIVE_PASSED` 扩写为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
- 不可把 `JM_EOD_INCREMENTAL_AUTOMATION_READY` 扩写为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
- 不可把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不可把 `report_id=14` trust audit passed 写成策略盈利或实盘准入。
- 不可把 `REJECTED_RESEARCH_CANDIDATE` 写成阶段 5 工程失败；它表示可信验证管道成功淘汰了当前候选。
