# Main Force Mirror V2 60m Sequence Forensic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 active `main_force_mirror_v2` Kernel/Web/API/Alert 语义的前提下，复用现有 V2 Research/CLI 增加 60m-only causal sequence forensic facts、5 个固定敏感性 profile 和 opt-in `--forensic` dossier，为是否值得冻结正式 Phase 规则提供只读 retrospective 证据。

**Architecture:** 所有新计算只位于现有 `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`。它消费现有 `MainForceMirrorV2Point`，按 physical-contract block 做 strict-prior sequence derivation，再复用当前 `_Observation → _outcome → _summary` 评价链；CLI 只增加一个布尔 `--forensic`，不建新 service、endpoint、repository、protocol、cache 或持久化 evidence。

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
- 所有 sequence facts 必须 same physical-contract、strict-prior、prefix invariant。
- `auto_order=false` 不变。
- 实现从当前 `develop` 创建独立 task branch/worktree；不得修改 main/runtime worktree。
- 完成后只允许 task → `develop`；不得 release main/tag、Runtime promotion 或真实写入。

---

## File Map

**Modify only:**

- `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py` — sequence profiles、pure derivation、sequence observations/summary、optional forensic result。
- `services/quant-api/app/guiyi_cli/research_parser.py` — `--forensic` flag。
- `services/quant-api/app/guiyi_cli/research_requests.py` — 把 flag 写入 immutable research request。
- `services/quant-api/app/guiyi_cli/research_payloads.py` — additive `sequence_profiles` 与 opt-in `forensic_points` JSON。
- `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py` — pure sequence、prefix、roll reset、summary tests。
- `services/quant-api/tests/test_research_cli.py` — CLI flag/default/payload tests。
- `TESTING.md` — 只补充 forensic 命令说明，不增加新测试框架。

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
- Consumes: existing `tuple[MainForceMirrorV2Point, ...]` returned by `MainForceMirrorV2Service`.
- Produces:
  - `MainForceMirrorV2SequenceProfile`
  - `SEQUENCE_PROFILES`
  - `MainForceMirrorV2SequenceFact`
  - `_derive_sequence_facts(points, profile) -> tuple[MainForceMirrorV2SequenceFact, ...]`
- No consumer outside the research module may import these facts in this task.

- [ ] **Step 1: Add failing profile-contract tests**

Add imports for the new symbols and freeze exactly five profiles:

```python
def test_sequence_profiles_are_small_fixed_global_sensitivity_set() -> None:
    assert tuple(profile.profile_id for profile in SEQUENCE_PROFILES) == (
        "balanced",
        "fast",
        "slow",
        "loose",
        "strict",
    )
    assert [
        (
            profile.peak_window,
            profile.peak_quantile,
            profile.decay_threshold,
            profile.transition_window,
        )
        for profile in SEQUENCE_PROFILES
    ] == [
        (10, Decimal("0.90"), Decimal("0.40"), 2),
        (5, Decimal("0.90"), Decimal("0.40"), 1),
        (20, Decimal("0.90"), Decimal("0.40"), 3),
        (10, Decimal("0.85"), Decimal("0.25"), 2),
        (10, Decimal("0.95"), Decimal("0.55"), 2),
    ]
```

- [ ] **Step 2: Run the test and confirm it fails because the profile symbols do not exist**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k sequence_profiles
```

Expected: FAIL during import or assertion because sequence profiles have not been defined.

- [ ] **Step 3: Add the exact profile and fact dataclasses**

In the existing research service, extend typing imports with `Sequence` only if needed, then add:

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
    side: SequenceSide
    pressure_state: str | None
    instant_pressure: float | None
    accumulated_pressure: float | None
    peak_index: int | None
    peak_pressure: float | None
    bars_since_peak: int | None
    decay_ratio: Decimal | None
    peak_seen: bool
    decay_seen: bool
    liquidation_seen: bool
    opposite_build_seen: bool
    accumulated_reversal_seen: bool
    state_transition: str | None
```

