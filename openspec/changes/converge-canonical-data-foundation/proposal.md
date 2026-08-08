## Why

当前仓库已具备四字段 DatasetKey、月度 Canonical、三个深模块和 Market-only 消费面，但 active
合同仍保留候选构建、发布 Gate、内容清单、缺口状态、合约参数和一次性迁移工具等双重语言。它们不服务
个人本地历史行情底座，反而让存储、Catalog、查询和维护接口持续复杂化。

## What Changes

- **BREAKING** active 数据模型固定为八表；退出 `contract_specs`、`data_gaps` 和所有发布清单/内容
  摘要字段。
- **BREAKING** 月分区只发布 `part.parquet`；可用性由 Catalog identity、coverage、row count 和文件
  可读性共同确定。
- **BREAKING** CLI 最终仅保留 `data update|refresh|audit`，退出 bootstrap、exact-plan repair 及
  Candidate/Gate/Promotion 操作面。
- **BREAKING** Market 查询响应退出 partition/source/session/map digest，仅保留请求、bars、coverage
  与 resolved contract segments。
- `update` 以 Catalog + 已发布月作为唯一 checkpoint，支持固定 through、1G/day quota 中止和自然续传；
  `refresh` 重建指定品种/窗口的完整数据族。
- 保留四字段 DatasetKey、Direct/Derived、实际 Calendar/Session、rank1 MainContractMap、月分区和
  `MarketDataService`；不重建回测、Signal/Review、live、通知或订单能力。

## Capabilities

### Modified Capabilities

- `canonical-market-storage`: 移除内容清单，保留最小 Parquet 发布和六项校验。
- `data-foundation-metadata`: 收口为八表及 Calendar/Session/MainContractMap 当前事实。
- `historical-data-maintenance`: 收口为 update/refresh/audit、fixed through 和 quota natural resume。
- `market-series-query`: 以 Catalog + Parquet 严格读取，最小化公开响应 lineage。

## Impact

后续 DFD-02～DFD-06 会修改后端领域、ORM、Alembic、Parquet adapters、CLI、API、Market Web 与相关
测试。DFD-01 只重置合同；生产 `0035→0036`、正式数据删除/重建和真实 RQData 调用不在本 change 的
普通仓库授权内，须在 DFD-07 前重新取得各自范围明确的一次性执行意图。
