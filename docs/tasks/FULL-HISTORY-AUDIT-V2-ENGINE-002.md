# FULL-HISTORY-AUDIT-V2-ENGINE-002

生成时间：2026-07-17

状态：`FULL_HISTORY_AUDIT_V2_READY`

## 1. 目标与边界

本任务以冻结的 V1 全历史契约、B2-01 physical inventory 和 direct PostgreSQL reference metadata 为输入，用动态品种/周期窗口替代 legacy final audit 的统一 `2023-01-03` 与固定 `2020..2026` 假设。

硬边界：

- 不写生产 DB，不调用 `flush` / `commit`。
- 不写 canonical Parquet、manifest、quality 或 Profile binding。
- 不导入或调用 RQData。
- 保留旧 target/final audit 和历史报告，只新增 V2 输出。
- audit end 固定为 `2026-07-10`。
- 旧 `1853 / 34 / 45` 只进入 legacy comparison，不参与 V2 Gate。

## 2. 实现

新增：

- `services/quant-api/app/services/rqdata_ingest/full_history_reference_metadata.py`
- `services/quant-api/app/services/rqdata_ingest/full_history_audit_v2.py`
- `scripts/rqdata_full_history_audit_v2.py`
- `services/quant-api/tests/test_full_history_reference_metadata.py`
- `services/quant-api/tests/test_full_history_audit_v2.py`

核心行为：

- expected year 从每个 `product + period + source_role` 的动态起点生成到 audit end。
- provider authoritative start、physical minimum、listing metadata 和最终 target start 分列保存。
- 当前没有权威 provider earliest 快照时，physical minimum 只形成 `start_boundary_supported`，不伪装精确理论起点。
- direct 1d 与 derived-from-1m 1d 分开；后者继承 1m 起点。
- weekly start 使用首个 completed weekly physical bar；TradingCalendar 不足以证明完整历史时保持 supported/unverified。
- actual dominant 只按 direct PostgreSQL `MainContractMap.rank=1` 有效区间生成 1m/1d 目标，不按发现的文件反推。
- asset layer、reference metadata 和 Profile eligibility 使用独立矩阵。
- `trading_sessions` 按产品适用性生成一行，不按年度机械重复；因当前 schema 无有效期，历史范围标记 `historical_scope_unverified`。
- direct PostgreSQL 不可用时返回 `ENV_BLOCKED_DB`；filtered run 只能得到 smoke 状态。
- 写报告前检查 V2 文件不存在，且记录 B2-01 输入 SHA-256 before/after。

## 3. V2 输出

目录：`data/reports/full_history_audit_v2_20260710/`

- `audit_v2_expected_windows.csv`
- `audit_v2_target_year_matrix.csv`
- `audit_v2_actual_rank1_ranges.csv`
- `audit_v2_asset_layer_matrix.csv`
- `audit_v2_reference_metadata_matrix.csv`
- `audit_v2_profile_eligibility_matrix.csv`
- `audit_v2_gap_register.csv`
- `audit_v2_summary.json`
- `audit_v2_legacy_comparison.json`
- `FULL_HISTORY_AUDIT_V2.md`

正式只读运行事实：

```text
status=FULL_HISTORY_AUDIT_V2_READY
data_gate_status=DATA_LAYER_REAUDIT_REQUIRED
db_snapshot_source=direct_postgresql
products=90
expected_windows=720
dynamic_year_rows=7964
actual_rank1_targets=12726
asset_layer_rows=720
reference_metadata_rows=630
profile_eligibility_rows=1350
gap_rows=180
trading_calendar_gap=90
trading_session_gap=90
writes_database=false
writes_parquet=false
calls_rqdata=false
```

五层事实继续分离：physical coverage 为 `468 covered / 252 partial`，registration 为 `720 registered`，quality 为 `693 passed / 6 warning / 21 failed`。reference metadata 因 calendar 只到 `2026-07-07` 且 session schema 无历史有效期，正式 Gate 保持 gap/unverified；warning 和 failed 未升级为 passed。

## 4. Golden evidence

在当前没有 authoritative provider-start snapshot 的前提下：

| product | direct 1m support | direct 1d support | direct 1w completed support | end |
|---|---|---|---|---|
| a | 2010-01-04 | 2002-03-15 | 2002-03-15 | 2026-07-10 |
| al | 2010-01-04 | 2000-01-05 | 2000-01-07 | 2026-07-10 |
| ag | 2012-05-10 | 2012-05-10 | 2012-05-11 | 2026-07-10 |
| jm | 2013-03-22 | 2013-03-22 | 2013-03-22 | 2026-07-10 |

以上起点状态为 `start_boundary_supported`，不是 provider authoritative exact。`ag` 的 2012-05-11 是合法首个 completed week；`jm` 不要求 2010 分钟线。

## 5. 验证

```text
baseline legacy/contract/inventory: 48 passed
new V2 tests: 8 passed
combined contract/V2/inventory/legacy/profile regression: 73 passed
ruff: passed
representative direct PostgreSQL smoke: FULL_HISTORY_AUDIT_V2_SMOKE_READY
formal direct PostgreSQL run: FULL_HISTORY_AUDIT_V2_READY
```

## 6. 状态语义

```text
FULL_HISTORY_AUDIT_V2_READY
DATA_LAYER_REAUDIT_REQUIRED
```

第一个状态只表示 V2 engine、输入和新矩阵可复查。当前 provider earliest 边界仍非 authoritative，calendar/session reference metadata 仍有缺口，physical/quality/Profile 也未全部严格通过，因此不能宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
