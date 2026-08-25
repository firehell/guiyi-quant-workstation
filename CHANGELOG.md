# Changelog

本文件记录正式产品版本；开发过程与逐品种执行流水从 Git history 追溯。

## [1.8.3] - 2026-08-25

- HTDY original 观察能力扩展到 Active60 的七个正式周期 `1m/5m/15m/30m/60m/1d/1w`；日内五周期只消费
  同周期 completed Live Bar，D1/W1 只复用既有 `canonical_updated` seam 读取 Canonical，不新增第二套
  Live 聚合、scheduler、retry、replay 或 backfill。
- HTDY Scope 唯一权威收口为 `symbol × frequency` pair，Event identity 纳入 frequency；旧 HTDY Scope
  migration 只继承原有 15m ON，SuBing 继续使用 `scope_products` 与 bar-level business identity。
- Market K 线支持七周期 HTDY Overlay、frequency-aware marker/cache 与当前 `symbol × frequency` 单开关；
  切换图表周期或 Overlay 不写 Scope，持久 Event 只展示实际命中周期。
- 本版包含 Alembic `20260825_0040`，但 release 不执行 production migration，不修改真实 HTDY Scope，
  不切换 Runtime、不发送真实 PushPlus、不写 Canonical/production Redis，也不增加订单能力；
  `auto_order=false` 不变。

## [1.8.2] - 2026-08-25

- 收敛 Market 首页为中文研究工作台：Runtime / Live / Alert 等状态采用中文、去除自选入口与列，
  全市场明细直接展示；价格变化 × 持仓变化改为不重叠的四象限完整名单，保留唯一品种入口。
- 品种详情首屏与向左历史分页均为 300 根 K 线，默认视图固定到最新 300 根，避免 Live 尾部或长历史
  被压缩至不可读尺度并降低首屏指标计算负担。
- 桌面端详情工作区改为占满工具栏和状态条以下的可用视口；主图、成交量/副图与“当前检查栏”等高，
  检查栏内容超出时独立滚动，窄屏仍使用既有抽屉布局。
- 本版不新增 migration，不写 Canonical、production DB/Redis，不改变 Alert Rule Scope/transport，
  不加载 RQAlpha sidecar、不运行手工 after-market 或真实通知，也不增加订单能力；`auto_order=false` 不变。

## [1.8.1] - 2026-08-24

- 新增 active60 单产品 `actual_dominant + 1m` 日进斗金 Historical reference replay；保持 JM
  pre-refactor golden exact parity、真实 rank1 segment identity 与 research-only action/fill 边界，不进入
  DB、Redis、Alert、Execution Review、Runtime consumer 或订单路径。
- 新增 SuBing Daily Watch V1：盘后成功后为 active60 生成下一交易日使用的不可变观察账本与 current-only
  API，Market 首页以“苏冰今日观察”替换 Trend Focus，并提供一次性
  `actual_dominant + 15m + subing` 图表入口；不改写全局图表偏好，盘中不重算。
- Daily Watch Store 只允许经校验的扩展盘根；目录和原子文件 mutation/replace 前重复校验 mount，禁止
  系统盘 fallback。同 target 失败使 current fail-closed，snapshot 严格校验 decision、reason、D1/H1
  facts 与 price-side，并以重构前 5m/15m 六字段 golden 锁定 EMA21/slope exact parity。
- 完成 No-Watch Reliability V1：Alert Runtime 与盘后任务写入 crash-visible 只读状态，Market 首页展示统一
  Runtime strip，data audit 支持 opt-in stderr NDJSON progress；失败观察不新增 retry/replay/backfill。
- 本版不新增 migration，不执行 Canonical、production DB/Redis 写入，不改变 Alert Rule Scope/transport，
  不加载 RQAlpha sidecar，不运行手工 after-market 或真实通知，也不增加订单能力；`auto_order=false` 不变。

## [1.8.0] - 2026-08-24

- 纳入 local-only、research-only 的 RQAlpha Plus Web 工作台：浏览器仅在 loopback 使用独立 sidecar，
  只读外部 Bundle、只写仓库外 artifact；不接主 API、Canonical、DB、Redis、Alert、Execution Review、
  Runtime、Candidate/OOS 或订单。sidecar 不随本 release 加载，真实 smoke 仍是独立人工 Gate。
- 纳入 JM `actual_dominant + 1m` 日进斗金参考策略 Historical replay 与 Market reference marker；
  只复用既有 Candidate reducer 输出 deterministic reference action，不形成正式回测、交易指令、
  Alert 或持久化结果。
