# Candidate Validation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Every implementation change follows TDD where executable behavior changes.
>
> Planning Review status: **Critical=0 / Important=0 after fixes**. Remaining non-blocking formatting note: the companion design file may lack a final newline; this does not alter semantics or execution.

**Goal:** 在不修改 SuBing V1/V2 公式、Alert、Scope、Runtime 与 Data Foundation 的前提下，先用现有 SuBing Lifecycle Shadow 对 `jm` 做真实只读 baseline preflight，再建立首个 research-only Candidate Validation V1：固定 Candidate/Protocol，生成 retrospective、10-fold rolling historical stability、严格冻结后的 prospective OOS，并形成版本化 `jm` evidence report。

**Architecture:** Candidate Validation V1 不重建传统 backtest engine，不增加 Strategy plugin/registry，不复制 SuBing Lifecycle 的 Opportunity、Transition、outcome 或 rank1 逻辑。唯一计算链为：

```text
CandidateValidationService
→ existing SubingLifecycleResearchService
→ MarketDataService
→ Historical Canonical
```

Candidate 层只负责 exact identity、时间协议、窗口编排、稳定投影和报告。所有 KEEP / DROP / PROMOTE 均保留人工 Gate。

**Tech Stack:** Python 3.13、dataclasses、Decimal、现有 FastAPI composition/CLI、pytest、Ruff、Mypy、JSON artifacts。

**Spec:** `docs/superpowers/specs/2026-08-19-candidate-validation-v1-design.md`

---

## Global Constraints

- 每个 Task 开始前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec、上游 SuBing Lifecycle V2 Spec 与本 Plan；冲突时 fail-closed。
- SuBing V1 Factor / Signal / Calibration / resolver / `subing_entry_signal_v1` / Alert / Scope / Clawbot 零变化。
- SuBing Lifecycle V2 exact policy、formula、ConfirmedPivot/Breakout/Retest、lifecycle reducer 零变化。
- Phase 4A 必须先运行 existing `guiyi research subing-lifecycle` 的真实 `jm` Historical baseline。若 source 因 Canonical、rank1、coverage、policy 等 fail-closed，停止 Phase 4B，不在新层做 fallback。
- Candidate 精确为 `subing_lifecycle_v2_candidate_v1`，绑定 `subing_lifecycle_v2_research_v1` / `subing_lifecycle_v2`，`research_only=true`。
- Protocol 精确为 `candidate_validation_v1`；freeze=`2026-08-19T20:57:00+08:00`；第一 eligible prospective OOS trading day=`2026-08-20`。
- `2023-01-01..2026-08-18` 只称 retrospective；rolling 历史窗口只称 `rolling_historical_stability`，不得冒充 true OOS。
- rolling 固定为 12 calendar months reference + 3 months test + 3 months step；首 test=2024Q1，末 test=2026Q2，共 10 folds；所有 folds 中 Candidate/Policy 完全冻结，不调参。
- prospective source 可以由 existing Lifecycle service 自行读取 freeze 前历史 Bars 作 causal warm-up；只有 request range `trading_day >= 2026-08-20` 的汇总可成为 prospective evidence。
- `--through` 的协议边界由 `SubingCandidateValidationService` 依据 injected `CandidateValidationProtocol` 校验；`CandidateValidationRequest` 只做字段类型/格式/日期解析，不重复硬编码协议日期。
- `--through < protocol.retrospective_through` → `CANDIDATE_VALIDATION_WINDOW_INVALID`；`retrospective_through <= through < prospective_start` → prospective `pending`。
- Candidate service 只依赖 injected `SubingLifecycleResearchService` protocol；不得 import/build 第二条 MarketData/Parquet/Redis/RQData 路径。
- V1 不新建第二套 `CandidateOpportunity` / `CandidateOutcome`；N 字作为第二个真实 Candidate 后再判断通用 event-level abstraction。
- 不新增 DB/migration、Canonical、Redis state、worker、queue、scheduler、HTTP Candidate API、Web dashboard、Alert Rule、Scope、notification、Execution Review 自动入口。
- 不计算账户收益、trade PnL、手续费/滑点后收益、保证金收益或 equity curve；只复用 existing 3/5/8 Bar directional return / MFE / MAE / EMA21 failure。
- CandidateReport 不输出 KEEP / DROP / PROMOTE / PASS_STRATEGY；系统只给研究事实与 factual quality flags。
- CLI 仍 `readonly=true`、只 stdout；版本化 report 由 shell redirection 写入仓库指定路径，CLI 不获得任意文件写能力。
- 本 Plan 不授权 `main`、release/tag、Runtime switch/promotion、Scope mutation、真实通知、production DB/Canonical 写入、RQData mutation 或订单。

