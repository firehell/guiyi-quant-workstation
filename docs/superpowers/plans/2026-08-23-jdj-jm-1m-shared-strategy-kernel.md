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
- Entry/Add 使用 decision 时已知的 admissible boundary 形成只对下一根 1m Bar 有效的 Limit Intent；普通 REDUCE/EXIT 使用 completed-Bar decision + next-Bar market/reference-open。不得实现猜测性 intrabar stop/target。
- 不接 Alert、PushPlus、Execution Review、Runtime 或真实订单账户。
- 本 Plan 不授权真实 RQAlpha Bundle smoke；真实回测另行 Gate。
- 不发布 main/tag，不做 Runtime promotion。

## Execution Phases

本 Plan 分两阶段，Codex 不得在一次会话中无条件跑到底：

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

**Interfaces:** Produces immutable primitive expected projections used after module moves. Does not change production imports or formulas.

- [ ] **Step 1: Inventory every production import that will move**

```bash
rg 'app\.research\.(n_structure\.n_structure_|jdj\.jdj_(policy|context|events|trend_follow|trend_reentry|key_level_breakout))' \
  services/quant-api/app services/quant-api/tests
```

Keep the output in Codex task notes as the migration checklist.

- [ ] **Step 2: Create deterministic test-only fixture builders**

Copy only small `_bar`/context construction helpers needed from current tests into `tests/strategy_kernel/fixtures.py`. Do not import one test module from another.

- [ ] **Step 3: Freeze N primitives**

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
            (s.epoch, s.kind.value, s.observed_at.isoformat())
            for s in trace.structures.snapshots
        ],
    }
```

Use existing outside-reset, same-epoch pivot and normal trend scenarios. Run once on current code and paste the literal primitive results into expected constants.

- [ ] **Step 4: Freeze JDJ primitives**

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

Freeze literal expectations for Trend Follow success/ambiguity, Reentry success/failed reaction and Key Level success/failed retest.

- [ ] **Step 5: Verify baseline**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py
```

Expected: PASS before production moves.

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/tests/strategy_kernel
git commit -m "test(strategy): freeze N and JDJ candidate golden facts"
```

---

### Task 1: Move the Pure N Structure Kernel Without Semantic Change

**Files:** Move five pure N modules; update all imports; test golden + current N/JDJ consumers.

**Interfaces:** unchanged `NStructurePolicy`, `NSwingPivot`, `NStructureKind`, `NStructureSnapshot`, `NStructureSegmentTrace`, `evaluate_n_structure_segment` under `app.strategy_kernel.n_structure`.

- [ ] **Step 1: `git mv` the five exact modules**; do not copy parallel definitions.
- [ ] **Step 2: Fix internal imports** to `app.strategy_kernel.n_structure`; keep `CanonicalBar` as normalized value shape.
- [ ] **Step 3: Update all Research/CLI/test consumers** so `research → strategy_kernel` only.
- [ ] **Step 4: Verify old imports are gone**

```bash
rg 'app\.research\.n_structure\.n_structure_(policy|pattern|swing|state|segment)' services/quant-api/app services/quant-api/tests
```

Expected: no active import references.

- [ ] **Step 5: Run parity/current tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_jdj_context.py
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/guiyi_cli services/quant-api/tests
git commit -m "refactor(strategy): move pure N structure kernel"
```

---

### Task 2: Move the Pure JDJ Candidate Kernel and Keep Golden Identity

**Files:** Move six JDJ pure modules; modify Research/validation/robustness/convergence/overlay/CLI/tests.

**Interfaces:** unchanged Candidate dataclasses and `reduce_jdj_trend_follow`, `reduce_jdj_trend_reentry_6`, `reduce_jdj_key_level_breakout` under `app.strategy_kernel.jdj`.

