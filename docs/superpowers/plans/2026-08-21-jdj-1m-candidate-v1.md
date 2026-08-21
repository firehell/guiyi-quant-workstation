# Phase 6 — JDJ 1m Research & Candidate V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、existing N Structure V1、SuBing、Alert/Runtime 的前提下，把用户冻结的三条 JDJ 1m 入场方法实现为三个独立、严格 causal、research-only Candidate，并形成 `jm` retrospective / 10-fold rolling / prospective-freeze baseline。

**Architecture:** 复用 `MarketDataService → ActualDominantResearchSegmentLoader` 一次读取 exact 1m/5m actual-dominant；同一 rank1 segment 内用 existing `ema_series` 计算 1m EMA20，并复用 `evaluate_n_structure_segment()` 生成 5m N Structure/Swing facts。新增 JDJ context projector 与三个纯 reducer；source research 只输出 immutable trigger facts 和 post-event price outcomes，Candidate Validation 复用 existing rolling/prospective schedule，不建立第二 Historical Gateway、第二 N、backtest/fill engine 或通用 Strategy Platform。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、`guiyi_quant.indicators.ema_series`、existing N Structure V1、MarketDataService、ActualDominantResearchSegmentLoader、argparse CLI、pytest、Ruff、Mypy、Git-tracked exact JSON research contracts。

**Spec:** `docs/superpowers/specs/2026-08-21-jdj-1m-candidate-v1-design.md`

**Task Contract:** `docs/tasks/TASK-JDJ-1M-CANDIDATE-V1-20260821.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 和最新 `develop`；active canonical 冲突时 `BLOCKED_CANONICAL_DRIFT`。
- 唯一业务来源是 `TREND_FOLLOW`、`TREND_REENTRY_6`、`KEY_LEVEL_BREAKOUT`；其他交易策略、资金管理、止盈止损、加仓、每日次数/目标全部不进入 V1。
- 市场固定国内期货 actual-dominant；Historical 唯一入口为 `MarketDataService`；禁止 direct Parquet/RQData/Redis Live/glob/自判主力。
- EMA 固定 existing `ema_series(period=20, seed_policy="sma_window", round_digits=6)`；不得复制 EMA 算法。
- 趋势固定 existing 5m N Structure V1；不得修改 N policy/formula/candidate/evidence。
- 5m→1m strict-before：当前 1m 只能使用 `observed_at <= previous_1m.bar_end` 的 pre-known N facts；same-boundary future use 是 Critical。
- Key Level 只能使用与 pre-known N snapshot **same epoch** 的 latest eligible confirmed N Swing Pivot；旧 epoch pivot 禁止复用。
- 所有 state 均 same trading day + physical contract + rank1 segment；任一变化立即 reset/terminal。
- previous-bar trigger 固定 dynamic strict breach；equal 不触发；`trigger_level` 不是 fill。
- Trend Follow/Reentry ARMED 使用 EMA20+trend invalidation；Key-Level accepted retest 后使用 frozen key-level+trend invalidation，**不得继承 EMA20 invalidation**。
- same-bar trigger/invalidation 无法确定路径时 fail-closed，不创建 Candidate event。
- Candidate identity 三条独立；禁止合并为一个 `jdj_1m_candidate_v1`。
- outcome reference=`trigger bar completed close`；horizon=`3/5/8/20 subsequent 1m bars`；trigger bar 不进入 future MFE/MAE；same-day/contract/segment/request-through。
- freeze 固定：`2026-08-21T09:34:00+08:00`；retrospective=`2023-01-01..2026-08-20`；embargo=`2026-08-21`；prospective first=`2026-08-24`；baseline through=`2026-08-21`。
- `2026-08-24` 必须通过 existing Instrument/TradingCalendar read-only 验证为 `jm` freeze 后首个 eligible trading day；失败即阻塞，不动态换日期。
- 不做 active60 Robustness V2、parameter sweep、winner/rank/KEEP/DROP/PROMOTE。
- 不新增 Web/API、DB、Redis、worker、Alert、PushPlus、Execution Review、order/account/position/cost/PnL。
- 不触及 `main`、tag、release、Runtime；task→develop 不授权外部 mutation。
- 策略公式/时序 Tasks 1–6 为 Lane 3：Codex 先 Plan-only，人工批准后才允许代码实现；实现后独立 Review C0/I0 才可集成 develop。

---

## Planned File Map

### New exact contracts

```text
data/research_policies/jdj_1m_policy_v1.json
data/research_candidates/jdj_trend_follow_1m_candidate_v1.json
data/research_candidates/jdj_trend_reentry_6_1m_candidate_v1.json
data/research_candidates/jdj_key_level_breakout_1m_candidate_v1.json
data/research_protocols/jdj_candidate_validation_v1.json
```

### New domain/source files

```text
services/quant-api/app/market_data/jdj_policy.py
services/quant-api/app/market_data/jdj_context.py
services/quant-api/app/market_data/jdj_events.py
services/quant-api/app/market_data/jdj_trend_follow.py
services/quant-api/app/market_data/jdj_trend_reentry.py
services/quant-api/app/market_data/jdj_key_level_breakout.py
services/quant-api/app/market_data/jdj_research.py
services/quant-api/app/market_data/jdj_research_service.py
services/quant-api/app/market_data/jdj_candidate_validation_policy.py
services/quant-api/app/market_data/jdj_candidate_validation.py
services/quant-api/app/market_data/jdj_candidate_validation_service.py
services/quant-api/app/market_data/jdj_candidate_validation_calendar.py
```

### New tests

```text
services/quant-api/tests/test_jdj_policy.py
services/quant-api/tests/test_jdj_context.py
services/quant-api/tests/test_jdj_trend_follow.py
services/quant-api/tests/test_jdj_trend_reentry.py
services/quant-api/tests/test_jdj_key_level_breakout.py
services/quant-api/tests/test_jdj_research.py
services/quant-api/tests/data_foundation/test_jdj_research_service.py
services/quant-api/tests/test_jdj_candidate_validation_policy.py
services/quant-api/tests/test_jdj_candidate_validation.py
services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py
services/quant-api/tests/data_foundation/test_jdj_candidate_validation_calendar.py
```

### Existing files intentionally modified

```text
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_research_cli.py
TESTING.md
STATUS.md
PROJECT_SOURCE.md
docs/ARCHITECTURE.md
```

### Evidence only in Task 10

```text
reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
```

---

# Task 1 — Freeze Exact Policy, Three Candidate Manifests and Validation Protocol

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后再实现
- 工作区：从最新 `develop` 创建 `research/jdj-v1-contracts` task worktree
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** exact JSON contracts, `jdj_policy.py`, `jdj_candidate_validation_policy.py`, two policy test files.

**Interfaces:**

```python
class JdjPolicyError(ValueError):
    code = "JDJ_POLICY_INVALID"

