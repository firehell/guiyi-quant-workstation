# 牛哇六品种 60m 差量恢复 Implementation Plan

**Goal:** 用封闭 60m profile 完成六品种原生依赖盘点、精确分批、受控恢复和三层结算。

**Architecture:** 复用 `HistoricalDataManager.contract_warmup(frequency=60m)` 与现有
campaign 编排；不新增 ETL、缺口权威或 Parquet writer。

## 约束

- 仅 `60m -> [1m, 60m]`；省略频率禁止。
- 60m 无来源隔离/partial-exception 继续。
- 不改 manager 行情、聚合或异常继续合同。
- 生产写入与日线 campaign、盘后维护串行。
- 真实 apply 仍需精确执行包批准。

## 文件

- `scripts/newow_weekly_recovery.py`：60m prepare/apply/读回
- `scripts/newow_weekly_recovery_campaign.py`：六报告并集、派生优先分批
- `scripts/newow_hourly_recovery_verification.py`：只读盘点摘要
- `TESTING.md`：可执行命令
