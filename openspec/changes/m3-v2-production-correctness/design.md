## Context

See `proposal.md` for why. Baseline `develop@bb1b75d`. Architecture is frozen on DatasetKey → CanonicalStore → Catalog/Manifest/Gap/MainContractMap → MarketDataService.

Current code already proves several defects:
- `_filter_missing` keeps full `DataTarget` when any sub-window is missing; Aggregate/Publisher publish that full requested window → Catalog conflict risk.
- Explicit `--since` with full coverage force-extends identity targets.
- Apply calls planner/`latest_completed_day` before metadata; metadata runs only when `plan.windows` is non-empty; empty publish set can early-return without metadata refresh.
- Calendar writer hardcodes `CNFE`; readers use exchange-specific codes and still have CNFE / CZCE fallbacks in `TradingSessionClock`.
- Catch-up since resolution excludes actual-dominant-only holes; completeness cannot be inferred from already-present actual datasets.

Formal canonical remains `docs/tasks/GY-DATA-CORE-V2.md`. This OpenSpec change is an implementation delta only.

## Goals / Non-Goals

**Goals:**
- Make routine update exact-append and idempotent at a fixed `--through`.
- Bootstrap metadata before final planning on apply.
- Drive actual-dominant completeness from refreshed MainContractMap expectations.
- Migrate Calendar/Session to actual-exchange identity without breaking current reads.
- Make 1w and M2 diagnostics gateable with executable acceptance.

**Non-Goals:**
- Redesigning Data Core V2, relaxing Catalog conflict, or adding overlay/version_replacement for routine catch-up.
- Restoring Profile/Binding/Hive/after-market/data_center HTTP.
- Dropping `DataDownloadTask` / `MarketDataFile` / `DataQualityReport`.
- Runtime promotion, autosend, or full Canonical rebuild.
- Turning OpenSpec into a second long-lived business canonical.

## Decisions

### D1 — `materialize_missing_targets` in planner; keep download TOCTOU
- **Choice:** Planner materializes exact targets via `plan_missing_windows`; Download keeps execution-time `plan_missing_windows` recheck.
- **Why:** Intent planning and execution-time safety are different layers, not a second selector.
- **Rejected:** Only fixing Derived; only relying on Download to clip after whole-window plan.

### D2 — `--since` is lower bound only
- **Choice:** Remove force-refresh branch when covered + explicit since → NOOP.
- **Why:** Force-refresh republishes covered windows and fights append-only Catalog.
- **Rejected:** Overloading `--since` as repair; widening Catalog to allow overlap.

### D3 — Apply control flow is bootstrap-first
- **Choice:** selected products → Calendar/Session bootstrap → latest completed day → MainContractMap refresh → final exact plan → Direct → Aggregate → verify.
- **Why:** Avoids calendar/map staleness loops when initial plan is empty/NOOP.
- **Rejected:** Keep plan→metadata→replan gated on `plan.windows`.
- **Dry-run:** no RQData/DB/Canonical writes; may emit `metadata_watermark` / `metadata_refresh_required`.

### D4 — Actual-dominant from map expectations
- **Choice:** Expand rank1 contiguous contract windows into expected seven-frequency identities, then exact-diff Catalog.
- **Why:** A brand-new dominant with zero Catalog rows is invisible if only scanning existing datasets.
- **Rejected:** continuous-only catch-up frontier; inferring completeness from present actual datasets.

### D5 — Calendar/Session migration is staged
- **Choice:** Writer first materializes actual exchanges; remove CNFE calendar/session and CZCE hardcoded fallbacks only after G0/G2 proves coverage.
- **Why:** Immediate fallback deletion can break production reads.
- **Rejected:** Dual-track permanent resolver; deleting residual CNFE rows in this change (leave unread/unwritten).
- **`has_night_session`:** define from real samples before writing; no unconditional `False`.

### D6 — ORM cleanup without new migration
- **Choice:** Delete Profile/Binding/Checkpoint model definitions/imports/tests; keep ingest recorder tables.
- **Why:** 0035 already dropped tables; need Base.metadata alignment only.
- **Gate wording:** head==0035; retired tables absent in DB and metadata; no autogenerate recreate suggestion.

### D7 — 1w semantics frozen then matrixed
- **Choice:** weekly watermark = last trading day of latest fully completed ISO week; AD 1w owner = rank1 on that week-last trading day.
- **Why:** Current `complete_week_end(through_day, today=through_day)` and daily-rollover clipping disagree with weekly ownership needs.
- **Rejected:** Deferring 1w out of M3; guessing provider-only fixes without matrix.

### D8 — M2 diagnostics propagate existing errors
- **Choice:** Replace bool probe with bounded `ProbeOutcome`; split map-invalid vs mapped-dataset-missing.
- **Why:** 676 identical unreadables hide root causes; second audit engine is forbidden.
- **Rejected:** Lowering M2 strictness to zero findings.

### D9 — Production gates and canary selection
- **Choice:** G0 read-only → G1 local → conditional G2 metadata mutation → G3 JM → G4 per-exchange deterministic canary → G5 69 → G6 M2 → G7 same `--through` NOOP.
- **Canary algorithm:** per actual exchange, lexicographically smallest active symbol with continuous 1m Catalog coverage and rank1 map; no canary registry.
- **Rejected:** JM→69 with no canary; second dry-run without fixed watermark.

## Risks / Trade-offs

- [Stale CNFE rows remain] → Mitigation: readers ignore CNFE at final Gate; deletion is a later controlled op if desired.
- [G2 metadata mutation needed] → Mitigation: only when G0 shows incomplete actual-exchange coverage; separate one-shot intent; no bars download.
- [DataGap leftover on 69] → Mitigation: do not auto-erase; classify as independent repair; Final Gate stays blocked.
- [1w provider semantics still ambiguous after matrix] → Mitigation: keep Gate blocked; fix only confirmed layer; no speculative multi-layer patch.
- [Bootstrap increases apply RQData/metadata cost] → Mitigation: necessary for correctness; dry-run stays zero-network.

## Migration Plan

1. G0 read-only production inventory (no mutation intent). Update STATUS/DATA_CENTER/ARCHITECTURE with observed facts only.
2. Land Wave1 code behind local G1: exact windows, since semantics, bootstrap-first apply, map-expected AD, writer calendar/session, ORM cleanup.
3. If needed, G2 metadata normalization intent → verify actual-exchange coverage → remove reader fallbacks.
4. Land Wave2: 1w matrix + fix; M2 ProbeOutcome + map split.
5. Production intents separately: G3 JM, G4 canary, G5 69, G6 M2 read, G7 same-through NOOP.
6. Only after six hard conditions: document Data Foundation Frozen in canonical docs; archive this OpenSpec change.

Rollback: revert task branch commits; do not force Catalog overlays; do not reintroduce Profile selector.

## Open Questions

- Exact evidence rule for `has_night_session` after G0 sample inspection (must be fixed before writer finalization; does not change specs above).
- Whether residual CNFE row deletion becomes a post-M3 controlled cleanup (out of this change).