@dataclass(frozen=True, slots=True)
class JdjPolicy:
    schema_version: int
    policy_id: str
    formula_version: str
    research_only: bool
    source_timeframe: BarFrequency
    trend_context_timeframe: BarFrequency
    ema_period: int
    ema_seed_policy: str
    ema_round_digits: int
    strict_previous_bar_trigger: bool
    same_epoch_key_level: bool
    raw: Mapping[str, object]

def load_jdj_policy(path: Path | None = None) -> JdjPolicy: ...
def is_exact_jdj_policy(policy: object) -> bool: ...

@dataclass(frozen=True, slots=True)
class JdjCandidateManifest: ...
@dataclass(frozen=True, slots=True)
class JdjCandidateRef:
    candidate_id: str
    source_event_kind: str
@dataclass(frozen=True, slots=True)
class JdjCandidateValidationProtocol: ...

def load_jdj_candidate_manifest(candidate_id: str) -> JdjCandidateManifest: ...
def load_jdj_candidate_validation_protocol() -> JdjCandidateValidationProtocol: ...
```

- [ ] **Step 1: Create task worktree**

```bash
git fetch origin develop
git worktree add ../guiyi-jdj-v1-contracts -b research/jdj-v1-contracts origin/develop
cd ../guiyi-jdj-v1-contracts
git status --short
git rev-parse HEAD
```

- [ ] **Step 2: Write RED policy tests**

```python
def test_loads_exact_jdj_v1_policy() -> None:
    policy = load_jdj_policy()
    assert policy.policy_id == "jdj_1m_policy_v1"
    assert policy.formula_version == "jdj_1m_v1"
    assert policy.source_timeframe is BarFrequency.M1
    assert policy.trend_context_timeframe is BarFrequency.M5
    assert policy.ema_period == 20
    assert policy.ema_seed_policy == "sma_window"
    assert policy.ema_round_digits == 6
    assert policy.strict_previous_bar_trigger is True
    assert policy.same_epoch_key_level is True
    assert policy.research_only is True
