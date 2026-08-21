# Main Force Mirror V2 Phase Memory Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the smallest causal 60m sequence-forensic capability to the existing Main Force Mirror V2 research path, without creating active Phase semantics, new modules, new storage, new APIs, Web behavior, member-history logic, or lower-timeframe dependencies.

**Architecture:** Reuse `MainForceMirrorV2Service` points as the sole input. Add a pure sequence-fact reducer inside the existing `main_force_mirror_v2_research_service.py`, summarize only exact adjacent state transitions through the existing 1/3/5/10-bar outcome machinery, and expose optional per-Bar detail through the existing `guiyi research main-force-mirror-v2 --forensic` command. Sequence summaries remain separate from existing `COHORTS`, `top_bottom_spreads`, member sensitivity, Kernel, API, and Web semantics.

**Tech Stack:** Python 3.13, dataclasses, Decimal/binary64 values already emitted by V2, pytest, argparse, existing `MarketDataService`/`MainForceMirrorV2Service`/research CLI.

**Spec:** `docs/superpowers/specs/2026-08-21-main-force-mirror-v2-phase-memory-design.md`

## Global Constraints

- Frequency is exactly `60m`; no 1m/5m/15m/30m/1d/1w input, confirmation, projection, or fallback.
- Reuse existing `main_force_mirror_v2`; do not create a new indicator/policy identity.
- Do not modify `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`.
- Do not modify `MainForceMirrorV2Service`, member snapshot reader/builder, API, Web, Alert, Execution Review, Runtime, Data Foundation, Catalog, Canonical, MainContractMap, or `STATUS.md`.
- Do not add Phase labels (`NORMAL/CLIMAX/UNWIND/TAKEOVER`), Phase thresholds, parameter sweep, new member-history formulas, or member-sequence historical cohorts.
- Sequence facts use current and prior confirmed 60m V2 points only; invalid/unready points and physical-contract changes reset memory.
- Forward 1/3/5/10-bar outcomes are evaluation only and must never affect sequence-fact construction.
- Existing V2 `COHORTS`, `top_bottom_spreads`, member sensitivity, caution formula/latch, and `parameters_hash` remain unchanged.
- `--forensic` is stdout-only, read-only, research-only; no report persistence or external mutation.
- `auto_order=false` remains true; no order path is created.
- Any need to break these boundaries is `BLOCKED_SCOPE_EXPANSION`: stop and return to design review.

---

### Task 1: Add the causal 60m sequence-fact contract and reducer

**Files:**
- Modify: `services/quant-api/app/market_data/main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`

**Interfaces:**
- Consumes: `tuple[MainForceMirrorV2Point, ...]` already returned by `MainForceMirrorV2Service.query_page()`.
- Produces:

```python
SequenceSignFlip: TypeAlias = Literal[
    "positive_to_negative",
    "negative_to_positive",
]

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SequenceFact:
    bar_end: datetime
    trading_day: date
    physical_contract: str
    previous_state: str | None
    current_state: str
    state_transition: str | None
    previous_instant_pressure: float | None
    current_instant_pressure: float
    previous_accumulated_pressure: float | None
    current_accumulated_pressure: float | None
    accumulated_delta: float | None
    accumulated_sign_flip: SequenceSignFlip | None
    state_sequence_3: tuple[str, ...]
    state_sequence_5: tuple[str, ...]
    range_position: float | None
    caution: str | None
    member_relation_to_accumulated: str


def build_main_force_mirror_v2_sequence_facts(
    points: tuple[MainForceMirrorV2Point, ...],
) -> tuple[MainForceMirrorV2SequenceFact | None, ...]: ...
```

The return tuple is one-to-one aligned with `points`; non-`pressure_ready` points return `None` and reset memory.

- [ ] **Step 1: Write failing tests for exact adjacent transitions and invalid-gap reset**

Add fixtures that explicitly include:

```python
states = (
    "long_build",
    "long_liquidation",
    "short_build",
    None,  # pressure-unready gap: must reset
    "short_build",
    "short_cover",
    "long_build",
)
```

Assert:

```python
facts[0].previous_state is None
facts[1].state_transition == "long_build->long_liquidation"
facts[2].state_sequence_3 == (
    "long_build",
    "long_liquidation",
    "short_build",
)
facts[3] is None
facts[4].previous_state is None
facts[5].state_transition == "short_build->short_cover"
facts[6].state_sequence_3 == (
    "short_build",
    "short_cover",
    "long_build",
)
```

