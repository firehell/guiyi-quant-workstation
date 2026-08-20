# Multi-Candidate Research & Robustness V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 SuBing/N exact Candidate、交易公式或 production 边界的前提下，建立两个 frozen Candidate 的 retrospective temporal、active60 cross-symbol 与 `jm` event relationship robustness dossier，并生成可复算的版本化研究证据。

**Architecture:** 继续复用现有 `MarketDataService → ActualDominantResearchSegmentLoader → SuBing/N source research → Candidate Validation`。新增层只做 additive event projection、统一描述性投影与 orchestration；不建立 Strategy Plugin/Registry、参数优化器、第二 rolling engine、第二 Historical Gateway 或自动策略排名。

**Tech Stack:** Python 3.13、dataclasses/StrEnum、Decimal、existing MarketDataService/Candidate Validation、argparse CLI、pytest、Ruff、Mypy、Git-tracked JSON research artifacts。

**Spec:** `docs/superpowers/specs/2026-08-20-multi-candidate-robustness-v1-design.md`

**Task Contract:** `docs/tasks/TASK-MULTI-CANDIDATE-ROBUSTNESS-V1-20260820.md`

## Global Constraints

- 每个 Task 开始前读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、Spec、Plan、Task Contract 与最新 `develop`；active canonical 与计划冲突时停止。
- 只研究 `subing_lifecycle_v2_candidate_v1` 与 `n_structure_5m_candidate_v1`；不得修改二者 Candidate/Policy/Formula/Protocol identity。
- common retrospective 固定 `2023-01-01..2026-08-18`；anchor 固定 `jm`；cross-symbol 固定 Spec §5 的 exact active60 顺序。
- SuBing anchor event 只能是 `ENTRY_CONFIRMED`；N anchor event 只能是 `CompletedNPattern completion`。
- event proximity 必须 same symbol + same physical contract + same rank1 segment；禁止跨换月匹配。
- exact same-boundary `same/opposite` 是 event-pair count；3/5/8 proximity 是 source-event coverage count，denominator 始终为 source event count。
- signed distance 固定 `target.segment_bar_index - source.segment_bar_index`；nearest tie 固定 earlier-first，再按 target event id。
- SuBing horizon semantics=`same_trading_day_only`；N=`same_rank1_segment`；不得把二者直接相减、做 ratio 或 winner 结论。
- V1 不做参数 sweep；规则变化必须新建 Candidate/Policy 任务。
- Robustness V1 不生成新 prospective OOS，不回填 OOS；SuBing/N 的 prospective 状态继续由自己的 exact Candidate Protocol 决定。
- 禁止 `KEEP/DROP/PROMOTE/rank/score/winner/profitability/expected_profit` 等策略决策字段。
- Historical 唯一入口仍为 `MarketDataService`；不直接读 Parquet/RQData/Redis，不复制 rank1 resolver。
- 无 HTTP/Web/DB/Redis/worker/queue/Alert/Scope/notification/Execution Review/order 变更。
- 不触及 `main`、tag、release 或 Runtime；任何 develop 集成不授权外部 mutation。
- 所有交易相关数值与 bps 使用 `Decimal`，不得 float 化。
- tracked 变更按 `TESTING.md` 运行适用测试、Ruff/Mypy、`python3 scripts/engineering/secret_scan.py --json` 与 `git diff --check`。

---

## Planned File Map

### New files

