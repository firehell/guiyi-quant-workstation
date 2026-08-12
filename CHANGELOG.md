# Changelog

本文件记录正式产品版本；开发过程与逐品种执行流水从 Git history 追溯。

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