---

## Codex 调度矩阵

| Task | Lane | Model | 推理 | 会话 | Plan | Workspace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Existing `jm` Shadow baseline preflight | Lane 1 | Sol | 高 | 新研究会话 | Plan-then-execute | 临时 research worktree | real source read-only PASS |
| 2 Exact Candidate/Protocol contracts | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | implementation worktree | exact loader tests |
| 3 Pure window/fold/report projection | Lane 1 | Sol | 高 | 同任务或新会话 | Plan-then-execute | same worktree | no duplicated math |
| 4 SuBing validation orchestration | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | same worktree | temporal/leakage tests |
| 5 CLI + composition wiring | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | same worktree | readonly CLI regression |
| 6 Causality/full regression | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | same worktree | all focused/upstream green |
| 7 Docs + independent implementation review | Lane 1 review | Sol | 高 | 新独立 Review | Review-only | implementation diff | Critical=0 / Important=0 |
| 8 Exact-develop `jm` Candidate baseline | Lane 1 | Sol | 高 | 新研究会话 | Plan-then-execute | evidence worktree | exact generated JSON |
| 9 Evidence review + closeout | Lane 1 review | Sol | 高 | 新独立 Review | Review-only | evidence diff | Critical=0 / Important=0 |

OOS / rolling / leakage 使用 Lane 1 + Sol/high。若实现过程中需要改 SuBing 公式、交易成交/成本语义或 Candidate promotion，立即停止并升级为独立 Lane 3。

### Worktree flow

```text
Task 1:
develop → temporary research worktree → read-only preflight → cleanup

Tasks 2-7:
develop → research/candidate-validation-v1 worktree
→ implementation/tests → independent review
→ develop → ancestry readback → cleanup

Tasks 8-9:
post-integration develop → research/subing-candidate-v1-jm-baseline worktree
→ generated report → evidence review
→ develop → ancestry readback → cleanup
```

不触及 `main`、release worktree 或 Runtime worktree。

---

## Planned Files

### Create

- `data/research_candidates/subing_lifecycle_v2_candidate_v1.json`
- `data/research_protocols/candidate_validation_v1.json`
- `services/quant-api/app/market_data/candidate_validation_policy.py`
- `services/quant-api/app/market_data/candidate_validation.py`
- `services/quant-api/app/market_data/subing_candidate_validation_service.py`
- `services/quant-api/tests/test_candidate_validation_policy.py`
- `services/quant-api/tests/test_candidate_validation.py`
- `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Task 8 only: `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json`

### Modify

- `services/quant-api/app/market_data/composition.py`
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_commands.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/tests/test_research_cli.py`
- Task 7 only after executable verification: `TESTING.md`, `docs/ARCHITECTURE.md`, then `STATUS.md`
- Task 9 only after evidence review: `STATUS.md`

No API schema/Web/DB/migration/launchd/notification/Runtime file belongs to this plan.

---

# Task 1 — Existing SuBing Lifecycle `jm` Shadow Baseline Preflight

**Lane:** Lane 1 / Sol / 高 / 新研究会话 / Plan-then-execute.

**Purpose:** 在写 Candidate Validation 前证明 existing source 能在真实 Historical Canonical 上运行。

### Step 1 — Create temporary workspace

