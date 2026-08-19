# SuBing Lifecycle V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 `subing_entry_signal_v1`、Alert、Scope、Clawbot、Execution Review、Data Foundation 与 production Runtime 的前提下，实现 SuBing 5m/15m research-only 生命周期：方向准备、研究确认、延续、退出风险、关闭，以及可解释的 Shadow 研究漏斗。

**Architecture:** V2 作为现有 SuBing V1 旁路纯函数 read-model。先实现 exact research policy 与不可变领域合同，再实现 ConfirmedPivot/Breakout/Retest 和生命周期 reducer；随后把 reducer 接入现有 `SubingReadService` 的 current-rank1 Historical/completed-Live seam，以 additive API/Web 暴露当前快照，最后增加只读 Historical Shadow CLI。整个实现不新增生命周期 DB、Redis 状态、worker、队列或正式 Rule。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、Decimal、现有 `MarketDataService` / `MarketReadService` / SuBing Factor/Signal、Vue 3、TypeScript、Naive UI、Lightweight Charts、pytest、Node test、Playwright。

**Spec:** `docs/superpowers/specs/2026-08-19-subing-lifecycle-v2-design.md`

## Global Constraints

- 实施基线从当前最新 `develop` 创建；开始每个 Task 前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、本 Spec 与本 Plan，并确认没有更新后的 canonical 冲突。
- `subing_entry_signal_v1` 的 Factor、Signal、Calibration、same-boundary resolver、Alert、Scope 和通知语义必须零变化。
- `FORMAL_V1` 仍精确定义为现有 `resolved_signal.status == MATCHED`；只有现有 V1 路径可以创建正式 AlertEvent。
- V2 全部 `research_only=true`；不得新增 Alert Rule、Scope、notification、Execution Review 自动入口或订单路径。
- `auto_order=false` 始终成立。
- Historical 只经 `MarketDataService`；Live 只经既有 completed-Live seam。不得直读 Parquet、RQData、Redis 或复制主力 resolver。
- current-rank1、segment-local、no pre-rank1 warmup、no cross-roll inheritance 保持不变。
- 不修改 `DatasetKey`、Canonical、八表 Market Catalog 或月分区合同。
- 不新增生命周期 DB/event store、Redis lifecycle cache、background worker、queue、outbox、在线多 Policy 或通用 Strategy/Research Framework。
- 研究参数只存在于 Git-tracked exact policy `subing_lifecycle_v2_research_v1`；同 ID 内容漂移 fail-closed。
- 每个 completed 5m boundary 最多一条顶层 transition；15m 同 boundary 复用既有 resolver 后只评价一次。
- 任何需未来 Bar 才能确认的事实只能记在真实 `confirmed_at`；Confirmed Pivot、Opportunity、Transition 必须满足 prefix invariance。
- 不可用 boundary 不推进 hold/retest/risk 计数，不制造 `EXIT_RISK` 或 `CLOSED`。
- Tasks 1–8 仅仓库开发与隔离测试；不得 release/tag、Runtime switch、真实通知、Scope mutation、生产 DB/Canonical 写入。
- 真实 `jm` 页面观察、开发态 Runtime reload 或生产部署不属于本 implementation plan；实现收口后另开明确 Gate。

## Task Dispatch Matrix

| Task | Lane | Model | Reasoning | Session | Plan | Workspace | Integration Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Policy + domain contracts | Lane 3 | Sol | 高 | 新会话 | Plan-only → 用户批准后执行 approved task | 从最新 develop 新 task worktree | 独立 Review 后才可进 develop |
| 2 Causal structure kernel | Lane 3 | Sol | 高 | 新会话 | Plan-only → approved task | 从最新 develop 新 task worktree | 独立 Review |
| 3 Entry lifecycle reducer | Lane 3 | Sol | 高 | 新会话 | Plan-only → approved task | 从最新 develop 新 task worktree | 独立 Review |
| 4 Continuation/risk/close | Lane 3 | Sol | 高 | 新会话 | Plan-only → approved task | 从最新 develop 新 task worktree | 独立 Review |
| 5 Existing read seam integration | Lane 3 | Sol | 高 | 新会话 | Plan-only → approved task | 从最新 develop 新 task worktree | 独立 Review |
| 6 Additive API contract | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 从最新 develop 新 task worktree | tests/review 后可进 develop |
| 7 Web lifecycle observation | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 从最新 develop 新 task worktree | tests/review 后可进 develop |
| 8 Read-only Shadow research | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 从最新 develop 新 task worktree | tests/review 后可进 develop |
| 9 Final regression + independent review | Lane 3 review | Sol | 高 | 新独立 Review 会话 | Plan-only | develop/read-only review worktree | Critical=0 / Important=0 |

Worktree rule for every implementation Task:

```text
latest develop
→ task branch/worktree
→ task tests + self-review
→ required review/gate
→ integrate develop
→ read back develop ancestry
→ remove merged task worktree/branch
```

No Task may touch `main`, tag, release worktree or Runtime worktree.

---

## File Structure

### Create

