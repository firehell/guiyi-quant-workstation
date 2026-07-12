# DATA_CENTER.md

更新时间：2026-07-11

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
| 1m | 290715 | 2023-01-03 09:01 | 2026-07-10 15:00 | RQData direct | passed |
| 5m | 58143 | 2023-01-03 09:05 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 15m | 19381 | 2023-01-03 09:15 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 30m | 10116 | 2023-01-03 09:30 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 60m | 5909 | 2023-01-03 10:00 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 1d | 851 | 2023-01-03 00:00 | 2026-07-10 00:00 | grouped by trading_day from 1m | passed |

所有派生 parquet 都包含唯一 `source_interval=1m`，并通过 checksum、DuckDB、row_count 和 PostgreSQL quality report 核对。

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260711.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260711.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`

最新六个目标 data_version 在 `market_data_files` 中每周期只有一条登记，均为 `provider=rqdata / data_role=primary / quality_status=passed`。

## 4. Stage 8.6 分层

### 全品种 `stage8_6_1d_first`

- products：90
- product `active_passed=82`
- product `active_partial=8`
- current snapshot manifest-level discovered active records `active_passed=1326`
- asset `audit_pending=8`
- Stage 9：90 `stage9_blocked`

旧任务表中的 `176 active_passed / 8 audit_pending` 是较早的 Stage 8.6 asset baseline。2026-07-11 `data-audit` 快照纳入了更多 actual-contract manifest-level records，因此当前 asset passed count 为 1326。该数字不代表完整目标覆盖率。

当前 1326 口径：

- 唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `actual_contract` 1244 行，其中 1241 passed / 3 pending。
- `dominant_main` 90 行，其中 85 passed / 5 pending。
- 当前 snapshot 全部为 `1d`，不是多周期全量覆盖。
- provider 从路径推断均为 `rqdata`。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在该报告中逐文件独立证明。
- 1326 passed 记录均有 DB 登记；3 个 pending 缺 `market_data_files`；5 个 pending 是 quality warning。

8 个 pending：

- `bb/rs/wh/wr/zc` 主连 1d：quality warning / abnormal price，不能升级为 passed。
- `L2609F/PP2609F/V2609F` actual-contract 1d：manifest 存在但缺 `market_data_files` 登记。

### JM 最新主连 `jm_main_six_period_latest`

- products：1 `active_passed`
- main assets：6/6 `active_passed`
- 该 profile 只审计最新 `jm.MAIN` 六周期，不把历史 actual-contract 片段混入六周期计数。
- Stage 9 仍 blocked；数据 Gate 不授权企业微信发送。

## 4.1 目标覆盖矩阵审计

2026-07-11 新增 `TASK-2026-07-11-002-data-target-coverage-audit`，用于区分“已经发现到的 active 资产快照”和“目标资产应覆盖矩阵”。

输出目录：

```text
data/reports/target_coverage_audit_20260711/
```

矩阵粒度：

```text
product x contract_role x symbol/contract x period x year x status
```

2026-07-11 修复前运行结果：

- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：2091 rows。
- 主工程复跑已使用 `db_snapshot_source=database`；未写 DB、未写 Parquet、未调用 RQData。

覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 16156 |
| covered_warning | 1039 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |
| row_count_mismatch | 8 |

元数据矩阵状态：

| status | count |
|---|---:|
| covered_passed | 2445 |
| metadata_gap | 831 |
| not_applicable | 504 |

Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| source_interval_unverified | 1039 |
| missing_db_registration | 108 |
| quality_failed | 105 |
| row_count_mismatch | 8 |

2026-07-12 `TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair` 仅对 `ad/ec/op` 三条旧版本周线 `market_data_files.row_count` 做受控 PostgreSQL metadata 修复：

- `ad` / `db_file_id=44115`：47 -> 55。
- `ec` / `db_file_id=44133`：134 -> 148。
- `op` / `db_file_id=44159`：36 -> 42。
- 未写 Parquet、manifest、checksum、data_version、data_role、quality_status；未调用 RQData。

修复后目标覆盖矩阵：

- 输出目录：`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`。
- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：2083 rows。
- `db_snapshot_source=database`。

修复后覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 16164 |
| covered_warning | 1039 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |

修复后 Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| source_interval_unverified | 1039 |
| missing_db_registration | 108 |
| quality_failed | 105 |

`row_count_mismatch` 已清零；该结论只覆盖这 3 条旧版本周线 DB metadata stale，不代表 provenance、missing registration、quality failed/warning 已处理。

解释边界：

- 目标覆盖矩阵不是 Stage 8.6 active snapshot 的替代结论。
- 本次主工程复跑已取得 DB 只读元数据快照，元数据缺口可进入后续只读根因分类。
- `source_interval_unverified` 需要另开只读根因分类，不能直接当作数据损坏。
- 2026-07-12 metadata repair 只修复 `ad/ec/op` 三条 row_count stale，不处理 `source_interval_unverified`、`missing_db_registration`、`quality_failed` 或参考元数据缺口，不授权 Stage 9。

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
- 当前 Stage 8.6 快照只是全量历史数据资产盘点的第一阶段基线，不能验收为完整目标资产目录。
- 下一步先另开只读 Plan-mode 任务 `codex/data-target-coverage-audit`，定义目标资产目录和完整覆盖矩阵；不得把修复 8 个 pending 当作唯一缺口。
- 后续修复 8 个 pending 时，不得为提高通过率覆盖 warning 或伪造登记。
- live ingest / scheduler、全品种多周期扩展和 actual-contract 批量修复必须另开 Plan。
