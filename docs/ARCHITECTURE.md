# 归一量化系统架构

更新时间：2026-07-31

## 1. 定位

归一量化是单用户、本地优先的国内期货研究工作站。V1 服务“数据 → 回测 → 报告 → 复盘 → 信号提醒 → 人工观察”，不做自动交易。

## 2. Active target（设计已冻结，尚未完成）

```text
RQData
-> temporary staging
-> schema/session/duplicate/OHLCV/coverage validation
-> one historical canonical Parquet root (provider 1m / 1d / 1w)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService (exact DatasetKey + deterministic aggregation)
-> Web / Indicator / Backtest / Signal / Review
```

`continuous` 与 `actual_dominant` 是显式且不可互换的数据类型。前者主要用于长周期展示、
指标研究和明确标注的数据类型回测；后者用于实际主力监听、信号和真实换月回测。
direct 数据矩阵仅为 continuous `1m/1d/1w` 和 actual-dominant `1m/1d`；
actual-dominant 的 coverage/read 必须按 rank=1 mapping 有效分段计算。
5m/15m/30m/60m 只从 canonical 1m 按 TradingSession 确定性聚合，不形成新的 canonical
身份。任何缺口相交请求必须 fail-closed。

live 目标仍是独立 observation 层：

```text
RQData live 1m -> PostgreSQL live observation
-> confirmed aggregation -> immutable SignalDecision
-> optional SignalEvent -> Notification Gate -> observation-only WeCom
-> EOD re-download RQData final -> input/result reconciliation
```

EOD 不把 live bar 复制为 historical canonical；修复、补数、replay 与 EOD 重算不得补发通知。

Task 06 branch-local candidate 使用 additive `20260802_0028`、identity correction
`20260802_0029`、create-only trigger `20260802_0030` 与 provider lineage `20260802_0031`
建立唯一 V2 active candidate：
`live_observation_bars -> signal_decisions -> signal_decision_reconciliations -> ReviewNote ->
research_samples`。新路径仅接受 `jm + rank=1 actual contract + confirmed 1m/15m`；15m 必须是
同一 TradingSession 内完整 15 根 confirmed 1m。同自然键相同内容幂等复用，revision、identity
或 OHLCV 漂移 fail-closed。旧 partial-first-seen 与旧 live 表保持 frozen compatibility，不导入、
不双写；Task 07 前不删除。

`StrategyInputSchema v1` 以 canonical JSON 固定 Decimal、UTC 时间、DatasetKey/manifest、策略、
indicator、policy、recipe、历史 15m 输入与有序 live 1m；trusted builder 固定唯一合同
`jm_data_core_v2_ema21_direction_observation/v1.0 + ema21/v1 + ema_sma_window_v1 +
jm_ema21_confirmed_close_direction_v1` 及 `period=21 / sma_window / round_digits=6 /
confirmed_close_vs_ema21 / equal=no_signal`，不接受调用方注入 identity、parameters 或 digest。该合同固定
`observation_only=true / future_looking=false / repainting_accepted=false /
historical_backtest_allowed=false / auto_order=false`，并显式拒绝既有 centered-XMA original
strategy/indicator/policy identity。历史输入窗口精确 128 根。
RQData provider-final loader 通过 data-core adapter 与 `validate_provider_batch` 重新获取 exact 1m
window，持久化 provider data version/request digest。固定 evaluator 只消费 128 根 confirmed
historical 15m 与当前 confirmed decision bar，复用 quant-core EMA21 registry/policy/kernel；close
大于/小于 EMA 分别记录 long/short，等于记录 no_signal。`LiveReviewRuntime` 不提供 evaluator 注入点，
EOD 也必须复用同一 evaluator。
SignalDecision create-only；有信号和无信号均记录。Task 06 不创建 SignalEvent 或 notification；
future first-seen 双时间语义必须另走既有 frozen Event 合同与独立 Gate。

所有可执行入口集中在 `LiveReviewRuntime`，live/EOD/retention 与人工 Review 分别由默认
false 的 flag fail-closed；SignalEvent/notification flag 继续保留为健康状态读回项但 Task 06 无写入器。
底层纯 domain service 只供编排与测试复用，不是 Runtime 入口。

以上是默认 disabled 的基础设施；`/api/runtime/health` 的
`data_core_v2_live_review` 必须回读 disabled、observation_only 与 auto_order=false。生产 migration、
已在 exact backup/approval 后升级到 `0031` 并通过 empty/disabled smoke。真实 provider-final 读取、
scheduler、Runtime 与通知仍需后续独立 Gate；schema ready 不等于 Runtime ready。

### 2.0 Task 04 Gate 前实现边界

`feature/data-core-v2-historical-loop` 已实现候选 historical 读链：

