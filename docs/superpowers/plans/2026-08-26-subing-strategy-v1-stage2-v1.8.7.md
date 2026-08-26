# SuBing Strategy V1 Stage 2 and v1.8.7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to execute this plan task-by-task. Every task follows RED → GREEN → REFACTOR, and every repository claim requires fresh command output.

**Goal:** Extend the integrated SuBing Strategy V1 Historical Projection into one completed-Live active60 strategy product, directly replace the old SuBing entry-signal Alert surface with exact Strategy Action Events, expose live/current Web projections, and prepare the complete result for release `v1.8.7` without executing any production migration, Runtime promotion, real notification, or release mutation inside the implementation task.

**Architecture:** Preserve one causal semantic owner. Refactor the existing batch EMA/MACD, SuBing Factor, Lifecycle, and 15m Strategy reducer into append-only step APIs; make Historical replay call those APIs; add an in-memory active60 runtime evaluator inside the existing Alert Runtime process; persist only immutable scoped Strategy Action Events; reconstruct current Strategy state from market facts rather than Event history; reconcile Live Events with Historical Actions by stable `action_id`.

**Tech Stack:** Python 3.13+, frozen dataclasses, `Decimal`, FastAPI/Pydantic, SQLAlchemy/PostgreSQL/Alembic, Redis Pub/Sub, Canonical Parquet through `MarketDataService`, Vue 3/Vite/TypeScript/Naive UI/Lightweight Charts, pytest, Ruff, Mypy, Vitest, Playwright.

**Approved Spec:** [`2026-08-26-subing-strategy-v1-stage2-v1.8.7-design.md`](../specs/2026-08-26-subing-strategy-v1-stage2-v1.8.7-design.md)

**Planning base:** `develop@357a67923b9f5f8f15e9507677f34bd1e706ab9d` (merged Design PR `#227`).

---

## 1. Non-negotiable boundaries

- This is **Lane 3**: strategy causality, live state, production schema, notification, Runtime, and release identity.
- Repository implementation may proceed only after this Plan is approved.
- Implementation branch/worktree must start from the then-latest `origin/develop` containing the approved Spec and this Plan.
- The public Strategy identity remains exactly `actual_dominant + 15m`.
- 1m and 5m are internal inputs only; neither may produce public Strategy Actions or Events.
- Historical and Live must use one step engine. Do not copy formulas into Alert Runtime or Web.
- All normal decisions use completed 15m data; a pending Action becomes effective only from the exact first completed 1m Bar of the next actual same-contract 15m interval.
- No later 1m open, decision-Bar close, synthetic timestamp, or cross-contract Bar may substitute for a missing first 1m.
- Every physical rank1 segment starts and ends flat. No Factor state, Pivot, Lifecycle opportunity, pending Action, position, or Episode crosses a segment boundary.
- Runtime calculates active60 independently of Alert Scope. `scope_products` controls only Event creation and PushPlus.
- Startup restores state but never backfills Event history or sends delayed notifications.
- `AlertEvent` is notification history, not Strategy position authority.
- Direct replacement is intentional: old `subing_entry_signal_v1` Event rows are deleted; no archive, compatibility reader, dual Rule, replay, or downgrade is added.
- HTDY Rule, Scope, Events, notification routing, and seven-frequency behavior must remain unchanged.
- SuBing Strategy PushPlus uses owner only, one attempt, no Topic, retry, queue, replay, backfill, or fallback.
- `auto_order=false` remains unchanged. No account, order, position sizing, commission, slippage, margin, leverage, equity, or automatic trading path.
- Do not execute production migration `20260826_0042`.
- Do not mutate production Scope.
- Do not start or switch Runtime.
- Do not send a real canary or natural notification.
- Do not create a release PR, merge `main`, create `v1.8.7`, or publish a GitHub Release until their separate external-operation Gate is granted.

---

## 2. Codex execution card

| Field | Value |
|---|---|
| Lane | Lane 3 — strategy causality / live Runtime / migration / notification / release |
| Entry | Codex App |
| Model | Sol |
| Reasoning | High |
| Session | New implementation session; separate exact-head Review session; separate release session |
| Plan | Plan-then-execute |
| Workspace | New task worktree from latest `origin/develop` |
| Task branch | `feature/subing-strategy-v1-stage2-v1.8.7` |
| Integration target | `develop` |
| Automatic task → develop | Not allowed |
| PR | Required |
| Human repository Gate | `允许集成 develop` |
| Release workspace | New `release/v1.8.7` worktree only after repository integration and release-candidate approval |
| External Gates | Release; production migration; Runtime promotion/natural notifications; owner canary |
| Forbidden worktrees | `main` and current detached Runtime worktrees |

Worktree lifecycle:

```text
origin/develop
→ feature/subing-strategy-v1-stage2-v1.8.7 worktree
→ implementation PR to develop
→ independent exact-head Review
→ human 允许集成 develop
→ merge confirmed in develop
→ remove task worktree and merged task branch

later, under a new release Gate:
develop
→ release/v1.8.7 worktree
→ release PR to main
→ human 允许发布 main/tag
```

---

## 3. Target package map

### Existing packages to refactor

```text
packages/quant-core/guiyi_quant/indicators/
├── ema.py
├── macd.py
├── models.py
└── __init__.py

services/quant-api/app/market_data/
├── subing_ema_trend.py
├── subing_research.py
├── subing_lifecycle.py
└── subing_strategy/
    ├── contracts.py
    ├── engine.py
    ├── replay.py
    ├── service.py
    ├── cache.py
    └── ...
```

### New focused modules

```text
services/quant-api/app/market_data/subing_strategy/
├── stream_contracts.py       completed input and step-output contracts
├── machine.py                one incremental Strategy semantic owner
├── current_service.py        read-only Canonical + completed-Live reconstruction
└── shadow.py                 no-write shadow comparison helper

services/quant-api/app/alerts/
├── subing_strategy_runtime.py  active60 in-memory runtime evaluator
└── strategy_payload.py         exact Event payload serializer/parser
```

Do not create a generic strategy registry, adapter framework, formula DSL, worker, queue, or strategy-state repository.

---

## 4. Dependency order

```text
Task 0  workspace and baseline
  ↓
Task 1  exact Action/effective-open and stream contracts
  ↓
Task 2  incremental EMA/MACD and SuBing Factor parity
  ↓
Task 3  incremental Lifecycle parity
  ↓
Task 4  unified Strategy machine and Historical parity
  ↓
Task 5  current read-only Strategy projection
  ↓
Task 6  active60 runtime evaluator
  ↓
Task 7  migration 0042 and exact Strategy Event contracts
  ↓
Task 8  exact PushPlus message formatting
  ↓
Task 9  Alert Runtime integration and status schema v3
  ↓
Task 10 Alert HTTP and Web live/current projection
  ↓
Task 11 no-write shadow acceptance and canonical reconciliation
  ↓
Task 12 full verification, documentation, independent Review, develop Gate
  ↓
Task 13 v1.8.7 release candidate preparation under a later Gate
```

Tasks 1–12 form the implementation PR to `develop`. Task 13 is not executed in the same task branch.

---

# Task 0: Create the isolated implementation workspace and capture the baseline

**Files:** none.

- [ ] **Step 1: Fetch and verify the approved planning base.**

```bash
git fetch origin
git show --stat --oneline origin/develop
git merge-base --is-ancestor \
  357a67923b9f5f8f15e9507677f34bd1e706ab9d \
  origin/develop
```

