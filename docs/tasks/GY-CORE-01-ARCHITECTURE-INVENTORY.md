# GY-CORE-01 全仓架构与 scripts 只读盘点

更新时间：2026-07-30
状态：`PLAN_REVIEW_REQUIRED`
基线：`develop@9ba39bb05432a8d69173e2455834301851b3e266`

## 1. 结论与边界

本文件是 `GY-CORE-01` 的只读 inventory 与 `GY-CORE-02～08` 实施 Plan。盘点期间没有修改
产品代码、Runtime、PostgreSQL、Redis、RQ、Parquet、mapping、通知、packet、receipt 或历史
evidence，也没有恢复旧 S6-10。

结论：

- 历史、EOD、live、HTDY、SignalEvent、通知、Web/API 和 Runtime 的真实调用链可以从仓库静态
  追踪；其中 EOD 与 Runtime 还存在当前主机只读状态证据。
- `scripts/` 共 143 个文件，全部纳入分类：
  `KEEP=44 / MERGE=5 / MOVE=6 / ARCHIVE=75 / DELETE_CANDIDATE=0 / UNKNOWN=13`。
- `ARCHIVE` 表示退出未来 active 入口但保留历史、测试、回滚或 hash 依赖，不表示当前可以删除。
- 没有任何脚本满足“已替代、无引用且经 Review 可删”的充分条件。
- 两项 P0 数据 identity 冲突和三个 P1 收口缺口必须在后续任务 Plan 中显式处理；不得在
  `GY-CORE-01` 修复。
- 旧 S6-10 schema v4～v7 代码、脚本、plist、packet/receipt 仍存在，但已由 canonical
  暂停；存在可执行代码不等于获授权。它们统一归为历史 `ARCHIVE`，不得复用为新授权链。

`GY-CORE-02` 是 Lane 3。用户批准本 Plan 之前，不开始实现。

## 2. 调用图

### 2.1 历史数据同步

```text
scripts/rqdata_actual_contract_bars_batch.py
  → rqdata_ingest.actual_contract_bars_batch.run_actual_contract_bars_batch
  → rqdata_ingest.actual_contract_bars_pilot.run_actual_contract_bars_pilot_write
  → RQData client
  → raw actual-contract bars
  → canonical Parquet
  → manifest
  → DataDownloadTask
  → MarketDataFile
  → DataQualityReport
  → ProfileActiveBinding / consumer lineage
```

正式 actual-contract 写入要求 quality `passed`。`MarketDataReader`、Profile consumer、Backtest、
Signal 和 Review 读取 metadata/lineage 后访问 canonical Parquet。

仓库另有一条 `.MAIN` dominant v2 增量线：

```text
scripts/rqdata_dominant_v2_incremental_tail.py
  → rqdata_ingest.dominant_v2_incremental.append_dominant_v2_tail
  → direct canonical-root glob / manifest baseline selection
  → canonical Parquet + registration
  → optional profile_aware_incremental binding
```

它是历史连续合约兼容线，不是 actual-contract EOD 线。其 baseline 选择仍绕过统一
Profile/MarketDataFile resolver，见第 4 节。

主力和参考元数据入口：

```text
rqdata_main_mapping_sync.py          → MainMappingIngestor
rqdata_contract_universe_sync.py     → ContractUniverseIngestor
rqdata_continuous_contracts_sync.py  → ContinuousContractIngestor
rqdata_catalog_sync.py               → catalog metadata
rqdata_ex_factor_sync.py             → ex-factor metadata
rqdata_member_rank_sync.py           → member-rank metadata
rqdata_trading_params_sync.py        → trading parameters
```

### 2.2 EOD 自动增量与归档

```text
deploy/launchd/com.guiyi.quant-after-market-scheduler.plist.template
  → scripts/run-after-market-scheduler.sh
  → app.after_market_scheduler
  → AfterMarketAutomationService
  → delegated archive gate
  → AfterMarketArchiveService.archive_once
  → actual-contract write service
  → canonical Parquet / quality / manifest / metadata
  → Profile consumer verification / binding
```