```

Parameterize missing/extra/wrong-type mutations for **every** nested policy field. Any formula drift must raise `JDJ_POLICY_INVALID` with sanitized cause/path.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_jdj_policy.py
```

- [ ] **Step 4: Create exact policy JSON that mechanically freezes all three formulas**

The exact payload must include these sections and values; the loader compares the complete nested object, including key order/type/value:

```json
{
  "schema_version": 1,
  "policy_id": "jdj_1m_policy_v1",
  "formula_version": "jdj_1m_v1",
  "research_only": true,
  "source_timeframe": "1m",
  "trend_context_timeframe": "5m",
  "trend_context": {
    "policy_id": "n_structure_5m_v1",
    "formula_version": "n_structure_v1",
    "strict_before": true,
    "same_epoch_key_level": true
  },
  "ema": {
    "kind": "ema",
    "period": 20,
    "seed_policy": "sma_window",
    "round_digits": 6,
    "input_field": "close"
  },
  "previous_bar_trigger": {
    "dynamic_reference": true,
    "equal_is_breach": false,
    "fill_model": false
  },
  "state_boundary": {
    "same_trading_day": true,
    "same_physical_contract": true,
    "same_rank1_segment": true
  },
  "trend_follow": {
    "reaction": "ema_touch_and_close_on_trend_side",
    "armed_invalidation": "ema_close_failure_or_trend_lost",
    "same_bar_trigger_invalidation": "ambiguous_no_event"
  },
  "trend_reentry_6": {
    "trend_side_prerequisite": true,
    "excursion_reference": "opposite_ema_side_extreme",
    "reclaim": "first_close_back_on_trend_side",
    "reclaim_bar_can_react": false,
    "first_post_reclaim_reaction_only": true,
    "failed_first_reaction_terminal": true,
    "armed_invalidation": "ema_close_failure_or_trend_lost"
  },
  "key_level_breakout": {
    "pivot_source": "latest_same_epoch_confirmed_n_swing",
    "post_confirmation_origin_side_required": true,
    "first_break_basis": "close_cross",
    "first_break_creates_entry": false,
    "first_break_bar_can_retest": false,
    "volume_rule": "all_first_break_do_not_chase",
    "retest": "touch_level_and_close_on_breakout_side",
    "failed_retest": "close_not_on_breakout_side",
    "same_pivot_single_episode": true,
    "armed_invalidation": "close_back_through_frozen_level_or_trend_lost"
  },
  "outcome": {
    "reference_price": "trigger_bar_close",
    "horizons_bars": [3, 5, 8, 20],
    "trigger_bar_in_future_window": false,
    "same_trading_day": true,
    "same_physical_contract": true,
    "same_rank1_segment": true
  },
  "parameter_sweep": false,
  "automatic_ranking": false,
  "automatic_promotion": false
}
```

This prevents code formula drift under an unchanged `jdj_1m_policy_v1` identity.

- [ ] **Step 5: RED Candidate/Protocol tests**

```python
EXPECTED_IDS = (
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
EXPECTED_EVENTS = (
    "jdj_trend_follow_triggered",
    "jdj_trend_reentry_6_triggered",
    "jdj_key_level_breakout_triggered",
)

def test_protocol_freezes_three_candidate_event_pairs_and_dates() -> None:
    p = load_jdj_candidate_validation_protocol()
    assert tuple(x.candidate_id for x in p.candidates) == EXPECTED_IDS
    assert tuple(x.source_event_kind for x in p.candidates) == EXPECTED_EVENTS
    assert p.candidate_frozen_at.isoformat() == "2026-08-21T09:34:00+08:00"
    assert p.retrospective_since == date(2023, 1, 1)
    assert p.retrospective_through == date(2026, 8, 20)
    assert p.embargo_trading_days == (date(2026, 8, 21),)
    assert p.prospective_oos_first_trading_day == date(2026, 8, 24)
    assert p.baseline_request_through == date(2026, 8, 21)
    assert p.horizons_bars == (3, 5, 8, 20)
```