```text
Catalog / Manifest / Gap / MainContractMap
-> CanonicalHistoricalReader
-> MarketDataService.get_bars(BarQuery)
-> canonical bars / EMA / MACD API
-> default-disabled JM Web consumer
```

响应 identity 分为不随请求窗口变化的 source DatasetKey/manifest/provider-version
lineage token，以及单独绑定 exact query window 的 `request_identity_token`。derived frequency
只读取 canonical 1m 并复用 TradingSession 聚合；读取路径不
补数、不缩窗、不写数据。JM Web 仅在 `VITE_JM_DATA_CORE_V2_ENABLED=true` 时使用 canonical
Catalog coverage 与上述 API；默认 false，非 JM 保持 legacy compatibility。

该实现当前为 `BLOCKED_AT_JM_REAL_DATA_GATE`：生产 revision 已在精确 Gate 下升级到
`20260730_0027`。绑定 `develop@e29c2940` 的第三次真实 apply 已完成任务窗口 rank=1 mapping
以及 continuous `JM.MAIN` 的 1m/1d canonical/metadata 发布，随后在 continuous direct 1w
写入前因 RQData 不输出 `2013-03-22` 上市残周 bar 而以
`CANONICAL_QUALITY_COVERAGE_MISMATCH` fail-closed。receipt 保持 `in_progress`，已发布 partition
必须在后续 exact-head Gate 中用 manifest digest 与物理 checksum 重验后才可 skip。

当前 TDD 修复保留 packet-bound 首交易日作为 RQData weekly query anchor，但从 expected weekly
endpoints 排除该非周一起始残周；通用 coverage validator、M1/D1 与 actual-dominant 路径均未
放宽。修复已通过真实 RQData 只读 `684 expected = 684 actual`、Data Core/后端全量与独立
Review，但尚未取得新 merge SHA/CI/packet/批准，因此不得续跑 apply，也未执行 historical
Shadow。这不能解释为消费者已正式切换、Runtime Ready 或任务 04 已验收。

### 2.0 Legacy compatibility（迁移期，禁止扩展为第二套 active）

当前已实现链路仍包含 standard Parquet、Profile/ActiveBinding、workbench/reader 与既有 live
服务。它们只作为迁移期兼容与历史 Gate 事实保留，必须按消费者逐个切换、Shadow/rollback、
引用清除的顺序退出；不得与 active target 竞争长期权威。

### 2.0.1 JM Active Dataset compatibility Facade

`GY-CORE-02` 新增的 `ActiveDatasetResolver`、`MarketDataService`、
`DatasetDescriptor` 与 `BarsResult` 是 **仅限 JM 的兼容 Facade**。historical selection
仍委托既有 Profile / workbench / reader 链：Facade 只冻结并校验该链的结果，不能成为第二套
active selector。

- Browser historical 可以绑定有序的多个合法资产；research 必须固定一个 `passed` 资产。
- 冻结的 file ID 与 evidence 把 bars、quality、conflicts、coverage 和 lineage 绑定到同一组文件；
  historical lineage token 继续使用既有 token，不改写其语义。
- dominant `rank=1` 请求以 exact-date 的 strict / effective identity 比较处理；同一请求存在歧义
  时 fail-closed，不静默择一。
- 唯一迁移调用方是 JM 分支的 `GET /api/v1/market/bars`。非 JM 请求保持既有 workbench
  路径以维持兼容性；coverage、live API routes、indicator/MACD、`/api/klines`、backtest、
  signal 与 review 均未迁移。

Facade 的 live 分支仅供 browser/read-only observation：只接受实际 JM 合约、显式且唯一的
provider/source mode 及 `tail=false`。strict/research live 尚不支持；`live-response-snapshot-v1`
只证明一个返回 response window，不能证明持久化 source-mode DB/schema identity。live
source-mode schema、upsert 与 aggregation 的 P0 是独立 Lane 3 任务，必须在 `GY-CORE-05`
Shadow 前完成，是旧路线当时的约束。该 future reference 已 superseded；新路线由
`GY-DATA-CORE-V2` 任务 11 收口，并在任务 19 前接受独立 Gate。本 Facade 不授权
Runtime、notification、trading 或 release。

### 2.0.2 Unified CLI 编排边界

`GY-CORE-03` 新增独立 Python package/entrypoint `guiyi`，不重命名或扩展旧
`app/cli.py` 为新的权威入口。CLI 只负责参数解析、共享 service 调用、稳定 JSON 与退出码：

```text
guiyi data verify
  -> core_cli.verify_active_dataset
  -> JM: GY-CORE-02 MarketDataService Facade

guiyi runtime status
  -> runtime_health.build_runtime_health

guiyi runtime plan
  -> runtime_scheduler.dry_run_payload
```

