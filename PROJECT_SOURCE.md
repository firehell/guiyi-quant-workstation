# 归一量化项目事实源

更新时间：2026-08-22

## 定位与边界

归一量化是本地运行、单用户的国内期货量化研究工作站。当前只服务可信历史行情、Market Web、
Indicator Kernel 与未来研究；不做自动交易、实盘下单、SaaS、多用户、高频/Tick 平台或 AI 自动
晋升策略，所有研究观察始终保持 `auto_order=false`。当前没有 backtest 子系统或旧 Signal/Review/Strategy 应用面；Alert 是独立、窄范围的观察通知应用，Execution Review 是独立的人工决策/手工执行/复盘 Application Domain，二者都不恢复旧应用面。Market Runtime V1 的历史分页、
Redis Live Overlay、盘后更新与 WebSocket 代码已实现；仓库 launchd 模板仍默认关闭，
本地工作站按明确请求启用由 `operational_products.txt` 定义范围的 Runtime。

## Data Foundation 目标合同

```text
RQData
-> temporary staging
-> normalization + six hard validations
-> monthly Canonical Parquet
-> PostgreSQL eight-table catalog and metadata
-> MarketDataService
-> Market Web / Indicator / future research
```

- RQData 是唯一外部行情事实源；Canonical Parquet 是唯一 active 历史 Bar 存储；PostgreSQL
  不保存 K 线。
- Data Foundation / Market Catalog 始终精确为八表。经明确设计的 Application Domain 可以新增不属于
  Market Catalog 的应用表；Alert V2 使用 `alert_rules` / `alert_events` 两张表，Execution Review 使用四张 `trade_*` 表，均不属于且不改变八表 Market Catalog。
- active universe 唯一入口是 `data/universe/active_products.txt` 的 60 品种；股指
  `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu`
  已退役，见 `retired_products.txt`。历史下界为
  `active_history_floor=2023-01-01`。
- 七周期固定为 `1m/5m/15m/30m/60m/1d/1w`。基础 provider 周期是 `1m/1d`；`1w` 只从完整同源
  日线聚合，`5m/15m/30m/60m` 只从 Canonical 1m 聚合。
- 物理 Dataset 只有 `continuous` 和 `contract`；`actual_dominant` 在查询时按 rank1
  `MainContractMap` 拼接。
- 每 Dataset 每自然月只保留一个 `part.parquet`。可用性由完整 coverage、row count 和文件可读性
  确定；不维护第二套发布、缺口或 checksum/digest 内容摘要状态。
- 所有消费者共用 `MarketDataService`，不得 glob、自选文件、自判主力或跨频回退。

### 已冻结的五条架构原则

以下原则是后续功能开发的固定前提，不因新增研究功能而重构或扩展其边界：

1. **Data Foundation Frozen**：不得因新功能修改 `DatasetKey`、八表 Catalog、Canonical 语义或“每
   Dataset 每自然月一个 `part.parquet`”的月分区模型。
2. **唯一 Historical Gateway**：`MarketDataService` 是所有新研究功能读取历史行情的唯一入口；新功能
   不得直接读取 Parquet，也不得复制历史行情 resolver。
3. **Live 永远是 Observation**：Live 只存在于 Redis Overlay；不得写入或提升为 Canonical，也不得作为
   正式历史事实。
4. **读模型优先**：可以由 Canonical 和现有 Catalog 计算得到的市场事实，必须按需计算；不得为其新增
   Catalog 表或长期数据副本。只有经明确业务设计、且不属于 Market Data Foundation 的应用事实才可
   进入独立 Application Domain 表。
5. **模块长期性与功能价值审查**：每新增一个模块，都必须先回答“个人使用真的需要长期维护这个模块吗？”；
   答案不明确时，不创建该模块。新增功能还必须至少明确实现以下一项：减少个人盯盘时间、提高发现研究机会
   的概率、提高人工观察与研究执行的一致性，或增加未来复盘研究的证据；四项均不满足时，不做。

