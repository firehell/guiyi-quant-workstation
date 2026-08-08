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
- V1 Recent Trusted Window：`data/universe/active_history_floor.txt` = `2023-01-01`；
  `effective_start = max(product_window_start, floor)`；RQData-only Candidate composition
  已提供；legacy Gate A 路径已 freeze。
- Alembic `20260808_0036`：候选不可逆最小 schema，未应用生产。
- OpenSpec：`converge-canonical-data-foundation` active；旧 M3 已 superseded 归档。

## 本地验证

- 后端与工程完整回归：262 passed，13 skipped（含 data_foundation 91）。
- ruff、mypy 与 OpenSpec strict validation 均通过。
- Alembic `0035:0036 --sql` 通过；隔离 PostgreSQL 升级测试本轮未配置 URL，未重跑。
- 前端：52 passed，1 skipped；生产 build（含 `vue-tsc`）通过。
- 浏览器 smoke 与真实 RQData/Candidate 写入本轮未执行。

## 已确认的现有生产事实

以 2026-08-08 先前的只读回读为限：生产 Alembic head 为 `20260808_0035`，正式 Canonical
根已配置，69 品种的实际交易所 Calendar/Session 元数据已存在，且当时 DataGap=0。
这些是前序现场事实，不证明新数据合同已迁移或 Gate C 已通过。

## 未完成的外部 Gate

合同已改为 **RQData-only Recent Trusted Window**（`active_history_floor=2023-01-01`）；下列
Gate 的真实 mutation 尚未执行：

1. **Gate A**：JM → 六交易所 canary → active 69；隔离 Candidate；RQData-only update；audit=0；
   DataGap=0；same-T NOOP。
2. **Gate B**：维护窗口内应用 `20260808_0036`，写入候选 Catalog 并原子切换正式 Canonical。
3. **Gate C**：验证 floor 后 69 品种七周期、DataGap=0、map/spec 完整、actual-dominant 换月/周线与
   fixed-through NOOP。
4. Gate C 通过后才删除 migration-only legacy 读取器并归档 OpenSpec change。

以上每个真实 mutation Gate 都需要目标和范围明确的新一次性执行意图。