状态和防重边界：

- `after_market_scheduler_checkpoints` 保存调度 checkpoint；
- Redis lease/heartbeat 防止并发 EOD；
- 只支持 `jm`，并验证 approval hash、bound facts、trading-day close 和 provider-final evidence；
- live 表只用于盘后比对，不会被复制为正式历史 active 数据；
- installer 是 `scripts/install-after-market-scheduler.sh`；
- 本任务未读取凭据、未诊断或重启该服务；其当前加载和健康状态属于 Runtime 实测 Gate，
  不从本版本化 inventory 推断。

### 2.3 live ingest / aggregation

```text
scripts/rqdata_live_1m_ingest.py --once
  → LiveMinuteIngestService.poll_once
  → RQData actual contract bars
  → live_minute_bars
  → live_ingest_checkpoints

scripts/rqdata_live_multi_tf_aggregate.py --once
  → LiveMultiTfAggregationService.aggregate_once
  → TradingSessionClock
  → live_aggregated_bars
  → live_aggregation_checkpoints
```

两个脚本自身都只提供 `--once`，仓库没有独立 live ingest launchd；持续执行由通用
`app.runtime_scheduler` 驱动。live 层不写 canonical Parquet、`MarketDataFile` 或 Profile。

### 2.4 主力映射与 active/profile

```text
MainContractMap
  ├─ generic rank/provider resolver
  │    → actual-contract historical / EOD
  └─ strict rule=volume_open_interest + rank=1 + provider=rqdata resolver
       → LiveTargetContractResolver / HTDY strict context

ProfileLineageResolver
  → DataProfileRegistry
  → ProfileActiveBinding
  → MarketDataFile
  → DataQualityReport
  → MarketDataReader.load_bars_from_market_file
```

Backtest、Signal 和 Review 使用 pinned file/version/checksum。Browser observation 允许
`rqdata/local_parquet + primary + quality != failed` 的兼容读取，但不是正式研究输入。

### 2.5 HTDY evaluator / writer

```text
HtDyRuntimeEventHandler / HtDyClosedBarRuntimeEventHandler
  → HtDyRealtimeSnapshotResolver
  → rank-1 actual contract + profile + historical/live snapshot
  → HtDyRealtimeCandidateEvaluator / HtDyClosedBarCandidateEvaluator
  → compute_htdy_original
  → HtDyFirstSeenEventService.persist
  → StrategySignal
  → SignalEvent(signal_created)
```

保留的语义：

- `jm / DCE / actual rank1 / 15m / observation_only / auto_order=false`；
- original XMA 的 future-looking/repainting 风险仍受精确白名单限制；
- first-seen 不撤回、不修改；禁止 `signal_changed`；
- 同桶 long/short 冲突 fail-closed；
- `StrategySignal.dedupe_key` 与 `SignalEvent.event_key` 由 DB unique 防重；
- 写入前拒绝 evaluator 自称 `writes_enabled`、`signal_event_enabled` 或
  `notification_enabled`。

通用 evaluator/writer 是需要保留的领域语义，但当前旧 S6-10 writer 路由未获授权。

### 2.6 SignalEvent / RQ / WeCom

```text
SignalEvent builders
  → SignalEvent(event_key unique)
  → NotificationDispatchService
  → SignalNotification(dedupe_key unique)
  → RQ queue "notifications"
  → app.worker
  → tasks.notifications
  → Stage9WechatDeliveryService
  → UrllibEnterpriseWechatSender
  → WeCom HTTP
```

真实 HTTP 发送必须同时满足 worker 运行、autosend 明确开启和 notification Gate。Stage-9
payload 固定含 `observation_only / not_trading_instruction / auto_order=false`。

