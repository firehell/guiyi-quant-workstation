---
name: database-modeling
description: 当任务涉及归一量化 PostgreSQL 表结构、SQLAlchemy 模型、Alembic 迁移、索引、关系、元数据和报告存储设计时使用。
---

# Database Modeling Skill

## 存储边界

- PostgreSQL：元数据、任务、策略、版本、报告、交易明细、信号、复盘、风控事件。
- Parquet：历史 K 线、tick、大体量行情。
- DuckDB：本地研究查询、批量统计、回测前读取。

## V1 表组

- 基础：`instruments`、`contracts`、`trading_calendars`。
- 数据：`data_download_tasks`、`data_quality_reports`。
- 策略：`strategies`、`strategy_versions`、`strategy_parameters`。
- 回测：`backtest_tasks`、`backtest_reports`、`backtest_trades`。
- 信号：`signals`、`signal_scan_tasks`。
- 复盘：`review_notes`、`review_tags`。
- 风控：`risk_profiles`、`risk_events`。

## 输出

- 表结构、字段类型、关系。
- 索引和常用查询。
- Alembic 迁移建议。
- 哪些数据不应进入 PostgreSQL。
- 后续扩展点。

## 禁止

- 不要把分钟线和 tick 全部入库。
- 不要所有字段都用 JSONB。
- 不要缺少策略版本和回测任务关联。
- 不要保存真实账号密码、API key、交易密码。
