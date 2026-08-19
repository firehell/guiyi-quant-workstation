# Candidate Validation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 SuBing V1/V2 公式、Alert、Scope、Runtime 与 Data Foundation 的前提下，建立首个 research-only Candidate Validation V1：把现有 SuBing Lifecycle Shadow 组织为 retrospective baseline、10-fold rolling historical stability、严格冻结边界后的 prospective OOS，并生成版本化 `jm` Candidate evidence report。

**Architecture:** V1 不重建 backtest engine，也不引入 Strategy plugin/registry。它新增两个 exact Git-tracked artifact（Candidate Manifest + Validation Protocol）、不可变 validation report contracts，以及一个只依赖现有 `SubingLifecycleResearchService` 的 SuBing Candidate adapter；所有窗口继续由现有 Shadow service 经 `MarketDataService` 读取 Historical Canonical。CLI 只输出 stdout JSON，首份 evidence 通过 shell redirection 保存为 Git-tracked report；任何 KEEP/DROP/PROMOTE 都留给人工 Review。

**Tech Stack:** Python 3.13、dataclasses、Decimal、FastAPI 项目既有 composition/CLI、现有 `SubingLifecycleResearchService` / `MarketDataService`、pytest、Ruff、Mypy、JSON artifacts。

**Spec:** `docs/superpowers/specs/2026-08-19-candidate-validation-v1-design.md`

## Global Constraints

- 每个 Task 开始前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec、上游 `2026-08-19-subing-lifecycle-v2-design.md` 与本 Plan；若 active canonical 已改变，先停止并重新评估。
- SuBing V1 的 Factor、Signal、accepted Calibration、same-boundary resolver、`subing_entry_signal_v1`、Alert Rule/Scope/Runtime/Clawbot 零变化。
- SuBing Lifecycle V2 的 exact policy、formula、ConfirmedPivot/Breakout/Retest/lifecycle reducer 零变化；本计划只消费 existing Historical Shadow 结果。
- 首个 Candidate 精确为 `subing_lifecycle_v2_candidate_v1`，引用 `subing_lifecycle_v2_research_v1` / `subing_lifecycle_v2`；同 ID 内容漂移必须 fail-closed。
- Validation Protocol 精确为 `candidate_validation_v1`；Candidate validation freeze 为 `2026-08-19T20:57:00+08:00`，第一 eligible prospective OOS trading day 为 `2026-08-20`。
- `2023-01-01..2026-08-18` 只能称为 `retrospective`；历史 rolling 只能称为 `rolling_historical_stability`，不得冒充 true OOS。
- rolling 固定为 12 calendar months reference + 3 calendar months test + 3 months step；第一 test 为 2024Q1，最后 test 为 2026Q2，共 10 folds；fold 内不得调参数、改 Policy 或生成新 Candidate。
- Validation service 必须只调用 existing `SubingLifecycleResearchService`；不得直接读 Parquet/RQData/Redis、不得创建第二套 rank1 resolver、不得复制 `build_outcomes_at()` 或 lifecycle reducer。
- 不新增 DB/migration、Canonical、Redis candidate state、worker、queue、scheduler、HTTP Candidate API、Web dashboard、Alert Rule、Scope、notification 或 Execution Review 自动入口。
- 不计算或命名账户收益、trade PnL、手续费后收益、equity curve、保证金收益；V1 只复用 3/5/8 Bar directional return / MFE / MAE / EMA21 failure 等 existing research outcomes。
- Report 不自动输出 `KEEP` / `DROP` / `PROMOTE` / `PASS_STRATEGY`；人工判断是 evidence 之后的独立 Gate。
- CLI 继续 `readonly=true` 且只写 stdout；版本化 report 只允许执行任务通过 shell redirection 写入仓库指定路径，不给 CLI 新增任意文件写能力。
- Tasks 1–5 只做仓库代码/测试，不运行真实 `jm` research；Task 6 只做 docs/review/integration；Task 7 才运行 exact-develop 的只读 Historical `jm` baseline；Task 8 只 Review evidence。
- 任一 Task 不授权 `main`、release/tag、Runtime switch/promotion、开发态 Runtime reload、Scope mutation、真实通知、production DB/Canonical 写入、RQData mutation 或订单。
- 所有 tracked 变更按 `TESTING.md` 运行适用验证，并运行 `python3 scripts/engineering/secret_scan.py --json` 与 `git diff --check`；任何必需检查失败时不得声明完成。

## Codex Task Dispatch Matrix

| Task | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Exact manifest/protocol + contracts | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 从最新 `develop` 新 task worktree | exact loader + contract tests |
| 2 Pure report projection | Lane 1 | Sol | 高 | 继续 Task 1 或新会话 | Plan-then-execute | 同 implementation worktree | no duplicated research math |
| 3 SuBing validation orchestration | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 同 implementation worktree | temporal/leakage tests |
| 4 Read-only CLI/composition | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 同 implementation worktree | CLI zero-side-effect regression |
| 5 Validation regression / causality suite | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 同 implementation worktree | all focused tests green |
| 6 Docs + independent implementation review | Lane 1 review | Sol | 高 | 新独立 Review 会话 | Review-only | implementation branch / read-only diff | Critical=0 / Important=0 |
| 7 `jm` exact-develop Evidence Baseline | Lane 1 | Sol | 高 | 新研究会话 | Plan-then-execute | 从已集成 develop 新 research worktree | exact JSON + source/read-only checks |
| 8 Evidence review + Phase 4B closeout | Lane 1 review | Sol | 高 | 新独立 Review 会话 | Review-only | evidence branch / read-only diff | evidence semantics accepted |