```text
data/research_protocols/multi_candidate_robustness_v1.json
services/quant-api/app/market_data/multi_candidate_robustness_policy.py
services/quant-api/app/market_data/multi_candidate_events.py
services/quant-api/app/market_data/multi_candidate_robustness.py
services/quant-api/app/market_data/multi_candidate_robustness_service.py
services/quant-api/tests/test_multi_candidate_robustness_policy.py
services/quant-api/tests/test_multi_candidate_events.py
services/quant-api/tests/test_multi_candidate_robustness.py
services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py
reports/research/candidate_robustness/multi_candidate_robustness_v1/
  anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

### Existing files intentionally modified

```text
services/quant-api/app/market_data/subing_lifecycle_research_service.py
services/quant-api/app/market_data/n_structure_research_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
services/quant-api/tests/data_foundation/test_n_structure_research_service.py
services/quant-api/tests/test_research_cli.py
TESTING.md
docs/ARCHITECTURE.md
PROJECT_SOURCE.md
STATUS.md
```

### Explicitly forbidden files

```text
data/research_candidates/subing_lifecycle_v2_candidate_v1.json
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/candidate_validation_v1.json
data/research_protocols/n_structure_validation_v1.json
data/research_policies/subing_lifecycle_v2_research_v1.json
data/research_policies/n_structure_5m_v1.json
Alert Rule/Scope files
Execution Review migrations/schema
Market Foundation schema/Catalog
main/tag/runtime deployment identity
```

---

## Codex 调度建议

- 任务车道：Task 1/6 Lane 2；Task 2/3/4/5/7/8 Lane 1
- 执行入口：Codex App
- 推荐模型：Tasks 1–5/7/8 Sol；Task 6 Terra
- 推理强度：Tasks 1–5/7/8 高；Task 6 中
- 会话：每个 Task 新开独立会话；Task 7、Task 8 各自再开独立 Review 会话
- Plan：Tasks 1–6 Plan-then-execute；Task 7 Review-only；Task 8 Plan-then-execute + Evidence Review
- 工作区：每个实现 Task 从最新 `develop` 创建新 task worktree；Task 7 使用 clean develop review worktree；Task 8 使用独立 evidence worktree
- 人工 Gate：无真实写入 Gate；Task 7 独立 Review；Task 8 独立 Evidence Review

### Task Matrix

| Task | Lane | Model | Reasoning | Session | Plan | Integration Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Exact protocol/contracts | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | focused tests + self-review |
| 2 causal event seams | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | source parity + temporal review |
| 3 relationship engine | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | segment/leakage review |
| 4 active60 cross-symbol | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | no silent drop + source parity |
| 5 temporal dossier | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | exact baseline/OOS boundary |
| 6 orchestration + CLI | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | CLI readonly + composition |
| 7 cumulative review | Lane 1 | Sol | 高 | 新独立 Review | Review-only | Critical=0 / Important=0 |
| 8 real evidence | Lane 1 | Sol | 高 | 新研究 + Review | Plan-then-execute | Evidence C0/I0 |

### Worktree lifecycle

Tasks 1–6：

```text
latest develop
→ new task branch/worktree
→ TDD
→ focused verification
→ self-review / required domain review
→ task branch → develop
→ read back ancestry
→ cleanup task worktree/merged branch
```

Task 7：

```text
clean develop
→ independent Review worktree/session
→ fix only if finding is in scope
→ Critical=0 / Important=0
```

Task 8：

```text
exact accepted develop
→ evidence branch/worktree
→ run exact read-only CLI
→ deterministic rerun
→ Evidence Review
→ docs/status closeout
→ develop
→ cleanup
```

任何步骤都不得触碰 `main`、tag、Runtime 或真实通知。

---

# Task 1 — Exact Robustness Protocol and Immutable Contracts

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从最新 `develop` 创建 `research/multi-candidate-robustness-v1-contracts`
- 人工 Gate：无；测试与自审通过后允许集成 develop

**Files:**
- Create `data/research_protocols/multi_candidate_robustness_v1.json`
- Create `services/quant-api/app/market_data/multi_candidate_robustness_policy.py`
- Create `services/quant-api/app/market_data/multi_candidate_robustness.py`
- Create `services/quant-api/tests/test_multi_candidate_robustness_policy.py`
- Create `services/quant-api/tests/test_multi_candidate_robustness.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class RobustnessCandidateRef:
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    candidate_protocol_id: str
    baseline_request_through: date
    source_event_kind: str
    evaluable_unit: str
    horizon_semantics: str

@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    frozen_at: datetime
    anchor_symbol: str
    candidates: tuple[RobustnessCandidateRef, ...]
    common_since: date
    common_through: date
    cross_symbol_products: tuple[str, ...]
    event_proximity_bars: tuple[int, ...]
    parameter_perturbation: bool
    automatic_ranking: bool
    automatic_promotion: bool

@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessRequest:
    protocol_id: str
```

Also define the exact immutable report types from Spec §§10–14 in `multi_candidate_robustness.py`.

- [ ] **Step 1: Create isolated task worktree**

```bash
git fetch origin develop
git worktree add ../guiyi-mcr-v1-contracts \
  -b research/multi-candidate-robustness-v1-contracts origin/develop
cd ../guiyi-mcr-v1-contracts
git status --short
```

Expected: clean worktree.

- [ ] **Step 2: Write RED exact protocol tests**

```python
def test_load_exact_multi_candidate_robustness_protocol() -> None:
    protocol = load_multi_candidate_robustness_protocol()
    assert protocol.protocol_id == "multi_candidate_robustness_v1"
    assert protocol.anchor_symbol == "jm"
    assert protocol.common_since == date(2023, 1, 1)
    assert protocol.common_through == date(2026, 8, 18)
    assert protocol.event_proximity_bars == (3, 5, 8)
    assert len(protocol.cross_symbol_products) == 60
    assert protocol.cross_symbol_products[22] == "jm"
    assert protocol.parameter_perturbation is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False
    assert tuple(ref.candidate_id for ref in protocol.candidates) == (
        "subing_lifecycle_v2_candidate_v1",
        "n_structure_5m_candidate_v1",
    )
```

Add parameterized mutations for every top-level/nested missing key, extra key, wrong type, wrong candidate order, wrong product order, duplicate product, wrong date and any `true` safety flag. Every mutation must raise `MULTI_CANDIDATE_PROTOCOL_INVALID`.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py
```

Expected: import/file failure.

- [ ] **Step 4: Create exact JSON and strict loader**

Copy Spec §5 payload byte-for-byte. Loader must compare exact nested key/type/value shape before constructing frozen objects; do not accept env overrides or defaults.

Core validation must include:

```python
if tuple(raw["event_proximity_bars"]) != (3, 5, 8):
    raise MultiCandidateRobustnessProtocolError()
if raw["parameter_perturbation"] is not False:
    raise MultiCandidateRobustnessProtocolError()
if raw["automatic_ranking"] is not False:
    raise MultiCandidateRobustnessProtocolError()
if raw["automatic_promotion"] is not False:
    raise MultiCandidateRobustnessProtocolError()
```