- [ ] **Step 6: Implement fixed-path strict loaders**

Three manifests use exact `source_kind=jdj_1m`, `policy_id=jdj_1m_policy_v1`, `formula_version=jdj_1m_v1`, `research_only=true`. Protocol contains exact ordered candidate/event refs, anchor `jm`, 12/3/3 rolling config, freeze dates, horizons and `automatic_ranking=false`, `automatic_promotion=false`. Unknown candidate id fails; no directory scan/registry.

- [ ] **Step 7: GREEN, Ruff, secret scan, diff-check**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_policy.py \
  services/quant-api/app/market_data/jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Independent Review C0/I0, commit, integrate develop, cleanup**

```bash
git add data/research_policies/jdj_1m_policy_v1.json data/research_candidates/jdj_*_candidate_v1.json \
  data/research_protocols/jdj_candidate_validation_v1.json \
  services/quant-api/app/market_data/jdj_policy.py \
  services/quant-api/app/market_data/jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_policy.py services/quant-api/tests/test_jdj_candidate_validation_policy.py
git commit -m 'feat(research): freeze JDJ 1m v1 contracts'
```

---

# Task 2 — Build Causal 1m/5m Context Projection

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：`research/jdj-v1-context` from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** `jdj_context.py`, `test_jdj_context.py`; existing N/EMA files remain unchanged.

**Interfaces:**

```python
class JdjContextError(ValueError):
    code = "JDJ_CONTEXT_INVALID"

@dataclass(frozen=True, slots=True)
class JdjBarContext:
    bar: CanonicalBar
    ema20: Decimal | None
    trend_kind: NStructureKind
    trend_snapshot_observed_at: datetime | None
    trend_epoch: int | None
    eligible_high_pivot: NSwingPivot | None
    eligible_low_pivot: NSwingPivot | None

def build_jdj_context_series(
    bars_1m: Sequence[CanonicalBar],
    bars_5m: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
    jdj_policy: JdjPolicy,
    n_policy: NStructurePolicy,
) -> tuple[JdjBarContext, ...]: ...
```

- [ ] **Step 1: RED EMA20 exact parity/readiness** using direct `ema_series` and `Decimal(str(point.value))` comparison for every 1m boundary.
- [ ] **Step 2: RED strict-before 09:35/09:36 test**: snapshot confirmed 09:35 is invisible to 09:35 1m, visible from 09:36.
- [ ] **Step 3: RED same-epoch pivot test**: outside reset makes old epoch pivot ineligible; new matching-epoch pivot becomes eligible only after strict-before confirmation.
- [ ] **Step 4: RED invalid series/policy/identity tests**: non-monotonic bars, wrong contract/segment day, non-exact JDJ/N policy all raise `JDJ_CONTEXT_INVALID`.
- [ ] **Step 5: Implement one-pass projection**:

```python
n_trace = evaluate_n_structure_segment(...)
ema = ema_series(...)
```

Advance snapshot/pivot pointers only while `fact_time <= previous_1m.bar_end`; pivot must match snapshot epoch. Choose latest eligible pivot by `(confirmed_at, pivot_time, pivot_id)`.
- [ ] **Step 6: Prefix causality test**: future 1m/5m suffix cannot alter earlier contexts.
- [ ] **Step 7: GREEN + N/EMA regressions + Review C0/I0**.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/test_n_structure_state.py
git diff --check
```

---

# Task 3 — TREND_FOLLOW Pure Reducer

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** create `jdj_events.py`, `jdj_trend_follow.py`, `test_jdj_trend_follow.py`.

**Interfaces:**

```python
class JdjDirection(StrEnum):
    LONG = "long"
    SHORT = "short"

class JdjSetupKind(StrEnum):
    TREND_FOLLOW = "trend_follow"
    TREND_REENTRY_6 = "trend_reentry_6"
    KEY_LEVEL_BREAKOUT = "key_level_breakout"

@dataclass(frozen=True, slots=True)
class JdjTrendFollowTriggerEvent:
    event_id: str
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    reaction_at: datetime
    ema20_at_reaction: Decimal
    trigger_level: Decimal
    observation_close: Decimal

