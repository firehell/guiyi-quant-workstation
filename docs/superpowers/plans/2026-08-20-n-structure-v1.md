# N 字 Structural Domain V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Data Foundation、SuBing V1/V2、Alert/Scope/Runtime 的前提下，实现 5m-only、research-only、prefix-invariant 的 N 字价格结构域，并让它成为 Candidate Validation 的第二个真实 producer，最终生成 `jm` retrospective/rolling evidence。

**Architecture:** N 字使用独立 sequential causal Swing reducer，不复用 SuBing 的 2-left/2-right Pivot；所有历史读取仍只经 `MarketDataService`。实现按 `Swing → Completed N → Break/Range Band → BULL/BEAR/RANGE Structure → Historical Research → Candidate Validation` 单向依赖；第二 producer 出现后只抽取真实重复的 actual-dominant segment loader、price-only outcome 和 Candidate schedule，不建立 Strategy Plugin/Registry。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、FastAPI 项目既有 composition/CLI、MarketDataService、pytest、Ruff、Mypy、JSON research artifacts。

**Spec:** `docs/superpowers/specs/2026-08-20-n-structure-v1-design.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec、本 Plan，以及当前 `develop` 最近提交；active canonical 与 Plan 冲突时停止，不按旧计划猜测。
- 原始研究来源只使用用户提供的《期货技术教程讲义【L修订打印版】》第四章 4.1～4.6。来源没有提供的机器规则必须明确属于 `GUIYI_ENGINEERING_V1`，不得伪称原书公式。
- N 字命名固定为 `UP_N / DOWN_N`；机器点为 `ORIGIN / N1_EXTREME / N2_ORIGIN / COMPLETION`；阶段只叫 `N1 / N1_N2 / N2`，不得重新引入“N1/N2/N3/N4 四种 N”。
- `source_timeframe=5m only`；只消费 completed Historical Canonical actual-dominant；不读 Live Redis，不跨频 fallback，不直接读 Parquet/RQData，不自行解析 rank1。
- Swing 反转固定为 previous-bar high/low strict breach；equal 不破；equal extreme keep first；inside bar 不反转；outside bar 不猜 intrabar 顺序而 reset unresolved/incomplete state。
- Outside bar 只禁止用该 boundary 决定 Swing 转向或完成新 N；对**已经 completed 的 N** 的 `N2_ORIGIN/ORIGIN` strict level breach、以及已经建立 Structure 的 trailing-defense strict breach，使用 current high/low 可直接观察且不依赖先后顺序，仍必须记录。
- N completion 固定为第一根 completed 5m strict breach `N1_EXTREME`；equal 不完成；completed N identity、completion time、三个 Pivot 永久不可被 future suffix 改写。
- Completed N 永久保留；`N2_ORIGIN_BROKEN` 与 `ORIGIN_BROKEN` 是后续 immutable event；前者不是 reversal confirmed。
- Range Band V1 只使用 `N1_EXTREME ↔ N2_ORIGIN` 的 exact price span。UP_N 完成后首次 `current.low <= band_upper` 为 re-entry；DOWN_N 完成后首次 `current.high >= band_lower` 为 re-entry。只输出 raw facts，不输出 STRONG/MEDIUM/WEAK 数值标签。
- Structure 至少需要同一 segment 内 2 个 completed N 且有两组可比较 HIGH/LOW；strict higher-high+higher-low=`BULL`，strict lower-high+lower-low=`BEAR`，其余=`RANGE`。equal 不算方向推进。
- BULL defense 是最新 qualifying confirmed LOW；BEAR defense 是最新 qualifying confirmed HIGH。strict defense breach 结束当前 directional structure 并进入 RANGE；不得同 bar 自动反手。
- N/Swing/Structure 全部 rank1 segment-local：trading-day change 不 reset；真实 rank1 contract segment change reset unresolved/active state，不跨合约拼接结构。
- 3/5/8 N price outcome 允许跨 trading day，但绝不跨 rank1 segment；SuBing 既有 5m/15m same-trading-day outcome 语义保持完全不变。
- N Candidate freeze=`2026-08-20T00:22:00+08:00`；retrospective=`2023-01-01..2026-08-19`；`trading_day=2026-08-20` 是 freeze-overlap embargo，不属于 retrospective 或 prospective；prospective OOS 从 `2026-08-21` 开始。
- Rolling historical stability 固定 12 calendar months reference + 3 calendar months test + 3 months step；首 test=2024Q1，末 test=2026Q2，共 10 folds；不在 fold 内调参或重建 Candidate。
- 所有 Candidate/Research output 都是 `research_only`；禁止 KEEP/DROP/PROMOTE/PASS_STRATEGY、盈利、账户收益或交易就绪结论。
- 不新增 HTTP N API、Web overlay、DB/migration、Canonical/Redis state、worker/queue/scheduler、Alert Rule、Scope、notification、Execution Review consumer、订单或账户路径。
- Tasks 1～4 改变价格结构公式/可信语义，属于 Lane 3：Sol + 高推理 + 新会话 + Plan-only；**本 Plan 写成并合入 develop 不等于授权实现**。实施前须由用户批准 Lane 3 Plan，实施后每 Task 独立 Review，Critical=0 / Important=0 才可集成 develop。
- Tasks 5～8 仍不得用其普通开发权限推导 main/tag/Runtime/真实写入授权。
- tracked 变更按 `TESTING.md` 运行适用测试、Ruff/Mypy，运行 `python3 scripts/engineering/secret_scan.py --json` 与 `git diff --check`；必需检查失败不得声明完成。

---

## Codex 调度矩阵

| Task | Lane | Model | 推理 | 会话 | Plan | 工作区 | 人工 Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Exact Policy + contracts | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | `research/n-structure-v1-policy` from latest develop | Plan 批准 + 独立 Review |
| 2 Sequential Swing reducer | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree from updated develop | Plan 批准 + 独立 Review |
| 3 N completion / break / band | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 4 BULL/BEAR/RANGE Structure | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 5 Shared segment loader | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | SuBing zero-regression |
| 6 N Historical Research + price outcomes | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | leakage/outcome review |
| 7 Shared Candidate schedule | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | SuBing Candidate byte/semantic parity |
| 8 N Candidate Validation | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | OOS/embargo review |
| 9 Cumulative verification + implementation Review | Lane 3 review | Sol | 高 | 新独立 Review | Review-only | clean review worktree at develop | Critical=0 / Important=0 |
| 10 `jm` evidence + evidence Review | Lane 1 | Sol | 高 | 新研究会话 + 独立 Review | Plan-then-execute / Review-only | evidence worktree from exact develop | Evidence Critical=0 / Important=0 |

### Worktree / integration model

Tasks 1～8 都按：

```text
latest develop
→ one task branch/worktree
→ RED/GREEN + focused verification
→ required Review
→ task branch → develop
→ read back ancestry
→ clean temporary worktree/merged branch
```

- Tasks 1～4：需要 PR 到 `develop`，用 PR diff 做独立公式/因果 Review；不得自动合并，用户的 Lane 3 Plan 批准只允许实现，不等于 release/runtime。
- Tasks 5～8：测试、自审和规定 Review 通过后允许按仓库普通流程集成 `develop`；不需要触及 `main`。
- Task 9：从 cumulative implementation baseline 到最新 `develop` 做独立只读 Review，不发布。
- Task 10：从 Task 9 验证后的 exact `develop` 创建独立 evidence worktree；evidence Review 后只集成 `develop`。
- 全流程不触及 `main`、release worktree、tag 或 Runtime worktree。

---

## Planned File Structure

### New source files

- `data/research_policies/n_structure_5m_v1.json` — exact N machine semantics。
- `services/quant-api/app/market_data/n_structure_policy.py` — strict exact policy loader。
- `services/quant-api/app/market_data/n_structure_swing.py` — `NSwingPivot` + sequential Swing reducer only。
- `services/quant-api/app/market_data/n_structure_pattern.py` — N base/completion/break/range-band facts only。
- `services/quant-api/app/market_data/n_structure_state.py` — BULL/BEAR/RANGE + trailing defense only。
- `services/quant-api/app/market_data/actual_dominant_research.py` — shared MDS-only segment-prefix loader。
- `services/quant-api/app/market_data/price_outcome.py` — pure price-only 3/5/8 directional outcome primitive。
- `services/quant-api/app/market_data/n_structure_research_service.py` — Historical aggregation over segment traces。
- `services/quant-api/app/market_data/candidate_validation_schedule.py` — shared request/errors/rolling/prospective schedule only。
- `data/research_candidates/n_structure_5m_candidate_v1.json`
- `data/research_protocols/n_structure_validation_v1.json`
- `services/quant-api/app/market_data/n_candidate_validation_policy.py`
- `services/quant-api/app/market_data/n_candidate_validation.py`
- `services/quant-api/app/market_data/n_candidate_validation_service.py`

### New tests

- `services/quant-api/tests/test_n_structure_policy.py`
- `services/quant-api/tests/test_n_structure_swing.py`
- `services/quant-api/tests/test_n_structure_pattern.py`
- `services/quant-api/tests/test_n_structure_state.py`
- `services/quant-api/tests/data_foundation/test_actual_dominant_research.py`
- `services/quant-api/tests/test_price_outcome.py`
- `services/quant-api/tests/data_foundation/test_n_structure_research_service.py`
- `services/quant-api/tests/test_candidate_validation_schedule.py`
- `services/quant-api/tests/test_n_candidate_validation_policy.py`
- `services/quant-api/tests/test_n_candidate_validation.py`
- `services/quant-api/tests/data_foundation/test_n_candidate_validation_service.py`

### Existing files intentionally modified

- `services/quant-api/app/market_data/subing_lifecycle_research_service.py` — consume shared segment loader; no SuBing semantics change。
- `services/quant-api/app/market_data/subing_calibration.py` — delegate price arithmetic only after existing SuBing availability/alignment checks; EMA21 and same-day semantics unchanged。
- `services/quant-api/app/market_data/subing_candidate_validation_service.py` — consume shared validation schedule; existing payload/identity unchanged。
- `services/quant-api/app/market_data/composition.py` — add N research/N candidate builders only。
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_commands.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/tests/test_research_cli.py`
- Task 9 closeout only: `TESTING.md`, `docs/ARCHITECTURE.md`, `STATUS.md`。
- Task 10 evidence closeout only: `STATUS.md`。

