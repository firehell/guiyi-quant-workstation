# DATA-PROFILE-FULL-HISTORY-RULES-007

生成时间：2026-07-18

状态：`COMPLETED / PROFILE_FULL_HISTORY_SELECTION_READY`

## 目标

将 `intraday_research_v1`、`long_horizon_daily_v1`、`live_observation_v1` 从旧 2020/2023/pilot 描述调整为 Audit V2 target-aware 语义，并修复仅依赖 `start_ts`/版本字符串的候选选优。

本任务只修改配置、候选生成、rulebook、validator、rollout fail-closed 行为与测试。禁止 binding apply、DB/Parquet/manifest 写入、RQData 调用和 `report_id=14` 修改。

## 冻结输入

正式 target 只允许来自：

```text
audit_v2_expected_windows.csv
derived_periods_005_final_001/consumer_target_matrix.csv
derived_periods_005_final_001/derived_period_inventory.csv
actual_dominant_roll_006_final_002/actual_target_coverage.csv
```

旧 `target_asset_catalog.csv` 不再作为正式 candidate target；缺失边界或 evidence 不可读时 fail-closed。

## 选择语义

1. provider、role、period、data role 与 quality policy 必须符合。
2. physical、metadata、checksum、sealing 以及必要的 derived 1m lineage 必须通过。
3. candidate 必须覆盖 Profile 的全部 target ranges。
4. 完整覆盖后优先 canonical/current evidence，再按版本、normalized path 与 file id 稳定排序。
5. target 只要求 2023 时，不因另一候选始于 2010 而无条件优先；provider-earliest target 下 2023 窄窗口必须阻断。
6. frozen report 14 reference 不得成为新 current；冲突 checksum duplicate fail-closed。

## 输出

只读 generate 写入新的非覆盖目录：

```text
data/reports/full_history_audit_v2_20260710/profile_rules_007/
  target_matrix.csv
  binding_candidates.csv
  blocked_ledger.csv
  generation_summary.json
  PROFILE-BINDING-GENERATION-SUMMARY.md
  dry_run_summary.json
```

候选新增固定 evidence 字段：

```text
target_start,target_end,target_ranges
coverage_start,coverage_end,covers_target
selection_reason,block_reason
checksum_status,sealing_status,lineage_status
```

`dry-run/apply/verify` 拒绝旧 schema、`covers_target=false`、checksum/sealing/lineage 不通过的候选。本任务只执行 generate 与 dry-run，不执行 apply/rollback/commit。

## Gate

验收标记：

```text
PROFILE_FULL_HISTORY_SELECTION_READY
writes_database=false
writes_parquet=false
writes_manifest=false
binding_apply_executed=false
calls_rqdata=false
report_id_14_modified=false
```

该标记仅证明 target-aware selection engine 和只读候选证据可用，不代表 binding 已切换，也不将长期状态从 `DATA_LAYER_REAUDIT_REQUIRED` 自动升级。

## 实际执行

Mac mini direct PostgreSQL read-only generate 与 dry-run 已完成：

```text
status=PROFILE_FULL_HISTORY_SELECTION_READY
products_count=90
target_rows=734
binding_candidate_rows=925
current_rows=265
blocked_rows=660
current_covering_rows=265
incomplete_coverage_rows=118
conflict_rows=2
target_resolution_issue_count=0
dry_run_candidate_count=265
dry_run_would_change=241
dry_run_unchanged=24
dry_run_errors=0
transaction_read_only=true
binding_apply_executed=false
```

660 条 blocked evidence 保持 fail-closed：494 lineage unverified、118 target coverage incomplete、45 quality policy violation、2 conflicting duplicate、1 checksum evidence missing。本 Task 未把这些 residual 自动转换为 apply ledger。

正式报告：`data/reports/full_history_audit_v2_20260710/profile_rules_007_final_002/`。首次旧 sealing-only 诊断与后续中间报告保留为历史证据，不作为正式 Gate。