@dataclass(frozen=True, slots=True)
class JdjTrendFollowTrace:
    events: tuple[JdjTrendFollowTriggerEvent, ...]
    ambiguous_count: int
    invalidated_count: int

def reduce_jdj_trend_follow(contexts: Sequence[JdjBarContext], *, symbol: str, contract: str, segment_start_trading_day: date) -> JdjTrendFollowTrace: ...
```

- [ ] **Step 1:** RED LONG/SHORT EMA reaction tests.
- [ ] **Step 2:** RED dynamic previous-bar strict trigger; equal does not trigger; later trigger uses latest previous bar, not reaction bar.
- [ ] **Step 3:** RED trend/EMA invalidation and same-bar trigger+invalidation ambiguity.
- [ ] **Step 4:** Implement explicit `_Armed` state; reaction bar cannot trigger; terminal state allows later new reaction episode.
- [ ] **Step 5:** Event id uses deterministic business fields; no UUID/hash/run counter.
- [ ] **Step 6:** RED trading-day reset, LONG/SHORT symmetry, prefix stability.
- [ ] **Step 7:** GREEN + Review C0/I0.

---

# Task 4 — TREND_REENTRY_6 Pure Reducer

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** modify `jdj_events.py`; create `jdj_trend_reentry.py`, `test_jdj_trend_reentry.py`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class JdjTrendReentryTriggerEvent:
    event_id: str
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    excursion_started_at: datetime
    excursion_extreme: Decimal
    reclaimed_at: datetime
    reaction_at: datetime
    trigger_level: Decimal
    observation_close: Decimal

def reduce_jdj_trend_reentry_6(...) -> JdjTrendReentryTrace: ...
```

- [ ] **Step 1:** RED trend-side prerequisite; starting below/above EMA cannot infer prior crossing.
- [ ] **Step 2:** RED excursion extreme aggregation.
- [ ] **Step 3:** RED reclaim; reclaim bar cannot be reaction.
- [ ] **Step 4:** RED first post-reclaim reaction only; `reaction.low > excursion_low` / `reaction.high < excursion_high`; first failure terminal.
- [ ] **Step 5:** RED reclaim failure starts a new independent excursion.
- [ ] **Step 6:** Implement explicit phases `WAIT_TREND_SIDE/WAIT_EXCURSION/IN_EXCURSION/WAIT_REACTION/ARMED`.
- [ ] **Step 7:** ARMED reuses dynamic previous-bar trigger + EMA/trend invalidation + same-bar ambiguity, not Trend Follow state object.
- [ ] **Step 8:** symmetry/prefix/event-id stability tests.
- [ ] **Step 9:** GREEN + Review C0/I0.

---

# Task 5 — KEY_LEVEL_BREAKOUT Second-Chance Reducer

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** modify `jdj_events.py`; create `jdj_key_level_breakout.py`, `test_jdj_key_level_breakout.py`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class JdjKeyLevelBreakoutTriggerEvent:
    event_id: str
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    trend_epoch: int
    key_level_pivot_id: str
    key_level_price: Decimal
    key_level_confirmed_at: datetime
    first_break_at: datetime
    retest_at: datetime
    trigger_level: Decimal
    observation_close: Decimal

def reduce_jdj_key_level_breakout(...) -> JdjKeyLevelBreakoutTrace: ...
```

- [ ] **Step 1:** RED eligible pivot exact kind + same epoch + strict-before.
- [ ] **Step 2:** RED post-confirmation origin-side prerequisite.
- [ ] **Step 3:** RED FIRST_BREAK uses close transition; first break never emits Candidate event; intrabar high/low alone not enough.
- [ ] **Step 4:** RED first-break bar cannot retest; freeze pivot/level; later pivot cannot replace active episode.
- [ ] **Step 5:** RED accepted/failed retest exact mirror rules.
- [ ] **Step 6:** RED ARMED invalidation exact: frozen key-level/trend only; EMA20 must have no effect. Trigger+key-level invalidation same bar → ambiguous/no event.
- [ ] **Step 7:** RED no-retest/context expiry, same-pivot consumption, new-pivot new episode.
- [ ] **Step 8:** Implement phases `WAIT_ORIGIN_SIDE/WAIT_FIRST_BREAK/WAIT_RETEST/ARMED`; no volume threshold/proximity/timeout.
- [ ] **Step 9:** symmetry/prefix/determinism tests.
- [ ] **Step 10:** GREEN + Review C0/I0.

---

# Task 6 — JDJ Read-only Research Service and 3/5/8/20 Outcomes

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:** create `jdj_research.py`, `jdj_research_service.py`, tests; modify `jdj_events.py` to add the union alias.

**Interfaces:**

```python
JdjTriggerEvent: TypeAlias = (
    JdjTrendFollowTriggerEvent
    | JdjTrendReentryTriggerEvent
    | JdjKeyLevelBreakoutTriggerEvent
)

