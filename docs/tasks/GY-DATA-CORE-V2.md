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

## 一次性迁移

本次候选 bootstrap 允许显式白名单读取旧 RQData Parquet，但必须经过与供应商数据相同的
标准化和六项校验。一个窗口只允许一个无歧义候选；失败则生成精确 RQData 重下窗口，
不做逐行多源裁决。

旧 raw/processed 文件本次不删除。它们不得进入日常更新组装、active Catalog 或 MarketDataService。
最终 Gate C 通过后删除临时读取器，bootstrap 只支持 RQData 全量重建。

## 验收与 Gate

### 普通代码验收

- domain/storage/catalog/maintenance/service 定向测试通过。
- 后端全套、ruff、mypy、前端 unit/build 通过。
- Alembic offline SQL 通过；隔离 PostgreSQL 可用时跑实际升级测试。
- active 代码、前端和 canonical 文档不依赖已退役数据语言。

### 受控外部 Gate

1. **Gate A**: 给出 69 品种、fixed through、候选根、Dataset/月分区和 RQData 精确窗口；取得一次性意图后才构建隔离候选。
2. **Gate B**: 给出确切生产表、候选根、正式根和服务范围；新意图后才迁移数据库并原子切换。
3. **Gate C**: 69 品种七周期可读、DataGap=0、map/spec 完整、actual-dominant 换月/周线正确、fixed-through NOOP。

日调度、live、通知与自动订单始终不在本任务授权内；`auto_order=false`。

## OpenSpec

active change 为 `converge-canonical-data-foundation`。旧 M3 已以 superseded 历史归档，不再并行执行。
