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
- No active OpenSpec currently owns this Market overlay behavior. Do not create a new OpenSpec for this task.

---

## File Structure / Responsibility Map

**Shared Historical identity**
- Read: `services/quant-api/app/market_data/actual_dominant_research.py` — existing probe-then-load true-rank1 segment loader; keep unchanged.
- Read: `services/quant-api/app/market_data/domain.py` — existing seven-value `BarFrequency`; keep unchanged.

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
- Modify `services/quant-api/app/research/n_structure/n_structure_segment.py` — keep exact native wrapper and delegate to formula seam.
- Keep `services/quant-api/app/research/n_structure/n_structure_state.py` unchanged; reuse its existing `_evaluate_n_market_structure_from_exact_facts` formula function.
- Create `services/quant-api/app/research/n_structure/n_structure_single_tf_observation_service.py`.
- Create `services/quant-api/tests/research/test_n_structure_formula.py` and golden fixture.
- Create `services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py`.

**JDJ setup seam + observation**
- Create `services/quant-api/app/research/jdj/jdj_setup_core.py` — neutral setup facts and explicit `TRADING_DAY|SEGMENT` reset scope.
- Modify `services/quant-api/app/research/jdj/jdj_context.py` — add a single-timeframe context builder without changing the native 1m+5m builder.
- Modify `services/quant-api/app/research/jdj/jdj_trend_follow.py`, `jdj_trend_reentry.py`, and `jdj_key_level_breakout.py` — native wrappers map neutral facts back to the exact current Candidate event types/IDs.
- Keep `services/quant-api/app/research/jdj/jdj_events.py` unchanged as the native-event contract; observation never instantiates those event classes.
- Create `services/quant-api/app/research/jdj/jdj_single_tf_observation_service.py`.
- Create `services/quant-api/tests/research/test_jdj_setup_core.py`.
- Create `services/quant-api/tests/research/test_jdj_single_tf_observation_service.py`.

**HTTP / API regression**
- Modify `services/quant-api/app/research/historical_overlay_api.py` — add N/JDJ observation routes.
- Modify `services/quant-api/tests/test_market_research_overlays_api.py` — native + observation routing/error matrix.
- Modify `services/quant-api/tests/test_research_composition.py` — exact builders.

**Web capability / routing / presentation**
- Modify `apps/quant-web/src/types/market.ts` — final overlay IDs, mode type, observation DTOs.
- Modify `apps/quant-web/src/utils/mainIndicators.ts` — preference V4 and `resolveResearchOverlayMode`.
- Modify `apps/quant-web/src/api/market.ts` — three new observation fetchers; existing JDJ Candidate fetcher may remain for non-Market consumers, but Market chart stops using it.
- Modify `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts` — mode-based source-specific fetch routing; preserve generation/dedupe/live-skip behavior.
- Modify `apps/quant-web/src/utils/historicalResearchMarkers.ts` — observation marker mapping.
- Modify `apps/quant-web/src/composables/useSubingObservation.ts` — accept an explicit native-mode enable input so main-chart non-native SuBing never calls current snapshot/lifecycle.
- Modify `apps/quant-web/src/pages/market/chart.vue` — single JDJ choice, native/non-native status tag, correct source wiring.
- Read `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`; its button list already consumes overlay definitions, so no production change is planned there.
- Modify `apps/quant-web/tests/mainIndicators.test.ts`, `historicalResearchMarkers.test.ts`, `subingResearch.test.ts`, `indicators.test.ts`.
- Create `apps/quant-web/tests/overlayObservationMarkers.test.ts` — isolated marker wording/projection tests.
- Modify `apps/quant-web/e2e/market-research.spec.mjs`.

**Canonical closeout**
- Modify `PROJECT_SOURCE.md`, `DECISIONS.md`, `STATUS.md` only after code and verification are true.
- Do not modify `TESTING.md`: the active60 smoke in this plan is a one-off acceptance check, not a new stable project command.

---