旧 S6-10 bounded dispatcher 是另一条隔离路径：它要求全局 autosend 为 false，仅允许旧
packet 选中的 v1.1/15m/bucket event，并限制 23 个 event、每 event 三次。该路径属于冻结
历史，不能与通用 notification worker 合并成新的 delivery policy。

### 2.7 Web / API 消费

```text
Vue page/component
  → apps/quant-web/src/api/*.ts
  → Axios request.ts
  → FastAPI router
  → app/services/*
  → PostgreSQL metadata / live tables / Profile / MarketDataFile / Parquet
```

| Web 能力 | API | 后端读取边界 |
|---|---|---|
| 历史 coverage/bars/indicator | `/api/v1/market/workbench/coverage`、`bars`、`indicators` | `market_workbench` / `market_indicators` → Profile/reader |
| live target/coverage/bars | `/api/v1/market/live/*` | `LiveTargetContractResolver` / `LiveMarketReader` → live tables |
| signal/event/preview | `/api/signals/*` | `StrategySignal` / `SignalEvent` / evaluator preview |
| Runtime health | `/api/runtime/health` | Runtime/Redis/EOD/S6-10 heartbeat 只读汇总 |
| 兼容 K 线 | `/api/klines` | `MarketDataReader.load_bars`，无 pinned profile |

`getMarketBarsForBacktestReport()` 会在前端从 report/trade 推导多个 contract/provider 候选并
顺序请求。它不直接读取文件，但含客户端 fallback 选择逻辑。`GY-CORE-02` 首个迁移 caller
不得选择该路径，也不得顺手改变其展示语义。

现有 `services/quant-api/app/cli.py` 的命令名为 `guiyi-data`，混合 `check-bars` 与苏冰回测；
没有发现稳定 packaging/README/Runtime 入口。它不能直接改名扩展为新 `guiyi` CLI。

### 2.8 Runtime install / start / restart / deploy / recovery

通用链：

```text
deploy/launchd/com.guiyi.quant-runtime-scheduler.plist.template
  → scripts/install-local-services.sh
  → scripts/run-local-service.sh runtime
  → app.runtime_scheduler --run --confirm-live-write
  → Redis singleton + heartbeat
  → LiveRuntimeCycleService
  → ingest → aggregate → optional gated signal handler
```

EOD 使用独立 label，不与 Runtime scheduler 共用 checkpoint。Runtime promotion 由
`scripts/engineering/runtime-promotion.sh` 与 release/worktree 规则约束；S6-07 的 DB
recovery、code rebind、checkpoint recovery 仍是独立 hash-bound Gate。

Runtime/launchd 状态会随主机运行变化，本版本化 inventory 不固化 PID、loaded state 或
last-exit-code。进入 `GY-CORE-05～07` 前必须重新只读核对 detached Runtime commit/clean、
plist path、loaded label、program/arguments、health、checkpoint 和 legacy/new writer
ownership。本任务未读取 `project.env`、Redis key、RQ queue、DB baseline 或通知 secret，
所以真实 flags/packet/业务状态均为 `UNKNOWN`。

旧 S6-10 deploy/recovery 实现仍可静态调用：

```text
stop dedicated services
  → suspend EOD
  → switch Runtime
  → S6-07 rebind
  → restore/verify EOD
  → activation receipt
  → install observer/dispatcher
  → on failure rollback Runtime/EOD + create-only failure receipt
```

canonical 已禁止执行这条链。旧 v4～v7 services/scripts/plists/packet/receipt/rebind/ledger/
dispatcher 全部按历史 `ARCHIVE` 保留。

## 3. `scripts/` 全量分类

分类基于当前调用、Python import、shell/plist、测试、canonical、历史 evidence 和 Runtime
回滚依赖。花括号表示列出的精确同前缀文件名；本节覆盖全部受版本控制脚本。修正扩展名后，
以 `rg --files scripts`/`git ls-files scripts`
得到 143 个路径，并将下列 brace 展开为 143 个路径做集合比对：
`missing=[] / extra=[]`。测试产生且被忽略的 `__pycache__/*.pyc` 不属于脚本清单。