- [ ] **Step 5: Write RED report contract tests**

Construct one valid minimal `MultiCandidateRobustnessReport`, then mutate:

```python
def test_report_rejects_forbidden_quality_or_identity_drift() -> None:
    report = valid_report()
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(report, protocol_id="other")
```

Validate exact candidate order, relationship order, exact 120 cross-symbol cells, Decimal-only metrics and the absence of strategy-decision fields from the dataclass surface.

- [ ] **Step 6: Implement immutable contracts and GREEN**

`CandidateSymbolRobustness` must enforce:

```python
if status is CandidateSymbolStatus.AVAILABLE:
    if reason_code is not None or event_count is None or evaluable_count is None:
        raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
else:
    if reason_code is None or event_count is not None or evaluable_count is not None:
        raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
```

All mappings are copied then wrapped with `MappingProxyType`; all tuples are re-materialized.

- [ ] **Step 7: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_robustness.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/multi_candidate_robustness_policy.py \
  services/quant-api/app/market_data/multi_candidate_robustness.py \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_robustness.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Commit only Task 1 files:

```bash
git add data/research_protocols/multi_candidate_robustness_v1.json \
  services/quant-api/app/market_data/multi_candidate_robustness_policy.py \
  services/quant-api/app/market_data/multi_candidate_robustness.py \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_robustness.py
git commit -m 'feat(research): freeze multi-candidate robustness v1'
```

---

# Task 2 — Additive Causal Event Projection Seams

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：从完成 Task 1 后的最新 `develop` 创建新 task worktree
- 人工 Gate：temporal/source parity Review

**Files:**
- Modify `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Modify `services/quant-api/app/market_data/n_structure_research_service.py`
- Create `services/quant-api/app/market_data/multi_candidate_events.py`
- Modify `services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py`
- Modify `services/quant-api/tests/data_foundation/test_n_structure_research_service.py`
- Create `services/quant-api/tests/test_multi_candidate_events.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class SubingLifecycleEntryResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: SubingDirection
    opportunity_key: SubingOpportunityKey
    confirmation_source: ConfirmationSource

@dataclass(frozen=True, slots=True)
class NStructureCompletionResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: NDirection
```

and:

```python
SubingLifecycleResearchService.entry_events(request)
NStructureResearchService.completion_events(request)
```

- [ ] **Step 1: Write RED SuBing event projection fixture**

Use an existing lifecycle fixture that produces one `ENTRY_CONFIRMED`. Assert:

```python
events = service.entry_events(request)
assert len(events) == 1
assert events[0].event_id == expected_transition.transition_id
assert events[0].observed_at == expected_transition.transition_at
assert events[0].contract == expected_transition.opportunity_key.contract
assert events[0].segment_start_trading_day == (
    expected_transition.opportunity_key.segment_start_trading_day
)
assert events[0].segment_bar_index == expected_5m_index
```

Also assert SETUP/TRIGGER/CONTINUATION/CLOSED transitions are not projected.

- [ ] **Step 2: Write RED N event projection fixture**

```python
events = service.completion_events(request)
assert tuple(event.event_id for event in events) == tuple(
    pattern.n_id for pattern in expected_patterns
)
assert tuple(event.observed_at for event in events) == tuple(
    pattern.completed_at for pattern in expected_patterns
)
```

Assert direction, contract, segment start, trading day and segment bar index exactly map to the existing completion bar.

- [ ] **Step 3: Write RED aggregate zero-regression tests**

For each source service:

```python
before = frozen_expected_payload(existing_run_result)
after = frozen_expected_payload(service.run(request))
assert after == before
```

Use the existing fixture’s full aggregate fields, not only event count.

- [ ] **Step 4: Refactor SuBing to one internal projection pass**

Introduce an internal frozen result container:

```python
@dataclass(frozen=True, slots=True)
class _SubingResearchProjection:
    result: SubingLifecycleResearchResult
    entry_events: tuple[SubingLifecycleEntryResearchEvent, ...]
```

`run()` becomes:

```python
def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult:
    return self._project(request).result


def entry_events(
    self, request: LifecycleResearchRequest
) -> tuple[SubingLifecycleEntryResearchEvent, ...]:
    return self._project(request).entry_events
```

Inside the existing snapshot loop, obtain the exact unique entry transition:

```python
entry_transitions = tuple(
    transition
    for transition in boundary_transitions
    if transition.to_stage is LifecycleStage.ENTRY_CONFIRMED
)
if len(entry_transitions) > 1:
    raise ValueError("multiple entry transitions on one lifecycle boundary")
```

When one exists, append its existing identity and current `bar_index[observed_at]`; do not re-evaluate the signal.

- [ ] **Step 5: Refactor N to one internal projection pass**

Use the same pattern:

```python
@dataclass(frozen=True, slots=True)
class _NStructureResearchProjection:
    result: NStructureResearchResult
    completion_events: tuple[NStructureCompletionResearchEvent, ...]
