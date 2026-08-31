# 苏冰趋势策略-日 Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `苏冰趋势策略-日 / subing_daily_trend_v1` 的最小 completed-D1 增量策略内核、Historical Projection 与研究报告，先得到 JM/AG/RB/EG 和 active60 的真实历史效果，再决定是否继续 Current/API/Web/Alert。

**Architecture:** 新策略放在独立 `subing_daily_trend` 包中，不修改现行 `subing_strategy_v1`。Python completed-D1 增量状态机是唯一策略语义 owner；EMA/MACD/ATR 与 Range 复用现有 Quant Core，Range 只做 CHOP regime gate。Historical 通过 `MarketDataService` 的 `actual_dominant + 1d` 和权威 rank1 物理段重放同一个状态机；效果计算只消费 Action/Episode，不建设账户或正式回测域。

**Tech Stack:** Python 3.12、dataclasses、Decimal、quant-core indicator kernel、MarketDataService、pytest、现有 `guiyi research` CLI。

**Spec:** `docs/tasks/2026-08-31-subing-trend-daily-strategy-spec.md`

**Issue:** `#275`

**Planning baseline inspected:** `develop@472db690b9ecf41cdde18c4558367588cd06c24b`

## Global Constraints

- 任务车道为 **Lane 3**，策略公式和可信口径必须由 Sol/high 独立 Review。
- 开工前必须确认 Spec 与本 Plan 已进入执行时最新 `origin/develop`；计划文档中的 baseline 只记录设计时事实。
- 正式名称固定为 `苏冰趋势策略-日`，内部 `strategy_id/formula_version/policy_id` 固定为 `subing_daily_trend_v1`。
- 正式数据身份固定 `actual_dominant + 1d`，只消费 completed D1。
- Range：`range_detector_lux_v1 / length=20 / width=1.0×ATR500 / wilder_sma_seed`，仅做 CHOP gate。
- EMA：EMA21、`sma_window` seed，最近 5 个 EMA21 点做线性回归 slope；只使用 5-bar slope。
- MACD：`12/26/9`、`sma_window` seed、histogram scale 2；near-zero 固定 `max(abs(DIF), abs(DEA)) / ATR14 <= 0.25`。
- 多头只要求 `TREND_ELIGIBLE + close>EMA21 + slope5>0 + near-zero golden cross`；空头完全对称。
- 不要求 Range breakout、EMA crossover、1.5 ATR 距离、成交量、持仓量、BOLL、3-Bar confirmation、前高前低、多周期共振或二次确认。
- completed D1 `t` 只做 decision；参考生效价固定下一根同物理合约 D1 open。
- 普通退出只有 EMA21 opposite cross；物理段终止使用旧段最后一根 D1 close。
- 不加仓、不减仓、不反手、不跨物理段、不建设账户/订单/资金曲线。
- Stage A 不实现 Current、HTTP API、Market Web、Alert Rule、migration、Scope、PushPlus、main/tag、release 或 Runtime。
- 不写 RQData、Canonical、production PostgreSQL、Redis 或 Git 外生产状态。
- 真实 Historical 效果运行如果需要连接本机正式 Catalog/Canonical 环境，必须在运行前再次确认 read-only 环境和范围；测试和 fake fixtures 不构成该授权。
- 所有必要检查失败时只能报告失败，不得声明完成。

---

## File Map

### New files

```text
data/research_policies/subing_daily_trend_v1.json
services/quant-api/app/market_data/subing_daily_trend/__init__.py
services/quant-api/app/market_data/subing_daily_trend/contracts.py
services/quant-api/app/market_data/subing_daily_trend/policy.py
services/quant-api/app/market_data/subing_daily_trend/indicators.py
services/quant-api/app/market_data/subing_daily_trend/machine.py
services/quant-api/app/market_data/subing_daily_trend/replay.py
services/quant-api/app/market_data/subing_daily_trend/report.py
services/quant-api/app/research/subing/subing_daily_trend_research_service.py
services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
services/quant-api/tests/research/test_subing_daily_trend_indicators.py
services/quant-api/tests/research/test_subing_daily_trend_machine.py
services/quant-api/tests/research/test_subing_daily_trend_replay.py
services/quant-api/tests/research/test_subing_daily_trend_report.py
services/quant-api/tests/research/test_subing_daily_trend_research_service.py
services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

### Modified files

```text
packages/quant-core/guiyi_quant/indicators/range_detector_lux.py
packages/quant-core/guiyi_quant/indicators/__init__.py
services/quant-api/app/market_data/subing_ema_trend.py
services/quant-api/tests/test_subing_ema_trend.py
services/quant-api/tests/test_range_detector_lux.py
services/quant-api/app/research/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/research/test_research_cli_parser_requests.py
TESTING.md
```

Do not create a generic strategy adapter, universal replay engine, account model, database table, snapshot store, worker, queue, scheduler or Alert Rule.

---

## Task 1: Add the Range physical-segment regime reset seam

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/range_detector_lux.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test: `services/quant-api/tests/test_range_detector_lux.py`

**Interfaces:**
- Consumes: existing `RangeDetectorLuxState`.
- Produces:

```python
def reset_range_detector_lux_regime(
    state: RangeDetectorLuxState,
) -> RangeDetectorLuxState:
    return replace(
        state,
        close_window=(),
        previous_candidate_valid=False,
        active_snapshot=None,
        active_detection_right_index=None,
    )
