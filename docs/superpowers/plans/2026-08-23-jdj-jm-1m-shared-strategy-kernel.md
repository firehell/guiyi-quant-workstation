# 日进斗金 JM 1m Shared Strategy Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 N/JDJ Candidate 因果语义的前提下，建立唯一 Shared Strategy Kernel，完成 `jdj_jm_1m_v1` 的 reference execution lifecycle、actual_dominant Historical Strategy Replay、Market 主图展示、batch/streaming parity，并在 RQAlpha Workbench 已存在后接入同一 Kernel。

**Architecture:** `app.strategy_kernel` 是公式与策略状态唯一来源；`app.research`、Historical Replay、Web 和 RQAlpha 都只是消费者。Historical Replay 使用 Canonical actual_dominant physical segments；RQAlpha 使用 Bundle price/fill，并在 child runner 启动前接收由现有 Market/Catalog read path 导出的非价格 identity schedule。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、`Decimal`、`MarketDataService` / `ActualDominantResearchSegmentLoader`、existing TradingSession resolver、Vue 3、TypeScript、Lightweight Charts、RQAlpha Plus local-only workbench。

**Spec:** `docs/superpowers/specs/2026-08-23-jdj-jm-1m-shared-strategy-kernel-design.md`

## Global Constraints

- Lane 3；策略公式、主力 identity、回测成交时序与风险语义均按可信口径处理。
- V1 唯一 accepted profile：`jdj_jm_1m_v1`；`jm / actual_dominant / 1m / 5m context`。
- 现有 N/JDJ Candidate 的 primitive golden projection 必须逐项不变；不得用“测试数量相同”代替 identity parity。
- 所有金融语义使用 `Decimal`；手数使用 `int`。
- 不建设 StrategyBase/plugin/optimizer/Portfolio 平台，不实现其他品种/周期/策略。
- Historical Replay 只读 Canonical/Catalog；不得写 DB、Canonical、Redis。
- RQAlpha child runner 不获得 Canonical OHLCV、DB URL 或项目凭据；只得到 Bundle、strategy/profile 和非价格 identity schedule。
- V1 统一 completed-bar decision + next executable bar open reference execution；不实现 intrabar stop/target 猜测。
- 不接 Alert、PushPlus、Execution Review、Runtime 或真实订单账户。
- 本 Plan 不授权真实 RQAlpha Bundle smoke；真实回测另行 Gate。
- 不发布 main/tag，不做 Runtime promotion。

## Execution Phases

本 Plan 分两阶段，Codex **不得在一次会话中无条件跑到底**：

```text
Phase A（当前可实现）
Task 0–7
Shared Kernel → Reference Replay → Web → Streaming parity
        ↓
独立 Review Gate

Phase B（有前置条件）
RQAlpha Workbench 已按其独立 Plan 存在于 develop
        ↓
Task 8 RQAlpha adapter
        ↓
Task 9 canonical closeout / full verification
```

如果 `services/quant-api/app/backtest/` 在 Task 8 开始时不存在，必须停止 Phase B；不能在本 Plan 中顺手重建工作台。

---

## File Structure

### Shared formula and strategy kernel

Create:

```text
services/quant-api/app/strategy_kernel/__init__.py
services/quant-api/app/strategy_kernel/n_structure/__init__.py
services/quant-api/app/strategy_kernel/jdj/__init__.py
services/quant-api/app/strategy_kernel/jdj/strategy_policy.py
services/quant-api/app/strategy_kernel/jdj/strategy_profile.py
services/quant-api/app/strategy_kernel/jdj/target.py
services/quant-api/app/strategy_kernel/jdj/risk.py
services/quant-api/app/strategy_kernel/jdj/execution.py
services/quant-api/app/strategy_kernel/jdj/engine.py
services/quant-api/app/strategy_kernel/jdj/streaming.py
```

Move with history (`git mv`), do not copy as parallel implementations:

```text
app/research/n_structure/n_structure_policy.py     → app/strategy_kernel/n_structure/
app/research/n_structure/n_structure_pattern.py    → app/strategy_kernel/n_structure/
app/research/n_structure/n_structure_swing.py      → app/strategy_kernel/n_structure/
app/research/n_structure/n_structure_state.py      → app/strategy_kernel/n_structure/
app/research/n_structure/n_structure_segment.py    → app/strategy_kernel/n_structure/

app/research/jdj/jdj_policy.py                     → app/strategy_kernel/jdj/
app/research/jdj/jdj_context.py                    → app/strategy_kernel/jdj/
app/research/jdj/jdj_events.py                     → app/strategy_kernel/jdj/
app/research/jdj/jdj_trend_follow.py               → app/strategy_kernel/jdj/
app/research/jdj/jdj_trend_reentry.py              → app/strategy_kernel/jdj/
app/research/jdj/jdj_key_level_breakout.py         → app/strategy_kernel/jdj/
```

Create contracts:

```text
data/strategy_policies/jdj_intraday_futures_v1.json
data/strategy_profiles/jdj_jm_1m_v1.json
```

### Reference replay

Create:

```text
services/quant-api/app/research/jdj_strategy/__init__.py
services/quant-api/app/research/jdj_strategy/models.py
services/quant-api/app/research/jdj_strategy/replay.py
services/quant-api/app/research/jdj_strategy/service.py
services/quant-api/tests/strategy_kernel/__init__.py
services/quant-api/tests/strategy_kernel/fixtures.py
services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py
services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py
services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py
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

### RQAlpha adapter, only in Phase B

Create/modify only after Workbench prerequisite passes:

```text
services/quant-api/app/backtest/execution_identity_schedule.py
services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py
services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py
services/quant-api/app/backtest/strategies/registry.json
services/quant-api/tests/backtest/test_jdj_execution_identity_schedule.py
services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

---

### Task 0: Freeze Current Golden Candidate Semantics Before Refactoring

**Files:**
- Create: `services/quant-api/tests/strategy_kernel/fixtures.py`
- Create: `services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py`
- Create: `services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py`
- Read only: current N/JDJ tests and exact policies

**Interfaces:**
- Produces immutable primitive expected projections used after module moves.
- Does not change production imports or formulas.

- [ ] **Step 1: Inventory every production import that will move**

Run:

```bash
rg 'app\.research\.(n_structure\.n_structure_|jdj\.jdj_(policy|context|events|trend_follow|trend_reentry|key_level_breakout))' \
  services/quant-api/app services/quant-api/tests
```

Save the output in the Codex task notes, not a new repository artifact. It is the migration checklist.

- [ ] **Step 2: Create deterministic test-only fixture builders**

Copy only the small `_bar`/context construction helpers needed from the current tests into `tests/strategy_kernel/fixtures.py`. Do not import one test module from another.

- [ ] **Step 3: Add primitive N projection helpers**

Project current N output to tuples/dicts of primitives rather than class equality:

```python
def project_n_trace(trace):
    return {
        "pivots": [
            (
                p.pivot_id,
                p.epoch,
                p.kind.value,
                p.pivot_time.isoformat(),
                p.confirmed_at.isoformat(),
                str(p.price),
                p.contract,
                p.segment_start_trading_day.isoformat(),
            )
            for p in trace.swings.pivots
        ],
        "snapshots": [
            (
                s.epoch,
                s.kind.value,
                s.observed_at.isoformat(),
            )
            for s in trace.structures.snapshots
        ],
    }
```

Use the existing deterministic segment scenarios for outside reset, same-epoch pivot selection and a normal trend segment. Paste the resulting literal primitive dictionaries into the test as expected constants.

- [ ] **Step 4: Add primitive JDJ projection helpers**

For each reducer project:

```python
def project_jdj_trace(trace):
    return {
        "events": [
            (
                e.event_id,
                e.candidate_id,
                e.source_event_kind,
                e.direction.value,
                e.observed_at.isoformat(),
                str(e.trigger_level),
                e.contract,
                e.trading_day.isoformat(),
            )
            for e in trace.events
        ],
        "ambiguous": trace.ambiguous_count,
        "invalidated": trace.invalidated_count,
        "expired_no_retest": getattr(trace, "expired_no_retest_count", None),
        "expired_context_lost": getattr(trace, "expired_context_lost_count", None),
    }
```

Freeze separate literal expectations for Trend Follow success/ambiguity, Reentry success/failed reaction and Key Level success/failed retest.

