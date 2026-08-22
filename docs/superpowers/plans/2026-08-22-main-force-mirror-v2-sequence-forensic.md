# Main Force Mirror V2 60m Sequence Forensic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 active `main_force_mirror_v2` Kernel/Web/API/Alert 语义的前提下，复用现有 V2 Research/CLI 增加 60m-only causal sequence forensic facts、5 个固定敏感性 profile 和 opt-in `--forensic` dossier，为是否值得冻结正式 Phase 规则提供只读 retrospective 证据。

**Architecture:** 新计算只位于现有 `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`。它消费已有 `MainForceMirrorV2Point`，按 physical-contract block 做 strict-prior sequence derivation，再复用当前 `_Observation → _outcome → _summary` 评价链；CLI 只增加 `--forensic`，不建新 service、endpoint、repository、protocol、cache 或持久化 evidence。

**Tech Stack:** Python 3.13、dataclasses、Decimal、现有 MarketDataService / MainForceMirrorV2Service / research CLI、pytest、ruff、mypy。

**Spec:** `docs/superpowers/specs/2026-08-22-main-force-mirror-v2-sequence-forensic-design.md`

## Global Constraints

- `frequency = 60m only`；禁止读取、投影或辅助使用 15m/5m/1m。
- Historical confirmed only；不接 Redis Live。
- 不修改 `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`。
- 不修改 `MainForceMirrorV2Service` 的 Web/API point 合同。
- 不修改 caution、member daily observation、MarketDataService、MainContractMap、Canonical、DB。
- 不新增 package/service/repository/endpoint/protocol/cache/checkpoint。
- 不调用 RQData、不执行 member snapshot `--apply`、不写 research-data-root。
- 不输出正式 `CLIMAX / UNWIND / TAKEOVER` Phase，不输出 best profile/winner/PnL/Sharpe。
- sequence facts 必须 same physical-contract、strict-prior、prefix invariant，并且同一 peak 的每种后续事件只记录首次 occurrence。
- peak candidate 第一轮只允许 `long_build` / `short_build`，不让 liquidation/cover Bar 抢占旧 peak memory。
- `auto_order=false` 不变。
- 实现从当前 `develop` 创建独立 task branch/worktree；不得修改 main/runtime worktree。
- 完成后只允许 task → `develop`；不得 release main/tag、Runtime promotion 或真实写入。

## Execution Alignment

- 原始代码基线为 `e8b6152665d3ff27c470ecc6c56840c7da254897`，原计划起点为 `91baeecb028a537b79e69d6726e274c015ddbe79`，实际执行起点为 `fef886ac77b97136a0d222f5751ee63289ef2991`。
- SequenceFact 使用双事实模型：`active_peak_*` 属于进入当前 Bar 时的旧 peak，`installed_peak_*` 属于当前 Bar 评价完旧 peak 后新安装的 build peak。
- 同一 Bar 同时是旧 peak 事件和新 peak candidate 时，同时保留旧方向 event cohort 与新方向 `peak_only` cohort。本节覆盖本文中任何旧的单 `side/peak_index` 表达。
- Task 2 的 evidence-Bar 测试必须断言手算 outcome 值，不得只断言 sample count。
- Task 5 使用 fail-closed 评审，不新造数值门槛；临时目录只能在验证路径和内容边界后清理。

---

## File Map

**Modify only:**

- `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_requests.py`
- `services/quant-api/app/guiyi_cli/research_payloads.py`
- `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`
- `services/quant-api/tests/test_research_cli.py`
- `TESTING.md`
- `docs/superpowers/specs/2026-08-22-main-force-mirror-v2-sequence-forensic-design.md`
- `docs/superpowers/plans/2026-08-22-main-force-mirror-v2-sequence-forensic.md`
- `docs/tasks/TASK-MFM-V2-SEQUENCE-FORENSIC-20260822.md`