class JdjSourceUnavailableError(RuntimeError):
    code = "JDJ_SOURCE_UNAVAILABLE"

@dataclass(frozen=True, slots=True)
class JdjResearchRequest:
    since: date
    through: date
    symbol: str
    candidate_id: str

@dataclass(frozen=True, slots=True)
class JdjResearchResult:
    candidate_id: str
    source_event_kind: str
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    trigger_count_long: int
    trigger_count_short: int
    horizon_summary: Mapping[int, PriceHorizonEvaluation]
    events: tuple[JdjTriggerEvent, ...]

class JdjResearchService:
    def run(self, request: JdjResearchRequest) -> JdjResearchResult: ...
```

- [ ] **Step 1:** RED request identity; unknown candidate/date/symbol invalid before loader call.
- [ ] **Step 2:** RED loader called once with `(M1, M5)` and restored true segment prefix.
- [ ] **Step 3:** RED exact candidate→reducer→source_event isolation.
- [ ] **Step 4:** Implement deterministic partition by returned exact `ResolvedContractSegment`; uncovered M1/M5 bar raises context/segment error, never re-resolves rank1.
- [ ] **Step 5:** RED outcomes call existing `build_price_outcomes_at(..., horizons=(3,5,8,20), same_trading_day_only=True)` at trigger-bar index.
- [ ] **Step 6:** Trim bars to request.through before outcome evaluation; no later-bar completion past requested waterline.
- [ ] **Step 7:** Source error mapping only `MarketDataError`/`ActualDominantResearchSegmentIdentityError`→`JDJ_SOURCE_UNAVAILABLE`; `JdjContextError` stays stable context error; unexpected programming errors propagate.
- [ ] **Step 8:** RED deterministic event ordering `(observed_at, segment_bar_index, event_id)` and prefix stability.
- [ ] **Step 9:** GREEN/Mypy/Ruff + Review C0/I0.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_price_outcome.py
```

---

# Task 7 — Candidate Validation, Rolling/OOS and Calendar Freeze Check

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话 + 独立 Review 会话
- Plan：Plan-then-execute
- 工作区：new task worktree from latest develop
- 人工 Gate：独立 Review；不授权 OOS backfill/promotion

**Files:** create three candidate validation Python files, `jdj_candidate_validation_calendar.py`, four tests including calendar test.

**Interfaces:**

```python
class JdjProspectiveCalendarError(ValueError):
    code = "JDJ_PROSPECTIVE_CALENDAR_INVALID"

def assert_jdj_prospective_calendar(session: Session) -> None: ...

@dataclass(frozen=True, slots=True)
class JdjCandidateWindowResult: ...
@dataclass(frozen=True, slots=True)
class JdjRollingCandidateFold: ...
@dataclass(frozen=True, slots=True)
class JdjCandidateStabilitySummary: ...
class JdjProspectiveOosStatus(StrEnum):
    PENDING = "pending"
    EVALUATED = "evaluated"
@dataclass(frozen=True, slots=True)
class JdjProspectiveOosResult: ...
@dataclass(frozen=True, slots=True)
class JdjCandidateValidationReport: ...

class JdjCandidateValidationService:
    def run(self, request: CandidateValidationRequest) -> JdjCandidateValidationReport: ...
```

