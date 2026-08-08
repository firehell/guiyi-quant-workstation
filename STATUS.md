# 当前状态

更新时间：2026-08-08

## 结论

Canonical Data Foundation 新架构已进入本地候选实现阶段：四字段 DatasetKey、月度
Canonical 分区、最小 Catalog、三个深模块、四个 data CLI 与新 Market 查询合同已实现。

该结论仅表示仓库代码与本地 fixture 验证进度，不表示生产数据库、正式 Canonical、
Runtime 或 69 品种真实数据已经切换。

## 当前可执行面

- Web：Market 工作台。
- API：`/api/v1/market/*`、`/api/runtime/*`。
- CLI：`guiyi data update/bootstrap/repair/audit`、`guiyi runtime status`。
- 数据：RQData 唯一外部事实源，Canonical Parquet 唯一 active 历史 Bar 存储目标。
- 品种：`data/universe/active_products.txt` 精确 69 个。
- 周期：`1m/5m/15m/30m/60m/1d/1w`。

当前不存在 backtest API/Web/worker、Signal/Review/Strategy 应用面或盘中 Live 路径。日调度、
live、真实通知和自动订单保持关闭。

## 数据基础候选实现

- `MetadataSynchronizer`：幂等同步日历、session、rank1 MainContractMap 和 contract specs。
- `HistoricalDataManager`：共享 update/bootstrap/repair/audit 的覆盖规划、标准化、
  六项校验、月分区发布、1m 聚合和 DataGap 处理。
- `MarketDataService`：唯一历史行情入口，支持 continuous、contract 和查询时
  actual-dominant 拼接。
- Alembic `20260808_0036`：候选不可逆最小 schema，未应用生产。
- OpenSpec：`converge-canonical-data-foundation` active；旧 M3 已 superseded 归档。

## 本地验证

- 后端与工程完整回归：2503 passed，56 skipped；其中隔离 PostgreSQL migration tests
  因未配置专用可丢弃数据库而跳过。
- ruff、mypy、OpenSpec strict validation、Alembic `0035:0036 --sql` 均通过。
- 前端：52 passed，1 skipped；TypeScript 与生产 build 通过。
- 浏览器 smoke 已验证 Market-only 页面、新 series query 和缺少正式候选数据时的
  fail-closed 提示；不构成 Gate C 数据验收。

## 已确认的现有生产事实

以 2026-08-08 先前的只读回读为限：生产 Alembic head 为 `20260808_0035`，正式 Canonical
根已配置，69 品种的实际交易所 Calendar/Session 元数据已存在，且当时 DataGap=0。
这些是前序现场事实，不证明新数据合同已迁移或 Gate C 已通过。

## 未完成的外部 Gate

1. **Gate A**：用固定 through 为 69 品种构建隔离候选 Canonical/Catalog，必要窗口精确调用 RQData。
2. **Gate B**：维护窗口内应用 `20260808_0036`，写入候选 Catalog 并原子切换正式 Canonical。
3. **Gate C**：验证 69 品种七周期、DataGap=0、map/spec 完整、actual-dominant 换月/周线与 fixed-through NOOP。
4. Gate C 通过后才删除一次性候选 bootstrap 读取器并归档新 OpenSpec change。

以上每个真实 mutation Gate 都需要目标和范围明确的新一次性执行意图。