```

The function must preserve `parameters`, `source_identity`, `atr`, `index`, and `last_bar_end` exactly.

- [ ] **Step 1: Write the failing segment-reset tests**

Add tests proving:

```python
def test_range_regime_reset_keeps_atr_but_drops_box_state() -> None:
    state = initial_range_detector_lux_state(
        source_identity="subing_daily_trend_v1|jm|actual_dominant|1d",
        minimum_range_length=4,
        range_atr_length=5,
    )
    for index in range(6):
        state, _ = step_range_detector_lux(
            state,
            high=101,
            low=99,
            close=100,
            bar_end=f"2026-01-0{index + 1}T07:00:00+00:00",
            trading_day=f"2026-01-0{index + 1}",
        )
    assert state.atr.previous_atr is not None
    before_atr = state.atr
    reset = reset_range_detector_lux_regime(state)
    assert reset.atr == before_atr
    assert reset.close_window == ()
    assert reset.active_snapshot is None
    assert reset.previous_candidate_valid is False
```

Also prove that after reset Range remains not-ready until `minimum_range_length + 1` current-segment closes have accumulated even though ATR is already ready.

- [ ] **Step 2: Run the focused tests and confirm the expected import failure**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py
```

Expected before implementation: import/name failure for `reset_range_detector_lux_regime`.

- [ ] **Step 3: Implement only the regime reset helper and export it**

Do not change candidate, confirmation, revision, break, ATR or display semantics.

- [ ] **Step 4: Run Range and indicator regression tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/range_detector_lux.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/tests/test_range_detector_lux.py
git commit -m "feat(indicators): add Range regime segment reset"
```

---

## Task 2: Freeze the exact daily-trend policy and immutable contracts

**Files:**
- Create: `data/research_policies/subing_daily_trend_v1.json`
- Create: `services/quant-api/app/market_data/subing_daily_trend/__init__.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/contracts.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/policy.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py`

**Exact policy JSON:**

```json
{
  "schema_version": 1,
  "strategy_id": "subing_daily_trend_v1",
  "formula_version": "subing_daily_trend_v1",
  "policy_id": "subing_daily_trend_v1",
  "research_only": true,
  "series_kind": "actual_dominant",
  "decision_frequency": "1d",
  "range": {
    "indicator_code": "range_detector_lux_v1",
    "minimum_range_length": 20,
    "range_width_atr_multiplier": 1.0,
    "range_atr_length": 500,
    "source": "close",
    "atr_smoothing_policy": "wilder_sma_seed",
    "regime_rule": "ready_and_no_intact_range_is_trend_eligible"
  },
  "ema": {
    "period": 21,
    "seed_policy": "sma_window",
    "slope_window": 5,
    "direction_rule": "price_side_and_slope"
  },
  "macd": {
    "fast": 12,
    "slow": 26,
    "signal": 9,
    "ema_seed_policy": "sma_window",
    "histogram_scale": 2,
    "near_zero_atr14_max": 0.25
  },
  "atr14": {
    "period": 14,
    "smoothing_policy": "wilder_sma_seed"
  },
  "execution": {
    "decision_basis": "completed_d1_close",
    "effective_fill_basis": "next_existing_same_physical_contract_d1_open",
    "allow_reverse": false
  },
  "exit": {
    "ordinary": "ema21_opposite_cross",
    "segment_terminal": "last_same_physical_contract_d1_close"
  }
}
```

**Required public contracts:**

```python
SUBING_DAILY_TREND_ID = "subing_daily_trend_v1"