## Task 1: Freeze the Final Web Capability Contract, One-JDJ Native Routing, and Preference V4

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`

**Interfaces:**
- Final active `ResearchOverlayId`: `none|subing|n_structure|jdj|htdy`.
- Legacy preference input may contain `jdj_strategy`, but active UI/state may not.
- `resolveResearchOverlayMode(overlay, seriesKind, frequency)` returns exactly:
  `none | subing_native | subing_single_tf_observation | n_native | n_single_tf_observation | jdj_strategy_native | jdj_single_tf_observation | htdy_local_observation | unsupported`.
- During this task, observation modes are recognized but do not fetch until Tasks 2/4/6/7 wire their DTOs/routes. Existing native modes remain fully functional.

- [ ] **Step 1: Write failing tests for the final capability matrix and V4 migration**

In `mainIndicators.test.ts`, require:

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

Use a V3 storage fixture with `selectedOverlay: 'jdj_strategy'`; require V4 `jdj` while preserving optional EMA, period, and realtimeFollow.

In `historicalResearchMarkers.test.ts`, change the Market-facing JDJ 1m expectation from Candidate fetch to Strategy fetch: active `jdj + actual_dominant + 1m` must call `fetchJdjStrategy`, not `fetchJdj`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
node --test \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts
```

Expected: FAIL because V4/final overlay union/mode routing do not exist.

- [ ] **Step 3: Implement the capability/persistence contract**

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

`ResearchOverlayDefinition` no longer owns one static `historicalSource`; source selection belongs only to the explicit mode resolver.

In `mainIndicators.ts`:
- set `MAIN_CHART_PREFERENCES_VERSION = 4` and key `guiyi.market.chart.preferences.v4`;
- preserve V3/V2/V1 readers as migrations;
- V3 `jdj_strategy` and `jdj` both normalize to active `jdj`;
- make SuBing/N/JDJ definitions list all seven official frequencies, with `actual_dominant` series-kind restriction;
- keep HTDY definition 15m-only until Task 8 so its all-frequency TDD has a real RED phase;
- implement the exact mode matrix independently of `supportedFrequencies`, including final HTDY modes.

- [ ] **Step 4: Make existing native Market routing compile and remain functional**

Refactor `useHistoricalResearchMarkers.ts` now to switch on `resolveResearchOverlayMode` for existing native modes:

```text
subing_native -> existing fetchSubing
n_native -> existing fetchNStructure
jdj_strategy_native -> existing fetchJdjStrategy
none/unsupported/all three not-yet-wired observation modes/htdy -> reset with no Historical HTTP fetch
```

Remove active Market dependency on `fetchJdj` Candidate. Keep the backend Candidate route and API helper if other research code still references them.

In `chart.vue`, remove `getJdjHistoricalEvents` from the Market marker controller dependency and keep `getJdjStrategyHistoricalActions` as the 1m JDJ source.

- [ ] **Step 5: Run tests and TypeScript build**

```bash
node --test \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts
pnpm --dir apps/quant-web build
```

Expected: PASS. No observation formula may be added to TypeScript.

- [ ] **Step 6: Commit**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/src/composables/useHistoricalResearchMarkers.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/historicalResearchMarkers.test.ts
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

Cover with deterministic `CanonicalBar` fixtures and a fake segment loader:

```text
1m/30m/60m/1d/1w admitted
5m/15m rejected by observation request
outside-active symbol rejected before loader access
only selected frequency requested from loader
one physical segment never inherits another segment's Factor state
only golden/dead cross snapshots create events
NONE cross creates no event
no ready Factor inside requested window -> insufficient_data
ready Factors but no cross -> ready + events=[]
event identity contains version + symbol + contract + segment start + frequency
full projection restricted to prefix == prefix projection
```

Assert the event object has no `direction`, calibration result, slope threshold, previous-volume ratio, Formal condition, or signal status field.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_single_tf_observation_service.py
```

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the service**

Create immutable `SubingSingleTfObservationRequest`, status enum, event, metadata/result contracts. Constructor:

```python
SubingSingleTfObservationService(
    segment_loader,
    *,
    products: tuple[str, ...],
)
```

`history()` must:
1. validate `actual_dominant`, active product, allowed frequency, exact dates and `since <= through`;
2. call loader with exactly `(request.frequency,)`;
3. partition returned bars by exact `ResolvedContractSegment`;
4. call `calculate_subing_factor_series(..., timeframe=request.frequency, latest_bar_source="canonical")` separately per segment;
5. filter projection to `since..through`;
6. emit only `GOLDEN`/`DEAD` cross events;
7. return `insufficient_data` only when no requested-window Factor snapshot is ready; otherwise `ready`, including empty events.

Do not change `_INTRADAY_TIMEFRAMES` or any Formal evaluator.

- [ ] **Step 4: Add failing DTO/builder/route tests**

Extend `test_market_research_overlays_api.py`:

```text
GET /api/v1/market/research/subing/observation/history
actual_dominant + 30m -> 200
5m -> 422 INVALID_SUBING_SINGLE_TF_OBSERVATION_REQUEST
continuous -> 422 same code
active-universe/source/segment failure -> 409 typed code
```

Metadata is exact:

```json
{"observation_only":true,"formal_evidence":false,"oos_eligible":false,"alert_eligible":false,"auto_order":false}
```

- [ ] **Step 5: Implement builder, DTOs, route, and error mapping**

Use exact codes:
- `INVALID_SUBING_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `SUBING_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `SUBING_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- existing `ACTIVE_UNIVERSE_INVALID` -> 409

