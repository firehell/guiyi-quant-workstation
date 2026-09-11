## ADDED Requirements

### Requirement: Partition boundary validation batches authoritative metadata reads

生产维护 composition 中的 Canonical boundary validation MUST 以单次分区的全部 Bar 为一个批次，批量取得必要 Contract、Calendar、Session 事实，再验证每条 `(bar_end, trading_day)`。同一固定分区及相同事实范围内，metadata SQL 往返 MUST NOT 随 Bar 数线性增长。批量处理 MUST 保留现有完整性、生命周期、history floor、session、周线、夜盘及合法 warm-up 合同，不增加无关稀疏日期要求，也不放宽必要上下文。

#### Scenario: More bars share the same partition facts

- **WHEN** 同一完整事实夹具、同一分区由 1 根增加到 5 根、60 根合法 1m Bar
- **THEN** continuous 与 contract 的 metadata SELECT 次数分别保持固定，所有 Bar 仍逐值通过权威边界验证

#### Scenario: Timestamp and trading day disagree

- **WHEN** Bar 的 timestamp 看似合法，但其 trading_day 不匹配权威端点归属
- **THEN** 分区被拒绝，不能通过跨日期 endpoint 集合误接受

#### Scenario: Weekly or night context crosses a date boundary

- **WHEN** W1 横跨月末，或夜盘依赖前一交易日
- **THEN** 验证复用现有权威完整上下文，不能只根据输入月份或出现的日期猜测端点

#### Scenario: Invalid lifecycle or missing authority

- **WHEN** 某 Bar 越出合约生命周期，或所需 Calendar/Session 事实缺失或不合法
- **THEN** 整个候选按既有错误合同失败，最后有效分区与 pointer 受到既有发布流程保护

### Requirement: Boundary validation context is local to each validation call

发布校验与严格 Catalog 读取 MUST 分别执行权威批量验证，不得复用跨调用的已验证缓存。store 的批量 callback MUST 与正式 composition 和 closeout 精确来源检查一致；closeout MUST 拒绝缺失、旧 scalar 或其他 coverage 实例的 callback，保留原 session/root 身份检查。

#### Scenario: Authority changes between independent validations

- **WHEN** 一次验证通过后，相关权威事实已提交变更，后续独立验证事务可见该变化
- **THEN** 后续验证重新读取事实，拒绝已不合法的旧候选

#### Scenario: Bound closeout receives a mismatched validator

- **WHEN** manager 注入 None、旧 scalar callback 或其他 coverage 实例的 validator
- **THEN** closeout 依赖来源检查 fail closed，不因 callback 可调用而通过

#### Scenario: Storage validation and physical readback remain separate

- **WHEN** 候选通过批量边界验证但 strict-read 的 hash、schema、rowcount 或 coverage 检查失败
- **THEN** 既有发布流程仍拒绝提交新 pointer，批量优化不替代其他校验
