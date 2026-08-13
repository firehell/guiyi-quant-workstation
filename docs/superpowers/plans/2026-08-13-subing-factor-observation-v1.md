# SuBing Factor Observation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、Alert V1 或 Runtime 的前提下，交付 current rank1 segment 的 1d/5m/15m 苏冰 Factor 只读观察，包括 completed Live 5m/15m、`无/苏冰/火天大有` 单选 Overlay 和 Product Workspace 研究展示。

**Architecture:** 新增 zero-I/O `subing_research.py` 作为 Factor 计算核心；新增薄 `SubingReadService` 作为 current-rank1/segment/primary-companion/Historical-Live orchestration seam。现有 `MarketResearchService` 继续 Historical-only，Historical 只经 `MarketDataService`，Live 只经 `MarketReadService`。换月后严格 rank1-segment-local warm-up；SuBing 模式的可见 Kline 本身也必须截断在 current segment，不能只截 Factor。

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

Require a READY case, segment warm-up insufficient case, Golden/Dead equality edges, invalid previous volume, strict increasing `bar_end`, and rejection of any input bar before `segment_start_trading_day`.

Example assertions:

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

Change `web_macd_legacy_v1.allowed_consumers` to include `subing_factor_observation`; do not change `macd` registry `compatibility_validated/live_capable=False/alert_capable=False`.

- [ ] **Step 4: Implement immutable Factor types and math**

Core fields:

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

Before MACD calculation:

```python
policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
definition = get_indicator("macd")
assert policy.policy_id == definition.formal_policy_id
```

Use EMA21 `sma_window`; MACD registry defaults; convert rounded kernel floats via `Decimal(str(value))`.

OLS slope:

```python
def _regression_slope(values: Sequence[Decimal]) -> Decimal:
    n = Decimal(len(values))
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = sum(values, Decimal(0)) / n
    numerator = sum(
        (Decimal(index) - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    )
    denominator = sum((Decimal(index) - x_mean) ** 2 for index in range(len(values)))
    return numerator / denominator
```

Normalize `slope/mean(EMA window)*10000`. Golden: prev `DIF<=DEA` and current `DIF>DEA`; Dead mirrored. `cross_level=(DIF+DEA)/2`; zero distances absolute and bps.

`calculate_subing_factor_series()` runs EMA/MACD once and returns one aligned result per bar. READY requires current EMA21, 10 ready EMA values, current+previous ready DIF/DEA, current/previous volume inputs. `calculate_subing_factor()` returns last result.

- [ ] **Step 5: Run Factor + existing Indicator tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

- [ ] **Step 6: Align `docs/INDICATOR_KERNEL.md`**

Correct stale Product Workspace wording; document `subing_factor_observation` as research-only. Do not claim Signal capability.

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

- [ ] **Step 1: Write failing tests using existing `session`/`tmp_path` fixtures**

Normal rollover test seeds calendar/map facts using keyword constructors:

```python
session.add_all((
    TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 2), is_trading_day=True),
    TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 3), is_trading_day=True),
    TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 6), is_trading_day=True),
    TradingCalendar(exchange_code="DCE", trade_date=date(2025, 1, 7), is_trading_day=True),
))
catalog.upsert_main_contracts((
    ("jm", date(2025, 1, 2), "JM2505"),
    ("jm", date(2025, 1, 3), "JM2505"),
    ("jm", date(2025, 1, 6), "JM2509"),
    ("jm", date(2025, 1, 7), "JM2509"),
))
```

Assert result contract JM2509, start Jan 6, end Jan 7.