```bash
git fetch origin develop
git worktree add ../guiyi-subing-shadow-jm-preflight \
  -b research/subing-shadow-jm-preflight origin/develop
cd ../guiyi-subing-shadow-jm-preflight
git status --short
git rev-parse HEAD
```

Expected: clean latest develop.

### Step 2 — Existing focused tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

### Step 3 — Real read-only source baseline

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research subing-lifecycle \
  --since 2023-01-01 \
  --through 2026-08-18 \
  --symbol jm \
  > /tmp/subing-lifecycle-jm-preflight-20260818.json
```

No data update/refresh, Runtime, DB/Canonical/Redis write or notification.

### Step 4 — Validate current payload

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('/tmp/subing-lifecycle-jm-preflight-20260818.json').read_text())
assert p['schema_version'] == 1
assert p['command'] == 'research.subing-lifecycle'
assert p['status'] == 'ok'
assert p['readonly'] is True
assert p['policy_id'] == 'subing_lifecycle_v2_research_v1'
assert p['products'] == ['jm']
for key in (
    'funnel_counts', 'confirmation_source_counts', 'v1_v2_overlap_counts',
    'v2_to_v1_lead_bars', 'confirmed_trading_day_span_counts',
    'risk_reason_counts', 'recovery_reason_counts', 'close_reason_counts',
    'horizon_summary',
):
    assert key in p, key
assert set(p['horizon_summary']) == {'3', '5', '8'}
print('SOURCE_BASELINE_READY')
PY
```

If source fails on rank1/coverage/policy/canonical identity/readability, output `SOURCE_BASELINE_BLOCKED` and stop before Task 2.

### Step 5 — Cleanup

```bash
git status --short
cd ..
git worktree remove ./guiyi-subing-shadow-jm-preflight
git branch -d research/subing-shadow-jm-preflight
rm -f /tmp/subing-lifecycle-jm-preflight-20260818.json
```

No commit.

---

# Task 2 — Exact Candidate Manifest + Validation Protocol

**Lane:** Lane 1 / Sol / 高 / new implementation session.

### Files

Create:

```text
data/research_candidates/subing_lifecycle_v2_candidate_v1.json
data/research_protocols/candidate_validation_v1.json
services/quant-api/app/market_data/candidate_validation_policy.py
services/quant-api/tests/test_candidate_validation_policy.py
```

### Contract

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
```

Stable errors:

```text
CANDIDATE_MANIFEST_INVALID
CANDIDATE_VALIDATION_PROTOCOL_INVALID
```

### Step 1 — Create implementation worktree

```bash
git fetch origin develop
git worktree add ../guiyi-candidate-validation-v1 \
  -b research/candidate-validation-v1 origin/develop
cd ../guiyi-candidate-validation-v1
```

### Step 2 — RED loader tests

Test exact accepted Candidate:

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

Test exact Protocol:

```json
{
  "schema_version": 1,
  "protocol_id": "candidate_validation_v1",
  "research_only": true,
  "candidate_frozen_at": "2026-08-19T20:57:00+08:00",
  "retrospective": {"since": "2023-01-01", "through": "2026-08-18"},
  "rolling_stability": {
    "reference_months": 12,
    "test_months": 3,
    "step_months": 3,
    "first_test_since": "2024-01-01",
    "last_test_through": "2026-06-30"
  },
  "prospective_oos": {"first_trading_day": "2026-08-20"},
  "horizons_bars": [3, 5, 8]
}
```

Reject missing/malformed file, extra/missing nested keys, wrong IDs, wrong formula/policy, `research_only=false`, naive freeze timestamp, wrong 12/3/3, wrong first/last fold range, wrong prospective date, wrong horizons.

### Step 3 — Run RED

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py
```

Expected import/file failure.

### Step 4 — Implement strict loaders

- project-root default path only;
- no env/HTTP override;
- exact nested shape and exact semantic values;
- frozen dataclasses;
- cross-check Candidate policy/formula against existing Lifecycle identity.