Do not add phase names or product-specific parameters.

- [ ] **Step 4: Add failing long-side causal sequence test**

Use `replace(_POINTS[0], ...)` to make one same-contract synthetic sequence. Keep all points in `JM2609`, with prior pressure magnitudes sufficient for the `fast` profile, then force a high positive peak followed by a negative `long_liquidation` point.

The assertion must prove the event is emitted on the later Bar, not backfilled to the peak:

```python
def test_sequence_long_peak_then_liquidation_is_recorded_only_when_seen() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "fast")
    points = tuple(
        replace(
            _POINTS[index],
            physical_contract="JM2609",
            pressure_state="long_build",
            instant_pressure=float(10 + index),
            accumulated_pressure=float(8 + index),
        )
        for index in range(6)
    )
    points = (
        *points,
        replace(
            _POINTS[0],
            bar_end=_bar(6).bar_end,
            trading_day=_bar(6).trading_day,
            physical_contract="JM2609",
            pressure_state="long_build",
            instant_pressure=80.0,
            accumulated_pressure=60.0,
        ),
        replace(
            _POINTS[0],
            bar_end=_bar(7).bar_end,
            trading_day=_bar(7).trading_day,
            physical_contract="JM2609",
            pressure_state="long_liquidation",
            instant_pressure=-50.0,
            accumulated_pressure=20.0,
        ),
    )

    facts = _derive_sequence_facts(points, profile)

    assert facts[6].peak_seen is True
    assert facts[6].liquidation_seen is False
    assert facts[7].peak_index == 6
    assert facts[7].liquidation_seen is True
```

- [ ] **Step 5: Add failing short-side mirror test**

Mirror the same construction exactly:

```python
def test_sequence_short_peak_then_cover_is_long_side_mirror() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "fast")
    # same magnitude history, signs inverted
    # peak state = short_build, later state = short_cover
    facts = _derive_sequence_facts(points, profile)
    assert facts[6].side == "short"
    assert facts[6].peak_seen is True
    assert facts[7].liquidation_seen is True
```

The test data must use the same magnitudes as the long test so only sign/state differ.

- [ ] **Step 6: Add failing physical-contract reset test**

```python
def test_sequence_memory_resets_at_physical_contract_change() -> None:
    profile = next(item for item in SEQUENCE_PROFILES if item.profile_id == "fast")
    points = _sequence_fixture_with_peak_at_last_jm2609_bar()
    points = (
        *points,
        replace(
            points[-1],
            bar_end=points[-1].bar_end + timedelta(hours=1),
            trading_day=points[-1].trading_day + timedelta(days=1),
            physical_contract="JM2701",
            pressure_state="long_liquidation",
            instant_pressure=-70.0,
            accumulated_pressure=-20.0,
        ),
    )
    facts = _derive_sequence_facts(points, profile)
    assert facts[-1].peak_index is None
    assert facts[-1].liquidation_seen is False
```

If a local helper is added for fixture construction, keep it in the test file only.

- [ ] **Step 7: Add failing prefix-invariance test for every profile**

```python
@pytest.mark.parametrize("profile", SEQUENCE_PROFILES)
def test_sequence_derivation_is_prefix_invariant(
    profile: MainForceMirrorV2SequenceProfile,
) -> None:
    points = _sequence_fixture_long_peak_liquidation_short_build()
    full = _derive_sequence_facts(points, profile)
    for end in range(1, len(points) + 1):
        prefix = _derive_sequence_facts(points[:end], profile)
        assert prefix[-1] == full[end - 1]
```

This test is the primary no-future-function guard.