- [ ] **Step 5: Run the golden tests on the untouched production code**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py
```

Expected: PASS before any production move. If literals do not match, fix the fixture/expectation; do not change production formulas.

- [ ] **Step 6: Commit the golden Gate**

```bash
git add services/quant-api/tests/strategy_kernel
git commit -m "test(strategy): freeze N and JDJ candidate golden facts"
```

---

### Task 1: Move the Pure N Structure Kernel Without Semantic Change

**Files:**
- Move: five pure N modules listed in File Structure
- Modify: all production/test imports found by Task 0
- Test: golden N + existing N/JDJ consumers

**Interfaces:**
- Produces unchanged `NStructurePolicy`, `NSwingPivot`, `NStructureKind`, `NStructureSnapshot`, `NStructureSegmentTrace`, `evaluate_n_structure_segment` under `app.strategy_kernel.n_structure`.

- [ ] **Step 1: `git mv` the five exact modules**

Do not copy and keep parallel definitions.

- [ ] **Step 2: Fix their internal imports first**

All five modules must import sibling N modules from `app.strategy_kernel.n_structure`; they may continue consuming `app.market_data.domain.CanonicalBar` as the normalized domain value.

- [ ] **Step 3: Update all Research/CLI/test consumers**

Dependency direction must be:

```text
app.research / guiyi_cli → app.strategy_kernel.n_structure
app.strategy_kernel      -X-> app.research
```

- [ ] **Step 4: Verify old pure-module imports are gone**

```bash
rg 'app\.research\.n_structure\.n_structure_(policy|pattern|swing|state|segment)' \
  services/quant-api/app services/quant-api/tests
```

Expected: no active import references.

- [ ] **Step 5: Run golden and current consumer tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_jdj_context.py
```

Expected: PASS and primitive golden output unchanged.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/guiyi_cli services/quant-api/tests
git commit -m "refactor(strategy): move pure N structure kernel"
```

---

### Task 2: Move the Pure JDJ Candidate Kernel and Keep Golden Identity

**Files:**
- Move: six JDJ modules listed in File Structure
- Modify: JDJ research, validation, robustness, convergence, overlays, CLI/tests
- Test: all current JDJ direct reducer tests + golden

**Interfaces:**
- Produces unchanged Candidate dataclasses and reducer functions under `app.strategy_kernel.jdj`.

- [ ] **Step 1: `git mv` the six pure modules**

No event-id builder, policy payload, dataclass field or formula edit in this step.

- [ ] **Step 2: Update internal imports to Shared N/JDJ paths**

No module under `app.strategy_kernel` may import `app.research`.

- [ ] **Step 3: Update all production consumers**

Use the Task 0 `rg` inventory plus a fresh repository-wide `rg` after edits. Robustness/convergence must consume the same moved event classes, not compatibility copies.

- [ ] **Step 4: Verify no old JDJ pure imports remain**

```bash
rg 'app\.research\.jdj\.jdj_(policy|context|events|trend_follow|trend_reentry|key_level_breakout)' \
  services/quant-api/app services/quant-api/tests
```

Expected: no active references.

- [ ] **Step 5: Run JDJ golden/direct/research tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS; frozen primitive event projections unchanged.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/guiyi_cli services/quant-api/tests
git commit -m "refactor(strategy): move pure JDJ candidate kernel"
```

---

### Task 3: Freeze Strategy Policy/Profile and Entry Authorization

**Files:**
- Create: `data/strategy_policies/jdj_intraday_futures_v1.json`
- Create: `data/strategy_profiles/jdj_jm_1m_v1.json`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_policy.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/strategy_profile.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/target.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/risk.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py`

**Interfaces:**

Define exact contracts:

```python
@dataclass(frozen=True, slots=True)
class JdjStrategyPolicy:
    policy_id: str
    candidate_policy_id: str
    minimum_reward_risk: Decimal
    max_planned_trade_risk_fraction: Decimal
    require_profit_before_add: bool
    require_partial_profit_before_add: bool
    add_fraction_of_current_qty: Decimal
    max_add_count: int
    losing_position_add_forbidden: bool
    daily_pause_drawdown_fraction: Decimal
    daily_pause_minutes: int
    daily_stop_drawdown_fraction: Decimal

@dataclass(frozen=True, slots=True)
class JdjStrategyProfile:
    profile_id: str
    symbol: str
    series_kind: str
    execution_frequency: BarFrequency
    trend_context_frequency: BarFrequency
    base_risk_fraction: Decimal
    first_profit_take_fraction: Decimal
    reference_stop_buffer_ticks: int
    terminal_flatten_lead_bars: int
    no_new_entry_lead_bars: int
    opening_profit_giveback_guard: bool
    historical_reference_cost_model: str
    historical_reference_margin_check: bool

