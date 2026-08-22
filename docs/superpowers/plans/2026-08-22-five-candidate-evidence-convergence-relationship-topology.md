# Phase 8 — Five-Candidate Evidence Convergence & Relationship Topology V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a deterministic five-Candidate evidence dossier, then freeze a relationship topology that distinguishes existing SuBing↔N event relationships, N→JDJ structural dependencies, exact JDJ↔JDJ same-boundary overlap, and undefined SuBing↔JDJ cross-timeframe relations without ranking Candidates or consuming prospective OOS.

**Architecture:** Phase 8A is artifact-only composition over seven Git-tracked frozen JSON artifacts and must execute before any DB Session is opened. Phase 8B is a separate Historical read-only recomputation using the existing `JdjResearchService`: one exact window through `2026-08-19` for N→JDJ dependency and a separate exact window through `2026-08-20` for JDJ overlap. The two phases share only bounded artifact verification and deterministic rendering; they do not create a general research platform or persistence layer.

**Tech Stack:** Python 3.12, dataclasses, `Decimal`, existing SQLAlchemy Session pattern for Phase 8B only, `MarketDataService → ActualDominantResearchSegmentLoader → JdjResearchService`, pytest, Ruff, Mypy, existing `guiyi research` CLI JSON renderer.

**Spec:** `docs/superpowers/specs/2026-08-22-five-candidate-evidence-convergence-relationship-topology-design.md`

## Global Constraints

- Start each execution segment from the latest `develop`; re-read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, this plan, the spec, and task-related source/tests.
- Exact Candidate order is: `subing_lifecycle_v2_candidate_v1`, `n_structure_5m_candidate_v1`, `jdj_trend_follow_1m_candidate_v1`, `jdj_trend_reentry_6_1m_candidate_v1`, `jdj_key_level_breakout_1m_candidate_v1`.
- Never create a Five-Candidate common retrospective window.
- Phase 8A reads only seven frozen repository artifacts and creates zero DB Sessions, zero MarketDataService objects, zero Candidate runners and zero robustness runners.
- Phase 8B N→JDJ dependency window is exactly `2023-01-01..2026-08-19`.
- Phase 8B JDJ↔JDJ exact-overlap window is exactly `2023-01-01..2026-08-20`.
- Never read N `2026-08-20` for N→JDJ dependency and filter it away later.
- Never consume JDJ `2026-08-21` embargo or `2026-08-24+` prospective OOS.
- Do not mutate or backfill any Candidate prospective evidence.
- No new Candidate, formula, parameter, parameter sweep, score, rank, winner, KEEP, DROP, ITERATE, PROMOTE or overlap-conditioned future outcome.
- No backtest/fill/order/position/cost/equity/PnL subsystem.
- No Alert/Scope/Execution Review/Runtime changes; no DB/Canonical/Redis writes; no main/tag/release/Runtime promotion; `auto_order=false` remains fixed.
- Keep `unavailable`, available zero-event and zero-sample as three distinct states.
- Tracked Phase 8 evidence must be exact CLI stdout generated only after the required verification passes; never hand-edit evidence JSON.
- Task 5 is a hard checkpoint. Phase 8B starts only after Tasks 1–5 are integrated to `develop` and a new Phase 8B worktree/session is created from updated `develop`.

---

## File Structure

### New files

