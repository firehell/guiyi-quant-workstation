# Source Interval Provenance Repair Dry Run

- mode: `source_interval_provenance_repair_dry_run`
- output_dir: `data/reports/source_interval_provenance_repair_dry_run_after_full_20260712`
- writes_database: `False`
- writes_parquet: `False`
- writes_manifest: `False`
- writes_processed_summary: `False`
- calls_rqdata: `False`

## Executive Result

- affected_coverage_rows: `1039`
- unique_candidate_files: `276`
- source_interval_issue_register_rows: `1039`
- source_interval_triage_rows: `1039`

## Candidate File Counts

| period | count |
|---|---:|
| `15m` | 49 |
| `1d` | 80 |
| `30m` | 49 |
| `5m` | 49 |
| `60m` | 49 |

## Source Interval Status

| status | count |
|---|---:|
| `already_source_interval_1m` | 276 |

## Apply Eligibility

| apply_eligible | count |
|---|---:|
| `False` | 276 |

## Synchronization Boundary

- This run only creates per-file repair candidates.
- If an apply task rewrites Parquet to add `source_interval=1m`, it must refresh the file checksum and file size evidence.
- The same apply task must update manifest checksum rows, processed summary checksum rows when present, and DB `market_data_files.checksum` for rows with `db_market_data_file_id`.
- `quality_status`, `data_role`, `data_version`, row counts and OHLCV values are not changed by this dry-run.

## Next Gate

- Open a separate controlled apply task only after reviewing `candidate_files.csv`.
- The apply task must remain file-level, because multiple target years can map to the same Parquet file.
