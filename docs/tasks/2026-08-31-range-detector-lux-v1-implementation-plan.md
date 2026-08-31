# Range Detector Lux V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现行苏冰、HTDY、Alert、数据和 Runtime 合同的前提下，交付一个可批量复算、可增量计算、无未来泄漏、Python/TypeScript golden parity，并可在 Market 图表设置中独立开启的 `range_detector_lux_v1` 箱体指标。

**Architecture:** Quant-core Python Kernel 是公式权威；Web TypeScript 只做与共享 golden 对齐的只读显示镜像。Python 与 TypeScript 都以显式状态机处理 ATR、candidate、confirmation、overlap revision 和 break。图表通过独立 Lightweight Charts primitive 绘制回画 box 与向右延伸的 active levels；策略可见性始终以 `confirmed_at` 为准。Market 页在开启指标时预载固定 warm-up，并冻结 session calculation anchor，避免后续 prepend 改写已经稳定的前缀。

**Tech Stack:** Python 3.12、dataclasses、quant-core、pytest、FastAPI repository conventions；TypeScript 6、Vue 3、Node test runner、Lightweight Charts 5、Playwright、pnpm、OpenSpec。

**Spec:** `docs/tasks/2026-08-31-subing-dual-strategy-range-detector-design.md`

**Issue:** `#258`

**Baseline:** `develop@2d53e65cdd811bcf993d45e41471d1f3b33180d4`

## Global Constraints

- 本任务是 **Lane 3：策略输入公式与可信口径**。
- 只实现 Stage 1 Range Detector；不得实现 `subing_daily_trend_v1` 的 Action、Episode、Current、Performance、Alert 或 Runtime evaluator。
- 不修改现行 `subing_strategy_v1` 公式、Rule、Event、Scope、Runtime state 或自然 evidence。
- 不修改 HTDY 公式、周期能力、Rule 或 repainting 合同。
- 不新增 Alembic migration，不连接或写入 RQData、Canonical、production PostgreSQL、Redis 或 Git 外 cache。
- 不发送真实通知，不发布 `main`，不创建正式 tag，不切换 Runtime。
- 不复制 LuxAlgo/TradingView Pine Script；只按批准设计进行 clean-room 行为重写。
- Python Kernel 是公式 authority；浏览器结果只能通过共享 fixture 与 golden parity 获得显示资格。
- `visual_start_at` 是回画起点；`confirmed_at` 是策略首次可见时点。任何实现不得混用。
- 所有价格、边界和 ATR 内部状态必须使用确定性数值路径；不得用 `0`、前值或其他周期静默替代 unavailable 数据。
- 保留 causality、future-tail、prefix invariance、batch/incremental parity 和 fail-closed 测试。
- 只在独立 Review 通过、用户明确给出“允许集成 develop”后合入 `develop`。本计划不授权自动 merge。

## Execution Topology

一个 Stage 1 指标任务使用一个 Codex 会话、一个 task branch/worktree 和一个 Draft PR：

```text
develop@latest
→ feature/range-detector-lux-v1 task worktree
→ 按 Task 1..8 顺序实现并小步提交
→ Draft PR to develop
→ 独立 Sol Review
→ 用户 Gate
→ develop
→ 清理 task worktree/branch
```

不得复用设计文档分支；必须从执行时最新 `develop` 创建：

```bash
git fetch origin
git worktree add ../guiyi-range-detector-lux-v1 -b feature/range-detector-lux-v1 origin/develop
cd ../guiyi-range-detector-lux-v1
```

开始前记录并检查：

```bash
git branch --show-current
git status --short
git log -5 --oneline
```

预期：当前 branch 为 `feature/range-detector-lux-v1`，worktree clean，基线包含 PR #257 的 merge commit。

## File Map

### New files

```text
packages/quant-core/guiyi_quant/indicators/range_detector_lux.py
services/quant-api/tests/test_range_detector_lux.py
tests/fixtures/range_detector_lux_v1_golden.json
apps/quant-web/src/utils/rangeDetectorLux.ts
apps/quant-web/src/components/kline/rangeDetectorPrimitive.ts
apps/quant-web/src/composables/useRangeDetectorOverlayWarmup.ts
apps/quant-web/tests/rangeDetectorLux.test.ts
apps/quant-web/tests/rangeDetectorGolden.test.ts
apps/quant-web/tests/rangeDetectorOverlayWarmup.test.ts
apps/quant-web/tests/rangeDetectorPrimitive.test.ts
apps/quant-web/e2e/market-range-detector.spec.mjs
openspec/specs/range-detector/spec.md
```

### Modified files

```text
packages/quant-core/guiyi_quant/indicators/models.py
packages/quant-core/guiyi_quant/indicators/atr.py
packages/quant-core/guiyi_quant/indicators/__init__.py
packages/quant-core/guiyi_quant/indicators/policy.py
packages/quant-core/guiyi_quant/indicators/registry.py
services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
services/quant-api/tests/test_indicator_registry_v1.py
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/indicators.ts
apps/quant-web/src/utils/klineViewModel.ts
apps/quant-web/src/utils/mainIndicators.ts
apps/quant-web/src/styles/chartTheme.ts
apps/quant-web/src/styles/tokens.css
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/components/kline/KlineHoverLegend.vue
apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/tests/indicators.test.ts
apps/quant-web/tests/kline-view-model.test.ts
apps/quant-web/tests/mainIndicators.test.ts
docs/INDICATOR_KERNEL.md
TESTING.md
```

Do not add a generic strategy adapter, generic channel DTO, database model, scheduler, worker, queue, cache table or Alert Rule.

---

## Task 1: Add an Incremental ATR State Without Changing Existing ATR Outputs

**Files:**

