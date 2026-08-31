# SuBing Live Trading-Day Rollover

## Problem

Stage 2 currently caps an occupancy-missing new trading day to the last mapped
day and silently ignores later completed Live bars.  A trading-day change is
not, by itself, a physical-contract segment rollover.

## Authority model

The only Live continuation identity seam classifies a frozen machine identity,
incoming bar trading day, `MarketReadState.trading_day`, frozen Live contract,
and `live_eligible/live_available` as exactly one of:

- `CONTINUE_SAME_SEGMENT`;
- `LIVE_CONTRACT_AUTHORITY_PENDING`;
- `STALE_OR_IDENTITY_INVALID`.

Same-contract continuation is causal Live authority.  MainContractMap is the
only authority for a formal physical-segment rollover.

## Same-contract continuation

If frozen Live contract equals the machine contract, the machine retains its
original `segment_start_trading_day`, is not terminal, creates no new segment,
and accepts completed 1m/5m/15m bars for the new trading day.  Before a new day
is advanced, Runtime resolves its TradingSession, authoritative interval, and
that day's direction context.  Missing or stale Daily Watch supplies the
existing typed UNAVAILABLE context: it blocks new entries but not
Factor/Lifecycle progression or exits for an existing position.

## Different-contract pending

A different Live contract never enters the old physical segment.  If its
MainContractMap occupancy is absent, or a confirmed new occupancy has not yet
been applied by `canonical_updated`, only that product becomes unavailable with
the fixed public reason `LIVE_CONTRACT_AUTHORITY_PENDING`.

## canonical_updated reconciliation

Ready products retain ordinary terminal checks.  Among unavailable products,
only `LIVE_CONTRACT_AUTHORITY_PENDING` may reconcile.  The trigger must confirm
the frozen pending contract as the next MainContractMap segment; it then
terminals the old segment and restores the new one.  Every other unavailable
reason remains fail-closed.

## Restart/catch-up

Restart and final catch-up use the same continuation seam as natural Live.
They may advance a same-contract new day or enter pending, but never backfill
ordinary actions, AlertEvents, or notifications.  If final catch-up completes
only after the market has closed, it may use the existing operational,
same-trading-day `post_close` display snapshot as a frozen completed-Live
authority.  Every 1m/5m/15m snapshot must retain the exact
`actual_dominant` identity, be `CLOSED`, have the same frozen subscription
contract, and contain only bars at or before the catch-up cutoff.  This path is
limited to final catch-up; it does not make post-close data ordinary Live input.
Missing, mixed-contract, mixed-day, non-operational, or malformed snapshots
remain fail-closed; a different valid frozen contract is still
`LIVE_CONTRACT_AUTHORITY_PENDING`.

## Event/no-backfill contract

Natural Live actions keep the existing Event-first/one-shot transport path.
Only a newly authoritative natural `canonical_updated` terminal close may use
that path.  Startup restore, final catch-up, startup drain, replay, and
non-natural reconciliation create no Event and send nothing.

## Acceptance tests

- same-contract new-day cutoffs advance without a new segment;
- missing/stale Daily Watch blocks entries while exits continue;
- different Live contract is isolated pending until formal canonical rollover;
- restart/final catch-up has identical authority and no backfill;
- post-close final catch-up uses only the same-contract frozen completed-Live
  boundary; missing or inconsistent frozen snapshots fail closed;
- only pending products reconcile on `canonical_updated`;
- historical/Live parity, prefix invariance, causality, and Active60 isolation
  remain intact.

## Non-goals

No HTTP, database, Alembic, Scope, Runtime-health, stale/grace monitoring,
Live-enable, notification configuration, release, or Runtime-promotion change.
