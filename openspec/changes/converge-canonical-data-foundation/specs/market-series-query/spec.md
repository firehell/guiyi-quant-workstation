## Purpose

定义 Web、指标和未来研究消费者唯一的历史行情查询语言与严格读取语义，避免消费者自行 glob、选择 active 数据或重复实现主力合约拼接。

## ADDED Requirements

### Requirement: 三种 SeriesQuery
公开查询 SHALL 接受 `series_kind=continuous|actual_dominant|contract`、symbol、frequency、start、end；只有 contract 模式 SHALL 要求 contract 字段，其他模式 MUST 拒绝 contract 字段。

#### Scenario: contract 缺少合约
- **WHEN** series_kind 为 contract 且 contract 为空
- **THEN** 请求在读取任何文件前被拒绝

#### Scenario: continuous 携带 contract
- **WHEN** series_kind 为 continuous 但请求包含 contract
- **THEN** 请求作为歧义身份被拒绝

### Requirement: 唯一 Catalog 定位
MarketDataService SHALL 只通过 Catalog 和 Manifest 定位同频月分区并使用 Parquet 查询引擎读取；所有消费者 MUST NOT glob 文件、猜测最新版本、绕过 DataGap 或自行解析主力映射。

#### Scenario: Catalog 与文件不一致
- **WHEN** Catalog 指向分区但 Manifest、checksum 或 row count 不一致
- **THEN** 查询 fail-closed 且不会扫描其他文件寻找替代数据

### Requirement: continuous 与 contract 查询
continuous SHALL 读取对应品种 `MAIN` 物理 Dataset；contract SHALL 读取指定真实合约物理 Dataset，且只返回请求窗口内同频 bars。

#### Scenario: direct monthly query
- **WHEN** 请求跨越多个自然月且每个月分区有效
- **THEN** 服务按时间有序合并分区并返回去重后的窗口 bars

### Requirement: actual dominant 查询时拼接
actual_dominant SHALL 根据 MainContractMap rank1 在查询时把真实 contract Dataset 拼接为单一序列，MUST NOT 读取或持久化 actual_dominant 物理 Parquet。映射缺失、映射合约 Dataset 缺失或 DataGap 相交 SHALL fail-closed。

#### Scenario: 跨换月拼接
- **WHEN** 查询窗口跨越 rank1 合约切换日且两个 contract Dataset 完整
- **THEN** 返回 bars 精确按各交易日映射选择合约并报告 resolved contract segments

#### Scenario: 映射合约数据缺失
- **WHEN** 某 rank1 片段对应 contract Dataset 或必要月份不存在
- **THEN** 整个严格查询失败并指出缺失片段，不回退 continuous

### Requirement: actual dominant 周线归属
actual_dominant `1w` SHALL 只返回完整 ISO 周，并以该周最后交易日的 rank1 合约作为整周 owner；假期缩短周 SHALL 使用该 ISO 周实际最后交易日。

#### Scenario: 周中换月
- **WHEN** rank1 在完整 ISO 周中间切换
- **THEN** 该周使用周最后交易日对应真实合约的 1w bar

#### Scenario: 未完整当前周
- **WHEN** end 落在尚未完成的 ISO 周
- **THEN** 服务不返回该不完整周

### Requirement: 查询可复算 lineage
成功结果 SHALL 返回规范化 request identity、bars、实际 coverage、partition digests、resolved contract segments 和 main-map digest；响应 MUST NOT 包含 profile、data_role、market_data_file、binding、quality report、access mode、strict research ready 或 legacy lineage selector 字段。

#### Scenario: continuous 响应
- **WHEN** continuous 查询成功
- **THEN** 响应包含所读月分区 digest 且 resolved contract segments 为空

#### Scenario: actual dominant 响应
- **WHEN** actual_dominant 查询成功
- **THEN** 响应同时包含实际合约片段和覆盖该请求的稳定 main-map digest
