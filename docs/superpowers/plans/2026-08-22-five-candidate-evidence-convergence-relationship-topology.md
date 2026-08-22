# Phase 8 — Five-Candidate Evidence Convergence & Relationship Topology V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a deterministic five-Candidate evidence dossier, then freeze a relationship topology that distinguishes existing SuBing↔N event relationships, N→JDJ structural dependencies, exact JDJ↔JDJ same-boundary overlap, and undefined SuBing↔JDJ cross-timeframe relations without ranking Candidates or consuming prospective OOS.

**Architecture:** Phase 8A is artifact-only composition over seven Git-tracked frozen JSON artifacts and executes before any DB Session is opened. Phase 8B is a separate Historical read-only recomputation through the existing `JdjResearchService`: one exact window through `2026-08-19` for N→JDJ dependency and one separate exact window through `2026-08-20` for JDJ overlap. The phases share only bounded artifact verification and deterministic JSON rendering.

**Tech Stack:** Python 3.12, dataclasses, `Decimal`, existing SQLAlchemy Session pattern for Phase 8B only, `MarketDataService → ActualDominantResearchSegmentLoader → JdjResearchService`, pytest, Ruff, Mypy, existing `guiyi research` CLI JSON renderer.

**Spec:** `docs/superpowers/specs/2026-08-22-five-candidate-evidence-convergence-relationship-topology-design.md`

## Global Constraints

- Start each execution segment from the latest `develop`; re-read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, this plan, the spec, and task-related source/tests.
- Candidate order is fixed: `subing_lifecycle_v2_candidate_v1`, `n_structure_5m_candidate_v1`, `jdj_trend_follow_1m_candidate_v1`, `jdj_trend_reentry_6_1m_candidate_v1`, `jdj_key_level_breakout_1m_candidate_v1`.
- Never create a Five-Candidate common retrospective window.
- Phase 8A reads only seven frozen repository artifacts and creates zero DB Sessions, zero MarketDataService objects, zero Candidate runners and zero robustness runners.
- N→JDJ dependency source window is exactly `2023-01-01..2026-08-19`.
- JDJ↔JDJ exact-overlap source window is exactly `2023-01-01..2026-08-20`.
- Never read N `2026-08-20` for N→JDJ dependency and filter it away later.
- Never consume JDJ `2026-08-21` embargo or `2026-08-24+` prospective OOS.
- Do not mutate or backfill any Candidate prospective evidence.
- No new Candidate, formula, parameter, parameter sweep, score, rank, winner, KEEP, DROP, ITERATE, PROMOTE or overlap-conditioned future outcome.
- No backtest/fill/order/position/cost/equity/PnL subsystem.
- No Alert/Scope/Execution Review/Runtime changes; no DB/Canonical/Redis writes; no main/tag/release/Runtime promotion; `auto_order=false` remains fixed.
- Keep `unavailable`, available zero-event and zero-sample as distinct states.
- Tracked Phase 8 evidence must be exact CLI stdout generated only after required verification passes; never hand-edit evidence JSON.
- Task 5 is a hard checkpoint. Phase 8B starts only after Tasks 1–5 are integrated to `develop` and a new worktree/session is created from updated `develop`.

---

## File Structure

### Create

