# Target Coverage Audit Summary

- mode: `target_coverage_audit`
- audit_end: `2026-07-10`
- products: 90
- target_catalog_rows: 19251
- physical_inventory_rows: 17022
- issue_register_rows: 105
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `database`

## Coverage Status

| status | count |
|---|---:|
| covered_passed | 17203 |
| covered_warning | 105 |
| not_applicable | 1943 |

## Metadata Status

| status | count |
|---|---:|
| covered_passed | 3276 |
| not_applicable | 504 |

## Issue Types

| status | count |
|---|---:|
| quality_warning | 105 |

## Scope Notes

- This report is a target coverage matrix, not a Stage 8.6 active snapshot.
- Stage 8.6 `1326 active_passed / 8 audit_pending` remains a discovered active asset snapshot only.
- The known 8 pending records are not repaired here; this audit only classifies target coverage gaps.
- JM V1-B latest six-period baseline remains separate and should still be verified through the JM Stage 8.6 profile.
- Stage 9 remains blocked until signal-event, actual-contract, trigger-price and metadata gates pass; this audit does not authorize enterprise WeChat sending.
