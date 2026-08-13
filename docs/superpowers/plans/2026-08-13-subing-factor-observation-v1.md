# SuBing Factor Observation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、Alert V1 或 Runtime 的前提下，交付当前 rank1 segment 的 1d/5m/15m 苏冰 Factor 只读观察，包括 completed Live 5m/15m、`无/苏冰/火天大有` 单选 Overlay 和 Product Workspace 研究展示。

**Architecture:** 新增 zero-I/O `subing_research.py` 作为 Factor 计算核心；新增薄 `SubingReadService` 作为 current-rank1/segment/primary-companion/Historical-Live orchestration seam。现有 `MarketResearchService` 继续 Historical-only，Historical 只经 `MarketDataService`，Live 只经 `MarketReadService`，换月后严格 rank1-segment-local warm-up；苏冰模式的**可见 Kline 本身也必须截断在 current rank1 segment**，不能只截 Factor。

**Tech Stack:** Python 3 / FastAPI / Decimal / quant-core Indicator Kernel / PostgreSQL Catalog read path / Redis Live Overlay via `MarketReadService` / Vue 3 / TypeScript / Naive UI / Lightweight Charts / Vitest / Playwright.

## Global Constraints

- 设计事实源：`docs/superpowers/specs/2026-08-13-subing-factor-signal-research-design.md`。
- 不修改 `DatasetKey`、八表 Market Catalog、Canonical、月分区或 contract rank1-day coverage 语义。
- 不直接读 Parquet、不直接读 Redis、不调用 RQData；Historical 经 `MarketDataService`，Live 经 `MarketReadService`。
- 不修改 `MarketResearchService` 的 P0 Historical-only 合同。
- 不修改 `alert_rules`、`alert_events`、Alert Runtime、HTDY evaluator、WeCom sender 或任何 Runtime 状态。
- 当前阶段只做 Factor Observation；不得输出正式 `MATCHED LONG/SHORT` Signal，不得自行填 Calibration。
- MACD 仅允许 `web_macd_legacy_v1` 作为明确命名的 research Factor observation policy；不得在本计划中晋升 generic `macd` 的 live/backtest/alert capability。
- 苏冰只支持 `1d / 5m / 15m`；5m/15m 只消费 completed Live bars。
- 当前品种自动使用 latest rank1 真实 contract，并只使用 current rank1 segment；不得跨换月继承 EMA/MACD，不得读取 pre-rank1 contract 数据补 warm-up。
- SuBing 模式 Kline、EMA21、MACD、Factor 必须使用同一 current rank1 segment；不得让图表向左分页显示 segment 之前的同 contract 历史。
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
- `apps/quant-web/src/pages/market/chart.vue` — current-rank1 contract pinning, segment-clipped visible Kline, SuBing snapshot fetch and completed-bar refresh.
- `apps/quant-web/e2e/market-research.spec.mjs` — Product Workspace regression and SuBing UI behavior.
- `TESTING.md` — add no-side-effect SuBing validation entry.
- `docs/ARCHITECTURE.md` — add thin `SubingReadService` read seam after implementation is real.
- `STATUS.md` — only if code and required tests actually complete.

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
- Later tasks pass only one current-segment `CanonicalBar` sequence into these functions.

- [ ] **Step 1: Write failing tests for Factor math and policy guard**

Create deterministic local bar builders in the test file; do not depend on undeclared fixtures. Require the new interfaces and verify exact semantics:

```python
from decimal import Decimal

from app.market_data.domain import BarFrequency
from app.market_data.subing_research import (
    PriceSide,
    SubingFactorStatus,
    calculate_subing_factor,
)


def test_subing_factor_reports_price_slope_macd_and_volume():
    bars = _ready_bars(count=48, final_volume=Decimal("300"), previous_volume=Decimal("100"))
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
    assert result.snapshot.slope_5_bps_per_bar is not None
    assert result.snapshot.slope_10_bps_per_bar is not None
    assert result.snapshot.volume_ratio_prev == Decimal("3")


def test_subing_factor_returns_insufficient_when_segment_warmup_is_short():
    bars = _ready_bars(count=20)
    result = calculate_subing_factor(
        bars,
        timeframe=BarFrequency.M15,
        contract="JM2609",
        segment_start_trading_day=bars[0].trading_day,
        latest_bar_source="canonical",
    )
    assert result.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.snapshot is None
```