### Evidence file (Task 10 only)

- `reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json`

---

# Task 1 — Freeze Exact N Policy and Contract Boundary

**Lane:** Lane 3 / Sol / 高 / new session / Plan-only before implementation.

**Files:**
- Create: `data/research_policies/n_structure_5m_v1.json`
- Create: `services/quant-api/app/market_data/n_structure_policy.py`
- Create: `services/quant-api/tests/test_n_structure_policy.py`
- Read: `docs/superpowers/specs/2026-08-20-n-structure-v1-design.md`
- Read: `services/quant-api/app/market_data/subing_lifecycle_policy.py`

**Interfaces:**

```python
class NStructurePolicyError(ValueError):
    code = "N_STRUCTURE_POLICY_INVALID"

@dataclass(frozen=True, slots=True)
class NStructurePolicy:
    schema_version: int
    policy_id: str
    formula_version: str
    research_only: bool
    source_timeframe: BarFrequency
    breach_basis: str
    equal_is_breach: bool
    outside_bar: str
    inside_bar: str
    extreme_tie: str
    completion: str
    completed_identity_immutable: bool
    n2_break_is_reversal: bool
    origin_break_is_stronger_direction_break: bool
    range_band_definition: str
    strong_medium_weak_labels: bool
    minimum_completed_n: int
    structure_kinds: tuple[str, ...]
    defense_break: str

def load_n_structure_policy(path: Path | None = None) -> NStructurePolicy: ...
```

- [ ] **Step 1: Re-read exact design and create Lane 3 task worktree only after user Plan approval**

```bash
git fetch origin develop
git worktree add ../guiyi-n-structure-v1-policy \
  -b research/n-structure-v1-policy origin/develop
cd ../guiyi-n-structure-v1-policy
git status --short
git log -5 --oneline --decorate
```

Expected: clean latest develop. If current canonical conflicts with the Spec, stop.

