# Target Coverage Audit Summary

- mode: `data_sealing_audit`
- audit_end: `2026-07-10`
- products: 90
- target_catalog_rows: 17581
- physical_inventory_rows: 15056
- issue_register_rows: 113
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- db_snapshot_source: `database`
- git_commit: `134cad3543cbc6afed67433e527ddbfa1c5cd337`
- sealing_mode: `True`
- duplicate_inventory_rows: 385
- orphan_inventory_rows: 3
- disposition_register_rows: 14018
- unclassified_dispositions: 0

## Checksum Status

| status | count |
|---|---:|
| checksum_matched | 15049 |
| checksum_mismatch | 3 |
| missing_physical_file | 4 |

## Coverage Status

| status | count |
|---|---:|
| covered_passed | 17195 |
| covered_warning | 105 |
| metadata_gap | 8 |
| not_applicable | 273 |

## Metadata Status

| status | count |
|---|---:|
| covered_passed | 3276 |
| not_applicable | 504 |

## Issue Types

| status | count |
|---|---:|
| checksum_mismatch | 8 |
| quality_warning | 105 |

## Scope Notes

- This report is a target coverage matrix, not a Stage 8.6 active snapshot.
- Stage 8.6 `1326 active_passed / 8 audit_pending` remains a discovered active asset snapshot only.
- The known 8 pending records are not repaired here; this audit only classifies target coverage gaps.
- JM V1-B latest six-period baseline remains separate and should still be verified through the JM Stage 8.6 profile.
- Stage 9 remains blocked until signal-event, actual-contract, trigger-price and metadata gates pass; this audit does not authorize enterprise WeChat sending.
