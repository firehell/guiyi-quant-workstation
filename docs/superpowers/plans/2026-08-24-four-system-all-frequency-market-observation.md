# Four-System Active60 All-Frequency Market Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one Market main-chart surface for SuBing, N Structure, JDJ, and HTDY across the official seven frequencies for the current active universe, while preserving every native Formal/Candidate/Strategy identity and keeping all non-native frequencies observation-only.

**Architecture:** Keep every existing native path intact. Add three narrow Historical single-timeframe observation projections for SuBing, N, and JDJ, all driven by `MarketDataService -> ActualDominantResearchSegmentLoader`; HTDY remains browser-local observation rendering. Refactor only the frequency-neutral N/JDJ formula/state-machine seams required to reuse existing rules without reusing native policy or event identities. The Web owns only capability routing, stale-response protection, marker rendering, and preference migration; it never becomes a Strategy adapter.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / `Decimal` / pytest / existing `MarketDataService` and `ActualDominantResearchSegmentLoader`; Vue 3 / TypeScript / Naive UI / Node test runner / Playwright; existing quant-core Indicator Kernel for EMA/MACD/HTDY display mirrors.

**Spec:** `docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md`

## Global Constraints

- Lane 3. Use **Sol + high reasoning** in a new implementation session.
- Before editing, read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, the Spec, and this plan. If active canonical has changed incompatibly since this plan was written, stop and report the conflict instead of adapting silently.
- Create one isolated task worktree/branch from the then-current `develop`; recommended branch: `feature/four-system-all-frequency-observation`. Integrate only to `develop` after the full plan, automated verification, and an independent Review conclusion of **允许集成 develop**. Delete the merged task worktree/branch only after `develop` contains the integration commit.
- Do not modify `main`, any Runtime worktree, release tags, launchd bindings, Alert Scope/transport, production DB/Redis/Canonical data, prospective OOS artifacts, or order paths.
- Official frequencies remain exactly `1m/5m/15m/30m/60m/1d/1w`. No 90m/150m/custom aggregation and no cross-frequency fallback.
- SuBing/N/JDJ observation supports only `actual_dominant`; HTDY keeps the existing `continuous|actual_dominant|contract` display capability. Never auto-switch the user's Market series identity.
- Native identities and semantics are frozen:
  - SuBing Formal Signal: `5m/15m` with existing companion/calibration/same-boundary resolution.
  - N: `n_structure_5m_v1` and existing public facts.
  - JDJ Candidate: `jdj_1m_policy_v1`, 1m + strict-before 5m N context.
  - JDJ Strategy: `jdj_active60_1m_v1`, active-product `actual_dominant + 1m` reference replay.
  - HTDY: original observation-only formula and existing repaint contract.
- Non-native observation versions are exact:
  - `subing_single_tf_observation_v1`
  - `n_structure_single_tf_observation_v1`
  - `jdj_single_tf_observation_v1`
- Non-native observation must never emit or reuse `subing_entry_signal_v1`, `n_structure_5m_v1`, any `jdj_*_1m_candidate_v1`, `jdj_active60_1m_v1`, Strategy actions, PnL/equity, execution quantity, AlertEvent, or OOS/promotion claims.
- No generic Strategy/Opportunity/Observation framework, DB/cache, worker, queue, scheduler, second active-universe list, batch HTTP API, per-product parameter, or per-frequency threshold tuning.
- Every SuBing/N/JDJ Historical observation must recover the true rank1 segment context through `ActualDominantResearchSegmentLoader`; never begin reducer state at the viewport start.
- For SuBing/N/JDJ, future completed bars must not change previously emitted observation identity. HTDY is the explicit exception because its centered XMA is accepted-repainting.
- No active OpenSpec currently owns this Market overlay behavior. Do not create a new OpenSpec merely to archive this task; update an existing active OpenSpec only if implementation proves an existing executable contract actually owns a changed behavior.

---

## File Structure / Responsibility Map

**Shared Historical identity**
- `services/quant-api/app/market_data/actual_dominant_research.py` — existing probe-then-load true-rank1 segment loader; expected unchanged unless a real defect is proven.
- `services/quant-api/app/market_data/domain.py` — existing `BarFrequency`; expected unchanged.

**SuBing observation**
- Create `services/quant-api/app/research/subing/subing_single_tf_observation_service.py` — non-native current-frequency projection only.
- Modify `services/quant-api/app/research/composition.py` — builder for the observation service.
- Modify `services/quant-api/app/api/market_research_overlays.py` — add `/subing/observation/history` beside the native route.
- Modify `services/quant-api/app/schemas/research_overlays.py` — DTOs.
- Create `services/quant-api/tests/research/test_subing_single_tf_observation_service.py`.

**N formula seam + observation**
- Create `services/quant-api/app/research/n_structure/n_structure_formula.py` — frequency-neutral formula rules and segment evaluator.
- Modify `services/quant-api/app/research/n_structure/n_structure_swing.py` — remove internal M5-only validation while preserving frequency in pivot identity.
- Modify `services/quant-api/app/research/n_structure/n_structure_pattern.py` — separate exact native-policy validation from formula evaluation.
- Modify `services/quant-api/app/research/n_structure/n_structure_state.py` only where needed to expose the already-existing formula seam safely.
- Modify `services/quant-api/app/research/n_structure/n_structure_segment.py` — keep exact native wrapper and delegate to formula seam.
- Create `services/quant-api/app/research/n_structure/n_structure_single_tf_observation_service.py`.
- Create `services/quant-api/tests/research/test_n_structure_formula.py`.
- Create `services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py`.