- 纳入 Market Historical Research Overlay、Trend Focus 只读读模型与 Main Force Mirror Diagnostic Phase A
  的 CLI/composition/payload 边界；诊断的真实 JM/active60 evidence Gate 仍 pending，不产生策略、
  Alert、Runtime 或晋升结论。
- 本版不新增 migration，不写 Canonical、production DB 或 Redis，不扩大 Alert Scope/transport，不执行
  通知 retry/replay/backfill，也不增加订单能力；`auto_order=false` 不变。

## [1.7.0] - 2026-08-22

- 收敛 Runtime seam：离线 Research 组装从 Market/Alert/Runtime 依赖方向中移出，Research CLI 拆为
  parser/request/command/payload 边界，`app.runtime_entry` 成为 Live、Alert、after-market 的唯一内部
  进程入口；Execution Review 读写/查询/reconstruction composition 继续独立。
- 严格化 Execution Review roll Gate：HTTP request-scoped composition 每请求读取一次 marker 并注入
  callback；missing、`disabled` 或 `invalid` 注入返回 `ROLL_RECONCILIATION_REQUIRED` 的 fail-closed
  callback 且不创建 `DOMINANT_ROLL`，只有精确 `enabled` 才注入真实 reconciler。
- Research 实现去重并收口测试治理：共享 exact identity/JSON contract 与 price outcome，拆分
  `tests/research`、`tests/execution_review`，完成 Five-Candidate Phase 8 dossier/relationship topology、
  JDJ active60 robustness 与 MFM 60m sequence forensic 代码；MFM 的真实 read-only evidence Gate 仍未执行，
  不产生 Phase 冻结或晋升结论。
- 完成 Market Web B1 决策漏斗：首页“需要处理 → 优先检查 0..3 → 全市场研究”，详情页固定使用
  “当前检查栏”验证顺序；保持 degraded fail-closed、正式 Event/研究观察/Research-only 分层，
  不增加评分、推荐或交易语义。
- 本版不新增 migration，不写或修改 Canonical、production DB、Redis，不扩大 Rule Scope，不新增通知
  retry/replay/backfill，也不增加订单能力，`auto_order=false` 不变。release PR `#197` 已合入 main，
  annotated `v1.7.0` tag 与 production Runtime 均精确绑定
  `4fe0644694ab9f534c61e0d48eae3f01a74fc7c0`；切换未运行 after-market、canary 或人工通知。

## [1.6.5] - 2026-08-21

- 修复 SuBing research overlay 侵占 Market K 线展示身份的问题：切换 overlay 不再强制
  `contract/current rank1`、截断基础 bars 或收紧向前分页；用户选择的 `continuous | contract |
  actual_dominant`、合约与周期持续由 Market 查询链决定。SuBing 仍只作为与当前展示并列的研究快照，
  不可用或加载中不会清空已验证的 Market display series。
- 纳入 JDJ 1m research-only Candidate V1：冻结 exact policy、三条独立候选 reducer 与 Validation
  protocol；所有输入仍仅经 `MarketDataService`，不读 Live、不写 DB/Canonical/Redis、不进入 Alert、
  Runtime、订单或自动晋升路径。
- 纳入 Multi-Candidate Robustness V1 的冻结 active60 historical evidence；它保留 typed-unavailable
  cells 和同 symbol / physical contract / rank1 segment 的因果边界，不生成 ranking、winner、收益或
  可交易结论。
- 本版不新增 migration、Canonical/生产 DB 写入、Scope 扩大、历史 Event 补发、真实通知重试或订单能力，
  `auto_order=false` 不变。

## [1.6.4] - 2026-08-20

- 修复 SuBing current snapshot 在 `Canonical edge < now` 时错误把 wall clock 作为 strict Historical
  cursor、触发 `DATASET_OR_PARTITION_MISSING` 的问题；5m/15m 现在分别依据各自 Canonical edge 选择
  latest-page bootstrap 或历史 strict cursor，并在并发发布出现 cutoff 后 Bar 时 strict 重读，保持
  Factor/Signal/Lifecycle 的因果边界与 300-Bar projection。
- SuBing snapshot 明确失败时，Market Web 保留已经成功加载的当前合约 K 线；loading 阶段仍不暴露未知
  rank1 segment 的旧 Bar，error fallback 也不放宽向前分页边界。
