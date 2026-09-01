# Newow 牛哇趋势策略 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox syntax for tracking. Every task requires its own branch/worktree, tests and review; this plan does not authorize Runtime, production writes, notification, main/tag/release or automatic merge.

**Goal:** 实现一套可独立运行的 `actual_dominant + completed D1` 牛哇趋势观察策略，包含轻量共享底层、完整趋势状态机、普通整理突破、趋势回调/再增强/减弱/失效、杯柄 Setup、只读 Web 与 active60 盘后 Shadow。

**Architecture:** `quant-core` 保存 NumPy-only 权威公式；Application 只通过 `MarketDataService` 读取真实 rank1 物理合约段并逐 Bar 驱动同一 `NewowDailyObserver.step()`；文件快照是 API/Web 唯一事实。V1 不建立通用策略平台、数据库表、Live/Redis 状态、订单或账户域。

**Tech Stack:** Python 3.12、NumPy、现有 EMA/ATR/MACD/Lux Range kernels、FastAPI/Pydantic、Vue 3/TypeScript、现有安全原子 Snapshot 模式。

**Spec:** `docs/tasks/2026-09-01-newow-trend-v1-design.md`

## Global Constraints

- `strategy_code = newow_trend_v1`；`setup_code = newow_cup_handle_v1`。
- 当前唯一 Profile 为 `newow_tf_1d_v1`；禁止 W1、60m、15m、5m、1m 或隐藏跨周期输入。
- Newow 与 SuBing/HTDY 完全隔离。
- 复用现有 `ema.py`、`atr.py`、`macd.py`、`range_detector_lux.py`；不得复制公式。
- Authoritative core 保持 NumPy-only；pandas 只允许研究报表。
- 不新增 migration、生产表、Redis key、worker queue、账户、订单、仓位或 PnL。
- 所有正式输出 completed-only、strict-before、prefix invariant、batch/incremental parity、same-contract isolated、fail-closed。
- Event immutable；失效、减弱、恢复使用新 Event。
- HTTP 只读 snapshot；Web 不重新计算公式。
- 真实盘后调度、PushPlus、Rule/Scope、Runtime、main/tag/release 均需独立授权。

---

## File Structure

### Quant Core

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py            # frozen contracts / enums
├── profile.py           # D1 profile and immutable hashes
├── features.py          # adapters + derived normalized features
├── phase_lite.py        # moments and phase states
├── structure_lite.py    # CausalExtremeLite + Lux Range adapter
├── observation.py       # evidence, key levels, immutable lifecycle
├── trend.py             # trend band and upper strategy state machine
└── cup_handle.py        # only named setup in V1
```

### Application

```text
services/quant-api/app/market_data/newow/
├── __init__.py
├── daily_observer.py
├── historical.py
├── snapshot.py
├── snapshot_store.py
└── query.py
```

### API / Web

```text
services/quant-api/app/api/market_research_newow.py
services/quant-api/app/schemas/market_research_newow.py
services/quant-api/app/main.py

apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/composables/useNewowTrend.ts
apps/quant-web/src/components/market/NewowTrendPanel.vue
apps/quant-web/src/pages/market/index.vue
apps/quant-web/src/pages/market/chart.vue
```

### Tests

```text
services/quant-api/tests/newow/
├── test_models_profile.py
├── test_features_phase.py
├── test_structure_lite.py
├── test_trend_state_machine.py
├── test_cup_handle.py
├── test_daily_observer.py
├── test_historical_snapshot.py
└── test_newow_api.py

apps/quant-web/tests/newowTrend.test.ts
apps/quant-web/tests/newowTrendChart.test.ts

tests/fixtures/newow/
├── trend_band_v1.json
├── trend_state_v1.json
├── cup_handle_positive_v1.json
└── cup_handle_negative_v1.json
```

---

## Task 1: Contracts、Profile 与身份

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/__init__.py`
- Create: `packages/quant-core/guiyi_quant/newow/models.py`
- Create: `packages/quant-core/guiyi_quant/newow/profile.py`
- Test: `services/quant-api/tests/newow/test_models_profile.py`

