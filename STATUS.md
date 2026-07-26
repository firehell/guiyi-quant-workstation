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

2026-07-26 只读事故审计确认：destructive migration test 曾误用普通 `DATABASE_URL`，把生产
PostgreSQL 从 `0025` 降到 `0022`。schema 后续已被外部 code-only 流程恢复到 `0025`，但 7 条
历史 Profile binding、S6-07 scheduler checkpoint 和部分 0023/0024 lineage 原始字段尚未完整
恢复。迁移测试现已改为只接受数据库名及 OID 均与 Runtime 不同的显式隔离数据库。对无法证明的
审计字段采用用户批准且逐字段声明的 semantic-reconstruction 合同；database-only logical
backup、真实 Docker 隔离恢复和精确 Approval R 已完成。当前 PostgreSQL 保持 `0025`，
`profile_active_bindings=5131`、S6-07 checkpoint=1；禁止表、report 14、task 23/report 15 与
active Profile hash 零漂移。Recovery receipt hash 为
`3d916810629a34f48cbdd488e6ace7ac5954fa16089362284d85db790f07f75d`，原 Approval R 已消费。
详见 `docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md`。

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
HTDY_S6_08_SCHEMA_V3_GATE_READY
HTDY_STEP5_PREFLIGHT_CODE_READY
NO_SIGNAL_WRITE_PATH_ENABLED
FORMAL_BACKTEST_POLICY_UNCHANGED
OLD_S6_08_AUTHORIZATION_REVOKED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
WEB_V1_READY
WEB_V1_BROWSER_ACCEPTANCE_PASSED
WEB_V1_13_PARTIAL
WEB_V1_RESEARCH_WORKSPACE_POLISHED
WEB_V1_MARKET_QUALITY_EXPLAINED
WEB_V1_CONTROL_CONTRAST_READY
WEB_V1_READONLY_ACCEPTANCE_PASSED
WEB_HTDY_FIRST_SEEN_PRESENTATION_READY
WEB_HTDY_LINEAGE_V2_COMPATIBLE
HTDY_OBSERVATION_ONLY_PRESENTATION_PRESERVED
WEB_HTDY_INTEGRATED_ACCEPTANCE_PASSED
NO_WEB_OR_HTDY_SEMANTIC_REGRESSION
NO_MARKET_SEMANTIC_REGRESSION
```

`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已从合入后的主干独立复跑。direct PostgreSQL `READ ONLY` snapshot、真实 Parquet、49 条消费者矩阵和 13 个 Hard Gate 全部通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。report 14、历史消费者记录、行情资产和 live runtime 未修改。通过证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前同名非 rerun 目录继续作为失败历史快照保留。

`FULL_HISTORY_AUDIT_V2_READY` 表示动态矩阵引擎和 direct PostgreSQL 只读审计已可复查；`DATA_LAYER_REAUDIT_REQUIRED` 保留 provider-earliest、TradingCalendar、TradingSession 和全历史资产 residual 的独立治理边界。它不否定已通过的消费者契约，但仍禁止把该结论扩写为“所有全历史资产零 residual”或 live runtime Ready。

阶段 4/5 已完成，S6-03 至 S6-06 既有 Gate 保持不变。S6-07 D1=`2026-07-22` 正常自动归档通过；`2026-07-23` 第二次在线归档作为连续性证据保留；D2=`2026-07-24` 在 scheduler 停机漏跑后由独立调度器自动发现。旧 Runtime 的 1w 聚合失败曾 fail-closed，随后经精确 recovery deployment、service enable 和显式同日 retry 授权恢复；没有手工调用单日 archive CLI。D2 最终生成 7 个 primary/passed 资产（含 1w）、7 行 manifest、8 条 consumer binding，watermark 与 required binding end 均到 `2026-07-24`，四类禁写 counter 增量为 0。最终 create-only receipt 已发布 `JM_EOD_INCREMENTAL_AUTOMATION_READY`；该 Gate 不代表 Runtime 长稳、SignalEvent、通知或自动交易 Ready。

2026-07-26 已完成 WEB-V1-14 研究工作台体验收口：Market 资格、quality 影响和工程证据分层，
Kline 盘面交互、Dashboard/Signal/Review/Backtest/Data/Runtime 跨页面语言，以及 unit/build/mock/
真实 PostgreSQL read-only Gate 均通过。该增量不改写 `WEB_V1_13_PARTIAL` 的真实关联样本缺口，
未部署 Runtime，也不代表策略有效、长稳、通知或自动交易 Ready。

