# FULL-HISTORY-DERIVED-PERIODS-005

生成时间：2026-07-17

状态：`COMPLETED / DERIVED_PERIOD_TARGETS_VERIFIED`

## 1. 目标与边界

本任务核验 V1 consumer target 的 `5m / 15m / 30m / 60m / derived 1d` 物理覆盖与 exact 1m lineage。固定 audit end 为 `2026-07-10`。

- JM V1-B Backtest、Signal 与 live observation 历史参考为 hard scope。
- 90 品种 `intraday_research_v1` 为 eligibility inventory，不自动触发全量重建。
- long-horizon direct `1d/1w` 与 derived `1d` 分离。
- verify 不写 DB、Parquet、manifest，不调用 RQData，不切换 Profile binding。
- repair 只接受由冻结 hard residual 生成的精确 ledger；未获得批准不执行。

## 2. 实现

新增：

- `services/quant-api/app/services/rqdata_ingest/full_history_derived_periods.py`
- `scripts/rqdata_full_history_derived_periods.py`
- `services/quant-api/tests/test_full_history_derived_periods.py`

复用并增强：

- `bar_aggregation.py` 增加 session-aware strict aggregation，保留旧 API 行为。
- `trading_session_clock.py` 增加批量交易日窗口解析，避免 full verification 逐日重复查询。

严格核验要求 processed summary 明确指向同一 registered passed-primary 1m path，并同时满足 source interval、source bar count、physical checksum、目标窗口与 full bucket recomputation。仅存在 `source_interval=1m` 不构成 lineage 证明。

## 3. 受控修复

JM 的 173 条 RQData 合约记录一致声明 `21:01–23:00,09:01–10:15,10:31–11:30,13:31–15:00`。冻结并执行 `jm-session-reference-005-001`：

```text
calendar_update=827
calendar_noop_no_night=24
session_insert=4
session_retire=1
ledger_sha256=05cf7afff36d923381cc63301db38494dfb778b7de5d60e05587b033da4a6c28
status=APPLIED_VERIFIED
```

旧 `CNFE/jm/regular` 行保留但 inactive；新增 DCE JM 夜盘、上午两段和下午时段，provider 为 `rqdata_contract_v1`。交易日日历按普通相邻日或周五至周一允许夜盘，节后首日不允许夜盘。

session 修复后的 full verification 仅剩 derived 1d exact-lineage residual。随后执行唯一资产批次 `jm-derived-1d-005-001`：

```text
operation_count=1
source_market_data_file_id=71290
target_window=2023-06-28..2026-06-26
new_market_data_file_id=103921
data_role=candidate
quality_status=passed
row_count=726
ledger_sha256=e27ad7ed841643d64df2a4928ec94f6e2d5a948f33bb3b53c8b47375afdcd728
profile_binding_changed=false
calls_rqdata=false
```

新 1d Parquet 和 processed summary 保存 source file id/path/version/checksum/profile、`source_interval=1m` 与 `source_bar_count`。旧 1d、现有 5m/15m 和 active binding 均未修改。

## 4. 最终实数证据

direct PostgreSQL、实际外置盘全量 full：

```text
product_count=90
consumer_target_count=548
derived_inventory_row_count=548
hard_target_count=8
hard_residual_count=0
lineage_residual_count=202
formal_gate_eligible=true
status=DERIVED_PERIOD_TARGETS_VERIFIED
db_snapshot_source=direct_postgresql
writes_database=false
writes_parquet=false
writes_manifest=false
calls_rqdata=false
profile_binding_changed=false
```

JM hard 5m/15m 继续使用既有 candidate，逐 bucket 与 passed-primary 1m 匹配；JM derived 1d 使用新 candidate 103921。七条派生 hard target均为 `coverage=covered / lineage=verified / session=passed / source_gap=0 / content=matched / checksum=matched`。

最终报告：

```text
data/reports/full_history_audit_v2_20260710/derived_periods_005_final_001/
```

修复证据：

```text
data/reports/full_history_audit_v2_20260710/derived_periods_005_session_repair_plan_001/
data/reports/full_history_audit_v2_20260710/derived_periods_005_repairs/jm-derived-1d-005-001/
```

## 5. Gate

验收标记为 `DERIVED_PERIOD_TARGETS_VERIFIED`。这只代表 V1 consumer 派生周期 target 已核验，不切换 Profile binding，也不把 90 品种 eligibility residual 自动升级为重建任务。长期状态保持 `DATA_LAYER_REAUDIT_REQUIRED`。