**Interfaces:**

```python
class NewowTrendBand(StrEnum): ...
class NewowTrendState(StrEnum): ...
class NewowObservationType(StrEnum): ...
class NewowDirection(StrEnum): ...

@dataclass(frozen=True)
class NewowTimeframeProfile: ...

@dataclass(frozen=True)
class NewowObservationEvent: ...

@dataclass(frozen=True)
class NewowTrendObservationSnapshot: ...

def newow_d1_profile_v1() -> NewowTimeframeProfile: ...
```

- [ ] **Step 1: Write exact enum and frozen-dataclass tests**

Assert only the design-approved states/events exist; reject OPEN/CLOSE/POSITION fields; require `frequency="1d"`, `series_kind="actual_dominant"`, `auto_order=False`.

- [ ] **Step 2: Run the failing test**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_models_profile.py
```

Expected: import failure because the package does not exist.

- [ ] **Step 3: Implement immutable contracts and stable hashing**

Use canonical JSON ordering for `profile_hash` and `formula_digest`; reject unsupported frequency and unknown fields.

- [ ] **Step 4: Add event identity tests**

Assert identity binds strategy instance, product, physical contract, frequency, observation type, direction, bar_end and optional setup ID; rerun with identical input yields the same ID.

- [ ] **Step 5: Run targeted tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/quant-core/guiyi_quant/newow \
  services/quant-api/tests/newow/test_models_profile.py
git commit -m "feat(newow): add trend observation contracts"
```

**Review Gate:** no strategy math, IO, database or SuBing dependency may appear in these files.

---

## Task 2: Shared Feature Snapshot 与 Phase Lite

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/features.py`
- Create: `packages/quant-core/guiyi_quant/newow/phase_lite.py`
- Test: `services/quant-api/tests/newow/test_features_phase.py`
- Fixture: `tests/fixtures/newow/trend_band_v1.json`

**Consumes:** existing EMA/ATR/MACD kernels and `NewowTimeframeProfile`.

**Produces:**

```python
@dataclass(frozen=True)
class NewowFeatureSnapshot: ...

@dataclass(frozen=True)
class NewowPhaseLiteSnapshot: ...

def compute_newow_features(...)-> NewowFeatureSnapshot: ...
def compute_phase_lite(...)-> NewowPhaseLiteSnapshot: ...
```

- [ ] **Step 1: Write failing numeric golden tests**

Cover EMA10/21/60, ATR14, MACD 12/26/9, normalized slope, deviation, ER20, RV ratio, volume ratio and OI delta using fixed arrays.

- [ ] **Step 2: Add explicit skew/kurtosis formula tests**

Use a fixed return vector with hand-pinned expected unbiased skew and Fisher excess kurtosis; test constant returns, insufficient samples and non-finite inputs return typed unavailable reasons.

- [ ] **Step 3: Run tests and confirm failure**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_features_phase.py
```

- [ ] **Step 4: Implement adapters without duplicating existing kernels**

`features.py` may call existing indicator functions, then compute only Newow-specific normalized values. Do not copy EMA/ATR/MACD implementations.

- [ ] **Step 5: Implement Phase Lite priority**

Priority must be deterministic:

```text
EXPANSION_UP / EXPANSION_DOWN
LOWER_CONTRACTION / UPPER_CONTRACTION
LOWER_EXTREME / UPPER_EXTREME
BALANCED
UNAVAILABLE
```

- [ ] **Step 6: Add prefix tests**

For each prefix, compare last feature/phase value with the same position in the full run; no future row may affect an earlier result.

- [ ] **Step 7: Run targeted suite and commit**

```bash
git add packages/quant-core/guiyi_quant/newow/features.py \
  packages/quant-core/guiyi_quant/newow/phase_lite.py \
  services/quant-api/tests/newow/test_features_phase.py \
  tests/fixtures/newow/trend_band_v1.json
git commit -m "feat(newow): add shared features and phase lite"
```

