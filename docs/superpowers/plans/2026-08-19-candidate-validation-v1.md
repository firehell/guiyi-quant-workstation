# Candidate Validation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 SuBing V1/V2 公式、Alert、Scope、Runtime 与 Data Foundation 的前提下，先真实运行现有 SuBing Lifecycle Shadow 的 `jm` baseline preflight，再建立首个 research-only Candidate Validation V1：把现有 Shadow 组织为 retrospective baseline、10-fold rolling historical stability、严格冻结边界后的 prospective OOS，并生成版本化 `jm` Candidate evidence report。

**Architecture:** V1 不重建 backtest engine，也不引入 Strategy plugin/registry，更不复制 Lifecycle 的 Opportunity/Outcome 模型。它新增两个 exact Git-tracked artifact（Candidate Manifest + Validation Protocol）、不可变 window/fold/report contracts，以及一个只依赖现有 `SubingLifecycleResearchService` 的 SuBing Candidate adapter；所有窗口继续由 existing Shadow service 经 `MarketDataService` 读取 Historical Canonical。CLI 只输出 stdout JSON，正式 evidence 通过 shell redirection 保存为 Git-tracked report；任何 KEEP/DROP/PROMOTE 都留给人工 Review。

**Tech Stack:** Python 3.13、dataclasses、Decimal、现有 FastAPI 项目 composition/CLI、`SubingLifecycleResearchService` / `MarketDataService`、pytest、Ruff、Mypy、JSON artifacts。

**Spec:** `docs/superpowers/specs/2026-08-19-candidate-validation-v1-design.md`

## Global Constraints

- 每个 Task 开始前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec、上游 `docs/superpowers/specs/2026-08-19-subing-lifecycle-v2-design.md` 与本 Plan；若 active canonical 已改变，先停止并重新评估。
- SuBing V1 的 Factor、Signal、accepted Calibration、same-boundary resolver、`subing_entry_signal_v1`、Alert Rule/Scope/Runtime/Clawbot 零变化。
- SuBing Lifecycle V2 的 exact policy、formula、ConfirmedPivot/Breakout/Retest/lifecycle reducer 零变化；本计划只消费 existing Historical Shadow 结果。
- Phase 4A 先运行 existing `guiyi research subing-lifecycle` 的真实 `jm` baseline preflight；如果真实 Historical Canonical / rank1 / lifecycle source fail-closed，Phase 4B 停止，不在 Candidate Validation 中做 fallback。
- 首个 Candidate 精确为 `subing_lifecycle_v2_candidate_v1`，引用 `subing_lifecycle_v2_research_v1` / `subing_lifecycle_v2`；同 ID 内容漂移必须 fail-closed。
- Validation Protocol 精确为 `candidate_validation_v1`；Candidate validation freeze 为 `2026-08-19T20:57:00+08:00`，第一 eligible prospective OOS trading day 为 `2026-08-20`。
- `2023-01-01..2026-08-18` 只能称为 `retrospective`；历史 rolling 只能称为 `rolling_historical_stability`，不得冒充 true OOS。
- rolling 固定为 12 calendar months reference + 3 calendar months test + 3 months step；第一 test 为 2024Q1，最后 test 为 2026Q2，共 10 folds；fold 内不得调参数、改 Policy 或生成新 Candidate。
- Prospective OOS 可以让 existing Lifecycle Shadow 读取 freeze 前历史 Bars 作为 causal warm-up；只有 `trading_day >= 2026-08-20` 的 observation/outcome 可以被统计为 prospective OOS。
- `candidate-validation --through` 必须 `>= 2026-08-18`；更早日期 fail-closed。`2026-08-18 <= through < 2026-08-20` 时 prospective 必须为 `pending`。
- Validation service 必须只调用 existing `SubingLifecycleResearchService`；不得直接读 Parquet/RQData/Redis、不得创建第二套 rank1 resolver、不得复制 `build_outcomes_at()` 或 lifecycle reducer。
- V1 不创建第二套 `CandidateOpportunity` / `CandidateOutcome` event model；N 字作为第二个真实 Candidate 进入后，再根据两个 producer 的共同需要抽象 event-level contract。
- 不新增 DB/migration、Canonical、Redis candidate state、worker、queue、scheduler、HTTP Candidate API、Web dashboard、Alert Rule、Scope、notification 或 Execution Review 自动入口。
- 不计算或命名账户收益、trade PnL、手续费后收益、equity curve、保证金收益；V1 只复用 3/5/8 Bar directional return / MFE / MAE / EMA21 failure 等 existing research outcomes。
- Report 不自动输出 `KEEP` / `DROP` / `PROMOTE` / `PASS_STRATEGY`；人工判断是 evidence 之后的独立 Gate。
- CLI 继续 `readonly=true` 且只写 stdout；版本化 report 只允许执行任务通过 shell redirection 写入仓库指定路径，不给 CLI 新增任意文件写能力。
- Tasks 2–6 只做仓库代码/测试，不运行真实 Candidate report；Task 7 只做 docs/review/integration；Task 8 才运行 exact-develop 的正式 `jm` Candidate baseline；Task 9 只 Review evidence。
- 任一 Task 不授权 `main`、release/tag、Runtime switch/promotion、开发态 Runtime reload、Scope mutation、真实通知、production DB/Canonical 写入、RQData mutation 或订单。
- 所有 tracked 变更按 `TESTING.md` 运行适用验证，并运行 `python3 scripts/engineering/secret_scan.py --json` 与 `git diff --check`；任何必需检查失败时不得声明完成。

