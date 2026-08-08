# GY-DATA-CORE-V2：Canonical Data Foundation active 合同

更新时间：2026-08-08

## 目标

用一套 active 数据语言完成个人期货研究工作站的数据基础闭环：

```text
RQData
-> temporary staging
-> normalization + six hard validations
-> one Canonical Parquet root
-> PostgreSQL minimal Catalog
-> MarketDataService
-> Market Web / Indicator / future research
```

active universe 精确为 `data/universe/active_products.txt` 中的 69 品种。只有七个周期：
`1m/5m/15m/30m/60m/1d/1w`。

V1 active 历史范围为 Recent Trusted Window：`active_history_floor = 2023-01-01`。

## 已冻结的合同

- 物理 Dataset 只有 `continuous | contract`。
- DatasetKey 只有 `(kind, symbol, series_or_contract, frequency)` 四字段。
- `actual_dominant` 只是查询模式，不存在物理 Parquet。
- continuous、contract 和 actual_dominant 身份显式且不可互换。
- RQData 是唯一外部事实源；Canonical Parquet 是唯一 active 历史 Bar 存储。
- `1m/1d/1w` 为 direct；`5m/15m/30m/60m` 只从 Canonical 1m 聚合。
- PostgreSQL 只保存 10 张最小数据表，不保存 Bar 或运行历史。
- 每 Dataset 每月只有一个 active 分区；不保留 active overlay 或 data version 目录。
- DataGap 只保存当前未解决缺口。
- 所有历史消费者必须经过 MarketDataService。
- `effective_start(symbol) = max(product_window_start, active_history_floor)`；不得改写 `product_window_starts.csv` 长期事实。

## 应用模块

1. `MetadataSynchronizer`: 交易所、合约、日历、session、rank1 map 和 contract specs 当前事实。
2. `HistoricalDataManager`: `update/bootstrap/repair/audit` 四个动作，共享规划、下载、标准化、校验、发布与聚合算法。
3. `MarketDataService`: 只通过 Catalog/Manifest 读取 continuous、contract 和 actual_dominant。

## CLI

```text
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data bootstrap --universe active [--through DATE] [--apply]
guiyi data repair --plan exact-plan.json [--apply]
guiyi data audit --universe active
```

无 `--apply` 的 update/bootstrap/repair 只计划、零 RQData、零写入。`audit` 只读。

## Candidate 与 legacy

新 Gate A 在隔离 Candidate DB + Candidate Canonical Root 上使用 **RQData-only `update`**（`legacy=None`），复用正常 HistoricalDataManager，不新建重建引擎。

既有 migration-only legacy 白名单 bootstrap 实现进入 freeze：不新增能力、不参加新 Gate A。旧 raw/processed 本次不删除，也不得进入日常更新组装、active Catalog 或 MarketDataService。Gate C 通过后删除临时读取器；最终重建为自 `active_history_floor` 起的 RQData 重建。

## 验收与 Gate

### 普通代码验收

- domain/storage/catalog/maintenance/service 定向测试通过。
- 后端全套、ruff、mypy、前端 unit/build 通过。
- Alembic offline SQL 通过；隔离 PostgreSQL 可用时跑实际升级测试。
- active 代码、前端和 canonical 文档不依赖已退役数据语言。
- Recent Trusted Window policy 与 RQData-only Candidate composition 本地验证通过。

### 受控外部 Gate

1. **Gate A**：JM → 六交易所 canary → active 69；隔离 Candidate；RQData-only；audit=0；DataGap=0；same-T NOOP。各写入步骤分别需要一次性意图。
2. **Gate B**：给出确切生产表、候选根、正式根和服务范围；新意图后才 `0035→0036` 并原子切根。
3. **Gate C**：floor 后 69 品种七周期可读、DataGap=0、map/spec 完整、actual-dominant 换月/周线正确、fixed-through NOOP。

日调度、live、通知与自动订单始终不在本任务授权内；`auto_order=false`。

## OpenSpec

active change 为 `converge-canonical-data-foundation`。旧 M3 已以 superseded 历史归档，不再并行执行。
