# Quality Failed Root-cause Audit

## Result

- candidate_target_rows: 105
- unique_paths: 15
- stale_processed_summary_failed: 15
- active_failed: 0
- warning_original_failed: 0
- blocked_metadata_mismatch: 0
- database_counts_unchanged: True
- market_data_files: 71098 -> 71098
- data_quality_reports: 65466 -> 65466

## Safety Boundary

- writes_database=False
- writes_parquet=False
- writes_manifest=False
- calls_rqdata=False
- This audit does not upgrade warning assets to passed.