## Codex 调度矩阵

| Task | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Existing `jm` Shadow baseline preflight | Lane 1 | Sol | 高 | 新研究会话 | Plan-then-execute | 临时 research worktree from `develop` | real source completes read-only |
| 2 Exact manifest/protocol + contracts | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 新 implementation worktree | exact loader + contract tests |
| 3 Pure window/fold/report projection | Lane 1 | Sol | 高 | 继续 Task 2 或新会话 | Plan-then-execute | 同 implementation worktree | no duplicated research math |
| 4 SuBing validation orchestration | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 同 implementation worktree | temporal/leakage tests |
| 5 Read-only CLI/composition | Lane 2 | Terra | 中 | 新会话 | Plan-then-execute | 同 implementation worktree | CLI zero-side-effect regression |
| 6 Validation regression / causality suite | Lane 1 | Sol | 高 | 新会话 | Plan-then-execute | 同 implementation worktree | all focused/upstream tests green |
| 7 Docs + independent implementation review | Lane 1 review | Sol | 高 | 新独立 Review 会话 | Review-only | implementation branch/read-only diff | Critical=0 / Important=0 |
| 8 Exact-develop `jm` Candidate baseline | Lane 1 | Sol | 高 | 新研究会话 | Plan-then-execute | 新 evidence worktree from integrated `develop` | exact JSON + read-only checks |
| 9 Evidence review + Phase 4B closeout | Lane 1 review | Sol | 高 | 新独立 Review 会话 | Review-only | evidence branch/read-only diff | Critical=0 / Important=0 |

Lane 说明：OOS / walk-forward / temporal leakage 属于研究语义，因此核心 tasks 使用 Lane 1 + Sol/high，而不是普通 Lane 2 工程。当前没有交易撮合、成本、正式策略公式变化或 promotion，所以不升级为 Lane 3；若实现中出现对 SuBing 公式、成交时序、成本/PnL 或正式 Candidate promotion 的修改需求，立即停止并升级为独立 Lane 3 任务。

## Worktree / Integration Flow

Phase 4A preflight：

```text
latest develop
→ temporary research/subing-shadow-jm-preflight worktree
→ Task 1 read-only Shadow run
→ no tracked change
→ remove clean temporary worktree/branch
```

Candidate implementation：

```text
latest develop after successful preflight
→ research/candidate-validation-v1 task branch/worktree
→ Tasks 2–6
→ Task 7 independent review
→ Critical=0 / Important=0
→ integrate task branch → develop
→ read back develop ancestry
→ remove merged implementation worktree/branch
```

Versioned evidence：

```text
post-integration exact develop
→ research/subing-candidate-v1-jm-baseline branch/worktree
→ Task 8 exact read-only run + tracked JSON report
→ Task 9 independent evidence review
→ integrate evidence branch → develop
→ remove merged evidence worktree/branch
```

任何时候都不得触及 `main`、release worktree、exact-tag Runtime worktree 或 production service state。

---

## File Structure

### Create in Tasks 2–6

- `data/research_candidates/subing_lifecycle_v2_candidate_v1.json` — exact Candidate semantic identity；不保存结果或 promotion 状态。
- `data/research_protocols/candidate_validation_v1.json` — exact freeze、retrospective、rolling 与 prospective OOS protocol。
- `services/quant-api/app/market_data/candidate_validation_policy.py` — strict loaders、immutable `CandidateManifest` / `CandidateValidationProtocol`。
- `services/quant-api/app/market_data/candidate_validation.py` — immutable window/fold/report contracts、pure projection、stability summary、factual quality flags。
- `services/quant-api/app/market_data/subing_candidate_validation_service.py` — 只编排 existing `SubingLifecycleResearchService`。
- `services/quant-api/tests/test_candidate_validation_policy.py`
- `services/quant-api/tests/test_candidate_validation.py`
- `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`

### Modify in Tasks 2–6

- `services/quant-api/app/market_data/composition.py` — load exact artifacts and build Candidate service by reusing existing lifecycle research builder。
- `services/quant-api/app/guiyi_cli/research_parser.py` — add exact `candidate-validation` parser。
- `services/quant-api/app/guiyi_cli/research_commands.py` — request construction + JSON serialization；preserve existing research payloads。
- `services/quant-api/app/guiyi_cli/main.py` — add exact third research factory dispatch，不改变 `data` / `runtime` / existing research behavior。
- `services/quant-api/tests/test_research_cli.py` — parser/dispatch/payload/readonly regression。

### Modify only in Task 7 after executable behavior is green

- `TESTING.md` — add exact Candidate Validation focused commands and read-only evidence command。
- `docs/ARCHITECTURE.md` — add Candidate Validation V1 as Historical research read-model over existing Lifecycle Shadow；不得描述成 backtest engine。
- `STATUS.md` — only after Task 7 review passes；记录 develop-only implementation，明确 real Candidate baseline 尚未运行。

### Create only in Task 8

- `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json` — exact stdout from read-only Candidate Validation command with `--through 2026-08-19`。

### Modify only in Task 9 if evidence truly exists and review passes

- `STATUS.md` — record exact evidence artifact identity and what it does/does not prove；不得写 `Ready` / `promoted` / `profitable`。

No API schema, Web file, DB model, migration, launchd, notification or Runtime config belongs to this plan.

---

# Task 1: Existing SuBing Lifecycle `jm` Shadow Baseline Preflight