Keep `/subing/history` unchanged.

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

Expected: PASS with existing 5m/15m Formal facts unchanged.

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

## Task 3: Extract the Frequency-Neutral N Formula Seam and Prove Exact 5m Native Parity

**Files:**
- Create: `services/quant-api/app/research/n_structure/n_structure_formula.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_swing.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_pattern.py`
- Modify: `services/quant-api/app/research/n_structure/n_structure_segment.py`
- Create: `services/quant-api/tests/research/test_n_structure_formula.py`
- Create: `services/quant-api/tests/research/fixtures/n_structure_5m_formula_golden.json`
- Regression: existing N Swing/Pattern/State/Service tests

**Interfaces:**
- `n_structure_5m_v1` remains the only Formal N policy.
- `NStructureFormulaRules` contains only frozen Swing/Pattern/Structure rules; it excludes source timeframe and outcome horizons.
- `evaluate_n_structure_formula_segment(..., source_timeframe, rules)` accepts official `BarFrequency` values and returns `NStructureSegmentTrace`.
- Native `evaluate_n_structure_segment(..., policy)` remains exact-policy gated and uses M5.

- [ ] **Step 1: Verify existing N tests before capturing a golden**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py \
  services/quant-api/tests/research/test_n_structure_research_service.py
```

Expected: PASS; otherwise stop.

- [ ] **Step 2: Generate a test-only golden from the existing deterministic `_bars()` fixture**

The exact source fixture is `services/quant-api/tests/research/test_n_structure_research_service.py::_bars`, whose segment identity is `JM2701 / 2026-08-18..2026-08-20`.

Run before any N production edit:

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

from app.research.n_structure.n_structure_policy import load_n_structure_policy
from app.research.n_structure.n_structure_segment import evaluate_n_structure_segment

fixture_path = Path('tests/research/test_n_structure_research_service.py')
spec = spec_from_file_location('_n_fixture', fixture_path)
assert spec is not None and spec.loader is not None
fixture = module_from_spec(spec)
spec.loader.exec_module(fixture)

trace = evaluate_n_structure_segment(
    fixture._bars(),
    contract='JM2701',
    segment_start_trading_day=date(2026, 8, 18),
    segment_end_trading_day=date(2026, 8, 20),
    policy=load_n_structure_policy(),
)

def norm(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: norm(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): norm(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [norm(item) for item in value]
    raise TypeError(type(value).__name__)

out = Path('tests/research/fixtures/n_structure_5m_formula_golden.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(norm(trace), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(out)
PY
cd ../..
```

- [ ] **Step 3: Add a parity test that only reads the golden, then run twice**

`test_n_structure_formula.py` must dynamically load the same `_bars()` fixture, normalize current `evaluate_n_structure_segment` using the exact function above, read `n_structure_5m_formula_golden.json`, and assert deep equality. It must not contain an update-golden option.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: PASS twice.

Commit the freeze before production refactor:

```bash
git add services/quant-api/tests/research/fixtures/n_structure_5m_formula_golden.json \
  services/quant-api/tests/research/test_n_structure_formula.py
git commit -m "test(research): freeze N structure 5m formula parity"
```

- [ ] **Step 4: Add failing non-5m formula-seam tests**

Extend the test to require the same bars to evaluate with `source_timeframe=15m`, `60m`, and `1d`; every pivot must carry that selected frequency and pivot IDs must differ across frequencies. Native wrapper must still reject any non-exact policy object.

- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: FAIL because Swing/Pattern internals remain M5-only and no formula seam exists.

- [ ] **Step 6: Implement `NStructureFormulaRules` and formula evaluation**

`exact_n_structure_formula_rules(load_n_structure_policy())` accepts only the current exact policy and copies only these existing rule groups: Swing breach/equality/outside/inside/tie; N completion/same-boundary/N2/origin break; range-band; structure. It does not copy `source_timeframe` or `outcome`.

Refactor `NSwingPivot`/Swing validation so any `BarFrequency` is representable and pivot identity continues to include `source_timeframe.value`. Refactor Pattern internal validation to accept `NStructureFormulaRules`; do not relax the native public policy checker. Reuse `_evaluate_n_market_structure_from_exact_facts` unchanged.

