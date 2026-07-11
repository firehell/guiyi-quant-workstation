# Stage 8.6 Active Gate Summary

- profile: `jm_main_six_period_latest`
- products: 1
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `http://127.0.0.1:8000/api/v1/data`
- cli_rerun_status: `blocked_missing_database_url_in_data_audit_worktree`

## Product Status

| status | count |
|---|---:|
| active_passed | 1 |

## Asset Gate Status

| status | count |
|---|---:|
| active_passed | 6 |

## Stage 9 Readiness

| status | count |
|---|---:|
| stage9_blocked | 1 |

Stage 9 remains guarded by `evaluate_stage9_signal_event_gate()`; this audit does not authorize enterprise WeChat sending.

Note: the primary CLI command was attempted first but this worktree has no `.env` / `DATABASE_URL`, so DB metadata was read through the already-running local readonly API instead of reading credentials.
