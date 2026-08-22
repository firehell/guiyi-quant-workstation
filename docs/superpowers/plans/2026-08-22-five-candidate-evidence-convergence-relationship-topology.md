# Phase 8 — Five-Candidate Evidence Convergence & Relationship Topology V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a deterministic five-Candidate evidence dossier, then freeze a relationship topology that distinguishes existing SuBing↔N event relationships, N→JDJ structural dependencies, exact JDJ↔JDJ same-boundary overlap, and undefined SuBing↔JDJ cross-timeframe relations without ranking Candidates or consuming prospective OOS.

**Architecture:** Phase 8A is artifact-only composition over seven Git-tracked frozen JSON artifacts and must execute before any DB Session is opened. Phase 8B is a separate Historical read-only recomputation using the existing `JdjResearchService`: one exact window through `2026-08-19` for N→JDJ dependency and a separate exact window through `2026-08-20` for JDJ overlap. The two phases share only small exact contract/artifact helpers and deterministic JSON rendering; they do not create a general research platform or persistence layer.

**Tech Stack:** Python 3.12, dataclasses / `Decimal`, FastAPI repository conventions, SQLAlchemy Session only for Phase 8B composition, existing `MarketDataService` → `ActualDominantResearchSegmentLoader` → `JdjResearchService`, pytest, Ruff, Mypy, existing `guiyi research` CLI JSON renderer.

**Spec:** `docs/superpowers/specs/2026-08-22-five-candidate-evidence-convergence-relationship-topology-design.md`

## Global Constraints

- Implement against the latest `develop`; before every execution segment re-read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, the spec above, and task-related source/tests.
- Exact Candidate order: `subing_lifecycle_v2_candidate_v1`, `n_structure_5m_candidate_v1`, `jdj_trend_follow_1m_candidate_v1`, `jdj_trend_reentry_6_1m_candidate_v1`, `jdj_key_level_breakout_1m_candidate_v1`.
- Never invent a Five-Candidate common retrospective window.
- Phase 8A reads only seven frozen repository artifacts; it must create zero DB Sessions and zero MarketDataService / Candidate / robustness runners.
- Phase 8B N→JDJ dependency source window is exactly `2023-01-01..2026-08-19`; do not read `2026-08-20` and filter it away afterward.
- Phase 8B JDJ↔JDJ overlap source window is exactly `2023-01-01..2026-08-20`.
- Do not consume JDJ `2026-08-21` embargo or `2026-08-24+` prospective OOS; do not backfill or mutate any Candidate prospective result.
- No new Candidate, formula, parameter, parameter sweep, automatic score/rank/winner, KEEP/DROP/ITERATE/PROMOTE, or overlap-conditioned future outcome.
- No backtest/fill/order/position/cost/equity/PnL subsystem.
- No Alert/Scope/Execution Review/Runtime changes; no DB/Canonical/Redis writes; no main/tag/release/Runtime promotion; `auto_order=false` remains fixed.
- `unavailable`, available zero-event, and zero-sample are distinct states and must never be collapsed.
- All tracked Phase 8 evidence is exact CLI stdout generated after tests pass; never hand-edit evidence JSON.
- Ordinary task commits may integrate to `develop` after required tests/review. Task 5 is a mandatory checkpoint: Phase 8B starts only after Phase 8A is integrated to an updated `develop` and a new task worktree/session is created.

---

## File Structure

### New files

- `data/research_protocols/five_candidate_research_dossier_v1.json` — exact Phase 8A protocol.
- `data/research_protocols/five_candidate_relationship_topology_v1.json` — exact Phase 8B protocol, created only after Task 5 evidence SHA is known.
- `services/quant-api/app/research/candidate_convergence/__init__.py` — package marker only.
- `services/quant-api/app/research/candidate_convergence/artifact_source.py` — bounded repo-relative artifact path + SHA256 + UTF-8/JSON-object verifier shared by 8A/8B.
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py` — 8A protocol/request/report/value contracts and invariants.
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py` — pure seven-artifact projection.
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py` — 8B protocol/request/report/value contracts and invariants.
- `services/quant-api/app/research/candidate_convergence/jdj_exact_overlap.py` — pure exact-boundary pair reducer; no proximity/future outcome.
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py` — 8B orchestration over two separate JDJ batch windows plus existing frozen relationship reference.
- `services/quant-api/tests/test_five_candidate_dossier.py` — 8A protocol/report/artifact/service tests.
- `services/quant-api/tests/test_five_candidate_relationships.py` — 8B protocol/report/dependency/overlap tests.
- `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json` — Task 5 exact evidence.
- `reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json` — Task 10 exact evidence.