### Step 5 — GREEN

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

### Step 6 — Commit

```bash
git add data/research_candidates data/research_protocols \
  services/quant-api/app/market_data/candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py
git commit -m 'feat(research): freeze candidate validation protocol'
```

---

# Task 3 — Pure Window / Fold / Report Projection

**Lane:** Lane 1 / Sol / 高. No I/O.

### Files

Create:

```text
services/quant-api/app/market_data/candidate_validation.py
services/quant-api/tests/test_candidate_validation.py
```

### Public contracts

```python
class CandidateWindowKind(StrEnum):
    RETROSPECTIVE = 'retrospective'
    ROLLING_REFERENCE = 'rolling_reference'
    ROLLING_TEST = 'rolling_test'
    PROSPECTIVE_OOS = 'prospective_oos'

class ProspectiveOosStatus(StrEnum):
    PENDING = 'pending'
    EVALUATED = 'evaluated'

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
def project_lifecycle_window(..., source: SubingLifecycleResearchResult) -> CandidateWindowResult: ...
def summarize_rolling_stability(folds: Sequence[RollingCandidateFold]) -> CandidateStabilitySummary: ...
```

### Step 1 — RED tests

Prove:

- projection copies existing funnel, confirmation, overlap, lead bars, day-span, reason and horizon values without recalculation;
- mapping inputs are defensively copied into immutable mappings;
- wrong horizon/funnel keys fail;
- duplicate fold IDs fail;
- reference/test kind mismatch fails;
- prospective `PENDING` requires `result=None`; `EVALUATED` requires a result;
- report identity mismatch fails;
- stability summary uses only `ENTRY_CONFIRMED` fold test counts;
- median uses Decimal, including even fold count.

### Step 2 — RED

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py
```

### Step 3 — Minimal implementation

Do **not** compute lifecycle, directional return, MFE, MAE or EMA21 failure. Those are source facts.

Allowed factual quality flags only:

```text
PROSPECTIVE_OOS_PENDING
ROLLING_FOLD_WITHOUT_ENTRY
HORIZON_WITHOUT_SAMPLE
```

No GOOD/BAD/PASS/PROMOTE semantics.

### Step 4 — GREEN

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
```

### Step 5 — Commit

```bash
git add services/quant-api/app/market_data/candidate_validation.py \
  services/quant-api/tests/test_candidate_validation.py
git commit -m 'feat(research): add candidate validation report contracts'
```

---

# Task 4 — SuBing Candidate Validation Orchestration

**Lane:** Lane 1 / Sol / 高 because this task defines OOS/rolling/leakage semantics.

### Files

Create:

```text
services/quant-api/app/market_data/subing_candidate_validation_service.py
services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
```

### Interfaces

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

class _LifecycleResearchRunner(Protocol):
    def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult: ...

class CandidateValidationSourceError(ValueError):
    code = 'CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE'
```

`CandidateValidationRequest.__post_init__` only:

- validates string/date types;
- strips/normalizes symbol;
- rejects empty/invalid syntax;
- **does not hardcode candidate/protocol IDs or freeze dates**.

Exact ID and date semantics are validated by `SubingCandidateValidationService` against injected Manifest/Protocol. This keeps the Git-tracked Protocol as the single validation authority.

### Step 1 — RED request tests

```python
def test_request_normalizes_symbol_without_embedding_protocol_semantics() -> None:
    request = CandidateValidationRequest(
        candidate_id='anything-syntactically-valid',
        protocol_id='anything-syntactically-valid',
        symbol=' JM ',
        through=date(2026, 8, 17),
    )
    assert request.symbol == 'jm'