@dataclass(frozen=True, slots=True)
class InstrumentExecutionFacts:
    contract_multiplier: Decimal
    price_tick: Decimal | None
    estimated_round_trip_cost: Decimal
    available_cash: Decimal
    margin_required_per_contract: Decimal | None

@dataclass(frozen=True, slots=True)
class EntryAuthorization:
    allowed: bool
    reason: str | None
    stop_price: Decimal | None
    target_price: Decimal | None
    reward_risk: Decimal | None
    admissible_price_bound: Decimal | None
    quantity: int
```

Public functions:

```text
load_jdj_strategy_policy() -> JdjStrategyPolicy
load_jdj_strategy_profile(profile_id: str) -> JdjStrategyProfile
resolve_candidate_conflict(events) -> JdjCandidateSelection
resolve_structural_stop(selection, context) -> Decimal
resolve_target_price(direction, entry_reference, known_levels) -> Decimal | None
admissible_entry_boundary(stop, target, minimum_reward_risk) -> Decimal
calculate_reference_quantity(equity, worst_admissible_price, stop, instrument, profile) -> int
authorize_entry(...) -> EntryAuthorization
```

- [ ] **Step 1: Write RED exact-contract tests**

Assert policy fields and profile fields are in their correct files. Specifically, `minimum_reward_risk`, max planned risk, add fraction/count, daily pause/stop are policy fields; `base_risk_fraction`, 40% first take and terminal guards are profile fields. Unknown/missing/extra/drifted JSON must fail closed.

- [ ] **Step 2: Write RED conflict/target/stop tests**

Require:

```text
same-direction key-level + reentry + trend-follow → one selection, primary=key-level
LONG + SHORT same decision bar → AMBIGUOUS_DIRECTION
no favorable known target → TARGET_UNAVAILABLE
structural stop on wrong side of entry → context invalid
```

Use exact current Candidate fixtures; do not invent a second EMA reaction detector.

- [ ] **Step 3: Write RED R:R and gap-bound tests**

For `r=2` assert the boundary algebra exactly:

```python
boundary = (target + Decimal("2") * stop) / Decimal("3")
```

LONG open above boundary and SHORT open below boundary must return `ENTRY_GAP_INVALIDATED`; equality is permitted only if R:R remains exactly 2 under Decimal arithmetic.

- [ ] **Step 4: Write RED sizing tests**

Use concrete `equity=100000`, `base_risk_fraction=0.005` and a multiplier fixture. Verify quantity uses worst admissible price and that adding estimated cost can reduce quantity by one. Missing/non-positive multiplier fails closed. Historical reference may omit margin; if trusted margin facts are present, quantity is `min(risk_qty, margin_qty)`.

- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
```

Expected: FAIL because strategy modules/contracts do not exist.

- [ ] **Step 6: Implement exact JSON loaders using `app.core.exact_json_contract`**

No formula/policy defaulting.

- [ ] **Step 7: Implement conflict, stop, target, boundary and sizing functions with Decimal only**

No financial conversion through float.

- [ ] **Step 8: Run green and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
git add data/strategy_policies data/strategy_profiles services/quant-api/app/strategy_kernel/jdj services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): freeze JDJ JM 1m strategy contract"
```

---

### Task 4: Implement TradeEpisode, Completed-Bar Execution and Daily/Session Risk

**Files:**
- Create: `services/quant-api/app/strategy_kernel/jdj/execution.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/engine.py`
- Create: `services/quant-api/app/research/jdj_strategy/models.py`
- Create: `services/quant-api/app/research/jdj_strategy/replay.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py`

**Interfaces:**

```python
class JdjActionKind(StrEnum):
    ENTRY = "entry"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    REJECTED_CANDIDATE = "rejected_candidate"
    DAILY_PAUSE = "daily_pause"
    DAILY_STOP = "daily_stop"