- [ ] **Step 8: Run the new tests and confirm they fail before implementation**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k "sequence or prefix"
```

Expected: FAIL because `_derive_sequence_facts` is not implemented.

- [ ] **Step 9: Implement nearest-rank strict-prior peak detection**

Add this exact helper; it avoids numpy/interpolation policy and keeps the research surface simple:

```python
def _nearest_rank(values: tuple[Decimal, ...], quantile: Decimal) -> Decimal:
    if not values:
        raise ValueError("sequence percentile requires values")
    if quantile <= 0 or quantile > 1:
        raise ValueError("sequence percentile must be in (0, 1]")
    ordered = sorted(values)
    numerator = quantile * Decimal(len(ordered))
    rank = int(numerator.to_integral_value(rounding="ROUND_CEILING"))
    return ordered[max(1, rank) - 1]
```

Use `ROUND_CEILING` imported from `decimal` rather than the string if mypy requires the enum constant:

```python
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
```

and:

```python
rank = int(numerator.to_integral_value(rounding=ROUND_CEILING))
```

Peak qualification for index `i` is exactly:

```python
prior_ready = last profile.peak_window ready instant-pressure magnitudes
len(prior_ready) == profile.peak_window
abs(current.instant_pressure) >= _nearest_rank(prior_ready, profile.peak_quantile)
current.pressure_state != "turnover"
current.instant_pressure != 0
```

The current Bar must not enter `prior_ready`.

- [ ] **Step 10: Implement `_derive_sequence_facts` as a single forward scan**

Use one active peak per profile and physical block. Required processing order per current point:

```text
1. reset on contract/non-ready boundary
2. calculate immediate state_transition from previous ready point
3. evaluate an already-active prior peak against the current Bar
4. expire prior peak when bars_since_peak > transition_window
5. only after current-Bar event facts are determined, evaluate whether current Bar becomes/replaces the active peak
6. append immutable fact
```

When an opposite large Bar is both a takeover event for the prior peak and a new peak candidate for the opposite side, the current fact must first preserve the causal event from the prior peak; the new active peak only affects subsequent Bars.

Use `Decimal(str(point.accumulated_pressure))` for decay/reversal comparisons. Long peak decay:

```python
(peak_accumulated - current_accumulated) / abs(peak_accumulated)
```

Short peak decay:

```python
(abs(peak_accumulated) - abs(current_accumulated)) / abs(peak_accumulated)
```

`decay_seen` is true only on the **first** Bar for that active peak where `decay_ratio >= profile.decay_threshold`. The same first-occurrence rule applies independently to liquidation, opposite build and accumulated reversal so one peak does not generate repeated copies of the same cohort on consecutive Bars.

- [ ] **Step 11: Run sequence tests until all pass**

Run the same `-k "sequence or prefix"` command. Expected: PASS.

- [ ] **Step 12: Run the whole existing V2 research-service test file**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
```

Expected: all existing tests plus new sequence tests PASS.

- [ ] **Step 13: Commit Task 1 only**

```bash
git add \
  services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
git commit -m "research: add causal 60m main force sequence facts"
```

---

### Task 2: Reuse existing outcome machinery for five sequence profile summaries

**Files:**
- Modify: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`

**Interfaces:**
- Consumes: `SEQUENCE_PROFILES`, `_derive_sequence_facts`, existing `_Observation`, `_outcome`, `_summary`, `HORIZONS`.
- Produces:
  - `SEQUENCE_COHORTS`
  - `MainForceMirrorV2SequenceProfileSummary`
  - `MainForceMirrorV2ResearchResult.sequence_profiles`
- Existing `pooled/yearly/by_product/sensitivity` fields stay byte-for-semantics compatible.

- [ ] **Step 1: Add failing additive-result test**

```python
def test_research_adds_five_sequence_profiles_without_changing_existing_summary() -> None:
    result = _result()
    assert tuple(result.sequence_profiles) == (
        "balanced", "fast", "slow", "loose", "strict"
    )
    assert result.pooled["all_caution"][5].sample_count == 2
    assert result.sensitivity[Decimal("2.0")].pooled[5].sample_count == 1
