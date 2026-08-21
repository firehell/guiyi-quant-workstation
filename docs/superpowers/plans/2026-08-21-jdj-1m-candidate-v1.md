# Phase 6 — JDJ 1m Research & Candidate V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、existing N Structure V1、SuBing、Alert/Runtime 的前提下，把用户冻结的三条 JDJ 1m 入场方法实现为三个独立、严格 causal、research-only Candidate，并形成 `jm` retrospective / 10-fold rolling / prospective-freeze baseline。

**Architecture:** 复用 `MarketDataService → ActualDominantResearchSegmentLoader` 一次读取 exact 1m/5m actual-dominant，同一 rank1 segment 内用现有 `ema_series` 计算 1m EMA20，并复用 existing `evaluate_n_structure_segment()` 生成 5m N Structure/Swing facts。新增 JDJ context projection 与三个纯 reducer；source research 只输出 immutable trigger facts 和 post-event price outcomes，Candidate Validation 复用现有 rolling/prospective schedule，不建立第二 Historical Gateway、第二 N、backtest/fill engine 或策略平台。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、`guiyi_quant.indicators.ema_series`、existing N Structure V1、MarketDataService、ActualDominantResearchSegmentLoader、argparse CLI、pytest、Ruff、Mypy、Git-tracked exact JSON research contracts。

**Spec:** `docs/superpowers/specs/2026-08-21-jdj-1m-candidate-v1-design.md`

**Task Contract:** `docs/tasks/TASK-JDJ-1M-CANDIDATE-V1-20260821.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 和最新 `develop`；active canonical 冲突时 `BLOCKED_CANONICAL_DRIFT`，不得猜测。
- 唯一业务来源是用户 2026-08-21 明确保留的三条：`TREND_FOLLOW`、`TREND_REENTRY_6`、`KEY_LEVEL_BREAKOUT`；止盈止损、仓位、加仓、每日次数/盈利目标、VWAP/ABC/三角形/多空陷阱等全部禁止进入 V1。
- 市场固定国内期货 actual-dominant；不得增加 QQQ、美股 provider 或第二套 Data Foundation。
- Historical 唯一入口仍为 `MarketDataService`；禁止 direct Parquet、RQData、Redis Live、glob、自判主力或跨频回退。
- JDJ 1m MA 固定 `EMA20`，exact kernel=`ema_series(period=20, seed_policy="sma_window", round_digits=6)`；不得复制 EMA 公式或换 seed。
- 趋势固定复用 existing 5m N Structure V1：`BULL→LONG only`、`BEAR→SHORT only`、`RANGE/UNDEFINED→no setup`；不得修改 N policy/formula/evidence。
- 5m→1m 必须 strict-before：当前 1m 只能使用 `observed_at <= previous_1m.bar_end` 的 pre-known N facts；same-boundary future use 是 Critical。
- key level 只能来自与当前 pre-known N snapshot **same epoch** 的 latest eligible 5m N Swing Pivot；outside-bar epoch reset 后旧 pivot 不再 eligible。
- 所有 JDJ state 均为 same trading day + same physical contract + same rank1 segment；任一变化立即 reset/terminal，不跨日。
- previous-bar trigger 固定 dynamic strict breach；equal 不触发；`trigger_level` 不是 fill price。
- Trend Follow / Reentry 的 armed invalidation 使用 EMA20 + pre-known trend；Key-Level accepted retest 后不使用 EMA20 invalidation，使用 frozen key-level + pre-known trend/context 自身失效语义。
- same-bar OHLC 无法判定 trigger/invalidation 顺序时 fail-closed，不创建 Candidate Entry Event。
- 三条 Candidate identity 独立，禁止合并为一个 `jdj_1m_candidate_v1`。
- outcome reference=`trigger bar completed close`；horizons=`3/5/8/20 subsequent 1m bars`；trigger bar 本身 high/low 不进入 future MFE/MAE；same-day、same-contract、same-segment。
- freeze 固定：`frozen_at=2026-08-21T09:34:00+08:00`；retrospective=`2023-01-01..2026-08-20`；embargo=`2026-08-21`；prospective first=`2026-08-24`；baseline request-through=`2026-08-21`。
- `2026-08-24` 必须由 existing TradingCalendar/Instrument metadata read-only 验证为 `jm` freeze 后首个 eligible trading day；失败即阻塞，不动态改日期。
- 不做 active60 Robustness V2、参数 sweep、Candidate rank/winner/KEEP/DROP/PROMOTE。
- 不新增 Web/API、DB、Redis、worker/queue、Alert Rule/Scope、PushPlus、Execution Review、order/account/position/cost/PnL。
- 不触及 `main`、tag、release、Runtime；task→develop 不授权任何真实写入或外部操作。
- 所有交易相关计算使用 Decimal；CLI Decimal 只以稳定字符串序列化。
- 每个实现 Task 使用 TDD；策略公式/时序 Task 属 Lane 3，必须 Plan-only → 人工批准 → implementation → 独立 Review，才能集成 develop。

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

### New JDJ source/domain files

```text
services/quant-api/app/market_data/jdj_policy.py
services/quant-api/app/market_data/jdj_context.py
services/quant-api/app/market_data/jdj_events.py
services/quant-api/app/market_data/jdj_trend_follow.py
services/quant-api/app/market_data/jdj_trend_reentry.py
services/quant-api/app/market_data/jdj_key_level_breakout.py
services/quant-api/app/market_data/jdj_research.py
services/quant-api/app/market_data/jdj_research_service.py
```

### New JDJ Candidate Validation files

```text
services/quant-api/app/market_data/jdj_candidate_validation_policy.py
services/quant-api/app/market_data/jdj_candidate_validation.py
services/quant-api/app/market_data/jdj_candidate_validation_service.py
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

### Versioned evidence created only in Task 10