- develop 的 Alert transport 由 Clawbot 收敛为 PushPlus：HTDY 每个 Event 对 `htdy_observers` Topic 发起
  一次请求，SuBing 每个 Event 只发给不带 Topic 的 owner；保持 Event-first、无 retry/replay/backfill、
  两条 Rule Scope 均仅 `jm`，PushPlus 接受请求不等同于微信最终送达。
- 纳入 reviewed N Structure V1 causal research domain 与冻结 `jm` retrospective baseline；prospective OOS
  仍为 pending，仅是 research asset，不形成策略有效、盈利、Alert、Runtime consumer 或晋升结论。
- 修复 fresh-root Runtime activation 顺序：marker 在服务启动前原子建立；任一 bootstrap/enable/kickstart
  失败会逆序停止本次触碰的 label 后恢复旧 marker，无法确认停止时保留 enabled marker，避免形成“进程
  仍运行但 health 显示 disabled”的假安全状态。
- 本版不新增 migration、Canonical/DB 写入、Scope 扩大、历史 Event 补发、真实通知重试或订单能力，
  `auto_order=false` 不变。

## [1.6.3] - 2026-08-20

- 修复 Market Radar 在同日盘后 Canonical 更新窗口内将理论目标日直接作为参与门槛、误报全市场
  `0/60 stale` 的问题；Radar 现在区分 `target_as_of` 与统一计算使用的 `data_as_of`。
- 当目标日尚未 60/60 时，继续展示严格早于目标日的最近完整 Canonical 快照，并以
  `pending_after_market / 盘后更新待完成 / status=ready / 60/60` 明示 freshness；目标日全部发布后
  自动恢复 `current`，跨自然日真实缺失仍只降级对应品种。
- API 以加法方式新增 `target_as_of`、`data_as_of`、`freshness_state`、`freshness_message`，保留
  `expected_as_of` 作为 `target_as_of` 的兼容别名；Web 同时展示数据日、目标日与三态中文标签。
- Radar 仍只经 `MarketDataService` 读取 Canonical 日线；本版不包含 Redis/Live Radar、临时 D1、
  migration、PushPlus、N Structure、Scope、通知、数据写入或订单能力，`auto_order=false` 不变。
- 本条首先形成 Radar-only release candidate；正式 main/tag/release 与 production Runtime 切换仍是
  两个独立的单次 Gate。

## [1.6.2] - 2026-08-20

- 新增 60m、`contract | actual_dominant` 的 `main_force_mirror_futures_v1` Web observation 与
  Historical-only Shadow；保持五状态、双向警戒、21/31 根 readiness、conflict/latch、物理合约分段和
  Python/Web 单一 golden 合同，不授予 Alert、notification、正式 backtest、Runtime consumer 或订单能力。
- 纳入 SuBing Candidate Validation V1 的只读 historical baseline/rolling-fold 研究合同与已冻结 jm
  retrospective evidence；不生成参数晋升、策略有效性或 Runtime 结论。
- 纳入 N Structure V1 的设计与实施计划文档，仍为未实现规划，不形成代码能力、数据写入或发布授权。
- 修复 actual-dominant 换月后 Pane 状态可被左侧旧合约 ready 点覆盖的问题：可见状态严格取最右侧 point/
  当前物理合约 block；真实 AG2601→AG2612 浏览器回归锁定换月后 10/21/31 根 warm-up、hover identity
  与 marker 不继承。
- 将 `main_force_mirror_v0` 运行时源码逐字恢复到 V1 开发前冻结版本；静态类型由同名 `.pyi` 单独承载，
  并以源码 hash 守卫防止后续“仅类型/格式”漂移。公式、输出、版本、golden 与 capability 均未改变。
- 本条首先形成 develop candidate；正式 main/tag/release 与 production Runtime 切换仍需各自独立 Gate。

## [1.6.1] - 2026-08-19

- 修复日盘收盘后、Canonical 盘后更新接管前刷新或切换 Market K 线时，当日已完成 Bar 消失的问题；
  Market WebSocket 新增只读 `post_close` 展示快照，并在 Canonical edge 前移后按 `bar_end` 无缝交接。
- `post_close` 仅限 CLOSED phase、operational product、五个日内周期与 Redis subscription 精确身份，
  Redis/交易日/合约异常均 fail-closed；它不依赖 heartbeat，也不会被视为 realtime Live。
- 不改变 `live_snapshot()`、`bars_until()`、SuBing、Alert、Redis TTL、18:05 调度、Canonical、Catalog、
  MainContractMap、数据库或通知语义；production Runtime 在独立 promotion Gate 前继续保持 `v1.6.0`。

