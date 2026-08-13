# SuBing Factor Observation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、Alert V1 或 Runtime 的前提下，交付 current rank1 segment 的 1d/5m/15m 苏冰 Factor 只读观察，包括 completed Live 5m/15m、`无/苏冰/火天大有` 单选 Overlay 和 Product Workspace 研究展示。

**Architecture:** 新增 zero-I/O `subing_research.py` 作为 Factor 计算核心；新增薄 `SubingReadService` 作为 current-rank1/segment/primary-companion/Historical-Live orchestration seam。现有 `MarketResearchService` 继续 Historical-only，Historical 只经 `MarketDataService`，Live 只经 `MarketReadService`。换月后严格 rank1-segment-local warm-up；SuBing 模式的可见 Kline 本身也必须截断在 current segment。Web 通过**effective chart identity**临时覆盖为 current rank1 contract，不改写用户原有 Market series preference。

**Tech Stack:** Python 3 / FastAPI / Decimal / quant-core Indicator Kernel / MarketDataService / MarketReadService / Vue 3 / TypeScript / Naive UI / Lightweight Charts / Vitest / Playwright.

## Global Constraints

- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md`。
- 不修改 `DatasetKey`、八表 Market Catalog、Canonical、月分区或 contract rank1-day coverage 语义。
- 不直接读 Parquet/Redis/RQData；Historical 经 `MarketDataService`，Live 经 `MarketReadService`。
- 不修改 `MarketResearchService` 的 Historical-only P0 合同。
- 不修改 Alert tables/runtime/evaluator/WeCom 或任何 Runtime 状态。
- 当前计划只做 Factor Observation；不得输出正式 `MATCHED LONG/SHORT`，不得自行填 Calibration。
- MACD 只允许 `web_macd_legacy_v1` 作为明确命名的 research Factor observation policy；generic MACD capability 不晋升。
- SuBing 只支持 `1d / 5m / 15m`；5m/15m 只消费 completed Live bars。
- 当前品种自动使用 latest rank1 真实 contract/current segment；不得跨换月继承 EMA/MACD，不得读取 pre-rank1 contract 数据补 warm-up。
- Kline、EMA21、MACD、Factor 必须使用同一 current segment；不得向左显示 segment 之前的同 contract 历史。
- Web research Overlay 单选：`none / subing / htdy`；SuBing 主图只显示 EMA21，Volume/MACD 副图固定。
- 选择 SuBing 只能改变当前 effective chart identity，不得覆盖用户原来保存的 `seriesKind/contract`；离开 SuBing 后恢复原 Market identity。
- 不新增 DB、Redis key、worker、scheduler、WebSocket、Factor Store、Rule Engine、Strategy Engine。
- 不做外部写入、Runtime switch、真实通知。

## File Map

**Create**
- `services/quant-api/app/market_data/subing_research.py`
- `services/quant-api/app/market_data/subing_read_service.py`
- `services/quant-api/tests/test_subing_research.py`
- `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- `services/quant-api/tests/test_subing_api.py`
- `apps/quant-web/src/components/market/SubingStatusStrip.vue`
- `apps/quant-web/src/components/market/SubingResearchSection.vue`
- `apps/quant-web/tests/subingResearch.test.ts`

**Modify**
- `packages/quant-core/guiyi_quant/indicators/policy.py`
- `docs/INDICATOR_KERNEL.md`
- `services/quant-api/app/market_data/market_data_service.py`
- `services/quant-api/tests/data_foundation/test_catalog_and_service.py`
- `services/quant-api/app/market_data/composition.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/api/market.py`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/tests/mainIndicators.test.ts`
- `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/e2e/market-research.spec.mjs`
- `TESTING.md`
- `docs/ARCHITECTURE.md`
- `STATUS.md` only after implementation/tests actually complete.

---

### Task 1: Build pure SuBing Factor core and pin MACD research-only policy

**Files:** create `subing_research.py`, `test_subing_research.py`; modify `policy.py`, `docs/INDICATOR_KERNEL.md`.

**Interfaces:** `SubingFactorStatus`, `PriceSide`, `MacdCross`, `SubingFactorSnapshot`, `SubingFactorResult`, `calculate_subing_factor_series()`, `calculate_subing_factor()`.

- [ ] **Step 1: Write failing deterministic tests with local bar builders**

Require READY, segment warm-up insufficient, Golden/Dead equality edges, invalid previous volume, zero close normalization fail-closed, strict increasing `bar_end`, and rejection of input before `segment_start_trading_day`.

```python
bars = _ready_bars(count=48, previous_volume=Decimal("100"), final_volume=Decimal("300"))
result = calculate_subing_factor(
    bars,
    timeframe=BarFrequency.M5,
    contract="JM2609",
    segment_start_trading_day=bars[0].trading_day,
    latest_bar_source="canonical",
)
assert result.status is SubingFactorStatus.READY
assert result.snapshot is not None
assert result.snapshot.price_side is PriceSide.ABOVE
assert result.snapshot.volume_ratio_prev == Decimal("3")
```

- [ ] **Step 2: Run test and confirm missing module/symbol failure**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_subing_research.py
```

