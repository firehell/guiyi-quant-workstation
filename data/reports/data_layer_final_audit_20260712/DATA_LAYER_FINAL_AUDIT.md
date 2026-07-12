# DATA LAYER FINAL AUDIT

- audit_time: `2026-07-12T15:18:17.407577+00:00`
- git_commit: `7710a51c3c28ff89e6840337f056114dfbbf74af`
- audit_end: `2026-07-10`
- data_root: `/Volumes/扩展盘/guiyi-quant-workstation/data`
- db_snapshot_source: `database`
- db_snapshot_time: `2026-07-12T15:00:46.335898+00:00`
- products: `90`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Coverage Status

| status | count |
|---|---:|
|  | 19251 |

## Candidate Claim Verdicts

| claim | verdict | detail |
|---|---|---|
| 全品种已经下载2020年至今的1m数据 | rejected | no expected 1m rows |
| 架构口径：主力1m自2023-01-03起 | rejected | no expected 1m rows |
| 全品种已经下载2020年至今的1d数据 | rejected | passed_or_warning=0/0 |
| 全品种已经下载2020年至今的1w数据 | partial | products_full_post2020=0/90 |
| 全品种从上市以来到2019年末的1w数据也已经下载 | rejected | pre2020_covered=0/63 |
| 全品种1w候选覆盖范围为上市以来至最新完成周 | confirmed | direct_1w_present=90/90; audit_end=2026-07-10 |
| 已下载主连、历史主力真实合约及相关附加数据 | partial | dominant_main_passed=85/90; actual_contract_passed=1241/1244 |

## Legacy Metric Re-check

- stage8_6 product active_passed / active_partial: `0` / `0`
- stage8_6 asset active_passed / audit_pending: `1326` / `8`
- legacy `82/90` still valid: `False`
- legacy `1326` still valid: `True`
- legacy `8 pending` still valid: `True`

## quality_warning (must not upgrade to passed)

- count: `0`

## JM Six-Period Snapshot

- jm product_gate_status: ``

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