当前用户接口为 Market Web、`/trade-records`、`/api/v1/market/*`、`/api/alerts/*`、`/api/execution-review/*`，以及 `guiyi data
update|refresh|audit|after-market`、只读 `guiyi research subing-calibration`、`guiyi research subing-lifecycle`、
`guiyi research n-structure`、`guiyi research jdj-1m`、`guiyi research candidate-validation`、`guiyi research candidate-robustness`、
`guiyi research candidate-dossier`、`guiyi research main-force-mirror-v2` 和 `guiyi runtime
status|live|alert|alert-canary`；其中 `alert-canary --audience owner|htdy_observers` 是独立真实通知 Gate。
这些命令都不能由普通只读测试授权。
`main_force_mirror_v2` 是主力照妖镜唯一 active identity，仅作为
`60m + contract|actual_dominant` Historical confirmed observation。行情仅经
`MarketDataService`，席位上下文仅经钉住的不可变 `main_force_member_rank_v1`
snapshot；Web 底部副图只有 `MACD | 主力照妖镜 V2`。V0/V1 已退役，仅由 Git
history 追溯。真实 member snapshot 与 retrospective matrix 尚未执行；本研究面不读
Live、不进入 Alert/notification/Runtime 或订单路径，`auto_order=false`。
`research n-structure` 只读取 Historical Canonical，经共享行情入口生成 research-only 观察；它不写数据、
不进入 Runtime，不证明效果，也不授权 candidate promotion。N Structure V1 的长期业务语义由本节、
`docs/ARCHITECTURE.md`、exact policy 与对应测试共同定义；历史 Plan/Task 只从 Git history 追溯。
`research jdj-1m` 通过同一个 `ActualDominantResearchSegmentLoader` 一次读取 exact 1m/5m
actual-dominant true segment prefix，以 existing N Structure 5m facts 投影 strict-before 1m context，
再分别运行 Trend Follow、Trend Reentry 6、Key-Level Breakout 三个 causal reducer。三条 Candidate
只产生 immutable trigger/outcome research facts；Candidate Validation 复用既有 10-fold schedule，
prospective 首日冻结为 `2026-08-24` 且当前 pending。它不建立 backtest/fill/order/position/cost/equity、
不自动排名或晋升，也不进入 Alert/Runtime。
`research candidate-robustness` 只比较已冻结的 SuBing/N exact Candidate research facts：复用各自
Candidate Validation 生成 anchor temporal dossier，在冻结 active60 上保留完整 120-cell 矩阵，
并且只在 same symbol + same physical contract + same rank1 segment 内比较 `jm` 双向 causal
event relationship。它不改变 Candidate/公式/参数，不做自动排名或晋升，不写
DB/Canonical/Redis，不进入 Alert/Runtime/订单路径，也不形成盈利、有效性或交易结论。
同一 CLI 的 exact Phase 7 入口为
`guiyi research candidate-robustness --protocol jdj_active60_robustness_v1`：它只按冻结的
`2023-01-01..2026-08-20` retrospective 从 `MarketDataService ->
ActualDominantResearchSegmentLoader` 读取 Historical Canonical，以单品种一次共享 1m/5m source
复算三条冻结 JDJ Candidate，形成完整 `3 × 60 = 180` 个品种、年度和 symbol-balanced 板块事实。
该 protocol 不消费 `2026-08-21` embargo 或 `2026-08-24+` prospective OOS，不接受运行时窗口、
品种、阈值、score 或 rank；只输出一份版本化 stdout JSON evidence，不写 DB/Canonical/Redis，
不进入 Alert/Runtime/订单路径，也不产生 ranking、KEEP/DROP/PROMOTE 或效果结论。
Phase 8A exact 入口
`guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1` 只读组装七份
Git-tracked immutable source artifact：五份 source-specific Candidate baseline 与两份既有
robustness evidence。它不读 `MarketDataService`，不重算行情、Candidate、metric 或
relationship。五条 Candidate 保留各自 retrospective window：SuBing
`2023-01-01..2026-08-18`、N `2023-01-01..2026-08-19`、三条 JDJ
`2023-01-01..2026-08-20`；不建立 common five-Candidate window。十个 pair 只投影显式
comparability status：SuBing/N 复用已有 relationship reference，SuBing/JDJ 为 cross-timeframe
not comparable，N/JDJ 的 pair metric 尚未定义，JDJ 内部为 same-family comparable。
comparability 不等于 relationship，该 dossier 不为其他 pair 新建 relationship evidence；不写
DB/Canonical/Redis，不进入 Alert/Runtime/订单路径，也不产生 Candidate 优劣、有效性、
盈利、可交易或可晋升结论。
Market Runtime 的 Live 与盘后更新共用
`operational_products.txt`；当前目标与 active 60 完全一致。Live 只观察
当日 rank1 completed 1m，盘后最多在 18:05 和一次一小时后 retry 更新相同范围，Live 永不提升为
Canonical。DFD-01～DFD-07 和 60 品种 Canonical 闭环已经完成，长期规范位于 `openspec/specs/`；现有旧
入口不能作为当前合同依据。

