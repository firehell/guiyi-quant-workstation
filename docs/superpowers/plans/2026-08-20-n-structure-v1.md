# N 字 Structural Domain V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 5m-only、research-only、prefix-invariant 的 N 字价格结构域，使其成为 Candidate Validation 的第二个真实 producer，并形成可复算的 `jm` retrospective/rolling evidence。

**Architecture:** `MarketDataService → shared actual-dominant segment loader → N Swing(epoch) → Completed N → immutable break/band facts → BULL/BEAR/RANGE Structure → N Historical Research → N Candidate Validation`。N 不依赖 SuBing Pivot；第二 producer 出现后只抽取已经真实重复的 segment loading、price arithmetic 和 validation schedule，不建设 Strategy Plugin/Registry。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、MarketDataService、现有 FastAPI composition/CLI、pytest、Ruff、Mypy、JSON research artifacts。

**Spec:** `docs/superpowers/specs/2026-08-20-n-structure-v1-design.md`

**Task Contract:** `docs/tasks/TASK-N-STRUCTURE-V1-20260820.md`

## Global Constraints

- 每个 Task 开始前重读 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 与最新 `develop`；冲突时 fail-closed。
- 来源术语固定：`UP_N / DOWN_N`；机器点 `ORIGIN / N1_EXTREME / N2_ORIGIN / COMPLETION`；阶段只叫 `N1 / N1_N2 / N2`。
- 5m completed Historical actual-dominant only；唯一历史入口是 `MarketDataService`；不读 Live/Redis，不直读 Parquet/RQData，不自行判 rank1。
- Swing 使用 previous-bar strict high/low breach；equal 不破；tie keep first；inside 不反转；outside 进入新 `swing_epoch`，不 confirm Pivot、不完成新 N、不跨 epoch 拼 N。
- Outside 对 bar 开始前已存在的 N2/ORIGIN/Structure defense strict level crossing 仍可记录；这是 path-independent price fact。
- N completion=first non-outside completed boundary strict breach `N1_EXTREME`；equal 不完成；completed identity 永不回写。
- 新 N 若在 completion boundary 同时 strict 穿越自己的 N2/ORIGIN，则完成事实与 break facts 同 timestamp 记录，不声称 intrabar 顺序。
- `completion_overshoot_bps` exact formula按 Spec §8.8；Range Band exact span按 Spec §10，first re-entry 从 `bar_end > completed_at` 才开始。
- Structure 新建立/重新建立只用同 `swing_epoch` 且至少 2 completed N 的证据；directional structure defense strict break → RANGE，不自动反手。
- N outcome 允许跨 trading day，但绝不能跨 rank1 segment；SuBing 原有 same-day + EMA21 semantics 完全不变。
- N Candidate：`n_structure_5m_candidate_v1 × n_structure_validation_v1`；retrospective through `2026-08-19`；`2026-08-20` embargo；prospective first trading day `2026-08-21`。
- 不新增强/中/弱机器阈值、recursive fractal、Web/API N surface、DB/Redis、worker/queue、Alert/Scope/notification、Execution Review consumer、订单/PnL/equity、自动 promotion。
- Tasks 1～4 是 Lane 3 价格结构公式/因果语义；本 docs 提交**不授权实现**。用户后续须明确批准 Lane 3 Plan 才能实现；每 Task 独立 Review `Critical=0 / Important=0` 才允许集成 develop。
- 本阶段任何 develop 集成都不授权 main/tag/release/Runtime/真实数据写入/通知/订单。
- tracked 变更按 `TESTING.md` 跑适用测试、Ruff/Mypy、`python3 scripts/engineering/secret_scan.py --json`、`git diff --check`。

---

## Codex 调度矩阵