`runtime plan` 不打开数据库、不连接 Redis、不构造 RQData client，也不写 live/historical、
SignalEvent 或 notification。`runtime status` 只读取既有 health 聚合，不启动或切换服务。
`data verify` 的新入口仅接受 GY-CORE-02 支持的 JM historical contract；非 JM 只在旧
`guiyi-data check-bars` 兼容 Shim 中继续走 legacy reader，不建立第二套 active selector。

首轮保留两个旧入口：`guiyi-data check-bars` 与
`scripts/rqdata_reference_metadata_gap_apply_plan.py`。它们保持参数和人类可读输出，
但编排改为调用 `app/services/core_cli.py`；后者仍会在调用者指定目录生成原有 plan report，
不会写 DB、Parquet、manifest 或调用 RQData。不得据此删除其他旧脚本或推断 data sync、
EOD、Runtime once/run、notification、backup 已迁移。

### 2.0.3 ObservationPlan 与只读 StrategyAdapter（legacy compatibility）

`GY-CORE-04` 已将首个观察计划冻结在版本化文件
`config/observation_plans.yaml`。`ObservationPlanRegistry` 对原始文件计算 SHA-256，并严格
校验 schema、字段、重复 ID 和 active 数量；当前唯一 active contract 是：

```text
jm + dominant_rank1 + 15m
-> htdy_original_realtime_first_seen/v1.0
-> realtime_first_seen
-> observation_only
-> notification.enabled=false
```

disabled 占位不会被 Adapter 执行；任何第二 active plan、非 JM/15m、通知开启、策略版本或
purpose 漂移均 fail-closed。当前没有实现苏冰策略，也没有扩展多品种或多周期。

`StrategyAdapter` 只定义 `StrategyContext -> StrategyEvaluation` 的内存合同。
`HtDyStrategyAdapter` 固定调用既有 `HtDyRealtimeCandidateEvaluator`，保留原生 candidate、
blocked observation、observation key、方向和 policy identity；返回对象的
`writes_enabled`、`signal_event_enabled`、`notification_enabled` 始终为 false。该边界没有
Session/writer 依赖，不创建 `StrategySignal` / `SignalEvent` / notification，不改变 HTDY
original indicator、partial、repainting、first-seen、no-retraction、`signal_changed` 禁止或
Stage 5 `REJECTED_RESEARCH_CANDIDATE`。旧 GY-CORE-04～08 路线现已
`superseded / paused`；本段只记录已合入代码事实，不授权继续旧 Shadow/Runtime 路线。
Adapter 在调用 evaluator 前还会要求 realtime
first-seen snapshot 的 `partial_allowed=true`，防止 confirmed-only snapshot 静默收缩语义。

### 2.1 HTDY 原版 XMA 精确实时观察支路

2026-07-26 冻结以下目标合同；Step 0 只冻结架构，不代表实现、部署或真实事件 Gate 已完成：

```text
passed historical actual-contract 15m warm-up
+
当前交易日 confirmed/passed live 1m
-> TradingSessionClock session-aware 15m snapshot
-> 当前桶允许 partial，但源 1m 必须 confirmed/passed
-> huotian_dayou_original_v0 / original-v0
-> 27-bar bounded repaint scan
-> first-seen candidate
-> existing StrategySignal -> SignalEvent(signal_created only)
-> optional exact-event Stage 9 single-send
```

精确身份为 `jm + 当日 MainContractMap.rank=1 实际主力 + 15m +
htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting +
htdy_original_xma_15m_first_seen_v1`。该支路：

- 复用既有 `strategy_signals / signal_events / signal_notifications`，不新增表或 migration；
- 不修改 formal confirmed-only writer，也不创建平行 notification 链；
- 同一观察桶只冻结第一次方向；后续消失、反向、重绘或 revision 不撤回、不修改、不新增事件；
- 同一桶 long/short 冲突 fail-closed；
- partial 只存在于实时快照，不写入 historical canonical；
- 不允许历史可信回测、OOS、收益有效性声明、订单草稿或自动交易。

### Step 2 read-only snapshot and candidate boundary

Step 2 仅新增 `HtDyRealtimeSnapshotResolver` 与无状态
`HtDyRealtimeCandidateEvaluator`：它们精确读取当日 `jm/rqdata/volume_open_interest/rank=1`
actual-contract mapping、`live_observation_v1` primary/passed 15m 历史尾部 128 根和显式
trading day 的 confirmed/passed 1m。`TradingSessionClock` 以 DCE session 建 15m 桶，完整桶为
`confirmed`，当前连续前缀仅为 `partial`；午休不建桶，夜盘仍归属其 trading day。