- `data/research_protocols/five_candidate_research_dossier_v1.json` — exact Phase 8A protocol.
- `data/research_protocols/five_candidate_relationship_topology_v1.json` — exact Phase 8B protocol, created only after Task 5 evidence SHA is known.
- `services/quant-api/app/research/candidate_convergence/__init__.py` — package marker.
- `services/quant-api/app/research/candidate_convergence/artifact_source.py` — repo-relative path, SHA256, UTF-8 and JSON-object verifier shared by 8A/8B.
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py` — 8A protocol/request/report contracts and invariants.
- `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py` — pure seven-artifact composition.
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py` — 8B protocol/request/report contracts and invariants.
- `services/quant-api/app/research/candidate_convergence/jdj_exact_overlap.py` — exact-boundary JDJ pair reducer with no proximity/future outcome.
- `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py` — 8B orchestration over two separate JDJ batch windows plus existing frozen SuBing/N relationship reference.
- `services/quant-api/tests/test_five_candidate_dossier.py` — 8A protocol/artifact/report/service tests.
- `services/quant-api/tests/test_five_candidate_relationships.py` — 8B protocol/dependency/overlap/report tests.
- `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json` — Task 5 evidence.
- `reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json` — Task 10 evidence.

### Existing files modified

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

# Execution Segment A — Phase 8A

## Task 1: Freeze Dossier Protocol and Artifact Integrity

**Lane:** Lane 1 / Sol / high reasoning / Plan-then-execute.

**Files:**
- Create: `data/research_protocols/five_candidate_research_dossier_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/__init__.py`
- Create: `services/quant-api/app/research/candidate_convergence/artifact_source.py`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Create: `services/quant-api/tests/test_five_candidate_dossier.py`

**Interfaces:**
- Produce `SourceArtifactRef`, `VerifiedJsonArtifact`, `verify_json_artifact`, `FiveCandidateDossierProtocol`, `FiveCandidateDossierRequest`, `load_five_candidate_dossier_protocol`.
- Stable errors: `FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID`, `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`.

- [ ] **Step 1: Write RED exact-protocol tests**

Add one test that asserts candidate order, seven artifact refs, ten pair refs, all safety booleans, `research_only=true`, `readonly=true` and `prospective_consumed=false`.

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

- [ ] **Step 2: Write RED protocol drift tests**

Load the exact protocol JSON with `json.loads`, copy it, then independently test these mutations: extra top-level field, candidate order swap, pair order swap, absolute artifact path, `../` path escape, invalid SHA string. Each case must raise `FiveCandidateDossierProtocolError`.

- [ ] **Step 3: Run RED tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: import/collection failure because the new package/contracts do not exist.

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

`SourceArtifactRef.__post_init__` must reject empty IDs, absolute paths, empty/`.`/`..` path components, non-ASCII path/control characters and any SHA that is not exactly 64 lowercase hex characters.

- [ ] **Step 5: Implement bounded artifact verification**

Use this algorithm in `verify_json_artifact`:

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

Public exceptions must not contain resolved paths, source JSON or mismatched hashes.

- [ ] **Step 6: Implement the exact dossier protocol loader**

Use existing `load_exact_json` for the protocol file. `FiveCandidateDossierProtocol.__post_init__` must repeat the exact identity/order/value validation so direct construction cannot bypass the loader. Copy the seven repository-relative paths and SHA256 values exactly from the approved spec.

- [ ] **Step 7: Add real-source verification test**

Load all seven tracked source artifacts through `verify_json_artifact` and assert each verified SHA equals its expected SHA. The test must not open a DB Session or construct MDS/Candidate/robustness services.

- [ ] **Step 8: Run GREEN tests and Ruff**

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
- Consume Task 1 protocol/artifact types.
- Produce `CandidateBaselineEvidence`, `CandidateRobustnessEvidence`, `CandidateDossier`, `FiveCandidateResearchDossier`, `FiveCandidateResearchDossierService`.
- Stable report error: `FIVE_CANDIDATE_DOSSIER_REPORT_INVALID`.

- [ ] **Step 1: Write RED report inventory test**

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

Use fixture artifacts to verify:

```text
unavailable → typed reason + event/count/metric fields null
available zero-event → status available + event_count 0
zero-sample horizon → sample_count 0 + numeric metrics null
```

Also verify illegal hybrids fail closed: unavailable with numeric event count; zero-sample with numeric median; available row with unavailable reason code.

- [ ] **Step 3: Run RED tests**

Run Task 1 pytest command. Expected: missing report/service types.