Add focused tests for Golden/Dead cross equality edges, `previous_volume <= 0`, strict increasing `bar_end`, and any bar whose `trading_day < segment_start_trading_day` being rejected.

- [ ] **Step 2: Run the new tests and confirm they fail because the module does not exist**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py
```

Expected: FAIL on missing `app.market_data.subing_research` or missing exported symbols.

- [ ] **Step 3: Add the explicit MACD Factor-observation policy consumer without promoting MACD**

Update only `web_macd_legacy_v1`:

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

- [ ] **Step 4: Implement pure Factor types and calculations**

Use exact policy IDs and Decimal outputs:

```python
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

Before MACD calculation:

```python
policy = require_formal_policy("web_macd_legacy_v1", consumer="subing_factor_observation")
definition = get_indicator("macd")
assert policy.policy_id == definition.formal_policy_id
```

Use `ema_series(..., period=21, seed_policy="sma_window")` and the registry MACD defaults. Convert rounded kernel values with `Decimal(str(value))`.

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
    denominator = sum(
        (Decimal(index) - x_mean) ** 2
        for index in range(len(values))
    )
    return numerator / denominator
```

Normalize with `slope / mean(ema_window) * Decimal(10000)`. Golden: previous `DIF <= DEA` and current `DIF > DEA`; Dead mirrored. `cross_level=(DIF+DEA)/2`; zero distance is absolute and `/close*10000`.

`calculate_subing_factor_series()` performs one aligned EMA/MACD pass and returns one `SubingFactorResult` per input bar. A bar is READY only when current EMA21, last 10 ready EMA21 values, current+previous ready DIF/DEA, current volume and previous volume are available. `calculate_subing_factor()` returns the last result.

- [ ] **Step 5: Run pure tests plus existing Indicator regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

Expected: PASS; generic MACD capability remains unchanged.

- [ ] **Step 6: Align `docs/INDICATOR_KERNEL.md`**

Replace the stale claim that Product Workspace does not mount indicators with the current EMA/MACD/HTDY observation facts. Document `subing_factor_observation` as research-only and explicitly state that formal Signal capability is still pending.

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

- [ ] **Step 1: Write failing service tests using existing `session` and `tmp_path` fixtures**

Seed exact calendar/map rows inside each test:

```python
def test_latest_dominant_segment_starts_after_last_contract_change(session, tmp_path):
    catalog = MarketCatalog(session, tmp_path)
    session.add_all(
        TradingCalendar("DCE", date(2025, 1, 2), True),
        TradingCalendar("DCE", date(2025, 1, 3), True),
        TradingCalendar("DCE", date(2025, 1, 6), True),
        TradingCalendar("DCE", date(2025, 1, 7), True),
    )
    catalog.upsert_main_contracts((
        ("jm", date(2025, 1, 2), "JM2505"),
        ("jm", date(2025, 1, 3), "JM2505"),
        ("jm", date(2025, 1, 6), "JM2509"),
        ("jm", date(2025, 1, 7), "JM2509"),
    ))
    session.commit()
    service = MarketDataService(catalog, CanonicalMonthlyStore(tmp_path))
    result = service.latest_dominant_segment("jm")
    assert result.contract == "JM2509"
    assert result.start_trading_day == date(2025, 1, 6)
    assert result.end_trading_day == date(2025, 1, 7)
```

For the missing-map test, seed trading days Jan 6/7 but only map Jan 7 to JM2509 and ensure the resolver raises `MarketDataError("MAIN_CONTRACT_MAP_MISSING")` rather than silently setting segment start Jan 7.

- [ ] **Step 2: Run exact new test node IDs and confirm failure**

Expected: FAIL because `latest_dominant_segment`/summary do not exist.

- [ ] **Step 3: Implement resolver inside MarketDataService**

```python
@dataclass(frozen=True, slots=True)
class DominantContractSegmentSummary:
    symbol: str
    contract: str
    start_trading_day: date
    end_trading_day: date