```text
reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json
reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-21.json
```

---

# Task 1 — Freeze JDJ Exact Policy, Three Candidate Manifests and Validation Protocol

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后再在同一 task branch 实现
- 工作区：从最新 `develop` 创建新 task worktree/branch `research/jdj-v1-contracts`
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Create `data/research_policies/jdj_1m_policy_v1.json`
- Create three files under `data/research_candidates/`
- Create `data/research_protocols/jdj_candidate_validation_v1.json`
- Create `services/quant-api/app/market_data/jdj_policy.py`
- Create `services/quant-api/app/market_data/jdj_candidate_validation_policy.py`
- Create `services/quant-api/tests/test_jdj_policy.py`
- Create `services/quant-api/tests/test_jdj_candidate_validation_policy.py`

**Interfaces:**
- Produces `JdjPolicy`, `load_jdj_policy()`, `is_exact_jdj_policy()`.
- Produces `JdjCandidateManifest`, `load_jdj_candidate_manifest(candidate_id)`.
- Produces `JdjCandidateValidationProtocol`, `load_jdj_candidate_validation_protocol()`.

- [ ] **Step 1: Create the isolated task worktree**

```bash
git fetch origin develop
git worktree add ../guiyi-jdj-v1-contracts \
  -b research/jdj-v1-contracts origin/develop
cd ../guiyi-jdj-v1-contracts
git status --short
git rev-parse HEAD
```

Expected: clean worktree at exact latest `origin/develop`.

- [ ] **Step 2: Write RED exact policy tests**

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

Also mutate every top-level/nested field: missing key, extra key, wrong type, EMA period 21, SMA, first-value seed, permissive equal breach, `same_epoch_key_level=false`, volume threshold, timeout, fill model or promotion flag. Every mutation raises exact `JDJ_POLICY_INVALID` with no input path/parser detail leakage.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py
```

Expected: import/file failure.

- [ ] **Step 4: Create exact policy JSON and strict loader**

The JSON must freeze the approved semantics, including these exact values:

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
  "parameter_sweep": false,
  "automatic_promotion": false
}
```

Strict loader uses exact recursive key/type/value comparison and recursively freezes raw payload with `MappingProxyType` / tuples.

- [ ] **Step 5: Write RED exact Candidate/Protocol tests**

```python
EXPECTED = (
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)

def test_loads_three_isolated_jdj_candidate_manifests() -> None:
    manifests = tuple(load_jdj_candidate_manifest(value) for value in EXPECTED)
    assert tuple(value.candidate_id for value in manifests) == EXPECTED
    assert all(value.source_kind == "jdj_1m" for value in manifests)
    assert all(value.policy_id == "jdj_1m_policy_v1" for value in manifests)
    assert all(value.formula_version == "jdj_1m_v1" for value in manifests)
    assert all(value.research_only is True for value in manifests)
```

Protocol assertions:

```python
def test_jdj_protocol_freezes_dates_and_exact_three_candidate_order() -> None:
    protocol = load_jdj_candidate_validation_protocol()
    assert protocol.protocol_id == "jdj_candidate_validation_v1"
    assert protocol.candidate_ids == EXPECTED
    assert protocol.candidate_frozen_at.isoformat() == "2026-08-21T09:34:00+08:00"
    assert protocol.retrospective_since == date(2023, 1, 1)
    assert protocol.retrospective_through == date(2026, 8, 20)
    assert protocol.embargo_trading_days == (date(2026, 8, 21),)
    assert protocol.prospective_oos_first_trading_day == date(2026, 8, 24)
    assert protocol.baseline_request_through == date(2026, 8, 21)
    assert protocol.horizons_bars == (3, 5, 8, 20)
```

- [ ] **Step 6: Implement strict manifest/protocol loaders**

Use a fixed candidate-id→path mapping; unknown id raises `JDJ_CANDIDATE_MANIFEST_INVALID`. Do not scan directories or build a plugin registry.

Required exact manifest payload for each candidate:

```json
{
  "schema_version": 1,
  "candidate_id": "<exact candidate id>",
  "source_kind": "jdj_1m",
  "policy_id": "jdj_1m_policy_v1",
  "formula_version": "jdj_1m_v1",
  "research_only": true
}
```

Protocol exact fields include `anchor_symbol="jm"`, candidate order, `reference_months=12`, `test_months=3`, `step_months=3`, `first_test_since=2024-01-01`, `last_test_through=2026-06-30`, `horizons_bars=[3,5,8,20]`, `automatic_ranking=false`, `automatic_promotion=false`.

- [ ] **Step 7: Run GREEN and static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_policy.py \
  services/quant-api/app/market_data/jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Independent Review and integrate**

Reviewer verifies exact JSON identity, no runtime tuning, no hidden volume/timeout/fill semantics and no N policy modification. Gate: `Critical=0 / Important=0`.

Commit:

```bash
git add data/research_policies/jdj_1m_policy_v1.json \
  data/research_candidates/jdj_trend_follow_1m_candidate_v1.json \
  data/research_candidates/jdj_trend_reentry_6_1m_candidate_v1.json \
  data/research_candidates/jdj_key_level_breakout_1m_candidate_v1.json \
  data/research_protocols/jdj_candidate_validation_v1.json \
  services/quant-api/app/market_data/jdj_policy.py \
  services/quant-api/app/market_data/jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py
git commit -m 'feat(research): freeze JDJ 1m v1 contracts'
```

After approved integration, confirm commit ancestry in `develop`, then clean task worktree/merged branch. Never touch `main`/tag/Runtime.

---

# Task 2 — Build the Causal 1m/5m JDJ Context Projection

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：从 Task 1 integrated latest `develop` 创建 `research/jdj-v1-context`
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Create `services/quant-api/app/market_data/jdj_context.py`
- Create `services/quant-api/tests/test_jdj_context.py`
- Reuse without modifying `n_structure_segment.py`, `n_structure_state.py`, `n_structure_swing.py`, `ema.py`.

