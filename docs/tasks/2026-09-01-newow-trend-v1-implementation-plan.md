# Newow 牛哇版本 · 日线趋势详情页 V1 Implementation Plan

日期：2026-09-01  
状态：`IMPLEMENTATION_PLAN_COMPLETE / INTERNAL_PLAN_REVIEW_PASSED / SOURCE_IMPLEMENTATION_NOT_STARTED`  

> 本文完整替换此前标记为 `SUPERSEDED / DO_NOT_EXECUTE` 的旧计划，是最新版 `docs/tasks/2026-09-01-newow-trend-v1-design.md` 的唯一实施计划。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不影响当前版本、已退役策略边界、HTDY、Alert 或 Runtime 的前提下，实现一套独立的“牛哇版本 · 趋势策略 · 日线详情页”，完整呈现牛哇黄蓝趋势带、建仓/清仓状态、D1/D2/D3、杯柄和牛哇式主图交互。

**Architecture:** `quant-core` 保存 NumPy-only 的 Newow 权威公式；`quant-api` 只通过 `MarketDataService` 读取 `actual_dominant + completed D1`，按真实物理合约段驱动同一个 `NewowTrendD1Engine.step()`；Web 使用独立 `NewowTrendDetailView` 和独立图表组件，现有 `chart.vue` 仅负责 `current/newow` 子页面分流。V1 不建立通用策略平台、数据库表、Redis 状态、Worker、全市场扫描、通知或自动交易。

**Tech Stack:** Python 3.13、NumPy 2.4+、FastAPI/Pydantic、Vue 3、TypeScript 6、lightweight-charts 5、Naive UI、Node test runner、Playwright。

**Spec:** `docs/tasks/2026-09-01-newow-trend-v1-design.md`

## Global Constraints

- 唯一产品身份：`display_name=牛哇趋势策略`、`strategy_code=newow_trend_v1`、`profile_id=newow_trend_d1_v1`。
- 唯一数据身份：`series_kind=actual_dominant`、`frequency=1d`、`bar_policy=completed_only`。
- Newow 只复用数据底座，不读取或继承已退役策略、HTDY、现有趋势 Overlay、Alert、Episode、Context 或前端指标结果。
- 黄蓝主趋势带使用 `newow_trend_band_cleanroom_v1`；D1/D2/D3 使用 `newow_escape_d123_v1`；杯柄使用 `newow_cup_handle_v1`。
- 蓝色只表示牛哇原始语义中的“空仓/风险阶段”，V1 不生成期货空单。
- V1 不实现底部三个副图、目标价、吸筹价、点阵、收益曲线、综合决策、仓位建议、震荡策略、其他形态、active60、Shadow、PushPlus 或 Runtime。
- 所有正式输出必须 completed-only、strict-before、prefix invariant、batch/incremental parity、same-physical-contract isolated、rollover-reset、first-seen immutable、fail-closed。
- 杯柄锚点允许绘制在 `pivot_at`，但状态不得早于 `confirmed_at`；READY 后锚点、突破位和分数冻结。
- 不新增 PostgreSQL 表、Alembic migration、Redis key、队列、Worker、账户、订单、仓位或 PnL。
- HTTP 只读；不得触发 RQData 下载、Canonical 写入、production DB/Redis 写入或任何外部通知。
- UI 和文案以用户提供的牛哇录屏、截图及手册为参考；无参考内容不自行扩展。
- 每个交付 Slice 使用一个独立 branch/worktree；Slice 内按任务先写失败测试、保持小提交，Slice 完成后独立 Review 再集成 `develop`。不为十四个任务创建十四套并行分支；本计划合入不授权自动实施。

---

## File Structure

### Quant Core

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py          # Newow immutable contracts and enums
├── profile.py         # frozen V1 parameters and formula digests
├── trend_band.py      # P/B/C values and yellow/blue state transitions
├── escape_d123.py     # VAR4, MA120, Amplitude30 and D1/D2/D3
├── cup_handle.py      # dedicated pivots, candidate scoring and lifecycle
└── engine.py          # one completed-D1 step pipeline
```

### Application / API

```text
services/quant-api/app/market_data/newow/
├── __init__.py
├── trend_detail_service.py
└── trend_detail_query.py

services/quant-api/app/schemas/market_newow.py
services/quant-api/app/api/market_newow.py
services/quant-api/app/main.py
```

### Web

```text
apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/composables/useNewowTrendDetail.ts
apps/quant-web/src/utils/marketDetailView.ts
apps/quant-web/src/utils/newowViewModel.ts
apps/quant-web/src/utils/newowChartModel.ts
apps/quant-web/src/utils/newowCopy.ts
apps/quant-web/src/pages/market/NewowTrendDetailView.vue
apps/quant-web/src/components/market/CurrentMarketDetailView.vue
apps/quant-web/src/components/newow/NewowHeader.vue
apps/quant-web/src/components/newow/NewowTrendChart.vue
apps/quant-web/src/components/newow/NewowIndicatorSheet.vue
apps/quant-web/src/components/newow/NewowSignalHistorySheet.vue
apps/quant-web/src/components/newow/NewowCupHandleSheet.vue
apps/quant-web/src/components/newow/newowTrendBandPrimitive.ts
apps/quant-web/src/components/newow/newowCupHandlePrimitive.ts
apps/quant-web/src/styles/newowTokens.ts
apps/quant-web/src/pages/market/chart.vue
```

### Tests / Reference Fixtures

```text
services/quant-api/tests/newow/
├── conftest.py
├── fixtures.py
├── test_models_profile.py
├── test_trend_band.py
├── test_escape_d123.py
├── test_cup_handle.py
├── test_engine_causality.py
├── test_trend_detail_service.py
└── test_market_newow_api.py

apps/quant-web/tests/newowTypes.test.ts
apps/quant-web/tests/newowViewModel.test.ts
apps/quant-web/tests/newowRoute.test.ts
apps/quant-web/tests/newowChartModel.test.ts
apps/quant-web/tests/newowCopy.test.ts
apps/quant-web/e2e/newow-trend-detail.spec.mjs
apps/quant-web/e2e/fixtures/newow-trend-detail.json