- Modify: `packages/quant-core/guiyi_quant/indicators/models.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/atr.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test: `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`

### Contract

Add this immutable state to `models.py`:

```python
@dataclass(frozen=True, slots=True)
class AtrState:
    period: int
    smoothing_policy: AtrSmoothingPolicy
    count: int
    seed_values: tuple[float, ...]
    previous_close: float | None
    previous_atr: float | None
    round_digits: int = 6
```

Add these public functions to `atr.py`:

```python
def initial_atr_state(
    period: int,
    *,
    smoothing_policy: AtrSmoothingPolicy,
    round_digits: int = 6,
) -> AtrState: ...


def step_atr(
    state: AtrState,
    *,
    high: float | int | None,
    low: float | int | None,
    close: float | int | None,
    bar_end: str | None,
) -> tuple[AtrState, IndicatorPoint]: ...
```

Rules:

```text
wilder_sma_seed:
  seed = SMA(first period true ranges)
  next = (previous_atr * (period - 1) + true_range) / period

invalid high/low/close:
  emit value=None, valid=False, reason=input_invalid
  reset previous_close, previous_atr and seed_values
  keep monotonically increasing count
```

Refactor `atr_series()` to initialize once, call `step_atr()` for every aligned input, and return the exact existing `IndicatorSeries` metadata and values.

### TDD steps

- [ ] Add failing tests for incremental/batch parity.

Append tests that assert all three smoothing policies and invalid-reset behavior:

```python
def test_incremental_atr_matches_batch_for_all_supported_policies() -> None:
    from guiyi_quant.indicators import atr_series, initial_atr_state, step_atr

    highs = [10.0, 11.0, 12.0, 13.0, float("nan"), 20.0, 21.0, 22.0]
    lows = [8.0, 9.0, 10.0, 11.0, 12.0, 18.0, 19.0, 20.0]
    closes = [9.0, 10.0, 11.0, 12.0, 12.5, 19.0, 20.0, 21.0]
    bar_ends = [f"bar-{index}" for index in range(len(closes))]

    for policy in ("wilder_sma_seed", "wilder_first_tr", "ema_first_tr"):
        batch = atr_series(
            highs, lows, closes, 3,
            smoothing_policy=policy,
            bar_ends=bar_ends,
        )
        state = initial_atr_state(3, smoothing_policy=policy)
        streamed = []
        for high, low, close, bar_end in zip(
            highs, lows, closes, bar_ends, strict=True
        ):
            state, point = step_atr(
                state,
                high=high,
                low=low,
                close=close,
                bar_end=bar_end,
            )
            streamed.append(point)
        assert streamed == batch.points
```

- [ ] Run the new test and confirm failure before implementation.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

Expected initial failure: `ImportError` for `initial_atr_state` or `step_atr`.

- [ ] Implement `AtrState`, `initial_atr_state()` and `step_atr()`.
- [ ] Refactor `atr_series()` through `step_atr()` without changing public metadata.
- [ ] Export `AtrState`, `initial_atr_state` and `step_atr` from `__init__.py`.
- [ ] Run the targeted test again and require zero failures.
- [ ] Run existing ATR/MACD regression tests and verify exact output hashes remain unchanged.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- [ ] Commit only Task 1 files.

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/models.py \
  packages/quant-core/guiyi_quant/indicators/atr.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
git commit -m "feat(indicators): add incremental ATR state"
```

---

## Task 2: Implement the Causal Python Range Detector State Machine

**Files:**

- Create: `packages/quant-core/guiyi_quant/indicators/range_detector_lux.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Create: `services/quant-api/tests/test_range_detector_lux.py`

### Public types

Use explicit indicator-specific dataclasses rather than extending generic `IndicatorSeries` into a mega DTO:

```python
from typing import Literal

RangeDetectorState = Literal["intact", "broken_up", "broken_down"]
RangeDetectorTransitionKind = Literal[
    "confirmed",
    "revised",
    "broken_up",
    "broken_down",
    "invalid_reset",
]


@dataclass(frozen=True, slots=True)
class RangeDetectorLuxParameters:
    minimum_range_length: int = 20
    range_width_atr_multiplier: float = 1.0
    range_atr_length: int = 500
    round_digits: int = 6


@dataclass(frozen=True, slots=True)
class RangeDetectorSnapshot:
    formula_version: str
    policy_id: str
    range_id: str
    revision: int
    visual_start_at: str
    confirmed_at: str
    detection_right_at: str
    levels_active_from: str
    initial_upper: float
    initial_lower: float
    current_upper: float
    current_lower: float
    current_mid: float
    state: RangeDetectorState
    broken_at: str | None
    merged_count: int
    candidate_valid: bool
    source_bar_end: str
    source_trading_day: str | None
    source_identity: str


@dataclass(frozen=True, slots=True)
class RangeDetectorTransition:
    kind: RangeDetectorTransitionKind
    range_id: str | None
    revision: int | None
    at: str


@dataclass(frozen=True, slots=True)
class RangeDetectorPoint:
    bar_end: str
    ready: bool
    valid: bool
    reason: str | None
    snapshot: RangeDetectorSnapshot | None
    transition: RangeDetectorTransition | None


@dataclass(frozen=True, slots=True)
class RangeDetectorLuxState:
    parameters: RangeDetectorLuxParameters
    source_identity: str
    atr: AtrState
    index: int
    close_window: tuple[tuple[str, str | None, float], ...]
    previous_candidate_valid: bool
    active_snapshot: RangeDetectorSnapshot | None
    active_detection_right_index: int | None
    last_bar_end: str | None


@dataclass(frozen=True, slots=True)
class RangeDetectorSeries:
    indicator_code: str
    indicator_version: str
    policy_id: str
    parameters: RangeDetectorLuxParameters
    source_identity: str
    points: tuple[RangeDetectorPoint, ...]
    ranges: tuple[RangeDetectorSnapshot, ...]
