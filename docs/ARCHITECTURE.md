# 归一量化系统架构

更新时间：2026-07-26

## 1. 定位

归一量化是单用户、本地优先的国内期货研究工作站。V1 服务“数据 → 回测 → 报告 → 复盘 → 信号提醒 → 人工观察”，不做自动交易。

## 2. 主链路

```text
RQData 1m
-> raw parquet
-> standard 1m parquet + quality Gate
-> local aggregation 5m / 15m / 30m / 60m / 1d
-> manifest / checksum / PostgreSQL metadata
-> DuckDB read_parquet
-> vn.py CTA / FastAPI
-> PostgreSQL report / trade / order / signal / review facts
-> Vue Web
```

live 数据是独立观察层：

```text
RQData live 1m -> live_minute_bars
-> confirmed 5m/15m/30m/60m/1d/1w
-> preview (zero write)
-> optional formal live_confirmed event
-> optional guiyi-notifications queue -> observation-only WeCom
```

单 APScheduler 由 Redis singleton lock 防重复，交易 session clock 控制夜盘、午休、节假日和 close grace。live 表不自动登记为 historical active，不进入可信回测；formal event、盘后归档和企业微信分别由默认关闭的独立 Gate 控制，永不生成订单。

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

Step 5 在 daily child 之前增加 exact mapping freeze：

```text
RQData jm rank=1 exact trading day
-> create/verify one MainContractMap row
-> transaction commit
-> create-only mapping receipt
-> daily child/current facts
-> HTDY 15m snapshot/evaluator/writer
```

该写入不新增 migration，不替代历史 Profile，也不把 live 数据晋升为 historical canonical。
scheduler 启动预检只验证 parent，禁止进入 daily mapping/child write phase；每轮正式事务才可
materialize mapping。mapping identity 不依赖可能在回滚后变化的数据库序列 id，因此失败重试
仍可验证既有 create-only child，actual contract、data version、source response 或 receipt
漂移仍会拒绝。Runtime 日志只写脱敏 observation summary。

纯 contract 模块仍不访问外部状态；独立 collector/CLI 负责 fail-closed 重采 facts 与 create-only
证据。真实 packet 发布、批准、部署和单日自然事件属于外部 Gate。

### S6-10 schema-v4 five-day stability boundary

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

### S6-10 schema-v5 one-day close-only boundary

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
Runtime scheduler 仅对 `schema_version=5 / htdy_s6_10_one_day_parent` 路由新 Gate，
且必须重新验证 Approval C2 receipt 与所有当前 bindings。全局 autosend 仍为 false；
专用发送范围最多 23 个窗口内自然事件、每事件最多 3 次，窗口结束自动失效。
backup/restore 不属于 schema-v5 前置，故 `disaster_recovery_ready=false`。

当前运行状态必须区分：

| 层级 | 状态 |
|---|---|
| 代码 / 模板 | live ingest、multi-timeframe aggregation、formal event、notification worker、launchd/frp/nginx 模板已具备 |
| 单次历史 smoke | Stage 9-B2 historical replay single-send smoke 已通过 |
| 单次真实 live / archive Gate | `T3_REAL_PASSED`、`JM_ARCHIVE_PASSED` 与 `JM_EOD_INCREMENTAL_AUTOMATION_READY` 均已达成；不自动继承到 SignalEvent、通知或长稳 |
| S6-08 SignalEvent | 旧 JM V1-B schema-v2 代码与 packet 仅作 superseded 历史；HTDY Step 3 immutable writer/完整 lineage v2/Stage 9 preview-only 例外已完成，delivery 与通知仍禁止；最终 Approval A 已将 code-only Runtime/Web bundle 部署到 `f63b3636`，S6-07 rebind receipt 与 production service-parent 零漂移验证均通过。SignalEvent flags 仍关闭，daily child、自然事件、幂等探测与长稳仍 pending |
| S6-10 长稳 | schema-v4 packet/child/ledger/observer/Runtime route/CLI 已在独立 worktree 实现；`/Volumes/GuiyiBackup` 未挂载，真实 backup/restore、Approval C、故障注入和五日 Ledger 均 pending |
| 长期运行 Gate | `JM_RUNTIME_READY` / `LONG_RUNNING_READY` 未达成 |
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
- 运行方向已迁移到本机磁盘副本 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`；开发主仓库仍在 `/Volumes/扩展盘/guiyi-quant-workstation`。
- optional scheduler/notification 只有对应 flag 开启且人工 `--confirm-load` 才加载。
- 当前已完成单次真实 T3 live Gate 与单交易日 T4 provider-final 归档 Gate，但仍不能宣称 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent 或通知 Ready。

### 公网入口

- 腾讯云 Nginx 443：TLS + Basic Auth，经 FRPS `18080/18000` 转发到 Mac mini 的静态 Web 与 FastAPI。
- Mac mini 使用 launchd 作为当前监督主线；仓库中的 systemd 单元仅是 Linux 同机运行候选，不是腾讯云当前运行事实。
- PostgreSQL、Redis、API、Web 和 FRPS 业务端口不得直接暴露公网。
- 当前只有配置级闭环，真实域名、证书、防火墙、隧道限制和远程恢复必须另做 smoke。

## 7. 当前未完成

- Audit V2 全历史 residual 治理：处理保留的 provider/calendar/session/asset 证据边界，不得把它等同于已通过的消费者准入。
- live/after-market/formal event/notification 的真实 smoke 和 5 日长稳。
- API/Web/backtest/signal worker 的实际 launchd kill/restart 验收。
- 样本外 / walk-forward 验证。
- 真实公网部署验收。

以上未完成项均不得扩大为自动交易、SaaS、多用户或大型平台重构。
