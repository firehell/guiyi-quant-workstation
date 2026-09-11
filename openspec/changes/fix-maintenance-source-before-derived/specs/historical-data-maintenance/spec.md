## ADDED Requirements

### Requirement: Pending minute source publication precedes dependent derivation

同一 maintenance 调用中，若某物理 family/month 的 1m 属于待发布来源，依赖它的 5m、15m、30m、60m 目标 MUST 等待该来源按现有分区发布合同成功提交，不能因旧 1m 完整而提前派生。此规则 MUST 独立于 refresh/update 路径、fail_stop 与 source cache。成功派生 MUST 使用该次已发布来源；不得用旧来源结果消耗待处理目标。

#### Scenario: Refresh replaces an already complete minute partition

- **WHEN** 旧 1m 及派生分区完整，本次 refresh 将同一 family/month 的 1m 更新为不同值
- **THEN** 派生分区在新来源成功发布之后计算，最终数值来自新来源
- **AND** 普通无缓存路径与 streaming 路径遵守相同顺序

#### Scenario: Pending source cannot be published

- **WHEN** 待更新 1m 发生校验失败、quota interruption 或 commit outcome unknown
- **THEN** 依赖目标不得使用旧 1m 标为成功，返回既有准确的失败或部分完成状态
- **AND** commit outcome unknown 保持全局停批，不重试、不隐式回滚

#### Scenario: Existing source is outside the current update set

- **WHEN** 派生目标的 1m 完整有效且不在本次待更新集合中
- **THEN** 它可保持既有提前派生行为，不必等待无关 family/month 的 provider 请求

#### Scenario: Dependencies remain partition specific

- **WHEN** 两个目标的物理 family 或月份不同
- **THEN** 来源依赖不会错误关联两者，成功结果与失败传播仍遵守既有维护合同