```

Append a completion event inside the existing `for pattern in patterns.patterns` branch only after the existing requested-window and bar-alignment checks pass.

- [ ] **Step 6: Implement generic adapters**

In `multi_candidate_events.py`:

```python
def from_subing_entry(
    event: SubingLifecycleEntryResearchEvent,
) -> CandidateResearchEvent:
    return CandidateResearchEvent(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        source_kind="subing_lifecycle",
        source_event_kind="entry_confirmed",
        source_event_id=event.event_id,
        symbol=event.symbol,
        contract=event.contract,
        segment_start_trading_day=event.segment_start_trading_day,
        observed_at=event.observed_at,
        trading_day=event.trading_day,
        segment_bar_index=event.segment_bar_index,
        direction=(
            CandidateResearchDirection.LONG
            if event.direction is SubingDirection.LONG
            else CandidateResearchDirection.SHORT
        ),
    )
```

Implement the N adapter symmetrically: UP→LONG, DOWN→SHORT.

- [ ] **Step 7: Add prefix/window/segment regression**

For both services verify:

```text
same rank1 segment + longer future suffix
→ all prior projected event identities unchanged

requested through cut
→ no event whose trading_day is after through
```

- [ ] **Step 8: Run verification and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_n_structure_research_service.py \
  services/quant-api/tests/test_multi_candidate_events.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/subing_lifecycle_research_service.py \
  services/quant-api/app/market_data/n_structure_research_service.py \
  services/quant-api/app/market_data/multi_candidate_events.py

git diff --check
```

Review must explicitly state: no SuBing/N formula change, no event identity duplication, no lookahead, aggregate parity preserved.

---

# Task 3 — Candidate Event Relationship / Overlap Engine

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree from latest develop
- 人工 Gate：segment/leakage independent review

**Files:**
- Modify `services/quant-api/app/market_data/multi_candidate_events.py`
- Modify `services/quant-api/tests/test_multi_candidate_events.py`
- Modify `services/quant-api/app/market_data/multi_candidate_robustness.py`
- Modify `services/quant-api/tests/test_multi_candidate_robustness.py`

**Produces:**

```python
def summarize_candidate_relationship(
    source_events: Sequence[CandidateResearchEvent],
    target_events: Sequence[CandidateResearchEvent],
    *,
    proximity_bars: tuple[int, int, int],
) -> CandidateRelationshipSummary
```

- [ ] **Step 1: RED exact boundary pair-count tests**

Create events in the same segment/bar:

```text
source LONG × 2
target LONG × 2
target SHORT × 1
```

Assert:

```python
assert summary.exact_same_direction_count == 4
assert summary.exact_opposite_direction_count == 2
```

These are **event-pair counts**, not source coverage counts.

- [ ] **Step 2: RED nearest distance and tie test**

Source at index 100; same-direction targets at 97 and 103. Assert earlier-first:

```python
assert selected.segment_bar_index == 97
assert signed_distance == -3
```

With two targets at 97, use lexicographically smaller `source_event_id`.

- [ ] **Step 3: RED cross-contract/cross-segment isolation**

A target one bar away but on another physical contract or another segment start must never match. Assert all within counts remain zero.

- [ ] **Step 4: RED nested 3/5/8 source coverage**

For source nearest distances `[0, 2, 4, 7, 9, no_match]` assert:

```python
assert summary.within_3_same_direction_source_count == 2
assert summary.within_5_same_direction_source_count == 3
assert summary.within_8_same_direction_source_count == 4
assert summary.nearest_match_count_within_8 == 4
```

- [ ] **Step 5: RED signed direction/day-span counts**

For nearest relationships within 8, assert exact counts for target earlier/same/later and same-day/cross-day.

- [ ] **Step 6: Implement deterministic index**

Group targets by:

```python
(symbol, contract, segment_start_trading_day, direction)
```

and sort each bucket by:

```python
(segment_bar_index, source_event_id)
```

Use `bisect_left` over bar indexes. Candidate selection must use:

```python
key = (
    abs(target.segment_bar_index - source.segment_bar_index),
    target.segment_bar_index,
    target.source_event_id,
)
```

Signed distance is computed only after selecting the minimum key.

- [ ] **Step 7: Implement exact pair counts separately**

Index target pair counts by `(symbol, contract, segment_start, bar_index, direction)`. For each source event add the count at same direction to `exact_same_direction_count` and opposite direction to `exact_opposite_direction_count`.

Do not derive exact counts from nearest matching.

- [ ] **Step 8: Guard against ranking semantics**

Test module/report payload names for forbidden tokens:

```python
FORBIDDEN = {
    "score", "rank", "winner", "better_candidate",
    "keep", "drop", "promote", "profitability", "expected_profit",
}
assert FORBIDDEN.isdisjoint(exported_report_keys())
```

- [ ] **Step 9: Verify and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/multi_candidate_events.py \
  services/quant-api/app/market_data/multi_candidate_robustness.py