### Existing files modified

- `services/quant-api/app/research/composition.py` — one no-Session dossier builder and one Session-based relationship builder.
- `services/quant-api/app/guiyi_cli/research_parser.py` — `candidate-dossier` and `candidate-relationships` exact protocol parsers.
- `services/quant-api/app/guiyi_cli/research_requests.py` — add the two immutable request types to `ResearchRequest` and build them.
- `services/quant-api/app/guiyi_cli/research_commands.py` — typed dispatch for the two new report types.
- `services/quant-api/app/guiyi_cli/research_payloads.py` — deterministic payload renderers.
- `services/quant-api/app/guiyi_cli/main.py` — branch `candidate-dossier` before `session_factory()`; keep `candidate-relationships` inside the Historical read-only Session path.
- `services/quant-api/tests/test_research_cli.py` — parser/dispatch/no-Session/session-based/redaction/determinism contracts.
- `STATUS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`, `TESTING.md` — Task 5/10 canonical closeout only after exact evidence exists.

---

# Execution Segment A — Phase 8A

## Task 1: Freeze Dossier Protocol and Artifact Integrity

**Lane:** Lane 1, Sol, high reasoning, Plan-then-execute.

**Files:**
- Create: `data/research_protocols/five_candidate_research_dossier_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/__init__.py`
- Create: `services/quant-api/app/research/candidate_convergence/artifact_source.py`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Create: `services/quant-api/tests/test_five_candidate_dossier.py`

**Interfaces:**
- Produces: `SourceArtifactRef`, `VerifiedJsonArtifact`, `verify_json_artifact()`, `FiveCandidateDossierProtocol`, `FiveCandidateDossierRequest`, `load_five_candidate_dossier_protocol()`.
- Error codes: `FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID`, `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`.
- Consumes: `PROJECT_ROOT`, existing exact JSON protocol-loader conventions, seven frozen artifact identities from the spec.

- [ ] **Step 1: Write RED tests for exact protocol values and ordering**

Add tests that lock Candidate order, seven artifact order/path/SHA, ten unordered pair order, all safety booleans, and `prospective_consumed=false`.

```python
CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)


def test_dossier_protocol_is_exact_and_readonly() -> None:
    protocol = load_five_candidate_dossier_protocol()
    assert protocol.protocol_id == "five_candidate_research_dossier_v1"
    assert protocol.candidate_order == CANDIDATES
    assert len(protocol.source_artifacts) == 7
    assert len(protocol.comparability_pair_order) == 10
    assert protocol.prospective_consumed is False
    assert protocol.new_metric_calculation is False
    assert protocol.new_relationship_calculation is False
    assert protocol.automatic_scoring is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False
```

- [ ] **Step 2: Write RED mutation tests for protocol and artifact refs**

Use `tmp_path` copies to mutate missing/extra fields, candidate order, pair order, absolute path, `../` escape, SHA format, and one source path.

```python
@pytest.mark.parametrize(
    "mutation",
    ("extra_field", "candidate_order", "pair_order", "absolute_path", "path_escape", "sha"),
)
def test_dossier_protocol_drift_fails_closed(tmp_path: Path, mutation: str) -> None:
    payload = json.loads(PROTOCOL.read_text())
    mutated = deepcopy(payload)
    # mutate exactly one frozen field per case
    ...
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(path)
```

Replace the `...` in the committed test with concrete branches for all six mutations; do not leave ellipsis in repository code.

- [ ] **Step 3: Run the RED tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: collection/import failures because the new package/contracts do not exist.

- [ ] **Step 4: Implement bounded artifact verification**

`artifact_source.py` must expose the following contract:

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


def verify_json_artifact(
    ref: SourceArtifactRef,
    *,
    project_root: Path,
    error_type: type[Exception],
) -> VerifiedJsonArtifact:
    ...