- `data/research_protocols/five_candidate_research_dossier_v1.json`
- `data/research_protocols/five_candidate_relationship_topology_v1.json`
- `services/quant-api/app/research/candidate_convergence/__init__.py`
- `services/quant-api/app/research/candidate_convergence/artifact_source.py`
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- `services/quant-api/app/research/candidate_convergence/jdj_exact_overlap.py`
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py`
- `services/quant-api/tests/test_five_candidate_dossier.py`
- `services/quant-api/tests/test_five_candidate_relationships.py`
- `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`
- `reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json`

### Modify

- `services/quant-api/app/research/composition.py`
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_requests.py`
- `services/quant-api/app/guiyi_cli/research_commands.py`
- `services/quant-api/app/guiyi_cli/research_payloads.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/tests/test_research_cli.py`
- `STATUS.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- `docs/ARCHITECTURE.md`
- `TESTING.md`

---

# Segment A — Phase 8A

## Task 1: Freeze Dossier Protocol and Artifact Integrity

**Lane:** Lane 1 / Sol / high / Plan-then-execute.

**Files:**
- Create: `data/research_protocols/five_candidate_research_dossier_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/__init__.py`
- Create: `services/quant-api/app/research/candidate_convergence/artifact_source.py`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Create: `services/quant-api/tests/test_five_candidate_dossier.py`

**Produces:** `SourceArtifactRef`, `VerifiedJsonArtifact`, `verify_json_artifact`, `FiveCandidateDossierProtocol`, `FiveCandidateDossierRequest`, `load_five_candidate_dossier_protocol`.

**Errors:** `FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID`, `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`.

- [ ] **Step 1: Write RED exact-protocol test**

```python
CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)


def test_dossier_protocol_is_exact() -> None:
    protocol = load_five_candidate_dossier_protocol()
    assert protocol.protocol_id == "five_candidate_research_dossier_v1"
    assert protocol.candidate_order == CANDIDATES
    assert len(protocol.source_artifacts) == 7
    assert len(protocol.comparability_pair_order) == 10
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.prospective_consumed is False
    assert protocol.new_metric_calculation is False
    assert protocol.new_relationship_calculation is False
    assert protocol.parameter_perturbation is False
    assert protocol.automatic_scoring is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False
```

- [ ] **Step 2: Write RED drift tests**

Load the exact protocol JSON, deepcopy it, and independently mutate: extra top-level field, candidate order, pair order, absolute artifact path, `../` path escape, invalid SHA. Each case must raise `FiveCandidateDossierProtocolError`.

- [ ] **Step 3: Run RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: import/collection failure.

- [ ] **Step 4: Implement immutable artifact refs**

```python
@dataclass(frozen=True, slots=True)
class SourceArtifactRef:
    artifact_id: str
    path: str
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedJsonArtifact:
    ref: SourceArtifactRef
    verified_sha256: str
    payload: Mapping[str, object]
```

Reject empty IDs, absolute paths, empty/`.`/`..` path components, control characters and any SHA that is not exactly 64 lowercase hex characters.

- [ ] **Step 5: Implement bounded artifact verification**

```python
root = project_root.resolve()
relative = PurePosixPath(ref.path)
if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
    raise error_type()
try:
    resolved = (root / Path(*relative.parts)).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise error_type()
    raw = resolved.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.expected_sha256:
        raise error_type()
    payload = json.loads(raw.decode("utf-8", errors="strict"))
    if type(payload) is not dict:
        raise error_type()
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise error_type() from None
return VerifiedJsonArtifact(
    ref=ref,
    verified_sha256=ref.expected_sha256,
    payload=MappingProxyType(dict(payload)),
)
```

No public exception text may contain resolved paths, source JSON or mismatch values.

- [ ] **Step 6: Implement exact protocol loader**

Use `load_exact_json` for `five_candidate_research_dossier_v1.json`. `FiveCandidateDossierProtocol.__post_init__` rechecks exact values/order. Copy the seven repo-relative source paths and SHA256 values exactly from the approved spec.

- [ ] **Step 7: Add real-source integrity test**

Verify all seven tracked source artifacts. Assert each verified SHA equals its expected SHA. Patch DB/MDS/Candidate/robustness constructors to fail if invoked.

- [ ] **Step 8: Run GREEN tests/Ruff**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  data/research_protocols/five_candidate_research_dossier_v1.json \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): freeze five-candidate dossier protocol"
```

---

## Task 2: Build Candidate Dossier and Missingness Contracts