```

- [ ] **Step 2: Add failing sequence-warning timing test**

Construct a single-contract market fixture where a long peak occurs at index P and `long_liquidation` is first seen at P+1. Assert:

```python
balanced = result.sequence_profiles["balanced"]
assert balanced.yearly[2026]["jm"]["long"]["peak_then_liquidation"][1].sample_count == 1
```

The observation index must be P+1, so the horizon starts after causal evidence appears, not from P.

- [ ] **Step 3: Add failing no-cross-roll outcome test**

Create a peak at the final old-contract Bar and an apparent liquidation in the first new-contract Bar. Assert every sequence cohort caused by that cross-roll combination has `sample_count == 0`.

- [ ] **Step 4: Run the three tests and confirm failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k "sequence_profiles or sequence_warning or cross_roll"
```

- [ ] **Step 5: Add exact sequence summary types**

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
    pooled: CohortMap
```

Add to `MainForceMirrorV2ResearchResult`:

```python
sequence_profiles: Mapping[str, MainForceMirrorV2SequenceProfileSummary]
```

Do not change `research_protocol`; this is additive diagnostics under the existing retrospective command, not a new formal protocol.

- [ ] **Step 6: Project facts into existing `_Observation`**

Add a pure helper:

```python
def _sequence_observations(
    product: str,
    points: tuple[MainForceMirrorV2Point, ...],
    facts: tuple[MainForceMirrorV2SequenceFact, ...],
) -> tuple[_Observation, ...]:
    ...
```

Rules:

```text
peak_seen                       → cohort peak_only at peak Bar
first decay_seen                → peak_then_decay at current Bar
first liquidation_seen          → peak_then_liquidation at current Bar
first opposite_build_seen       → peak_then_opposite_build at current Bar
first accumulated_reversal_seen → peak_then_accumulated_reversal at current Bar
```

For all sequence warnings, `_Observation.direction` is the **peak side** (`+1` long, `-1` short), and `_Observation.state` is literal `"long"` or `"short"`. This makes the existing yearly tree naturally become `year → product → side → cohort`.

Extend warning detection exactly:

```python
def _is_warning_cohort(cohort: str) -> bool:
    return (
        cohort == "all_caution"
        or cohort.startswith("caution_member_")
        or cohort in SEQUENCE_COHORTS
    )
```

This preserves the existing reversal/MFE/MAE convention.

- [ ] **Step 7: Add a cohort-parameterized summarizer instead of duplicating outcome code**

Refactor only the cohort selector:

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

Make existing `_summarize_cohorts` call it with `COHORTS`; do not rewrite `_outcome` or `_summary`.

Add a matching private yearly helper accepting a cohort tuple, or make `_yearly` accept an optional exact `cohorts` argument defaulting to `COHORTS`. Existing callers must produce unchanged structures.

- [ ] **Step 8: Populate five summaries in `run()`**

For each frozen profile:

```python
facts = _derive_sequence_facts(points, profile)
sequence_observations = _sequence_observations(request.symbol, points, facts)
summary = MainForceMirrorV2SequenceProfileSummary(
    profile_id=profile.profile_id,
    yearly=_yearly_selected(sequence_observations, SEQUENCE_COHORTS, bars, points),
    pooled=_summarize_selected_cohorts(
        sequence_observations, SEQUENCE_COHORTS, bars, points
    ),
)
```

Store in a `MappingProxyType` keyed in `SEQUENCE_PROFILES` order. Do not compute any best/winner field.

- [ ] **Step 9: Run Task 2 tests and full research-service tests**

Use the test file command from Task 1. Expected: PASS.

- [ ] **Step 10: Commit Task 2 only**

```bash
git add \
  services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
git commit -m "research: summarize main force sequence profiles"
```

---

### Task 3: Add opt-in `--forensic` dossier through existing CLI

**Files:**
- Modify: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `TESTING.md`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes: balanced sequence facts from Tasks 1–2.
- Produces:
  - `MainForceMirrorV2ResearchRequest.forensic: bool = False`
  - `MainForceMirrorV2ResearchResult.forensic_points`
  - CLI `--forensic`
  - JSON `sequence_profiles` always; `forensic_points` only when requested.
- No new CLI subcommand and no `research_commands.py` branching required.

- [ ] **Step 1: Add failing request-default test**

In research-service tests:

```python
def test_main_force_research_request_defaults_forensic_off() -> None:
    assert _request().forensic is False