**JDJ setup seam + observation**
- Create `services/quant-api/app/research/jdj/jdj_setup_core.py` — neutral setup facts and explicit `TRADING_DAY|SEGMENT` reset scope.
- Modify `services/quant-api/app/research/jdj/jdj_context.py` — add a single-timeframe context builder without changing the native 1m+5m builder.
- Modify `services/quant-api/app/research/jdj/jdj_trend_follow.py`, `jdj_trend_reentry.py`, and `jdj_key_level_breakout.py` — native wrappers map neutral facts back to the exact current Candidate event types/IDs.
- Keep `services/quant-api/app/research/jdj/jdj_events.py` as the native-event contract; observation must not instantiate these event classes.
- Create `services/quant-api/app/research/jdj/jdj_single_tf_observation_service.py`.
- Create `services/quant-api/tests/research/test_jdj_setup_core.py`.
- Create `services/quant-api/tests/research/test_jdj_single_tf_observation_service.py`.

**HTTP / API regression**
- Modify `services/quant-api/app/research/historical_overlay_api.py` — add N/JDJ observation routes.
- Modify `services/quant-api/tests/test_market_research_overlays_api.py` — native + observation routing/error matrix.
- Modify `services/quant-api/tests/test_research_composition.py` as needed for the three new builders.

**Web capability / routing / presentation**
- Modify `apps/quant-web/src/types/market.ts` — final overlay IDs and observation DTOs.
- Modify `apps/quant-web/src/utils/mainIndicators.ts` — preference V4 and `resolveResearchOverlayMode`.
- Modify `apps/quant-web/src/api/market.ts` — three new observation fetchers.
- Modify `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts` — mode-based source-specific fetch routing; preserve generation/dedupe/live-skip behavior.
- Modify `apps/quant-web/src/utils/historicalResearchMarkers.ts` — observation marker mapping.
- Modify `apps/quant-web/src/composables/useSubingObservation.ts` or its caller only enough to ensure current `/subing` snapshot/lifecycle runs for native 5m/15m mode, not for non-native main-chart observation.
- Modify `apps/quant-web/src/pages/market/chart.vue` — single JDJ choice, native/non-native status tag, correct source wiring.
- Modify `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue` only if final five-choice presentation needs an explicit prop/label adjustment.
- Modify `apps/quant-web/tests/mainIndicators.test.ts`, `historicalResearchMarkers.test.ts`, `subingResearch.test.ts`, `indicators.test.ts`.
- Create `apps/quant-web/tests/overlayObservationMarkers.test.ts` if marker assertions would otherwise overload the existing historical marker test.
- Modify `apps/quant-web/e2e/market-research.spec.mjs`.

**Canonical closeout**
- Modify `PROJECT_SOURCE.md`, `DECISIONS.md`, `STATUS.md` only after code and verification are true.
- Modify `TESTING.md` only if a stable project-native verification command introduced by this feature is worth retaining; do not copy stage-one one-off smoke recovery machinery.

---

## Task 1: Freeze the Final Web Capability Contract and Preference V4

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`

**Interfaces:**
- Final active `ResearchOverlayId`: `none|subing|n_structure|jdj|htdy`.
- Legacy preference input may still contain `jdj_strategy`, but active UI/state may not.
- `resolveResearchOverlayMode(overlay, seriesKind, frequency)` returns exactly:
  `none | subing_native | subing_single_tf_observation | n_native | n_single_tf_observation | jdj_strategy_native | jdj_single_tf_observation | htdy_local_observation | unsupported`.

- [ ] **Step 1: Write failing tests for the final capability matrix and V4 migration**

In `mainIndicators.test.ts`, replace the V3-separate-JDJ assertions with tests that require:

```ts
assert.deepEqual(defaultMainChartPreferences(), {
  version: 4,
  selectedOverlay: 'subing',
  optionalEmaIndicators: [],
  period: null,
  realtimeFollow: false,
})

assert.equal(resolveResearchOverlayMode('jdj', 'actual_dominant', '1m'), 'jdj_strategy_native')
assert.equal(resolveResearchOverlayMode('jdj', 'actual_dominant', '30m'), 'jdj_single_tf_observation')
assert.equal(resolveResearchOverlayMode('subing', 'actual_dominant', '5m'), 'subing_native')
assert.equal(resolveResearchOverlayMode('subing', 'actual_dominant', '1d'), 'subing_single_tf_observation')
assert.equal(resolveResearchOverlayMode('n_structure', 'actual_dominant', '5m'), 'n_native')
assert.equal(resolveResearchOverlayMode('n_structure', 'actual_dominant', '60m'), 'n_single_tf_observation')
assert.equal(resolveResearchOverlayMode('htdy', 'contract', '1w'), 'htdy_local_observation')
assert.equal(resolveResearchOverlayMode('jdj', 'continuous', '1m'), 'unsupported')
```

Also construct a storage fixture under legacy key `guiyi.market.chart.preferences.v3` with `selectedOverlay: 'jdj_strategy'` and assert it loads as V4 `jdj` while preserving optional EMA, period, and realtimeFollow.

- [ ] **Step 2: Run the focused Web test and verify failure**

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts
```

Expected: FAIL because V4, the final overlay union, and the mode resolver do not exist yet.

- [ ] **Step 3: Implement the smallest capability/persistence change**

In `market.ts`:

```ts
export type ResearchOverlayId = 'none' | 'subing' | 'n_structure' | 'jdj' | 'htdy'
export type ResearchOverlayMode =
  | 'none'
  | 'subing_native'
  | 'subing_single_tf_observation'
  | 'n_native'
  | 'n_single_tf_observation'
  | 'jdj_strategy_native'
  | 'jdj_single_tf_observation'
  | 'htdy_local_observation'
  | 'unsupported'
```

Remove `jdj_strategy` from active overlay definitions. Do not delete any backend Candidate/Strategy route.

In `mainIndicators.ts`:
- change the preference key/version to V4;
- keep V3 as a legacy read key;
- map legacy `jdj_strategy -> jdj` and `jdj -> jdj`;
- make SuBing/N/JDJ/HTDY active definitions available across the seven official frequencies subject to series-kind rules;
- implement the mode resolver as an explicit matrix, not a generic next-timeframe algorithm.

- [ ] **Step 4: Run tests and TypeScript build**

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts
pnpm --dir apps/quant-web build
```

Expected: PASS. If removing `jdj_strategy` exposes compile errors elsewhere, update only type-safe routing references required to compile; do not implement observation formulas in TypeScript.

- [ ] **Step 5: Commit**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/mainIndicators.test.ts
git commit -m "refactor(web): freeze all-frequency overlay modes"
```

---

## Task 2: Add SuBing Single-Timeframe Observation Without Widening Formal Signal Semantics

**Files:**
- Create: `services/quant-api/app/research/subing/subing_single_tf_observation_service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Create: `services/quant-api/tests/research/test_subing_single_tf_observation_service.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/test_research_composition.py`
- Regression-read: `services/quant-api/app/market_data/subing_research.py`

**Interfaces:**
- Version: `subing_single_tf_observation_v1`.
- Allowed frequencies: `{1m,30m,60m,1d,1w}` only.
- Reuse `calculate_subing_factor_series`; never call `evaluate_subing_signal` or `resolve_subing_matched_signal`.
- Public event facts only: cross, zero-axis distance, close/EMA21/price-side, current volume, rank1 segment identity.

- [ ] **Step 1: Add failing service tests**

Cover all of the following with deterministic `CanonicalBar` fixtures and a fake segment loader:

```text
1m/30m/60m/1d/1w are admitted
5m/15m are rejected by this observation request
outside-active symbol is rejected before loader access
only selected frequency is requested from the loader
one physical segment never inherits another segment's Factor state
only golden/dead cross snapshots create events
NONE cross creates no event
no ready Factor inside requested window -> insufficient_data
ready Factors but no cross -> ready + events=[]
event identity contains observation version + symbol + contract + segment start + frequency
full projection restricted to prefix == prefix projection
```

Assert the event object has no `direction`, calibration result, slope threshold, previous-volume ratio, Formal condition, or signal status field.

- [ ] **Step 2: Run and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_single_tf_observation_service.py
```

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the service**

Create immutable request/status/event/result contracts. The service constructor receives:

```python
SubingSingleTfObservationService(
    segment_loader,
    *,
    products: tuple[str, ...],
)
```

`history()` must:
1. validate `actual_dominant`, active product, allowed non-native frequency, and date window;
2. call the shared loader with exactly `(request.frequency,)`;
3. partition bars by the returned `ResolvedContractSegment` identities;
4. call `calculate_subing_factor_series(..., timeframe=request.frequency, latest_bar_source="canonical")` separately per segment;
5. filter projection to `since..through`;
6. emit events only when `macd_cross` is `GOLDEN` or `DEAD`;
7. return `insufficient_data` only when no requested-window Factor snapshot is ready; otherwise `ready`, including an empty event list.

Do not change `_INTRADAY_TIMEFRAMES` or the existing Formal evaluator.

- [ ] **Step 4: Add DTO/builder/HTTP tests before HTTP implementation**

Extend `test_market_research_overlays_api.py` with expected route behavior:

```text
GET /api/v1/market/research/subing/observation/history
actual_dominant + 30m -> 200
5m -> 422 INVALID_SUBING_SINGLE_TF_OBSERVATION_REQUEST
continuous -> 422 same code
active-universe/source/segment failure -> 409 typed code
```

Response metadata must be exact booleans:

```json
{
  "observation_only": true,
  "formal_evidence": false,
  "oos_eligible": false,
  "alert_eligible": false,
  "auto_order": false
}
```

- [ ] **Step 5: Implement builder, DTOs, and route**

Use exact error codes:
- `INVALID_SUBING_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `SUBING_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `SUBING_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- existing `ACTIVE_UNIVERSE_INVALID` -> 409

Keep the native `/subing/history` route and its error contract unchanged.

- [ ] **Step 6: Run SuBing native + observation regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/data_foundation/test_subing_historical_signal_service.py \
  services/quant-api/tests/research/test_subing_single_tf_observation_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
```