Native wrapper becomes mechanically equivalent to:

```python
policy = exact n_structure_5m_v1
return evaluate_n_structure_formula_segment(
    bars,
    source_timeframe=BarFrequency.M5,
    contract=contract,
    segment_start_trading_day=segment_start_trading_day,
    segment_end_trading_day=segment_end_trading_day,
    rules=exact_n_structure_formula_rules(policy),
)
```

- [ ] **Step 7: Run native and formula regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_structure_formula.py
```

Expected: PASS; frozen 5m golden is unchanged.

- [ ] **Step 8: Commit formula refactor**

```bash
git add services/quant-api/app/research/n_structure/n_structure_formula.py \
  services/quant-api/app/research/n_structure/n_structure_swing.py \
  services/quant-api/app/research/n_structure/n_structure_pattern.py \
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
- Projection contains N completion observation events only; no outcomes, rank, score, Candidate/OOS result.

- [ ] **Step 1: Add failing service tests**

Cover:

```text
allowed non-native frequency matrix
5m rejected
active admission before loader access
single selected frequency load
true rank1 segment reset/no cross-contract memory
completion projected only at completed_at
ready + events=[] when valid source has no completion
public event ID isolated from n_structure_5m_v1 and contains frequency
full/prefix invariance
prepend earlier history does not change later observation IDs
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_n_structure_single_tf_observation_service.py
```

- [ ] **Step 3: Implement service using only the formula seam**

Load exactly `(request.frequency,)`, partition by true segments, call `evaluate_n_structure_formula_segment`, and project patterns whose `completed_at` trading day is inside `since..through`.

Public event ID is canonical:

```text
n_structure_single_tf_observation_v1|symbol|contract|segment_start|frequency|formula_n_id|completed_at
```

The formula `n_id` is source provenance, never the public event ID.

- [ ] **Step 4: Add DTO/builder/route and exact errors**

Route: `GET /api/v1/market/research/n-structure/observation/history`.

Use:
- `INVALID_N_STRUCTURE_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `N_STRUCTURE_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `N_STRUCTURE_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- `ACTIVE_UNIVERSE_INVALID` -> 409

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
- Core emits neutral setup facts, never `Jdj*TriggerEvent`.
- `JdjSetupStateScope` has exactly `TRADING_DAY` and `SEGMENT`.
- Native wrappers call core with `TRADING_DAY` and construct the exact existing Candidate event types/IDs.

- [ ] **Step 1: Run native baseline before editing**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_strategy_jm_parity.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Expected: PASS; otherwise stop.

- [ ] **Step 2: Add failing neutral-core tests**

For each setup family, reuse its current successful fixture and require a neutral fact with identical direction, observed boundary, trigger level, and provenance boundaries. Add reset tests:

```text
TRADING_DAY -> armed state cannot cross trading_day
SEGMENT -> same state may cross trading_day while contract+segment are unchanged
both -> segment identity change resets state
```

Key-level neutral core consumes an `NSwingPivot` object and must not parse/require literal `5m` from pivot ID; the unchanged native event wrapper remains responsible for its current 5m-specific event validation.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_setup_core.py
```

- [ ] **Step 4: Implement neutral core and native wrappers**

Move only setup state-machine decisions into `jdj_setup_core.py`. Keep `jdj_events.py` unchanged. Existing public reducers:
1. retain current native context validation;
2. call neutral core with `TRADING_DAY`;
3. map each neutral fact into the existing formal event constructor using current canonical ID helper.

Do not rename Candidate IDs/source kinds/event kinds.

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

Any native event or Strategy action drift blocks implementation.

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
- Selected frequency drives EMA20, N formula context, setup triggers.
- `5m..60m` uses `TRADING_DAY`; `1d/1w` uses `SEGMENT`.
- Strict-before: bar `i` consumes only N facts with evidence boundary `<= bars[i-1].bar_end` within the active reset scope.

- [ ] **Step 1: Add failing single-timeframe context tests**

Require:

```text
EMA20 from selected-frequency close series
N formula called with same selected frequency
current bar cannot see N fact confirmed on same bar
next bar can see it
5m..60m first bar of trading day has no inherited N context
1d/1w keeps prior context across trading days inside same segment
segment boundary clears context
future suffix does not change earlier context
```

All existing `build_jdj_context_series(1m,5m)` tests remain unchanged.

- [ ] **Step 2: Implement `build_jdj_single_tf_context_series`**