### 3.1 KEEP（44）

当前正式入口、唯一业务入口或稳定工程/恢复依赖：

```text
scripts/after_market_archive.py
scripts/backtest_trust_audit.py
scripts/backup/{__init__,artifact,core,create,database_only_drill}.py
scripts/restore/{__init__,core,isolated}.py
scripts/dev-{up,down,status,healthcheck}.sh
scripts/engineering/{check-secrets,preflight,release-flow,runtime-health,runtime-promotion,
                     task-worktree,test}.sh
scripts/engineering/{task_workflow,worktree_flow}.py
scripts/install-after-market-scheduler.sh
scripts/install-local-services.sh
scripts/jm_eod_automation_gate.py
scripts/local-services-status.sh
scripts/regenerate_jm_aggregated_bars.sh
scripts/rotate-local-service-logs.sh
scripts/run-after-market-scheduler.sh
scripts/run-local-service.sh
scripts/rqdata_{catalog_sync,continuous_contracts_sync,contract_universe_sync,
                daily_baseline_sync,ex_factor_sync,jm_update_plan,live_1m_ingest,
                live_multi_tf_aggregate,main_mapping_sync,member_rank_sync,
                research_enhancers_sync,trading_params_sync,v1b_jm_asset}.py
```

### 3.2 MERGE（5）

与未来统一只读/verify CLI 重叠；当前保留，后续改为调用同一 service 的兼容 Shim：

```text
scripts/rqdata_data_layer_final_audit.py
scripts/rqdata_direct_db_baseline_audit.py
scripts/rqdata_full_history_audit_v2.py
scripts/rqdata_reference_metadata_gap_apply_plan.py
scripts/rqdata_target_coverage_audit.py
```

### 3.3 MOVE（6）

含有业务算法或公共实现，应迁入或确认已迁入 `app/services/`；CLI 只保留解析和编排：

```text
scripts/rqdata_dominant_v2_backfill.py
scripts/rqdata_dominant_v2_parquet.py
scripts/rqdata_dominant_v2_register_quality.py
scripts/rqdata_jm_v2_parquet.py
scripts/rqdata_jm_v2_register_quality.py
scripts/rqdata_sync_common.py
```

### 3.4 ARCHIVE（75）

阶段性 Gate、旧 S6-07/08/09/10、历史数据闭环或一次性修复入口。全部保留到相应历史、
测试、rollback/hash 依赖经 `GY-CORE-08` 重新证明可处置：