**Lane:** Lane 1 — Sol/high. New research session. Read-only Historical source check before building Candidate Validation.

**Files:**
- Read: `STATUS.md`
- Read: `TESTING.md`
- Read: `services/quant-api/app/guiyi_cli/research_parser.py`
- Read: `services/quant-api/app/guiyi_cli/research_commands.py`
- Output only to: `/tmp/subing-lifecycle-jm-preflight-20260818.json`

**Interfaces:**
- Consumes: already released/implemented `guiyi research subing-lifecycle`.
- Produces: `SOURCE_BASELINE_READY` or `SOURCE_BASELINE_BLOCKED`; no Git artifact.

- [ ] **Step 1: Create temporary clean research workspace**

```bash
git fetch origin develop
git worktree add ../guiyi-subing-shadow-jm-preflight \
  -b research/subing-shadow-jm-preflight origin/develop
cd ../guiyi-subing-shadow-jm-preflight
git status --short
git rev-parse HEAD
```

Expected: clean latest `develop` identity.

- [ ] **Step 2: Run existing focused Shadow tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_lifecycle_policy.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/test_subing_lifecycle.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: all pass before real Historical read.

- [ ] **Step 3: Run exact existing `jm` Shadow baseline**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research subing-lifecycle \
  --since 2023-01-01 \
  --through 2026-08-18 \
  --symbol jm \
  > /tmp/subing-lifecycle-jm-preflight-20260818.json
```

This is a read-only Historical research command. Do not run data update/refresh, RQData, Runtime, DB mutation or notification.

- [ ] **Step 4: Validate existing payload contract**

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path('/tmp/subing-lifecycle-jm-preflight-20260818.json')
payload = json.loads(path.read_text())
assert payload['schema_version'] == 1
assert payload['command'] == 'research.subing-lifecycle'
assert payload['status'] == 'ok'
assert payload['readonly'] is True
assert payload['policy_id'] == 'subing_lifecycle_v2_research_v1'
assert payload['products'] == ['jm']
for key in (
    'funnel_counts',
    'confirmation_source_counts',
    'v1_v2_overlap_counts',
    'v2_to_v1_lead_bars',
    'confirmed_trading_day_span_counts',
    'risk_reason_counts',
    'recovery_reason_counts',
    'close_reason_counts',
    'horizon_summary',
):
    assert key in payload, key
assert set(payload['horizon_summary']) == {'3', '5', '8'}
print('SOURCE_BASELINE_READY')
PY
```

- [ ] **Step 5: Stop on real source failure**

If the CLI fails because of rank1 identity, coverage, policy, canonical readability or source contract, output:

```text
SOURCE_BASELINE_BLOCKED
```

Do not continue to Task 2. Fix the original data/lifecycle source in a separate scoped task first.

- [ ] **Step 6: Clean temporary workspace**

No tracked file should change:

```bash
git status --short
cd ..
git worktree remove ./guiyi-subing-shadow-jm-preflight
git branch -d research/subing-shadow-jm-preflight
rm -f /tmp/subing-lifecycle-jm-preflight-20260818.json
```

Expected: no commit and no develop change.

---

# Task 2: Exact Candidate Manifest, Validation Protocol and Immutable Contracts

**Lane:** Lane 1 — Sol/high. New implementation session after Task 1 `SOURCE_BASELINE_READY`.

**Files:**
- Create: `data/research_candidates/subing_lifecycle_v2_candidate_v1.json`
- Create: `data/research_protocols/candidate_validation_v1.json`
- Create: `services/quant-api/app/market_data/candidate_validation_policy.py`
- Create: `services/quant-api/tests/test_candidate_validation_policy.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_policy.py`
- Read: `data/research_policies/subing_lifecycle_v2_research_v1.json`

**Interfaces:**

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
    code = 'CANDIDATE_MANIFEST_INVALID'

class CandidateValidationProtocolError(ValueError):
    code = 'CANDIDATE_VALIDATION_PROTOCOL_INVALID'
```

- [ ] **Step 1: Create implementation worktree**

```bash
git fetch origin develop
git worktree add ../guiyi-candidate-validation-v1 \
  -b research/candidate-validation-v1 origin/develop
cd ../guiyi-candidate-validation-v1
git status --short
git log -5 --oneline --decorate
```

- [ ] **Step 2: Write RED exact-loader tests**

```python
def test_load_exact_candidate_manifest() -> None:
    manifest = load_candidate_manifest()
    assert manifest == CandidateManifest(
        schema_version=1,
        candidate_id='subing_lifecycle_v2_candidate_v1',
        source_kind='subing_lifecycle',
        policy_id='subing_lifecycle_v2_research_v1',
        formula_version='subing_lifecycle_v2',
        research_only=True,
    )


def test_load_exact_validation_protocol() -> None:
    protocol = load_candidate_validation_protocol()
    assert protocol.protocol_id == 'candidate_validation_v1'
    assert protocol.candidate_frozen_at.isoformat() == '2026-08-19T20:57:00+08:00'
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

