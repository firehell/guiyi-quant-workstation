# 日进斗金 JM 1m Shared Strategy Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 N Structure/JDJ Candidate 公式下沉为唯一 Shared Strategy Kernel，在不改变冻结 Candidate 语义的前提下实现 `jdj_jm_1m_v1` 完整交易生命周期、actual_dominant Historical Strategy Replay、Market 主图展示和 RQAlpha research-only adapter。

**Architecture:** `app.strategy_kernel` 是唯一公式与执行策略语义层；`app.research`、Historical Replay 和 RQAlpha 都只是消费者。Historical Replay 使用 Canonical `actual_dominant` physical segments；RQAlpha 使用 Bundle price/fill，只额外只读消费由 `MainContractMap` 生成的 dominant identity schedule。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、`Decimal`、现有 `MarketDataService` / `ActualDominantResearchSegmentLoader`、Vue 3、TypeScript、Lightweight Charts、RQAlpha Plus local-only workbench。

**Spec:** `docs/superpowers/specs/2026-08-23-jdj-jm-1m-shared-strategy-kernel-design.md`

## Global Constraints

- 本任务为 Lane 3；策略公式、回测成交时序和主力 identity 均属于可信口径。
- 第一版唯一 profile：`jdj_jm_1m_v1`；`symbol=jm`、`series_kind=actual_dominant`、execution=`1m`、trend context=`5m`。
- 现有三个 JDJ Candidate 的 event identity、direction、`observed_at`、trigger level、strict-before、same-contract/same-segment 语义必须保持逐事件一致。
- 金额、价格、仓位风险、PnL、手续费统一使用 `Decimal`；数量为整数手。
- 不创建 StrategyBase、plugin framework、optimizer、Portfolio platform；不适配其他策略、品种或周期。
- Historical Replay 只读 Canonical；不得写 DB、Canonical 或 Redis。
- RQAlpha adapter 的价格与撮合来自 Bundle；Canonical 只允许导出 dominant identity schedule，不得把 Canonical Bar 注入 runner。
- 不接 Alert、PushPlus、Execution Review、Runtime 或真实订单账户。
- 本 Plan 不执行真实 RQAlpha Bundle smoke；真实回测需要后续单独执行意图。
- 不发布 main/tag，不做 Runtime promotion。

---

## File Structure

### Shared Formula / Strategy Kernel

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

### Historical Replay Consumer

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

### RQAlpha Workbench Integration

Only after the separately approved RQAlpha workbench exists, create/modify:

```text
services/quant-api/app/backtest/dominant_schedule.py
services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py
services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py
services/quant-api/app/backtest/strategies/registry.json
services/quant-api/tests/backtest/test_jdj_dominant_schedule.py
services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

If `services/quant-api/app/backtest/` does not exist when Task 7 starts, Task 7 must stop. Do not recreate the workbench inside this plan; finish Tasks 1–6, execute the already-approved RQAlpha workbench implementation plan separately, integrate that result into `develop`, then resume Task 7 from a fresh task branch/worktree.

---

### Task 1: Extract the N Structure Pure Kernel Without Semantic Change

**Files:**
- Create: `services/quant-api/app/strategy_kernel/n_structure/*.py`
- Modify: imports under `services/quant-api/app/research/n_structure/` and JDJ/N consumers
- Test: `services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py`

**Interfaces:**
- Consumes: `CanonicalBar`, exact `NStructurePolicy`
- Produces unchanged public types/functions: `NStructureKind`, `NStructureSnapshot`, `NSwingPivot`, `NStructureSegmentTrace`, `evaluate_n_structure_segment`

- [ ] **Step 1: Copy the current five pure N modules to the new package without changing the old imports yet**

Copy exactly:

```text
n_structure_policy.py
n_structure_pattern.py
n_structure_swing.py
n_structure_state.py
n_structure_segment.py
```

Do not copy research service, candidate validation, HTTP, CLI or reporting modules.

- [ ] **Step 2: Add parity tests that import old and new modules simultaneously**

Reuse the current deterministic N test fixtures. For every tested segment, call both old and new `evaluate_n_structure_segment` with the same bars, contract, segment boundaries and exact policy, then require object equality:

```python
assert new_trace == old_trace
assert new_trace.swings.pivots == old_trace.swings.pivots
assert new_trace.structures.snapshots == old_trace.structures.snapshots
```

Add explicit cases for epoch reset, latest same-epoch pivot selection and trading-day boundary already represented by the current N/JDJ fixture builders.

- [ ] **Step 3: Run the parity test before changing production imports**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py
```

Expected: PASS. Any failure means the copy is not exact and blocks the task.

- [ ] **Step 4: Change production imports to `app.strategy_kernel.n_structure`**

Required dependency direction:

```text
app.research.* → app.strategy_kernel.n_structure.*
app.strategy_kernel.* -X-> app.research.*
```

Update JDJ context imports in the same change so there is no mixed old/new N type identity.

- [ ] **Step 5: Run N research, candidate and JDJ context tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_kernel_parity.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_jdj_context.py
```

Expected: PASS.

- [ ] **Step 6: Remove the old five pure module files only after no production import references remain**

Run:

```bash
rg 'app\.research\.n_structure\.n_structure_(policy|pattern|swing|state|segment)' services/quant-api/app services/quant-api/tests
```

Expected after import migration: no active references. Then remove the old pure files; research-specific files stay under `app/research/n_structure`.

- [ ] **Step 7: Re-run the Task 1 test command and commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/tests
git commit -m "refactor(strategy): extract shared N structure kernel"
```

---

### Task 2: Extract JDJ Candidate Logic and Prove Exact Parity

**Files:**
- Create: shared copies of `jdj_policy.py`, `jdj_context.py`, `jdj_events.py`, `jdj_trend_follow.py`, `jdj_trend_reentry.py`, `jdj_key_level_breakout.py`
- Modify: JDJ research, robustness/convergence and tests to use shared types
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py`

**Interfaces:**
- Consumes: Shared N kernel + `CanonicalBar`
- Produces unchanged `JdjBarContext`, existing Candidate event dataclasses and the three reducer functions

- [ ] **Step 1: Copy the six current pure JDJ modules to `app.strategy_kernel.jdj` while leaving old modules temporarily intact**

No formula, event-id builder, dataclass field, strict-before rule or policy payload may be edited during this copy.

- [ ] **Step 2: Add old-vs-new parity tests**

Reuse the fixture helpers in current JDJ tests, especially `_bar`, `_m1_bars`, `_m5_bars` and the existing deterministic reducer contexts. For each of the three reducers, run old and new implementations over the identical context tuple and require full trace equality:

```python
assert new_trend_follow_trace == old_trend_follow_trace
assert new_reentry_trace == old_reentry_trace
assert new_key_level_trace == old_key_level_trace
```

Separate parity cases must cover successful trigger, failed reaction, failed retest, same-bar ambiguity, strict-before visibility, trading-day reset and physical-contract boundary.

- [ ] **Step 3: Run JDJ parity before changing production imports**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py
```

Expected: PASS. This is the formula-migration Gate.

- [ ] **Step 4: Update all production imports to shared JDJ/N types**

`JdjResearchService`, candidate validation, robustness, convergence and historical overlay must import event/context/reducer types from `app.strategy_kernel.jdj`. Do not keep duplicated dataclasses under `app.research.jdj`.

- [ ] **Step 5: Run existing JDJ research surfaces with parity tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS with existing Candidate identities unchanged.

- [ ] **Step 6: Remove the six old pure JDJ files after `rg` confirms no production consumer imports them**

Keep `jdj_research.py`, `jdj_research_service.py`, candidate validation/calendar and other research-only orchestration under `app/research/jdj`.

- [ ] **Step 7: Re-run Task 2 tests and commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/tests
git commit -m "refactor(strategy): make JDJ candidate kernel shared"
```

---

### Task 3: Freeze the Strategy Policy/Profile and Implement Entry Authorization

**Files:**
- Create: `data/strategy_policies/jdj_intraday_futures_v1.json`
- Create: `data/strategy_profiles/jdj_jm_1m_v1.json`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_policy.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_profile.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/target.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/risk.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py`

**Interfaces:**

Define these exact public contracts:

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
    opening_profit_giveback_guard: bool

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

Public functions:

```text
load_jdj_strategy_policy() -> JdjStrategyPolicy
load_jdj_strategy_profile(profile_id: str) -> JdjStrategyProfile
resolve_candidate_conflict(events: Sequence[JdjTriggerEvent]) -> JdjCandidateSelection
resolve_stop_price(event, contexts, instrument, profile) -> Decimal
resolve_target_price(direction, entry_reference, known_pivots, known_session_high, known_session_low) -> Decimal | None
calculate_base_quantity(equity, available_cash, entry_reference, stop_price, instrument, profile) -> int
authorize_entry(selection, context, account, instrument, profile) -> EntryAuthorization
```

- [ ] **Step 1: Write exact JSON contract tests**

The accepted `jdj_jm_1m_v1` test must assert all Spec values exactly: `jm`, `actual_dominant`, `1m`, `5m`, one tick buffer, base risk `0.005`, episode cap `0.01`, minimum R:R `2.0`, first take fraction `0.40`, add fraction `0.25`, max adds `2`, daily pause `0.005` for 15 trading minutes, daily stop `0.01`, opening-profit guard disabled.

Also assert unknown profile id and modified contract payload fail closed.

- [ ] **Step 2: Write conflict/stop/target/risk RED tests**

Required expectations:

```text
same-direction key-level + reentry + trend-follow → one selection with primary=key-level and two supporting source ids
LONG + SHORT on same decision bar → allowed=false, reason=AMBIGUOUS_DIRECTION
no forward target → reason=TARGET_UNAVAILABLE
reward:risk=1.99 → reason=REWARD_RISK_TOO_LOW
missing InstrumentSpec → reason=INSTRUMENT_SPEC_UNAVAILABLE
calculated base quantity < 1 → reason=POSITION_SIZE_ZERO
```

For stop tests, use concrete current event fixtures and assert one tick below/above the exact reaction, excursion or frozen key-level reference stated in the Spec.

- [ ] **Step 3: Run the contract tests and verify they fail before implementation**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
```

Expected: FAIL because the new policy/profile/authorization modules are absent.

- [ ] **Step 4: Implement exact policy/profile loaders with `app.core.exact_json_contract`**

No formula field may silently default. Unknown, missing or changed fields raise stable strategy contract errors.

- [ ] **Step 5: Implement candidate conflict and setup-specific stop resolution**

Use only decision-time facts. Apply the one-tick buffer in the adverse direction after resolving the setup’s structural stop.

- [ ] **Step 6: Implement target resolution**

Filter to levels already known at decision time; LONG keeps levels strictly above entry, SHORT strictly below; choose the nearest favorable level. An empty set returns no target and causes authorization rejection.

- [ ] **Step 7: Implement R:R and integer futures sizing with Decimal only**

The quantity algorithm is exactly:

```text
risk_cash = equity × 0.005
per_contract_risk = abs(entry_reference - stop_price) × contract_multiplier + estimated_round_trip_cost
qty_by_risk = floor(risk_cash / per_contract_risk)
qty_by_margin = floor(available_cash / margin_per_contract)
base_qty = min(qty_by_risk, qty_by_margin)
```

Authorization also rejects any planned episode risk above equity × `0.01`.

- [ ] **Step 8: Run Task 3 tests until green**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add data/strategy_policies data/strategy_profiles services/quant-api/app/strategy_kernel/jdj services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): define JDJ JM 1m execution contract"
```

---

### Task 4: Implement Position Management, Daily Risk and the Deterministic Replay Fill Model

**Files:**
- Create: `services/quant-api/app/strategy_kernel/jdj/execution.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/engine.py`
- Create: `services/quant-api/app/research/jdj_strategy/replay.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py`

**Interfaces:**

Define:

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

Public functions:

```text
initial_jdj_strategy_state(trading_day: date, start_equity: Decimal) -> JdjStrategyState
reduce_jdj_strategy_frame(state: JdjStrategyState, frame: JdjStrategyFrame, policy: JdjStrategyPolicy, profile: JdjStrategyProfile) -> JdjStrategyStep
run_jdj_reference_replay(frames: Sequence[JdjStrategyFrame], policy: JdjStrategyPolicy, profile: JdjStrategyProfile) -> JdjReplayResult
```

- [ ] **Step 1: Write RED tests for target1 partial profit and add eligibility**

Concrete expectations:

```text
10 lots at target1 → REDUCE 4 lots, 6 remain, partial_profit_taken=true
2 lots at target1 → floor(2×0.40)=0, no fake REDUCE and partial_profit_taken remains false
before real profitable partial exit → ADD forbidden
first valid post-profit EMA20 reaction → add floor(current_qty×0.25) if at least 1
second valid reaction → second add if risk/margin permit
third reaction → no ADD
negative realized episode → no ADD
successful ADD → protective stop equals post-fill weighted average cost
```

- [ ] **Step 2: Write RED tests for daily pause/stop**

Use `start_equity=100000` in tests:

```text
current equity 99499 → drawdown 0.501% → DAILY_PAUSE and no new Entry/Add for 15 trading minutes
current equity 99000 → drawdown 1.0% → DAILY_STOP, remaining position exits, stopped_for_day=true
next trading day → pause/stop state reset
```

Existing position stop/exit management must continue during the pause.

- [ ] **Step 3: Write RED tests for reference fills**

Use explicit two-Bar fixtures to assert:

```text
completed-bar Entry decision → next same-segment Bar open
LONG resting stop with next open below stop → fill at next open
LONG resting stop with open above stop and low below stop → fill at stop
profit target touched without gap → fill at target
no next Bar inside the same physical segment → intent cancelled
same Bar touches both target and stop → EXIT uses stop first and records INTRABAR_ORDER_AMBIGUOUS
```

Add SHORT symmetric cases.

- [ ] **Step 4: Run Task 4 tests and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
```

- [ ] **Step 5: Implement immutable position and daily-risk transitions**

Every action records source event ids, profile id, contract, trading day, segment start, `decision_at`, `effective_at`, quantity, post-action quantity, stop, target, planned risk, R:R and reason.

- [ ] **Step 6: Implement the replay fill model exactly as specified**

No completed-bar decision may fill on the decision Bar. Stop/target ambiguity always uses the adverse ordering rather than the profitable ordering.

- [ ] **Step 7: Run execution + Candidate parity together**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py \
  services/quant-api/tests/strategy_kernel/test_jdj_kernel_parity.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

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

Add two read-only endpoints:

```text
GET /api/v1/market/research/jdj-strategy/profiles?symbol=jm
GET /api/v1/market/research/jdj-strategy/history?series_kind=actual_dominant&symbol=jm&frequency=1m&since=YYYY-MM-DD&through=YYYY-MM-DD
```

- [ ] **Step 1: Write RED service tests with two physical JM contract segments**

The fixture must contain two non-overlapping resolved segments. Require:

```text
every emitted action contract matches the segment containing its trading day
no position/action state crosses the segment boundary
profile_id is jdj_jm_1m_v1
the same prefix evaluated alone and as part of a longer through-date keeps identical event ids, decision_at and effective_at
```

- [ ] **Step 2: Write RED API contract tests**

Required responses:

```text
jm + actual_dominant + 1m → accepted
jm + actual_dominant + 5m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
rb + actual_dominant + 1m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
jm + continuous + 1m → 422 invalid request
source/segment identity unavailable → 409 typed source error
```

- [ ] **Step 3: Implement `JdjStrategyReplayService`**

It consumes the existing `ActualDominantResearchSegmentLoader`, exact shared JDJ/N policy and accepted strategy profile. Each physical segment is processed independently; no derived events are persisted.

- [ ] **Step 4: Add Pydantic DTOs**

Response action DTO must expose profile id, event id, action kind, primary/supporting setup, contract/segment, direction, decision/effective time, price, qty/post-position qty, stop, target, planned risk fraction, R:R and reason. Preserve backend values as Decimal-compatible JSON values; do not compute strategy logic in schema conversion.

- [ ] **Step 5: Wire composition and the two routes**

The existing Candidate `/jdj/history` route stays unchanged and separate.

- [ ] **Step 6: Run service/API tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/jdj_strategy services/quant-api/app/research/composition.py services/quant-api/app/research/historical_overlay_api.py services/quant-api/app/schemas/research_overlays.py services/quant-api/tests
git commit -m "feat(research): expose JDJ JM strategy replay"
```

---

### Task 6: Add a Separate `日进斗金策略` Market Overlay and Profile-Aware Frequency Switching

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
- Consumes Task 5 profile/history endpoints
- Produces overlay id `jdj_strategy`, distinct from existing JDJ Candidate overlay

- [ ] **Step 1: Write RED marker mapping tests**

Exact glyph mapping:

```text
LONG ENTRY  → ▲
SHORT ENTRY → ▼
ADD         → ＋
REDUCE      → －
EXIT        → ×
```

Hover model must include primary setup, supporting setups, contract, decision/effective timestamps, quantity, stop, target, R:R and reason.

- [ ] **Step 2: Write RED composable identity tests**

Require:

```text
jm / actual_dominant / 1m → load accepted jdj_jm_1m_v1
switch 1m → 5m → clear markers and show profile unavailable
switch 5m → 1m → reload profile without duplicate event ids
prepend older bars → preserve existing event ids and append only new historical ids
stale response after identity change → ignored
```

- [ ] **Step 3: Implement API/type projections and marker utility**

Web receives already-computed actions. No EMA, N Structure, R:R, stop, position or PnL formula may appear in TypeScript.

- [ ] **Step 4: Implement `useHistoricalStrategyMarkers` independently**

Use the same generation/full-identity stale-response protection pattern as `useHistoricalResearchMarkers`, but maintain a separate event map and error state.

- [ ] **Step 5: Add `日进斗金策略` chart control**

Candidate “日进斗金” and Strategy “日进斗金策略” remain two distinct selections. Unsupported frequency displays “该品种/周期尚未验证”; old 1m strategy markers must be removed immediately on identity change.

- [ ] **Step 6: Extend Playwright coverage**

Cover Candidate vs Strategy separation and `1m → 5m → 1m` switching without stale marker leakage.

- [ ] **Step 7: Run Web tests/build**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/quant-web
git commit -m "feat(web): show JDJ historical strategy replay"
```

---

### Task 7: Integrate the Same Kernel Into the Local RQAlpha Workbench

**Prerequisite Gate:**

```bash
test -d services/quant-api/app/backtest
```

Expected: exit 0. If the directory is absent, stop Task 7 and implement the separately approved RQAlpha workbench plan first; do not create a second workbench in this task.

**Files:**
- Create: `services/quant-api/app/backtest/dominant_schedule.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py`
- Modify: `services/quant-api/app/backtest/strategies/registry.json`
- Modify: existing backtest result normalization only where needed for JDJ attribution
- Test: `services/quant-api/tests/backtest/test_jdj_dominant_schedule.py`
- Test: `services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py`

**Interfaces:**

`dominant_schedule.json` contains only:

```json
{
  "symbol": "jm",
  "series_kind": "actual_dominant",
  "contracts_by_trading_day": {
    "2026-08-20": "JM2609"
  }
}
```

- [ ] **Step 1: Write RED dominant-schedule tests**

Use fake MainContractMap rows and require deterministic day→contract output; missing rank1 day, overlapping rank1 identities or non-JM request must fail with `DOMINANT_SCHEDULE_INCOMPLETE` or the exact input error defined by the module.

- [ ] **Step 2: Implement read-only schedule generation**

The file must not contain OHLCV, Canonical file paths, DB URL or credentials. It is generated before the runner starts and copied into the run directory as an input artifact.

- [ ] **Step 3: Write RED fake-RQAlpha adapter tests**

Required behaviors:

```text
adapter imports app.strategy_kernel.jdj rather than app.research.jdj formulas
current Bundle contract must equal dominant schedule contract before an order intent is accepted
ENTRY/ADD open futures exposure; REDUCE/EXIT close only existing simulated exposure
no strategy action may call MarketDataService or read Canonical Bars inside the runner
run metadata remains research_only=true, formal_evidence=false, promotion_eligible=false
```

Use fake RQAlpha order/account objects; do not import the commercial runtime in unit tests.

- [ ] **Step 4: Implement the thin RQAlpha lifecycle adapter**

The RQAlpha strategy file handles engine callbacks and translates Bundle bars/account/fills into Shared Kernel frames. It must not reimplement EMA20, N Structure or any JDJ Setup reducer.

- [ ] **Step 5: Register only `jdj_intraday_futures_v1 / jdj_jm_1m_v1`**

Formula/profile-frozen fields are not exposed as arbitrary Web overrides. Workbench-level capital, cost and slippage inputs remain governed by the existing workbench contract.

- [ ] **Step 6: Add JDJ episode attribution to normalized results**

Expose profile, physical contract, primary/supporting setup, entry/exit, add/reduce count, exit reason, gross/cost/net PnL, return_R, MFE_R, MAE_R and holding bars using RQAlpha fills/account facts. Do not introduce a parallel price/PnL calculator.

- [ ] **Step 7: Run fake adapter tests only**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/backtest/test_jdj_dominant_schedule.py \
  services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

Expected: PASS. Do not run the real Bundle.

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
- Do not update `STATUS.md` unless a separate status action explicitly records this exact implementation as a develop release candidate.

- [ ] **Step 1: Update stable product/data boundaries**

Document these distinct identities:

```text
JDJ Candidate Research = source event facts only
JDJ Historical Strategy Replay = Canonical actual_dominant deterministic reference execution
RQAlpha JDJ Backtest = RQAlpha Bundle price/fill + Canonical-derived dominant identity schedule
```

All remain research-only and grant no promotion/order authority.

- [ ] **Step 2: Document dependency direction**

The canonical description must say that Research Replay obtains Historical data and supplies facts/bars into Shared Strategy Kernel; Strategy Kernel never reads FastAPI/DB/RQAlpha/Research consumers itself. RQAlpha adapter also consumes Shared Kernel, not Research formulas.

- [ ] **Step 3: Narrow the old RQAlpha “no Canonical” statement**

Allow only the JDJ dominant identity schedule bridge; continue to prohibit Canonical OHLCV in the RQAlpha runner.

- [ ] **Step 4: Add Task 1–7 test commands to `TESTING.md`**

Do not add a real Bundle smoke command to automatic verification.

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

If Task 7 exists, append the two fake backtest tests from Task 7 to this verification run.

- [ ] **Step 6: Run backend baseline, Ruff and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/market_data
```

Expected: all commands exit 0.

- [ ] **Step 7: Run Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: all commands exit 0.

- [ ] **Step 8: Run engineering/document checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

`git status --short` may show only intended task files before commit; no `.env`, production secret/config, migration, Runtime or unrelated dirty paths are allowed.

- [ ] **Step 9: Perform an independent whole-branch Review before integration**

Reviewer must explicitly inspect: future/same-boundary leakage, Candidate event identity drift, cross-contract state leakage, float use in financial semantics, favorable intrabar ordering, duplicated RQAlpha formulas, unsupported-period fallback, Canonical OHLCV use inside RQAlpha, and parameter-search/promotion scope creep.

- [ ] **Step 10: Commit canonical closeout**

```bash
git add PROJECT_SOURCE.md AGENTS.md docs/ARCHITECTURE.md DECISIONS.md docs/RQALPHA_RESEARCH_BACKTEST.md TESTING.md
git commit -m "docs: define shared JDJ strategy boundaries"
```

---

## Integration and Gates

Implementation flow:

```text
fresh develop
→ Lane 3 task worktree/branch
→ Tasks 1–6
→ RQAlpha workbench prerequisite Gate
→ Task 7 only when prerequisite exists
→ Task 8 full verification
→ independent Review
→ user reviews exact diff/results
→ integrate develop
```

Allowed by this Plan: repository code/tests/docs and deterministic read-only test fixtures.

Not authorized by this Plan:

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

The first real JM RQAlpha run is a separate post-implementation Gate. Its first purpose is contract/fill/causality/risk verification, not parameter tuning or profitability selection.
