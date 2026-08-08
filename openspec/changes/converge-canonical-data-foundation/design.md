## Context

项目是单用户、本地优先的国内期货研究工作站。RQData 是唯一外部事实源，Canonical Parquet 是唯一
历史 Bar 数据面，PostgreSQL 只保存最小 Catalog/metadata，`MarketDataService` 是唯一历史读入口。
当前 `20260808_0036` 未被本 change 证明已应用到正式环境；在改写它前，DFD-03 必须重新只读确认生产
仍处于 `20260808_0035`。

## Decisions

### D1 — 身份、周期和物理存储

`DatasetKey=(kind,symbol,series_or_contract,frequency)`；物理 kind 仅 `continuous|contract`；
`actual_dominant` 按 `MainContractMap rank=1` 查询时拼接。Direct 为 `1m/1d/1w`，Derived 为
`5m/15m/30m/60m`，且只由同 Dataset 的 Canonical 1m 和实际 Session 聚合。每 Dataset 每自然月
仅有一个 `part.parquet`。

### D2 — 发布和可用性

写入同目录临时 Parquet，完成 schema、identity、OHLCV、session/frequency、coverage 和物理可读性
校验后原子 replace；再以单数据库事务 upsert 当月 Catalog。`market_partitions` 的 coverage、row count、
URI 和可读文件即为发布状态；不保存内容清单、digest/checksum 或第二套 Gap 状态。

### D3 — 八表 Catalog

active 表为 `exchanges`、`instruments`、`contracts`、`trading_calendars`、`trading_sessions`、
`main_contract_map`、`market_datasets`、`market_partitions`。`contracts` 只维护真实上市/退市边界，
不承担 fee、margin 或回测参数。`market_partitions` 不含内容完整性摘要字段。

### D4 — 三个深模块和三个 CLI

`MetadataSynchronizer` 维护 products、contracts、Calendar、Session 和 rank1 Map；
`HistoricalDataManager` 是唯一写服务，提供 `update|refresh|audit`；`MarketDataService` 是唯一读服务。
无 `--apply` 的 update/refresh 只计划。`refresh` 强制重建指定 symbol/日期范围中相交月的 continuous
与 rank1 contract Direct，然后从新 1m 重建 Derived。

### D5 — 1G/day natural resume

`effective_start=max(product_window_start,2023-01-01)`。固定 `--through` 后，update 先完成 metadata，
再优先 `1d/1w`、已有完整 1m 的 Derived，最后按 active universe、Dataset、年月顺序处理 1m。已有月
完整则跳过，合法子集只下载缺失 bars，冲突/不可读月整月重建。明确 quota 错误映射为
`PROVIDER_QUOTA_EXHAUSTED`，立即停止、保留已发布月、不发布当前月；下一次同命令从首个缺失目标继续。

### D6 — 真实操作边界

DFD-02～DFD-06 仅进行仓库代码、fixture 和隔离测试。DFD-07 前必须分别得到生产 migration、正式
数据删除和真实 RQData 重建的单次明确执行意图；不把测试、dry-run 或 develop 合并当作授权。

## Risks

- 单月替换会增加 1m 月度 IO；以自然月限定范围，优先一致性和简单维护。
- 文件 replace 与 Catalog transaction 不跨系统 ACID；reader 只信 Catalog 所指、完整且可读的月，失败
  保留最后有效月。
- 退出旧接口会立即暴露 caller；DFD-02～DFD-06 按顺序删除引用并做 API/Web/CLI 全量验证。