## [1.6.0] - 2026-08-19

- 新增 causal、`observation_only` 的主力照妖镜 V0：Python Indicator Kernel 为唯一数学口径，Web
  在现有最底部副图以 `MACD / 主力照妖镜` Tab 二选一，默认仍为 MACD；六色柱仅为 OHLCV
  设计代理，“小心”保持 `rising_edge(BARSLAST(HIGH=HHV(HIGH,5))<10)`。
- 加入完整 SuBing Lifecycle V2 research-only 代码链：exact policy、不可变领域合同、
  causal ConfirmedPivot/Breakout/Retest/lifecycle reducer、additive API/Web 生命周期与独立研究 Marker、
  Historical-only Shadow CLI；不改 V1 正式信号、Alert Rule/Scope/Runtime 或通知。
- 不新增 DB/migration、Canonical、Redis、Scope、通知或订单行为，`auto_order=false` 不变；
  production Runtime 在取得独立 promotion 授权前继续保持 `v1.5.0`。

## [1.5.0] - 2026-08-19

- Alert 通知代码由 WeCom 收敛为唯一 Clawbot/OpenClaw-Weixin single-shot transport，保持 Event-first、
  每个 Event 最多一个 child/一次 `sendMessageWeixin()`，无 retry/replay/backfill/fallback；rollout
  G2～G5 已通过，production 在独立 G8 promotion 前仍保持 WeCom。
- 修复 Market Live stale-feed 恢复路径，并收口 HTDY 图表观察层的高对比展示与说明。
- 不改变 Rule/Scope、Alert DB/Event identity、Canonical、Execution Review、RQData 或订单边界；
  `auto_order=false` 不变。

## [1.4.2] - 2026-08-17

- 盘后一小时后 retry 仅允许 `NEXT_TRADING_SESSION_NOT_READY`；其他失败首试即结束，
  并按实际执行次数公开 `attempts=1`。
- 不改变 18:05 自然调度、Historical/Live seam、operational 60、Alert Scope、通知或订单边界。

## [1.4.1] - 2026-08-17

- 新增共享可选 EMA 显示开关，并完成 v3 本地偏好迁移；指标计算公式保持不变。
- 后端、Alert、Runtime 与数据边界保持不变。

## [1.4.0] - 2026-08-16

Execution Review V1：

- 新增 `/trade-records` 与 `/api/execution-review/*`，以独立的 Decision / Episode / Execution /
  Review 四表 Application Domain 保存苏冰 Formal Signal 的人工决策、真实手工执行时间线与结构化复盘；
- 支持 origin Signal 形成 OPEN、同方向同合约 later Signal 形成 ADD，以及人工
  ADD/REDUCE/CLOSE；不连接账户、不创建订单，`auto_order=false` 不变；
- 历史行情 reconstruction 只经 `MarketDataService`，并提供默认关闭的有界 `DOMINANT_ROLL`
  reconcile 能力，不调用 RQData、不写 Canonical、不伪造真实 CLOSE；
- 新增 Lightweight Stats，仅呈现机会、处理、执行、Episode 状态、未执行原因与结构化复盘标签，
  不提供胜率、Sharpe、PnL ranking 或策略盈利结论；
- multiplier 采用 trusted-partial official reference，当前 coverage 为 `7 / 60`。缺失 multiplier
  只令人民币 Estimated Gross PnL unavailable；realized points、仓位拓扑、时间线与 Review 仍可用，
  `60 / 60` 不属于 v1.4 release Gate。

## [1.3.1] - 2026-08-15

Market Web 品牌视觉与错误态收口：

- Market 首页收敛为“需要处理 → Summary → 散点/值得关注 → 板块 Tab 明细”四层决策结构，
  正式信号两列换行，板块顺序及中位涨跌直接复用 Radar 返回事实；
- 首次加载使用分区骨架；手动刷新失败时保留页面内最后成功快照，同时明示旧快照时点、
  错误条和重试入口，不新增轮询或持久化；
- 深蓝品牌壳、浅色工作区、图表主题与 Marker `tone` 语义统一；SuBing 买入红/卖出绿、
  HTDY 橙色观察和 reduced-motion 合同保持一致；
- 删除旧板块概览组件、源码字符串型测试与重复图表色值定义，EMA/HTDY 色板只从
  `chartTheme`/CSS token 解析；
- 本补丁不改后端、HTTP DTO、DB、Canonical、指标公式、Signal 判断、Alert Scope、
  WeCom 或 `auto_order=false`。

## [1.3.0] - 2026-08-15