```

Constants:

```python
RANGE_DETECTOR_LUX_CODE = "range_detector_lux_v1"
RANGE_DETECTOR_LUX_VERSION = "v1"
RANGE_DETECTOR_LUX_POLICY_ID = "range_detector_lux_v1"
```

### Public functions

```python
def initial_range_detector_lux_state(
    *,
    source_identity: str,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorLuxState: ...


def step_range_detector_lux(
    state: RangeDetectorLuxState,
    *,
    high: float | int | None,
    low: float | int | None,
    close: float | int | None,
    bar_end: str,
    trading_day: str | None = None,
) -> tuple[RangeDetectorLuxState, RangeDetectorPoint]: ...


def range_detector_lux_series(
    highs: Sequence[float | int | None],
    lows: Sequence[float | int | None],
    closes: Sequence[float | int | None],
    *,
    bar_ends: Sequence[str],
    source_identity: str,
    trading_days: Sequence[str | None] | None = None,
    minimum_range_length: int = 20,
    range_width_atr_multiplier: float = 1.0,
    range_atr_length: int = 500,
    round_digits: int = 6,
) -> RangeDetectorSeries: ...
```

### Exact state-machine rules

For Bar index `t`:

```text
L = minimum_range_length
ATR = current Wilder-SMA-seed ATR(range_atr_length)
window = closes[t-L+1 .. t]
center = SMA(window)
width = ATR * range_width_atr_multiplier
candidate = every(abs(close_i - center) <= width for close_i in window)
visual_start_at = bar_end[t-L]
```

The state must retain `L + 1` valid close/time observations so `visual_start_at` can refer to the Bar immediately before the L-Bar candidate window.

Per-Bar order:

```text
1. Validate source identity, parameters, bar timestamp and OHLC input.
2. Advance ATR.
3. Build candidate only when ATR and L+1 retained closes are ready.
4. If candidate changes false -> true:
   a. visual_start_index <= previous detection_right_index => overlap revision
   b. otherwise create a new range_id
5. If candidate remains true, extend detection_right_at only.
6. Evaluate exact break using the post-confirmation/revision boundaries.
7. Emit one aligned RangeDetectorPoint for this Bar.
```

Boundaries:

```text
confirmation:
  initial_upper = center + width
  initial_lower = center - width
  current_upper = initial_upper
  current_lower = initial_lower
  revision = 1
  merged_count = 0
  state = intact

overlap revision:
  same range_id
  revision += 1
  merged_count += 1
  current_upper = max(previous.current_upper, candidate_upper)
  current_lower = min(previous.current_lower, candidate_lower)
  current_mid = (current_upper + current_lower) / 2
  confirmed_at = current bar_end
  levels_active_from = current bar_end
  state = intact
  broken_at = None
```

Breaks:

```text
close > current_upper => broken_up
close < current_lower => broken_down
close == either boundary => remains intact
broken state does not revert before a new confirmation/revision
one range_id + revision can emit at most one break transition
```

Causality:

- The point emitted at Bar `t` may include a new confirmation for display.
- Future strategy code must consume the snapshot emitted at `t-1`, never the new snapshot from `t` when evaluating the same Bar.
- `range_id` is the full lowercase SHA-256 hex digest of:

```text
range_detector_lux_v1|source_identity|first_confirmed_at
```

- Do not include `levels_active_until` in incremental state. `RangeDetectorSeries.ranges` may derive it only after the next confirmation is known.
- Require `bar_end` parseable as ISO-8601 and strictly increasing. Use a small private parser that accepts trailing `Z` by converting it to `+00:00` before `datetime.fromisoformat()`.
- Invalid OHLC resets ATR, close window, previous-candidate state and active range; emit `invalid_reset`. No historical box crosses an invalid input.

### TDD steps

- [ ] Create failing parameter and warm-up tests.
- [ ] Add tests for exact confirmation, continuous extension and deterministic ID.
- [ ] Add exact-boundary tests where `close == upper` and `close == lower` remain `intact`.
- [ ] Add tests for `broken_up`, `broken_down`, no automatic recovery and one transition per revision.
- [ ] Add overlap revision tests proving same ID, envelope expansion, revision increment and new causal `confirmed_at`.
- [ ] Add non-overlap tests proving a new deterministic ID and termination of previous active levels.
- [ ] Add invalid-input reset and timestamp fail-closed tests.
- [ ] Add batch/incremental parity and future-tail invariance tests.
- [ ] Add prefix-invariance tests comparing every ready prefix with the corresponding prefix of the full run.

Representative tests must include:

```python
def test_decision_prefix_is_unchanged_by_future_tail() -> None:
    original = range_detector_lux_series(..., closes=base_closes, ...)
    changed = range_detector_lux_series(
        ...,
        closes=[*base_closes[:cutoff], 999.0, 1.0, 999.0],
        ...,
    )
    assert changed.points[:cutoff] == original.points[:cutoff]


def test_batch_matches_incremental_exactly() -> None:
    batch = range_detector_lux_series(...)
    state = initial_range_detector_lux_state(...)
    streamed = []
    for bar in bars:
        state, point = step_range_detector_lux(state, **bar)
        streamed.append(point)
    assert tuple(streamed) == batch.points
```

- [ ] Run tests before implementation and confirm expected import/attribute failures.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] Implement types, validation, calculation, revisions and batch wrapper.
- [ ] Export all public Range Detector constants/types/functions from `__init__.py`.
- [ ] Run targeted tests until zero failures.
- [ ] Run Task 1 and Task 2 together to verify ATR refactor parity remains intact.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] Commit Task 2 files.

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/range_detector_lux.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_range_detector_lux.py
git commit -m "feat(indicators): add causal Range Detector Lux kernel"
```

---

## Task 3: Freeze the Registry, Scoped Policy, Shared Golden and OpenSpec

**Files:**

- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`
- Create: `tests/fixtures/range_detector_lux_v1_golden.json`
- Modify: `services/quant-api/tests/test_range_detector_lux.py`
- Create: `openspec/specs/range-detector/spec.md`
- Modify: `docs/INDICATOR_KERNEL.md`

### Scoped formal policy

Add constants:

```python
RANGE_DETECTOR_DISPLAY_CONSUMER = "range_detector_readonly_display"
RANGE_DETECTOR_RESEARCH_CONSUMER = "subing_daily_trend_research"
```

Add exactly one policy:

```python
"range_detector_lux_v1": FormalPolicy(
    policy_id="range_detector_lux_v1",
    indicator_family="RANGE_DETECTOR",
    seed_policy=None,
    smoothing_policy="wilder_sma_seed",
    histogram_scale=None,
    lookback="range20_atr500_multiplier1",
    confirmed_only=True,
    frozen_legacy=False,
    allowed_consumers=(
        RANGE_DETECTOR_DISPLAY_CONSUMER,
        RANGE_DETECTOR_RESEARCH_CONSUMER,
    ),
    blocked_consumers=(
        FORMAL_BACKTEST_CONSUMER,
        "generic_strategy",
        "generic_live",
        "alert",
        "notification",
    ),
    notes=(
        "Clean-room causal Lux Range behavior for readonly display and the "
        "versioned SuBing daily-trend research candidate only."
    ),
),
```

This is intentionally not a generic backtest or live policy.

### Registry entry

Add `range_detector_lux_v1` to all seven standard frequencies:

```python
"range_detector_lux_v1": build_indicator_definition(
    indicator_code="range_detector_lux_v1",
    indicator_version="v1",
    display_name="箱体识别（Lux Range）",
    display_type="overlay",
    input_fields=("high", "low", "close"),
    supported_intervals=_ALL_INTERVALS,
    default_parameters={
        "minimum_range_length": 20,
        "range_width_atr_multiplier": 1.0,
        "range_atr_length": 500,
        "source": "close",
        "atr_smoothing_policy": "wilder_sma_seed",
        "round_digits": 6,
    },
    lookback_bars=500,
    warmup_bars=499,
    calculation_source=(
        "guiyi_quant.indicators.range_detector_lux."
        "range_detector_lux_series"
    ),
    closed_bar_only=True,
    confirmed_only=True,
    status="strategy_candidate",
    repainting_risk="none",
    repainting_notes=(
        "Kernel outputs are append-only and causal; Web may retrospectively draw "
        "the confirmed box from visual_start_at without making it strategy-visible."
    ),
    web_capable=True,
    backtest_capable=True,
    live_capable=False,
    alert_capable=False,
    default_visible=False,
    default_color="#2563EB",
    output_schema="channel",
    formal_policy_id="range_detector_lux_v1",
    seed_policy=None,
    smoothing_policy="wilder_sma_seed",
    histogram_scale=None,
),
```

### Shared golden fixture

The fixture is cross-runtime evidence, not a source of third-party code. Use reduced test-only parameters to keep it reviewable:

```json
{
  "formula_version": "range_detector_lux_v1",
  "parameters": {
    "minimum_range_length": 4,
    "range_width_atr_multiplier": 1.0,
    "range_atr_length": 5,
    "round_digits": 6
  },
  "source_identity": "golden:actual_dominant:jm:1d",
  "bars": [],
  "expected": {
    "points": [],
    "ranges": []
  },
  "payload_sha256": "..."
}
```

The committed fixture must exercise all of these states:

```text
warming_up
confirmed
continuous candidate extension
broken_up
overlap revised
broken_down
non-overlap new range
exact boundary without break
invalid_reset
```

Generate expected output only after the hand-written formula tests pass. Use a one-off repository-root Python command that:

1. constructs reviewed synthetic bars;
2. calls the Python authority;
3. asserts every required transition appears;
4. serializes sorted keys and stable decimal rounding;
5. computes SHA-256 over `{bars, expected, metadata}`;
6. writes `tests/fixtures/range_detector_lux_v1_golden.json`.

Do not commit a fixture generator script.

### OpenSpec requirements

`openspec/specs/range-detector/spec.md` must include SHALL/MUST scenarios for:

- fixed default parameters;
- completed/confirmed Bar input only;
- `visual_start_at` versus `confirmed_at`;
- exact overlap revision identity;
- exact break boundaries;
- invalid reset;
- deterministic `range_id`;
- batch/incremental parity;
- future-tail and prefix invariance;
- scoped consumer policy;
- Web-only backpaint not granting historical strategy visibility.

### TDD and verification steps

- [ ] Extend registry tests first and confirm the new expected entry fails before implementation.
- [ ] Add policy allow/block tests for both approved consumers and every blocked consumer.
- [ ] Add Python golden fixture test that verifies exact outputs and canonical hash.
- [ ] Implement policy, registry and exports.
- [ ] Create and manually inspect the shared fixture.
- [ ] Add OpenSpec and update `docs/INDICATOR_KERNEL.md` to list EMA/MACD/ATR/Range/HTDY, preserving pure-kernel boundaries.
- [ ] Run targeted tests.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] Run OpenSpec validation.

```bash
openspec validate --specs --strict --no-interactive
```

- [ ] Commit Task 3 files.

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  packages/quant-core/guiyi_quant/indicators/registry.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py \
  tests/fixtures/range_detector_lux_v1_golden.json \
  openspec/specs/range-detector/spec.md \
  docs/INDICATOR_KERNEL.md
git commit -m "test(indicators): freeze Range Detector policy and golden"
```

### Formula checkpoint

Before starting browser work, review the diff for Tasks 1–3 with a fresh independent reviewer. The reviewer must explicitly inspect:

```text
ATR output parity
candidate window indexing
visual_start_at indexing
confirmation/revision order
overlap identity
exact-boundary comparisons
invalid reset
future-tail and prefix tests
policy consumer boundaries
```

Record review findings in the Draft PR. Fix blocking findings before Task 4. This checkpoint does not authorize merge.

---

## Task 4: Implement the TypeScript Readonly Mirror and Cross-Runtime Golden Parity

**Files:**

- Create: `apps/quant-web/src/utils/rangeDetectorLux.ts`
- Modify: `apps/quant-web/src/utils/indicators.ts`
- Create: `apps/quant-web/tests/rangeDetectorLux.test.ts`
- Create: `apps/quant-web/tests/rangeDetectorGolden.test.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`

### Public browser API

```typescript
export type RangeDetectorState = 'intact' | 'broken_up' | 'broken_down'
export type RangeDetectorTransitionKind =
  | 'confirmed'
  | 'revised'
  | 'broken_up'
  | 'broken_down'
  | 'invalid_reset'

export interface RangeDetectorLuxOptions {
  sourceIdentity: string
  minimumRangeLength?: number
  rangeWidthAtrMultiplier?: number
  rangeAtrLength?: number
  roundDigits?: number
}

export interface RangeDetectorSnapshot {
  formulaVersion: 'range_detector_lux_v1'
  policyId: 'range_detector_lux_v1'
  rangeId: string
  revision: number
  visualStartAt: string
  confirmedAt: string
  detectionRightAt: string
  levelsActiveFrom: string
  initialUpper: number
  initialLower: number
  currentUpper: number
  currentLower: number
  currentMid: number
  state: RangeDetectorState
  brokenAt: string | null
  mergedCount: number
  candidateValid: boolean
  sourceBarEnd: string
  sourceTradingDay: string | null
  sourceIdentity: string
}

export interface RangeDetectorPoint {
  time: string
  ready: boolean
  valid: boolean
  reason: string | null
  snapshot: RangeDetectorSnapshot | null
  transition: {
    kind: RangeDetectorTransitionKind
    rangeId: string | null
    revision: number | null
    at: string
  } | null
}

export interface RangeDetectorVisualRange {
  key: string
  rangeId: string
  revision: number
  visualStartAt: string
  detectionRightAt: string
  levelsActiveFrom: string
  levelsActiveUntil: string | null
  confirmedAt: string
  upper: number
  lower: number
  mid: number
  state: RangeDetectorState
  brokenAt: string | null
}

export interface RangeDetectorLuxResult {
  points: RangeDetectorPoint[]
  ranges: RangeDetectorVisualRange[]
}

export function calculateRangeDetectorLux(
  bars: BarData[],
  options: RangeDetectorLuxOptions,
): RangeDetectorLuxResult
```

Implementation rules:

- Mirror the approved Python state machine; do not import strategy code or API DTOs.
- Use a module-private Wilder SMA seed ATR state with the same reset behavior.
- Use `crypto.subtle` only if asynchronous behavior is acceptable; it is not. For deterministic synchronous IDs, implement the same repository-reviewed SHA-256 helper already used by tests or use a compact synchronous pure TypeScript SHA-256 function isolated in this module. Do not substitute a non-cryptographic hash.
- Validate timestamps with `Date.parse()` and require strict monotonicity.
- Preserve full 64-character lowercase SHA-256 IDs.
- The browser module may return retrospective visual ranges, but `confirmedAt` remains explicit.

### Tests

- [ ] Write TypeScript unit tests matching every Python state-machine scenario.
- [ ] Write append and future-tail invariance tests.
- [ ] Write invalid-input and timestamp fail-closed tests.
- [ ] Write a shared golden test that reads `tests/fixtures/range_detector_lux_v1_golden.json` from repository root, converts null numeric inputs to `Number.NaN`, compares points/ranges/metadata exactly, and verifies `payload_sha256`.
- [ ] Confirm tests fail before implementation.

```bash
pnpm -C apps/quant-web exec node --test \
  tests/rangeDetectorLux.test.ts \
  tests/rangeDetectorGolden.test.ts
```

Expected initial failure: module not found.

- [ ] Implement `rangeDetectorLux.ts`.
- [ ] Add only a thin named export from `utils/indicators.ts`; do not duplicate the formula there.
- [ ] Run targeted tests until zero failures.
- [ ] Run all existing indicator tests to ensure EMA/MACD/ATR/HTDY parity is unchanged.

```bash
pnpm -C apps/quant-web run test:indicators
pnpm -C apps/quant-web exec node --test \
  tests/rangeDetectorLux.test.ts \
  tests/rangeDetectorGolden.test.ts
```

- [ ] Commit Task 4 files.

```bash
git add \
  apps/quant-web/src/utils/rangeDetectorLux.ts \
  apps/quant-web/src/utils/indicators.ts \
  apps/quant-web/tests/rangeDetectorLux.test.ts \
  apps/quant-web/tests/rangeDetectorGolden.test.ts \
  apps/quant-web/tests/indicators.test.ts
git commit -m "feat(web): mirror Range Detector Lux with golden parity"
```

---

## Task 5: Add Preference V8 and a Stable Warm-up/Calculation Anchor

**Files:**

- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Create: `apps/quant-web/src/composables/useRangeDetectorOverlayWarmup.ts`
- Create: `apps/quant-web/tests/rangeDetectorOverlayWarmup.test.ts`

### Type and registry changes

Change:

```typescript
export type MainIndicatorId =
  | 'ema_10'
  | 'ema_21'
  | 'ema_60'
  | 'range_detector'
  | 'htdy'
```

Keep `OptionalEmaIndicatorId` unchanged.

Add one Web definition:

```typescript
{
  id: 'range_detector',
  name: 'range_detector_lux_v1',
  displayName: '箱体识别（Lux Range）',
  pane: 'main',
  renderer: 'band',
  capability: 'standard_overlay',
  defaultVisible: false,
  parameters: {
    minimumRangeLength: 20,
    rangeWidthAtrMultiplier: 1,
    rangeAtrLength: 500,
  },
  lookbackBars: 500,
  alertCapable: false,
  available: true,
}
```

### Preference v8

Use a new key and one-way migration:

```typescript
export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v8'
export const MAIN_CHART_PREFERENCES_VERSION = 8

export interface MainChartPreferences {
  version: 8
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
  showSubingInternalProcess: boolean
  showSubingStrategyPerformance: boolean
  period?: string | null
  realtimeFollow?: boolean
}
```

Rules:

- Default `showRangeDetector=false`.
- v7 → v8 preserves every v7 field and adds `showRangeDetector=false`.
- v6/v5 migrate directly into v8 with the existing overlay-retirement behavior.
- Purge the old v7 key only after successful v8 persistence; if persistence throws, return the readable migrated value without deleting source data.
- `visibleMainIndicatorsForOverlay()` receives a third argument:

```typescript
export function visibleMainIndicatorsForOverlay(
  overlay: ResearchOverlayId,
  optionalEmaIndicators: OptionalEmaIndicatorId[] = [],
  showRangeDetector = false,
): MainIndicatorId[]
```

For `overlay='none'`, preserve current behavior and return `[]`. For `subing` or `htdy`, append `range_detector` when enabled, before overlay-owned `htdy`.

### Warm-up composable

The existing initial page is 300 Bars while ATR500 requires more history. Add a session-only composable:

```typescript
export const RANGE_DETECTOR_REQUIRED_BARS = 520

export interface RangeDetectorOverlayWarmupOptions {
  bars: Readonly<Ref<BarData[]>>
  hasMoreBefore: Readonly<Ref<boolean>>
  enabled: Readonly<Ref<boolean>>
  identityKey: Readonly<Ref<string>>
  loadMoreBefore: () => Promise<void>
}

export function useRangeDetectorOverlayWarmup(
  options: RangeDetectorOverlayWarmupOptions,
): {
  anchorTime: Readonly<Ref<string | null>>
  loading: Readonly<Ref<boolean>>
  unavailableReason: Readonly<Ref<string | null>>
  ensureReady: () => Promise<void>
  reset: () => void
}
```

Exact behavior:

```text
enabled false:
  anchorTime = null
  cancel current generation

enabled true or identity changes:
  generation += 1
  anchorTime = null
  while same generation and enabled and bars.length < 520 and hasMoreBefore:
      await loadMoreBefore()
  if same generation and bars not empty:
      anchorTime = bars[0].time
  if bars.length < 500:
      unavailableReason = RANGE_DETECTOR_WARMUP_INSUFFICIENT
  else:
      unavailableReason = null
```

After `anchorTime` is frozen, later manual prepend does not change it. The Range calculation filters input to `bar.time >= anchorTime`, so already-ready results cannot drift when older pages are loaded.

Identity key must include:

```text
seriesKind | symbol | contract-or-empty | frequency
```

Do not persist `anchorTime` to localStorage.

### Tests

- [ ] Update existing preference tests first; confirm failures against v7 behavior.
- [ ] Cover default, save/load, v7→v8, v6/v5→v8, persistence failure, invalid JSON and retired keys.
- [ ] Assert indicator order for `subing`, `htdy` and `none`.
- [ ] Test warm-up loops from 300 to at least 520 Bars.
- [ ] Test no-more-history with fewer than 500 Bars returns explicit unavailable.
- [ ] Test identity changes cancel stale generations.
- [ ] Test later prepend does not move a frozen anchor.

```bash
pnpm -C apps/quant-web exec node --test \
  tests/mainIndicators.test.ts \
  tests/rangeDetectorOverlayWarmup.test.ts
```

- [ ] Implement types, v8 migration, definition and composable.
- [ ] Run targeted tests and full Web unit suite.

```bash
pnpm -C apps/quant-web test
```

- [ ] Commit Task 5 files.

```bash
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/src/composables/useRangeDetectorOverlayWarmup.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/rangeDetectorOverlayWarmup.test.ts
git commit -m "feat(web): persist and warm Range Detector overlay"
```

---

## Task 6: Build the Derived View Model, Hover Facts and Chart Primitive

**Files:**

- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Create: `apps/quant-web/src/components/kline/rangeDetectorPrimitive.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Modify: `apps/quant-web/src/styles/chartTheme.ts`
- Modify: `apps/quant-web/src/styles/tokens.css`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Create: `apps/quant-web/tests/rangeDetectorPrimitive.test.ts`

### Derived-data contract

Extend options without changing existing callers:

```typescript
export interface KlineDerivedOptions {
  showSubingEmaRibbon?: boolean
  rangeDetector?: {
    enabled: boolean
    sourceIdentity: string
    anchorTime: string | null
  }
}
```

Extend derived data:

```typescript
export interface KlineDerivedData {
  ema: ...
  macd: ...
  htdy: HtdyDerivedData | null
  subingEmaRibbon: SubingEmaRibbon | null
  rangeDetector: RangeDetectorLuxResult | null
}
```

Calculation:

```typescript
const anchoredBars = options.rangeDetector?.anchorTime
  ? bars.filter((bar) => Date.parse(bar.time) >= Date.parse(options.rangeDetector!.anchorTime!))
  : []

const rangeDetector = options.rangeDetector?.enabled
  && options.rangeDetector.anchorTime
  ? calculateRangeDetectorLux(anchoredBars, {
      sourceIdentity: options.rangeDetector.sourceIdentity,
    })
  : null
```

No anchor means no partial boxes. Do not silently calculate from an unstable 300-Bar page.

### Hover context

Add an optional fact block:

```typescript
rangeDetector?: {
  rangeId: string
  revision: number
  state: RangeDetectorState
  upper: number
  lower: number
  mid: number
  confirmedAt: string
  visualStartAt: string
} | null
```

At a hover time, use the most recent point at or before that Bar whose active-level interval contains the time. Display:

```text
箱体 上沿 / 中线 / 下沿 / 状态
箱体起点为回画展示；策略自确认时刻起才可使用
```

Do not imply that the box was known at `visualStartAt`.

### Primitive contract

Attach `RangeDetectorPrimitive` to the candlestick series, following the existing series-primitive lifecycle:

```typescript
export class RangeDetectorPrimitive implements ISeriesPrimitive<Time> {
  setData(
    ranges: readonly RangeDetectorVisualRange[],
    lastBarTime: string | null,
    timeOf: (iso: string) => Time | null,
  ): void
}
```

Render in media coordinate space:

- translucent box from `visualStartAt` to `detectionRightAt`;
- upper/lower active lines from `levelsActiveFrom` to `levelsActiveUntil ?? lastBarTime`;
- dotted midline over the same active-level interval;
- intact tone blue;
- `broken_up` tone green;
- `broken_down` tone red;
- confirmation indicator visually weak and non-marker-based;
- primitive `zOrder='bottom'` so candles and action markers remain readable.

Do not mutate candlestick data and do not convert box boundaries into strategy markers.

### Theme fields

Add explicit theme properties and CSS tokens:

```typescript
rangeIntact: string
rangeBrokenUp: string
rangeBrokenDown: string
rangeFill: string
rangeMid: string
```

Fallbacks:

```text
rangeIntact     #2563EB
rangeBrokenUp   #16A34A
rangeBrokenDown #DC2626
rangeFill       rgba(37, 99, 235, 0.10)
rangeMid        rgba(37, 99, 235, 0.65)
```

### KlineChart props

Add:

```typescript
rangeDetectorSourceIdentity?: string
rangeDetectorAnchorTime?: string | null
```

The primitive is enabled only when `visibleMainIndicators` includes `range_detector` and both identity/anchor are present.

On every replace/prepend/live update:

- rebuild deterministic derived data from anchored bars;
- preserve viewport behavior;
- call `rangeDetectorPrimitive.setData()`;
- never move the anchor inside KlineChart.

### Tests

- [ ] Add derived-data tests for disabled/no-anchor/ready states.
- [ ] Add hover tests proving `confirmedAt` remains distinct from `visualStartAt`.
- [ ] Extract and test pure draw-command generation from the primitive: x/time intervals, upper/lower order, colors, active-level end and missing-coordinate omission.
- [ ] Add prepend tests proving older Bars before anchor do not alter existing Range results.
- [ ] Add append tests proving new completed Bars extend the result.
- [ ] Confirm tests fail before implementation.

```bash
pnpm -C apps/quant-web exec node --test \
  tests/kline-view-model.test.ts \
  tests/rangeDetectorPrimitive.test.ts
```

- [ ] Implement derived model, primitive, hover facts and theme.
- [ ] Run targeted tests, full Web unit tests and TypeScript build.

```bash
pnpm -C apps/quant-web test
pnpm -C apps/quant-web exec vue-tsc -b
```

- [ ] Commit Task 6 files.

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/components/kline/rangeDetectorPrimitive.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/styles/chartTheme.ts \
  apps/quant-web/src/styles/tokens.css \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/tests/rangeDetectorPrimitive.test.ts
git commit -m "feat(web): render Range Detector chart primitive"
```

---

## Task 7: Wire the Chart Setting, Page Orchestration and E2E Behavior

**Files:**

- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/e2e/market-range-detector.spec.mjs`
- Modify: `apps/quant-web/e2e/market-research.helpers.mjs` only if a reusable range fixture helper is required

### Toolbar contract

Add prop and emit:

```typescript
showRangeDetector: boolean

'update:show-range-detector': [value: boolean]
```

Add under EMA settings:

```vue
<div class="toolbar__settings-title">
  <span>箱体识别</span>
  <NSwitch
    :value="showRangeDetector"
    size="small"
    aria-label="显示箱体识别"
    @update:value="emit('update:show-range-detector', $event)"
  />
</div>
<small class="toolbar__settings-help">
  使用已完成 K 线；箱体左端为回画展示，确认前不可用于策略判断
</small>
```

Do not expose length, ATR length or multiplier controls.

### Page orchestration

In `chart.vue`:

- initialize `showRangeDetector` from v8 preferences;
- instantiate `useRangeDetectorOverlayWarmup()` using Market Bars, `hasMoreBefore`, effective identity key and raw `loadMoreBefore()`;
- call `ensureReady()` when enabled or identity changes;
- disable/cancel warm-up when toggled off;
- include `showRangeDetector` in preference persistence;
- call `visibleMainIndicatorsForOverlay(selectedOverlay, optionalEmaIndicators, showRangeDetector)`;
- pass `rangeDetectorSourceIdentity` and `rangeDetectorAnchorTime` into `KlineChart`;
- expose data attributes for E2E:

```text
data-range-detector-enabled=true|false
data-range-detector-anchor=<ISO or absent>
data-range-detector-warmup=loading|ready|insufficient|disabled
```

Source identity must be deterministic and include the effective chart identity:

```typescript
const rangeDetectorSourceIdentity = computed(() => [
  effectiveIdentity.value.seriesKind,
  effectiveIdentity.value.symbol,
  effectiveIdentity.value.contract ?? '',
  frequency.value,
].join(':'))
```

Do not let `overlay=subing` or `overlay=htdy` change the formula identity. The indicator is an optional standard overlay.

When preload fails:

- preserve existing chart and other indicators;
- set a public, redacted UI warning `箱体历史预载失败`;
- do not show partial Range boxes;
- allow the user to toggle off/on to retry once through the normal user action.

### E2E scenarios

Create a focused Playwright spec with route fixtures that return at least 540 deterministic Bars over multiple pages.

Required tests:

1. Range is off by default and no range primitive data is present.
2. Enabling the switch fetches earlier pages until at least 520 Bars or history ends.
3. Anchor is set once after warm-up and remains unchanged when the user pans left and triggers another prepend.
4. Box visualization appears only after anchor readiness.
5. Hover warning contains `确认前不可用于策略判断`.
6. Toggle state survives page reload through v8 localStorage.
7. Switching symbol/frequency resets the anchor and calculates a new source identity.
8. Existing SuBing EMA ribbon and HTDY paths remain usable.
9. Fullscreen and narrow viewport do not throw and retain the box layer.
10. Insufficient history yields an explicit warning and no fabricated box.

Use the existing Market route helper patterns; do not hit the real API or WebSocket.

### TDD and implementation steps

- [ ] Write the E2E spec first and run the default-off test to confirm the new control is absent.
- [ ] Add Toolbar unit-level expectations in existing Web tests where practical.
- [ ] Implement prop/emit wiring and page orchestration.
- [ ] Run the focused E2E spec.

```bash
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-range-detector.spec.mjs
```

- [ ] Run existing Market chart interaction and SuBing/HTDY E2E regression specs.

```bash
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-research-chart-interaction.spec.mjs \
  e2e/market-research-subing-current-history.spec.mjs
```

- [ ] Run Web build.

```bash
pnpm -C apps/quant-web build
```

- [ ] Commit Task 7 files.

```bash
git add \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/e2e/market-range-detector.spec.mjs \
  apps/quant-web/e2e/market-research.helpers.mjs
git commit -m "feat(web): expose Range Detector chart setting"
```

If `market-research.helpers.mjs` is unchanged, omit it from `git add`.

---

## Task 8: Finalize Documentation, Verification and the Draft PR

**Files:**

- Modify: `TESTING.md`
- Modify: `docs/INDICATOR_KERNEL.md` only for corrections discovered during implementation
- Modify: `openspec/specs/range-detector/spec.md` only for corrections discovered during implementation
- Do not modify: `STATUS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`

### TESTING.md additions

Add a focused Range Detector section with these read-only commands:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py

pnpm -C apps/quant-web exec node --test \
  tests/rangeDetectorLux.test.ts \
  tests/rangeDetectorGolden.test.ts \
  tests/rangeDetectorOverlayWarmup.test.ts \
  tests/rangeDetectorPrimitive.test.ts \
  tests/mainIndicators.test.ts \
  tests/kline-view-model.test.ts

pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-range-detector.spec.mjs
```

State explicitly that these checks do not authorize data writes, Alert, release or Runtime promotion.

### Full verification

Run every command fresh and record exact result counts in the PR:

- [ ] Focused backend tests.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] Full non-isolated backend suite.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] Ruff.