- [ ] **Step 2: Write RED exact-policy tests**

```python
def test_load_exact_n_structure_policy() -> None:
    policy = load_n_structure_policy()
    assert policy.policy_id == "n_structure_5m_v1"
    assert policy.formula_version == "n_structure_v1"
    assert policy.research_only is True
    assert policy.source_timeframe is BarFrequency.M5
    assert policy.breach_basis == "previous_bar_high_low"
    assert policy.equal_is_breach is False
    assert policy.outside_bar == "reset_unresolved"
    assert policy.extreme_tie == "keep_first"
    assert policy.completion == "first_strict_n1_extreme_breach"
    assert policy.n2_break_is_reversal is False
    assert policy.strong_medium_weak_labels is False
    assert policy.minimum_completed_n == 2
    assert policy.structure_kinds == ("bull", "bear", "range")
```

Also write parameterized rejection tests for missing/extra nested keys, malformed JSON/UTF-8, wrong schema/id/formula/timeframe, any breach rule drift, `equal_is_breach=true`, outside-bar close arbitration, strong/medium/weak labels enabled, `minimum_completed_n != 2`, or non-strict defense break.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_policy.py
```

Expected: import/file failure.

- [ ] **Step 4: Add the exact JSON from the Spec**

Use the exact payload under Spec §4. Do not add tunable thresholds or optional extension fields.

- [ ] **Step 5: Implement strict loader**

Use exact nested key/value comparison before dataclass construction. Any same-ID semantic drift raises only `N_STRUCTURE_POLICY_INVALID`; do not silently default.

- [ ] **Step 6: Run GREEN + lint**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_policy.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/n_structure_policy.py \
  services/quant-api/tests/test_n_structure_policy.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 7: Independent Lane 3 Review**

Reviewer checks exact Spec parity, absence of knobs/default fallback, no SuBing/Data Foundation changes. Gate: `Critical=0 / Important=0`.

- [ ] **Step 8: Commit and integrate develop only after Review**

```bash
git add data/research_policies/n_structure_5m_v1.json \
  services/quant-api/app/market_data/n_structure_policy.py \
  services/quant-api/tests/test_n_structure_policy.py
git commit -m 'feat(research): freeze N structure v1 policy'
```

Use PR to `develop`; never `main`.

---

# Task 2 — Sequential Causal Swing Reducer

**Lane:** Lane 3 / Sol / 高 / new session / independent Review.

**Files:**
- Create: `services/quant-api/app/market_data/n_structure_swing.py`
- Create: `services/quant-api/tests/test_n_structure_swing.py`
- Read: `services/quant-api/app/market_data/domain.py`
- Read only for contrast: `services/quant-api/app/market_data/subing_structure.py`

**Interfaces:**

```python
class NSwingLeg(StrEnum):
    UNRESOLVED = "unresolved"
    UP = "up"
    DOWN = "down"

class NSwingPivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True, slots=True)
class NSwingPivot:
    pivot_id: str
    kind: NSwingPivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date

@dataclass(frozen=True, slots=True)
class NSwingTrace:
    contract: str
    segment_start_trading_day: date
    pivots: tuple[NSwingPivot, ...]
    ambiguous_outside_reset_at: tuple[datetime, ...]
    final_leg: NSwingLeg

def reduce_n_swings(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    source_timeframe: BarFrequency = BarFrequency.M5,
) -> NSwingTrace: ...
```

- [ ] **Step 1: Write RED contract tests**

Test aware UTC normalization, Decimal finite, M5 only, `pivot_time < confirmed_at`, normalized contract/segment identity and canonical `pivot_id`; wrong values raise `N_STRUCTURE_CONTRACT_INVALID`.

- [ ] **Step 2: Write RED initialization/UP/DOWN golden cases**

Use small explicit `CanonicalBar` fixtures proving:

```text
UNRESOLVED + strict higher high / non-lower low → UP
UP + lower low / non-higher high → confirm first HIGH and switch DOWN
DOWN + higher high / non-lower low → confirm LOW and switch UP
```

Assert `confirmed_at` is the reversal boundary and running extreme `pivot_time` remains the original extreme bar.

- [ ] **Step 3: Write RED tie/inside/outside tests**

```python
def test_equal_extreme_keeps_first_time() -> None: ...
def test_inside_bar_never_reverses_leg() -> None: ...
def test_outside_bar_records_reset_without_pivot() -> None: ...
```

Outside bar must not emit Pivot or infer close-based order; subsequent reducer state restarts from that bar as unresolved seed.

- [ ] **Step 4: Write RED segment/trading-day tests**

The reducer rejects bars outside the supplied segment or non-strictly ordered bars. A trading-day change inside the same segment remains one trace and can confirm a pivot across the day boundary.

- [ ] **Step 5: Write RED prefix-invariance property matrix**

For each golden series and every prefix length `k`:

```python
prefix = reduce_n_swings(bars[:k], ...)
full = reduce_n_swings(bars, ...)
assert tuple(p for p in full.pivots if p.confirmed_at <= bars[k-1].bar_end) == prefix.pivots
```

Also compare outside-reset timestamps up to prefix end.

- [ ] **Step 6: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py
```

- [ ] **Step 7: Implement single-pass reducer**

Implementation must be O(n), keep only previous bar + current leg/running extreme state, and append immutable pivots/resets. No right-hand lookahead, ATR/ZigZag threshold or SuBing import.

- [ ] **Step 8: Run GREEN + static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/n_structure_swing.py \
  services/quant-api/tests/test_n_structure_swing.py
```

- [ ] **Step 9: Independent Lane 3 Review and integrate**

Review strict previous-bar semantics, tie behavior, outside ambiguity and prefix invariance. Gate `Critical=0 / Important=0`; then commit `feat(research): add causal N swing reducer` and PR to develop.

---

# Task 3 — N Pattern Completion, Break Events and Range Band

**Lane:** Lane 3 / Sol / 高 / new session.

**Files:**
- Create: `services/quant-api/app/market_data/n_structure_pattern.py`
- Create: `services/quant-api/tests/test_n_structure_pattern.py`
- Consume: `n_structure_swing.NSwingTrace`
- Consume: exact `NStructurePolicy`

**Interfaces:**

```python
class NDirection(StrEnum):
    UP = "up"
    DOWN = "down"