```

The implementation must:

```text
PurePosixPath(ref.path).is_absolute() == False
".." not in path.parts
resolved = (project_root / ref.path).resolve(strict=True)
resolved.is_relative_to(project_root.resolve()) == True
resolved.is_file() == True
sha256(raw_bytes).hexdigest() == expected_sha256
raw_bytes.decode("utf-8", errors="strict")
json.loads(text) is dict
```

On any `OSError`, decode error, JSON error, path escape, hash mismatch, or non-object root, raise the caller-provided stable error without leaking content/path details.

- [ ] **Step 5: Implement exact dossier protocol loader**

Use `load_exact_json()` for the protocol itself. `FiveCandidateDossierProtocol.__post_init__()` must validate all frozen values and ordering a second time so direct construction cannot bypass the file loader.

The seven exact refs are the paths/SHA values from the spec. Protocol JSON must contain only repo-relative paths.

- [ ] **Step 6: Add real-source verification test**

The test loads all seven current tracked source artifacts through `verify_json_artifact()` and asserts `verified_sha256 == expected_sha256`; it must not parse DB/Catalog or call source services.

- [ ] **Step 7: Run Task 1 tests and static checks**

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

- [ ] **Step 8: Commit Task 1**

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

**Interfaces:**
- Consumes: Task 1 `FiveCandidateDossierProtocol`, `VerifiedJsonArtifact`.
- Produces: `CandidateDossier`, `CandidateBaselineEvidence`, `CandidateRobustnessEvidence`, `MetricComparability`, `ComparabilityPair`, `FiveCandidateResearchDossier`, `FiveCandidateResearchDossierService.run(FiveCandidateDossierRequest)`.
- Report error: `FIVE_CANDIDATE_DOSSIER_REPORT_INVALID`.

- [ ] **Step 1: Write RED report-shape tests**

Lock exact five-Candidate order, seven verified sources, per-Candidate baseline/robustness identities, and exact 300 source-cell inventory.

```python
def test_dossier_has_exact_candidate_and_source_inventory(service) -> None:
    report = service.run(FiveCandidateDossierRequest("five_candidate_research_dossier_v1"))
    assert report.candidate_order == CANDIDATES
    assert len(report.source_artifacts) == 7
    assert len(report.candidate_dossiers) == 5
    assert sum(item.robustness.matrix_cell_count for item in report.candidate_dossiers) == 300
    assert sum(item.robustness.available_symbol_count for item in report.candidate_dossiers) == 245
    assert sum(item.robustness.unavailable_symbol_count for item in report.candidate_dossiers) == 55
```

- [ ] **Step 2: Write RED missingness tests**

Create focused fixture source JSON for these three cases and assert they remain distinct:

```python
unavailable = {"status": "unavailable", "reason_code": "SOURCE_UNAVAILABLE", "event_count": None}
zero_event = {"status": "available", "reason_code": None, "event_count": 0}
zero_sample = {"sample_count": 0, "median_directional_return_bps": None}
```

Also assert illegal hybrids fail: unavailable + `event_count=0`; `sample_count=0` + numeric median; available with missing status/reason identity.

- [ ] **Step 3: Run RED tests**

Use the Task 1 pytest command; expected failures are missing report/service types.

- [ ] **Step 4: Implement immutable report contracts**

Use frozen dataclasses and `MappingProxyType` where mappings are retained. The report must preserve the source-specific windows exactly rather than compute an intersection.

For each Candidate hard-bind source semantics:

```python
SOURCE_SEMANTICS = {
    "subing_lifecycle_v2_candidate_v1": ("subing_lifecycle", ("5m", "15m"), "5m_ready_boundary", "same_trading_day_only", (3, 5, 8)),
    "n_structure_5m_candidate_v1": ("n_structure", ("5m",), "5m_canonical_bar", "same_rank1_segment", (3, 5, 8)),
    "jdj_trend_follow_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_trend_reentry_6_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_key_level_breakout_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
}
```

- [ ] **Step 5: Implement pure source projection**

`FiveCandidateResearchDossierService` constructor accepts only:

```python
class FiveCandidateResearchDossierService:
    def __init__(self, protocol: FiveCandidateDossierProtocol, *, project_root: Path = PROJECT_ROOT) -> None: ...
    def run(self, request: FiveCandidateDossierRequest) -> FiveCandidateResearchDossier: ...
```

No `Session`, MDS, Candidate service, robustness service, provider, Redis, or network dependency is allowed.

Load the seven artifacts once, validate each source artifact identity before projection, then derive compact summaries only from fields already present in those artifacts. Do not copy full 120/180-cell matrices into the dossier.

- [ ] **Step 6: Add source-identity drift tests**

Mutate one verified fixture artifact at a time: wrong `candidate_id`, wrong `protocol_id`, wrong retrospective through, wrong row order/count. Hash-adjust the fixture ref so the test reaches semantic validation; expect `FiveCandidateDossierSourceError` rather than partial dossier output.

- [ ] **Step 7: Run Task 2 tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): compose five-candidate dossier"
```

---

## Task 3: Freeze Metric Comparability and Existing Relationship Projection

