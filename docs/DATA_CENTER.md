# DATA_CENTER.md

生成时间：2026-07-07

## 1. 数据中心定位

数据中心负责把外部数据变成本地可信、可追溯、可复算的数据资产。

主链路：

```text
RQData
-> raw parquet
-> standard parquet
-> manifest / checksum / quality report
-> PostgreSQL market_data_files / data_quality_reports
-> DuckDB read_parquet
-> Market / Backtest / Signal / Review
```

## 2. active 数据入口

V1 active 数据入口只允许：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先：

```text
quality_status = "passed"
```

不得进入正式默认读取：

- validation
- legacy_reference
- candidate
- failed
- 旧 TqSdk / 天勤数据
- 交易练习者数据

## 3. 当前 JM v2 数据资产

Stage 2C / 2D / 2E 已完成。

| timeframe | rows | min datetime | max datetime | max trading_day | data_version |
|---|---:|---|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_1m_20230103_20260707_v2` |
| 5m | 57891 | 2023-01-03 09:05 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_5m_20230103_20260707_v2` |
| 15m | 19297 | 2023-01-03 09:15 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_15m_20230103_20260707_v2` |
| 30m | 10072 | 2023-01-03 09:30 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_30m_20230103_20260707_v2` |
| 60m | 5883 | 2023-01-03 10:00 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_60m_20230103_20260707_v2` |
| 1d | 847 | 2023-01-03 00:00 | 2026-07-06 00:00 | 2026-07-06 | `rqdata_jm_standard_1d_20230103_20260707_v2` |

关键输出：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

DB 登记：

| timeframe | market_data_file_id | data_quality_report_id | provider | data_role | quality_status |
|---|---:|---:|---|---|---|
| 1m | 33205 | 34804 | rqdata | primary | passed |
| 5m | 33206 | 34805 | rqdata | primary | passed |
| 15m | 33207 | 34806 | rqdata | primary | passed |
| 30m | 33208 | 34807 | rqdata | primary | passed |
| 60m | 33209 | 34808 | rqdata | primary | passed |
| 1d | 33210 | 34809 | rqdata | primary | passed |

## 4. 已完成质量检查

- 六周期 DuckDB 可读。
- 六周期 `duplicate_count=0`。
- 异常 OHLC 为 0。
- 负 volume 为 0。
- 负 open_interest 为 0。
- 必填空值为 0。
- v2 未覆盖旧 v1 文件，旧 v1 保留为 rollback fallback。

## 5. 后续数据任务

1. 补强 active 数据过滤测试。
2. Web Data 页面 smoke 最新覆盖和质量状态。
3. 设计 RQData 实时 1m 入库。
4. 实现 1m 聚合多周期。
5. 继续追踪 `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因。

## 6. 安全要求

- 不把凭据写入仓库、日志、文档或任务文件。
- 不打印 webhook、token、密码、license。
- 未经明确授权，不运行新的 RQData 写入或覆盖任务。
- 没有质量报告的数据不能进入默认正式回测。