Missing-map test must be able to catch a gap **immediately before the first current-contract mapping**: seed Jan 3 old contract, trading day Jan 6 with no mapping, Jan 7 current contract. Expected `MAIN_CONTRACT_MAP_MISSING`; do not use a test where the only mapping is Jan 7 because the active-history beginning is then unknowable.

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
1. Read `main_map_before(symbol, None)`; empty -> `DOMINANT_CONTEXT_MISSING`.
2. Latest mapping defines current contract/end day.
3. Walk backward through same-contract mappings to find first current-contract mapping index.
4. If a previous different-contract mapping exists, set validation start to its trade date; otherwise validation start is earliest known mapping date.
5. Query formal `trading_days(validation_start, latest.trade_date)`.
6. Every expected day in this validation interval must have a rank1 mapping; any gap -> `MAIN_CONTRACT_MAP_MISSING`.
7. Recompute current segment start as the first mapped trading day after the previous different-contract mapping whose contract equals latest contract.
8. Every mapped day from segment start through end must equal latest contract; otherwise fail closed.
9. Return summary.

This catches Jan3-old / Jan6-missing / Jan7-new ambiguity without assuming mappings before the repository's earliest known map.

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

Cover current segment, old same-contract segment poison, companion cutoff, Live contract mismatch and 1d Historical-only behavior. Assert companion `bar_end <= primary.bar_end` whenever both snapshots are READY.

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

Unsupported frequency -> `SubingReadError("SUBING_FREQUENCY_UNSUPPORTED")`.

- [ ] **Step 4: Implement segment-local Historical/Live orchestration**

For each required timeframe:

```python
identity = SeriesPageQuery(
    SeriesKind.CONTRACT,
    request.symbol,
    frequency,
    contract=segment.contract,
    limit=300,
)
historical = tuple(
    bar for bar in self._market_read.history_page(identity).bars
    if bar.trading_day >= segment.start_trading_day
)
```

5m/15m: inspect `MarketReadService.state(identity, now)`; merge Live only if live contract equals resolved current rank1 and live is available. Use `live_snapshot`, dedupe/sort/filter segment again. 1d never reads Live.

Companion: 15m for 5m primary, 5m for 15m primary; slice `bar_end <= primary_cutoff` before Factor calculation. No future companion.

Set `latest_bar_source="live"` only when final selected bar originated from Live; `calibration_state="pending"`. No Signal in this plan.

- [ ] **Step 5: Add composition builder, leaving MarketResearchService untouched**

```python
def build_subing_read_service(session: Session) -> SubingReadService:
    return SubingReadService(
        market_data=build_market_data_service(session),
        market_read=build_market_read_service(session),
    )
```

- [ ] **Step 6: Run regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py
```

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
git commit -m "feat: add SuBing read model"
```

---

### Task 4: Add read-only SuBing HTTP contract

**Files:** modify `schemas/market.py`, `api/market.py`; create `test_subing_api.py`.

**Endpoint:** `GET /api/v1/market/research/subing?symbol=jm&frequency=5m`; no user-supplied `series_kind`/contract.

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

- [ ] **Step 2: Run test and confirm failure**

- [ ] **Step 3: Add nested Factor DTOs**

`SubingFactorOut` mirrors all Factor fields with Decimal; `SubingFactorResultOut` has `status/snapshot`; `SubingResearchResponse` has symbol/product/frequency/current contract/mapping date/segment start/source/live status/macd policy/calibration state/primary/companion. No Signal field.

- [ ] **Step 4: Add endpoint with existing redacted error conventions**

Unsupported timeframe/input -> 422; MarketDataError -> 409; no internal Redis/provider details.

- [ ] **Step 5: Run API regressions and commit**

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

### Task 5: Replace user-facing indicator multi-select with one research Overlay

**Files:** modify `types/market.ts`, `mainIndicators.ts`, `mainIndicators.test.ts`, `ProductWorkspaceToolbar.vue`, `chart.vue`.

**Interfaces:** `ResearchOverlayId = 'none'|'subing'|'htdy'`; `visibleMainIndicatorsForOverlay()`; preference v2.

- [ ] **Step 1: Write failing preference/migration tests**

```ts
expect(defaultMainChartPreferences().selectedOverlay).toBe('subing')
expect(visibleMainIndicatorsForOverlay('subing')).toEqual(['ema_21'])
expect(visibleMainIndicatorsForOverlay('htdy')).toEqual(['htdy'])
expect(visibleMainIndicatorsForOverlay('none')).toEqual([])
```

V1 with HTDY visible -> HTDY; every other valid v1 state -> default SuBing; preserve period/realtimeFollow.