git diff --check
```

Review focus: no future-trigger semantics, no cross-segment leakage, deterministic tie, pair-count vs source-coverage units explicit.

---

# Task 4 — Frozen Active60 Cross-Symbol Robustness

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree
- 人工 Gate：source identity / no-silent-drop review

**Files:**
- Create `services/quant-api/app/market_data/multi_candidate_robustness_service.py`
- Modify `services/quant-api/app/market_data/multi_candidate_robustness.py`
- Create `services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py`
- Modify `services/quant-api/tests/test_multi_candidate_robustness.py`

**Consumes:** exact Protocol, existing SuBing/N `run()` source methods.

**Produces internal method:**

```python
MultiCandidateRobustnessService._cross_symbol_results()
```

- [ ] **Step 1: RED exact 60 matrix test**

Build fake source runners for all 60 protocol products. Assert:

```python
results, summaries = service._cross_symbol_results()
assert len(results) == 120
assert tuple((r.candidate_id, r.symbol) for r in results[:60]) == tuple(
    ("subing_lifecycle_v2_candidate_v1", symbol)
    for symbol in protocol.cross_symbol_products
)
assert tuple((r.candidate_id, r.symbol) for r in results[60:]) == tuple(
    ("n_structure_5m_candidate_v1", symbol)
    for symbol in protocol.cross_symbol_products
)
```

- [ ] **Step 2: RED source request boundary test**

Fake runners capture every request. Assert every request is exactly:

```text
since   = 2023-01-01
through = 2026-08-18
symbol  = current frozen product
```

No runtime date may enter the request.

- [ ] **Step 3: RED normalization tests**

SuBing:

```python
assert row.event_count == source.funnel_counts["ENTRY_CONFIRMED"]
assert row.evaluable_count == source.evaluable_boundary_count
assert row.evaluable_unit == "5m_ready_boundary"
assert row.horizon_semantics == "same_trading_day_only"
```

N:

```python
assert row.event_count == sum(source.completed_n_counts.values())
assert row.evaluable_count == source.evaluable_bar_count
assert row.evaluable_unit == "5m_canonical_bar"
assert row.horizon_semantics == "same_rank1_segment"
```

- [ ] **Step 4: RED exact Decimal event-rate test**

```python
assert row.event_rate_per_1000_evaluable == (
    Decimal(row.event_count) * Decimal(1000) / Decimal(row.evaluable_count)
)
```

For `evaluable_count=0`, status remains `available`, event rate is `None`.

- [ ] **Step 5: RED unavailable and zero-event distinction**

Make one source runner raise its stable unavailable error and another return a valid zero-event result. Assert both symbols remain present:

```python
assert unavailable.status.value == "unavailable"
assert unavailable.reason_code == "MULTI_CANDIDATE_SOURCE_UNAVAILABLE"
assert zero_event.status.value == "available"
assert zero_event.event_count == 0
```

No exception text/stack/provider details may be exposed.

- [ ] **Step 6: RED candidate summary sign counts**

For controlled per-symbol medians `[-1, 0, +1, None]`, assert positive/zero/negative/sample counts exactly. Event-rate min/median/max must use available non-null rates only, while `product_count` stays 60.

- [ ] **Step 7: Implement sequential collector**

Iterate candidates in protocol order, then products in frozen order. Do not introduce thread/process pools.

The source identity check is exact:

```python
if source.products != (symbol,):
    raise MultiCandidateRobustnessSourceError()
```

Typed source failures become explicit unavailable rows; identity mismatch fails the entire run because it is contract corruption, not a missing sample.

- [ ] **Step 8: Preserve common horizon semantics**

Map only directional return/MFE/MAE to `CommonPriceHorizonSummary`; never copy SuBing EMA21 into the common metric. Validate horizon keys `(3, 5, 8)` exact.

- [ ] **Step 9: Verify and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/multi_candidate_robustness.py \
  services/quant-api/app/market_data/multi_candidate_robustness_service.py

git diff --check
```

---

# Task 5 — Anchor `jm` Temporal Dossier via Existing Candidate Validation

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree
- 人工 Gate：exact baseline/OOS boundary review

**Files:**
- Modify `services/quant-api/app/market_data/multi_candidate_robustness.py`
- Modify `services/quant-api/app/market_data/multi_candidate_robustness_service.py`
- Modify `services/quant-api/tests/test_multi_candidate_robustness.py`
- Modify `services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py`

**Consumes:** existing `SubingCandidateValidationService` and `NStructureCandidateValidationService` runners.

- [ ] **Step 1: RED exact baseline request-through tests**

Capture requests and assert:

```python
assert subing_request == CandidateValidationRequest(
    candidate_id="subing_lifecycle_v2_candidate_v1",
    protocol_id="candidate_validation_v1",
    symbol="jm",
    through=date(2026, 8, 19),
)
assert n_request == CandidateValidationRequest(
    candidate_id="n_structure_5m_candidate_v1",
    protocol_id="n_structure_validation_v1",
    symbol="jm",
    through=date(2026, 8, 20),
)
```

- [ ] **Step 2: RED candidate identity and fold identity checks**

A fake report with wrong candidate/protocol, fewer than 10 folds, duplicate fold id, or unexpected fold dates must raise `MULTI_CANDIDATE_BASELINE_INVALID`.

The expected fold schedule is derived from the existing source reports and must match the frozen 12m/3m/3m schedule ending 2026Q2; do not create another calendar generator in this module.

- [ ] **Step 3: RED event-count normalization**

SuBing dossier:

```python
retrospective_event_count = report.retrospective.funnel_counts["ENTRY_CONFIRMED"]
test_counts = [fold.test.funnel_counts["ENTRY_CONFIRMED"] for fold in report.rolling_folds]
```

