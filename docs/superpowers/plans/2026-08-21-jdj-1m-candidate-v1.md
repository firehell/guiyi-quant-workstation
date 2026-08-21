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
- `2026-08-24` 必须通过 protocol 内 exact RQData `get_trading_dates` freeze evidence 与 existing
  Instrument/TradingCalendar read-only cross-check 验证；Catalog 21..23 必须匹配，24 可暂缺但存在时
  必须匹配。失败即阻塞，不动态换日期，不向 Runtime/Alert 提供 Calendar 或 night-session facts。
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

**Files:** exact JSON contracts, `jdj_policy.py`, `jdj_candidate_validation_policy.py`, `test_jdj_policy.py`, `test_jdj_candidate_validation_policy.py`.

**Interfaces:** Task 1 must define these exact public names: `JdjPolicyError`, `JdjPolicy`, `load_jdj_policy(path: Path | None = None) -> JdjPolicy`, `is_exact_jdj_policy(policy: object) -> bool`, `JdjCandidateManifest`, `JdjCandidateRef`, `JdjCandidateValidationProtocol`, `load_jdj_candidate_manifest(candidate_id: str) -> JdjCandidateManifest`, `load_jdj_candidate_validation_protocol() -> JdjCandidateValidationProtocol`. `JdjCandidateRef` has exactly `candidate_id: str` and `source_event_kind: str`. `JdjPolicy` exposes the identity/EMA/context fields listed in the policy test below plus recursively frozen `raw`.

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

Expected: import/file failure because Task 1 implementation does not yet exist.

- [ ] **Step 4: Create exact policy JSON that mechanically freezes all three formulas**

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

Strict loader compares complete nested key/type/value shape and recursively freezes mappings/tuples. This mechanically prevents formula drift under unchanged identity.

- [ ] **Step 5: Write RED Candidate/Protocol tests**

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

def test_protocol_freezes_candidate_event_pairs_and_dates() -> None:
    protocol = load_jdj_candidate_validation_protocol()
    assert tuple(item.candidate_id for item in protocol.candidates) == EXPECTED_IDS
    assert tuple(item.source_event_kind for item in protocol.candidates) == EXPECTED_EVENTS
    assert protocol.candidate_frozen_at.isoformat() == "2026-08-21T09:34:00+08:00"
    assert protocol.retrospective_since == date(2023, 1, 1)
    assert protocol.retrospective_through == date(2026, 8, 20)
    assert protocol.embargo_trading_days == (date(2026, 8, 21),)
    assert protocol.prospective_oos_first_trading_day == date(2026, 8, 24)
    assert protocol.baseline_request_through == date(2026, 8, 21)
    assert protocol.horizons_bars == (3, 5, 8, 20)
```

- [ ] **Step 6: Implement fixed-path strict loaders**

Three manifests use exact `source_kind=jdj_1m`, `policy_id=jdj_1m_policy_v1`, `formula_version=jdj_1m_v1`, `research_only=true`. Protocol contains exact ordered candidate/event refs, anchor `jm`, 12/3/3 rolling config, freeze dates, horizons and `automatic_ranking=false`, `automatic_promotion=false`. Unknown candidate id raises the stable manifest error; no directory scan/registry.

- [ ] **Step 7: Run GREEN and static checks**

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

- [ ] **Step 8: Independent Review C0/I0, then commit/integrate/cleanup**

```bash
git add data/research_policies/jdj_1m_policy_v1.json data/research_candidates/jdj_*_candidate_v1.json \
  data/research_protocols/jdj_candidate_validation_v1.json \
  services/quant-api/app/market_data/jdj_policy.py \
  services/quant-api/app/market_data/jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_policy.py services/quant-api/tests/test_jdj_candidate_validation_policy.py