class NBreakKind(StrEnum):
    N2_ORIGIN_BROKEN = "n2_origin_broken"
    ORIGIN_BROKEN = "origin_broken"

class NRangeBandRole(StrEnum):
    SUPPORT_REFERENCE = "support_reference"
    RESISTANCE_REFERENCE = "resistance_reference"

@dataclass(frozen=True, slots=True)
class NRangeBand:
    lower: Decimal
    upper: Decimal
    role: NRangeBandRole

@dataclass(frozen=True, slots=True)
class CompletedNPattern:
    n_id: str
    direction: NDirection
    origin: NSwingPivot
    n1_extreme: NSwingPivot
    n2_origin: NSwingPivot
    completed_at: datetime
    completion_level: Decimal
    completion_bar_close: Decimal
    completion_overshoot_bps: Decimal
    range_band: NRangeBand

@dataclass(frozen=True, slots=True)
class NBreakEvent:
    event_id: str
    n_id: str
    kind: NBreakKind
    observed_at: datetime
    observed_price: Decimal

@dataclass(frozen=True, slots=True)
class NRangeBandReentryEvent:
    event_id: str
    n_id: str
    observed_at: datetime

@dataclass(frozen=True, slots=True)
class NPatternTrace:
    patterns: tuple[CompletedNPattern, ...]
    break_events: tuple[NBreakEvent, ...]
    range_band_reentries: tuple[NRangeBandReentryEvent, ...]
    incomplete_attempt_replaced_count: int

def evaluate_n_patterns(
    bars: Sequence[CanonicalBar],
    swings: NSwingTrace,
    *,
    policy: NStructurePolicy,
) -> NPatternTrace: ...
```

- [ ] **Step 1: RED alternating-pivot/base tests**

Explicit pivots prove:

```text
LOW-HIGH-LOW with N2 >= ORIGIN → valid UP base
LOW-HIGH-LOW with N2 < ORIGIN  → invalid UP base
HIGH-LOW-HIGH with N2 <= ORIGIN → valid DOWN base
HIGH-LOW-HIGH with N2 > ORIGIN  → invalid DOWN base
```

Equal at ORIGIN is allowed because equal is not a break.

- [ ] **Step 2: RED completion tests**

UP completion is first non-ambiguous completed bar with `high > n1_extreme.price`; DOWN uses `low <`. Equal does not complete. Assert completion can occur at the same boundary that confirms `n2_origin` if that boundary is not in `swings.ambiguous_outside_reset_at`.

- [ ] **Step 3: RED immutable identity/future-extension tests**

Add bars making new highs/lows after completion; assert all `n_id`, three pivots, `completed_at`, completion level and close remain byte/equality stable.

- [ ] **Step 4: RED incomplete replacement / outside reset tests**

When newer confirmed pivots replace a not-yet-completed base, increment diagnostic count and do not expose a failed Pattern object. If an outside reset boundary occurs before completion, discard active incomplete attempt; never complete on that ambiguous bar.

- [ ] **Step 5: RED break-event tests**

For completed UP:

```text
low < n2_origin → N2_ORIGIN_BROKEN
low < origin    → ORIGIN_BROKEN
```

DOWN symmetric. Equal no event. If one bar strictly crosses both levels, preserve both events with deterministic ordering `N2_ORIGIN_BROKEN` then `ORIGIN_BROKEN`. Events fire at most once per N/kind.

**Outside rule:** an outside bar after N completion can emit these level-breach events because the high/low crossing is an observed fact and event identity does not require knowing intrabar order.

- [ ] **Step 6: RED Range Band tests**

Band is exact min/max of N1_EXTREME and N2_ORIGIN. UP role support, DOWN resistance.

First re-entry:

```text
UP   current.low <= band.upper
DOWN current.high >= band.lower
```

Only evaluate bars after `completed_at`; emit one first-reentry event per N. A bar may re-enter and also break N2/origin; preserve both raw facts. Assert serialized/domain keys never include STRONG/MEDIUM/WEAK.

- [ ] **Step 7: Run RED, implement O(n + active-pattern assessments), run GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_swing.py
```

Implementation must index bars by `bar_end`, never search future bars for completion. Avoid rescanning all history on each boundary; completed patterns only need outstanding first reentry/N2/origin flags.

- [ ] **Step 8: Prefix-invariance regression**

For every prefix, completed patterns and events with timestamps in the prefix equal the corresponding full-trace subset.

- [ ] **Step 9: Independent Lane 3 Review and integrate**

Gate `Critical=0 / Important=0`; commit `feat(research): add causal N pattern facts`; PR to develop.

---

# Task 4 — BULL / BEAR / RANGE Structure and Trailing Defense

**Lane:** Lane 3 / Sol / 高 / new session.

**Files:**
- Create: `services/quant-api/app/market_data/n_structure_state.py`
- Create: `services/quant-api/tests/test_n_structure_state.py`
- Consume: Swing + N Pattern traces.

**Interfaces:**

```python
class NStructureKind(StrEnum):
    UNDEFINED = "undefined"
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"

@dataclass(frozen=True, slots=True)
class NStructureSnapshot:
    observed_at: datetime
    kind: NStructureKind
    established_at: datetime | None
    trailing_defense: NSwingPivot | None
    completed_n_count: int

@dataclass(frozen=True, slots=True)
class NStructureTransition:
    transition_id: str
    transition_at: datetime
    from_kind: NStructureKind
    to_kind: NStructureKind
    reason_code: str
    trailing_defense_pivot_id: str | None

@dataclass(frozen=True, slots=True)
class NStructureTrace:
    snapshots: tuple[NStructureSnapshot, ...]
    transitions: tuple[NStructureTransition, ...]

def evaluate_n_market_structure(
    bars: Sequence[CanonicalBar],
    *,
    swings: NSwingTrace,
    patterns: NPatternTrace,
    policy: NStructurePolicy,
) -> NStructureTrace: ...
```

- [ ] **Step 1: RED minimum-evidence tests**

Before 2 completed N, `UNDEFINED`; never infer directional structure from one N alone.

- [ ] **Step 2: RED classification golden matrix**