**Files:**
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_dossier.py`

**Interfaces:**
- Produces exact enum `ComparabilityStatus` with four values and exact ten `ComparabilityPair` rows.
- Reuses only the existing SuBing↔N relationship payload from the frozen multi-candidate robustness artifact.

- [ ] **Step 1: Write RED exact pair matrix tests**

```python
EXPECTED = {
    (SUBING, N): ComparabilityStatus.SUPPORTED_EXISTING,
    (SUBING, TF): ComparabilityStatus.NOT_COMPARABLE,
    (SUBING, R6): ComparabilityStatus.NOT_COMPARABLE,
    (SUBING, KLB): ComparabilityStatus.NOT_COMPARABLE,
    (N, TF): ComparabilityStatus.NOT_YET_DEFINED,
    (N, R6): ComparabilityStatus.NOT_YET_DEFINED,
    (N, KLB): ComparabilityStatus.NOT_YET_DEFINED,
    (TF, R6): ComparabilityStatus.SUPPORTED_SAME_FAMILY,
    (TF, KLB): ComparabilityStatus.SUPPORTED_SAME_FAMILY,
    (R6, KLB): ComparabilityStatus.SUPPORTED_SAME_FAMILY,
}
```

Assert exactly 10 unique unordered pairs, canonical order only, no self-pairs and no duplicate reversed pairs.

- [ ] **Step 2: Write RED metric-catalog tests**

Assert five-Candidate common metrics are evidence-completeness only; JDJ-only metrics carry an exact allowed-candidate set; SuBing/N horizon comparison carries `EVALUABLE_UNIT_DIFFERS` and `HORIZON_SEMANTICS_DIFFERS`.

Assert no field named `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote` exists recursively.

- [ ] **Step 3: Write RED existing-relationship projection test**

Use a frozen-artifact fixture containing both directional SuBing↔N relationship rows. Assert Task 3 copies the existing payload values without recomputation and without changing the source relationship window.

- [ ] **Step 4: Implement exact enums/catalog/pairs**

```python
class ComparabilityStatus(StrEnum):
    SUPPORTED_EXISTING = "SUPPORTED_EXISTING"
    SUPPORTED_SAME_FAMILY = "SUPPORTED_SAME_FAMILY"
    NOT_YET_DEFINED = "NOT_YET_DEFINED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
```

`ComparabilityPair` must carry `left_candidate_id`, `right_candidate_id`, `status`, `reason_codes`, and optional `existing_relationship_reference`; no numeric pair performance field is allowed.

- [ ] **Step 5: Run Task 3 tests**

Use Task 2 test command. Expected: PASS.

- [ ] **Step 6: Commit Task 3**

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

**Interfaces:**
- New command: `guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1`.
- New factory: `build_five_candidate_dossier_service() -> FiveCandidateResearchDossierService`, no Session argument.
- New request is part of `ResearchRequest`.

- [ ] **Step 1: Write RED parser/request tests**

```python
def test_candidate_dossier_parser_builds_exact_request() -> None:
    args = build_parser().parse_args([
        "research", "candidate-dossier",
        "--protocol", "five_candidate_research_dossier_v1",
    ])
    request = build_research_request(args)
    assert request == FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