- `data/research_policies/subing_lifecycle_v2_research_v1.json` — exact research-only policy payload.
- `services/quant-api/app/market_data/subing_lifecycle_policy.py` — strict policy loader and immutable policy model.
- `services/quant-api/app/market_data/subing_structure.py` — ConfirmedPivot、BreakoutAssessment、RetestAssessment pure functions.
- `services/quant-api/app/market_data/subing_lifecycle.py` — lifecycle enums/dataclasses、pure reducer、current snapshot/trace projection.
- `services/quant-api/app/market_data/subing_lifecycle_research_service.py` — historical-only, segment-local Shadow research orchestration through `MarketDataService`.
- `services/quant-api/tests/test_subing_lifecycle_policy.py`
- `services/quant-api/tests/test_subing_structure.py`
- `services/quant-api/tests/test_subing_lifecycle.py`
- `services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py`
- `apps/quant-web/src/components/market/SubingLifecyclePanel.vue`
- `apps/quant-web/src/utils/subingLifecycleMarkers.ts`
- `apps/quant-web/tests/subingLifecycle.test.ts`

### Modify

- `services/quant-api/app/market_data/subing_read_service.py` — reuse existing aligned current-rank1 inputs and add lifecycle projection without changing V1 output semantics.
- `services/quant-api/app/market_data/composition.py` — inject exact lifecycle policy and historical Shadow service.
- `services/quant-api/app/schemas/market.py` — additive lifecycle response DTOs.
- `services/quant-api/app/api/market.py` — additive `lifecycle` field under `/research/subing`.
- `services/quant-api/app/guiyi_cli/research_parser.py` — add `subing-lifecycle` read-only command.
- `services/quant-api/app/guiyi_cli/research_commands.py` — parse/render lifecycle Shadow request/result.
- `services/quant-api/app/guiyi_cli/main.py` — dispatch two research command families without changing `subing-calibration` behavior.
- `services/quant-api/tests/data_foundation/test_subing_read_service.py` — integration and Historical/Live identity regression.
- `services/quant-api/tests/test_subing_api.py` — additive API contract and 1d unavailable behavior.
- `services/quant-api/tests/test_research_cli.py` — existing CLI characterization plus lifecycle Shadow command.
- `apps/quant-web/src/types/market.ts` — lifecycle DTO/types/Decimal normalization.
- `apps/quant-web/src/components/market/SubingStatusStrip.vue` — research lifecycle strip while retaining formal V1 signal block.
- `apps/quant-web/src/components/market/SubingResearchSection.vue` — lifecycle funnel and evidence facts.
- `apps/quant-web/src/pages/market/chart.vue` — supply lifecycle research markers alongside existing persistent Alert markers.
- `apps/quant-web/src/components/kline/KlineChart.vue` — only if needed to merge a third marker source; do not change formal marker semantics.
- `apps/quant-web/tests/subingResearch.test.ts`
- `apps/quant-web/e2e/market-research.spec.mjs`
- `TESTING.md` — add exact lifecycle verification commands after executable work exists.
- `docs/ARCHITECTURE.md` — final closure only: describe lifecycle as research-only read-model; do not change current production claims.
- `STATUS.md` — only Task 9 may record actual develop implementation completion after all tests/review; never claim release/Runtime promotion.

---

### Task 1: Exact Research Policy and Immutable Lifecycle Contracts

**Lane:** Lane 3 — strategy semantics. Sol/high, new session, Plan-only until this Task is explicitly approved.

**Files:**
- Create: `data/research_policies/subing_lifecycle_v2_research_v1.json`
- Create: `services/quant-api/app/market_data/subing_lifecycle_policy.py`
- Create: `services/quant-api/app/market_data/subing_lifecycle.py`
- Create: `services/quant-api/tests/test_subing_lifecycle_policy.py`
- Test: `services/quant-api/tests/test_subing_lifecycle.py`

**Interfaces:**

Produces exact policy loader:

```python
@dataclass(frozen=True, slots=True)
class SubingLifecyclePolicy:
    policy_id: str
    formula_version: str
    research_only: bool
    supported_timeframes: tuple[BarFrequency, BarFrequency]
    clock_timeframe: BarFrequency
    trend_anchor_timeframe: BarFrequency
    hold_required_bars: int
    retest_rebreak_max_bars: int
    lower_tf_risk_consecutive_bars: int
    pivot_left_span: int
    pivot_right_span: int
    pivot_tie_policy: str


def load_subing_lifecycle_policy(path: Path | None = None) -> SubingLifecyclePolicy: ...
```

Produces lifecycle public domain contracts used by Tasks 2–8:

```python
class LifecycleAvailability(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"

class LifecycleStage(StrEnum):
    IDLE = "idle"
    SETUP_ARMED = "setup_armed"
    ENTRY_CONFIRMED = "entry_confirmed"
    CONTINUATION = "continuation"
    EXIT_RISK = "exit_risk"
    CLOSED = "closed"

class EntryProgress(StrEnum):
    WAITING_TRIGGER = "waiting_trigger"
    HOLD_CONFIRMING = "hold_confirming"
    RETEST_CONFIRMING = "retest_confirming"

class ConfirmationSource(StrEnum):
    FORMAL_V1 = "formal_v1"
    MOMENTUM_HOLD = "momentum_hold"
    PIVOT_BREAK_HOLD = "pivot_break_hold"
    PIVOT_RETEST_REBREAK = "pivot_retest_rebreak"

@dataclass(frozen=True, slots=True)
class SubingOpportunityKey:
    policy_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    direction: SubingDirection
    origin_at: datetime
```

- [ ] **Step 1: Write policy RED tests**

Tests must reject missing file, malformed JSON, extra/missing keys, wrong schema version, wrong `policy_id`, `research_only=false`, timeframes other than exact `5m/15m`, non-5m clock, non-15m anchor, hold/retest values other than approved baseline, risk count other than 2, pivot spans other than 2/2, tie policy other than `reject`, and same-ID semantic drift.

Representative assertion:

```python
def test_load_exact_lifecycle_policy() -> None:
    policy = load_subing_lifecycle_policy()
    assert policy.policy_id == "subing_lifecycle_v2_research_v1"
    assert policy.formula_version == "subing_lifecycle_v2"
    assert policy.research_only is True
    assert policy.hold_required_bars == 3
    assert policy.retest_rebreak_max_bars == 3
    assert policy.lower_tf_risk_consecutive_bars == 2
    assert (policy.pivot_left_span, policy.pivot_right_span) == (2, 2)
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py
```

Expected: import/file failure because the policy module does not exist yet.

- [ ] **Step 3: Add exact JSON policy**

Write the approved values only:

```json
{
  "schema_version": 1,
  "policy_id": "subing_lifecycle_v2_research_v1",
  "formula_version": "subing_lifecycle_v2",
  "research_only": true,
  "supported_timeframes": ["5m", "15m"],
  "clock_timeframe": "5m",
  "trend_anchor_timeframe": "15m",
  "setup": {
    "requires_both_timeframes": true,
    "calibration_id": "subing_intraday_v1"
  },
  "pivot": {
    "source_timeframe": "5m",
    "left_span": 2,
    "right_span": 2,
    "tie_policy": "reject",
    "same_trading_day_only": true,
    "breakout_basis": "close_cross"
  },
  "entry_confirmation": {
    "hold_required_bars": 3,
    "hold_count_includes_trigger_bar": true,
    "retest_rebreak_max_bars": 3,
    "unavailable_boundary_policy": "pause",
    "trigger_priority": ["formal_v1", "pivot_break", "macd_cross"]
  },
  "risk": {
    "lower_tf_consecutive_bars": 2,
    "anchor_soft_risk_immediate": true,
    "recovery_requires_completed_15m": true
  },
  "trading_day": {
    "unconfirmed_setup_cross_trading_day": false,
    "confirmed_opportunity_cross_trading_day": true
  }
}
```

- [ ] **Step 4: Implement strict loader**

Follow the existing accepted Calibration pattern: exact shape, Decimal/integer validation, immutable dataclass, one project path, no environment/HTTP override. Stable invalid state:

```python
class SubingLifecyclePolicyError(ValueError):
    code = "SUBING_LIFECYCLE_POLICY_INVALID"
```

- [ ] **Step 5: Add immutable state/identity contract tests**

Test invalid combinations such as `SETUP_ARMED + direction=NONE`, `ENTRY_CONFIRMED` without opportunity key, non-directional opportunity key, naive datetimes, and mutation attempts raising `FrozenInstanceError`.

- [ ] **Step 6: Implement only domain types; no reducer yet**

`subing_lifecycle.py` in this Task contains enums/dataclasses/validators only. It must not import DB, FastAPI, Redis, API schemas or Alert code.

- [ ] **Step 7: Verify Task 1**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_lifecycle.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/subing_lifecycle_policy.py \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_lifecycle.py

git diff --check
```

- [ ] **Step 8: Independent Review and commit**

Review must confirm Critical=0 / Important=0, no V1 import-cycle or policy drift, then commit only Task 1 files:

```bash
git add \
  data/research_policies/subing_lifecycle_v2_research_v1.json \
  services/quant-api/app/market_data/subing_lifecycle_policy.py \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_lifecycle.py
git commit -m "feat(research): add SuBing lifecycle contracts"
```

---

### Task 2: Confirmed Pivot, Breakout and Retest Pure Kernel

**Lane:** Lane 3 — causal structure/repainting risk. Sol/high, new session, independent Review.

**Files:**
- Create: `services/quant-api/app/market_data/subing_structure.py`
- Create: `services/quant-api/tests/test_subing_structure.py`
- Modify: `services/quant-api/app/market_data/subing_lifecycle.py` only for shared typed references if required.

**Interfaces:**

```python
class PivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True, slots=True)
class ConfirmedPivot:
    pivot_id: str
    kind: PivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date