```text
scripts/backfill_jm_price_tick.py
scripts/configure-htdy-s610-{long-running-runtime,one-day-runtime,runtime}.sh
scripts/configure-live-signal-events.sh
scripts/consumer_contract_final_closeout_006.py
scripts/data_stage_closure_audit.py
scripts/full_history_audit_v2_closure.py
scripts/htdy_s610_fault_watchdog.py
scripts/install-htdy-s610-{observer,one-day-services}.sh
scripts/run-htdy-s610-{observer,one-day-dispatcher,one-day-observer}.sh
scripts/jm_htdy_s6_08_schema_v3_gate.py
scripts/jm_htdy_s6_09_wecom_gate.py
scripts/jm_htdy_s6_10_{one_day_dispatch,one_day_gate,remaining_deploy,
                        remaining_window_gate,stability_gate}.py
scripts/jm_live_signal_event_deployment_gate.py
scripts/jm_live_t3_gate.py
scripts/profile_binding_rollout.py
scripts/profile_binding_rollout_closeout_008b.py
scripts/s607_{database_recovery,recovery_lineage_rebind}_gate.py
scripts/stage13g_repair_report14_lineage.py
scripts/stage9_{jm_v1b_replay_event_once,wechat_send_once}.py
scripts/rqdata_{1m_pre2020_backfill,actual_contract_bars_batch,
                actual_contract_bars_pilot,actual_contract_registration_reconcile,
                actual_dominant_roll_audit_v2,aggregate_main_universe,
                audit,coverage_audit,daily_pre2020_backfill,
                daily_weekly_overlap_reconcile,dominant_daily_baseline_sync,
                dominant_v2_incremental_tail,download_pending_inventory,
                duplicate_active_supersede,duplicate_path_version_reconcile,
                field_audit,full_history_derived_periods,
                full_history_physical_inventory,full_history_residual_closure,
                full_history_residual_closure_apply,full_history_residual_repair,
                full_history_residual_rqdata_replan,
                full_universe_active_gate_audit,
                market_samples_sync,multi_primary_inventory,orphan_file_register,
                quality_failed_root_cause_audit,realtime_poc,recover_raw,
                reference_metadata_gap_reconcile,residual_root_cause_audit,
                source_interval_provenance_repair,stage8_6_pending_reconcile,
                weekly_metadata_row_count_repair,weekly_pre2020_backfill,
                weekly_row_count_reconcile}.py
scripts/rqdata_aggregate_tail_universe.sh
scripts/rqdata_backfill_1w_pre2020_listing.sh
scripts/rqdata_full_universe_backfill_1d_1w.sh
scripts/rqdata_full_universe_backfill_1m.sh
scripts/rqdata_full_universe_download.sh
scripts/rqdata_incremental_tail_universe.sh
scripts/rqdata_roll_1d_1w_incremental.sh
scripts/rqdata_roll_gap_master.sh
scripts/rqdata_roll_incremental.sh
```

### 3.5 UNKNOWN（13）

用途或外部依赖不能仅靠仓库静态引用证明；必须保留并阻塞删除：

```text
scripts/configure-after-market-automation.sh
scripts/export_su_bing_daily_score2of4_package.py
scripts/export_su_bing_daily_trend_cross_score2_package.py
scripts/export_su_bing_report_10_review_package.py
scripts/local-tunnel-healthcheck.sh
scripts/oos_validation_run.py
scripts/post-reboot-verify.sh
scripts/public-healthcheck.sh
scripts/rqdata_reference_metadata_gap_apply.py
scripts/server-recover.sh
scripts/server-status.sh
scripts/signal_review_lineage_gate_003.py
scripts/tunnel-healthcheck.sh
```

### 3.6 DELETE_CANDIDATE（0）

无。静态引用为零不能证明没有人工 runbook、外部 launchd、hash、evidence 或 rollback 依赖。

## 4. 冲突、缺口与 UNKNOWN

### P0-1：MainContractMap resolver 语义不统一

`rqdata_ingest.actual_contract_bars_pilot.resolve_main_mapping` 及 EOD caller 只限定
product/date/rank/provider，并按创建时间取一条；它没有固定
`rule=volume_open_interest`，也不拒绝不同 version 指向不同合约。

`actual_contract_semantics.load_strict_main_contract_mapping` 则固定 rule/rank/provider，并在
同日合约冲突或同 version 重复时 fail-closed。EOD/actual-history 与 live target/HTDY
存在选择不同 mapping 的风险。

### P0-2：live 1m source-mode identity 不闭合

`live_ingest_checkpoints` 唯一键含 `source_mode`，但 `live_minute_bars` 唯一键和 ingest
upsert 查询不含；切换 source 可覆盖同一 bar 的 `source_mode`，同时保留两套 checkpoint。
aggregation source query 也未按 source mode 过滤，而 aggregate target 唯一键又包含
source mode。由此可能产生混源 lineage/revision。

这不是 `GY-CORE-02` Facade 可以顺手修复的问题：修复唯一键需要 migration，已超出该任务
明确禁止范围。必须先单独冻结 identity 决策和迁移/兼容方案。

### P1-1：session 最后一个聚合桶缺少显式 close flush

