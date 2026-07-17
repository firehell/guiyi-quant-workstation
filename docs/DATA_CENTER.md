# DATA_CENTER.md

更新时间：2026-07-17

## 0. 当前 canonical 结论

当前数据层最终状态已进入全历史重审口径：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_INVENTORY_READY
FULL_HISTORY_AUDIT_V2_READY
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

`FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只说明仓库 manifest 强烈支持全历史物理数据已经大规模下载；不代表本地全部 Parquet、direct PostgreSQL、quality、Profile binding 或 formal consumer 已验收。当前 Profile 配置仍需按 target-aware 规则重算和受控 binding rollout。

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不能覆盖当前数据层最终验收。以下 Phase 3 DB 口径仅作为旧审计模型历史快照保留：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |

本文件后续章节保留数据链路、历史处理链和阶段证据。凡历史章节出现 `metadata_gap=0`、`covered_passed=17203`、`metadata_gap=1853`、`pre_2020_weekly_missing=34`、actual contract 旧固定 gap 或 `DATA-PART-TARGET-CLOSURE`，均只表示对应审计模型下的历史快照，不代表当前确定下载缺口、当前批量修复清单或数据层最终 ready。

当前暂停基于旧 `1853 / 34 / 45` 数字的批量修复。B2-01 physical inventory 与 B2-02 Audit V2 已完成；下一步以 V2 gap register 做只读 residual triage，不直接进入下载、DB 修复或 Profile binding。

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

## 2.1 quality_warning 消费边界

OHLC envelope 校验对二进制浮点舍入使用确定性容差：`max(1e-12, 1e-12 * max(abs(O/H/L/C), 1))`。该规则只消除远小于最小变动价位的机器精度噪声；超过容差的 `high/low` 越界仍为 hard failure。历史 quality 证据不因规则修正被原地升级，需通过新 data version 重新验证。

Stage 5-B reference metadata gap 已收口；target coverage 剩余 **105 条 `quality_warning`**（15 个唯一文件，abnormal price warning）。这些资产**不得为覆盖率升级为 `passed`**。

| 模块 | 默认行为 | warning 允许条件 |
|---|---|---|
| Market | 允许展示（active 入口 `!= failed`） | 始终允许，但必须返回质量字段并在 UI 提示 |
| Backtest | 严格 `passed-only` | 显式 `allow_warning_quality=true` 或 config 标记 |
| Signal | 默认阻断 | Stage 9 前 `allow_warning_quality=false` |
| Review | 可展示历史 note | extra 记录 `data_quality_status`；warning 不可作信号证据 |

读取分层：

```text
active 入口（Market 默认）
  provider in (rqdata, local_parquet)
  data_role = primary
  quality_status != failed

strict 入口（Backtest / Signal / 严格研究）
  上述条件 + quality_status = passed
  或显式 allow_warning_quality opt-in