- [ ] **Step 4: Implement source-specific identity constants**

Use one immutable source-semantics mapping with these exact values:

```python
SOURCE_SEMANTICS = {
    "subing_lifecycle_v2_candidate_v1": ("subing_lifecycle", ("5m", "15m"), "5m_ready_boundary", "same_trading_day_only", (3, 5, 8)),
    "n_structure_5m_candidate_v1": ("n_structure", ("5m",), "5m_canonical_bar", "same_rank1_segment", (3, 5, 8)),
    "jdj_trend_follow_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_trend_reentry_6_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
    "jdj_key_level_breakout_1m_candidate_v1": ("jdj_1m", ("1m", "5m_strict_before_context"), "1m_canonical_bar", "same_trading_day_physical_contract_rank1_segment", (3, 5, 8, 20)),
}
```

- [ ] **Step 5: Implement the pure service**

Exact public interfaces:

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

`run` must perform these six operations in order:

1. validate request/protocol identity;
2. verify seven artifacts exactly once;
3. validate candidate/protocol/window/order identity of each artifact;
4. project baseline identity/count/status/window facts;
5. project robustness availability/unavailable/zero-event/zero-sample/sector/yearly inventory without recomputing metrics;
6. return immutable report rows in protocol order.

The service constructor and run path must have no `Session`, MDS, provider, Redis, Candidate service or robustness service dependency.

- [ ] **Step 6: Add semantic-drift tests independent of SHA drift**

For each fixture, mutate one semantic field and recompute that fixture SHA so hash verification passes. Cover wrong candidate ID, wrong protocol ID, wrong retrospective through date, wrong cross-symbol row count and row-order drift. Every case must raise `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID` and return no partial dossier.

- [ ] **Step 7: Run Task 2 tests and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_five_candidate_dossier.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_jdj_robustness.py
```

Expected: PASS.

```bash
git add services/quant-api/app/research/candidate_convergence \
  services/quant-api/tests/test_five_candidate_dossier.py
git commit -m "feat(research): compose five-candidate dossier"
```

---

## Task 3: Freeze Comparability Catalog and Existing SuBing↔N Relationship Reference

**Files:**
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Modify: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- Modify: `services/quant-api/tests/test_five_candidate_dossier.py`

**Interfaces:**
- Produce `ComparabilityStatus`, `MetricComparability`, exact ten `ComparabilityPair` rows and projection of existing SuBing↔N relationship facts.

- [ ] **Step 1: Write RED exact pair-status test**

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

Assert exactly 10 unique unordered pairs, no self-pair and no reversed duplicate.

- [ ] **Step 2: Write RED metric-catalog test**

Verify five-Candidate shared metrics are evidence-completeness metrics only; JDJ-only event-rate/long-short/3-5-8-20/yearly/sector metrics list exactly the three JDJ candidates; SuBing/N horizon metrics carry `EVALUABLE_UNIT_DIFFERS` and `HORIZON_SEMANTICS_DIFFERS`.

- [ ] **Step 3: Write RED existing relationship projection test**

Use a multi-candidate robustness fixture with both directional SuBing↔N relationship rows. Assert the dossier copies the existing relationship values and existing source window exactly. Patch the existing relationship summarizer to raise if called so this test proves 8A performs no relationship recomputation.

- [ ] **Step 4: Implement exact comparability enum and pair contract**

```python
class ComparabilityStatus(StrEnum):
    SUPPORTED_EXISTING = "SUPPORTED_EXISTING"
    SUPPORTED_SAME_FAMILY = "SUPPORTED_SAME_FAMILY"
    NOT_YET_DEFINED = "NOT_YET_DEFINED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