快照与候选均为内存值对象：绝不调用 multi-timeframe aggregation、不写
`live_aggregated_bars`、`StrategySignal`、`SignalEvent`、通知、Runtime 或数据库。每次 evaluator
只对 128 根 warm-up 加本轮桶运行一次 original kernel，并检查最后 27 根；双向同桶只返回
`dual_direction_conflict` block。它不维护 seen state，因此 Step 2 尚未实现 first-seen ledger、
事件、通知、部署、真实 live Gate、盈利或交易 Ready。

### Step 3 immutable first-seen event boundary

Step 3 的 `HtDyFirstSeenEventService` 与 evaluator 保持分离。Step 4 仅通过独立
`HtDyRuntimeEventHandler` 组合 Step 2 resolver/evaluator 与该 writer；旧
`LiveSignalEvaluator` 不进入 HTDY active path。writer 先完整校验
一轮 candidates，再复用既有 `strategy_signals` 与 `signal_events` 写入一次
`signal_created`；稳定 dedupe 只使用 evaluator 已冻结的 `observation_key`。第一次写入后，
同桶的 direction、source revision、snapshot hash、消失或重绘均不更新原 Signal/Event，
不产生 `signal_changed`。

事件冻结 `signal_review_lineage_v2`：保存历史 Profile/file/window、实际主力、观察桶、
首次 detection price、全部 source 1m identity/revision/OHLCV/confirmed_at 以及 indicator/policy
hash。该 writer 不 commit、不写 `signal_notifications`，不新增表或 migration；真实写入仍必须
等待 schema-v3 parent/child、精确批准 hash 与 deployment Gate。

### Step 4 schema-v3 Gate code boundary

Step 4 的纯函数 Gate 分为 bounded parent、exact daily child 和 execution verifier：

- parent 最多绑定五个明确交易日以及 deployment packet、S6-07 final receipt、service bundle、
  Runtime commit、DB revision、indicator source、policy 和 writer 精确 hash；
- child 只绑定 parent 允许的一天、当日实际主力 mapping hash 和六类受控表 baseline；
- execution verifier 至少要求一条 exact HTDY `signal_created`，StrategySignal/Event delta
  与事件数相等，notification/scan/order/trade delta 全部为零；
- schema-v2、hash/Runtime/DB/mapping/baseline 漂移、`signal_changed`、lineage 非 v2 或任何
  禁写漂移均 fail-closed。
- active Runtime Gate 每轮重采 parent/child facts，daily child create-only；第一个自然事件提交后，
  仅再允许同一 event id/key 的一次 `unchanged>0 / created=0 / changed=0` 幂等探测。探测完成即
  create-only 消费授权，后续轮次 fail-closed。
- scheduler 只接收 Gate 构造的 `HtDyRuntimeEventHandler`；旧 `persist_signal_events=True`
  在 1m ingest 前拒绝。deployment packet、S6-07 code-only rebind、service parent 按 hash
  串联，且 service parent 不伪造尚不存在的 deployment receipt。
- deployment 成功后，S6-07 rebind confirm 必须验证 create-only deployment receipt，再冻结
  Runtime/DB/launchd/disabled health 前后状态并写 create-only rebind receipt。after-market
  scheduler 未加载时保持未加载；已加载时只重启精确 label 并等待 PID 变化。active Runtime
  collector 必须重载验证两份 receipt 后才可采集 parent facts。
- rebind 的 after-market checkpoint identity 必须通过 0025 ORM 全列 baseline 采集，不得手写
  漂移列名；receipt 同时冻结 checkpoint count/hash、十类受控计数和四类 baseline hash。
- Web `dist` 是 Git ignore 资产；code-only deployment 必须在批准包中同时冻结 source/runtime
  bundle path/hash，通过原子目录交换安装精确 source bundle，失败恢复旧 bundle，并在
  deployment receipt 中记录 before/after/synced。只切换 Git commit 不足以满足 service parent。

> 2026-07-30 Owner 覆盖：以下 Step 5 与 S6-10 schema-v4～v7 均为
> `superseded / frozen historical`。它们保留架构 lineage，但不得再生成 authorization、
> mapping、daily child、部署或 Runtime/notification 写入。恢复入口仅为
> `GY-S6-10-R2` 单交易日合同。

Step 5 在旧 daily child 之前增加 exact mapping freeze：

```text
首个 schema-v7 完整日：
signed Approval C2 parent
-> deployment preflight 前的 bounded initial mapping transaction

Approval D 长期日切：
previous-day S6-07 EOD exact authorization
-> bounded pre-open Runtime scheduler transaction

RQData jm rank=1 exact trading day
-> create/verify one MainContractMap row
-> transaction commit
-> create-only mapping receipt
-> daily child/current facts
-> HTDY 15m snapshot/evaluator/writer
```

