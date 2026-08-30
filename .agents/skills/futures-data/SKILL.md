---
name: futures-data
description: Use when 任务涉及归一量化 RQData、期货合约数据、Canonical Parquet、八表 Catalog、SQLAlchemy 市场模型、Alembic 数据迁移、MainContractMap、数据质量或 guiyi data CLI。
---

# 期货数据与 Catalog

用于 RQData、Canonical Parquet、Catalog、MainContractMap、数据质量、Alembic 或 `guiyi data` 任务。

先读 `AGENTS.md`、`STATUS.md`、`docs/DATA_CENTER.md` 与相关 OpenSpec：

- Catalog：`openspec/specs/data-foundation-metadata/spec.md`
- Canonical：`openspec/specs/canonical-market-storage/spec.md`
- 维护：`openspec/specs/historical-data-maintenance/spec.md`
- 查询：`openspec/specs/market-series-query/spec.md`

实现入口为 `services/quant-api/app/market_data/`、`app/models/market_tables.py` 与
`app/guiyi_cli/data_commands.py`。验证命令以 `TESTING.md` 为准；定向测试位于
`services/quant-api/tests/data_foundation/` 与 `services/quant-api/tests/alembic/`。
