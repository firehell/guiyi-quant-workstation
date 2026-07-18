# DATA-PROFILE-ROLLOUT-DRYRUN-008A Approval Packet

Status: `PROFILE_ROLLOUT_DRYRUN_READY`

This packet is dry-run evidence only. It does not authorize or execute a binding apply.

## Profile batches

| Profile | Current | Would change | Unchanged | Blocked candidate rows | Excluded |
|---|---:|---:|---:|---:|---:|
| intraday_research_v1 | 89 | 89 | 0 | 577 | 0 |
| long_horizon_daily_v1 | 174 | 150 | 24 | 81 | 0 |
| live_observation_v1 | 2 | 2 | 0 | 2 | 0 |

Exact current/blocked selection reasons are in `binding_candidates.csv` and `binding_blocked_ledger.csv`.
Exact before/after market_data_file_id and data_version values are frozen in `binding_diff.csv`.
Rollback: reactivate the exact prior binding/file recorded per identity in one approved transaction; rollback the batch on any error.

## Representative pilot evidence

| Product | Target identities | Current identities | Missing current identities | Would change | Unchanged | Whole-product recommendation |
|---|---:|---:|---:|---:|---:|---|
| a | 8 | 3 | 5 | 3 | 0 | blocked; use exact identity subset only |
| al | 8 | 3 | 5 | 3 | 0 | blocked; use exact identity subset only |
| ag | 8 | 3 | 5 | 3 | 0 | blocked; use exact identity subset only |
| jm | 22 | 15 | 7 | 7 | 8 | blocked; use exact identity subset only |

Recommended whole-product pilot order: `none`. Each representative product has unresolved target identities; no blocked identity may enter apply. A later task may freeze an exact subset drawn only from the 265 verified current identities.

## Frozen report 14 reference

`report_id=14` remains `frozen_reference_only`; it is not eligible as a new current candidate. Matching candidate rows: `0`; modified: `false`.

## Gate and risk

- Current candidates: `265`; duplicate current identities: `0`.
- Dry-run: would_change=`241`, unchanged=`24`, errors=`0`.
- Candidate verification passed: `True`; declared-vs-physical checksum checked: `265`.
- Blocked candidate rows remain fail-closed: `660`; excluded rows: `0`.
- Main risks for a later apply are stale active state, concurrent binding changes, duplicate active identities, and rollback lineage drift.
- A later apply must regenerate/compare the DB before-state and use an explicit batch approval; this dry-run is not approval.

## Write boundary

```text
writes_database=false
writes_parquet=false
writes_manifest=false
binding_apply_executed=false
calls_rqdata=false
report_id_14_modified=false
```

## Evidence hashes

- `binding_candidates.csv`: `639009e89a8c5424c7de8281f059e296495595bc75c1abe939c19d461deba59b`
- `binding_blocked_ledger.csv`: `9f239d0fded6ff558b9b06b8f1c9d58b1451b60d136b51abd5021a52cdc01713`
- `binding_diff.csv`: `5792ec8e03f4bbe29d46aaa36cd4f7557f1eddbd4a8094dcc9ec80c8c3010327`
- `dry_run_results.csv`: `39f408f153ea57112b4927698810926c01c07b6d3dbe37e4c4d1a3a10eb90f11`
- `rollout_summary.json`: `7bd937db8d29b7a64944109fe6804c031f273464efa6c865ecd9cefa3f6a4e44`