Decision Compression / Alert V2：

- 将 SuBing 5m/15m Formal Signal 接入现有 Alert Application Domain，与 HTDY 一起由
  `htdy_original_15m`、`subing_entry_signal_v1` 两条 code-defined Rule 和 single Alert Runtime 统一编排；
- Market 首页新增当前交易日“需要处理”，只展示 Formal Signal；Product Workspace 提供 HTDY/SuBing
  双 Rule 独立 Scope、当前交易日“今日记录”和 actual-dominant exact-frequency persistent Marker；
- Market Web 统一为高对比亮色界面，保留中国期货红涨绿跌与既有 Radar/Kline 能力；
- Alert V2 保持 Event 先提交、WeCom one-shot，无 replay、backfill、retry、Signal Center 或自动交易，
  `auto_order=false` 不变；
- annotated `v1.3.0` 已发布并部署到 exact peeled commit `d7b45ffcd563abe37963620de45fe41978e6c839`，
  production migration 已读回为 `20260814_0038`，五个应用 label 均从 clean/detached v1.3 Runtime 根运行；
- production HTDY Scope 保持仅 `jm`，SuBing Scope 保持 `[]`；本次未执行 SuBing Scope activation、
  真实 WeCom、replay/backfill/retry 或 natural SuBing canary。

## [1.2.0] - 2026-08-14

盘中观察与只读信号研究版本：

- 新增独立 Alert V1 Application Domain：只处理 server-side Scope 中自然到达的 actual-dominant
  confirmed 15m Bar，复用 Python HTDY current-bar evaluator，AlertEvent 先提交后最多尝试一次 WeCom；
  停机历史不 replay/backfill，发送失败不 retry；
- Product Workspace 新增 Alert Scope 控制与持久铃铛，只展示已记录 Event，不恢复旧
  Signal/Review/Strategy 应用链；当前生产 Scope 仍精确为 `jm`；
- 新增苏冰 current-rank1-segment-local Factor Observation、slope-only Calibration 与 5m/15m
  Entry Signal 只读观察；Zero-Band hard gate 已由 OOS evidence 拒绝，1d 保持非阻断
  `RESEARCH_PENDING`；
- SuBing Signal 只在 Product Workspace 展示，不持久化、不接 Alert、不自动晋升参数或 Runtime；
- 盘后目标调度由 17:00 收敛为 18:05，并显式分类下一交易日 Session 尚未就绪；Live 与 Historical
  Canonical 继续分离；
- launchd 增加精确 loaded commit 身份核对，API/Web/Live/after-market/Alert 统一从 clean/detached
  Runtime 根运行；
- 完成 Alert、HTDY、苏冰、WeCom、DB Session 生命周期、Web composable 与文档一致性 Review 收口；
  `auto_order=false` 不变，不新增订单、自动交易、Alert V2、SuBing Runtime 或新的 Market Catalog 表。

## [1.1.0] - 2026-08-12

Market Research Workspace P0 封板版本：

- 全市场 Radar 通过只读 Research/Radar 服务覆盖 active 60，显式展示 `expected_as_of`、参与数、stale 与 unavailable；
- Product Workspace 提供真实主力/主连与七周期切换、轻量右侧研究摘要和本地自选；
- K 线固定为 `Kline + EMA / Volume / MACD` 三层，保留 Historical/Live seam、向左分页和 viewport；
- Research 继续只经 `MarketDataService` 读取 Canonical，未新增 provider 直连、研究表、历史 writer 或 DB migration；
- HTDY original 默认关闭，仅作为带未来引用/重绘风险提示的观察层；`auto_order=false` 不变；
- Runtime health 正确公开 after-market activation 状态；active/operational 继续精确为 60。

## [1.0.0] - 2026-08-12

首个封板候选，范围为本地单用户国内期货行情研究底座：

- 60 品种、七周期 Canonical Parquet 与八表 Catalog 完整闭环；
- `MarketDataService` 统一历史入口，actual dominant 按 rank1 map 查询拼接；
- Market Web/API、data/runtime CLI 与 Redis Live Overlay；
- operational 60 的 Live observation 和 17:00 盘后增量更新，Historical/Live 严格分离；
- 无 backtest、Signal/Review/Strategy 兼容面，无交易账户、订单或自动交易路径。

2026-08-12 的 60 品种 17:00 自然盘后于唯一一小时自动 retry 后完成，且 Session、
MainContractMap、Canonical edge 与 Live cleanup 只读验收通过；本版本据此封板。
