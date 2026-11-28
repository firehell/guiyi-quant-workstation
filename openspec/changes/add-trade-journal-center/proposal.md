## Why

交易计划、实际操作过程和事后反思需要围绕同一个案例查阅。工作站现有中心负责各自的行情、回测和成交证据，复盘中心负责用户自己的记录及来源关联。

## What Changes

- 建立交易日及品种计划、手动归案、复盘和日周总结的工作台。
- 以来源身份关联账户成交、Paper、参考交易和历史回测。
- 使用组件版本和 trade-journal-center/vX.Y.Z 发布独立版本。

## Capabilities

### New Capabilities

- `trade-journal-center`: 计划、案例、过程、复盘和只读证据关联。

### Modified Capabilities

无。

## Impact

新增 Web 路由、API 和可独立验证的 PostgreSQL 表。现有账户账本继续由原模块负责。
