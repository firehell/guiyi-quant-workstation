# HTDY Account Execution Implementation Plan

> Inline execution with superpowers:executing-plans; one independent whole-change safety review.

**Goal:** Implement the accepted 70%-margin, permanent-skip, opponent-limit, natural-180s and final-close-60s policies with durable local reservations and no Broker transport.

**Architecture:** A versioned account reducer consumes existing HTDY Signal/Owner/native fill identities, explicit authoritative funding/instrument/quote/session/readback facts, and emits proposals only. Keep the earlier v1 reducer as a frozen compatibility baseline; the new account profile is the sole next-stage execution entry. Local SQLite serializes commands, state and effects under one transaction; no production database/migration/Runtime.

**Spec:** docs/HTDY_SIMNOW_V1.md (accepted account/order decisions).

## Scope and validation

- Facts are explicit injected native/authoritative inputs, never AI-created or provider fallback; cash/price/margin calculations use Decimal.
- Preserve real late fills, unknown outcomes and occupancy. Only complete account/trade/position proof can settle and release.
- Recovery cancels old opening intentions and does not backfill signals; closing obligations survive. Trading session final-close is contract-specific, not intraday breaks.
- Evidence freshness is bounded by fact validity intervals; no new signal expiry or price stop.
- No broker/order/cancel I/O, no Runtime enable, no real account modification. Fixtures do not prove live readiness.

## Work

1. Define deep model/value objects, reducer, serialization and fixture builders. Prove 70% admission, concurrent reservations, duplicate/frozen signals and permanent skips.
2. Implement acknowledged-order lifecycle, natural-time repricing, cancel/readback release, close-only cutoff, reversal, late fill, rollover and restart recovery. Test boundary races and invalid facts.
3. Add local SQLite command journal/state/effect commit and duplicate recovery. Prove serialization across two independent SQLite connections, rollback and deterministic replay/checkpoint; do not send effects.
4. Expose an explicit operational-universe seam, update canonical/testing/status after results, run direct and existing HTDY/formula/adapter regressions. Independent safety review and fix verified findings before commit/push/integration.

## Validation result

124 related tests passed; Ruff, secret scan (0), diff checks passed. Independent high-risk review findings repaired with regression tests; focused review permits develop integration. No Broker or Runtime I/O.

## Review focus

- Margin frozen by the broker must not be counted twice or release unreflected local exposure; fills require newer account facts before another open.
- Cancelled/filled/unknown reports without trade/position reconciliation never free capacity or allow a replacement.
- Cutoff defeats a simultaneous 180s retry, and never drops the pending close portion of reversal.
- Late contradictory fills remain immutable evidence and block, rather than resetting to an imaginary flat state.
- Restore and two concurrent writers cannot resend or exceed account capacity; no old risk-rejected signal requalifies.