Lane 说明：本阶段涉及 OOS / walk-forward / temporal leakage，因此核心 validation semantics 使用 Lane 1 + Sol/high，而不是普通 Lane 2 工程。它没有交易撮合、成本、正式策略公式变化或 promotion，因此不升级为 Lane 3；若实现过程中出现对 SuBing 公式、成交时序、成本/PnL 或正式 Candidate promotion 的修改需求，立即停止并升级为独立 Lane 3 任务。

### Worktree / integration flow

Implementation：

```text
latest develop
→ research/candidate-validation-v1 task branch/worktree
→ Tasks 1–5
→ Task 6 independent review
→ Critical=0 / Important=0
→ integrate task branch → develop
→ read back develop ancestry
→ remove merged implementation worktree/branch
```

Evidence：

```text
post-integration exact develop
→ research/subing-candidate-v1-jm-baseline branch/worktree
→ Task 7 exact read-only run + tracked JSON report
→ Task 8 independent evidence review
→ integrate evidence branch → develop
→ remove merged evidence worktree/branch
```

任何时候都不得触及 `main`、release worktree、exact-tag Runtime worktree 或 production service state。

---

## File Structure

### Create in Tasks 1–5

- `data/research_candidates/subing_lifecycle_v2_candidate_v1.json` — exact Candidate semantic identity；不保存结果或 promotion 状态。
- `data/research_protocols/candidate_validation_v1.json` — exact freeze、retrospective、rolling 与 prospective OOS protocol。
- `services/quant-api/app/market_data/candidate_validation_policy.py` — strict loaders、immutable `CandidateManifest` / `CandidateValidationProtocol`。
- `services/quant-api/app/market_data/candidate_validation.py` — immutable window/fold/report contracts、pure stability projection、quality flags。
- `services/quant-api/app/market_data/subing_candidate_validation_service.py` — 只编排 existing `SubingLifecycleResearchService` 的 Candidate validation service。
- `services/quant-api/tests/test_candidate_validation_policy.py`
- `services/quant-api/tests/test_candidate_validation.py`
- `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`

### Modify in Tasks 1–5

- `services/quant-api/app/market_data/composition.py` — load exact artifacts and build candidate validation service by reusing existing lifecycle research service。
- `services/quant-api/app/guiyi_cli/research_parser.py` — add exact `candidate-validation` parser。
- `services/quant-api/app/guiyi_cli/research_commands.py` — request construction + JSON serialization；preserve both existing research payloads。
- `services/quant-api/app/guiyi_cli/main.py` — add exact third research factory dispatch，不改变 `data` / `runtime` / existing research behavior。
- `services/quant-api/tests/test_research_cli.py` — parser/dispatch/payload/readonly regression。

### Modify only in Task 6 after executable behavior is green

- `TESTING.md` — add exact Candidate Validation focused commands and read-only evidence command。
- `docs/ARCHITECTURE.md` — add Candidate Validation V1 as Historical research read-model over existing Lifecycle Shadow；不得描述成 backtest engine。
- `STATUS.md` — only after Task 6 review passes; record develop-only implementation, not evidence success / release / Runtime / strategy validity。

### Create only in Task 7

- `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json` — exact stdout from the read-only Candidate Validation command using `--through 2026-08-19`。

### Modify only in Task 8 if evidence truly exists and review passes

- `STATUS.md` — record exact evidence artifact identity and what it does/does not prove；不得 write `Ready` / `promoted` / `profitable`。

No API schema, Web file, DB model, migration, launchd, notification or Runtime config belongs to this plan.

---

### Task 1: Exact Candidate Manifest, Validation Protocol and Immutable Contracts

**Lane:** Lane 1 research semantics — Sol/high. New session. Plan-then-execute in a task worktree from latest `develop`.

**Files:**
- Create: `data/research_candidates/subing_lifecycle_v2_candidate_v1.json`
- Create: `data/research_protocols/candidate_validation_v1.json`
- Create: `services/quant-api/app/market_data/candidate_validation_policy.py`
- Create: `services/quant-api/tests/test_candidate_validation_policy.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_policy.py`
- Read: `data/research_policies/subing_lifecycle_v2_research_v1.json`

**Interfaces:**
- Consumes: existing exact SuBing lifecycle `policy_id=subing_lifecycle_v2_research_v1` / `formula_version=subing_lifecycle_v2`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CandidateManifest:
    schema_version: int
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    research_only: bool

@dataclass(frozen=True, slots=True)
class CandidateValidationProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    candidate_frozen_at: datetime
    retrospective_since: date
    retrospective_through: date
    reference_months: int
    test_months: int
    step_months: int
    first_test_since: date
    last_test_through: date
    prospective_oos_first_trading_day: date
    horizons_bars: tuple[int, ...]

def load_candidate_manifest(path: Path | None = None) -> CandidateManifest: ...
def load_candidate_validation_protocol(path: Path | None = None) -> CandidateValidationProtocol: ...
```

Stable errors:

```python
class CandidateManifestError(ValueError):
    code = "CANDIDATE_MANIFEST_INVALID"

