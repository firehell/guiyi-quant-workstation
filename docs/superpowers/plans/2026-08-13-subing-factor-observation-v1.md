# SuBing Factor Observation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、Alert V1 或 Runtime 的前提下，交付当前 rank1 segment 的 1d/5m/15m 苏冰 Factor 只读观察，包括 completed Live 5m/15m、`无/苏冰/火天大有` 单选 Overlay 和 Product Workspace 研究展示。

**Architecture:** 新增 zero-I/O `subing_research.py` 作为 Factor 计算核心；新增薄 `SubingReadService` 作为 current-rank1/segment/primary-companion/Historical-Live orchestration seam。现有 `MarketResearchService` 继续 Historical-only，Historical 只经 `MarketDataService`，Live 只经 `MarketReadService`，换月后严格 rank1-segment-local warm-up。

**Tech Stack:** Python 3 / FastAPI / Decimal / quant-core Indicator Kernel / PostgreSQL Catalog read path / Redis Live Overlay via `MarketReadService` / Vue 3 / TypeScript / Naive UI / Lightweight Charts / Vitest / Playwright.

## Global Constraints

- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md`。
- 不修改 `DatasetKey`、八表 Market Catalog、Canonical、月分区或 contract rank1-day coverage 语义。
- 不直接读 Parquet、不直接读 Redis、不调用 RQData；Historical 经 `MarketDataService`，Live 经 `MarketReadService`。
- 不修改 `MarketResearchService` 的 P0 Historical-only 合同。
- 不修改 `alert_rules`、`alert_events`、Alert Runtime、HTDY evaluator、WeCom sender 或任何 Runtime 状态。
- 当前阶段只做 Factor Observation；不得输出正式 `MATCHED LONG/SHORT` Signal，不得自行填 Calibration。
- MACD 仅允许 `web_macd_legacy_v1` 作为明确命名的 research Factor observation policy；不得在本计划中晋升 `live_candidate`、backtest 或 alert capability。
- 苏冰只支持 `1d / 5m / 15m`；5m/15m 只消费 completed Live bars。
- 当前品种自动使用 latest rank1 真实 contract，并只使用 current rank1 segment；不得跨换月继承 EMA/MACD，不得读取 pre-rank1 contract 数据补 warm-up。
- Web 用户层主图 Overlay 单选：`none / subing / htdy`；苏冰主图只显示 EMA21，Volume/MACD 副图继续固定。
- 不新增 DB、Redis key、worker、scheduler、WebSocket、Factor Store、Rule Engine 或 Strategy Engine。
- 所有外部写入、Runtime switch、真实通知均不在本计划范围。

---

## File Map

**Create**
- `services/quant-api/app/market_data/subing_research.py` — pure Factor calculations and explicit MACD observation policy guard.
- `services/quant-api/app/market_data/subing_read_service.py` — current-rank1 segment and Historical/Live orchestration.
- `services/quant-api/tests/test_subing_research.py` — pure Factor math, warm-up, MACD cross and volume tests.
- `services/quant-api/tests/data_foundation/test_subing_read_service.py` — rank1 segment, rollover, Live seam and multi-TF tests.
- `services/quant-api/tests/test_subing_api.py` — HTTP contract tests.
- `apps/quant-web/src/components/market/SubingStatusStrip.vue` — compact current Factor state.
- `apps/quant-web/src/components/market/SubingResearchSection.vue` — detailed Factor section inside existing sidebar.
- `apps/quant-web/tests/subingResearch.test.ts` — API normalization and UI helper tests.

**Modify**
- `packages/quant-core/guiyi_quant/indicators/policy.py` — allow explicitly named `subing_factor_observation` consumer for the existing MACD display policy only.
- `docs/INDICATOR_KERNEL.md` — align stale Product Workspace wording and document research-only MACD Factor consumer.
- `services/quant-api/app/market_data/market_data_service.py` — expose latest contiguous rank1 segment without duplicating resolver logic.
- `services/quant-api/tests/data_foundation/test_catalog_and_service.py` — latest segment resolver tests.
- `services/quant-api/app/market_data/composition.py` — build `SubingReadService` from existing read services.
- `services/quant-api/app/schemas/market.py` — SuBing Factor response DTOs.
- `services/quant-api/app/api/market.py` — `GET /api/v1/market/research/subing`.
- `apps/quant-web/src/types/market.ts` — Overlay and SuBing response types.
- `apps/quant-web/src/api/market.ts` — SuBing endpoint and Decimal normalization.
- `apps/quant-web/src/utils/mainIndicators.ts` — v2 single-overlay preference while retaining existing primitive definitions.
- `apps/quant-web/tests/mainIndicators.test.ts` — preference migration and overlay mapping.
- `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue` — single-select research Overlay and SuBing current-contract mode.
- `apps/quant-web/src/components/market/ProductResearchSidebar.vue` — mount `SubingResearchSection` inside existing sidebar.
- `apps/quant-web/src/pages/market/chart.vue` — current-rank1 contract pinning, SuBing snapshot fetch and completed-bar refresh.
- `apps/quant-web/e2e/market-research.spec.mjs` — Product Workspace regression and SuBing UI behavior.
- `TESTING.md` — add no-side-effect SuBing validation entry.
- `docs/ARCHITECTURE.md` — add thin `SubingReadService` read seam after implementation is real.

---

### Task 1: Build the pure SuBing Factor core and pin MACD research-only policy

**Files:**
- Create: `services/quant-api/app/market_data/subing_research.py`
- Create: `services/quant-api/tests/test_subing_research.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `docs/INDICATOR_KERNEL.md`