```bash
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app \
  services/quant-api/tests \
  packages/quant-core/guiyi_quant \
  tests/engineering
```

- [ ] Mypy.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy \
  --explicit-package-bases \
  --ignore-missing-imports \
  services/quant-api/app \
  packages/quant-core/guiyi_quant
```

- [ ] Full Web unit suite.

```bash
pnpm -C apps/quant-web test
```

- [ ] Focused and regression E2E.

```bash
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-range-detector.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs \
  e2e/market-research-subing-current-history.spec.mjs
```

- [ ] Web build and alert ownership guard.

```bash
pnpm -C apps/quant-web run check:alert-rules
pnpm -C apps/quant-web build
```

- [ ] OpenSpec, canonical consistency, secret scan and diff check.

```bash
openspec validate --specs --strict --no-interactive
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Do not run isolated PostgreSQL tests without an explicitly provided disposable isolated DB. Do not run any real-data warm command.

### PR preparation

- [ ] Commit TESTING.md and final contract corrections.

```bash
git add TESTING.md docs/INDICATOR_KERNEL.md openspec/specs/range-detector/spec.md
git commit -m "docs: finalize Range Detector validation contract"
```

- [ ] Verify the complete branch diff contains no unrelated files.

```bash
git status --short
git diff --stat origin/develop...HEAD
git diff --name-only origin/develop...HEAD
git log --oneline origin/develop..HEAD
```

