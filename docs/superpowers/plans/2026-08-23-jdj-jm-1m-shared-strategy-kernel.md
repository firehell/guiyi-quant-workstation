# 日进斗金 JM 1m Shared Strategy Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 N Structure/JDJ Candidate 公式下沉为唯一 Shared Strategy Kernel，在不改变冻结 Candidate 语义的前提下实现 `jdj_jm_1m_v1` 完整交易生命周期、actual_dominant Historical Strategy Replay、Market 主图展示和 RQAlpha research-only adapter。

**Architecture:** `app.strategy_kernel` 是唯一公式与执行策略语义层；`app.research`、Historical Replay 和 RQAlpha 都只是消费者。Historical Replay 使用 Canonical `actual_dominant` physical segments；RQAlpha 使用 Bundle price/fill，只额外只读消费由 `MainContractMap` 生成的 dominant identity schedule。

**Tech Stack:** Python 3.13/FastAPI/Pydantic/Decimal、现有 `MarketDataService` / `ActualDominantResearchSegmentLoader`、Vue 3/TypeScript/Lightweight Charts、RQAlpha Plus local-only workbench。

**Spec:** `docs/superpowers/specs/2026-08-23-jdj-jm-1m-shared-strategy-kernel-design.md`

## Global Constraints

- 本任务为 Lane 3；策略公式、回测成交时序和主力 identity 均属于可信口径。
- 第一版唯一 profile：`jdj_jm_1m_v1`；`symbol=jm`、`actual_dominant`、execution=`1m`、trend context=`5m`。
- 现有三个 JDJ Candidate 的 event identity、direction、`observed_at`、trigger level、strict-before、same-contract/same-segment 语义必须 100% parity。
- 金额、价格、仓位、风险、PnL、手续费统一使用 `Decimal`；数量为整数手。
- 不创建 StrategyBase/plugin/optimizer/Portfolio 平台；不适配其他策略、品种或周期。
- Historical Replay 只读 Canonical；不得写 DB/Canonical/Redis。
- RQAlpha adapter 价格/撮合来自 Bundle；Canonical 只允许导出 dominant identity schedule，不得把 Canonical Bar 注入 runner。
- 不接 Alert、PushPlus、Execution Review、Runtime 或订单账户。
- 不执行真实 RQAlpha smoke；真实 Bundle 回测需要后续单独执行意图。
- 不发布 main/tag，不做 Runtime promotion。

---

## File Structure

### Shared formula / strategy kernel

Create:

```text
services/quant-api/app/strategy_kernel/__init__.py
services/quant-api/app/strategy_kernel/n_structure/__init__.py
services/quant-api/app/strategy_kernel/n_structure/n_structure_policy.py
services/quant-api/app/strategy_kernel/n_structure/n_structure_pattern.py
services/quant-api/app/strategy_kernel/n_structure/n_structure_swing.py
services/quant-api/app/strategy_kernel/n_structure/n_structure_state.py
services/quant-api/app/strategy_kernel/n_structure/n_structure_segment.py
services/quant-api/app/strategy_kernel/jdj/__init__.py
services/quant-api/app/strategy_kernel/jdj/jdj_policy.py
services/quant-api/app/strategy_kernel/jdj/jdj_context.py
services/quant-api/app/strategy_kernel/jdj/jdj_events.py
services/quant-api/app/strategy_kernel/jdj/jdj_trend_follow.py
services/quant-api/app/strategy_kernel/jdj/jdj_trend_reentry.py
services/quant-api/app/strategy_kernel/jdj/jdj_key_level_breakout.py
services/quant-api/app/strategy_kernel/jdj/strategy_policy.py
services/quant-api/app/strategy_kernel/jdj/strategy_profile.py
services/quant-api/app/strategy_kernel/jdj/target.py
services/quant-api/app/strategy_kernel/jdj/risk.py
services/quant-api/app/strategy_kernel/jdj/execution.py
services/quant-api/app/strategy_kernel/jdj/engine.py
```

Create tracked contracts:

```text
data/strategy_policies/jdj_intraday_futures_v1.json
data/strategy_profiles/jdj_jm_1m_v1.json
```

