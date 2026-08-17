# Changelog

本文件记录正式产品版本；开发过程与逐品种执行流水从 Git history 追溯。

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
