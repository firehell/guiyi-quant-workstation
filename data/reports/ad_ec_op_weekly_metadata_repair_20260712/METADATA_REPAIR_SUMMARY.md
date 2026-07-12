# AD/EC/OP Weekly Metadata Row Count Repair Summary

- mode: `weekly_metadata_row_count_repair`
- operation: `apply`
- output_dir: `data/reports/ad_ec_op_weekly_metadata_repair_20260712`
- db_status: `available`
- writes_database: `True`
- writes_parquet: `False`
- calls_rqdata: `False`
- ready_to_apply: `True`

## Candidates

| product | db_file_id | file | before | target | manifest | processed | duckdb | duplicate_datetime | classification | decision | blocked_reasons |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|
| ad | 44115 | `ad_MAIN_1w_20230103_20260707_v2.parquet` | 47 | 55 | 55 | 55 | 55 | 0 | `old_version_metadata_stale` | `ready` | `` |
| ec | 44133 | `ec_MAIN_1w_20230103_20260707_v2.parquet` | 134 | 148 | 148 | 148 | 148 | 0 | `old_version_metadata_stale` | `ready` | `` |
| op | 44159 | `op_MAIN_1w_20230103_20260707_v2.parquet` | 36 | 42 | 42 | 42 | 42 | 0 | `old_version_metadata_stale` | `ready` | `` |

## Boundary

- This repair may update only `market_data_files.row_count` for the three fixed 20260707 weekly metadata rows.
- It does not write Parquet, manifest, checksum, data_version, data_role, quality_status, RQData downloads, strategy, signal, live runtime, scheduler or trading execution state.