Expected: PASS, with existing 5m/15m formal results unchanged.

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/subing/subing_single_tf_observation_service.py \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/tests/research/test_subing_single_tf_observation_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
git commit -m "feat(research): add SuBing single-timeframe observation"
```

---

## Task 3: Extract the Frequency-Neutral N Formula Seam and Prove 5m Native Parity

**Files:**
- Create: `services/quant-api/app/research/n_structure/n_structure_formula.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_swing.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_pattern.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_state.py` only if needed
- Modify: `services/quant-api/app/research/n_structure/n_structure_segment.py`
- Create: `services/quant-api/tests/research/test_n_structure_formula.py`
- Regression: existing N Swing/Pattern/State/Service tests

**Interfaces:**
- `n_structure_5m_v1` remains the only Formal N policy.
- `NStructureFormulaRules` contains only the frozen Swing/Pattern/Structure rules required for formula evaluation; it excludes source timeframe and outcome horizons.
- `evaluate_n_structure_formula_segment(..., source_timeframe, rules)` accepts official Market frequencies and returns the same `NStructureSegmentTrace` shape.
- `evaluate_n_structure_segment(..., policy)` remains the native exact-policy wrapper and still only accepts the exact 5m policy.

- [ ] **Step 1: Add a pre-refactor 5m parity fixture/test before changing production code**

Use a deterministic 5m bar sequence already capable of producing pivots, completed N patterns, and structure transitions. Serialize only stable formula facts:

```text
pivot_id/kind/pivot_time/confirmed_at/price/epoch
completed n_id/direction/completed_at/completion_level/range band
structure snapshot observed_at/epoch/kind/defense pivot id/count
transition IDs/reasons
```

Store the fixture at:
`services/quant-api/tests/research/fixtures/n_structure_5m_formula_golden.json`.

The test must call current `evaluate_n_structure_segment(..., load_n_structure_policy())` and compare the normalized facts exactly. Do not add an update-golden flag.

- [ ] **Step 2: Run the golden test twice and commit the test-only freeze**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: PASS twice. Commit only the fixture/test before touching N production code:

```bash
git add services/quant-api/tests/research/fixtures/n_structure_5m_formula_golden.json \
  services/quant-api/tests/research/test_n_structure_formula.py
git commit -m "test(research): freeze N structure 5m formula parity"
```

- [ ] **Step 3: Extend the test with failing non-5m formula-seam cases**

Add tests requiring the desired internal seam to run the same deterministic bars at `15m`, `60m`, and `1d`, with every pivot carrying the selected `source_timeframe` and IDs remaining frequency-distinct. Also assert the native wrapper still rejects a synthetic non-exact policy.

- [ ] **Step 4: Run and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: FAIL because `NSwingPivot` and Swing/Pattern validation are still M5-only and the formula seam does not exist.

- [ ] **Step 5: Implement `NStructureFormulaRules` and the formula segment evaluator**

`exact_n_structure_formula_rules(load_n_structure_policy())` must accept only the existing exact policy and mechanically copy these frozen rule groups: Swing breach/equality/outside/inside/tie, N completion/same-boundary/break semantics, range-band semantics, and structure semantics. Do not copy `source_timeframe` or `outcome`.

Refactor `NSwingPivot` and reducer validation so any `BarFrequency` can be represented internally while pivot IDs continue to include `source_timeframe.value`. Refactor Pattern/State internal seams to validate formula rules/facts rather than requiring the exact 5m policy. Keep all public native entry points exact-policy-gated.

`evaluate_n_structure_segment()` must become a thin wrapper:

```python
policy = require exact n_structure_5m_v1
evaluate_n_structure_formula_segment(
    bars,
    source_timeframe=BarFrequency.M5,
    rules=exact_n_structure_formula_rules(policy),
    ...,
)
```

No rule value may change.

- [ ] **Step 6: Run native and formula regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: PASS and the frozen 5m golden remains byte-for-byte unchanged.

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/n_structure/n_structure_formula.py \
  services/quant-api/app/research/n_structure/n_structure_swing.py \
  services/quant-api/app/research/n_structure/n_structure_pattern.py \
  services/quant-api/app/research/n_structure/n_structure_state.py \
  services/quant-api/app/research/n_structure/n_structure_segment.py \
  services/quant-api/tests/research/test_n_structure_formula.py
git commit -m "refactor(research): isolate N structure formula rules"
```

---

## Task 4: Add N Single-Timeframe Historical Observation

**Files:**
- Create: `services/quant-api/app/research/n_structure/n_structure_single_tf_observation_service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Create: `services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/test_research_composition.py`

**Interfaces:**
- Version: `n_structure_single_tf_observation_v1`.
- Allowed frequencies: `{1m,15m,30m,60m,1d,1w}`.
- Projection contains N completion observation events only; no outcome horizons, rank, score, or Candidate/OOS result.

- [ ] **Step 1: Add failing service tests**

Cover:

```text
allowed non-native frequency matrix
5m rejected by observation request
active admission before loader access
single selected frequency load
true rank1 segment reset and no cross-contract memory
completion emitted only at completed_at/confirmation boundary
ready + events=[] when source is valid but no N completion
observation event ID isolated from n_structure_5m_v1 and contains frequency
full/prefix invariance
prepend starting earlier does not change later observation IDs
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py
```

- [ ] **Step 3: Implement service using only the formula seam**

The service loads exactly `(request.frequency,)`, partitions by returned true segments, calls `evaluate_n_structure_formula_segment`, and projects patterns whose `completed_at` trading day falls inside `since..through`.

Observation event ID must be generated in the observation service namespace, for example by canonical joining:

```text
n_structure_single_tf_observation_v1|symbol|contract|segment_start|frequency|formula_n_id|completed_at
```

Do not expose the formula's internal `n_id` as the public event ID.

- [ ] **Step 4: Add DTO/builder/route and exact HTTP errors**

Use:
- `INVALID_N_STRUCTURE_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `N_STRUCTURE_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `N_STRUCTURE_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- `ACTIVE_UNIVERSE_INVALID` -> 409

