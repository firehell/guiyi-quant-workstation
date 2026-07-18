# DATA-PROFILE-ROLLOUT-DRYRUN-008A Approval Packet

Status: `PROFILE_ROLLOUT_DRYRUN_BLOCKED`

This packet is dry-run evidence only. It does not authorize or execute a binding apply.

## Profile batches

| Profile | Current | Would change | Unchanged | Blocked |
|---|---:|---:|---:|---:|
| intraday_research_v1 | 0 | 0 | 0 | 666 |
| long_horizon_daily_v1 | 0 | 0 | 0 | 255 |
| live_observation_v1 | 0 | 0 | 0 | 4 |

Exact before/after market_data_file_id and data_version values are frozen in `binding_diff.csv`.
Rollback: reactivate the exact prior binding/file recorded per identity in a single approved transaction; rollback the batch on any error.

## Representative pilot evidence

| Product | Current | Would change | Unchanged | Blocked | Apply recommendation |
|---|---:|---:|---:|---:|---|
| a | 0 | 0 | 0 | 11 | blocked; do not apply |
| al | 0 | 0 | 0 | 11 | blocked; do not apply |
| ag | 0 | 0 | 0 | 11 | blocked; do not apply |
| jm | 0 | 0 | 0 | 27 | blocked; do not apply |

Recommended staged pilot order: `none`.

## Frozen report 14 reference

Frozen reference rows: `0`. They remain excluded from new current selection and were not modified.

## Gate and risk

- Current candidates: `0`; duplicate current identities: `0`.
- Dry-run: would_change=`0`, unchanged=`0`, errors=`0`.
- Candidate verification passed: `True`; checksum checked: `0`.
- Blocked rows remain fail-closed: `925`; no blocked identity is approved by this packet.
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

- `binding_candidates.csv`: `1f107451482f7990b9a9aed5a3dbcf0fdd1f946291e660a67161346f3800e5c1`
- `binding_blocked_ledger.csv`: `f2706f7b85f6280bf7985b09b2960d3e1a1e43b271332505e6468d4937d447e3`
- `binding_diff.csv`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `dry_run_results.csv`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `rollout_summary.json`: `f5f5afa738a31c3739571affa5ecb544146b8bae7657bd58d6faf2a69fd33e64`