```

`ComparabilityPair` contains only left/right Candidate IDs, status, reason codes and optional existing-relationship reference. Do not add numeric pair score/performance fields.

- [ ] **Step 5: Add forbidden decision-key test**

Recursively collect report keys and assert they do not contain:

```python
FORBIDDEN_KEYS = {
    "score", "rank", "winner", "best", "keep", "drop", "iterate",
    "promote", "approved", "expected_profit", "profitability", "pnl",
}
```

- [ ] **Step 6: Run Task 3 tests and commit**

Run the Task 2 pytest command. Expected: PASS.

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
- Builder: `build_five_candidate_dossier_service() -> FiveCandidateResearchDossierService` with no Session argument.

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

- [ ] **Step 2: Write RED invalid-flag tests**

For each of `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`, invoke the exact dossier command with the extra flag/value and require CLI argument failure. Unknown protocol must also fail.

- [ ] **Step 3: Write RED no-Session dispatch test**

Create a local fake dossier service whose `run` returns a valid report fixture. Pass a `session_factory` function that calls `pytest.fail` immediately. Invoke the dossier CLI and assert exit code 0. This test proves the dossier branch executes before Session creation.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_dossier.py
```

Expected: parser/request/factory/dispatch failures.

- [ ] **Step 5: Add parser/request/typed command support**

`research_parser.py` adds only the exact required `--protocol`. `research_requests.py` adds `FiveCandidateDossierRequest` to `ResearchRequest`. `research_commands.py` adds typed dossier dispatch before the existing robustness branches.

- [ ] **Step 6: Change `main()` so only dossier bypasses Session creation**

Preserve the existing Session-backed `elif` chain. Wrap it like this:

```python
elif args.domain == "research":
    assert research_request is not None
    if isinstance(research_request, FiveCandidateDossierRequest):
        service = candidate_dossier_service_factory()
        payload = run_research_command(research_request, service)
    else:
        with session_factory() as session:
            # Keep the existing research-command service selection here.
            # Do not change existing service identity or order except to add Phase 8B later.
            service = select_existing_research_service_inside_this_block
            payload = run_research_command(research_request, service)
```

The repository implementation must preserve the current concrete `elif` branches instead of introducing the descriptive `select_existing_research_service_inside_this_block` name. This plan intentionally requires no new helper abstraction for the existing dispatch.

- [ ] **Step 7: Implement deterministic dossier payload**

Render exact protocol/Candidate/artifact/pair order, reuse the existing Decimal-to-string helper, render Decimal zero as `"0"`, and omit full 120/180 source matrices.

- [ ] **Step 8: Add redacted error test**

Force `FiveCandidateDossierSourceError`; stderr must contain only the public error shape/code with `readonly=true` and must not contain absolute paths, source JSON, source SHA or traceback.

- [ ] **Step 9: Run CLI regressions and commit**

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

## Task 5: Freeze Phase 8A Evidence and Close 8A Canonical Boundary

**Files:**
- Create: `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`
- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`

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

Expected: PASS.

- [ ] **Step 2: Run repository-native backend/static checks**

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

Assert five Candidates, seven source artifacts, ten comparability pairs, `prospective_consumed=false`, source cells `300`, available `245`, unavailable `55`, and no forbidden automatic-decision keys.

- [ ] **Step 5: Track exact stdout and compute SHA256**

```bash
mkdir -p reports/research/candidate_dossier/five_candidate_research_dossier_v1
cp /private/tmp/guiyi-phase8/dossier-1.json \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Record the exact SHA in the completion report and `STATUS.md`. Task 6 must freeze the same SHA verbatim.

- [ ] **Step 6: Update canonical docs narrowly**

- `STATUS.md`: Phase 8A evidence path/SHA; Phase 8B explicitly not complete; all prospective states unchanged.
- `PROJECT_SOURCE.md`: artifact-only dossier boundary, source-specific windows, no ranking.
- `DECISIONS.md`: no Five-Candidate common window; comparability and relationship are distinct concepts.
- `docs/ARCHITECTURE.md`: add an artifact-only `FiveCandidateResearchDossierService` node with no MDS edge.
- `TESTING.md`: add exact `candidate-dossier` verification command and no-side-effect statement.

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