## Alert V2 应用边界

Alert V2 只保留两条 code-defined Rule：`htdy_original_15m` 复用 `MarketReadService.bars_until()` 的 event-cutoff 窗口与 Python Indicator Kernel；`subing_entry_signal_v1` 只消费现有 current-rank1 segment-local `SubingReadService` 产出的 `resolved_signal`，复用 Factor、accepted Calibration、FormalPolicy 和 same-boundary resolver，不在 Alert 中复制公式、阈值或 5m/15m 优先规则。

SuBing 只在 incoming completed Bar 与 current snapshot 的 `bar_end` 和 `trading_day` 同一时创建 Event，stale 或不可用状态 fail-closed。final Session Bar 只在 Live 共享的有界 arrival grace 内可见；该 phase observation 不建立 `snapshot_at`/cutoff/replay 路径。5m 事件落在同一 15m boundary 时依既有 TradingSession bucket 语义延后，继续由 15m snapshot 唯一决议。HTDY event-cutoff 语义不变。

当前交易日仅由既有 `MarketPhaseResolver` 对 `operational_products.txt` 品种集唯一解析；存在缺失或不一致时 API fail-closed 为 `unavailable`，不用自然日或 Event `bar_end` 猜测。Event 先提交，然后 develop 的 `AlertNotificationDispatcher` 最多调用一次 PushPlus SDK：HTDY 路由到 `htdy_observers` Topic，SuBing 路由到不带 Topic 的 `owner`。`notification_attempted_at` 表示 Runtime 已进入该一次发送阶段，SDK shortCode 只表示 provider 接受请求，二者都不表示微信已送达。无 replay/backfill/retry/outbox/queue/逐人 fan-out/Signal Center/订单路径。SuBing Rule 的 migration seed Scope 为空集。

PushPlus 消息 token 与 HTDY Topic code 只存于 Git 外的单份 `0700` parent / `0600` private JSON，不写入仓库、日志、health 或 Event。Runtime 只公开两个逻辑 audience 与脱敏 shortCode 后缀，不调用开放接口查询 Topic 成员。owner 与最多三位朋友在 PushPlus 外部扫码加入专用 Topic；创建者也必须加入。Topic 可在 `1..4` 人边界内先以当前成员启用，后续增加成员仍由 operator 人工核对且不得超过 4 人。

Alert 代码与 launchd 模板默认关闭。当前 deployed Alert exact-tag `v1.6.5` 使用 PushPlus：HTDY 只向 `htdy_observers` Topic，SuBing 只向不带 Topic 的 owner，两条 Rule Scope 均精确为 `jm`；各服务的实际部署身份只由 `STATUS.md` 记录。Git 外配置、owner/Topic 历史 canary、v1.6.5 Alert Runtime switch 已完成；自然 HTDY/SuBing Event 验收仍 pending。未来 Scope/transport 变化、后续 release/tag、再次 Runtime switch、真实 canary/send 与 rollback 仍是互不授权的受控外部操作；代码、测试、测试路由 Scope PUT、fake seam、render-only 或已经完成的 Gate 不证明未来 Gate 获得授权。