- [ ] **Step 2: Run the reset test and confirm RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k 'sequence_fact and reset'
```

Expected: FAIL because `build_main_force_mirror_v2_sequence_facts` and the dataclass do not exist.

- [ ] **Step 3: Write failing tests for physical-contract reset**

Construct consecutive ready points:

```text
JM2609 long_build
JM2701 long_liquidation
```

Assert the second point begins a fresh block:

```python
assert facts[1].previous_state is None
assert facts[1].state_transition is None
assert facts[1].state_sequence_3 == ("long_liquidation",)
```

- [ ] **Step 4: Implement the minimal sequence reducer**

Implement one pass with only current-prefix memory:

```python
def build_main_force_mirror_v2_sequence_facts(points):
    facts = []
    block_contract: str | None = None
    block_states: list[str] = []
    previous: MainForceMirrorV2Point | None = None

    for point in points:
        if (
            not point.pressure_ready
            or point.pressure_state is None
            or point.physical_contract is None
            or point.instant_pressure is None
        ):
            facts.append(None)
            block_contract = None
            block_states = []
            previous = None
            continue

        if block_contract != point.physical_contract:
            block_contract = point.physical_contract
            block_states = []
            previous = None

        previous_state = previous.pressure_state if previous is not None else None
        transition = (
            None
            if previous_state is None
            else f"{previous_state}->{point.pressure_state}"
        )
        previous_accumulated = (
            previous.accumulated_pressure
            if previous is not None and previous.accumulated_ready
            else None
        )
        current_accumulated = (
            point.accumulated_pressure if point.accumulated_ready else None
        )
        accumulated_delta = _sequence_accumulated_delta(
            previous_accumulated,
            current_accumulated,
        )
        sign_flip = _sequence_sign_flip(
            previous_accumulated,
            current_accumulated,
        )
        sequence = (*block_states, point.pressure_state)
        member_relation = (
            "unavailable"
            if point.member is None or point.member.status != "ready"
            else point.member.relation_to_accumulated
        )
        facts.append(
            MainForceMirrorV2SequenceFact(
                bar_end=point.bar_end,
                trading_day=point.trading_day,
                physical_contract=point.physical_contract,
                previous_state=previous_state,
                current_state=point.pressure_state,
                state_transition=transition,
                previous_instant_pressure=(
                    None if previous is None else previous.instant_pressure
                ),
                current_instant_pressure=point.instant_pressure,
                previous_accumulated_pressure=previous_accumulated,
                current_accumulated_pressure=current_accumulated,
                accumulated_delta=accumulated_delta,
                accumulated_sign_flip=sign_flip,
                state_sequence_3=tuple(sequence[-3:]),
                state_sequence_5=tuple(sequence[-5:]),
                range_position=point.range_position,
                caution=point.caution,
                member_relation_to_accumulated=member_relation,
            )
        )
        block_states.append(point.pressure_state)
        previous = point

    return tuple(facts)
```

Use the existing V2 public rounding helper for `accumulated_delta` so derived stdout does not introduce a second rounding convention:

```python
round_half_away_from_zero_binary64(current - previous, 6)
```

Strict sign flip:

```python
if previous > 0 and current < 0:
    return "positive_to_negative"
if previous < 0 and current > 0:
    return "negative_to_positive"
return None
```

Zero never counts as a flip.

- [ ] **Step 5: Run the targeted sequence tests and confirm GREEN**

Run the same targeted pytest command. Expected: PASS.

- [ ] **Step 6: Write and run prefix-invariance test**

For every `end` from 1 through fixture length:

```python
full = build_main_force_mirror_v2_sequence_facts(points)
for end in range(1, len(points) + 1):
    prefix = build_main_force_mirror_v2_sequence_facts(points[:end])
    assert prefix[-1] == full[end - 1]
```

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k 'sequence_fact or prefix'
```

Expected: PASS.

- [ ] **Step 7: Run existing V2 research-service tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
```

Expected: all existing and new tests PASS; existing result fields remain unchanged at this task.

- [ ] **Step 8: Commit only Task 1 files**

```bash
git add \
  services/quant-api/app/market_data/main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