Also reject missing file, malformed JSON, extra/missing keys, wrong schema, wrong IDs, `research_only=false`, candidate policy/formula drift, naive freeze datetime, retrospective floor before 2023-01-01, fold values other than exact 12/3/3, wrong first/last rolling boundaries, wrong prospective date, horizons other than exact `[3,5,8]`.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py
```

Expected: import/file failure.

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

- [ ] **Step 6: Implement strict loaders**

Use exact nested key sets, project-root default path only, no environment/HTTP override, frozen dataclasses and exact value checks. Representative manifest validation:

```python
if payload != {
    'schema_version': 1,
    'candidate_id': 'subing_lifecycle_v2_candidate_v1',
    'source_kind': 'subing_lifecycle',
    'policy_id': 'subing_lifecycle_v2_research_v1',
    'formula_version': 'subing_lifecycle_v2',
    'research_only': True,
}:
    raise CandidateManifestError()
```

Protocol loader must compare the exact approved nested values before constructing typed dates/datetime.

- [ ] **Step 7: Run GREEN + upstream policy regression**

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

- [ ] **Step 8: Commit Task 2**

```bash
git add \
  data/research_candidates/subing_lifecycle_v2_candidate_v1.json \
  data/research_protocols/candidate_validation_v1.json \
  services/quant-api/app/market_data/candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation_policy.py
git commit -m 'feat(research): freeze candidate validation protocol'
```

---

# Task 3: Pure Candidate Window, Fold and Report Projection

**Lane:** Lane 1 — Sol/high. No I/O and no MarketData access.

**Files:**
- Create: `services/quant-api/app/market_data/candidate_validation.py`
- Create: `services/quant-api/tests/test_candidate_validation.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Read: `services/quant-api/app/market_data/subing_calibration.py`

**Interfaces:**

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

- [ ] **Step 1: Write RED projection tests**

```python
def test_projection_preserves_existing_shadow_metrics_without_recalculation() -> None:
    source = _lifecycle_result(entry_count=4)
    projected = project_lifecycle_window(
        window_id='retrospective',
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
        source=source,
    )
    assert projected.funnel_counts == source.funnel_counts
    assert projected.horizon_summary == source.horizon_summary
    assert projected.confirmation_source_counts == source.confirmation_source_counts
```

Projection may accept existing source mappings, but must copy them into immutable `MappingProxyType` values; later mutation of the source fixture must not mutate the Candidate result.

- [ ] **Step 2: Write RED stability tests**

```python
def test_stability_summary_uses_entry_confirmed_counts_only() -> None:
    folds = (
        _fold('f01', entry_count=0),
        _fold('f02', entry_count=2),
        _fold('f03', entry_count=5),
    )
    summary = summarize_rolling_stability(folds)
    assert summary.fold_count == 3
    assert summary.folds_with_entries == 2
    assert summary.entry_count_min == 0
    assert summary.entry_count_max == 5
    assert summary.entry_count_median == Decimal('2')
```

Also test even-count median, duplicate fold IDs, wrong reference/test kinds, missing exact funnel/horizon keys, invalid window order, `PENDING` with result, `EVALUATED` without result and report identity mismatch.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py
```

- [ ] **Step 4: Implement pure immutable projection**

Do not calculate lifecycle, directional return, MFE, MAE or EMA21 failure here. Copy already-computed values from `SubingLifecycleResearchResult`.

Exact integer median helper:

```python
def _median_count(values: Sequence[int]) -> Decimal:
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[middle])
    return (
        Decimal(ordered[middle - 1]) + Decimal(ordered[middle])
    ) / Decimal(2)
```

Factual quality flags only:

```text
PROSPECTIVE_OOS_PENDING
ROLLING_FOLD_WITHOUT_ENTRY
HORIZON_WITHOUT_SAMPLE
```

No `GOOD` / `BAD` / `PASS` / `PROMOTE` flag.

- [ ] **Step 5: Run GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
```

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  services/quant-api/app/market_data/candidate_validation.py \
  services/quant-api/tests/test_candidate_validation.py
git commit -m 'feat(research): add candidate validation report contracts'
```

---

# Task 4: SuBing Candidate Validation Orchestration and Temporal Isolation

**Lane:** Lane 1 — Sol/high because this task defines retrospective / rolling / prospective OOS semantics.

**Files:**
- Create: `services/quant-api/app/market_data/subing_candidate_validation_service.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Read: `services/quant-api/app/market_data/subing_lifecycle_research_service.py`
- Read: `services/quant-api/app/market_data/candidate_validation.py`
- Read: `services/quant-api/app/market_data/candidate_validation_policy.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CandidateValidationRequest:
    candidate_id: str
    protocol_id: str
    symbol: str
    through: date

class _LifecycleResearchRunner(Protocol):
    def run(
        self,
        request: LifecycleResearchRequest,
    ) -> SubingLifecycleResearchResult: ...

class CandidateValidationSourceError(ValueError):
    code = 'CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE'

class SubingCandidateValidationService:
    def __init__(
        self,
        lifecycle_research: _LifecycleResearchRunner,
        *,
        manifest: CandidateManifest,
        protocol: CandidateValidationProtocol,
    ) -> None: ...

    def run(
        self,
        request: CandidateValidationRequest,
    ) -> CandidateValidationReport: ...
```

- [ ] **Step 1: Write RED request validation tests**

```python
def test_request_normalizes_symbol_and_rejects_pre_retrospective_through() -> None:
    request = CandidateValidationRequest(
        candidate_id='subing_lifecycle_v2_candidate_v1',
        protocol_id='candidate_validation_v1',
        symbol=' JM ',
        through=date(2026, 8, 19),
    )
    assert request.symbol == 'jm'

    with pytest.raises(ValueError, match='CANDIDATE_VALIDATION_WINDOW_INVALID'):
        CandidateValidationRequest(
            candidate_id='subing_lifecycle_v2_candidate_v1',
            protocol_id='candidate_validation_v1',
            symbol='jm',
            through=date(2026, 8, 17),
        )
```

