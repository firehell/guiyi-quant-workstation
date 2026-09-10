## ADDED Requirements

### Requirement: Conflict invalidation revokes asynchronous write eligibility

客户端失效资源时 MUST 同步撤销旧请求的写入资格、取消在途请求、清除关联 token、数据及分页状态。旧请求即使忽略 abort，其成功、失败及 finally MUST NOT 修改失效后的状态或后续请求身份。chart/reference/explanation 的事实或响应冲突 MUST 失效全部五个 section 与 auxiliary cache，防止共享冲突快照再次通过 compatible token 被选用。auxiliary/comparator 自身局部响应错误 MAY 仅失效该 section 及 auxiliary cache。

#### Scenario: An explanation arrives after shared chart conflict

- **WHEN** explanation 仍在请求中而 chart 发现 shared Bar 冲突，随后旧 explanation 成功返回
- **THEN** 旧请求已经被取消且失去写入资格，相关资源保持 input_conflict 且数据为空
- **AND** 同样的保护适用于忽略 abort 的请求与晚到异常

#### Scenario: A later request replaces an invalidated request

- **WHEN** 冲突后新请求开始，旧请求再执行 finally
- **THEN** 旧 finally 不得清除新 controller/token，新请求可以正常提交已验证结果

#### Scenario: Rebuilding one incompatible snapshot

- **WHEN** 当前请求遭遇允许重建的 409
- **THEN** 关联旧资源与其他在途请求失效，当前请求可保留身份完成最多一次去除旧绑定的重建
- **AND** 第二次失败不再重建，429 不得触发自动重试

#### Scenario: Compatible navigation preserves independent reference state

- **WHEN** 服务端接受同一 snapshot token 的不同 chart 窗口
- **THEN** 客户端保留独立 reference 统计、列表及 cursor
- **AND** 同窗口分页和无 token 情形仍执行既有严格身份验证

#### Scenario: Conflict clears navigation and auxiliary provenance

- **WHEN** 主要事实冲突导致全部 section 失效
- **THEN** chart current-window provenance、分页与 generation signature 被清除，旧 auxiliary cache 不得恢复结果，后续 token 选择不能命中失效快照