```

Also reject empty IDs, invalid symbol syntax and non-date `through`.

### Step 2 — RED service identity/window tests

Construct service with exact manifest/protocol. Assert service rejects:

```text
wrong candidate_id            → CANDIDATE_VALIDATION_IDENTITY_MISMATCH
wrong protocol_id             → CANDIDATE_VALIDATION_IDENTITY_MISMATCH
through < retrospective_through → CANDIDATE_VALIDATION_WINDOW_INVALID
```

For `through=2026-08-19`, first source call is always frozen retrospective:

```python
LifecycleResearchRequest(
    since=date(2023, 1, 1),
    through=date(2026, 8, 18),
    symbol='jm',
)
```

### Step 3 — RED exact rolling folds

Test windows:

```text
fold_01 2024-01-01..2024-03-31
fold_02 2024-04-01..2024-06-30
fold_03 2024-07-01..2024-09-30
fold_04 2024-10-01..2024-12-31
fold_05 2025-01-01..2025-03-31
fold_06 2025-04-01..2025-06-30
fold_07 2025-07-01..2025-09-30
fold_08 2025-10-01..2025-12-31
fold_09 2026-01-01..2026-03-31
fold_10 2026-04-01..2026-06-30
```

Each reference is immediately preceding 12 calendar months. Assert 10 folds, 20 rolling source calls.

Use local calendar helpers only; no new dependency:

```python
def _add_months(value: date, months: int) -> date:
    start = date(value.year, value.month, 1)
    absolute = start.year * 12 + (start.month - 1) + months
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)
```

Then:

```text
reference_since   = add_months(test_since, -12)
reference_through = test_since - 1 day
test_through      = add_months(test_since, 3) - 1 day
next test_since   = add_months(test_since, 3)
```

### Step 4 — RED prospective boundary tests

`through=2026-08-19`:

```text
prospective.status = pending
prospective.result = None
no prospective source call
```

`through=2026-08-20`:

```python
LifecycleResearchRequest(
    since=date(2026, 8, 20),
    through=date(2026, 8, 20),
    symbol='jm',
)
```

**Important:** Candidate layer proves its temporal boundary by the exact `LifecycleResearchRequest` it emits. Existing `SubingLifecycleResearchService` tests remain responsible for proving that its aggregate result only counts `since..through` while it may read older segment-local warm-up internally. Because `SubingLifecycleResearchResult` is aggregate-only and carries no individual observation timestamps, Candidate V1 must not invent an impossible second “out-of-range observation inspection” step.

### Step 5 — RED source-failure test

When the injected lifecycle runner raises a source-domain failure, return stable `CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE`; never return partial report.

### Step 6 — Implement minimal orchestration

Order:

```text
1 validate request against manifest/protocol
2 run fixed retrospective
3 run 10 fixed reference/test folds
4 if through < prospective_start: pending
5 else run prospective request prospective_start..through
6 project source results
7 build threshold-free stability summary / quality flags
8 return immutable report
```

The module must not import `MarketDataService`, storage, Redis or RQData.

### Step 7 — GREEN

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_candidate_validation.py
```

### Step 8 — Commit

```bash
git add services/quant-api/app/market_data/subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
git commit -m 'feat(research): validate SuBing candidate windows'
```

---

# Task 5 — Read-only CLI and Composition Wiring

**Lane:** Lane 2 / Terra / 中. Semantics already frozen by Task 4.

### Modify

```text
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_research_cli.py
```

### Step 1 — RED parser/payload/dispatch tests

Exact command:

```text
guiyi research candidate-validation
  --candidate subing_lifecycle_v2_candidate_v1
  --protocol candidate_validation_v1
  --symbol jm
  --through YYYY-MM-DD
```

Parser uses exact one-value choices for candidate/protocol. Build request does not validate Protocol dates; service does.

Required payload top-level:

```text
schema_version=1
command=research.candidate-validation
status=ok
readonly=true
candidate_id
policy_id
formula_version
protocol_id
research_only=true
symbol
retrospective
rolling_folds
rolling_stability
prospective_oos
quality_flags
```

Reuse existing `_horizon_payload()` for Decimal serialization.

Main dispatch must be explicit:

```python
if args.research_command == 'subing-lifecycle':
    service_factory = lifecycle_research_service_factory
elif args.research_command == 'candidate-validation':
    service_factory = candidate_validation_service_factory
elif args.research_command == 'subing-calibration':
    service_factory = research_service_factory
else:
    raise ValueError('CLI_RESEARCH_COMMAND_INVALID')
```