Do not modify `jdj_1m_policy_v1`. New builder receives selected-frequency bars, exact native JDJ policy as the source of EMA/setup constants, `NStructureFormulaRules`, selected frequency, segment identity, and `JdjSetupStateScope`. It evaluates N once per segment and projects only strict-before facts.

Do not change native builder signature or native output.

- [ ] **Step 3: Add failing observation-service tests**

Cover:

```text
allowed non-native matrix + 1m rejection
active admission before loader
only selected frequency loaded
three setup families projected
no Strategy/execution fields
5m..60m trading-day reset
1d/1w segment-continuous behavior
frequency-isolated IDs
strict-before same-boundary poison case
full/prefix invariance
rank1 rollover reset
no EMA20 ready in requested window -> insufficient_data
EMA ready but no setup -> ready + events=[]
```

- [ ] **Step 4: Implement service and isolated event identity**

Call neutral setup reducers directly, never formal Candidate reducers. Canonical public ID:

```text
jdj_single_tf_observation_v1|symbol|contract|segment_start|frequency|setup_kind|direction|observed_at|trigger_level|source_fact_key
```

Public event contains only `event_id, observation_version, frequency, setup_kind, direction, observed_at, trading_day, contract, segment_start_trading_day, trigger_level` plus the minimum non-execution provenance boundary for that setup.

- [ ] **Step 5: Add DTO/builder/route and exact errors**

Route: `GET /api/v1/market/research/jdj/observation/history`.

Use:
- `INVALID_JDJ_SINGLE_TF_OBSERVATION_REQUEST` -> 422
- `JDJ_SINGLE_TF_OBSERVATION_SOURCE_UNAVAILABLE` -> 409
- `JDJ_SINGLE_TF_OBSERVATION_SEGMENT_IDENTITY_INVALID` -> 409
- `JDJ_SINGLE_TF_OBSERVATION_CONTEXT_INVALID` -> 409
- `ACTIVE_UNIVERSE_INVALID` -> 409

Metadata has common eligibility flags plus `single_timeframe=true`.

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

Expected: PASS; native JDJ parity is non-negotiable.

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

## Task 7: Wire the Three Observation Modes Into Market Web

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/src/composables/useSubingObservation.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Create: `apps/quant-web/tests/overlayObservationMarkers.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- JDJ 1m -> existing Strategy endpoint; non-1m -> new observation endpoint.
- SuBing 5/15 -> native current/lifecycle + native Historical Formal path; other TF -> Historical observation only.
- N 5m -> native; other TF -> Historical observation.
- Historical observation never refreshes on `live` mutation.

- [ ] **Step 1: Add failing marker/routing tests**

Require exact mode routing:

```text
subing_native -> fetchSubing
subing_single_tf_observation -> fetchSubingObservation
n_native -> fetchNStructure
n_single_tf_observation -> fetchNStructureObservation
jdj_strategy_native -> fetchJdjStrategy
jdj_single_tf_observation -> fetchJdjObservation
htdy_local_observation/none/unsupported -> no Historical HTTP fetch
```

Retain generation invalidation, full identity check, event-ID dedupe, confirmed-range intersection, prepend behavior, and `live` early return.

`overlayObservationMarkers.test.ts` exact wording:
- SuBing labels only `MACD金叉|MACD死叉`; tooltip only cross/zero-distance/EMA21-side/current-volume and contains no `买入|卖出|强|弱`.
- N tooltip includes `单周期观察` and uses public observation ID.
- JDJ label is setup-family + `多|空`, tooltip includes `单周期观察`, and contains no `ENTRY|ADD|REDUCE|EXIT`.

- [ ] **Step 2: Run RED**

```bash
node --test \
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/tests/overlayObservationMarkers.test.ts
```

- [ ] **Step 3: Add DTOs, API fetchers, marker mappers**

Types must exactly mirror backend metadata/status/event contracts. Each source-specific loader validates echoed `series_kind/symbol/frequency/since/through`; no universal response adapter.

- [ ] **Step 4: Wire mode routing**

Extend Task-1 mode switch so all three observation modes fetch their source-specific route. `live` mutation still returns before any Historical observation request.

- [ ] **Step 5: Gate current SuBing snapshot/lifecycle to native mode**

Add an explicit `enabled` computed/ref input to `useSubingObservation`. In `chart.vue`, pass `enabled = mode === 'subing_native'`. Preserve backend `/market/research/subing` 1d research behavior and existing helper semantics outside this main-chart gating.

- [ ] **Step 6: Finish chart UX**

Final UI choices are exactly `无｜苏冰｜N字｜日进斗金｜火天大有`.

Display:
- JDJ 1m: EMA20 + Strategy reference actions, status `原生策略`.
- JDJ other TF: EMA20 + setup observation markers, status `单周期观察`.
- SuBing 5/15: native status `原生周期`; other TF: EMA21 + Historical observation markers, status `单周期观察`.
- N 5m: `原生周期`; other TF: `单周期观察`.
- HTDY 15m: `原始观察周期`; non-15m remains unavailable until Task 8.
- Unsupported series kind: visible unavailable state; no identity mutation.

- [ ] **Step 7: Extend E2E interception**

Cover:

```text
JDJ 1m -> jdj-strategy/history, never JDJ observation
JDJ 30m -> JDJ observation
SuBing 5m -> native history + current snapshot
SuBing 30m -> observation and no current snapshot
N 5m -> native
N 60m -> observation
rapid overlay/frequency switch ignores stale response
legacy V3 jdj_strategy preference renders active JDJ choice
```

- [ ] **Step 8: Run Web tests/build/E2E**

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
  apps/quant-web/tests/historicalResearchMarkers.test.ts \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/tests/overlayObservationMarkers.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): wire single-timeframe observations"
```