**Files:**
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_dossier.py`

**Produces:** `CandidateBaselineEvidence`, `CandidateRobustnessEvidence`, `CandidateDossier`, `FiveCandidateResearchDossier`, `FiveCandidateResearchDossierService`.

**Error:** `FIVE_CANDIDATE_DOSSIER_REPORT_INVALID`.

- [ ] **Step 1: Write RED inventory test**

```python
def test_dossier_has_exact_inventory(service: FiveCandidateResearchDossierService) -> None:
    report = service.run(FiveCandidateDossierRequest("five_candidate_research_dossier_v1"))
    assert len(report.candidate_dossiers) == 5
    assert len(report.source_artifacts) == 7
    assert sum(item.robustness.matrix_cell_count for item in report.candidate_dossiers) == 300
    assert sum(item.robustness.available_symbol_count for item in report.candidate_dossiers) == 245
    assert sum(item.robustness.unavailable_symbol_count for item in report.candidate_dossiers) == 55
```

- [ ] **Step 2: Write RED missingness tests**

Verify exact states:

```text
unavailable → typed reason + count/metric fields null
available zero-event → status available + event_count 0
zero-sample → sample_count 0 + numeric horizon metrics null
```

Illegal hybrids must fail report/source validation.

- [ ] **Step 3: Run RED tests**

Use Task 1 pytest command. Expected: missing report/service types.

- [ ] **Step 4: Implement exact source semantics**

```python
SOURCE_SEMANTICS = {
    "subing_lifecycle_v2_candidate_v1": ("subing_lifecycle", ("5m", "15m"), "5m_ready_boundary", "same_trading_day_only", (3, 5, 8)),
    "n_structure_5m_candidate_v1": ("n_structure", ("5m",), "5m_canonical_bar", "same_rank1_segment", (3, 5, 8)),
    "jdj_trend_follow_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_trend_reentry_6_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_key_level_breakout_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
}
```

- [ ] **Step 5: Implement pure service interfaces**

```text
FiveCandidateResearchDossierService.__init__(
    protocol: FiveCandidateDossierProtocol,
    *,
    project_root: Path = PROJECT_ROOT,
)

FiveCandidateResearchDossierService.run(
    request: FiveCandidateDossierRequest,
) -> FiveCandidateResearchDossier
```

`run` executes exactly: request/protocol identity validation → seven artifact verifications → source semantic identity validation → baseline projection → robustness inventory projection → immutable report construction. It never constructs Session/MDS/provider/Redis/Candidate/robustness services.

- [ ] **Step 6: Add semantic-drift tests with valid fixture SHA**

Mutate candidate ID, protocol ID, retrospective through date, cross-symbol row count and row order. Recompute the fixture SHA for each mutated fixture so semantic validation is exercised after hash validation. Every case fails with `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`.

- [ ] **Step 7: Run GREEN regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): compose five-candidate dossier"
```

---

## Task 3: Freeze Comparability Catalog

**Files:**
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_dossier.py`

**Produces:** `ComparabilityStatus`, `MetricComparability`, 10 `ComparabilityPair` rows, existing SuBing↔N relationship reference projection.

- [ ] **Step 1: Write RED pair-status test**

```python
EXPECTED_PAIR_STATUS = {
    (SUBING, N): "SUPPORTED_EXISTING",
    (SUBING, TF): "NOT_COMPARABLE",
    (SUBING, R6): "NOT_COMPARABLE",
    (SUBING, KLB): "NOT_COMPARABLE",
    (N, TF): "NOT_YET_DEFINED",
    (N, R6): "NOT_YET_DEFINED",
    (N, KLB): "NOT_YET_DEFINED",
    (TF, R6): "SUPPORTED_SAME_FAMILY",
    (TF, KLB): "SUPPORTED_SAME_FAMILY",
    (R6, KLB): "SUPPORTED_SAME_FAMILY",
}
```

Assert exactly 10 unique unordered pairs and no reversed duplicates.

- [ ] **Step 2: Write RED metric-catalog test**

Five-Candidate shared metrics are evidence-completeness only. JDJ event-rate/long-short/3-5-8-20/yearly/sector metrics list exactly the three JDJ Candidates. SuBing/N horizon entries carry `EVALUABLE_UNIT_DIFFERS` and `HORIZON_SEMANTICS_DIFFERS`.

- [ ] **Step 3: Write RED existing relationship-reference test**

Use a frozen `multi_candidate_robustness_v1` fixture. Assert SuBing↔N relationship values/window are projected unchanged. Patch the relationship summarizer to fail if called to prove no recomputation.

- [ ] **Step 4: Implement enum/pair contract**

```python
class ComparabilityStatus(StrEnum):
    SUPPORTED_EXISTING = "SUPPORTED_EXISTING"
    SUPPORTED_SAME_FAMILY = "SUPPORTED_SAME_FAMILY"
    NOT_YET_DEFINED = "NOT_YET_DEFINED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