- [ ] **Step 1: `git mv` the six exact modules**; no event-id/policy/dataclass/formula edits.
- [ ] **Step 2: Update internal imports** to Shared N/JDJ paths; kernel must not import `app.research`.
- [ ] **Step 3: Update all consumers**, including robustness/convergence, to the moved event classes.
- [ ] **Step 4: Verify old imports are gone**

```bash
rg 'app\.research\.jdj\.jdj_(policy|context|events|trend_follow|trend_reentry|key_level_breakout)' services/quant-api/app services/quant-api/tests
```

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
    historical_reference_start_equity: Decimal
    historical_reference_cost_model: str
    historical_reference_margin_check: bool
    entry_limit_valid_bars: int

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

Functions:

```text
load_jdj_strategy_policy()
load_jdj_strategy_profile(profile_id)
resolve_candidate_conflict(events)
resolve_structural_stop(selection, context)
resolve_target_price(direction, entry_reference, known_levels)
admissible_entry_boundary(stop, target, minimum_reward_risk)
calculate_reference_quantity(equity, admissible_boundary, stop, instrument, profile)
authorize_entry(...)
```

- [ ] **Step 1: Write RED exact-contract tests**

Assert policy-vs-profile separation exactly. Require profile fields `historical_reference_start_equity=1000000` and `entry_limit_valid_bars=1`. Unknown/missing/extra/drifted JSON fails closed.

- [ ] **Step 2: Write RED conflict/target/stop tests**

```text
same-direction key-level + reentry + trend-follow → one selection, primary=key-level
LONG + SHORT → AMBIGUOUS_DIRECTION
no favorable known target → TARGET_UNAVAILABLE
structural stop on wrong side → context invalid
```

- [ ] **Step 3: Write RED R:R/boundary tests**

```python
boundary = (target + Decimal("2") * stop) / Decimal("3")
```

Verify LONG/SHORT symmetry and exact Decimal R:R=2 at the boundary.

- [ ] **Step 4: Write RED sizing tests**

Use concrete equity, 0.5% base risk and multiplier fixture. Quantity uses boundary as worst allowed price. Missing/non-positive multiplier fails closed. Trusted margin facts constrain quantity only when provided.

- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
```

- [ ] **Step 6: Implement exact JSON loaders using `app.core.exact_json_contract`**; no policy defaults.
- [ ] **Step 7: Implement conflict/stop/target/boundary/sizing with Decimal only**.
- [ ] **Step 8: Run green and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py
git add data/strategy_policies data/strategy_profiles services/quant-api/app/strategy_kernel/jdj services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): freeze JDJ JM 1m strategy contract"
```

---

### Task 4: Implement TradeEpisode, One-Bar Entry/Add Limits, Management and Daily/Session Risk

**Files:**
- Create: `services/quant-api/app/strategy_kernel/jdj/execution.py`
- Create: `services/quant-api/app/strategy_kernel/jdj/engine.py`
- Create: `services/quant-api/app/research/jdj_strategy/models.py`
- Create: `services/quant-api/app/research/jdj_strategy/replay.py`
- Test: `services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py`

**Interfaces:**