- [ ] **Step 3: Allow only explicit MACD Factor observation consumer**

Add `subing_factor_observation` to `web_macd_legacy_v1.allowed_consumers`; keep generic `macd` `compatibility_validated/live_capable=False/alert_capable=False`.

- [ ] **Step 4: Implement immutable Factor types and math**

```python
@dataclass(frozen=True, slots=True)
class SubingFactorSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    bar_source: str
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
    macd_dif: Decimal
    macd_dea: Decimal
    macd_histogram: Decimal
    macd_cross: MacdCross
    macd_cross_level: Decimal
    macd_zero_distance_abs: Decimal
    macd_zero_distance_bps: Decimal
    volume: Decimal
    previous_volume: Decimal
    volume_ratio_prev: Decimal | None
```

Before MACD:

```python
policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
definition = get_indicator("macd")
assert policy.policy_id == definition.formal_policy_id
```

Use EMA21 `sma_window`; MACD registry defaults; convert rounded kernel floats via `Decimal(str(value))`.

OLS:

```python
def _regression_slope(values: Sequence[Decimal]) -> Decimal:
    n = Decimal(len(values))
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = sum(values, Decimal(0)) / n
    numerator = sum((Decimal(i) - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((Decimal(i) - x_mean) ** 2 for i in range(len(values)))
    return numerator / denominator
```

Normalize `slope/mean(EMA)*10000`. Golden: prev `DIF<=DEA`, current `DIF>DEA`; Dead mirrored. `cross_level=(DIF+DEA)/2`. If `close == 0`, normalized zero distance cannot be defined, so that bar is `INSUFFICIENT_DATA` rather than dividing/filling.

`calculate_subing_factor_series()` runs one aligned EMA/MACD pass. READY requires current EMA21, 10 ready EMA values, current+previous ready DIF/DEA, current/previous volume. `calculate_subing_factor()` returns last result.

- [ ] **Step 5: Run Factor + Indicator tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

- [ ] **Step 6: Align `docs/INDICATOR_KERNEL.md`**

Correct stale Product Workspace wording; document Factor-only consumer; formal Signal still pending.

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py \
  packages/quant-core/guiyi_quant/indicators/policy.py docs/INDICATOR_KERNEL.md
git commit -m "feat: add SuBing factor core"
```

---

### Task 2: Expose current contiguous rank1 segment through MarketDataService

**Files:** modify `market_data_service.py`, `test_catalog_and_service.py`.

**Interfaces:** `DominantContractSegmentSummary`; `MarketDataService.latest_dominant_segment(symbol)`.

- [ ] **Step 1: Write failing tests using existing session/tmp_path fixtures**

Seed keyword `TradingCalendar` and rank1 rows. Normal case: Jan2/3 JM2505, Jan6/7 JM2509 -> current segment Jan6-Jan7.

Missing-map poison: Jan3 old contract mapped, Jan6 is a formal trading day with no mapping, Jan7 new contract mapped -> resolver must raise `MAIN_CONTRACT_MAP_MISSING`. Do not use a test with no previous known mapping because pre-history cannot be inferred.

- [ ] **Step 2: Run new test node IDs; confirm method missing**

- [ ] **Step 3: Implement fail-closed current-segment resolver**

```python
@dataclass(frozen=True, slots=True)
class DominantContractSegmentSummary:
    symbol: str
    contract: str
    start_trading_day: date
    end_trading_day: date