Expected: exit `0`; the merged Stage 2 Spec and this Plan are reachable from `origin/develop`.

- [ ] **Step 2: Create the task worktree.**

```bash
git worktree add ../guiyi-subing-strategy-v1-stage2 \
  -b feature/subing-strategy-v1-stage2-v1.8.7 \
  origin/develop
cd ../guiyi-subing-strategy-v1-stage2
git status --short
git rev-parse HEAD
```

Expected: clean status.

- [ ] **Step 3: Inspect repository facts before editing.**

```bash
sed -n '1,220p' STATUS.md
sed -n '1,220p' AGENTS.md
sed -n '1,220p' docs/DEVELOPMENT.md
sed -n '1,220p' PROJECT_SOURCE.md
sed -n '1,220p' DECISIONS.md
sed -n '1,260p' \
  docs/superpowers/specs/2026-08-26-subing-strategy-v1-stage2-v1.8.7-design.md
```

Stop if active canonical contradicts the approved Spec. Do not guess through a conflict.

- [ ] **Step 4: Install locked dependencies.**

```bash
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

- [ ] **Step 5: Run the focused pre-change baseline.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
```

Record the exact counts in the implementation log. A pre-existing failure blocks implementation until it is classified.

---

# Task 1: Freeze effective-open and streaming contracts without changing Action identity

**Files:**

- Modify: `services/quant-api/app/market_data/subing_strategy/contracts.py`
- Create: `services/quant-api/app/market_data/subing_strategy/stream_contracts.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/__init__.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/cache.py`
- Modify: `services/quant-api/tests/research/subing_strategy_fixtures.py`
- Modify: `services/quant-api/tests/research/test_subing_strategy_contracts.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_stream_contracts.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_cache.py`

**Locked interfaces:**

```python
@dataclass(frozen=True, slots=True)
class Completed1mBar:
    bar: CanonicalBar

@dataclass(frozen=True, slots=True)
class Completed5mBar:
    bar: CanonicalBar

@dataclass(frozen=True, slots=True)
class Completed15mBar:
    bar: CanonicalBar

@dataclass(frozen=True, slots=True)
class AuthoritativeSegmentTerminal:
    symbol: str
    contract: str
    segment_start_trading_day: date
    terminal_bar: CanonicalBar

SubingStrategyStreamInput = (
    Completed1mBar
    | Completed5mBar
    | Completed15mBar
    | AuthoritativeSegmentTerminal
)

@dataclass(frozen=True, slots=True)
class SubingStrategyStepOutput:
    actions: tuple[SubingStrategyAction, ...]
    cancellations: tuple[SubingStrategyPendingCancellation, ...]
    state_changed: bool
```

`SubingStrategyAction` gains:

```python
effective_open_at: datetime | None
```

Rules:

```text
next_bar_open:
  effective_open_at is aware and earlier than effective_bar_end

segment_terminal_close:
  effective_open_at is null
```

`effective_open_at` is a derived fact and is **not** added to `identity_fields()`. Existing Action identity remains based on:

```text
strategy/formula/symbol/contract/segment/opportunity/kind/
decision_at/effective_bar_end/fill_basis
```

This preserves existing Stage 1 Action ids while allowing Live and Historical payload parity.

- [ ] **Step 1: Add failing contract tests.**

```python
def test_next_bar_open_requires_effective_open_at() -> None:
    with pytest.raises(SubingStrategyContractError):
        action_fixture(
            fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
            effective_open_at=None,
        )

def test_terminal_close_rejects_effective_open_at() -> None:
    with pytest.raises(SubingStrategyContractError):
        action_fixture(
            fill_basis=SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE,
            effective_open_at=aware_dt(10, 15),
        )

def test_effective_open_at_does_not_change_action_identity() -> None:
    first = action_fixture(effective_open_at=aware_dt(10, 15))
    second = action_fixture(effective_open_at=aware_dt(10, 16))
    assert first.action_id == second.action_id
```

Add stream-input tests that reject:

- wrong frequency wrapper;
- naive timestamps;
- non-normalized contracts;
- terminal Bar outside its segment;
- Boolean or arbitrary object inputs.

- [ ] **Step 2: Run tests and observe RED.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_stream_contracts.py
```

Expected: import/constructor failures.

- [ ] **Step 3: Implement immutable stream contracts and Action validation.**

Use frozen dataclasses and exact enum/frequency checks. Normalize aware times to UTC in `__post_init__`.

Do not add serialization methods that accept arbitrary dictionaries. The Event payload parser is a separate exact boundary in Task 7.

- [ ] **Step 4: Bump only the expendable cache payload schema.**

The cache path remains:

```text
<observation-root>/cache/subing-strategy-v1/
```

Change the cache envelope schema from the current version to the next integer and include `effective_open_at` in Action bytes. Old entries must parse as a cache miss/unavailable, never as authoritative facts.

Do not change `strategy_id` or `formula_version`.

- [ ] **Step 5: Run focused tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_stream_contracts.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py
```

- [ ] **Step 6: Commit.**

```bash
git add \
  services/quant-api/app/market_data/subing_strategy/contracts.py \
  services/quant-api/app/market_data/subing_strategy/stream_contracts.py \
  services/quant-api/app/market_data/subing_strategy/__init__.py \
  services/quant-api/app/market_data/subing_strategy/cache.py \
  services/quant-api/tests/research/subing_strategy_fixtures.py \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_stream_contracts.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py
git commit -m "refactor(subing): add streaming strategy contracts"
```

---

# Task 2: Add incremental EMA, MACD, EMA-trend, and SuBing Factor parity

**Files:**

- Modify: `packages/quant-core/guiyi_quant/indicators/ema.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/macd.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/models.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `services/quant-api/app/market_data/subing_ema_trend.py`
- Modify: `services/quant-api/app/market_data/subing_research.py`
- Create: `services/quant-api/tests/research/test_subing_factor_streaming.py`
- Modify: `services/quant-api/tests/test_indicator_kernel.py`
- Modify: `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
- Modify: `services/quant-api/tests/test_subing_ema_trend.py`
- Modify: `services/quant-api/tests/test_subing_research.py`

**Required incremental APIs:**

```python
@dataclass(frozen=True, slots=True)
class EmaState:
    period: int
    seed_policy: SeedPolicy
    count: int
    seed_values: tuple[float, ...]
    previous: float | None

def step_ema(
    state: EmaState,
    value: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[EmaState, IndicatorPoint]:
    ...

@dataclass(frozen=True, slots=True)
class MacdState:
    fast: EmaState
    slow: EmaState
    signal: EmaState
    ...

def step_macd(
    state: MacdState,
    close: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[MacdState, tuple[IndicatorPoint, IndicatorPoint, IndicatorPoint]]:
    ...
```

Service-specific Factor API:

```python
@dataclass(frozen=True, slots=True)
class SubingFactorStreamState:
    timeframe: BarFrequency
    contract: str
    segment_start_trading_day: date
    ...

def step_subing_factor(
    state: SubingFactorStreamState,
    bar: CanonicalBar,
) -> tuple[SubingFactorStreamState, SubingFactorResult]:
    ...
```

Batch APIs remain public, but become loops over the step APIs:

```python
def ema_series(...):
    state = initial_ema_state(...)
    for value in values:
        state, point = step_ema(state, value, ...)
```

Do the same for `macd_series`, `calculate_subing_ema_trend_series`, and `calculate_subing_factor_series`.

Do not change:

