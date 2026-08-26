---
name: futures-data
description: Use when 任务涉及归一量化 RQData、期货合约数据、Canonical Parquet、八表 Catalog、SQLAlchemy 市场模型、Alembic 数据迁移、MainContractMap、数据质量或 guiyi data CLI。
---

# 期货数据与 Catalog

## 核心边界

唯一 Historical 事实链是：

```text
RQData -> staging + hard validation -> Canonical Parquet
       -> 八表 Catalog + MainContractMap -> MarketDataService
```

PostgreSQL 只保存 Catalog、lineage 与应用元数据，不保存全量 K 线。Alert 两表和 Execution
Review 四表是独立 Application Domain，不属于八表 Catalog。

先读 `STATUS.md`、`docs/DATA_CENTER.md` 和任务相关的 OpenSpec；Catalog 模型任务优先读取
`openspec/specs/data-foundation-metadata/spec.md`，Canonical 发布任务优先读取
`openspec/specs/canonical-market-storage/spec.md`。实现以
`services/quant-api/app/market_data/` 与 `app/models/market_tables.py` 为准。

## 必须保持

- 物理 `DatasetKey=(kind, symbol, series_or_contract, frequency)`；kind 只有
  `continuous|contract`，`actual_dominant` 只在查询时按 rank1 有效区间拼接。
- `1m/1d/1w` 与派生周期遵守 `docs/DATA_CENTER.md` 的来源和 Session 聚合合同。
- 发布前校验 schema、session、duplicate、OHLCV、coverage、identity、row-count 和物理可读性；
  月分区同文件系统原子替换，失败保留最后有效 Canonical。
- 消费者不得 glob、自选 active、自判主力、绕过质量状态或跨频回退。

## 数据库与 migration

- 八表是 `exchanges`、`instruments`、`contracts`、`trading_calendars`、
  `trading_sessions`、`main_contract_map`、`market_datasets`、`market_partitions`。
- 修改模型前检查当前 Alembic heads、现有 migration 与生产状态；新 migration 只从当前 head
  延伸，不改写或删除历史 migration。
- 从仓库根目录本地只读检查使用
  `uv run --project services/quant-api alembic -c services/quant-api/alembic.ini heads` 和
  `uv run --project services/quant-api alembic -c services/quant-api/alembic.ini history`。只有任务确实
  需要生产 schema readback 时，才通过既有 Git 外安全配置和同一 `-c` 路径执行 `alembic current`；
  不得回显配置或凭据，也不得把 readback 推导为 upgrade 授权。
- 索引、关系、约束和类型应服务真实查询与 identity；不以 JSONB 或第二套缺口表替代明确模型。
- 生产 migration、真实 DB 写入、RQData 下载和 Canonical 写入均需当次范围明确的执行意图。

## 关键入口与验证

- 数据实现：`services/quant-api/app/market_data/`
- 市场模型：`services/quant-api/app/models/market_tables.py`
- CLI：`services/quant-api/app/guiyi_cli/data_commands.py`
- 定向测试：`services/quant-api/tests/data_foundation/`、`services/quant-api/tests/alembic/`
- Catalog migration 的最小验证先运行上述两个目录的 pytest；涉及真实约束、索引或 downgrade
  行为时，再按 `TESTING.md` 运行 isolated PostgreSQL marker，最后按风险扩展完整后端检查。
- isolated PostgreSQL 只按 `TESTING.md` 使用专用、空白、可销毁数据库；普通 dry-run 不授权真实写入。

不得提交 `.env`、RQData license、Webhook 或任何凭据；配置缺失时 fail-closed。
