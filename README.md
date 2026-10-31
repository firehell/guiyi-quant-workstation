# 归一量化

本地优先、单用户的国内期货研究观察工作站。它围绕可信行情、Newow 只读策略与参考交易、通用指标、HTDY/苏冰观察、提醒与人工复盘构建，独立 SimNow 提供只读账户监控与 observe 宿主，页面不提供交易操作，当前 `auto_order=false`；执行模块与未来阶段边界见稳定产品文档。

## 日常入口

- `/market`：Runtime 健康、completed D1/W1 市场概览与当前 Alert Events。
- `/market/chart`：主力连续 K 线、当日 Live、Newow/HTDY/苏冰/Free 四视角、通用 EMA/MACD/Range 与只读参考交易。
- `/research/new-subing`：独立新苏冰历史研究结果；Market 导航未提供直接入口。
- CLI：`guiyi data ...`、`guiyi runtime ...`、`guiyi reference ...` 与 `guiyi home build`。

各视角、指标及参考交易的身份与开放边界统一见 [稳定产品面](PROJECT_SOURCE.md)。

## 工程入口

- [执行规则](AGENTS.md)
- [开发与版本维护](docs/DEVELOPMENT.md)
- [子代理角色与交付](docs/AGENT_ROLES.md)
- [当前状态](STATUS.md)
- [稳定产品边界](PROJECT_SOURCE.md)
- [架构决策](DECISIONS.md)
- [Active Architecture](docs/ARCHITECTURE.md)
- [测试命令](TESTING.md)
- [牛哇完整手册](docs/research/newow-v3.2.82/REPLICATION_MANUAL.md)
- [数据合同](docs/DATA_CENTER.md)
- [部署与运行检查](deploy/README.md)

任务授权与真实操作边界统一见 [AGENTS.md](AGENTS.md)。所有研究观察 `auto_order=false`。