---

## Task 8: Expand HTDY Display Capability to All Seven Frequencies Without Changing Formula or Alert Identity

**Files:**
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Read regression: `packages/quant-core/guiyi_quant/indicators/htdy_original.py`
- Read regression: `services/quant-api/tests/test_htdy_production_kernel_policy.py`

- [ ] **Step 1: Add failing capability tests**

Require `researchOverlayCapability('htdy', seriesKind, frequency).supported === true` for every official frequency and each existing HTDY series kind. Require unchanged metadata: `observation_only`, `future_looking=true`, `repainting_accepted=true`, `historical_backtest_allowed=false`, 24 future-dependency Bars and 27 scan-zone Bars.

- [ ] **Step 2: Run RED**

```bash
node --test apps/quant-web/tests/mainIndicators.test.ts apps/quant-web/tests/indicators.test.ts
```

Expected: FAIL because Task 1 deliberately left HTDY's active capability at 15m.

- [ ] **Step 3: Change only HTDY supported frequency list**

Set HTDY active `supportedFrequencies` to all seven official values. Do not touch XMA calculation, metadata constants, local marker calculation, backend policy, or Alert code/scope.

- [ ] **Step 4: Extend E2E to select HTDY at 1m/60m/1w and verify no Historical observation HTTP route is called**

Then run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py

node --test \
  apps/quant-web/tests/indicators.test.ts \
  apps/quant-web/tests/htdyGoldenSample.test.ts \
  apps/quant-web/tests/htdyStep1Golden.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts

pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  apps/quant-web/e2e/market-research.spec.mjs
```

Expected: PASS; golden files are not regenerated.

- [ ] **Step 5: Commit**

```bash
git add apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/indicators.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): expose HTDY across market frequencies"
```

---

## Task 9: Run Full Native-Parity, Causal, API, and Web Verification

**Files:** no planned production changes. A discovered defect is fixed in its owning earlier module and all affected earlier tests are rerun before continuing.

- [ ] **Step 1: Run focused native + observation suites**

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

- [ ] **Step 2: Run full backend/engineering/static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api mypy services/quant-api/app
```

- [ ] **Step 3: Run full Web validation**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
```

- [ ] **Step 4: Run secret scan and inspect scope**

```bash
python3 scripts/engineering/secret_scan.py
git diff --check
git diff --stat develop...HEAD
git diff --name-only develop...HEAD
```

Expected: all checks pass; changed paths contain no Alert migration/runtime/RQAlpha/new DB model/new policy JSON/per-product config.

---

## Task 10: Run a Bounded Active60 Read-Only Capability Smoke

**Files:** none. No repository artifact or batch script is created.

**Coverage design:** Product admission and frequency routing are two independent dimensions. To keep the personal workstation smoke bounded, check all active60 products at one representative non-native frequency per system, then check all native/non-native frequency routes for JM. Automated matrix tests remain the authority for every frequency/system combination.

**Fixed Historical window:** `2026-08-18..2026-08-20`, selected independently because existing status evidence establishes confirmed active60 Canonical coverage there. This does not reuse stage-one Strategy smoke results or recovery machinery.

- [ ] **Step 1: Verify local read access without printing configuration values**

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from sqlalchemy import text
from app.db.session import SessionLocal
with SessionLocal() as session:
    session.execute(text('SELECT 1'))
print('read_access=ready')
PY
cd ../..
```