**Must remain untouched:**

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`
- `services/quant-api/app/market_data/main_force_mirror_v2_service.py`
- `services/quant-api/app/market_data/member_rank_snapshot.py`
- `services/quant-api/app/market_data/member_rank_snapshot_builder.py`
- `apps/quant-web/**`
- migrations / Alert / Execution Review / Runtime
- `STATUS.md` / `PROJECT_SOURCE.md` / `DECISIONS.md`

---

### Task 1: Add pure 60m sequence profiles and prefix-invariant derivation

**Files:**
- Modify: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`

**Interfaces:**
- Consumes: existing `tuple[MainForceMirrorV2Point, ...]`.
- Produces:
  - `MainForceMirrorV2SequenceProfile`
  - `SEQUENCE_PROFILES`
  - `MainForceMirrorV2SequenceFact`
  - `_derive_sequence_facts(points, profile) -> tuple[MainForceMirrorV2SequenceFact, ...]`
- These are research-only symbols; no active consumer may import them.

- [ ] **Step 1: Add exact synthetic sequence fixtures to the existing research-service test file**

Add these helpers. They deliberately use one synthetic 60m point per trading day only to keep fake MarketData identity simple; they do not test session aggregation.

```python
def _sequence_point(
    index: int,
    *,
    state: str,
    instant: float,
    accumulated: float,
    contract: str = "JM2609",
) -> MainForceMirrorV2Point:
    moment = datetime(2026, 2, 1, 7, tzinfo=UTC) + timedelta(days=index)
    return replace(
        _POINTS[0],
        bar_end=moment,
        trading_day=moment.date(),
        physical_contract=contract,
        pressure_ready=True,
        pressure_state=state,  # type: ignore[arg-type]
        instant_pressure=instant,
        accumulated_ready=True,
        accumulated_pressure=accumulated,
        caution=None,
        caution_conflict=False,
        long_caution_score=0.0,
        short_caution_score=0.0,
        caution_reason_codes=(),
        unavailable_reason=None,
    )


def _long_sequence_points() -> tuple[MainForceMirrorV2Point, ...]:
    prior = tuple(
        _sequence_point(
            index,
            state="long_build",
            instant=10.0 + index,
            accumulated=8.0 + index,
        )
        for index in range(21)
    )
    return (
        *prior,
        _sequence_point(21, state="long_build", instant=100.0, accumulated=80.0),
        _sequence_point(
            22,
            state="long_liquidation",
            instant=-60.0,
            accumulated=30.0,
        ),
        _sequence_point(23, state="short_build", instant=-70.0, accumulated=-10.0),
    )


def _short_sequence_points() -> tuple[MainForceMirrorV2Point, ...]:
    mirror_state = {
        "long_build": "short_build",
        "long_liquidation": "short_cover",
        "short_build": "long_build",
    }
    return tuple(
        replace(
            point,
            pressure_state=mirror_state[str(point.pressure_state)],  # type: ignore[arg-type]
            instant_pressure=-float(point.instant_pressure or 0.0),
            accumulated_pressure=-float(point.accumulated_pressure or 0.0),
        )
        for point in _long_sequence_points()
    )
```

- [ ] **Step 2: Write failing profile-contract test**

```python
def test_sequence_profiles_are_exact_small_global_set() -> None:
    assert [
        (
            profile.profile_id,
            profile.peak_window,
            profile.peak_quantile,
            profile.decay_threshold,
            profile.transition_window,
        )
        for profile in SEQUENCE_PROFILES
    ] == [
        ("balanced", 10, Decimal("0.90"), Decimal("0.40"), 2),
        ("fast", 5, Decimal("0.90"), Decimal("0.40"), 1),
        ("slow", 20, Decimal("0.90"), Decimal("0.40"), 3),
        ("loose", 10, Decimal("0.85"), Decimal("0.25"), 2),
        ("strict", 10, Decimal("0.95"), Decimal("0.55"), 2),
    ]
```

- [ ] **Step 3: Write failing causal long/short tests**

```python
def test_sequence_long_peak_emits_later_events_on_evidence_bars() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    facts = _derive_sequence_facts(_long_sequence_points(), profile)

    assert facts[21].installed_peak_side == "long"
    assert facts[21].peak_seen is True
    assert facts[21].decay_seen is False
    assert facts[21].liquidation_seen is False
    assert facts[22].active_peak_index == 21
    assert facts[22].decay_seen is True
    assert facts[22].liquidation_seen is True
    assert facts[23].active_peak_index == 21
    assert facts[23].opposite_build_seen is True
    assert facts[23].accumulated_reversal_seen is True
    assert facts[23].installed_peak_index == 23
    assert facts[23].installed_peak_side == "short"
    assert facts[23].peak_seen is True


def test_sequence_short_side_is_exact_sign_state_mirror() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    facts = _derive_sequence_facts(_short_sequence_points(), profile)

    assert facts[21].installed_peak_side == "short"
    assert facts[21].peak_seen is True
    assert facts[22].decay_seen is True
    assert facts[22].liquidation_seen is True
    assert facts[23].opposite_build_seen is True
    assert facts[23].accumulated_reversal_seen is True
```

- [ ] **Step 4: Write failing first-occurrence and roll-reset tests**

```python
def test_sequence_event_types_emit_only_first_occurrence_for_one_peak() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "slow")
    points = (
        *_long_sequence_points()[:23],
        _sequence_point(23, state="short_build", instant=-1.0, accumulated=-10.0),
        _sequence_point(24, state="short_build", instant=-1.0, accumulated=-20.0),
    )
    facts = _derive_sequence_facts(points, profile)

    assert facts[22].decay_seen is True
    assert facts[23].opposite_build_seen is True
    assert facts[24].decay_seen is False
    assert facts[24].opposite_build_seen is False
    assert facts[24].accumulated_reversal_seen is False


def test_sequence_memory_resets_at_physical_contract_change() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    points = tuple(
        replace(point, physical_contract="JM2701") if index >= 22 else point
        for index, point in enumerate(_long_sequence_points())
    )
    facts = _derive_sequence_facts(points, profile)

    assert facts[21].peak_seen is True
    assert facts[22].active_peak_index is None
    assert facts[22].decay_seen is False
    assert facts[22].liquidation_seen is False
    assert facts[23].opposite_build_seen is False


def test_sequence_requires_full_strict_prior_window() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    points = tuple(
        _sequence_point(index, state="long_build", instant=100.0, accumulated=80.0)
        for index in range(11)
    )
    facts = _derive_sequence_facts(points, profile)

    assert all(not fact.peak_seen for fact in facts[:10])
    assert facts[10].installed_peak_index == 10


def test_sequence_resets_on_non_monotonic_time() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    points = list(_long_sequence_points())
    points[22] = replace(points[22], bar_end=points[21].bar_end)
    facts = _derive_sequence_facts(tuple(points), profile)

    assert facts[22].active_peak_index is None
    assert facts[22].liquidation_seen is False


def test_sequence_accumulated_unavailable_keeps_state_events_only() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "balanced")
    points = list(_long_sequence_points())
    points[22] = replace(
        points[22], accumulated_ready=False, accumulated_pressure=None
    )
    facts = _derive_sequence_facts(tuple(points), profile)

    assert facts[22].active_peak_index == 21
    assert facts[22].liquidation_seen is True
    assert facts[22].decay_seen is False
    assert facts[22].accumulated_reversal_seen is False
```

- [ ] **Step 5: Write failing prefix-invariance test for all five profiles**

```python
@pytest.mark.parametrize("profile", SEQUENCE_PROFILES)
def test_sequence_derivation_is_prefix_invariant(
    profile: MainForceMirrorV2SequenceProfile,
) -> None:
    points = _long_sequence_points()
    full = _derive_sequence_facts(points, profile)

    for end in range(1, len(points) + 1):
        assert _derive_sequence_facts(points[:end], profile)[-1] == full[end - 1]
```

- [ ] **Step 6: Run new tests and confirm they fail before implementation**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k "sequence or prefix"
```

Expected: FAIL because the new profile/fact/helper symbols do not exist.

- [ ] **Step 7: Add exact profile/fact types in the existing research service**

Extend `decimal` import with `ROUND_CEILING`; add:

```python
SequenceSide = Literal["long", "short", "neutral"]
SequenceProfileId = Literal["balanced", "fast", "slow", "loose", "strict"]


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceProfile:
    profile_id: SequenceProfileId
    peak_window: int
    peak_quantile: Decimal
    decay_threshold: Decimal
    transition_window: int


SEQUENCE_PROFILES = (
    MainForceMirrorV2SequenceProfile("balanced", 10, Decimal("0.90"), Decimal("0.40"), 2),
    MainForceMirrorV2SequenceProfile("fast", 5, Decimal("0.90"), Decimal("0.40"), 1),
    MainForceMirrorV2SequenceProfile("slow", 20, Decimal("0.90"), Decimal("0.40"), 3),
    MainForceMirrorV2SequenceProfile("loose", 10, Decimal("0.85"), Decimal("0.25"), 2),
    MainForceMirrorV2SequenceProfile("strict", 10, Decimal("0.95"), Decimal("0.55"), 2),
)


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceFact:
    index: int
    current_side: SequenceSide
    pressure_state: str | None
    instant_pressure: float | None
    accumulated_pressure: float | None
    active_peak_index: int | None
    active_peak_side: Literal["long", "short"] | None
    active_peak_instant_pressure: float | None
    active_peak_accumulated_pressure: float | None
    bars_since_active_peak: int | None
    decay_ratio: Decimal | None
    installed_peak_index: int | None
    installed_peak_side: Literal["long", "short"] | None
    installed_peak_instant_pressure: float | None
    installed_peak_accumulated_pressure: float | None
    peak_seen: bool
    decay_seen: bool
    liquidation_seen: bool
    opposite_build_seen: bool
    accumulated_reversal_seen: bool
    state_transition: str | None
```

Add one private mutable scan-state dataclass in the same file only:

```python
@dataclass(slots=True)
class _ActiveSequencePeak:
    index: int
    side: Literal["long", "short"]
    pressure: float
    accumulated: Decimal | None
    decay_emitted: bool = False
    liquidation_emitted: bool = False
    opposite_build_emitted: bool = False
    reversal_emitted: bool = False
```

- [ ] **Step 8: Implement nearest-rank strict-prior build-peak threshold**

```python
def _nearest_rank(values: tuple[Decimal, ...], quantile: Decimal) -> Decimal:
    if not values:
        raise ValueError("sequence percentile requires values")
    if quantile <= 0 or quantile > 1:
        raise ValueError("sequence percentile must be in (0, 1]")
    ordered = sorted(values)
    rank = int(
        (quantile * Decimal(len(ordered))).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return ordered[max(1, rank) - 1]
```

A current point is a peak candidate only when all are true:

```text
pressure_ready
instant_pressure is finite and non-zero
pressure_state in {long_build, short_build}
there are exactly profile.peak_window prior ready points in the same block
abs(current instant pressure) >= nearest-rank(abs(prior instant pressure), q)
```

The current point is never in its own baseline. `short_cover` / `long_liquidation` can be later sequence evidence but never install a new peak in this first-round design.

- [ ] **Step 9: Implement `_derive_sequence_facts` as one forward scan**

Use this fixed order for each current point:

```text
A. reset on missing/changed contract, pressure_ready=false, missing/non-finite instant pressure, or non-increasing bar_end
B. derive immediate previous_state -> current_state transition inside the block
C. if an older active peak exists and age <= transition_window, evaluate decay/liquidation/opposite/reversal
D. event booleans are true only for the first occurrence of each type
E. if active peak age > transition_window, expire it
F. after C–E, evaluate whether current point is a new long_build/short_build peak candidate and install it for subsequent bars
G. append immutable MainForceMirrorV2SequenceFact with both active_peak_* and installed_peak_* contexts
```

Side/state mapping is exact:

```python
liquidation_state = {"long": "long_liquidation", "short": "short_cover"}
opposite_build_state = {"long": "short_build", "short": "long_build"}
```

Long decay uses `(peak - current) / abs(peak)`; short decay uses `(abs(peak) - abs(current)) / abs(peak)`. Convert exposed accumulated floats with `Decimal(str(value))`. If current accumulated crosses the peak side’s zero boundary, `accumulated_reversal_seen` emits once. Do not clip `decay_ratio`.

If current `short_build`/`long_build` point is both an event for the old peak and a candidate for the opposite new peak, its fact reports the old peak through `active_peak_*` and the new peak through `installed_peak_*`. Task 2 must emit both observations from this Bar.

- [ ] **Step 10: Run sequence tests, then the whole research-service test file**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
```

Expected: all tests PASS.

- [ ] **Step 11: Commit Task 1**

```bash
git add \
  services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
git commit -m "research: add causal 60m main force sequence facts"
```

---

### Task 2: Reuse existing outcome machinery for sequence profile summaries

**Files:**
- Modify: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`

**Interfaces:**
- Consumes: Task 1 profiles/facts plus existing `_Observation`, `_outcome`, `_summary`, `HORIZONS`.
- Produces:
  - `SEQUENCE_COHORTS`
  - `MainForceMirrorV2SequenceProfileSummary`
  - `MainForceMirrorV2ResearchResult.sequence_profiles`
- Existing `pooled/yearly/by_product/top_bottom_spreads/sensitivity` remain unchanged.

- [ ] **Step 1: Add exact synthetic market/service fixture**

Append to the same test file:

```python
def _sequence_bar(point: MainForceMirrorV2Point, index: int) -> CanonicalBar:
    close = Decimal(100 if index <= 21 else 100 - 5 * (index - 21))
    return CanonicalBar(
        bar_end=point.bar_end,
        trading_day=point.trading_day,
        open=close,
        high=close + Decimal(1),
        low=close - Decimal(1),
        close=close,
        volume=Decimal(100),
        turnover=None,
        open_interest=Decimal(1000),
    )


def _sequence_research_result(*, roll_before_event: bool = False):
    points = _long_sequence_points()
    if roll_before_event:
        points = tuple(
            replace(point, physical_contract="JM2701") if index >= 22 else point
            for index, point in enumerate(points)
        )
    bars = tuple(_sequence_bar(point, index) for index, point in enumerate(points))
    if roll_before_event:
        segments = (
            ResolvedContractSegment(
                "JM2609", points[0].trading_day, points[21].trading_day
            ),
            ResolvedContractSegment(
                "JM2701", points[22].trading_day, points[-1].trading_day
            ),
        )
    else:
        segments = (
            ResolvedContractSegment(
                "JM2609", points[0].trading_day, points[-1].trading_day
            ),
        )
    request = MainForceMirrorV2ResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        contract=None,
        frequency=BarFrequency.H1,
        since=points[0].trading_day,
        through=points[-1].trading_day,
    )
    return MainForceMirrorV2ResearchService(
        market_data=_MarketData(bars=bars, segments=segments),
        mirror_service=_MirrorService(points=points, segments=segments),
    ).run(request)
```

- [ ] **Step 2: Write failing additive summary/timing tests**

```python
def test_research_adds_exact_five_sequence_profiles() -> None:
    result = _sequence_research_result()
    assert tuple(result.sequence_profiles) == (
        "balanced", "fast", "slow", "loose", "strict"
    )
    assert result.pooled["all_caution"][5].sample_count == 0


def test_sequence_warning_horizon_starts_from_causal_evidence_bar() -> None:
    result = _sequence_research_result()
    balanced = result.sequence_profiles["balanced"]

    assert balanced.yearly[2026]["jm"]["long"]["peak_then_liquidation"][1].sample_count == 1
    assert balanced.by_side["long"]["peak_then_liquidation"][1].sample_count == 1
    assert balanced.by_side["long"]["peak_then_liquidation"][1].median_reversal_return == Decimal("0.052632")
    assert balanced.by_side["short"]["peak_then_liquidation"][1].sample_count == 0
```

This fixture has peak index 21 and liquidation index 22; the horizon-1 target must therefore be index 23. Its hand-calculated rounded reversal return is `0.052632`, which differs from the `0.05` produced by an illegal backfill to the peak. Extend the fixture with at least ten same-contract follow-up Bars so horizons 1/3/5/10 are all exercised.

- [ ] **Step 3: Write failing cross-roll summary test**

```python
def test_sequence_summary_does_not_join_peak_and_event_across_roll() -> None:
    result = _sequence_research_result(roll_before_event=True)
    balanced = result.sequence_profiles["balanced"]

    assert balanced.by_side["long"]["peak_only"][1].sample_count == 0
    assert balanced.by_side["long"]["peak_then_liquidation"][1].sample_count == 0
    assert balanced.by_side["long"]["peak_then_opposite_build"][1].sample_count == 0
```

`peak_only` horizon-1 is also zero here because the next Bar crosses the physical contract.

- [ ] **Step 4: Run Task 2 tests and confirm failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k "sequence_profiles or sequence_warning or sequence_summary"
```

- [ ] **Step 5: Add exact summary interfaces**

```python
SEQUENCE_COHORTS = (
    "peak_only",
    "peak_then_decay",
    "peak_then_liquidation",
    "peak_then_opposite_build",
    "peak_then_accumulated_reversal",
)


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceProfileSummary:
    profile_id: SequenceProfileId
    yearly: YearlyMap
    by_side: Mapping[str, CohortMap]
    pooled: CohortMap
```

Add to `MainForceMirrorV2ResearchResult`:

```python
sequence_profiles: Mapping[str, MainForceMirrorV2SequenceProfileSummary]
```

Keep `research_protocol="main_force_mirror_v2_retrospective_v1"`; do not create a new protocol file.

- [ ] **Step 6: Project event facts into existing `_Observation`**

Add:

```python
def _sequence_observations(
    product: str,
    points: tuple[MainForceMirrorV2Point, ...],
    facts: tuple[MainForceMirrorV2SequenceFact, ...],
) -> tuple[_Observation, ...]:
    observations: list[_Observation] = []
    for fact in facts:
        if fact.peak_seen and fact.installed_peak_side is not None:
            observations.append(
                _Observation(
                    fact.index,
                    product,
                    points[fact.index].trading_day.year,
                    fact.installed_peak_side,
                    "peak_only",
                    1 if fact.installed_peak_side == "long" else -1,
                )
            )
        if fact.active_peak_side is None:
            continue
        direction = 1 if fact.active_peak_side == "long" else -1
        events = (
            (fact.decay_seen, "peak_then_decay"),
            (fact.liquidation_seen, "peak_then_liquidation"),
            (fact.opposite_build_seen, "peak_then_opposite_build"),
            (
                fact.accumulated_reversal_seen,
                "peak_then_accumulated_reversal",
            ),
        )
        for active, cohort in events:
            if active:
                observations.append(
                    _Observation(
                        fact.index,
                        product,
                        points[fact.index].trading_day.year,
                        fact.active_peak_side,
                        cohort,
                        direction,
                    )
                )
    return tuple(observations)
```

Extend warning classification:

```python
def _is_warning_cohort(cohort: str) -> bool:
    return (
        cohort == "all_caution"
        or cohort.startswith("caution_member_")
        or cohort in SEQUENCE_COHORTS
    )
```

- [ ] **Step 7: Parameterize only the cohort selector; reuse `_outcome` and `_summary` unchanged**

```python
def _summarize_selected_cohorts(
    observations: tuple[_Observation, ...],
    cohorts: tuple[str, ...],
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
) -> CohortMap:
    return MappingProxyType(
        {
            cohort: MappingProxyType(
                {
                    horizon: _summary(
                        tuple(item for item in observations if item.cohort == cohort),
                        horizon,
                        bars,
                        points,
                    )
                    for horizon in HORIZONS
                }
            )
            for cohort in cohorts
        }
    )
```

Make existing `_summarize_cohorts(...)` delegate to this helper with `COHORTS` so the old output stays identical.

Add `_yearly_selected(...)` with the same grouping logic as current `_yearly`, but call `_summarize_selected_cohorts(..., SEQUENCE_COHORTS, ...)`. Add `_sequence_by_side(...)` that always returns both `long` and `short` keys, each summarized over `SEQUENCE_COHORTS`.

- [ ] **Step 8: Populate five profile summaries in `run()`**

Derive each profile independently; for each:

```python
facts = _derive_sequence_facts(points, profile)
sequence_observations = _sequence_observations(request.symbol, points, facts)
summary = MainForceMirrorV2SequenceProfileSummary(
    profile_id=profile.profile_id,
    yearly=_yearly_selected(sequence_observations, bars, points),
    by_side=_sequence_by_side(sequence_observations, bars, points),
    pooled=_summarize_selected_cohorts(
        sequence_observations,
        SEQUENCE_COHORTS,
        bars,
        points,
    ),
)
```

Store in `MappingProxyType` in `SEQUENCE_PROFILES` order. There is no best-profile field.

- [ ] **Step 9: Run the entire research-service test file and commit Task 2**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py

git add \
  services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
git commit -m "research: summarize main force sequence profiles"
```

---

### Task 3: Add opt-in `--forensic` dossier through the existing CLI

**Files:**
- Modify: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `TESTING.md`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes: balanced facts and profile summaries from Tasks 1–2.
- Produces:
  - `MainForceMirrorV2ResearchRequest.forensic: bool = False`
  - `MainForceMirrorV2ForensicPoint`
  - `MainForceMirrorV2ResearchResult.forensic_points`
  - CLI `--forensic`
  - JSON `sequence_profiles` always; `forensic_points` only when requested.
- No new subcommand and no `research_commands.py` change.

- [ ] **Step 1: Extend existing CLI test helper with exact forensic flag**

Modify the existing `_mirror_arguments` helper:

```python
def _mirror_arguments(
    *,
    series_kind: str = "actual_dominant",
    contract: str | None = None,
    forensic: bool = False,
) -> list[str]:
    arguments = [
        "research",
        "main-force-mirror-v2",
        "--symbol",
        "jm",
        "--series-kind",
        series_kind,
        "--frequency",
        "60m",
        "--since",
        "2023-01-01",
        "--through",
        "2026-08-18",
    ]
    if contract is not None:
        arguments.extend(("--contract", contract))
    if forensic:
        arguments.append("--forensic")
    return arguments
```

- [ ] **Step 2: Add failing default/flag request tests**

```python
def test_mirror_forensic_flag_is_explicit_and_defaults_off() -> None:
    normal = _request(_mirror_arguments())
    forensic = _request(_mirror_arguments(forensic=True))

    assert normal.forensic is False
    assert forensic.forensic is True
```

Existing request equality tests should keep passing because the new dataclass field defaults to false.

- [ ] **Step 3: Add failing result/payload tests**

Update `_mirror_result()` to include five empty sequence profile summaries and `forensic_points=None`:

```python
empty_profiles = {
    profile_id: MainForceMirrorV2SequenceProfileSummary(
        profile_id=profile_id,  # type: ignore[arg-type]
        yearly={},
        by_side={"long": {}, "short": {}},
        pooled={},
    )
    for profile_id in ("balanced", "fast", "slow", "loose", "strict")
}
```

Then add:

```python
def test_mirror_default_payload_adds_profiles_without_forensic_points() -> None:
    request = _request(_mirror_arguments())
    payload = run_research_command(request, _FakeMirrorResearchService(_mirror_result()))

    assert tuple(payload["sequence_profiles"]) == (
        "balanced", "fast", "slow", "loose", "strict"
    )
    assert "forensic_points" not in payload
```

- [ ] **Step 4: Add exact forensic fixture and failing renderer test**

Import `MainForceMirrorV2Point`, `MainForceMirrorV2SequenceFact`, and `MainForceMirrorV2ForensicPoint`. Add:

```python
def _mirror_forensic_fixture() -> MainForceMirrorV2ForensicPoint:
    point = MainForceMirrorV2Point(
        bar_end=datetime(2026, 3, 23, 7, tzinfo=UTC),
        trading_day=date(2026, 3, 23),
        physical_contract="JM2609",
        pressure_ready=True,
        pressure_state="long_build",
        instant_pressure=95.0,
        accumulated_ready=True,
        accumulated_pressure=70.0,
        caution_ready=True,
        caution="long_chase_caution",
        caution_conflict=False,
        long_caution_score=70.0,
        short_caution_score=0.0,
        caution_reason_codes=("LONG_UPPER_EXTREME",),
        member=None,
        unavailable_reason=None,
        price_impulse=2.0,
        clv=0.8,
        volume_ratio=2.1,
        delta_oi=1000.0,
        oi_impulse=2.5,
        range_position=0.95,
    )
    fact = MainForceMirrorV2SequenceFact(
        index=0,
        current_side="long",
        pressure_state="long_build",
        instant_pressure=95.0,
        accumulated_pressure=70.0,
        active_peak_index=None,
        active_peak_side=None,
        active_peak_instant_pressure=None,
        active_peak_accumulated_pressure=None,
        bars_since_active_peak=None,
        decay_ratio=None,
        installed_peak_index=0,
        installed_peak_side="long",
        installed_peak_instant_pressure=95.0,
        installed_peak_accumulated_pressure=70.0,
        peak_seen=True,
        decay_seen=False,
        liquidation_seen=False,
        opposite_build_seen=False,
        accumulated_reversal_seen=False,
        state_transition=None,
    )
    return MainForceMirrorV2ForensicPoint(point=point, sequence=fact)


def test_mirror_forensic_payload_is_balanced_readonly_detail() -> None:
    request = _request(_mirror_arguments(forensic=True))
    result = replace(_mirror_result(), forensic_points=(_mirror_forensic_fixture(),))
    payload = run_research_command(request, _FakeMirrorResearchService(result))

    assert len(payload["forensic_points"]) == 1
    rendered = payload["forensic_points"][0]
    assert rendered["physical_contract"] == "JM2609"
    assert rendered["pressure_state"] == "long_build"
    assert rendered["sequence"]["profile_id"] == "balanced"
    assert rendered["sequence"]["peak_seen"] is True
    assert rendered["member_status"] == "unavailable"
```

- [ ] **Step 5: Run CLI tests and confirm failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  -k "mirror and (forensic or sequence_profiles)"
```

- [ ] **Step 6: Add `forensic` to the immutable request and parser**

At the end of `MainForceMirrorV2ResearchRequest` fields add:

```python
forensic: bool = False
```

In `__post_init__`:

```python
if type(self.forensic) is not bool:
    raise ValueError("forensic must be boolean")
```

In `research_parser.py`:

```python
mirror.add_argument("--forensic", action="store_true")
```

In `research_requests.py`:

```python
forensic=args.forensic,
```

The flag must not alter market query identity or V2 calculation.

- [ ] **Step 7: Add forensic result DTO and reuse balanced derivation**

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2ForensicPoint:
    point: MainForceMirrorV2Point
    sequence: MainForceMirrorV2SequenceFact
```

Add to `MainForceMirrorV2ResearchResult`:

```python
forensic_points: tuple[MainForceMirrorV2ForensicPoint, ...] | None
```

In `run()`, cache the already-derived `balanced` facts while building profile summaries. When `request.forensic` is true:

```python
forensic_points = tuple(
    MainForceMirrorV2ForensicPoint(point=point, sequence=fact)
    for point, fact in zip(points, balanced_facts, strict=True)
)
```

Otherwise set `None`. Do not duplicate formula calculations in CLI code.

- [ ] **Step 8: Render additive profile summaries and opt-in points**

In `_main_force_mirror_v2_payload`, build the current dict as `payload`. Add:

```python
payload["sequence_profiles"] = {
    profile_id: {
        "yearly": _main_force_mirror_v2_summary_tree(summary.yearly),
        "by_side": _main_force_mirror_v2_summary_tree(summary.by_side),
        "pooled": _main_force_mirror_v2_summary_tree(summary.pooled),
    }
    for profile_id, summary in result.sequence_profiles.items()
}
```

When `request.forensic` only:

```python
payload["forensic_points"] = [
    _main_force_mirror_v2_forensic_point_payload(item)
    for item in result.forensic_points or ()
]
```

The forensic renderer copies only existing point values plus sequence fields. Member output is exactly:

```text
member_status = ready | unavailable
member_relation_to_accumulated = existing relation or unavailable
member_relation_to_caution = existing relation or unavailable
```

Sequence JSON uses `profile_id="balanced"` and serializes `Decimal decay_ratio` through existing `_optional_decimal`.

- [ ] **Step 9: Add a read-only CLI example to `TESTING.md`**

Under “主力照妖镜 V2” add:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2026-03-10 \
  --through 2026-03-30 \
  --forensic
```

State immediately that it is Historical read-only stdout JSON and does not call RQData or write Canonical/DB/Redis/research-data.

- [ ] **Step 10: Run Task 3 tests and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py

git add \
  services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_requests.py \
  services/quant-api/app/guiyi_cli/research_payloads.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  TESTING.md
git commit -m "research: expose main force sequence forensic diagnostics"
```

---

### Task 4: Full zero-regression and scope audit before integration

**Files:** No planned source changes. Any required change outside the whitelist blocks integration and requires redesign.

**Interfaces:**
- Consumes: Tasks 1–3 complete branch.
- Produces: independently reviewed branch eligible for task → `develop`.

- [ ] **Step 1: Run project-native Main Force V2 suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS without real provider/data writes.

- [ ] **Step 2: Run Ruff and Mypy**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli
```

Expected: PASS.

- [ ] **Step 3: Audit changed paths exactly**

```bash
git diff --name-only develop...HEAD
```

Every path must be in the File Map whitelist. Any Kernel/Web/API service/member snapshot/migration/Alert/Runtime/STATUS/PROJECT_SOURCE/DECISIONS path is a hard failure.

- [ ] **Step 4: Run secret scan and diff check**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: clean.

- [ ] **Step 5: Audit for accidental new write/provider code**

```bash
git diff develop...HEAD -- \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli \
  | grep -E "rqdatac|get_member_rank|member-rank snapshot|--apply|pq\.write|session\.commit|redis" \
  && exit 1 || true
```

Expected: no new write/provider path. If an existing-context line matches, inspect the diff hunk and record why no new behavior was introduced.

- [ ] **Step 6: Open an independent Sol review session**

The independent reviewer checks only the spec/plan/branch diff and must explicitly answer:

```text
current Bar included in own percentile baseline? must be no
future horizon leaked into SequenceFact? must be no
memory crosses physical contract? must be no
long/short asymmetry? must be no
same peak repeats event cohorts? must be no
same Bar old event and new peak both retained? must be yes
non-monotonic time resets memory? must be yes
accumulated unavailable fabricates decay/reversal? must be no
existing V2/caution/member semantics changed? must be no
best-profile/product tuning added? must be no
new unnecessary subsystem added? must be no
```

Review conclusion is only `允许集成 develop` or `要求修正后再集成`.

- [ ] **Step 7: Integrate and clean only after review passes**

Merge/cherry-pick the task commits to `develop` using the repository’s current normal flow. Confirm commits are in `develop`, then remove the temporary worktree and merged task branch. Do not publish main/tag, reload Runtime, call RQData, or run real member writes.

---

### Task 5: Read-only JM forensic and active60 pressure-only evidence Gate

**Files:** No tracked changes. Temporary JSON is OS-temp only and must be deleted.

**Interfaces:**
- Consumes: integrated `develop` CLI.
- Produces: human-readable retrospective diagnosis plus exactly one Gate: `STOP` or `ALLOW_PHASE_FREEZE_DESIGN`.

- [ ] **Step 1: Run JM forensic**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2026-03-10 \
  --through 2026-03-30 \
  --forensic
```

Record for the user-marked high area: peak Bar, first `decay_seen`, first `liquidation_seen`, first `opposite_build_seen`, first `accumulated_reversal_seen`, and physical-contract continuity. If member context is unavailable, state unavailable; do not fetch it.

- [ ] **Step 2: Run active60 summaries through an external loop only**

```bash
tmp_dir="$(mktemp -d)"
while IFS= read -r symbol; do
  [ -z "$symbol" ] && continue
  UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 \
    --symbol "$symbol" \
    --series-kind actual_dominant \
    --frequency 60m \
    --since 2023-01-01 \
    --through 2026-08-20 \
    > "$tmp_dir/$symbol.json"
done < data/universe/active_products.txt
```

Do not add a repository batch script/module. Typed unavailable products remain explicit; do not silently drop them.

- [ ] **Step 3: Compare only the five predefined profiles**

For each symbol/profile, inspect sample counts and 1/3/5/10-bar `median_reversal_return`, `hit_rate`, `median_mfe`, `median_mae`, then inspect yearly long/short splits. The human report must answer:

```text
usable sample coverage across active60
long/short symmetry
balanced/fast/slow/loose/strict broad-direction consistency
product concentration
year-to-year sign/behavior drift
causal delay from peak to later sequence evidence
```

No product ranking, best profile, PnL, Sharpe or winner.

- [ ] **Step 4: Apply the value Gate**

Return `STOP` if sequence facts are unstable, too late, too sparse, or product-specific enough that they do not materially reduce manual stitching or improve review evidence.

Return `ALLOW_PHASE_FREEZE_DESIGN` only if a small cross-product/cross-year/cross-side stable region exists. This authorizes only a future Lane 3 design for formal Phase semantics, not implementation.

- [ ] **Step 5: Remove temp outputs**

Before cleanup, resolve the directory and require all of these checks:

```text
real path matches /private/tmp/guiyi-mfm-v2-sequence-forensic.*
the directory contains only expected per-symbol .json/.stderr/.status files
no symlink, directory, device, socket, or unexpected filename is present
```

If any check fails, stop and retain the directory for inspection. Only after the checks pass may the exact generated directory be removed; never target a broad root, glob, or unresolved variable.

No report is committed unless the user separately requests a versioned research artifact and its exact contract.

---

## Plan Self-Review

- Spec coverage: 60m-only, same-contract memory, nearest-rank strict-prior **build peak**、five fixed profiles、first-occurrence events、causal timing、prefix invariance、additive CLI、no member writes、no formal Phase and deletion boundary are all covered.
- YAGNI: no new module/service/repository/API/protocol/cache/batch orchestrator; active60 batching stays an external loop.
- Type consistency: profile/fact/summary/forensic DTOs are defined once in the existing research service and reused by tests/payload.
- Future-leak boundary: Task 1 derives only current/prior points; Task 2 alone uses forward horizons. Prefix equality is tested for every profile.
- Scope boundary: Kernel/Web/API service/member snapshot remain untouched.
- No undefined helper/function appears in the test steps; all synthetic helpers referenced by later tests are defined in earlier steps.
- The build-only peak constraint prevents liquidation/cover Bars from preempting the original peak sequence being diagnosed.
- No implementation placeholder remains.

## Execution Handoff

Recommended execution: Tasks 1–3 are checkpoints inside one independently integrable feature branch/worktree and one Codex implementation session; Task 4 is a separate independent Review session; Task 5 is a new read-only research session after integration. This avoids multiplying branches for mechanically dependent subtasks while preserving the project’s independent-review Gate.