```

任务单：`docs/tasks/TASK-2026-07-12-010-quality-warning-consumption-boundary.md`

## 2.2 V1 全历史数据契约

状态：

```text
V1_DATA_CONTRACT_FROZEN
```

机器契约位于 `services/quant-api/app/services/rqdata_ingest/full_history_contract.py`。本节是长期语义事实源；纯模块提供 Audit V2 可复用的字段与算法。冻结契约不表示各品种 provider earliest evidence 已盘点完成，也不表示 Profile binding 或 formal consumer 已验收。

### 2.2.1 时间与 expected window

```text
audit_end = 2026-07-10
timezone = Asia/Shanghai
```

- `trading_day` 优先使用 provider 字段；夜盘 bar 归属下一交易日，周分组使用 trading day 的 ISO week。
- continuous 1m `expected_start = max(listed semantic start, authoritative provider first valid 1m bar)`。
- continuous direct 1d `expected_start = max(listed semantic start, provider first valid completed daily bar)`；可以早于 2010。
- continuous direct 1w 从 provider 第一条完成交易周 bar 开始，不要求等于上市日。
- 1m/1d `expected_end` 为不晚于 audit end 的最后完成交易日；1w 为不晚于 audit end 的最后完成交易周 bar。
- 缺少权威 provider earliest evidence 时，V2 将 canonical physical minimum 记录为 `start_boundary_supported`；缺少物理支持时为 `start_boundary_unverified`。两者均不等于 provider authoritative exact，并保持严格 data Gate fail-closed；不使用统一 2020/2023 起点。

provider earliest evidence 优先级：

1. 带查询参数、provider/version、时区和 checksum 的 provider earliest 快照。
2. 可证明完整的既有 provider raw response。
3. checksum 可验证的 canonical Parquet + manifest，只证明 observed physical coverage。
4. PostgreSQL metadata，只证明 registration/quality 状态。
5. listing metadata，只提供上市语义下界。

物理文件最早时间、manifest 文件名、DB start_time 或 listing date 均不得单独解释为 provider 理论最早时间。

### 2.2.2 first listed week

- 使用交易日历确定 provider weekly bar 所属周的最后实际交易日，不硬编码星期五。
- 上市当周存在 provider completed weekly bar 时，以该 bar 日期作为 expected start。
- 上市当周未形成完成周 bar 时，顺延到 provider 下一条 completed weekly bar。
- 节假日短周以该周最后实际交易日作为完成日。
- calendar 不完整、最后交易日未收盘、bar 不是周末实际交易日或 provider evidence 不权威时保持 unresolved/partial。

### 2.2.3 数据角色

| 角色 | V1 契约 |
|---|---|
| direct 1m | continuous 和 rank=1 actual 的基础分钟资产 |
| derived 5m/15m/30m/60m | 只允许从 passed 1m 本地聚合 |
| direct 1d | 长周期研究和 provider reference；通过 Profile/quality Gate 后可消费 |
| derived 1d | 日内研究的日线方向上下文，只允许从 passed 1m 聚合 |
| direct 1w | 长周期研究、Market 展示和 provider reference；不作为 actual 或分钟 Signal 默认要求 |
| actual dominant | 只覆盖 `MainContractMap.rank=1` 有效日期段的 1m/1d，不要求所有挂牌合约全量分钟数据 |
| live | 只存在 live DB 观察层；盘后重新获取 provider 最终历史数据并通过完整 Gate 后才能进入 historical canonical |

### 2.2.4 partial / confirmed

historical `confirmed` 同时要求：目标 bucket 已完成、数据来自盘后 provider 最终历史获取、quality 通过、registration 与 lineage 完整。`partial` 只能用于 live preview 或审计说明，不得进入 historical formal consumer。

周线完成需满足：交易日历完整、该周最后实际交易日已收盘、provider completed bar 存在。live 聚合的 confirmed bar 仍不自动成为 historical canonical。

### 2.2.5 五层状态与 Profile eligibility

以下状态必须独立记录，禁止用一层成功替代另一层：

```text
physical_coverage: covered / partial / missing / unverified
registration: registered / missing / not_required / unavailable
quality: passed / warning / failed / unchecked
reference_metadata: passed / warning / missing / not_applicable / unavailable
profile_eligibility: eligible / blocked / unresolved / not_applicable
```

Profile eligibility 至少要求 physical covered、registration registered、reference metadata passed/not-applicable、identity 在 Profile target 内、bar confirmed，并满足 Profile quality policy。当前 Profile JSON 不在本任务修改；target-aware 选优属于 B2-07。

### 2.2.6 formal consumer 准入

| Consumer | 默认准入 | warning 边界 |
|---|---|---|
| Market | 五层完整、confirmed、quality passed/warning | 允许展示，必须返回并显示 warning |
| Backtest | confirmed、passed、Profile eligible | 显式 opt-in 仅为 research warning run，不计入最终 Ready Gate |
| Signal | confirmed、passed、reference/Profile 完整 | warning、partial、failed、unchecked 全部阻断 |
| Review | passed 可作正式证据 | warning 只可带标签展示，不可作信号证据 |

所有 formal consumers 均阻断 registration missing、reference metadata gap、Profile ineligible 和 historical partial。`report_id=14` 是冻结历史基线，只能读取和引用，禁止更新、回填、重算覆盖或替换 lineage。

## 2.2.7 Audit V2（2026-07-17）

状态：

```text
FULL_HISTORY_AUDIT_V2_READY
DATA_LAYER_REAUDIT_REQUIRED
```

V2 读取 B2-01 的全部物理 inventory 和 direct PostgreSQL reference metadata，按 `product + period + source_role` 动态生成 expected window/year。旧 final audit 的统一 `DEFAULT_MINUTE_START=2023-01-03`、固定 `2020..2026` 年目录和旧 `1853 / 34 / 45` 数字均不参与新 Gate。

输出位于 `data/reports/full_history_audit_v2_20260710/`。正式结果为 90 个产品、720 个 expected window、7964 条动态年度区间、12726 条 rank=1 actual 1m/1d 目标。当前 reference gap 为 90 个 `trading_calendar_gap` 和 90 个 `trading_session_gap`；physical coverage 为 468 covered / 252 partial；quality 保持 693 passed / 6 warning / 21 failed。

代表品种 direct support：

| product | 1m | 1d | 1w completed | status |
|---|---|---|---|---|
| a | 2010-01-04 | 2002-03-15 | 2002-03-15 | start_boundary_supported |
| al | 2010-01-04 | 2000-01-05 | 2000-01-07 | start_boundary_supported |
| ag | 2012-05-10 | 2012-05-10 | 2012-05-11 | start_boundary_supported |
| jm | 2013-03-22 | 2013-03-22 | 2013-03-22 | start_boundary_supported |

这些日期来自可读 canonical physical evidence，不是 authoritative provider earliest snapshot。`FULL_HISTORY_AUDIT_V2_READY` 只表示引擎和报告可复查；calendar/session、partial/failed quality 和 Profile eligibility 未严格通过前，仍不得宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。

## 2.3 数据阶段收口审计（2026-07-13）

当前数据层封板状态：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

本轮只做只读审计与文档事实源整理，不写 DB、Parquet、manifest、checksum 或 quality status，不调用 RQData。收口包：

```text
data/reports/data_stage_closure/
```

Phase 3 DB 口径事实源为 `data/reports/data_layer_final_audit_phase3_20260712/`。A2-01 后，该口径改为历史审计模型快照，不再作为当前确定下载缺口：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

本轮复跑 `scripts/rqdata_data_layer_final_audit.py` 时，PostgreSQL 因 `fe_sendauth: no password supplied` 不可用，API snapshot 返回 502，审计降级为 `db_snapshot_source=manifest_only`。该复跑结果保存在 `data/reports/data_stage_closure/final_audit/`，用于记录环境 Gate，不作为数据完成度唯一口径。

边界说明：

- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论。
- 更新后的数据层最终验收为 `DATA_LAYER_REAUDIT_REQUIRED`；旧 `1853 / 34 / 45` 不再直接驱动批量修复。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 不等于 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 通过。
- 105 条 `quality_warning` 保持 warning，不升级为 passed。
- 当前不能宣称“全品种周线从上市以来完整”。
- 本结论不授权 Stage 9、企业微信、live runtime、自动交易或实盘。

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

8 个 pending（TASK-012 已分流，不再作为模糊尾巴）：

- `bb/rs/wh/wr/zc` 主连 1d：`accepted_warning`（abnormal price，不升级 passed）。
- `L2609F/PP2609F/V2609F` actual-contract 1d：`registration_not_needed`（snapshot product=l/pp/v 误报；`l_f/pp_f/v_f` 已 active_passed）。

证据：`data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`

### JM 最新主连 `jm_main_six_period_latest`

- products：1 `active_passed`
- main assets：6/6 `active_passed`
- 该 profile 只审计最新 `jm.MAIN` 六周期，不把历史 actual-contract 片段混入六周期计数。
- Stage 9 仍 blocked；数据 Gate 不授权企业微信发送。

## 4.1 目标覆盖矩阵审计

说明：本节以下保留目标覆盖矩阵从 2026-07-11 到 2026-07-12 的处理链。中间状态用于追溯，不覆盖 §0 和 §2.2 的当前最终口径。

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

2026-07-12 `TASK-2026-07-12-005-source-interval-provenance-repair-apply` 对 `source_interval_unverified` 做受控 Parquet/metadata 修复：

- 输入：`data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv`。
- Pilot：5 files applied，`source_interval_unverified` 1039 -> 1019。
- Full：276 selected / 271 applied / 5 skipped / 0 blocked。
- 写入范围：canonical Parquet 新增 `source_interval=1m`，同步 manifest checksum、DB `market_data_files.checksum/file_size_bytes`，并同步 61 个已有 processed summary checksum。
- 未调用 RQData；未改 `row_count`、`data_version`、`data_role`、`quality_status`；未处理 `missing_db_registration`、`quality_failed` 或 reference metadata gaps。

source interval 修复后目标覆盖矩阵：

- 输出目录：`data/reports/target_coverage_audit_20260712_after_source_interval_full/`。
- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `issue_register.csv`：1044 rows。
- `db_snapshot_source=database`。

source interval 修复后覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 17203 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |

source interval 修复后 Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| missing_db_registration | 108 |
| quality_failed | 105 |

`source_interval_unverified` 已清零；该结论只覆盖 provenance metadata 和 checksum/file_size 同步。

2026-07-12 `TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run` 对 108 条 `missing_db_registration` 做只读 reconcile：

- 108 target rows 按 `standard_path` 去重为 93 个物理文件。
- 93 个文件均存在，DuckDB / manifest metadata 校验通过。
- `already_registered=87`。
- `duplicate_path_versions=6`，均为 `L2609F` 六周期的两个历史 `data_version` 指向同一路径。
- `eligible_for_registration=0`，`blocked_metadata_mismatch=0`。
- `market_data_files: 71098 -> 71098`，`data_quality_reports: 65466 -> 65466`。
- 根因是 actual-contract manifest 文件名解析将 `l_f/pp_f/v_f` 错分为 `l/pp/v`，导致 manifest 与 DB evidence 无法合并。
- 本任务未写 DB、Parquet 或 manifest，未调用 RQData，未提供 apply 入口。
- 人工 Gate 结论：不需要且不授权受控 DB 登记；六条同路径多版本只报告，不删除、合并、归档或修改。

LPV reconcile 后权威 target coverage 复跑（分支修复代码 + 主工程完整数据目录）：

- 输出：`data/reports/target_coverage_audit_20260712_after_lpv_reconcile/`。
- `target_asset_catalog_rows: 17689 -> 17581`；删除的 108 行是 `l_f/pp_f/v_f` 被错分到 `l/pp/v` 后产生的 phantom targets，不是新增 covered assets。
- `physical_inventory_rows=15056`。
- `covered_passed=17203`，`metadata_gap=105`，`not_applicable=273`。
- `issue_register_rows: 1044 -> 936`。
- 剩余 issue：546 `missing_continuous_contract_map`、285 `missing_contract_universe`、105 `quality_failed`。
- `missing_db_registration=0`，且未改变既有 105 条 `quality_failed` 语义。

解释边界：

- 目标覆盖矩阵不是 Stage 8.6 active snapshot 的替代结论。
- 本次主工程复跑已取得 DB 只读元数据快照，元数据缺口可进入后续只读根因分类。
- `missing_db_registration` dry-run 已证实为审计匹配误报，不授权新增 DB 登记；`quality_failed` 已由 TASK-007 证实为 stale processed summary 误报并转为 `quality_warning`，reference metadata gaps 仍需独立 metadata-only Gate。
- 2026-07-12 metadata repair 只修复 `ad/ec/op` 三条 row_count stale；source interval apply 只修复 provenance metadata，不授权 Stage 9。

2026-07-12 `TASK-2026-07-12-007-residual-data-risk-closeout-dry-run` 对剩余风险做只读 closeout：

- `quality_failed_root_cause_audit` 输入 105 target rows，去重为 15 个唯一文件。
- 15 个文件全部分类为 `stale_processed_summary_failed`。
- 当前 DB、manifest、quality report 均为 `warning`；误报根因是 `processed/v1b/*_v2_parquet_*.json` 仍保留旧 `quality_status=failed`。
- 本任务修正 target coverage audit 质量状态合并口径：DB/manifest 当前 active evidence 优先，processed summary 只在没有 active evidence 时兜底。
- `duplicate_path_version_reconcile` 输入 6 条 `L2609F` 同路径多版本，全部分类为 `duplicate_path_versions`，仅输出 current/superseded 对照，不删除、不归档、不合并、不改 DB。
- `reference_metadata_gap_reconcile` 历史输入 831 rows：`needs_contract_universe_sync: 285`，`needs_continuous_contract_sync: 546`，`partial_year_rows: 0`。
- 输出目录：
  - `data/reports/quality_failed_root_cause_audit_20260712/`
  - `data/reports/duplicate_path_version_reconcile_20260712/`
  - `data/reports/reference_metadata_gap_reconcile_20260712/`
  - `data/reports/target_coverage_audit_20260712_after_residual_closeout/`
- 本任务未写 DB、Parquet 或 manifest，未调用 RQData，未修改 `data_version/data_role/quality_status/checksum`。

Residual closeout 后权威 target coverage 复跑：

- `target_catalog_rows=17581`。
- `physical_inventory_rows=15056`。
- `covered_passed=17203`。
- `covered_warning=105`。
- `not_applicable=273`。
- `metadata_gap=831`。
- `issue_register_rows=936`。
- Issue 类型：546 `missing_continuous_contract_map`、285 `missing_contract_universe`、105 `quality_warning`。
- `quality_failed=0`，`missing_db_registration=0`。
- 105 条 warning asset 不升级为 `passed`，仍需人工理解其异常价 warning；reference metadata gaps 只能进入后续 metadata-only sync/apply Gate。

2026-07-12 `TASK-2026-07-12-008-reference-metadata-gap-apply-plan` 已将 reference metadata gaps 转成 no-write apply plan：

- 输入：`data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`。
- 输出目录：`data/reports/reference_metadata_gap_apply_plan_20260712/`。
- `candidate_rows=831`：
  - `needs_contract_universe_sync=285`。
  - `needs_continuous_contract_sync: 546`。
- `batch_count=11`：
  - `contract_universe`：2020、2021、2022、2023。
  - `continuous_contract_map`：2020、2021、2022、2023、2024、2025、2026。
- 本任务仅生成 `apply_candidate_rows.csv`、`apply_batches.csv` 和 Markdown plan，不执行生成命令。
- 安全边界：`writes_database=False`、`writes_parquet=False`、`writes_manifest=False`、`calls_rqdata=False`。
- 后续若进入真实 apply，必须另开人工 Gate；只允许 metadata-only 写 `futures_contract_universe`、`futures_continuous_contract_map` 和相关 task/raw manifest metadata。
- 后续 apply 仍不得写 K 线 Parquet、`market_data_files`、`data_quality_reports`、质量状态、策略、回测、信号、live runtime 或交易执行。

2026-07-12 `TASK-2026-07-12-009-reference-metadata-gap-apply` 已执行 metadata-only apply，并完成 Stage 5-B reference metadata gap 收口：

- 新增受控 apply runner：`scripts/rqdata_reference_metadata_gap_apply.py`。
- 真实写入必须显式使用 `--apply --confirm-metadata-only`。
- `contract_universe` 4 个批次全部成功：
  - candidates：285。
  - status：285 `success`。
  - 写入/更新：`futures_contract_universe`。
  - `rows_fetched_sum=652928`。
- `continuous_contract_map` 7 个 RQData SDK 直接批次已尝试但无数据：
  - candidates：546。
  - status：546 `no_data`。
  - 当前 `rqdatac 3.2.5` runtime 不暴露文档要求的 `futures.get_continuous_contracts`。
  - 不允许用 `get_dominant` 或主力映射替代 `front_month` / `next_month` 连续合约。
- derived `continuous_contract_map` apply 已完成：
  - candidates：546。
  - status：546 `success`。
  - `rows_fetched_sum=234812`。
  - `calls_rqdata=False`，该证据不是 RQData SDK `get_continuous_contracts` 直接接口验收。
- apply ledger 安全列均为：
  - `writes_parquet=False`。
  - `writes_market_data_files=False`。
  - `writes_quality_status=False`。
- Reference reconcile after full reference metadata apply：
  - `needs_contract_universe_sync=0`。
  - `needs_continuous_contract_sync=0`。
  - `partial_year_rows=831`。
- Target coverage after full reference metadata apply：
  - `covered_passed=17203`。
  - `covered_warning=105`。
  - `not_applicable=273`。
  - `issue_register_rows=105`。
  - Issue 类型：105 `quality_warning`。
- Stage 5-B reference metadata gap 已收口；105 条 `quality_warning` 是独立后续 Gate，不属于 reference metadata gap 失败项。
- 输出目录：
  - `data/reports/reference_metadata_gap_apply_batch_01_contract_universe_2020_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_02_contract_universe_2021_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_03_contract_universe_2022_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_04_contract_universe_2023_20260712/`
  - `data/reports/reference_metadata_gap_apply_derived_continuous_contract_map_20260712/`
  - `data/reports/reference_metadata_gap_reconcile_after_continuous_contract_map_derived_20260712/`
  - `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/`

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
- Stage 5-B reference metadata gap 已清零；不得把 derived continuous map 结果改写为 RQData SDK `get_continuous_contracts` 直接接口验收。
- 后续不得为了消除或重建 metadata gap 将 `get_dominant` 写入 `front_month` / `next_month` continuous map。
- 105 条 `quality_warning` 消费边界已定义（§2.1）；TASK-011 负责代码统一执行。
- live ingest / scheduler、全品种多周期扩展和 actual-contract 批量修复必须另开 Plan。

## 8. Full History Audit V2 物理事实 inventory（2026-07-17）

`FULL-HISTORY-PHYSICAL-INVENTORY-001` 新增独立 inventory 工具，不复用旧 target matrix，只聚合当前 canonical Parquet、全部字段匹配 manifest、全部 processed summary、direct PostgreSQL `market_data_files` 与按 `file_id` 关联的 `data_quality_reports`。

### 8.1 B2-04B 受控 residual 修复边界（2026-07-17）

Audit V2 的 actual rank=1 目标必须裁剪到每个 `product + period` 的 direct supported start，并在裁剪后去重。静态 `trading_sessions` 是运行时配置，不是可按年份机械要求的全历史 reference metadata，因此 Audit V2 将其标为 `not_applicable`，不生成 `trading_session_gap`。

quality evidence 保持分层：physical inventory 分别输出 `quality_statuses_db`、`quality_statuses_manifest`、`quality_statuses_processed`，同时保留兼容聚合列。Audit V2 当前 Gate 优先 direct PostgreSQL evidence；processed summary 的原始 evaluator 状态继续作为 provenance 保留，warning 不升级为 passed。

B2-04A 四个 repair queue 以文件 SHA-256、action type allowlist、显式 action IDs 和 deterministic ledger 冻结。任何 metadata、DB、Parquet 或 RQData 操作必须使用独立 batch approval；通用实施指令不授权生产写入。当前 CLI 只支持 dry-run plan 和 approval verification，不提供生产 apply。

正式 quick 输出位于：

```text
data/reports/full_history_audit_v2_20260710/
```

当前事实：

```text
status=FULL_HISTORY_PHYSICAL_INVENTORY_READY
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
audit_end=2026-07-10
physical_file_count=24763
physical_inventory_rows=27234
manifest_rows_seen=38092
manifest_asset_rows=16298
processed_period_records=1437
market_data_file_rows=25134
quality_report_rows=25134
db_snapshot_source=direct_postgresql
```

异常事实：

- 4 条 DB rows 指向已不存在的 `experiments/rqdata_sample_acceptance/output/...` jm 样本文件。
- 4934 行存在同路径多 version identity；inventory 保留每条 path identity，不选择 active 版本。
- 未发现空文件、Parquet 读取失败、schema mismatch、schema inconsistency 或 audit-end 之后的物理最大时间。

安全边界：

```text
writes_database=false
writes_parquet=false
calls_rqdata=false
expected_matrix_generated=false
```

该 `READY` 只代表当前事实 inventory 可复查，不代表 expected coverage、Profile binding 或 Market/Backtest/Signal 消费 Gate 已通过。旧 `1853/34/45` 数字继续作为历史快照，不得由本 inventory 重新推导。

### 8.2 B2-04B post-repair 事实（2026-07-17）

受控 residual repair 完成后，full-checksum inventory 与 direct PostgreSQL Audit V2 重新执行：

```text
physical_file_count=25495
physical_inventory_rows=27837
market_data_file_rows=25495
quality_report_rows=25495
checksum_matched_rows=27837
checksum_mismatch_rows=0
declared_conflict_rows=0
missing_physical_rows=0
path_drift_rows=0
audit_v2_products=90
audit_v2_expected_windows=720
audit_v2_gap_count=0
profile_binding_changed=false
```

RQData closure 只登记 71 个 `candidate + passed` actual-contract 日线资产；其中 32 个供应商 direct daily 存在 settlement-close/OHLC envelope 冲突，改用新 1m raw 本地聚合日线。异常旧 raw 不覆盖，warning 不升级为 passed，active Profile 不切换。`DATA_LAYER_REAUDIT_REQUIRED` 继续作为更高层 Gate 状态，本次 repair 完成不等同于自动宣布数据层 final ready。

### 8.3 B2-05 derived-period consumer Gate（2026-07-17）

`FULL-HISTORY-DERIVED-PERIODS-005` 将派生周期分成三层：JM V1-B actual consumer hard target、90 品种 Profile eligibility inventory，以及无当前 hard consumer 的 on-demand/deferred target。不得用 Profile 声明自动要求 90 品种重建全部 derived 1d，也不得用 long-horizon direct 1d 冒充 intraday Profile 的 derived 1d。

派生 lineage 只有在以下证据同时成立时才为 verified：

```text
processed summary exact source path
+ registered passed-primary 1m source
+ source version/checksum
+ source_interval=1m
+ source_bar_count
+ target-window coverage
+ physical checksum
+ session-aware bucket recomputation
```

direct PostgreSQL 全量核验覆盖 90 品种、548 consumer/Profile targets。受控修复将旧 `CNFE/jm/regular` 置为 inactive，并登记 DCE JM 夜盘、上午两段和下午时段；目标窗口 851 个交易日中 827 个允许夜盘，24 个节后首日不允许夜盘。修复后既有 5m/15m 与 passed-primary 1m 逐 bucket 完全匹配，无需重建。

Backtest derived 1d 另生成一份 `candidate + passed` 新版本，窗口 `2023-06-28..2026-06-26`，精确记录 source file id/path/version/checksum/profile、`source_interval=1m` 和 `source_bar_count`。最终 8 条 JM hard target residual 为 0，状态为 `DERIVED_PERIOD_TARGETS_VERIFIED`；Profile binding 未切换，未调用 RQData，长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。正式证据位于 `data/reports/full_history_audit_v2_20260710/derived_periods_005_final_001/`。
