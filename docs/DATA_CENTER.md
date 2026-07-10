# DATA_CENTER.md

更新时间：2026-07-10

## 1. 定位

数据中心把 RQData 变成本地可信、可追溯、可复算的数据资产：

```text
RQData -> raw parquet -> standard parquet -> quality
-> manifest/checksum -> PostgreSQL metadata -> DuckDB
-> Market / Backtest / Signal / Review
```

PostgreSQL 只保存元数据、任务、质量和业务事实，不保存全量历史分钟线。

## 2. active 入口

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据不得进入默认读取。

当前主周期规则：

```text
passed 1m standard parquet
-> local aggregation
-> 5m / 15m / 30m / 60m / 1d quality passed
-> active metadata registration
```

不允许从 RQData 直接拉取 5m/15m/30m/60m 作为新的正式主链路。

## 3. JM 最新主连资产

产品：`jm`
研究合约：`jm.MAIN`
窗口：`2023-01-03..2026-07-10`

| period | rows | min datetime | max datetime | derivation | quality |
|---|---:|---|---|---|---|
| 1m | 290490 | 2023-01-03 09:01 | 2026-07-09 23:00 | RQData direct | passed |
| 5m | 58098 | 2023-01-03 09:05 | 2026-07-09 23:00 | aggregated from 1m | passed |
| 15m | 19366 | 2023-01-03 09:15 | 2026-07-09 23:00 | aggregated from 1m | passed |
| 30m | 10108 | 2023-01-03 09:30 | 2026-07-09 23:00 | aggregated from 1m | passed |
| 60m | 5904 | 2023-01-03 10:00 | 2026-07-09 23:00 | aggregated from 1m | passed |
| 1d | 851 | 2023-01-03 00:00 | 2026-07-10 00:00 | grouped by trading_day from 1m | passed |

所有派生 parquet 都包含唯一 `source_interval=1m`，并通过 checksum、DuckDB、row_count 和 PostgreSQL quality report 核对。

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260710.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260710.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`

最新六个目标 data_version 在 `market_data_files` 中每周期只有一条登记，均为 `provider=rqdata / data_role=primary / quality_status=passed`。

## 4. Stage 8.6 分层

### 全品种 `stage8_6_1d_first`

- products：90
- product `active_passed=82`
- product `active_partial=8`
- asset `active_passed=176`
- asset `audit_pending=8`
- Stage 9：90 `stage9_blocked`

8 个 pending：

- `bb/rs/wh/wr/zc` 主连 1d：quality warning / abnormal price，不能升级为 passed。
- `L2609F/PP2609F/V2609F` actual-contract 1d：manifest 存在但缺 `market_data_files` 登记。

### JM 最新主连 `jm_main_six_period_latest`

- products：1 `active_passed`
- main assets：6/6 `active_passed`
- 该 profile 只审计最新 `jm.MAIN` 六周期，不把历史 actual-contract 片段混入六周期计数。
- Stage 9 仍 blocked；数据 Gate 不授权企业微信发送。

## 5. 真实合约与 live 边界

- `continuous_contract` 用于研究、方向和连续图。
- `actual_contract` 来自 `MainContractMap.rank=1`，用于真实成本、trigger price、提醒和复盘。
- `JM2609` 是特定映射日期的真实合约证据，不得硬编码为长期主力。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 historical active。
- 盘后归档必须重新经过 gap、duplicate、trading_day、OHLC、manifest、checksum 和 quality Gate。

## 6. 质量规则

每个正式资产至少检查：

- DuckDB 可读与 row_count。
- datetime/trading_day 边界。
- duplicate、必填空值、OHLC、volume、open_interest。
- manifest/checksum 与文件一致。
- DB data_role/quality 与质量报告一致。
- 派生周期 `source_interval=1m`。

自然午休、夜盘、周末和节假日 gap 仅作为样本记录；交易时段内缺口需要交易日历增强后才能精确分类。

## 7. 安全与后续

- RQData credential/license 只从环境变量读取，不写仓库或日志。
- 数据脚本失败时保留失败状态，不登记为 primary passed。
- 下一步只处理 8 个全品种 pending；不得为提高通过率覆盖 warning 或伪造登记。
- live ingest / scheduler、全品种多周期扩展和 actual-contract 批量修复必须另开 Plan。
