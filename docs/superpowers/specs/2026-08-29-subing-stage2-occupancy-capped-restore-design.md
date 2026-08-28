# SuBing Stage 2 occupancy-capped restore

**Date:** 2026-08-29

## Problem

Production Alert Runtime restore after 2026-08-29 00:08 promotion returned `strategy_state=degraded` with active60 `0 ready / 60 unavailable`. HTDY processing stayed `ok`.

Read-only diagnosis against production Catalog:

- Daily Watch expected day at Saturday 00:49 was `2026-08-31`
- MarketPhase unique active day was also `2026-08-31` (11 overnight products `TRADING`)
- `dominant_segment_for_day(symbol, 2026-08-31)` raised `MAIN_CONTRACT_MAP_MISSING` for closed and trading symbols
- rank1 occupancy `effective_end` was `2026-08-28` for sampled products (`jm`, `au`, `ag`, `a`)

Root cause: restore used the next-session Daily Watch day as the current rank1 target. MainContractMap occupancy is only written through the last Canonical trading day, so every product failed before replay.

## Decision

When the expected target day has no rank1 occupancy, restore and catch-up fall back to the previous common mapped day (the last Canonical occupancy day) and replay Canonical through that day inclusive.

Live overlay is used only when `MarketReadState.trading_day` equals that replay target. Next-session Live bars are not mixed into the last occupancy segment and are not an identity error.

This does not invent Monday occupancy, does not write Catalog, and does not backfill Events or notifications. After the next natural after-market writes `2026-08-31` occupancy, `canonical_updated` remains the existing rollover seam.

## Non-goals

- Extending MainContractMap into future days without Canonical coverage
- Changing Daily Watch expected-day cutover
- Owner canary or WeChat delivery evidence
- New Alert Rule, Scope, or migration
