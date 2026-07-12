# AD/EC/OP Weekly Row Count Reconcile Summary

- mode: `weekly_row_count_reconcile`
- output_dir: `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair`
- db_status: `available`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Classification Counts

| classification | count |
|---|---:|
| `matched` | 9 |

## Reconcile Rows

| product | file | db_row_count | manifest_row_count | processed_summary_row_count | duckdb_row_count | duplicate_datetime_count | newer_matched_sibling | classification |
|---|---|---:|---:|---:|---:|---:|---|---|
| ec | `ec_MAIN_1w_20230103_20260707_v2.parquet` | 148 | 148 | 148 | 148 | 0 | True | `matched` |
| ec | `ec_MAIN_1w_20230103_20260710_v2.parquet` | 149 | 149 |  | 149 | 0 | True | `matched` |
| ec | `ec_MAIN_1w_20230103_20260711_v2.parquet` | 149 | 149 | 149 | 149 | 0 | False | `matched` |
| ad | `ad_MAIN_1w_20230103_20260707_v2.parquet` | 55 | 55 | 55 | 55 | 0 | True | `matched` |
| ad | `ad_MAIN_1w_20230103_20260710_v2.parquet` | 56 | 56 |  | 56 | 0 | True | `matched` |
| ad | `ad_MAIN_1w_20230103_20260711_v2.parquet` | 56 | 56 | 56 | 56 | 0 | False | `matched` |
| op | `op_MAIN_1w_20230103_20260707_v2.parquet` | 42 | 42 | 42 | 42 | 0 | True | `matched` |
| op | `op_MAIN_1w_20230103_20260710_v2.parquet` | 43 | 43 | 43 | 43 | 0 | True | `matched` |
| op | `op_MAIN_1w_20230103_20260711_v2.parquet` | 43 | 43 | 43 | 43 | 0 | False | `matched` |

## Conclusion Boundary

- This task reconciles row-count evidence only; it does not repair metadata.
- `source_interval` provenance metadata is out of scope for this run.
- No PostgreSQL, Parquet, manifest, checksum, RQData, strategy, signal, live runtime or trading execution writes are authorized by this report.
