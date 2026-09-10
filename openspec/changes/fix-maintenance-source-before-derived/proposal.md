## Why

普通 refresh 在旧 Canonical 1m 已完整时，可能先使用旧 1m 发布派生周期，再更新 1m，最后返回 passed。上一轮隔离复现得到 1m 最后一根 close=205、5m close=105；这是数据更新顺序错误，并非聚合公式问题。

## What Changes

- 同一物理数据 family、同一月份存在本次待发布 1m 时，派生目标必须等待该来源成功发布。
- 将依赖判断从 fail_stop/source_cache 条件中移出，覆盖普通与 streaming 维护路径。
- 保留来源不变时的派生提前处理、分区级原子性及既有失败停批语义。
- 增加真实 manager/store 组合下的隔离回归；不建设通用任务 DAG。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `historical-data-maintenance`：明确本次待更新来源与派生发布之间的先后关系。

## Impact

预计修改 `services/quant-api/app/market_data/historical_data_manager.py` 与对应 data_foundation 测试。现有权威入口、公式、数据 schema、CLI 和分区事务边界不变。

本 change 当前只有设计。后续实现仅使用隔离数据库、临时 Canonical 与 FakeProvider；生产 refresh、真实 RQData、Canonical 写入及 Runtime 切换均不在授权中。

建议实施顺序：本项 → [前端失效修复](../fix-newow-conflict-invalidation/proposal.md) → [批量边界校验](../batch-canonical-boundary-validation/proposal.md)。三项分别验收，不合成一次大重构。
