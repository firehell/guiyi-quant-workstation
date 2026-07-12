# Duplicate Path Version Reconcile

## Result

- input_duplicate_rows: 6
- unique_paths: 6
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
- No historical DB row is deleted, archived, merged, or modified.