### Historical replay consumer

Create:

```text
services/quant-api/app/research/jdj_strategy/__init__.py
services/quant-api/app/research/jdj_strategy/replay.py
services/quant-api/app/research/jdj_strategy/service.py
services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py
services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py
services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

Modify:

```text
services/quant-api/app/research/composition.py
services/quant-api/app/research/historical_overlay_api.py
services/quant-api/app/schemas/research_overlays.py
services/quant-api/tests/test_market_research_overlays_api.py
```

### Web

Create:

```text
apps/quant-web/src/composables/useHistoricalStrategyMarkers.ts
apps/quant-web/src/utils/historicalStrategyMarkers.ts
apps/quant-web/tests/historicalStrategyMarkers.test.ts
```

Modify:

```text
apps/quant-web/src/api/market.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/mainIndicators.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/e2e/market-research.spec.mjs
```

### RQAlpha workbench integration

Only after the previously designed RQAlpha workbench implementation exists, create/modify:

```text
services/quant-api/app/backtest/dominant_schedule.py
services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py
services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py
services/quant-api/app/backtest/strategies/registry.json
services/quant-api/tests/backtest/test_jdj_dominant_schedule.py
services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

Do not recreate the workbench in this plan if `services/quant-api/app/backtest/` is absent; complete Tasks 1～6, then execute the already-approved RQAlpha workbench plan in its own task before resuming Task 7.

---

### Task 1: Extract the N Structure Pure Kernel Without Semantic Change

**Files:**
- Create/move: `services/quant-api/app/strategy_kernel/n_structure/*.py`
- Modify imports in: `services/quant-api/app/research/n_structure/*.py`, `services/quant-api/app/research/jdj/jdj_context.py`, JDJ/N tests that import the moved pure modules
- Test: `services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py`

**Interfaces:**
- Consumes: existing `CanonicalBar` and exact `NStructurePolicy`
- Produces: unchanged `NStructureKind`, `NStructureSnapshot`, `NSwingPivot`, `NStructureSegmentTrace`, `evaluate_n_structure_segment(...)`

- [ ] **Step 1: Write a failing import/parity test against the new package**

```python
from app.strategy_kernel.n_structure.n_structure_segment import (
    evaluate_n_structure_segment,
)
from app.strategy_kernel.n_structure.n_structure_state import NStructureKind


def test_shared_n_kernel_exposes_existing_contract() -> None:
    assert callable(evaluate_n_structure_segment)
    assert NStructureKind.BULL.value == "bull"
```

Add fixture-based assertions using the same bars already exercised by current N tests; assert exact snapshots/pivots and their ids/timestamps, not only counts.

- [ ] **Step 2: Run the new test and verify it fails because the package does not exist**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py
```

Expected: FAIL on `app.strategy_kernel.n_structure` import.

- [ ] **Step 3: Move only the pure N modules into `app.strategy_kernel.n_structure`**

Move these exact implementations without changing formulas:

```text
n_structure_policy.py
n_structure_pattern.py
n_structure_swing.py
n_structure_state.py
n_structure_segment.py
```

Do not move `n_structure_research_service.py`, candidate validation, HTTP, CLI or report code.

- [ ] **Step 4: Update imports so dependency direction is `research → strategy_kernel`**

Example:

```python
from app.strategy_kernel.n_structure.n_structure_policy import NStructurePolicy
from app.strategy_kernel.n_structure.n_structure_segment import (
    evaluate_n_structure_segment,
)
```

No module under `app.strategy_kernel` may import `app.research`.

- [ ] **Step 5: Run parity + existing N/JDJ context tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_jdj_context.py
```

Expected: PASS; no snapshot/pivot identity drift.

