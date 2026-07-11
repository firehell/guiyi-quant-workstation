# Target Coverage Audit Summary

- mode: `target_coverage_audit`
- audit_end: `2026-07-10`
- products: 90
- target_catalog_rows: 17689
- physical_inventory_rows: 15159
- issue_register_rows: 4528
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `http://127.0.0.1:8000/api/v1/data`
- db_error: `OperationalError: (psycopg.OperationalError) connection failed: connection to server at "127.0.0.1", port 5432 failed: fe_sendauth: no password supplied
(Background on this error at: https://sqlalche.me/e/20/e3q8)`

## Coverage Status

| status | count |
|---|---:|
| covered_passed | 16164 |
| covered_warning | 1144 |
| missing_db_registration | 108 |
| not_applicable | 273 |

## Metadata Status

| status | count |
|---|---:|
| metadata_gap | 3276 |
| not_applicable | 504 |

## Issue Types

| status | count |
|---|---:|
| db_unavailable | 3276 |
| missing_db_registration | 108 |
| quality_warning | 105 |
| source_interval_unverified | 1039 |

## Scope Notes

- This report is a target coverage matrix, not a Stage 8.6 active snapshot.
- Stage 8.6 `1326 active_passed / 8 audit_pending` remains a discovered active asset snapshot only.
- The known 8 pending records are not repaired here; this audit only classifies target coverage gaps.
- JM V1-B latest six-period baseline remains separate and should still be verified through the JM Stage 8.6 profile.
- Stage 9 remains blocked until signal-event, actual-contract, trigger-price and metadata gates pass; this audit does not authorize enterprise WeChat sending.