Also reject wrong exact candidate/protocol ID and invalid symbol syntax.

- [ ] **Step 2: Write RED fixed-retrospective test**

Fake lifecycle runner records calls. First source request must always be:

```python
LifecycleResearchRequest(
    since=date(2023, 1, 1),
    through=date(2026, 8, 18),
    symbol='jm',
)
```

Request `through` must not move frozen retrospective/rolling windows.

- [ ] **Step 3: Write RED rolling-fold golden test**

Exact test windows:

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

Reference window for each fold is the immediately preceding 12 calendar months. Assert exactly 20 source calls for rolling windows: 10 reference + 10 test.

- [ ] **Step 4: Write RED prospective boundary tests**

For `through=2026-08-19`:

```text
prospective.status = pending
prospective.result = None
no source call starts at 2026-08-20
```

For `through=2026-08-20`:

```python
LifecycleResearchRequest(
    since=date(2026, 8, 20),
    through=date(2026, 8, 20),
    symbol='jm',
)
```

The existing Lifecycle service may internally read older causal warm-up; Candidate service must never ask it to **count** prospective results before `since=2026-08-20`.

- [ ] **Step 5: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
```

- [ ] **Step 6: Implement calendar helpers without new dependency**

```python
def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    start = _month_start(value)
    absolute = start.year * 12 + (start.month - 1) + months
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)


def _month_end(value: date) -> date:
    return _add_months(value, 1) - timedelta(days=1)
```

Fold generator:

```python
def _rolling_windows(
    protocol: CandidateValidationProtocol,
) -> tuple[tuple[str, date, date, date, date], ...]:
    rows: list[tuple[str, date, date, date, date]] = []
    test_since = protocol.first_test_since
    fold_number = 1
    while test_since <= protocol.last_test_through:
        test_through = _add_months(test_since, protocol.test_months) - timedelta(days=1)
        reference_since = _add_months(test_since, -protocol.reference_months)
        reference_through = test_since - timedelta(days=1)
        rows.append((
            f'fold_{fold_number:02d}',
            reference_since,
            reference_through,
            test_since,
            test_through,
        ))
        test_since = _add_months(test_since, protocol.step_months)
        fold_number += 1
    if len(rows) != 10 or rows[-1][4] != protocol.last_test_through:
        raise ValueError('CANDIDATE_VALIDATION_WINDOW_INVALID')
    return tuple(rows)
```

- [ ] **Step 7: Implement service orchestration**

Core flow:

```python
def run(self, request: CandidateValidationRequest) -> CandidateValidationReport:
    self._validate_request_identity(request)

    retrospective_source = self._run_source(
        self._protocol.retrospective_since,
        self._protocol.retrospective_through,
        request.symbol,
    )
    retrospective = project_lifecycle_window(
        window_id='retrospective',
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=self._protocol.retrospective_since,
        through=self._protocol.retrospective_through,
        source=retrospective_source,
    )

    folds = tuple(self._run_fold(row, request.symbol) for row in _rolling_windows(self._protocol))

    if request.through < self._protocol.prospective_oos_first_trading_day:
        prospective = ProspectiveOosResult(
            status=ProspectiveOosStatus.PENDING,
            first_trading_day=self._protocol.prospective_oos_first_trading_day,
            through=request.through,
            result=None,
        )
    else:
        source = self._run_source(
            self._protocol.prospective_oos_first_trading_day,
            request.through,
            request.symbol,
        )
        prospective = ProspectiveOosResult(
            status=ProspectiveOosStatus.EVALUATED,
            first_trading_day=self._protocol.prospective_oos_first_trading_day,
            through=request.through,
            result=project_lifecycle_window(
                window_id='prospective_oos',
                window_kind=CandidateWindowKind.PROSPECTIVE_OOS,
                since=self._protocol.prospective_oos_first_trading_day,
                through=request.through,
                source=source,
            ),
        )

    return self._report(request, retrospective, folds, prospective)
```

`_run_source()` catches source-domain failures and raises `CandidateValidationSourceError` without returning partial report.

- [ ] **Step 8: Run GREEN + source regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/test_candidate_validation.py
```

- [ ] **Step 9: Commit Task 4**

```bash
git add \
  services/quant-api/app/market_data/subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py
git commit -m 'feat(research): validate SuBing candidate windows'
```

---

# Task 5: Read-only `guiyi research candidate-validation` and Composition Wiring

**Lane:** Lane 2 — Terra/medium. Only wire already-approved research semantics.

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**

```text
guiyi research candidate-validation
  --candidate subing_lifecycle_v2_candidate_v1
  --protocol candidate_validation_v1
  --symbol jm
  --through YYYY-MM-DD
```

- [ ] **Step 1: Write parser RED test**

```python
def test_candidate_validation_parser_builds_exact_request() -> None:
    args = build_parser().parse_args([
        'research',
        'candidate-validation',
        '--candidate', 'subing_lifecycle_v2_candidate_v1',
        '--protocol', 'candidate_validation_v1',
        '--symbol', 'jm',
        '--through', '2026-08-19',
    ])
    assert build_research_request(args) == CandidateValidationRequest(
        candidate_id='subing_lifecycle_v2_candidate_v1',
        protocol_id='candidate_validation_v1',
        symbol='jm',
        through=date(2026, 8, 19),
    )
```

