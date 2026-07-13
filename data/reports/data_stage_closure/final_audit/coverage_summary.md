# Target Coverage Audit Summary

- mode: `target_coverage_audit`
- audit_end: `2026-07-10`
- products: 90
- target_catalog_rows: 16191
- physical_inventory_rows: 14163
- issue_register_rows: 19194
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `manifest_only`
- db_error: `OperationalError: (psycopg.OperationalError) connection failed: connection to server at "127.0.0.1", port 5432 failed: fe_sendauth: no password supplied
(Background on this error at: https://sqlalche.me/e/20/e3q8); api_snapshot_error=HTTPError: HTTP Error 502: Bad Gateway`

## Coverage Status

| status | count |
|---|---:|
| missing_db_registration | 15918 |
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
| missing_db_registration | 15918 |

## Scope Notes

- This report is a target coverage matrix, not a Stage 8.6 active snapshot.
- Stage 8.6 `1326 active_passed / 8 audit_pending` remains a discovered active asset snapshot only.
- The known 8 pending records are not repaired here; this audit only classifies target coverage gaps.
- JM V1-B latest six-period baseline remains separate and should still be verified through the JM Stage 8.6 profile.
- Stage 9 remains blocked until signal-event, actual-contract, trigger-price and metadata gates pass; this audit does not authorize enterprise WeChat sending.