@dataclass(frozen=True, slots=True)
class BreakoutAssessment:
    pivot_id: str
    observed_at: datetime
    direction: SubingDirection
    reference_price: Decimal
    intrabar_touched: bool
    close_beyond_level: bool
    crossed_on_close: bool
    volume_ratio_prev: Decimal | None
    open_interest_delta: Decimal | None

@dataclass(frozen=True, slots=True)
class RetestAssessment:
    pivot_id: str
    observed_at: datetime
    touched_reference: bool
    close_preserved_side: bool
    hard_invalidated: bool


def confirmed_pivots(...)->tuple[ConfirmedPivot, ...]: ...
def assess_pivot_breakout(...)->BreakoutAssessment: ...
def assess_pivot_retest(...)->RetestAssessment: ...
```

- [ ] **Step 1: Write strict Pivot RED tests**

Cover exact 2-left/2-right HIGH/LOW, equal-high/equal-low tie rejection, first/last two bars never confirmed, `pivot_time` at center and `confirmed_at` at right span completion, segment identity retained, and no cross-trading-day reference selection.

- [ ] **Step 2: Add prefix-invariance RED test**

```python
def test_confirmed_pivots_are_prefix_invariant() -> None:
    prefix = bars[:8]
    before = confirmed_pivots(prefix, ...)
    after = confirmed_pivots(bars, ...)
    assert tuple(p for p in after if p.confirmed_at <= prefix[-1].bar_end) == before
```

Also explicitly prove a Pivot confirmed at current boundary cannot be used for a breakout on that same boundary.

- [ ] **Step 3: Implement single-pass Pivot generation**

Only completed 5m bars are accepted. No ZigZag, ATR, range clustering, preview persistence or future-tail rewrite.

- [ ] **Step 4: Write Breakout/Retest RED tests**

Breakout LONG must require:

```python
previous.close <= pivot.price and current.close > pivot.price
```

SHORT mirrors. Intrabar touch without close cross must remain evidence-only. Retest must match the exact close-preserved-side definitions from the Spec.

- [ ] **Step 5: Implement Breakout/Retest**

Compute `open_interest_delta` only when both current and previous OI are non-null; never invent an OI threshold.

- [ ] **Step 6: Verify pure kernel and V1 non-regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_research.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/subing_structure.py \
  services/quant-api/tests/test_subing_structure.py

git diff --check
```

- [ ] **Step 7: Independent Review and commit**

Review specifically checks future-function/repainting and confirms no StructuralRange/N-pattern scope creep.

```bash
git add \
  services/quant-api/app/market_data/subing_structure.py \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_structure.py
git commit -m "feat(research): add causal SuBing structure kernel"
```

---

### Task 3: Setup and Entry Lifecycle Reducer

**Lane:** Lane 3 — strategy formula/state transitions. Sol/high, new session, independent Review.

**Files:**
- Modify: `services/quant-api/app/market_data/subing_lifecycle.py`
- Test: `services/quant-api/tests/test_subing_lifecycle.py`

**Interfaces:**

The pure evaluator signature is fixed here for later Tasks:

```python
def evaluate_subing_lifecycle(
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    bars_5m: Sequence[CanonicalBar],
    factors_5m: Sequence[SubingFactorResult],
    bars_15m: Sequence[CanonicalBar],
    factors_15m: Sequence[SubingFactorResult],
    calibration: SubingCalibration,
    policy: SubingLifecyclePolicy,
) -> SubingLifecycleTrace: ...
```

The reducer may call existing `evaluate_subing_signal()` and `resolve_same_boundary_subing_signals()`; it must not copy their formulas.

- [ ] **Step 1: Write alignment and clock RED tests**

Cover:

```text
5m is only top-level clock
latest completed 15m <= current 5m boundary
same 15m boundary evaluates once
future 15m is never visible
one top-level transition per 5m boundary
```

- [ ] **Step 2: Write Direction Context RED tests**

LONG/SHORT require both periods to pass existing accepted slope threshold + EMA21 side + slope10 direction. Missing alignment yields `READY/NONE/IDLE`; actual data/policy identity failure yields `UNAVAILABLE`.

- [ ] **Step 3: Write Opportunity identity RED tests**

```text
SETUP_ARMED origin_at = first departure from IDLE
IDLE → FORMAL_V1 ENTRY_CONFIRMED origin_at = confirmed_at
policy/symbol/contract/segment/direction/origin_at are immutable
CLOSED old direction cannot be reused for a new opposite opportunity
```

- [ ] **Step 4: Implement IDLE/SETUP and FORMAL_V1 bridge**

Trigger priority starts with current V1 only:

```python
if formal_v1 is not None:
    return confirm_entry(source=ConfirmationSource.FORMAL_V1, ...)
```

This does not create AlertEvent; it only represents the V1 fact inside the research trace.

- [ ] **Step 5: Write MOMENTUM_HOLD RED tests**

Trigger on same-direction MACD cross from either 5m or 15m, count trigger bar as 1, require three evaluable 5m boundaries with persistence context, pause on unavailable, fail on opposite trigger/persistence hard failure.