```

- [ ] **Step 2: Add failing CLI parser/request test**

In `test_research_cli.py`, follow the existing CLI parsing helper and assert both modes:

```python
assert build_research_request(args_without_flag).forensic is False
assert build_research_request(args_with_forensic).forensic is True
```

The command remains:

```text
guiyi research main-force-mirror-v2 \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2026-03-10 \
  --through 2026-03-30 \
  [--forensic]
```

- [ ] **Step 3: Add failing payload-contract tests**

Default payload:

```python
assert "sequence_profiles" in payload
assert "forensic_points" not in payload
```

Forensic payload:

```python
assert payload["forensic_points"]
point = payload["forensic_points"][0]
assert set(point) >= {
    "bar_end",
    "trading_day",
    "physical_contract",
    "pressure_state",
    "instant_pressure",
    "accumulated_pressure",
    "price_impulse",
    "volume_ratio",
    "delta_oi",
    "oi_impulse",
    "range_position",
    "caution",
    "long_caution_score",
    "short_caution_score",
    "caution_reason_codes",
    "sequence",
    "member_status",
    "member_relation_to_accumulated",
    "member_relation_to_caution",
}
assert point["sequence"]["profile_id"] == "balanced"
```

- [ ] **Step 4: Run CLI/research tests and confirm failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  -k "forensic or sequence_profiles"
```

- [ ] **Step 5: Add `forensic` to immutable request**

Modify `MainForceMirrorV2ResearchRequest`:

```python
forensic: bool = False
```

In `__post_init__` add:

```python
if type(self.forensic) is not bool:
    raise ValueError("forensic must be boolean")
```

Do not let this flag affect market identity, frequency, bars, V2 point calculation or outcomes.

- [ ] **Step 6: Add forensic DTO without duplicating formulas**

Add:

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2ForensicPoint:
    point: MainForceMirrorV2Point
    sequence: MainForceMirrorV2SequenceFact
```

Add to result:

```python
forensic_points: tuple[MainForceMirrorV2ForensicPoint, ...] | None
```

In `run()`, derive `balanced` facts once and reuse them both for the balanced summary and, only if `request.forensic`, for:

```python
forensic_points = tuple(
    MainForceMirrorV2ForensicPoint(point, fact)
    for point, fact in zip(points, balanced_facts, strict=True)
)
```

When false, set `None`; do not copy full point DTOs for the default path.

- [ ] **Step 7: Wire parser and request builder**

In `research_parser.py` add exactly:

```python
mirror.add_argument("--forensic", action="store_true")
```

In `research_requests.py` add:

```python
forensic=args.forensic,
```

No new subcommand, no new service dispatch.

- [ ] **Step 8: Render sequence summaries additively**

Import the new sequence summary/fact types in `research_payloads.py` and add `sequence_profiles` to `_main_force_mirror_v2_payload`:

```python
"sequence_profiles": {
    profile_id: {
        "yearly": _main_force_mirror_v2_summary_tree(summary.yearly),
        "pooled": _main_force_mirror_v2_summary_tree(summary.pooled),
    }
    for profile_id, summary in result.sequence_profiles.items()
},
```

Do not rename or remove any existing field.

- [ ] **Step 9: Render forensic points only when requested**

Build the base payload first, then:

```python
if request.forensic:
    payload["forensic_points"] = [
        _main_force_mirror_v2_forensic_point_payload(item)
        for item in result.forensic_points or ()
    ]
