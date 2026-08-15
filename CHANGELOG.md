# Changelog

本文件记录正式产品版本；开发过程与逐品种执行流水从 Git history 追溯。

## [1.3.0] - 2026-08-15

Decision Compression / Alert V2：

- 将 SuBing 5m/15m Formal Signal 接入现有 Alert Application Domain，与 HTDY 一起由
  `htdy_original_15m`、`subing_entry_signal_v1` 两条 code-defined Rule 和 single Alert Runtime 统一编排；
- Market 首页新增当前交易日“需要处理”，只展示 Formal Signal；Product Workspace 提供 HTDY/SuBing
  双 Rule 独立 Scope、当前交易日“今日记录”和 actual-dominant exact-frequency persistent Marker；
- Market Web 统一为高对比亮色界面，保留中国期货红涨绿跌与既有 Radar/Kline 能力；
- Alert V2 保持 Event 先提交、WeCom one-shot，无 replay、backfill、retry、Signal Center 或自动交易，
  `auto_order=false` 不变；
- 本条只记录已实现的 `v1.3.0` 代码事实，不表示 production migration、Runtime promotion、
  SuBing production Scope activation 或 natural SuBing canary 已完成。

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