@dataclass(frozen=True, slots=True)
class TradeEpisode:
    episode_id: str
    initial_source_event_ids: tuple[str, ...]
    consumed_source_event_ids: frozenset[str]
    primary_setup: str
    supporting_setups: tuple[str, ...]
    direction: JdjDirection
    contract: str
    trading_day: date
    segment_start_trading_day: date
    quantity: int
    weighted_average_cost: Decimal
    protective_stop: Decimal
    target_1: Decimal
    add_count: int
    partial_profit_taken: bool
    realized_pnl: Decimal

@dataclass(frozen=True, slots=True)
class JdjStrategyState:
    trading_day: date
    start_equity: Decimal
    episode: TradeEpisode | None
    pause_bars_remaining: int
    stopped_for_day: bool

@dataclass(frozen=True, slots=True)
class JdjStrategyFrame:
    context: JdjBarContext
    candidate_events: tuple[JdjTriggerEvent, ...]
    account_equity: Decimal
    instrument: InstrumentExecutionFacts
    bars_remaining_in_trading_day: int
```

- [ ] **Step 1: Write RED Entry/Episode tests**

Assert ENTRY creates one deterministic `episode_id`; all initial source ids are consumed; re-presenting the same source event cannot create a second ENTRY/ADD.

- [ ] **Step 2: Write RED completed-bar partial-profit tests**

Require:

```text
LONG close < target → no reduce
LONG close >= target → REDUCE_INTENT
next same-segment open → fill reference reduce
10 lots × 0.40 → 4 reduced, 6 remain
2 lots × 0.40 → floor=0, no fake reduce, partial_profit_taken remains false
```

SHORT symmetric. Do not use Bar high/low to create intrabar target fills.

- [ ] **Step 3: Write RED profitable-add tests**

ADD source must be a **new full `jdj_trend_follow_1m_candidate_v1` event** after profitable partial exit. Require first/second add, third reject, losing Episode reject, repeated source event reject, and `floor(current_qty×0.25)` integer quantity. Re-run admissible-gap/risk checks before fill.

- [ ] **Step 4: Write RED exit tests**

Completed Bar close crossing protective stop/EMA or losing strict-prior 5m trend creates EXIT intent; fill is next legal Bar open. No intrabar stop fill assertions are allowed.

- [ ] **Step 5: Write RED daily-risk tests**

With `start_equity=100000`:

```text
99499 → drawdown 0.501% → DAILY_PAUSE
pause consumes exactly 15 subsequent in-session 1m frames, not wall-clock gaps
99000 → DAILY_STOP + JM V1 EXIT intent + stopped_for_day=true
new trading day → reset pause/stop
```

Existing Episode management continues during pause.

- [ ] **Step 6: Write RED session-terminal tests**

For `bars_remaining_in_trading_day=1`, new Entry/Add is forbidden. If an Episode exists, emit `SESSION_FLATTEN` exit intent so the final legal Bar open can execute. Intermediate session breaks are represented with bars remaining >1 and must not flatten.

- [ ] **Step 7: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
```

- [ ] **Step 8: Implement immutable reducer and deterministic reference execution**

Every action records `episode_id`, source ids, decision/effective time, contract/segment, qty/post-qty, stop/target, R:R, planned risk and reason. Reference fills always use the next legal open; no intrabar ambiguity code is introduced.