```

`ComparabilityPair` contains left/right Candidate IDs, status, reason codes and optional existing-relationship reference only.

- [ ] **Step 5: Add forbidden decision-key test**

Reject these recursive report keys:

```python
FORBIDDEN_KEYS = {
    "score", "rank", "winner", "best", "keep", "drop", "iterate",
    "promote", "approved", "expected_profit", "profitability", "pnl",
}
```

- [ ] **Step 6: Run tests and commit**

Run Task 2 test command. Expected: PASS.

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): freeze candidate comparability catalog"
```

---

## Task 4: Add Artifact-Only `candidate-dossier` CLI

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `services/quant-api/tests/test_five_candidate_dossier.py`

**Command:** `guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1`.

**Builder:** `build_five_candidate_dossier_service() -> FiveCandidateResearchDossierService` with no Session argument.

- [ ] **Step 1: Write RED parser/request test**

```python
def test_candidate_dossier_parser_builds_exact_request() -> None:
    args = build_parser().parse_args([
        "research", "candidate-dossier",
        "--protocol", "five_candidate_research_dossier_v1",
    ])
    request = build_research_request(args)
    assert request == FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
```

- [ ] **Step 2: Write RED invalid flag tests**

Reject `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`, and unknown protocol.

- [ ] **Step 3: Write RED zero-Session test**

Create a local fake dossier service returning a valid report. Pass a `session_factory` that immediately calls `pytest.fail`. Dossier CLI must exit 0 without entering Session creation.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: parser/request/factory failures.

- [ ] **Step 5: Implement parser/request/typed command support**

Add exact `candidate-dossier` parser, add `FiveCandidateDossierRequest` to `ResearchRequest`, and add typed dossier dispatch in `research_commands.py`.

- [ ] **Step 6: Branch dossier before the existing Session block**

Add exactly this new branch in `main.py` immediately before the current Session-backed research service selection:

```python
if isinstance(research_request, FiveCandidateDossierRequest):
    service = candidate_dossier_service_factory()
    payload = run_research_command(research_request, service)
else:
    with session_factory() as session:
        # The repository code below this line remains the current concrete
        # research-command service-selection chain, only indented under else.
        pass
```

In the actual repository change, do not commit the comment or `pass`; move the existing concrete `if/elif` service-selection statements unchanged under the `with session_factory()` block. The only new behavior is the dossier branch before Session creation.

- [ ] **Step 7: Implement deterministic dossier payload**

Render protocol/Candidate/artifact/pair order exactly, reuse existing Decimal string rendering, render Decimal zero as `"0"`, and omit full 120/180 source matrices.

- [ ] **Step 8: Add redacted-error test**

Force `FiveCandidateDossierSourceError`; stderr must contain stable public error information and no absolute path, source JSON, source SHA or traceback.

- [ ] **Step 9: Run regressions and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

```bash
git add services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): expose five-candidate dossier CLI"
```

---

## Task 5: Freeze Phase 8A Evidence

**Files:**
- Create: `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`
- Modify: `STATUS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`, `TESTING.md`

- [ ] **Step 1: Run focused regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/test_n_candidate_validation.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS.

- [ ] **Step 2: Run native backend/static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  pytest -q -m "not isolated_postgresql" services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/research services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Any failure blocks evidence generation.

- [ ] **Step 3: Generate dossier twice and compare bytes**

