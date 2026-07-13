# DATA LAYER FINAL AUDIT

- audit_time: `2026-07-13T00:30:35.779983+00:00`
- git_commit: `f8b71a2643c1342c4f70fca676baeb654032b616`
- audit_end: `2026-07-10`
- data_root: `/Volumes/扩展盘/guiyi-quant-workstation/data`
- db_snapshot_source: `manifest_only`
- db_snapshot_time: `2026-07-13T00:28:25.144907+00:00`
- products: `90`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Coverage Status

| status | count |
|---|---:|
| missing_db_registration | 15918 |
| not_applicable | 273 |

## Candidate Claim Verdicts

| claim | verdict | detail |
|---|---|---|
| 全品种已经下载2020年至今的1m数据 | rejected | passed=0/339 catalog_years=2023..2026; claim_2020_plus_not_in_target_matrix (architecture_starts=2023-01-03) |
| 架构口径：主力1m自2023-01-03起 | rejected | passed=0/339 catalog_years=2023..2026 |
| 全品种已经下载2020年至今的1d数据 | rejected | passed_or_warning=0/546 |
| 全品种已经下载2020年至今的1w数据 | partial | products_full_post2020=0/90 |
| 全品种从上市以来到2019年末的1w数据也已经下载 | rejected | pre2020_covered=0/63 |
| 全品种1w候选覆盖范围为上市以来至最新完成周 | rejected | direct_1w_present=0/90; audit_end=2026-07-10 |
| 已下载主连、历史主力真实合约及相关附加数据 | rejected | dominant_main_passed=0/0; actual_contract_passed=0/0 |

## Legacy Metric Re-check

- stage8_6 product active_passed / active_partial: `0` / `0`
- stage8_6 asset active_passed / audit_pending: `0` / `90`
- legacy `82/90` still valid: `False`
- legacy `1326` still valid: `False`
- legacy `8 pending` still valid: `False`

## quality_warning (must not upgrade to passed)

- count: `0`

## JM Six-Period Snapshot

- jm product_status: `audit_pending`

## Phase 1 Conclusion

本报告为只读审计产物，**不代表数据层最终封板完成**。
若 claim 与架构口径冲突、1w 历史覆盖不足或 crosscheck 存在差异，须进入 Phase 2 受控补齐。

## Evidence Files

- `audit_evidence.json`
- `target_coverage_matrix.csv`
- `weekly_history_audit.csv`
- `duplicate_active_assets.csv`
- `orphan_files.csv`
- `main_contract_mapping_audit.csv`
- `daily_intraday_crosscheck.csv`