git commit -m "research: add causal main force sequence facts"
```

**Task 1 acceptance:** causal one-to-one sequence facts exist; 60m semantics are unchanged; no Phase labels/cohorts/CLI changes yet.

---

### Task 2: Add separate sequence summaries and optional `--forensic` output

**Files:**
- Modify: `services/quant-api/app/market_data/main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `TESTING.md`
- Test: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`
- Test: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes: `build_main_force_mirror_v2_sequence_facts()` from Task 1 and existing `_summary()` / `_outcome()` machinery.
- Produces exact sequence cohort names:

```python
SEQUENCE_COHORTS = (
    "long_build_to_long_liquidation",
    "long_build_to_short_build",
    "long_build_to_long_liquidation_to_short_build",
    "short_build_to_short_cover",
    "short_build_to_long_build",
    "short_build_to_short_cover_to_long_build",
    "accumulated_positive_to_negative",
    "accumulated_negative_to_positive",
)
```

- Extends `MainForceMirrorV2ResearchRequest` with:

```python
forensic: bool = False
```

- Extends `MainForceMirrorV2ResearchResult` with separate research-only fields:

```python
sequence_pooled: Mapping[str, HorizonMap]
sequence_yearly: Mapping[int, Mapping[str, HorizonMap]]
forensic_points: tuple[MainForceMirrorV2Point, ...] | None
forensic_sequence_facts: tuple[MainForceMirrorV2SequenceFact | None, ...] | None
```

The default request keeps both forensic fields `None`.

- [ ] **Step 1: Write failing tests for exact 2-step/3-step cohort mapping**

Use a same-contract fixture containing:

```text
long_build → long_liquidation → short_build
short_build → short_cover → long_build
```

Assert only exact cohorts appear, with no skipped-state inference:

```python
assert result.sequence_pooled[
    "long_build_to_long_liquidation"
][1].sample_count == 1
assert result.sequence_pooled[
    "long_build_to_long_liquidation_to_short_build"
][1].sample_count == 1
assert result.sequence_pooled[
    "short_build_to_short_cover"
][1].sample_count == 1
assert result.sequence_pooled[
    "short_build_to_short_cover_to_long_build"
][1].sample_count == 1
```

Add a fixture `long_build → turnover → short_build` and assert:

```python
assert result.sequence_pooled[
    "long_build_to_short_build"
][1].sample_count == 0
```

- [ ] **Step 2: Run cohort tests and confirm RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  -k 'sequence_cohort'
```

Expected: FAIL because sequence summaries do not exist.

- [ ] **Step 3: Implement sequence observations without touching existing `COHORTS`**

Keep `COHORTS` byte-for-byte semantically unchanged. Add a separate helper:

```python
def _sequence_observations(
    product: str,
    points: tuple[MainForceMirrorV2Point, ...],
    facts: tuple[MainForceMirrorV2SequenceFact | None, ...],
) -> tuple[_Observation, ...]:
    observations: list[_Observation] = []
    for index, fact in enumerate(facts):
        if fact is None:
            continue

        cohort_and_direction: list[tuple[str, int]] = []
        if fact.state_transition == "long_build->long_liquidation":
            cohort_and_direction.append(("long_build_to_long_liquidation", 1))
        if fact.state_transition == "long_build->short_build":
            cohort_and_direction.append(("long_build_to_short_build", 1))
        if fact.state_sequence_3 == (
            "long_build", "long_liquidation", "short_build"
        ):
            cohort_and_direction.append(
                ("long_build_to_long_liquidation_to_short_build", 1)
            )
        if fact.state_transition == "short_build->short_cover":
            cohort_and_direction.append(("short_build_to_short_cover", -1))
        if fact.state_transition == "short_build->long_build":
            cohort_and_direction.append(("short_build_to_long_build", -1))
        if fact.state_sequence_3 == (
            "short_build", "short_cover", "long_build"
        ):
            cohort_and_direction.append(
                ("short_build_to_short_cover_to_long_build", -1)
            )
        if fact.accumulated_sign_flip == "positive_to_negative":
            cohort_and_direction.append(("accumulated_positive_to_negative", 1))
        if fact.accumulated_sign_flip == "negative_to_positive":
            cohort_and_direction.append(("accumulated_negative_to_positive", -1))

        for cohort, original_side in cohort_and_direction:
            observations.append(
                _Observation(
                    index=index,
                    product=product,
                    year=points[index].trading_day.year,
                    state=cohort,
                    cohort=cohort,
                    direction=original_side,
                )
            )
    return tuple(observations)
```

