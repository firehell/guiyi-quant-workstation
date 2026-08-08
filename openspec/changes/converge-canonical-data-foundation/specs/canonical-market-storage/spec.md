## Purpose

定义唯一长期历史 Bar 资产的身份、月分区、标准字段、Manifest、质量准入和派生规则，使任何可发布数据都能被严格复算和安全替换。

## ADDED Requirements

### Requirement: 四字段 DatasetKey
物理 DatasetKey SHALL 精确为 `(kind, symbol, series_or_contract, frequency)`；`kind` 只允许 `continuous` 或 `contract`，frequency 只允许 `1m/5m/15m/30m/60m/1d/1w`。continuous 的 series SHALL 为 `MAIN`，contract 的 series SHALL 为规范化真实合约代码。

#### Scenario: 合法身份规范化
- **WHEN** 输入包含大小写或空白差异的品种、MAIN 或真实合约代码
- **THEN** 系统生成唯一规范化四字段身份和稳定目录路径

#### Scenario: 非法物理身份
- **WHEN** 输入 kind 为 actual_dominant、frequency 不受支持或 kind 与 series 不匹配
- **THEN** 系统拒绝创建 DatasetKey

### Requirement: 唯一 Canonical 月分区
系统 SHALL 按 `canonical/kind=.../symbol=.../series=.../frequency=.../year=YYYY/month=MM/` 保存每 Dataset 每自然月一个 `part.parquet` 和 `manifest.json`，且 MUST NOT 保存 data_version 目录、overlay 或重叠 active 分区。

#### Scenario: 日常当前月更新
- **WHEN** 当前月出现新的完整交易日且历史区间已经正确
- **THEN** 系统只原子重写当前月并保持其他月份不变

#### Scenario: closed month repair
- **WHEN** 精确 repair 计划指向一个已关闭月份
- **THEN** 系统仅替换受影响月份并保留同 Dataset 其他月份

### Requirement: 最小 CanonicalBar schema
Parquet 行 SHALL 只包含 `bar_end`、`trading_day`、`open`、`high`、`low`、`close`、`volume`、`turnover`、`open_interest`；价格与金额字段 SHALL 使用约定 Decimal，`bar_end` SHALL 为 UTC-aware timestamp，身份 MUST 由路径、Manifest 和 Catalog 表达而不在每行重复。

#### Scenario: provider batch 标准化
- **WHEN** RQData 提供可识别的字段和时区
- **THEN** 系统输出完全相同的 CanonicalBar schema 与值语义

### Requirement: Manifest 完整性
每个月分区 Manifest SHALL 保存 DatasetKey、schema version、source kind、覆盖范围、row count、Parquet checksum 和 source digest；派生分区还 SHALL 保存源 1m digest 和 session digest。

#### Scenario: 派生分区 lineage
- **WHEN** 5m/15m/30m/60m 分区从 Canonical 1m 生成
- **THEN** Manifest 可以精确识别所用 1m 内容和交易时段规则

### Requirement: 六项发布硬校验
系统 MUST 在发布前验证：Canonical schema/Decimal/timestamp；`bar_end` 单调且唯一；OHLCV 合法；trading day/session/周期边界正确；请求窗口覆盖完整；row count/checksum/原子发布一致。任一校验失败 SHALL 保留最后有效 Canonical 并记录当前 DataGap，不得生成 DataQualityReport。

#### Scenario: 重复主键被拒绝
- **WHEN** 候选月包含重复 `bar_end`
- **THEN** 发布失败、原分区不变且缺口原因可审计

#### Scenario: 覆盖窗口缺失被拒绝
- **WHEN** 候选数据未完整覆盖 TargetWindow 所要求的交易时段
- **THEN** 发布失败且系统输出可用于精确重下的缺失窗口

#### Scenario: 原子发布成功
- **WHEN** 六项校验全部通过且临时文件 row count/checksum 与 Manifest 一致
- **THEN** Parquet、Manifest 与 Catalog 以单月一致状态成为当前有效分区

### Requirement: Direct 与 Derived 来源边界
`1m/1d/1w` SHALL 由 RQData direct 数据标准化；`5m/15m/30m/60m` SHALL 只从质量通过的 Canonical 1m 按实际 session 聚合，Derived MUST NOT 调用 RQData 或跨频回退。

#### Scenario: direct 周线请求映射
- **WHEN** Candidate 或日常维护为 `1w` Direct 目标请求 provider 数据
- **THEN** 系统以 provider weekly frequency 发起请求，并且不得将该目标映射为 `1d`、`1m` 或任何 Derived 请求

#### Scenario: 1m 失败阻断 Derived
- **WHEN** 某目标窗口的 Canonical 1m 下载或校验失败
- **THEN** 相依 Derived 标记 blocked 且不会发布或调用 provider

#### Scenario: 周线完整周
- **WHEN** 生成 1w direct 目标或验证周线
- **THEN** 只接受以最新完整 ISO 周最后交易日为边界的数据
