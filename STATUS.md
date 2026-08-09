# 当前状态

更新时间：2026-08-09

## 结论

Data Foundation 已完成 **DFD-01～DFD-06**，并已进入 **DFD-07**：生产 PostgreSQL 已从
`20260808_0035` 升级至最终不可逆 `20260808_0036`，盘点范围内的旧正式数据已删除。固定
`T0=2026-08-07` 的 JM 重建已完整闭环：已发布 678 个 JM 月分区（continuous 308、真实合约
370），JM `update` dry-run 为 NOOP、JM audit 通过，Catalog、物理 Parquet 与
`MarketDataService` 的 continuous / contract / actual_dominant 有界读回均已验收。此前周线与
Derived 开放月 Session 上界缺陷已修复；补齐两个周线 Direct 与四个 Derived 分区的受控执行
成功完成（2 次 provider 请求、6 个分区发布）。其余 59 个 active 品种尚无正式 Canonical
分区，且历史 Session facts 未完整；60 品种重建及全域 Canonical 验收仍未完成。退役品种含
股指 `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu`；
生产 Catalog 已对退役名单执行 `retire-products --apply`（详见 `GY-DATA-PRODUCT-RETIREMENT-5`）。

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
- 最终公开 CLI 为 `guiyi data update|refresh|audit|retire-products`。`update` 以数据库和已发布月度
  Parquet 自然续传；`refresh` 按指定品种和日期范围强制重建相交月份；`audit` 只读；
  `retire-products` 清退已退役品种 Catalog/Canonical（默认 dry-run）。

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
仅为观察镜像。旧 `guiyi_quant/strategies/` vn.py 策略研究包及对应策略测试已退役；HTDY strict 计算源
收口为 `guiyi_quant.indicators.htdy_strict.compute_strict_fields`。事实源仍只认 `STATUS.md`、
`docs/DATA_CENTER.md` 与 `app/market_data/`。

## 外部操作状态

在用户明确的一次性执行意图下，已执行生产 `0035→0036` migration，删除 `data/raw`、
`data/processed`、`data/parquet/canonical` 与 `data/canonical-candidates`，并启动 JM 的真实 RQData
重建。migration 后八张 active 表已验收，旧 Catalog 已清空；JM 先完成 672 个物理月分区，随后在
新的精确单次意图下补齐 `JM2405/1w/2024-04`、`JM2505/1w/2025-04` 与
`JM2609/{5m,15m,30m,60m}/2026-08`。该次执行 `applied=6`、`failed=0`、
`provider_requests=2`；其后 JM fixed-T0 dry-run 为 NOOP、JM audit 通过，678 个 Catalog
分区及对应 Parquet 均可读。`actual_dominant` 在缺少对应 concrete-contract 分区时仍保持
fail-closed；其余 59 品种的历史 Session facts 与 Canonical 重建仍需后续受控执行。在明确单次
意图下已多次对生产执行 `guiyi data retire-products --apply`，覆盖退役名单
`br/cs/ic/if/ih/im/lu/nr/sp`；Canonical 退役目录均为 0，事后 residual=0，显式退役码返回
`PRODUCT_RETIRED`。未执行服务切换、main/tag/release 或 Runtime promotion。

日调度、live、真实通知和自动订单保持关闭，`auto_order=false`。