- [ ] **Step 2: Implement preference v2 while retaining primitive indicator metadata**

```ts
export type ResearchOverlayId = 'none' | 'subing' | 'htdy'

export interface MainChartPreferences {
  version: 2
  selectedOverlay: ResearchOverlayId
  period?: string | null
  realtimeFollow?: boolean
}
```

Same storage key, explicit migration.

- [ ] **Step 3: Convert toolbar to exactly `无 / 苏冰 / 火天大有` single-select**

In SuBing mode hide/disable user series-kind/arbitrary-contract controls and show current dominant contract.

- [ ] **Step 4: Pin initial and subsequent SuBing chart identity before every series refresh**

```ts
function activateSubing() {
  const dominant = selectedDominant.value
  if (!dominant) return
  seriesKind.value = 'contract'
  contract.value = dominant.actual_contract
}
```

Call after dominant metadata resolves **before initial `refreshSeries()`** when default/current Overlay is SuBing; also before refresh on symbol change and transition into SuBing. Never use actual-dominant Kline in SuBing mode.

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

READY: current timeframe/companion directions, MACD cross/zero distance, volume ratio, “研究参数待冻结”.

INSUFFICIENT: “当前主力已切换 / 指标 warm-up 中”.

Live unavailable: explicit Historical/Live unavailable wording.

No 买入/卖出 in this plan.

- [ ] **Step 4: Build detailed SuBing section inside existing ProductResearchSidebar**

Display current contract, segment start, primary/companion confirmed times and Factor values. Keep Product Research and existing HTDY Alert control intact.

- [ ] **Step 5: Make current rank1 segment own the visible Kline range**

```ts
const visibleBars = computed(() => {
  if (selectedOverlay.value !== 'subing') return bars.value
  const start = subing.value?.segment_start_trading_day
  return start ? filterBarsToSubingSegment(bars.value, start) : []
})
```

While SuBing snapshot is loading, do not flash unbounded contract bars. Pass `visibleBars` to `KlineChart`.

When SuBing is active, the existing `mutation` watcher must rebuild from `visibleBars` instead of forwarding unfiltered prepend/update mutations, so browser EMA/MACD mirrors never see pre-segment bars.

`loadEarlierBars()` no-ops once the earliest visible trading day equals segment start. If an underlying page contains older bars, keep them internal only; never render or derive indicators from them.

- [ ] **Step 6: Add snapshot lifecycle and one bounded common-boundary refresh**

Fetch on initial metadata ready, symbol/frequency changes, Overlay entry and completed primary mutation. Only 1d/5m/15m call API. For a 5m primary at a 15m boundary, if first response companion is older than primary, schedule exactly one delayed refresh; clear timer on identity change/unmount. No polling.

- [ ] **Step 7: Extend E2E**

Assert exact Overlay options, default initial current-contract request, no pre-segment Kline, EMA21-only main overlay, Factor-not-trade wording, HTDY repaint warning regression, unsupported 30m state.

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

**Files:** modify `TESTING.md`, `docs/ARCHITECTURE.md`, and `STATUS.md` only after actual completion.

- [ ] **Step 1: Add no-side-effect SuBing validation block to TESTING.md**

Include SuBing tests plus MarketRead/MarketResearch regressions, Ruff, Mypy, Web tests/E2E/build. No Runtime command.

- [ ] **Step 2: Align ARCHITECTURE.md**

Add thin `SubingReadService`; explicitly no provider/Redis-direct/storage/Runtime responsibilities; MarketResearchService stays Historical-only.

- [ ] **Step 3: Run full backend/Web/engineering checks**

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

- [ ] **Step 4: Update STATUS.md only if all implementation/checks actually pass**

Record Factor Observation/current-segment Kline/completed Live facts; explicitly Calibration pending, Signal absent, Alert V1 unchanged, no Runtime deployment.

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
no pre-rank1 warm-up
no cross-roll indicator state
no new persistence/cache/runtime component
```

Do not start `2026-08-13-subing-calibration-entry-signal-v1.md` until this plan is green and independently reviewed.