**Review Gate:** NumPy-only, fixed float64 behavior, no pandas/SciPy defaults, no main-force-intent labels.

---

## Task 3: Structure Lite 与 Lux Range 复用

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/structure_lite.py`
- Test: `services/quant-api/tests/newow/test_structure_lite.py`
- Existing dependency: `packages/quant-core/guiyi_quant/indicators/range_detector_lux.py`
- Existing test to rerun: `services/quant-api/tests/test_range_detector_lux.py`

**Produces:**

```python
@dataclass(frozen=True)
class CausalExtremePoint: ...
@dataclass(frozen=True)
class NewowStructureLiteSnapshot: ...

class CausalExtremeLite:
    def step(self, completed_bar, atr_value) -> tuple[...]: ...

def adapt_lux_range_for_newow(...) -> NewowRangeContext: ...
```

- [ ] **Step 1: Write failing causal extreme tests**

Cover high/low confirmation, `pivot_at != confirmed_at`, minimum leg length, reversal ATR threshold, immutable confirmed point and contract reset.

- [ ] **Step 2: Write HH/HL/LH/LL tolerance tests**

Use `0.35 ATR` equality tolerance and assert deterministic labels.

- [ ] **Step 3: Write strict-before Lux Range tests**

A Range confirmed or revised on Bar t must not be usable as a breakout boundary on Bar t.

- [ ] **Step 4: Run tests and confirm failure**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_structure_lite.py \
  services/quant-api/tests/test_range_detector_lux.py
```

- [ ] **Step 5: Implement only the minimal structure contract**

Do not add BOS/CHOCH graph, zone clustering or generic pattern APIs.

- [ ] **Step 6: Add batch/incremental and prefix parity**

Serialize confirmed extremes and Range references; assert all old IDs, prices and confirmation times remain unchanged after append.

- [ ] **Step 7: Commit**

```bash
git add packages/quant-core/guiyi_quant/newow/structure_lite.py \
  services/quant-api/tests/newow/test_structure_lite.py
git commit -m "feat(newow): add causal structure lite"
```

**Review Gate:** no future pivot, no second Range formula, no cross-contract state.

---

## Task 4: Observation Evidence 与 Lifecycle

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/observation.py`
- Modify: `packages/quant-core/guiyi_quant/newow/models.py`
- Test: `services/quant-api/tests/newow/test_models_profile.py`
- Test: `services/quant-api/tests/newow/test_daily_observer.py`

**Produces:**

```python
@dataclass(frozen=True)
class NewowKeyLevelContext: ...
@dataclass(frozen=True)
class NewowEvidenceSnapshot: ...

class ObservationLifecycle:
    def transition(...) -> tuple[NewowTrendObservationSnapshot, tuple[NewowObservationEvent, ...]]: ...
```

- [ ] **Step 1: Write failing immutable-event tests**

Create a first-seen event, then invalidate it; assert the original bytes remain unchanged and a new linked event is created.

- [ ] **Step 2: Write dedupe tests**

Same prefix and same event identity emit zero new events on replay; later bars may update Snapshot but not replay the Event.

- [ ] **Step 3: Write primary-observation priority tests**

Pin the priority order from the design so one product produces one radar row.

- [ ] **Step 4: Implement lifecycle as pure state transition**

No IO, time-of-day lookup or external clock; all timestamps are explicit inputs.

- [ ] **Step 5: Run tests and commit**

```bash
git add packages/quant-core/guiyi_quant/newow/models.py \
  packages/quant-core/guiyi_quant/newow/observation.py \
  services/quant-api/tests/newow/test_models_profile.py \
  services/quant-api/tests/newow/test_daily_observer.py
git commit -m "feat(newow): add immutable observation lifecycle"
```

**Review Gate:** no OPEN/CLOSE, position, cost, PnL or automatic-execution semantics.

---

## Task 5: 牛哇趋势上层状态机

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/trend.py`
- Test: `services/quant-api/tests/newow/test_trend_state_machine.py`
- Fixture: `tests/fixtures/newow/trend_state_v1.json`

