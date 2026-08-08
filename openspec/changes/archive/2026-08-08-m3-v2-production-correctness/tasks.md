## 1. Baseline facts (G0)

- [x] 1.1 Run read-only production inventory: alembic head, retired tables absent, canonical root, legacy roots, Catalog provider URI share, active exchanges, per-exchange calendar max date / session counts, MainContractMap max dates, DataGap count, CNFE residual, has_night_session distribution
- [x] 1.2 Update `STATUS.md`, `docs/DATA_CENTER.md`, and `docs/ARCHITECTURE.md` with observed facts only (no Foundation Ready; no unearned M3 semantics in GY-DATA-CORE-V2)

## 2. Exact missing + since semantics

- [x] 2.1 Implement `materialize_missing_targets` in historical update planner so Direct and Derived emit exact Catalog holes only
- [x] 2.2 Keep Download execution-time `plan_missing_windows` TOCTOU recheck; do not widen Catalog conflict rules
- [x] 2.3 Remove explicit-`--since` force-refresh of fully covered identity windows; covered range MUST NOOP
- [x] 2.4 Add tests: subwindow hole → exact target; covered + `--since` → NOOP; no Catalog conflict on routine append

## 3. Metadata bootstrap before final plan

- [x] 3.1 Restructure apply flow: Calendar/Session bootstrap → refreshed latest completed day → MainContractMap refresh → final exact plan → Direct → Aggregate → verify
- [x] 3.2 Ensure apply metadata freshness does not depend on non-empty initial plan/windows/targets; remove early-return that skips metadata when publish set is empty before bootstrap
- [x] 3.3 Dry-run: zero RQData/DB/Canonical writes; expose `metadata_watermark` / `metadata_refresh_required` without refreshing remotely
- [x] 3.4 Add tests proving bootstrap-first apply and dry-run network/write silence

## 4. Actual-dominant expected coverage

- [x] 4.1 Build expected actual-dominant contract windows from refreshed MainContractMap rank=1 contiguous ranges
- [x] 4.2 Expand each expected window to seven frequencies and exact-diff Catalog (discover whole missing datasets)
- [x] 4.3 Change catch-up earliest-missing frontier to min(continuous direct/derived, expected AD direct/derived)
- [x] 4.4 Add tests: new rank1 contract with zero Catalog rows discovered; continuous-complete + AD derived-only hole discovered without `--since`

## 5. Exchange calendar/session identity

- [x] 5.1 From G0 samples, define evidence-backed `has_night_session` write rule (no unconditional False)
- [x] 5.2 Change calendar/session writers to materialize actual `Instrument.exchange_code`; ban CNFE hardcode / default
- [x] 5.3 If G0 shows incomplete actual-exchange coverage: land writer first, run gated Metadata Normalization (Calendar/Session/Map only), verify coverage; else proceed
  - G2 applied 2026-06-01..2026-08-08 for active 69: Calendar PASSED (all exchanges max=2026-08-08); MainContractMap PASSED; Sessions first apply wrote 0 rows (get_trading_periods rejects product codes). Writer fixed to parse instrument trading_hours; **sessions re-apply (new intent) PASSED: 253 rows, writes_postgresql=true, writes_canonical=false; active 69 actual-exchange coverage 69/69**. Production CNFE `trading_calendars` (7897) + `trading_sessions` (77) **deleted** under separate intent; non-CNFE counts unchanged.
- [x] 5.4 Remove CNFE calendar fallback, CNFE session fallback, and CZCE hardcoded missing-session fallback after coverage verified; missing metadata fails closed
- [x] 5.5 Add tests for actual-exchange identity and fail-closed missing session behavior

## 6. ORM alignment

- [x] 6.1 Remove `DataProfile`, `ProfileActiveBinding`, `AfterMarketSchedulerCheckpoint` models/imports/tests from `Base.metadata`
- [x] 6.2 Keep `DataDownloadTask` / `MarketDataFile` / `DataQualityReport` wired for IngestRecorder
- [x] 6.3 Verify no Alembic autogenerate suggestion recreates the three retired tables

## 7. Weekly bar semantics (mandatory)

- [ ] 7.1 Freeze weekly watermark as last trading day of latest fully completed ISO week from TradingCalendar
- [ ] 7.2 Freeze actual-dominant 1w ownership as rank1 on that week-last trading day
- [ ] 7.3 Add failing/evidence matrix: continuous×AD × complete/incomplete/rollover/listing-first/holiday-shortened across planner, watermark, provider request, RQData batch
- [ ] 7.4 Fix only the confirmed failing layer; keep Final Gate blocked until 1w converges for JM path locally

## 8. M2 probe diagnostics

- [x] 8.1 Replace bool probe callback with bounded `ProbeOutcome` (`readable` + reason_code set from existing reader/probe errors)
- [x] 8.2 Emit unreadable findings with bounded reason codes; do not add a second correctness DB model
- [x] 8.3 Split map findings: invalid mapping vs `M2_MAPPED_CONTRACT_DATASET_MISSING`
- [x] 8.4 Add tests covering calendar_missing / reader_empty / mapped-dataset-missing classification

## 9. Local Gate G1 + production gates

- [ ] 9.1 Run full local G1 suite for exact window, since-noop, bootstrap-first, AD expected missing, calendar identity, ORM absence, W1 matrix, M2 reasons
- [ ] 9.2 Document deterministic canary selector (per exchange lexicographically smallest active symbol with continuous 1m Catalog + rank1 map)
- [ ] 9.3 After separate intents: G3 JM apply (seven freq continuous + expected AD), G4 multi-exchange canary, G5 69 apply (0 unexpected ERROR/BLOCKED; DataGap classified not auto-erased)
- [ ] 9.4 G6 read-only M2 `finding_count=0`; G7 dry-run with same `--through` as G5 → zero targets/changes and zero remote writes
- [ ] 9.5 Only after six hard conditions, update canonical docs for Data Foundation Frozen and archive this OpenSpec change
