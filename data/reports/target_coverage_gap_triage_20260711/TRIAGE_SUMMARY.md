# Target Coverage Gap Triage Summary

- mode: `target_coverage_gap_triage`
- source_report: `data/reports/target_coverage_audit_20260711/`
- output_dir: `data/reports/target_coverage_gap_triage_20260711/`
- reads_database: `False`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`
- input_issue_register_rows: 2091

## Executive Triage

- `source_interval_unverified`: 1039 target rows, 276 unique Parquet files; all checked rows classify as `source_interval_column_missing`. This is a metadata/provenance column gap, not evidence of broken OHLCV rows by itself.
- `row_count_mismatch`: 8 target rows map to 3 unique weekly dominant-main files: `ad.MAIN`, `ec.MAIN`, `op.MAIN`. DuckDB reads more rows than DB/manifest row_count, with zero duplicate datetimes in the sampled files; this points first to stale or incomplete metadata row counts.
- `missing_db_registration`: 108 target rows are retained as candidate-only records for a controlled metadata registration plan; no DB write is performed here.
- `quality_failed`: 105 target rows preserve failed quality status and require separate readonly quality root-cause review; no status upgrade is performed here.
- metadata consistency gaps: 831 rows, mostly contract universe and continuous contract map gaps.

## Issue Register Counts

| item | count |
|---|---:|
| `source_interval_unverified` | 1039 |
| `missing_continuous_contract_map` | 546 |
| `missing_contract_universe` | 285 |
| `missing_db_registration` | 108 |
| `quality_failed` | 105 |
| `row_count_mismatch` | 8 |

## Source Interval Triage By Period

| period | triage_result | count |
|---|---|---:|
| `15m` | `source_interval_column_missing` | 185 |
| `1d` | `source_interval_column_missing` | 299 |
| `30m` | `source_interval_column_missing` | 185 |
| `5m` | `source_interval_column_missing` | 185 |
| `60m` | `source_interval_column_missing` | 185 |

## Row Count Mismatch Unique Files

| symbol | metadata_row_count | duckdb_row_count | delta | duplicate_datetime_count | duckdb_min | duckdb_max |
|---|---:|---:|---:|---:|---|---|
| `ad.MAIN` | 47 | 55 | 8 | 0 | `2025-06-13T00:00:00` | `2026-07-03T00:00:00` |
| `ec.MAIN` | 134 | 148 | 14 | 0 | `2023-08-18T00:00:00` | `2026-07-03T00:00:00` |
| `op.MAIN` | 36 | 42 | 6 | 0 | `2025-09-12T00:00:00` | `2026-07-03T00:00:00` |

## Missing DB Registration By Product

| item | count |
|---|---:|
| `l` | 46 |
| `pp` | 31 |
| `v` | 31 |

## Quality Failed By Symbol

| item | count |
|---|---:|
| `bb.MAIN` | 14 |
| `jr.MAIN` | 14 |
| `pm.MAIN` | 14 |
| `ri.MAIN` | 14 |
| `rs.MAIN` | 14 |
| `wh.MAIN` | 14 |
| `fb.MAIN` | 7 |
| `wr.MAIN` | 7 |
| `zc.MAIN` | 7 |

## Metadata Gaps By Type

| item | count |
|---|---:|
| `missing_continuous_contract_map` | 546 |
| `missing_contract_universe` | 285 |

## Recommended Next Gates

1. `source_interval_unverified`: add or repair provenance metadata only through a separate controlled data/metadata plan; do not mark the assets failed solely because the column is absent.
2. `row_count_mismatch`: compare DB `market_data_files.row_count` and manifest row_count against DuckDB row_count for the three weekly files, then decide whether the metadata should be refreshed or the Parquet needs regeneration.
3. `missing_db_registration`: create a dry-run registration manifest for `L/PP/V` actual contracts first, then run a gated DB write only after manual approval.
4. `quality_failed`: inspect the underlying quality reports for abnormal price or other failed checks; do not overwrite failed status for coverage cosmetics.