- [ ] **Step 1:** RED immutable window/report contracts; horizon keys exact `(3,5,8,20)`; no decision fields.
- [ ] **Step 2:** RED shared exact 10 folds via `build_rolling_validation_windows`.
- [ ] **Step 3:** RED baseline request: retrospective source through 2026-08-20 + 20 rolling source calls; no prospective source call at baseline through 2026-08-21.
- [ ] **Step 4:** Implement exact candidate/protocol identity pairing; wrong cross-pair fails before source.
- [ ] **Step 5:** Candidate service only maps `JdjSourceUnavailableError` and `JdjContextError` to `CandidateValidationSourceError`; unexpected errors propagate.
- [ ] **Step 6:** Implement `assert_jdj_prospective_calendar(session)` using existing `Instrument` to resolve `jm` exchange and existing `TradingCalendar` to prove 2026-08-21 trading, 22/23 non-eligible, 24 trading. Read-only only; missing/duplicate/conflicting facts fail stable error.
- [ ] **Step 7:** Allowed quality flags only `PROSPECTIVE_OOS_PENDING`, `ROLLING_FOLD_WITHOUT_EVENT`, `HORIZON_WITHOUT_SAMPLE`.
- [ ] **Step 8:** GREEN + OOS Review C0/I0.

---

# Task 8 — Composition and Read-only CLI

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Terra
- 推理强度：中
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：new task worktree from latest develop
- 人工 Gate：无真实写入 Gate；tests+self-review 后可集成 develop

**Files:** `composition.py`, research parser/commands/main, `test_research_cli.py`.

- [ ] **Step 1:** RED research command set becomes exact seven commands with `jdj-1m`.
- [ ] **Step 2:** RED `jdj-1m` accepts exact 3 candidates + symbol/since/through; rejects formula runtime flags.
- [ ] **Step 3:** Add 3 JDJ candidates and `jdj_candidate_validation_v1` to candidate-validation parser choices; cross-pairs still fail service identity.
- [ ] **Step 4:** Composition:

```python
def build_jdj_research_service(session: Session) -> JdjResearchService: ...
def build_jdj_candidate_validation_service(session: Session, candidate_id: str) -> JdjCandidateValidationService:
    assert_jdj_prospective_calendar(session)
    ...
```

Reuse one MDS per builder; no registry/plugin.
- [ ] **Step 5:** Add `JdjResearchRequest` to `ResearchRequest` union and deterministic JSON renderer; Decimal fields as strings.
- [ ] **Step 6:** Candidate renderer recognizes `JdjCandidateValidationReport` and emits exact 3/5/8/20 data.
- [ ] **Step 7:** `main()` adds typed JDJ factories and routes exact three ids; invalid arguments fail before service construction.
- [ ] **Step 8:** RED no data manager/Runtime/Alert/notification construction on JDJ research paths.
- [ ] **Step 9:** GREEN + full CLI/Mypy/Ruff/secret_scan/diff-check.

---

# Task 9 — Cumulative Verification and Independent Implementation Review

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开独立 Review 会话
- Plan：Review-only
- 工作区：clean detached worktree at exact develop
- 人工 Gate：Critical=0 / Important=0

**Files:** modify `TESTING.md`; code/tests only if concrete review finding requires a dedicated fix branch.

- [ ] **Step 1:** detached exact-develop review worktree and record SHA.
- [ ] **Step 2:** run all JDJ focused tests.
- [ ] **Step 3:** run existing N full-chain regression.
- [ ] **Step 4:** run existing SuBing Candidate Validation + Multi-Candidate Robustness V1 regressions.
- [ ] **Step 5:** run Ruff, Mypy, secret scan, `git diff --check` fresh.
- [ ] **Step 6:** Review Critical list: future leak, cross identity/day leakage, N identity mutation, OOS backfill, optimistic OHLC ordering, fill/order semantics, production boundary.
- [ ] **Step 7:** Review Important list: EMA drift, cross-epoch pivot, Key-Level EMA invalidation, first-break direct entry, Reentry first-reaction skip, broad exception swallowing, candidate mixing, trigger-bar outcome leak, nondeterminism, duplicate resolver.
- [ ] **Step 8:** if finding exists, fix in separate branch, rerun affected+cumulative suite and Review again.
- [ ] **Step 9:** add exact `## JDJ 1m Research & Candidate V1` test block to TESTING.md; state fixtures/read-only do not authorize real evidence/release/Runtime/Alert.

---

# Task 10 — Exact-develop Evidence, Evidence Review and Canonical Closeout

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新 evidence 会话 + 独立 Evidence Review
- Plan：Plan-then-execute
- 工作区：independent evidence branch/worktree from exact accepted develop
- 人工 Gate：Evidence Review C0/I0；不得 main/tag/Runtime promotion