**Produces:**

```python
@dataclass(frozen=True)
class NewowTrendDecision: ...

class NewowTrendMachine:
    def step(
        self,
        *,
        features,
        phase,
        structure,
        previous_snapshot,
    ) -> NewowTrendDecision: ...
```

- [ ] **Step 1: Write trend-band boundary tests**

Cover exact thresholds and NEUTRAL hysteresis for `spread_atr`, `slope21_atr` and close/EMA21.

- [ ] **Step 2: Write CHOP_BLOCK tests**

Pin yellow/blue direct flip counting while ignoring neutral bars.

- [ ] **Step 3: Write state-transition table tests**

Cover long and short start, active, pullback, re-strengthening, weakening and invalidation; assert at most one primary transition per completed Bar.

- [ ] **Step 4: Write generic Range breakout tests**

Require prior frozen Range, body close breakout, participation support and same trend direction; geometry-only or volume-unconfirmed cases remain diagnostic.

- [ ] **Step 5: Run failing tests**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_trend_state_machine.py
```

- [ ] **Step 6: Implement minimal deterministic machine**

Keep thresholds in `newow_tf_1d_v1`, not as global magic constants or per-product overrides.

- [ ] **Step 7: Add mirror and prefix parity tests**

Bullish and bearish use a shared direction-normalization path but have separate expected fixtures.

- [ ] **Step 8: Commit**

```bash
git add packages/quant-core/guiyi_quant/newow/trend.py \
  services/quant-api/tests/newow/test_trend_state_machine.py \
  tests/fixtures/newow/trend_state_v1.json
git commit -m "feat(newow): add daily trend observer state machine"
```

**Review Gate:** strategy works without cup-handle; cup-handle must not be a mandatory condition for trend events.

---

## Task 6: 杯柄 Setup V1

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/cup_handle.py`
- Modify: `packages/quant-core/guiyi_quant/newow/profile.py`
- Modify: `packages/quant-core/guiyi_quant/newow/models.py`
- Test: `services/quant-api/tests/newow/test_cup_handle.py`
- Fixtures:
  - `tests/fixtures/newow/cup_handle_positive_v1.json`
  - `tests/fixtures/newow/cup_handle_negative_v1.json`

**Produces:**

```python
@dataclass(frozen=True)
class CupHandleCandidate: ...
@dataclass(frozen=True)
class CupHandleScoreBreakdown: ...

def evaluate_cup_handle_prefix(...) -> tuple[CupHandleCandidate, ...]: ...
```

- [ ] **Step 1: Write hard-negative fixtures**

Include V-bottom, broad range, downtrend rebound, cup depth below 10%, handle >15 bars, handle too deep, no handle contraction, breakout without volume, cross-contract window.

- [ ] **Step 2: Write positive bullish and bearish fixtures**

Pin L/B/R/H/P anchors, timestamps, geometry metrics, score breakdown and state.

- [ ] **Step 3: Write READY freeze tests**

After READY, append future Bars and assert candidate ID, anchors, confirmed_at and score breakdown never change.

- [ ] **Step 4: Write trend-context integration tests**

Geometry may be visible as FORMING, but READY/BREAKOUT requires the upper trend context and MACD rules from the design.

- [ ] **Step 5: Run failing tests**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_cup_handle.py
```

- [ ] **Step 6: Implement scoring in five explicit components**

Each rejected Gate and deducted point must produce a stable reason code. Do not implement any other pattern.

- [ ] **Step 7: Run prefix, append and mirror tests**

FORMING may evolve; READY/BREAKOUT may not backpaint.

- [ ] **Step 8: Commit**

```bash
git add packages/quant-core/guiyi_quant/newow/cup_handle.py \
  packages/quant-core/guiyi_quant/newow/profile.py \
  packages/quant-core/guiyi_quant/newow/models.py \
  services/quant-api/tests/newow/test_cup_handle.py \
  tests/fixtures/newow/cup_handle_positive_v1.json \
  tests/fixtures/newow/cup_handle_negative_v1.json