## Execution Review V1 应用边界

Execution Review 只消费不可变的 `subing_entry_signal_v1` AlertEvent，保存人工 Decision、固定真实合约/方向的 Episode、真实手工 Execution timeline 与结构化 Review。一个品种最多一个 OPEN Episode；不跨合约合并、不自动反手、不连接账户或创建订单。历史重建只经 `MarketDataService`，默认截止 Signal 时点；roll reconcile 是默认关闭、独立授权的估算关闭路径。

Multiplier 使用 trusted-partial 官方证据合同：reference 与 official evidence 集合严格相等且只是 active 60 的子集。缺失 multiplier 不阻断 Decision/Execution/Review，只使人民币估算不可用；realized points 与仓位拓扑仍可用。Episode 创建时 snapshot，当时为 NULL 的历史记录不因后续 reference 扩大而自动改写。完整业务语义见 `docs/EXECUTION_REVIEW.md`。

## 工程与外部操作

普通仓库开发可以在 `develop` 或任务 worktree 中实现、测试、commit 和 push。真实 RQData、
正式 Canonical 写入/切换、生产数据库 mutation、Runtime/live、真实通知、release/tag 等均需执行前
获得范围明确的一次性意图；dry-run 不授权后续 mutation。Market Runtime V1 例外仅在用户明确请求启用
该本地工作站后生效：该一次启用允许 `operational_products.txt` 明确列出的 Live 与盘后有限自动化持续运行，不授权任何其他 DB、
release、通知或订单动作。

Alert Runtime V2 只有在用户对识别出的本地工作站明确执行 promotion，且目标 Scope 已获得精确 Rule + Product 授权后，才获得独立、有界的持续授权：

```text
htdy_original_15m × 该 Rule 显式 scope_products × htdy_observers × pushplus-wechat-topic
+
subing_entry_signal_v1 × 该 Rule 显式 scope_products × owner × pushplus-wechat
```

当前 deployed Alert exact-tag `v1.6.5` instance 的两条 Rule 各自 `scope_products=jm`，PushPlus 持续授权只覆盖之后新建的自然 AlertEvent，并精确保持 HTDY Topic / SuBing owner 路由；可变运行事实只由 `STATUS.md` 记录。已批准 Topic 在 `1..4` 人内的成员加入不改变代码或 transport；超过 4 人、未知成员或更换 Topic 必须重新授权。该授权不覆盖未来第三条 Rule、synthetic Event、replay/backfill、额外 canary、migration、再次 Runtime switch、后续 release、Canonical 写入、订单或 rollback。未来 Scope 变化仍必须独立执行精确 Rule + Product activation，不能从 Market Runtime V1、既有 Scope 或其他 Gate 推导授权。

当前本机部署根属于可变运行事实，只由 `STATUS.md` 记录。功能开发期可临时从 `develop` 部署以便快速观察；最终 Runtime 采用绑定精确提交的独立 worktree，验收读回身份、拓扑、健康和范围。已经在同一代码谱系形成且由用户接受的自然时点证据不因部署封装重复采集；开发态部署仍不等于 Ready、release 或 Runtime promotion。

任何结论只证明其精确验证范围；不由代码、测试或数据存在推导盈利、长期稳定、交易或 Runtime Ready。

## 文档职责

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则 |
| `STATUS.md` | 当前实施状态与未执行外部操作 |
| `PROJECT_SOURCE.md` | 长期产品与系统边界 |
| `DECISIONS.md` | 当前有效长期决策 |
| `docs/ARCHITECTURE.md` | 项目分层和组件边界 |
| `docs/DATA_CENTER.md` | Canonical 数据合同 |
| `docs/EXECUTION_REVIEW.md` | Execution Review 业务语义 deep canonical |
| `openspec/specs/` | 当前数据与查询行为规范 |
| `TESTING.md` | 当前可执行验证入口 |
