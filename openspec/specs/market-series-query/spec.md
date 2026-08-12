# market-series-query Specification

## Purpose

定义 Market Web、指标和未来研究共用的唯一历史查询语言、主力映射解析规则、最小可复算响应，以及数据不完整时的 fail-closed 读取行为。

## Requirements

### Requirement: 三种 SeriesQuery
查询 SHALL 接受 `continuous|actual_dominant|contract`、symbol、frequency、start、end；contract
模式必须有 contract，其他模式不得提供 contract。连续/真实合约查询直接读取同频 Catalog 月分区；
actual_dominant MUST 按 rank1 Map 拼接真实 contract，不得存储重复 Parquet。

#### Scenario: 缺失真实合约分区
- **WHEN** actual_dominant 映射片段缺月、coverage 或可读文件
- **THEN** 整个查询 fail-closed，不回退 continuous

### Requirement: 周线 owner
actual_dominant 的 1w SHALL 只返回完整 ISO 周，并以该周最后交易日 rank1 contract 作为整周 owner。

#### Scenario: 周中换月
- **WHEN** rank1 在完整 ISO 周内变更
- **THEN** 系统返回周最后交易日 owner 的真实合约周线

### Requirement: 最小可复算响应
成功响应 SHALL 返回规范化请求、bars、实际 coverage 与 resolved contract segments；不得返回
profile、binding、quality report、content digest、access-mode 或 legacy selector 字段。

#### Scenario: 多月连续查询
- **WHEN** 所有相交月完整且可读
- **THEN** 服务按时间有序合并并去重返回窗口 bars