Expected: `read_access=ready`. If this fails, stop empirical smoke and report environment unavailable; do not add credentials or a secret-recovery script.

- [ ] **Step 2: Run active60 representative route smoke through FastAPI TestClient**

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from collections import Counter
from fastapi.testclient import TestClient
from app.main import app
from app.market_data.operational_universe import load_active_products

SINCE = '2026-08-18'
THROUGH = '2026-08-20'
PROBES = (
    ('subing', '/api/v1/market/research/subing/observation/history', '30m'),
    ('n', '/api/v1/market/research/n-structure/observation/history', '60m'),
    ('jdj', '/api/v1/market/research/jdj/observation/history', '30m'),
)
products = load_active_products()
assert len(products) == 60, len(products)
counts = Counter()
with TestClient(app) as client:
    for symbol in products:
        for system, path, frequency in PROBES:
            try:
                response = client.get(path, params={
                    'series_kind': 'actual_dominant',
                    'symbol': symbol,
                    'frequency': frequency,
                    'since': SINCE,
                    'through': THROUGH,
                })
                if response.status_code == 200:
                    payload = response.json()
                    request = payload.get('request', {})
                    if request.get('series_kind') != 'actual_dominant' or request.get('symbol') != symbol or request.get('frequency') != frequency:
                        counts['identity_drift'] += 1
                        print(symbol, system, 'identity_drift')
                        continue
                    status = payload.get('status')
                    if status not in {'ready', 'insufficient_data'}:
                        counts['command_failed'] += 1
                        print(symbol, system, 'command_failed')
                        continue
                    counts[status] += 1
                    print(symbol, system, status)
                elif response.status_code == 409:
                    code = ((response.json().get('detail') or {}).get('code'))
                    counts['typed_unavailable'] += 1
                    print(symbol, system, 'typed_unavailable', code)
                elif response.status_code == 422:
                    counts['unsupported'] += 1
                    print(symbol, system, 'unsupported')
                else:
                    counts['command_failed'] += 1
                    print(symbol, system, 'command_failed')
            except Exception:
                counts['command_failed'] += 1
                print(symbol, system, 'command_failed')
print('summary', dict(counts))
assert counts['unsupported'] == 0
assert counts['identity_drift'] == 0
assert counts['command_failed'] == 0
PY
cd ../..
```

`insufficient_data` and typed 409 unavailable are retained, not skipped. No stack trace/config/SQL is printed.

- [ ] **Step 3: Run JM all-frequency native/observation routing smoke**

```bash
cd services/quant-api
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app

SINCE = '2026-08-18'
THROUGH = '2026-08-20'
CASES = (
    ('/api/v1/market/research/subing/observation/history', ('1m','30m','60m','1d','1w'), 'observation'),
    ('/api/v1/market/research/n-structure/observation/history', ('1m','15m','30m','60m','1d','1w'), 'observation'),
    ('/api/v1/market/research/jdj/observation/history', ('5m','15m','30m','60m','1d','1w'), 'observation'),
    ('/api/v1/market/research/subing/history', ('5m','15m'), 'native'),
    ('/api/v1/market/research/n-structure/history', ('5m',), 'native'),
    ('/api/v1/market/research/jdj-strategy/history', ('1m',), 'strategy'),
)
with TestClient(app) as client:
    for path, frequencies, mode in CASES:
        for frequency in frequencies:
            response = client.get(path, params={
                'series_kind': 'actual_dominant', 'symbol': 'jm', 'frequency': frequency,
                'since': SINCE, 'through': THROUGH,
            })
            assert response.status_code in {200, 409}, (path, frequency, response.status_code)
            if response.status_code == 409:
                code = ((response.json().get('detail') or {}).get('code'))
                print(path, frequency, 'typed_unavailable', code)
                continue
            payload = response.json()
            request = payload['request']
            assert request['series_kind'] == 'actual_dominant'
            assert request['symbol'] == 'jm'
            assert request['frequency'] == frequency
            if mode == 'observation':
                assert payload['observation_only'] is True
                assert payload['formal_evidence'] is False
                assert payload['oos_eligible'] is False
                assert payload['alert_eligible'] is False
                assert payload['auto_order'] is False
                assert 'actions' not in payload
                assert 'reference_execution' not in payload
            elif mode == 'strategy':
                assert payload['reference_execution'] is True
                assert 'actions' in payload
                assert 'observation_only' not in payload
            else:
                assert 'observation_only' not in payload
            print(path, frequency, 'ok')