**Interfaces:**

```python
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

- [ ] **Step 1: Write RED EMA20 parity/readiness tests**

Use 25 exact 1m bars and compare every context EMA to direct kernel output:

```python
kernel = ema_series(
    [float(bar.close) for bar in bars_1m],
    20,
    bar_ends=[bar.bar_end.isoformat() for bar in bars_1m],
    seed_policy="sma_window",
    round_digits=6,
)
contexts = build_jdj_context_series(...)
for context, point in zip(contexts, kernel.points, strict=True):
    expected = None if point.value is None else Decimal(str(point.value))
    assert context.ema20 == expected
```

- [ ] **Step 2: Write RED strict-before tests**

Construct exact 5m trace with a snapshot at `09:35`. Assert the 1m bar ending `09:35` does **not** see it and the next 1m bar ending `09:36` can see it:

```python
assert by_end[t0935].trend_snapshot_observed_at != t0935
assert by_end[t0936].trend_snapshot_observed_at == t0935
```

Also assert the implementation selects facts by `observed_at <= previous_1m.bar_end`, never `<= current.bar_end`.

- [ ] **Step 3: Write RED same-epoch key-level tests**

Create an older HIGH pivot in epoch 0, an outside reset to epoch 1, and a BULL snapshot in epoch 1 without an epoch-1 HIGH pivot. Expected:

```python
assert context.trend_epoch == 1
assert context.eligible_high_pivot is None
```

After an epoch-1 HIGH pivot is confirmed strict-before:

```python
assert context.eligible_high_pivot.epoch == context.trend_epoch == 1
```

- [ ] **Step 4: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py
```

- [ ] **Step 5: Implement the single causal projection**

Core implementation must use existing N once:

```python
n_trace = evaluate_n_structure_segment(
    bars_5m,
    contract=contract,
    segment_start_trading_day=segment_start_trading_day,
    segment_end_trading_day=segment_end_trading_day,
    policy=n_policy,
)
```

EMA uses existing kernel exactly. Iterate 1m bars in order and advance pointers only while:

```python
snapshot.observed_at <= previous_1m.bar_end
pivot.confirmed_at <= previous_1m.bar_end
```

Pivot eligibility additionally requires `pivot.epoch == latest_snapshot.epoch`. Do not rescan full 5m prefixes per 1m bar.

- [ ] **Step 6: Validate identity and monotonicity**

The function must reject non-monotonic 1m/5m, wrong policy identities, contract mismatch, segment-day leakage and impossible pivot/snapshot identities with stable `JDJ_CONTEXT_INVALID`.

- [ ] **Step 7: Add prefix-causality test**

```python
prefix = build_jdj_context_series(bars_1m[:n], bars_5m_prefix, ...)
extended = build_jdj_context_series(bars_1m, bars_5m, ...)
assert extended[:len(prefix)] == prefix
```

Future 1m/5m suffix must not rewrite past contexts.

- [ ] **Step 8: GREEN, Review and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/test_n_structure_state.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_context.py \
  services/quant-api/tests/test_jdj_context.py
git diff --check
```

Independent Review explicitly checks future leak, same-boundary semantics, same epoch, no N formula duplication. Gate C0/I0.

---

# Task 3 — Implement TREND_FOLLOW Reducer and Immutable Trigger Events

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Create `services/quant-api/app/market_data/jdj_events.py`
- Create `services/quant-api/app/market_data/jdj_trend_follow.py`
- Create `services/quant-api/tests/test_jdj_trend_follow.py`

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
```

Pure reducer:

```python
def reduce_jdj_trend_follow(
    contexts: Sequence[JdjBarContext],
    *,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
) -> JdjTrendFollowTrace: ...
```

- [ ] **Step 1: RED reaction tests LONG/SHORT**

LONG reaction only if:

```python
context.trend_kind is NStructureKind.BULL
and context.ema20 is not None
and context.bar.low <= context.ema20 <= context.bar.high
and context.bar.close > context.ema20
```

SHORT is exact mirror.

- [ ] **Step 2: RED dynamic previous-bar strict trigger**

Construct reaction at bar 0, no trigger at bar 1, trigger at bar 2. Assert trigger level is bar 1 high/low, not reaction bar:

```python
assert event.trigger_level == contexts[1].bar.high
assert event.observed_at == contexts[2].bar.bar_end
```

Equal high/low does not trigger.

- [ ] **Step 3: RED invalidation and ambiguous tests**

LONG armed invalidates when pre-known trend becomes non-BULL or current close `<= EMA20`. If same current OHLC satisfies `current.high > previous.high` and `close <= EMA20`, assert:

```python
assert trace.events == ()
assert trace.ambiguous_count == 1
```

SHORT mirror uses `close >= EMA20`.

- [ ] **Step 4: Implement minimal state machine**

Use explicit private state:

```python
@dataclass(slots=True)
class _Armed:
    direction: JdjDirection
    reaction_at: datetime
    ema20_at_reaction: Decimal
    trend_snapshot_observed_at: datetime
```

Per current context after the reaction boundary:

```python
triggered = current.bar.high > previous.bar.high  # LONG
invalid = current.ema20 is None or current.bar.close <= current.ema20 \
    or current.trend_kind is not NStructureKind.BULL
if triggered and invalid:
    ambiguous += 1
    armed = None
elif invalid:
    invalidated += 1
    armed = None
elif triggered:
    events.append(...)
    armed = None
```

Do not process the same reaction bar as trigger.

- [ ] **Step 5: Stable event identity**

Event id must be derived only from business identity/provenance, e.g. canonical joined fields:

```text
jdj_trend_follow_1m_candidate_v1|symbol|contract|segment_start|direction|reaction_at|observed_at|trigger_level
```