```bash
mkdir -p /private/tmp/guiyi-phase8
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-dossier \
  --protocol five_candidate_research_dossier_v1 \
  > /private/tmp/guiyi-phase8/dossier-1.json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-dossier \
  --protocol five_candidate_research_dossier_v1 \
  > /private/tmp/guiyi-phase8/dossier-2.json

cmp /private/tmp/guiyi-phase8/dossier-1.json /private/tmp/guiyi-phase8/dossier-2.json
```

Expected: exit 0.

- [ ] **Step 4: Verify parsed invariants**

Assert 5 Candidates, 7 source artifacts, 10 comparability pairs, source cells 300, available 245, unavailable 55, `prospective_consumed=false`, and no forbidden decision keys.

- [ ] **Step 5: Track exact stdout and compute SHA**

```bash
mkdir -p reports/research/candidate_dossier/five_candidate_research_dossier_v1
cp /private/tmp/guiyi-phase8/dossier-1.json \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Record the exact SHA in `STATUS.md` and completion output. Task 6 freezes that same SHA.

- [ ] **Step 6: Update canonical docs**

- `STATUS.md`: Phase 8A artifact path/SHA; Phase 8B explicitly incomplete; prospective statuses unchanged.
- `PROJECT_SOURCE.md`: artifact-only dossier boundary and source-specific windows.
- `DECISIONS.md`: no common five-Candidate window; comparability and relationship are distinct.
- `docs/ARCHITECTURE.md`: artifact-only dossier node with no MDS edge.
- `TESTING.md`: exact dossier command and no-side-effect statement.

- [ ] **Step 7: Run docs checks and commit**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

```bash
git add \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze five-candidate dossier evidence"
```

### Segment A Gate

Independent review Tasks 1–5. Fix Critical/Important findings and rerun affected checks. Integrate accepted Segment A into `develop`, verify the commits/artifact in `develop`, clean the task worktree/branch, then start Segment B in a new session/worktree from updated `develop`.

---

# Segment B — Phase 8B

## Task 6: Freeze Relationship Protocol and Report Contracts

**Lane:** Lane 1 / Sol / high / new session / Plan-then-execute.

**Files:**
- Create: `data/research_protocols/five_candidate_relationship_topology_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- Create: `services/quant-api/tests/test_five_candidate_relationships.py`

**Produces:** `RelationshipKind`, `DependencyRole`, `FiveCandidateRelationshipProtocol`, `FiveCandidateRelationshipRequest`, dependency/overlap/report VOs and exact loader.

**Errors:** `FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID`.

- [ ] **Step 1: Verify integrated 8A SHA**

```bash
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Compare with `STATUS.md`. Mismatch blocks Task 6.

- [ ] **Step 2: Write RED exact-window test**

```python
def test_relationship_protocol_has_exact_windows() -> None:
    protocol = load_five_candidate_relationship_protocol()
    assert protocol.n_jdj_since == date(2023, 1, 1)
    assert protocol.n_jdj_through == date(2026, 8, 19)
    assert protocol.jdj_overlap_since == date(2023, 1, 1)
    assert protocol.jdj_overlap_through == date(2026, 8, 20)
    assert protocol.n_jdj_proximity is None
    assert protocol.jdj_overlap_proximity is None
    assert protocol.future_outcomes is False
    assert protocol.prospective_consumed is False
```

- [ ] **Step 3: Write RED protocol-drift tests**

Independently mutate N→JDJ through to `2026-08-20`, overlap through to `2026-08-21`, either proximity to 1, `future_outcomes` to true, pair order, Task 5 dossier SHA, SuBing↔JDJ recompute to true. Each case must fail before JDJ runner use.

- [ ] **Step 4: Run RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: import/collection failure.

- [ ] **Step 5: Implement exact enums**

```python
class RelationshipKind(StrEnum):
    EXISTING_EVENT_RELATIONSHIP = "EXISTING_EVENT_RELATIONSHIP"
    STRUCTURAL_CONTEXT_DEPENDENCY = "STRUCTURAL_CONTEXT_DEPENDENCY"
    EXACT_SAME_BOUNDARY_OVERLAP = "EXACT_SAME_BOUNDARY_OVERLAP"
    UNDEFINED_CROSS_TIMEFRAME = "UNDEFINED_CROSS_TIMEFRAME"


