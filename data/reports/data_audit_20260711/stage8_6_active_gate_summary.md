# Stage 8.6 Active Gate Snapshot Summary

- profile: `stage8_6_1d_first`
- products: 90
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `http://127.0.0.1:8000/api/v1/data`
- cli_rerun_status: `blocked_missing_database_url_in_data_audit_worktree`

## Product Status

| status | count |
|---|---:|
| active_partial | 8 |
| active_passed | 82 |

## Asset Gate Status

| status | count |
|---|---:|
| active_passed | 1326 |
| audit_pending | 8 |

## Asset Count Semantics

`1326 active_passed` is a manifest-level discovered active-record count for the current `stage8_6_1d_first` snapshot. It is not proof that the full target historical data catalog is covered.

Current matrix grain:

```text
product + asset_scope + contract + period + standard_path
```

Breakdown:

| dimension | group | count |
|---|---|---:|
| total matrix rows | all records | 1334 |
| asset_scope | actual_contract | 1244 |
| asset_scope | actual_contract / active_passed | 1241 |
| asset_scope | actual_contract / audit_pending | 3 |
| asset_scope | dominant_main | 90 |
| asset_scope | dominant_main / active_passed | 85 |
| asset_scope | dominant_main / audit_pending | 5 |
| period | 1d | 1334 |
| provider inferred from path | rqdata | 1334 |
| DuckDB physical check | row count and datetime boundary checked | 1334 |
| checksum physical check | not independently proven for every file in this report | 0 |
| DB registration | registered active_passed records | 1326 |
| DB registration | missing market_data_file pending records | 3 |
| quality warning | registered pending records | 5 |

## Stage 9 Readiness

| status | count |
|---|---:|
| stage9_blocked | 90 |

Stage 9 remains guarded by `evaluate_stage9_signal_event_gate()`; this audit does not authorize enterprise WeChat sending.

Note: the primary CLI command was attempted first but this worktree has no `.env` / `DATABASE_URL`, so DB metadata was read through the already-running local readonly API instead of reading credentials.

This report is a Stage 8.6 active snapshot only. It is the first baseline for the broader data asset inventory, not a complete target-coverage audit for 2020+ daily/weekly assets, 2023+ minute assets, derived periods, historical actual contracts, calendars, sessions, mappings, contract parameters, manifests, checksums, DB registration, and physical files.
