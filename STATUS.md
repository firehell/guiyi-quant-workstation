# 当前状态

更新时间：2026-08-09

## 结论

Data Foundation 已完成 **DFD-01～DFD-06**，并已进入 **DFD-07**：生产 PostgreSQL 已从
`20260808_0035` 升级至最终不可逆 `20260808_0036`，盘点范围内的旧正式数据已删除。固定
`T0=2026-08-07` 的 JM 重建已真实启动，但在首轮达到 provider quota 后按合同停止；69 品种重建及
完整历史 Canonical 验收尚未完成。

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

DFD-02 已删除退出的维护面、legacy importer、旧 CLI 入口及其生成工件。DFD-03 已将
storage、Catalog、ORM 和最终 `20260808_0036` 收口为八表与单月 `part.parquet`，并已在正式 PostgreSQL
完成 migration。DFD-04 已验证三种查询、周线 rank1 owner 和 Derived physical partition 读取，并移除
Market API/Web 的 digest 展示。DFD-05 已实现 `update|refresh|audit`、完整月 refresh、quota partial
自然续传和本地 Derived 优先重建。DFD-06 已运行后端/工程全量、前端 test/build、Ruff、Mypy 和严格
OpenSpec 验证，并将 active Canonical 一致性断言从退出的发布/缺口合同收口为八表、完整性和
原子月分区发布合同。

## 外部操作状态

在用户明确的一次性执行意图下，已执行生产 `0035→0036` migration，删除 `data/raw`、
`data/processed`、`data/parquet/canonical` 与 `data/canonical-candidates`，并启动 JM 的真实 RQData
重建。migration 后八张 active 表已验收，旧 Catalog 已清空；JM 当前只有部分 continuous 分区，
`actual_dominant` 因缺少 concrete-contract 分区保持 fail-closed。provider quota 停止后不得在同一
额度周期继续调用。未执行服务切换、main/tag/release 或 Runtime promotion。

日调度、live、真实通知和自动订单保持关闭，`auto_order=false`。
