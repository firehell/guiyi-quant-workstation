# DATA-ASSET-PROFILE-ACCEPTANCE-009

## 结论

`DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT`

本结论仅表示资产与 Profile hard Gate 已完成只读验收，可进入阶段 C consumer contract；不表示整个数据层已可供 Market / Backtest / Signal 使用。

## 固定环境

- audit end: `2026-07-10`
- code commit: `d19b67dc68c7f28e8109720be51775390aed49d8` (`main` / `origin/main` 一致: `True`)
- data worktree: `codex/full-history-residual-repair-004b-closure@7273f311d7c5e182f51db5457c27aa8a659a0ae2`
- data root: `/Volumes/扩展盘/guiyi-quant-workstation`
- DB snapshot source: `direct_postgresql`
- DB snapshot: `91955:91955:`
- PostgreSQL transaction read only: `on`
- preflight status: `FULL_HISTORY_AUDIT_ENV_READY`

历史 B2 报告生成于各任务当时的 feature commit；本次统一以已包含这些实现的 `main@d19b67dc68c7f28e8109720be51775390aed49d8` 作为代码验收基准，并以同一数据根及本次 direct PostgreSQL snapshot 复核 Profile 当前状态。

## Hard Gate

- asset gates: `9/9` PASS
- profile gates: `5/5` PASS
- hard blocked register rows: `0`
- current candidates: `265`
- direct DB current mismatches: `0`
- duplicate active groups: `0`
- passed-only non-passed active bindings: `0`
- historical/live boundary violations: `0`
- superseded legacy active bindings formally blocked / live-only excluded / unexplained: `392 / 3 / 0`

## 资产事实

- physical inventory: `27837` rows, checksum matched/readable/schema ok all `27837`
- physical missing/path drift: `0`
- Audit V2: `FULL_HISTORY_AUDIT_V2_READY`, gap count `0`
- quality: passed `693`, warning `27`; warnings promoted to passed: `false`
- actual dominant: `ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED`, formal residual `0`, non-hard inventory residual `1054`
- derived periods: `DERIVED_PERIOD_TARGETS_VERIFIED`, hard residual `0`, non-hard eligibility residual `202`

## Profile 事实

- B2-08A current / blocked: `265 / 660`
- B2-08B final active matches: `265`
- current checksum verified: `265`
- rollback rehearsal rows: `16`
- report_id=14 md5 matched frozen snapshot: `True`
- Profile blocked reasons: `{"checksum_missing|lineage_unverified|missing": 9, "checksum_not_verified": 1, "conflicting_duplicate_candidates": 2, "lineage_unverified": 685, "lineage_unverified|partial": 1, "mapping_date_missing": 1015, "partial": 1, "quality_policy_violation": 45, "roll_transition": 39, "superseded_active_excluded:conflicting_duplicate_candidates": 1, "superseded_active_excluded:lineage_unverified": 379, "superseded_active_excluded:live_tables_only_period": 3, "superseded_active_excluded:quality_policy_violation": 11, "superseded_active_excluded:quality_policy_violation|target_coverage_incomplete": 1, "target_coverage_incomplete": 118}`

## 写入边界

- writes_database: `false`
- writes_parquet: `false`
- writes_manifest: `false`
- changes_profile_binding: `false`
- calls_rqdata: `false`
- starts_live_runtime: `false`

## 输出

- `asset_gate_matrix.csv`
- `profile_gate_matrix.csv`
- `blocked_register.csv`
- `DATA_ASSET_PROFILE_ACCEPTANCE.md`

阶段 C 仍需独立验证 Market / Backtest / Signal consumer contract。本报告不授予阶段 C 的最终数据层状态。