Extend warning semantics only in `_is_warning_cohort`:

```python
return (
    cohort == "all_caution"
    or cohort.startswith("caution_member_")
    or cohort in SEQUENCE_COHORTS
)
```

Do **not** append sequence names to `COHORTS`; this prevents sequence diagnostics from changing existing `top_bottom_spreads` and member sensitivity.

- [ ] **Step 4: Add independent pooled/yearly sequence summaries**

Add helpers that summarize only `SEQUENCE_COHORTS`:

```python
def _summarize_sequence_cohorts(...):
    return MappingProxyType({
        cohort: MappingProxyType({
            horizon: _summary(
                tuple(item for item in observations if item.cohort == cohort),
                horizon,
                bars,
                points,
            )
            for horizon in HORIZONS
        })
        for cohort in SEQUENCE_COHORTS
    })
```

Yearly grouping is only:

```text
year → sequence cohort → horizon summary
```

Do not create `sequence_by_product`; one request already has one symbol.

- [ ] **Step 5: Add regression test that existing ranking/sensitivity are unchanged**

Capture the current fixture result before sequence observations are included and assert after the change:

```python
assert tuple(result.pooled) == COHORTS
assert tuple(result.top_bottom_spreads) == (1, 3, 5, 10)
assert tuple(result.sensitivity) == tuple(
    Decimal(value) for value in ("0.5", "1.0", "1.5", "2.0", "2.5")
)
```

Also assert none of `SEQUENCE_COHORTS` appears in `result.pooled`.

- [ ] **Step 6: Add `forensic: bool = False` to the request contract**

In `MainForceMirrorV2ResearchRequest.__post_init__` reject non-bool values:

```python
if type(self.forensic) is not bool:
    raise ValueError("forensic must be bool")
```

In `run()` compute sequence facts once and return:

```python
forensic_points=points if request.forensic else None
forensic_sequence_facts=facts if request.forensic else None
```

Default result remains compact.

- [ ] **Step 7: Write failing CLI parser/payload tests**

In `test_research_cli.py` verify:

```text
main-force-mirror-v2 --frequency accepts only 60m
--forensic defaults false
--forensic sets request.forensic true
```

Default payload assertions:

```python
assert "sequence_pooled" in payload
assert "sequence_yearly" in payload
assert "forensic_points" not in payload
```

Forensic payload assertions:

```python
assert len(payload["forensic_points"]) == len(result.forensic_points)
assert payload["forensic_points"][0]["sequence_fact"] is not None
```

- [ ] **Step 8: Run CLI tests and confirm RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  -k 'main_force_mirror_v2'
```

Expected: FAIL because parser and serializer do not know `--forensic` or sequence fields.

- [ ] **Step 9: Implement the existing-command CLI extension**

In `research_parser.py`:

```python
mirror.add_argument("--forensic", action="store_true")
```

In `build_research_request()`:

```python
forensic=args.forensic,
```

In `_main_force_mirror_v2_payload()` always add:

```python
"sequence_pooled": _main_force_mirror_v2_summary_tree(result.sequence_pooled),
"sequence_yearly": _main_force_mirror_v2_summary_tree(result.sequence_yearly),
```

When `request.forensic` is true, add `forensic_points` by zipping `result.forensic_points` and `result.forensic_sequence_facts`. Serialize existing point values; do not recompute V2 formulas in CLI.

Exact member fallback:

```text
member is None/unavailable → status="unavailable" and nullable member fields
```

Do not expose paths, credentials, provider internals, or new data identities.

- [ ] **Step 10: Update `TESTING.md` only for the new read-only research contract**

Under `## 主力照妖镜 V2`, state that the V2 test group now also covers:

```text
60m same-contract sequence facts
prefix invariance
separate sequence retrospective summaries
optional stdout-only --forensic
```

Explicitly state it still does not run real member snapshot, provider writes, Phase promotion, Alert, Runtime, or orders.

- [ ] **Step 11: Run Task 2 targeted tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS.

- [ ] **Step 12: Run the full V2 regression set**

Use the exact `TESTING.md` Main Force Mirror V2 command:

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

Expected: PASS; no Web/API behavior changes.