git commit -m 'feat(research): freeze JDJ 1m v1 contracts'
```

Read back develop ancestry after integration and clean the merged task worktree/branch. Do not touch main/tag/Runtime.

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

**Files:** create `jdj_context.py`, `test_jdj_context.py`; existing N/EMA files remain unchanged.

**Interfaces:** define `JdjContextError(ValueError)` with `code="JDJ_CONTEXT_INVALID"`. Define frozen `JdjBarContext` fields exactly: `bar: CanonicalBar`, `ema20: Decimal | None`, `trend_kind: NStructureKind`, `trend_snapshot_observed_at: datetime | None`, `trend_epoch: int | None`, `eligible_high_pivot: NSwingPivot | None`, `eligible_low_pivot: NSwingPivot | None`. Public function signature is `build_jdj_context_series(bars_1m: Sequence[CanonicalBar], bars_5m: Sequence[CanonicalBar], *, contract: str, segment_start_trading_day: date, segment_end_trading_day: date, jdj_policy: JdjPolicy, n_policy: NStructurePolicy) -> tuple[JdjBarContext, ...]`.

- [ ] **Step 1: Write RED EMA20 parity/readiness test** using direct `ema_series` and `Decimal(str(point.value))` comparison at every boundary.
- [ ] **Step 2: Run the context test and confirm RED** because `jdj_context` does not exist yet.
- [ ] **Step 3: Write RED strict-before 09:35/09:36 test**: a snapshot confirmed 09:35 is invisible to the 09:35 1m and visible from 09:36.
- [ ] **Step 4: Write RED same-epoch pivot test**: outside reset invalidates old-epoch level; new matching-epoch pivot becomes eligible only after its confirmation is strict-before.
- [ ] **Step 5: Implement EMA + N projection** with this exact kernel call:

```python
ema = ema_series(
    [float(bar.close) for bar in bars_1m],
    20,
    bar_ends=[bar.bar_end.isoformat() for bar in bars_1m],
    seed_policy="sma_window",
    indicator_code="ema20",
    round_digits=6,
)
```

Run `evaluate_n_structure_segment()` exactly once for the 5m segment. Iterate 1m in ascending order; advance snapshot/pivot pointers only while fact time is `<= previous_1m.bar_end`. Only pivots with `pivot.epoch == latest_snapshot.epoch` may be selected. Latest is deterministic by `(confirmed_at, pivot_time, pivot_id)`.
- [ ] **Step 6: Add fail-closed validation** for non-monotonic M1/M5, contract/segment mismatch, wrong exact policy and impossible snapshot/pivot identity; all map to `JDJ_CONTEXT_INVALID` without internal path detail.
- [ ] **Step 7: Add prefix-causality test**: future M1/M5 suffix cannot change earlier contexts.
- [ ] **Step 8: Run GREEN + N/EMA regressions + Review C0/I0**.

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

**Interfaces:** `JdjDirection={LONG,SHORT}` and `JdjSetupKind={TREND_FOLLOW,TREND_REENTRY_6,KEY_LEVEL_BREAKOUT}`. Frozen `JdjTrendFollowTriggerEvent` fields exactly: event/candidate/source-event identity, direction, symbol, contract, segment start/trading day, observed_at/index, trend snapshot observed_at, reaction_at, ema20_at_reaction, trigger_level, observation_close. Frozen `JdjTrendFollowTrace` fields: `events`, `ambiguous_count`, `invalidated_count`. Public reducer signature is `reduce_jdj_trend_follow(contexts: Sequence[JdjBarContext], *, symbol: str, contract: str, segment_start_trading_day: date) -> JdjTrendFollowTrace`.

- [ ] **Step 1: Write RED LONG/SHORT EMA reaction tests**.
- [ ] **Step 2: Write RED dynamic previous-bar strict trigger test**; equal high/low does not trigger; after one non-trigger bar, next trigger references that latest previous bar rather than original reaction bar.
- [ ] **Step 3: Write RED invalidation/ambiguity tests** for trend loss, `close<=EMA20` LONG / `close>=EMA20` SHORT, and trigger+invalidation same OHLC.
- [ ] **Step 4: Implement explicit armed state** storing direction, reaction time, reaction EMA and trend snapshot time. The reaction boundary cannot also trigger.
- [ ] **Step 5: Implement deterministic event id** from candidate/symbol/contract/segment/direction/reaction_at/observed_at/trigger_level; no random UUID, Python hash or run counter.
- [ ] **Step 6: Write RED day-reset, LONG/SHORT symmetry and prefix tests**.
- [ ] **Step 7: Run GREEN and independent formula Review C0/I0**.

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

**Interfaces:** frozen `JdjTrendReentryTriggerEvent` includes common event identity plus `trend_snapshot_observed_at`, `excursion_started_at`, `excursion_extreme`, `reclaimed_at`, `reaction_at`, `trigger_level`, `observation_close`. Public reducer signature is `reduce_jdj_trend_reentry_6(contexts: Sequence[JdjBarContext], *, symbol: str, contract: str, segment_start_trading_day: date) -> JdjTrendReentryTrace`.

- [ ] **Step 1: Write RED trend-side prerequisite test**; starting the day on the opposite EMA side cannot infer a prior crossing.
- [ ] **Step 2: Write RED excursion-extreme aggregation test**.
- [ ] **Step 3: Write RED reclaim test**; reclaim bar cannot be the post-reclaim reaction.
- [ ] **Step 4: Write RED first-post-reclaim reaction test**; first reaction must satisfy higher-low/lower-high against excursion extreme, otherwise terminal; later nicer reaction cannot be selected.
- [ ] **Step 5: Write RED reclaim-failure test**; crossing back before first reaction starts a new independent excursion at the current bar.
- [ ] **Step 6: Implement phases** `WAIT_TREND_SIDE`, `WAIT_EXCURSION`, `IN_EXCURSION`, `WAIT_REACTION`, `ARMED` with explicit direction and provenance.
- [ ] **Step 7: Implement ARMED logic** using the same exact dynamic previous-bar trigger and EMA/trend invalidation predicates as the policy, without calling or embedding Trend Follow state.
- [ ] **Step 8: Add symmetry/prefix/event-id tests**.
- [ ] **Step 9: Run GREEN + independent Review C0/I0**.

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

**Interfaces:** frozen `JdjKeyLevelBreakoutTriggerEvent` includes common event identity plus `trend_snapshot_observed_at`, `trend_epoch`, `key_level_pivot_id`, `key_level_price`, `key_level_confirmed_at`, `first_break_at`, `retest_at`, `trigger_level`, `observation_close`. Public reducer signature is `reduce_jdj_key_level_breakout(contexts: Sequence[JdjBarContext], *, symbol: str, contract: str, segment_start_trading_day: date) -> JdjKeyLevelBreakoutTrace`.

- [ ] **Step 1: Write RED eligible-pivot test** for exact kind + same epoch + strict-before.
- [ ] **Step 2: Write RED post-confirmation origin-side test**.
- [ ] **Step 3: Write RED FIRST_BREAK test**: only close transition confirms; first break never emits Candidate event; intrabar high/low alone is insufficient.
- [ ] **Step 4: Write RED freeze/no-chase test**: first-break bar cannot retest; active episode keeps frozen pivot/level even when later pivot appears.
- [ ] **Step 5: Write RED accepted/failed retest mirror tests**.
- [ ] **Step 6: Write RED ARMED invalidation test** proving EMA20 changes do not affect this setup; only frozen key-level/trend can invalidate. Trigger+key-level invalidation same bar is ambiguous/no event.
- [ ] **Step 7: Write RED no-retest/context-expiry/same-pivot-consumption tests**.
- [ ] **Step 8: Implement phases** `WAIT_ORIGIN_SIDE`, `WAIT_FIRST_BREAK`, `WAIT_RETEST`, `ARMED`; no volume threshold, proximity zone or fixed timeout.
- [ ] **Step 9: Add symmetry/prefix/determinism tests**.
- [ ] **Step 10: Run GREEN + independent Review C0/I0**.

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

**Files:** create `jdj_research.py`, `jdj_research_service.py`, `test_jdj_research.py`, `data_foundation/test_jdj_research_service.py`; modify `jdj_events.py` to add the exact union alias.

**Interfaces:** define `JdjTriggerEvent` as the exact union of the three trigger-event dataclasses. Define `JdjSourceUnavailableError(RuntimeError)` with code `JDJ_SOURCE_UNAVAILABLE`. Frozen `JdjResearchRequest` fields are `since`, `through`, `symbol`, `candidate_id`. Frozen `JdjResearchResult` fields are `candidate_id`, `source_event_kind`, `products`, `segment_count`, `evaluable_bar_count`, `trigger_count_long`, `trigger_count_short`, `horizon_summary`, `events`. Public service method is `JdjResearchService.run(request: JdjResearchRequest) -> JdjResearchResult`.

- [ ] **Step 1: Write RED request identity tests**; invalid candidate/date/symbol fails before loader call.
- [ ] **Step 2: Write RED loader-call test** requiring exactly `(BarFrequency.M1, BarFrequency.M5)` once per symbol/window and restored true segment prefix.
- [ ] **Step 3: Write RED candidate→reducer→source-event isolation tests**.
- [ ] **Step 4: Implement deterministic partition by returned `ResolvedContractSegment`**; uncovered M1/M5 bar is an identity error and never triggers a second rank1 resolution.
- [ ] **Step 5: Write RED price-outcome test** calling existing `build_price_outcomes_at` at the trigger-bar index with `(3,5,8,20)` and `same_trading_day_only=True`.
- [ ] **Step 6: Write RED request-through cutoff test**; bars later than request.through cannot complete a horizon.
- [ ] **Step 7: Implement typed source error boundary**: only `MarketDataError` and `ActualDominantResearchSegmentIdentityError` convert to `JDJ_SOURCE_UNAVAILABLE`; `JdjContextError` remains its own stable context error; programming exceptions propagate.
- [ ] **Step 8: Add deterministic event ordering and prefix tests** using `(observed_at, segment_bar_index, event_id)`.
- [ ] **Step 9: Run GREEN, Mypy, Ruff and independent Review C0/I0**.

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

**Files:** create `jdj_candidate_validation.py`, `jdj_candidate_validation_service.py`, `jdj_candidate_validation_calendar.py`, `test_jdj_candidate_validation.py`, `data_foundation/test_jdj_candidate_validation_service.py`, `data_foundation/test_jdj_candidate_validation_calendar.py`.

**Interfaces:** define `JdjProspectiveCalendarError(ValueError)` with code `JDJ_PROSPECTIVE_CALENDAR_INVALID` and exact function signature `assert_jdj_prospective_calendar(session: Session) -> None`. Define frozen `JdjCandidateWindowResult`, `JdjRollingCandidateFold`, `JdjCandidateStabilitySummary`, `JdjProspectiveOosResult`, `JdjCandidateValidationReport`, plus enum `JdjProspectiveOosStatus={PENDING,EVALUATED}`. Public validation method is `JdjCandidateValidationService.run(request: CandidateValidationRequest) -> JdjCandidateValidationReport`.

- [ ] **Step 1: Write RED immutable window/report tests**; exact `(3,5,8,20)` horizon keys and no decision fields.
- [ ] **Step 2: Write RED exact rolling test** reusing `build_rolling_validation_windows` and asserting existing fold_01..fold_10 boundaries.
- [ ] **Step 3: Write RED baseline-call test**: one retrospective through 2026-08-20 + 20 rolling source calls; no prospective source call at baseline through 2026-08-21.
- [ ] **Step 4: Implement exact candidate/protocol pairing**; wrong cross-pair fails before source call.
- [ ] **Step 5: Implement validation source exception policy**; only `JdjSourceUnavailableError` and `JdjContextError` convert to shared `CandidateValidationSourceError`; programming errors propagate.
- [ ] **Step 6: Write RED calendar facts/evidence tests** using exact protocol RQData evidence and isolated/fake session rows for `jm` Instrument and TradingCalendar.
- [ ] **Step 7: Implement read-only `assert_jdj_prospective_calendar`** to prove 2026-08-21 trading,
  22/23 non-eligible and 24 trading；Catalog 21..23 are required，24 may be absent until provider Session
  readiness but must match if present。Missing/drift/duplicate/conflicting evidence or Catalog facts fail stable
  error and never alter the frozen date or metadata tables.
- [ ] **Step 8: Implement structural-only quality flags**: `PROSPECTIVE_OOS_PENDING`, `ROLLING_FOLD_WITHOUT_EVENT`, `HORIZON_WITHOUT_SAMPLE`.
- [ ] **Step 9: Run GREEN + OOS Review C0/I0**.

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

**Files:** modify `composition.py`, `research_parser.py`, `research_commands.py`, `main.py`, `test_research_cli.py`.

- [ ] **Step 1: Write RED command-set test**: research commands become exact seven with `jdj-1m`.
- [ ] **Step 2: Write RED `jdj-1m` parser tests**: exact 3 candidates + symbol/since/through; reject `--ema-period`, `--volume-multiple`, `--timeout-bars`, `--trend-method`, `--key-level-distance`.
- [ ] **Step 3: Write RED Candidate Validation parser/identity tests** for the three JDJ ids and `jdj_candidate_validation_v1`; wrong cross-pair reaches identity error before source construction.
- [ ] **Step 4: Implement exact composition builders** with public signatures `build_jdj_research_service(session: Session) -> JdjResearchService` and `build_jdj_candidate_validation_service(session: Session, candidate_id: str) -> JdjCandidateValidationService`. The validation builder first calls `assert_jdj_prospective_calendar(session)`. Reuse one MDS inside each builder and do not create a registry/plugin.
- [ ] **Step 5: Add `JdjResearchRequest` to ResearchRequest union and implement deterministic source JSON rendering** with `readonly=true`, `research_only=true`; Decimal fields serialize as strings.
- [ ] **Step 6: Add JDJ Candidate Validation renderer** before generic SuBing fallback; emit exact 3/5/8/20 horizon data.
- [ ] **Step 7: Add typed factories/routing in `main()`** for source and exact three Candidate ids.
- [ ] **Step 8: Write RED no-side-effect factory test** proving JDJ research does not construct data manager/Runtime/Alert/notification paths.
- [ ] **Step 9: Run GREEN + CLI/Mypy/Ruff/secret_scan/diff-check**.

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

**Files:** modify `TESTING.md`; code/tests only if a concrete review finding is fixed on a separate branch.

- [ ] **Step 1: Create detached exact-develop Review worktree and record SHA**.
- [ ] **Step 2: Run all JDJ focused tests fresh**.
- [ ] **Step 3: Run existing N full-chain regression fresh**.
- [ ] **Step 4: Run existing SuBing Candidate Validation + Multi-Candidate Robustness V1 regressions fresh**.
- [ ] **Step 5: Run Ruff, Mypy, secret scan, `git diff --check` fresh**.
- [ ] **Step 6: Review Critical list**: future leak, cross identity/day leakage, N identity mutation, OOS backfill, optimistic OHLC ordering, fill/order semantics, production boundary.
- [ ] **Step 7: Review Important list**: EMA drift, cross-epoch pivot, Key-Level EMA invalidation, first-break direct entry, Reentry first-reaction skip, broad exception swallowing, candidate mixing, trigger-bar outcome leak, nondeterminism, duplicate resolver.
- [ ] **Step 8: If finding exists, fix it in a dedicated branch, rerun affected+cumulative suites and repeat Review until C0/I0**.
- [ ] **Step 9: Add exact `## JDJ 1m Research & Candidate V1` block to TESTING.md** and state tests are fixture/read-only and do not authorize real evidence/release/Runtime/Alert.

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