| Task | Lane | Model | 推理 | 会话 | Plan | Workspace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Exact Policy | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 2 Swing epoch reducer | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 3 N completion/break/band | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 4 Structure state | Lane 3 | Sol | 高 | 新会话 | Plan-only → 批准后 execute | 新 task worktree | Plan 批准 + 独立 Review |
| 5 Shared segment loader | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | SuBing zero regression |
| 6 Price outcome + N research | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | temporal leakage Review |
| 7 Shared candidate schedule | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | SuBing Candidate parity |
| 8 N Candidate Validation | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 新 task worktree | OOS/embargo Review |
| 9 Cumulative verification | Lane 3 review | Sol | 高 | 新独立 Review | Review-only | clean develop review worktree | Critical=0 / Important=0 |
| 10 `jm` evidence | Lane 1 | Sol | 高 | 新研究 + 独立 Review | Plan-then-execute | evidence worktree | Evidence Critical=0 / Important=0 |

### Worktree lifecycle

Each Task 1～8:

```text
latest develop
→ new task branch/worktree
→ RED/GREEN + focused verification
→ required Review
→ integrate task branch → develop
→ read back ancestry
→ cleanup merged worktree/branch
```

Tasks 1～4 需要 PR to `develop` 做公式/因果 Review；不得自动 merge。Tasks 5～8 可在测试/Review 满足本 Plan 后按仓库普通流程合入 develop。Task 10 使用独立 evidence branch。所有步骤禁止碰 `main`、tag 或 Runtime worktree。

---

## Planned Files

### New implementation files

```text
data/research_policies/n_structure_5m_v1.json
services/quant-api/app/market_data/n_structure_policy.py
services/quant-api/app/market_data/n_structure_swing.py
services/quant-api/app/market_data/n_structure_pattern.py
services/quant-api/app/market_data/n_structure_state.py
services/quant-api/app/market_data/actual_dominant_research.py
services/quant-api/app/market_data/price_outcome.py
services/quant-api/app/market_data/n_structure_research_service.py
services/quant-api/app/market_data/candidate_validation_schedule.py
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/n_structure_validation_v1.json
services/quant-api/app/market_data/n_candidate_validation_policy.py
services/quant-api/app/market_data/n_candidate_validation.py
services/quant-api/app/market_data/n_candidate_validation_service.py
```

### Existing files modified intentionally

```text
services/quant-api/app/market_data/subing_lifecycle_research_service.py
services/quant-api/app/market_data/subing_calibration.py
services/quant-api/app/market_data/subing_candidate_validation_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_research_cli.py
TESTING.md
docs/ARCHITECTURE.md
STATUS.md
```

No Market Foundation schema/Catalog/API/Web/Alert/Runtime file belongs to this scope.

---

# Task 1 — Exact N Structure Policy

**Lane:** Lane 3 / Sol / 高.

**Files:**
- Create `data/research_policies/n_structure_5m_v1.json`
- Create `services/quant-api/app/market_data/n_structure_policy.py`
- Create `services/quant-api/tests/test_n_structure_policy.py`

**Produces:**

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
    raw: Mapping[str, object]

def load_n_structure_policy(path: Path | None = None) -> NStructurePolicy: ...
```

- [ ] **Step 1: Create worktree after explicit Lane 3 Plan approval**

```bash
git fetch origin develop
git worktree add ../guiyi-n-policy -b research/n-structure-v1-policy origin/develop
cd ../guiyi-n-policy
git status --short
```

- [ ] **Step 2: Write RED exact loader test**

```python
def test_load_exact_policy() -> None:
    p = load_n_structure_policy()
    assert p.policy_id == "n_structure_5m_v1"
    assert p.formula_version == "n_structure_v1"
    assert p.research_only is True
    assert p.source_timeframe is BarFrequency.M5
    assert p.raw["swing"]["outside_bar"] == "reset_unresolved_epoch"
    assert p.raw["n_pattern"]["same_boundary_completion_break"] == (
        "record_both_without_intrabar_order_claim"
    )
    assert p.raw["outcome"]["may_cross_trading_day"] is True
    assert p.raw["outcome"]["may_cross_rank1_segment"] is False
