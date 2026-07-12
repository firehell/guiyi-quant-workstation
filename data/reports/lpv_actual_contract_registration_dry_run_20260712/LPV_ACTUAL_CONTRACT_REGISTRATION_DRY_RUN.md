# LPV Actual Contract Registration Dry-run

## Result

- candidate_target_rows: 108
- unique_paths: 93
- already_registered: 87
- eligible_for_registration: 0
- duplicate_path_versions: 6
- blocked_metadata_mismatch: 0
- database_counts_unchanged: True
- market_data_files: 71098 -> 71098
- data_quality_reports: 65466 -> 65466

## Safety Boundary

- writes_database=False
- writes_parquet=False
- writes_manifest=False
- calls_rqdata=False
- Duplicate path versions are reported only; no historical DB row is deleted, merged, archived or changed.

## Human Gate

- No registration candidate remains. Controlled DB registration is not authorized or required by this dry-run.