class SubingDailyTrendRegime(StrEnum):
    DATA_UNAVAILABLE = "data_unavailable"
    CHOP = "chop"
    TREND_ELIGIBLE = "trend_eligible"

class SubingDailyTrendMacdCross(StrEnum):
    NONE = "none"
    GOLDEN = "golden"
    DEAD = "dead"

class SubingDailyTrendPositionState(StrEnum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"

class SubingDailyTrendActionKind(StrEnum):
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"

class SubingDailyTrendFillBasis(StrEnum):
    NEXT_D1_OPEN = "next_d1_open"
    SEGMENT_TERMINAL_CLOSE = "segment_terminal_close"
```

Add frozen dataclasses for `SubingDailyTrendFacts`, `SubingDailyTrendPendingAction`, `SubingDailyTrendAction`, `SubingDailyTrendCancellation`, and `SubingDailyTrendEpisode`. Prices, ratios and reference changes are `Decimal`. IDs are deterministic SHA-256 canonical IDs with prefixes `subing-daily-trend-action:` and `subing-daily-trend-episode:`.

- [ ] **Step 1: Write policy and contract tests first**

Tests must reject policy drift in every fixed parameter and verify identical identity fields produce identical IDs while any material identity field change produces a different ID.

- [ ] **Step 2: Run and confirm failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
```

- [ ] **Step 3: Implement the exact policy loader using `load_exact_json` and immutable contracts**

Do not add runtime-adjustable thresholds.

- [ ] **Step 4: Re-run tests and run the existing SuBing contract/policy suite**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  data/research_policies/subing_daily_trend_v1.json \
  services/quant-api/app/market_data/subing_daily_trend \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py
git commit -m "feat(subing): freeze daily trend policy and contracts"
```

---

## Task 3: Build one stitched daily indicator stream

**Files:**
- Modify: `services/quant-api/app/market_data/subing_ema_trend.py`
- Modify: `services/quant-api/tests/test_subing_ema_trend.py`
- Create: `services/quant-api/app/market_data/subing_daily_trend/indicators.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_indicators.py`

**Interfaces:**

Expose the existing slope math without changing its semantics:

```python
def ema_regression_slope_bps(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        raise ValueError("EMA_REGRESSION_WINDOW_INVALID")
    raw = _regression_slope(values)
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    if mean == 0:
        raise ValueError("EMA_REGRESSION_MEAN_ZERO")
    return raw / mean * Decimal(10000)
```

Refactor existing `subing_ema_trend.py` to call this helper for its 5/10-bar bps fields and prove old snapshots are unchanged.

Create:

```python
@dataclass(frozen=True, slots=True)
class SubingDailyTrendIndicatorState:
    ema21: EmaState
    ema21_values: tuple[Decimal, ...]
    macd: MacdState
    previous_dif: Decimal | None
    previous_dea: Decimal | None
    atr14: AtrState
    range_state: RangeDetectorLuxState
    last_bar_end: datetime | None
```

Public functions:

```python
def initial_subing_daily_trend_indicator_state(
    *,
    source_identity: str,
) -> SubingDailyTrendIndicatorState:
    ...

def reset_subing_daily_trend_segment(
    state: SubingDailyTrendIndicatorState,
) -> SubingDailyTrendIndicatorState:
    ...

def step_subing_daily_trend_indicators(
    state: SubingDailyTrendIndicatorState,
    bar: CanonicalBar,
) -> tuple[SubingDailyTrendIndicatorState, SubingDailyTrendFacts]:
    ...
```

The committed implementation must contain complete function bodies; the signatures above define interfaces only.

**Fact rules:**

```text
Range point not ready/invalid => regime DATA_UNAVAILABLE
Range ready + active snapshot state intact => CHOP
Range ready + no active snapshot => TREND_ELIGIBLE
Range ready + active snapshot broken_up/broken_down => TREND_ELIGIBLE

price_side = ABOVE / BELOW / EQUAL
slope_5_bps = EMA21 last 5 ready values
MACD cross uses previous ready DIF/DEA versus current ready DIF/DEA
near_zero_ratio = max(abs(current DIF), abs(current DEA)) / ATR14
ATR14 unavailable or <= 0 => facts unavailable
```

- [ ] **Step 1: Write failing parity and boundary tests**

Must cover:
- existing EMA slope parity after refactor;
- exactly zero slope;
- close exactly EMA21;
- golden/dead cross equality boundary;
- near-zero ratio exactly `0.25` accepted and `0.2500001` rejected;
- Range ready with no active snapshot => `TREND_ELIGIBLE`;
- intact Range => `CHOP`;
- segment reset keeps EMA/MACD/ATR14/Range ATR warm-up but clears Range close-window/active box.

- [ ] **Step 2: Run tests and confirm expected missing-interface failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
```

- [ ] **Step 3: Implement the minimal indicator stream**

Use Quant Core `initial_ema_state/step_ema`, `initial_macd_state/step_macd`, `initial_atr_state/step_atr`, `initial_range_detector_lux_state/step_range_detector_lux/reset_range_detector_lux_regime`. Do not reimplement EMA, MACD, ATR or Range formulas.

- [ ] **Step 4: Run focused and kernel regression tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_daily_trend/indicators.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py
git commit -m "feat(subing): add daily trend indicator stream"
```

---

## Task 4: Implement the single completed-D1 strategy state machine

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/machine.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_machine.py`

**Core state:**

```python
@dataclass(frozen=True, slots=True)
class SubingDailyTrendMachineState:
    symbol: str
    policy: SubingDailyTrendPolicy
    indicators: SubingDailyTrendIndicatorState
    current_segment: ResolvedContractSegment | None
    segment_bar_count: int
    position: SubingDailyTrendPositionState
    pending_action: SubingDailyTrendPendingAction | None
    current_episode: SubingDailyTrendEpisode | None
    closed_episodes: tuple[SubingDailyTrendEpisode, ...]
    actions: tuple[SubingDailyTrendAction, ...]
    cancellations: tuple[SubingDailyTrendCancellation, ...]
    previous_facts: SubingDailyTrendFacts | None
    last_bar_end: datetime | None
```

Public API:

```python
def initial_subing_daily_trend_machine(
    *,
    symbol: str,
    policy: SubingDailyTrendPolicy,
) -> SubingDailyTrendMachineState:
    ...

def step_subing_daily_trend_machine(
    state: SubingDailyTrendMachineState,
    *,
    bar: CanonicalBar,
    segment: ResolvedContractSegment,
) -> SubingDailyTrendMachineState:
    ...
```

**Per-bar order is fixed:**

```text
1. Validate bar timestamp and exactly-one segment ownership.
2. Detect physical segment transition; preserve stitched EMA/MACD/ATR states but reset Range regime and strategy segment-local state.
3. Apply previous pending action at current same-segment D1 open before reading current close facts.
4. Advance current completed-D1 indicators.
5. If current Bar is authoritative segment terminal: close any open position at current close with CONTRACT_SEGMENT_END and prohibit new decision.
6. Else if position LONG/SHORT: evaluate only EMA21 opposite-cross exit and create pending close for next same-segment D1 open.
7. Else if FLAT: require segment_bar_count > 1, TREND_ELIGIBLE, correct EMA side/slope, near-zero golden/dead cross; create one pending open.
8. Store current facts as previous facts.
```

**Long entry predicate:**

```python
long_entry = (
    facts.regime is SubingDailyTrendRegime.TREND_ELIGIBLE
    and facts.price_side is PriceSide.ABOVE
    and facts.ema21_slope_5_bps_per_bar > 0
    and facts.macd_cross is SubingDailyTrendMacdCross.GOLDEN
    and facts.macd_zero_distance_atr14 <= Decimal("0.25")
)
```

Short is exactly symmetric.

**Exit predicates:**

```text
LONG exit: previous_close >= previous_ema21 and current_close < current_ema21
SHORT exit: previous_close <= previous_ema21 and current_close > current_ema21
```

- [ ] **Step 1: Write failing machine tests**

Tests must independently cover:
- first segment D1 never enters;
- CHOP blocks an otherwise valid golden/dead cross;
- Range ready/no box permits entry;
- long and short signals;
- no MACD cross => no entry;
- wrong EMA side or slope => no entry;
- signal at `t` never uses `t` close as reference fill;
- pending open becomes effective only at next same-segment D1 open;
- gap never cancels entry and is recorded;
- ordinary exit only on EMA opposite cross;
- reverse MACD does not exit;
- Range becoming intact while holding does not exit;
- no same-Bar reversal;
- terminal close precedence and `CONTRACT_SEGMENT_END`;
- no cross-segment position/pending state;
- duplicate/stale input fails closed.

- [ ] **Step 2: Run and confirm failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
```

- [ ] **Step 3: Implement the pure machine**

No MarketDataService calls, filesystem access, DB access, HTTP or Alert code belongs in `machine.py`.

- [ ] **Step 4: Run Task 2–4 tests together**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py
git commit -m "feat(subing): add daily trend D1 state machine"
```

---

## Task 5: Build deterministic Historical Projection over rank1 physical segments

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/replay.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_replay.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SubingDailyTrendHistoricalResult:
    strategy_id: str
    symbol: str
    through: date
    source_bar_count: int
    source_first_trading_day: date
    source_last_trading_day: date
    segments: tuple[ResolvedContractSegment, ...]
    actions: tuple[SubingDailyTrendAction, ...]
    cancellations: tuple[SubingDailyTrendCancellation, ...]
    open_episode: SubingDailyTrendEpisode | None
    closed_episodes: tuple[SubingDailyTrendEpisode, ...]
    final_state: SubingDailyTrendMachineState


def replay_subing_daily_trend(
    *,
    symbol: str,
    bars: Sequence[CanonicalBar],
    segments: Sequence[ResolvedContractSegment],
    policy: SubingDailyTrendPolicy,
) -> SubingDailyTrendHistoricalResult:
    ...
```

Replay must map every D1 Bar to exactly one segment. Missing coverage, overlapping segments, non-monotonic bars or wrong symbol/contract identity fails closed before replay.

- [ ] **Step 1: Write replay invariance tests**

Required tests:
- batch replay equals manually stepping every Bar;
- replay of every prefix equals the corresponding prefix of full replay actions/closed episodes;
- appending future tail does not alter previously effective Action identity/reference price;
- prepend history only fills prior warm-up; once the compared prefix has full EMA/MACD/ATR/Range warm-up, stable Action identity does not drift;
- `visual_start_at` cannot cause an Action before Range causal readiness;
- segment close-window reset prevents old contract Range box from suppressing the new contract;
- no Action/Episode crosses segment boundary.

- [ ] **Step 2: Run and confirm missing replay failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 3: Implement replay as a thin loop around the machine**

Do not add a separate batch formula path.

- [ ] **Step 4: Run replay + machine + Range causality tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/replay.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
git commit -m "feat(subing): add daily trend historical replay"
```

---

## Task 6: Add read-only full-history research loading and effect metrics

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_trend/report.py`
- Create: `services/quant-api/app/research/subing/subing_daily_trend_research_service.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_report.py`
- Test: `services/quant-api/tests/research/test_subing_daily_trend_research_service.py`

**Research service request:**

```python
class SubingDailyTrendScope(StrEnum):
    REPRESENTATIVE = "representative"
    ACTIVE = "active"

@dataclass(frozen=True, slots=True)
class SubingDailyTrendResearchRequest:
    scope: SubingDailyTrendScope
    through: date
    include_episodes: bool = False
```

Representative scope is fixed to `("jm", "ag", "rb", "eg")`. Active scope uses `active_products.txt` and never `operational_products.txt` as a research-capability shortcut.

**Earliest-history discovery:**

For each symbol:
1. call `query_actual_dominant_recent_bars(... D1, through, limit=2000)`;
2. while `has_more_before`, call public `query_page(SeriesPageQuery(ACTUAL_DOMINANT, symbol, D1, before=next_before, limit=2000))`;
3. require each page to move `next_before` strictly backward and expose at least one earlier Bar;
4. record the minimum discovered trading day;
5. call existing `ActualDominantResearchSegmentLoader.load(symbol, (D1,), earliest_day, through)` once to obtain the authoritative full bars and restored true segments;
6. pass those bars/segments to `replay_subing_daily_trend`.

This deliberately trades one extra read pass for simpler identity correctness; do not reach into Catalog/Parquet directly.

**80/20 split rule:**

For closed Episodes, collect sorted unique `entry_trading_day` values. When at least two unique entry days exist:

```python
cut = max(1, min(len(days) - 1, int(len(days) * 0.8)))
holdout_start = days[cut]
development = episode.entry_trading_day < holdout_start
holdout = episode.entry_trading_day >= holdout_start
```

All Episodes from the same entry day stay in the same split. If fewer than two unique entry days exist, report holdout as unavailable instead of fabricating a split.

**Metrics:**

Per product and aggregate:
- closed/open Episode counts;
- long/short counts;
- positive ratio;
- mean, median, q25, q75, min and max reference change;
- mean/median holding D1 bars;
- `EMA21_OPPOSITE_CROSS` and `CONTRACT_SEGMENT_END` counts;
- entry gap absolute and ATR14-normalized distributions;
- by year and direction;
- development and holdout summaries;
- `INSUFFICIENT_SAMPLE` when closed Episodes < 30.

Quantiles must use Decimal linear interpolation over sorted values, not float conversion.

- [ ] **Step 1: Write report math tests**

Use hand-calculated Decimal Episode values to lock mean/median/q25/q75, same-day split grouping and sample-status behavior.

- [ ] **Step 2: Write fake-reader service tests**

Prove:
- paging to earliest history makes progress;
- no-progress cursor fails closed;
- loader is D1/actual_dominant only;
- representative scope is exactly JM/AG/RB/EG;
- active scope reads active universe;
- one product failure is reported as product failure and does not mutate other product results;
- service performs no write calls.

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py
```

- [ ] **Step 4: Implement report and research service**

Response must carry `strategy_id`, policy digest, through date, per-product source first/last day, source-bar count and segment count so results remain tied to exact formula/data identity.

- [ ] **Step 5: Re-run focused tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_trend/report.py \
  services/quant-api/app/research/subing/subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py
git commit -m "feat(subing): add daily trend research reporting"
```

---

## Task 7: Wire one read-only `guiyi research subing-daily-trend` command

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/research/test_research_cli_parser_requests.py`
- Create: `services/quant-api/tests/research/test_subing_daily_trend_cli.py`
- Modify: `TESTING.md`

**CLI contract:**

```text
guiyi research subing-daily-trend \
  --scope representative|active \
  --through YYYY-MM-DD \
  [--include-episodes]
```

Rules:
- `--include-episodes` is accepted only with `--scope representative`;
- command is classified read-only;
- stdout is one JSON payload; no report cache or filesystem publish occurs;
- response status is `passed` only when requested products all complete; product failures yield `degraded` with stable public codes;
- never expose storage path, SQL, stack trace, token or environment details.

- [ ] **Step 1: Write parser/request/CLI output tests**

Expected parser registry after the change:

```python
RESEARCH_COMMAND_NAMES = (
    "subing-calibration",
    "subing-lifecycle",
    "subing-strategy-performance",
    "subing-daily-trend",
)
```

Test representative and active request construction, invalid `include_episodes + active`, safe exception mapping, read-only flag and injected fake service output.

- [ ] **Step 2: Run and confirm failures**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

- [ ] **Step 3: Implement CLI wiring and composition**

Reuse existing `MarketDataService` composition; do not construct a second data reader.

- [ ] **Step 4: Run all Stage A focused tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_daily_trend_policy_contracts.py \
  services/quant-api/tests/research/test_subing_daily_trend_indicators.py \
  services/quant-api/tests/research/test_subing_daily_trend_machine.py \
  services/quant-api/tests/research/test_subing_daily_trend_replay.py \
  services/quant-api/tests/research/test_subing_daily_trend_report.py \
  services/quant-api/tests/research/test_subing_daily_trend_research_service.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_requests.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_daily_trend_cli.py \
  TESTING.md
git commit -m "feat(cli): expose daily trend historical research"
```

---

## Task 8: Full verification, independent Review, then Historical evidence Gate

**Files:**
- No source expansion unless verification exposes a defect within Stage A scope.
- After explicit read-only environment approval only: create `docs/tasks/2026-08-31-subing-trend-daily-historical-evidence.md` with the exact run evidence.

### Part A — code verification before real-data execution

- [ ] **Step 1: Run the full non-isolated backend suite**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  -m "not isolated_postgresql" \
  services/quant-api/tests
```

- [ ] **Step 2: Ruff and Mypy**

```bash
uv run --project services/quant-api --no-sync ruff check \
  packages/quant-core/guiyi_quant \
  services/quant-api/app \
  services/quant-api/tests

uv run --project services/quant-api --no-sync mypy \
  packages/quant-core/guiyi_quant \
  services/quant-api/app
```

- [ ] **Step 3: Contract and repository checks**

Run the repository-prescribed commands from `TESTING.md` for:
- OpenSpec strict validation if the implementation adds/changes an active spec;
- canonical consistency;
- secret scan;
- `git diff --check`.

Do not invent alternate commands if `TESTING.md` has an authoritative command.

- [ ] **Step 4: Create/update one Draft implementation PR to `develop`**

PR title:

```text
feat: add 苏冰趋势策略-日 Historical Projection
```

PR body must record exact commands/results, strategy identity, policy digest, fixed formula, and explicitly state Current/API/Web/Alert are not implemented.

- [ ] **Step 5: Dispatch independent Sol/high Review**

Reviewer must inspect, not merely rerun tests:
- Range reset preserves ATR500 but clears segment-local regime;
- Range ready/no active box means TREND_ELIGIBLE;
- intact Range blocks entries;
- EMA21 side + exact 5-bar slope only;
- MACD near-zero cross is the only entry trigger;
- next same-contract D1 open causality;
- EMA-only ordinary exit;
- segment terminal and no cross-segment state;
- deterministic Action/Episode identity;
- batch/incremental, prefix, future-tail, prepend invariance;
- 80/20 split isolation;
- no Current/API/Web/Alert/DB write scope expansion.

Allowed Review conclusions:

```text
允许进入 Historical evidence run
要求修正后再 Review
阻塞
```

### Part B — real Historical effect run, separate read-only Gate

Do not execute this part merely because code Review passed.

- [ ] **Step 6: Ask owner to identify/approve the read-only Historical environment and exact `through` date**

The approval must identify that the run may read local Catalog/Canonical facts but will not write DB/Redis/Canonical/RQData or notify.

- [ ] **Step 7: Run representative scope first**

After approval:

```bash
uv run --project services/quant-api --no-sync guiyi research subing-daily-trend \
  --scope representative \
  --through <APPROVED_TRADING_DAY> \
  --include-episodes
```

Replace `<APPROVED_TRADING_DAY>` with the exact owner-approved trading day before execution; never commit this placeholder into source code or generated evidence.

Review JM/AG/RB/EG episode-by-episode before active60.

- [ ] **Step 8: Run active scope only if representative evidence is structurally correct**

```bash
uv run --project services/quant-api --no-sync guiyi research subing-daily-trend \
  --scope active \
  --through <APPROVED_TRADING_DAY>
```

- [ ] **Step 9: Write versioned Historical evidence**

`docs/tasks/2026-08-31-subing-trend-daily-historical-evidence.md` must contain:
- code commit SHA;
- policy SHA-256;
- exact through date;
- representative and active scope commands;
- per-product source window and segment counts;
- JM/AG/RB/EG episode counts and sample status;
- active60 aggregate and product failures;
- development/holdout summaries;
- explicit note that results are gross reference changes, not account PnL;
- no automatic promotion conclusion.

- [ ] **Step 10: Stop at Historical Gate**

The highest allowed completion state is:

```text
CODE_COMPLETE
TEST_COMPLETE
HISTORICAL_REPORT_READY
```

Do not implement Current/API/Web/Alert until the owner reads the evidence and explicitly says to continue.

---

## Implementation PR / Worktree Topology

After this plan is approved and merged to `develop`:

```text
latest origin/develop
→ feature/subing-daily-trend-v1-historical task worktree
→ Task 1..7 with small commits
→ Draft PR to develop
→ independent Formula/Spec Review
→ separate read-only Historical environment Gate
→ representative evidence
→ active60 evidence
→ owner Historical Gate
```

Do not reuse the docs branch for source implementation.

The implementation branch may be merged to `develop` only after independent Review and explicit owner integration approval. Merge to `develop` does not authorize `main`, tag, release, Runtime, production data mutation or notification.

## Plan Self-Review Checklist

Before implementation starts, verify all of the following remain true against the merged Spec:

- Every Stage A Spec requirement maps to Task 1–8.
- No task implements Current/API/Web/Alert.
- No strategy threshold is runtime-adjustable.
- `subing_strategy_v1` is untouched except shared tests may be run.
- Range segment reset keeps ATR500 stitched warm-up while clearing only regime-local fields.
- Machine and Historical replay share one step function.
- Historical service reads only through MarketDataService/public research loader seams.
- Effect reporting uses Decimal and keeps same-day entries in one development/holdout partition.
- Real Historical environment execution is a separate read-only Gate after code Review.
- No plan step authorizes main/tag/Runtime/production write/notification.