该写入不新增 migration，不替代历史 Profile，也不把 live 数据晋升为 historical canonical。
首个完整日必须先验签 exact C2，并校验 parent/deployment/source/旧 Runtime/关闭状态与截止时间；
只有这些检查通过后，才允许在 full preflight 前 materialize 目标日 mapping，解除“preflight
要求 mapping 已存在、mapping 又等待部署后 Approval D”的循环依赖。长期 scheduler 进程启动
预检仍只验证 Approval D parent；下一夜盘前四小时的正式 Runtime transaction 才可 materialize
后续 mapping。DB commit 后先发布 mapping receipt，开盘正式事务再发布 daily child；
metadata 消费者不得创建两者。mapping identity 不依赖可能在回滚后变化的数据库序列 id，
因此失败重试仍可验证既有 create-only receipt/child，actual contract、data version、
source response、对应 C2/Approval D 或 receipt 漂移仍会拒绝。schema-v7 activation receipt
只在 post-activation 校验 confirmed-close allowlist 时强制要求；pre-activation、
activation-ready 与 Runtime switch 阶段不得提前依赖尚未生成的 receipt。Runtime 日志只写
脱敏 observation summary。

纯 contract 模块仍不访问外部状态；独立 collector/CLI 负责 fail-closed 重采 facts 与 create-only
证据。真实 packet 发布、批准、部署和单日自然事件属于外部 Gate。

### S6-10 schema-v4 five-day stability boundary（frozen historical）

> 历史状态：`superseded`。保留全部 schema-v4 证据，但 active Runtime 不得再以旧
> Approval C 启动新窗口。

S6-10 不复用 S6-08 的“一次自然事件 + 一次幂等探测后消费授权”状态机。它使用独立
`schema_version=4 / htdy_s6_10_five_day_parent`，只在 Runtime scheduler 识别到该精确
packet type 时路由 `HtDyS610RuntimeGate`；schema-v3 的历史 receipt、S6-08 packet 或
S6-09 single-send packet 不能取得五日运行资格。

```text
hash-bound five-day parent
-> create-only daily child
-> exact HTDY JM actual-contract 15m event handler
-> read-only 60s observer
-> create-only sample hash chain
-> create-only daily seal
-> five-day manifest/final receipt
```

parent 同时绑定 target Runtime/source tree、DB 0025、Profile、S6-07/08/09 receipt、
真实 full-backup/isolated-restore receipt、DCE calendar、launchd、feature flags、baseline
counts/hashes 和故障矩阵。每个 child 绑定当日 rank=1 actual mapping、session geometry、
source facts、beginning state 与前一日 seal。任何 binding 漂移、`signal_changed`、新增通知、
ReviewNote/order/trade、禁止 hash 漂移或事件数超过安全上限都 fail-closed。
高风险命令与 Runtime 每轮必须同时验证 parent hash、独立 Approval C bundle hash 和由
预绑定 approved-signers 公钥验证的 detached-signature approval receipt；bundle
再绑定 deployment/rebind/enable packet、observer plist 与 fault schedule 的当前文件身份，
因此 parent 自身 hash 不能充当 Approval C。

JM 每日 session geometry 为 23 个 15m 桶；加初始 27-bar repaint zone，五日理论唯一观察
bar 上限为 142，parent 总事件安全上限为 160。该上限是运行异常保险，不是收益或信号数量
预期。S6-10 observer evidence 在外部 create-only 目录，不新增数据库表或 migration。
passed daily seal 必须覆盖夜盘及三段日盘（60 秒采样、最大允许抖动/故障间隔 150 秒），
append/seal/finalize 均重验完整 hash chain，finalize 只能接受 parent 指定的五个交易日。

真实 full backup、isolated restore、部署、calendar write、fault injection、Mac reboot 与
五日运行仍分别受 Approval C 的精确 hash/slot/target 约束。代码和 fake test 通过不等于
`LONG_RUNNING_READY / JM_RUNTIME_READY`。

### S6-10 schema-v5 one-day close-only boundary（frozen historical）

active 路径为：

```text
confirmed/passed 1m
-> session-aware 15m aggregate
-> only newly confirmed bucket_end
-> HTDY v1.1 frozen 27-bar repaint scan
-> immutable signal_created
-> parent/hash-bound bounded WeCom dispatcher
```