class CandidateValidationProtocolError(ValueError):
    code = "CANDIDATE_VALIDATION_PROTOCOL_INVALID"
```

- [ ] **Step 1: Create isolated implementation workspace**

```bash
git fetch origin develop
git worktree add ../guiyi-candidate-validation-v1 \
  -b research/candidate-validation-v1 origin/develop
cd ../guiyi-candidate-validation-v1
git status --short
git log -5 --oneline --decorate
```

Expected: clean worktree at latest `origin/develop`.

- [ ] **Step 2: Write RED exact-loader tests**

Create tests covering:

```python
def test_load_exact_candidate_manifest() -> None:
    manifest = load_candidate_manifest()
    assert manifest == CandidateManifest(
        schema_version=1,
        candidate_id="subing_lifecycle_v2_candidate_v1",
        source_kind="subing_lifecycle",
        policy_id="subing_lifecycle_v2_research_v1",
        formula_version="subing_lifecycle_v2",
        research_only=True,
    )


def test_load_exact_validation_protocol() -> None:
    protocol = load_candidate_validation_protocol()
    assert protocol.protocol_id == "candidate_validation_v1"
    assert protocol.candidate_frozen_at.isoformat() == "2026-08-19T20:57:00+08:00"
    assert protocol.retrospective_since == date(2023, 1, 1)
    assert protocol.retrospective_through == date(2026, 8, 18)
    assert protocol.reference_months == 12
    assert protocol.test_months == 3
    assert protocol.step_months == 3
    assert protocol.first_test_since == date(2024, 1, 1)
    assert protocol.last_test_through == date(2026, 6, 30)
    assert protocol.prospective_oos_first_trading_day == date(2026, 8, 20)
    assert protocol.horizons_bars == (3, 5, 8)
```

Also reject missing file, malformed JSON, extra/missing keys, wrong schema, wrong IDs, `research_only=false`, candidate policy/formula drift, naive freeze datetime, historical floor before 2023-01-01, retrospective through on/after prospective start, fold values other than exact 12/3/3, wrong first/last test boundaries, wrong prospective date, horizons other than exact `[3,5,8]`.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py
```

Expected: import/file failure because artifacts and loader do not exist.

- [ ] **Step 4: Add exact Candidate JSON**

```json
{
  "schema_version": 1,
  "candidate_id": "subing_lifecycle_v2_candidate_v1",
  "source_kind": "subing_lifecycle",
  "policy_id": "subing_lifecycle_v2_research_v1",
  "formula_version": "subing_lifecycle_v2",
  "research_only": true
}
```

- [ ] **Step 5: Add exact Protocol JSON**

```json
{
  "schema_version": 1,
  "protocol_id": "candidate_validation_v1",
  "research_only": true,
  "candidate_frozen_at": "2026-08-19T20:57:00+08:00",
  "retrospective": {
    "since": "2023-01-01",
    "through": "2026-08-18"
  },
  "rolling_stability": {
    "reference_months": 12,
    "test_months": 3,
    "step_months": 3,
    "first_test_since": "2024-01-01",
    "last_test_through": "2026-06-30"
  },
  "prospective_oos": {
    "first_trading_day": "2026-08-20"
  },
  "horizons_bars": [3, 5, 8]
}
```

- [ ] **Step 6: Implement strict immutable loaders**

Follow the existing lifecycle-policy pattern: project-root default path only, `json.loads`, exact nested key sets, no env/HTTP override, UTC-offset-aware freeze timestamp, exact values, frozen dataclasses. Loader must cross-check Candidate policy/formula against the existing exact lifecycle constants or loaded lifecycle policy without changing that policy.

Representative identity check:

```python
if (
    manifest.candidate_id != "subing_lifecycle_v2_candidate_v1"
    or manifest.source_kind != "subing_lifecycle"
    or manifest.policy_id != "subing_lifecycle_v2_research_v1"
    or manifest.formula_version != "subing_lifecycle_v2"
    or manifest.research_only is not True
):
    raise CandidateManifestError()
```

- [ ] **Step 7: Run GREEN + static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_subing_lifecycle_policy.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/market_data/candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py
```

Expected: all pass.

- [ ] **Step 8: Commit Task 1 only**

```bash
git add \
  data/research_candidates/subing_lifecycle_v2_candidate_v1.json \
  data/research_protocols/candidate_validation_v1.json \
  services/quant-api/app/market_data/candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py
git commit -m "feat(research): freeze candidate validation protocol"
```

---

### Task 2: Pure Candidate Window, Fold and Report Projection

**Lane:** Lane 1 — Sol/high. No I/O, no MarketData access.

**Files:**
- Create: `services/quant-api/app/market_data/candidate_validation.py`
- Create: `services/quant-api/tests/test_candidate_validation.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Read: `services/quant-api/app/market_data/subing_calibration.py`

**Interfaces:**
- Consumes: `CandidateManifest`, `CandidateValidationProtocol`, existing `SubingLifecycleResearchResult`, existing `HorizonEvaluation`.
- Produces:

```python
class CandidateWindowKind(StrEnum):
    RETROSPECTIVE = "retrospective"
    ROLLING_REFERENCE = "rolling_reference"
    ROLLING_TEST = "rolling_test"
    PROSPECTIVE_OOS = "prospective_oos"

class ProspectiveOosStatus(StrEnum):
    PENDING = "pending"
    EVALUATED = "evaluated"

@dataclass(frozen=True, slots=True)
class CandidateWindowResult:
    window_id: str
    window_kind: CandidateWindowKind
    since: date
    through: date
    products: tuple[str, ...]
    segment_count: int
    evaluable_boundary_count: int
    funnel_counts: Mapping[str, int]
    funnel_count_units: Mapping[str, str]
    confirmation_source_counts: Mapping[str, int]
    v1_v2_overlap_counts: Mapping[str, int]
    v2_to_v1_lead_bars: tuple[int, ...]
    confirmed_trading_day_span_counts: Mapping[str, int]
    risk_reason_counts: Mapping[str, int]
    recovery_reason_counts: Mapping[str, int]
    close_reason_counts: Mapping[str, int]
    horizon_summary: Mapping[int, HorizonEvaluation]

@dataclass(frozen=True, slots=True)
class RollingCandidateFold:
    fold_id: str
    reference: CandidateWindowResult
    test: CandidateWindowResult

@dataclass(frozen=True, slots=True)
class CandidateStabilitySummary:
    fold_count: int
    folds_with_entries: int
    entry_count_min: int
    entry_count_max: int
    entry_count_median: Decimal

@dataclass(frozen=True, slots=True)
class ProspectiveOosResult:
    status: ProspectiveOosStatus
    first_trading_day: date
    through: date
    result: CandidateWindowResult | None

@dataclass(frozen=True, slots=True)
class CandidateValidationReport:
    schema_version: int
    candidate_id: str
    policy_id: str
    formula_version: str
    protocol_id: str
    research_only: bool
    symbol: str
    retrospective: CandidateWindowResult
    rolling_folds: tuple[RollingCandidateFold, ...]
    rolling_stability: CandidateStabilitySummary
    prospective_oos: ProspectiveOosResult
    quality_flags: tuple[str, ...]
```

Pure functions:

```python
def project_lifecycle_window(
    *,
    window_id: str,
    window_kind: CandidateWindowKind,
    since: date,
    through: date,
    source: SubingLifecycleResearchResult,
) -> CandidateWindowResult: ...


def summarize_rolling_stability(
    folds: Sequence[RollingCandidateFold],
) -> CandidateStabilitySummary: ...
```

- [ ] **Step 1: Write RED contract/projection tests**

At minimum cover:

```python
def test_projection_preserves_existing_shadow_metrics_without_recalculation() -> None:
    source = _lifecycle_result(entry_count=4)
    projected = project_lifecycle_window(
        window_id="retrospective",
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
        source=source,
    )
    assert projected.funnel_counts == source.funnel_counts
    assert projected.horizon_summary == source.horizon_summary
    assert projected.confirmation_source_counts == source.confirmation_source_counts


def test_stability_summary_uses_entry_confirmed_counts_only() -> None:
    folds = (
        _fold("f01", entry_count=0),
        _fold("f02", entry_count=2),
        _fold("f03", entry_count=5),
    )
    summary = summarize_rolling_stability(folds)
    assert summary.fold_count == 3
    assert summary.folds_with_entries == 2
    assert summary.entry_count_min == 0
    assert summary.entry_count_max == 5
    assert summary.entry_count_median == Decimal("2")
```

Also reject mutable dict/list inputs by copying into immutable mapping/tuple projections, wrong horizon keys, missing exact funnel keys, invalid window order, duplicate fold IDs, reference/test kind mismatch, report identity mismatch, prospective `PENDING` with a result, prospective `EVALUATED` without a result.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py
```

Expected: module import failure.

- [ ] **Step 3: Implement immutable contracts and pure projection**

Do not calculate lifecycle, directional return, MFE, MAE or EMA21 failure here. Copy already-computed exact values from `SubingLifecycleResearchResult` into immutable mappings/tuples.

Use an exact Decimal median helper for integer entry counts:

```python
def _median_count(values: Sequence[int]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[middle])
    return (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)
```

Quality flags may only be factual and threshold-free:

```text
PROSPECTIVE_OOS_PENDING
ROLLING_FOLD_WITHOUT_ENTRY
HORIZON_WITHOUT_SAMPLE
```

No `GOOD` / `BAD` / `PASS` / `PROMOTE` flag.

- [ ] **Step 4: Run GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
```

Expected: all pass; existing Lifecycle result semantics unchanged.

- [ ] **Step 5: Commit Task 2 only**

```bash
git add \
  services/quant-api/app/market_data/candidate_validation.py \
  services/quant-api/tests/test_candidate_validation.py
git commit -m "feat(research): add candidate validation report contracts"
```

---

### Task 3: SuBing Candidate Validation Orchestration and Temporal Isolation

**Lane:** Lane 1 — Sol/high because this task defines retrospective / rolling / prospective OOS semantics and must prevent leakage.

**Files:**
- Create: `services/quant-api/app/market_data/subing_candidate_validation_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Read: `services/quant-api/app/market_data/candidate_validation.py`
- Read: `services/quant-api/app/market_data/candidate_validation_policy.py`

**Interfaces:**
- Consumes: exact manifest/protocol + one injected existing lifecycle research runner.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

class _LifecycleResearchRunner(Protocol):
    def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult: ...

class SubingCandidateValidationService:
    def __init__(
        self,
        lifecycle_research: _LifecycleResearchRunner,
        *,
        manifest: CandidateManifest,
        protocol: CandidateValidationProtocol,
    ) -> None: ...

    def run(self, request: CandidateValidationRequest) -> CandidateValidationReport: ...
```

