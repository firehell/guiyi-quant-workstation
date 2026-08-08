# 当前状态

更新时间：2026-08-09

## 结论

Data Foundation 已完成 **DFD-01～DFD-05**：目标架构现在是本地、单用户、可从 RQData 重建的
历史行情底座；月度 storage、最小 Catalog/ORM、候选 migration 及最小 Market 查询/API/Web 合同已收口。
此结论不表示 DFD-06 的代码收口、生产数据库迁移、正式 Canonical 重建或真实 RQData 下载已经发生。

## 已冻结的目标合同

- 物理 `DatasetKey=(kind, symbol, series_or_contract, frequency)`；物理 kind 只有
  `continuous|contract`，`actual_dominant` 只在查询时由 `MainContractMap rank=1` 拼接。
- Direct 周期是 `1m/1d/1w`；Derived 周期是 `5m/15m/30m/60m`，只从同 Dataset 的
  Canonical `1m` 按实际交易 Session 聚合。
- 每 Dataset 每自然月只有一个 `part.parquet`。发布前保留 schema、identity、OHLCV、
  session/frequency、coverage 和物理可读性校验；Catalog coverage、row count 和可读文件共同
  表示可用状态。
- PostgreSQL active 数据模型最终为八表：`exchanges`、`instruments`、`contracts`、
  `trading_calendars`、`trading_sessions`、`main_contract_map`、`market_datasets`、
  `market_partitions`。
- 最终公开 CLI 为 `guiyi data update|refresh|audit`。`update` 以数据库和已发布月度
  Parquet 自然续传；`refresh` 按指定品种和日期范围强制重建相交月份；`audit` 只读。

## 当前实现差异

DFD-02 已删除 Candidate/Gate/Promotion、legacy importer、旧 CLI 入口及其生成工件。DFD-03 已将
storage、Catalog、ORM 和候选 `20260808_0036` 收口为八表与单月 `part.parquet`，并仅在隔离 PostgreSQL
中验证 migration。DFD-04 已验证三种查询、周线 rank1 owner 和 Derived physical partition 读取，并移除
Market API/Web 的 digest 展示。DFD-05 已实现 `update|refresh|audit`、完整月 refresh、quota partial
自然续传和本地 Derived 优先重建；DFD-06 负责最终全量验证。在 DFD-06 完成前，不把所有 active 引用收口
表述为已实现。

## 外部操作状态

未执行真实 RQData 下载、正式 Canonical 写入/删除/重建、生产 PostgreSQL migration、服务切换、
main/tag/release 或 Runtime promotion。DFD-07 才处理真实数据清理和重建，且每项外部 mutation
都需要其目标、范围和时间窗明确的一次性执行意图。

日调度、live、真实通知和自动订单保持关闭，`auto_order=false`。