### Step 2 — RED

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py
```

### Step 3 — Composition builder

Add exact paths:

```python
_CANDIDATE_MANIFEST = PROJECT_ROOT / 'data/research_candidates/subing_lifecycle_v2_candidate_v1.json'
_CANDIDATE_VALIDATION_PROTOCOL = PROJECT_ROOT / 'data/research_protocols/candidate_validation_v1.json'
```

Builder must reuse existing lifecycle research builder:

```python
def build_subing_candidate_validation_service(session: Session) -> SubingCandidateValidationService:
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(_CANDIDATE_MANIFEST),
        protocol=load_candidate_validation_protocol(_CANDIDATE_VALIDATION_PROTOCOL),
    )
```

No second `MarketDataService` construction inside Candidate service.

### Step 4 — Implement parser/serializer/dispatch

Unknown research command still fails. Existing `subing-calibration` and `subing-lifecycle` behavior remains unchanged.

### Step 5 — GREEN

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py
```

### Step 6 — Commit

```bash
git add services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_research_cli.py
git commit -m 'feat(cli): expose candidate validation research'
```

---

# Task 6 — Temporal Leakage, Determinism and Full Regression

**Lane:** Lane 1 / Sol / 高.

### Step 1 — Exact protocol boundary tests

Verify:

- service, not Request dataclass, rejects `through < 2026-08-18` from injected protocol;
- exactly 10 rolling test windows and exact 12m reference windows;
- all folds reuse same manifest/policy/formula;
- prospective source request starts exactly 2026-08-20;
- through 2026-08-18/19 produces prospective pending;
- no auto-decision fields exist.

### Step 2 — Source-boundary / warm-up regression

Use fake runner to assert Candidate service emits the exact `since/through` for each window.

Then rely on existing real `SubingLifecycleResearchService` regression to prove its `add_trace(... since, through ...)` filtering and segment warm-up behavior. Do not attempt to inspect nonexistent event timestamps from aggregate source output.

### Step 3 — Same-prefix determinism

For same fake source mapping and request, reports are equal. Add data only after requested `through`; source fake still returns identical requested-window aggregates; report remains equal.

### Step 4 — No auto-decision serialization

Forbidden JSON keys:

```text
keep
drop
promote
pass_strategy
expected_profit
account_return
```

### Step 5 — Focused Candidate suite

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

### Step 6 — Upstream SuBing zero-regression

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

### Step 7 — Static/security/diff

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

### Step 8 — Commit test-only deltas

```bash
git add services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m 'test(research): lock candidate validation causality'
```

---

# Task 7 — Docs, Independent Review and Develop Integration

**Lane:** Lane 1 review / Sol / 高 / new independent Review session.

### Step 1 — Update canonical docs narrowly

`TESTING.md` adds exact Candidate Validation tests and notes no real Candidate report during implementation tests.

`docs/ARCHITECTURE.md` adds only:

```text
Candidate Validation V1
→ exact Candidate/Protocol
→ existing SubingLifecycleResearchService
→ MarketDataService
→ Historical Canonical
→ stdout JSON / versioned research report
```

Explicit non-backtest semantics:

```text
no order / position / cost / equity
no DB/Redis persistence
no Alert consumer
```

### Step 2 — Independent implementation Review

Review full branch diff. Required checks:

```text
1 Task 1 real source baseline passed before implementation
2 retrospective is never called OOS
3 prospective starts at trading_day 2026-08-20
4 pre-freeze Bars are causal warm-up only
5 service derives through boundary from injected Protocol
6 Request dataclass does not duplicate Protocol semantics
7 no fold changes Candidate/Policy
8 no duplicated lifecycle/outcome/rank1 math
9 Candidate service has no direct Parquet/Redis/RQData/MarketData path
10 no second CandidateOpportunity/Outcome model
11 no auto KEEP/DROP/PROMOTE
12 existing research CLI zero regression
13 no API/Web/DB/Runtime/Alert expansion
14 temporal boundary proof is source request + existing source filter regression, not impossible aggregate introspection
```