Route:
`GET /api/v1/market/research/n-structure/observation/history`.

- [ ] **Step 5: Run native + observation regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/research/n_structure/n_structure_single_tf_observation_service.py \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/research/historical_overlay_api.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
git commit -m "feat(research): add N single-timeframe observation"
```

---

## Task 5: Extract Neutral JDJ Setup Facts While Preserving Every Native Candidate Event

**Files:**
- Create: `services/quant-api/app/research/jdj/jdj_setup_core.py`
- Modify: `services/quant-api/app/research/jdj/jdj_trend_follow.py`
- Modify: `services/quant-api/app/research/jdj/jdj_trend_reentry.py`
- Modify: `services/quant-api/app/research/jdj/jdj_key_level_breakout.py`
- Create: `services/quant-api/tests/research/test_jdj_setup_core.py`
- Regression: existing three reducer tests + JDJ Strategy parity tests

**Interfaces:**
- Core produces neutral setup facts, not `Jdj*TriggerEvent`.
- `JdjSetupStateScope` is exactly `TRADING_DAY` or `SEGMENT`.
- Native wrappers call core with `TRADING_DAY` and map neutral facts to the current event constructors/IDs without semantic changes.

- [ ] **Step 1: Run and record the native reducer baseline before editing**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Expected: PASS. If baseline fails, stop before refactoring.

- [ ] **Step 2: Add failing neutral-core tests**

For each setup family, use existing successful fixtures and require a neutral fact with the same direction, observed boundary, trigger level, and provenance boundaries as the formal event. Add reset-scope tests:

```text
TRADING_DAY: armed state cannot cross trading_day
SEGMENT: same fixture may continue across trading_day while contract/segment identity is unchanged
both scopes: segment change resets state
```

For key-level breakout, neutral core accepts an arbitrary-frequency N pivot fact; it must not parse or require the literal `5m` string in a pivot ID.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_setup_core.py
```

- [ ] **Step 4: Implement `jdj_setup_core.py` and convert native reducers into wrappers**

Move only the state-machine decisions into neutral reducers. Keep current `jdj_events.py` unchanged as the formal/native event contract. Each existing public reducer must:
1. validate native context as today;
2. call the neutral core with `TRADING_DAY`;
3. construct the exact existing `JdjTrendFollowTriggerEvent`, `JdjTrendReentryTriggerEvent`, or `JdjKeyLevelBreakoutTriggerEvent` using the current canonical event-ID helpers.

Do not rename Candidate IDs, source kinds, or formal event kinds.

- [ ] **Step 5: Run exact native parity and core tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_setup_core.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Any native event or Strategy action drift blocks the task.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/research/jdj/jdj_setup_core.py \
  services/quant-api/app/research/jdj/jdj_trend_follow.py \
  services/quant-api/app/research/jdj/jdj_trend_reentry.py \
  services/quant-api/app/research/jdj/jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_setup_core.py
git commit -m "refactor(research): isolate JDJ setup facts"
```

---

## Task 6: Build JDJ Single-Timeframe Context and Historical Observation

**Files:**
- Modify: `services/quant-api/app/research/jdj/jdj_context.py`
- Create: `services/quant-api/app/research/jdj/jdj_single_tf_observation_service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Create: `services/quant-api/tests/research/test_jdj_single_tf_observation_service.py`
- Modify: `services/quant-api/tests/test_jdj_context.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/test_research_composition.py`

**Interfaces:**
- Version: `jdj_single_tf_observation_v1`.
- Allowed frequencies: `{5m,15m,30m,60m,1d,1w}`.
- Selected frequency drives EMA20, N formula context, and setup triggers.
- `5m..60m` uses `TRADING_DAY`; `1d/1w` uses `SEGMENT`.
- Strict-before means bar `i` can consume only N snapshots/pivots whose evidence boundary is `<= bars[i-1].bar_end` within its active reset scope.

- [ ] **Step 1: Add failing single-timeframe context tests**

Extend `test_jdj_context.py` or isolate focused tests to require:

```text
EMA20 calculated from selected-frequency close series
N formula called with the same selected frequency
current bar cannot see an N snapshot/pivot confirmed on that same bar
next bar can see the fact
5m..60m first bar of each trading day has no inherited N context
1d/1w keeps prior-bar context across trading days within the same segment
segment boundary clears all context for both scopes
future suffix does not change previous contexts
```

Keep every current `build_jdj_context_series(1m,5m)` test unchanged and green.

- [ ] **Step 2: Implement `build_jdj_single_tf_context_series` minimally**

The new builder must not modify `jdj_1m_policy_v1`. It receives selected-frequency bars, the exact native JDJ policy only as the source of EMA/setup rule constants, `NStructureFormulaRules`, source frequency, segment identity, and reset scope. It uses the N formula seam once per segment and projects only strict-before facts.

Do not change the native builder's public signature.

- [ ] **Step 3: Add failing observation-service tests**

Cover:

```text
allowed non-native frequency matrix and 1m rejection
active admission before loader
only selected frequency loaded
three setup families projected as observation events
no Strategy action/execution fields
5m..60m trading-day reset behavior
1d/1w segment-continuous behavior
frequency-isolated event IDs
strict-before same-boundary poison case
full/prefix invariance
rank1 segment rollover reset
insufficient_data only when EMA20 never becomes ready in requested window; otherwise ready + empty allowed
```

- [ ] **Step 4: Implement service and isolated event identity**

The service must call neutral setup reducers directly, never formal Candidate reducers. Public ID must use the observation namespace, for example:

```text
jdj_single_tf_observation_v1|symbol|contract|segment_start|frequency|setup_kind|direction|observed_at|trigger_level|source-fact-key
```

Public output contains only:
`event_id, observation_version, frequency, setup_kind, direction, observed_at, trading_day, contract, segment_start_trading_day, trigger_level` plus the minimum non-execution source fact needed to explain the marker.

- [ ] **Step 5: Add DTO/builder/route and exact errors**

Route:
`GET /api/v1/market/research/jdj/observation/history`.

Use:
- `INVALID_JDJ_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `JDJ_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `JDJ_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- `JDJ_SINGLE_TF_OBSERVATION_CONTEXT_INVALID` -> 409
- `ACTIVE_UNIVERSE_INVALID` -> 409

Metadata includes the five common false/true eligibility flags plus `single_timeframe=true`.

- [ ] **Step 6: Run JDJ native + observation regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/research/test_jdj_setup_core.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_single_tf_observation_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
```

Expected: PASS. Native JDJ 1m Strategy parity is non-negotiable.

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/jdj/jdj_context.py \
  services/quant-api/app/research/jdj/jdj_single_tf_observation_service.py \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/research/historical_overlay_api.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/tests/research/test_jdj_single_tf_observation_service.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
git commit -m "feat(research): add JDJ single-timeframe observation"
```

---

## Task 7: Wire Source-Specific Observation Modes Into the Market Web

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/src/composables/useSubingObservation.ts` or `chart.vue` gating
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue` if needed
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Create: `apps/quant-web/tests/overlayObservationMarkers.test.ts` if useful
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- One JDJ UI choice only.
- `jdj + 1m` -> existing Strategy endpoint.
- `jdj + non-1m` -> new JDJ observation endpoint.
- SuBing 5/15 -> native current/lifecycle + native Historical Formal marker path; other TF -> Historical observation only.
- N 5m -> native; other TF -> Historical observation.
- Historical observation never refreshes on `live` mutation.

- [ ] **Step 1: Extend marker/composable tests before wiring production code**

Add dependency mocks for the three observation fetchers and require mode routing:

```text
subing_native -> /subing/history
subing_single_tf_observation -> /subing/observation/history
n_native -> /n-structure/history
n_single_tf_observation -> /n-structure/observation/history
jdj_strategy_native -> /jdj-strategy/history
jdj_single_tf_observation -> /jdj/observation/history
htdy_local_observation/none/unsupported -> no Historical HTTP fetch
```

Retain all existing identity checks, generation invalidation, event-ID dedupe, confirmed-range intersection, prepend behavior, and `live` early-return.

- [ ] **Step 2: Run focused Web tests and verify failure**

```bash
node --test \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/subingResearch.test.ts
```

- [ ] **Step 3: Add Web DTOs, API fetchers, and marker mappers**

Define exact response types matching backend metadata/status/event fields. Marker rules:

**SuBing observation**
- label `MACD金叉` or `MACD死叉`;
- tooltip contains only cross, zero-axis distance, EMA21 side, current volume;
- no 买入/卖出/强/弱 wording.

**N observation**
- use the same visual direction vocabulary as the existing N marker but tooltip must say `单周期观察` and must not reuse a native event ID.

**JDJ observation**
- label setup family + 多/空; tooltip says `单周期观察`;
- never label ENTRY/ADD/REDUCE/EXIT.

- [ ] **Step 4: Refactor `useHistoricalResearchMarkers` to mode routing**

Replace static `historicalSource` branching with `resolveResearchOverlayMode`. Do not create a universal response adapter; each source-specific loader validates its own request/response identity and then returns the existing internal `{eventId, marker}` mechanical shape.

- [ ] **Step 5: Gate the current SuBing snapshot/lifecycle to native 5m/15m mode**

Do not remove backend `/market/research/subing` 1d research capability just because main-chart 1d becomes non-native observation. Prefer passing an explicit native-mode `enabled` input to `useSubingObservation` or gating calls in `chart.vue`, rather than globally redefining unrelated SuBing research frequency helpers.

- [ ] **Step 6: Finish chart UX and one-JDJ choice**

In `chart.vue`/toolbar:
- final choices are exactly `无｜苏冰｜N字｜日进斗金｜火天大有`;
- JDJ 1m shows EMA20 + Strategy reference markers;
- JDJ non-1m shows EMA20 + observation setup markers;
- SuBing shows EMA21 on all supported display frequencies, while non-native markers are backend observation facts;
- show a single lightweight state tag:
  `原生周期`, `单周期观察`, `原生策略`, or `原始观察周期` as defined by the Spec;
- unsupported series kind shows unavailable without changing series identity.

- [ ] **Step 7: Extend E2E route interception**

Cover at least:

```text
JDJ 1m calls jdj-strategy/history and does not call jdj/observation/history
JDJ 30m calls jdj/observation/history
SuBing 5m uses native route/current snapshot
SuBing 30m uses observation route and does not fetch native current snapshot
N 5m uses native route
N 60m uses observation route
rapid overlay/frequency switch ignores stale earlier response
legacy jdj_strategy preference renders JDJ single choice
```

- [ ] **Step 8: Run focused Web test/build/E2E**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  apps/quant-web/e2e/market-research.spec.mjs
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/composables/useHistoricalResearchMarkers.ts \
  apps/quant-web/src/utils/historicalResearchMarkers.ts \
  apps/quant-web/src/composables/useSubingObservation.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/tests/overlayObservationMarkers.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): unify four-system all-frequency observation"
```