同日 HTDY first-seen Web 兼容候选已在 `codex/v1-htdy-realtime-integration@cba1ca87`
完成集成验收：`live_realtime_repainting` 固定显示为 observation-only；Signal、Dashboard、
Market marker 与 Review 均保留实际主力、15m first-seen 冻结桶和
`signal_review_lineage_v2`，且 notification/auto-order 持续为 false。Web 不重算历史 HTDY，
marker 只接受首次 `signal_created`，不跟随 `signal_changed` 移动或删除。mock 浏览器与本机真实
GET-only 验收通过；该候选尚未部署 Runtime，未产生真实 HTDY 事件、ReviewNote、通知或交易写入，
`WEB_V1_13_PARTIAL` 保持不变。

2026-07-26 已完成 HTDY Step 0 合同冻结和旧 S6-08 授权收口。旧
`jm_v1b_daily_direction_fast_entry/v1b.0` schema-v2 packet 文件保留为历史证据，但 Runtime
已是 SignalEvent flag=false、packet/hash 空、autosend=false；只重启 live scheduler 后
Runtime/live/EOD health fresh/ok，受控表计数、Profile hash、EOD watermark 与 DB revision
均无漂移。新目标只冻结为 exact `jm + 当日 rank=1 实际主力 + 15m +
htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting` 观察例外。Step 1 已冻结纯 production
kernel、exact fail-closed policy、Python/Web golden 与 24-horizon/27-zone evidence；schema-v3
Runtime 接线代码已完成，但部署、真实事件和通知仍未授权。

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
或平行通知链。Step 4 已完成 schema-v3 bounded parent、exact daily child、执行结果 verifier、
独立 `HtDyRuntimeEventHandler`、首次自然事件后唯一一次同 key 幂等探测及 create-only 授权消费
代码：parent 最多五个明确 DCE 交易日并绑定 deployment、S6-07 final receipt、service bundle、
Runtime commit、DB revision、source/policy/writer hash；child 绑定单日实际主力 mapping 与受控表
baseline；结果只接受一条 `signal_created` 和全部禁写 delta=0。旧 `LiveSignalEvaluator` 不进入
HTDY active path，旧 `persist_signal_events=True` 在 ingest 前拒绝。尚未生成真实三个 packet/hash；
S6-07 数据库业务事实恢复已按 Approval R 完成。第二轮 deployment/rebind/service-parent 三包虽
取得 Approval A，但执行前 fresh verification 发现 `origin/main` 与 ahead facts 漂移；批准未消费、
Runtime 未部署。进一步审计确认旧 S6-07 code rebind 缺少 confirm executor 和 create-only receipt。
当前 `codex/v1-htdy-approval-a-rebind` 正在补齐 receipt-bound rebind Gate；完成后必须从新的干净
checkpoint 重新生成三包并取得新的精确 Approval A。真实 deployment、事件、通知与外部 Gate 仍
pending。
这些 checkpoint 不代表盈利、Runtime 或交易 Ready。

第三轮精确 Approval A 随后完成 code-only deployment，Runtime 已从 `facd8034` 切换到
`22760122`；deployment receipt 证明 DB 保持 `0025`、SignalEvent/autosend 保持关闭、
health verified 且未 rollback。S6-07 rebind 在 receipt 写入前因 DB 环境未加载而 fail-closed；
显式加载环境后发现 checkpoint collector 使用了 0025 schema 不存在的列。after-market scheduler
保持 unloaded/disabled，未生成 rebind receipt，未产生 HTDY 事件或任何通知/交易写入。当前修复
改用 ORM 全列 checkpoint baseline；修复后需新 commit、新三包和新的精确 Approval A。

第四轮精确 Approval A 已将 Runtime 从 `22760122` 部署到 `d6fb9a38`，并成功生成、重载验证
create-only `deployment_receipt.json` 与 `s6_07_rebind_receipt.json`：DB 保持 `0025`，checkpoint
count/hash、十类受控计数和四类 baseline hash 零漂移，after-market scheduler 保持
unloaded/disabled，SignalEvent/autosend 继续关闭。部署后 production parent collector 随即
fail-closed 于唯一差异 `web.bundle_sha256`：`apps/quant-web/dist` 被 Git ignore，旧 code-only
deployment 只切换 commit，未同步 service parent 已冻结的新 Web bundle。当前补丁将 source/runtime
bundle path/hash 纳入 deployment packet，使用 hash-bound 原子目录交换并提供失败回滚，receipt
冻结 before/after/synced。该补丁产生新 commit 后必须重新生成三包并取得新的精确 Approval A；
在此之前不得创建 daily child、接受自然事件或宣称 HTDY Runtime Ready。

