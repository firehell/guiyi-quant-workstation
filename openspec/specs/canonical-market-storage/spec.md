# canonical-market-storage Specification

## Purpose

定义唯一长期历史 Bar 资产的身份、月分区、最小 schema、发布校验和 Derived 边界。

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

### Requirement: Direct 与 Derived 边界
`1m/1d/1w` SHALL 直接来自 RQData；`5m/15m/30m/60m` SHALL 只从质量通过的同 Dataset Canonical
1m 按实际 Session 聚合，且 MUST NOT 调用 RQData 或回退其他周期。`continuous/MAIN` 的 Direct
来源 SHALL 仅为 RQData `{SYMBOL}88` 未平滑主力连续；系统 MUST NOT 将 `{SYMBOL}99` 持仓量加权
指数作为空窗 fallback。

#### Scenario: 1m 月发布
- **WHEN** 1m dataset-month 通过发布校验
- **THEN** 系统可在同一轮生成该月四个 Derived 分区