If `overlayObservationMarkers.test.ts` or a toolbar/composable path is not modified, omit that exact path from `git add`; never use `git add -A`.

---

## Task 8: Expand HTDY Display Capability to All Seven Frequencies Without Changing Its Formula or Alert Identity

**Files:**
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Read-only regression: `packages/quant-core/guiyi_quant/indicators/htdy_original.py`
- Read-only regression: `services/quant-api/tests/test_htdy_production_kernel_policy.py`
- Read-only regression: `apps/quant-web/tests/htdyGoldenSample.test.ts`, `htdyStep1Golden.test.ts`

- [ ] **Step 1: Add failing capability tests**

Assert HTDY is selectable for every official frequency and for each existing series kind while its metadata remains `observation_only`, `future_looking=true`, `repainting_accepted=true`, and `historical_backtest_allowed=false`.

- [ ] **Step 2: Run RED**

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts apps/quant-web/tests/indicators.test.ts
```

Expected: FAIL if the capability is still 15m-only.

- [ ] **Step 3: Change only Web capability/presentation**

Do not touch `compute_htdy_original`, XMA windows, future horizon, 27-bar repaint scan zone, or Alert code/scope. The selected Market frequency's existing bars feed the same browser-local HTDY display mirror.

- [ ] **Step 4: Run HTDY cross-language golden regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py

node --test \
  apps/quant-web/tests/indicators.test.ts \
  apps/quant-web/tests/htdyGoldenSample.test.ts \
  apps/quant-web/tests/htdyStep1Golden.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts
```

Expected: PASS; no golden updates are allowed to make this task pass.

- [ ] **Step 5: Commit**

```bash
git add apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/indicators.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): expose HTDY across market frequencies"
```

---

## Task 9: Run the Full Native-Parity, Causal, API, and Web Verification Matrix

**Files:** no production changes unless a verified defect is found; fixes remain in the same task branch and rerun the affected earlier task tests.

- [ ] **Step 1: Run focused observation/native suites together**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/data_foundation/test_subing_historical_signal_service.py \
  services/quant-api/tests/research/test_subing_single_tf_observation_service.py \
  services/quant-api/tests/research/test_n_structure_formula.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/research/test_jdj_setup_core.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_single_tf_observation_service.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/test_htdy_production_kernel_policy.py
```

Expected: PASS.

- [ ] **Step 2: Run full backend and engineering validation**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api mypy services/quant-api/app
```

Expected: PASS.

- [ ] **Step 3: Run full Web validation**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  apps/quant-web/e2e/market-research.spec.mjs
```

Expected: PASS.

- [ ] **Step 4: Run secret scan**

```bash
python3 scripts/engineering/secret_scan.py
```

Expected: PASS with no secret values printed.

- [ ] **Step 5: Inspect scope diff**

```bash
git diff --stat develop...HEAD
git diff --name-only develop...HEAD
```

Expected: only files serving the approved stage-two scope. No Alert migrations/runtime configs/RQAlpha changes/new DB models/new policy JSON/per-product configs.

---

## Task 10: Run a Bounded Active60 Read-Only Capability Smoke

**Files:** no repository artifact is created by the smoke.

**Purpose:** Empirically cover the two independent dimensions without doing a 60×all-frequency×all-system batch: active60 product admission is checked with one representative non-native frequency per system; all-frequency routing is checked on JM. Unit/API/Web tests remain the authority for the complete frequency matrix.

**Fixed Historical window:** `2026-08-18..2026-08-20` because the stage-one capability smoke already established confirmed active60 Canonical availability there. Reusing the dates does **not** reuse stage-one evidence or its one-off environment/recovery procedure.

- [ ] **Step 1: Ensure the implementation environment already has the project read-only DB/Catalog configuration**

Do not add or source a new secret-handling script for this task. From `services/quant-api`, verify only that the application can construct a read-only session without printing configuration values:

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from app.db.session import SessionLocal
session = SessionLocal()
try:
    session.execute(__import__('sqlalchemy').text('SELECT 1'))
    print('read_only_session=ready')
finally:
    session.close()
PY
cd ../..
```

Expected: `read_only_session=ready`. If it fails, stop the empirical smoke and report environment unavailable; do not invent credentials or copy stage-one environment-recovery commands.

- [ ] **Step 2: Run representative active60 admission smoke**

From `services/quant-api`, run an inline Python probe using `load_active_products()`, one SQLAlchemy session, and the three new builders. For every active product call:

```text
SuBing observation: 30m
N observation:      60m
JDJ observation:    30m
window: 2026-08-18..2026-08-20
```

Classify each call as `ready`, `insufficient_data`, `typed_unavailable`, or `command_failed`; print only product/system/status/error-code, never config/SQL/stack traces. The summary assertion is:

```text
active_products == 60
unsupported == 0
identity_drift == 0
silent_fallback == 0
command_failed == 0
```

`insufficient_data` is allowed. A typed source/segment unavailable result must be listed, not skipped.

- [ ] **Step 3: Run JM all-frequency routing smoke**

For `jm` and the same window, call every non-native frequency allowed by each observation service:

```text
SuBing: 1m,30m,60m,1d,1w
N:      1m,15m,30m,60m,1d,1w
JDJ:    5m,15m,30m,60m,1d,1w
```

Also call the native routes once:

```text
SuBing 5m and 15m
N 5m
JDJ Strategy 1m
```