```

Add parameterized malformed/extra/missing/drift fixtures; every one raises `N_STRUCTURE_POLICY_INVALID`.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_structure_policy.py
```

Expected import/file failure.

- [ ] **Step 4: Create exact JSON**

Copy the exact JSON from Spec §5 verbatim. No optional thresholds, no defaults, no environment override.

- [ ] **Step 5: Implement strict loader and run GREEN**

Loader compares exact nested type/key/value shape before constructing the dataclass.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_structure_policy.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  ruff check services/quant-api/app/market_data/n_structure_policy.py \
  services/quant-api/tests/test_n_structure_policy.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 6: Independent Review + commit**

Gate `Critical=0 / Important=0`; then commit:

```bash
git add data/research_policies/n_structure_5m_v1.json \
  services/quant-api/app/market_data/n_structure_policy.py \
  services/quant-api/tests/test_n_structure_policy.py
git commit -m 'feat(research): freeze N structure v1 policy'
```

PR to develop only.

---

# Task 2 — Sequential Causal Swing Reducer with Epoch Barrier

**Lane:** Lane 3 / Sol / 高.

**Files:**
- Create `services/quant-api/app/market_data/n_structure_swing.py`
- Create `services/quant-api/tests/test_n_structure_swing.py`

**Produces:**

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
    epoch: int
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
    final_epoch: int
    final_leg: NSwingLeg

def reduce_n_swings(...exact segment args...) -> NSwingTrace: ...
```

- [ ] **Step 1: RED contract tests**

```python
def test_pivot_requires_m5_aware_positive_decimal_and_epoch() -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID"):
        NSwingPivot(..., epoch=-1, ...)
```

Also cover `pivot_time < confirmed_at`, contract normalization and canonical id including epoch.

- [ ] **Step 2: RED golden direction test**

Build explicit bars:

```text
b0 seed
b1 higher-high + non-lower-low → UP
b2 strict higher high          → running high=b2
b3 lower-low + non-higher-high → confirm HIGH@b2, confirmed_at=b3, switch DOWN
b4 strict lower low
b5 higher-high + non-lower-low → confirm LOW@b4, switch UP
```

Assert exact pivot times/prices/confirmation times.

- [ ] **Step 3: RED equal/inside/outside tests**

```python
def test_equal_extreme_keeps_first_pivot_time() -> None: ...
def test_inside_bar_does_not_reverse() -> None: ...
def test_outside_bar_increments_epoch_and_emits_no_pivot() -> None: ...
```

After outside, current bar becomes new unresolved seed; next pivots carry `epoch+1`.

- [ ] **Step 4: RED trading-day/segment tests**

Same contract segment may confirm pivot across trading-day transition. Bars outside supplied segment or unsorted bars raise `N_STRUCTURE_SERIES_INVALID`.

- [ ] **Step 5: RED prefix invariance**

```python
for k in range(2, len(bars) + 1):
    p = reduce_n_swings(bars[:k], ...)
    full = reduce_n_swings(bars, ...)
    assert p.pivots == tuple(x for x in full.pivots if x.confirmed_at <= bars[k-1].bar_end)
    assert p.ambiguous_outside_reset_at == tuple(
        t for t in full.ambiguous_outside_reset_at if t <= bars[k-1].bar_end
    )
```

- [ ] **Step 6: Implement O(n) reducer and GREEN**

Only previous bar + current running state may drive a boundary; no right-hand lookahead/ATR/ZigZag/SuBing import.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_structure_swing.py
```

- [ ] **Step 7: Independent Review + PR develop**

Review previous-bar semantics, epoch barrier, tie/inside/outside and prefix invariance. Gate `Critical=0 / Important=0`.

---

# Task 3 — N Completion, Same-Boundary Breaks and Range Band