Same exact input rerun yields identical ids/order.

- [ ] **Step 6: Prefix and trading-day reset tests**

Reducer must treat trading-day boundary as terminal/reset even inside the same physical contract. Future suffix cannot alter earlier emitted events.

- [ ] **Step 7: GREEN + independent semantic Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_events.py \
  services/quant-api/app/market_data/jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_follow.py
git diff --check
```

Review checks strict previous-bar semantics, EMA invalidation, OHLC ambiguity and no fill claim. Gate C0/I0.

---

# Task 4 — Implement TREND_REENTRY_6 Reducer

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Modify `services/quant-api/app/market_data/jdj_events.py`
- Create `services/quant-api/app/market_data/jdj_trend_reentry.py`
- Create `services/quant-api/tests/test_jdj_trend_reentry.py`

**Produces:** `JdjTrendReentryTriggerEvent`, `JdjTrendReentryTrace`, `reduce_jdj_trend_reentry_6()`.

- [ ] **Step 1: RED trend-side prerequisite**

LONG must observe a ready BULL context with `close > EMA20` before a later `close <= EMA20` can open an excursion. Starting the day below EMA20 cannot synthesize an exit proxy. SHORT mirrors below/above.

- [ ] **Step 2: RED excursion aggregation**

LONG consecutive `close <= EMA20` bars maintain:

```python
excursion_low = min(context.bar.low for bars in current excursion)
```

SHORT uses max high. Assert the stored extreme includes every excursion bar and freezes at reclaim.

- [ ] **Step 3: RED reclaim and no-same-bar-reaction**

LONG first `close > EMA20` is reclaim. Even if it touches EMA20, it cannot be the higher-low reaction. The earliest reaction is a later completed 1m bar.

- [ ] **Step 4: RED first post-reclaim reaction rule**

For LONG, first post-reclaim reaction:

```python
bar.low <= ema20 <= bar.high and bar.close > ema20
```

If `reaction.low > excursion_low`, arm. If `reaction.low <= excursion_low`, terminate that episode immediately; do not skip it and wait for a later nicer reaction. SHORT exact mirror.

- [ ] **Step 5: RED reclaim failure**

If before the first qualifying reaction LONG closes `<= EMA20`, old reclaim fails and a new below-EMA excursion begins at this bar with a new extreme. Do not merge old/new excursions.

- [ ] **Step 6: Implement explicit reducer phases**

Use a small enum rather than implicit booleans:

```python
class _Phase(StrEnum):
    WAIT_TREND_SIDE = "wait_trend_side"
    WAIT_EXCURSION = "wait_excursion"
    IN_EXCURSION = "in_excursion"
    WAIT_REACTION = "wait_reaction"
    ARMED = "armed"
```

Store `excursion_started_at`, `excursion_extreme`, `reclaimed_at`, reaction provenance and direction. Reset on trend/context/day boundary.

- [ ] **Step 7: Reuse exact trigger/ambiguity semantics**

After ARMED, use the same dynamic previous-bar strict trigger and EMA/trend invalidation rules as Trend Follow. Do not call Trend Follow reducer or duplicate event identity logic; share only tiny pure helpers from `jdj_events.py` if needed.

- [ ] **Step 8: LONG/SHORT symmetry, prefix and deterministic event tests**

Assert mirror behavior, event id stability and prefix causality.

- [ ] **Step 9: GREEN + independent Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_events.py \
  services/quant-api/app/market_data/jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_trend_reentry.py
git diff --check
```

Review checks no fake position/exit, no adjacent-bar shortcut, first reaction selection and exact mirrors. Gate C0/I0.

---

# Task 5 — Implement KEY_LEVEL_BREAKOUT Second-Chance Reducer

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Modify `services/quant-api/app/market_data/jdj_events.py`
- Create `services/quant-api/app/market_data/jdj_key_level_breakout.py`
- Create `services/quant-api/tests/test_jdj_key_level_breakout.py`

**Produces:** `JdjKeyLevelBreakoutTriggerEvent`, trace/terminal facts and `reduce_jdj_key_level_breakout()`.

- [ ] **Step 1: RED eligible pivot identity**

LONG requires BULL + `eligible_high_pivot`; SHORT requires BEAR + `eligible_low_pivot`. Assert pivot is strict-before and `pivot.epoch == context.trend_epoch`; otherwise no episode.

- [ ] **Step 2: RED post-confirmation origin-side requirement**

LONG pivot cannot become first-break eligible until a later 1m close `<= key_level`; SHORT until close `>= key_level`. This prevents back-labeling a level that was already crossed before eligibility.

- [ ] **Step 3: RED FIRST_BREAK close transition**

LONG exact:

```python
previous.bar.close <= key_level and current.bar.close > key_level
```

SHORT mirror. First-break produces only observation state; `events` remains empty. Intrabar high/low alone does not confirm first break.

- [ ] **Step 4: RED first-break freeze and no chase**

On FIRST_BREAK freeze `pivot_id`, `price`, `confirmed_at`, `first_break_at`. A newer eligible pivot arriving during WAIT_RETEST cannot replace this level. First-break bar cannot also be retest.

- [ ] **Step 5: RED accepted/failed retest**

LONG after first-break:

```python
accepted = bar.low <= key_level and bar.close > key_level
failed = bar.close <= key_level
```

SHORT:

```python
accepted = bar.high >= key_level and bar.close < key_level
failed = bar.close >= key_level
```

Accepted moves to ARMED from the next bar; failed is terminal. If OHLC makes both an accepted touch and failed close, failed wins because close is not on breakout side.

- [ ] **Step 6: Freeze KEY_LEVEL ARMED invalidation semantics**

This setup does **not** inherit EMA20 invalidation. After accepted retest:

```text
LONG invalid if pre-known trend != BULL OR completed close <= frozen key_level
SHORT invalid if pre-known trend != BEAR OR completed close >= frozen key_level
```

If the same current OHLC satisfies previous-bar strict trigger and key-level invalidation, mark ambiguous/terminal with no event. EMA20 is irrelevant after retest.

- [ ] **Step 7: RED no-retest/context expiry and pivot consumption**

Trading-day end before retest → `EXPIRED_NO_RETEST`. Trend loss/segment change → `EXPIRED_CONTEXT_LOST`. Any terminal state consumes that `pivot_id` for the same trading day/segment; it cannot start another first-break episode. A new eligible pivot can.

- [ ] **Step 8: Implement explicit phases**

```python
class _Phase(StrEnum):
    WAIT_ORIGIN_SIDE = "wait_origin_side"
    WAIT_FIRST_BREAK = "wait_first_break"
    WAIT_RETEST = "wait_retest"
    ARMED = "armed"
```

State includes frozen pivot provenance and consumed pivot ids. No volume multiplier, proximity zone, timeout bars or EMA filter.

- [ ] **Step 9: RED/green prefix causality and symmetry**

Future pivots/bars cannot rewrite old first-break/retest/trigger facts; LONG/SHORT mirror tests are mandatory.

- [ ] **Step 10: GREEN + independent Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/jdj_events.py \
  services/quant-api/app/market_data/jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py
git diff --check
```

Review checks same epoch, no volume invention, first-break never entry, frozen level, no EMA invalidation leakage and same-bar ambiguity. Gate C0/I0.

---

# Task 6 — Build JDJ Read-only Research Service and 3/5/8/20 Price Outcomes

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-only；人工批准后实现
- 工作区：new task worktree from latest develop
- 人工 Gate：Plan 批准 + 独立 Review

**Files:**
- Create `services/quant-api/app/market_data/jdj_research.py`
- Create `services/quant-api/app/market_data/jdj_research_service.py`
- Create `services/quant-api/tests/test_jdj_research.py`
- Create `services/quant-api/tests/data_foundation/test_jdj_research_service.py`
- Reuse `price_outcome.py` unchanged.

**Interfaces:**

```python
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

- [ ] **Step 1: RED request identity tests**

Normalize symbol lower-case, require one of exact three candidate ids, dates exact and `since<=through`. Unknown candidate raises `JDJ_RESEARCH_REQUEST_INVALID` before loader call.

- [ ] **Step 2: RED multi-frequency loader call**

Fake `ActualDominantResearchSegmentLoader` and assert exactly one load per symbol/window:

```python
assert loader.calls == [{
    "symbol": "jm",
    "frequencies": (BarFrequency.M1, BarFrequency.M5),
    "since": request.since,
    "through": request.through,
}]
```

The service must use the restored true segment prefix returned by the loader, then count only requested trading days.

- [ ] **Step 3: RED exact reducer dispatch isolation**

For each candidate id assert only its reducer event kind appears:

```text
jdj_trend_follow_1m_candidate_v1 → jdj_trend_follow_triggered
jdj_trend_reentry_6_1m_candidate_v1 → jdj_trend_reentry_6_triggered
jdj_key_level_breakout_1m_candidate_v1 → jdj_key_level_breakout_triggered
```

No source trigger can be re-labeled into another Candidate.

- [ ] **Step 4: Implement exact segment partition and context→reducer path**

For each restored rank1 segment, partition 1m and 5m bars by `ResolvedContractSegment` trading-day bounds. Build context once per segment, run exactly one selected reducer, and aggregate only events whose `trading_day` is within request window.

Do not duplicate dominant mapping logic; trust loader segments and fail if either frequency has uncovered bars.

- [ ] **Step 5: RED outcome semantics**

For each trigger event find exact trigger bar index and call existing:

```python
build_price_outcomes_at(
    bars_1m,
    index=trigger_index,
    direction=PriceDirection.LONG if event.direction is JdjDirection.LONG else PriceDirection.SHORT,
    horizons=(3, 5, 8, 20),
    same_trading_day_only=True,
)
```

Because service passes only one exact physical segment, this also enforces no cross-roll outcome. Assert trigger-bar high/low is excluded by existing helper’s `index+1..index+H` behavior.

- [ ] **Step 6: RED later-bar/window leakage test**

If loader fixture returns bars after request.through, those later bars cannot complete a horizon for an event at the requested edge. Trim outcome evaluation to `bar.trading_day <= request.through` before calling helper.

- [ ] **Step 7: Stable source error boundary**

Map only existing data-boundary failures:

```text
MarketDataError
ActualDominantResearchSegmentIdentityError
→ JDJ_SOURCE_UNAVAILABLE
```

Context identity errors become `JDJ_CONTEXT_INVALID`. Unexpected `TypeError`, `AssertionError`, programming `ValueError`, unexpected `RuntimeError` must propagate; no `except Exception` swallowing.

- [ ] **Step 8: GREEN + independent Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_price_outcome.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data/jdj_*.py

