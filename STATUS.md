# 当前状态

更新时间：2026-08-09

## 结论

Data Foundation 已完成 **DFD-01～DFD-06**，并已进入 **DFD-07**：生产 PostgreSQL 已从
`20260808_0035` 升级至最终不可逆 `20260808_0036`，盘点范围内的旧正式数据已删除。固定
`T0=2026-08-07` 的 JM 重建已真实启动并完成一次自然续传；当前已发布 670 个 JM 月分区，但固定
T0 的只读计划与 audit 仍各有 12 个目标/缺口。最近一次继续执行在下载前被
`TRADING_SESSION_MISSING` 阻止，未写入数据；其 Derived 开放月 Session 上界缺陷已修复并完成本地回归。
69 品种重建及完整历史 Canonical 验收尚未完成。

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

工程双轨收口（2026-08-09）：旧 `data_core` / `rqdata_ingest` 等空壳与 pycache、退役 worker 启动面、
孤儿 data_profiles / v2_targets、未用 ECharts/DuckDB 依赖已清；Market coverage/dominants 经
`MarketDataService`；ORM 合并为 `models/market_tables.py`；指标权威定为 quant-core Kernel，Web TS
仅为观察镜像。事实源仍只认 `STATUS.md`、`docs/DATA_CENTER.md` 与 `app/market_data/`。

## 外部操作状态

在用户明确的一次性执行意图下，已执行生产 `0035→0036` migration，删除 `data/raw`、
`data/processed`、`data/parquet/canonical` 与 `data/canonical-candidates`，并启动 JM 的真实 RQData
重建。migration 后八张 active 表已验收，旧 Catalog 已清空；JM 已完成一次续传并发布 670 个物理月
分区。该命令的终端结构化 payload 未被执行包装层保留，因此未把停止原因推断为 quota；只读 plan/audit
已确认仍各有 12 个目标/缺口，且未追加 provider 请求。随后一次用户授权的 JM 续传在任何下载或数据写入
之前被 `TRADING_SESSION_MISSING` 阻止；根因是 Derived 聚合为开放月枚举至月末、越过固定 T0。实现现已将
该查询上界收紧为目标末端覆盖日，并通过生产 Catalog 的只读 Session 检查。`actual_dominant` 在缺少对应
concrete-contract 分区时保持 fail-closed。未执行服务切换、main/tag/release 或 Runtime promotion。

日调度、live、真实通知和自动订单保持关闭，`auto_order=false`。
