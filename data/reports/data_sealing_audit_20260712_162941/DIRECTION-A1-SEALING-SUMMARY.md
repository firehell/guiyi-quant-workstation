# DIRECTION-A1 Final Data Sealing Summary

- mode: `data_sealing_audit`
- audit_end: `2026-07-10`
- products: 90
- git_commit: `134cad3543cbc6afed67433e527ddbfa1c5cd337`
- db_snapshot_source: `database`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Physical Inventory

- physical_inventory_rows: 15056
- checksum_matrix_rows: 15056
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

## Disposition Register

| status | count |
|---|---:|
| accepted_warning | 15 |
| active_passed | 13499 |
| checksum_mismatch_requires_review | 6 |
| duplicate_version_requires_review | 385 |
| metadata_mismatch_requires_review | 4 |
| not_applicable | 106 |
| orphan_requires_disposition | 3 |

## Acceptance

- A1 checksum proven: `15056/15056`
- A1 zero unclassified: `PASS`

## Scope Notes

- This is a final sealing readonly audit. It does not repair data, register DB rows, or call RQData.
- quality_warning rows remain `accepted_warning`; they are not upgraded to passed.
- report_id=14 baseline remains frozen and is not rewritten by this audit.