N dossier:

```python
retrospective_event_count = sum(report.retrospective.completed_n_counts.values())
test_counts = [sum(fold.test.completed_n_counts.values()) for fold in report.rolling_folds]
```

Assert min/median/max/folds-with-events exactly.

- [ ] **Step 4: RED prospective preservation**

Assert output preserves source-specific:

```text
SuBing first = 2026-08-20
N first      = 2026-08-21
```

and both baseline requests remain `pending`; no robustness code may convert them to evaluated.

- [ ] **Step 5: Implement temporal projection**

Use a shared exact Decimal median helper for event counts:

```python
def _decimal_median(values: Sequence[int]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[mid])
    return (Decimal(ordered[mid - 1]) + Decimal(ordered[mid])) / Decimal(2)
```

Preserve `source_quality_flags` without interpreting them as strategy quality.

- [ ] **Step 6: Add horizon common projection**

Project only common price metrics and keep each dossier’s `horizon_semantics` field from exact protocol candidate ref.

- [ ] **Step 7: Verify and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/test_n_candidate_validation.py

git diff --check
```

Review must explicitly state: no second rolling engine, no OOS relabel, exact baseline request dates preserved.

---

# Task 6 — Orchestrator, Composition and Read-only CLI

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Terra
- 推理强度：中
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree
- 人工 Gate：无；CLI/composition tests pass 后可集成 develop

**Files:**
- Modify `services/quant-api/app/market_data/multi_candidate_robustness_service.py`
- Modify `services/quant-api/app/market_data/composition.py`
- Modify `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify `services/quant-api/app/guiyi_cli/main.py`
- Modify `services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py`
- Modify `services/quant-api/tests/test_research_cli.py`

**Produces:**

```text
guiyi research candidate-robustness \
  --protocol multi_candidate_robustness_v1
```

- [ ] **Step 1: RED final orchestration test**

With fake dependencies, run:

```python
report = service.run(MultiCandidateRobustnessRequest("multi_candidate_robustness_v1"))
```

Assert:

```python
assert report.anchor_symbol == "jm"
assert report.common_since == date(2023, 1, 1)
assert report.common_through == date(2026, 8, 18)
assert len(report.temporal_dossiers) == 2
assert len(report.cross_symbol_results) == 120
assert len(report.cross_symbol_summaries) == 2
assert tuple((r.source_candidate_id, r.target_candidate_id) for r in report.relationships) == (
    ("subing_lifecycle_v2_candidate_v1", "n_structure_5m_candidate_v1"),
    ("n_structure_5m_candidate_v1", "subing_lifecycle_v2_candidate_v1"),
)
```

- [ ] **Step 2: RED active-universe drift test**

Inject current active products missing one frozen symbol. Service construction or run must raise `MULTI_CANDIDATE_ACTIVE_UNIVERSE_DRIFT`; do not silently substitute the current list.

- [ ] **Step 3: Implement final `run()`**

Execution order is deterministic:

```text
1. validate request/protocol/current active set
2. build temporal dossiers
3. build cross-symbol matrix and summaries
4. collect jm source events on common window
5. normalize events
6. build SuBing→N relationship
7. build N→SuBing relationship
8. derive structural quality flags
9. construct immutable report
```

Quality flags are structural only; `SYMBOL_WITHOUT_EVENT` is present if any available row has zero events, and `CROSS_SYMBOL_SOURCE_UNAVAILABLE` if any row is unavailable.

- [ ] **Step 4: Build dedicated exact composition**

Add:

```python
def build_multi_candidate_robustness_service(
    session: Session,
) -> MultiCandidateRobustnessService:
```

Load exact robustness protocol first. Validate `load_active_products()` tuple exactly equals protocol frozen products.

Construct one `MarketDataService`, then source services with `products=protocol.cross_symbol_products`, not dynamic product substitution.

Construct exact Candidate Validation runners from those source services plus existing strict candidate/protocol loaders. Do not add a registry/plugin.

- [ ] **Step 5: RED CLI parser test**

Valid:

```text
guiyi research candidate-robustness --protocol multi_candidate_robustness_v1
```

Invalid and exit 2:

```text
--since
--through
--symbol
--candidate
--products
```

No run-time cherry-pick flags are accepted.

- [ ] **Step 6: Add request and dispatch**

`ResearchRequest` union adds `MultiCandidateRobustnessRequest`.

`build_research_request()`:

```python
if args.research_command == "candidate-robustness":
    return MultiCandidateRobustnessRequest(protocol_id=args.protocol)
```

`main()` gets a dedicated `multi_candidate_robustness_service_factory` and routes only this request to it.

- [ ] **Step 7: Add deterministic JSON renderer**

Top-level keys fixed in this order:

```text
schema_version
command
status
readonly
research_only
protocol_id
frozen_at
anchor_symbol
common_retrospective
temporal_dossiers
cross_symbol_results
cross_symbol_summaries
relationships
metric_compatibility_flags
quality_flags
```

`command="research.candidate-robustness"`, `readonly=true`, `research_only=true`.

Serialize Decimal as strings using existing CLI Decimal helpers; no float.

- [ ] **Step 8: CLI forbidden-key test**

Recursively inspect payload keys and reject any normalized key in:

```python
{
    "score", "rank", "winner", "better_candidate",
    "keep", "drop", "promote", "profitability", "expected_profit",
}
```

- [ ] **Step 9: Verify and integrate**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_research_cli.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

---

# Task 7 — Cumulative Temporal / Parity Verification and Independent Review

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开独立 Review 会话
- Plan：Review-only；只有 finding 才修改
- 工作区：clean `develop` review worktree
- 人工 Gate：独立 Review `Critical=0 / Important=0`

**Files:**
- Modify `TESTING.md`
- Fix implementation/tests only if Review identifies a concrete in-scope issue

- [ ] **Step 1: Create clean review worktree at exact develop**

```bash
git fetch origin develop
git worktree add --detach ../guiyi-mcr-v1-review origin/develop
cd ../guiyi-mcr-v1-review
git status --short
git rev-parse HEAD
```

Record the exact reviewed SHA.

- [ ] **Step 2: Run new focused suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 3: Run N full-chain regression**

Use the exact N Structure V1 command block already in `TESTING.md`, including:

```text
test_n_structure_policy.py
test_n_structure_swing.py
test_n_structure_pattern.py
test_n_structure_state.py
test_n_structure_segment.py
test_actual_dominant_research.py
test_price_outcome.py
test_n_structure_research_service.py
test_candidate_validation_schedule.py
test_n_candidate_validation_policy.py
test_n_candidate_validation.py
test_n_candidate_validation_service.py
test_research_cli.py
```

- [ ] **Step 4: Run SuBing zero-regression**

Use the exact current `TESTING.md` SuBing zero-regression block. No test may be removed merely to make robustness pass.

- [ ] **Step 5: Run static/security checks**

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

- [ ] **Step 6: Independent Review checklist**

Reviewer must explicitly inspect:

```text
1. no SuBing/N formula or exact policy drift
2. source events use existing immutable identities
3. no lookahead/executable trigger semantics
4. no cross-contract/segment relationship
5. exact pair-count vs source-coverage units
6. exact frozen 60; unavailable not dropped
7. common window fixed to 2026-08-18
8. baseline request-through fixed to historical baseline
9. outcome horizon semantics preserved
10. no hidden parameter sweep/rank/promotion
11. no Data Foundation/Alert/Runtime boundary change
12. deterministic ordering
```

Severity Gate:

```text
Critical = 0
Important = 0
```

- [ ] **Step 7: Update `TESTING.md` only after commands are verified**

Add a `Multi-Candidate Robustness V1` section containing the exact focused command and read-only semantics. Do not duplicate unrelated project verification text.

- [ ] **Step 8: Integrate any review fixes and re-run affected gates**

If fixes are required, use a task branch from the reviewed develop SHA, apply only findings, rerun affected focused + upstream regression, then integrate to develop. Final accepted SHA must be read back from `origin/develop`.

---

# Task 8 — Exact-develop Real Evidence, Evidence Review and Closeout

## Codex 调度建议

- 任务车道：Lane 1
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新研究会话 + 新独立 Evidence Review 会话
- Plan：Plan-then-execute
- 工作区：从 Task 7 accepted exact `develop` 创建独立 evidence worktree/branch
- 人工 Gate：Evidence Review `Critical=0 / Important=0`

**Files:**
- Create `reports/research/candidate_robustness/multi_candidate_robustness_v1/anchor-jm-active60-retrospective-freeze-2026-08-20.json`
- Modify `STATUS.md`
- Modify `docs/ARCHITECTURE.md`
- Modify `PROJECT_SOURCE.md`
- Modify `TESTING.md` only if evidence reveals an exact command clarification

- [ ] **Step 1: Freeze exact evidence source SHA**

```bash
git fetch origin develop
git worktree add ../guiyi-mcr-v1-evidence \
  -b research/multi-candidate-robustness-v1-evidence origin/develop
cd ../guiyi-mcr-v1-evidence
git status --short
git rev-parse HEAD
```

Do not proceed from dirty or moving source.

- [ ] **Step 2: Recompute the two tracked baseline payloads first**

SuBing:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate subing_lifecycle_v2_candidate_v1 \
  --protocol candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-19 \
  > /tmp/guiyi-subing-baseline.json

cmp /tmp/guiyi-subing-baseline.json \
  reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-19.json
```

In the actual shell command, keep the report path on one line after the backslash continuation.

N:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate n_structure_5m_candidate_v1 \
  --protocol n_structure_validation_v1 \
  --symbol jm \
  --through 2026-08-20 \
  > /tmp/guiyi-n-baseline.json

cmp /tmp/guiyi-n-baseline.json \
  reports/research/candidate_validation/n_structure_5m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-20.json
```

Any mismatch blocks evidence generation; do not “update baseline” in this task.

- [ ] **Step 3: Run exact robustness command**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-robustness \
  --protocol multi_candidate_robustness_v1 \
  > /tmp/guiyi-multi-candidate-robustness-v1.json