git commit -m "feat(newow): add cup handle trend setup"
```

**Review Gate:** no generic pattern framework, no profitability-based threshold tuning, and cup-handle is optional evidence rather than the trend product identity.

---

## Task 7: 唯一日线 Observer 与物理合约分段

**Files:**
- Create: `services/quant-api/app/market_data/newow/__init__.py`
- Create: `services/quant-api/app/market_data/newow/daily_observer.py`
- Create: `services/quant-api/app/market_data/newow/historical.py`
- Test: `services/quant-api/tests/newow/test_daily_observer.py`

**Produces:**

```python
class NewowDailyObserver:
    def step(self, completed_d1_bar) -> NewowObserverStepResult: ...

class NewowHistoricalService:
    def project(self, symbol, *, through) -> NewowHistoricalProjection: ...
```

- [ ] **Step 1: Write source-identity tests**

Reject non-D1, uncompleted, mismatched product/contract/segment, non-increasing bar_end and cross-contract continuation.

- [ ] **Step 2: Write deterministic step-order test**

Assert features → phase/structure → trend → cup setup → primary observation → lifecycle → snapshot.

- [ ] **Step 3: Write physical-segment reset tests**

Range, extremes, trend, cup candidate and lifecycle reset at rank1 contract change; no administrative seam creates trade or invalidation events.

- [ ] **Step 4: Write Historical/Incremental golden parity**

Run the same D1 segment in one pass and one-Bar increments; compare every Snapshot and Event field.

- [ ] **Step 5: Implement using only `MarketDataService`**

Do not glob files, infer dominant owner or fall back across frequency.

- [ ] **Step 6: Run tests and commit**

```bash
git add services/quant-api/app/market_data/newow \
  services/quant-api/tests/newow/test_daily_observer.py
git commit -m "feat(newow): add actual-dominant daily observer"
```

**Review Gate:** Historical owner availability, trading_day and segment identity are explicit; no Live/Redis path is introduced.

---

## Task 8: Immutable Snapshot 与只读 Query

**Files:**
- Create: `services/quant-api/app/market_data/newow/snapshot.py`
- Create: `services/quant-api/app/market_data/newow/snapshot_store.py`
- Create: `services/quant-api/app/market_data/newow/query.py`
- Test: `services/quant-api/tests/newow/test_historical_snapshot.py`

**Produces:**

```python
class NewowTrendSnapshotStore: ...
class NewowTrendSnapshotQuery: ...
```

- [ ] **Step 1: Write exact schema/hash tests**

Unknown/missing keys, digest mismatch and inconsistent current manifest fail closed.

- [ ] **Step 2: Write secure-path tests**

Require trusted absolute root, no symlink, 0700 directory, 0600 file, immutable payload and containment.

- [ ] **Step 3: Write atomic publication tests**

Temporary write → fsync/close → `os.replace` → physical readback → current manifest switch; failure preserves the previous current snapshot.

- [ ] **Step 4: Write HTTP-path prohibition seam tests**

Query may read current snapshot and slice it; it may not call Historical replay or publish.

- [ ] **Step 5: Implement and commit**

```bash
git add services/quant-api/app/market_data/newow/snapshot.py \
  services/quant-api/app/market_data/newow/snapshot_store.py \
  services/quant-api/app/market_data/newow/query.py \
  services/quant-api/tests/newow/test_historical_snapshot.py