With 2+ completed N and two comparable highs/lows:

```text
H2 > H1 and L2 > L1 → BULL
H2 < H1 and L2 < L1 → BEAR
all other combinations, including any equality → RANGE
```

- [ ] **Step 3: RED trailing-defense progression**

For BULL, defense is latest qualifying LOW participating in a completed higher-high+higher-low pair. A new low alone cannot advance defense until the paired higher-high evidence exists. BEAR symmetric.

- [ ] **Step 4: RED strict structure-break behavior**

```text
BULL + current.low < defense.price → BULL_STRUCTURE_BROKEN → RANGE
BEAR + current.high > defense.price → BEAR_STRUCTURE_BROKEN → RANGE
```

Equal does not break. Break bar does not auto-establish opposite structure; subsequent confirmed high/low pairs are required.

An ambiguous outside bar can still break an already-established defense because strict level crossing is path-independent; it still cannot confirm a new Swing/N on the same boundary.

- [ ] **Step 5: RED RANGE re-establishment tests**

RANGE has no defense. Subsequent strict HH+HL establishes BULL; LH+LL establishes BEAR. Each transition has stable identity/reason.

- [ ] **Step 6: RED prefix and immutability tests**

Historical transitions/snapshots already observed in prefix are unchanged by suffix. Active trailing defense may only move in the favorable structural direction via new qualifying evidence.

- [ ] **Step 7: Implement deterministic boundary order**

For each completed bar:

```text
1. evaluate already-established N/Structure strict level breaks from current high/low
2. apply Swing boundary (outside may reset unresolved state)
3. consume any newly confirmed Pivot
4. consume any newly completed N
5. classify/reclassify Structure and advance defense
6. append immutable snapshot/transition facts
```

This order prevents outside-bar intrabar guessing while preserving path-independent level breaches.

- [ ] **Step 8: Run GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py
```

- [ ] **Step 9: Independent Lane 3 Review and integrate**

Review source-vs-engineering labeling, structure minimum, defense movement, outside behavior, no auto reversal, prefix invariance. Gate `Critical=0 / Important=0`; commit `feat(research): add N market structure reducer`; PR to develop.

---

# Task 5 — Extract Shared Actual-Dominant Research Segment Loader

**Lane:** Lane 2 / Sol / 高 because it changes a shared historical research boundary.

**Files:**
- Create: `services/quant-api/app/market_data/actual_dominant_research.py`
- Create: `services/quant-api/tests/data_foundation/test_actual_dominant_research.py`
- Modify: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py`

**Interfaces:**

```python
class _ActualDominantResearchReader(Protocol):
    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult: ...
    def dominant_segment_for_day(
        self, symbol: str, trading_day: date
    ) -> DominantContractSegmentSummary: ...

@dataclass(frozen=True, slots=True)
class ActualDominantResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesResult]
    segments: tuple[ResolvedContractSegment, ...]

class ActualDominantResearchSegmentLoader:
    def __init__(self, market_data: _ActualDominantResearchReader) -> None: ...
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...
```

- [ ] **Step 1: Characterize existing SuBing behavior before extraction**

Run and record current focused test count/hashable golden payload fixtures before code changes:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 2: RED shared-loader tests**

Port exact behaviors from current `SubingLifecycleResearchService._query_product/_restore_true_segments/_validate_segment_coverage` into new tests:

- probe only exact requested trading days;
- restore containing true rank1 segment via `dominant_segment_for_day`;
- full read restarts at true first segment start;
- cross-frequency segment identities must match;
- overlapping/missing segment coverage fails;
- source methods are only MDS public research methods.

- [ ] **Step 3: Implement loader by extraction, not rewrite**

Move the existing validated algorithm with no semantic broadening. Loader must not import Catalog/store/RQData/Redis.

- [ ] **Step 4: Replace SuBing private logic with shared loader**

`SubingLifecycleResearchService.__init__` may retain the current market_data constructor and internally create `ActualDominantResearchSegmentLoader(market_data)` so composition/API call sites do not change. `_query_product` becomes a thin call to `loader.load(frequencies=(M5,M15), ...)`.

- [ ] **Step 5: Run shared + full SuBing zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_research_cli.py
```

Existing SuBing JSON semantics/counts must not change.

- [ ] **Step 6: Static checks + commit/integrate**

Commit `refactor(research): share actual-dominant segment loading`. Integration only to develop.

---

# Task 6 — Price-Only Outcomes, N Historical Research and `n-structure` CLI

**Lane:** Lane 1 / Sol / 高 due horizon/leakage semantics.

**Files:**
- Create: `services/quant-api/app/market_data/price_outcome.py`
- Create: `services/quant-api/tests/test_price_outcome.py`
- Modify: `services/quant-api/app/market_data/subing_calibration.py`
- Modify: existing SuBing calibration/lifecycle tests
- Create: `services/quant-api/app/market_data/n_structure_research_service.py`
- Create: `services/quant-api/tests/data_foundation/test_n_structure_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces — price only:**

```python
class PriceDirection(StrEnum):
    LONG = "long"
    SHORT = "short"

@dataclass(frozen=True, slots=True)
class PriceDirectionalOutcome:
    horizon: int
    directional_return_bps: Decimal
    mfe_bps: Decimal
    mae_bps: Decimal

@dataclass(frozen=True, slots=True)
class PriceHorizonEvaluation:
    sample_count: int
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None

def calculate_price_outcome(
    *, entry_close: Decimal, future_bars: Sequence[CanonicalBar], direction: PriceDirection
) -> PriceDirectionalOutcome: ...

def build_price_outcomes_at(
    bars: Sequence[CanonicalBar],
    *, index: int,
    direction: PriceDirection,
    horizons: Sequence[int] = (3, 5, 8),
    same_trading_day_only: bool,
) -> Mapping[int, PriceDirectionalOutcome | None]: ...
```

**Interfaces — N research:**