- [ ] **Step 6: Implement MOMENTUM_HOLD**

No volume/OI hard gate. Record them only as supporting evidence.

- [ ] **Step 7: Write PIVOT_BREAK_HOLD and RETEST RED tests**

Cover:

```text
reference Pivot must have confirmed_at < trigger boundary
true close cross required
reference Pivot frozen at trigger
legal retest beats hold_count increment
3-bar hold confirms
retest bar excluded from rebreak window
rebreak reference fixed to trigger high/low
3 evaluable bars max after retest
hard close through Pivot invalidates
```

- [ ] **Step 8: Implement PIVOT paths and trigger priority**

Exact order:

```text
FORMAL_V1
PIVOT_BREAK
MACD_CROSS
```

Do not run parallel confirmation machines.

- [ ] **Step 9: Add unconfirmed trading-day rollover**

At the first **evaluable** 5m boundary of a later `trading_day`, a same-direction `FORMAL_V1` match first confirms the existing setup and sets `crossed_trading_day=true`. Otherwise, including an opposite-direction Formal match, close the old setup as `UNCONFIRMED_TRADING_DAY_ROLLOVER`; a new direction may start no earlier than the next evaluable boundary. An unavailable boundary pauses and neither confirms nor closes.

- [ ] **Step 10: Verify Task 3**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_research.py

git diff --check
```

- [ ] **Step 11: Independent Review and commit**

Review must explicitly answer: future leakage=none; confirmed-at backfill=none; V1 formula copies=none; top-level transitions per boundary <=1.

```bash
git add \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_lifecycle.py
git commit -m "feat(research): add SuBing entry lifecycle reducer"
```

---

### Task 4: Continuation, Exit Risk, Recovery and Hard Close

**Lane:** Lane 3 — strategy lifecycle semantics. Sol/high, new session, independent Review.

**Files:**
- Modify: `services/quant-api/app/market_data/subing_lifecycle.py`
- Test: `services/quant-api/tests/test_subing_lifecycle.py`

- [ ] **Step 1: Write ENTRY_CONFIRMED → CONTINUATION RED test**

`ENTRY_CONFIRMED` exists only on confirmation boundary. Next evaluable boundary with no risk/hard close becomes `CONTINUATION`.

- [ ] **Step 2: Write lower-TF risk RED tests**

Risk candidates:

```text
LOWER_TF_EMA21_BREACH
LOWER_TF_SLOPE5_REVERSAL
LOWER_TF_MACD_OPPOSITE_CROSS
LOWER_TF_BOUND_PIVOT_REENTRY
```

First evaluable 5m risk -> `risk_progress=WATCHING`, still `CONTINUATION`; two consecutive evaluable risk boundaries -> `EXIT_RISK`. A clean boundary resets the count. Unavailable pauses without reset or increment.

- [ ] **Step 3: Write 15m anchor soft-risk RED tests**

On a completed 15m boundary, any approved anchor soft risk may move directly to `EXIT_RISK`. Non-15m boundary must not synthesize an anchor update.

- [ ] **Step 4: Write recovery RED tests**

Recovery only at completed 15m boundary and requires no hard close, correct anchor EMA21 side, slope10 direction, no 15m opposite MACD cross, no current lower-TF risk, and bound Pivot side preserved for Pivot-confirmed opportunities.

- [ ] **Step 5: Write hard-close priority RED tests**

Exact priority:

```text
OPPOSITE_FORMAL_V1
OPPOSITE_DIRECTION_CONTEXT_CONFIRMED
ANCHOR_TREND_BROKEN
STRUCTURE_INVALIDATED
```

Test a single boundary satisfying multiple close facts and assert the first reason wins deterministically.

- [ ] **Step 6: Implement continuation/risk/close**

`ANCHOR_TREND_BROKEN` LONG is exact `15m close < EMA21 AND slope10 < 0`; SHORT mirrors. `STRUCTURE_INVALIDATED` only applies to Pivot-confirmed opportunities and uses completed 15m close through the bound Pivot.

- [ ] **Step 7: Add confirmed cross-trading-day behavior**

Confirmed `ENTRY_CONFIRMED/CONTINUATION/EXIT_RISK` may continue across `trading_day` within the same segment and sets `crossed_trading_day=true`; no automatic close.

- [ ] **Step 8: Add full prefix-invariance test matrix**

For every prefix T in a deterministic fixture, evaluate prefix and full series; compare all Pivot/opportunity/transition facts with `transition_at <= T`. Existing facts may only be appended to, never moved/deleted/rewritten.

- [ ] **Step 9: Verify Task 4**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_research.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_lifecycle.py

git diff --check
```

- [ ] **Step 10: Independent Review and commit**

```bash
git add \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/tests/test_subing_lifecycle.py
git commit -m "feat(research): complete SuBing lifecycle states"
```

---

### Task 5: Integrate Lifecycle into the Existing SuBing Read Seam

**Lane:** Lane 3 — current-rank1 Historical/Live identity and existing formal signal seam. Sol/high, new session, independent Review.

