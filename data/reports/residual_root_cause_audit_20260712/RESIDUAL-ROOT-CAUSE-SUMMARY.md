# Residual Root Cause Audit Summary

- output_dir: `data/reports/residual_root_cause_audit_20260712`
- root_cause_rows: 501
- repair_rows: 501
- gate_rows: 397
- multi_primary_csv: `/Volumes/扩展盘/guiyi-quant-workstation/data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Anomaly Types

| anomaly_type | count |
|---|---:|
| `checksum_mismatch` | 3 |
| `duplicate_path_versions` | 385 |
| `missing_physical_file` | 4 |
| `multi_primary_inventory` | 1 |
| `orphan_parquet` | 3 |
| `quality_warning` | 105 |

## Repair Types

| repair_type | count |
|---|---:|
| `archive-only` | 3 |
| `no_action` | 105 |
| `requires_manual_review` | 3 |
| `supersede` | 390 |

## Audit Results

| audit_result | count |
|---|---:|
| `block` | 3 |
| `pass` | 498 |

## Hard Constraints

- `quality_warning` must remain `accepted_warning`; upgrade to `passed` is forbidden.
- This audit is read-only and does not authorize metadata/parquet/db writes.