aggregation 跳过 `bucket_end >= max_source_datetime` 的桶，只在后继 1m bar 出现后关闭上一桶。
session 收盘最后一个 5m/15m/30m/60m 桶没有独立 session-close flush 证据。这会影响未来
23 个 confirmed 15m 桶完整性，不影响 EOD RQData 最终历史归档。

### P1-2：dominant v2 incremental 仍直接 glob baseline

`dominant_v2_incremental` 和 `dominant_v2_backfill` 通过 canonical root glob/manifest 选择
baseline，后者还允许 `quality_status=unknown` 参与候选。该路径绕过 Profile/MarketDataFile
resolver，不得作为 future active selector。

### P1-3：Browser/Web fallback 与 formal lineage 必须隔离

`/api/klines` 无 pinned profile；Web 回测报告 K 线还会在客户端尝试多个 contract/provider。
这些是展示兼容行为，不是 formal input。Facade 首批 caller 必须选后端只读 caller，并明确
browser 与 strict/research 的不同失败语义。

### Runtime/外部 UNKNOWN

- 未读取 Runtime `project.env`，所以 live SignalEvent、autosend、packet/hash flag 为 UNKNOWN；
- 未读取 Redis lease/heartbeat 和 RQ queue；
- 未读取 PostgreSQL 行数、DB revision 或 SignalEvent/Notification baseline；
- 未验证 RQData 当前 mapping/provider-final 状态；
- EOD label 的 `EX_CONFIG` 根因未诊断；
- UNKNOWN 13 个脚本的外部 runbook/人工使用方未确认；
- 新 Shadow/new writer 尚未实现，`GY-CORE-07` 的新模块最终路径不能提前伪造。

## 5. 引用矩阵

| 引用面 | 当前事实 | 后续约束 |
|---|---|---|
| launchd | 11 个模板；通用 API/Web/workers/runtime/EOD 与 3 个旧 S6-10 模板 | S6-10 模板仅历史；07 原子修改 runtime identity；08 重扫 |
| Makefile | 仅调用 engineering preflight/test/secret/worktree audit | 不证明业务 scripts 被覆盖 |
| CI | engineering-test/lane-pr-gate 主要绑定治理入口 | 业务脚本移动需新增定向测试 |
| shell | installer/runner 以精确路径复制、执行脚本 | MOVE/MERGE 前先保持兼容 Shim |
| Python import | tests 直接 import backup、restore、backfill、S6-10 dispatcher | 测试迁移前不得删 |
| canonical | S6-07 task 路径/hash 被 recovery code 消费；S6-10 主体为冻结历史 | 保留精确路径与历史文本 |
| tests | EOD、runtime health、S6-07/08/10、engineering entrypoint 均绑定现有路径/schema | archive 不等于删；逐项迁移 |
| Runtime | 运行状态是易变外部事实，本 inventory 不固化 PID/loaded state | 05～07 前从 detached Runtime、launchd 和 health 重新取证 |

## 6. `GY-CORE-02～08` 精确实施 Plan

### 6.1 GY-CORE-02：兼容 Facade（Lane 3）

目标严格保持手册原边界：先新增 `ActiveDatasetResolver`、`MarketDataService`、
`DatasetDescriptor`、`BarsResult`，委托现有 Profile/MarketDataFile/reader，不改变选择结果。

首轮允许范围：

- 新增 Facade/domain model 模块及测试；
- 复用 `profile_lineage.py`、`data_profile_registry.py`、`market_data_reader.py`、
  `live_market_reader.py`、`live_target_contracts.py`、`actual_contract_semantics.py`；
- 仅 JM、`.MAIN` historical、actual historical、live 1m/15m、browser/strict；
- 只迁移一个后端只读 caller，优先 market API 的只读 service seam；
- 新旧逐字段/逐 bar 对照 profile/file ID、contract role、actual contract、period、quality、
  version、checksum、coverage、lineage token、row count、bar key、OHLCV。

禁止范围：

