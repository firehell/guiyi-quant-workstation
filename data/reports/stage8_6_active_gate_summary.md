# Stage 8.6 Active Gate Summary

- profile: `stage8_6_1d_first`
- products: 90
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Product Status

| status | count |
|---|---:|
| active_partial | 8 |
| active_passed | 82 |

## Asset Gate Status

| status | count |
|---|---:|
| active_passed | 176 |
| audit_pending | 8 |

## Stage 9 Readiness

| status | count |
|---|---:|
| stage9_blocked | 90 |

Stage 9 remains guarded by `evaluate_stage9_signal_event_gate()`; this audit does not authorize enterprise WeChat sending.
