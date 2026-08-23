# 归一量化项目事实源

更新时间：2026-08-23

## 稳定产品边界

归一量化是本地运行、单用户的国内期货研究工作站，服务可信行情、Market Web、指标与只读研究、
人工观察提醒和 Execution Review。它不做自动交易、实盘下单、账户/委托/持仓管理、SaaS、多用户、
高频/Tick 平台或 AI 自动晋升；所有页面、信号、通知和研究结论始终是观察事实，`auto_order=false`。

当前产品包含一个独立的 local-only、research-only RQAlpha Plus Web 工作台：它只运行 Git
注册策略、只读外部米筐 Bundle、只写仓库外文件系统 artifact，并且不挂载到主 API。它不是旧
backtest/Signal/Review/Strategy Web·HTTP·worker·queue 的恢复，也不是未来基于
Canonical/MarketDataService 的正式 Candidate/OOS 验证体系。当前工作台仅为仓库实现与自动化验证状态；
sidecar 未加载、未 release、未进入 Runtime，真实 RQAlpha smoke 仍是独立人工 Gate。Alert 与
Execution Review 是两个独立 Application Domain，不属于 Market Data Foundation。

## 稳定数据边界

```text
RQData
-> temporary staging
-> normalization + hard validation
-> monthly Canonical Parquet
-> PostgreSQL eight-table Catalog + MainContractMap
-> MarketDataService
-> Market Web / Indicator / read-only research
```

- RQData 是唯一外部行情事实源；Canonical Parquet 是唯一 active 历史 Bar 存储；PostgreSQL 不保存 Bar。
- active universe 唯一入口为 `data/universe/active_products.txt`；正式周期只有
  `1m/5m/15m/30m/60m/1d/1w`。
- Provider 基础周期为 `1m/1d`；`1w` 只从完整同源 `1d` 聚合，其他日内派生周期只从质量通过的
  Canonical `1m` 聚合。
- 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 只在查询时按
  `MainContractMap rank=1` 的有效区间拼接。
- 每 Dataset 每自然月只保留一个 `part.parquet`；schema、identity、OHLCV、session/frequency、
  coverage 或物理可读性失败时 fail-closed，并保留最后有效 Canonical。
- `MarketDataService` 是所有 Historical consumer 的唯一入口；consumer 不得 glob、自选 active、
  自判主力、绕过质量状态或跨频回退。
- Redis Live 只承载当日 observation；不得写入或提升为 Canonical，也不得替代 Historical 事实。

Data Foundation / Market Catalog 精确为八表。Alert 的 `alert_rules` / `alert_events` 与 Execution
Review 的四张 `trade_*` 表属于各自 Application Domain，不改变八表合同。

## 稳定产品接口

用户界面为 Market Web、`/trade-records` 与只在浏览器 hostname 精确为
`localhost|127.0.0.1` 时开放的 `/backtests`。主 HTTP 面为 `/api/v1/market/*`、
`/api/alerts/*`、`/api/execution-review/*` 和只读 Runtime health/status。RQAlpha 工作台只由固定
`127.0.0.1:8011` 的独立 app 提供 `/api/v1/backtests` 六路由，不进入主 API 或统一 CLI。统一 CLI
仍为 `guiyi data`、`guiyi research` 与 `guiyi runtime`；真实通知 canary 与真实 RQAlpha smoke
都是彼此独立的外部 Gate。

只读 Research 命令精确为：

- `guiyi research subing-calibration`
- `guiyi research subing-lifecycle`
- `guiyi research n-structure`
- `guiyi research jdj-1m`
- `guiyi research candidate-validation`
- `guiyi research candidate-robustness`
- `guiyi research candidate-dossier`
- `guiyi research candidate-relationships`
- `guiyi research main-force-mirror-v2`
- `guiyi research main-force-mirror-diagnostic`

`main-force-mirror-diagnostic` 仅接受冻结协议
`main_force_mirror_diagnostic_phase_a_v1`，通过同一个 `MarketDataService` 与
`main_force_mirror_v2` historical reader 形成 read-only retrospective diagnostic；它不替换
`main-force-mirror-v2`，也不增加任意窗口、阈值、模型、member dataset 或输出路径覆盖面。

