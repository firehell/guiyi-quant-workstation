## Context

基于 `develop@284ae9abeb2eaf045899fbebe82419360bc01560` 及当时工作区只读检查。正式 `composition.py` 注入 `coverage.valid_boundary`，`CanonicalMonthlyStore._validate` 在循环内每 Bar 调用；同一验证逻辑也用于 `read_catalog_partition`。大量相同事实查询发生在实际存储边界，规划阶段优化不能替代这里的改动。

`closeout_binding.py` 还精确检查 `manager.store.boundary_validator == manager.coverage.valid_boundary`。这是依赖来源保护，内部接口变更必须联动更新，不能因为只是“性能优化”而遗漏。

## Goals / Non-Goals

目标：同一固定分区、同一事实范围内，增加 Bar 数不再线性增加 metadata SQL；继续逐根检查边界与权威 trading_day，发布和独立 readback 分别取得自己的验证上下文。

不做：跨调用缓存、共享长期 session snapshot、全库预加载、新 resolver、SQL schema/index migration、放宽 Calendar/Session、改变 warm-up 或修正生产数据。

## Decisions

### 1. 一次性替换内部 callback 合同

采用以下接口形状；这是设计示意，并非本 change 已完成实现：

```python
PartitionBoundaryValidator = Callable[[DatasetKey, tuple[CanonicalBar, ...]], bool]

def valid_boundaries(self, key: DatasetKey, bars: tuple[CanonicalBar, ...]) -> bool:
    ...
```

store 构造参数继续叫 `boundary_validator`，避免无意义的额外命名改动；类型与入参统一更新。`_validate` 先保留非空、月范围、严格排序、expected endpoints 与逐 Bar 月份结构检查，再对整个 tuple 调用一次 validator。返回 False 仍映射为 `SESSION_BOUNDARY_INVALID`。不添加 try-call-scalar fallback，不保留两套正式方法。

已有 `boundary_validator=None` 的纯存储构造保持显式无 DB callback 模式，不自动补接外部 DB。生产 manager 的 composition 必须继续注入权威 coverage；不把可选构造误当作生产绕过入口。

### 2. 每次调用构造有界事实上下文

以当前分区出现的 distinct trading_day 为验证范围，批量读取对应 Calendar 与 active rqdata Session 事实。contract 一次读取 ContractFact，再验证所有日期都落在 `[listed_date, expired_date)`，且每个待验证日期确为合约交易日、有原有严格 Session 证据。continuous 保留现有 product window/history floor 限制及对应 Calendar/Session 合同。

复用 `expected_bar_end_pairs_for_trading_days` 和 `SessionWindowBatch`，得到 `(bar_end, authoritative_trading_day)` 集合，再检查所有输入 pair。不得只比较时间戳而丢失 trading_day 归属，也不得自写第二套频率端点算法。

批量化需要的权威筛选代码留在 `coverage_source.py` 内，可提取小型私有方法。不能直接把每根 Bar 的 `contract_trading_days(day, day)` 换成无条件 `contract_trading_days(min_day, max_day)`：后者会要求稀疏输入中间所有自然日均有事实，从而暗中改变验收范围。对原本不需验证的无关空档不增加要求；夜盘所需前一交易日和 W1 完整 ISO 周属于必要上下文，仍必须读取验证。

空 tuple 明确返回 False，store 非空检查仍先行。保持当前 Catalog/Infrastructure 错误的分类及传播边界：原先返回 False 的事实非法继续拒绝，原先上抛的基础设施异常不吞掉或改为成功。不要用批量优化掩盖未知错误。

### 3. 验证上下文不跨调用复用

上下文仅为一次 `valid_boundaries` 的局部变量。publish validation 与 catalog readback 各执行一次批量读取；第二次不得复用第一次的“已验证”标记或内存结果。后续调用必须执行权威查询，按其数据库事务可见性读取事实；不承诺打破数据库隔离级别看见事务外未提交变化。

保留现有 schema/hash/rowcount、expected coverage、不可变 URI、文件 durability 与 Catalog commit 逻辑。没有必要把同一 SQL 查询做到全事务只执行一次。

### 4. 精确联动 composition 与 closeout

`composition.py` 注入 `coverage.valid_boundaries`；`closeout_binding.py` 的等值检查对应改成 `manager.coverage.valid_boundaries`，仍要求同一个 coverage 实例、同一个 session 和既有 canonical root 绑定。不得弱化成 `callable(...)` 或只比较函数名。

更新 `test_closeout_binding.py`，覆盖正确绑定通过、None/错误 coverage 实例/旧 scalar callback/错误 session 拒绝。当前这两个 closeout 文件属于其他未提交工作；实施前先等其集成或取得无冲突已完成基线，本任务仅调整精确 callback 断言及对应测试，不更改 source-age、配置 allowlist、执行 Gate 或收尾结果语义。

## Alternatives considered

- 给 scalar validator 加 memoization：缓存失效边界复杂，容易跨事务保留旧事实，不采用。
- 全局加载所有 Calendar/Session：范围无界且独立 readback 失去意义，不采用。
- 取消 store 边界校验，依赖 planner：绕过发布与读取的安全边界，不采用。

## Validation

先用实际 `DatabaseCoverageSource` 注入 store，在 SQLite 隔离 DB 上计数 SQL，复现当前随 Bar 数线性增长；不能使用省略 validator 的 `_manager` 夹具证明性能修复。对同一完整事实夹具、同一 1m 分区内的 1/5/60 根合法 Bar 分别校验，metadata SELECT 次数应保持相同；continuous/contract 分别验证。多交易日分区也不能退回逐 Bar 或逐日期 SQL 循环。

publish 与 `read_catalog_partition` 两个阶段分开计数，确认各自有真实权威读取。记录查询数即可，不设置依赖机器负载的毫秒门槛。读取事实数量和纯计算可随输入规模增长，SQL 往返不得随 Bar 数增长。

语义矩阵覆盖七种频率、日盘/夜盘、session 尾部短 Bar、跨月 ISO 周 W1、错误 trading_day、缺失/非交易日 Calendar、失效 Session、合约上市/到期边界、合法 pre-rank1 warm-up、稀疏日期及 history floor。保留独立分区 coverage 与 contract superset 规则；不能把批量 pair membership 当作覆盖完整性证明。

额外做 fresh-call 回归：第一次成功后，在隔离环境提交相关 Session 或 Contract 生命周期变化，使用新验证调用/必要的新事务读取，原候选必须被拒绝。另测试文件/hash/rowcount/strict-read 故障仍阻止 pointer 提交。

## Rollout and risks

建议第一项维护顺序修复验收后再做本项，减少 shared maintenance 测试变化混杂；不是算法依赖。内部所有注入和调用点必须同一工程变更更新，不能分步发布旧 callback 与新 store 的混合版本。

无 migration 或外部操作。源码恢复使用整个变更的 Git revert；不能只回退 callback 的一侧。工程通过不授权 production apply、main/tag 或 Runtime promotion。
