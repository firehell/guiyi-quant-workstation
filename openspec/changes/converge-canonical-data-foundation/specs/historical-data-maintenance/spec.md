## Purpose

定义 Recent Trusted Window 内的 update、refresh、audit、固定水位和 quota natural resume。

## ADDED Requirements

### Requirement: 公开维护面
系统 SHALL 公开 `update`、`refresh`、`audit` 与 `retire-products`。无 `--apply` 的
update/refresh/`retire-products` MUST 只计划或盘点，不得写 PostgreSQL/Parquet（retire 的
`--apply` 除外且受退役名单与单次意图约束）；audit MUST 只读。

#### Scenario: 已退出动作
- **WHEN** 用户调用任何已退出的维护操作
- **THEN** CLI 不暴露该入口

#### Scenario: retire-products dry-run
- **WHEN** 用户调用 `guiyi data retire-products` 且未传 `--apply`
- **THEN** 仅返回退役品种盘点且不删除 Catalog 行或 Canonical 文件

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
Direct；新 1m 发布后 MUST 重建四个 Derived 月。

#### Scenario: refresh dry-run
- **WHEN** refresh 未传 `--apply`
- **THEN** 输出计划的 month/series 范围且不调用 provider 或写入