class DependencyRole(StrEnum):
    TREND_FILTER = "trend_filter"
    TREND_AND_PIVOT_SOURCE = "trend_and_pivot_source"
```

- [ ] **Step 6: Implement exact protocol with real Task 5 SHA**

Freeze the actual 8A SHA, the existing SuBing/N robustness path/SHA, exact Candidate/pair order, exact source windows and all disabled safety flags. Do not use a template hash.

- [ ] **Step 7: Implement report invariants**

Require exactly 10 relationship catalog pairs, 180 dependency rows, 180 overlap rows, fixed ordering, and typed unavailable rows with metric fields null.

- [ ] **Step 8: Run GREEN tests/Ruff and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: PASS.

```bash
git add data/research_protocols/five_candidate_relationship_topology_v1.json \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_relationships.py
git commit -m "feat(research): freeze candidate relationship topology protocol"
```

---

## Task 7: Project N → JDJ Structural Dependency

**Files:**
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_relationships.py`

**Produces:** 180 `CandidateDependencyResult` rows.

- [ ] **Step 1: Write RED runner-window test**

Fake runner records calls. Dependency projection must call each active60 symbol exactly once with `since=2023-01-01`, `through=2026-08-19`.

- [ ] **Step 2: Write RED lineage-completeness test**

```python
assert tf.events_with_trend_snapshot_lineage == tf.event_count
assert tf.events_with_exact_pivot_lineage is None
assert r6.events_with_trend_snapshot_lineage == r6.event_count
assert r6.events_with_exact_pivot_lineage is None
assert klb.events_with_trend_snapshot_lineage == klb.event_count
assert klb.events_with_exact_pivot_lineage == klb.event_count
```

Invalid/missing required lineage must fail closed.

- [ ] **Step 3: Write RED unavailable-row test**

`JdjSourceUnavailableError` for one symbol retains three dependency rows for that symbol with typed reason and null metrics.

- [ ] **Step 4: Run RED tests**

Use Task 6 pytest command. Expected: missing service/projection failures.

- [ ] **Step 5: Implement dependency projection**

For each symbol call the runner once for the exact N-safe window. Exact role:

```python
if candidate_id == "jdj_key_level_breakout_1m_candidate_v1":
    role = DependencyRole.TREND_AND_PIVOT_SOURCE
else:
    role = DependencyRole.TREND_FILTER
```

Count lineage only from immutable JDJ events. Do not call N completion events and do not perform temporal proximity joins.

- [ ] **Step 6: Enforce source/error boundary**

Only `JdjSourceUnavailableError` maps to unavailable. `JdjContextError`, wrong batch identity/order/products, or invalid events fail the whole execution.

- [ ] **Step 7: Run regressions and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py
```

Expected: PASS.

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_relationships.py
git commit -m "feat(research): project N-to-JDJ dependency evidence"
```

---

## Task 8: Add JDJ Exact Same-Boundary Overlap

**Files:**
- Create: `services/quant-api/app/research/candidate_convergence/jdj_exact_overlap.py`
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_relationships.py`

**Produces:** `summarize_exact_jdj_overlap(left, right, *, symbol) -> JdjExactOverlapResult`.

- [ ] **Step 1: Write RED exact-key tests**

Events differing in contract, segment start day, trading day, segment bar index or observed_at do not match. Only full-key equality counts.

- [ ] **Step 2: Write RED direction tests**

Same boundary/same direction and same boundary/opposite direction update separate counts only.

- [ ] **Step 3: Write RED unique matched-event tests**

Matched-event counters count unique event IDs, not Cartesian multiplicity. Duplicate event IDs fail validation.

- [ ] **Step 4: Write RED no-future-outcome test**

Two inputs with identical event streams and different `event_outcomes` must produce equal overlap results.

- [ ] **Step 5: Run RED tests**

Use Task 6 pytest command. Expected: missing reducer failures.

- [ ] **Step 6: Implement exact boundary key**

```python
def _boundary(event: JdjTriggerEvent) -> tuple[object, ...]:
    return (
        event.symbol,
        event.contract,
        event.segment_start_trading_day,
        event.trading_day,
        event.segment_bar_index,
        event.observed_at,
    )