**Lane:** Lane 3 / Sol / 高.

**Files:**
- Create `services/quant-api/app/market_data/n_structure_pattern.py`
- Create `services/quant-api/tests/test_n_structure_pattern.py`

**Consumes:** `NSwingTrace`, `NStructurePolicy`, segment bars.

**Produces:**

```python
class NDirection(StrEnum): UP="up"; DOWN="down"
class NBreakKind(StrEnum):
    N2_ORIGIN_BROKEN="n2_origin_broken"
    ORIGIN_BROKEN="origin_broken"

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
class NPatternTrace:
    patterns: tuple[CompletedNPattern, ...]
    break_events: tuple[NBreakEvent, ...]
    range_band_reentries: tuple[NRangeBandReentryEvent, ...]
    incomplete_attempt_replaced_count: int

def evaluate_n_patterns(bars, swings, *, policy) -> NPatternTrace: ...
```

- [ ] **Step 1: RED same-epoch base matrix**

```python
assert up_base(LOW(10), HIGH(12), LOW(10)) is valid
assert up_base(LOW(10), HIGH(12), LOW(9)) is invalid
assert down_base(HIGH(12), LOW(10), HIGH(12)) is valid
assert down_base(HIGH(12), LOW(10), HIGH(13)) is invalid
```

Add a reset between pivot confirmations and assert no N can use pivots from two epochs.

- [ ] **Step 2: RED completion/equality/outside tests**

UP completes at first non-outside `high > n1`; DOWN at `low < n1`. Equal does not complete. Boundary listed in `ambiguous_outside_reset_at` cannot complete a new N.

- [ ] **Step 3: RED overshoot formula**

For UP `n1=100,current.high=101` assert `100 bps`; for DOWN `n1=100,current.low=99` assert `100 bps`, using Decimal exactly.

- [ ] **Step 4: RED same-boundary completion + break**

Construct a non-outside bar that completes UP and also has `low < n2_origin`; assert:

```text
one CompletedNPattern at current.bar_end
one N2_ORIGIN_BROKEN at same bar_end
```

If also `low < origin`, assert ordered events `[N2_ORIGIN_BROKEN, ORIGIN_BROKEN]`. Test must not contain any `intrabar_order` field/claim.

- [ ] **Step 5: RED post-completion immutable event tests**

Equal to N2/origin does not break. Each N/kind emits once. Future highs/lows never rewrite N identity/completion.

- [ ] **Step 6: RED Range Band**

```text
band=[min(n1,n2), max(n1,n2)]
UP role=support_reference
DOWN role=resistance_reference
```

First re-entry only on `bar_end > completed_at`:

```text
UP: low <= band.upper
DOWN: high >= band.lower
```

Completion bar itself never counts. Re-entry may coexist with later N break. Assert no STRONG/MEDIUM/WEAK field.

- [ ] **Step 7: RED incomplete replacement/outside reset**

New legal same-epoch base replaces old incomplete attempt and increments diagnostic count. Outside reset discards active incomplete attempt and prevents cross-epoch continuation.

- [ ] **Step 8: Implement + prefix GREEN**

For every test fixture, compare full-trace subsets against every prefix. Keep active completed N assessments indexed so evaluation is not full-history rescanning per bar.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py
```

- [ ] **Step 9: Independent Review + PR develop**

Gate `Critical=0 / Important=0`.

---

# Task 4 — BULL / BEAR / RANGE Structure and Trailing Defense

**Lane:** Lane 3 / Sol / 高.

**Files:**
- Create `services/quant-api/app/market_data/n_structure_state.py`
- Create `services/quant-api/tests/test_n_structure_state.py`

**Produces:**

```python
class NStructureKind(StrEnum):
    UNDEFINED="undefined"; BULL="bull"; BEAR="bear"; RANGE="range"