git diff --check
```

Review checks full true-segment prefix, requested-window cutoff, trigger close reference, no fill model, no broad exception swallowing. Gate C0/I0.

---

# Task 7 — Add Three JDJ Candidate Validation Reports, Rolling Folds and Prospective Gate

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话；完成后新开独立 Review 会话
- Plan：Plan-then-execute
- 工作区：new task worktree from latest develop
- 人工 Gate：独立 Review；不授权任何 OOS backfill/promotion

**Files:**
- Create `services/quant-api/app/market_data/jdj_candidate_validation.py`
- Create `services/quant-api/app/market_data/jdj_candidate_validation_service.py`
- Create `services/quant-api/tests/test_jdj_candidate_validation.py`
- Create `services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py`

**Produces:** `JdjCandidateWindowResult`, `JdjRollingCandidateFold`, `JdjCandidateStabilitySummary`, `JdjProspectiveOosResult`, `JdjCandidateValidationReport`, `JdjCandidateValidationService`.

- [ ] **Step 1: RED window/report contracts**

Window freezes exact `(3,5,8,20)` horizon keys, exact candidate id/source event kind, products, segment/evaluable/event counts, immutable mappings/tuples and no decision fields.

Stability summary uses test-fold event counts:

```python
counts = sorted(fold.test.event_count for fold in folds)
```

and returns fold count, folds with events, min/median/max.

- [ ] **Step 2: RED exact ten rolling windows**

Reuse `build_rolling_validation_windows()` with the frozen 12/3/3 schedule. Assert exactly the existing fold_01..fold_10 dates; do not create a second scheduler.

- [ ] **Step 3: RED retrospective/embargo/prospective requests**

For baseline through `2026-08-21`, runner requests:

```python
JdjResearchRequest(
    since=date(2023, 1, 1),
    through=date(2026, 8, 20),
    symbol="jm",
    candidate_id=<exact>,
)
```

plus 20 rolling reference/test requests. It must not call source for prospective because `2026-08-21 < 2026-08-24`.

Report:

```python
assert report.prospective_oos.status is JdjProspectiveOosStatus.PENDING
assert report.prospective_oos.first_trading_day == date(2026, 8, 24)
assert report.prospective_oos.through == date(2026, 8, 21)
assert report.prospective_oos.result is None
```

- [ ] **Step 4: Implement service with exact identity checks**

`CandidateValidationRequest` must match selected manifest id + `jdj_candidate_validation_v1`; through before retrospective through fails `CANDIDATE_VALIDATION_WINDOW_INVALID`.

Window runner creates exact `JdjResearchRequest`; source result must have `products==(symbol,)` and candidate id exact.

Only `JdjSourceUnavailableError` / `JdjContextError` map to `CandidateValidationSourceError`. Unexpected programming errors propagate.

- [ ] **Step 5: Add read-only calendar validation seam**

Before composition exposes JDJ Validation, a helper must verify existing metadata for anchor `jm`:

```text
2026-08-21 = trading day
2026-08-22/23 = not eligible trading days
2026-08-24 = trading day
```

Resolve exchange from existing `Instrument(symbol="jm")`; query existing `TradingCalendar`. Missing/conflicting rows raise stable `JDJ_PROSPECTIVE_CALENDAR_INVALID`; do not mutate calendar and do not choose a replacement date.

Unit tests use fake/isolated session rows; no production write.

- [ ] **Step 6: Quality flags only structural**

Allowed:

```text
PROSPECTIVE_OOS_PENDING
ROLLING_FOLD_WITHOUT_EVENT
HORIZON_WITHOUT_SAMPLE
```

No strategy pass/fail/rank/promotion fields.

- [ ] **Step 7: GREEN + Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py

git diff --check
```

Independent Review checks exact freeze dates, no OOS relabel/backfill, calendar fail-closed and three Candidate isolation. Gate C0/I0.

---

# Task 8 — Wire Composition and Read-only `jdj-1m` / Candidate Validation CLI

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Terra
- 推理强度：中
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：new task worktree from latest develop
- 人工 Gate：无真实写入 Gate；focused tests/self-review 后允许集成 develop

**Files:**
- Modify `services/quant-api/app/market_data/composition.py`
- Modify `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify `services/quant-api/app/guiyi_cli/main.py`
- Modify `services/quant-api/tests/test_research_cli.py`

- [ ] **Step 1: RED parser command-set test**

Existing six read-only research commands become exactly seven by adding `jdj-1m`:

```python
assert set(command_action.choices) == {
    "candidate-robustness",
    "candidate-validation",
    "jdj-1m",
    "main-force-mirror-futures",
    "n-structure",
    "subing-calibration",
    "subing-lifecycle",
}
```

- [ ] **Step 2: RED exact `jdj-1m` parser**

Valid:

```text
guiyi research jdj-1m \
  --candidate jdj_trend_follow_1m_candidate_v1 \
  --symbol jm --since 2026-01-01 --through 2026-03-31
```

Candidate choices exact three. Reject formula flags `--ema-period`, `--volume-multiple`, `--timeout-bars`, `--trend-method`, `--key-level-distance`, plus unknown candidate.

- [ ] **Step 3: Extend `candidate-validation` choices**

Candidate choices add exact three JDJ ids; protocol choices add `jdj_candidate_validation_v1`. Parser may syntactically accept cross-pairs, but service dispatch must reject wrong pairing before source construction.

- [ ] **Step 4: Add exact composition builders**

```python
def build_jdj_research_service(session: Session) -> JdjResearchService:
    market_data = build_market_data_service(session)
    return JdjResearchService(
        ActualDominantResearchSegmentLoader(market_data),
        products=load_active_products(),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )


def build_jdj_candidate_validation_service(
    session: Session,
    candidate_id: str,
) -> JdjCandidateValidationService:
    assert_jdj_prospective_calendar(session)
    return JdjCandidateValidationService(
        build_jdj_research_service(session),
        manifest=load_jdj_candidate_manifest(candidate_id),
        protocol=load_jdj_candidate_validation_protocol(),
    )
```

Do not create dynamic plugin registry.

- [ ] **Step 5: Add request/rendering path**

`JdjResearchRequest` joins `ResearchRequest` union. Render deterministic source payload:

```text
schema_version
command=research.jdj-1m
status=ok
readonly=true
research_only=true
candidate_id
source_event_kind
since
through
products
segment_count
evaluable_bar_count
trigger_count_long
trigger_count_short
horizon_summary
events
```

Decimal strings use existing `_optional_decimal()` convention; event Decimal fields become strings, not float.

`candidate-validation` renderer recognizes `JdjCandidateValidationReport` before generic SuBing fallback and emits exact 3/5/8/20 horizon summaries.

- [ ] **Step 6: Route factories in `main()`**

Add a dedicated JDJ research factory and JDJ candidate validation factory. For Candidate Validation:

```python
if request.candidate_id in JDJ_CANDIDATE_IDS:
    service = jdj_candidate_validation_service_factory(session, request.candidate_id)