- migration、DB/Parquet/Profile binding 写入；
- 修复 P0-2 唯一键、session-close flush 或 dominant glob；
- 修改 EOD、Runtime、HTDY、report 14/15 或 Web fallback；
- 静默选择最新、静默降级 provider。

前置决策：

1. Facade 必须调用 strict mapping，但要先证明旧 caller 的结果等价；遇到现有 mapping
   冲突时 fail-closed，不可偷偷改选。
2. P0-2 需另开 Lane 3 identity/migration Plan；未解决前 Facade 对 live source mode
   必须显式返回冲突/不支持，不能声称统一 identity 已完成。

定向测试：现有 Profile/market reader/workbench/live reader/target tests，加新 descriptor、
equivalence、ambiguous mapping、missing asset、failed/unknown、provider no-fallback tests。

### 6.2 GY-CORE-03：统一 CLI 首轮（Lane 2）

新增独立 `guiyi` CLI package/entrypoint，不能直接重命名混有苏冰回测的旧 `app/cli.py`。

首轮：

- `guiyi data verify` → GY-CORE-02 Facade 的只读验证；
- `guiyi runtime status` → `runtime_health.build_runtime_health`；
- 一个 `runtime plan` 或 scheduler dry-run 样板，只调用现有 dry-run payload；
- 旧 `guiyi-data check-bars` 与一个 MERGE 类只读 audit 改为兼容 Shim；
- 固定 JSON schema、stdout/stderr、退出码与参数兼容测试。

禁止触碰 `run-local-service.sh`、installer、launchd、EOD、live write、S6-07/08/10 Gate 和
任何真实 data sync。

### 6.3 GY-CORE-04：ObservationPlan / Adapter（Lane 2）

新增 `config/observation_plans.yaml`、registry/domain model、StrategyAdapter contract、
`HtDyStrategyAdapter` 和 contract/golden tests。

仅允许：

```text
jm / dominant rank1 / 15m
htdy_original_realtime_first_seen v1.0
realtime_first_seen / observation_only
notification.enabled=false
```

Adapter 只包装现有 evaluator 的只读 seam；不修改 original formula、partial、repainting、
first-seen、no-retraction、observation key、Stage 5 rejection、writer 或 DB。苏冰不实现。

### 6.4 GY-CORE-05：只读 Shadow（Lane 3 Plan 后实现）

新增 Shadow orchestrator、bar boundary tracker、JSONL/report schema 和 zero-write verifier。
只读调用 02 Facade 与 04 Adapter，不接 `LiveRuntimeCycleService` 写路径，不拥有 ingest、
aggregate、checkpoint、SignalEvent、notification、Parquet 或 Runtime config 权限。

在实现前必须解决/冻结：

- P0-2 source-mode identity 的只读选择政策；
- P1-1 session-close bucket policy；
- legacy candidate 的只读对照来源；
- JSONL restart continuation、source revision hash、23-bucket matrix；
- 进程、DB role、filesystem allowlist 和 network side-effect guard。

### 6.5 GY-CORE-06：一个完整交易日 Shadow

真实运行前需用户批准。使用 exact release 的只读 Shadow，覆盖夜盘、三段日盘、23 个
confirmed 15m 桶、EOD、同桶幂等、零正式写入。任何异常整日作废，Ledger append-only，
不现场热修。Runtime/RQData/Mac 恢复证据可在前后独立执行，但必须绑定同一 exact release。

输出：逐桶 identity/snapshot/candidate/observation-key 对照、zero-write baseline/delta、
EOD、差异根因与独立 Review。未解释差异即阻塞。

### 6.6 GY-CORE-07：ReleaseManifest / Runtime promotion（Lane 3）

已确定的现有影响面：

- `scripts/engineering/{release-flow,runtime-promotion,runtime-health,worktree_flow}*`；
- `docs/WORKTREE_RELEASE_WORKFLOW.md` 与 ADR-WS-003/004；
- `scripts/{run-local-service,install-local-services,local-services-status}.sh`；
- runtime launchd template；
- `app/runtime_scheduler.py`、`app/after_market_scheduler.py`；
- `services/{live_runtime,runtime_health,after_market_automation,
  after_market_deployment,after_market_checkpoint_recovery,s607_code_rebind}.py`；