- [ ] **Step 1: Write RED request/identity tests**

```python
def test_request_normalizes_symbol_but_does_not_accept_dynamic_candidate() -> None:
    request = CandidateValidationRequest(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        protocol_id="candidate_validation_v1",
        symbol=" JM ",
        through=date(2026, 8, 19),
    )
    assert request.symbol == "jm"

    with pytest.raises(ValueError, match="CANDIDATE_VALIDATION_IDENTITY_MISMATCH"):
        CandidateValidationRequest(
            candidate_id="other",
            protocol_id="candidate_validation_v1",
            symbol="jm",
            through=date(2026, 8, 19),
        )
```

Service construction must reject manifest/policy/formula/protocol mismatch before any source call.

- [ ] **Step 2: Write RED fixed-retrospective test**

Use a fake lifecycle runner recording `LifecycleResearchRequest` calls. Assert the first request is exactly:

```python
LifecycleResearchRequest(
    since=date(2023, 1, 1),
    through=date(2026, 8, 18),
    symbol="jm",
)
```

The CLI/request `through` must not move the retrospective window.

- [ ] **Step 3: Write RED exact rolling-fold test**

Assert exactly 20 lifecycle calls for rolling data: 10 reference + 10 test windows.

Fold identities:

```text
fold_01 reference 2023-01-01..2023-12-31 test 2024-01-01..2024-03-31
fold_02 reference 2023-04-01..2024-03-31 test 2024-04-01..2024-06-30
...
fold_10 reference 2025-04-01..2026-03-31 test 2026-04-01..2026-06-30
```

Implement month arithmetic with a small pure helper using calendar boundaries; do not add pandas or dateutil dependency solely for this plan.

- [ ] **Step 4: Write RED prospective OOS leakage tests**

Case A:

```python
through = date(2026, 8, 19)
```

Expected:

```text
prospective.status = pending
prospective.result = None
no LifecycleResearchRequest has since=2026-08-20
```

Case B:

```python
through = date(2026, 8, 20)
```

Expected exactly one prospective request:

```python
LifecycleResearchRequest(
    since=date(2026, 8, 20),
    through=date(2026, 8, 20),
    symbol="jm",
)
```

No request may use `since < 2026-08-20` for `CandidateWindowKind.PROSPECTIVE_OOS`.

- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
```

Expected: service missing.

- [ ] **Step 6: Implement minimal orchestration**

Required ordering:

```text
1. validate exact request/manifest/protocol identity
2. run one fixed retrospective window
3. generate 10 exact rolling folds and run reference/test for each
4. if through < 2026-08-20 -> prospective pending
5. else run prospective 2026-08-20..through
6. project source results without recomputing outcomes
7. build stability summary + factual quality flags
8. return immutable CandidateValidationReport
```

The service must not import `MarketDataService`, `CanonicalMonthlyStore`, Redis or RQData. The only research dependency is `_LifecycleResearchRunner`.

- [ ] **Step 7: Add source-failure fail-closed test**

Fake the existing lifecycle runner raising `ValueError("rank1 segment identity is missing or inconsistent")`. Candidate service must raise a stable wrapper:

```text
CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE
```

Do not return partial retrospective/folds.

- [ ] **Step 8: Run GREEN + source regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_candidate_validation.py
```

Expected: all pass.

- [ ] **Step 9: Commit Task 3 only**

```bash
git add \
  services/quant-api/app/market_data/subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
git commit -m "feat(research): validate SuBing candidate windows"
```

---

### Task 4: Read-only `guiyi research candidate-validation` and Composition Wiring

**Lane:** Lane 2 — Terra/medium. This task only wires approved semantics; if implementation requires changing validation dates or Candidate semantics, stop and return to Lane 1/Sol.

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes: `CandidateValidationRequest`, `SubingCandidateValidationService`.
- Produces exact command:

```text
guiyi research candidate-validation
  --candidate subing_lifecycle_v2_candidate_v1
  --protocol candidate_validation_v1
  --symbol jm
  --through YYYY-MM-DD
```

- [ ] **Step 1: Write parser RED test**

```python
def test_candidate_validation_parser_requires_exact_arguments() -> None:
    args = build_parser().parse_args([
        "research",
        "candidate-validation",
        "--candidate", "subing_lifecycle_v2_candidate_v1",
        "--protocol", "candidate_validation_v1",
        "--symbol", "jm",
        "--through", "2026-08-19",
    ])
    request = build_research_request(args)
    assert request == CandidateValidationRequest(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        protocol_id="candidate_validation_v1",
        symbol="jm",
        through=date(2026, 8, 19),
    )
```

Parser choices for `--candidate` and `--protocol` must be exact single-value choices, not arbitrary strings.

- [ ] **Step 2: Write stdout payload RED test**

Required top-level JSON shape:

```json
{
  "schema_version": 1,
  "command": "research.candidate-validation",
  "status": "ok",
  "readonly": true,
  "candidate_id": "subing_lifecycle_v2_candidate_v1",
  "policy_id": "subing_lifecycle_v2_research_v1",
  "formula_version": "subing_lifecycle_v2",
  "protocol_id": "candidate_validation_v1",
  "research_only": true,
  "symbol": "jm",
  "retrospective": {},
  "rolling_folds": [],
  "rolling_stability": {},
  "prospective_oos": {},
  "quality_flags": []
}
```