```

Algorithm:
1. `main_map_before(symbol, None)`; empty -> `DOMINANT_CONTEXT_MISSING`.
2. Let latest mapping be the current contract/end day.
3. Walk mappings backward while the contract is unchanged to find tentative start.
4. Query formal trading days between tentative start and end.
5. Every expected trading day must have a rank1 mapping and the same current contract; otherwise `MAIN_CONTRACT_MAP_MISSING`.
6. Return the summary.

Do not add a second Catalog resolver.

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

### Task 3: Build `SubingReadService` on existing Historical/Live seams

**Files:**
- Create: `services/quant-api/app/market_data/subing_read_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`

**Interfaces:**
- Consumes: `MarketDataService.latest_dominant_segment`, `MarketDataService.list_latest_dominants`, `MarketReadService.history_page/state/live_snapshot`, `calculate_subing_factor`.
- Produces: `SubingReadRequest`, `SubingReadSnapshot`, `SubingReadService.snapshot(request, now)`.

- [ ] **Step 1: Write failing tests for segment isolation, Live mismatch and multi-TF cutoff**

Use local fakes in the new test file; do not rely on Redis/production DB. Require:

```python
snapshot = service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now)
assert snapshot.actual_contract == "JM2610"
assert snapshot.segment_start_trading_day == date(2026, 8, 12)
assert snapshot.primary.snapshot is None or snapshot.primary.snapshot.trading_day >= date(2026, 8, 12)
assert snapshot.companion is not None
if snapshot.primary.snapshot and snapshot.companion.snapshot:
    assert snapshot.companion.snapshot.bar_end <= snapshot.primary.snapshot.bar_end
```

Rollover poison: make the physical contract page also contain an older, non-current segment of the same contract and assert those bars never enter the Factor core.

Live contract mismatch: current rank1 JM2610 but MarketRead state reports JM2609; assert canonical Factor remains readable, `live_observation="unavailable"`, `live_reason="contract_mismatch"`, and no live bar is merged.

- [ ] **Step 2: Run focused tests and confirm missing module/types**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
```

Expected: FAIL.

- [ ] **Step 3: Implement request/snapshot contracts**

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

Unsupported frequency -> stable `SubingReadError("SUBING_FREQUENCY_UNSUPPORTED")`.

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

For 5m/15m only, inspect `MarketReadService.state(identity, now)`. Merge Live only when live contract equals current rank1 contract and Live is available. Use `live_snapshot(identity, after=historical[-1].bar_end if historical else None, now=now)`, dedupe by `bar_end`, filter current segment again, and sort.

Companion frequency is 15m for 5m primary and 5m for 15m primary; slice companion to `bar_end <= primary_cutoff` before Factor calculation. 1d never reads Live and has no companion.

Set `latest_bar_source="live"` only if the final selected bar came from Live. Set `calibration_state="pending"`; formal Signal evaluation is forbidden in this plan.

- [ ] **Step 5: Add composition wiring without touching `MarketResearchService`**

```python
def build_subing_read_service(session: Session) -> SubingReadService:
    market_data = build_market_data_service(session)
    market_read = build_market_read_service(session)
    return SubingReadService(market_data=market_data, market_read=market_read)
```

- [ ] **Step 6: Run read-service and MarketRead regressions**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_research.py
```

Expected: PASS and P0 research remains Historical-only.

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

Test 200 shape, unsupported 30m -> 422, MarketDataError -> 409, and no `series_kind`/contract dependency:

```python
assert payload["symbol"] == "jm"
assert payload["actual_contract"] == "JM2609"
assert payload["frequency"] == "5m"
assert payload["calibration_state"] == "pending"
assert payload["primary"]["status"] in {"ready", "insufficient_data"}
assert "signal" not in payload
```

- [ ] **Step 2: Run the API test and confirm 404/import failure**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_subing_api.py
```

Expected: FAIL.

- [ ] **Step 3: Add Pydantic DTOs**

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

- [ ] **Step 4: Add endpoint with existing error conventions**

