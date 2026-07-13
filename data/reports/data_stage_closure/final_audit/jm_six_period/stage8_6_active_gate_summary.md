# Stage 8.6 Active Gate Summary

- profile: `jm_main_six_period_latest`
- products: 1
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Product Status

| status | count |
|---|---:|
| audit_pending | 1 |

## Asset Gate Status

| status | count |
|---|---:|
| audit_pending | 1 |

## Stage 9 Readiness

| status | count |
|---|---:|
| stage9_blocked | 1 |

Stage 9 remains guarded by `evaluate_stage9_signal_event_gate()`; this audit does not authorize enterprise WeChat sending.