```python
@dataclass(frozen=True, slots=True)
class NStructureResearchRequest:
    since: date
    through: date
    symbol: str | None

@dataclass(frozen=True, slots=True)
class NStructureResearchResult:
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    confirmed_pivot_count: int
    ambiguous_outside_reset_count: int
    incomplete_attempt_replaced_count: int
    completed_n_counts: Mapping[str, int]
    n_break_counts: Mapping[str, int]
    range_band_reentry_count: int
    structure_established_counts: Mapping[str, int]
    structure_break_counts: Mapping[str, int]
    horizon_summary: Mapping[int, PriceHorizonEvaluation]

class NStructureResearchService:
    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult: ...
```

- [ ] **Step 1: RED price formula tests**

Use explicit Decimal bars for LONG/SHORT 3-bar horizons and verify exact directional return/MFE/MAE. Verify insufficient future bars returns None at builder layer.

- [ ] **Step 2: RED horizon boundary tests**

`same_trading_day_only=True` rejects a horizon crossing trading_day; `False` permits it. No builder may cross the supplied segment because caller only supplies one segment’s bars.

- [ ] **Step 3: Refactor SuBing arithmetic with characterization safety**

Keep all existing SuBing factor availability/alignment/contract checks **before** delegating price arithmetic. Call the shared calculation only after the old code would have accepted the same future bars; preserve `same_trading_day_only=True` and EMA21 computation exactly.

Run existing SuBing calibration/lifecycle golden tests and assert no payload/metric changes.

- [ ] **Step 4: RED N research service tests**

Fake `ActualDominantResearchSegmentLoader`/MDS results prove:

- M5 only;
- reducer starts at true segment start but counts `evaluable_bar_count`/events only when `since <= trading_day <= through`;
- segment change produces separate traces;
- completed N counts split up/down;
- outside reset/incomplete replacement/break/band/structure counts exact;
- 3/5/8 outcome entry is `completion_bar_close` at completion index;
- N outcome can cross trading day in same segment;
- outcome never has future bars beyond request `through` or next rank1 segment.

- [ ] **Step 5: Implement N research aggregation**

One reducer run per true segment. Use dictionaries by `bar_end` to locate completion indices; no future data outside loaded prefix. Aggregate `PriceHorizonEvaluation` using medians only, no pass/fail score.

- [ ] **Step 6: RED/implement read-only CLI**

Add parser:

```text
guiyi research n-structure --since YYYY-MM-DD --through YYYY-MM-DD [--symbol jm]
```

Add explicit `NStructureResearchRequest` branch in `ResearchRequest`, `run_research_command`, `main()` service routing, and composition builder. Required JSON:

```text
schema_version=1
command=research.n-structure
status=ok
readonly=true
policy_id=n_structure_5m_v1
formula_version=n_structure_v1
research_only=true
since/through/products
all N source metrics
horizon_summary with price-only fields
```

No EMA21 field in N horizon payload.

- [ ] **Step 7: Run focused and upstream regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_price_outcome.py \
  services/quant-api/tests/data_foundation/test_n_structure_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
```

- [ ] **Step 8: Commit/integrate**

Commit `feat(research): add N structure historical research`; integrate only develop.

---

# Task 7 — Extract Shared Candidate Validation Schedule Without Changing SuBing

**Lane:** Lane 2 / Sol / 高 due shared contract refactor.

**Files:**
- Create: `services/quant-api/app/market_data/candidate_validation_schedule.py`
- Create: `services/quant-api/tests/test_candidate_validation_schedule.py`
- Modify: `services/quant-api/app/market_data/subing_candidate_validation_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Read: existing `candidate_validation.py` / `candidate_validation_policy.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

class CandidateValidationIdentityError(ValueError):
    code = "CANDIDATE_VALIDATION_IDENTITY_MISMATCH"
class CandidateValidationWindowError(ValueError):
    code = "CANDIDATE_VALIDATION_WINDOW_INVALID"
class CandidateValidationSourceError(ValueError):
    code = "CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE"

@dataclass(frozen=True, slots=True)
class RollingValidationWindow:
    fold_id: str
    reference_since: date
    reference_through: date
    test_since: date
    test_through: date

def build_rolling_validation_windows(...exact month inputs...) -> tuple[RollingValidationWindow, ...]: ...
def prospective_window(*, through: date, first_trading_day: date) -> tuple[date, date] | None: ...
```

- [ ] **Step 1: Characterize current SuBing Candidate objects/payload**

Run current Candidate focused suite and save test fixture comparison in-memory/test code, not a new long-lived artifact.

- [ ] **Step 2: RED generic schedule tests**

Verify request normalization has no protocol-specific date; 12/3/3 inputs generate exact 10 folds; prospective helper returns None before first day and exact `(first_day, through)` at/after first day; invalid month/order inputs fail.

- [ ] **Step 3: Extract request/errors/month helpers from SuBing service**

Move code, do not alter signatures/error codes. Keep SuBing-specific `CandidateManifest`, report contracts and quality flags where they are.

- [ ] **Step 4: Replace SuBing fold/prospective date math with shared helper**

Source window calls, results, flags and serialized JSON must remain identical for existing Candidate Protocol.

- [ ] **Step 5: Run SuBing Candidate zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

No generic Strategy interface/registry is permitted.

- [ ] **Step 6: Commit/integrate**

Commit `refactor(research): share candidate validation schedule`; integrate develop.

---

# Task 8 — N Candidate/Protocol and N-Specific Candidate Validation

**Lane:** Lane 1 / Sol / 高 due OOS/embargo semantics.

**Files:**
- Create: `data/research_candidates/n_structure_5m_candidate_v1.json`
- Create: `data/research_protocols/n_structure_validation_v1.json`
- Create: `services/quant-api/app/market_data/n_candidate_validation_policy.py`
- Create: `services/quant-api/app/market_data/n_candidate_validation.py`
- Create: `services/quant-api/app/market_data/n_candidate_validation_service.py`
- Create: corresponding three test files
- Modify: composition + research parser/commands/main + CLI tests

**Exact Candidate:**

```json
{
  "schema_version": 1,
  "candidate_id": "n_structure_5m_candidate_v1",
  "source_kind": "n_structure",
  "policy_id": "n_structure_5m_v1",
  "formula_version": "n_structure_v1",
  "research_only": true
}
```

**Exact Protocol:**