```text
EMA_VERSION
MACD_VERSION
seed_policy
histogram_scale
rounding
warm-up
invalid-input reset behavior
Subing Factor formula fields
```

- [ ] **Step 1: Write RED parity tests.**

For every prefix of a deterministic corpus:

```python
batch = calculate_subing_factor_series(
    bars[:prefix],
    timeframe=BarFrequency.M5,
    contract="JM2601",
    segment_start_trading_day=date(2026, 8, 1),
)
stream = stream_factor_results(bars[:prefix], timeframe=BarFrequency.M5)
assert stream == batch
```

Repeat for 15m.

Kernel parity must cover:

- `sma_window` EMA seed;
- invalid value reset and reseed;
- compact DIF → DEA behavior;
- MACD histogram scale `2`;
- exact rounded points;
- warm-up boundary;
- one appended future Bar not changing prior points.

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/research/test_subing_factor_streaming.py
```

- [ ] **Step 3: Implement EMA step state.**

Preserve reset semantics:

```text
invalid input
→ previous = None
→ seed window reset
→ exact invalid/warm-up IndicatorPoint reason
```

For `sma_window`, do not seed until the last `period` inputs are all finite.

- [ ] **Step 4: Implement MACD step state.**

For `sma_window`:

```text
fast EMA and slow EMA ready
→ append one compact DIF observation
→ feed only ready DIF observations into signal EMA
```

A missing/invalid close resets all dependent recursive state exactly as the current batch implementation does.

- [ ] **Step 5: Refactor series functions to delegate to steps.**

This is required. Merely adding an incremental implementation beside the old batch implementation is not sufficient because it would create two semantic owners.

- [ ] **Step 6: Implement EMA-trend and Factor stream state.**

Keep only the bounded rolling values needed for:

- EMA21;
- 5-Bar and 10-Bar regression slopes;
- previous Factor MACD relation for cross detection;
- previous volume;
- latest identity/watermark.

No state may cross a physical segment.

- [ ] **Step 7: Run focused and affected tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/research/test_subing_factor_streaming.py
```

- [ ] **Step 8: Run mutation checks for the new parity tests.**

Temporarily alter one of:

- EMA alpha;
- MACD histogram scale;
- DEA compact-DIF step;
- slope rolling window.

Confirm the parity test fails, then restore production code and rerun GREEN.

- [ ] **Step 9: Commit.**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/ema.py \
  packages/quant-core/guiyi_quant/indicators/macd.py \
  packages/quant-core/guiyi_quant/indicators/models.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/research/test_subing_factor_streaming.py \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/test_subing_research.py
git commit -m "refactor(subing): make factor calculation incremental"
```

---

# Task 3: Extract one incremental Lifecycle reducer and preserve exact trace parity

**Files:**

- Modify: `services/quant-api/app/market_data/subing_lifecycle.py`
- Modify: `services/quant-api/app/market_data/subing_lifecycle_policy.py`
- Create: `services/quant-api/tests/research/test_subing_lifecycle_streaming.py`
- Modify: `services/quant-api/tests/research/test_subing_lifecycle_causality.py`
- Modify: `services/quant-api/tests/research/test_subing_lifecycle_transitions.py`
- Modify: `services/quant-api/tests/research/test_subing_lifecycle_contracts.py`
- Modify: `services/quant-api/tests/research/subing_lifecycle_fixtures.py`

**Required API:**

```python
@dataclass(frozen=True, slots=True)
class SubingLifecycleMachineState:
    formula_version: str
    policy_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    active_opportunity: ...
    confirmed_pivots: tuple[ConfirmedPivot, ...]
    transitions: tuple[SubingLifecycleTransition, ...]
    snapshots: tuple[SubingLifecycleSnapshot, ...]
    latest_15m_factor: SubingFactorSnapshot | None
    latest_5m_bar_end: datetime | None
    latest_15m_bar_end: datetime | None
    ...

def step_subing_lifecycle_15m(
    state: SubingLifecycleMachineState,
    *,
    bar: CanonicalBar,
    factor: SubingFactorResult,
) -> SubingLifecycleMachineState:
    ...

def step_subing_lifecycle_5m(
    state: SubingLifecycleMachineState,
    *,
    bar: CanonicalBar,
    factor: SubingFactorResult,
    calibration: SubingCalibration,
    policy: SubingLifecyclePolicy,
) -> tuple[SubingLifecycleMachineState, SubingLifecycleSnapshot]:
    ...
```

For equal `bar_end`, processing order is locked:

```text
1. update completed 15m anchor
2. update completed 5m clock
3. emit confirmation/transition/snapshot
```

This matches the existing batch evaluator's ability to use the completed 15m anchor at the same boundary and permits `B_prev < confirmed_at <= B_now`.

The existing `evaluate_subing_lifecycle(...)` becomes a deterministic loop over these step functions. Do not retain a second formula loop.

- [ ] **Step 1: Add RED prefix-parity tests.**

For every prefix:

```python
batch = evaluate_subing_lifecycle(...bars[:prefix]...)
stream = stream_lifecycle(...bars[:prefix]...)
assert stream.current_snapshot == batch.current_snapshot
assert stream.transitions == batch.transitions
assert stream.confirmed_pivots == batch.confirmed_pivots
```

Fixtures must cover all four confirmation sources:

```text
formal_v1
momentum_hold
pivot_break_hold
pivot_retest_rebreak
```

Also cover:

- trigger Pivot and protective bound Pivot as distinct facts;
- same-day LOW for long and HIGH for short;
- strict `pivot.confirmed_at < confirmation_at`;
- risk/recovery;
- trading-day crossing;
- segment reset;
- future append preserving earlier transition ids.

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_lifecycle_streaming.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/research/test_subing_lifecycle_transitions.py
```

- [ ] **Step 3: Extract immutable public state and private bounded mutable builder.**

The pure public boundary returns a new frozen state. A private mutable builder may be used inside one step for performance, but it may not escape the module.

Keep current:

```text
policy_id = subing_lifecycle_v2_research_v1
formula_version = subing_lifecycle_v2_structure_binding_v1
```

because this is a behavior-preserving execution refactor. Any observed parity difference requires stopping and reviewing whether a formula version bump is necessary.

- [ ] **Step 4: Move batch loop logic into step functions.**

Do not reinterpret:

- trigger priority;
- hold count;
- retest window;
- Pivot tie policy;
- risk thresholds;
- confirmation sources;
- protective Pivot binding;
- transition reason ordering.

- [ ] **Step 5: Make the batch evaluator call the step reducer.**

Delete or inline obsolete duplicated branches after parity is green.

- [ ] **Step 6: Run focused tests and mutation checks.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_lifecycle_streaming.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/research/test_subing_lifecycle_transitions.py \
  services/quant-api/tests/research/test_subing_lifecycle_contracts.py \
  services/quant-api/tests/test_subing_lifecycle_policy.py
```

Temporarily reverse equal-boundary processing or allow `pivot.confirmed_at == confirmed_at`; confirm tests fail; restore and rerun.

- [ ] **Step 7: Commit.**

```bash
git add \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/app/market_data/subing_lifecycle_policy.py \
  services/quant-api/tests/research/test_subing_lifecycle_streaming.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/research/test_subing_lifecycle_transitions.py \
  services/quant-api/tests/research/test_subing_lifecycle_contracts.py \
  services/quant-api/tests/research/subing_lifecycle_fixtures.py