Run an independent review over Tasks 1–5. Fix Critical/Important findings and rerun affected verification. After acceptance, integrate the Phase 8A branch to `develop`, verify the commits and artifact in `develop`, clean the task worktree/branch, then start Segment B from updated `develop` in a new session/worktree.

---

# Execution Segment B — Phase 8B

## Task 6: Freeze Relationship Topology Protocol and Report Contracts

**Lane:** Lane 1 / Sol / high reasoning / new session / Plan-then-execute.

**Files:**
- Create: `data/research_protocols/five_candidate_relationship_topology_v1.json`
- Create: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- Create: `services/quant-api/tests/test_five_candidate_relationships.py`
- Modify: `services/quant-api/app/research/candidate_convergence/artifact_source.py` only if a narrowly typed verifier extension is actually needed.

**Interfaces:**
- Produce `RelationshipKind`, `DependencyRole`, `FiveCandidateRelationshipProtocol`, `FiveCandidateRelationshipRequest`, dependency/overlap/report VOs and exact loader.
- Stable errors: `FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID`, `FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID`.

- [ ] **Step 1: Verify integrated 8A artifact identity**

```bash
sha256sum \
  reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json
```

Compare with `STATUS.md`. Any mismatch blocks Task 6.

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

- [ ] **Step 3: Write RED protocol-drift tests**

Independently mutate N→JDJ through to `2026-08-20`, JDJ overlap through to `2026-08-21`, either proximity to numeric `1`, `future_outcomes` to true, pair order, Task 5 dossier SHA, and SuBing↔JDJ recompute to true. Every case must fail before the JDJ runner is invoked.

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

- [ ] **Step 6: Implement exact protocol using real 8A SHA**

The committed 8B protocol must contain the actual Task 5 dossier SHA, the existing SuBing/N robustness path/SHA from the approved spec, exact Candidate/pair order, exact windows and all disabled safety flags. No placeholder hash is permitted.

- [ ] **Step 7: Implement report invariants**

Require exactly:

```text
10 relationship catalog pairs
180 dependency rows = 3 JDJ candidates × 60 symbols
180 overlap rows = 3 unordered JDJ pairs × 60 symbols
candidate-major/symbol order for dependency rows
pair-major/symbol order for overlap rows
typed unavailable rows with all metric fields null
```

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

**Interfaces:**
- Consume `JdjResearchService.run_batch(symbol, since, through)` and exact JDJ event types.
- Produce 180 `CandidateDependencyResult` rows.

- [ ] **Step 1: Write RED runner-window test**

Fake runner records calls. Dependency projection must call each active60 symbol exactly once with `since=2023-01-01`, `through=2026-08-19`.

- [ ] **Step 2: Write RED lineage-completeness tests**

For available rows require:

```python
assert tf.events_with_trend_snapshot_lineage == tf.event_count
assert tf.events_with_exact_pivot_lineage is None
assert r6.events_with_trend_snapshot_lineage == r6.event_count
assert r6.events_with_exact_pivot_lineage is None
assert klb.events_with_trend_snapshot_lineage == klb.event_count
assert klb.events_with_exact_pivot_lineage == klb.event_count
```

Also create a deliberately invalid boundary object missing required lineage and require execution/report validation failure rather than a degraded ratio.

- [ ] **Step 3: Write RED unavailable-row test**

When `JdjSourceUnavailableError` occurs for one symbol, retain three dependency identity rows for that symbol with `status=unavailable`, `reason_code=JDJ_SOURCE_UNAVAILABLE` and all lineage/count metrics null.

- [ ] **Step 4: Run RED tests**

Use Task 6 pytest command. Expected: missing service/projection failures.

- [ ] **Step 5: Implement dependency projection**

For each symbol call the runner once for the exact N-safe window. Dependency role is exact:

```python
if candidate_id == "jdj_key_level_breakout_1m_candidate_v1":
    role = DependencyRole.TREND_AND_PIVOT_SOURCE
else:
    role = DependencyRole.TREND_FILTER
```

Count lineage only from immutable JDJ events. Do not call `NStructureResearchService.completion_events()` and do not join N completion events by time.

- [ ] **Step 6: Enforce source identity and error boundary**

Require batch symbol, Candidate order, products and event identity to satisfy existing JDJ contracts. Only `JdjSourceUnavailableError` maps to typed unavailable. `JdjContextError` or invalid event identity fails the whole execution.

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
- Produce `summarize_exact_jdj_overlap(left, right, *, symbol) -> JdjExactOverlapResult`.
- The reducer must not inspect `event_outcomes`.

- [ ] **Step 1: Write RED exact-boundary-key tests**

Create event pairs differing one field at a time: contract, segment start trading day, trading day, segment bar index, observed_at. Only full identity equality may count as overlap.

- [ ] **Step 2: Write RED direction tests**

Same boundary + same direction increments only `exact_same_boundary_same_direction_count`. Same boundary + opposite direction increments only `exact_same_boundary_opposite_direction_count`.

- [ ] **Step 3: Write RED unique matched-event tests**

Verify `left_events_with_same_direction_match` and `right_events_with_same_direction_match` count unique matched source event IDs rather than Cartesian match multiplicity. Duplicate event IDs must fail validation.

- [ ] **Step 4: Write RED no-future-outcome test**

Build two detailed Candidate inputs with identical event streams but different `event_outcomes`; overlap reports must compare equal. This is the mechanical proof that future outcomes are ignored.

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

Index right events by boundary and direction; count exact same/opposite direction matches and unique same-direction matched event IDs. The public function accepts no proximity, horizon or outcome argument. Do not import `PriceDirectionalOutcome`.

- [ ] **Step 7: Add separate overlap-window service test**

Assert overlap orchestration calls each active60 symbol with exactly `2023-01-01..2026-08-20`. Assert these calls are separate from the Task 7 `2023-01-01..2026-08-19` dependency calls rather than a later-window reuse/filter.

- [ ] **Step 8: Assert exact 180 overlap rows**

Pair order is `(TF,R6)`, `(TF,KLB)`, `(R6,KLB)`; symbol order is active60. Source unavailable retains all three pair rows for that symbol.

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

Accept only the exact protocol. Add invalid flag cases for `--since`, `--through`, `--symbol`, `--candidate`, `--products`, `--threshold`, `--score`, `--rank`.

- [ ] **Step 2: Write RED Session-backed CLI test**

Use a counting context manager and fake relationship service factory; assert one Session context entry. Keep the Task 4 no-Session dossier test passing in the same file.

- [ ] **Step 3: Write RED composition source test**

Patch `build_jdj_research_service(session)` to return a sentinel runner and assert that sentinel is injected. Patch `build_n_structure_research_service` and `build_multi_candidate_robustness_service` to fail if called so no duplicate N/robustness recomputation path can appear.

- [ ] **Step 4: Run RED CLI tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli.py \
  services/quant-api/tests/test_five_candidate_relationships.py