Nested horizon Decimal values must use the existing research CLI serializer convention: strings, not float.

- [ ] **Step 3: Write main-dispatch RED test**

Inject three independent factories:

```text
subing-calibration       -> existing research_service_factory
subing-lifecycle         -> existing lifecycle_research_service_factory
candidate-validation     -> new candidate_validation_service_factory
```

Assert candidate command never invokes the calibration or lifecycle CLI factory directly; the new factory internally receives an existing lifecycle research service through composition.

- [ ] **Step 4: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py
```

Expected: parser/dispatch assertions fail because command does not exist.

- [ ] **Step 5: Add composition constants and builder**

Add exact paths under `PROJECT_ROOT`:

```python
_CANDIDATE_MANIFEST = (
    PROJECT_ROOT / "data/research_candidates/subing_lifecycle_v2_candidate_v1.json"
)
_CANDIDATE_VALIDATION_PROTOCOL = (
    PROJECT_ROOT / "data/research_protocols/candidate_validation_v1.json"
)
```

Builder:

```python
def build_subing_candidate_validation_service(
    session: Session,
) -> SubingCandidateValidationService:
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(_CANDIDATE_MANIFEST),
        protocol=load_candidate_validation_protocol(_CANDIDATE_VALIDATION_PROTOCOL),
    )
```

This intentionally reuses `build_subing_lifecycle_research_service(session)` instead of building a second MarketData reader.

- [ ] **Step 6: Add parser/request/serializer**

`research_parser.py`:

```python
candidate = commands.add_parser("candidate-validation")
candidate.add_argument(
    "--candidate",
    choices=("subing_lifecycle_v2_candidate_v1",),
    required=True,
)
candidate.add_argument(
    "--protocol",
    choices=("candidate_validation_v1",),
    required=True,
)
candidate.add_argument("--symbol", required=True)
candidate.add_argument("--through", required=True)
```

`research_commands.py` extends `ResearchRequest` union and serializes all windows/folds. Reuse `_horizon_payload()` for horizon values; do not implement a second Decimal formatter.

- [ ] **Step 7: Add exact main dispatch**

Add a `candidate_validation_service_factory` parameter defaulted to the new composition builder. Dispatch with explicit branches, not a broad `else`:

```python
if args.research_command == "subing-lifecycle":
    service_factory = lifecycle_research_service_factory
elif args.research_command == "candidate-validation":
    service_factory = candidate_validation_service_factory
else:
    service_factory = research_service_factory
```

- [ ] **Step 8: Run GREEN + existing research zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py
```

Expected: all three research command families pass.

- [ ] **Step 9: Commit Task 4 only**

```bash
git add \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat(cli): expose candidate validation research"
```

---

### Task 5: Temporal Leakage, Prefix and Full Candidate Validation Regression

**Lane:** Lane 1 — Sol/high.

**Files:**
- Modify: `services/quant-api/tests/test_candidate_validation.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Read/run: all existing SuBing lifecycle/calibration/read-service tests required by `TESTING.md`.

**Interfaces:**
- Consumes: Tasks 1–4 implementation.
- Produces: executable proof that Candidate Validation adds no look-ahead, no historical/OOS relabeling and no V1/V2 regression.

- [ ] **Step 1: Add exact 10-fold boundary golden test**

Assert fold test windows equal:

```text
2024-01-01..2024-03-31
2024-04-01..2024-06-30
2024-07-01..2024-09-30
2024-10-01..2024-12-31
2025-01-01..2025-03-31
2025-04-01..2025-06-30
2025-07-01..2025-09-30
2025-10-01..2025-12-31
2026-01-01..2026-03-31
2026-04-01..2026-06-30
```

and each reference starts exactly 12 calendar months before its test start.

- [ ] **Step 2: Add pre-freeze contamination test**

Build a fake source where a large entry exists on trading day `2026-08-19` and another on `2026-08-20`. Run through `2026-08-20`. Assert prospective request begins at `2026-08-20`; the 2026-08-19 observation can only appear in retrospective if that retrospective window included it—which V1 does not—therefore it appears nowhere in prospective OOS.

- [ ] **Step 3: Add same-source deterministic report test**

For the same fake source results and request, call service twice and assert complete dataclass equality. Then mutate only a future prospective fake result beyond the first run’s `through`; rerun with the original `through` and assert the original report is unchanged.

- [ ] **Step 4: Add no-auto-decision contract test**

Assert serialized JSON has no keys:

```text
keep
drop
promote
pass_strategy
expected_profit
account_return
```

and quality flags are limited to the approved factual set.

- [ ] **Step 5: Run focused complete Candidate suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: all pass.

- [ ] **Step 6: Run upstream SuBing regression suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
```

Expected: zero regression.

- [ ] **Step 7: Run static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: all pass / secret findings 0.

- [ ] **Step 8: Commit only new regression changes**

```bash
git add \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "test(research): lock candidate validation causality"
```

---

### Task 6: Canonical Documentation, Independent Implementation Review and Develop Integration

**Lane:** Lane 1 review — Sol/high, new independent Review session.

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify only after all verification/review gates pass: `STATUS.md`
- Review: full diff from implementation branch base to HEAD.