return payload
```

The forensic renderer must only copy existing V2 point values plus balanced sequence facts. Member fields are limited to existing `status`, `relation_to_accumulated`, `relation_to_caution`; do not add member-history calculations.

Sequence payload fields:

```python
{
    "profile_id": "balanced",
    "side": fact.side,
    "peak_index": fact.peak_index,
    "peak_pressure": fact.peak_pressure,
    "bars_since_peak": fact.bars_since_peak,
    "decay_ratio": _optional_decimal(fact.decay_ratio),
    "peak_seen": fact.peak_seen,
    "decay_seen": fact.decay_seen,
    "liquidation_seen": fact.liquidation_seen,
    "opposite_build_seen": fact.opposite_build_seen,
    "accumulated_reversal_seen": fact.accumulated_reversal_seen,
    "state_transition": fact.state_transition,
}
```

- [ ] **Step 10: Document only the opt-in usage in `TESTING.md`**

Under “主力照妖镜 V2”, add a short read-only example:

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

Immediately state: this is Historical read-only stdout JSON; it does not call RQData, write Canonical/DB/Redis/research-data, or authorize Phase promotion.

- [ ] **Step 11: Run Task 3 targeted tests**

Use the two-file command from Step 4. Expected: PASS.

- [ ] **Step 12: Commit Task 3 only**

```bash
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

**Files:**
- No planned source changes.
- If a test fails, only fix files already allowed by the spec; any need to touch a forbidden path blocks integration and requires redesign.

**Interfaces:**
- Consumes: Tasks 1–3 complete branch.
- Produces: verified branch eligible for review/integration to `develop`.

- [ ] **Step 1: Run the project-native Main Force V2 suite**

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

Expected: PASS. This suite must not perform real member snapshot/RQData calls.

- [ ] **Step 2: Run Ruff on touched Python domains**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS.

- [ ] **Step 3: Run Mypy on research + CLI**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli
```

Expected: PASS.

- [ ] **Step 4: Prove forbidden code surfaces were not touched**

Run:

```bash
git diff --name-only develop...HEAD
```

Expected paths are a subset of the seven allowed files in the spec. Explicitly fail review if output includes `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`, any `apps/quant-web/`, migration, Alert, Runtime, member snapshot implementation, `STATUS.md`, `PROJECT_SOURCE.md`, or `DECISIONS.md`.

- [ ] **Step 5: Run secret scan and diff check**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: no secret findings for changed files; diff check clean.

- [ ] **Step 6: Verify no provider/write side effect was introduced**

Search the changed diff only:

```bash
git diff develop...HEAD -- \
  services/quant-api/app/research/main_force \
  services/quant-api/app/guiyi_cli \
  | grep -E "rqdatac|get_member_rank|member-rank snapshot|--apply|pq\.write|write_text\(|session\.commit|redis" \
  && exit 1 || true
```

Expected: no matches from new code. If a false positive is caused by existing context, inspect it manually and record why it is not a new write path.

- [ ] **Step 7: Open an independent Sol review session**

Review only the branch diff against the spec. Required review questions:

```text
- any future leak / prefix violation?
- current Bar accidentally included in its own peak baseline?
- contract roll memory leak?
- long/short asymmetry?
- duplicate events from one peak?
- existing V2/caution/member semantics altered?
- any best-profile selection or product tuning?
- any unnecessary abstraction/module?
```

Review outcome must be either `允许集成 develop` or `要求修正后再集成`.

- [ ] **Step 8: Integrate to develop only after review passes**

Use repository normal task integration flow. Do not publish `main`, create tag, reload Runtime, run RQData, or write member data.

- [ ] **Step 9: Clean task worktree/branch after confirmed integration**

Confirm the exact commits are in `develop`, then remove the temporary worktree and already-merged task branch. Do not delete the design/plan/task docs until the whole sequence-forensic work is accepted; cleanup of completed planning docs is a separate normal repository cleanup step.

---

### Task 5: Read-only JM forensic and active60 pressure-only research Gate

**Files:**
- No tracked source changes.
- Temporary stdout JSON may be stored under an OS temp directory only and deleted after summarization.

**Interfaces:**
- Consumes: integrated `develop` sequence-forensic CLI.
- Produces: a human-readable retrospective diagnosis and a binary recommendation: `STOP` or `ALLOW_PHASE_FREEZE_DESIGN`.
- Does not produce a formal research artifact, candidate, policy, release or Runtime conclusion.

- [ ] **Step 1: Run JM forensic on a window wide enough for the 20-bar slow profile**

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

Read-only requirements before execution:

```text
member dataset may be unavailable; that is acceptable
no RQData credentials/provider call is required
no --apply or data command is allowed
```

- [ ] **Step 2: For the user-marked 2026-03 peak, record exact causal timing**

From `forensic_points`, report only facts known by each Bar:

```text
peak Bar time/state/instant/accumulated
first balanced decay_seen Bar
first liquidation_seen Bar
first opposite_build_seen Bar
first accumulated_reversal_seen Bar
physical_contract continuity
caution/member context if already available
```

Do not rewrite the peak Bar label because of later decline.

- [ ] **Step 3: Run pressure-only summary for every active product with an external loop**

Create an OS temp directory:

```bash
tmp_dir="$(mktemp -d)"
```

Loop over `data/universe/active_products.txt` without adding a repo script:

```bash
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