```

Algorithm:
1. `main_map_before(symbol,None)`; empty -> `DOMINANT_CONTEXT_MISSING`.
2. Latest row defines current contract/end.
3. Walk backward through same-contract rows to first current-contract mapping index.
4. Validation starts at previous different-contract mapping date if one exists, otherwise earliest known mapping date.
5. Every formal trading day in validation range must have rank1 mapping; any gap -> `MAIN_CONTRACT_MAP_MISSING`.
6. Current segment starts first current-contract mapped trading day after previous different-contract mapping.
7. Every mapped day through end must remain current contract; otherwise fail closed.
8. Return summary.

- [ ] **Step 4: Run service/pagination regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_market_pagination.py
```

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/market_data/market_data_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py
git commit -m "feat: expose current dominant segment"
```

---

### Task 3: Build `SubingReadService` on existing Historical/Live seams

**Files:** create `subing_read_service.py`, `test_subing_read_service.py`; modify `composition.py`.

**Interfaces:** `SubingReadRequest`, `SubingReadSnapshot`, `SubingReadService.snapshot(request, now)`.

- [ ] **Step 1: Write failing local-fake tests**

Cover current segment, old same-contract segment poison, companion cutoff, Live contract mismatch and 1d Historical-only. Companion must never be later than primary.

- [ ] **Step 2: Run focused test; confirm missing module**

- [ ] **Step 3: Implement contracts**

```python
SUPPORTED_SUBING_FREQUENCIES = frozenset({BarFrequency.M5, BarFrequency.M15, BarFrequency.D1})

@dataclass(frozen=True, slots=True)
class SubingReadRequest:
    symbol: str
    frequency: BarFrequency

@dataclass(frozen=True, slots=True)
class SubingReadSnapshot:
    symbol: str
    product_name: str
    frequency: BarFrequency
    actual_contract: str
    dominant_mapping_date: date
    segment_start_trading_day: date
    source_mode: str
    live_observation: str
    live_reason: str | None
    macd_policy_id: str
    calibration_state: str
    primary: SubingFactorResult
    companion: SubingFactorResult | None
```

- [ ] **Step 4: Implement segment-local orchestration**

Use `SeriesPageQuery(CONTRACT,current contract,frequency,limit=300)` through `MarketReadService.history_page`, then filter `trading_day >= segment_start`.

5m/15m: merge Live only when `MarketReadService.state` reports same live contract and available; use `live_snapshot`, dedupe/sort/filter segment. 1d no Live.

Companion 15m for 5m, 5m for 15m; slice `bar_end<=primary_cutoff` before Factor calculation. Set bar source correctly. Calibration stays pending; no Signal.

- [ ] **Step 5: Add composition builder without touching MarketResearchService**

```python
def build_subing_read_service(session: Session) -> SubingReadService:
    return SubingReadService(
        market_data=build_market_data_service(session),
        market_read=build_market_read_service(session),
    )
```

- [ ] **Step 6: Run regressions and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py

git add services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
git commit -m "feat: add SuBing read model"
```

---

### Task 4: Add read-only SuBing HTTP contract

**Files:** modify `schemas/market.py`, `api/market.py`; create `test_subing_api.py`.

**Endpoint:** `GET /api/v1/market/research/subing?symbol=jm&frequency=5m`; no series_kind/contract request parameters.

- [ ] **Step 1: Write failing API tests**

```python
assert payload["symbol"] == "jm"
assert payload["actual_contract"] == "JM2609"
assert payload["frequency"] == "5m"
assert payload["calibration_state"] == "pending"
assert payload["primary"]["status"] in {"ready", "insufficient_data"}
assert "signal" not in payload
```

Also 30m -> 422; MarketDataError -> 409.

- [ ] **Step 2: Add nested Factor DTOs and endpoint**

DTO mirrors Factor Decimals plus symbol/product/frequency/current contract/mapping date/segment start/source/live/macd policy/calibration/primary/companion. Map invalid SuBing input -> 422; MarketDataError -> 409; no internal details.

- [ ] **Step 3: Run API regressions and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_market_research.py

git add services/quant-api/app/schemas/market.py services/quant-api/app/api/market.py \
  services/quant-api/tests/test_subing_api.py