git commit -m "refactor(subing): make lifecycle evaluation incremental"
```

---

# Task 4: Build the unified Strategy machine and migrate Historical replay to exact 1m opens

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/machine.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/engine.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/replay.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/service.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/cache.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/contracts.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/__init__.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_machine.py`
- Create: `services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py`
- Modify: `services/quant-api/tests/research/test_subing_strategy_engine.py`
- Modify: `services/quant-api/tests/research/test_subing_strategy_causality.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_cache.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`

**Required state:**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyMachineState:
    symbol: str
    contract: str
    segment_start_trading_day: date
    factor_5m: SubingFactorStreamState
    factor_15m: SubingFactorStreamState
    lifecycle: SubingLifecycleMachineState
    position: SubingStrategyPosition | None
    pending_action: SubingStrategyPendingAction | None
    consumed_opportunity_ids: tuple[str, ...]
    current_episode: SubingStrategyEpisode | None
    previous_15m_bar: CanonicalBar | None
    pending_boundary_15m: ...
    watermarks: ...
```

**Boundary coordinator:**

At a shared 5m/15m `bar_end`, messages may arrive in either order. The machine must not rely on Redis publication order.

```text
buffer completed 15m fact
buffer completed 5m fact
when both exact identities are present:
  1. update 15m Factor/anchor
  2. update 5m Factor/Lifecycle
  3. project confirmations through this boundary
  4. evaluate the one 15m Strategy decision
```

A missing required companion at the next boundary is a typed product-level unavailable condition, not a partial decision.

**Historical event stream:**

Load physical-segment 1m, 5m, and 15m Canonical Bars. Merge by business time with the same boundary coordinator. Historical ordinary Actions use:

```text
reference_price    = exact first 1m open of next actual 15m interval
effective_open_at  = first 1m interval start
effective_bar_end  = containing 15m interval end
```

The containing 15m Bar's `open` must equal the first 1m `open`; mismatch fails closed as source-identity inconsistency.

- [ ] **Step 1: Write RED machine tests.**

```python
def test_pending_open_applies_on_exact_first_completed_1m() -> None:
    state = state_with_pending_open(...)
    output = step_subing_strategy_machine(
        state,
        Completed1mBar(first_bar_of_next_15m(open="100")),
    )
    assert output.actions[0].reference_price == Decimal("100")
    assert output.actions[0].effective_open_at == interval_start
    assert output.actions[0].effective_bar_end == interval_end

def test_later_1m_cannot_substitute_for_missing_first_bar() -> None:
    ...

def test_equal_boundary_message_order_is_invariant() -> None:
    first = feed([completed_15m, completed_5m])
    second = feed([completed_5m, completed_15m])
    assert first == second
```

Also assert:

- 5m alone never emits a public Action;
- 15m decision produces pending only;
- exact first 1m applies open and close;
- no same-effective-Bar re-entry;
- no reverse;
- terminal close uses 15m close and `effective_open_at=None`;
- duplicate message idempotency;
- conflicting duplicate degrades/fails closed;
- stale segment input rejected;
- missing exact open cancels with `NEXT_BAR_OPEN_UNAVAILABLE`.

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_machine.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py
```

- [ ] **Step 3: Split Strategy decision from Action application.**

Refactor `engine.py` into pure operations:

```python
def decide_completed_15m(...): ...
def apply_pending_next_open(...): ...
def finalize_segment(...): ...
```

`run_subing_strategy_segment` becomes a compatibility wrapper over the unified machine during this task, then may be removed only after all consumers move.

- [ ] **Step 4: Implement the unified machine and coordinator.**

Keep Action reason ordering and ids unchanged.

- [ ] **Step 5: Change Historical replay to load 1m/5m/15m.**

Update:

```python
frequencies=(BarFrequency.M1, BarFrequency.M5, BarFrequency.M15)
```

Partition every frequency by the authoritative physical segment. Include 1m digest/cutoff in cache identity and bump the cache envelope schema from Task 1.

Do not infer session arithmetic outside existing session/bucket utilities.

- [ ] **Step 6: Add Historical/Live byte-parity tests.**

For the same recorded input stream:

```python
historical = replay_subing_strategy_segment(...)
streamed = feed_machine(...)
assert serialize_actions(streamed.actions) == serialize_actions(historical.actions)
assert serialize_episodes(streamed.episodes) == serialize_episodes(historical.episodes)
```

Normalize only processing timestamps that are not part of core Action/Episode facts.

Cover all four entry sources and all four exit families.

- [ ] **Step 7: Update Historical API/cache contracts.**

Add `effective_open_at` to output. If a public segment summary exposes counts, add `bar_count_1m`; otherwise keep the summary stable and include 1m only in internal cache identity.

Do not silently accept old cache bytes.

- [ ] **Step 8: Run focused and Stage 1 regression tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_machine.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

- [ ] **Step 9: Commit.**

```bash
git add \
  services/quant-api/app/market_data/subing_strategy \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/tests/research/test_subing_strategy_machine.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/test_market_research_overlays_api.py
git commit -m "feat(subing): unify historical and streaming strategy engine"
```

---

# Task 5: Add the read-only current Strategy projection

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/current_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_current_service.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/test_research_composition.py`

**HTTP surface:**

```text
GET /api/v1/market/research/subing-strategy/current
series_kind=actual_dominant
symbol=<active product>
frequency=15m
```

**Response:**

```python
class SubingStrategyCurrentResponse(BaseModel):
    strategy_id: Literal["subing_strategy_v1"]
    formula_version: Literal["subing_strategy_15m_v1"]
    series_kind: Literal["actual_dominant"]
    symbol: str
    frequency: Literal["15m"]
    contract: str
    segment_start_trading_day: date
    source_mode: Literal["canonical", "canonical_live"]
    cutoff: datetime
    position_state: Literal["flat", "long", "short"]
    pending_action: SubingStrategyPendingSummaryOut | None
    current_episode: SubingStrategyEpisodeOut | None
    latest_completed_episode: SubingStrategyEpisodeOut | None
    direction_context: SubingStrategyCurrentContextOut
```

**Causal context:**

```text
prior target days
→ Stage 1 Historical Daily Watch V2 reconstruction

current target day
→ exact current Daily Watch V2 immutable artifact
```

The service must never use today's artifact for an earlier target day.

It performs no:

```text
AlertEvent write
Scope read/write
Runtime-status read/write
PushPlus
strategy cache write
Canonical write
```

- [ ] **Step 1: Write RED service tests.**

Cover:

- exact `actual_dominant + 15m` request;
- current segment restore;
- Canonical-only and Canonical+completed-Live modes;
- prior-day context reconstruction;
- current artifact exact identity;
- stale/missing current context blocks entry but preserves exit evaluation;
- Event history not consulted;
- unsupported frequency returns typed 422;
- source identity failure returns typed 409.

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_current_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

- [ ] **Step 3: Implement the read-only composition.**

Reuse:

- `ActualDominantResearchSegmentLoader`;
- existing completed-Live read/aggregation seams;
- Historical direction resolver;
- Daily Watch V2 current Store;
- unified machine.

Do not read Alert Runtime process memory.

- [ ] **Step 4: Add API schemas and exact error mapping.**

Return only public, non-secret, source-specific facts.

- [ ] **Step 5: Run focused tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_current_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
```

- [ ] **Step 6: Commit.**

```bash
git add \
  services/quant-api/app/market_data/subing_strategy/current_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_current_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_composition.py
git commit -m "feat(subing): expose current strategy projection"
```

---

# Task 6: Implement the active60 in-memory runtime evaluator