docs/tasks/fixtures/newow/
├── reference-index.json
└── README.md
```

---

### Task 1: Freeze Reference Matrix, Contracts, and V1 Profile

**Files:**
- Create: `docs/tasks/fixtures/newow/reference-index.json`
- Create: `docs/tasks/fixtures/newow/README.md`
- Create: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Create: `packages/quant-core/guiyi_quant/newow/models.py`
- Create: `packages/quant-core/guiyi_quant/newow/profile.py`
- Create: `services/quant-api/tests/newow/__init__.py`
- Create: `services/quant-api/tests/newow/conftest.py`
- Create: `services/quant-api/tests/newow/fixtures.py`
- Create: `services/quant-api/tests/newow/test_models_profile.py`

**Interfaces:**
- Consumes: no Newow code.
- Produces:
  - `NewowTrendProfile`
  - `NewowDailyBar`
  - `TrendBandState`
  - `TrendTransition`
  - `NewowMarkerType`
  - `EscapeSeverity`
  - `CupHandleDirection`
  - `CupHandleState`
  - `NewowTrendBandPoint`
  - `NewowMainMarker`
  - `NewowCupHandleOverlay`
  - `NewowTrendFrame`
  - `NEWOW_TREND_D1_V1`

- [ ] **Step 1: Record the exact reference inventory**

Create `reference-index.json` with stable IDs rather than copying binary screenshots into Git:

```json
{
  "schema_version": 1,
  "references": [
    {
      "id": "NEWOW-DETAIL-VIDEO-20260901",
      "kind": "user_video",
      "sha256": "204176376e0df5679b4ab45d511818b3a8130dbaa175136ca35eb06f0567bd63",
      "description": "牛哇详情页纵向录屏：顶部、趋势策略、主图、标记、弹层、历史入口",
      "required_for": ["layout", "interaction", "trend_band", "markers"]
    },
    {
      "id": "NEWOW-DETAIL-HEADER-20260901",
      "kind": "user_screenshot",
      "sha256": "a3e634e64b116f1b245de2c6cddfc4677edfd9ae8e04bd86ea6ab1817466de01",
      "description": "详情页顶部信息、日K胶囊、收藏/历史入口与趋势策略选中态",
      "required_for": ["header", "spacing", "strategy_chip"]
    },
    {
      "id": "NEWOW-CONTROL-SHEET-20260901",
      "kind": "user_screenshot",
      "sha256": "e2a8b9eb0707c98c3cc825ac167a4a91d5dde1791dfce0674c4fb76f197ae13c",
      "description": "主力控盘指标解读弹层；V1只参考弹层结构，副图公式明确后移",
      "required_for": ["modal_shell"]
    },
    {
      "id": "NEWOW-DYNAMIC-SHEET-20260901",
      "kind": "user_screenshot",
      "sha256": "81a0b5580081d0e1d14b1401532d876c221ba7a58d7635449df38136718904e6",
      "description": "主力动态指标解读弹层；V1只参考弹层结构，副图公式明确后移",
      "required_for": ["modal_shell"]
    },
    {
      "id": "NEWOW-D123-MODAL-20260901",
      "kind": "user_screenshot",
      "sha256": "7fdde4f233fd51928c306907445c4ee65949af49c4e0ded3a787350acbf827ac",
      "description": "首页 D1/D2/D3 逃顶条件、文案、颜色和排列顺序",
      "required_for": ["escape_d123", "copy", "colors"]
    },
    {
      "id": "NEWOW-MOMENTUM-SHEET-20260901",
      "kind": "user_screenshot",
      "sha256": "e18e0ce2344a57531159baad0ff6a9f4c99599b007d7149573373c33b3c9d975",
      "description": "涨跌动能指标解读弹层；V1只参考弹层结构，副图公式明确后移",
      "required_for": ["modal_shell"]
    },
    {
      "id": "NEWOW-CUPHANDLE-V36-20260901",
      "kind": "user_screenshot",
      "sha256": "5b42ac554b2376bbba1616be24a2a6844d88beb6c40310df19c7c4e26105323e",
      "description": "v3.6 杯柄成交量、V形扣分、前置趋势、柄长和10%杯深说明",
      "required_for": ["cup_handle"]
    }
  ]
}
```

`README.md` must state:

```text
Binary references remain outside Git.
Tests use synthetic fixtures derived from explicitly documented behavior.
When a visual or formula mismatch appears, request another Newow screenshot/recording;
do not search for substitute indicators or tune by returns.
```

- [ ] **Step 2: Write failing contract tests**

```python
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import (
    CupHandleState,
    NewowDailyBar,
    TrendBandState,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_V1


def test_newow_profile_is_exact_and_immutable() -> None:
    profile = NEWOW_TREND_D1_V1
    assert profile.profile_id == "newow_trend_d1_v1"
    assert profile.frequency == "1d"
    assert profile.trend_band_formula == "newow_trend_band_cleanroom_v1"
    assert profile.escape_formula == "newow_escape_d123_v1"
    assert profile.cup_handle_formula == "newow_cup_handle_v1"
    with pytest.raises(FrozenInstanceError):
        profile.frequency = "60m"  # type: ignore[misc]


def test_newow_daily_bar_requires_completed_d1_and_valid_ohlc() -> None:
    with pytest.raises(ValueError, match="NEWOW_BAR_NOT_COMPLETED"):
        NewowDailyBar(
            product="rb",
            physical_contract="RB2701",
            segment_id="rb:RB2701:2026-01-01",
            trading_day=date(2026, 1, 5),
            bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
            open=Decimal("3500"),
            high=Decimal("3520"),
            low=Decimal("3480"),
            close=Decimal("3510"),
            volume=100,
            open_interest=200,
            source_identity="fixture:rb:RB2701:1d",
            observation_eligible=True,
            completed=False,
        )


def test_enum_values_are_stable() -> None:
    assert TrendBandState.YELLOW.value == "YELLOW"
    assert TrendBandState.BLUE.value == "BLUE"
    assert CupHandleState.READY.value == "READY"
```

- [ ] **Step 3: Run the tests and verify failure**

Run:

```bash
cd services/quant-api
uv run pytest tests/newow/test_models_profile.py -q
```

Expected: collection fails because `guiyi_quant.newow` does not exist.

- [ ] **Step 4: Implement immutable contracts and profile**

`models.py` must:
- use `@dataclass(frozen=True, slots=True)`;
- validate uppercase physical contracts and lowercase products;
- use `Decimal` for price values;
- reject incomplete Bars, invalid OHLC envelopes, negative volume/OI, naive timestamps, and empty identities;
- define `observation_eligible: bool`: same-contract warm-up Bars are `False`; formal rank1 Bars are `True`;
- keep formula values as `float | None` only inside calculated series objects;
- define stable string enums exactly matching the API payload.

`profile.py` must define:

```python
@dataclass(frozen=True, slots=True)
class NewowTrendProfile:
    profile_id: str
    frequency: str
    trend_band_formula: str
    escape_formula: str
    cup_handle_formula: str
    typical_price_close_weight: float
    trend_weight_period: int
    trend_signal_period: int
    var4_lookback: int
    var4_smoothing_n: int
    var4_smoothing_m: int
    ma120_period: int
    ma120_slope_window: int
    ma120_flat_threshold: float
    cup_reversal_atr: float
    cup_min_leg_bars: int
    cup_history_limit: int
    cup_max_confirmed_pivots: int
    cup_max_candidate_checks_per_step: int
```

Freeze `NEWOW_TREND_D1_V1` with values copied from the Spec.

- [ ] **Step 5: Run focused tests**

```bash
cd services/quant-api
uv run pytest tests/newow/test_models_profile.py -q
```

Expected: PASS.

- [ ] **Step 6: Run lint and type checks for the new package**

```bash
cd services/quant-api
uv run ruff check ../../packages/quant-core/guiyi_quant/newow tests/newow/test_models_profile.py
uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  docs/tasks/fixtures/newow \
  packages/quant-core/guiyi_quant/newow \
  services/quant-api/tests/newow
git commit -m "feat(newow): add immutable D1 contracts and reference matrix"
```

**Review Gate:** reject if the contracts contain retired-strategy/HTDY fields, generic strategy registration, OPEN/CLOSE/position semantics, mutable event objects, or frequency branches.

---

### Task 2: Implement the Yellow/Blue Trend Band and Build/Clear Markers

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/trend_band.py`
- Create: `services/quant-api/tests/newow/test_trend_band.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`

**Interfaces:**
- Consumes:
  - `NewowTrendProfile`
  - `NewowDailyBar`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class TrendBandStateValue:
    weighted_window: tuple[float, ...]
    signal_window: tuple[float, ...]
    previous_state: TrendBandState | None

@dataclass(frozen=True, slots=True)
class TrendBandStepResult:
    state: TrendBandStateValue
    point: NewowTrendBandPoint
    marker: NewowMainMarker | None

def initial_trend_band_state() -> TrendBandStateValue
def step_trend_band(
    state: TrendBandStateValue,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> TrendBandStepResult
def calculate_trend_band(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[NewowTrendBandPoint, ...]
```

- [ ] **Step 1: Write formula golden tests**

Use a deterministic list of 30 OHLC Bars and independently compute:

```python
def manual_typical(bar: NewowDailyBar) -> float:
    return (
        3.0 * float(bar.close)
        + float(bar.open)
        + float(bar.high)
        + float(bar.low)
    ) / 6.0
```

The tests must assert:
- first B value exists only after 20 completed Bars;
- first C value exists only after five B values;
- `B >= C` is YELLOW and `B < C` is BLUE;
- the first BLUE→YELLOW transition creates `NEWOW_BUILD_MARKER`;
- the first YELLOW→BLUE transition creates `NEWOW_CLEAR_MARKER`;
- HOLD/EMPTY Bars do not create daily duplicate markers;
- clear marker reference change uses the preceding build marker close;
- no build exists before the actual rank1 marker eligibility boundary supplied by the engine.

Example:

```python
def test_blue_to_yellow_creates_one_build_marker() -> None:
    points, markers = run_fixture("trend_blue_to_yellow")
    transition_points = [p for p in points if p.transition is not None]
    assert transition_points[-1].transition.value == "BUILD"
    assert [m.marker_type.value for m in markers].count("BUILD") == 1
```

- [ ] **Step 2: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_band.py -q
```

Expected: FAIL because `trend_band.py` is missing.

- [ ] **Step 3: Implement one-step and batch formulas**

Implementation rules:
- calculate `P_t` from the current completed Bar only;
- calculate B with weights 1..20 aligned oldest→newest;
- calculate C as a simple mean of the last five finite B values;
- carry only the bounded windows required for the next step;
- calculate numeric state on same-contract warm-up Bars, but emit no transition or marker while `observation_eligible=False`;
- the first eligible Bar may emit a transition only from the already-warmed prior state and its own completed close;
- use deterministic marker IDs:

```text
sha256(strategy_code | formula_version | physical_contract | marker_type | bar_end)
```

- [ ] **Step 4: Add reference-change tests**

```python
def test_clear_reference_change_is_signal_close_not_next_open() -> None:
    result = run_fixture("one_build_one_clear")
    clear = next(m for m in result.markers if m.marker_type.value == "CLEAR")
    assert clear.trigger_facts["reference_basis"] == "signal_close"
    assert clear.trigger_facts["reference_change_pct"] == pytest.approx(13.24)
```

The marker copy must include:

```text
策略信号参考变化
非真实成交
未计手续费、滑点、涨跌停和换月
```

- [ ] **Step 5: Add prefix and batch/incremental parity tests**

```python
def test_trend_band_prefix_invariance() -> None:
    bars = fixture_bars("long_trend_cycle")
    full = calculate_trend_band(bars)
    for length in range(1, len(bars) + 1):
        assert calculate_trend_band(bars[:length]) == full[:length]
```

Also serialize the bounded state to a plain dataclass/dict and restore it before the last ten Bars; results must match continuous execution.

- [ ] **Step 6: Run focused and package checks**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_band.py -q
uv run ruff check ../../packages/quant-core/guiyi_quant/newow tests/newow/test_trend_band.py
uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/newow/trend_band.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_trend_band.py
git commit -m "feat(newow): implement yellow blue D1 trend band"
```

**Review Gate:** compare formula values and transition dates, not historical returns. Stop if the implementation uses EMA/MACD, future Bars, unfinished Bars, continuous-series data, or daily marker duplication.

---

### Task 3: Implement VAR4 and D1/D2/D3 Escape Signals

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/escape_d123.py`
- Create: `services/quant-api/tests/newow/test_escape_d123.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`

**Interfaces:**
- Consumes: `NewowDailyBar`, `NewowTrendProfile`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class EscapeState:
    closes: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    ma120_values: tuple[float, ...]
    previous_rsv9: float | None
    previous_var4: float | None

@dataclass(frozen=True, slots=True)
class EscapeStepResult:
    state: EscapeState
    ma120: float | None
    ma120_slope10: float | None
    amplitude30: float | None
    rsv9: float | None
    var4: float | None
    markers: tuple[NewowMainMarker, ...]

def initial_escape_state() -> EscapeState
def step_escape_d123(
    state: EscapeState,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> EscapeStepResult
```

- [ ] **Step 1: Write exact VAR4 smoothing tests**

Tests must independently assert:

```text
RSV9 = 100 × (close - LLV9) / (HHV9 - LLV9)
VAR4[t] = (RSV9[t] + 2 × VAR4[t-1]) / 3
```

When HHV9 == LLV9:
- reuse the previous finite RSV9;
- use 50.0 only when no previous finite value exists.

- [ ] **Step 2: Write one test for each public D signal rule**

```python
def test_d1_requires_cross_below_95_and_30_percent_above_ma120() -> None:
    result = run_escape_fixture("d1_exact")
    marker = assert_single_marker(result, "ESCAPE_D1")
    assert marker.label == "★S逃命"
    assert marker.trigger_facts["var4_cross_level"] == 95
    assert marker.trigger_facts["ma120_deviation"] >= 0.30


def test_d2_requires_amplitude_and_flat_ma120() -> None:
    result = run_escape_fixture("d2_exact")
    marker = assert_single_marker(result, "ESCAPE_D2")
    assert marker.trigger_facts["amplitude30"] > 0.10
    assert abs(marker.trigger_facts["ma120_slope10"]) <= 0.0005


def test_d3_requires_below_falling_ma120_and_cross_below_90() -> None:
    result = run_escape_fixture("d3_exact")
    marker = assert_single_marker(result, "ESCAPE_D3")
    assert marker.trigger_facts["close_below_ma120"] is True
    assert marker.trigger_facts["ma120_slope10"] < -0.0005
```

- [ ] **Step 3: Write negative boundary tests**

Include:
- previous VAR4 below the threshold must not re-trigger;
- D1 deviation 29.99% must fail;
- D2 amplitude exactly 10% must fail because rule is `> 10%`;
- D2 slope just above 0.0005 must fail;
- D3 slope equal to -0.0005 must fail;
- fewer than 120 same-contract Bars returns no D marker;
- same Bar may retain multiple calculations but display priority is D1 > D2 > D3.

- [ ] **Step 4: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_escape_d123.py -q
```

Expected: FAIL because `escape_d123.py` is missing.

- [ ] **Step 5: Implement bounded incremental calculations**

Implementation rules:
- retain at most 120 close/high/low values plus ten MA120 values;
- use NumPy only for OLS slope;
- do not forward-fill a missing Bar or cross a physical-contract reset;
- update numeric VAR4/MA120 state on same-contract warm-up Bars, but emit no D marker while `observation_eligible=False`;
- emit immutable markers with the original Chinese labels and color tokens;
- return all same-Bar hits from core; UI priority is a separate view-model concern.

- [ ] **Step 6: Add parity and formula-digest tests**

```python
def test_escape_batch_matches_incremental() -> None:
    bars = fixture_bars("escape_mixed")
    assert calculate_escape_series(bars) == run_escape_incrementally(bars)


def test_escape_marker_identity_changes_with_formula_version() -> None:
    old = marker_id_for("newow_escape_d123_v1")
    new = marker_id_for("newow_escape_d123_v2")
    assert old != new
```

- [ ] **Step 7: Run checks**

```bash
cd services/quant-api
uv run pytest tests/newow/test_escape_d123.py -q
uv run ruff check ../../packages/quant-core/guiyi_quant/newow/escape_d123.py tests/newow/test_escape_d123.py
uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/newow/escape_d123.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_escape_d123.py
git commit -m "feat(newow): add D1 D2 D3 escape signals"
```

**Review Gate:** verify the screenshot-derived rules exactly. The reviewer must reject any imported internet VAR4 variant, return-based parameter tuning, use of settlement instead of close, or repeated marker emission after a cross.

---

### Task 4: Implement the Dedicated Cup-and-Handle Kernel

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/cup_handle.py`
- Create: `services/quant-api/tests/newow/test_cup_handle.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Modify: `services/quant-api/tests/newow/fixtures.py`

**Interfaces:**
- Consumes: `NewowDailyBar`, `NewowTrendProfile`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CupPivot:
    kind: Literal["HIGH", "LOW"]
    price: float
    pivot_at: datetime
    confirmed_at: datetime
    atr_at_pivot: float
    bar_index: int

@dataclass(frozen=True, slots=True)
class CupHandleStateValue:
    recent_bars: tuple[NewowDailyBar, ...]
    recent_atr_values: tuple[float | None, ...]
    confirmed_pivots: tuple[CupPivot, ...]
    active_candidate: NewowCupHandleOverlay | None
    recent_emitted_candidate_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CupHandleStepResult:
    state: CupHandleStateValue
    active_overlay: NewowCupHandleOverlay | None
    markers: tuple[NewowMainMarker, ...]

def initial_cup_handle_state() -> CupHandleStateValue
def step_cup_handle(
    state: CupHandleStateValue,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> CupHandleStepResult
```

- [ ] **Step 1: Build synthetic positive and hard-negative fixtures**

`fixtures.py` must expose:
- `bullish_true_cup_handle()`
- `bearish_true_cup_handle()`
- `v_bottom_rejected()`
- `wide_range_rejected()`
- `downtrend_rebound_rejected()`
- `shallow_cup_rejected()`
- `handle_too_short_rejected()`
- `handle_too_long_rejected()`
- `handle_too_deep_rejected()`
- `handle_volume_not_contracting()`
- `breakout_volume_not_confirmed()`
- `rollover_split_candidate()`

Each fixture must include explicit expected anchor dates and expected hard-failure codes; future returns are not fixture labels.

- [ ] **Step 2: Write failing pivot-causality tests**

```python
def test_pivot_is_not_actionable_before_confirmation() -> None:
    bars = bullish_true_cup_handle()
    full = run_cup_handle(bars)
    pivot = full.active_overlay.left_rim
    assert pivot.pivot_at < pivot.confirmed_at
    prefix = bars[: index_after(pivot.pivot_at)]
    assert run_cup_handle(prefix).active_overlay is None
```

Also assert that appending Bars cannot move a READY candidate's L/B/R/H/P anchors.

- [ ] **Step 3: Write each v3.6 filter as a separate test**

```python
def test_shallow_cup_below_ten_percent_is_rejected() -> None:
    overlay = run_cup_handle(shallow_cup_rejected()).last_candidate
    assert "CUP_DEPTH_BELOW_10_PERCENT" in overlay.hard_failures


def test_single_bar_v_bottom_cannot_reach_ready() -> None:
    overlay = run_cup_handle(v_bottom_rejected()).last_candidate
    assert overlay.state is not CupHandleState.READY
    assert overlay.score_breakdown["u_shape_purity"] <= 5
```

Tests must separately cover:
- pretrend 10% OR 4 ATR;
- 25–90 cup Bars;
- 10%–50% depth and >= 3 ATR;
- rim gap <= 5% and <= 1.5 ATR;
- handle 5–15 Bars;
- handle depth <= 15%;
- handle retrace <= one-third of the right-leg advance;
- handle in upper half;
- handle volume ratios 0.80 and 0.90;
- breakout buffer 0.10 ATR;
- breakout volume ratios 1.20 and 1.50;
- wide-range crossing count and leg-ratio penalty.

- [ ] **Step 4: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_cup_handle.py -q
```

Expected: FAIL because `cup_handle.py` is missing.

- [ ] **Step 5: Implement the dedicated pivot tracker**

Rules:
- ignore `observation_eligible=False` Bars for Pivot/cup geometry; they may warm ATR only;
- retain at most `cup_history_limit=220` eligible Bars and at most 32 confirmed pivots;
- candidate enumeration may only end at the newest confirmed pivot/current completed Bar and must have a deterministic maximum of 256 candidate skeleton checks per step;
- if the candidate bound would be exceeded, return `CUP_CANDIDATE_LIMIT_EXCEEDED` and do not guess;
- use Wilder ATR14 inside this module only as a mathematical helper;
- reversal confirmation uses `1.25 × ATR_at_extreme`;
- minimum leg length is three completed D1 Bars;
- track `pivot_at` and `confirmed_at`;
- do not expose unconfirmed pivots to candidate enumeration;
- reset all pivot and candidate state at physical-contract rollover.

- [ ] **Step 6: Implement bounded candidate enumeration**

Use confirmed alternating pivots to enumerate only the minimum anchor combinations required for bullish and bearish cup handles.

Deterministic ranking order:

```text
hard-valid candidate first
higher state precedence: BREAKOUT > READY > FORMING
higher score
later confirmed_at
stable candidate_id
```

Do not build a generic Pattern Engine or inspect arbitrary future windows.

- [ ] **Step 7: Implement score breakdown and lifecycle**

Score keys are fixed:

```text
pretrend
cup_geometry
u_shape_purity
handle_quality
volume_structure
```

Lifecycle:
- FORMING may change as Bars arrive;
- READY freezes identity, anchors, pivot price, confirmed_at and score;
- BREAKOUT requires close and volume hard Gates;
- WEAKENED/INVALIDATED/EXPIRED create new state/marker facts; never rewrite READY;
- same anchor tuple in one physical segment maps to one candidate ID.

- [ ] **Step 8: Add batch/incremental, prefix, and mirror tests**

```python
def test_cup_handle_batch_matches_incremental() -> None:
    bars = bullish_true_cup_handle()
    assert calculate_cup_handle_series(bars) == run_cup_incrementally(bars)


def test_bearish_fixture_is_directional_mirror() -> None:
    bull = run_cup_handle(bullish_true_cup_handle()).active_overlay
    bear = run_cup_handle(bearish_true_cup_handle()).active_overlay
    assert bull.score == bear.score
    assert bull.direction.value == "BULLISH"
    assert bear.direction.value == "BEARISH"
```

- [ ] **Step 9: Run checks**

```bash
cd services/quant-api
uv run pytest tests/newow/test_cup_handle.py -q
uv run ruff check ../../packages/quant-core/guiyi_quant/newow/cup_handle.py tests/newow/test_cup_handle.py
uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/newow/cup_handle.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/fixtures.py \
  services/quant-api/tests/newow/test_cup_handle.py
git commit -m "feat(newow): add causal cup handle setup"
```

**Review Gate:** Formula review must be independent from UI review. Reject if the code uses centered windows, confirms a Pivot on its own Bar, changes READY anchors after future data, joins across contracts, or promotes weak-volume geometric breakouts to BREAKOUT.

---

### Task 5: Compose the Single Newow D1 Engine and Prove Causality

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/engine.py`
- Create: `services/quant-api/tests/newow/test_engine_causality.py`
- Modify: `packages/quant-core/guiyi_quant/newow/__init__.py`

**Interfaces:**
- Consumes:
  - `step_trend_band`
  - `step_escape_d123`
  - `step_cup_handle`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class NewowTrendEngineState:
    physical_contract: str | None
    segment_id: str | None
    trend_band_state: TrendBandStateValue
    escape_state: EscapeState
    cup_handle_state: CupHandleStateValue
    last_bar_end: datetime | None
    last_build_marker_id: str | None

@dataclass(frozen=True, slots=True)
class NewowTrendStepResult:
    state: NewowTrendEngineState
    frame: NewowTrendFrame
    markers: tuple[NewowMainMarker, ...]

class NewowTrendD1Engine:
    @classmethod
    def initial(cls, *, profile: NewowTrendProfile = NEWOW_TREND_D1_V1) -> "NewowTrendD1Engine"
    def step(self, completed_d1_bar: NewowDailyBar) -> NewowTrendStepResult
```

- [ ] **Step 1: Write pipeline-order tests**

Tests must assert that for each Bar:
1. identity, sequence, and `observation_eligible` validation happen first;
2. trend-band, escape and cup-handle inputs all see the same completed Bar;
3. the frozen frame includes every module's result for that exact `bar_end`;
4. marker order is deterministic: CLEAR/BUILD, D1/D2/D3, cup-handle milestone;
5. same-Bar D1/D2/D3 display priority does not delete core results.

- [ ] **Step 2: Write physical-contract rollover tests**

```python
def test_rollover_resets_all_newow_state_without_emitting_false_markers() -> None:
    first_segment = fixture_bars("rb2401_trend")
    second_segment = fixture_bars("rb2405_after_roll")
    engine = NewowTrendD1Engine.initial()
    first_results = feed(engine, first_segment)
    roll_result = engine.step(second_segment[0])
    assert roll_result.frame.rollover_started is True
    assert roll_result.markers == ()
    assert roll_result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert roll_result.frame.cup_handle is None
```

Also prove that a cup begun in contract A cannot complete in contract B.

- [ ] **Step 3: Write incomplete-Bar and duplicate-Bar rejection tests**

```python
with pytest.raises(ValueError, match="NEWOW_BAR_NOT_COMPLETED"):
    engine.step(incomplete_bar)

with pytest.raises(ValueError, match="NEWOW_BAR_OUT_OF_ORDER"):
    engine.step(previous_bar)
```

- [ ] **Step 4: Write full prefix-invariance harness**

For each fixture:
- run all Bars once;
- rerun every prefix;
- compare all completed frames and marker IDs;
- serialize/restore state at multiple cut points;
- alter an uncompleted tail Bar and prove no official output changes.

- [ ] **Step 5: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_engine_causality.py -q
```

Expected: FAIL because `engine.py` is missing.

- [ ] **Step 6: Implement minimal orchestration**

The engine must not:
- read MarketDataService;
- know HTTP/Web;
- cache files;
- calculate external indicators;
- create positions or PnL;
- accept frequencies other than D1;
- emit formal markers from warm-up Bars.

- [ ] **Step 7: Run all core tests**

```bash
cd services/quant-api
uv run pytest tests/newow/test_models_profile.py \
  tests/newow/test_trend_band.py \
  tests/newow/test_escape_d123.py \
  tests/newow/test_cup_handle.py \
  tests/newow/test_engine_causality.py -q
uv run ruff check ../../packages/quant-core/guiyi_quant/newow tests/newow
uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/newow/engine.py \
  packages/quant-core/guiyi_quant/newow/__init__.py \
  services/quant-api/tests/newow/test_engine_causality.py
git commit -m "feat(newow): compose causal D1 trend engine"
```

**Review Gate:** Core Review must finish before any API/Web task starts. Reject if rollover generates a strategy trade, Historical uses a vectorized alternate formula, or the engine knows UI labels beyond stable marker metadata.

---

### Task 6: Read Actual-Dominant D1, Segment It, and Build the Detail Response

**Files:**
- Create: `services/quant-api/app/market_data/newow/__init__.py`
- Create: `services/quant-api/app/market_data/newow/trend_detail_query.py`
- Create: `services/quant-api/app/market_data/newow/trend_detail_service.py`
- Create: `services/quant-api/tests/newow/test_trend_detail_service.py`

**Interfaces:**
- Consumes:
  - `MarketDataService.query(SeriesQuery)`
  - `SeriesKind.ACTUAL_DOMINANT`
  - `BarFrequency.D1`
  - `ResolvedContractSegment`
  - `NewowTrendD1Engine`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class NewowTrendDetailQuery:
    product: str
    since: date
    through: date
    frequency: BarFrequency = BarFrequency.D1
    series_kind: SeriesKind = SeriesKind.ACTUAL_DOMINANT

@dataclass(frozen=True, slots=True)
class NewowTrendDetailResult:
    source_identity: str
    instrument: NewowInstrumentContext
    bars: tuple[CanonicalBar, ...]
    frames: tuple[NewowTrendFrame, ...]
    markers: tuple[NewowMainMarker, ...]
    cup_handles: tuple[NewowCupHandleOverlay, ...]
    rollover_seams: tuple[NewowRolloverSeam, ...]
    warnings: tuple[str, ...]

class NewowTrendDetailService:
    def __init__(self, market_data_service: MarketDataService) -> None
    def query(self, request: NewowTrendDetailQuery) -> NewowTrendDetailResult
```

- [ ] **Step 1: Write query-contract tests**

Reject:
- frequency other than D1;
- series kind other than actual_dominant;
- empty product;
- since > through;
- range longer than the explicit V1 maximum, fixed at 1,500 D1 Bars;
- data result with duplicate or non-increasing Bars.

- [ ] **Step 2: Write segment and warm-up tests**

The service must:
- use resolved physical segments returned by MarketDataService;
- for each rank1 segment, query the same physical contract through `MarketDataService` back to its authoritative available coverage start, then retain no more than the Profile's required history;
- mark pre-rank1 same-contract Bars `observation_eligible=False`; they may warm B/C, VAR4, MA120 and ATR only;
- start cup Pivot/geometry state and all formal markers at the rank1 segment start;
- return only the requested visible range even when additional same-contract warm-up was read;
- make overlapping query windows return identical frames/marker IDs for the same Bar;
- suppress formal markers before segment start;
- create a rollover seam at the segment boundary;
- reset engine state at each physical segment;
- never join one trend interval or cup candidate across segments.

- [ ] **Step 3: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_detail_service.py -q
```

Expected: FAIL because the Newow application package is missing.

- [ ] **Step 4: Implement domain conversion**

Create one private converter:

```python
def _to_newow_bar(
    bar: CanonicalBar,
    *,
    product: str,
    physical_contract: str,
    segment_id: str,
    source_identity: str,
    observation_eligible: bool,
) -> NewowDailyBar:
    return NewowDailyBar(
        product=product,
        physical_contract=physical_contract,
        segment_id=segment_id,
        trading_day=bar.trading_day,
        bar_end=bar.bar_end,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        open_interest=bar.open_interest,
        source_identity=source_identity,
        observation_eligible=observation_eligible,
        completed=True,
    )
```

It must preserve Decimal prices and the authoritative `trading_day`.

- [ ] **Step 5: Implement per-segment engine replay**

For each segment:
- create a fresh engine;
- feed same-contract warm-up Bars first with `observation_eligible=False`;
- feed rank1 segment Bars with `observation_eligible=True`;
- collect frames, immutable markers and frozen cup overlays;
- mark the first segment Bar as rollover start without manufacturing a BUILD/CLEAR marker;
- return typed warnings for insufficient 20/120/cup history.

- [ ] **Step 6: Add deterministic-source-identity test**

The source identity must bind:

```text
dataset read identity
actual-dominant mapping digest
product
frequency
since/through
formula/profile digest
```

The same exact inputs return the same identity; any formula or mapping change returns a different identity.

Also assert that two requests with different visible `since` values but the same physical source history produce byte-identical frame/marker data on their overlapping Bars. The query window must not change indicator history.

- [ ] **Step 7: Run checks**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_detail_service.py -q
uv run ruff check app/market_data/newow tests/newow/test_trend_detail_service.py
uv run mypy app/market_data/newow
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  services/quant-api/app/market_data/newow \
  services/quant-api/tests/newow/test_trend_detail_service.py
git commit -m "feat(newow): build actual-dominant D1 detail service"
```

**Review Gate:** reject any direct Parquet glob, consumer-selected main contract, continuous-series fallback, settlement-price substitution, cross-frequency fallback, DB write, or Runtime dependency.

---

### Task 7: Keep V1 Stateless and Prove Bounded Request Work

**Files:**
- Modify: `services/quant-api/app/market_data/newow/trend_detail_service.py`
- Modify: `services/quant-api/tests/newow/test_trend_detail_service.py`

**Interfaces:**
- Consumes: `NewowTrendDetailService`.
- Produces: no new persistence component. V1 remains request-scoped and cache-free.

- [ ] **Step 1: Write statelessness tests**

Tests must prove:
- two identical queries return byte-equivalent domain results and marker IDs;
- a query does not create files, database rows, Redis keys, queues, jobs, or background tasks;
- the service invokes the injected `MarketDataService` only through its read-only query contract;
- one request cannot change the result of a later request;
- the 1,500-Bar request bound is enforced before expensive replay.

Use fakes at the dependency boundary. Do not monkeypatch global filesystem or network APIs when an injected fake can prove the same contract.

- [ ] **Step 2: Write bounded-work tests**

For a maximum-size 1,500-Bar synthetic response, assert:
- the engine processes each returned Bar exactly once;
- no nested re-query occurs;
- candidate enumeration remains bounded by the dedicated cup-handle state contract;
- response ordering is deterministic.

Do not add a wall-clock assertion to unit tests. Record performance observations during final Review instead.

- [ ] **Step 3: Verify the new tests fail for the intended reason**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_detail_service.py -q
```

Expected: the new statelessness or bounded-work assertions fail until the service contract is completed.

- [ ] **Step 4: Complete request-scoped orchestration**

Keep all replay state local to `query()`. Do not create:
- `trend_detail_cache.py`;
- `GUIYI_NEWOW_CACHE_ROOT`;
- cache manifests;
- scheduled precomputation;
- a new process-global mutable cache.

If later measurements show a real latency problem, caching requires a separate bounded design task. It is not part of V1 correctness.

- [ ] **Step 5: Run checks**

```bash
cd services/quant-api
uv run pytest tests/newow/test_trend_detail_service.py -q
uv run ruff check app/market_data/newow tests/newow/test_trend_detail_service.py
uv run mypy app/market_data/newow
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  services/quant-api/app/market_data/newow/trend_detail_service.py \
  services/quant-api/tests/newow/test_trend_detail_service.py
git commit -m "test(newow): prove stateless bounded detail queries"
```

**Review Gate:** reject any filesystem cache, mutable singleton, hidden scheduler, provider call, Canonical repair, or request-triggered write. The first version is a single-user D1 detail view; simplicity wins until measured evidence justifies caching.

---

### Task 8: Expose the Read-only FastAPI Contract

**Files:**
- Create: `services/quant-api/app/schemas/market_newow.py`
- Create: `services/quant-api/app/api/market_newow.py`
- Modify: `services/quant-api/app/main.py`
- Create: `services/quant-api/tests/newow/test_market_newow_api.py`

**Interfaces:**
- Consumes: `NewowTrendDetailService.query(NewowTrendDetailQuery)`.
- Produces:

```text
GET /api/v1/market/newow/trend-detail
```

Query parameters:

```text
product
from
through
frequency=1d
series_kind=actual_dominant
```

Response:
- `source_identity`
- `instrument`
- `frequency`
- `visible_range`
- `bars`
- `trend_band`
- `trend_markers`
- `escape_markers`
- `cup_handle_candidates`
- `rollover_seams`
- `legend`
- `formula_descriptions`
- `reference_version`
- `warnings`

- [ ] **Step 1: Write schema serialization tests**

Assert:
- Decimal values serialize as JSON numbers or exact agreed strings consistently with existing market schemas;
- timestamps are RFC3339 with timezone;
- enum values remain stable;
- trigger facts expose only public codes and values;
- no paths, provider messages, SQL, stack traces, tokens or internal exception text.

- [ ] **Step 2: Write endpoint boundary tests**

```python
def test_newow_endpoint_rejects_non_daily_frequency(client) -> None:
    response = client.get(
        "/api/v1/market/newow/trend-detail",
        params={"product": "rb", "from": "2025-01-01", "through": "2026-01-01", "frequency": "15m"},
    )
    assert response.status_code == 422
```

Also test:
- actual_dominant is fixed;
- MarketDataError maps to stable public reason;
- current page endpoints are unchanged;
- endpoint has no POST/PUT/DELETE sibling;
- the route does not touch Alert or Runtime dependencies.

- [ ] **Step 3: Verify failure**

```bash
cd services/quant-api
uv run pytest tests/newow/test_market_newow_api.py -q
```

Expected: FAIL because router/schema are missing.

- [ ] **Step 4: Implement Pydantic response models**

Keep API DTOs separate from core dataclasses. Explicitly map fields; never return `asdict()` blindly.

- [ ] **Step 5: Implement router and dependency construction**

Follow existing Market router dependency patterns. The router is read-only and tagged `market-newow`.

- [ ] **Step 6: Register router in `app/main.py`**

Add:

```python
from app.api.market_newow import router as market_newow_router

app.include_router(market_newow_router)
```

No existing router order or behavior should change beyond the new path.

- [ ] **Step 7: Run API and regression tests**

```bash
cd services/quant-api
uv run pytest tests/newow/test_market_newow_api.py tests/data_foundation/test_market_api.py tests/test_market_research_overlays_api.py -q
uv run ruff check app/api/market_newow.py app/schemas/market_newow.py app/main.py tests/newow/test_market_newow_api.py
uv run mypy app/api/market_newow.py app/schemas/market_newow.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  services/quant-api/app/schemas/market_newow.py \
  services/quant-api/app/api/market_newow.py \
  services/quant-api/app/main.py \
  services/quant-api/tests/newow/test_market_newow_api.py
git commit -m "feat(newow): expose read-only trend detail API"
```

**Review Gate:** verify that API output is typed, redacted, bounded, D1-only, and contains no automatic trade recommendation.

---

### Task 9: Add Web Types, API Client, and Pure View Models

**Files:**
- Create: `apps/quant-web/src/types/newow.ts`
- Create: `apps/quant-web/src/api/newow.ts`
- Create: `apps/quant-web/src/utils/newowViewModel.ts`
- Create: `apps/quant-web/tests/newowTypes.test.ts`
- Create: `apps/quant-web/tests/newowViewModel.test.ts`
- Create: `apps/quant-web/e2e/fixtures/newow-trend-detail.json`

**Interfaces:**
- Consumes: FastAPI JSON.
- Produces:

```ts
export interface NewowTrendDetailResponse {
  source_identity: string
  instrument: NewowInstrumentContext
  frequency: '1d'
  visible_range: { from: string; through: string }
  bars: NewowBar[]
  trend_band: NewowTrendBandPoint[]
  trend_markers: NewowMainMarker[]
  escape_markers: NewowMainMarker[]
  cup_handle_candidates: NewowCupHandleOverlay[]
  rollover_seams: NewowRolloverSeam[]
  legend: NewowLegendItem[]
  formula_descriptions: NewowFormulaDescription[]
  reference_version: string
  warnings: string[]
}
export async function getNewowTrendDetail(params: NewowTrendDetailParams): Promise<NewowTrendDetailResponse>
export function buildNewowMarkerRows(response: NewowTrendDetailResponse): NewowSignalRow[]
export function visibleMarkerForBar(markers: NewowMainMarker[]): NewowMainMarker | null
export function buildNewowIndicatorCopy(marker: NewowMainMarker): NewowIndicatorCopy
```

- [ ] **Step 1: Write response-shape and snake_case boundary tests using the fixture JSON**

Assert discriminated unions for:
- band state;
- BUILD/CLEAR;
- D1/D2/D3;
- cup-handle states;
- warnings;
- rollover seam.

- [ ] **Step 2: Write D-marker display-priority tests**

```ts
test('D1 wins the chart label while all same-day hits remain in the sheet', () => {
  const markers = sameDayEscapeMarkers()
  assert.equal(visibleMarkerForBar(markers)?.markerType, 'ESCAPE_D1')
  assert.deepEqual(buildNewowMarkerRows({ markers }).map((item) => item.markerType), [
    'ESCAPE_D1',
    'ESCAPE_D2',
    'ESCAPE_D3',
  ])
})
```

- [ ] **Step 3: Write copy-integrity tests**

The visible copy must match the user screenshots:
- `★S逃命 / 高位急转，最强烈逃顶警示`
- `★S逃 / 中期见顶回落`
- `★S跑 / 跌破半年线，加速下跌`
- build/clear language uses `建仓/清仓`, not `买入/卖出`;
- reference change contains the non-trade disclaimer.

- [ ] **Step 4: Verify failure**

```bash
cd apps/quant-web
pnpm exec node --test tests/newowTypes.test.ts tests/newowViewModel.test.ts
```

Expected: FAIL because files are missing.

- [ ] **Step 5: Implement exact TypeScript contracts and API client**

Keep transport DTO field names in backend `snake_case`, matching the existing Market Web convention. Pure view-model helpers may expose local camelCase fields, but the boundary conversion must be explicit and tested.

Use the existing Axios client configuration. Reject unsupported `frequency` or `series_kind` before sending the request.

- [ ] **Step 6: Implement pure view-model helpers**

No chart or DOM imports in `newowViewModel.ts`.

- [ ] **Step 7: Run tests and typecheck**

```bash
cd apps/quant-web
pnpm test
pnpm build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/src/types/newow.ts \
  apps/quant-web/src/api/newow.ts \
  apps/quant-web/src/utils/newowViewModel.ts \
  apps/quant-web/tests/newowTypes.test.ts \
  apps/quant-web/tests/newowViewModel.test.ts \
  apps/quant-web/e2e/fixtures/newow-trend-detail.json
git commit -m "feat(newow): add typed web detail contract"
```

**Review Gate:** reject any duplicated trend/D/cup formula in TypeScript.

---

### Task 10: Create the Independent Newow Detail Shell and Route Switch

**Files:**
- Move without business changes: `apps/quant-web/src/pages/market/chart.vue` → `apps/quant-web/src/components/market/CurrentMarketDetailView.vue`
- Create: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/src/pages/market/NewowTrendDetailView.vue`
- Create: `apps/quant-web/src/components/newow/NewowHeader.vue`
- Create: `apps/quant-web/src/composables/useNewowTrendDetail.ts`
- Create: `apps/quant-web/src/utils/marketDetailView.ts`
- Create: `apps/quant-web/tests/newowRoute.test.ts`

**Interfaces:**
- Consumes:
  - route query `view=current|newow`
  - symbol/from/through
  - `getNewowTrendDetail`
- Produces:
  - isolated Current/Newow child rendering;
  - loading/error/unsupported states.

- [ ] **Step 1: Write route-normalization tests**

Pure helper expectations:

```ts
resolveMarketDetailView({ view: 'newow' }) === 'newow'
resolveMarketDetailView({ view: 'unknown' }) === 'current'
newowRouteQuery('rb', range) preserves symbol/from/through
```

- [ ] **Step 2: Verify failure**

```bash
cd apps/quant-web
pnpm exec node --test tests/newowRoute.test.ts
```

Expected: FAIL because route helpers and Newow page do not exist.

- [ ] **Step 3: Mechanically isolate the current detail implementation**

Move the complete existing page implementation to `CurrentMarketDetailView.vue` without changing its script, template behavior, styles, request graph, defaults, or preference keys. Create a small route shell in `chart.vue`:

```vue
<template>
  <CurrentMarketDetailView v-if="detailView === 'current'" />
  <NewowTrendDetailView v-else />
</template>
```

The shell owns only route normalization and the `当前版本 / 牛哇版本` switch. Because only the selected child is mounted:
- Newow mode must not initialize retired-strategy/HTDY/Alert composables;
- current mode must not request the Newow endpoint;
- current-view DOM and API behavior remain unchanged apart from the explicit version switch.

Do not opportunistically refactor the moved current component.

- [ ] **Step 4: Implement the Newow page data composable**

`useNewowTrendDetail`:
- accepts product/from/through;
- cancels stale requests;
- exposes loading/data/public error;
- never falls back to another product/frequency/series;
- does not request unfinished/live data.

- [ ] **Step 5: Implement the header and version switch**

Header matches the included reference flow:
- 返回;
- 日K胶囊;
- 收藏;
- 历史.

The version switch is a Guiyi-only control:
- current→newow preserves product and visible range;
- newow→current preserves product and visible range;
- unsupported Newow period renders `牛哇趋势 V1 仅支持日K`.

Use existing local preference infrastructure for favorite if available; otherwise implement localStorage scoped to Newow product IDs, not a server table.

- [ ] **Step 6: Run tests and current-page regression build**

```bash
cd apps/quant-web
pnpm test
pnpm build
pnpm exec playwright test \
  e2e/market-research-market-core.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/components/market/CurrentMarketDetailView.vue \
  apps/quant-web/src/pages/market/NewowTrendDetailView.vue \
  apps/quant-web/src/components/newow/NewowHeader.vue \
  apps/quant-web/src/composables/useNewowTrendDetail.ts \
  apps/quant-web/src/utils/marketDetailView.ts \
  apps/quant-web/tests/newowRoute.test.ts
git commit -m "feat(newow): add isolated trend detail route"
```

**Review Gate:** manually verify that the current view sends the same requests and renders the same DOM paths as before. Reject broad `chart.vue` refactoring or Newow business logic inside the shell.

---

### Task 11: Render the Newow Main Chart, Trend Band, Markers, and Cup Handle

**Files:**
- Create: `apps/quant-web/src/components/newow/NewowTrendChart.vue`
- Create: `apps/quant-web/src/components/newow/newowTrendBandPrimitive.ts`
- Create: `apps/quant-web/src/components/newow/newowCupHandlePrimitive.ts`
- Create: `apps/quant-web/src/styles/newowTokens.ts`
- Create: `apps/quant-web/src/utils/newowChartModel.ts`
- Create: `apps/quant-web/tests/newowChartModel.test.ts`
- Modify: `apps/quant-web/src/pages/market/NewowTrendDetailView.vue`

**Interfaces:**
- Consumes: `NewowTrendDetailResponse`.
- Produces:
  - Kline + volume;
  - yellow/blue band;
  - cup outline/handle/pivot;
  - build/clear/D markers;
  - rollover seams;
  - crosshair selection events.

- [ ] **Step 1: Freeze semantic visual tokens**

`newowTokens.ts` must contain named tokens only:

```ts
export const NEWOW_COLORS = {
  yellow: '#FFCC00',
  blue: '#0066BB',
  buildBorder: '#7A3E1D',
  clearBorder: '#7A3E1D',
  d1: '#FF3B30',
  d2: '#34C759',
  d3: '#007AFF',
  modalMask: 'rgba(0, 0, 0, 0.45)',
  orange: '#FF8800',
  actionBlue: '#007AFF',
} as const
```

The task implementer samples values from the user-provided reference screenshots and records the RGB/hex values in the commit description. Do not use current Guiyi indicator colors as substitutes.

- [ ] **Step 2: Write chart-model tests**

Tests must verify:
- band segments split exactly on state transitions;
- same-Bar marker priority D1>D2>D3;
- build/clear marker boxes include signal close and reference change;
- cup path uses L/B/R/H/P anchors from API and never recomputes geometry;
- rollover seam splits visual continuity;
- missing trend/escape/cup data yields explicit unavailable overlays rather than zero values.

- [ ] **Step 3: Verify failure**

```bash
cd apps/quant-web
pnpm exec node --test tests/newowChartModel.test.ts
```

Expected: FAIL because chart files are missing.

- [ ] **Step 4: Implement a dedicated lightweight-charts component**

Use:
- one main price pane;
- one volume pane;
- existing Shanghai time-format utilities;
- existing viewport and `need-more-before` patterns where applicable.

Do not render MACD or the three deferred lower indicators.

- [ ] **Step 5: Implement the trend-band primitive**

It consumes API-provided B/C points and:
- draws the B–C area with yellow or blue;
- applies a minimum pixel thickness without changing prices;
- breaks at rollover seams and unavailable regions;
- aligns after zoom/pan/resize.

- [ ] **Step 6: Implement the cup-handle primitive**

It consumes API overlays and draws:
- L/B/R anchors;
- cup outline;
- translucent handle box;
- P pivot line;
- state capsule;
- score only when the API has a score.

It does not draw a target-profit or automatic-stop region.

- [ ] **Step 7: Implement build/clear and D markers**

Marker cards must reflect Newow reference:
- build/clear at their signal Bars;
- D1 red, D2 green, D3 blue;
- click emits the complete marker set for the Bar;
- chart label collision layout is deterministic.

- [ ] **Step 8: Implement crosshair facts**

Crosshair data includes:
- OHLCV;
- physical contract;
- yellow/blue state;
- build/clear;
- all D hits;
- cup state.

- [ ] **Step 9: Run web tests and build**

```bash
cd apps/quant-web
pnpm test
pnpm build
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add \
  apps/quant-web/src/components/newow/NewowTrendChart.vue \
  apps/quant-web/src/components/newow/newowTrendBandPrimitive.ts \
  apps/quant-web/src/components/newow/newowCupHandlePrimitive.ts \
  apps/quant-web/src/styles/newowTokens.ts \
  apps/quant-web/src/utils/newowChartModel.ts \
  apps/quant-web/src/pages/market/NewowTrendDetailView.vue \
  apps/quant-web/tests/newowChartModel.test.ts
git commit -m "feat(newow): render reference-led D1 trend chart"
```

**Review Gate:** compare against the recording at phone width. Reject any lower indicator pane, target line, fake unsupported button, formula calculation in TypeScript, or visual continuity across rollover.

---

### Task 12: Implement Indicator Sheets, Cup Sheet, and Signal History

**Files:**
- Create: `apps/quant-web/src/components/newow/NewowIndicatorSheet.vue`
- Create: `apps/quant-web/src/components/newow/NewowSignalHistorySheet.vue`
- Create: `apps/quant-web/src/components/newow/NewowCupHandleSheet.vue`
- Create: `apps/quant-web/src/utils/newowCopy.ts`
- Create: `apps/quant-web/tests/newowCopy.test.ts`
- Modify: `apps/quant-web/src/pages/market/NewowTrendDetailView.vue`

**Interfaces:**
- Consumes: selected marker/cup overlay and history rows.
- Produces: Newow-style modal flows.

- [ ] **Step 1: Write exact-copy tests**

D1/D2/D3 copy must be byte-for-byte stable except dynamic values.

Trend copy must say:
- 蓝变黄：建仓阶段;
- 黄变黄：持有阶段;
- 黄变蓝：清仓阶段;
- 蓝变蓝：空仓阶段;
- reference change is not a real fill.

Cup copy must explain:
- pretrend;
- cup/body;
- handle;
- volume contraction;
- volume-confirmed breakout;
- v3.6 rejection reasons.

- [ ] **Step 2: Verify failure**

```bash
cd apps/quant-web
pnpm exec node --test tests/newowCopy.test.ts
```

Expected: FAIL because copy/sheets are missing.

- [ ] **Step 3: Implement the shared Newow sheet shell**

Match the screenshots:
- dim mask;
- large white rounded card;
- centered title;
- colored emphasis blocks;
- vertically scrollable content on small screens;
- bottom `知道了` button;
- close by button and mask only where reference supports it.

- [ ] **Step 4: Implement marker detail**

Display:
- date;
- Bar facts;
- state before/after;
- every triggered condition with pass/fail and actual value;
- formula version;
- reference-only disclaimer.

- [ ] **Step 5: Implement signal history**

History includes only:
- BUILD/CLEAR;
- D1/D2/D3;
- CUP READY/BREAKOUT/WEAKENED/INVALIDATED/EXPIRED.

Selecting a row:
- closes the sheet;
- moves the chart to the Bar;
- opens marker detail.

- [ ] **Step 6: Implement cup detail**

Display API-provided:
- state;
- L/B/R/H/P;
- score breakdown;
- hard failures;
- handle/right-leg/20-day volume ratios;
- `pivot_at`, `confirmed_at`, `first_seen_at`.

- [ ] **Step 7: Run tests and build**

```bash
cd apps/quant-web
pnpm test
pnpm build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/src/components/newow/NewowIndicatorSheet.vue \
  apps/quant-web/src/components/newow/NewowSignalHistorySheet.vue \
  apps/quant-web/src/components/newow/NewowCupHandleSheet.vue \
  apps/quant-web/src/utils/newowCopy.ts \
  apps/quant-web/src/pages/market/NewowTrendDetailView.vue \
  apps/quant-web/tests/newowCopy.test.ts
git commit -m "feat(newow): add indicator and history sheets"
```

**Review Gate:** reject content invented beyond the Spec/reference set, automatic-order language, or mismatch between home D-copy and detail D-copy.

---

### Task 13: Add Mobile/Desktop E2E and Visual Reference Acceptance

**Files:**
- Create: `apps/quant-web/e2e/newow-trend-detail.spec.mjs`
- Modify: `apps/quant-web/playwright.config.mjs` to add one named `newow-mobile` project while preserving the existing desktop `chromium` project
- Create: `docs/tasks/fixtures/newow/visual-review-template.md`
- Modify: `docs/tasks/fixtures/newow/reference-index.json`

**Interfaces:**
- Consumes: API fixture and implemented UI.
- Produces: repeatable interaction/visual acceptance record.

- [ ] **Step 1: Add deterministic API interception**

The Playwright test intercepts:

```text
/api/v1/market/newow/trend-detail
```

and returns `newow-trend-detail.json`.

- [ ] **Step 2: Test the complete included flow on a phone viewport**

Use the reference screenshot's CSS viewport:

```text
width = 414
height = 896
deviceScaleFactor = 2
isMobile = true
hasTouch = true
```

Do not infer safe-area spacing from a different iPhone preset.

Test:
1. open current view;
2. switch to Newow;
3. confirm product and D1;
4. inspect yellow/blue band;
5. click BUILD;
6. close indicator sheet;
7. click D1/D2/D3;
8. open history;
9. select a cup event;
10. pan/zoom and use crosshair;
11. switch back to current view without losing symbol/range.

- [ ] **Step 3: Test explicit exclusions**

Assert absent:
- bottom three indicator tabs;
- target price;
- absorption price;
- performance chart;
-震荡策略/主升浪/AI分析 buttons;
- position recommendation;
- Push/Alert controls.

- [ ] **Step 4: Add desktop smoke**

Desktop may widen but must preserve the same information order and interactions.

- [ ] **Step 5: Create the visual review template**

The template records per screenshot/window:

```text
reference_id
viewport
item
MATCH / MISMATCH / REFERENCE_INSUFFICIENT
notes
```

Required items:
- top bar;
- instrument header;
- orange trend chip;
- chart proportions;
- band color/thickness;
- build/clear cards;
- D marker colors;
- modal shape;
- history sheet.

- [ ] **Step 6: Run E2E**

```bash
cd apps/quant-web
pnpm exec playwright test \
  e2e/newow-trend-detail.spec.mjs \
  e2e/market-research-market-core.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs
```

Expected: PASS.

- [ ] **Step 7: Run final web regression**

```bash
cd apps/quant-web
pnpm test
pnpm build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/e2e/newow-trend-detail.spec.mjs \
  apps/quant-web/playwright.config.mjs \
  docs/tasks/fixtures/newow/visual-review-template.md \
  docs/tasks/fixtures/newow/reference-index.json
git commit -m "test(newow): add detail visual acceptance flow"
```

**Review Gate:** user-facing visual Review is mandatory. If a detail is unclear, label it `REFERENCE_INSUFFICIENT` and ask the user for a focused screenshot; do not improvise.

---

### Task 14: Final Causality, Regression, Documentation, and Completion Review

**Files:**
- Modify: `docs/tasks/2026-09-01-newow-trend-v1-design.md`
- Modify: `docs/tasks/2026-09-01-newow-trend-v1-implementation-plan.md`
- Modify: `docs/ARCHITECTURE.md` only for accepted Newow dependency edges
- Modify: `TESTING.md` only for accepted Newow commands
- Modify: `STATUS.md` only after source and tests are actually complete
- Test: all Newow and touched regressions

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: one reviewed V1 implementation state; no release/runtime action.

- [ ] **Step 1: Run the complete Newow core/API suite**

```bash
cd services/quant-api
uv run pytest tests/newow -q
uv run ruff check ../../packages/quant-core/guiyi_quant/newow app/market_data/newow app/api/market_newow.py app/schemas/market_newow.py tests/newow
uv run mypy ../../packages/quant-core/guiyi_quant/newow app/market_data/newow app/api/market_newow.py app/schemas/market_newow.py
```

Expected: PASS.

- [ ] **Step 2: Run touched API regression**

```bash
cd services/quant-api
uv run pytest tests/data_foundation/test_market_api.py tests/test_market_research_overlays_api.py -q
```

If exact filenames differ at implementation time, use the existing tests that own `/api/v1/market` and `MarketDataService`; record the actual commands in `TESTING.md`, not a new broad suite name.

Expected: PASS.

- [ ] **Step 3: Run web unit/build/E2E**

```bash
cd apps/quant-web
pnpm test
pnpm build
pnpm exec playwright test \
  e2e/newow-trend-detail.spec.mjs \
  e2e/market-research-market-core.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs
```

Expected: PASS.

- [ ] **Step 4: Run explicit invariance matrix**

Record evidence for:
- completed-only;
- prefix invariance;
- batch/incremental parity;
- restore parity;
- physical-contract reset;
- no cross-contract cup;
- no rollover BUILD/CLEAR/D signal;
- first-seen marker identity;
- same-Bar D conflict;
- trend-band warm-up;
- D123 warm-up;
- cup warm-up.

- [ ] **Step 5: Review the diff for forbidden scope**

```bash
git diff --check
git diff --name-only "$(git merge-base develop HEAD)"..HEAD
```

There must be no:
- migration;
- production DB/Redis config;
- Alert/Runtime rule;
- notification code;
- auto-order code;
- generic strategy framework;
- unrelated current-view refactor.

- [ ] **Step 6: Complete the visual reference review**

The human reviewer fills `visual-review-template.md` using the user references. Any blocking MISMATCH returns to the owning task.

- [ ] **Step 7: Update canonical docs only with verified facts**

Set:
- Spec status to `IMPLEMENTED / REVIEW_PENDING` only when code exists;
- Plan checkboxes to the actual completed state;
- `STATUS.md` to `CODE_COMPLETE` or `TEST_COMPLETE` only with command evidence;
- explicitly preserve `NOT_RELEASED`, `RUNTIME_NOT_CHANGED`, `ALERT_NOT_ENABLED`.

- [ ] **Step 8: Independent final review**

Review separately:
1. formula/causality;
2. API/security;
3. UI/reference fidelity;
4. scope/maintenance cost.

Final conclusion must be one of:

```text
ALLOW_DEVELOP_INTEGRATION
REQUIRE_FIXES
BLOCKED
```

- [ ] **Step 9: Commit**

```bash
git add \
  docs/tasks/2026-09-01-newow-trend-v1-design.md \
  docs/tasks/2026-09-01-newow-trend-v1-implementation-plan.md \
  docs/ARCHITECTURE.md \
  TESTING.md \
  STATUS.md
git commit -m "docs(newow): record V1 implementation evidence"
```

Only add files actually changed; do not touch `STATUS.md` before evidence exists.

**Review Gate:** develop integration is not release, main merge, tag, Runtime promotion, Shadow enablement or notification permission.

---

## Task Dependency Order

```text
Task 1 Contracts/Profile
  ↓
Task 2 Trend Band ───────┐
Task 3 D1/D2/D3 ────────┤
Task 4 Cup Handle ───────┤
                         ↓
Task 5 Unified D1 Engine
  ↓
Task 6 MarketDataService Detail Service
  ↓
Task 7 Stateless/Bounded Query Gate
  ↓
Task 8 Read-only API
  ↓
Task 9 Web Types/View Models
  ↓
Task 10 Independent Page Shell
  ↓
Task 11 Newow Chart
  ↓
Task 12 Sheets/History
  ↓
Task 13 E2E/Visual Acceptance
  ↓
Task 14 Final Review
```

Tasks 2, 3, and 4 are formula-independent after Task 1, but for this personal-maintained project they should still be delivered sequentially inside the planned Slices. All other tasks are sequential because their interfaces depend on the preceding task.

## Recommended Delivery Slices

For a personal-maintained project, do not open fourteen simultaneous workstreams. Deliver in five reviewable slices:

```text
Slice A — `feature/newow-d1-core`:
  Task 1–3   contracts + trend band + D123

Slice B — `feature/newow-cup-engine`:
  Task 4–5   cup handle + unified causal engine

Slice C — `feature/newow-detail-api`:
  Task 6–8   application + stateless gate + API

Slice D — `feature/newow-detail-web`:
  Task 9–12  isolated page + chart + sheets

Slice E — `test/newow-v1-acceptance`:
  Task 13–14 visual acceptance + final evidence
```

Each slice should remain understandable by one reviewer without loading the whole repository into context.

## Plan Self-Review

### Spec Coverage

- Independent Current/Newow detail split: Tasks 10–13.
- Newow-only D1 data identity: Tasks 1, 5, 6, 8.
- Yellow/blue band and four states: Tasks 2, 5, 11, 12.
- BUILD/CLEAR markers and reference-change disclaimer: Tasks 2, 11, 12.
- D1/D2/D3 formulas/copy/conflict handling: Tasks 3, 5, 9, 11, 12.
- Cup-handle filters/scoring/lifecycle: Tasks 4, 5, 11, 12.
- Physical contract/rollover rules: Tasks 5, 6, 11, 14.
- Read-only stateless API/no file cache/DB/Redis/Runtime: Tasks 6–8, 14.
- Newow reference UI/interaction: Tasks 10–13.
- Deferred lower indicators/targets/scan/alerts: Global Constraints and Tasks 13–14.
- Causality/prefix/batch-incremental: Tasks 2–6 and 14.

### Placeholder Scan

The placeholder scan found no unfinished sections, unnamed follow-up work, generic test instructions, or unnamed error-handling steps. `REFERENCE_INSUFFICIENT` is an explicit acceptance result from the Spec, not an implementation placeholder.

### Type Consistency

The plan uses the same names across tasks:
- `NewowDailyBar.observation_eligible` for same-contract numeric warm-up;
- `NewowTrendD1Engine.step(NewowDailyBar)`;
- `NewowTrendDetailService.query(NewowTrendDetailQuery)`;
- `NewowTrendDetailResponse`;
- `NewowMainMarker`;
- `NewowCupHandleOverlay`;
- `newow_trend_v1 / newow_trend_d1_v1`.

## Plan Status

```text
IMPLEMENTATION_PLAN_COMPLETE
INTERNAL_PLAN_REVIEW_PASSED
SOURCE_IMPLEMENTATION_NOT_STARTED
RUNTIME_NOT_CHANGED
ALERT_NOT_CHANGED
DATA_NOT_CHANGED
```
