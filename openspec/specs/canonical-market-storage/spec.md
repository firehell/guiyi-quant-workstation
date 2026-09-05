# canonical-market-storage Specification

## Purpose

定义唯一长期历史 Bar 资产的身份、月分区、最小 schema、发布校验、派生边界及消费者共享的读取契约。

## Requirements

### Requirement: 四字段 DatasetKey 与单月 Parquet
物理 DatasetKey SHALL 精确为 `(kind, symbol, series_or_contract, frequency)`；kind 仅允许
`continuous|contract`，frequency 仅允许七个正式周期。每 Dataset 每自然月 SHALL 只保存一个
`part.parquet`，不得保存 active overlay、data version、内容清单或旁路发布文件。

#### Scenario: 非法物理身份
- **WHEN** 输入 actual_dominant、未支持周期或 kind/series 不匹配
- **THEN** 系统在创建路径或 Catalog 身份前拒绝输入

### Requirement: Contract partition preserves valid lifecycle warm-up
对 `contract` Dataset，所有 rank1 映射所需的 Bar end MUST 被持久化 Bar end 包含；每一条已持久化 Bar 又
MUST 被 Contract 的 active lifecycle、TradingCalendar 与 TradingSession 共同证明合法。非 rank1 的同物理
合约 warm-up Bar 因此可被保留，但不得改变 `actual_dominant` 的 rank1 owner 解析。`continuous` Dataset
继续要求 persisted 与 expected 精确相等，不采用此 superset 合同。refresh 覆盖含合法 warm-up 的 contract
分区时 MUST 将这些 timestamps 纳入 provider 重拉目标，不得静默删除。

#### Scenario: A valid pre-rank1 contract prefix exists

- **WHEN** contract partition 同时含 rank1 required Bar 与其上市有效期内的真实 pre-rank1 Bar
- **THEN** 分区通过校验，且 actual_dominant 仍只返回 rank1 有效日对应的 owner

#### Scenario: A persisted contract Bar is outside its lifecycle

- **WHEN** contract partition 含有超出 Contract active lifecycle、Calendar 或 Session 的 Bar
- **THEN** 该分区 fail closed；合法 warm-up 规则不得放宽越界 Bar

### Requirement: 最小行 schema 和发布校验
Parquet 行 SHALL 只包含 `bar_end`、`trading_day`、`open`、`high`、`low`、`close`、`volume`、
`turnover`、`open_interest`；价格与金额使用 Decimal，`bar_end` 为 UTC timestamp。发布前 MUST 验证
schema、identity、主键单调唯一、OHLCV、session/frequency、coverage 和物理可读性；失败 MUST 保留
最后有效月且不得发布半成品。

#### Scenario: 覆盖不完整
- **WHEN** 候选月未覆盖 TargetWindow 的预期 bars
- **THEN** 该月不发布，后续 update 将其仍视为待处理目标

### Requirement: 基础 provider 与派生周期边界
`1m/1d` SHALL 是 RQData 的基础 provider 周期；`1w` SHALL 只由完整同源交易所日行情聚合。
`5m/15m/30m/60m` SHALL 只从质量通过的同 Dataset Canonical 1m 按实际 Session 聚合，且 MUST NOT
调用 RQData 或回退其他周期。
RQData `1m` session 的首根标签 SHALL 在 adapter 边界减一分钟，转换为统一
`SessionWindow(start, end]` 的排他 start；聚合器、Live 与 Historical consumer MUST 共用该 DB session，
不得分别补偿。分钟不对齐、无效、重叠或跨午夜布局不可解释时 MUST fail closed。
`continuous/MAIN` 的 `1m` 来源 SHALL 仅为 RQData `{SYMBOL}88` 未平滑主力连续，系统 MUST NOT
将 `{SYMBOL}99` 持仓量加权指数作为空窗 fallback；其 `1d` SHALL 按每个交易日的 rank1
`MainContractMap` 读取 RQData 真实合约交易所日行情，`1w` SHALL 只由完整同源 `1d` 聚合。

#### Scenario: 1m 月发布
- **WHEN** 1m dataset-month 通过发布校验
- **THEN** 系统可在同一轮生成该月四个日内派生分区

#### Scenario: RQData 真实首分钟标签
- **WHEN** provider 返回 `09:01/10:31/13:31/21:01` 作为各 session 首根 1m `bar_end`
- **THEN** DB session start 为 `09:00/10:30/13:30/21:00`，首根 Bar 被 `(start, end]` 包含且 15m 完成时间不右移

#### Scenario: 修复既有错误锚点
- **WHEN** 受控 repair 以真实缺失 1m 重建并发布既有日内分区
- **THEN** 唯一 Canonical V2 的分区内容、coverage 与 row count 被替换，不创建并行 data-version；D1/W1 hash 不变

#### Scenario: continuous 日周事实
- **WHEN** 系统构建 `continuous/MAIN` 的 `1d` 或 `1w`
- **THEN** 日线按 rank1 真实合约交易所事实拼接，周线只由完整同源日线聚合，不读取 `{SYMBOL}88/99` 日周线