git commit -m "feat(newow): publish immutable trend snapshots"
```

**Review Gate:** no DB/migration/cache repair, no unsafe path or request-time replay.

---

## Task 9: Read-only API

**Files:**
- Create: `services/quant-api/app/api/market_research_newow.py`
- Create: `services/quant-api/app/schemas/market_research_newow.py`
- Modify: `services/quant-api/app/main.py`
- Test: `services/quant-api/tests/newow/test_newow_api.py`

**Endpoints:**

```text
GET /api/v1/market/research/newow/definitions
GET /api/v1/market/research/newow/radar
GET /api/v1/market/research/newow/history
GET /api/v1/market/research/newow/current
```

- [ ] **Step 1: Write typed response and exact error tests**

Cover unavailable root, no snapshot, hash mismatch, unsupported frequency, symbol not in snapshot and invalid time window.

- [ ] **Step 2: Write no-replay/no-write tests**

Monkeypatch Historical and store writers to fail if called from HTTP.

- [ ] **Step 3: Implement thin router over `NewowTrendSnapshotQuery`**

Current V1 returns `Historical / Post-close`; no Live label.

- [ ] **Step 4: Run targeted API tests**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_api.py
```

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/api/market_research_newow.py \
  services/quant-api/app/schemas/market_research_newow.py \
  services/quant-api/app/main.py \
  services/quant-api/tests/newow/test_newow_api.py
git commit -m "feat(api): expose Newow trend observations"
```

**Review Gate:** read-only, typed, no provider access and no secret/output leakage.

---

## Task 10: Market Web 复核台

**Files:**
- Create: `apps/quant-web/src/api/newow.ts`
- Create: `apps/quant-web/src/types/newow.ts`
- Create: `apps/quant-web/src/composables/useNewowTrend.ts`
- Create: `apps/quant-web/src/components/market/NewowTrendPanel.vue`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Test: `apps/quant-web/tests/newowTrend.test.ts`
- Test: `apps/quant-web/tests/newowTrendChart.test.ts`

- [ ] **Step 1: Write API normalization tests**

Unknown reason codes render safely; timestamps and Decimal strings remain exact.

- [ ] **Step 2: Write radar priority tests**

One product renders one primary row in the spec order; unavailable/error counts remain separate from none.

- [ ] **Step 3: Write chart-layer tests**

Trend band, EMA10/21/60, confirmed extremes, Lux Range and cup anchors are drawn only from API data; `pivot_at` and `confirmed_at` both appear in tooltip.

- [ ] **Step 4: Implement minimal panel**

Do not add another general dashboard framework. Use existing Market index/card patterns and existing chart component seams.

- [ ] **Step 5: Run Web tests and build**

```bash
pnpm -C apps/quant-web test
pnpm -C apps/quant-web build
```

- [ ] **Step 6: Commit**

```bash
git add apps/quant-web/src/api/newow.ts \
  apps/quant-web/src/types/newow.ts \
  apps/quant-web/src/composables/useNewowTrend.ts \
  apps/quant-web/src/components/market/NewowTrendPanel.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/newowTrend.test.ts \
  apps/quant-web/tests/newowTrendChart.test.ts
git commit -m "feat(web): add Newow trend review workspace"
```

**Review Gate:** Web contains no strategy thresholds or reimplementation; no buy/sell/position wording.

---

## Task 11: active60 盘后 Shadow 与健康摘要

**Files:**
- Create: `services/quant-api/app/market_data/newow/shadow.py`
- Create: `services/quant-api/app/cli/newow_trend_shadow.py`
- Test: `services/quant-api/tests/newow/test_newow_shadow.py`
- Modify when accepted: `TESTING.md`

**Produces:**

```python
@dataclass(frozen=True)
class NewowShadowSummary:
    expected: int
    processed: int
    none: int
    observation_counts: Mapping[str, int]
    unavailable_by_reason: Mapping[str, int]
    error_by_reason: Mapping[str, int]
    latency_ms: int
```

- [ ] **Step 1: Write coverage-accounting tests**

Every expected product lands in exactly one of processed-none, processed-observation, unavailable or error; totals must reconcile.

- [ ] **Step 2: Write no-mutation dry-run tests**

Default CLI prints/returns a summary without publishing, writing DB/Redis or sending notification.

- [ ] **Step 3: Implement one-shot after-market batch**

Use `active_products.txt` as research capability, not `operational_products.txt` Runtime authorization.

- [ ] **Step 4: Add explicit publication flag guarded by trusted root**

Code merge does not authorize actual scheduled invocation or external write.

- [ ] **Step 5: Run tests and commit**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_shadow.py
```

