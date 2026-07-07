---
name: futures-data
description: 当任务涉及米筐 RQData 期货数据下载、合约元数据、品种池、K线清洗、Parquet、DuckDB、数据质量检查时使用。
---

# 期货数据中心 Skill

## 项目定位

V1 主链路：

```text
RQData / rqdatac
-> raw parquet
-> standard parquet
-> manifest / checksum / quality report
-> PostgreSQL market_data_files / data_quality_reports
-> DuckDB read_parquet
-> Market / Backtest / Signal / Review
```

事实源优先读 `docs/DATA_CENTER.md`、`docs/DATA_UNIVERSE_AND_ARCHIVE.md`。

## active 数据入口

正式默认读取只允许：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status = "passed"`。

不得进入正式默认读取：`validation`、`legacy_reference`、`candidate`、`failed`、旧天勤数据、交易练习者数据。

## 必做

- 米筐 license / addr 只读环境变量，不写入代码库。
- 历史行情以 Parquet 存储，PostgreSQL 只存元数据、任务、质量报告。
- DuckDB 负责本地研究查询和回测前批量读取。
- 标准字段至少包含 `datetime/open/high/low/close/volume/open_interest`。
- 每次下载后生成质量检查：缺失、重复、异常价、时间断点、合约到期后数据。
- 合约元数据维护乘数、最小变动、手续费、保证金率。

## 关键代码与脚本

- `services/quant-api/app/services/rqdata_ingest/*`
- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/api/data_center.py`
- `scripts/rqdata_live_1m_ingest.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`

## 建议分区

```text
data/parquet/canonical/bars/provider=rqdata/symbol=jm/timeframe=5m/year=2024/month=01/part-000.parquet
```

## 禁止

- 不要把分钟线、tick 全量塞进 PostgreSQL。
- 不要没有数据质量报告就接回测。
- 不要把主力连续合约当成可直接交易合约，除非任务明确只做研究展示。
- 不要把 TqSdk、TuShare、AKShare 作为 V1 主数据源或默认 active 输入。
- 不要提交 `.env`、米筐 license、Webhook。

## 验证

- `uv run --project services/quant-api python -c "import rqdatac; print('rqdatac ok')"`。
- 能写入 sample parquet，并用 DuckDB 读出行数和时间范围。
- 数据下载任务、失败原因、data_version 可追踪。