```json
{
  "schema_version": 1,
  "protocol_id": "n_structure_validation_v1",
  "research_only": true,
  "candidate_frozen_at": "2026-08-20T00:22:00+08:00",
  "retrospective": {"since": "2023-01-01", "through": "2026-08-19"},
  "embargo_trading_days": ["2026-08-20"],
  "rolling_stability": {
    "reference_months": 12,
    "test_months": 3,
    "step_months": 3,
    "first_test_since": "2024-01-01",
    "last_test_through": "2026-06-30"
  },
  "prospective_oos": {"first_trading_day": "2026-08-21"},
  "horizons_bars": [3, 5, 8]
}
```

The policy loader must cross-check exact N policy identity. `2026-08-20` can never be reported as retrospective/prospective evidence.

**N report contracts:**

```python
@dataclass(frozen=True, slots=True)
class NCandidateWindowResult:
    window_id: str
    window_kind: CandidateWindowKind
    since: date
    through: date
    segment_count: int
    evaluable_bar_count: int
    confirmed_pivot_count: int
    completed_n_counts: Mapping[str, int]
    n_break_counts: Mapping[str, int]
    range_band_reentry_count: int
    structure_established_counts: Mapping[str, int]
    structure_break_counts: Mapping[str, int]
    horizon_summary: Mapping[int, PriceHorizonEvaluation]

@dataclass(frozen=True, slots=True)
class NRollingStabilitySummary:
    fold_count: int
    folds_with_completed_n: int
    completed_n_min: int
    completed_n_max: int
    completed_n_median: Decimal

@dataclass(frozen=True, slots=True)
class NStructureCandidateValidationReport:
    schema_version: int
    candidate_id: str
    policy_id: str
    formula_version: str
    protocol_id: str
    research_only: bool
    symbol: str
    retrospective: NCandidateWindowResult
    rolling_folds: tuple[NRollingCandidateFold, ...]
    rolling_stability: NRollingStabilitySummary
    prospective_oos: NProspectiveOosResult
    quality_flags: tuple[str, ...]
```

- [ ] **Step 1: RED exact manifest/protocol tests**

Reject extra/missing/wrong values, freeze drift, wrong retrospective, missing embargo, prospective start 2026-08-20, wrong folds/horizons, or policy identity mismatch.

- [ ] **Step 2: RED N projection/stability tests**

Projection copies N research source facts without recalculation. Stability counts total completed N in each test fold; no threshold score.

- [ ] **Step 3: RED orchestration tests**

Using fake N research runner, prove source requests:

```text
retrospective = 2023-01-01..2026-08-19
10 rolling reference/test windows exactly as frozen
through=2026-08-19 or 2026-08-20 → prospective pending; no OOS source call
through>=2026-08-21 → prospective source since=2026-08-21
```

Also assert no source request has `since=2026-08-20` for an evidence window.

- [ ] **Step 4: Expand candidate CLI routing without registry**

`candidate-validation` parser choices become the two exact IDs/protocols. In `main()` select exact service factory by candidate ID:

```text
subing_lifecycle_v2_candidate_v1 → existing SubingCandidateValidationService
n_structure_5m_candidate_v1     → NStructureCandidateValidationService
unknown                          → CLI argument failure
```

Invalid cross-pair candidate/protocol is rejected by the selected exact service.

`run_research_command()` accepts either existing `CandidateValidationReport` or new `NStructureCandidateValidationReport`; existing SuBing `_candidate_payload()` output must remain byte/semantic identical. Add separate `_n_candidate_payload()`.

- [ ] **Step 5: Required N Candidate JSON shape**

Top-level remains:

```text
schema_version
command=research.candidate-validation
status=ok
readonly=true
candidate/policy/formula/protocol/research_only/symbol
retrospective
rolling_folds
rolling_stability
prospective_oos
quality_flags
```

N nested window fields remain N-specific; no SuBing confirmation/V1-overlap/EMA21 keys.

- [ ] **Step 6: Run focused + SuBing zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_candidate_validation_policy.py \
  services/quant-api/tests/test_n_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 7: Commit/integrate**

Commit `feat(research): validate N structure candidate`; integrate develop only.

---

# Task 9 — Full Causality Verification, Canonical Docs and Independent Implementation Review

**Lane:** Lane 3 review / Sol / 高 / new independent Review session.

**Files:**
- Review cumulative source/test diff from pre-Task-1 baseline through Task 8.
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify after all Gate pass: `STATUS.md`

- [ ] **Step 1: Run complete N focused suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_policy.py \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/test_price_outcome.py \
  services/quant-api/tests/data_foundation/test_n_structure_research_service.py \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_n_candidate_validation_policy.py \
  services/quant-api/tests/test_n_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 2: Run complete upstream SuBing regression**