最终精确 Approval A
`deployment=63745f53... / rebind=00e60479... / service_parent=f0316f26...`
已执行：Runtime 从 `d6fb9a38` 切换到 `f63b3636`，Web bundle 原子同步为获批
`be70524d...`，DB revision 保持 `20260721_0025`。create-only deployment/rebind receipts
均通过仓库 verifier；production parent collector 重采 commit/tree、DB、Profile、mapping、
source/policy/writer、Web、flags、launchd、output 与全部 baseline 后，service parent 验证为
零漂移。SignalEvent/autosend 仍关闭，after-market scheduler 未加载且未重启，未创建 daily
child 或真实 HTDY event，也未写 ReviewNote、通知、订单或交易。由此 Step 0–4 工程验收已闭合；
下一项仍是独立授权的自然 first-seen event/一次幂等探测，之后才可能进入五交易日长稳，当前
不得宣称 Runtime、通知、交易或长稳 Ready。

Step 5 实施前复核确认 HTDY 的目标周期仍是焦煤实际主力 `15m`；confirmed/passed 1m 仅作为
session-aware snapshot 源。首日真实 facts 还缺 `2026-07-27` exact rank=1 mapping，因此新增
RQData 当日 mapping create/verify Gate、事务提交后 create-only receipt、scheduler 无写启动预检
以及脱敏 observation summary。冻结窗口只允许首日上海时间 08:30 前且无 event/child 时补发
新三包，任一 facts 漂移继续 fail-closed。当前仅为 `HTDY_STEP5_PREFLIGHT_CODE_READY /
FRESH_APPROVAL_A_PENDING / S6_08_NATURAL_EVENT_GATE_PENDING`；SignalEvent/autosend 仍关闭，
尚未部署本 checkpoint、创建 mapping/child 或写真实事件。

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
| Web V1 最终验收 | WEB-V1-12 历史 Gate 保留；WEB-V1-13 的真实 SignalEvent→ReviewNote 样本缺口继续为 `WEB_V1_13_PARTIAL`；WEB-V1-14 已发布研究工作台 polish；HTDY first-seen observation-only Web 兼容已通过集成与真实 GET-only 验收，获批 bundle 已随 code-only Runtime 部署，仍无真实 HTDY event/ReviewNote 样本 | `docs/tasks/WEB-V1-FINAL-ACCEPTANCE.md`、`docs/tasks/WEB-V1-13-FINAL-ACCEPTANCE.md`、`docs/tasks/WEB-V1-14-FINAL-ACCEPTANCE.md`、`docs/tasks/V1-HTDY-REALTIME-INTEGRATION-CLOSEOUT.md` |
| 业务下一入口 | HTDY Step 0–4 工程验收已闭合：最终 Approval A 对应 deployment/rebind receipts 与 production service-parent 零漂移验证通过；SignalEvent/autosend 仍关闭。下一项只能是独立授权的单日自然 first-seen event + 同 key 一次幂等探测，之后再进入 S6-10 五交易日长稳 | `docs/tasks/V1-HTDY-04-S6-08-SCHEMA-V3-GATE.md`、`docs/tasks/V1-HTDY-REALTIME-INTEGRATION-CLOSEOUT.md`、`docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md`；`HTDY_S6_08_SCHEMA_V3_GATE_READY / RUNTIME_CHANGESET_DEPLOYED / S6_08_NATURAL_EVENT_GATE_PENDING / FORMAL_BACKTEST_POLICY_UNCHANGED / NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE`；不代表真实 SignalEvent、通知、Runtime 或长稳 Ready |

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
- 阶段 6 JM 主线：S6-03 至 S6-07 已通过。HTDY exact realtime exception 的 Step 0 合同冻结、
  Step 1 production kernel/policy/Web golden、Step 2 snapshot/evaluator、Step 3 first-seen
  writer/lineage v2 与 Step 4 schema-v3 code-only deployment/rebind/parent 验证均已完成；S6-08
  自然事件与一次幂等探测、S6-09 企业微信单条发送和 S6-10 五交易日长稳仍须串行完成各自
  前置与精确批准。阶段 5 的 HTDY rejection 不得通过实时例外、调参或重跑翻转。

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