**Files:** create three exact baseline JSON; update STATUS/PROJECT_SOURCE/ARCHITECTURE; TESTING only if evidence command text itself needs correction.

**Calendar remediation prerequisite:** perform one explicitly authorized read-only RQData
`get_trading_dates(2026-08-21, 2026-08-24)` probe。Only exact returned trading days
`[2026-08-21, 2026-08-24]` may be frozen into the existing protocol。This probe does not authorize
Catalog/Canonical/Runtime writes；the Runtime current-day metadata transaction and
`NEXT_TRADING_SESSION_NOT_READY` behavior remain unchanged.

- [ ] **Step 1: Create clean evidence worktree and record exact develop SHA**.
- [ ] **Step 2: Rerun Task 9 verification fresh**; any failure blocks evidence.
- [ ] **Step 3: Rerun existing SuBing/N exact baseline commands and `cmp` tracked artifacts**; mismatch blocks and old artifacts remain unchanged.
- [ ] **Step 4: Run three exact JDJ baseline commands**:

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

- [ ] **Step 5: Validate each artifact**: exact candidate/protocol, `readonly/research_only=true`, retrospective 2023-01-01..2026-08-20, 10 folds, prospective pending/first 2026-08-24/through 2026-08-21/result null, horizons 3/5/8/20, no decision/profit/fill/order keys.
- [ ] **Step 6: Rerun all three commands and `cmp`**; record byte sizes and SHA-256 only after byte identity succeeds.
- [ ] **Step 7: Copy exact files to the three tracked report paths** from Planned File Map.
- [ ] **Step 8: Independent Evidence Review** checks no OOS backfill, no cross-day/segment horizon, no old baseline mutation, deterministic artifacts; Gate C0/I0.
- [ ] **Step 9: Canonical closeout**: STATUS records exact code/test/evidence facts only; PROJECT_SOURCE adds readonly JDJ CLI; ARCHITECTURE adds N5m context→JDJ three Candidate→existing Validation. No profitability claim.
- [ ] **Step 10: Run secret scan + diff-check, commit evidence/docs, integrate develop, read back ancestry and cleanup**. No main/tag/Runtime/Alert.

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
