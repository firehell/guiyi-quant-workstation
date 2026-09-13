# Quant API

FastAPI 后端提供统一行情读取、只读策略/参考交易、Alert 与 Runtime 状态。

- `/api/v1/market/*`：Canonical/Live bars、dominants、首页概览、Newow 分区响应与苏冰历史参考。
- `/api/alerts/*`：HTDY 与 SuBing 两种 observation Rule、symbol × frequency Scope、immutable Event。
  Scope mutation 和首次 SuBing activation 仍须对应明确授权。
- `/api/runtime/*`：只读 Runtime 状态。
- CLI：`guiyi data ...` 与 `guiyi runtime ...`；数据维护、恢复及真实操作合同见
  [DATA_CENTER.md](../../docs/DATA_CENTER.md) 和 [部署合同](../../deploy/README.md)。

行情通过 `MarketDataService` 统一读取；指标/策略与参考投影复用 `packages/quant-core`。
Newow、苏冰历史参考与 AlertEvent 分别保留身份，不创建账户、订单或成交。
退役产品入口不恢复，完整边界见 [PROJECT_SOURCE.md](../../PROJECT_SOURCE.md) 和
[ARCHITECTURE.md](../../docs/ARCHITECTURE.md)。

验证命令统一见 [TESTING.md](../../TESTING.md)。隔离测试不授权生产 PostgreSQL、Redis、
Canonical、Scope、通知或 Runtime mutation；当前运行事实只看 [STATUS.md](../../STATUS.md)。