**Interfaces:**
- Produces: `SubingFactorStatus`, `PriceSide`, `MacdCross`, `SubingFactorSnapshot`, `SubingFactorResult`.
- Produces: `calculate_subing_factor_series(...)` and `calculate_subing_factor(...)`.
- Later tasks pass only current-segment `CanonicalBar` sequences into these functions.

- [ ] **Step 1: Write failing tests for factor math and policy guard**

Create tests that require the new interfaces and verify exact semantics:

```python
from datetime import date
from decimal import Decimal

from app.market_data.domain import BarFrequency
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorStatus,
    calculate_subing_factor,
)


def test_subing_factor_reports_price_slope_macd_and_volume(ready_bars):
    result = calculate_subing_factor(
        ready_bars,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=ready_bars[0].trading_day,
        latest_bar_source="canonical",
    )
    assert result.status is SubingFactorStatus.READY
    assert result.snapshot is not None
    assert result.snapshot.price_side is PriceSide.ABOVE
    assert result.snapshot.slope_5_bps_per_bar is not None
    assert result.snapshot.slope_10_bps_per_bar is not None
    assert result.snapshot.volume_ratio_prev == Decimal("3")


def test_subing_factor_returns_insufficient_when_segment_warmup_is_short(short_bars):
    result = calculate_subing_factor(
        short_bars,
        timeframe=BarFrequency.M15,
        contract="JM2609",
        segment_start_trading_day=short_bars[0].trading_day,
        latest_bar_source="canonical",
    )
    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None
```

Add focused tests for Golden/Dead cross equality edges, `previous_volume <= 0`, strict input ordering, and segment dates before `segment_start_trading_day` being rejected.

- [ ] **Step 2: Run the new tests and confirm they fail because the module does not exist**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py
```

Expected: FAIL on missing `app.market_data.subing_research` or missing exported symbols.

- [ ] **Step 3: Add the explicit MACD Factor-observation policy consumer without promoting MACD**

Update `web_macd_legacy_v1` only as follows; do not change `macd` registry status/capability in this plan:

```python
"web_macd_legacy_v1": FormalPolicy(
    policy_id="web_macd_legacy_v1",
    indicator_family="MACD",
    seed_policy="sma_window",
    smoothing_policy=None,
    histogram_scale=2,
    lookback="fast12_slow26_signal9",
    confirmed_only=True,
    frozen_legacy=False,
    allowed_consumers=("Market_readonly_display", "subing_factor_observation"),
    blocked_consumers=("formal_strategy_signal_until_validated", FORMAL_BACKTEST_CONSUMER),
    notes="Web/Market MACD compatibility policy; SuBing may use it for confirmed research Factor observation only.",
),
```

`registry.py` must still report `status="compatibility_validated"`, `live_capable=False`, `alert_capable=False`.

- [ ] **Step 4: Implement the pure Factor types and calculations**

Use exact policy IDs and Decimal outputs. The core shape should be:

```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from collections.abc import Sequence

