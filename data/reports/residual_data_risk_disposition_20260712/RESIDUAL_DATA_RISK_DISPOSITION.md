# Residual Data Risk Disposition

- mode: `residual_data_risk_disposition`
- source_report: `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`
- output_dir: `data/reports/residual_data_risk_disposition_20260712/`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Executive Result

The old-version weekly `row_count_mismatch` issue is closed after the controlled `ad/ec/op` DB metadata repair. Remaining issues are not safe to auto-apply in the same stage, so they are converted into explicit gated follow-up tracks.

## Residual Issue Summary

| issue_group | rows | unique_assets | disposition | next_gate |
|---|---:|---:|---|---|
| `source_interval_unverified` | 1039 | 276 | provenance repair only; do not mark data failed | `source_interval_provenance_repair_dry_run` |
| `missing_db_registration` | 108 | 93 | DB registration candidate dry-run first | `lpv_actual_contract_registration_dry_run` |
| `quality_failed` | 105 | 15 | readonly root-cause audit; do not upgrade status | `quality_failed_root_cause_audit` |
| `metadata_reference_gaps` | 831 | 0 | reference metadata dry-run/backfill plan | `reference_metadata_gap_dry_run` |
| `workspace_external_changes` | 0 | 0 | previously observed items are not active in current git status | `manual_git_checkpoint_or_separate_task` |

## Decisions

### source_interval_unverified

- Current evidence: `1039` target rows map to `276` unique derived Parquet files.
- All rows classify as `source_interval_column_missing`.
- All affected coverage rows keep `quality_status=passed`; this is provenance metadata debt, not OHLCV corruption evidence.
- Required repair boundary: if the Parquet files are rewritten to add `source_interval=1m`, the same controlled stage must also refresh checksums in manifest, processed summary and DB `market_data_files.checksum`.
- No Alembic/schema change is recommended for this stage; there is no existing `market_data_files.source_interval` column.

### missing_db_registration

- Current evidence: `108` target rows, `93` unique physical files.
- Products: `l`, `pp`, `v`.
- Current status is candidate-only from manifest/physical files.
- Next action must be a dry-run registration manifest that verifies file existence, DuckDB row count, manifest quality `passed`, checksum and exact unique key before any DB write.

### quality_failed

- Current evidence: `105` target rows, `15` unique files.
- Products include `bb/fb/jr/pm/ri/rs/wh/wr/zc` dominant-main `1d/1w`.
- Failed status must be preserved until a readonly root-cause audit decides whether to rebuild, redownload, archive, or keep failed.
- Do not convert `failed` to `passed` or `warning` for coverage cosmetics.

### reference metadata gaps

- Current evidence: `831` metadata rows.
- Missing continuous contract map: `546`.
- Missing contract universe: `285`.
- This should be handled as reference metadata sync/backfill, not as page-local Market/Backtest/Signal fallback logic.

### workspace external changes

- `README.md`, `scripts/local-services-status.sh`, and `scripts/post-reboot-verify.sh` were previously observed around the worktree state and are outside this data-risk task.
- Current `git status --short` no longer reports these paths as active changes.
- No action is required in this data task; if they reappear, handle them through a separate runtime/local-workstation checkpoint.

## Next Step

Open the next controlled task for `source_interval_provenance_repair_dry_run`. It should be dry-run first and produce exact per-file update candidates before any Parquet/checksum/DB metadata write.
