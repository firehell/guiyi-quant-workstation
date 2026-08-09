---
name: database-modeling
description: 当任务涉及归一量化 PostgreSQL 表结构、SQLAlchemy 模型、Alembic 迁移、索引、关系、元数据和报告存储设计时使用。
---

# Database Modeling Skill

## 存储边界

- PostgreSQL：八表 Catalog / MainContractMap / Calendar / Session 元数据；不存全量 K 线。
- Canonical Parquet：历史 K 线月分区 `part.parquet`。
- 读取门面：`MarketDataService`（不是 DuckDB 主链路）。

事实源：`STATUS.md`、`docs/DATA_CENTER.md`、`app/models/market_tables.py`。

## Active 八表

- `exchanges`
- `instruments`
- `contracts`
- `trading_calendars`
- `trading_sessions`
- `main_contract_map`
- `market_datasets`
- `market_partitions`

候选/最终 Alembic 收口见 `20260808_0036`；生产 migration 需单次执行意图。

## 已退出、不得复活为 active 表组

旧 Profile/Binding、data_quality_reports 主读路径、signal/review/strategy/backtest/live 业务表均已退役或非 active migration asset。恢复只能走新任务新合同，不以旧表为兼容入口。

## 输出

- 表结构、字段类型、关系。
- 索引和常用查询。
- Alembic 迁移建议。
- 哪些数据不应进入 PostgreSQL。

## 禁止

- 不要把分钟线和 tick 全部入库。
- 不要所有字段都用 JSONB。
- 不要把 Catalog coverage 拆成第二套缺口状态表。
- 不要保存真实账号密码、API key、交易密码。