Parse via `BarFrequency`; unsupported SuBing timeframe -> 422. Call `build_subing_read_service(session).snapshot(..., now=datetime.now(UTC))`. Map `ContractError`/input `SubingReadError` to 422 and `MarketDataError` to 409; never expose Redis/provider/internal details.

- [ ] **Step 5: Run API regressions**

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

### Task 5: Replace user-facing indicator multi-select with one research Overlay

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`

**Interfaces:**
- Produces: `ResearchOverlayId = 'none' | 'subing' | 'htdy'`.
- Produces: `visibleMainIndicatorsForOverlay(overlay)`.
- Preference schema becomes version 2 with explicit v1 migration.

- [ ] **Step 1: Write failing preference tests**

```ts
expect(defaultMainChartPreferences().selectedOverlay).toBe('subing')
expect(visibleMainIndicatorsForOverlay('subing')).toEqual(['ema_21'])
expect(visibleMainIndicatorsForOverlay('htdy')).toEqual(['htdy'])
expect(visibleMainIndicatorsForOverlay('none')).toEqual([])
```

Stored v1 with `htdy` visible -> `htdy`; every other valid v1 visible-indicator state -> default `subing`. Preserve period/realtimeFollow.

- [ ] **Step 2: Run focused Web test and confirm failure**

```bash
pnpm --dir apps/quant-web test -- mainIndicators.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Change preferences to v2 without removing primitive metadata**

Keep `MAIN_INDICATOR_DEFINITIONS` for chart internals/HTDY metadata. Add:

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

Same storage key; schema version 2; explicit migration.

- [ ] **Step 4: Convert toolbar to one Overlay selector**

Exactly:

```ts
[
  { label: '无', value: 'none' },
  { label: '苏冰', value: 'subing' },
  { label: '火天大有', value: 'htdy' },
]
```

Add `selectedOverlay` prop and `update:selected-overlay` emit. In SuBing mode hide/disable user series-kind/arbitrary-contract controls and show `当前主力 {dominantContract}`; user cannot choose continuous/arbitrary contract inside SuBing.

- [ ] **Step 5: Pin SuBing chart identity to current dominant on initial load and every symbol change**

```ts
function activateSubing() {
  const dominant = selectedDominant.value
  if (!dominant) return
  seriesKind.value = 'contract'
  contract.value = dominant.actual_contract
}
```

Call `activateSubing()` **after dominants metadata is loaded but before the initial `refreshSeries()`** when default/current Overlay is SuBing. Also call it before `refreshSeries()` on every symbol change while SuBing is selected and on transitions into SuBing. Do not use actual-dominant Kline in SuBing mode.

Unsupported 1m/30m/60m/1w keeps Overlay selected but Factor fetch is skipped later with explicit unavailable UI.

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

### Task 6: Render segment-clipped SuBing Factor observation and refresh from completed Live bars

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
- Consumes: `GET /market/research/subing` and existing completed-bar `mutation` events.
- Produces: current-segment visible Kline + compact Factor strip + detailed sidebar section; no Signal/Alert actions.

- [ ] **Step 1: Write failing API normalization/helper tests**

```ts
const result = normalizeSubingResearch(payload)
expect(result.primary.snapshot?.slope_5_bps_per_bar).toBe(2.7)
expect(result.primary.snapshot?.macd_zero_distance_abs).toBe(8.3)
expect(result.companion?.snapshot?.bar_end).toBe('2026-08-13T02:15:00Z')
expect(filterBarsToSubingSegment(bars, '2026-08-12').every((bar) => bar.trading_day >= '2026-08-12')).toBe(true)
```

Also test `status='insufficient_data'` with `snapshot=null` and a segment filter containing old same-contract bars.

- [ ] **Step 2: Add Web DTOs, normalization and segment helper**

```ts
export function getSubingResearch(params: { symbol: string; frequency: '5m' | '15m' | '1d' }) {
  return request.get<never, SubingResearchResponse>('/market/research/subing', { params })
    .then(normalizeSubingResearch)
}

export function filterBarsToSubingSegment(bars: BarData[], segmentStart: string): BarData[] {
  return bars.filter((bar) => (bar.trading_day || '') >= segmentStart)
}
```