- [ ] **Step 13: Run static checks and repository checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/main_force_mirror_v2_research_service.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data/main_force_mirror_v2_research_service.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: all PASS/clean; secret scan must not print secret values.

- [ ] **Step 14: Commit Task 2 files only**

```bash
git add \
  services/quant-api/app/market_data/main_force_mirror_v2_research_service.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py \
  TESTING.md
git commit -m "research: expose main force sequence diagnostics"
```

**Task 2 acceptance:** existing `main-force-mirror-v2` gains separate sequence summaries and optional forensic detail; no new command/module/storage/Phase semantics.

---

### Task 3: Independent causal/scope review before evidence

**Files:**
- Review only: Task 1–2 diff against latest `develop`
- Read: `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, Design, Plan, Task Contract

**Interfaces:**
- Consumes: accepted Task 1–2 implementation commits.
- Produces: review result only: `C0/I0` or explicit blocking findings. No code changes in the review worktree.

- [ ] **Step 1: Review scope mechanically**

The changed-path set must be a subset of:

```text
services/quant-api/app/market_data/main_force_mirror_v2_research_service.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md
```

Any Kernel/API/Web/member-builder/Runtime/Alert/Data Foundation change is blocking.

- [ ] **Step 2: Review causal semantics**

Prove from code/tests:

```text
current fact depends only on current/prior V2 points
unready gap resets
contract switch resets
state_sequence_3/5 never crosses reset
zero accumulated value is not sign flip
forward outcomes never feed fact construction
```

Any future dependency or full-series backfill/relabel is blocking.

- [ ] **Step 3: Review YAGNI constraints**

Verify absence of:

```text
Phase label/reducer
new thresholds
new policy/hash
new member-history reducer
new storage/cache
new endpoint
new Web behavior
new batch service
```

- [ ] **Step 4: Re-run the Task 2 verification commands from a clean review identity**

Expected: PASS.

- [ ] **Step 5: Report review conclusion**

Only two valid outputs:

```text
C0/I0 — 允许进入 Stage A evidence
```

or

```text
BLOCKED — list exact finding, file, behavior, required correction
```

If blocked, open a separate fix task from latest `develop`; do not edit inside the review worktree.

**Task 3 acceptance:** independent review confirms causal 60m-only research semantics and no scope expansion.

---

### Task 4: Run read-only JM forensic + active60 Stage A and make the Go/Stop decision

**Files:**
- No repository source changes required.
- Temporary output only: `/tmp/guiyi-mfm-phase-memory-stage-a-20260821/`
- Read: `data/universe/active_products.txt`

**Interfaces:**
- Consumes: reviewed `guiyi research main-force-mirror-v2` implementation.
- Produces: temporary JSON evidence and a human-reviewed Go/Stop recommendation. This task does **not** create Git-tracked evidence, member snapshot, policy, candidate, Web marker, or Phase implementation.

- [ ] **Step 1: Create a temporary read-only evidence directory**

```bash
rm -rf /tmp/guiyi-mfm-phase-memory-stage-a-20260821
mkdir -p /tmp/guiyi-mfm-phase-memory-stage-a-20260821
```

This removes only the task-specific `/tmp` directory, never repository or research-data content.

- [ ] **Step 2: Run the JM 2026-03 forensic case**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 \
  --symbol jm \
  --series-kind actual_dominant \
  --frequency 60m \
  --since 2026-03-20 \
  --through 2026-03-27 \
  --forensic \
  > /tmp/guiyi-mfm-phase-memory-stage-a-20260821/jm-2026-03-forensic.json
```

Expected: JSON status `ok`, `readonly=true`, `research_only=true`, `frequency=60m`, and non-empty `forensic_points` for the available window.

- [ ] **Step 3: Inspect JM without imposing a target label**

Record only observed facts:

```text
first large long_build in highlighted rally
first later long_liquidation
first later short_build
first accumulated positive_to_negative flip if any
first exact long_build→long_liquidation→short_build sequence if any
member relation only if already available; unavailable is acceptable
```

Do not classify any Bar as “出货/CLIMAX/UNWIND/TAKEOVER”.

- [ ] **Step 4: Run active60 pressure-only retrospective summaries**

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
    > "/tmp/guiyi-mfm-phase-memory-stage-a-20260821/${symbol}.json" || exit 1