git commit -m "feat: expose SuBing factor research API"
```

---

### Task 5: Replace indicator multi-select with single Overlay without mutating Market preference

**Files:** modify `types/market.ts`, `mainIndicators.ts`, `mainIndicators.test.ts`, `ProductWorkspaceToolbar.vue`, `chart.vue`.

**Interfaces:** `ResearchOverlayId='none'|'subing'|'htdy'`; preference v2; `effectiveSeriesIdentity()`.

- [ ] **Step 1: Write failing preference and effective-identity tests**

```ts
expect(defaultMainChartPreferences().selectedOverlay).toBe('subing')
expect(visibleMainIndicatorsForOverlay('subing')).toEqual(['ema_21'])
expect(visibleMainIndicatorsForOverlay('htdy')).toEqual(['htdy'])
expect(visibleMainIndicatorsForOverlay('none')).toEqual([])
```

Add a pure helper test:

```ts
expect(resolveEffectiveSeriesIdentity({
  overlay: 'subing',
  userSeriesKind: 'continuous',
  userContract: undefined,
  dominantContract: 'JM2609',
})).toEqual({ seriesKind: 'contract', contract: 'JM2609' })

expect(resolveEffectiveSeriesIdentity({
  overlay: 'htdy',
  userSeriesKind: 'continuous',
  userContract: undefined,
  dominantContract: 'JM2609',
})).toEqual({ seriesKind: 'continuous', contract: undefined })
```

This proves entering/leaving SuBing does not overwrite the user's Market identity.

V1 preferences with HTDY visible -> htdy; every other valid old indicator state -> default subing; preserve period/realtimeFollow.

- [ ] **Step 2: Implement preference v2 and effective identity helper**

Keep primitive `MAIN_INDICATOR_DEFINITIONS`. Add:

```ts
export type ResearchOverlayId = 'none' | 'subing' | 'htdy'

export function resolveEffectiveSeriesIdentity(input: {
  overlay: ResearchOverlayId
  userSeriesKind: SeriesKind
  userContract?: string
  dominantContract?: string
}): { seriesKind: SeriesKind; contract?: string } {
  if (input.overlay === 'subing') {
    return { seriesKind: 'contract', contract: input.dominantContract }
  }
  return {
    seriesKind: input.userSeriesKind,
    contract: input.userSeriesKind === 'contract' ? input.userContract : undefined,
  }
}
```

If SuBing has no resolved dominant contract, `refreshSeries()` must wait/fail closed; never fall back to user series.

- [ ] **Step 3: Convert toolbar to exactly `无 / 苏冰 / 火天大有` single-select**

In SuBing hide/disable user series-kind/arbitrary-contract controls and display current dominant. Do not mutate the underlying refs that store the user's Market preference.

- [ ] **Step 4: Make `currentIdentity()` use effective identity**

In `chart.vue`, preserve existing `seriesKind`/`contract` as user preference. Derive effective identity from Overlay + selected dominant:

```ts
function currentIdentity() {
  const effective = resolveEffectiveSeriesIdentity({
    overlay: selectedOverlay.value,
    userSeriesKind: seriesKind.value,
    userContract: contract.value,
    dominantContract: selectedDominant.value?.actual_contract,
  })
  return {
    seriesKind: effective.seriesKind,
    symbol: symbol.value,
    contract: effective.contract,
    frequency: frequency.value,
  }
}
```

Use `currentIdentity()` for `replaceSeries`, current Product Research identity and persistent marker synchronization. Add `selectedOverlay` to refresh watchers. On initial metadata load, wait until dominants are resolved before first SuBing `refreshSeries()`. Do not write effective contract into user `contract` preference or router preference state as if user selected it; route may display effective identity, but persistence keeps user choice separate.

When Overlay leaves SuBing, next `currentIdentity()` automatically returns prior user seriesKind/contract.

- [ ] **Step 5: Run Web test/build and commit**

```bash
pnpm --dir apps/quant-web test -- mainIndicators.test.ts
pnpm --dir apps/quant-web build

git add apps/quant-web/src/types/market.ts apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue
git commit -m "feat: make research overlay single select"
```

---

### Task 6: Render segment-clipped SuBing Factor observation and completed-Live refresh

**Files:** modify Web types/API/sidebar/chart/e2e; create `SubingStatusStrip.vue`, `SubingResearchSection.vue`, `subingResearch.test.ts`.

- [ ] **Step 1: Write failing normalization + segment-filter tests**

```ts
const result = normalizeSubingResearch(payload)
expect(result.primary.snapshot?.slope_5_bps_per_bar).toBe(2.7)
expect(filterBarsToSubingSegment(bars, '2026-08-12')
  .every((bar) => (bar.trading_day || '') >= '2026-08-12')).toBe(true)
