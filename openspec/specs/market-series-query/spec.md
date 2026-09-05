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

`resolved contract segments` SHALL 仅表达该周期实际返回 Bar 的 owner 事实。需要跨周期研究和
query-invariant segment identity 的消费者 SHALL 另由 `MarketDataService.actual_dominant_segments`
读取与请求交易日窗口相交的完整 rank1 MainContractMap 分段。不同周期的 owner 子集 MAY 不相等；
每根返回 Bar MUST 同时被唯一的响应 owner 和全局权威 owner 覆盖，且 contract 一致。消费者不得以
D1 owner 推断 W1/60m，也不得把各周期 owner 子集的并集冒充全局 MainContractMap。

#### Scenario: 多月连续查询
- **WHEN** 所有相交月完整且可读
- **THEN** 服务按时间有序合并并去重返回窗口 bars

#### Scenario: 短主力段没有完整周线 Bar
- **WHEN** 一个 rank1 分段短于完整 ISO 周且该段没有 W1 Bar，但 D1/60m 存在 Bar
- **THEN** 全局权威分段仍包含该段，W1 响应 owner 子集可以省略它，逐 Bar owner 校验通过