Normalize Decimal-valued Factor fields only.

- [ ] **Step 3: Build `SubingStatusStrip.vue`**

Render Factor-only states:

```text
READY:
苏冰 · Live观察 · 10:25
5m ↑ / 15m ↑
MACD 金叉 · 距零轴 8.3 · 量 3.42x
研究参数待冻结

INSUFFICIENT:
苏冰 · 当前主力已切换
指标 warm-up 中 · 暂无正式判断

LIVE unavailable:
苏冰 · Historical
Live 苏冰暂不可用
```

Do not render 买入/卖出 in this plan.

- [ ] **Step 4: Build `SubingResearchSection.vue` and mount in existing sidebar**

Display primary Factor values, companion confirmed time/direction facts, current contract, segment start, source mode and policy/calibration state. Existing Product Research and HTDY Alert controls remain intact.

- [ ] **Step 5: Make current rank1 segment own the SuBing visible chart range**

In `chart.vue` derive:

```ts
const visibleBars = computed(() => {
  if (selectedOverlay.value !== 'subing') return bars.value
  const start = subing.value?.segment_start_trading_day
  return start ? filterBarsToSubingSegment(bars.value, start) : []
})
```

While SuBing snapshot is loading, do not briefly render unbounded contract bars; show chart loading/empty state until segment start is known.

Pass `visibleBars` to `KlineChart`. In the existing `mutation` watcher, when SuBing is selected, rebuild the chart from `visibleBars` rather than forwarding an unfiltered prepend/update directly. This low-frequency replace is acceptable for V1 and prevents any pre-segment bar from entering EMA/MACD browser mirrors.

`loadEarlierBars()` must no-op once the earliest visible bar is at `segment_start_trading_day`; if an underlying page fetch returns bars before the segment, they may stay in `useMarketSeries` internal state but must never become visible or feed Kline-derived EMA/MACD.

- [ ] **Step 6: Add SuBing snapshot lifecycle and completed-Live refresh**

Use a generation counter to discard stale HTTP responses. Fetch on initial metadata-ready state, symbol/frequency changes, transition into SuBing and completed primary Live mutation. Only call for 5m/15m/1d; unsupported frequency clears snapshot into explicit unavailable state.

At a common 15m boundary on a 5m page, if first response has `companion.snapshot.bar_end < primary.snapshot.bar_end`, schedule exactly one delayed refresh; clear the timer on identity change/unmount. No polling.

- [ ] **Step 7: Extend Market Research E2E**

Mock `/api/v1/market/research/subing` and assert:

```text
Overlay options exactly 无/苏冰/火天大有
initial default SuBing uses current dominant real contract before first series request
old same-contract bars before segment_start are not rendered
EMA21 is the only SuBing main overlay
status strip shows Factor observation, not trade command
火天大有 hides SuBing strip and preserves HTDY repaint warning
unsupported 30m keeps 苏冰 selected but shows unavailable
```

- [ ] **Step 8: Run Web unit/E2E/build regressions**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 9: Commit Task 6**

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

- [ ] **Step 1: Add no-side-effect SuBing validation to `TESTING.md`**

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

Add `SubingReadService` as a thin seam between `MarketDataService`/`MarketReadService` and Product Workspace. State explicitly: no provider, no Redis direct access, no storage/Runtime responsibility; existing `MarketResearchService` remains Historical-only.

- [ ] **Step 3: Run full affected backend validation**

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

Expected: PASS.

- [ ] **Step 4: Run engineering/tracked-content checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: no secret findings, no whitespace errors, only intended task files modified.

- [ ] **Step 5: Update `STATUS.md` conservatively only after Tasks 1-6 and validation pass**

Record only:

```text
SuBing Factor Observation code complete on develop
1d/5m/15m current-rank1 segment-local read model available
SuBing visible Kline is current-rank1-segment-local
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
Kline/EMA/MACD/Factor = current rank1 segment only
no pre-rank1 warm-up
no cross-roll indicator state
no new persistence/cache/runtime component
```

Do not start `2026-08-13-subing-calibration-entry-signal-v1.md` until this plan is green and independently reviewed.