- [ ] **Step 9: Run contract + execution + Candidate golden together**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add services/quant-api/app/strategy_kernel/jdj services/quant-api/app/research/jdj_strategy services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): add JDJ trade episode execution"
```

---

### Task 5: Add JM actual_dominant Historical Reference Replay API

**Files:**
- Create: `services/quant-api/app/research/jdj_strategy/service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Test: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`

**Interfaces:**

```text
GET /api/v1/market/research/jdj-strategy/profiles?symbol=jm
GET /api/v1/market/research/jdj-strategy/history?series_kind=actual_dominant&symbol=jm&frequency=1m&since=YYYY-MM-DD&through=YYYY-MM-DD
```

- [ ] **Step 1: Write RED two-segment service tests**

Build two non-overlapping JM physical segments. Assert contract/segment on every action, no Episode state crosses segment boundary, and same input rerun yields identical event/episode ids.

- [ ] **Step 2: Write RED warm-up/prefix tests**

Request `since` in the middle of a physical segment. Service must load from true segment start so EMA/N state equals a full-prefix evaluation, but response must suppress actions before requested `since`. Evaluate the same prefix inside a longer `through` and require identical events inside the prefix.

- [ ] **Step 3: Write RED terminal-session tests using the existing TradingSession resolver**

Composition may call the existing Market session resolver to obtain the final trading-day window. Missing/ambiguous session identity must raise `JDJ_STRATEGY_SESSION_IDENTITY_INVALID`; do not infer 15:00 from a hardcoded string.

- [ ] **Step 4: Write RED API capability tests**

```text
jm + actual_dominant + 1m → accepted
jm + actual_dominant + 5m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
rb + actual_dominant + 1m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
continuous → 422 invalid request
segment/session source unavailable → typed 409
```

- [ ] **Step 5: Implement `JdjStrategyReplayService`**

Use `ActualDominantResearchSegmentLoader`; do not query `MainContractMap` directly. Construct `bars_remaining_in_trading_day` from validated session/bar identity. Historical reference multiplier must come from trusted project metadata/reference, never a guessed literal inside strategy code. Reference cost/margin are explicitly excluded per profile.

- [ ] **Step 6: Add response DTOs**

Expose action/episode/profile identity, primary/supporting setup, contract/segment, direction, decision/effective time, reference price, qty/post-qty, stop, target, R:R, reason and `reference_execution=true`. Do not expose fake “actual commission” or “actual PnL”.

- [ ] **Step 7: Wire composition/routes and run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS; existing Candidate `/jdj/history` remains unchanged.

- [ ] **Step 8: Commit**

```bash
git add services/quant-api/app/research/jdj_strategy services/quant-api/app/research/composition.py services/quant-api/app/research/historical_overlay_api.py services/quant-api/app/schemas/research_overlays.py services/quant-api/tests
git commit -m "feat(research): add JDJ JM reference replay"
```

---

### Task 6: Add Separate `日进斗金策略` Market Overlay

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
- Produces overlay id `jdj_strategy`, distinct from current JDJ Candidate overlay.

- [ ] **Step 1: Write RED marker projection tests**

Mapping:

```text
LONG ENTRY  → ▲
SHORT ENTRY → ▼
ADD         → ＋
REDUCE      → －
EXIT        → ×
```

Hover must include episode/setup, supporting setups, contract, decision/effective time, qty, stop, target, R:R, reason and “参考回放”。

- [ ] **Step 2: Write RED identity/capability tests**

```text
jm/actual_dominant/1m → load accepted profile
1m → 5m → immediately clear strategy markers and show unavailable
5m → 1m → reload without duplicate ids
prepend older bars → event-id dedupe
stale response after identity change → ignored
```

- [ ] **Step 3: Implement API/types/marker utility**

No strategy formula in TypeScript.

- [ ] **Step 4: Implement independent `useHistoricalStrategyMarkers`**

Reuse the generation/full-identity stale-response pattern from research markers, but keep separate state/maps/errors.

- [ ] **Step 5: Wire `chart.vue` with minimal logic**

Do not move strategy calculations into the already-large chart component. Candidate and Strategy selections remain visually distinct.

- [ ] **Step 6: Extend Playwright and run Web checks**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: all exit 0.

- [ ] **Step 7: Commit**

```bash
git add apps/quant-web
git commit -m "feat(web): show JDJ JM strategy replay"
```

---

### Task 7: Add Streaming Evaluator and Prove Batch/Streaming Parity

**Files:**
- Create: `services/quant-api/app/strategy_kernel/jdj/streaming.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py`
- Modify shared N modules only where a small explicit state object is required; no formula change.

**Interfaces:**

```python
@dataclass(slots=True)
class JdjStreamingEvaluator:
    # initialized for one physical segment
    ...

    def push_1m(self, bar: CanonicalBar) -> tuple[JdjTriggerEvent, ...]: ...
    def push_5m(self, bar: CanonicalBar) -> None: ...
    def reset_segment(self, *, contract: str, segment_start_trading_day: date) -> None: ...
```

Exact method naming may be adjusted once current reducer state is factored, but there must be one explicit stateful object and no per-Bar full-prefix recomputation.

- [ ] **Step 1: Write RED stream-vs-batch parity tests before implementing streaming**

For each frozen segment fixture:

1. Run existing batch `build_jdj_context_series` + all three reducers.
2. Push the same completed 1m/5m bars in chronological order into streaming evaluator.
3. Compare `project_jdj_trace` primitives from Task 0 exactly.

Include a fixture spanning two trading days inside one physical contract to prove EMA/N segment state survives the day change while JDJ day-scoped state resets.

- [ ] **Step 2: Add a segment-change test**

After `reset_segment`, no EMA/N/JDJ state from the previous contract may influence the first events of the next segment.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py
```

