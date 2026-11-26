# M1 · Market 生产者、消费者与保留依据

基线为 `f72f8f9adc4e`。2026-11-26 13:24 CST 对照正式 service-bindings 和各 binding 的实际 launchd label。Feed、Live、Alert、Reference 和首页派生运行于 `v1.16.141`／generation 94。API、Web 运行于 `v1.16.146`／generation 95。盘后维护、迟到修复和周审计已登记为启用，本次读取时进程空闲。独立快期和苏冰 Paper label 均有运行进程；此处只记录进程与引用，账户自然推进和成交需另有证据。 [部署与保留入口](../../../../deploy/README.md) · [绑定读面](../../../../services/quant-api/app/runtime_bindings.py)

## 生产、存储与恢复

| 链路 | 生产者、用途与接续 |
|---|---|
| 日历、Session、合约和主力 | RQData 元数据经 `metadata`、每日 `day_preparation` 写入 Catalog。物理合约及其寿命、交易日、Session 和 rank1 owner 校验由归一掌握。Live 侧 `contract_preparation_runtime` 完成已批准合约历史准备。候选沿用这些入口及现有活跃/运行品种边界。 |
| 历史维护 | `guiyi data`、18:05 `after_market` 和获准迟到修复共用 `HistoricalDataManager`。RQData 1m 加交易所 D1 是输入，四个日内周期以完整 Session 端点聚合，W1 从完整 D1 周派生。staging、硬校验、immutable Parquet、Catalog 事务和 MDS 读回继续承担历史权威职责。周审计独立只读。 |
| 盘中采集 | 正式 Market Feed 由 `RQDataLiveProvider` 接受已完成 1m，以获授权物理合约写入按交易日分区的 source ObservationStream。Live 由 `StreamLiveProvider` 续读该 stream，`DurableLiveMarketService` 校验来源、时段及水位，聚合并写 completed stream 和 Redis 行情投影。候选 Tick 发布者复用同一正式输入合同，在隔离环境中作为唯一源，其米筐 1m 对照唯读。 |
| 报价、运行状态 | `RedisLiveStore`、行情 Pub/Sub 及 heartbeat、订阅快照是在线投影和可读性证据。候选报价和活动 K 线独立承接 Tick，按需有界读取，完成流保持分钟级原载荷。 |
| 盘后、核对与恢复 | `after_market`、`after_market_closeout`、`after_market_history` 维持盘后状态、锁和读回。实时普通缺口、已捕获源恢复和投影恢复分别通过 `live_recovery`、`captured_live_recovery`、`observation_restore`。各路径保留原始观察身份，历史修订不能伪造 first-seen 输入或推进旧订单。 |

[历史与 Session 合同](../../../../docs/DATA_CENTER.md) · [Feed/Live 装配](../../../../services/quant-api/app/market_data/composition.py) · [分钟身份、索引与水位](../../../../services/quant-api/app/market_data/observation_stream.py)

## 读取与消费者

| 消费者 | 输入、依赖与保留合同 |
|---|---|
| 行情工作台、自由看盘、通用指标 | `api.market` 历史通过 MDS，`api.market_live` 通过 MarketReadService 和有界 WebSocket 并发；首页 `MarketHomeLiveService` 使用 Catalog 和 Live 投影，`MarketHomeOverviewService` 维护已完成 D1/W1 派生读面。候选共用品种权威、系列身份与状态，活动行情只供显示。 |
| 牛哇 | 现役 `reference_trading.worker_entry` 从 completed stream 向独立 Reference Inbox 投递，`historical_refresh` 按历史合同时序更新。新 Market 盘后参考沿用历史读面、公式和 Reference 投影，必须由合格发布触发。已有参考记录、未决观察、消息定位和恢复闭包受保护。 |
| Alert | `alerts.composition` 通过其 completed stream 水位及 MarketReadService 查看合格窗口，盘后 D1/W1 使用现有 Canonical 更新入口。Scope、事件提交、通知资格与 one-shot 行为沿用原合同。预览与对照源不进入 Alert。 |
| 快期 HTDY | 隔离的 `tqkq-simulation` 使用 `tq_simulation_market`、`PortfolioMarket` 与 HTDY input admission 读取 1m 准入、60m 信号和合约权威；快期原生报价、委托、成交与对账仍来自该独立执行宿主。不可用旧观察或归档价格回填未知报单、成交、游标与旧月义务。 |
| 苏冰独立量化 | `subing_portfolio_worker` 从 completed journal 消费 1m／30m／60m，按交易日、物理合约和原 run 衔接。其 Paper 状态、执行事实、资金、模型事件及消耗水位归其原有 journal/store。独立账户域之间没有共享写入。 |
| 隔离 RQAlpha P3/P4 | `newow_backtest_job` 和 `newow_backtest_eod` 沿用其现有研究 MDS 冻结、凭证、私有结果库及版本化研究读面。保留已完成 run、逐笔、权益、限价与费用事实；Market 候选不会替这些研究结果起新调度。 |

[产品与依赖](../../../../docs/ARCHITECTURE.md) · [快期接入](../../../../services/quant-api/app/tq_simulation_market.py) · [苏冰 worker](../../../../services/quant-api/app/subing_portfolio_worker.py) · [RQAlpha P3/P4](../../../../services/newow-rqalpha/README.md)

## 收敛与退役条件

- 候选沿用 Canonical + Catalog、MDS、分钟 journal、Session-aware 聚合及生产者／消费者的事务边界。VeighNa 为同进程分发和隔离对照提供组件，原生历史库、DataManager 和 DataRecorder 不增加为正式依赖。 [组件与历史存储证据](storage/README.md)
- 盘后可再生行情投影以已确认归档的交易日为清理单位。source／completed 原件、identity 索引、各消费者水位、Reference Inbox／回执、独立委托成交、Paper 账本和旧研究输入冻结件按原合同保存。下一交易日夜盘由独立交易日 key 保护。
- 正式 Feed 的 1m provider、非 durable Live 入口和 legacy 牛哇前向 Reference 属于切换后复查项。它们当前有部署、显式兼容 mode 或恢复引用。候选路径统一到原有读取及发布入口，保留这些引用所需的代码；正式停旧前需验证绑定、源代次末水位、未决路由和可恢复记录。P3/P4 的 MDS 读取继续由研究域负责。
- 退役扫描应覆盖导入、部署配置、精确 release binding、活动进程、旧合约义务、回执及位点。与旧数据引用无关的候选实验产物可作为临时资源清理，现役支撑模块与保存中的历史原件继续可读。 [运行保留规则](../../../../deploy/README.md)