```bash
git add services/quant-api/app/market_data/newow/shadow.py \
  services/quant-api/app/cli/newow_trend_shadow.py \
  services/quant-api/tests/newow/test_newow_shadow.py \
  TESTING.md
git commit -m "feat(newow): add after-market shadow summary"
```

**Review Gate:** no scheduler, launchd, PushPlus, Rule/Scope or Runtime enablement in this task.

---

## Task 12: 用户复核标签与最小结果

**Files:**
- Create: `services/quant-api/app/research/newow/review_labels.py`
- Create: `services/quant-api/app/research/newow/outcomes.py`
- Create: `services/quant-api/app/api/market_research_newow_feedback.py`
- Create: `apps/quant-web/src/components/market/NewowReviewLabels.vue`
- Test: `services/quant-api/tests/newow/test_newow_review_outcomes.py`
- Test: `apps/quant-web/tests/newowReviewLabels.test.ts`

- [ ] **Step 1: Define a tiny closed label set**

```text
WORTH_REVIEWING
NOT_WORTH_REVIEWING
TOO_EARLY
TOO_LATE
BAD_LOCATION
V_BOTTOM_FALSE_POSITIVE
WIDE_RANGE_FALSE_POSITIVE
DOWNTREND_REBOUND_FALSE_POSITIVE
VOLUME_UNTRUSTWORTHY
```

- [ ] **Step 2: Prove feedback cannot mutate strategy facts**

Feedback references Event ID and user timestamp; it cannot alter Snapshot/Event bytes, score or thresholds.

- [ ] **Step 3: Implement minimal retrospective outcomes**

Compute 3/5/10/20 D1 direction change, MFE, MAE, return-to-pivot and structural invalidation within the same physical contract only.

- [ ] **Step 4: Add report labels**

Every report states `retrospective observation outcome / gross / pre-cost / not OOS / not tradability evidence`.

- [ ] **Step 5: Run tests and commit**

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow/test_newow_review_outcomes.py
pnpm -C apps/quant-web exec node --test tests/newowReviewLabels.test.ts
```

**Review Gate:** no threshold auto-tuning, winner selection or prospective backfill.

---

## Task 13: 独立盘后摘要通知 Gate

This task is not authorized by approving or implementing Tasks 1—12.

A separate task may be opened only after all conditions are true:

```text
existing Runtime/Alert natural reliability evidence complete
active60 Shadow coverage stable
observation volume acceptable
repeat/rapid-failure rate acceptable
user review shows real value
user explicitly authorizes Newow Rule/Scope/transport
```

Preferred product shape:

```text
每日盘后一条摘要
而不是每个品种逐条推送
```

Any future notification task must retain existing Alert two-table, Event-first, one-shot transport and provider-accepted-not-delivered boundaries.

---

## Final Verification

Before claiming source completion, run:

```bash
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/newow \
  services/quant-api/tests/test_range_detector_lux.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py

uv run --project services/quant-api --no-sync ruff check \
  packages/quant-core/guiyi_quant/newow \
  services/quant-api/app/market_data/newow \
  services/quant-api/app/api/market_research_newow.py \
  services/quant-api/app/schemas/market_research_newow.py \
  services/quant-api/tests/newow

uv run --project services/quant-api --no-sync mypy \
  packages/quant-core/guiyi_quant/newow \
  services/quant-api/app/market_data/newow

pnpm -C apps/quant-web test
pnpm -C apps/quant-web build

git diff --check
```

Also run the repository's applicable OpenSpec and secret-scan commands from `TESTING.md`.

## Completion States

```text
DESIGN_COMPLETE          本设计已批准
PLAN_COMPLETE            本计划已合入develop
CODE_COMPLETE            所有源码任务完成
TEST_COMPLETE            必要测试真实通过
SHADOW_CODE_COMPLETE     Shadow代码完成但未真实启用
EXTERNAL_GATE_PENDING    调度、通知、release或Runtime未授权
```

Do not claim `RELEASED` or `RUNTIME_READY` without the separate evidence required by `AGENTS.md` and `STATUS.md`.