At minimum:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
```

- [ ] **Step 3: Run generated prefix-invariance matrix**

Test fixtures must cover:

```text
straight trend
inside bars
equal highs/lows
multiple ties
outside reset before N completion
outside bar after completed N causing N break
outside bar causing Structure defense break
trading-day transition within segment
rank1 segment reset
same-bar N2 confirmation + N completion
N2 break without origin break
N2 + origin break same bar
BULL/RANGE/BEAR transitions
```

For each fixture, all prefix-confirmed pivots/N/events/transitions must equal full-trace subsets.

- [ ] **Step 4: Static/security checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: Update TESTING/ARCHITECTURE narrowly**

Architecture must show:

```text
MDS
→ shared actual-dominant research loader
→ SuBing Lifecycle / N Structure (independent domains)
→ source-specific research results
→ shared schedule only
→ source-specific Candidate reports
```

Document N as Historical/research-only, not backtest/Alert/live.

- [ ] **Step 6: Independent implementation Review checklist**

Classify Critical/Important/Minor. Required checks:

```text
1 source terminology matches book; engineering inventions labeled
2 only 5m completed Historical actual-dominant
3 no SuBing Pivot reuse/coupling
4 previous-bar strict Swing, equal/inside/outside exact
5 outside bar never guesses intrabar order
6 outside can still emit path-independent existing level breaks
7 completed N first strict N1 breach and immutable identity
8 N2 break not reversal; origin break separate
9 no strong/medium/weak invented thresholds
10 Structure requires >=2 completed N and strict HH/HL or LH/LL
11 defense advancement/break and no auto reversal exact
12 segment-local, trading-day continuity, rank1 reset
13 prefix invariance for every immutable fact
14 N outcomes cross day only within same segment
15 SuBing same-day outcome/payload unchanged
16 MDS is only Historical gateway
17 Candidate 2026-08-20 embargo and prospective start 2026-08-21 exact
18 no plugin/registry/DB/Web/Alert/Runtime/order expansion
19 no auto strategy-quality verdict
```

Gate: `Critical=0 / Important=0`. Any such finding requires fix + fresh full verification before closeout.

- [ ] **Step 7: Update STATUS only after review is clean**

Record only:

```text
N Structural Domain V1 implementation exists in develop
research_only / Historical-only / 5m-only
second Candidate producer exists
N prospective boundary starts 2026-08-21; 2026-08-20 is embargo
formal jm Candidate evidence has NOT yet been generated
no strategy effectiveness / Alert / release / Runtime claim
```

- [ ] **Step 8: Read back develop identity**

Confirm cumulative code is in develop; no main/tag/Runtime action. Clean any review worktree.

---

# Task 10 — Exact-Develop Real `jm` N Baseline, Candidate Evidence and Evidence Review

**Lane:** Lane 1 / Sol / 高; new research session followed by independent Review.

**Files:**
- Create: `reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json`
- Modify after evidence review only: `STATUS.md`

- [ ] **Step 1: Create clean evidence worktree from exact reviewed develop**

```bash
git fetch origin develop
git worktree add ../guiyi-n-structure-jm-evidence \
  -b research/n-structure-jm-evidence origin/develop
cd ../guiyi-n-structure-jm-evidence
git status --short
git rev-parse HEAD
```

- [ ] **Step 2: Run real read-only `n-structure` preflight**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research n-structure \
  --since 2023-01-01 \
  --through 2026-08-19 \
  --symbol jm \
  > /tmp/n-structure-jm-preflight.json
```

Validate `readonly=true`, exact policy/formula/product, all required source metrics and horizon keys `3/5/8`. Do not commit preflight.

- [ ] **Step 3: Generate exact Candidate baseline**

```bash
mkdir -p reports/research/candidate_validation/n_structure_5m_candidate_v1
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate n_structure_5m_candidate_v1 \
  --protocol n_structure_validation_v1 \
  --symbol jm \
  --through 2026-08-20 \
  > reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json
```

This command must not query an OOS window because `through < 2026-08-21`; prospective result must be pending. It also must not label 2026-08-20 as retrospective.

- [ ] **Step 4: Validate artifact contract**

```python
assert payload["command"] == "research.candidate-validation"
assert payload["readonly"] is True
assert payload["research_only"] is True
assert payload["candidate_id"] == "n_structure_5m_candidate_v1"
assert payload["policy_id"] == "n_structure_5m_v1"
assert payload["formula_version"] == "n_structure_v1"
assert payload["protocol_id"] == "n_structure_validation_v1"
assert payload["symbol"] == "jm"
assert payload["retrospective"]["through"] == "2026-08-19"
assert len(payload["rolling_folds"]) == 10
assert payload["prospective_oos"]["status"] == "pending"
assert payload["prospective_oos"]["first_trading_day"] == "2026-08-21"
```

Scan that `2026-08-20` appears only as protocol/embargo/through context, never as a retrospective/prospective result window.

- [ ] **Step 5: Recompute twice for determinism**

Run the exact command again to `/tmp/n-candidate-repeat.json`; byte-compare or canonical JSON-compare with the tracked artifact. Any mismatch blocks evidence acceptance.

- [ ] **Step 6: Secret/diff checks and commit generated artifact without metric edits**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
git add reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json
git commit -m 'research(n-structure): add jm candidate baseline'
```

- [ ] **Step 7: Independent evidence Review**

Review exact identity, 10 folds, source metric completeness, horizon samples, embargo, prospective pending, deterministic recompute and absence of profitability/promotion claims.

Gate: `Critical=0 / Important=0`.

- [ ] **Step 8: Update STATUS and integrate evidence to develop**

Only after accepted evidence, record artifact path and exact non-conclusion:

```text
N Candidate retrospective/rolling baseline exists and is reproducible.
Prospective OOS evidence is still pending and begins no earlier than trading_day 2026-08-21.
No effectiveness/promotion/Alert/release/Runtime conclusion.
```

Integrate evidence branch to develop, read back ancestry, then cleanup worktree/branch.

---

## Final Acceptance Criteria

N 字 Structural Domain V1 is complete only when all are true:

```text
[ ] exact n_structure_5m_v1 policy is strict-loaded
[ ] sequential Swing is causal, 5m-only and prefix-invariant
[ ] equal/inside/outside rules match frozen design
[ ] outside ambiguity never invents intrabar order
[ ] UP/DOWN N base/completion semantics are exact
[ ] completed N history is immutable
[ ] N2/origin breaks are separate immutable facts
[ ] range band is raw N1-N2 span with no machine strong/medium/weak score
[ ] BULL/BEAR/RANGE requires >=2 completed N and strict high/low progression
[ ] trailing defense advances/ends exactly and no break auto-reverses
[ ] all N/Structure state is rank1 segment-local
[ ] shared actual-dominant loader preserves SuBing behavior
[ ] N research reads only MarketDataService Historical path
[ ] price outcome reuse preserves SuBing same-day/EMA21 semantics
[ ] candidate schedule extraction preserves existing SuBing Candidate payload
[ ] N exact Candidate/Protocol are strict-loaded
[ ] 2026-08-20 is embargo, never OOS
[ ] N prospective OOS starts 2026-08-21
[ ] all focused/upstream/static checks pass
[ ] implementation Review Critical=0 / Important=0
[ ] real jm retrospective/rolling candidate evidence exists and recomputes deterministically
[ ] evidence Review Critical=0 / Important=0
[ ] STATUS contains only exact research facts
[ ] main/tag/Runtime/Alert/Scope/notification/DB/Canonical/order remain untouched
```

Completion authorizes only the next research decision: accumulate N/SuBing prospective OOS and compare candidates, or proceed to the next approved research domain. It does not authorize Candidate promotion or a third production Alert Rule.