```

Index by boundary+direction. Public reducer accepts no proximity, horizon or outcome argument and does not import `PriceDirectionalOutcome`.

- [ ] **Step 7: Add separate overlap-window test**

Overlap orchestration calls every symbol with `2023-01-01..2026-08-20`. This call family must remain separate from the dependency `2023-01-01..2026-08-19` calls.

- [ ] **Step 8: Assert exact 180 overlap rows**

Pair order: `(TF,R6)`, `(TF,KLB)`, `(R6,KLB)`; symbol order active60. Unavailable source retains all three pair rows.

- [ ] **Step 9: Run regressions and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_relationships.py
git commit -m "feat(research): add exact JDJ candidate overlap"
```

---

## Task 9: Add `candidate-relationships` CLI

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `services/quant-api/tests/test_five_candidate_relationships.py`

**Command:** `guiyi research candidate-relationships --protocol five_candidate_relationship_topology_v1`.

**Builder:** `build_five_candidate_relationship_service(session: Session) -> FiveCandidateRelationshipService`.

- [ ] **Step 1: Write RED parser/request tests**

Accept exact protocol only; reject `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`.

- [ ] **Step 2: Write RED Session-backed CLI test**

Use a counting Session context manager and fake relationship service; assert exactly one Session entry. Keep Task 4's dossier no-Session test passing.

- [ ] **Step 3: Write RED composition test**

Patch `build_jdj_research_service(session)` to a sentinel runner and assert it is injected. Patch N research and multi-candidate robustness builders to fail if called.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: parser/factory failures.

- [ ] **Step 5: Implement relationship builder**

Exact order: load relationship protocol → verify Task 5 dossier artifact → verify existing SuBing/N robustness artifact → build one `JdjResearchService(session)` → construct `FiveCandidateRelationshipService`.

- [ ] **Step 6: Add request/dispatch**

Add `FiveCandidateRelationshipRequest` to `ResearchRequest` and dispatch it inside the existing Session-backed research path. Do not move `candidate-dossier` under Session creation.

- [ ] **Step 7: Implement deterministic payload**

Render 10 catalog pairs, 180 dependency rows, 180 overlap rows and typed unavailable rows. Do not serialize source events, full old matrices or future outcomes.

- [ ] **Step 8: Add forbidden-key/redaction tests**

Reject keys: `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote`, `combined_return`, `overlap_return`, `expected_profit`, `pnl`. Errors must not expose source path/content/traceback.

- [ ] **Step 9: Run regressions and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

```bash
git add services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_relationships.py
git commit -m "feat(research): expose candidate relationship topology CLI"
```

---

## Task 10: Freeze Phase 8B Evidence and Close Phase 8

**Files:**
- Create: `reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json`
- Modify: `STATUS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`, `TESTING.md`

- [ ] **Step 1: Run focused Phase 8 regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py \
  services/quant-api/tests/test_jdj_candidate_validation.py \
  services/quant-api/tests/data_foundation/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/test_jdj_robustness.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: PASS.

- [ ] **Step 2: Run full backend/static/engineering checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  pytest -q -m "not isolated_postgresql" services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/research services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Any failure blocks evidence generation.

- [ ] **Step 3: Generate relationship evidence twice and compare bytes**

```bash
mkdir -p /private/tmp/guiyi-phase8
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-relationships \
  --protocol five_candidate_relationship_topology_v1 \
  > /private/tmp/guiyi-phase8/relationships-1.json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api guiyi research candidate-relationships \
  --protocol five_candidate_relationship_topology_v1 \
  > /private/tmp/guiyi-phase8/relationships-2.json

cmp /private/tmp/guiyi-phase8/relationships-1.json \
    /private/tmp/guiyi-phase8/relationships-2.json
```