```

Expected: parser/factory/dispatch failures.

- [ ] **Step 5: Implement relationship composition**

Builder order is exact:

1. load `five_candidate_relationship_topology_v1`;
2. verify Task 5 dossier artifact path/SHA;
3. verify existing SuBing/N robustness artifact path/SHA;
4. build exactly one `JdjResearchService(session)`;
5. construct `FiveCandidateRelationshipService` with those verified sources and runner.

- [ ] **Step 6: Add parser/request/command dispatch**

Add `FiveCandidateRelationshipRequest` to `ResearchRequest` and dispatch inside the existing Session-backed research path. Do not move `candidate-dossier` under Session creation.

- [ ] **Step 7: Implement deterministic relationship payload**

Render exact 10 catalog pairs, 180 dependency rows, 180 overlap rows and typed unavailable rows. Do not serialize source-event details, full prior robustness matrices or future outcomes.

- [ ] **Step 8: Add forbidden-key and redaction tests**

Reject report keys: `score`, `rank`, `winner`, `best`, `keep`, `drop`, `iterate`, `promote`, `combined_return`, `overlap_return`, `expected_profit`, `pnl`. Protocol/source/context errors must use existing redacted CLI JSON without source path/content/traceback leakage.

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

- [ ] **Step 1: Run complete focused Phase 8 regressions**

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

- [ ] **Step 4: Verify exact topology invariants**

Assert:

```text
relationship_catalog count = 10
n_jdj_dependency_results count = 180
jdj_exact_overlap_results count = 180
prospective_consumed = false
N→JDJ window = 2023-01-01..2026-08-19
JDJ overlap window = 2023-01-01..2026-08-20
all SuBing↔JDJ rows = UNDEFINED_CROSS_TIMEFRAME
no numeric proximity for N→JDJ or JDJ overlap
all available dependency rows satisfy exact lineage-count equality
no overlap-conditioned future outcome field exists
```

- [ ] **Step 5: Track exact stdout and compute SHA256**

```bash
mkdir -p reports/research/candidate_relationships/five_candidate_relationship_topology_v1
cp /private/tmp/guiyi-phase8/relationships-1.json \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
sha256sum \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json
```

- [ ] **Step 6: Update canonical docs to close Phase 8 only**

- `STATUS.md`: both Phase 8A/8B artifact paths/SHA and exact boundaries; keep prospective OOS states truthful.
- `PROJECT_SOURCE.md`: Candidate convergence + relationship topology as read-only research surfaces.
- `DECISIONS.md`: no common five-Candidate window; N→JDJ dependency is not independent signal confirmation; JDJ overlap V1 is exact-boundary only; SuBing↔JDJ remains undefined.
- `docs/ARCHITECTURE.md`: Phase 8A artifact-only node and Phase 8B JDJ source node with separate `through=2026-08-19` and `through=2026-08-20` paths.
- `TESTING.md`: exact Phase 8A/8B commands and no-side-effect/no-promotion statement.

- [ ] **Step 7: Run final docs checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Open independent Sol/high review**

Review the complete Segment B diff for:

1. N embargo/future leakage;
2. accidental `event_outcomes` use in overlap;
3. invented proximity/lead-lag parameters;
4. N→JDJ wording implying independent confirmation;
5. missing 180/180 identity rows or typed unavailable rows;
6. automatic ranking/promotion/trading claims;
7. DB/Canonical/Redis/Alert/Runtime side effects.

Critical/Important findings must be fixed and affected verification rerun.

- [ ] **Step 9: Commit Task 10**

```bash
git add \
  reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git commit -m "docs(research): freeze phase 8 relationship topology evidence"
```

- [ ] **Step 10: Integrate to `develop` and clean workspace**

After all tests and independent review pass, integrate Segment B to `develop`, confirm Tasks 6–10 are in `develop`, then delete the merged temporary worktree/branch. Do not touch `main`, create a tag, release, switch Runtime, send notifications, or perform real data/DB mutation.

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

PR is optional under current repository workflow. Neither segment may touch `main`, tag or Runtime. Release approval and Runtime promotion remain separate future Gates.

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

Task 5 and Task 10 completion reports must additionally include exact evidence SHA256. Evidence does not grant Candidate promotion or release authority.

# Final Acceptance

Phase 8 is complete only when both tracked artifacts exist, deterministic generation is verified, all 300 Phase 8A source identities and all 360 Phase 8B relationship identities are preserved, N/JDJ embargo and prospective boundaries are untouched, and canonical docs describe only evidence convergence/topology facts.

Allowed final verdict after Task 10 review: **允许集成 develop**.

Not allowed from this plan alone: **允许发布 main/tag** or **允许 Runtime promotion**.
