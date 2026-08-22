# Phase 8 — Five-Candidate Evidence Convergence & Relationship Topology V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a deterministic five-Candidate evidence dossier, then freeze a relationship topology that distinguishes existing SuBing↔N event relationships, N→JDJ structural dependencies, exact JDJ↔JDJ same-boundary overlap, and undefined SuBing↔JDJ cross-timeframe relations without ranking Candidates or consuming prospective OOS.

**Architecture:** Phase 8A is artifact-only composition over seven Git-tracked frozen JSON artifacts and must execute before any DB Session is opened. Phase 8B is a separate Historical read-only recomputation using the existing `JdjResearchService`: one exact window through `2026-08-19` for N→JDJ dependency and a separate exact window through `2026-08-20` for JDJ overlap. The two phases share only small exact contract/artifact helpers and deterministic JSON rendering; they do not create a general research platform or persistence layer.

**Tech Stack:** Python 3.12, dataclasses / `Decimal`, repository-standard SQLAlchemy Session only for Phase 8B composition, existing `MarketDataService → ActualDominantResearchSegmentLoader → JdjResearchService`, pytest, Ruff, Mypy, existing `guiyi research` CLI JSON renderer.

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
- Task 5 is a mandatory checkpoint: Phase 8B starts only after Phase 8A is integrated to an updated `develop` and a new task worktree/session is created.

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
- Produces `SourceArtifactRef`, `VerifiedJsonArtifact`, `verify_json_artifact`, `FiveCandidateDossierProtocol`, `FiveCandidateDossierRequest`, `load_five_candidate_dossier_protocol`.
- Stable errors: `FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID`, `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`.
- Consumes `PROJECT_ROOT`, `load_exact_json`, and the seven frozen source identities in the spec.

- [ ] **Step 1: Write RED tests for exact protocol values and ordering**

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

- [ ] **Step 2: Write RED mutation tests with concrete mutations**

Create a helper that writes a mutated protocol object, then add six independent tests:

```python
def _write_protocol(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_protocol_rejects_extra_field(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["threshold"] = 1
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "extra.json"))


def test_protocol_rejects_candidate_order_drift(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["candidate_order"][0:2] = reversed(payload["candidate_order"][0:2])
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "candidate-order.json"))


def test_protocol_rejects_pair_order_drift(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["comparability_pair_order"][0:2] = reversed(payload["comparability_pair_order"][0:2])
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "pair-order.json"))


def test_protocol_rejects_absolute_source_path(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["source_artifacts"][0]["path"] = "/tmp/source.json"
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "absolute.json"))


def test_protocol_rejects_source_path_escape(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["source_artifacts"][0]["path"] = "../source.json"
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "escape.json"))


def test_protocol_rejects_invalid_sha(tmp_path: Path) -> None:
    payload = deepcopy(_protocol_payload())
    payload["source_artifacts"][0]["expected_sha256"] = "not-a-sha256"
    with pytest.raises(FiveCandidateDossierProtocolError):
        load_five_candidate_dossier_protocol(_write_protocol(tmp_path, payload, "sha.json"))
```

The committed helper must type/narrow the loaded JSON object before indexed mutation so Mypy passes; do not use unchecked `Any` to bypass the contract.

- [ ] **Step 3: Run the RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: import/collection failure because the new package/contracts do not exist.

- [ ] **Step 4: Implement bounded artifact value objects**

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

`SourceArtifactRef.__post_init__` must require a non-empty ASCII-safe `artifact_id`, a relative POSIX path with no empty/`.`/`..` components, and exactly 64 lowercase hexadecimal SHA characters.

- [ ] **Step 5: Implement bounded artifact verification**

