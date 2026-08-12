# Changelog

本文件记录正式产品版本；开发过程与逐品种执行流水从 Git history 追溯。

## [1.0.0] - Unreleased

首个封板候选，范围为本地单用户国内期货行情研究底座：

- 60 品种、七周期 Canonical Parquet 与八表 Catalog 完整闭环；
- `MarketDataService` 统一历史入口，actual dominant 按 rank1 map 查询拼接；
- Market Web/API、data/runtime CLI 与 Redis Live Overlay；
- operational 60 的 Live observation 和 17:00 盘后增量更新，Historical/Live 严格分离；
- 无 backtest、Signal/Review/Strategy 兼容面，无交易账户、订单或自动交易路径。

正式 `v1.0.0` tag 仅在 60 品种 17:00 自然盘后验收通过后创建。