from app.market_data.domain import BarFrequency, CanonicalBar
from guiyi_quant.indicators.ema import ema_series
from guiyi_quant.indicators.macd import macd_series
from guiyi_quant.indicators.policy import require_formal_policy
from guiyi_quant.indicators.registry import get_indicator


class SubingFactorStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"


class PriceSide(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    EQUAL = "equal"


class MacdCross(StrEnum):
    GOLDEN = "golden"
    DEAD = "dead"
    NONE = "none"


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


@dataclass(frozen=True, slots=True)
class SubingFactorResult:
    status: SubingFactorStatus
    snapshot: SubingFactorSnapshot | None
```

Before MACD calculation, require:

```python
policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
definition = get_indicator("macd")
assert policy.policy_id == definition.formal_policy_id
```

Use `ema_series(..., period=21, seed_policy="sma_window")`, the registry MACD defaults, and convert rounded kernel values via `Decimal(str(value))`.

Implement OLS slope with Decimal:

```python
def _regression_slope(values: Sequence[Decimal]) -> Decimal:
    n = Decimal(len(values))
    x_mean = Decimal(len(values) - 1) / Decimal(2)
    y_mean = sum(values, Decimal(0)) / n
    numerator = sum(
        (Decimal(index) - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    )
    denominator = sum(
        (Decimal(index) - x_mean) ** 2
        for index in range(len(values))
    )
    return numerator / denominator
```

Normalize with `slope / mean(ema_window) * Decimal(10000)`. Golden is previous `DIF <= DEA` and current `DIF > DEA`; Dead is mirrored. `cross_level=(DIF+DEA)/2`; zero distance is both absolute and `/ close * 10000`.

`calculate_subing_factor_series()` must compute one aligned indicator pass and return results for all input bars; `calculate_subing_factor()` returns the last result. This avoids recomputing indicators per historical bar in the Calibration plan.

- [ ] **Step 5: Run pure tests plus existing indicator tests**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

Expected: PASS; existing MACD `compatibility_validated/live_capable=False` assertions remain unchanged except the newly allowed research consumer.

- [ ] **Step 6: Align `docs/INDICATOR_KERNEL.md` with current Product Workspace facts**

Replace the stale statement that Market charts do not mount indicators with the current state: Product Workspace already renders EMA/MACD/HTDY observation, Python Kernel remains authoritative, and `web_macd_legacy_v1` is additionally allowed only for `subing_factor_observation`. Do not describe Signal capability as approved.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_research.py \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  docs/INDICATOR_KERNEL.md
git commit -m "feat: add SuBing factor core"
```

---

### Task 2: Expose the latest contiguous rank1 segment through MarketDataService

**Files:**
- Modify: `services/quant-api/app/market_data/market_data_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_catalog_and_service.py`

**Interfaces:**
- Produces: `DominantContractSegmentSummary`.
- Produces: `MarketDataService.latest_dominant_segment(symbol: str) -> DominantContractSegmentSummary`.
- `SubingReadService` must use this method instead of reading `MainContractMap` directly.

- [ ] **Step 1: Write failing service tests for contiguous current segment resolution**

Add tests covering normal rollover and missing-map fail-closed behavior:

```python
def test_latest_dominant_segment_starts_after_last_contract_change(service, seeded_catalog):
    # rank1: JM2609, JM2609, JM2610, JM2610
    result = service.latest_dominant_segment("jm")
    assert result.contract == "JM2610"
    assert result.start_trading_day == date(2026, 8, 12)
    assert result.end_trading_day == date(2026, 8, 13)


def test_latest_dominant_segment_rejects_missing_mapping_day(service, seeded_catalog):
    # remove one expected trading-day mapping inside the candidate segment
    with pytest.raises(MarketDataError, match="MAIN_CONTRACT_MAP_MISSING"):
        service.latest_dominant_segment("jm")
```

- [ ] **Step 2: Run the two focused tests and confirm the method is missing**

Run the exact new test node IDs with `pytest -q`; expected FAIL with `AttributeError`/import error for the new summary.

- [ ] **Step 3: Implement the resolver inside MarketDataService**

Add:

```python
@dataclass(frozen=True, slots=True)
class DominantContractSegmentSummary:
    symbol: str
    contract: str
    start_trading_day: date
    end_trading_day: date


def latest_dominant_segment(self, symbol: str) -> DominantContractSegmentSummary:
    mappings = self.catalog.main_map_before(symbol, None)
    if not mappings:
        raise MarketDataError("DOMINANT_CONTEXT_MISSING")
    latest = mappings[-1]
    start = latest.trade_date
    for item in reversed(mappings[:-1]):
        if item.contract != latest.contract:
            break
        start = item.trade_date
    expected_days = self.catalog.trading_days(symbol, start, latest.trade_date)
    mapping_by_day = {item.trade_date: item for item in mappings if start <= item.trade_date <= latest.trade_date}
    if any(day not in mapping_by_day for day in expected_days):
        raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
    return DominantContractSegmentSummary(symbol, latest.contract, start, latest.trade_date)
```

Do not add a new Catalog resolver or expose Catalog to SuBing.

- [ ] **Step 4: Run service/pagination regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_market_pagination.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add services/quant-api/app/market_data/market_data_service.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py
git commit -m "feat: expose current dominant segment"
```

---

### Task 3: Build `SubingReadService` on the existing Historical/Live seams

**Files:**
- Create: `services/quant-api/app/market_data/subing_read_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`

**Interfaces:**
- Consumes: `MarketDataService.latest_dominant_segment`, `MarketDataService.list_latest_dominants`, `MarketReadService.history_page/state/live_snapshot`, `calculate_subing_factor`.
- Produces: `SubingReadRequest`, `SubingReadSnapshot`, `SubingReadService.snapshot(request, now)`.

- [ ] **Step 1: Write failing tests for current segment, rollover poison and multi-timeframe cutoff**

Tests must prove:

```python
snapshot = service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now)
assert snapshot.actual_contract == "JM2610"
assert snapshot.segment_start_trading_day == date(2026, 8, 12)
assert snapshot.primary.snapshot.trading_day >= snapshot.segment_start_trading_day
assert snapshot.companion is not None
assert snapshot.companion.snapshot.bar_end <= snapshot.primary.snapshot.bar_end
```

Add a rollover poison fixture where the physical contract page also contains an older rank1 segment of the same contract; assert bars before `segment_start_trading_day` never reach the Factor core. Add a Live contract mismatch case and assert `live_observation="unavailable"`, `live_reason="contract_mismatch"`, with canonical factors still readable.

- [ ] **Step 2: Run focused tests and confirm the service is missing**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
```

Expected: FAIL on missing module/types.

- [ ] **Step 3: Implement request/snapshot contracts**

Use these stable shapes:

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

Reject unsupported frequencies with a stable `SubingReadError("SUBING_FREQUENCY_UNSUPPORTED")`.

- [ ] **Step 4: Implement segment-local primary/companion orchestration**

For each timeframe:

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

For 5m/15m only, inspect `MarketReadService.state(identity, now)`. Merge Live only when the current live contract equals the resolved rank1 contract and Live is available. Use `live_snapshot(identity, after=historical[-1].bar_end if historical else None, now=now)`, dedupe by `bar_end`, filter again to current segment, and sort.

For companion:

```python
companion_frequency = BarFrequency.M15 if request.frequency is BarFrequency.M5 else BarFrequency.M5
companion_bars = tuple(bar for bar in merged_companion if bar.bar_end <= primary_cutoff)
```

1d never reads Live and has no companion.

Set `latest_bar_source="live"` only if the final primary/companion `bar_end` came from the Live snapshot. Set `calibration_state="pending"` and never evaluate formal Signal in this plan.

- [ ] **Step 5: Add composition wiring without touching `MarketResearchService`**

Add:

```python
def build_subing_read_service(session: Session) -> SubingReadService:
    market_data = build_market_data_service(session)
    market_read = build_market_read_service(session)
    return SubingReadService(market_data=market_data, market_read=market_read)
```

Do not change `build_market_research_service()`.

- [ ] **Step 6: Run read-service and MarketRead regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py
```

Expected: PASS, including proof that P0 research remains Historical-only.

- [ ] **Step 7: Commit Task 3**

```bash
git add services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
git commit -m "feat: add SuBing read model"
```

---

### Task 4: Add the read-only SuBing HTTP contract

**Files:**
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/test_subing_api.py`

**Interfaces:**
- Endpoint: `GET /api/v1/market/research/subing?symbol=jm&frequency=5m`.
- No `series_kind` or `contract` request parameters.
- Produces nested Factor DTOs; no formal Signal DTO in this plan.

- [ ] **Step 1: Write failing API tests**

Test 200 shape, unsupported 30m -> 422, MarketDataError -> 409, and no `series_kind`/contract dependency. The 200 assertion must include:

```python
assert payload["symbol"] == "jm"
assert payload["actual_contract"] == "JM2609"
assert payload["frequency"] == "5m"
assert payload["calibration_state"] == "pending"
assert payload["primary"]["status"] in {"ready", "insufficient_data"}
assert payload["signal"] if "signal" in payload else None is None
```

Do not add a `signal` field just to satisfy this test; preferably assert `"signal" not in payload`.

- [ ] **Step 2: Run the API test and confirm 404/import failure**

Run `pytest -q services/quant-api/tests/test_subing_api.py`; expected FAIL.

- [ ] **Step 3: Add Pydantic DTOs**

Use nested models such as:

```python
class SubingFactorOut(BaseModel):
    timeframe: str
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    bar_source: str
    close: Decimal
    ema21: Decimal
    price_side: str
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
    macd_dif: Decimal
    macd_dea: Decimal
    macd_histogram: Decimal
    macd_cross: str
    macd_cross_level: Decimal
    macd_zero_distance_abs: Decimal
    macd_zero_distance_bps: Decimal
    volume: Decimal
    previous_volume: Decimal
    volume_ratio_prev: Decimal | None

class SubingFactorResultOut(BaseModel):
    status: str
    snapshot: SubingFactorOut | None

class SubingResearchResponse(BaseModel):
    symbol: str
    product_name: str
    frequency: str
    actual_contract: str
    dominant_mapping_date: date
    segment_start_trading_day: date
    source_mode: str
    live_observation: str
    live_reason: str | None
    macd_policy_id: str
    calibration_state: str
    primary: SubingFactorResultOut
    companion: SubingFactorResultOut | None
```

- [ ] **Step 4: Add the endpoint with existing error conventions**

Parse frequency through `BarFrequency`; reject anything outside the SuBing set as 422. Call `build_subing_read_service(session).snapshot(..., now=datetime.now(UTC))`. Map `ContractError`/`SubingReadError` input errors to 422 and `MarketDataError` to 409. Never expose Redis/provider/internal stack details.

- [ ] **Step 5: Run API plus Market API regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_market_research.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_subing_api.py
git commit -m "feat: expose SuBing factor research API"
```

---

### Task 5: Replace the user-facing indicator multi-select with a single research Overlay

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`

**Interfaces:**
- Produces: `ResearchOverlayId = 'none' | 'subing' | 'htdy'`.
- Produces: `visibleMainIndicatorsForOverlay(overlay)` mapping internal chart primitives.
- Preference version becomes 2; v1 preference migrates without breaking existing users.

- [ ] **Step 1: Write failing preference tests**

Require:

```ts
expect(defaultMainChartPreferences().selectedOverlay).toBe('subing')
expect(visibleMainIndicatorsForOverlay('subing')).toEqual(['ema_21'])
expect(visibleMainIndicatorsForOverlay('htdy')).toEqual(['htdy'])
expect(visibleMainIndicatorsForOverlay('none')).toEqual([])
```

Add a v1 migration case: stored `visibleMainIndicators` containing `htdy` migrates to `htdy`; all other valid old states migrate to default `subing`. Preserve stored period/realtimeFollow.

- [ ] **Step 2: Run the focused Web test and confirm failure**

```bash
pnpm --dir apps/quant-web test -- mainIndicators.test.ts
```

Expected: FAIL on missing `selectedOverlay`/helper.

- [ ] **Step 3: Change preferences to v2 without removing primitive indicator metadata**

Keep `MAIN_INDICATOR_DEFINITIONS` because Kline internals and HTDY metadata still use it. Change only user preference shape:

```ts
export type ResearchOverlayId = 'none' | 'subing' | 'htdy'

export interface MainChartPreferences {
  version: 2
  selectedOverlay: ResearchOverlayId
  period?: string | null
  realtimeFollow?: boolean
}

export function visibleMainIndicatorsForOverlay(value: ResearchOverlayId): MainIndicatorId[] {
  if (value === 'subing') return ['ema_21']
  if (value === 'htdy') return ['htdy']
  return []
}
```

Keep the same storage key, bump schema version to 2, and implement explicit v1 migration rather than silently discarding period.

- [ ] **Step 4: Convert the toolbar to a single-select Overlay**

Replace the checkbox group with a single select/radio surface containing exactly:

```ts
[
  { label: '无', value: 'none' },
  { label: '苏冰', value: 'subing' },
  { label: '火天大有', value: 'htdy' },
]
```

Add `selectedOverlay` prop and `update:selected-overlay` emit. When `selectedOverlay === 'subing'`, hide/disable the user series-kind and arbitrary-contract controls and display `当前主力 {dominantContract}` instead; the user must not choose main-continuous or arbitrary contract inside SuBing mode.

- [ ] **Step 5: Pin SuBing chart identity to the current dominant contract**

In `chart.vue`, maintain `selectedOverlay` from v2 preferences and derive internal `visibleMainIndicators` using the helper. On transition to `subing`:

```ts
function activateSubing() {
  const dominant = selectedDominant.value
  if (!dominant) return
  seriesKind.value = 'contract'
  contract.value = dominant.actual_contract
}
```

When symbol changes while SuBing is active, immediately resync `contract` from the new dominant before `refreshSeries()`. Do not use `actual_dominant` bars for the SuBing chart.

Unsupported 1m/30m/60m/1w keeps `selectedOverlay='subing'` but later SuBing API fetch must be skipped with an explicit unavailable UI state.

- [ ] **Step 6: Run preference tests and Web build**

```bash
pnpm --dir apps/quant-web test -- mainIndicators.test.ts
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue
git commit -m "feat: make research overlay single select"
```

---

### Task 6: Render SuBing Factor observation and refresh it from completed Live bars

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Create: `apps/quant-web/src/components/market/SubingStatusStrip.vue`
- Create: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/tests/subingResearch.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Consumes: `GET /market/research/subing` and the existing `useMarketSeries().mutation` completed-bar updates.
- Produces: compact status strip + detailed sidebar section; no Signal/Alert actions.

- [ ] **Step 1: Write failing API normalization tests**

Add a fixture with Decimal strings and verify:

```ts
const result = normalizeSubingResearch(payload)
expect(result.primary.snapshot?.slope_5_bps_per_bar).toBe(2.7)
expect(result.primary.snapshot?.macd_zero_distance_abs).toBe(8.3)
expect(result.companion?.snapshot?.bar_end).toBe('2026-08-13T02:15:00Z')
```

Also test a `status='insufficient_data'` factor with `snapshot=null`.

- [ ] **Step 2: Add Web DTOs and `getSubingResearch()`**

Define exact response types mirroring backend DTOs, using numeric browser values after normalization. Add:

```ts
export function getSubingResearch(params: { symbol: string; frequency: '5m' | '15m' | '1d' }) {
  return request.get<never, SubingResearchResponse>('/market/research/subing', { params })
    .then(normalizeSubingResearch)
}
```

Normalize only Decimal-valued Factor fields; keep timestamps/enum strings unchanged.

- [ ] **Step 3: Build `SubingStatusStrip.vue`**

The component must render these cases without inventing Signal semantics:

```text
ready factor:
苏冰 · Live观察 · 10:25
5m ↑ / 15m ↑
MACD 金叉 · 距零轴 8.3 · 量 3.42x
研究参数待冻结

insufficient:
苏冰 · 当前主力已切换
指标 warm-up 中 · 暂无正式判断

live unavailable:
苏冰 · Historical
Live 苏冰暂不可用
```

Do not render “买入/卖出” in this plan.

- [ ] **Step 4: Build `SubingResearchSection.vue` and mount it inside the existing sidebar**

Render primary Factor values, companion confirmed time/direction facts, current contract, segment start, source mode, and policy/calibration state. Keep existing Product Research and HTDY Alert controls intact. `ProductResearchSidebar.vue` should receive a nullable `subing` prop and mount the section first when Overlay is SuBing.

- [ ] **Step 5: Add snapshot lifecycle to `chart.vue`**

Maintain generation counters just like existing Product Research to drop stale async responses. Fetch on:

```text
initial metadata ready
symbol change
frequency change
Overlay enters subing
completed primary Live mutation
```

Only call the endpoint for `5m|15m|1d`. Clear the snapshot for unsupported frequency.

On a 5m completed bar that is also a 15m boundary, if the first response has `companion.snapshot.bar_end < primary.snapshot.bar_end`, schedule exactly one delayed refresh; store the timeout handle and clear it on identity change/unmount. Do not poll.

- [ ] **Step 6: Extend the existing Market Research E2E mock**

Mock `/api/v1/market/research/subing` and assert:

```text
Overlay options are exactly 无/苏冰/火天大有
苏冰 selects current dominant real contract
EMA21 is visible through existing chart primitive mapping
status strip shows Factor observation, not a trade command
switching to 火天大有 hides SuBing strip and preserves HTDY repaint warning
unsupported 30m keeps 苏冰 selected but shows unavailable
```

- [ ] **Step 7: Run Web unit/E2E/build regressions**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS; Alert V1 UI regression stays green.

- [ ] **Step 8: Commit Task 6**

```bash
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/components/market/SubingStatusStrip.vue \
  apps/quant-web/src/components/market/SubingResearchSection.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat: show SuBing factor observation"
```

---

### Task 7: Close canonical, test and regression boundaries for Factor Observation

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md` only if implementation is actually complete and all required local verification passes.

**Interfaces:**
- No new runtime interface.
- Completion state remains Factor Observation / Calibration pending; no Signal Ready claim.

- [ ] **Step 1: Add a no-side-effect SuBing validation block to `TESTING.md`**

Document only commands that do not mutate Runtime/DB/Canonical:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/api/market.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 2: Align `docs/ARCHITECTURE.md`**

Add `SubingReadService` as a thin Market research read seam between MarketDataService/MarketReadService and Product Workspace. Explicitly state that it has no provider, Redis direct access, storage or Runtime responsibility and that existing `MarketResearchService` remains Historical-only.

- [ ] **Step 3: Run the full affected backend validation**

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
```

Expected: all required checks PASS.

- [ ] **Step 4: Run engineering and tracked-content checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: no secret findings, no whitespace errors, only intended task files modified.

- [ ] **Step 5: Update `STATUS.md` conservatively if and only if Tasks 1-6 and all validations passed**

Record only:

```text
SuBing Factor Observation code complete on develop
1d/5m/15m current-rank1 segment-local read model available
5m/15m completed Live Factor observation implemented
Calibration remains pending
formal Entry Signal not implemented
Alert V1 unchanged
no Runtime deployment/promotion performed
```

Do not claim Signal/Alert/Runtime Ready.

- [ ] **Step 6: Commit Task 7**

```bash
git add TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: record SuBing factor observation boundaries"
```

---

## Plan Acceptance

This plan is complete when Factor Observation is independently usable and testable on `develop`, while all of the following remain true:

```text
Calibration = pending
formal Signal = not implemented
Alert V1 = unchanged
Runtime = untouched
Data Foundation = unchanged
no pre-rank1 warm-up
no cross-roll indicator state
no new persistence/cache/runtime component
```

Do not start `2026-08-13-subing-calibration-entry-signal-v1.md` until this plan is green and independently reviewed.