Use this exact algorithm in `verify_json_artifact`:

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
    decoded = raw.decode("utf-8", errors="strict")
    payload = json.loads(decoded)
    if type(payload) is not dict:
        raise error_type()
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise error_type() from None
return VerifiedJsonArtifact(ref, ref.expected_sha256, MappingProxyType(dict(payload)))
```

Do not include the resolved path, source JSON, or SHA mismatch values in the public exception string.

- [ ] **Step 6: Implement exact dossier protocol loader**

Use `load_exact_json()` for the protocol itself. `FiveCandidateDossierProtocol.__post_init__()` must re-check all exact values and ordering so direct construction cannot bypass the file loader. The seven refs must be copied exactly from the approved spec, using repository-relative paths only.

- [ ] **Step 7: Add real-source verification test**

Load all seven current tracked artifacts through `verify_json_artifact` and assert `verified_sha256 == ref.expected_sha256`. Patch/fail if DB/MDS/source service constructors are called; Task 1 must be pure filesystem verification only.

- [ ] **Step 8: Run Task 1 tests and static checks**

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

- [ ] **Step 9: Commit Task 1**

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
- Consumes Task 1 `FiveCandidateDossierProtocol` and `VerifiedJsonArtifact`.
- Produces `CandidateDossier`, `CandidateBaselineEvidence`, `CandidateRobustnessEvidence`, `MetricComparability`, `ComparabilityPair`, `FiveCandidateResearchDossier`, `FiveCandidateResearchDossierService.run`.
- Stable report error: `FIVE_CANDIDATE_DOSSIER_REPORT_INVALID`.

- [ ] **Step 1: Write RED report-shape tests**

```python
def test_dossier_has_exact_candidate_and_source_inventory(service: FiveCandidateResearchDossierService) -> None:
    report = service.run(FiveCandidateDossierRequest("five_candidate_research_dossier_v1"))
    assert report.candidate_order == CANDIDATES
    assert len(report.source_artifacts) == 7
    assert len(report.candidate_dossiers) == 5
    assert sum(item.robustness.matrix_cell_count for item in report.candidate_dossiers) == 300
    assert sum(item.robustness.available_symbol_count for item in report.candidate_dossiers) == 245
    assert sum(item.robustness.unavailable_symbol_count for item in report.candidate_dossiers) == 55
```

- [ ] **Step 2: Write RED missingness tests**

Create small source fixtures and assert:

```python
assert unavailable_row["status"] == "unavailable"
assert unavailable_row["reason_code"] == "JDJ_SOURCE_UNAVAILABLE"
assert unavailable_row["event_count"] is None

assert zero_event_row["status"] == "available"
assert zero_event_row["reason_code"] is None
assert zero_event_row["event_count"] == 0