**Files:**
- Modify: `services/quant-api/app/market_data/subing_read_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_read_service.py`
- Test: all existing V1 tests.

**Produces:** `SubingReadSnapshot.lifecycle: SubingLifecycleSnapshot` while preserving every existing V1 field.

- [ ] **Step 1: Characterize current V1 snapshot before refactor**

Add/retain tests that lock:

```text
current rank1 segment only
post-segment history fails closed
companion cutoff
live contract mismatch fallback
completed live merge
same-boundary reciprocal resolver
primary_signal remains requested timeframe
resolved_signal remains optional actual matched opportunity
D1 historical-only behavior
```

- [ ] **Step 2: Write lifecycle integration RED tests**

For 5m and 15m request at the same `now`, assert the new lifecycle key/stage are identical because lifecycle clock is independent of requested V1 primary timeframe. For D1 assert lifecycle is `UNAVAILABLE` with `SUBING_LIFECYCLE_INTRADAY_ONLY` while existing D1 V1 output is unchanged.

- [ ] **Step 3: Refactor one private aligned-input seam**

Use a private immutable helper/dataclass inside `subing_read_service.py`; do not create a second public read service. It must return the exact current contract/segment and merged completed 5m/15m sequences required by both V1 latest projection and V2 lifecycle.

Representative shape:

```python
@dataclass(frozen=True, slots=True)
class _AlignedIntradaySeries:
    bars_5m: tuple[CanonicalBar, ...]
    bars_15m: tuple[CanonicalBar, ...]
    latest_5m_source: str
    latest_15m_source: str
    source_mode: str
```

- [ ] **Step 4: Compute Factor series once per timeframe**

Use existing `calculate_subing_factor_series()` for full aligned input and take the final result for existing V1 `primary`/`companion`. Do not alter EMA/MACD formula, Calibration or resolver.

- [ ] **Step 5: Call pure lifecycle reducer**

Pass only immutable bars/factors/calibration/policy. If lifecycle-specific policy is unavailable, return lifecycle `UNAVAILABLE` without degrading existing V1 Factor/Signal unless the existing V1 dependency itself is invalid.

- [ ] **Step 6: Add Historical/Live equivalence tests**

Same completed Bar prefix represented as all-canonical vs canonical+completed-live must produce the same lifecycle trace/snapshot facts. Same 15m boundary must not depend on simulated 5m/15m arrival order after the existing bounded companion refresh contract resolves.

- [ ] **Step 7: Verify full V1 backend regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_alert_runtime.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/subing_lifecycle.py \
  services/quant-api/app/market_data/subing_structure.py

git diff --check
```

- [ ] **Step 8: Independent Review and commit**

Review diff against pre-Task V1 behavior; any V1 Signal/Alert output change blocks integration.

```bash
git add \
  services/quant-api/app/market_data/subing_read_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
git commit -m "feat(research): project SuBing lifecycle snapshot"
```

---

### Task 6: Additive Market API Lifecycle Contract

**Lane:** Lane 2 — normal API/read-only Web contract. Terra/medium, Plan-then-execute.

**Files:**
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/tests/test_subing_api.py`

**Interfaces:** Add only `lifecycle` under existing `SubingResearchResponse`; do not rename/delete existing fields.

Pydantic DTOs include at least:

```python
class SubingLifecycleTransitionOut(BaseModel):
    transition_id: str
    transition_at: datetime
    from_stage: str
    to_stage: str
    reason_codes: list[str]

class SubingLifecycleSnapshotOut(BaseModel):
    formula_version: str
    policy_id: str
    research_only: bool
    availability: str
    unavailable_reason: str | None
    direction: str
    stage: str
    opportunity_key: str | None
    entry_progress: str | None
    trigger_kind: str | None
    trigger_timeframe: str | None
    triggered_at: datetime | None
    confirmation_source: str | None
    confirmed_at: datetime | None
    hold_count: int
    hold_required: int
    current_risk_codes: list[str]
    risk_progress: str | None
    lower_tf_risk_count: int
    last_confirmed_stage: str
    last_confirmed_at: datetime | None
    latest_transition: SubingLifecycleTransitionOut | None
    crossed_trading_day: bool
    boundary_reset: str | None
    formal_v1_matched: bool
```

- [ ] **Step 1: Write API RED tests**

Assert:

```text
existing response fields unchanged
lifecycle.research_only == true
5m/15m same-now lifecycle identity same
1d lifecycle unavailable/intraday-only
V2 research confirmation never appears as AlertEvent/result_codes
Decimal evidence serializes predictably
```

- [ ] **Step 2: Add Pydantic models and mapper**

Keep mapper code in `app/api/market.py`; do not move lifecycle logic into API.

- [ ] **Step 3: Verify API and formal Alert regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_runtime.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py