partial 15m 不进入 evaluator。进程内 checkpoint 阻止 polling/revision 对同一桶重复判断，
重启后的安全重算依靠 StrategySignal/SignalEvent/SignalNotification 唯一键保持幂等。
checkpoint 跨 Runtime 轮询共享但不共享数据库 session，确保每轮仍使用本轮事务。
Runtime scheduler 仅对 `schema_version=5 / htdy_s6_10_one_day_parent` 路由新 Gate，
且必须重新验证 Approval C2 receipt 与所有当前 bindings。全局 autosend 仍为 false；
专用发送范围最多 23 个窗口内自然事件、每事件最多 3 次，窗口结束自动失效。
observer/dispatcher 的 launchd template、runner 和文件哈希必须进入 parent；installer
在装载前重新计算并拒绝漂移。
同一 parent 还必须绑定 S6-07 code-rebind packet、新 after-market enable packet 和
schema-v5 deployment packet。部署 receipt 绑定最终 parent；S6-07 rebind 执行时重新验证
parent 所绑定的两个 packet 文件哈希及 target commit，避免 after-market scheduler
继续使用旧 commit-bound enable packet，也避免 parent/rebind 之间形成哈希循环。
backup/restore 不属于 schema-v5 前置，故 `disaster_recovery_ready=false`。

### S6-10 schema-v6 activation-bound remainder boundary（frozen historical）

schema-v6 不把 21:00 后才部署的窗口伪装成完整一交易日。parent 绑定目标交易日、
activation deadline、EOD、目标 commit/tree、DB/Profile baseline、S6-07 rebind/enable
和专用服务身份；签名 C2 必须早于 create-only activation receipt。activation receipt
按 DCE JM session geometry 冻结 `next_full_15m_bucket` 起的精确 bucket-end allowlist。
Runtime evaluator、observer ledger 和 bounded dispatcher 共用该 allowlist，部署前桶、
正在形成的 partial 桶及窗口外事件全部 fail-closed。

部署只允许通过 `jm_htdy_s6_10_remaining_deploy.py` 的单一有序入口；pre-activation、
activation-ready 与 post-activation bindings 分相校验。失败回滚卸载专用服务、关闭
signal/dispatcher 授权、恢复旧 Runtime，并使用独立绑定的部署前 S6-07 packet 恢复
after-market；任何回滚步骤失败均发布 `rollback_incomplete`，不得写成安全恢复成功。
S6-07 恢复先 bootout，再等待 Redis singleton lease 自然释放；不得删除其他 owner 的
lock。恢复权威 owner 由 Redis heartbeat PID 与 launchd PID 直接组合验证，Runtime
health 仅验证 enabled/status/authorization hash，因此 forward 与 rollback 不依赖某个
特定 Runtime health schema 是否暴露 heartbeat PID。等待、配置、启动与验证共享一个
bounded monotonic deadline，且只接受晚于本次恢复启动点的 fresh heartbeat。
`configure-after-market-automation.sh` 更新 runtime env 后必须在同一 deadline 内重启
API，使 `/api/runtime/health` 重新加载 packet/hash/enable 绑定；之后才允许启动并验证
after-market scheduler。仅 env 与 Redis owner 正确、但 API 仍持有旧环境时必须失败。
若组合验证失败，必须在任何 rollback bootstrap 覆盖服务日志前创建脱敏 restore
diagnostic，冻结 env binding、launchd owner、API authorization 与 Redis heartbeat
各自的 expected/observed match；failure receipt 绑定该文件哈希。诊断不得包含环境变量
全集、Redis URL、数据库口令或企业微信 webhook。
activation receipt 创建后、signal Runtime 重启前还必须保留距首个允许桶开盘至少
180 秒的启动余量；专用 launchd PID 与 signal Runtime authorization 健康后再以实际时间
复核未越过首桶开盘，否则整次激活 fail-closed。失败 receipt 保留且不删除
SignalEvent/SignalNotification 审计记录。最终 Gate 只允许
`REMAINING_TRADING_DAY_STABILITY_PASSED[_NATURAL_SIGNAL_PENDING]`，且
`complete_trading_day_passed=false / disaster_recovery_ready=false / auto_order=false`。

### S6-10 schema-v7 decision-close and no-code promotion boundary（frozen historical）

schema-v7 修复 centered-XMA 重绘观察的双时间语义。`SignalEvent.bar_end` 永久表示原始
observation 所在 K 线；`formal_lineage.live_detection_snapshot.decision_bucket_end`
表示哪一次 confirmed 15m 收线首次看见该 observation。允许的收线窗口、Ledger 计数与
bounded WeCom dispatcher 只按 `decision_bucket_end` 判断，字段缺失、无时区或窗口外一律
fail-closed。旧 K 线在当前收线首次出现属于当前 decision close，但消息仍同时展示原始
K 线与当前检测时间，事件首次创建后不撤回、不修改、不产生 `signal_changed`。

