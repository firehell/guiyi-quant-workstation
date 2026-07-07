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

## 5. 当前真实主力合约试点资产

Stage 8.5-6B 已完成 JM-only 当前真实主力合约 historical bars 真实最小写入试点。

试点口径：

- `product=jm`
- `continuous_contract=jm.MAIN`
- `actual_contract=JM2609`
- `dominant_mapping_date=2026-07-07`
- window：`2026-07-06..2026-07-07`
- raw path：`data/raw/rqdata/actual_contract_bars/product=jm/contract=JM2609/frequency=1m/JM2609_1m_raw_20260706_20260707.parquet`
- manifest：`data/manifests/rqdata_actual_contract_bars_jm_JM2609_20260706_20260707.csv`

DB 登记：

| timeframe | rows | market_data_file_id | data_quality_report_id | provider | data_role | quality_status |
|---|---:|---:|---:|---|---|---|
| 1m | 690 | 33214 | 34812 | rqdata | primary | passed |
| 5m | 138 | 33215 | 34813 | rqdata | primary | passed |
| 15m | 46 | 33216 | 34814 | rqdata | primary | passed |
| 30m | 24 | 33217 | 34815 | rqdata | primary | passed |
| 60m | 14 | 33218 | 34816 | rqdata | primary | passed |
| 1d | 3 | 33219 | 34817 | rqdata | primary | passed |

质量口径：

- 自然午休、夜盘、节假日和周末间隔记录为 `gap_samples`，不计入 `missing_bars`。
- 重复 bar、OHLC 异常、负 volume、负 open_interest 仍阻断 primary 登记。
- 后续如果要区分真实交易时段缺口和自然非交易间隔，需要单独补交易时段日历质量 Gate。

## 6. 后续数据任务

Stage 3A / 3B、Stage 4A / 4B、Stage 5、Stage 6A / 6B、Stage 8 已完成代码或文档闭环。Stage 8.5 已完成 8.5-0 / 8.5-1 / 8.5-2 文档闭环、8.5-3 schema 最小代码闭环、8.5-4 RQData 元数据只读方案冻结、8.5-5 historical bars 设计冻结、8.5-6 dry-run / fixture Gate 和 8.5-6B JM2609 真实写入试点，详见：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

Stage 8.5 冻结的新口径：

1. `continuous_contract` 用于研究、回测背景、连续图和日线方向。
2. `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
3. live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
4. 盘后归档必须单独经过 gap / duplicate / trading_day / OHLC / manifest / checksum / quality Gate 后，才能登记为 historical active。
5. Stage 9 企业微信前，`signal_events` 已具备显式字段，但仍必须补齐真实主力映射、真实合约 trigger price 和质量 Gate。
6. V1-B 默认目标品种池先锁定为 `jm`；`actual_contract` 只能来自 `MainContractMap.rank=1`，`dominant_mapping_date` 对应 `MainContractMap.trade_date`。
7. trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。
8. `jm.MAIN` historical bars 只作为研究主连资产；当前真实主力合约 historical bars 必须作为独立 canonical bars 资产，不得混入 `jm.MAIN` 文件。
9. `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 不能宣称为真实合约提醒价。

当前后续任务：

1. `Stage 8.5-7`：Web Data / Web Market actual-contract 数据消费扩展。
2. `Stage 8.5-9`：盘后归档设计和 Stage 9 前数据 Gate。

## 7. 合约角色口径

| 字段 | 用途 | 是否可作为交易合约 |
|---|---|---|
| `continuous_contract` | 研究背景、连续图、日线方向、回测上下文 | 否 |
| `actual_contract` | live 触发、trigger price、提醒 payload、复盘入口 | 是，仍只用于提醒和人工观察 |
| `previous_actual_contract` | 换月安全窗口、覆盖审计、回放 | 仅审计 / 观察 |
| `next_actual_contract` | 换月前预检、数据补齐 | 仅审计 / 观察 |

`jm.MAIN` 等主连代码不得被企业微信描述为真实交易合约。

## 8. Historical bars 扩展边界

8.5-5 冻结方案，8.5-6 完成代码 + dry-run + fixture 测试闭环，8.5-6B 已完成 `JM2609` 真实最小写入试点。后续新增日期、合约或品种的真实写入仍应遵守：

- 目标品种先限于 `jm`。
- 真实合约来自 `MainContractMap.rank=1`，缺映射时阻断。
- periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 文件路径和 `MarketDataFile.contract_code` 使用真实 `actual_contract`，不使用 `jm.MAIN`。
- 每个资产必须有 manifest、checksum、quality report 和 DuckDB 可读性验证。
- Stage 9 前严格优先要求 `quality_status=passed`。

8.5-6 / 8.5-6B 入口：

- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`

未经单独授权，不运行新的真实 RQData historical write，不登记新的真实 `market_data_files`，不把任何新真实 bars 标记为 active。

## 9. 盘后归档边界

目标归档流程：

```text
RQData after-market direct data / live DB verification
-> gap check
-> duplicate check
-> trading_day check
-> OHLC check
-> standard parquet
-> manifest
-> checksum
-> quality report
-> market_data_files
-> historical active
```

该流程尚未实现。未经单独授权，不运行真实归档写入。

## 10. 安全要求

- 不把凭据写入仓库、日志、文档或任务文件。
- 不打印 webhook、token、密码、license。
- 未经明确授权，不运行新的 RQData 写入或覆盖任务。
- 没有质量报告的数据不能进入默认正式回测。
- 不把 live DB 或 live 聚合 DB 直接登记为 trusted historical active。