```

Include old same-contract bars and insufficient snapshot.

- [ ] **Step 2: Add `getSubingResearch`, Decimal normalization and segment helper**

```ts
export function filterBarsToSubingSegment(bars: BarData[], segmentStart: string): BarData[] {
  return bars.filter((bar) => (bar.trading_day || '') >= segmentStart)
}
```

- [ ] **Step 3: Build compact Factor-only status strip**

READY shows timeframe/companion direction, MACD cross/zero distance, volume ratio and “研究参数待冻结”. INSUFFICIENT shows current-main rollover/warm-up. Live unavailable is explicit. No 买入/卖出.

- [ ] **Step 4: Build detailed SuBing section in existing sidebar**

Display current contract, segment start, primary/companion confirmed times/Factor values. Existing Product Research and HTDY Alert control stay intact.

- [ ] **Step 5: Make current segment own visible chart range**

```ts
const visibleBars = computed(() => {
  if (selectedOverlay.value !== 'subing') return bars.value
  const start = subing.value?.segment_start_trading_day
  return start ? filterBarsToSubingSegment(bars.value, start) : []
})
```

While SuBing snapshot loads, do not flash unbounded contract bars. Pass `visibleBars` to KlineChart. In SuBing mode, mutation watcher rebuilds from `visibleBars` instead of forwarding unfiltered prepend/live mutations, ensuring browser EMA/MACD mirrors never see pre-segment bars.

`loadEarlierBars()` no-ops once earliest visible trading day equals segment start. Older underlying rows remain invisible and must not feed Kline-derived indicators.

- [ ] **Step 6: Add snapshot lifecycle + one bounded common-boundary refresh**

Fetch on metadata ready, symbol/frequency/Overlay changes and completed primary Live mutation. Only 1d/5m/15m. At a 5m bar that is also 15m boundary, if first response companion is older than primary, exactly one delayed refresh; clear timer on identity change/unmount. No polling.

- [ ] **Step 7: Extend E2E**

Assert exact Overlay options, SuBing effective request uses current dominant contract while underlying user series preference is preserved, leaving SuBing restores previous series identity, no pre-segment Kline, EMA21-only overlay, Factor-not-trade wording, HTDY repaint warning regression, unsupported 30m behavior.

- [ ] **Step 8: Run Web regressions and commit**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build

git add apps/quant-web/src/types/market.ts apps/quant-web/src/api/market.ts \
  apps/quant-web/src/components/market/SubingStatusStrip.vue \
  apps/quant-web/src/components/market/SubingResearchSection.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat: show SuBing factor observation"
```

---

### Task 7: Close canonical/test/status boundaries

**Files:** modify `TESTING.md`, `docs/ARCHITECTURE.md`, `STATUS.md` only after actual completion.

- [ ] **Step 1: Add no-side-effect SuBing validation to TESTING**

Include all SuBing tests, MarketRead/MarketResearch regressions, Ruff/Mypy, Web tests/E2E/build. No Runtime mutation command.

- [ ] **Step 2: Align ARCHITECTURE**

Add thin `SubingReadService`; no provider/Redis-direct/storage/Runtime responsibility; MarketResearchService Historical-only.

- [ ] **Step 3: Run full checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

- [ ] **Step 4: Update STATUS only after all implementation/checks pass**

Record Factor Observation/current-segment Kline/effective current-contract view/completed Live; Calibration pending, Signal absent, Alert V1 unchanged, no Runtime deployment.

- [ ] **Step 5: Commit docs/status**

```bash
git add TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: record SuBing factor observation boundaries"
```

## Plan Acceptance

```text
Calibration = pending
formal Signal = not implemented
Alert V1 = unchanged
Runtime = untouched
Data Foundation = unchanged
Kline/EMA/MACD/Factor = current rank1 segment only
SuBing effective identity does not overwrite user Market series preference
no pre-rank1 warm-up
no cross-roll indicator state
no new persistence/cache/runtime component
```

Do not start `2026-08-13-subing-calibration-entry-signal-v1.md` until this plan is green and independently reviewed.