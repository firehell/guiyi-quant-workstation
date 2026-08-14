# Live Channel Grace Teardown Design

## Goal

Make RQData Live provider channels follow the active market phases without losing a delayed
session-final 1m Bar. A channel may remain subscribed only while its product is `TRADING` or
while an already-started subscription is inside the existing 60-second session-end arrival
grace. After that grace expires, the service must request a real provider unsubscribe and make
the heartbeat converge to the remaining channel count.

This repair is independent of the successful 18:05 after-market update. It does not change
Canonical data, `MainContractMap`, the frozen daily rank1 snapshot, Redis after-market cleanup,
or any Runtime activation.

## Current Defect

`LiveMarketService.poll()` returns early when no product is `TRADING`, and
`LiveMarketService.reconcile()` also returns before calculating its channel diff when there is
no active trading day. Therefore the service never reaches `provider.unsubscribe()` during an
all-idle interval. The heartbeat truthfully reports the retained in-memory `_channels`, while
Runtime health accepts the fresh and available heartbeat without checking phase/count
consistency.

The existing session-end protection drains buffered final Bars for 60 seconds, but it has no
matching teardown step after the grace. Existing tests cover mixed phase reconciliation and
the first seconds after a session ends, but not the transition from an active subscription to
an all-idle state after the grace expires.

## Selected Design

Use one channel-lifecycle rule for both mixed and all-idle phase states:

```text
desired channels
= channels for current TRADING products
+ already-subscribed channels whose most recent known Session ended no more than 60 seconds ago
```

The grace rule only retains an existing channel. It must never create a provider or add a new
subscription while no product is trading.

The service will extract channel diff application into one private operation. It will:

1. calculate removed and added channels;
2. avoid creating a provider when both the current and desired channel sets are empty;
3. call `unsubscribe` before `subscribe`, preserving the existing ordering;
4. update `_channels` only after provider operations succeed;
5. publish heartbeat state from the successfully applied channel set.

For an all-idle poll cycle, the order is:

1. resolve phases and known Session facts;
2. drain the already-started provider buffer;
3. finalize due Bars;
4. retain channels still inside the 60-second arrival grace;
5. unsubscribe channels whose grace expired;
6. publish the resulting heartbeat.

For a mixed phase cycle, the normal reconciliation path uses the same desired-channel rule.
This closes the related case where a short-session product could otherwise be unsubscribed
immediately while another product remained trading.

The 60-second boundary is inclusive, matching `_session_for_bar`: a session-final Bar is still
eligible when `now == session_end + 60 seconds`; teardown occurs only when `now` is later than
that boundary.

## Provider Failure Semantics

An unsubscribe failure must not be reported as a Redis failure and must not be represented as
a successful cleanup. The service keeps the previous `_channels`, marks provider availability
false, publishes a degraded heartbeat, and returns `LIVE_PROVIDER_UNAVAILABLE`. A later
trading reconciliation retries through the existing `_ProviderUnavailable` ten-second recovery
path; it clears local channels only when replacing the failed provider client.

Redis failures retain their existing fail-closed `LIVE_REDIS_UNAVAILABLE` classification.

## Scope

Modify only:

- `services/quant-api/app/market_data/live_market.py`
- `services/quant-api/tests/data_foundation/test_live_market.py`

No new public API, configuration option, dependency, persistence table, scheduler, or Runtime
health payload field is introduced. A transient `subscribed_count > TRADING` during the
documented 60-second grace is valid; after the grace it must converge.

## Test Contract

The regression suite must prove:

1. an existing channel remains subscribed through `session_end + 60 seconds`;
2. a buffered final Bar remains accepted and finalized during that grace;
3. the first poll after the grace unsubscribes exactly once and publishes count zero when all
   products are idle;
4. mixed products retain and remove their channels independently by Session boundary;
5. repeated idle polls do not repeat unsubscribe calls;
6. an idle service with no provider does not create one;
7. unsubscribe failure is provider-specific, leaves the old channel set visible, and degrades
   availability;
8. existing rank1 snapshot, final-Bar, reconnect, Redis failure, and derived-Bar tests remain
   green.

## Acceptance Boundary

Passing tests establishes `CODE_COMPLETE` and `TEST_COMPLETE` for the repository change. It
does not authorize or prove a Runtime switch. Runtime acceptance requires a separately
authorized reload of an exact commit followed by read-only observation of a natural market
phase transition.
