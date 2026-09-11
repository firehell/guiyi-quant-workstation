## Why

正式 composition 把 `DatabaseCoverageSource.valid_boundary` 注入 Canonical store，而 store 对每根 Bar 调用它，重复读取 Calendar、Session 和合约事实。上一轮隔离 SQL 计数中，continuous 1/5 根分别执行 5/25 次查询，contract 为 6/30 次。已有规划批量化没有消除发布与严格读取阶段的逐 Bar 查询。

## What Changes

- 将内部 boundary validator 改为一次接收一个分区的 Bar tuple，批量取得所需权威事实，再逐值验证。
- 复用现有 Calendar/Session/endpoint 解析，保持分区完整性、夜盘、周线及合约生命周期语义。
- 同步更新正式 composition 和 closeout 精确依赖来源检查，不保留 scalar 兼容分支。
- 用真实 coverage + store 注入的 SQL 计数与语义回归验收；不增加跨调用缓存。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `canonical-market-storage`：边界验证以单次分区为批次，保持独立严格读取与 fail-closed。

## Impact

**BREAKING（仓库内部 Python 回调）**：`boundary_validator` 的输入从单根 Bar 改为 `tuple[CanonicalBar, ...]`；`valid_boundary` 替换为 `valid_boundaries`。外部 API、Parquet schema、Catalog schema、公式与价格精度不变。

涉及 `storage.py`、`coverage_source.py`、`composition.py`、`closeout_binding.py` 和相关测试。当前 closeout 源码及测试已有其他任务的未提交修改；实施前必须接续其已完成基线，不能覆盖或顺手重构。

本 change 已完成实现、定向验证与独立 Review；全量类型检查仍有两份未改文件的既有错误。查询计数验收只使用隔离 DB 和临时目录，不代表生产墙钟性能，不授权生产连接、数据写入、closeout apply 或 Runtime 切换。