**Interfaces:**
- Consumes: Tasks 1–5 green implementation.
- Produces: reviewed, accurately documented develop-only Candidate Validation implementation.

- [ ] **Step 1: Add exact testing commands**

`TESTING.md` must state Candidate Validation is Historical-only and include the four focused test files plus Ruff/Mypy. It must explicitly say tests do not run real `jm` research or write DB/Canonical/Redis/Runtime/notification.

- [ ] **Step 2: Update architecture narrowly**

Add one component under Historical research:

```text
Candidate Validation V1
→ exact Candidate/Protocol artifacts
→ existing SubingLifecycleResearchService
→ MarketDataService
→ Historical Canonical
→ stdout JSON / versioned research report
```

Explicitly state:

```text
not a backtest engine
no order/position/cost/equity semantics
no DB/Redis persistence
no Alert consumer
```

- [ ] **Step 3: Run repository checks after docs**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 4: Commit docs except STATUS**

```bash
git add TESTING.md docs/ARCHITECTURE.md
git commit -m "docs(research): document candidate validation v1"
```

- [ ] **Step 5: Open independent Review session and review full implementation diff**

Reviewer must inspect at minimum:

```text
1. retrospective is never called OOS
2. prospective starts exactly 2026-08-20
3. no fold modifies candidate/policy
4. no duplicated SuBing/outcome math
5. no direct MarketData/Parquet/Redis/RQData bypass in candidate service
6. no dynamic candidate/protocol parameters
7. no auto KEEP/DROP/PROMOTE
8. existing research CLI commands remain unchanged
9. no API/Web/DB/Runtime/Alert surface expansion
10. all required tests cover fail-closed paths
```

Review classification:

```text
Critical
Important
Minor
```

Integration requires:

```text
Critical = 0
Important = 0
```

Any Critical/Important finding is fixed with RED→GREEN regression before continuing.

- [ ] **Step 6: Run final focused verification after review fixes**

Repeat Task 5 Steps 5–7. Do not rely on pre-review test output if source changed.

- [ ] **Step 7: Update STATUS accurately**

Only after Review and tests pass, record:

```text
Candidate Validation V1 develop implementation exists
research_only / Historical-only
first candidate = subing_lifecycle_v2_candidate_v1
true prospective OOS starts 2026-08-20
real jm baseline has NOT been run yet
no strategy validity / promotion / release / Runtime claim
```

- [ ] **Step 8: Commit STATUS closeout**

```bash
git add STATUS.md
git commit -m "docs(status): record candidate validation implementation"
```

- [ ] **Step 9: Integrate implementation branch to develop**

Use repository-approved ordinary develop integration. If using a PR, target `develop`, never `main`.

After integration:

```bash
git fetch origin develop
git merge-base --is-ancestor <IMPLEMENTATION_HEAD_SHA> origin/develop
git log -5 --oneline --decorate origin/develop
```

Expected: implementation head is ancestor of latest develop.

- [ ] **Step 10: Clean implementation workspace only after ancestry readback**

```bash
git worktree remove ../guiyi-candidate-validation-v1
git branch -d research/candidate-validation-v1
```

Do not delete any unmerged or dirty workspace.

---

### Task 7: Exact-Develop `jm` Candidate Evidence Baseline

**Lane:** Lane 1 research — Sol/high, new session and new worktree from the exact post-Task-6 `develop`.

**Files:**
- Create: `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json`
- Read: exact Candidate Manifest / Validation Protocol / `STATUS.md`
- Execute: read-only `guiyi research candidate-validation`

**Interfaces:**
- Consumes: reviewed Candidate Validation implementation already in develop + Historical Canonical through the existing Lifecycle Shadow service.
- Produces: first versioned `jm` retrospective/rolling evidence artifact; prospective OOS must remain `pending` because the run uses `--through 2026-08-19`.

- [ ] **Step 1: Create evidence workspace from exact develop**

```bash
git fetch origin develop
git worktree add ../guiyi-subing-candidate-v1-jm-baseline \
  -b research/subing-candidate-v1-jm-baseline origin/develop
cd ../guiyi-subing-candidate-v1-jm-baseline
git status --short
git rev-parse HEAD
```

Record the exact develop commit used for the run in the task output. Do not write it into Candidate semantic identity.

- [ ] **Step 2: Run preflight tests before touching the report path**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: all pass. Failure blocks the evidence run.

- [ ] **Step 3: Ensure output directory exists**

```bash
mkdir -p \
  reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1
```

- [ ] **Step 4: Run one exact read-only baseline command**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate subing_lifecycle_v2_candidate_v1 \
  --protocol candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-19 \
  > reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json
```

This command is allowed to read Historical Canonical only. It must not run RQData update/refresh, write DB/Canonical/Redis, load Runtime or send notification.

- [ ] **Step 5: Validate JSON contract without editing the output**

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json")
payload = json.loads(path.read_text())
assert payload["schema_version"] == 1
assert payload["command"] == "research.candidate-validation"
assert payload["status"] == "ok"
assert payload["readonly"] is True
assert payload["research_only"] is True
assert payload["candidate_id"] == "subing_lifecycle_v2_candidate_v1"
assert payload["protocol_id"] == "candidate_validation_v1"
assert payload["symbol"] == "jm"
assert len(payload["rolling_folds"]) == 10
assert payload["prospective_oos"]["status"] == "pending"
assert payload["prospective_oos"]["first_trading_day"] == "2026-08-20"
print("candidate baseline contract: PASS")
PY
```