```python
class JdjActionKind(StrEnum):
    ENTRY_INTENT = "entry_intent"
    ENTRY = "entry"
    ADD_INTENT = "add_intent"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    REJECTED_CANDIDATE = "rejected_candidate"
    DAILY_PAUSE = "daily_pause"
    DAILY_STOP = "daily_stop"

@dataclass(frozen=True, slots=True)
class PendingLimitIntent:
    source_event_ids: tuple[str, ...]
    direction: JdjDirection
    limit_price: Decimal
    quantity: int
    decision_at: datetime
    valid_bars_remaining: int
    action_kind: JdjActionKind

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
    pending_limit: PendingLimitIntent | None
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

- [ ] **Step 1: Write RED one-Bar limit reference tests**

For LONG intent at limit 100:

```text
next open 99  → fill 99, fill_basis=better_open
next open 101 and low 99.5 → fill 100, fill_basis=limit_touch
next low 100.5 → no fill; after that one Bar intent expires
```

SHORT symmetric. No Episode exists until actual reference fill. Intent never survives into a second following Bar.

- [ ] **Step 2: Write RED Episode/source-id tests**

Filled ENTRY creates deterministic `episode_id`; all source ids are consumed. Re-presenting the same source event cannot create another Entry/Add.

- [ ] **Step 3: Write RED completed-Bar partial-profit tests**

```text
LONG close < target → no reduce
LONG close >= target → REDUCE decision
next same-segment open → reference reduce
10 lots × 0.40 → 4 reduced, 6 remain
2 lots × 0.40 → floor=0, no fake reduce, partial_profit_taken=false
```

No Bar-high target fill.

- [ ] **Step 4: Write RED profitable-add tests**

ADD source must be a new full `jdj_trend_follow_1m_candidate_v1` event after profitable partial exit. First/second add accepted subject to one-Bar limit/risk; third, losing Episode, repeated source id rejected. `floor(current_qty×0.25)` only.

- [ ] **Step 5: Write RED completed-Bar exit tests**

Close crossing protective stop/EMA or losing strict-prior 5m trend creates EXIT decision; next legal Bar market/reference-open. No intrabar stop assertion.

- [ ] **Step 6: Write RED daily-risk tests**

With `start_equity=100000`:

```text
99499 → DAILY_PAUSE
pause consumes exactly 15 subsequent in-session 1m frames
99000 → DAILY_STOP + JM V1 EXIT decision + stopped_for_day=true
new trading day → reset pause/stop
```

- [ ] **Step 7: Write RED session-terminal tests**

`bars_remaining_in_trading_day=1` forbids new Entry/Add. Existing Episode emits `SESSION_FLATTEN` so the final legal Bar open can close. Intermediate breaks never flatten.

- [ ] **Step 8: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py
```

- [ ] **Step 9: Implement immutable reducer/reference execution**

Every action records episode/source ids, decision/effective bar, contract/segment, qty/post-qty, stop/target, R:R, risk, reason and fill basis. High/low is permitted only to determine whether the already-existing next-Bar limit intent could fill; never to infer a same-Bar stop/target order.

- [ ] **Step 10: Run green and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_contract.py \
  services/quant-api/tests/strategy_kernel/test_jdj_strategy_execution.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py
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

- [ ] **Step 1: Write RED two-segment tests**

Assert contract/segment on every action, no state crossing segment boundary and deterministic event/episode ids.

- [ ] **Step 2: Write RED warm-up/prefix tests**

Request `since` mid-segment. Compute from true segment start but suppress pre-`since` outputs. Same prefix inside a longer `through` must be identical.

- [ ] **Step 3: Write RED terminal-session tests using existing TradingSession resolver**

Missing/ambiguous terminal identity → `JDJ_STRATEGY_SESSION_IDENTITY_INVALID`; no hardcoded 15:00.

- [ ] **Step 4: Write RED reference-account tests**

Profile supplies `historical_reference_start_equity=1000000`, cost model excluded, margin check disabled. Multiplier comes from trusted Catalog/reference source. Response marks `reference_execution=true`; it must not label reference cost/margin/PnL as real or RQAlpha facts.

- [ ] **Step 5: Write RED API capability tests**

```text
jm + actual_dominant + 1m → accepted
jm + actual_dominant + 5m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
rb + actual_dominant + 1m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
continuous → 422 invalid request
segment/session unavailable → typed 409
```

- [ ] **Step 6: Implement service**

Use `ActualDominantResearchSegmentLoader`; do not query `MainContractMap` directly. Construct bars-remaining identity from validated session/bar coverage. Reference multiplier is sourced, not hardcoded in strategy code.

- [ ] **Step 7: Add DTOs and routes**

Expose action/episode/profile identity, primary/supporting setup, contract/segment, direction, decision/effective bar, reference price, qty/post-qty, stop, target, R:R, reason, fill basis and `reference_execution=true`. Existing Candidate `/jdj/history` remains unchanged.