Assertions:
- every response/request identity echoes the exact requested frequency and `actual_dominant`;
- native calls never route through observation service;
- observation calls never return a native identity or Strategy action;
- no cross-frequency fallback occurs.

- [ ] **Step 4: Do not persist smoke output**

Do not add a report, cache, DB row, JSON artifact, or repository batch script. The implementation completion note may report aggregate counts only.

---

## Task 11: Canonical Closeout, Independent Review, and Develop Integration

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `STATUS.md`
- Modify: `TESTING.md` only if stable project-native commands changed
- Do not create an active OpenSpec unless an existing active spec was actually modified by the implementation.

- [ ] **Step 1: Update stable product/canonical wording only after all tests and smoke are true**

`PROJECT_SOURCE.md` must state:
- final main-chart choices `无｜苏冰｜N字｜日进斗金｜火天大有`;
- official seven-frequency observation capability;
- native vs non-native single-TF observation boundary;
- JDJ 1m choice routes to the existing Strategy reference replay while non-1m is setup observation;
- SuBing/N/JDJ non-native observations are confirmed-Historical-only and `actual_dominant` only;
- no generic Strategy adapter, persistence, Alert/OOS/Runtime/order connection.

`DECISIONS.md` must add one durable decision: non-native single-timeframe observation may reuse formula/state-machine rules through narrow seams but never changes or inherits Formal/Candidate/Strategy/OOS/Alert identity.

`STATUS.md` records only observed completion facts: implementation head, relevant automated test results, active60 read-only smoke summary, and the fact that release/Runtime/Alert Scope remain unchanged. Do not declare release-ready or Runtime-ready.

- [ ] **Step 2: Run documentation/reference validation and secret scan**

```bash
python3 scripts/engineering/secret_scan.py
git diff --check
git grep -n "日进斗金策略" -- PROJECT_SOURCE.md apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e || true
git grep -n "jdj_strategy" -- apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e || true
```

Expected:
- secret scan and `git diff --check` pass;
- any remaining `日进斗金策略`/`jdj_strategy` reference is either explicit legacy preference migration or backend route naming, not an active Market UI choice.

- [ ] **Step 3: Commit closeout docs on the task branch**

```bash
git add PROJECT_SOURCE.md DECISIONS.md STATUS.md
git add TESTING.md  # only if it actually changed
git commit -m "docs: record stage2 market observation completion"
```

- [ ] **Step 4: Open a PR to `develop` for independent Lane 3 Review**

The PR summary must identify:
- native parity surfaces;
- N formula seam and exact 5m wrapper;
- JDJ neutral setup seam and exact native wrapper;
- strict-before + intraday/segment reset split;
- observation identity isolation;
- Web one-JDJ choice and V4 migration;
- tests and active60 smoke results;
- explicit untouched surfaces: Alert, Runtime, main/tag/release, DB/Redis/Canonical writes, OOS, RQAlpha, orders.

- [ ] **Step 5: Independent reviewer must inspect code, not only the PR summary**

Reviewer must return one of the project conclusions. Integration requires exactly:

```text
允许集成 develop
```

If the result is `要求修正后再集成` or `阻塞`, fix in the same task branch, rerun affected tests plus Task 9 verification, and request review again.

- [ ] **Step 6: Merge to `develop` only after Review approval**

Use the repository's normal merge method. Do not merge to `main`, create a tag, or switch Runtime.

After merge, verify the merged task commit is an ancestor of current `develop`, then delete the merged task worktree and branch. Do not touch the main or Runtime worktrees.

---

## Completion Checklist

The task is complete only if all are true:

- [ ] Market active choices are exactly `none/subing/n_structure/jdj/htdy` and UI labels are `无｜苏冰｜N字｜日进斗金｜火天大有`.
- [ ] V3 `jdj_strategy` preference migrates to V4 `jdj` without losing period/EMA/realtimeFollow.
- [ ] SuBing 5m/15m Formal facts are unchanged; non-native SuBing exposes only EMA side, MACD cross/zero distance, and current volume.
- [ ] N 5m native golden is unchanged; non-native N uses the same formula rules with frequency-isolated observation IDs and no outcome/OOS semantics.
- [ ] JDJ Candidate/Strategy 1m tests and stage-one JM parity are unchanged.
- [ ] JDJ non-native uses same-frequency EMA20+N+setup facts only, strict-before; 5m..60m resets by trading day, 1d/1w by segment.
- [ ] JDJ non-native emits setup observations only, never Strategy actions/execution fields.
- [ ] HTDY is selectable on all seven frequencies while its formula/golden/repaint metadata and Alert identity are unchanged.
- [ ] SuBing/N/JDJ observation uses the shared true-rank1 segment loader and has prefix-invariant confirmed-history facts.
- [ ] Unsupported series/frequency never silently falls back.
- [ ] Full backend, engineering, Ruff, Mypy, Web unit, build, focused Playwright, and secret scan pass.
- [ ] Active60 representative smoke has 60 admitted products and zero unsupported/identity-drift/silent-fallback/command-failed results; JM all-frequency routing smoke passes.
- [ ] No new DB/cache/worker/queue/scheduler/batch API/policy-per-frequency/per-product override was added.
- [ ] Alert Scope/transport, Runtime, release/tag/main, production writes, OOS, RQAlpha sidecar, and orders remain untouched.
- [ ] Independent Lane 3 Review says `允许集成 develop`, and only then is the task integrated into `develop` and its temporary task worktree/branch cleaned.