Parser choices for candidate/protocol are exact single-value choices.

- [ ] **Step 2: Write JSON payload RED test**

Required top-level shape:

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

Nested horizon Decimal values reuse existing `_horizon_payload()` and remain strings, not float.

- [ ] **Step 3: Write main dispatch RED test**

Exact routing:

```text
subing-calibration   -> research_service_factory
subing-lifecycle     -> lifecycle_research_service_factory
candidate-validation -> candidate_validation_service_factory
```

No broad fallback may route unknown research commands into calibration.

- [ ] **Step 4: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py
```

- [ ] **Step 5: Add composition paths and builder**

```python
_CANDIDATE_MANIFEST = (
    PROJECT_ROOT / 'data/research_candidates/subing_lifecycle_v2_candidate_v1.json'
)
_CANDIDATE_VALIDATION_PROTOCOL = (
    PROJECT_ROOT / 'data/research_protocols/candidate_validation_v1.json'
)


def build_subing_candidate_validation_service(
    session: Session,
) -> SubingCandidateValidationService:
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(_CANDIDATE_MANIFEST),
        protocol=load_candidate_validation_protocol(_CANDIDATE_VALIDATION_PROTOCOL),
    )
```

This deliberately reuses the existing lifecycle builder rather than creating another `MarketDataService` path.

- [ ] **Step 6: Add exact parser**

```python
candidate = commands.add_parser('candidate-validation')
candidate.add_argument(
    '--candidate',
    choices=('subing_lifecycle_v2_candidate_v1',),
    required=True,
)
candidate.add_argument(
    '--protocol',
    choices=('candidate_validation_v1',),
    required=True,
)
candidate.add_argument('--symbol', required=True)
candidate.add_argument('--through', required=True)
```

`build_research_request()` constructs `CandidateValidationRequest`; its validation enforces `through >= 2026-08-18`.

- [ ] **Step 7: Add serializer and exact main dispatch**

Extend `ResearchRequest` union to include `CandidateValidationRequest`. In `main()` add a new factory defaulted to `build_subing_candidate_validation_service` and dispatch explicitly:

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

- [ ] **Step 8: Run GREEN + existing CLI zero regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py \
  services/quant-api/tests/data_foundation/test_subing_calibration_service.py
```

- [ ] **Step 9: Commit Task 5**

```bash
git add \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_research_cli.py
git commit -m 'feat(cli): expose candidate validation research'
```

---

# Task 6: Temporal Leakage, Determinism and Full Candidate Validation Regression

**Lane:** Lane 1 — Sol/high.

**Files:**
- Modify: `services/quant-api/tests/test_candidate_validation.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Read/run: existing SuBing lifecycle/calibration/read-service tests from `TESTING.md`.

**Interfaces:**
- Consumes: Tasks 2–5 implementation.
- Produces: proof that Candidate Validation adds no look-ahead, no OOS relabeling and no V1/V2 regression.

- [ ] **Step 1: Lock all 10 rolling test windows**

Assert exact sequence listed in Task 4 and exact 12-month reference boundaries. Also assert protocol generates exactly 10 folds.

- [ ] **Step 2: Prove pre-freeze observations cannot enter prospective OOS**

Use a fake source where observations exist on both `2026-08-19` and `2026-08-20`. Candidate service must request prospective source only with:

```text
since = 2026-08-20
```

The existing lifecycle runner may internally consume earlier causal warm-up, but its result window must count only request range. If a fake runner returns an observation outside request range, the candidate adapter should reject the malformed source fixture rather than silently include it.

- [ ] **Step 3: Prove same-prefix determinism**

Run the same fake request twice and assert complete report dataclass equality. Add future source data after the original `through`, rerun with original `through`, and assert the original report is unchanged.

- [ ] **Step 4: Prove no auto-decision contract**

Serialized JSON must not contain keys:

```text
keep
drop
promote
pass_strategy
expected_profit
account_return
```

Quality flags are limited to the approved factual set.

- [ ] **Step 5: Run focused Candidate suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

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

- [ ] **Step 7: Run static/security/diff checks**

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

- [ ] **Step 8: Commit only Task 6 regression additions**

```bash
git add \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m 'test(research): lock candidate validation causality'
```

---

# Task 7: Canonical Docs, Independent Implementation Review and Develop Integration

**Lane:** Lane 1 review — Sol/high, new independent Review session.

**Files:**
- Modify: `TESTING.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify only after all verification/review gates pass: `STATUS.md`
- Review: complete implementation diff from task branch base to HEAD.

**Interfaces:**
- Consumes: Tasks 2–6 green implementation.
- Produces: reviewed develop-only Candidate Validation implementation; real Candidate baseline is still not produced.

- [ ] **Step 1: Add exact `TESTING.md` commands**

Document Candidate Validation as Historical-only and list:

```text
test_candidate_validation_policy.py
test_candidate_validation.py
data_foundation/test_subing_candidate_validation_service.py
test_research_cli.py
upstream SuBing regressions
Ruff / Mypy / secret_scan / diff check
```

State explicitly that implementation tests do not run real `jm` Candidate report or write DB/Canonical/Redis/Runtime/notification.

- [ ] **Step 2: Update architecture narrowly**

Add:

```text
Candidate Validation V1
→ exact Candidate/Protocol artifacts
→ existing SubingLifecycleResearchService
→ MarketDataService
→ Historical Canonical
→ stdout JSON / versioned research report
```

State:

```text
not a backtest engine
no order/position/cost/equity semantics
no DB/Redis persistence
no Alert consumer
```

- [ ] **Step 3: Commit docs except STATUS**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add TESTING.md docs/ARCHITECTURE.md
git commit -m 'docs(research): document candidate validation v1'
```

- [ ] **Step 4: Independent Review checklist**

Reviewer must verify:

```text
1. Task 1 real source baseline succeeded before implementation
2. retrospective is never called OOS
3. prospective starts exactly trading_day 2026-08-20
4. pre-freeze bars are warm-up only, never prospective observations
5. --through < 2026-08-18 fails
6. no fold modifies candidate/policy
7. no duplicated SuBing/lifecycle/outcome/rank1 math
8. no direct Parquet/Redis/RQData/MarketData bypass in candidate service
9. no dynamic candidate/protocol parameters
10. no second CandidateOpportunity/Outcome event model
11. no auto KEEP/DROP/PROMOTE
12. existing research CLI commands remain unchanged
13. no API/Web/DB/Runtime/Alert surface expansion
14. all fail-closed paths have tests
```

Classify findings as `Critical / Important / Minor`.

Integration gate:

```text
Critical = 0
Important = 0
```

Any Critical/Important finding is fixed with RED→GREEN regression before continuing.

- [ ] **Step 5: Re-run all Task 6 verification after review fixes**

Do not rely on pre-review results if source changed.

- [ ] **Step 6: Update STATUS accurately**

Only after review/tests pass, record:

```text
Candidate Validation V1 develop implementation exists
research_only / Historical-only
first candidate = subing_lifecycle_v2_candidate_v1
true prospective OOS starts 2026-08-20
existing jm Shadow baseline preflight succeeded
formal versioned Candidate baseline has NOT been run yet
no strategy validity / promotion / release / Runtime claim
```

- [ ] **Step 7: Commit STATUS**

```bash
git add STATUS.md
git commit -m 'docs(status): record candidate validation implementation'
```

- [ ] **Step 8: Integrate implementation branch to develop**

Use ordinary repository develop integration. If using PR, target `develop`, never `main`.

Read back:

```bash
git fetch origin develop
git merge-base --is-ancestor <IMPLEMENTATION_HEAD_SHA> origin/develop
git log -5 --oneline --decorate origin/develop
```

- [ ] **Step 9: Clean implementation worktree/branch only after ancestry success**

```bash
git worktree remove ../guiyi-candidate-validation-v1
git branch -d research/candidate-validation-v1
```

---

# Task 8: Exact-Develop `jm` Versioned Candidate Baseline

**Lane:** Lane 1 research — Sol/high, new evidence session and worktree from the exact post-Task-7 `develop`.

**Files:**
- Create: `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json`
- Read: exact Candidate Manifest / Validation Protocol / `STATUS.md`
- Execute: read-only `guiyi research candidate-validation`

**Interfaces:**
- Consumes: reviewed Candidate Validation implementation already in develop + Historical Canonical through existing Lifecycle Shadow.
- Produces: first versioned `jm` retrospective/rolling Candidate report; prospective OOS must be `pending` because command is frozen at `--through 2026-08-19`.

- [ ] **Step 1: Create evidence worktree from exact integrated develop**

```bash
git fetch origin develop
git worktree add ../guiyi-subing-candidate-v1-jm-baseline \
  -b research/subing-candidate-v1-jm-baseline origin/develop
cd ../guiyi-subing-candidate-v1-jm-baseline
git status --short
git rev-parse HEAD
```

Record exact develop commit in task output. Git history of the report commit is the implementation lineage; do not add Git SHA to Candidate semantic identity.

- [ ] **Step 2: Run Candidate preflight tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_candidate_validation_policy.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_research_cli.py
```

Failure blocks report generation.

- [ ] **Step 3: Create exact output directory**

```bash
mkdir -p \
  reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1
```

- [ ] **Step 4: Run one exact baseline command**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api guiyi research candidate-validation \
  --candidate subing_lifecycle_v2_candidate_v1 \
  --protocol candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-19 \
  > reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json
```

No RQData update/refresh, DB/Canonical/Redis write, Runtime load or notification is part of this command.

- [ ] **Step 5: Validate exact JSON contract**

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path(
    'reports/research/candidate_validation/'
    'subing_lifecycle_v2_candidate_v1/'
    'jm-retrospective-baseline-freeze-2026-08-19.json'
)
payload = json.loads(path.read_text())
assert payload['schema_version'] == 1
assert payload['command'] == 'research.candidate-validation'
assert payload['status'] == 'ok'
assert payload['readonly'] is True
assert payload['research_only'] is True
assert payload['candidate_id'] == 'subing_lifecycle_v2_candidate_v1'
assert payload['policy_id'] == 'subing_lifecycle_v2_research_v1'
assert payload['formula_version'] == 'subing_lifecycle_v2'
assert payload['protocol_id'] == 'candidate_validation_v1'
assert payload['symbol'] == 'jm'
assert payload['retrospective']['since'] == '2023-01-01'
assert payload['retrospective']['through'] == '2026-08-18'
assert len(payload['rolling_folds']) == 10
assert payload['prospective_oos']['status'] == 'pending'
assert payload['prospective_oos']['first_trading_day'] == '2026-08-20'
print('candidate baseline contract: PASS')
PY
```

- [ ] **Step 6: Check forbidden claims**