**Files:**

- Create: `services/quant-api/app/alerts/subing_strategy_runtime.py`
- Modify: `services/quant-api/app/alerts/__init__.py`
- Create: `services/quant-api/tests/test_subing_strategy_runtime.py`
- Modify: `services/quant-api/tests/fixtures/` only if a reusable production-format Bar fixture is required

**Public evaluator boundary:**

```python
@dataclass(frozen=True, slots=True)
class SubingStrategyRuntimeProductStatus:
    symbol: str
    state: Literal["warming", "ready", "unavailable"]
    cutoff_1m: datetime | None
    cutoff_5m: datetime | None
    cutoff_15m: datetime | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SubingStrategyRuntimeResult:
    actions: tuple[SubingStrategyAction, ...]
    product_status: SubingStrategyRuntimeProductStatus

class SubingStrategyRuntimeEvaluator:
    def restore_all(self, *, started_at: datetime) -> ...: ...
    def final_catch_up(self, ...) -> ...: ...
    def process_completed_bar(self, bar: CanonicalBar, frequency: BarFrequency) -> ...: ...
    def process_canonical_updated(self, trading_day: date) -> ...: ...
    def current_state(self, symbol: str) -> ...: ...
```

The evaluator does not know:

- Rule enablement;
- Scope;
- `AlertEvent`;
- PushPlus;
- notification status.

It calculates active60 even when the new Rule is disabled or empty-scope.

**Startup watermark:**

For each product, record `ready_cutoff`. Actions effective at or before that cutoff restore state only and are not returned as newly notifyable output. A pending Action whose target interval starts after readiness remains eligible.

- [ ] **Step 1: Write RED runtime-evaluator tests.**

Use fake restore/current readers and recorded completed-Bar streams.

Required cases:

```text
active60 restored independently of Scope
subscribe/restore race modeled by final catch-up
past Actions restore but do not emit
future pending Action emits after readiness
5m updates internal state only
15m creates pending only
first 1m applies Action
duplicate completed Bar is idempotent
conflicting same identity makes one product unavailable
one product failure does not stop others
stale contract/segment rejected
missing first 1m cancels pending
canonical_updated emits terminal close only when newly authoritative
later startup does not re-emit old terminal close
```

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_strategy_runtime.py
```

- [ ] **Step 3: Implement restore and per-product state.**

Store only in memory:

```text
symbol → machine state + ready watermark + availability
```

No Redis checkpoint and no database position table.

- [ ] **Step 4: Implement completed-Bar and terminal processing.**

Use the same machine from Task 4. Do not add strategy formulas here.

- [ ] **Step 5: Prove no-backfill behavior.**

Add a regression test where an open and close both occurred while Runtime was down. Restore must end flat and emit no Action.

- [ ] **Step 6: Run focused tests and Mypy.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_strategy_runtime.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py

MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy \
  services/quant-api/app/alerts/subing_strategy_runtime.py \
  services/quant-api/app/market_data/subing_strategy
```

- [ ] **Step 7: Commit.**

```bash
git add \
  services/quant-api/app/alerts/subing_strategy_runtime.py \
  services/quant-api/app/alerts/__init__.py \
  services/quant-api/tests/test_subing_strategy_runtime.py \
  services/quant-api/tests/fixtures
git commit -m "feat(alert): add active60 subing strategy evaluator"
```

Do not stage an unchanged or unrelated fixtures directory.

---

# Task 7: Add migration 0042 and exact Strategy Action Event contracts

**Files:**

- Create: `services/quant-api/alembic/versions/20260826_0042_subing_strategy_alert.py`
- Modify: `services/quant-api/app/alerts/models.py`
- Modify: `services/quant-api/app/alerts/registry.py`
- Create: `services/quant-api/app/alerts/strategy_payload.py`
- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/app/schemas/alerts.py`
- Create: `services/quant-api/tests/alembic/test_subing_strategy_alert_migration.py`
- Modify: `services/quant-api/tests/test_alert_models.py`
- Modify: `services/quant-api/tests/test_alert_registry.py`
- Modify: `services/quant-api/tests/test_alert_service.py`
- Modify: `services/quant-api/tests/test_migration_test_guard.py`

**Migration parent:**

```python
revision = "20260826_0042"
down_revision = "20260826_0041"
```

**Preflight before destructive changes:**

```text
exactly one subing_entry_signal_v1 Rule
zero subing_strategy_v1 Rules
old Rule Scope structurally valid
HTDY Rule exists and Scope/Event state structurally valid
no unknown active Rule codes
all existing result codes valid under current Rule
```

**Transaction changes:**

```text
delete old SuBing Event rows
rename old Rule row to subing_strategy_v1
preserve id/enabled/scope_products
drop lower_tf_confirmation
widen result-code element storage
global finite result-code union
add nullable action_id
add nullable strategy_payload JSON
partial UNIQUE(action_id) WHERE action_id IS NOT NULL
preserve HTDY logical rows unchanged
```

**Rule registry:**

```python
class AlertRuleKind(StrEnum):
    INDICATOR_OBSERVATION = "indicator_observation"
    STRATEGY_ACTION = "strategy_action"

SUBING_RULE = AlertRuleDefinition(
    rule_code="subing_strategy_v1",
    display_name="苏冰策略",
    kind=AlertRuleKind.STRATEGY_ACTION,
    input_frequencies=("1m", "5m", "15m"),
    series_kind="actual_dominant",
)
```

Remove the active `FORMAL_SIGNAL` kind only after all callers/tests are converted. No compatibility alias remains.

**Exact per-Rule contracts:**

```text
HTDY:
  buy / sell / buy+sell
  action_id = null
  strategy_payload = null

SuBing Strategy:
  exactly one open_long / open_short / close_long / close_short
  action_id required
  exact strategy_payload required
```

- [ ] **Step 1: Write isolated migration RED tests.**

Test realistic 0041 state with:

- old SuBing Rule + Scope + old Events;
- HTDY Rule + pair Scope + Events;
- invalid preflight variants.

Assertions:

```text
old SuBing Events removed
HTDY events logically equal
Rule primary key/enabled/scope preserved
new Rule code exists
old Rule code absent
lower_tf_confirmation absent
action_id partial uniqueness works
close_short accepted
arbitrary code rejected
downgrade raises exact unsupported error
preflight failure leaves schema/data at 0041
```

- [ ] **Step 2: Run RED isolated test.**

```bash
export GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../guiyi_quant_migration_test'

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_strategy_alert_migration.py
```

Use only the dedicated disposable database. Never point this command at Runtime or production DB.

- [ ] **Step 3: Implement exact payload serializer/parser.**

`strategy_payload.py` must:

- serialize from validated core `SubingStrategyAction` and optional Episode;
- use finite canonical Decimal strings;
- use UTC aware ISO timestamps;
- reject extra/missing fields;
- enforce open/close field differences;
- cross-check payload kind, ids, prices, reasons, entry facts, and `AlertEvent` columns;
- never recompute reasons or price change independently.

- [ ] **Step 4: Implement migration and ORM changes.**

Use a partial unique index with a stable name, for example:

```text
ux_alert_events_action_id_not_null
```

Do not add a third table.

- [ ] **Step 5: Implement Rule-specific service validation and idempotency.**

`create_event` behavior for `action_id`:

```text
not found
→ insert and commit

found and exact facts match
→ return None; no duplicate notification

