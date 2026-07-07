# JM History Update Plan

生成时间：2026-07-07
状态：Stage 2C / 2D / 2E 已完成

## 1. 当前结论

JM v2 历史数据闭环已完成。

- Stage 2B：只读 plan verification 已完成。
- Stage 2C：JM v2 六周期 raw / standard parquet 已写入。
- Stage 2D：manifest、checksum、quality report、DB 登记已完成。
- Stage 2E：coverage audit 已生成，结论 `can_enter_stage3=true`。

本文件现在作为 JM v2 数据更新结果摘要和 Stage 3 入口说明，不再作为待执行写入计划。

## 2. 输出文件

| artifact | path |
|---|---|
| 2C summary | `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json` |
| 2D manifest | `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv` |
| 2E coverage audit | `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json` |

## 3. JM v2 覆盖

| timeframe | rows | min datetime | max datetime | max trading_day | data_version |
|---|---:|---|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_1m_20230103_20260707_v2` |
| 5m | 57891 | 2023-01-03 09:05 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_5m_20230103_20260707_v2` |
| 15m | 19297 | 2023-01-03 09:15 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_15m_20230103_20260707_v2` |
| 30m | 10072 | 2023-01-03 09:30 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_30m_20230103_20260707_v2` |
| 60m | 5883 | 2023-01-03 10:00 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_60m_20230103_20260707_v2` |
| 1d | 847 | 2023-01-03 00:00 | 2026-07-06 00:00 | 2026-07-06 | `rqdata_jm_standard_1d_20230103_20260707_v2` |

## 4. DB 登记

| timeframe | market_data_file_id | data_quality_report_id | provider | data_role | quality_status |
|---|---:|---:|---|---|---|
| 1m | 33205 | 34804 | rqdata | primary | passed |
| 5m | 33206 | 34805 | rqdata | primary | passed |
| 15m | 33207 | 34806 | rqdata | primary | passed |
| 30m | 33208 | 34807 | rqdata | primary | passed |
| 60m | 33209 | 34808 | rqdata | primary | passed |
| 1d | 33210 | 34809 | rqdata | primary | passed |

## 5. 质量审计

- 六周期 DuckDB 可读。
- 六周期 `duplicate_count=0`。
- 异常 OHLC 为 0。
- 负 volume 为 0。
- 负 open_interest 为 0。
- 必填空值为 0。
- v2 未覆盖旧 v1 文件；v1 保留为 rollback fallback。
- gap samples 仅作为 session / lunch / night / holiday gap 信息记录，不等同于 failed。

## 6. active 数据 Gate

Stage 3A 必须验证默认读取满足：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先：

```text
quality_status = "passed"
```

## 7. 下一步

1. `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`
2. `WEB-DATA-3B-DATA-PAGE-SMOKE`

禁止在未授权任务中重跑写入或覆盖 JM v2 文件。