@dataclass(frozen=True, slots=True)
class NStructureSnapshot:
    observed_at: datetime
    epoch: int
    kind: NStructureKind
    established_at: datetime | None
    trailing_defense: NSwingPivot | None
    completed_n_count_in_epoch: int

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

def evaluate_n_market_structure(bars, *, swings, patterns, policy) -> NStructureTrace: ...
```

- [ ] **Step 1: RED minimum evidence**

Less than 2 completed N in current evidence epoch stays `UNDEFINED` unless an earlier directional structure is already active.

- [ ] **Step 2: RED classification matrix**

With >=2 completed N in same epoch and comparable pivots:

```text
H2>H1 & L2>L1 → BULL
H2<H1 & L2<L1 → BEAR
otherwise      → RANGE
```

Equality is non-directional.

- [ ] **Step 3: RED defense progression**

BULL defense only advances to a new confirmed LOW after a same-epoch qualifying HH+HL pair exists. BEAR symmetric. A lone low/high cannot advance defense.

- [ ] **Step 4: RED strict defense break**

```text
BULL + low < defense → BULL_STRUCTURE_BROKEN → RANGE
BEAR + high > defense → BEAR_STRUCTURE_BROKEN → RANGE
```

Equal no break; break bar no auto opposite direction.

- [ ] **Step 5: RED outside behavior**

Outside bar first checks existing defense level. If it breaks, record structure break. If it does not, active BULL/BEAR remains; epoch increments from Swing; post-reset pivots cannot pair with pre-reset pivots for new defense advancement/establishment. Opposite-looking post-reset pivots do not auto reverse an unbroken structure.

- [ ] **Step 6: RED RANGE establishment after reset**

RANGE can establish BULL/BEAR only after current epoch independently has >=2 completed N plus strict matching high/low progression.

- [ ] **Step 7: Implement exact boundary order**

```text
existing N level breaks
→ existing Structure defense break
→ Swing step / possible epoch reset
→ new Pivot
→ N base/replacement
→ new N completion
→ same-boundary new-N break facts
→ Range Band (only later boundaries)
→ same-epoch Structure establish/advance
→ append snapshots/transitions
```

- [ ] **Step 8: Prefix GREEN + independent Review**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_pattern.py \
  services/quant-api/tests/test_n_structure_state.py
```

Gate `Critical=0 / Important=0`; PR develop.

---

# Task 5 — Shared Actual-Dominant Research Segment Loader

**Lane:** Lane 2 / Sol / 高.

**Files:**
- Create `services/quant-api/app/market_data/actual_dominant_research.py`
- Create `services/quant-api/tests/data_foundation/test_actual_dominant_research.py`
- Modify `subing_lifecycle_research_service.py` and its tests

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class ActualDominantResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesResult]
    segments: tuple[ResolvedContractSegment, ...]

class ActualDominantResearchSegmentLoader:
    def __init__(self, market_data: _ActualDominantResearchReader) -> None: ...
    def load(self, *, symbol, frequencies, since, through) -> ActualDominantResearchSeries: ...
```

- [ ] **Step 1: Characterize existing SuBing source behavior**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 2: RED extracted loader tests**

Test exact current algorithm:

```text
probe via query_actual_dominant_trading_days(since..through)
restore containing true segment via dominant_segment_for_day
full query from first true segment start..through
validate no overlap/gap
multiple frequencies must have identical segment identities
```

Loader must not import Catalog/store/RQData/Redis.

- [ ] **Step 3: Implement by extraction, not redesign**

Move existing `_query_product/_restore_true_segments/_validate_segment_coverage` responsibilities into shared helper. Keep `SubingLifecycleResearchService` external constructor compatible and internally delegate to helper.

- [ ] **Step 4: SuBing zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 5: Commit/integrate develop**

```bash
git commit -m 'refactor(research): share actual-dominant segment loading'
```

---

# Task 6 — Price-Only Outcomes + N Historical Research + `n-structure` CLI

**Lane:** Lane 1 / Sol / 高.

**Files:**
- Create `price_outcome.py`, `n_structure_research_service.py` and tests
- Modify `subing_calibration.py` only for price arithmetic delegation
- Modify composition/research parser/commands/main and CLI tests

**Price interfaces:**

```python
class PriceDirection(StrEnum): LONG="long"; SHORT="short"
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

