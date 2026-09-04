# historical-data-maintenance Specification

## Purpose

定义 Recent Trusted Window 内的 update、refresh、audit、固定水位和 quota natural resume。

## Requirements

### Requirement: 公开维护面
系统 SHALL 公开 `update`、`refresh` 与 `audit`。`audit` SHALL 接受
`(--symbol X | --universe active)` 的互斥选择器。无 `--apply` 的 update/refresh MUST 只计划，
不得写 PostgreSQL/Parquet；audit MUST 只读。
系统还 SHALL 公开一次性 `session-anchor-repair` 三阶段 seam：`plan` 只读输出精确 session、Dataset、
分区、预计缺失首分钟与稳定 scope hash；`prepare --apply` 只在外部 shadow root 使用真实 RQData 重建完整
Canonical；`publish --apply` 只在五项 Runtime 全部停止、manifest/基线/hash 未漂移时切换 root、reconcile
Catalog、执行精确 0045 并清理 publish 执行时由 operational phase authority 唯一解析的当前交易日旧锚点 Live Bar；此 repair cleanup MUST 保留 after-market reconciliation 所需的不可变 rank1 subscription snapshot。

#### Scenario: 已退出动作
- **WHEN** 用户调用任何已退出的维护操作
- **THEN** CLI 不暴露该入口

#### Scenario: session-anchor plan
- **WHEN** operator 执行 `session-anchor-repair --phase plan`
- **THEN** 不调用 RQData、不写 DB/Parquet/Redis，返回稳定 scope hash 与精确影响计数

#### Scenario: publish 前基线漂移
- **WHEN** active file、Catalog、revision、shadow hash、D1/W1 hash 或 Runtime stop proof 任一不匹配 manifest
- **THEN** publish 在 root switch 与 0045 前 fail closed

#### Scenario: 0045 后步骤失败
- **WHEN** root/Catalog 已切换且 0045 已成功后 Redis cleanup 失败
- **THEN** 系统保持维护状态并返回 forward recovery required，不恢复错误 session 或混用新旧锚点

### Requirement: 分类 audit finding
audit SHALL 为每个请求品种独立检查并返回 `code`、`category`、dataset、year、month 的结构化 finding。
已知历史 Session、交易日历和产品窗口元数据缺口 MUST 分别使用 `metadata_session`、
`metadata_calendar`、`metadata_window` 分类，并继续审计其余请求品种；主力映射、预期分区缺失和
Catalog/Parquet 物理一致性问题 MUST 分别使用 `main_contract_map`、`partition`、`physical` 分类。
无法分类的基础设施异常 MUST 继续 fail-closed，不得伪造 finding。

#### Scenario: 一个品种缺少历史 Session
- **WHEN** active universe 的某个品种无法解析完整交易日并产生 `TRADING_SESSION_MISSING`
- **THEN** audit 返回该品种的 `metadata_session` finding，并继续返回其他品种的审计结果

### Requirement: fixed through 和 natural resume
`effective_start(symbol)` SHALL 为 `max(product_window_start(symbol),2023-01-01)`。update SHALL 以
显式 `--through` 或在规划开始解析的最新完整交易日固定本轮水位，检查全域月度 coverage；完整月跳过，
合法子集仅请求缺失 bars，冲突或不可读月整月重建。已发布 Catalog + Parquet SHALL 是唯一进度状态。

#### Scenario: same-T NOOP
- **WHEN** 所有预期月完整且再次运行相同 fixed through update
- **THEN** 结果为零目标、零 provider request、零写入

### Requirement: quota 中止和续传
明确的 provider quota/limit 异常 SHALL 映射为 `PROVIDER_QUOTA_EXHAUSTED`；该轮 MUST 立即停止后续
provider 调用，保留已发布月且不发布当前未完成月，并返回 `status=partial` 和
`stop_reason=provider_quota_exhausted`。

#### Scenario: 下次续传
- **WHEN** 以相同参数重新执行 quota 中止的 update
- **THEN** 系统从第一个未完整 target 自然继续，不读取 checkpoint 或进度文件

### Requirement: refresh 完整月重建
refresh SHALL 接受 symbol、since、through，并强制重建相交月份的 continuous 与所涉 rank1 contract
基础 provider `1m/1d` 与日线派生 `1w`；新 1m 发布后 MUST 重建四个日内派生月。

#### Scenario: refresh dry-run
- **WHEN** refresh 未传 `--apply`
- **THEN** 输出计划的 month/series 范围且不调用 provider 或写入