found but facts conflict
→ AlertConsistencyError; no notification
```

- [ ] **Step 6: Run focused backend tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_migration_test_guard.py

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_strategy_alert_migration.py
```

- [ ] **Step 7: Commit.**

```bash
git add \
  services/quant-api/alembic/versions/20260826_0042_subing_strategy_alert.py \
  services/quant-api/app/alerts/models.py \
  services/quant-api/app/alerts/registry.py \
  services/quant-api/app/alerts/strategy_payload.py \
  services/quant-api/app/alerts/service.py \
  services/quant-api/app/schemas/alerts.py \
  services/quant-api/tests/alembic/test_subing_strategy_alert_migration.py \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_migration_test_guard.py
git commit -m "feat(alert): replace subing events with strategy actions"
```

---

# Task 8: Implement the exact owner PushPlus message contract

**Files:**

- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/app/alerts/notification_composition.py` only if constructor typing changes
- Modify: `services/quant-api/app/alerts/pushplus.py` only if payload typing changes; transport behavior must not change
- Modify: `services/quant-api/tests/test_alert_notification.py`
- Modify: `services/quant-api/tests/test_alert_notification_dispatcher.py`
- Modify: `services/quant-api/tests/test_alert_notification_composition.py`
- Modify: `services/quant-api/tests/test_alert_pushplus.py`

**Fixed reason labels:**

```python
SUBING_STRATEGY_REASON_LABELS = {
    "EMA21_BREACH_LONG": "跌破 EMA21",
    "EMA21_BREACH_SHORT": "突破 EMA21",
    "PREVIOUS_BAR_LOW_BREACH": "跌破上一根 15m 低点",
    "PREVIOUS_BAR_HIGH_BREACH": "突破上一根 15m 高点",
    "BOUND_LOW_PIVOT_BREACH": "跌破结构前低",
    "BOUND_HIGH_PIVOT_BREACH": "突破结构前高",
    "MACD_HIGH_DEAD_CROSS": "MACD 高位死叉",
    "MACD_LOW_GOLDEN_CROSS": "MACD 低位金叉",
    "CONTRACT_SEGMENT_END": "主力合约切换",
}
```

**Exact close fixture:**

```text
【苏冰策略】焦煤 · JM2601

15m 清多
建仓参考：xxx
清仓参考：xxx
参考变动：+x.xx%
原因：
- 跌破 EMA21
- MACD 高位死叉
```

No extra disclaimer, id, timestamp, provider reference, or link is appended.

Open messages contain:

```text
15m 建多 / 建空
建仓参考
原因
- confirmation source label
- optional 结构保护：前低/前高 <price>
```

- [ ] **Step 1: Replace old buy/sell formatter tests with RED exact-string tests.**

Cover:

- open_long with Pivot;
- open_short without Pivot;
- close_long exact user fixture;
- close_short;
- multiple reason order;
- terminal close;
- canonical Decimal formatting;
- explicit sign and two decimals;
- invalid unknown reason;
- HTDY formatting unchanged.

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py
```

- [ ] **Step 3: Implement formatting from committed exact payload.**

Do not accept loosely typed `dict`. Parse through Task 7's exact payload type first.

- [ ] **Step 4: Preserve one-shot owner routing.**

```text
subing_strategy_v1 → owner
htdy_original_15m → htdy_observers Topic
```

No routing change to HTDY.

- [ ] **Step 5: Run focused notification tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_alert_pushplus.py
```

- [ ] **Step 6: Commit.**

```bash
git add \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/app/alerts/notification_composition.py \
  services/quant-api/app/alerts/pushplus.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_alert_pushplus.py
git commit -m "feat(alert): format subing strategy notifications"
```

Stage only files actually changed.

---

# Task 9: Integrate Strategy evaluation into Alert Runtime and add status schema v3

**Files:**

- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/runtime_entry.py`
- Modify: `services/quant-api/app/api/runtime.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_runtime_entry.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`
- Modify: `services/quant-api/tests/test_alert_notification_composition.py`

**Required orchestration order:**

```text
run_forever:
  validate policy/schema/composition
  subscribe Redis patterns
  write strategy_state=warming
  restore active60
  final completed-Live catch-up
  write ready/degraded counts and cutoffs
  enter message loop
```

**Per completed-Bar trigger:**

```text
1. Parse and validate operational symbol + Bar identity.
2. Feed the Strategy evaluator once, independent of Rule Scope.
3. Process HTDY through its existing Rule path.
4. For each newly effective Strategy Action:
   a. load the one subing_strategy_v1 Rule
   b. check enabled and scope_products
   c. persist exact Event
   d. prepare message from committed payload
5. Commit Event before one-shot send.
```

Remove `_evaluate_subing` and the old `SubingReadService` formal-signal Alert seam from Runtime composition. Keep `SubingReadService` where Current Signal State still consumes it.

**Canonical updated:**

Feed `market:state(reason=canonical_updated)` to:

- existing HTDY D1/W1 path;
- Strategy terminal resolver.

These paths must be Rule-isolated.

**Runtime status schema v3:**

Add:

```text
strategy_state
strategy_started_at
strategy_ready_at
strategy_product_count
strategy_ready_product_count
strategy_unavailable_product_count
strategy_unavailable_symbols
last_strategy_action_at
last_strategy_restore_at
```

Read v1/v2 for upgrade compatibility; write only v3.

Existing notification failure acknowledgment semantics remain byte-for-byte compatible.

- [ ] **Step 1: Add RED runtime-order and status tests.**

Required assertions:

```text
subscribe occurs before restore
no Event/send during restore or catch-up
pending future Action can notify after ready
Scope does not change calculation state
disabled/empty Scope suppresses Event/send only
Event commit precedes sender
duplicate action_id does not send
conflicting action_id does not send
one Strategy product failure is isolated
invalid policy/schema blocks ready
HTDY still processes after Strategy product failure
canonical_updated terminal Action follows same Event path
status v1/v2 normalizes to v3
all v1.8.7 writes are schema v3
notification acknowledgment behavior unchanged
```

- [ ] **Step 2: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_runtime_entry.py
```

- [ ] **Step 3: Refactor Alert Runtime orchestration.**

Keep Rule-level try/rollback isolation. A Strategy Action Event persistence failure must prevent its notification but must not roll back a previously committed unrelated Event.

- [ ] **Step 4: Update composition.**

Inject:

```text
SubingStrategyRuntimeEvaluator
Historical/current restore dependencies
exact policies
Market/Live read seams
```

Construction must not start I/O. Activation marker behavior remains default-off.

- [ ] **Step 5: Extend health output.**

Expose aggregate counts and bounded symbol codes. Do not expose paths, tokens, payload bodies, or private provider details.

- [ ] **Step 6: Run focused tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_strategy_runtime.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_entry.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_alert_notification_composition.py
```

- [ ] **Step 7: Commit.**

```bash
git add \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/app/runtime_entry.py \
  services/quant-api/app/api/runtime.py \
  services/quant-api/app/schemas/runtime.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_entry.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_alert_notification_composition.py
git commit -m "feat(runtime): run subing strategy on completed live bars"
```

---

# Task 10: Replace Alert HTTP/Web presentation and add Live/Canonical reconciliation

**Backend files:**

