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
`continuous/MAIN` 的 `1m` 来源 SHALL 仅为 RQData `{SYMBOL}88` 未平滑主力连续，系统 MUST NOT
将 `{SYMBOL}99` 持仓量加权指数作为空窗 fallback；其 `1d` SHALL 按每个交易日的 rank1
`MainContractMap` 读取 RQData 真实合约交易所日行情，`1w` SHALL 只由完整同源 `1d` 聚合。

#### Scenario: 1m 月发布
- **WHEN** 1m dataset-month 通过发布校验
- **THEN** 系统可在同一轮生成该月四个日内派生分区

#### Scenario: continuous 日周事实
- **WHEN** 系统构建 `continuous/MAIN` 的 `1d` 或 `1w`
- **THEN** 日线按 rank1 真实合约交易所事实拼接，周线只由完整同源日线聚合，不读取 `{SYMBOL}88/99` 日周线
