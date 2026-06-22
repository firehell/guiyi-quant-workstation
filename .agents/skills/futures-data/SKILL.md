---
name: futures-data
description: 当任务涉及天勤 TqSdk 期货数据下载、合约元数据、品种池、K线清洗、Parquet、DuckDB、数据质量检查时使用。
---

# 期货数据中心 Skill

## 项目定位

V0/V1 优先跑通：天勤 TqSdk 下载 -> 清洗 -> Parquet -> DuckDB 查询 -> 后端 API -> 前端 K 线/回测读取。Tushare/AKShare 只能作为后备数据源，不替代天勤主链路。

## 必做

- TqSdk 账号、密码、授权信息只读环境变量，不写入代码库。
- 历史行情以 Parquet 存储，PostgreSQL 只存元数据、任务、质量报告。
- DuckDB 负责本地研究查询和回测前批量读取。
- 标准字段至少包含 `datetime/open/high/low/close/volume/open_interest`。
- 每次下载后生成质量检查：缺失、重复、异常价、时间断点、合约到期后数据。
- 合约元数据维护乘数、最小变动、手续费、保证金率。

## 建议分区

```text
data/parquet/exchange=SHFE/product=rb/symbol=rb2405/timeframe=1m/year=2024/month=01/part-000.parquet
```

## 禁止

- 不要把分钟线、tick 全量塞进 PostgreSQL。
- 不要没有数据质量报告就接回测。
- 不要把主力连续合约当成可直接交易合约，除非任务明确只做研究展示。
- 不要提交 `.env`、天勤账号密码、Webhook。

## 验证

- `uv run python -c "import tqsdk; print(tqsdk.__version__)"`。
- 能写入 sample parquet，并用 DuckDB 读出行数和时间范围。
- 数据下载任务、失败原因、数据版本可追踪。
