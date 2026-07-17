# B-01 Direct PostgreSQL Final Baseline Audit

Gate: `DIRECT_DB_BASELINE_READY`

- db_snapshot_source: `database`
- writes_database: `False`
- writes_parquet: `False`
- writes_manifest/quality/profile_binding: `False`
- calls_rqdata: `False`

## 当前真实指标与旧 Phase 3 差异

| metric | current | phase3 | delta |
|---|---:|---:|---:|
| covered_passed | 0 | 15350 | -15350 |
| covered_warning | 0 | 105 | -105 |
| metadata_gap | 0 | 1853 | -1853 |
| not_applicable | 7600 | 1943 | +5657 |
| pre_2020_weekly_missing | 34 | 34 | +0 |

差异来源必须按 CSV 中的 `classification_source` 逐行追溯；旧 Phase 3 数字保留为历史 canonical，不在本报告中改写。

## 阻塞与下一步输入

- blocked_items: 44432
- weekly_gaps: 34
- actual_roll_gaps: 18592
- profile_bindings: 6591
- cross_file_conflicts: 351
- B-02: `metadata_consistency_matrix.csv`
- B-03: `weekly_gaps.csv`
- B-04: `actual_roll_gaps.csv`
- B-05: `profile_bindings.csv`