git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/tests/test_subing_api.py
git commit -m "feat(api): expose SuBing lifecycle research snapshot"
```

---

### Task 7: Web Lifecycle Strip, Funnel and Research Markers

**Lane:** Lane 2 — Web/read-only UI. Terra/medium, Plan-then-execute.

**Files:**
- Create: `apps/quant-web/src/components/market/SubingLifecyclePanel.vue`
- Create: `apps/quant-web/src/utils/subingLifecycleMarkers.ts`
- Create: `apps/quant-web/tests/subingLifecycle.test.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/components/market/SubingStatusStrip.vue`
- Modify: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify only if required: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/tests/subingResearch.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

- [ ] **Step 1: Add TS lifecycle types and Decimal normalization RED tests**

Add types matching backend enums exactly. `normalizeSubingResearch()` must convert lifecycle Decimal evidence/reference prices without mutating existing Factor normalization.

- [ ] **Step 2: Implement types/normalization**

Keep V1 `subingSignalLabel()` untouched. Add separate research labels:

```typescript
export function subingLifecycleStageLabel(stage: SubingLifecycleStage): string {
  switch (stage) {
    case 'setup_armed': return '准备中'
    case 'entry_confirmed': return '研究确认'
    case 'continuation': return '延续'
    case 'exit_risk': return '退出风险'
    case 'closed': return '本轮结束'
    default: return '暂无机会'
  }
}
```

No lifecycle label may use “买入信号/卖出信号/下单/加仓/平仓指令”.

- [ ] **Step 3: Build `SubingLifecyclePanel.vue`**

Display only current snapshot facts:

```text
方向
阶段
触发来源
确认进度 X/3
绑定前高/前低（如有）
风险 codes
最近状态转换
Research only 标签
```

Do not render full trace history by default.

- [ ] **Step 4: Update StatusStrip and ResearchSection**

`SubingStatusStrip` keeps current formal V1 signal block and adds a visually separate research lifecycle line. `SubingResearchSection` hosts the lifecycle funnel and evidence detail.

- [ ] **Step 5: Write research marker RED tests**

`subingLifecycleMarkers.ts` maps lifecycle facts to neutral/research markers:

```text
SETUP_ARMED       → “准备”
PIVOT_BREAK       → “前高/前低突破”
ENTRY_CONFIRMED   → “研究确认”
EXIT_RISK         → “风险”
CLOSED            → “结束”
```

V2 markers use neutral/research tone and must never look like persistent formal Alert markers. Existing `alertEventsToMarkers()` remains unchanged.

- [ ] **Step 6: Wire markers into chart composition**

In `chart.vue`, combine lifecycle markers with `persistentAlertMarkers` only at presentation time. If `KlineChart` needs a generic third marker prop, extend it additively; do not change existing alert marker identity, tone or labels.

- [ ] **Step 7: Web unit verification**

```bash
pnpm --dir apps/quant-web test
```

Expected: all existing Web unit tests plus lifecycle tests pass.

- [ ] **Step 8: Browser verification**

Extend `market-research.spec.mjs` to assert:

```text
formal V1 buy/sell wording still present when formal signal exists
V2 research confirmation is visibly research-only
setup/hold progress shown
risk/closed display works
1d lifecycle unavailable does not break existing Factor panel
no horizontal overflow at existing acceptance viewports
```

Run:

```bash
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs \
  e2e/alert-v1.spec.mjs

pnpm --dir apps/quant-web build
```

- [ ] **Step 9: Commit**

```bash
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/components/market/SubingLifecyclePanel.vue \
  apps/quant-web/src/components/market/SubingStatusStrip.vue \
  apps/quant-web/src/components/market/SubingResearchSection.vue \
  apps/quant-web/src/utils/subingLifecycleMarkers.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/tests/subingLifecycle.test.ts \
  apps/quant-web/tests/subingResearch.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): show SuBing lifecycle research"
```

If `KlineChart.vue` was not changed, omit it from staging.

---

### Task 8: Read-only Historical Shadow Research CLI

**Lane:** Lane 1 research, but use Sol/high because leakage/prefix/OOS interpretation matters. New session, Plan-then-execute.

**Files:**
- Create: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class LifecycleResearchRequest:
    since: date
    through: date
    symbol: str | None

@dataclass(frozen=True, slots=True)
class SubingLifecycleResearchResult:
    products: tuple[str, ...]
    segment_count: int
    evaluable_boundary_count: int
    funnel_counts: Mapping[str, int]
    confirmation_source_counts: Mapping[str, int]
    v1_v2_overlap_counts: Mapping[str, int]
    close_reason_counts: Mapping[str, int]
    horizon_summary: Mapping[int, HorizonEvaluation]
```

- [ ] **Step 1: Write service RED tests**

Follow current `SubingCalibrationResearchService` pattern:

```text
MarketDataService only
actual_dominant Historical only
resolved_contract_segments required
run each rank1 segment independently
no cross-segment warmup/lifecycle
no Live/RQData/Redis
active products when symbol omitted
single validated symbol when supplied
```

- [ ] **Step 2: Implement historical service**

For each segment, query 5m and 15m Historical Canonical, compute Factor series, run `evaluate_subing_lifecycle()`, aggregate the funnel. Reuse existing 3/5/8 horizon outcome semantics; do not call this a formal backtest or account PnL.