done < data/universe/active_products.txt
```

Expected: one JSON file per active product; any real typed-unavailable failure must stop the loop and be diagnosed, not silently dropped.

- [ ] **Step 5: Aggregate only the sequence summaries in a temporary analysis**

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path('/tmp/guiyi-mfm-phase-memory-stage-a-20260821')
rows = []
for path in sorted(root.glob('*.json')):
    if path.name.startswith('jm-2026-03-forensic'):
        continue
    data = json.loads(path.read_text())
    symbol = data['symbol']
    for cohort, horizons in data['sequence_pooled'].items():
        for horizon, summary in horizons.items():
            rows.append({
                'symbol': symbol,
                'cohort': cohort,
                'horizon': int(horizon),
                'sample_count': summary['sample_count'],
                'median_reversal_return': summary['median_reversal_return'],
                'hit_rate': summary['hit_rate'],
            })

for cohort in sorted({row['cohort'] for row in rows}):
    subset = [row for row in rows if row['cohort'] == cohort and row['horizon'] == 5]
    available = [row for row in subset if row['sample_count'] > 0]
    print(
        cohort,
        'products_with_samples=', len(available),
        'samples=', sum(row['sample_count'] for row in available),
    )
PY
```

This is descriptive only; do not automatically rank or select a winner.

- [ ] **Step 6: Review yearly stability and long/short mirror coverage**

For each exact mirror pair:

```text
long_build_to_long_liquidation
vs short_build_to_short_cover

long_build_to_short_build
vs short_build_to_long_build

long_build_to_long_liquidation_to_short_build
vs short_build_to_short_cover_to_long_build

accumulated_positive_to_negative
vs accumulated_negative_to_positive
```

Check:

```text
number of products with samples
sample counts by year
whether one side is nearly absent across most products
whether 3/5/10-bar reversal behavior changes sign erratically by year
```

Do not create a universal threshold from this task.

- [ ] **Step 7: Apply the Design Go/Stop gate**

Recommend **GO to a new Phase design only if all are true**:

```text
multi-product + multi-year recurrence
formation is early enough to reduce manual interpretation
long/short mirror is not structurally broken
output clearly improves interpretation or replay evidence
future rule can remain small and deletable
```

Otherwise recommend:

```text
STOP — keep current V2; delete or retain research-only diagnostics according to demonstrated utility; no Phase implementation
```

- [ ] **Step 8: Do not perform member snapshot, Web, Alert, Runtime, release, or Phase changes**

Task 4 ends at the evidence recommendation. Any next implementation requires a new explicit design task.

**Task 4 acceptance:** JM is explainable from causal 60m facts, active60 Stage A is reviewed, and a human Go/Stop decision exists without changing active product semantics.

---

## Plan Self-Review

### Spec coverage

- Five-question/YAGNI gate: enforced by Global Constraints, Task 3, Task 4 Go/Stop.
- 60m-only: enforced by existing request plus parser tests and no lower-timeframe inputs.
- Reuse existing Research: only existing research service/CLI are modified.
- No Kernel/Phase/member expansion: explicit forbidden paths and Task 3 scope review.
- Sequence facts/reset/prefix invariance: Task 1.
- Exact mirror cohorts and separate summaries: Task 2.
- Existing cohort ranking/sensitivity isolation: Task 2 regression test.
- Forensic stdout: Task 2.
- JM Golden Behavior Case: Task 4.
- active60 pressure-only Stage A: Task 4.
- Member snapshot/history and Phase productization deferred: Global Constraints and Task 4 stop boundary.

### Placeholder scan

No `TBD`, `TODO`, “implement later”, generic “add tests”, or undefined implementation step remains. Future Phase/member work is explicitly outside this plan, not a placeholder inside it.

### Type consistency

`MainForceMirrorV2SequenceFact`, `build_main_force_mirror_v2_sequence_facts`, `SEQUENCE_COHORTS`, `sequence_pooled`, `sequence_yearly`, `forensic_points`, and `forensic_sequence_facts` are defined once in Tasks 1–2 and used consistently thereafter.

## Completion boundary

Completing Tasks 1–3 means only **“sequence research capability is implemented and reviewed.”** Completing Task 4 adds only a **read-only retrospective Go/Stop recommendation**.

Nothing in this plan authorizes or proves:

```text
Phase model effectiveness
member snapshot mutation
strategy validity
Alert/notification
release/tag
Runtime promotion
order capability
```
