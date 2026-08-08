## Why

当前行情链路同时保留 DatasetKey/Catalog/Manifest/Gap 与 MarketDataFile/Profile/Binding/QualityReport 两套 active 数据语言，导致增量、标准化、主力拼接和消费者读取不能形成单一可信闭环。现在需要按个人量化工作站边界一次性收口：RQData 是唯一外部事实源，Canonical Parquet 是唯一历史 Bar 存储，PostgreSQL 只保留最小目录与期货元数据，所有消费者只经 MarketDataService 读取。

## What Changes

- **BREAKING** 将物理 Dataset 身份收敛为四字段 `(kind, symbol, series_or_contract, frequency)`，物理 kind 只允许 `continuous` 与 `contract`；provider、adjustment 与 schema version 移入 Manifest。
- **BREAKING** 将 Canonical 收敛为每 Dataset 每自然月一个当前有效 Parquet 分区；直接周期为 `1m/1d/1w`，派生周期只从质量通过的 Canonical `1m` 聚合。
- **BREAKING** 将 PostgreSQL active 数据表收敛为交易所、合约、日历/时段、主力映射、每日合约参数与 Catalog/Gap 十张表，并以不可逆迁移 drop 旧 Data Center/Profile/Binding/QualityReport 语言相关表。
- **BREAKING** 将公开行情查询改为 `continuous | contract | actual_dominant` 三种 series；`actual_dominant` 由 rank1 MainContractMap 查询时拼接，不再持久化重复 Parquet。
- **BREAKING** 将用户 CLI 收敛为 `data update|bootstrap|repair|audit`，删除公开 `download|aggregate|sync|verify` 与 legacy migration/task/receipt 入口。
- 新增 `MetadataSynchronizer`、`HistoricalDataManager` 与精简 `MarketDataService` 三个深模块，统一覆盖规划、标准化、六项硬校验、月分区发布、聚合、Gap 生命周期和严格读取。
- **V1 Recent Trusted Window**：正式 `active_history_floor = 2023-01-01`；`effective_start(symbol) = max(product_window_start, floor)`。Gate A 改为隔离 Candidate 上的 **RQData-only `update`**，不再以 legacy 白名单作为新 Gate A 数据源。既有 migration-only legacy bootstrap 实现进入 freeze，Gate C 通过后删除；最终重建语义为自 floor 起的 RQData 重建，不是 1999+ 全历史。
- 吸收 `m3-v2-production-correctness` 尚未完成的周线、精确缺口、固定水位幂等、实际交易所 session identity 与生产验收要求；旧 change 标记 superseded 后以 `--skip-specs` 归档，不把未完成任务记为完成。
- 保持 daily scheduler、live、通知和订单能力关闭；本 change 不重建回测、Signal/Review 或交易能力。

## Capabilities

### New Capabilities

- `data-foundation-metadata`: active 69 品种的交易所、合约、日历、交易时段、rank1 主力映射、每日合约参数和最小 Catalog/Gap 数据模型。
- `canonical-market-storage`: 四字段 DatasetKey、月分区 Canonical Parquet、Manifest、标准化、六项硬校验、原子发布与 1m 派生聚合。
- `historical-data-maintenance`: update/bootstrap/repair/audit 四动作、精确历史缺口、固定水位幂等、故障隔离、DataGap 生命周期与 Recent Trusted Window 候选构建。
- `market-series-query`: continuous/contract/actual_dominant 统一查询、周线主力归属、严格缺口阻断和可复算查询 lineage。

### Modified Capabilities

- （无；`openspec/specs/` 当前没有既有能力，本 change 创建新的完整行为合同。）

## Impact

- 后端领域、ORM、Alembic、RQData/Parquet/DuckDB/PostgreSQL adapters、统一 CLI 与 `/api/v1/market` 合同将发生 breaking 变更。
- Market Web 类型与 evidence 展示删除 Profile/Binding/QualityReport/legacy lineage 字段。
- active legacy importer、task07/historical migration、generic ingestors、ActiveDataset 与 CanonicalBarLoader 兼容接口及无调用脚本/文档将删除。
- 真实 RQData、生产 PostgreSQL、正式 Canonical 和服务切换仍分别受一次性精确执行 Gate 控制；代码实现与本地隔离验证不授权这些外部 mutation。