```bash
python3 - <<'PY'
from pathlib import Path
text = Path(
    'reports/research/candidate_validation/'
    'subing_lifecycle_v2_candidate_v1/'
    'jm-retrospective-baseline-freeze-2026-08-19.json'
).read_text().lower()
for forbidden in (
    'historical_oos',
    'backtest_profit',
    'expected_profit',
    'pass_strategy',
    'promotion_approved',
):
    assert forbidden not in text, forbidden
print('candidate evidence semantics: PASS')
PY
```

- [ ] **Step 7: Run secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: only the intended report file is new; secret findings 0.

- [ ] **Step 8: Commit exact generated artifact without hand editing metrics**

```bash
git add \
  reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json
git commit -m 'research(subing): add candidate v1 jm retrospective baseline'
```

Do not update `STATUS.md` until Task 9 evidence review passes.

---

# Task 9: Independent Evidence Review and Phase 4B Closeout

**Lane:** Lane 1 review — Sol/high, new independent Review session.

**Files:**
- Review: exact Task 8 JSON artifact + implementation Spec/Plan + source contracts.
- Modify only after evidence review passes: `STATUS.md`

**Interfaces:**
- Consumes: exact Candidate baseline artifact.
- Produces: reviewed evidence quality conclusion only; not Candidate promotion.

- [ ] **Step 1: Review identity and temporal semantics**

Confirm:

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

Any pre-2026-08-20 observation counted under prospective OOS is Critical.

- [ ] **Step 2: Review evidence completeness**

Artifact must contain:

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

Missing required section is Important unless the source is correctly unavailable—in that case the run should have failed rather than emitted partial success.

- [ ] **Step 3: Review claims**

Report and STATUS must not infer:

```text
profitability
trade readiness
formal Rule readiness
Alert readiness
promotion approval
Runtime readiness
```

Allowed conclusion only:

```text
Candidate Validation infrastructure produced a reproducible retrospective/rolling research baseline for the exact candidate/protocol/symbol/window; prospective OOS has not yet produced evidence in this baseline artifact.
```

- [ ] **Step 4: Record Review result**

Integration gate:

```text
Critical = 0
Important = 0
```

Semantic fixes require regenerating the report from the exact command; never hand-edit generated metrics.

- [ ] **Step 5: Update STATUS after accepted evidence**

Record exact facts:

```text
Candidate Validation V1 implementation is in develop
existing jm Shadow preflight succeeded
first jm retrospective/rolling Candidate baseline artifact exists at the exact path
prospective OOS is still pending for --through 2026-08-19
next eligible prospective observations start trading_day 2026-08-20
no Candidate effectiveness or promotion conclusion has been made
```

- [ ] **Step 6: Commit STATUS closeout**

```bash
git add STATUS.md
git commit -m 'docs(status): record candidate validation baseline'
```

- [ ] **Step 7: Integrate evidence branch to develop and read back**

```bash
git fetch origin develop
git merge-base --is-ancestor <EVIDENCE_HEAD_SHA> origin/develop
git log -5 --oneline --decorate origin/develop
```

- [ ] **Step 8: Clean evidence workspace only after ancestry success**

```bash
git worktree remove ../guiyi-subing-candidate-v1-jm-baseline
git branch -d research/subing-candidate-v1-jm-baseline
```

---

## Final Acceptance Criteria

Phase 4B V1 is complete only when all are true:

```text
[ ] existing real-jm Lifecycle Shadow baseline preflight completed successfully
[ ] exact Candidate Manifest is tracked and strict-loaded
[ ] exact Validation Protocol is tracked and strict-loaded
[ ] historical retrospective is never labeled true OOS
[ ] rolling historical stability is exactly 10 folds with frozen Candidate semantics
[ ] prospective OOS starts at trading_day 2026-08-20 and cannot backfill earlier observations
[ ] freeze-preceding Bars may be causal warm-up but are never counted as prospective evidence
[ ] --through < 2026-08-18 fails closed
[ ] Candidate service reuses existing SubingLifecycleResearchService only
[ ] no duplicated lifecycle/outcome/rank1/event model exists
[ ] candidate-validation CLI is read-only and existing research CLI is unchanged
[ ] no API/Web/DB/Redis/worker/Alert/Runtime surface was added
[ ] implementation Review Critical=0 / Important=0
[ ] exact-develop jm retrospective baseline JSON exists and validates
[ ] evidence Review Critical=0 / Important=0
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

## Planning Review Summary

本 Plan 已在提交前完成自审并修正：

- 历史窗口统一收口为 retrospective / rolling historical stability，true prospective OOS 从 `2026-08-20` 开始；
- 明确 pre-freeze history 只可作为 causal warm-up，不能回填 prospective evidence；
- 删除最初讨论中的自动 KEEP/DROP/PROMOTE；
- 删除 V1 的第二套 CandidateOpportunity/CandidateOutcome event abstraction；
- 将 OOS/walk-forward/leakage 核心任务从 Lane 2 修正为 Lane 1 + Sol/high；
- 新增 Task 1：先真实运行 existing `subing-lifecycle` 的 `jm` baseline preflight；
- 报告文件名改为 freeze provenance，不把协议冻结日期伪装成实际运行日期；
- `--through` 增加 `>= 2026-08-18` 的明确 fail-closed 边界；
- rolling fold 日历算法、CLI dispatch 和 report projection 接口已逐项对齐，未发现跨 Task 命名冲突；
- placeholder 扫描不允许 `TBD` / `TODO` / 未定义接口。
