# 归一量化

本地优先、单用户的国内期货研究观察工作站。它围绕可信行情、通用指标、HTDY 观察、提醒与人工复盘构建，不做自动交易或账户/订单管理。

## 日常入口

- `/market`：Runtime 健康。
- `/market/chart`：主力连续 K 线、当日 Live、通用 EMA/MACD/Range、HTDY overlay 与 HTDY 提醒开关。
- CLI：`guiyi data ...` 与 `guiyi runtime ...`。

主图 Overlay 只有 **无 / 火天大有**。Web 不显示策略建仓、清仓、持仓或全历史策略效果。

EMA21 斜率只保留通用 10K 计算：10 个 EMA21 值、9 个间隔、输出 bps/bar。Daily Watch 方向过滤以及 5m/15m 正式因子均已退出 active surface。

## 工程入口

- [当前状态](STATUS.md)
- [稳定产品边界](PROJECT_SOURCE.md)
- [架构决策](DECISIONS.md)
- [Active Architecture](docs/ARCHITECTURE.md)
- [测试命令](TESTING.md)

真实数据、生产 DB、Runtime、Scope、通知、main、release/tag 均受独立明确授权约束。所有研究观察 `auto_order=false`。
