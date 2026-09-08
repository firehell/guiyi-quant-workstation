# 归一量化

本地优先、单用户的国内期货研究观察工作站。它围绕可信行情、Newow 只读策略与参考交易、通用指标、HTDY/苏冰观察、提醒与人工复盘构建，不做自动交易或账户/订单管理。

## 日常入口

- `/market`：Runtime 健康、completed D1/W1 市场概览与当前 Alert Events。
- `/market/chart`：主力连续 K 线、当日 Live、Newow/HTDY/苏冰/Free 四视角、通用 EMA/MACD/Range 与只读参考交易。
- CLI：`guiyi data ...` 与 `guiyi runtime ...`。

通用主图 Overlay 只有 **无 / 火天大有**；Newow 使用独立 typed API 与 Workspace 图层。Newow 的 `BUILD/HOLD/CLEAR/FLAT`、Hint 和 ReferenceTrade 都是只读研究事实，不是模拟或真实持仓、订单、成交与账户收益。

EMA21 斜率只保留通用 10K 计算：10 个 EMA21 值、9 个间隔、输出 bps/bar。Daily Watch 方向过滤以及 5m/15m 正式因子均已退出 active surface。

## 工程入口

- [当前状态](STATUS.md)
- [稳定产品边界](PROJECT_SOURCE.md)
- [架构决策](DECISIONS.md)
- [Active Architecture](docs/ARCHITECTURE.md)
- [测试命令](TESTING.md)

真实数据、生产 DB、Runtime、Scope、通知、main、release/tag 均受独立明确授权约束。所有研究观察 `auto_order=false`。
