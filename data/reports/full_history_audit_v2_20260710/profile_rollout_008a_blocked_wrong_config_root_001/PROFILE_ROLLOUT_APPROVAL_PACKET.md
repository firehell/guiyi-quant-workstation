# DATA-PROFILE-ROLLOUT-DRYRUN-008A Approval Packet

Status: `PROFILE_ROLLOUT_DRYRUN_BLOCKED`

This packet is dry-run evidence only. It does not authorize or execute a binding apply.

## Profile batches

| Profile | Current | Would change | Unchanged | Blocked |
|---|---:|---:|---:|---:|
| intraday_research_v1 | 0 | 0 | 0 | 1 |
| long_horizon_daily_v1 | 0 | 0 | 0 | 1 |
| live_observation_v1 | 0 | 0 | 0 | 1 |

Exact before/after market_data_file_id and data_version values are frozen in `binding_diff.csv`.
Rollback: reactivate the exact prior binding/file recorded per identity in a single approved transaction; rollback the batch on any error.

## Representative pilot evidence

| Product | Current | Would change | Unchanged | Blocked | Apply recommendation |
|---|---:|---:|---:|---:|---|
| a | 0 | 0 | 0 | 0 | blocked; do not apply |
| al | 0 | 0 | 0 | 0 | blocked; do not apply |
| ag | 0 | 0 | 0 | 0 | blocked; do not apply |
| jm | 0 | 0 | 0 | 0 | blocked; do not apply |

Recommended staged pilot order: `none`.

## Frozen report 14 reference

Frozen reference rows: `0`. They remain excluded from new current selection and were not modified.

## Gate and risk

- Current candidates: `0`; duplicate current identities: `0`.
- Dry-run: would_change=`0`, unchanged=`0`, errors=`0`.
- Candidate verification passed: `True`; checksum checked: `0`.
- Blocked rows remain fail-closed: `3`; no blocked identity is approved by this packet.
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

- `binding_candidates.csv`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `binding_blocked_ledger.csv`: `fc963bb5f72f895478a8c8ac819c0e934ef01f4d0fbaf36d280715edcfde8285`
- `binding_diff.csv`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `dry_run_results.csv`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `rollout_summary.json`: `4cb5f64c8a1ee48fe43981329a4f6cdd9117eb27ed7a370028416649f13ec85a`