**Files:** create three exact baseline JSON; update STATUS/PROJECT_SOURCE/ARCHITECTURE; TESTING only if evidence command text needs correction.

- [ ] **Step 1:** create clean evidence worktree and record exact develop SHA.
- [ ] **Step 2:** rerun Task 9 verification fresh; failure blocks evidence.
- [ ] **Step 3:** rerun existing SuBing/N exact baseline commands and `cmp` tracked artifacts; mismatch blocks and old artifacts are not modified.
- [ ] **Step 4:** run three JDJ exact commands:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_trend_follow_1m_candidate_v1 --protocol jdj_candidate_validation_v1 --symbol jm --through 2026-08-21 \
  > /tmp/jdj-trend-follow-v1.json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_trend_reentry_6_1m_candidate_v1 --protocol jdj_candidate_validation_v1 --symbol jm --through 2026-08-21 \
  > /tmp/jdj-trend-reentry-6-v1.json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_key_level_breakout_1m_candidate_v1 --protocol jdj_candidate_validation_v1 --symbol jm --through 2026-08-21 \
  > /tmp/jdj-key-level-breakout-v1.json
```

- [ ] **Step 5:** validate each artifact: exact candidate/protocol, `readonly/research_only=true`, retrospective 2023-01-01..2026-08-20, 10 folds, prospective `{pending, first=2026-08-24, through=2026-08-21, result=null}`, horizons 3/5/8/20, no decision/profit/fill/order keys.
- [ ] **Step 6:** rerun all 3 commands and `cmp`; record byte sizes and SHA-256 only after byte identity succeeds.
- [ ] **Step 7:** copy to exact three tracked report paths.
- [ ] **Step 8:** independent Evidence Review checks no OOS backfill, no cross-day/segment horizon, no old baseline mutation, deterministic artifacts; Gate C0/I0.
- [ ] **Step 9:** STATUS records exact code/test/evidence facts only; PROJECT_SOURCE adds readonly JDJ CLI; ARCHITECTURE adds N5m context→JDJ three Candidate→existing Validation. No profitability claim.
- [ ] **Step 10:** secret scan + diff check, commit evidence/docs, integrate develop, read back ancestry, cleanup. No main/tag/Runtime/Alert.

---

## Final Acceptance Criteria

```text
[ ] exact policy JSON mechanically freezes all three strategy formulas, context, outcome and safety flags
[ ] three exact Candidate manifests and event mappings are isolated
[ ] exact freeze dates / 10-fold / 3-5-8-20 protocol exist
[ ] EMA20 exact kernel parity
[ ] strict-before same-boundary-safe N context
[ ] same-epoch Key Level pivot eligibility
[ ] Trend Follow causal state/ambiguity
[ ] Reentry prerequisite/excursion/reclaim/first-reaction semantics
[ ] Key Level first-break no-chase/retest/frozen-level/no-EMA-invalidation semantics
[ ] source M1/M5 shared actual-dominant loader only
[ ] deterministic/prefix-stable immutable events
[ ] trigger-bar close reference; trigger bar excluded from future outcomes
[ ] no cross-day/contract/segment/request-through horizons
[ ] shared 10-fold scheduler only
[ ] 2026-08-24 metadata validation or fail-closed
[ ] baseline 2026-08-21 remains prospective pending; no backfill
[ ] readonly CLI routes exist
[ ] N/SuBing/Candidate/Robustness regressions pass
[ ] Implementation Review Critical=0 / Important=0
[ ] existing SuBing/N tracked baselines byte-identical
[ ] 3 JDJ tracked baselines byte-identical
[ ] Evidence Review Critical=0 / Important=0
[ ] canonical docs reflect exact state
[ ] no main/tag/Runtime/Alert/DB/Canonical/notification/order mutation
```

Final allowed statement:

```text
Phase 6 JDJ 1m Research & Candidate V1 已将三条 source-derived setup 转换为三个 exact causal Candidate，
形成 jm retrospective / 10-fold rolling baseline 并冻结 prospective OOS；全部结果仍为 research-only。
```

Final forbidden statement: 策略有效/盈利、某条最好、KEEP/DROP/PROMOTE、允许 Alert/交易、允许 main/tag 或 Runtime promotion。