def build_price_outcomes_at(
    bars, *, index, direction, horizons=(3,5,8), same_trading_day_only: bool
) -> Mapping[int, PriceDirectionalOutcome | None]: ...
```

**N research interfaces:**

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
    completed_n_counts: Mapping[str,int]
    n_break_counts: Mapping[str,int]
    range_band_reentry_count: int
    structure_established_counts: Mapping[str,int]
    structure_break_counts: Mapping[str,int]
    horizon_summary: Mapping[int,PriceHorizonEvaluation]
```

- [ ] **Step 1: RED exact LONG/SHORT Decimal formula tests**

Use `entry=100`; verify LONG future final 102 produces +200 bps and SHORT final 98 produces +200 bps; assert MFE/MAE from high/low exactly per Spec §16.

- [ ] **Step 2: RED time boundary**

`same_trading_day_only=True` returns None if horizon crosses trading day; `False` permits it. Caller-provided bars are one rank1 segment only, so N cannot cross segment.

- [ ] **Step 3: Preserve SuBing**

Keep all old factor alignment/availability/contract/same-day gates before shared price arithmetic. Existing SuBing EMA21 labels remain SuBing-specific.

- [ ] **Step 4: RED N research aggregation**

Fake shared loader proves reducer starts at true segment start, but metrics only count requested trading days. Completion outcome entry uses `completion_bar_close`; N horizon uses `same_trading_day_only=False`; insufficient bars before `through`/segment end → None.

- [ ] **Step 5: Implement read-only CLI**

```text
guiyi research n-structure --since YYYY-MM-DD --through YYYY-MM-DD [--symbol jm]
```

Required top-level JSON:

```text
schema_version=1
command=research.n-structure
status=ok
readonly=true
policy_id=n_structure_5m_v1
formula_version=n_structure_v1
research_only=true
since/through/products
N source metrics
3/5/8 price-only horizon_summary
```

No EMA21 key in N payload.

- [ ] **Step 6: Focused + SuBing GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_price_outcome.py \
  services/quant-api/tests/data_foundation/test_n_structure_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
```

- [ ] **Step 7: Commit/integrate develop**

`feat(research): add N structure historical research`.

---

# Task 7 — Shared Candidate Validation Schedule

**Lane:** Lane 2 / Sol / 高.

**Files:**
- Create `candidate_validation_schedule.py` + test
- Modify `subing_candidate_validation_service.py` + existing tests

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

@dataclass(frozen=True, slots=True)
class RollingValidationWindow:
    fold_id: str
    reference_since: date
    reference_through: date
    test_since: date
    test_through: date

def build_rolling_validation_windows(...month args...) -> tuple[RollingValidationWindow,...]: ...
def prospective_window(*, through, first_trading_day) -> tuple[date,date] | None: ...
```

Stable existing errors move here unchanged.

- [ ] **Step 1: Characterize existing SuBing Candidate payload/tests**
- [ ] **Step 2: RED request + 12/3/3 fold + prospective helper tests**
- [ ] **Step 3: Extract only request/errors/date math; no source-specific report abstraction**
- [ ] **Step 4: Replace SuBing service date math with shared helper**
- [ ] **Step 5: Run zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 6: Commit/integrate develop**

No Strategy interface, Registry or DB table.

---

# Task 8 — N Candidate / Protocol / N-Specific Validation

**Lane:** Lane 1 / Sol / 高.

**Files:**
- Create exact Candidate/Protocol JSON
- Create `n_candidate_validation_policy.py`, `n_candidate_validation.py`, `n_candidate_validation_service.py`
- Create tests
- Modify composition and research CLI routing/tests

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