- Modify: `services/quant-api/app/api/alerts.py`
- Modify: `services/quant-api/app/schemas/alerts.py`
- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/tests/test_alert_api.py`
- Modify: `services/quant-api/tests/test_alert_current_trading_day.py`

**Web files:**

- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/alerts.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/utils/alertRules.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/src/utils/subingStrategyRecords.ts`
- Create: `apps/quant-web/src/utils/subingStrategyReconciliation.ts`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Create: `apps/quant-web/src/composables/useSubingStrategyCurrent.ts`
- Modify: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`
- Modify: `apps/quant-web/src/components/market/SubingPanel.vue`
- Modify: `apps/quant-web/src/components/market/SubingStrategyRecords.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/alertMarkers.test.ts`
- Modify: `apps/quant-web/tests/subingPanel.test.ts`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Modify: `apps/quant-web/tests/marketResearch.test.ts` if present
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Alert wire contract:**

```ts
type SubingStrategyActionKind =
  | 'open_long'
  | 'open_short'
  | 'close_long'
  | 'close_short'

interface AlertEvent {
  // existing identity fields
  action_id: string | null
  strategy_action: SubingStrategyActionPayload | null
}
```

Remove `lower_tf_confirmation` from backend and TypeScript.

**Presentation:**

```text
苏冰策略事件
建多 / 建空 / 清多 / 清空
```

No active `subing_entry_signal_v1`, “买入信号”, or “卖出信号” branch remains for SuBing Alert Events.

**Marker reconciliation:**

```text
Live Strategy Event marker key = action_id
Historical Action marker key   = action_id
Marker time                     = effective_bar_end
```

Rules:

```text
same action_id + exact facts
→ one Marker

same action_id + factual mismatch
→ Canonical Historical Marker is chart authority
→ immutable Event remains visible as notification fact
→ surface STRATEGY_ACTION_FACT_MISMATCH
→ no duplicate Marker
→ no re-notification
```

HTDY alert markers continue to use their current identity.

**Current Episode:**

On completed Live mutation for displayed `actual_dominant + 15m` SuBing:

```text
refresh /subing-strategy/current
→ update flat/long/short, pending, current Episode
```

Historical Strategy failure or current Strategy failure degrades only its layer; K-lines remain usable.

- [ ] **Step 1: Add RED backend API tests.**

Assert:

- HTDY Event returns null Strategy fields;
- Strategy Event returns exact typed payload;
- malformed Rule/payload pair fails closed;
- current effective trading-day reads include cross-day next-open Event;
- no `lower_tf_confirmation`;
- no old Rule code.

- [ ] **Step 2: Add RED Web unit tests.**

```ts
it('dedupes one live event and one historical action by action_id', () => {
  // expect one marker at effective_bar_end
})

it('uses canonical marker and reports mismatch for conflicting same-id facts', () => {
  // expect one canonical marker and STRATEGY_ACTION_FACT_MISMATCH
})

it('renders current open episode from the current endpoint', () => {
  // expect 持仓中 and reference facts
})
```

- [ ] **Step 3: Run RED tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_current_trading_day.py

pnpm --dir apps/quant-web test -- --run
```

- [ ] **Step 4: Update backend schemas and API.**

Use exact typed Pydantic unions. Do not expose raw unvalidated JSON.

- [ ] **Step 5: Implement Web reconciliation.**

Do not store screen coordinates. Continue to anchor markers by business time.

Filter Strategy Events out of the generic Alert marker path before merging, so the same Action is not rendered once as Alert and once as Research.

- [ ] **Step 6: Add current Strategy composable with identity generation.**

Reject stale responses across:

```text
symbol
series_kind
frequency
contract
request generation
```

Refresh on `live` mutation only for supported SuBing identity.

- [ ] **Step 7: Update product panel wording.**

Replace “Formal Event” for SuBing with “苏冰策略事件”. Keep current Factor/Lifecycle internal details behind the existing advanced toggle.

- [ ] **Step 8: Run Web unit/build/E2E focused tests.**

```bash
pnpm --dir apps/quant-web test -- --run
pnpm --dir apps/quant-web exec vue-tsc --noEmit
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e -- --grep "SuBing|strategy|marker|prepend"
```

- [ ] **Step 9: Commit.**

```bash
git add \
  services/quant-api/app/api/alerts.py \
  services/quant-api/app/schemas/alerts.py \
  services/quant-api/app/alerts/service.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_current_trading_day.py \
  apps/quant-web/src \
  apps/quant-web/tests \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): present live subing strategy actions"
```

Before committing, inspect `git diff --cached --stat` and unstage unrelated Web files.

---

# Task 11: Add no-write shadow acceptance and reconcile canonical documentation

**Files:**

- Create: `services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py`
- Modify: `services/quant-api/pyproject.toml` to register a `manual_acceptance` marker
- Modify: `TESTING.md`
- Modify only after evidence exists:
  - `STATUS.md`
  - `PROJECT_SOURCE.md`
  - `AGENTS.md`
  - `DECISIONS.md`
- Modify active OpenSpec files only if their current contracts require Alert/Runtime updates

**Acceptance test boundary:**

The manual acceptance test is skipped unless explicitly enabled:

```text
GUIYI_SUBING_STAGE2_SHADOW=1
```

It must inject:

```text
Null Event writer
Null notification sender
no cache writer
read-only PostgreSQL transaction
read-only Canonical/Live readers
```

It may consume an authorized read-only stream or a recorded production-format stream. It produces no:

```text
AlertEvent
Scope mutation
Redis status write
PushPlus
Canonical write
Runtime activation
```

**Required evidence:**

- active60 restore result and bounded unavailable list;
- no Historical/Live Action divergence on identical prefixes;
- no cross-contract/segment state;
- exact first-1m effective opens;
- no external writes;
- no manufactured Action when the natural stream has none.

- [ ] **Step 1: Add the skipped manual-acceptance test and guard tests.**

The test must fail if a real writer/sender is injected.

- [ ] **Step 2: Run it without authorization and confirm skip.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m manual_acceptance \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py
```

Expected: skipped.

- [ ] **Step 3: Run recorded-stream no-write acceptance.**

This is repository-safe and uses only committed fixtures/fakes.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py \
  -k recorded_stream
```

Keep the recorded-stream test outside the `manual_acceptance` marker so it is part of ordinary repository verification. Document both recorded and real read-only commands in `TESTING.md`.

- [ ] **Step 4: Run authorized real read-only shadow only when the user has granted that exact read scope.**

Do not infer this authorization from implementation approval.

- [ ] **Step 5: Update canonical docs with actual, not intended, results.**

Required facts:

```text
Stage 1 + Stage 2 code status
new Rule code and direct replacement semantics
migration 0042 present but not executed
Runtime remains unchanged until promotion Gate
release remains v1.8.5 until v1.8.7 release exists
no natural Strategy notification claim before one exists
```

Remove stale statements that PR #226 is unmerged or Stage 2 is absent only after the corresponding repository facts are true.

- [ ] **Step 6: Run documentation/contract checks.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_canonical_consistency.py

uv run --with openspec \
  openspec validate --specs --strict --no-interactive

bash scripts/security/scan-secrets.sh
git diff --check
```

- [ ] **Step 7: Commit.**

```bash
git add \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py \
  services/quant-api/pyproject.toml \
  TESTING.md \
  STATUS.md \
  PROJECT_SOURCE.md \
  AGENTS.md \
  DECISIONS.md \
  openspec