数据库 Gate 将不可变表哈希与获准追加账本分离：SignalEvent/SignalNotification 只能按
exact v1.1、decision close、单事件唯一通知、最多 3 次尝试和每日 23 条逐项验证；订单、
成交、复盘、扫描任务、Profile 与 canonical asset 仍保持零漂移。部署必须按
`arm(signal=false) → create-only activation receipt → activate(exact Gate)` 执行；
Runtime health 必须同时匹配 schema、parent hash、目标交易日、最近 decision close 及
observer/dispatcher 心跳，不能只依赖 launchd PID。

完整日最后一根收线后，observer 先把 exact parent/day/last-close 与两个服务心跳封为
create-only terminal seal，并同时写 Redis 与 evidence 文件；16:00 后 evaluator 和发送窗口
保持关闭，但 observer 转入最长 3 小时的 post-window finalize，只读等待 S6-07 的 120 分钟
安全延迟与目标日 checkpoint，成功后生成唯一 `final_acceptance.json`。EOD 判定以目标交易日
durable checkpoint 为主、fresh non-failed heartbeat 为活性证明，不依赖 heartbeat 瞬时恰好
处于 `success`。不可变表内容摘要按 `count/max(id)/max(xmin)` 变更标记缓存；真实库只读基准
首次约 1.093 秒、同进程无变更复核约 0.024 秒。

长期运行不由一次剩余窗口自动继承。先使用 schema-v7 complete-day parent 验收完整 23 个
confirmed close 与 S6-07 EOD；再生成绑定同一 commit/tree 和 acceptance sample 的
Approval D request。只有固定 trust root 与 SSH signature 验证通过的精确 Approval D
receipt 才可生成每日 create-only child；
child 每日从 DCE calendar/session、PostgreSQL rank=1 actual mapping、
`live_observation_v1` active `actual_contract` 的 1m/15m passed-primary RQData binding
（含 profile、provider、版本、checksum 与文件实哈希）、干净 Runtime identity 重建
23-close allowlist，并要求相邻前一交易日 S6-07 checkpoint 的
authorization hash 与 Approval D 绑定值一致。Runtime/scheduler、observer、bounded
dispatcher 与 health 只消费当日 child hash；同日重启仅恢复完全一致的 create-only 文件，
跨日自动轮换新 child。该路径继续保持 global autosend=false、auto_order=false，并复用
S6-07 EOD，不创建第二套盘后调度器。该链代码完成仍不等于长期运行 Ready；fresh 完整日
C2、Approval D 签名、干净 Runtime 与真实部署/运行验收缺一不可。

当前运行状态必须区分：