PY
cd ../..
```

Expected: no 422 and exact frequency echo; no observation/native identity mixing.

- [ ] **Step 4: Do not persist smoke output**

Do not add report/cache/DB row/JSON artifact/repository script. Completion notes may report aggregate counts only.

---

## Task 11: Canonical Closeout, Independent Review, and Develop Integration

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Update canonical wording only after Tasks 9-10 pass**

`PROJECT_SOURCE.md` records:
- final choices `无｜苏冰｜N字｜日进斗金｜火天大有`;
- official seven-frequency observation capability;
- native vs non-native single-TF boundary;
- JDJ 1m uses Strategy reference replay, non-1m uses setup observation;
- SuBing/N/JDJ non-native is confirmed-Historical `actual_dominant` only;
- no generic adapter/persistence/Alert/OOS/Runtime/order connection.

`DECISIONS.md` adds one durable decision: non-native single-TF observation may reuse formula/state-machine rules through narrow seams but never changes/inherits Formal/Candidate/Strategy/OOS/Alert identity.

`STATUS.md` records implementation head, automated validation summary, read-only smoke summary, and explicit unchanged release/Runtime/Alert Scope. Do not claim release-ready or Runtime-ready.

- [ ] **Step 2: Validate documentation/references**

```bash
python3 scripts/engineering/secret_scan.py
git diff --check
git grep -n "日进斗金策略" -- PROJECT_SOURCE.md apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e || true
git grep -n "jdj_strategy" -- apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e || true
```

Remaining `jdj_strategy` text is permitted only in explicit legacy V3 preference migration or backend route/type naming; it must not remain an active Market choice.

- [ ] **Step 3: Commit closeout docs**

```bash
git add PROJECT_SOURCE.md DECISIONS.md STATUS.md
git commit -m "docs: record stage2 market observation completion"
```

- [ ] **Step 4: Open a PR to `develop` for independent Lane 3 Review**

PR summary must identify: native parity surfaces; N formula seam; JDJ neutral setup seam; strict-before and reset-scope split; observation identity isolation; one-JDJ Web choice + V4 migration; test/smoke results; untouched Alert/Runtime/main/tag/release/DB/Redis/Canonical-write/OOS/RQAlpha/order surfaces.

- [ ] **Step 5: Independent reviewer inspects code and returns project conclusion**

Integration requires exactly:

```text
允许集成 develop
```

If `要求修正后再集成` or `阻塞`, fix on the same branch, rerun owning task tests plus Task 9, then review again.

- [ ] **Step 6: Merge only to `develop`, then clean temporary task assets**

Use repository normal merge method. Do not merge `main`, create tag, or switch Runtime. Verify merged task commit is ancestor of current `develop`; then remove the merged task worktree and task branch. Never remove main/develop/runtime worktrees.

---

## Completion Checklist

- [ ] Active UI labels exactly `无｜苏冰｜N字｜日进斗金｜火天大有`; active IDs exactly `none|subing|n_structure|jdj|htdy`.
- [ ] V3 `jdj_strategy` migrates to V4 `jdj` preserving period/EMA/realtimeFollow.
- [ ] SuBing 5/15 Formal facts unchanged; non-native exposes only EMA side, MACD cross/zero distance, current volume.
- [ ] N 5m golden unchanged; non-native uses same formula rules with frequency-isolated observation IDs and no outcome/OOS semantics.
- [ ] JDJ Candidate/Strategy 1m tests and stage-one JM parity unchanged.
- [ ] JDJ non-native uses same-frequency EMA20+N+setup only, strict-before; 5m..60m reset by trading day, 1d/1w by segment.
- [ ] JDJ non-native emits setup observations only, never Strategy actions/execution fields.
- [ ] HTDY selectable on all seven frequencies while formula/golden/repaint metadata and Alert identity remain unchanged.
- [ ] SuBing/N/JDJ use shared true-rank1 loader and have prefix-invariant confirmed-history observation facts.
- [ ] Unsupported series/frequency never silently falls back.
- [ ] Full backend, engineering, Ruff, Mypy, Web unit, build, focused Playwright, secret scan pass.
- [ ] Active60 representative smoke admits 60 products and has zero unsupported/identity-drift/command-failed; JM all-frequency routing passes.
- [ ] No DB/cache/worker/queue/scheduler/batch API/policy-per-frequency/per-product override added.
- [ ] Alert Scope/transport, Runtime, release/tag/main, production writes, OOS, RQAlpha sidecar, orders untouched.
- [ ] Independent Review says `允许集成 develop`; only then integrated into `develop` and temporary task worktree/branch cleaned.