assert zero_sample_horizon["sample_count"] == 0
assert zero_sample_horizon["median_directional_return_bps"] is None
```

Also construct illegal hybrids and require `FiveCandidateDossierSourceError` or `FiveCandidateDossierReportError`:

- unavailable + numeric event count;
- sample_count zero + numeric median;
- available + unavailable reason code.

- [ ] **Step 3: Run RED tests**

Use the Task 1 pytest command. Expected: missing report/service types.

- [ ] **Step 4: Implement frozen report contracts and source semantics**

Hard-bind the five source semantics in one immutable constant. Exact values:

```python
SOURCE_SEMANTICS = {
    "subing_lifecycle_v2_candidate_v1": ("subing_lifecycle", ("5m", "15m"), "5m_ready_boundary", "same_trading_day_only", (3, 5, 8)),
    "n_structure_5m_candidate_v1": ("n_structure", ("5m",), "5m_canonical_bar", "same_rank1_segment", (3, 5, 8)),
    "jdj_trend_follow_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_trend_reentry_6_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_key_level_breakout_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
}
```

The report must store each source's actual retrospective dates. It must never calculate or serialize a five-Candidate intersection window.

- [ ] **Step 5: Implement pure seven-artifact projection**

Constructor and run signatures are exact:

```python
class FiveCandidateResearchDossierService:
    def __init__(
        self,
        protocol: FiveCandidateDossierProtocol,
        *,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self._protocol = protocol
        self._project_root = project_root

    def run(self, request: FiveCandidateDossierRequest) -> FiveCandidateResearchDossier:
        ...
```

In repository code, replace the final body marker with concrete code that:

1. exact-validates request/protocol identity;
2. verifies seven artifacts once each;
3. validates each artifact's candidate/protocol/window/order identity;
4. projects baseline counts/status/window data;
5. projects robustness availability/zero-event/zero-sample/sector/yearly inventory;
6. returns immutable report rows in protocol order.

The committed Python file must contain no placeholder body.

- [ ] **Step 6: Add semantic-drift tests independent of SHA drift**

For each fixture, rewrite the JSON and recompute its fixture SHA so hash verification succeeds, then mutate exactly one semantic field: candidate ID, protocol ID, retrospective through, cross-symbol row count, row order. Each case must raise `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID` and return no partial report.

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
- Produces exact `ComparabilityStatus` enum, ten `ComparabilityPair` rows, `MetricComparability` catalog, and read-only projection of existing SuBing↔N relationship facts.

- [ ] **Step 1: Write RED exact pair tests**

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

Assert 10 unique unordered pairs, no self-pairs, canonical pair order and no reversed duplicates.

- [ ] **Step 2: Write RED metric-catalog tests**

Assert:

- five-Candidate shared metrics are evidence completeness/availability/zero-event/zero-sample/rolling/prospective status only;
- JDJ event-rate, long/short, 3/5/8/20 source outcome, yearly, sector metrics list exactly the three JDJ Candidate IDs;
- SuBing/N same-named horizon metrics carry both `EVALUABLE_UNIT_DIFFERS` and `HORIZON_SEMANTICS_DIFFERS`.

- [ ] **Step 3: Write RED existing-relationship projection test**

Feed a frozen robustness fixture with both directional SuBing↔N relationship rows. Assert output values and source window are copied exactly; patch `summarize_candidate_relationship` to fail if called so the test proves no relationship recomputation occurs in 8A.

- [ ] **Step 4: Implement exact comparability enum and value objects**

```python
class ComparabilityStatus(StrEnum):
    SUPPORTED_EXISTING = "SUPPORTED_EXISTING"
    SUPPORTED_SAME_FAMILY = "SUPPORTED_SAME_FAMILY"
    NOT_YET_DEFINED = "NOT_YET_DEFINED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
```

`ComparabilityPair` fields: `left_candidate_id`, `right_candidate_id`, `status`, `reason_codes`, `existing_relationship_reference`. Do not add numeric pair score/performance fields.

- [ ] **Step 5: Add recursive automatic-decision-field test**

Collect keys recursively and assert disjointness from:

```python
FORBIDDEN_KEYS = {
    "score", "rank", "winner", "best", "keep", "drop", "iterate",
    "promote", "approved", "expected_profit", "profitability", "pnl",
}
```

- [ ] **Step 6: Run Task 3 tests and commit**

Run the Task 2 test command. Expected: PASS.

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
- Command: `guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1`.
- Builder: `build_five_candidate_dossier_service() -> FiveCandidateResearchDossierService`, with no Session argument.

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

- [ ] **Step 2: Write RED invalid-argument tests**

For each of `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`, invoke the parser with the exact dossier command plus that flag/value and assert CLI argument failure. Unknown protocol must also fail at parse/request time.

- [ ] **Step 3: Write RED zero-Session dispatch test**

```python
def test_candidate_dossier_does_not_open_session() -> None:
    def forbidden_session() -> AbstractContextManager[object]:
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

Use the test file's existing context-manager typing pattern so the helper type-checks.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: parser/request/factory/dispatch failures.

- [ ] **Step 5: Add parser/request/typed command support**

`research_parser.py` adds a `candidate-dossier` parser with only one required exact `--protocol` choice. `research_requests.py` adds `FiveCandidateDossierRequest` to `ResearchRequest`. `research_commands.py` adds typed dispatch before the existing robustness/request branches.

- [ ] **Step 6: Refactor `main()` before Session creation**

Required concrete flow:

```python
elif args.domain == "research":
    assert research_request is not None
    if isinstance(research_request, FiveCandidateDossierRequest):
        service = candidate_dossier_service_factory()
        payload = run_research_command(research_request, service)
    else:
        with session_factory() as session:
            service = _build_existing_session_backed_research_service(
                args,
                research_request,
                session,
                lifecycle_research_service_factory=lifecycle_research_service_factory,
                candidate_validation_service_factory=candidate_validation_service_factory,
                n_candidate_validation_service_factory=n_candidate_validation_service_factory,
                main_force_mirror_v2_research_service_factory=main_force_mirror_v2_research_service_factory,
                n_structure_research_service_factory=n_structure_research_service_factory,
                jdj_research_service_factory=jdj_research_service_factory,
                jdj_candidate_validation_service_factory=jdj_candidate_validation_service_factory,
                multi_candidate_robustness_service_factory=multi_candidate_robustness_service_factory,
                jdj_active60_robustness_service_factory=jdj_active60_robustness_service_factory,
                research_service_factory=research_service_factory,
            )
            payload = run_research_command(research_request, service)
```

If extracting `_build_existing_session_backed_research_service` would create an unnecessary broad refactor, preserve the existing `elif` chain verbatim inside the `with session_factory()` block instead. The invariant under test is that only the dossier branch bypasses Session creation.

- [ ] **Step 7: Implement deterministic dossier payload**

Render exact protocol/Candidate/artifact/pair order. Reuse the existing Decimal-to-string helper; Decimal zero must serialize as `"0"`. Do not include full 120/180 source matrices.

- [ ] **Step 8: Add redacted-error test**

Force `FiveCandidateDossierSourceError`; assert stderr contains the stable public error code and `readonly=true`, and does not contain an absolute path, source JSON, source SHA, or traceback.

- [ ] **Step 9: Run CLI + regression tests and commit**

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

## Task 5: Freeze Phase 8A Evidence and Close Canonical Boundary

**Files:**
- Create: `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`
- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`

**Produces:** exact Phase 8A artifact path/SHA consumed by Task 6.

- [ ] **Step 1: Run focused Phase 8A/source regressions**

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

- [ ] **Step 3: Generate dossier twice and require byte equality**

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

- [ ] **Step 4: Verify parsed invariants with an explicit checker**

Create a one-off local checker or add a test helper that asserts:

```python
payload = json.loads(Path("/private/tmp/guiyi-phase8/dossier-1.json").read_text())
assert len(payload["candidate_order"]) == 5
assert len(payload["source_artifacts"]) == 7
assert len(payload["comparability_pairs"]) == 10
assert payload["prospective_consumed"] is False
assert sum(item["robustness"]["matrix_cell_count"] for item in payload["candidate_dossiers"]) == 300
assert sum(item["robustness"]["available_symbol_count"] for item in payload["candidate_dossiers"]) == 245
assert sum(item["robustness"]["unavailable_symbol_count"] for item in payload["candidate_dossiers"]) == 55
```

Recursively collect report keys and reject automatic-decision keys. Check keys/enum decision values rather than arbitrary substrings in artifact paths.

- [ ] **Step 5: Copy exact stdout as tracked evidence and calculate SHA256**

```bash
mkdir -p reports/research/candidate_dossier/five_candidate_research_dossier_v1
cp /private/tmp/guiyi-phase8/dossier-1.json \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Preserve the exact SHA in the completion report; Task 6 must copy it verbatim into the 8B protocol.

- [ ] **Step 6: Update canonical docs narrowly**

- `STATUS.md`: add Phase 8A evidence path/SHA and explicitly state Phase 8B not complete; prospective statuses remain truthful.
- `PROJECT_SOURCE.md`: record artifact-only dossier boundary, source-specific windows and no-ranking semantics.
- `DECISIONS.md`: record no Five-Candidate common window and comparability/relationship separation.
- `docs/ARCHITECTURE.md`: add an artifact-only `FiveCandidateResearchDossierService` node with no MDS edge.
- `TESTING.md`: add the exact `candidate-dossier` verification command and no-side-effect statement.

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

### Mandatory Segment A Gate

Open an independent review of the complete Phase 8A diff. Fix Critical/Important findings and rerun affected checks. After acceptance, integrate Phase 8A into `develop`, verify the Task 1–5 commits are in `develop`, clean the merged task worktree/branch, then start Phase 8B in a new session/worktree from updated `develop`.

---

# Execution Segment B — Phase 8B

## Task 6: Freeze Relationship Topology Protocol and Contracts

**Lane:** Lane 1, Sol/high because this task freezes causality/embargo boundaries. New session; independent review required before final integration.

**Files:**
- Create: `data/research_protocols/five_candidate_relationship_topology_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- Create: `services/quant-api/tests/test_five_candidate_relationships.py`
- Modify: `services/quant-api/app/research/candidate_convergence/artifact_source.py` only if a narrowly typed shared verifier addition is required.

**Interfaces:**
- Produces `RelationshipKind`, `DependencyRole`, `FiveCandidateRelationshipProtocol`, `FiveCandidateRelationshipRequest`, dependency/overlap/report VOs, exact loader.
- Stable errors: `FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID`.

- [ ] **Step 1: Read and hash the integrated Phase 8A artifact**

```bash
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Compare with `STATUS.md`. If they differ, stop; do not create 8B protocol against drifted 8A evidence.

- [ ] **Step 2: Write RED exact-window/safety tests**

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

- [ ] **Step 3: Write RED drift tests**

Write separate tests that mutate:

- N→JDJ through to `2026-08-20`;
- JDJ overlap through to `2026-08-21`;
- either proximity from null to `1`;
- `future_outcomes` to true;
- pair order;
- Phase 8A dossier SHA;
- SuBing↔JDJ `recompute` to true.

Each must fail before any JDJ source runner is invoked.

- [ ] **Step 4: Run RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: missing module/contracts failures.

- [ ] **Step 5: Implement exact relation enums**

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

The committed protocol must contain the actual SHA from Step 1, not a template value. It also freezes the known SuBing/N robustness path/SHA from the approved spec and the exact 10 pair order.

- [ ] **Step 7: Add report invariants**

`FiveCandidateRelationshipReport.__post_init__` must require:

```text
10 relationship catalog pairs
180 dependency rows = 3 JDJ × 60 symbols
180 overlap rows = 3 unordered JDJ pairs × 60 symbols
candidate-major/symbol order for dependency rows
pair-major/symbol order for overlap rows
typed unavailable rows with all metric fields null
```

- [ ] **Step 8: Run Task 6 tests/static checks and commit**

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

**Interfaces:**
- Consumes `JdjResearchService.run_batch(symbol, since, through)` and exact JDJ event types.
- Produces 180 `CandidateDependencyResult` rows.

- [ ] **Step 1: Write RED runner-window test**

Fake runner records calls. Dependency projection must call exactly:

```python
expected_calls = {
    (symbol, date(2023, 1, 1), date(2026, 8, 19))
    for symbol in PRODUCTS
}
assert set(fake.calls) == expected_calls
```

- [ ] **Step 2: Write RED lineage-completeness tests**

For valid batches assert:

```python
assert tf.events_with_trend_snapshot_lineage == tf.event_count
assert tf.events_with_exact_pivot_lineage is None
assert r6.events_with_trend_snapshot_lineage == r6.event_count
assert r6.events_with_exact_pivot_lineage is None
assert klb.events_with_trend_snapshot_lineage == klb.event_count
assert klb.events_with_exact_pivot_lineage == klb.event_count
```

Construct a fake boundary object missing one required lineage field and assert report construction/service validation fails rather than reporting a lower lineage percentage.

- [ ] **Step 3: Write RED unavailable-row test**

When `run_batch` raises `JdjSourceUnavailableError` for one symbol, require three dependency rows for that symbol with `status=unavailable`, `reason_code=JDJ_SOURCE_UNAVAILABLE`, and all lineage/count metrics null.

- [ ] **Step 4: Run RED tests**

Use the Task 6 pytest command. Expected: missing service/projection failures.

- [ ] **Step 5: Implement dependency service branch**

For every active60 symbol call the runner once for the N-safe window. Dependency role is exact:

```python
if candidate_id == "jdj_key_level_breakout_1m_candidate_v1":
    role = DependencyRole.TREND_AND_PIVOT_SOURCE
else:
    role = DependencyRole.TREND_FILTER
```

Count lineage only from immutable JDJ events. Do not call `NStructureResearchService.completion_events()` and do not join N completion events by time.

- [ ] **Step 6: Enforce source identity**

Require batch symbol, Candidate order, result products and event identity to satisfy existing JDJ contracts. Only `JdjSourceUnavailableError` maps to typed unavailable. `JdjContextError` or invalid event identity fails the whole execution.

- [ ] **Step 7: Run Task 7 regressions and commit**

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

**Interfaces:**
- Produces `summarize_exact_jdj_overlap(left, right, *, symbol) -> JdjExactOverlapResult`.
- The reducer must not inspect `event_outcomes`.

- [ ] **Step 1: Write RED exact-key tests**

Create event pairs differing one identity field at a time: `contract`, `segment_start_trading_day`, `trading_day`, `segment_bar_index`, `observed_at`. Only full-key equality counts.

- [ ] **Step 2: Write RED direction tests**

Same boundary/same direction increments only `exact_same_boundary_same_direction_count`; same boundary/opposite direction increments only `exact_same_boundary_opposite_direction_count`.

- [ ] **Step 3: Write RED matched-event uniqueness test**

Use multiple events at distinct boundaries and assert `left_events_with_same_direction_match` / `right_events_with_same_direction_match` count matched event IDs, not Cartesian pair multiplicity. Duplicate event IDs must fail input validation.

- [ ] **Step 4: Write RED no-future-outcome test**

Build two `JdjDetailedCandidateResult` sets with identical `result.events` but different `event_outcomes`. Assert the overlap result is equal. This proves future outcomes are not consumed.

- [ ] **Step 5: Run RED tests**

Use Task 6 pytest command. Expected: missing reducer failures.

- [ ] **Step 6: Implement exact boundary reducer**

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

Index right events by boundary+direction; count exact same/opposite direction matches and unique left/right same-direction matched IDs. The function signature must have no proximity/horizon parameter. Do not import `PriceDirectionalOutcome`.

- [ ] **Step 7: Add separate overlap-window service test**

Assert overlap orchestration calls every symbol with exactly `2023-01-01..2026-08-20`. Assert the fake runner call list also contains the Task 7 `2023-01-01..2026-08-19` calls as a separate run family rather than reusing a later window and filtering.

- [ ] **Step 8: Assert exact 180 overlap rows**

Pair order is `(TF,R6)`, `(TF,KLB)`, `(R6,KLB)`; symbol order is active60. Source unavailable retains all three pair rows for the symbol.

- [ ] **Step 9: Run Task 8 regressions and commit**

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
- Command: `guiyi research candidate-relationships --protocol five_candidate_relationship_topology_v1`.
- Builder: `build_five_candidate_relationship_service(session: Session) -> FiveCandidateRelationshipService`.

- [ ] **Step 1: Write RED parser/request tests**

Exact protocol only. Add invalid flag cases for `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`.

- [ ] **Step 2: Write RED Session-backed CLI test**

Use a counting context manager and fake relationship factory. Assert the command enters exactly one Session context. This intentionally contrasts with the Task 4 zero-Session dossier test.

- [ ] **Step 3: Write RED composition-source test**

Patch `build_jdj_research_service(session)` to return a sentinel runner. Assert `build_five_candidate_relationship_service(session)` passes that sentinel to the service. Patch `build_n_structure_research_service` and `build_multi_candidate_robustness_service` to fail if invoked; Phase 8B must not create duplicate N or robustness recomputation paths.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: parser/factory/dispatch failures.

- [ ] **Step 5: Implement relationship composition**

The builder performs exactly these steps in order:

1. load exact `five_candidate_relationship_topology_v1` protocol;
2. verify Task 5 dossier artifact path/SHA;
3. verify existing SuBing/N robustness artifact path/SHA;
4. build one `JdjResearchService(session)`;
5. return `FiveCandidateRelationshipService(protocol, jdj_research=runner, dossier_source=verified_dossier, existing_relationship_source=verified_robustness)`.

- [ ] **Step 6: Add parser/request/command dispatch**

Add `FiveCandidateRelationshipRequest` to `ResearchRequest`; dispatch it inside the existing Session-backed research path. Do not move `candidate-dossier` back under Session creation.

- [ ] **Step 7: Implement deterministic relationship payload**

Render exact 10 catalog pairs, 180 dependency rows, 180 overlap rows and typed unavailable rows. Do not serialize source event details, full prior robustness matrices, or future outcomes.

- [ ] **Step 8: Add forbidden-field and redaction tests**

Reject keys: `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote`, `combined_return`, `overlap_return`, `expected_profit`, `pnl`. Protocol/source/context errors must use the existing redacted CLI error JSON and must not expose source paths/content/traceback.

- [ ] **Step 9: Run Task 9 regressions and commit**

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

- [ ] **Step 3: Generate relationship evidence twice and require byte equality**

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

- [ ] **Step 4: Verify exact topology invariants**

Use parsed JSON assertions:

```python
payload = json.loads(Path("/private/tmp/guiyi-phase8/relationships-1.json").read_text())
assert len(payload["relationship_catalog"]) == 10
assert len(payload["n_jdj_dependency_results"]) == 180
assert len(payload["jdj_exact_overlap_results"]) == 180
assert payload["prospective_consumed"] is False
assert payload["analysis_windows"]["n_jdj"] == {"since": "2023-01-01", "through": "2026-08-19"}
assert payload["analysis_windows"]["jdj_overlap"] == {"since": "2023-01-01", "through": "2026-08-20"}
```

Also assert all SuBing↔JDJ catalog rows use `UNDEFINED_CROSS_TIMEFRAME`, no N→JDJ/JDJ-overlap numeric proximity value exists, and every available dependency row satisfies the required lineage count equality.

- [ ] **Step 5: Copy exact stdout as tracked evidence and compute SHA**

```bash
mkdir -p reports/research/candidate_relationships/five_candidate_relationship_topology_v1
cp /private/tmp/guiyi-phase8/relationships-1.json \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
```

- [ ] **Step 6: Update canonical docs to close Phase 8 only**

- `STATUS.md`: record both Phase 8A/8B artifact paths/SHA and exact boundaries; keep all prospective OOS states truthful.
- `PROJECT_SOURCE.md`: add Candidate convergence + relationship topology as read-only research surfaces.
- `DECISIONS.md`: record no common five-Candidate window; N→JDJ dependency is not independent signal confirmation; JDJ overlap V1 is exact-boundary only; SuBing↔JDJ remains undefined.
- `docs/ARCHITECTURE.md`: show the Phase 8A artifact-only node and Phase 8B JDJ source node with separate 8/19 and 8/20 windows.
- `TESTING.md`: add exact Phase 8A/8B commands and no-side-effect/no-promotion statement.

- [ ] **Step 7: Run final docs/secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Open independent Sol/high review before integration**

Review the complete Phase 8B branch diff for:

1. N embargo/future leakage;
2. accidental `event_outcomes` use in overlap;
3. invented proximity/lead-lag parameters;
4. N→JDJ wording implying independent confirmation;
5. missing 180/180 identity rows or typed unavailable rows;
6. automatic ranking/promotion/trading claims;
7. DB/Canonical/Redis/Alert/Runtime side effects.

Critical/Important findings must be fixed and affected checks rerun.

- [ ] **Step 9: Commit Task 10**

```bash
git add \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze phase 8 relationship topology evidence"
```

- [ ] **Step 10: Integrate to `develop` and clean workspace**

After all tests and independent review pass, integrate the Phase 8B task branch into `develop` using the repository's current ordinary development flow. Confirm Task 6–10 commits are in `develop`, then delete the merged temporary worktree/branch. Do not touch `main`, create a tag, release, switch Runtime, send notifications, or perform real data/DB mutation.

---

# Codex Scheduling Matrix

| Segment | Tasks | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
|---|---:|---|---|---|---|---|---|---|
| Phase 8A | 1–5 | Lane 1 | Sol | High | new | Plan-then-execute | new task worktree from latest `develop` | independent review before 8A integration |
| Phase 8B | 6–10 | Lane 1 | Sol | High | new after 8A integration | Plan-then-execute | new task worktree from updated `develop` | independent review before integration |

## Worktree Flow

```text
latest develop
  → research/five-candidate-dossier-v1 task worktree
  → Tasks 1–5
  → independent review
  → integrate develop
  → verify integration
  → cleanup Phase 8A task worktree/branch

updated develop
  → research/five-candidate-relationship-topology-v1 task worktree
  → Tasks 6–10
  → independent Sol/high review
  → integrate develop
  → verify integration
  → cleanup Phase 8B task worktree/branch
```

PR is optional under the current repository workflow. Neither segment may touch `main`, tag or Runtime. Release approval and Runtime promotion remain separate future Gates.

# Task Contract Summary

Every Task ends with:

```text
1. exact scoped diff only;
2. RED→GREEN focused tests;
3. relevant regressions;
4. no unrelated refactor;
5. no real write / Runtime / notification side effect;
6. a task-scoped commit;
7. completion output containing modification summary, tests, risks and unresolved items.
```

Task 5 and Task 10 evidence completion reports must additionally include exact artifact SHA256. Evidence does not grant Candidate promotion or release authority.

# Final Acceptance

Phase 8 is complete only when both tracked artifacts exist, deterministic generation is verified, all 300 Phase 8A source identities and all 360 Phase 8B relationship identities are preserved, N/JDJ embargo and prospective boundaries are untouched, and canonical docs describe only evidence convergence/topology facts.

Allowed final verdict after Task 10 review: **允许集成 develop**.

Not allowed from this plan alone: **允许发布 main/tag** or **允许 Runtime promotion**.