If a product is typed unavailable, retain that as an explicit unavailable result in the review; do not silently drop it and do not change product scope.

- [ ] **Step 4: Summarize only the five predefined profiles**

For each product/profile, inspect sequence cohort sample counts and 1/3/5/10-bar `median_reversal_return`, `hit_rate`, `median_mfe`, `median_mae`, plus yearly long/short splits. Do not rank products and do not select a best profile.

The final comparison table must answer:

```text
1. how many products have usable peak/sequence samples?
2. do long and short sides behave roughly symmetrically?
3. do balanced/fast/slow/loose/strict tell the same broad story?
4. are results concentrated in only one or two products?
5. are there years where the sign/behavior reverses materially?
6. how many 60m Bars after a peak do causal decay/liquidation/takeover facts typically appear?
```

- [ ] **Step 5: Apply the value Gate**

Return exactly one of:

```text
STOP
```

when sequence facts do not materially improve explanation or are unstable/product-specific; in this case no Phase subsystem is built.

Or:

```text
ALLOW_PHASE_FREEZE_DESIGN
```

only when the evidence shows a small, understandable, cross-period/cross-side stable region that plausibly reduces manual stitching and improves review evidence.

Even `ALLOW_PHASE_FREEZE_DESIGN` does not authorize implementation. It only authorizes a new Lane 3 design task for formal Phase semantics.

- [ ] **Step 6: Remove temporary JSON**

```bash
rm -rf "$tmp_dir"
```

No retrospective output is committed unless the user separately requests a versioned research artifact and its contract.

---

## Plan Self-Review

- Spec coverage: 60m-only, same-contract memory, five fixed profiles, causal event timing, prefix invariance, additive CLI, no member writes, no formal Phase, deletion boundary are all assigned to Tasks 1–5.
- YAGNI: no new module/service/repository/API/protocol/cache/batch orchestrator; active60 batching remains an external loop.
- Type consistency: `SequenceProfileId`, `MainForceMirrorV2SequenceProfile`, `MainForceMirrorV2SequenceFact`, `MainForceMirrorV2SequenceProfileSummary`, `MainForceMirrorV2ForensicPoint` are defined once in the existing research service and reused by payload/tests.
- Future-leak boundary: Task 1 derives only from current/prior V2 points; Task 2 alone uses forward horizons for retrospective outcome. Prefix equality is explicitly tested for every profile.
- Scope boundary: Kernel/Web/API/member snapshot implementations remain untouched.
- No placeholder implementation steps remain.

## Execution Handoff

Plan complete. Recommended execution is **one independent Codex session per Task 1–4**, with Task 5 as a separate read-only research session after integration. Because this is causal research rather than active formula promotion, Tasks 1–4 are Lane 1 + Sol/high reasoning; any later formal Phase freeze is a new Lane 3 task.