- [ ] **Step 6: Remove any temporary N compatibility shim after `rg 'app\.research\.n_structure\.n_structure_(policy|pattern|swing|state|segment)'` returns no active production imports**

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/tests
git commit -m "refactor(strategy): extract shared N structure kernel"
```

---

### Task 2: Extract JDJ Candidate Logic and Prove Exact Parity

**Files:**
- Create/move: `services/quant-api/app/strategy_kernel/jdj/jdj_*.py` for policy/context/events/three reducers
- Modify: `services/quant-api/app/research/jdj/*.py`, robustness/convergence imports that consume JDJ event types
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py`

**Interfaces:**
- Consumes: Shared N kernel + `CanonicalBar`
- Produces: unchanged `JdjBarContext`, existing Candidate event classes, `reduce_jdj_trend_follow`, `reduce_jdj_trend_reentry_6`, `reduce_jdj_key_level_breakout`

- [ ] **Step 1: Freeze literal JDJ golden outputs in a new parity test before moving code**

Use deterministic existing fixtures and assert at least:

```python
assert [event.event_id for event in trace.events] == EXPECTED_EVENT_IDS
assert [event.observed_at for event in trace.events] == EXPECTED_OBSERVED_AT
assert [event.trigger_level for event in trace.events] == EXPECTED_TRIGGER_LEVELS
assert trace.ambiguous_count == EXPECTED_AMBIGUOUS
assert trace.invalidated_count == EXPECTED_INVALIDATED
```

Create separate cases for Trend Follow, Trend Reentry 6 and Key Level Breakout, plus failed reaction/retest and same-bar ambiguity.

- [ ] **Step 2: Run the golden test on the existing code and record PASS**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py
```

- [ ] **Step 3: Move the six pure JDJ modules plus exact policy into `app.strategy_kernel.jdj` without formula edits**

```text
jdj_policy.py
jdj_context.py
jdj_events.py
jdj_trend_follow.py
jdj_trend_reentry.py
jdj_key_level_breakout.py
```

- [ ] **Step 4: Update Research services to import the shared kernel**

Example in `jdj_research_service.py`:

```python
from app.strategy_kernel.jdj.jdj_context import build_jdj_context_series
from app.strategy_kernel.jdj.jdj_trend_follow import reduce_jdj_trend_follow
from app.strategy_kernel.jdj.jdj_trend_reentry import reduce_jdj_trend_reentry_6
from app.strategy_kernel.jdj.jdj_key_level_breakout import (
    reduce_jdj_key_level_breakout,
)
```

Update robustness/convergence/test imports to the new event type path; do not duplicate dataclasses.

- [ ] **Step 5: Run exact parity and the existing JDJ research suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS with unchanged event ids/counts/times/levels.

- [ ] **Step 6: Remove temporary old-path shims after no production import references remain**

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/tests
git commit -m "refactor(strategy): make JDJ candidate kernel shared"
```

---

### Task 3: Add the Immutable JDJ Strategy Policy, JM 1m Profile, Target and Risk Authorization

**Files:**
- Create: `data/strategy_policies/jdj_intraday_futures_v1.json`
- Create: `data/strategy_profiles/jdj_jm_1m_v1.json`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_policy.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_profile.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/target.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/risk.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class JdjStrategyProfile:
    profile_id: str
    symbol: str
    series_kind: str
    execution_frequency: BarFrequency
    trend_context_frequency: BarFrequency
    stop_buffer_ticks: int
    base_risk_fraction: Decimal
    max_episode_risk_fraction: Decimal
    minimum_reward_risk: Decimal
    first_profit_take_fraction: Decimal
    add_fraction_of_current_qty: Decimal
    max_add_count: int
    daily_pause_drawdown_fraction: Decimal
    daily_pause_minutes: int
    daily_stop_drawdown_fraction: Decimal

@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    price_tick: Decimal
    contract_multiplier: Decimal
    margin_per_contract: Decimal
    estimated_round_trip_cost: Decimal

@dataclass(frozen=True, slots=True)
class EntryAuthorization:
    allowed: bool
    reason: str | None
    stop_price: Decimal | None
    target_price: Decimal | None
    reward_risk: Decimal | None
    quantity: int
```

- [ ] **Step 1: Write failing exact-policy/profile tests**

Assert the JSON contract equals the Spec values exactly, including `jm/1m/5m`, `0.005`, `0.01`, `2.0`, `0.40`, `0.25`, add count `2`, daily pause and daily stop.

- [ ] **Step 2: Write failing target/risk tests**

Cover:

```python
assert authorize_entry(...reward_risk=Decimal("1.99")).reason == "REWARD_RISK_TOO_LOW"
assert authorize_entry(...forward_levels=()).reason == "TARGET_UNAVAILABLE"
assert authorize_entry(...instrument=None).reason == "INSTRUMENT_SPEC_UNAVAILABLE"
```

Also assert same-direction setup attribution priority is exactly key-level > reentry > trend-follow and opposite-direction conflict is rejected.

- [ ] **Step 3: Run tests and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
```

- [ ] **Step 4: Implement exact JSON loaders using the repository `exact_json_contract` pattern**

The loader must reject unknown/missing/drifted fields; do not silently default formula values.

- [ ] **Step 5: Implement setup-specific stop resolution**

```python
def resolve_stop_price(
    event: JdjTriggerEvent,
    *,
    contexts: Sequence[JdjBarContext],
    instrument: InstrumentSpec,
    profile: JdjStrategyProfile,
) -> Decimal:
    ...
```

Use reaction-bar extreme for Trend Follow, excursion extreme for Reentry 6 and frozen key level for Key Level Breakout, then apply one tick buffer in the adverse direction.

- [ ] **Step 6: Implement strictly-known target resolution**

```python
def resolve_target_price(
    *,
    direction: JdjDirection,
    entry_reference: Decimal,
    known_pivots: Sequence[NSwingPivot],
    known_session_high: Decimal,
    known_session_low: Decimal,
) -> Decimal | None:
    ...
```

Only use levels known by decision time; choose nearest favorable level. Return `None` when no forward target exists.

- [ ] **Step 7: Implement risk sizing**

```python
def calculate_base_quantity(
    *,
    equity: Decimal,
    available_cash: Decimal,
    entry_reference: Decimal,
    stop_price: Decimal,
    instrument: InstrumentSpec,
    profile: JdjStrategyProfile,
) -> int:
    ...
```

Use `floor(min(qty_by_risk, qty_by_margin))`; no float arithmetic.

- [ ] **Step 8: Run contract/risk tests**

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add data/strategy_policies data/strategy_profiles services/quant-api/app/strategy_kernel/jdj services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): define JDJ JM 1m execution contract"
```

---

### Task 4: Implement the Pure Position / Daily-Risk Execution Reducer and Reference Fill Model

**Files:**
- Create: `services/quant-api/app/strategy_kernel/jdj/execution.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/engine.py`
- Create: `services/quant-api/app/research/jdj_strategy/replay.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py`

**Interfaces:**
- Produces:

```python
class JdjActionKind(StrEnum):
    ENTRY = "entry"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    DAILY_PAUSE = "daily_pause"
    DAILY_STOP = "daily_stop"
    REJECTED_CANDIDATE = "rejected_candidate"

@dataclass(frozen=True, slots=True)
class JdjPositionState:
    direction: JdjDirection
    quantity: int
    weighted_average_cost: Decimal
    protective_stop: Decimal
    target_1: Decimal
    base_quantity: int
    add_count: int
    partial_profit_taken: bool
    realized_pnl: Decimal

@dataclass(frozen=True, slots=True)
class JdjStrategyState:
    trading_day: date
    start_equity: Decimal
    position: JdjPositionState | None
    pause_until: datetime | None
    stopped_for_day: bool
    consumed_source_event_ids: frozenset[str]
```

Main reducer:

```python
def reduce_jdj_strategy(
    state: JdjStrategyState,
    frame: JdjStrategyFrame,
    *,
    policy: JdjStrategyPolicy,
    profile: JdjStrategyProfile,
) -> JdjStrategyStep:
    ...
```

- [ ] **Step 1: Write failing tests for base entry, target reduce and add eligibility**

Assert:

- target1 fill reduces `floor(current_qty * 0.40)`;
- a 1～2 lot position does not fabricate a partial reduce when floor is zero;
- add is rejected before any profitable partial exit;
- first and second qualifying EMA20 reaction can add `floor(current_qty * 0.25)`;
- third add is rejected;
- any losing/negative-realized episode cannot add;
- successful add moves protective stop to new weighted average cost.

- [ ] **Step 2: Write failing daily-risk tests**

Create frames where mark-to-market drawdown crosses 0.5% and 1%:

```python
assert step.actions[0].kind is JdjActionKind.DAILY_PAUSE
assert step.state.pause_until == now + trading_minutes(15)
assert later_step.state.stopped_for_day is True
```

At 1%, assert remaining position receives EXIT and no later entry/add can be emitted that trading day.

- [ ] **Step 3: Write failing replay fill tests**

Cover next-bar-open fill, gap-through stop, normal stop touch, target touch, end-of-segment cancellation and stop+target same-bar ambiguity. For ambiguity assert adverse order: stop first.

- [ ] **Step 4: Run tests and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
```

- [ ] **Step 5: Implement the reducer with immutable state transitions**

Do not mutate RQAlpha objects or database state. Every action must carry `decision_at`, `effective_at`, source event ids, contract and reason.

- [ ] **Step 6: Implement daily risk on mark-to-market equity**

Existing position management continues during pause; pause blocks only new Entry/Add. Daily stop emits exit and permanently blocks Entry/Add until trading-day reset.

- [ ] **Step 7: Implement reference replay fills**

Use the Spec’s exact next-bar-open/resting stop/resting target rules; never choose favorable intrabar ordering when both stop and target are touched.

- [ ] **Step 8: Run execution tests and the JDJ parity suite together**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py \
  services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py
```

- [ ] **Step 9: Commit**

```bash
git add services/quant-api/app/strategy_kernel/jdj services/quant-api/app/research/jdj_strategy services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): add JDJ execution and replay reducer"
```

---

### Task 5: Add JM actual_dominant Historical Strategy Replay API

**Files:**
- Create: `services/quant-api/app/research/jdj_strategy/service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Modify test: `services/quant-api/tests/test_market_research_overlays_api.py`

**Interfaces:**
- Produces two read-only endpoints:

```text
GET /api/v1/market/research/jdj-strategy/profiles?symbol=jm
GET /api/v1/market/research/jdj-strategy/history?series_kind=actual_dominant&symbol=jm&frequency=1m&since=YYYY-MM-DD&through=YYYY-MM-DD
```

- [ ] **Step 1: Write failing service tests for actual_dominant segmentation**

Use a fake `ActualDominantResearchSegmentLoader` with at least two physical contracts and assert:

```python
assert all(event.contract == expected_contract_for_day[event.trading_day] for event in result.events)
assert no_position_crosses_segment_boundary(result.events)
assert result.profile_id == "jdj_jm_1m_v1"
```

Also split the same history into prefixes/pages and assert previously emitted event ids and effective times are unchanged.

- [ ] **Step 2: Write failing API tests**

Assert `jm + actual_dominant + 1m` succeeds; `5m`, `rb`, `continuous`, missing coverage and invalid segment identity fail explicitly.

Expected unsupported code:

```json
{"detail":{"code":"JDJ_STRATEGY_PROFILE_UNAVAILABLE"}}
```

- [ ] **Step 3: Implement `JdjStrategyReplayService`**

Constructor consumes the existing segment loader plus exact JDJ/N policy and accepted strategy profile. It must process each physical segment independently and concatenate only stable StrategyAction projections.

- [ ] **Step 4: Add Pydantic DTOs**

Add request/profile/action/response models to `research_overlays.py`. Preserve `Decimal` fields; do not turn prices/risks into float in the backend.

- [ ] **Step 5: Wire composition and API**

Keep API read-only. Do not create tables or cache derived events in DB/Redis.

- [ ] **Step 6: Run service/API tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/jdj_strategy services/quant-api/app/research/composition.py services/quant-api/app/research/historical_overlay_api.py services/quant-api/app/schemas/research_overlays.py services/quant-api/tests
git commit -m "feat(research): expose JDJ JM strategy replay"
```

---

### Task 6: Add the Separate `日进斗金策略` Market Overlay and Profile-Aware Frequency Switching

**Files:**
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Create: `apps/quant-web/src/composables/useHistoricalStrategyMarkers.ts`
- Create: `apps/quant-web/src/utils/historicalStrategyMarkers.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/tests/historicalStrategyMarkers.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Consumes: profile/history endpoints from Task 5
- Produces: distinct overlay id `jdj_strategy`, independent from existing Candidate `jdj` overlay

- [ ] **Step 1: Write failing TypeScript unit tests for action marker mapping**

Map only:

```text
ENTRY  → ▲/▼
ADD    → ＋
REDUCE → －
EXIT   → ×
```

Assert hover metadata carries primary setup, contract, decision/effective timestamps, qty, stop, target, R:R and reason.

- [ ] **Step 2: Write failing composable tests for identity switching**

Assert:

- `jm/actual_dominant/1m` loads `jdj_jm_1m_v1`;
- switching to 5m clears old markers and exposes `PROFILE_UNAVAILABLE` state;
- switching back to 1m reloads without duplicate event ids;
- prepend pagination preserves already-rendered event ids.

- [ ] **Step 3: Implement API/types and marker utility**

Browser types mirror backend fields but never calculate strategy prices or risk.

- [ ] **Step 4: Implement `useHistoricalStrategyMarkers` separately from `useHistoricalResearchMarkers`**

Do not add strategy actions to the Candidate marker map; keep independent identity/generation guards.

- [ ] **Step 5: Add `日进斗金策略` to the chart control**

When profile unsupported, show explicit “该品种/周期尚未验证”; do not silently display stale 1m markers on another frequency.

- [ ] **Step 6: Extend Playwright coverage**

Test Candidate JDJ and Strategy JDJ independently, including frequency switch 1m → 5m → 1m.

- [ ] **Step 7: Run Web tests/build**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 8: Commit**

```bash
git add apps/quant-web
git commit -m "feat(web): show JDJ historical strategy replay"
```

---

### Task 7: Integrate the Same Kernel Into the Local RQAlpha Workbench

**Prerequisite Gate:**

Run:

```bash
test -d services/quant-api/app/backtest
```

If this fails, stop this task. Do **not** recreate the workbench here. Implement the approved RQAlpha workbench plan first, integrate it into `develop`, then resume this task from a fresh branch/worktree.

**Files:**
- Create: `services/quant-api/app/backtest/dominant_schedule.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py`
- Modify: `services/quant-api/app/backtest/strategies/registry.json`
- Modify existing result normalization only as needed to include JDJ attribution
- Test: `services/quant-api/tests/backtest/test_jdj_dominant_schedule.py`
- Test: `services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py`

**Interfaces:**
- Produces `dominant_schedule.json` containing only `trading_day -> physical_contract`
- Registers `strategy_id=jdj_intraday_futures_v1`, `profile_id=jdj_jm_1m_v1`

- [ ] **Step 1: Write failing dominant-schedule tests**

Assert schedule generation is read-only, deterministic, `jm`-only and rejects missing/conflicting rank1 identity with `DOMINANT_SCHEDULE_INCOMPLETE`.

- [ ] **Step 2: Implement schedule generation from existing MainContractMap/actual-dominant identity services**

Do not put OHLCV, Canonical paths or credentials into the schedule.

Example output shape:

```json
{
  "symbol": "jm",
  "series_kind": "actual_dominant",
  "contracts_by_trading_day": {
    "2026-08-20": "JM2609"
  }
}
```

- [ ] **Step 3: Write failing adapter tests using fake RQAlpha objects**

Assert adapter:

- imports Shared Kernel;
- refuses a contract different from schedule;
- maps ENTRY/ADD/REDUCE/EXIT to futures open/close actions;
- never enables signal mode;
- never calls Canonical Bar readers;
- preserves `research_only=true` attribution.

- [ ] **Step 4: Implement the thin adapter**

The strategy file owns RQAlpha lifecycle hooks only. All Setup/stop/target/risk/position decisions come from Shared Kernel.

- [ ] **Step 5: Register the fixed strategy/profile**

The Web backtest form may select dates/capital/cost inputs allowed by the workbench, but must not expose formula parameters that the profile freezes (`EMA20`, `minimum_reward_risk`, add count, etc.) as arbitrary overrides.

- [ ] **Step 6: Extend result attribution**

Ensure each episode result includes profile id, contract, setup attribution, entry/exit, adds/reduces, `return_R/MFE_R/MAE_R`, cost and exit reason. Do not create a second PnL calculator when RQAlpha already supplies account/trade values.

- [ ] **Step 7: Run fake-adapter/backtest tests only**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/backtest/test_jdj_dominant_schedule.py \
  services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

Do not run the real Bundle.

- [ ] **Step 8: Commit**

```bash
git add services/quant-api/app/backtest services/quant-api/tests/backtest
git commit -m "feat(backtest): adapt JDJ JM strategy to RQAlpha"
```

---

### Task 8: Canonical Closeout and Full Verification

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/RQALPHA_RESEARCH_BACKTEST.md`
- Modify: `TESTING.md`
- Do not modify `STATUS.md` unless this exact implementation is explicitly being recorded as a develop RC in a separate status action.

- [ ] **Step 1: Update stable boundaries**

Record these exact distinctions:

```text
JDJ Candidate Research = source event facts only
JDJ Historical Strategy Replay = Canonical actual_dominant reference execution
RQAlpha JDJ Backtest = Bundle price/fill + Canonical-derived dominant identity schedule
```

All three remain research-only and cannot produce promotion/order authority.

- [ ] **Step 2: Update dependency direction in ARCHITECTURE/DECISIONS**

Document:

```text
MarketDataService → Research Replay → Strategy Kernel
                         ↑
RQAlpha Adapter ────────┘

Research / Web / RQAlpha consume Strategy Kernel;
Strategy Kernel never imports those consumers.
```

Correct the drawing in prose if necessary so it does not imply Strategy Kernel reads MarketDataService directly; the replay consumer supplies Bars/Facts to the kernel.

- [ ] **Step 3: Narrow the old RQAlpha “no Canonical” statement**

Allow only the JDJ dominant identity schedule bridge; explicitly keep Canonical OHLCV forbidden inside RQAlpha runner.

- [ ] **Step 4: Add exact commands to TESTING.md**

Add targeted kernel/replay/Web/fake-RQAlpha commands from Tasks 1～7. Do not add a real Bundle command to automatic verification.

- [ ] **Step 5: Run targeted backend strategy/research tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

If Task 7 is present, append `services/quant-api/tests/backtest/test_jdj_dominant_schedule.py services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py`.

- [ ] **Step 6: Run the backend baseline, Ruff and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/market_data
```

- [ ] **Step 7: Run Web tests and build**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 8: Run engineering/document checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Review the diff and confirm no DB migration, production config, Alert, Runtime, main/tag or real-data mutation is present.

- [ ] **Step 9: Independent whole-branch review**

Review specifically for:

- future/same-boundary leakage;
- event identity drift after refactor;
- cross-contract state leakage;
- float usage in price/risk/PnL;
- favorable intrabar ordering;
- RQAlpha strategy formula duplication;
- unsupported-period silent fallback;
- accidental Canonical OHLCV use in RQAlpha;
- parameter-search or promotion scope creep.

- [ ] **Step 10: Commit closeout docs/fixes**

```bash
git add PROJECT_SOURCE.md AGENTS.md docs/ARCHITECTURE.md DECISIONS.md docs/RQALPHA_RESEARCH_BACKTEST.md TESTING.md
git commit -m "docs: define shared JDJ strategy boundaries"
```

---

## Integration and Gates

Implementation execution model:

```text
fresh develop
→ task worktree / branch
→ Tasks 1～6
→ RQAlpha workbench prerequisite check
→ Task 7 when prerequisite exists
→ Task 8 verification + independent review
→ user reviews exact diff/results
→ integrate develop
```

Allowed in implementation: repository code/tests/docs and read-only deterministic fixtures.

Not authorized by this plan:

```text
real RQAlpha Bundle smoke
parameter sweep
JM profitability conclusion
prospective OOS consumption
main/tag/release
Runtime promotion/switch
Alert/PushPlus
DB/Canonical/Redis writes
real orders
```

The first real JM RQAlpha run is a separate post-implementation Gate. Its first purpose is causal/fill/contract/risk verification, not parameter tuning or profitability selection.
