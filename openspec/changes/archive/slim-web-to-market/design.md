## Context

See proposal.md for motivation. Current Web (`apps/quant-web`) registers dashboard/signal/strategy/review/data/runtime beside Market; API (`services/quant-api`) mounts matching routers plus `/ws/signals` and RQ signal/notification workers. Market chart still embeds signal layer, right-rail tabs, and FuturesResearch. Data Core V2 / Canonical Market read path and CLI must stay intact. No production DB mutation authorized.

## Goals / Non-Goals

**Goals:**
- Collapse Web to Market-only navigation and chart observation with EMA/HTDY/MACD.
- Unmount retired routers/workers so removed modules have no live executable surface.
- Keep data/runtime HTTP + CLI and Market canonical APIs.
- Keep DB tables and quant-core strategy sources for later rebuild.

**Non-Goals:**
- Dropping DB tables or rewriting Alembic history.
- Deleting quant-core strategy implementations.
- Rebuilding strategy/signal/backtest/review features.
- Enabling live, notifications, or auto trading.
- Changing the 69-product active universe.

## Decisions

1. **Delete pages and unmount routers rather than feature-flag**  
   Rationale: goal is a clean baseline; dormant routes invite accidental use.  
   Alternative considered: leave APIs mounted but hide Web nav — rejected (half-dead surface).

2. **Retain `/api/v1/data` and `/api/runtime` despite removing Web pages**  
   Rationale: ops/acceptance still use HTTP or CLI; SystemPulse/Web pages go, APIs stay.  
   Alternative: remove HTTP too and keep CLI only — deferred; CLI already covers status, but data center API remains useful for tooling.

3. **Unmount `futures_research` and `watchlists` routers if Web consumers are gone**  
   Rationale: chart research panel removed; avoid orphan APIs. Confirm no remaining frontend imports before delete.

4. **Leave ORM models in place; stop workers**  
   Rationale: avoids controlled external DB mutation; models can be cleaned in a later authorized migration.

5. **Default home `/market`**  
   Rationale: only remaining primary surface.

## Risks / Trade-offs

- [Orphan imports/tests break CI] → Delete or rewrite tests that target removed routers/pages in the same change; run directed frontend build + backend pytest.
- [Operators expect Web data/runtime pages] → Document that ops move to CLI/`STATUS.md`; APIs remain.
- [Later rebuild needs signal tables] → Tables retained; only executable surface removed.
- [Large chart.vue refactor risk] → Prefer surgical removal of signal/right-rail/research blocks over full rewrite.

## Migration Plan

1. Land OpenSpec artifacts, then implement frontend shell + chart slim, then backend unmount, then docs/tests.
2. Deploy as ordinary `develop` code change; no production data writes.
3. Rollback: revert the commit; DB schema unchanged so rollback is code-only.

## Open Questions

None — grilling decisions locked in proposal/plan.