```

Also assert unknown protocol and runtime flags `--since/--through/--symbol/--candidate/--products/--threshold/--score/--rank` return `CLI_ARGUMENT_INVALID`.

- [ ] **Step 2: Write RED zero-Session dispatch test**

```python
def test_candidate_dossier_does_not_open_session() -> None:
    def forbidden_session():
        pytest.fail("candidate-dossier must not create a DB Session")
    code = main(
        ["research", "candidate-dossier", "--protocol", "five_candidate_research_dossier_v1"],
        session_factory=forbidden_session,
        candidate_dossier_service_factory=lambda: FakeDossierService(_report()),
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0
```

- [ ] **Step 3: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: FAIL because parser/request/factory/dispatch do not exist.

- [ ] **Step 4: Add parser/request/typed command support**

`research_parser.py` adds only the exact `--protocol` choice. `research_requests.py` adds `FiveCandidateDossierRequest` to `ResearchRequest`. `research_commands.py` adds a typed service protocol and `_five_candidate_dossier_payload()` dispatch.

- [ ] **Step 5: Refactor `main()` so dossier dispatch occurs before Session creation**

Required control flow:

```python
elif args.domain == "research":
    assert research_request is not None
    if isinstance(research_request, FiveCandidateDossierRequest):
        service = candidate_dossier_service_factory()
        payload = run_research_command(research_request, service)
    else:
        with session_factory() as session:
            service = _session_backed_research_service(...)
            payload = run_research_command(research_request, service)
```

Do not move existing Session-backed research commands out of their current read-only Session path.

- [ ] **Step 6: Implement deterministic payload renderer**

Renderer must preserve exact protocol/Candidate/artifact/pair order. Decimal conversion must reuse the existing optional Decimal string convention; numeric zero renders as string `"0"` where Decimal fields are serialized.

- [ ] **Step 7: Add error-redaction test**

Force `FiveCandidateDossierSourceError`; assert stderr contains only public command/status/error code/read-only fields and contains neither absolute file path nor hash/source JSON nor traceback.

- [ ] **Step 8: Run CLI + regression tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add services/quant-api/app/research/composition.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): expose five-candidate dossier CLI"
```

---

## Task 5: Freeze Phase 8A Evidence and Close Canonical Boundary

**Files:**
- Create: `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`
- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`

**Interfaces:**
- Produces the exact Phase 8A artifact whose SHA is consumed by Task 6.

- [ ] **Step 1: Run focused Phase 8A and source regressions**

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

Any failure blocks evidence generation and closeout.

- [ ] **Step 3: Generate dossier twice without editing output**

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

Expected: `cmp` exit 0.

- [ ] **Step 4: Verify semantic invariants and forbidden fields**

Run a small Python assertion over parsed JSON: 5 candidates, 7 sources, 10 pairs, 300 source cells, 245/55 current inventory, `prospective_consumed=false`, and recursively reject case-insensitive keys/values containing automatic-decision/trading claims: `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote`, `approved`, `expected_profit`, `profitability`, `fill`, `order`, `position`, `equity`, `pnl`.

Do not reject legitimate descriptive strings such as `trade` when they occur inside source protocol terminology unless they form a report key/decision claim; write the checker against report keys and enumerated decision values, not arbitrary substrings in paths.

- [ ] **Step 5: Copy exact stdout as the tracked artifact and compute SHA256**

```bash
mkdir -p reports/research/candidate_dossier/five_candidate_research_dossier_v1
cp /private/tmp/guiyi-phase8/dossier-1.json \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Record this exact SHA in the Task 5 commit message/body notes and use it verbatim in Task 6 protocol.

- [ ] **Step 6: Update canonical docs narrowly**

`STATUS.md` records Phase 8A evidence path/SHA and explicitly says Phase 8B not yet complete; all prospective states remain unchanged.

`PROJECT_SOURCE.md` / `DECISIONS.md` record the artifact-only composition boundary and no-ranking/no-common-window rule.

`docs/ARCHITECTURE.md` adds one read-only `FiveCandidateResearchDossierService` node fed only by frozen artifacts, not MDS.

`TESTING.md` adds the exact `candidate-dossier` verification command.

- [ ] **Step 7: Run docs/reference/secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Commit Task 5**

```bash
git add \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze five-candidate dossier evidence"
```

### Mandatory Segment A Gate

After Task 5: independent review the Phase 8A diff. If Critical/Important findings exist, fix in the same Phase 8A branch and rerun affected validation. Once accepted, integrate Phase 8A into `develop`, confirm ancestry/readback, remove the merged Phase 8A task worktree/branch if using one, then start Phase 8B in a **new session and new task worktree from updated `develop`**.

---

# Execution Segment B — Phase 8B

## Task 6: Freeze Relationship Topology Protocol and Contracts

**Lane:** Lane 1 with Sol/high due causality/embargo boundaries. New session. Independent review required before integration.

**Files:**
- Create: `data/research_protocols/five_candidate_relationship_topology_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- Create: `services/quant-api/tests/test_five_candidate_relationships.py`
- Modify: `services/quant-api/app/research/candidate_convergence/artifact_source.py` only if 8B needs a narrowly typed shared verifier extension.

**Interfaces:**
- Produces: `RelationshipKind`, `DependencyRole`, `FiveCandidateRelationshipProtocol`, `FiveCandidateRelationshipRequest`, report row contracts and exact protocol loader.
- Errors: `FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID`.

- [ ] **Step 1: Re-read updated Phase 8A identity**

Fetch/read the tracked Task 5 dossier artifact and calculate its SHA256. Confirm it matches Phase 8A canonical. If it does not, stop; do not draft an 8B protocol against a moving source.

- [ ] **Step 2: Write RED exact-protocol tests**

Lock all four relationship kinds, ten pair order, three analysis families, exact windows and safety booleans.

```python
def test_relationship_protocol_has_exact_windows() -> None:
    protocol = load_five_candidate_relationship_protocol()
    assert protocol.n_jdj_since == date(2023, 1, 1)
    assert protocol.n_jdj_through == date(2026, 8, 19)
    assert protocol.jdj_overlap_since == date(2023, 1, 1)
    assert protocol.jdj_overlap_through == date(2026, 8, 20)
    assert protocol.prospective_consumed is False
    assert protocol.n_jdj_proximity is None
    assert protocol.jdj_overlap_proximity is None
    assert protocol.future_outcomes is False
```

- [ ] **Step 3: Write RED drift tests**

Mutations must include: N→JDJ through changed to `2026-08-20`, JDJ overlap through changed to `2026-08-21`, non-null proximity, `future_outcomes=true`, pair order drift, source dossier SHA drift, and SuBing↔JDJ recompute flag enabled. All raise protocol/source errors before source research runs.

- [ ] **Step 4: Run RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: missing module/contracts failures.

- [ ] **Step 5: Implement exact relationship contracts**

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

Protocol JSON must freeze the exact Task 5 dossier repo-relative path + actual SHA256, plus the existing SuBing/N robustness repo-relative path + known SHA256. No placeholder hash is allowed in committed protocol.

- [ ] **Step 6: Add report identity invariants**

Report construction must require exactly 10 catalog pairs, exactly 180 dependency rows in candidate-major/symbol order, exactly 180 overlap rows in pair-major/symbol order, and legal unavailable nullability.

- [ ] **Step 7: Run Task 6 tests/static checks**

Use Task 6 pytest command plus Ruff on the package/test. Expected: PASS.

- [ ] **Step 8: Commit Task 6**

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

**Interfaces:**
- Consumes: existing `JdjResearchService.run_batch(symbol, since, through)` and exact JDJ event types.
- Produces: 180 `CandidateDependencyResult` rows.

- [ ] **Step 1: Write RED fake-runner call-boundary test**

Fake runner records calls. Running dependency projection must call each active symbol with exactly `since=date(2023,1,1)`, `through=date(2026,8,19)` and never with `2026-08-20`.

```python
assert set(fake.calls) == {
    (symbol, date(2023, 1, 1), date(2026, 8, 19))
    for symbol in PRODUCTS
}
```

- [ ] **Step 2: Write RED lineage completeness tests**

Construct exact JDJ events:

- Trend Follow / Reentry events with valid non-null `trend_snapshot_observed_at`;
- KLB event with valid `trend_snapshot_observed_at`, `trend_epoch`, `key_level_pivot_id`, `key_level_confirmed_at`.

Assert available rows satisfy event-count equality. Build corrupted fake event/result objects at the service boundary and require fail-closed rather than silently lowering the lineage count.

- [ ] **Step 3: Write RED unavailable-row test**

When `run_batch()` raises `JdjSourceUnavailableError` for one symbol, the report retains three candidate rows for that symbol with `status=unavailable`, `reason_code=JDJ_SOURCE_UNAVAILABLE`, all dependency metrics null.

- [ ] **Step 4: Run RED tests**

Expected: missing service/projection failures.

- [ ] **Step 5: Implement dependency projection**

For each symbol call the runner once for the N-safe window. For each candidate:

```python
role = (
    DependencyRole.TREND_AND_PIVOT_SOURCE
    if candidate_id == "jdj_key_level_breakout_1m_candidate_v1"
    else DependencyRole.TREND_FILTER
)
```

Count event lineage from immutable JDJ events only. Do not call `NStructureResearchService.completion_events()` and do not join N completion events by time.

- [ ] **Step 6: Validate strict source identity**

Require batch symbol, candidate order, products and observed window to satisfy existing JDJ contracts. Context/event contract corruption raises an execution error; only `JdjSourceUnavailableError` maps to typed unavailable.

- [ ] **Step 7: Run Task 7 tests + JDJ regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/data_foundation/test_jdj_research_service.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 7**

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

**Interfaces:**
- Produces pure function:

```python
def summarize_exact_jdj_overlap(
    left: JdjDetailedCandidateResult,
    right: JdjDetailedCandidateResult,
    *,
    symbol: str,
) -> JdjExactOverlapResult: ...
```

- Uses no horizon outcomes even though `JdjDetailedCandidateResult` carries them.

- [ ] **Step 1: Write RED exact-key tests**

Create events that differ one field at a time: contract, segment start day, trading day, bar index, `observed_at`. Only exact equality across the full key counts as overlap.

- [ ] **Step 2: Write RED direction tests**

Same boundary/same direction increments `exact_same_boundary_same_direction_count`; same boundary/opposite direction increments only `exact_same_boundary_opposite_direction_count`.

- [ ] **Step 3: Write RED dedup/matched-event tests**

Assert `left_events_with_same_direction_match` and `right_events_with_same_direction_match` count unique source events, not Cartesian pair multiplicity. Existing JDJ event IDs are unique; still write the reducer to fail if duplicate event IDs enter.

- [ ] **Step 4: Write RED no-future-outcome test**

Provide identical event streams with deliberately different `event_outcomes`; the overlap result must be exactly equal. This mechanically proves the reducer ignores future outcome data.

- [ ] **Step 5: Run RED tests**

Expected: missing reducer failures.

- [ ] **Step 6: Implement exact overlap reducer**

Use key:

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

Do not import `PriceDirectionalOutcome`, do not inspect `event_outcomes`, and do not accept a proximity parameter.

- [ ] **Step 7: Add service window test**

The overlap orchestration separately calls `run_batch(symbol, since=2023-01-01, through=2026-08-20)` for each symbol. Assert this call set is distinct from the Task 7 dependency call set.

- [ ] **Step 8: Assert exact 180 overlap rows**

Canonical pair order is `(TF,R6)`, `(TF,KLB)`, `(R6,KLB)`; symbol order is protocol active60 order. Missing/unavailable source still retains all three pair rows for the symbol.

- [ ] **Step 9: Run Task 8 tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py \
  services/quant-api/tests/test_jdj_research.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

- [ ] **Step 10: Commit Task 8**

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_relationships.py
git commit -m "feat(research): add exact JDJ candidate overlap"
```

---

## Task 9: Add `candidate-relationships` Historical CLI

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `services/quant-api/tests/test_five_candidate_relationships.py`

**Interfaces:**
- New command: `guiyi research candidate-relationships --protocol five_candidate_relationship_topology_v1`.
- New builder: `build_five_candidate_relationship_service(session: Session) -> FiveCandidateRelationshipService`.

- [ ] **Step 1: Write RED parser/request tests**

Exact protocol only; reject all runtime selectors and parameter/ranking flags.

- [ ] **Step 2: Write RED Session-backed composition test**

Unlike `candidate-dossier`, this command must create one read-only Session and build a relationship service over the existing `build_jdj_research_service(session)` path. The test should inject a fake factory and assert exactly one Session context entry.

- [ ] **Step 3: Write RED composition source test**

Patch `build_jdj_research_service` to return a sentinel runner and assert `build_five_candidate_relationship_service(session)` injects that exact runner. Do not create a second N research loader or robustness recomputation service.

- [ ] **Step 4: Run RED CLI tests**

Expected: parser/factory/dispatch failures.

- [ ] **Step 5: Implement builder and CLI dispatch**

`research/composition.py` must:

1. load exact relationship protocol;
2. verify the frozen Phase 8A dossier artifact and existing SuBing/N relationship artifact via the shared artifact verifier;
3. build exactly one `JdjResearchService` from the current Session;
4. construct `FiveCandidateRelationshipService`.

`main.py` keeps this command inside the existing `with session_factory() as session:` branch.

- [ ] **Step 6: Implement deterministic relationship payload**

Render exact 10 catalog pairs, 180 dependency rows, 180 overlap rows, typed unavailable nulls and source references. Do not render source event details or full prior robustness matrices.

- [ ] **Step 7: Add recursive forbidden-field test**

Report keys must be disjoint from automatic decision/performance-combination keys such as `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote`, `combined_return`, `overlap_return`, `expected_profit`, `pnl`.

- [ ] **Step 8: Add error-redaction tests**

Protocol/source/context errors must produce existing redacted CLI error JSON; no absolute path/source JSON/traceback.

- [ ] **Step 9: Run Task 9 CLI + source regressions**

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

- [ ] **Step 10: Commit Task 9**

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
- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`

- [ ] **Step 1: Run complete Phase 8 focused regressions**

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

- [ ] **Step 2: Run native full backend/static/engineering checks**

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

Any failure blocks evidence/canonical closeout.

- [ ] **Step 3: Generate relationship evidence twice**

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

Expected: byte-identical.

- [ ] **Step 4: Verify exact topology invariants**

Parsed JSON assertions:

```text
relationship_catalog == 10
n_jdj_dependency_results == 180
jdj_exact_overlap_results == 180
prospective_consumed == false
N→JDJ window == 2023-01-01..2026-08-19
JDJ overlap window == 2023-01-01..2026-08-20
SuBing↔JDJ relation kind == UNDEFINED_CROSS_TIMEFRAME
no proximity field has a numeric value for N→JDJ/JDJ overlap
no future-outcome/combined-performance field exists
```

For every available dependency row enforce lineage count equality from the spec.

- [ ] **Step 5: Copy exact stdout as tracked evidence and compute SHA**

```bash
mkdir -p reports/research/candidate_relationships/five_candidate_relationship_topology_v1
cp /private/tmp/guiyi-phase8/relationships-1.json \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
```

- [ ] **Step 6: Update canonical docs to close Phase 8 only**

`STATUS.md` records both Phase 8A and 8B artifact paths/SHA and exact boundaries. Keep all prospective OOS statuses truthful; do not claim OOS completion.

`PROJECT_SOURCE.md` records Candidate convergence + relationship topology as read-only research surfaces.

`DECISIONS.md` records: no Five-Candidate common window; N→JDJ dependency is not independent signal confirmation; JDJ overlap V1 is exact-boundary only; SuBing↔JDJ remains undefined.

`docs/ARCHITECTURE.md` shows Phase 8A artifact-only node and Phase 8B `JdjResearchService` read-only topology node with separate 8/19 and 8/20 windows.

`TESTING.md` adds exact Phase 8A/8B verification commands and states that tests/evidence do not authorize promotion/release/Runtime/data writes.

- [ ] **Step 7: Run final docs/secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Independent review before integration**

Open a fresh Sol/high Review session against the complete Phase 8B task branch diff. Review focus:

1. N embargo/future leakage;
2. accidental use of JDJ `event_outcomes` in overlap;
3. invented proximity/lead-lag parameters;
4. N→JDJ wording accidentally implying independent confirmation;
5. missing 180/180 identity rows or missing typed unavailable rows;
6. automatic ranking/promotion/trading claims;
7. unwanted DB/Canonical/Redis/Alert/Runtime side effects.

Critical/Important findings must be fixed and affected tests rerun before integration.

- [ ] **Step 9: Commit Task 10**

```bash
git add \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze phase 8 relationship topology evidence"
```

- [ ] **Step 10: Integrate to `develop` and clean task workspace**

After all tests and independent review pass, integrate the Phase 8B task branch into `develop` using the repository's current ordinary development flow. Confirm the commits are in `develop`, then delete the merged temporary worktree/branch. Do not touch `main`, create a tag, release, switch Runtime, send notifications, or perform any real data/DB mutation.

---

# Codex Scheduling Matrix

| Segment | Tasks | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
|---|---:|---|---|---|---|---|---|---|
| Phase 8A | 1–5 | Lane 1 | Sol | High | new | Plan-then-execute | new task worktree from latest `develop` | independent review before 8A integration |
| Phase 8B | 6–10 | Lane 1 | Sol | High | **new after 8A integration** | Plan-then-execute | new task worktree from updated `develop` | Plan boundary readback + independent review before integration |

## Worktree Flow

```text
latest develop
  → research/five-candidate-dossier-v1 task worktree
  → Tasks 1–5
  → review
  → integrate develop
  → verify integration
  → cleanup Phase 8A task worktree/branch

updated develop
  → research/five-candidate-relationship-topology-v1 task worktree
  → Tasks 6–10
  → independent Sol review
  → integrate develop
  → verify integration
  → cleanup Phase 8B task worktree/branch
```

PR is optional under current repository workflow. Neither segment may touch `main`, tag or Runtime. Release approval and Runtime promotion remain separate future Gates.

# Task Contract Summary

Every Task must end with:

```text
1. exact scoped diff only;
2. RED→GREEN focused tests;
3. relevant regressions;
4. no unrelated refactor;
5. no real write / Runtime / notification side effect;
6. a task-scoped commit;
7. output: modification summary, tests, risks, unresolved items.
```

Task 5 and Task 10 evidence commits must additionally include exact artifact SHA256 in the completion report. Evidence does not grant Candidate promotion or release authority.

# Final Acceptance

Phase 8 is complete only when both tracked artifacts exist, their deterministic generation is verified, all 300 Phase 8A source identities and all 360 Phase 8B relationship identities are preserved, N/JDJ embargo and prospective boundaries are untouched, and canonical docs describe only evidence convergence/topology facts.

Allowed final verdict after Task 10 review: **允许集成 develop**.

Not allowed from this plan alone: **允许发布 main/tag** or **允许 Runtime promotion**.