- [ ] **Step 8: Run tests and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
git add services/quant-api/app/research/jdj_strategy services/quant-api/app/research/composition.py services/quant-api/app/research/historical_overlay_api.py services/quant-api/app/schemas/research_overlays.py services/quant-api/tests
git commit -m "feat(research): add JDJ JM reference replay"
```

---

### Task 6: Add Separate `日进斗金策略` Market Overlay

**Files:** Web paths listed in File Structure.

**Interfaces:** overlay id `jdj_strategy`, distinct from current Candidate overlay.

- [ ] **Step 1: Write RED marker tests**: ENTRY `▲/▼`, ADD `＋`, REDUCE `－`, EXIT `×`; hover includes episode/setup/supporting setup/contract/decision/effective bar/qty/stop/target/R:R/reason/“参考回放”。Unfilled intents do not render as fills.
- [ ] **Step 2: Write RED capability/identity tests**: `jm/actual_dominant/1m` loads; switching to unsupported period clears immediately; switching back reloads; prepend dedupes; stale response ignored.
- [ ] **Step 3: Implement API/types/marker utility** with no strategy formula in TypeScript.
- [ ] **Step 4: Implement independent `useHistoricalStrategyMarkers`**, reusing generation/full-identity stale protection but separate state.
- [ ] **Step 5: Wire `chart.vue` minimally**; do not calculate strategy in the large component.
- [ ] **Step 6: Run Web checks**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

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
- Modify shared N/JDJ modules only to extract reusable state transitions; formula outputs must remain golden-identical.

**Interfaces:** one explicit stateful evaluator for one physical segment. Exact method names may follow the refactor, but it must accept completed 1m/5m facts incrementally and emit the same Candidate primitive projection as batch.

- [ ] **Step 1: Write RED stream-vs-batch tests** for each Task 0 frozen segment.
- [ ] **Step 2: Add a same-boundary strict-before test**: a newly completed 5m fact with end equal to the current 1m boundary cannot affect the current 1m decision; it becomes visible only for the next 1m decision.
- [ ] **Step 3: Add a two-trading-day same-contract test**: EMA/N segment state survives trading-day change while JDJ day-scoped/Execution state resets.
- [ ] **Step 4: Add segment-reset test**: no prior contract state after reset.
- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py
```

- [ ] **Step 6: Extract pure single-step transitions from existing batch loops** and make batch + streaming call the same transitions. Do not maintain two formulas.
- [ ] **Step 7: Preserve exact EMA seed/rounding and N/JDJ state**; no per-Bar full-prefix recomputation.
- [ ] **Step 8: Add a regression guard against O(n²) fallback** using a spy/counter/code-boundary assertion that streaming `push` does not call the full batch segment evaluator on every Bar.
- [ ] **Step 9: Run golden + streaming + Research tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/strategy_kernel/test_n_structure_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_golden_parity.py \
  services/quant-api/tests/strategy_kernel/test_jdj_streaming_parity.py \
  services/quant-api/tests/research/test_jdj_research_service.py