- [ ] **Step 6: Fail if the evidence mislabels historical data**

```bash
python3 - <<'PY'
from pathlib import Path
text = Path("reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json").read_text().lower()
for forbidden in ("historical_oos", "backtest_profit", "expected_profit", "promote", "pass_strategy"):
    assert forbidden not in text, forbidden
print("candidate evidence semantics: PASS")
PY
```

- [ ] **Step 7: Run secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: only the intended report file is new; secret findings 0.

- [ ] **Step 8: Commit the exact evidence artifact**

```bash
git add \
  reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/2026-08-19-jm-baseline.json
git commit -m "research(subing): add candidate v1 jm baseline"
```

Do not update `STATUS.md` in Task 7; evidence semantics are reviewed independently in Task 8 first.

---

### Task 8: Independent Evidence Review and Phase 4B Closeout

**Lane:** Lane 1 review — Sol/high, new independent Review session.

**Files:**
- Review: exact Task 7 JSON artifact + implementation Spec/Plan + source code contracts.
- Modify only after evidence review passes: `STATUS.md`

**Interfaces:**
- Consumes: exact Candidate baseline artifact.
- Produces: a reviewed research conclusion about evidence quality only; not strategy promotion.

- [ ] **Step 1: Review identity and temporal semantics**

Reviewer must confirm:

```text
candidate_id = subing_lifecycle_v2_candidate_v1
policy_id = subing_lifecycle_v2_research_v1
formula_version = subing_lifecycle_v2
protocol_id = candidate_validation_v1
symbol = jm
retrospective through = 2026-08-18
rolling test folds = 10, ending 2026Q2
prospective OOS = pending for --through 2026-08-19
first prospective trading day = 2026-08-20
```

Any historical value appearing under prospective OOS is Critical.

- [ ] **Step 2: Review evidence completeness**

Confirm the artifact contains:

```text
funnel counts
confirmation source counts
V1/V2 overlap
V2→V1 lead bars
same-day / cross-day counts
risk / recovery / close reasons
3/5/8 horizon summaries
10 rolling reference/test folds
stability summary
quality flags
```

Missing required section is Important unless the source is correctly `unavailable`, in which case the entire run should have failed rather than written a partial success report.

- [ ] **Step 3: Review claims**

The report and proposed STATUS text must not infer:

```text
profitability
trade readiness
formal Rule readiness
Alert readiness
promotion approval
Runtime readiness
```

The only allowed conclusion is that Candidate Validation infrastructure produced a reproducible research evidence baseline for the exact candidate/protocol/symbol/window.

- [ ] **Step 4: Record Review result**

Required integration gate:

```text
Critical = 0
Important = 0
```

Minor findings may be documented if they do not alter evidence meaning. Any semantic fix requires regenerating the report from the same exact command; do not hand-edit generated metrics.

- [ ] **Step 5: Update STATUS after accepted evidence**

Record exact facts:

```text
Candidate Validation V1 implementation is in develop
first jm retrospective/rolling baseline artifact exists at the exact path
prospective OOS is still pending as of --through 2026-08-19
no Candidate effectiveness or promotion conclusion has been made
next valid prospective samples start trading_day 2026-08-20
```

- [ ] **Step 6: Commit closeout docs**

```bash
git add STATUS.md
git commit -m "docs(status): record candidate validation baseline"
```

- [ ] **Step 7: Integrate evidence branch to develop and read back**

After integration:

```bash
git fetch origin develop
git merge-base --is-ancestor <EVIDENCE_HEAD_SHA> origin/develop
git log -5 --oneline --decorate origin/develop
```

Expected: evidence head is ancestor of current develop.

- [ ] **Step 8: Clean evidence worktree/branch**

```bash
git worktree remove ../guiyi-subing-candidate-v1-jm-baseline
git branch -d research/subing-candidate-v1-jm-baseline
```

---

## Final Acceptance Criteria

Phase 4B V1 is complete only when all are true:

```text
[ ] exact Candidate Manifest is tracked and strict-loaded
[ ] exact Validation Protocol is tracked and strict-loaded
[ ] historical retrospective is never labeled true OOS
[ ] rolling historical stability is exactly 10 folds with frozen candidate semantics
[ ] prospective OOS starts at trading_day 2026-08-20 and cannot backfill earlier data
[ ] Candidate service reuses existing SubingLifecycleResearchService only
[ ] no duplicated lifecycle/outcome/rank1 formula exists
[ ] candidate-validation CLI is read-only and existing research CLI is unchanged
[ ] no API/Web/DB/Redis/worker/Alert/Runtime surface was added
[ ] implementation review Critical=0 / Important=0
[ ] exact-develop jm baseline JSON exists and validates
[ ] evidence review Critical=0 / Important=0
[ ] STATUS states only exact research facts
[ ] main/tag/Runtime/Scope/notification/order remain untouched
```

Successful completion yields only:

```text
允许进入 N 字 Structural Domain V1 设计/实现阶段
```

It does **not** yield:

```text
允许发布新的 SuBing Alert Rule
允许 Candidate promotion
允许 main/tag release
允许 Runtime promotion
```

Those remain future independent tasks/Gates.