```

If factory signature handling becomes awkward, use a typed `Callable[[Any, str], Any]`; do not hide candidate selection in global mutable state.

- [ ] **Step 7: RED readonly/no-side-effect tests**

Fake session/service verifies no data manager, Runtime, Alert or notification factory is constructed. Invalid JDJ arguments exit 2 before service construction; typed research failures exit 1 with sanitized public code and `readonly=true`.

- [ ] **Step 8: GREEN + static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/test_jdj_*.py \
  services/quant-api/tests/data_foundation/test_jdj_*.py \
  services/quant-api/tests/test_research_cli.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Integrate to develop only after tests/self-review. No release/Runtime.

---

# Task 9 — Cumulative Verification and Independent Implementation Review

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开独立 Review 会话
- Plan：Plan-only / Review-only；只在发现明确 in-scope defect 时修改
- 工作区：clean detached review worktree at exact latest `develop`
- 人工 Gate：独立 Review `Critical=0 / Important=0`

**Files:**
- Modify `TESTING.md` to add the stable Phase 6 verification block.
- Fix implementation/tests only for concrete Review findings.

- [ ] **Step 1: Create clean review worktree and record SHA**

```bash
git fetch origin develop
git worktree add --detach ../guiyi-jdj-v1-review origin/develop
cd ../guiyi-jdj-v1-review
git status --short
git rev-parse HEAD
```

- [ ] **Step 2: Run full JDJ focused suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_jdj_policy.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_jdj_candidate_validation_policy.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 3: Run N full-chain zero-regression**

Use the exact N block already in `TESTING.md`, including policy/swing/pattern/state/segment/actual-dominant/price-outcome/research/candidate validation/CLI.

- [ ] **Step 4: Run SuBing + existing Candidate/Robustness zero-regression**

Run current SuBing lifecycle/candidate tests and Multi-Candidate Robustness V1 tests exactly from `TESTING.md`; existing tracked baseline files must remain unchanged.

- [ ] **Step 5: Run engineering gates**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 6: Independent Review checklist**

Reviewer must examine code, tests and exact JSON contracts for:

```text
Critical:
  future leak / same-boundary 5m use
  cross-contract/segment/day state leakage
  N formula/policy modification under existing identity
  OOS backfill/relabel
  optimistic same-bar trigger ordering
  fill/order/position semantics introduced
  production/Runtime/Alert boundary violation

Important:
  EMA20 kernel/seed/round drift
  key-level pivot not same epoch
  key-level wrongly using EMA invalidation after retest
  first-break directly generating entry
  reentry skipping first failed post-reclaim reaction
  broad exception swallowing
  Candidate identity mixing
  trigger bar included in future MFE/MAE
  nondeterministic event ids/order/JSON
  duplicate Historical/rank1/N resolver
```

Gate: `Critical=0 / Important=0`. Minor may be documented if behavior-neutral.

- [ ] **Step 7: Update TESTING.md and integrate**

Add a `## JDJ 1m Research & Candidate V1` block containing the exact focused suite and explicit statement that tests are fixture/read-only and do not authorize real evidence, Alert/Runtime, release or trading.

If Review fixes are needed, implement them in a dedicated fix branch from reviewed develop, rerun affected + cumulative tests, obtain C0/I0 again, then integrate.

---

# Task 10 — Exact-develop Baselines, Evidence Review and Canonical Closeout

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开 evidence 会话 + 新开独立 Evidence Review 会话
- Plan：Plan-then-execute
- 工作区：independent evidence branch/worktree from exact accepted `develop`
- 人工 Gate：独立 Evidence Review；不得发布 main/tag；不得 Runtime promotion

**Files:**
- Create three versioned JDJ baseline JSON files.
- Modify `STATUS.md`, `PROJECT_SOURCE.md`, `docs/ARCHITECTURE.md`; `TESTING.md` only if exact evidence commands need correction.

- [ ] **Step 1: Freeze exact reviewed develop identity**

```bash
git fetch origin develop
git worktree add ../guiyi-jdj-v1-evidence \
  -b research/jdj-v1-evidence origin/develop
cd ../guiyi-jdj-v1-evidence
git status --short
git rev-parse HEAD
```

Record exact SHA. Evidence must be generated from this clean code identity.

- [ ] **Step 2: Re-run engineering/implementation gates fresh**

Run Task 9 focused JDJ suite, N/SuBing/Robustness regressions, Ruff, Mypy, secret scan and `git diff --check`. Any failure blocks evidence generation.

- [ ] **Step 3: Prove existing SuBing/N tracked baselines are unchanged**

Re-run their existing exact Candidate Validation commands using their own frozen request-through dates and compare byte-for-byte to tracked artifacts. Any mismatch blocks; do not update those files in Phase 6.

- [ ] **Step 4: Run the three exact JDJ baseline commands**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_trend_follow_1m_candidate_v1 \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm --through 2026-08-21 \
  > /tmp/jdj-trend-follow-v1.json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_trend_reentry_6_1m_candidate_v1 \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm --through 2026-08-21 \
  > /tmp/jdj-trend-reentry-6-v1.json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate jdj_key_level_breakout_1m_candidate_v1 \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm --through 2026-08-21 \
  > /tmp/jdj-key-level-breakout-v1.json