`app.runtime_entry` 仅是受监督 Runtime 的内部进程入口；它不是第二套用户 CLI，也不能由手工运行产生
自然 Runtime evidence。

Market K 线的 Historical Research Overlay 只通过三个 source-specific 只读接口按需复算 confirmed
Canonical facts：`/api/v1/market/research/subing/history`、`/api/v1/market/research/n-structure/history`
与 `/api/v1/market/research/jdj/history`。三者只支持 `actual_dominant`，分别固定为 SuBing `5m/15m`、
N Structure `5m`、JDJ `1m`；各自保留独立 DTO、Policy、reducer 与 event identity，不建立统一 Strategy
adapter，不创建 AlertEvent 或持久化派生结果。

Market 首页“优先检查”只消费 `/api/v1/market/research/trend-focus` 的当前只读快照。该 read model
按请求从 Radar、`MarketDataService`、`MarketReadService` 与当前 rank1 physical contract 重算，输出
多/空新机会及运行/转弱趋势；不持久化、不接 Alert/Runtime/订单，也不生成综合分或交易推荐。

## 研究边界

- RQAlpha 工作台不读 Canonical/MarketDataService，不把 Bundle 宣称为归一量化数据事实。它只保存
  `research_only=true / formal_evidence=false / promotion_eligible=false` 的本机 RQAlpha 结果，
  不消费、回填或证明 prospective OOS，不产生 Candidate 晋升、策略有效性或可交易结论。
- SuBing、N Structure、JDJ 与主力照妖镜各自保留 source-specific Policy、时间粒度、因果 reducer 和
  Candidate/OOS 语义；不得为了统一展示建立 Strategy/Opportunity adapter 或修改既有公式。
- Historical Research 只通过 `MarketDataService -> ActualDominantResearchSegmentLoader` 或对应
  Market read service 读取 confirmed facts；不得读取未来 Bar。rank1 segment、physical contract、
  trading-day 与 strict-before 边界不完整时 fail-closed。
- Candidate Validation 只共享 request/error 与 rolling/prospective schedule。retrospective、embargo 与
  prospective OOS 必须分离；retrospective 不得回填 OOS，也不得从 evidence 自动产生 rank、winner、
  KEEP/DROP/PROMOTE、盈利、有效性或可交易结论。
- Robustness、dossier 与 relationship topology 只组合或复算既有 Candidate facts。source-specific
  window 不得伪装成 common window；comparability 不等于 relationship；N→JDJ strict-before dependency
  不等于独立确认，JDJ overlap 不得扩写为 proximity、lead/lag 或 future outcome。
- `main_force_mirror_v2` 仅支持 `60m + contract|actual_dominant` Historical confirmed observation，
  只读不可变 member-rank snapshot。sequence forensic 保持 same-contract、strict-prior、prefix-invariant，
  只输出预定义 profile 的事实，不选择 best profile，也不冻结正式 Phase。
- `main_force_mirror_diagnostic_phase_a_v1` 只消费 frozen active60 `2023-01-01..2026-08-18`；
  JM `2026-03-10..2026-03-30` 是同一 full causal input 内的固定 named view，单独输出 scoped
  label/sequence/funnel 或 typed unavailable，但不单独训练 model、计算 member feasibility 或形成 Gate。
  active60 整体只输出 label/sequence/funnel、deterministic model ceiling、member feasibility 与
  `STOP|ALLOW_PHASE_FREEZE_DESIGN` research Gate，
  不消费 `2026-08-19..20` 或 prospective 数据，不产生 PnL、rank、recommendation 或 promotion。
- Research 只输出 source-specific 只读 HTTP projection、stdout JSON 或显式版本化 artifact；不写
  DB/Canonical/Redis，不进入
  Alert/notification/Runtime/Execution Review/订单路径。