Gate:

```text
Critical=0
Important=0
```

Fix Critical/Important with RED→GREEN and rerun Task 6 verification.

### Step 3 — Update STATUS only after review

Record:

```text
Candidate Validation V1 implementation exists in develop
research_only / Historical-only
Candidate=subing_lifecycle_v2_candidate_v1
prospective OOS begins 2026-08-20
existing jm Shadow baseline preflight succeeded
formal versioned Candidate baseline has NOT been run yet
no strategy validity / promotion / release / Runtime claim
```

### Step 4 — Integrate to develop and read back

```bash
git fetch origin develop
git merge-base --is-ancestor <IMPLEMENTATION_HEAD_SHA> origin/develop
git log -5 --oneline --decorate origin/develop
```

Only after ancestry success remove task worktree/branch. Never touch main/tag/Runtime.

---

# Task 8 — Exact-Develop `jm` Versioned Candidate Baseline

**Lane:** Lane 1 / Sol / 高 / new evidence session.

### Output

```text
reports/research/candidate_validation/
  subing_lifecycle_v2_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-19.json
```

Filename identifies **protocol freeze date**, not execution date. Git commit history is execution provenance.

### Step 1 — New evidence worktree from integrated develop

```bash
git fetch origin develop
git worktree add ../guiyi-subing-candidate-v1-jm-baseline \
  -b research/subing-candidate-v1-jm-baseline origin/develop
cd ../guiyi-subing-candidate-v1-jm-baseline
git status --short
git rev-parse HEAD
```

### Step 2 — Focused preflight tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

### Step 3 — Generate exact report

```bash
mkdir -p reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate subing_lifecycle_v2_candidate_v1 \
  --protocol candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-19 \
  > reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json
```

No RQData update/refresh, DB/Canonical/Redis write, Runtime or notification.

### Step 4 — Validate generated JSON

```bash
python3 - <<'PY'
import json
from pathlib import Path
path = Path(
  'reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/'
  'jm-retrospective-baseline-freeze-2026-08-19.json'
)
p = json.loads(path.read_text())
assert p['schema_version'] == 1
assert p['command'] == 'research.candidate-validation'
assert p['status'] == 'ok'
assert p['readonly'] is True
assert p['research_only'] is True
assert p['candidate_id'] == 'subing_lifecycle_v2_candidate_v1'
assert p['policy_id'] == 'subing_lifecycle_v2_research_v1'
assert p['formula_version'] == 'subing_lifecycle_v2'
assert p['protocol_id'] == 'candidate_validation_v1'
assert p['symbol'] == 'jm'
assert p['retrospective']['since'] == '2023-01-01'
assert p['retrospective']['through'] == '2026-08-18'
assert len(p['rolling_folds']) == 10
assert p['prospective_oos']['status'] == 'pending'
assert p['prospective_oos']['first_trading_day'] == '2026-08-20'
print('candidate baseline contract: PASS')
PY
```

### Step 5 — Forbidden-claim scan

Generated report must not contain auto-decision/profitability fields such as:

```text
historical_oos
backtest_profit
expected_profit
pass_strategy
promotion_approved
```

Then:

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Only the intended report file may be new.

### Step 6 — Commit generated artifact

```bash
git add reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json
git commit -m 'research(subing): add candidate v1 jm retrospective baseline'
```

Do not hand-edit generated metrics and do not update STATUS before Task 9.

---

# Task 9 — Independent Evidence Review and Phase 4B Closeout

**Lane:** Lane 1 review / Sol / 高 / new independent Review session.

### Step 1 — Identity/temporal review

Must confirm:

```text
candidate_id = subing_lifecycle_v2_candidate_v1
policy_id = subing_lifecycle_v2_research_v1
formula_version = subing_lifecycle_v2
protocol_id = candidate_validation_v1
symbol = jm
retrospective through = 2026-08-18
rolling test folds = 10 ending 2026Q2
prospective = pending for --through 2026-08-19
prospective start = trading_day 2026-08-20
```

Any pre-2026-08-20 observation counted as prospective is Critical.

### Step 2 — Completeness review

Required sections:

```text
funnel counts
confirmation source counts
V1/V2 overlap
V2→V1 lead bars
same/cross-day counts
risk/recovery/close reasons
3/5/8 horizon summaries
10 rolling reference/test folds
stability summary
quality flags
```

Partial success report on source failure is Important/Critical depending on semantics.

### Step 3 — Claim review

No profitability, trade readiness, formal Rule readiness, Alert readiness, promotion or Runtime readiness inference.

Allowed conclusion only:

```text
Candidate Validation produced a reproducible retrospective/rolling research baseline for the exact candidate/protocol/symbol/window; this baseline contains no prospective OOS evidence yet.
```

### Step 4 — Gate and STATUS

Require:

```text
Critical=0
Important=0
```

Then update STATUS with exact evidence path, prospective pending state and explicit non-promotion claim.

### Step 5 — Integrate evidence to develop and cleanup

Read back ancestry before removing evidence worktree/branch. Never touch main/tag/Runtime.

---

## Final Acceptance Criteria

Phase 4B V1 is complete only when:

```text
[ ] real-jm existing Lifecycle Shadow preflight passed
[ ] exact Candidate Manifest tracked and strict-loaded
[ ] exact Validation Protocol tracked and strict-loaded
[ ] Request dataclass contains no duplicated Protocol date semantics
[ ] retrospective is never labeled true OOS
[ ] rolling historical stability is exactly 10 frozen-Candidate folds
[ ] prospective source requests start exactly trading_day 2026-08-20
[ ] pre-freeze Bars may warm up existing source but never count as prospective evidence
[ ] service rejects through earlier than injected Protocol retrospective_through
[ ] Candidate service reuses existing SubingLifecycleResearchService only
[ ] no duplicated lifecycle/outcome/rank1/event model
[ ] readonly candidate-validation CLI passes existing research regression
[ ] no API/Web/DB/Redis/worker/Alert/Runtime expansion
[ ] implementation Review Critical=0 / Important=0
[ ] exact-develop `jm` retrospective baseline exists and validates
[ ] evidence Review Critical=0 / Important=0
[ ] STATUS contains only exact research facts
[ ] main/tag/Runtime/Scope/notification/order untouched
```

Successful completion yields only:

```text
允许进入 N 字 Structural Domain V1 设计/实现阶段
```

It does not authorize a new SuBing Alert Rule, Candidate promotion, release/tag or Runtime promotion.

---

## Planning Review Findings Applied

本 Plan 在合并前完成两轮 Review，并已修正以下问题：

1. pre-freeze historical data 全部收口为 retrospective / rolling historical stability；true prospective OOS 从 `2026-08-20` 开始。
2. pre-freeze history 可以作 existing source 的 causal warm-up，但不能回填 prospective evidence。
3. 删除自动 KEEP/DROP/PROMOTE。
4. 删除 V1 第二套 CandidateOpportunity/CandidateOutcome。
5. OOS/rolling/leakage 任务使用 Lane 1 + Sol/high；CLI wiring 单独 Lane 2。
6. 新增 Task 1，先在真实 Canonical 上验证 existing `subing-lifecycle` 的 `jm` baseline。
7. report filename 明确为 protocol freeze provenance，不冒充执行日期。
8. `--through` 边界由 injected Protocol 在 service 中校验，Request dataclass 不重复硬编码协议日期。
9. 删除了无法由 aggregate `SubingLifecycleResearchResult` 实现的“逐 observation 越界检查”；改为 Candidate source-request 边界测试 + existing Lifecycle window-filter regression。
10. rolling fold、CLI dispatch、projection 与 review Gate 均有明确验收；无未定义执行接口。