- [ ] **Step 4: Refactor existing reducers only enough to expose reusable state transitions**

Prefer extracting pure “advance one fact” reducers from the existing batch loops and making batch functions call those transitions. Do not maintain separate batch and streaming formulas.

- [ ] **Step 5: Implement streaming EMA/N/JDJ state**

EMA must preserve the existing SMA-window seed and 6-digit emitted rounding semantics. N swing/pattern/structure and JDJ armed states must preserve exact strict-before timing.

- [ ] **Step 6: Prohibit O(n²) fallback explicitly**

Add a test spy/counter or code-review assertion showing `push_1m` does not invoke full `evaluate_n_structure_segment` over all historical bars on every 1m Bar.

- [ ] **Step 7: Run golden + streaming + existing research tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py \
  services/quant-api/tests/research/test_jdj_research_service.py
```

Expected: PASS.

- [ ] **Step 8: Commit and stop for Phase A independent Review**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): add JDJ streaming parity evaluator"
```

Reviewer must explicitly check future/same-boundary leakage, day-vs-segment reset, EMA rounding drift and formula duplication before Phase B.

---

### Task 8: Phase B — Integrate the Same Kernel Into RQAlpha Workbench

**Prerequisite Gate:**

```bash
test -d services/quant-api/app/backtest
```

Expected: exit 0. If absent, stop. Implement the already-approved RQAlpha Workbench Plan in its own task/worktree, integrate it to `develop`, then start Task 8 in a fresh branch/worktree.

**Files:**
- Create: `services/quant-api/app/backtest/execution_identity_schedule.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py`
- Modify: `services/quant-api/app/backtest/strategies/registry.json`
- Modify existing run/result normalization only for JDJ attribution
- Test: `services/quant-api/tests/backtest/test_jdj_execution_identity_schedule.py`
- Test: `services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py`

**Interfaces:**

Schedule semantic payload:

```json
{
  "schema_version": 1,
  "strategy_id": "jdj_intraday_futures_v1",
  "profile_id": "jdj_jm_1m_v1",
  "symbol": "jm",
  "series_kind": "actual_dominant",
  "mapping_source": "MarketDataService/ActualDominantResearchSegmentLoader",
  "trading_day_start": "2026-08-01",
  "trading_day_end": "2026-08-20",
  "days": {
    "2026-08-20": {
      "contract": "JM2609",
      "terminal_bar_end": "2026-08-20T15:00:00+08:00"
    }
  }
}
```

- [ ] **Step 1: Write RED schedule-source tests**

Use a fake `ActualDominantResearchSegmentLoader`/session resolver, not fake raw MainContractMap rows. Require day→contract coverage, terminal identity, deterministic ordering and fail-closed missing/overlap behavior. Non-trading calendar days are absent and do not count as missing schedule rows.

- [ ] **Step 2: Implement schedule generation in the local sidecar parent process**

The sidecar may read project identity/catalog facts through existing read paths; the child RQAlpha process receives only the resulting JSON. Child env must still omit DB/Redis/project credentials. Schedule contains no price bars.

- [ ] **Step 3: Write RED fake-RQAlpha adapter tests**

Required:

```text
Bundle bar contract must match schedule contract before action
Bundle Bar → in-memory CanonicalBar → JdjStreamingEvaluator
ENTRY/ADD use futures open APIs; REDUCE/EXIT close only existing simulated exposure
completed-bar decision is configured with matching_type=next_bar
signal=false
no MarketDataService/DB/Canonical OHLCV access inside child adapter
missing/mismatched schedule → fail closed
research_only=true / formal_evidence=false / promotion_eligible=false
```

Use fake order/account/instrument objects; unit tests do not import/start the commercial runtime.

- [ ] **Step 4: Revalidate Entry/Add at RQAlpha fill boundary**

Adapter must respect the admissible price bound. For a LONG, use a bounded limit/open mechanism or cancel when the available next-bar reference is above the max admissible price; SHORT symmetric. It may not accept a gap that makes R:R <2 or planned risk exceed cap.

- [ ] **Step 5: Implement session terminal guard from schedule**