Historical Overlay 的事件只能落在当时可知的 evidence Bar：SuBing 使用 resolved `bar_end`，N 与 JDJ
使用 source event `observed_at`，不得回标 pivot/reaction/reclaim/first-break/retest。Web 只统一 capability、
confirmed Canonical 请求窗口、generation/full-identity 防旧响应、event-id 去重与 marker 渲染；不复制公式。
顶部固定为“无｜苏冰｜N字｜日进斗金｜火天大有”，JDJ 的 EMA20 只复用已有 EMA 展示算法，不参与浏览器
策略计算，也不增加 Candidate 开关或持久化设置。

Exact protocol、window、hash、row/cell count 与 artifact identity 只保存在对应 policy、report 和测试中；
当前 evidence 与 pending Gate 只看 `STATUS.md`。

## Alert V2 稳定边界

Alert Code Registry 只含 `htdy_original_15m` 与 `subing_entry_signal_v1`。HTDY 复用 event-cutoff
Historical window；SuBing 只消费现有 `SubingReadService` 的 current-rank1 segment-local
`resolved_signal`，不复制 Factor、Calibration、FormalPolicy 或 same-boundary resolver。

incoming completed Bar 与 current snapshot 的 `bar_end + trading_day` 不同一、当前交易日不能由
`MarketPhaseResolver + operational_products.txt` 唯一解析，或 Live arrival identity 不完整时
fail-closed。5m/15m 同 boundary 继续服从 TradingSession bucket 与既有 resolver。

AlertEvent 先提交，随后最多调用一次 transport。HTDY 路由到 topic audience，SuBing 路由到 owner；
provider 接受不等于微信最终送达。无 replay、backfill、retry、outbox、queue、逐人 fan-out、fallback
或订单路径。Git 外配置只含 transport 所需秘密，权限异常时 fail-closed。

## Execution Review 稳定边界

Execution Review 只消费不可变的 `subing_entry_signal_v1` AlertEvent，记录人工 Decision、固定合约/方向
Episode、真实手工 Execution timeline 与结构化 Review。一个品种最多一个 OPEN Episode；不跨合约合并、
不自动反手、不连接账户、不创建订单。历史重建只经 `MarketDataService`。

Multiplier 采用 trusted-partial 官方 evidence；缺失值不阻断 Decision/Execution/Review，只使人民币估算
unavailable。Episode 创建时 snapshot，reference 扩大不自动改写历史。

roll reconcile 默认关闭。HTTP request-scoped composition 每请求读取一次 Gate 并注入 callback；marker
missing、`disabled` 或 `invalid` 时 callback 必须返回 `ROLL_RECONCILIATION_REQUIRED` 且不创建
`DOMINANT_ROLL`，只有精确 `enabled` 才注入真实 reconciler。`record_executed` 不自行重复读取 marker。
完整业务语义见 `docs/EXECUTION_REVIEW.md`。

## 外部操作边界

普通源码、测试、文档和 `develop` commit/push 是开发行为。真实 RQData、正式 Canonical、生产 DB、
Runtime/live、真实通知、release/tag、Scope/transport 变化，以及加载 sidecar 并运行真实 RQAlpha
smoke，必须在执行前取得范围明确的一次性意图；
dry-run、代码、测试、health、历史 evidence 或既有授权都不能转换为新的 mutation 权限。

Market Runtime 与 Alert Runtime 的持续授权彼此独立，只覆盖各自被明确启用的有界范围；不授权订单、
未来 release、再次 Runtime switch 或其他数据/DB mutation。当前 release、Runtime、Scope 与 Gate 状态
只由 `STATUS.md` 记录。

## 文档职责

| 文件 | 唯一职责 |
|---|---|
| `STATUS.md` | 当前 release、Runtime、evidence 与 pending Gate |
| `PROJECT_SOURCE.md` | 稳定产品与系统边界 |
| `DECISIONS.md` | 长期决策及理由 |
| `docs/ARCHITECTURE.md` | 模块与依赖方向 |
| `docs/DATA_CENTER.md` | Canonical 数据合同 |
| `docs/EXECUTION_REVIEW.md` | Execution Review 业务语义 |
| `openspec/specs/` | 当前可执行行为规范 |
| `TESTING.md` | 当前可执行验证命令 |