Expected: exit 0.

- [ ] **Step 4: Verify topology invariants**

Assert exactly 10 relationship catalog rows, 180 dependency rows, 180 overlap rows, `prospective_consumed=false`, N→JDJ window `2023-01-01..2026-08-19`, JDJ overlap window `2023-01-01..2026-08-20`, all SuBing↔JDJ relations undefined, no numeric proximity, exact lineage equality for available dependency rows, and no overlap-conditioned future outcome field.

- [ ] **Step 5: Track stdout and compute SHA**

```bash
mkdir -p reports/research/candidate_relationships/five_candidate_relationship_topology_v1
cp /private/tmp/guiyi-phase8/relationships-1.json \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
```

- [ ] **Step 6: Update canonical docs**

- `STATUS.md`: both Phase 8 artifact paths/SHA; exact windows; prospective statuses remain truthful.
- `PROJECT_SOURCE.md`: convergence + relationship topology as read-only research surfaces.
- `DECISIONS.md`: no common window; N→JDJ dependency is not independent signal confirmation; JDJ overlap is exact-boundary only; SuBing↔JDJ remains undefined.
- `docs/ARCHITECTURE.md`: artifact-only 8A node and two separate 8B Historical windows.
- `TESTING.md`: exact Phase 8A/8B commands and no-side-effect/no-promotion statement.

- [ ] **Step 7: Run docs checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Independent Sol/high review**

Review for N embargo/future leakage, accidental `event_outcomes` use, invented proximity/lead-lag, N→JDJ independence misstatement, missing 180/180 identity rows, automatic ranking/promotion claims, and DB/Canonical/Redis/Alert/Runtime side effects. Fix Critical/Important findings and rerun affected verification.

- [ ] **Step 9: Commit**

```bash
git add \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze phase 8 relationship topology evidence"
```

- [ ] **Step 10: Integrate and clean**

Integrate accepted Segment B to `develop`, confirm Tasks 6–10 are in `develop`, then remove the merged task worktree/branch. Do not touch `main`, tag, release, Runtime, notification or real data/DB mutation.

---

# Codex Scheduling Matrix

| Segment | Tasks | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
|---|---:|---|---|---|---|---|---|---|
| Phase 8A | 1–5 | Lane 1 | Sol | High | new | Plan-then-execute | new task worktree from latest `develop` | independent review before integration |
| Phase 8B | 6–10 | Lane 1 | Sol | High | new after 8A integration | Plan-then-execute | new task worktree from updated `develop` | independent review before integration |

## Worktree Flow

```text
latest develop
  → research/five-candidate-dossier-v1
  → Tasks 1–5
  → independent review
  → integrate develop
  → verify integration
  → cleanup

updated develop
  → research/five-candidate-relationship-topology-v1
  → Tasks 6–10
  → independent Sol/high review
  → integrate develop
  → verify integration
  → cleanup
```

PR is optional under current repository workflow. Neither segment touches `main`, tag or Runtime. Release approval and Runtime promotion remain separate future Gates.

# Task Contract Summary

Every Task ends with:

```text
1. exact scoped diff;
2. RED→GREEN focused tests;
3. relevant regressions;
4. no unrelated refactor;
5. no real write / Runtime / notification side effect;
6. task-scoped commit;
7. completion output: modifications, tests, risks, unresolved items.
```

Task 5 and Task 10 completion outputs additionally include exact evidence SHA256. Evidence does not grant Candidate promotion or release authority.

# Final Acceptance

Phase 8 is complete only when both tracked artifacts exist, deterministic generation is verified, all 300 Phase 8A source identities and all 360 Phase 8B relationship identities are preserved, N/JDJ embargo and prospective boundaries are untouched, and canonical docs describe only evidence convergence/topology facts.

Allowed final verdict after Task 10 review: **允许集成 develop**.

Not allowed from this plan alone: **允许发布 main/tag** or **允许 Runtime promotion**.