```

These are Historical read-only commands; they do not send notifications or write DB/Canonical/Redis.

- [ ] **Step 5: Validate artifact identities before tracking**

For each JSON assert:

```python
assert data["readonly"] is True
assert data["research_only"] is True
assert data["protocol_id"] == "jdj_candidate_validation_v1"
assert data["symbol"] == "jm"
assert data["retrospective"]["since"] == "2023-01-01"
assert data["retrospective"]["through"] == "2026-08-20"
assert len(data["rolling_folds"]) == 10
assert data["prospective_oos"] == {
    "status": "pending",
    "first_trading_day": "2026-08-24",
    "through": "2026-08-21",
    "result": None,
}
assert tuple(data["retrospective"]["horizon_summary"]) == ("3", "5", "8", "20")
```

Recursively reject decision/profit/fill/order keys including `rank`, `winner`, `keep`, `drop`, `promote`, `fill_price`, `pnl`, `expected_profit`.

- [ ] **Step 6: Determinism rerun**

Run all three commands again to `*-rerun.json`; `cmp` each original/rerun and record byte size + SHA-256. Any byte drift blocks evidence.

- [ ] **Step 7: Track exact artifacts**

```bash
mkdir -p \
  reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1 \
  reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1 \
  reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1

cp /tmp/jdj-trend-follow-v1.json \
  reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
cp /tmp/jdj-trend-reentry-6-v1.json \
  reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
cp /tmp/jdj-key-level-breakout-v1.json \
  reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json
```

- [ ] **Step 8: Independent Evidence Review**

Reviewer examines exact files, not only summary. Required:

```text
three exact Candidate ids and source event kinds
policy/formula identity exact
retrospective through 2026-08-20
embargo 2026-08-21
prospective first 2026-08-24 and pending through 2026-08-21
10 exact rolling folds
3/5/8/20 source-specific horizons
no OOS backfill
no cross-day/contract/segment future outcome
same-boundary strict-before contract retained
three reruns byte-identical
existing SuBing/N tracked baselines unchanged
no decision/rank/profit/fill/order fields
```

Gate: `Critical=0 / Important=0`.

- [ ] **Step 9: Canonical documentation closeout**

`STATUS.md` records code/test/evidence facts, exact reviewed/evidence SHA, event/sample counts and SHA-256, but no validity/profitability conclusion.

`PROJECT_SOURCE.md` adds read-only `guiyi research jdj-1m` and JDJ Candidate Validation boundary.

`docs/ARCHITECTURE.md` adds:

```text
existing N Structure 5m context + 1m EMA20/price
        ↓
JDJ Domain
├─ Trend Follow Candidate
├─ Reentry 6 Candidate
└─ Key-Level Breakout Candidate
        ↓
existing rolling/prospective Candidate Validation
```

Do not update `DECISIONS.md` unless implementation introduced a genuinely new long-term decision not already contained in accepted Spec.

- [ ] **Step 10: Final tracked checks, commit, integrate and cleanup**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check

git add \
  reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json \
  reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json \
  reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json \
  STATUS.md PROJECT_SOURCE.md docs/ARCHITECTURE.md TESTING.md

git commit -m 'research: add JDJ 1m candidate v1 baselines'
```

Only include `TESTING.md` if it changed in this task. After Evidence Review C0/I0, integrate evidence branch to `develop`, read back ancestry, clean task worktree/merged branch. Do not merge `main`, tag/release, switch Runtime or add Alert.

---

## Final Acceptance Criteria

Phase 6 is complete only when all are true:

```text
[ ] exact jdj_1m_policy_v1 exists and strict loader rejects drift
[ ] exact three independent Candidate manifests exist
[ ] exact jdj_candidate_validation_v1 freeze exists
[ ] EMA20 uses existing ema_series V1 with sma_window seed / 6-digit rounding
[ ] 5m N context is strict-before and same-boundary-safe
[ ] key-level pivot is same epoch as pre-known N snapshot
[ ] TREND_FOLLOW long/short/reaction/trigger/invalidation/ambiguity tests pass
[ ] TREND_REENTRY_6 prerequisite/excursion/reclaim/first-reaction/trigger tests pass
[ ] KEY_LEVEL first-break/no-chase/retest/frozen-level/pivot-consumption tests pass
[ ] key-level armed invalidation does not inherit EMA20
[ ] JDJ source service loads M1/M5 through shared actual-dominant loader only
[ ] source event ids/order are deterministic and prefix-stable
[ ] outcome reference is trigger-bar close; trigger bar excluded from future MFE/MAE
[ ] 3/5/8/20 horizons cannot cross day/contract/rank1 segment/request-through
[ ] Candidate Validation reuses exact shared 10-fold schedule
[ ] 2026-08-24 prospective day metadata check passes or implementation blocks
[ ] baseline through 2026-08-21 remains prospective pending; no OOS backfill
[ ] read-only jdj-1m CLI and three Candidate Validation routes exist
[ ] N, SuBing, existing Candidate Validation and Robustness regressions pass
[ ] Implementation Review Critical=0 / Important=0
[ ] existing SuBing/N tracked baselines reproduce byte-identically
[ ] three JDJ tracked baselines reproduce byte-identically
[ ] Evidence Review Critical=0 / Important=0
[ ] STATUS/PROJECT_SOURCE/ARCHITECTURE/TESTING reflect exact state
[ ] no main/tag/Runtime/Alert/DB/Canonical/notification/order mutation occurred
```

Final allowed statement:

```text
Phase 6 JDJ 1m Research & Candidate V1 已把三条 source-derived setup 转换为三个 exact causal Candidate，
形成 jm retrospective / 10-fold rolling baseline，并冻结 prospective OOS；全部结果仍为 research-only。
```

Final forbidden statements:

```text
JDJ 策略有效/盈利
三条里某条更好/应该 KEEP/DROP/PROMOTE
允许新增 Alert/PushPlus
允许自动交易/下单
允许 main/tag release
允许 Runtime promotion
```