```

- [ ] **Step 10: Commit and stop for Phase A independent Review**

```bash
git add services/quant-api/app/strategy_kernel services/quant-api/tests/strategy_kernel
git commit -m "feat(strategy): add JDJ streaming parity evaluator"
```

Reviewer checks future/same-boundary leakage, day-vs-segment reset, EMA rounding drift and formula duplication before Phase B.

---

### Task 8: Phase B — Integrate the Same Kernel Into RQAlpha Workbench

**Prerequisite Gate:**

```bash
test -d services/quant-api/app/backtest
```

Expected: exit 0. If absent, stop. Implement the approved RQAlpha Workbench Plan separately, integrate it to `develop`, then start Task 8 in a fresh branch/worktree.

**Files:**
- Create: `services/quant-api/app/backtest/execution_identity_schedule.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_rqalpha_adapter.py`
- Create: `services/quant-api/app/backtest/strategies/jdj_intraday_futures_v1.py`
- Modify: `services/quant-api/app/backtest/strategies/registry.json`
- Modify existing result normalization only for JDJ attribution
- Test: `services/quant-api/tests/backtest/test_jdj_execution_identity_schedule.py`
- Test: `services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py`

**Interfaces:** schedule semantic payload:

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

- [ ] **Step 1: Write RED schedule tests** using fake validated loader/session resolver, not raw MainContractMap rows. Require day→contract + terminal identity, deterministic ordering and fail-closed coverage; non-trading days are absent, not errors.
- [ ] **Step 2: Implement schedule generation in sidecar parent process**. Parent may use existing read paths; child receives JSON only, no DB/Redis credentials or Canonical OHLCV.
- [ ] **Step 3: Write RED fake-RQAlpha stream tests**: Bundle Bar → in-memory domain Bar → shared streaming evaluator; schedule contract match required; `frequency=1m`, `matching_type=next_bar`, `signal=false`; child cannot load Canonical/DB.
- [ ] **Step 4: Write RED one-Bar LimitOrder lifecycle tests**: ENTRY/ADD submits limit at admissible boundary after decision; if still open at the very next `handle_bar`, call `cancel_order`; never leave the order into a second following Bar. Fill callback creates/updates Episode using actual RQAlpha price/time.
- [ ] **Step 5: Write RED management-order tests**: completed-Bar REDUCE/EXIT submits market close action for `next_bar`; no synthetic stop order; no close beyond current simulated position.
- [ ] **Step 6: Implement session terminal guard from schedule**; no hardcoded 15:00.
- [ ] **Step 7: Register strategy/profile without exposing policy-frozen fields as arbitrary Web parameters**.
- [ ] **Step 8: Add attribution using RQAlpha fill/account facts**, not a duplicate PnL calculator.
- [ ] **Step 9: Run fake tests only**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/backtest/test_jdj_execution_identity_schedule.py \
  services/quant-api/tests/backtest/test_jdj_rqalpha_adapter.py
```

- [ ] **Step 10: Commit**

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

- [ ] **Step 1: Update distinct identities**: Candidate Research / Historical Reference Strategy Replay / RQAlpha Backtest only if Task 8 completed. All remain research-only.
- [ ] **Step 2: Document one-way dependencies and reference-vs-RQAlpha execution semantics**.
- [ ] **Step 3: Narrow RQAlpha data boundary only if adapter exists**: parent may generate validated dominant/session identity schedule; child still receives no Canonical OHLCV/DB credentials.
- [ ] **Step 4: Add exact strategy verification commands to `TESTING.md`**, excluding real Bundle smoke.
- [ ] **Step 5: Run targeted backend tests**

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

- [ ] **Step 6: Run backend baseline, Ruff, Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/strategy_kernel services/quant-api/app/research services/quant-api/app/market_data
```

- [ ] **Step 7: Run Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 8: Run engineering checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

- [ ] **Step 9: Independent whole-branch Review** must inspect:

```text
future/same-boundary leakage
batch/streaming drift
day-vs-segment reset
cross-contract Episode leakage
float use in financial semantics
admissible-limit R:R violation
limit-order expiry drift
intrabar stop/target reintroduction
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

RQAlpha Workbench prerequisite absent
→ STOP Phase B

Workbench later integrated to develop
→ fresh Task 8 branch/worktree
→ fake adapter tests
→ Task 9 verification + independent Review
→ user decides integration develop
```

Allowed: repository code/tests/docs and deterministic read-only fixtures.

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

第一笔真实 JM RQAlpha run 是实现后的独立 Gate；首先验证 contract identity、batch/streaming causality、LimitOrder 生命周期、management next-bar execution、risk/episode behavior 和 costs，不用于选参数或宣称盈利。
