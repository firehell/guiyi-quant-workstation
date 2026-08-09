---
name: futures-data
description: 当任务涉及米筐 RQData 期货数据下载、合约元数据、品种池、Canonical Parquet、Catalog、数据质量检查或 guiyi data CLI 时使用。
---

# 期货数据中心 Skill

## 项目定位

Active 主链路（唯一）：

```text
RQData
-> 临时 staging
-> 六项硬校验
-> 单一 historical canonical Parquet（月分区 part.parquet）
-> 八表 Catalog / MainContractMap
-> MarketDataService
-> Market API / guiyi data / 研究消费者
```

事实源只认：

1. `STATUS.md`
2. `docs/DATA_CENTER.md`
3. `services/quant-api/app/market_data/`

长期边界见 `AGENTS.md` / `PROJECT_SOURCE.md`；active 业务合同见 `docs/tasks/GY-DATA-CORE-V2.md`。

## active 数据入口

- 物理 `DatasetKey=(kind, symbol, series_or_contract, frequency)`
- 物理 kind 只有 `continuous|contract`；`actual_dominant` 只在查询时由 `MainContractMap rank=1` 拼接
- Direct：`1m/1d/1w`；Derived：`5m/15m/30m/60m`（只从同 Dataset Canonical `1m` 按 Session 聚合）
- 消费者不得自行 glob、选择 active、判断主力或绕过完整性校验
- 正式 CLI：`guiyi data update|refresh|audit`

## 必做

- 米筐 license / addr 只读环境变量，不写入代码库。
- 历史行情以 Canonical Parquet 存储；PostgreSQL 只存八表 Catalog/元数据。
- 发布前完成 schema/session/duplicate/OHLCV/coverage、identity、row-count 与物理可读性校验。
- 月分区以同文件系统临时文件原子替换 `part.parquet`；失败保留最后有效 canonical。
- 映射、分区、coverage 或物理完整性异常必须显式失败。

## 关键代码

- `services/quant-api/app/market_data/`（Catalog / Storage / MarketDataService / HistoricalDataManager / RQData adapter）
- `services/quant-api/app/guiyi_cli/data_commands.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/models/market_tables.py`

## 建议分区

```text
data/canonical/{kind}/{symbol}/{series_or_contract}/{frequency}/yyyy/mm/part.parquet
```

具体根路径与相对 URI 规则以 `docs/DATA_CENTER.md` 与 `market_data/storage.py` 为准。

## 禁止

- 不要把分钟线、tick 全量塞进 PostgreSQL。
- 不要恢复 `data_core` / `rqdata_ingest` / `data_operations` / Profile-Binding / Hive 路径。
- 不要把主力连续合约当成可直接交易合约，除非任务明确只做研究展示。
- 不要把 TqSdk、TuShare、AKShare 作为主数据源或默认 active 输入。
- 不要提交 `.env`、米筐 license、Webhook。
- 不要把 live observation 直接提升为正式历史 active。

## 验证

- 只读：`uv run --project services/quant-api guiyi data audit ...`
- 定向：`uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation`
- 需要 provider 探测时再 `import rqdatac`；任何 dry-run 不授权真实写入。