- [ ] Push branch and create a Draft PR to `develop` linked to Issue #258.

PR title:

```text
feat: add causal Range Detector Lux V1 indicator
```

PR body must include:

```text
Summary
Formula identity and fixed parameters
visual_start_at / confirmed_at causality boundary
Shared Python/TypeScript golden hash
ATR batch-output parity evidence
Unit/E2E/build/static-check commands and exact results
Known limitations: display/research only, no trend strategy, no Alert/Runtime
Files intentionally not changed: STATUS, production migration, Scope, main/tag
Closes #258 only after merge
```

- [ ] Keep the PR Draft. Do not merge.

## Independent Review Gate

Open a **new Sol/high reasoning Review session** against the Draft PR. The reviewer must inspect, not merely rerun tests:

1. formula transcription and indexing;
2. strict-before and visual-backpaint separation;
3. invalid reset and segment/source identity behavior;
4. Python/TypeScript golden independence and hash stability;
5. append/prepend invariance;
6. preference migration safety;
7. canvas primitive lifecycle, viewport and pagination behavior;
8. absence of Alert, Runtime, migration, production-write and generic-strategy expansion;
9. no silent changes to current SuBing or HTDY behavior.

Required review conclusion:

```text
允许集成 develop
要求修正后再集成
阻塞
```

Only `允许集成 develop` plus the user's explicit integration approval permits merge. Merge to `develop` still does not authorize `main`, tag, release, Runtime, data writes or notifications.

## Completion Report

The implementation session must finish by reporting:

```text
Branch/worktree
Commits
Changed files
Formula identity and policy
Golden fixture SHA-256
Targeted test results
Full test/static/build results
Draft PR URL
Independent Review status
Unresolved risks
External Gates still pending
```

Do not claim `RELEASED` or `RUNTIME_READY`. The maximum status for this task before merge is:

```text
CODE_COMPLETE
TEST_COMPLETE
INDEPENDENT_REVIEW_PENDING
```