```

This command is read-only Historical research.

- [ ] **Step 4: Validate artifact identity before tracking**

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path('/tmp/guiyi-multi-candidate-robustness-v1.json')
data = json.loads(p.read_text())
assert data['command'] == 'research.candidate-robustness'
assert data['readonly'] is True
assert data['research_only'] is True
assert data['protocol_id'] == 'multi_candidate_robustness_v1'
assert data['anchor_symbol'] == 'jm'
assert data['common_retrospective'] == {
    'since': '2023-01-01',
    'through': '2026-08-18',
}
assert len(data['temporal_dossiers']) == 2
assert len(data['cross_symbol_results']) == 120
assert len(data['cross_symbol_summaries']) == 2
assert len(data['relationships']) == 2
forbidden = {
    'score', 'rank', 'winner', 'better_candidate',
    'keep', 'drop', 'promote', 'profitability', 'expected_profit',
}

def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in forbidden
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
walk(data)
PY
```

- [ ] **Step 5: Track exact artifact**

```bash
mkdir -p reports/research/candidate_robustness/multi_candidate_robustness_v1
cp /tmp/guiyi-multi-candidate-robustness-v1.json \
  reports/research/candidate_robustness/multi_candidate_robustness_v1/
  anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

Use a single shell line for the destination path in actual execution.

- [ ] **Step 6: Determinism rerun**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-robustness \
  --protocol multi_candidate_robustness_v1 \
  > /tmp/guiyi-multi-candidate-robustness-v1-rerun.json

cmp /tmp/guiyi-multi-candidate-robustness-v1.json \
  /tmp/guiyi-multi-candidate-robustness-v1-rerun.json
shasum -a 256 /tmp/guiyi-multi-candidate-robustness-v1.json
```

Record byte size and SHA-256 in `STATUS.md` only after `cmp` succeeds.

- [ ] **Step 7: Independent Evidence Review**

Reviewer checks exact artifact, not narrative summary:

```text
protocol identity exact
candidate identities exact
frozen 60 exact order
120 matrix cells
common window exact
anchor jm exact
source-specific baseline dates exact
both relationship directions present
metric compatibility flags present
prospective statuses are candidate-specific baseline facts
no OOS backfill
no hidden unavailable symbol drop
no forbidden rank/decision/profit fields
rerun byte-identical
```

Gate:

```text
Critical = 0
Important = 0
```

- [ ] **Step 8: Close canonical documentation**

`STATUS.md` records code/test/evidence state and no strategy-validity claim.

`PROJECT_SOURCE.md` adds `guiyi research candidate-robustness` to current read-only interface and states it compares frozen Candidate research facts only.

`docs/ARCHITECTURE.md` adds the layer:

```text
SuBing Candidate ─┐
                  ├─ Multi-Candidate Robustness V1 → versioned evidence
N Candidate ──────┘
```

No `DECISIONS.md` update unless implementation introduced a new long-term architectural decision beyond this Spec.

- [ ] **Step 9: Final tracked checks and commit**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check

git add \
  reports/research/candidate_robustness/multi_candidate_robustness_v1/anchor-jm-active60-retrospective-freeze-2026-08-20.json \
  STATUS.md docs/ARCHITECTURE.md PROJECT_SOURCE.md TESTING.md

git commit -m 'research: add multi-candidate robustness v1 evidence'
```

Only add `TESTING.md` if it changed in this evidence task.

- [ ] **Step 10: Integrate develop and cleanup**

After Evidence Review C0/I0:

```text
evidence branch → develop
read back origin/develop contains evidence commit
cleanup evidence worktree/merged branch
```

Do not release `main`, create tag, switch Runtime, change Alert/Scope, send notifications, or write DB/Canonical/Redis.

---

## Final Acceptance Criteria

Phase 5 V1 is complete only if all are true:

```text
[ ] exact multi_candidate_robustness_v1 Protocol exists
[ ] exact two Candidate identities unchanged
[ ] source aggregate payloads retain zero-regression
[ ] causal source event seams exist and are prefix-stable
[ ] jm relationships are same-contract/same-segment only
[ ] exact pair-count and 3/5/8 source-coverage units are explicit
[ ] frozen active60 produces exactly 120 retained result cells
[ ] unavailable/zero-event symbols are distinguished
[ ] horizon semantics stay source-specific
[ ] anchor temporal dossier reuses existing Candidate Validation
[ ] no new OOS protocol/backfill exists
[ ] read-only candidate-robustness CLI exists
[ ] cumulative N/SuBing regressions pass
[ ] implementation Review Critical=0 / Important=0
[ ] two tracked baseline artifacts reproduce byte-identically
[ ] robustness evidence reruns byte-identically
[ ] Evidence Review Critical=0 / Important=0
[ ] STATUS/ARCHITECTURE/PROJECT_SOURCE/TESTING reflect exact state
[ ] no decision/rank/profit/promotion claim exists
[ ] no main/tag/Runtime/Alert/DB/Canonical mutation occurred
```

Final allowed statement:

```text
Multi-Candidate Research & Robustness V1 已形成可复算的 retrospective robustness dossier；
它描述两个 frozen Candidate 的 temporal、active60 cross-symbol 与 jm event relationship；
prospective OOS 仍由各 Candidate exact Protocol 独立累积。
```

Final forbidden statement:

```text
SuBing/N 谁更好
某 Candidate 有效/盈利
允许 KEEP/DROP/PROMOTE
允许第三条 Alert
允许 main/tag release
允许 Runtime promotion
```