Required funnel:

```text
DATA_READY
DIRECTION_CONTEXT_ALIGNED
SETUP_ARMED
TRIGGER_OBSERVED
ENTRY_CONFIRMED
```

Required confirmation counts:

```text
FORMAL_V1
MOMENTUM_HOLD
PIVOT_BREAK_HOLD
PIVOT_RETEST_REBREAK
```

Required overlap buckets:

```text
V1_AND_V2
V2_ONLY
V1_ONLY
```

- [ ] **Step 3: Extend CLI parser RED tests**

Existing parser choice test changes from exactly `{subing-calibration}` to exactly:

```python
{"subing-calibration", "subing-lifecycle"}
```

New command syntax:

```bash
guiyi research subing-lifecycle \
  --since 2026-01-01 \
  --through 2026-03-31 \
  [--symbol jm]
```

No policy override flags.

- [ ] **Step 4: Generalize CLI dispatch without breaking calibration**

Do not replace existing Calibration request/result formats. Dispatch by `research_command` and construct the correct service lazily so invalid CLI input exits 2 before service construction.

- [ ] **Step 5: JSON renderer tests**

Required envelope:

```json
{
  "schema_version": 1,
  "command": "research.subing-lifecycle",
  "status": "ok",
  "readonly": true,
  "policy_id": "subing_lifecycle_v2_research_v1"
}
```

All Decimal values render as strings. No write path, no “profitability/ready/promotion” conclusion.

- [ ] **Step 6: Verify both research commands**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/market_data/subing_lifecycle_research_service.py

git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_lifecycle_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat(research): add SuBing lifecycle shadow report"
```

---

### Task 9: Full Regression, Canonical Closure and Independent Final Review

**Lane:** Lane 3 review. Sol/high, new independent Review session. No implementation expansion.

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `STATUS.md` only after all actual develop checks pass
- Review: all Task 1–8 changes

- [ ] **Step 1: Update project verification entry points**

Add lifecycle backend/read/CLI tests to the existing SuBing verification section in `TESTING.md`; do not duplicate the whole test guide.

- [ ] **Step 2: Update architecture narrowly**

Add one research-only lifecycle node alongside `SubingReadService`; state explicitly that AlertRuntime still consumes only V1 `resolved_signal` and lifecycle has no persistence/notification path.

- [ ] **Step 3: Run complete SuBing/backend verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 4: Run static verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/api/market.py
```

- [ ] **Step 5: Run full Web verification**

```bash
pnpm --dir apps/quant-web test

pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs \
  e2e/alert-v1.spec.mjs

pnpm --dir apps/quant-web build
```

- [ ] **Step 6: Run repository hygiene**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 7: Independent final review**

Review against the approved Spec, not this Plan alone. Required final findings:

```text
Critical = 0
Important = 0
```

Reviewer must explicitly confirm:

```text
V1 formula diff = none
Alert Rule/Scope diff = none
AlertRuntime lifecycle dependency = none
lifecycle DB/Redis/queue = none
future leakage / confirmed backfill = none
same-boundary double transition = none
cross-roll inheritance = none
research markers distinguishable from formal signal markers = yes
Shadow CLI readonly = true
```

- [ ] **Step 8: Record only actual develop truth**

If all verification/review passes, `STATUS.md` may state that SuBing Lifecycle V2 research-only code exists on develop and is not released/promoted. It must not claim formal Rule readiness, profitability, Runtime deployment or live `jm` evidence.

- [ ] **Step 9: Commit closure**

```bash
git add TESTING.md docs/ARCHITECTURE.md STATUS.md
git commit -m "docs: close SuBing lifecycle v2 development"
```

- [ ] **Step 10: Stop before real observation**

Do not reload local API/Web, do not run a real current-market Shadow observation, do not change Runtime, Scope or notification. Present the verified develop result to the user. Real `jm` observation is a separate explicit Gate/task.

---

## Acceptance Summary

Implementation is complete on `develop` only when all of these are true:

```text
V1 Factor / Signal / resolver unchanged
subing_entry_signal_v1 unchanged
Alert Runtime / Scope / Clawbot unchanged
Lifecycle Policy exact and research_only
5m unique clock / 15m anchor enforced
ConfirmedPivot prefix-invariant
FORMAL_V1 / MOMENTUM_HOLD / PIVOT_BREAK_HOLD / PIVOT_RETEST_REBREAK covered
unavailable pauses state and counters
unconfirmed setup does not cross trading_day
confirmed opportunity may cross trading_day within same segment
5m risk debounce + 15m recovery covered
hard-close priority deterministic
no cross-roll lifecycle
API additive only
Web distinguishes formal V1 from V2 research
Shadow CLI readonly and Historical-only
no lifecycle DB/cache/worker/queue
backend/Web/static/hygiene checks green
final independent review Critical=0 / Important=0
```

This acceptance authorizes only integration into `develop`. It does not authorize release/tag, production Runtime promotion, real notification, Scope mutation, production DB/Canonical writes or any order action.