**Exact Protocol:** copy Spec §19 verbatim, including:

```text
candidate_frozen_at=2026-08-20T00:22:00+08:00
retrospective through=2026-08-19
embargo_trading_days=[2026-08-20]
prospective first=2026-08-21
12/3/3; 10 folds; horizons 3/5/8
```

**N report:** source-specific `NCandidateWindowResult`, `NStructureCandidateValidationReport`; stability = fold_count/folds_with_completed_n/min/max/median.

- [ ] **Step 1: RED strict candidate/protocol loader tests**

Reject prospective 2026-08-20, missing embargo, freeze drift, wrong policy/formula, extra keys.

- [ ] **Step 2: RED projection/stability tests**

Copy N research metrics without recalculation. No SuBing confirmation/V1-overlap/EMA21 fields.

- [ ] **Step 3: RED source window calls**

```text
retrospective: 2023-01-01..2026-08-19
rolling: exact 10 frozen folds
through=2026-08-19/20: pending, no prospective source call
through>=2026-08-21: prospective since 2026-08-21
```

Assert no evidence source window includes 2026-08-20.

- [ ] **Step 4: Extend CLI without plugin registry**

`candidate-validation` accepts exactly two candidate IDs. Main dispatch selects service by candidate ID. Invalid candidate/protocol cross-pair fails inside exact service.

`run_research_command()` serializes existing SuBing report with the unchanged existing payload function and N report with a new N-specific payload function.

- [ ] **Step 5: RED forbidden fields**

N Candidate JSON must not contain `keep/drop/promote/pass_strategy/profitability/expected_profit/account_return`.

- [ ] **Step 6: Focused + SuBing Candidate GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  pytest -q services/quant-api/tests/test_n_candidate_validation_policy.py \
  services/quant-api/tests/test_n_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_n_candidate_validation_service.py \
  services/quant-api/tests/test_candidate_validation_schedule.py \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 7: Commit/integrate develop**

`feat(research): validate N structure candidate`.

---

# Task 9 — Full Verification, Canonical Docs and Independent Implementation Review

**Lane:** Lane 3 Review / Sol / 高.

- [ ] **Step 1: Complete N suite**

Run all new Policy/Swing/Pattern/Structure/segment loader/price outcome/N research/schedule/N Candidate/CLI tests.

- [ ] **Step 2: Upstream SuBing regression**

Run lifecycle policy/structure/lifecycle/calibration/research/read-service/Candidate focused suites and `test_research_cli.py`.

- [ ] **Step 3: Mandatory prefix fixture matrix**

Must cover:

```text
straight trend
inside bars
equal highs/lows
tied extrema
outside reset before completion
outside reset prevents cross-epoch N
outside after completed N causing N break
outside causing Structure defense break
outside not breaking defense then new epoch evidence
trading-day transition within same segment
rank1 segment reset
same-boundary N2 confirmation + completion
same-boundary completion + N2/origin break
N2 break without origin break
BULL/RANGE/BEAR transitions
```

Every immutable full-trace subset must equal corresponding prefix facts.

- [ ] **Step 4: Static/security**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app/market_data services/quant-api/app/guiyi_cli
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: Update `TESTING.md` and `docs/ARCHITECTURE.md`**

Document N as Historical/research-only and architecture as MDS → shared loader → independent SuBing/N domains → source-specific candidate reports.

- [ ] **Step 6: Independent Review**

Gate checklist: source vs engineering labels; 5m only; epoch barrier; outside path rules; same-boundary completion/break; no strong/medium/weak thresholds; structure >=2 N; defense no auto reverse; segment-local; prefix invariance; N cross-day/no cross-segment outcomes; SuBing parity; MDS-only; 2026-08-20 embargo; no Web/Alert/Runtime/DB/order/promotion.