Do not hardcode 15:00. Adapter uses the schedule’s terminal identity and profile lead bars to stop new Entry/Add and flatten before terminal boundary.

- [ ] **Step 6: Add strategy/profile to fixed registry**

Do not expose policy-frozen fields as arbitrary Web parameters. Workbench capital/cost/slippage remains governed by its existing contract.

- [ ] **Step 7: Add attribution using RQAlpha fill/account facts**

Episode result includes profile, contract, primary/supporting setup, entry/exit, add/reduce counts, exit reason, gross/cost/net PnL, return_R, MFE_R, MAE_R and holding bars. Do not create a second PnL calculator if RQAlpha already provides the facts.

- [ ] **Step 8: Run fake tests only**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/backtest/test_jdj_execution_identity_schedule.py \
  services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

Expected: PASS. Do not run real Bundle.

- [ ] **Step 9: Commit**

```bash
git add services/quant-api/app/backtest services/quant-api/tests/backtest
git commit -m "feat(backtest): adapt shared JDJ JM strategy to RQAlpha"
```

---

### Task 9: Canonical Closeout and Full Verification

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/RQALPHA_RESEARCH_BACKTEST.md` only if Task 8 exists
- Modify: `TESTING.md`
- Do not update `STATUS.md` unless a separate status action records an exact develop RC.

- [ ] **Step 1: Update the three distinct identities**

```text
JDJ Candidate Research
JDJ Historical Reference Strategy Replay
RQAlpha JDJ Backtest (only if Task 8 completed)
```

All remain research-only.

- [ ] **Step 2: Document one-way dependencies and reference-vs-RQAlpha execution semantics**

Make explicit that Historical Replay is deterministic reference execution, not historical real fills; RQAlpha Bundle is the simulated fill/cost authority for backtests.

- [ ] **Step 3: Narrow RQAlpha data boundary only if adapter exists**

Allow validated dominant/session identity schedule in the parent sidecar; continue to prohibit Canonical OHLCV and DB credentials inside the child runner.

- [ ] **Step 4: Add exact verification commands to `TESTING.md`**

Do not add real Bundle smoke to automatic commands.

- [ ] **Step 5: Run targeted strategy/research tests**

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

If Task 8 completed, append both fake backtest tests.

- [ ] **Step 6: Run backend baseline, Ruff and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/market_data
```

Expected: all exit 0.

- [ ] **Step 7: Run Web verification**

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

Only intended task files may be dirty before final commit.

- [ ] **Step 9: Independent whole-branch Review**

Reviewer must explicitly inspect:

```text
future/same-boundary leakage
batch/streaming drift
day-vs-segment reset
cross-contract Episode leakage
float use in financial semantics
Entry gap R:R violation
intrabar fill reintroduction
session-terminal leakage
direct MainContractMap self-selection
Canonical OHLCV in RQAlpha child
duplicated strategy formulas
unsupported-period fallback
parameter-search/promotion scope creep
```

- [ ] **Step 10: Commit canonical closeout**

```bash
git add PROJECT_SOURCE.md AGENTS.md docs/ARCHITECTURE.md DECISIONS.md TESTING.md
if test -d services/quant-api/app/backtest; then git add docs/RQALPHA_RESEARCH_BACKTEST.md; fi
git commit -m "docs: define shared JDJ strategy boundaries"
```

---

## Integration and Gates

```text
fresh develop
→ Lane 3 task worktree/branch
→ Tasks 0–7
→ Phase A independent Review
→ user reviews exact diff/results
→ integrate Phase A to develop

RQAlpha Workbench prerequisite not present?
→ STOP Phase B

Workbench later integrated to develop
→ fresh Task 8 branch/worktree
→ fake adapter tests
→ Task 9 verification + independent Review
→ user decides integration develop
```

Allowed by this Plan: repository code/tests/docs and deterministic read-only fixtures.

Not authorized:

```text
real RQAlpha Bundle smoke
parameter sweep
JM profitability conclusion
prospective OOS consumption
main/tag/release
Runtime promotion/switch
Alert/PushPlus
Canonical/DB/Redis writes
real orders
```

第一笔真实 JM RQAlpha run 是实现后的独立 Gate；首先验证 contract identity、batch/streaming causality、next-bar execution、risk/episode behavior 和 costs，不用于选参数或宣称盈利。