| 层级 | 状态 |
|---|---|
| 代码 / 模板 | live ingest、multi-timeframe aggregation、formal event、notification worker、launchd/frp/nginx 模板已具备 |
| 单次历史 smoke | Stage 9-B2 historical replay single-send smoke 已通过 |
| 单次真实 live / archive Gate | `T3_REAL_PASSED`、`JM_ARCHIVE_PASSED` 与 `JM_EOD_INCREMENTAL_AUTOMATION_READY` 均已达成；不自动继承到 SignalEvent、通知或长稳 |
| S6-08 SignalEvent | 旧 JM V1-B schema-v2 代码与 packet 仅作 superseded 历史；HTDY Step 3 immutable writer/完整 lineage v2/Stage 9 preview-only 例外已完成，delivery 与通知仍禁止；最终 Approval A 已将 code-only Runtime/Web bundle 部署到 `f63b3636`，S6-07 rebind receipt 与 production service-parent 零漂移验证均通过。SignalEvent flags 仍关闭，daily child、自然事件、幂等探测与长稳仍 pending |
| 旧 S6-10 | schema-v4～v7 owner-paused / frozen historical；旧授权、mapping、部署和运行均禁止 |
| 新版 JM Runtime Gate | `GY-S6-10-R2` 待设计：一个完整 DCE 交易日自然运行 + 同一 exact release 独立恢复证据 + 独立 Review + 用户最终批准 |
| Ready 兼容字段 | `JM_RUNTIME_READY` 未达成；`LONG_RUNNING_READY=false` 固定为 deprecated/not_applicable，单日 Gate 永不设 true |
| 消费者数据层 Gate | `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已通过；`DATA_LAYER_REAUDIT_REQUIRED` 仍是全历史 residual 治理，不是消费者契约阻断 |
| 全历史契约 | `V1_DATA_CONTRACT_FROZEN`；只冻结目标与消费语义，不代表 Audit V2 或 Profile rollout 已通过 |

## 3. 模块

| 模块 | 职责 |
|---|---|
| `apps/quant-web` | Vue 3、Naive UI、Lightweight Charts；Data/Market/Backtest/Signal/Review/Runtime |
| `services/quant-api` | FastAPI、SQLAlchemy、Alembic、RQ、DuckDB、数据/回测/信号/复盘服务 |
| `packages/quant-core` | vn.py `CtaTemplate` 策略、配置和复盘标签 |
| `data` | raw/canonical parquet、manifest、质量与 Gate 报告 |
| `scripts` | 数据、审计、开发启停和受控运维入口 |
| `docs/tasks` / `scripts/engineering` | 高风险任务契约（按需）与工程入口；任务生命周期以 GitHub Issue/PR 为准 |

## 4. 数据边界

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。禁止 validation、legacy_reference、candidate、failed、旧 TqSdk / 天勤和交易练习者数据进入默认 active 链路。

- `continuous_contract`：研究图、日线方向、回测上下文。
- `actual_contract`：真实合约成本、触发价、提醒和复盘上下文。
- `signal_events` 必须保留 product、continuous/actual contract、bar_end、trigger_price、provider、data_role 和 quality lineage。

全历史目标通过 `rqdata_ingest/full_history_contract.py` 的纯契约解析：continuous 1m/1d/1w 使用权威 provider first-valid evidence，derived 5m/15m/30m/60m/1d 继承 passed 1m，actual contract 只覆盖 `MainContractMap.rank=1` 区间的 1m/1d。统一 audit end 为 `2026-07-10`，交易时区为 `Asia/Shanghai`；旧 2020/2023 窗口只属于 legacy Phase 3。

formal consumer 读取前必须保留并检查五层状态：

```text
physical coverage -> registration -> quality
-> reference metadata -> Profile eligibility
```

Market 可显示 warning 但必须展示质量；Backtest 默认 passed-only；Signal 对 warning/partial fail-closed；Review 可展示 warning lineage，但不得把它当作信号证据。live partial 只能 preview，盘后重新获取并验收的 provider 最终数据才能进入 historical canonical。

## 5. 回测边界

```text
Backtest API
-> BacktestService
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit
```

- 信号收盘后仅允许 `next_bar_open` 成交口径。
- 手续费、滑点、乘数、最小变动和保证金必须可追溯。
- 报告曲线从 closed trades 派生，不信任外部传入曲线。
- Stage 13-G `report_id=14` 当前 trust audit 为 passed；收益为负，不能推导策略有效。
- `report_id=14` 是冻结历史基线，只能读取和引用，不得更新、回填或覆盖 lineage。

## 6. 运行与部署

### 本地开发

- Docker Compose：PostgreSQL、带密码 Redis，均只绑定 `127.0.0.1`。
- `dev-up.sh`：开发用途，可运行 Vite dev 和 uvicorn reload，不作为长期部署。
- `dev-status.sh` / `dev-healthcheck.sh`：只读检查，不自动启动或发送。

### macOS 长期运行

- `deploy/launchd` 提供 API、Web preview、backtest/signal worker、JM scheduler、notification worker 和日志轮转模板。
- Runtime 是独立 detached checkout；当前实际根目录由 launchd 的 `GUIYI_PROJECT_ROOT` 与
  `scripts/local-services-status.sh` 共同核对（当前外置盘部署为
  `/Volumes/扩展盘/GuiyiRuntime/guiyi-quant-workstation-runtime`）。开发主仓库仍在
  `/Volumes/扩展盘/guiyi-quant-workstation`；task/develop worktree 不得被服务引用。
- optional scheduler/notification 只有对应 flag 开启且人工 `--confirm-load` 才加载。
- 当前已完成单次真实 T3 live Gate 与单交易日 T4 provider-final 归档 Gate，但仍不能宣称
  `JM_RUNTIME_READY`、SignalEvent 或通知 Ready；`LONG_RUNNING_READY=false` 仅为
  deprecated/not_applicable 兼容字段。

### 公网入口

- 腾讯云 Nginx 443：TLS + Basic Auth，经 FRPS `18080/18000` 转发到 Mac mini 的静态 Web 与 FastAPI。
- Mac mini 使用 launchd 作为当前监督主线；仓库中的 systemd 单元仅是 Linux 同机运行候选，不是腾讯云当前运行事实。
- PostgreSQL、Redis、API、Web 和 FRPS 业务端口不得直接暴露公网。
- 当前只有配置级闭环，真实域名、证书、防火墙、隧道限制和远程恢复必须另做 smoke。

## 7. 当前未完成

- Audit V2 全历史 residual 治理：处理保留的 provider/calendar/session/asset 证据边界，不得把它等同于已通过的消费者准入。
- live/after-market/formal event/notification 的新版单交易日 Runtime 验收：夜盘、三段日盘、
  23 个 confirmed 15m 桶、EOD、幂等、零非法写入，以及同一 exact release 的独立恢复证据。
- API/Web/backtest/signal worker 的实际 launchd kill/restart 验收。
- 样本外 / walk-forward 验证。
- 真实公网部署验收。

以上未完成项均不得扩大为自动交易、SaaS、多用户或大型平台重构。