Require `Critical=0 / Important=0`.

- [ ] **Step 7: Update STATUS only after clean Review**

Record implementation exists in develop, second candidate producer exists, prospective starts 2026-08-21, evidence not yet generated, and no effectiveness/release/runtime claim.

---

# Task 10 — Exact-Develop Real `jm` Evidence

**Lane:** Lane 1 / Sol / 高 + independent Evidence Review.

**Output:**

```text
reports/research/candidate_validation/
  n_structure_5m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-20.json
```

- [ ] **Step 1: New evidence worktree from exact reviewed develop**

```bash
git fetch origin develop
git worktree add ../guiyi-n-jm-evidence -b research/n-structure-jm-evidence origin/develop
cd ../guiyi-n-jm-evidence
git rev-parse HEAD
```

- [ ] **Step 2: Real read-only N preflight**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  guiyi research n-structure --since 2023-01-01 --through 2026-08-19 --symbol jm \
  > /tmp/n-structure-jm-preflight.json
```

Validate exact policy/formula, readonly, product jm, source metrics and horizon `3/5/8`; do not commit preflight.

- [ ] **Step 3: Generate Candidate baseline**

```bash
mkdir -p reports/research/candidate_validation/n_structure_5m_candidate_v1
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api \
  guiyi research candidate-validation \
  --candidate n_structure_5m_candidate_v1 \
  --protocol n_structure_validation_v1 \
  --symbol jm --through 2026-08-20 \
  > reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json
```

- [ ] **Step 4: Validate exact temporal contract**

```python
assert p["readonly"] is True
assert p["candidate_id"] == "n_structure_5m_candidate_v1"
assert p["retrospective"]["through"] == "2026-08-19"
assert len(p["rolling_folds"]) == 10
assert p["prospective_oos"]["status"] == "pending"
assert p["prospective_oos"]["first_trading_day"] == "2026-08-21"
```

2026-08-20 may appear only as freeze/embargo/request-through context, never an evidence window.

- [ ] **Step 5: Deterministic recompute**

Run exact command again to `/tmp/n-candidate-repeat.json`; byte-compare or canonical-JSON compare. Mismatch blocks acceptance.

- [ ] **Step 6: Commit generated artifact unedited**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json
git commit -m 'research(n-structure): add jm candidate baseline'
```

- [ ] **Step 7: Independent Evidence Review**

Review identity, source metric completeness, 10 folds, 3/5/8 outcomes, embargo/pending state, deterministic recompute and forbidden claims. Gate `Critical=0 / Important=0`.

- [ ] **Step 8: STATUS + develop integration**

Only after accepted evidence, record exact artifact and non-conclusion; integrate to develop, read back ancestry, cleanup. Do not touch main/tag/Runtime.

---

## Final Acceptance

```text
[ ] exact policy strict-loaded
[ ] sequential Swing causal + epoch barrier + prefix invariance
[ ] N never crosses outside epoch
[ ] first strict N1 completion + same-boundary break facts exact
[ ] completed N immutable
[ ] raw Range Band only; no strong/medium/weak classifier
[ ] BULL/BEAR/RANGE >=2 N; defense strict; no auto reversal
[ ] rank1 segment-local
[ ] shared segment loader preserves SuBing
[ ] N price outcomes cross day only within same segment
[ ] SuBing same-day/EMA21 unchanged
[ ] shared candidate schedule preserves SuBing Candidate output
[ ] exact N Candidate/Protocol with 2026-08-20 embargo
[ ] prospective starts 2026-08-21
[ ] full verification + Review Critical=0 / Important=0
[ ] real jm retrospective/rolling evidence deterministic
[ ] Evidence Review Critical=0 / Important=0
[ ] no main/tag/Runtime/Alert/Scope/notification/DB/Canonical/order action
```

Completion authorizes only continued research/prospective OOS accumulation. It does not authorize Candidate promotion or a third production Alert Rule.