- backup/restore 仅作 rollback/recovery consumer，不在本任务擅自执行；
- 新 ReleaseManifest schema/service/verifier、new writer binding、handover/rollback tests。

`runtime_health.py`、runtime scheduler、runner 和 plist 是同一运行身份链，必须作为原子
reviewed set。Release、main/tag、Runtime promotion、真实写入分别审批；先停 legacy writer，
冻结 checkpoint，验证 detached exact tag/manifest，再启动 new writer，绝对禁止双写。

### 6.7 GY-CORE-08：归档与 canonical

开始前必须满足：新 Runtime 已正式切换、至少一个受控观察窗口、rollback bundle 可用、
legacy 不再是 writer，并重新执行本 inventory。

顺序：

1. 对 75 个 ARCHIVE、5 个 MERGE、6 个 MOVE 和 13 个 UNKNOWN 重跑 launchd/Makefile/CI/
   shell/import/docs/tests/Runtime 全引用扫描；
2. UNKNOWN 一律保留；DELETE_CANDIDATE 仍需独立 Review；
3. MERGE/MOVE 先提供兼容 Shim 和窗口，再讨论删除；
4. 旧 S6-10 scripts/plists/services 优先归入历史路径，不改写旧 contract/evidence；
5. 更新 `STATUS.md`、`DECISIONS.md`、`AGENTS.md`、`README.md`、`TESTING.md`、
   architecture/signal/worktree canonical。

必须保留 S6-07 hash-consumed task、reports 14/15、receipt、失败 evidence、数据/manifest/
checksum、Git 历史、HTDY Golden，以及至少到新版 S6-10 通过为止的 legacy rollback bundle。

## 7. 任务冲突矩阵

| 并发组合 | 结论 | 原因 |
|---|---|---|
| 02 与 active mapping/Profile/DB migration | 禁止 | 同一 identity/active selector |
| 03 与 live/EOD/launchd 改造 | 禁止 | CLI 首轮只读，避免入口与运行身份同时变化 |
| 04 与 HTDY formula/policy/writer | 禁止 | Golden 和 observation key 必须不漂移 |
| 05/06 与 legacy Runtime deploy/recovery | 禁止 | Shadow 零写入和 exact identity 无法证明 |
| 06 与现场 hotfix | 禁止 | 单日失败必须整日重启 |
| 07 与任何 Runtime/release work | 禁止 | stop/start/manifest/checkpoint 必须原子 |
| 08 与未完成 07/稳定窗口 | 禁止 | rollback 与引用边界尚未冻结 |
| Su Bing/多品种/AI 与 02～08 | 不在范围 | V1 核心收口只限 JM |

## 8. 验收与回滚

本任务验收：

- 9 条真实调用链均有代码落点；
- 143 个 scripts 全覆盖且计数闭合；
- launchd、Makefile、CI、shell、Python import、canonical、tests、Runtime 引用均已列出；
- 02～08 有范围、依赖、测试、冲突、禁止项和批准点；
- P0/P1/UNKNOWN 未被隐藏或擅自修复；
- 仅提交本审计/Plan 文档。

文档变更回滚只使用 PR/merge commit 的 `git revert`。本任务没有数据、Runtime 或部署回滚。

## 9. 用户 Gate

独立 Review 通过后，用户可选择：

```text
允许继续实现
```

该结论只批准进入 `GY-CORE-02` 的独立 Lane 3 Plan 会话，不批准实现、migration、真实数据、
Runtime、mapping、通知、main/tag 或 release。

若用户不接受 live source-mode 暂时 fail-closed、strict mapping 等价验证或 P0 拆分方式，
结论应为：

```text
阻塞
```
