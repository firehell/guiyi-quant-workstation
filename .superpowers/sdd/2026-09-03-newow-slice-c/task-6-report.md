# Task 6 report — actual-dominant D1 detail service

## Files

- `services/quant-api/app/market_data/newow/__init__.py`
- `services/quant-api/app/market_data/newow/trend_detail_query.py`
- `services/quant-api/app/market_data/newow/trend_detail_service.py`
- `services/quant-api/tests/newow/test_trend_detail_service.py`

## Design

- Uses `ActualDominantResearchSegmentLoader` and the injected `MarketDataService` only.
- Replays each restored rank-1 physical segment with one fresh `NewowTrendD1Engine`; its same-contract prefix is numeric pre-warm-up only, and clipping happens after replay.
- Returns immutable tuple facts for bars, frames, markers, cup overlays, seams, and warnings.  Public failures are mapped to a small stable Newow detail code set.
- No formula/core, Web, DB, Redis, cache, worker, Runtime, or external-data changes.

## Verification

`PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_trend_detail_service.py`

Result: `6 passed`.

`PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api ruff check services/quant-api/app/market_data/newow services/quant-api/tests/newow/test_trend_detail_service.py`

Result: passed.

## Commit

`feat(newow): add actual dominant D1 detail service`

## Unresolved risks

Task 7 remains responsible for the separate bounded-work proof.  This service performs only read-only request-scoped replay and does not authorize any production data or Runtime operation.