git commit -m "docs(subing): record stage2 verification boundary"
```

Stage only changed canonical/OpenSpec files.

---

# Task 12: Run complete verification, create the implementation PR, and stop at the develop Gate

**Files:** no new product files unless verification finds a defect.

- [ ] **Step 1: Rebase or merge latest develop safely before final verification.**

```bash
git fetch origin
git merge --no-edit origin/develop
```

Resolve only task-related conflicts. Re-run affected tests after any merge.

- [ ] **Step 2: Run full non-isolated Python verification.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] **Step 3: Run isolated PostgreSQL verification.**

```bash
export GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../guiyi_quant_migration_test'

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests
```

Never use production or Runtime DB.

- [ ] **Step 4: Run static checks.**

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app \
  services/quant-api/tests \
  packages/quant-core/guiyi_quant \
  scripts

MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy \
  --follow-imports=skip \
  --exclude 'services/quant-api/app/research/market_structure/' \
  services/quant-api/app \
  packages/quant-core/guiyi_quant
```

- [ ] **Step 5: Run engineering canonical checks.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_canonical_consistency.py
```

- [ ] **Step 6: Run complete Web verification.**

```bash
pnpm --dir apps/quant-web test -- --run
pnpm --dir apps/quant-web exec vue-tsc --noEmit
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 7: Run OpenSpec, secret, diff, and scope checks.**

```bash
uv run --with openspec \
  openspec validate --specs --strict --no-interactive

bash scripts/security/scan-secrets.sh
git diff --check
git status --short
git diff --stat origin/develop...HEAD
```

Verify there is no:

```text
main/tag/release mutation
Runtime switch
activation marker change
production Scope value
credential
real notification
production data write
order path
generic strategy platform
```

- [ ] **Step 8: Create the implementation PR to develop.**

PR title:

```text
feat: run SuBing Strategy V1 on completed Live bars
```

PR body must report:

- exact base/head;
- task commits;
- complete verification counts;
- isolated migration result;
- recorded/read-only shadow result;
- no external mutation;
- remaining external Gates;
- known unavailable products or evidence gaps;
- explicit repository conclusion request.

- [ ] **Step 9: Open a separate exact-head Review session.**

Review against:

```text
base = implementation planning base/latest develop merge-base
head = exact PR head
```

Review must check:

- Historical/Live parity;
- first-1m causality;
- equal-boundary ordering;
- no-backfill;
- Pivot semantics;
- migration destruction/preflight;
- Rule-specific payload validation;
- one-shot notification;
- HTDY non-regression;
- Event/Action identity;
- Web mismatch reconciliation;
- default-off Runtime;
- no release or external mutation.

Fix every Critical and Important finding, rerun affected and full checks, then obtain a new exact-head review.

- [ ] **Step 10: Stop at the human integration Gate.**

The only acceptable final conclusions are:

```text
允许集成 develop
要求修正后再集成
阻塞
```

Do not merge automatically.

After a human `允许集成 develop` and confirmed merge:

```bash
git worktree remove ../guiyi-subing-strategy-v1-stage2
git branch -d feature/subing-strategy-v1-stage2-v1.8.7
```

Do not clean the worktree/branch before merge readback.

---

# Task 13: Prepare release candidate v1.8.7 only under a later release-candidate Gate

This task is **not** part of the implementation branch. Start it only after:

```text
Stage 2 implementation merged into develop
independent Review passed
human allows entry into release candidate
```

**Workspace:**

```bash
git fetch origin
git worktree add ../guiyi-release-v1.8.7 \
  -b release/v1.8.7 \
  origin/develop
cd ../guiyi-release-v1.8.7
```

**Likely version files:**

- Modify: `services/quant-api/app/version.py`
- Modify: `services/quant-api/pyproject.toml`
- Modify: `apps/quant-web/package.json`
- Modify: `uv.lock`
- Modify: `pnpm-lock.yaml`
- Modify any existing release/version consistency fixture that currently contains `1.8.5`
- Create or update repository-standard release notes

Do not change `guiyi-quant-core` package version unless the repository's current release consistency test requires it; its package version is independent from the workstation release.

- [ ] **Step 1: Add/adjust release consistency tests first.**

Tests must fail while any active component reports:

```text
1.8.5
1.8.6
develop
```

Expected target:

```text
1.8.7
```

- [ ] **Step 2: Update all active release identities together.**

```python
APP_VERSION = "1.8.7"
```

Update package/lock metadata through normal package manager commands rather than hand-editing generated lock sections.

- [ ] **Step 3: Run the complete Task 12 verification on the exact release head.**

Additionally verify:

```bash
grep -R "1\.8\.5\|1\.8\.6" \
  services/quant-api/app/version.py \
  services/quant-api/pyproject.toml \
  apps/quant-web/package.json \
  uv.lock \
  pnpm-lock.yaml
```

Expected: no stale active release identity.

- [ ] **Step 4: Create a release PR to main and stop.**

PR title:

```text
release: v1.8.7
```

The PR includes code already integrated in develop plus release identity only. It does not execute migration or switch Runtime.

- [ ] **Step 5: Obtain independent release review.**

Stop at:

```text
允许发布 main/tag
```

Do not merge, tag, or publish without that exact external-operation Gate.

---

## 5. Operator-only external-operation sequence

The implementation and release-preparation sessions must not execute this section. It records the required order and readbacks.

### Gate A — release

Explicit authorization must identify:

```text
merge release/v1.8.7 to main
create annotated tag v1.8.7
create GitHub Release targeting the peeled exact tag commit
```

Read back:

```text
main commit
annotated tag object and peeled commit
GitHub Release target
API/Web/package version identity
```

### Gate B — production migration

Explicit authorization must identify:

```text
production PostgreSQL
migration 20260826_0042
one forward-only attempt
```

Preflight and readback:

```text
parent head = 20260826_0041
old/new Rule counts
old SuBing Event count
HTDY Rule/Scope/Event counts
preserved SuBing Rule id/enabled/scope
columns/indexes/constraints
final head = 20260826_0042
```

Do not start v1.8.5 after this migration.

### Gate C — Runtime promotion

Explicit authorization must identify:

```text
exact v1.8.7 tag
detached Runtime worktree
which launchd labels switch
whether preserved enabled/scope may begin future natural Strategy notifications
```

If natural Strategy notification activation is not explicit, leave Alert stopped or non-operational.

Read back:

```text
clean detached Runtime root
all launchd roots
API health version=1.8.7
DB head=0042
strategy_state ready/degraded counts
Rule code and Scope
no synthetic Strategy Event
```

### Gate D — owner canary

Explicit authorization permits one generic owner canary only.

It:

```text
creates no Strategy Event
fakes no Action
does not prove WeChat delivery
does not authorize retry
```

Natural Strategy Event evidence is observed separately.

---

## 6. Plan acceptance checklist

Before implementation starts, confirm this Plan contains no unresolved ambiguity about:

- one shared semantic engine;
- first completed 1m effective open;
- 5m/15m equal-boundary coordination;
- Action id stability;
- historical 1m parity;
- current-day versus prior-day context;
- active60 calculation versus Scope;
- startup no-backfill;
- terminal rollover;
- exact migration destruction and no downgrade;
- exact per-Rule Event payload;
- exact PushPlus text;
- Live/Historical mismatch reconciliation;
- default-off Runtime;
- separate repository/release/migration/Runtime/canary Gates.

Plan self-check:

```text
No unresolved placeholder markers
No production command is authorized by implementation approval
No automatic task → develop merge
No automatic release/tag
No hidden order/account path
No second Alert process
No strategy checkpoint table
No notification retry infrastructure
```

The correct next step after Plan approval is a new Sol/high-reasoning implementation session in the isolated task worktree. The correct repository endpoint remains the human `允许集成 develop` Gate.
