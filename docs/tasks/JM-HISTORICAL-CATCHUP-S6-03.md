# JM-HISTORICAL-CATCHUP-S6-03

## Task Metadata

| Field | Value |
|---|---|
| Task ID | JM-HISTORICAL-CATCHUP-S6-03 |
| Task branch | feature/jm-historical-catchup-s6-03 |
| Worktree | /private/tmp/guiyi-s6-03 |
| Risk Level | L3 |
| Status | CODE_COMPLETE_APPROVAL_PACKET_PENDING |

## Goal

JM-only historical catch-up to the dynamically resolved latest provider-final trading day. Generate a commit-bound approval packet before any real write, then execute reference metadata, continuous, actual, derived, quality, registration, Profile CAS, consumer smoke, idempotency and final audit in order.

## Allowed Paths

- `docs/tasks/JM-HISTORICAL-CATCHUP-S6-03.md`
- `services/quant-api/app/services/rqdata_ingest/jm_historical_catchup.py`
- `services/quant-api/app/services/rqdata_ingest/jm_historical_catchup_execution.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/scripts/jm_historical_catchup.py`
- `services/quant-api/tests/test_jm_historical_catchup.py`
- `services/quant-api/tests/test_jm_historical_catchup_execution.py`
- `services/quant-api/tests/test_live_target_freshness.py`
- canonical status documents after the real Gate
- packet-listed JM-only files under the approved output root
- approved JM-only metadata, quality and Profile rows in PostgreSQL

## Forbidden

- Other products, existing asset overwrite, live tables, SignalEvent, notification, strategy, backtest, report 14, trade or order writes.
- Push, merge, deploy, scheduler/live enablement or service restart.

## Gates

```text
JM_HISTORICAL_CATCHUP_READY
JM_REFERENCE_METADATA_FRESH
JM_LIVE_TARGET_FRESHNESS_READY
```

All remain pending until the hash-approved real apply and final audit pass.

## Implemented Controls

- Dynamic latest completed trading day requires both session close and provider-final direct daily data.
- Reference calendar, rank-1 mapping, trading parameters and fee/margin candidates are refreshed before bars.
- Continuous direct `1m/1d/1w` and actual direct `1m/1d` use overlap downloads; local derived periods use the new full `1m` candidate.
- Every candidate is create-only and quality must be exactly `passed`; warning is not promotable.
- Continuous and actual direct candidates merge immutable active baselines before Profile promotion.
- Profile promotion uses an approval-bound active binding snapshot and compare-and-switch in the registration transaction.
- Live target freshness can be checked against an explicit `required_date`.
- Apply requires `--run-write`, `--confirm-jm-only` and the exact approved packet hash.
- A matching completion receipt makes repeated apply return `already_completed` without writes.

## Verification Before Real Approval

```text
74 passed
ruff: passed
git diff --check: passed
read-only real preflight: passed
immediate packet fact re-verification: passed
```

The pre-commit smoke packet bound commit `a1e01b35` and is invalid after the S6-03 checkpoint commit. A new packet must be generated from the clean checkpoint before real writes.
