# Task 3 Report — session facts and direct weekly mapping

## Scope and boundary

- Changed only reusable `market_data` infrastructure, maintenance orchestration,
  bounded Candidate CLI diagnostics, and existing data-foundation test modules.
- No RQData request was made. All provider behaviour was exercised by local
  DataFrame fixtures; all persistence tests used in-memory SQLite and pytest
  temporary paths.
- No Candidate/production database, Canonical root, Runtime, notification, or
  order state was read or written.

## RED evidence

The following commands were run before the corresponding production fixes:

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  -k 'weekly_adapter_requests_full_iso_context or historical_session_coverage_rejects_missing_provider_context'
```

Result: `2 failed, 17 deselected`. The weekly adapter requested only the
expected Friday and the coverage source had no historical-session check.

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  -k 'weekly_adapter_requests_full_iso_context or historical_session_coverage_rejects_missing_provider_context or historical_trading_period_facts_not_current_hours'
```

Result: `3 failed, 17 deselected`. The third failure showed that a current
contract `trading_hours` field was being written as an open-ended historical
session rather than using a range fact.

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_maintenance.py \
  -k 'historical_session_facts_are_missing'
```

Result: `1 failed, 13 deselected`: maintenance still reached the provider after
the test coverage source declared the historical facts missing.

## Implementation

- `RQDataMarketAdapter.fetch` expands direct `1w` requests to Monday–Sunday
  ISO context, keeps provider frequency `1w`, and resolves provider rows by
  `(ISO year, ISO week)` only. The ordinal fallback was removed.
- `_RqdatacClient.metadata_snapshot` now calls RQData
  `get_trading_periods(..., start_date, end_date, frequency="1m")` for actual
  rank-1 contracts and stores per-date historical session facts. It no longer
  uses current `Contract.trading_hours` to fill an historical window. Calendar
  facts are persisted for every context/window day.
- `DatabaseCoverageSource.require_historical_session_facts` fails closed when
  provider-backed Calendar facts do not cover the minimum context/window or a
  trading day lacks an effective historical session. It emits only
  `CANDIDATE_SESSION_FACT_MISSING` with at most 20 D14-shaped samples.
- `HistoricalDataManager.update/bootstrap` invokes this check after metadata
  synchronization and before any bar-provider request. Candidate CLI output
  validates and bounds the same diagnostic samples.
- Derived `5m/15m/30m/60m` paths were not changed; `1w` remains direct.

## GREEN evidence

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_maintenance.py \
  services/quant-api/tests/data_foundation/test_metadata.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

Result: `44 passed`.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation
```

Result: `93 passed`.

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation

MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli
```

Result: Ruff passed; mypy passed (`16 source files`).

## Known unknowns

- The range-session adapter is verified only with fixtures. A real provider
  request remains an external Gate and is deliberately unexecuted.
- `get_trading_periods` malformed, duplicate, missing, or mismatched rank-1
  rows fail closed; no older `get_trading_hours` fallback is used.
- No Candidate Gate A/B/C conclusion follows from this repository-only change.
