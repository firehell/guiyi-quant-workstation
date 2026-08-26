# Market Structure V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a clean-room, causal, read-only `market_structure_v1` capability through four independently gated stages: calibrated formula, pure kernel, internal research projection, and optional Market context UI.

**Architecture:** One pure quant-core engine owns all formula semantics. Application services resolve logical/physical market identity, full segment context, completed-Live seams, policy approval, and provenance. Source-specific read models project facts to CLI/API; Web only renders those facts as a context layer and never joins the four strategy-overlay ids.

**Tech Stack:** Python 3.13+, `Decimal`, dataclasses, Pydantic/FastAPI, SQLAlchemy read composition, `MarketDataService`, pytest, Ruff, Mypy, Vue 3, TypeScript, Vitest, Naive UI, Lightweight Charts, Playwright.

**Spec:** [Market Structure V1 Design Spec](../specs/2026-08-25-market-structure-v1-design.md)

## Global Constraints

- This document is an execution plan, not implementation authorization. The current documentation branch changes no runtime code.
- After creating each stage worktree, prepare the locked Python environment with `uv sync --project services/quant-api --locked`; before Stage D Web tests, also run `pnpm --dir apps/quant-web install --frozen-lockfile`.
- Use a new worktree and a new branch from the then-current `develop` for each stage. Never continue on the documentation branch after its PR merges.
- Stage branches are sequential:
  - A: `research/market-structure-v1-stage-a`
  - B: `research/market-structure-v1-stage-b`
  - C: `research/market-structure-v1-stage-c`
  - D: `feat/market-structure-v1-stage-d`
- Do not start the next stage until the prior stage has fresh verification, independent review, a human `允许集成 develop` decision, and is present in `develop`.
- Stage D additionally requires a new human `允许继续实现` decision after reviewing Stage C evidence. Approval of this plan does not satisfy that Gate.
- Preserve existing SuBing, N Structure, JDJ, HTDY, Market overlays, Alert, Execution Review, Canonical, Live, and Runtime behavior. Do not create a generic strategy adapter or policy DSL.
- Do not add DB tables, migrations, Redis keys, workers, schedulers, queues, replay/backfill, notifications, orders, `main` changes, tags, releases, or Runtime promotion.
- Historical reads go only through `MarketDataService`; actual-dominant segmentation uses `ActualDominantResearchSegmentLoader`; D1/W1 remain Canonical-only.
- Do not invent or scrape acceptance evidence. If the user-authorized same-feed observation corpus is absent or below the Spec minimum, Stage A must return `calibration_evidence_insufficient` and stop.
- `packages/quant-core/guiyi_quant/indicators/market_structure_v1.py` is the single formula file. After Stage A freezes its digest, any byte change returns execution to Stage A.
- Each implementation step follows red → green → refactor: write the named failing test, run it and observe the expected failure, implement the minimum behavior, rerun, then commit only task files.
- At every Gate, report one of the project conclusions exactly: `允许继续实现`, `允许集成 develop`, `要求修正后再集成`, or `阻塞`.

## Execution Card

| Field | Value |
|---|---|
| Lane | Lane 3 — formula/causality/evidence-sensitive |
| Mode | Code only after the applicable Gate; current change remains Plan-only |
| Recommended worker | Codex App, Sol, high reasoning, new session |
| Isolation | one worktree + branch per stage |
| Review | independent read-only reviewer for every stage head |
| Integration | PR to `develop`; no automatic merge |
| External operations | prohibited |

---

## Stage A — Clean-room evaluator and frozen calibration

### Task 1: Create the corpus/protocol contract and fail-closed validator

**Files:**

- Create: `services/quant-api/app/research/market_structure/__init__.py`
- Create: `services/quant-api/app/research/market_structure/calibration_contract.py`
- Create: `data/research_protocols/market_structure_clean_room_v1.json`
- Create: `services/quant-api/tests/research/test_market_structure_calibration_contract.py`
- Create: `services/quant-api/tests/fixtures/market_structure_v1/synthetic_manifest.json`

- [ ] Create the Stage A worktree from the latest `origin/develop`, record base SHA, and confirm no unrelated dirty paths:

```bash
git fetch origin
git worktree add ../guiyi-market-structure-stage-a \
  -b research/market-structure-v1-stage-a origin/develop
git -C ../guiyi-market-structure-stage-a status --short
git -C ../guiyi-market-structure-stage-a rev-parse HEAD
```

- [ ] Write failing validator tests for schema version, `evidence_tier`, exact-feed identity, Decimal strings, seven-frequency coverage, scored-label counts, frozen calibration/holdout ids, lifecycle minima, active-leg minima, and digest ordering.

```python
def test_acceptance_manifest_requires_every_frequency_and_split_minimum() -> None:
    with pytest.raises(CalibrationEvidenceError) as exc:
        validate_corpus_manifest(incomplete_manifest())
    assert exc.value.reason == "calibration_evidence_insufficient"


def test_corpus_digest_ignores_images_and_exploratory_records() -> None:
    assert corpus_digest(manifest_a) == corpus_digest(manifest_b)
```

- [ ] Run the tests and confirm they fail because the contract module is absent:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py
```

- [ ] Implement immutable manifest/fixture dataclasses and canonical JSON hashing. Use exact Decimal strings; do not add a tick-size source or use retired fee/margin fields.

```python
@dataclass(frozen=True, slots=True)
class ObservationEvent:
    kind: Literal["high", "low"]
    label: Literal["HH", "LH", "EH", "HL", "LL", "EL"]
    pivot_time: datetime
    price: Decimal


def validate_corpus_manifest(payload: Mapping[str, object]) -> CorpusManifest: ...
def corpus_digest(manifest: CorpusManifest) -> str: ...
```

- [ ] Freeze the grid and thresholds in `market_structure_clean_room_v1.json`; the validator must reject any manifest whose embedded protocol id/digest differs.

- [ ] Keep `synthetic_manifest.json` explicitly `evidence_tier=exploratory`; tests must prove it can test mechanics but cannot pass the acceptance Gate.

- [ ] Re-run the focused tests, Ruff the new module/tests, and commit:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/research/market_structure \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py
git add services/quant-api/app/research/market_structure \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py \
  services/quant-api/tests/fixtures/market_structure_v1/synthetic_manifest.json \
  data/research_protocols/market_structure_clean_room_v1.json
git commit -m "test(research): define market structure calibration contract"
```

### Task 2: Implement the unregistered A0 formula engine

**Files:**

- Create: `packages/quant-core/guiyi_quant/indicators/market_structure_v1.py`
- Create: `services/quant-api/tests/test_market_structure_v1_formula.py`

- [ ] Write failing tests for the local Decimal context, OHLC/time validation, strict symmetric pivots, Wilder ATR, move filter, equality, plateau rejection, ambiguous outside bars, same-kind points, state readiness, invalid range, preview partial-right predicate/winner, canonical ids, dependency closure, and ambient-context independence.

```python
@pytest.mark.parametrize(("precision", "rounding"), [(6, ROUND_DOWN), (50, ROUND_UP)])
def test_formula_is_independent_of_ambient_decimal_context(precision, rounding) -> None:
    getcontext().prec = precision
    getcontext().rounding = rounding
    assert compute_market_structure(context, bars, policy) == expected


def test_preview_drops_candidate_already_defeated_on_observed_right() -> None:
    assert compute_market_structure(context, bars, policy).preview is None


def test_fact_dependency_indices_cover_transitive_formula_inputs() -> None:
    fact = compute_market_structure(context, mixed_source_seam_bars, policy).facts[-1]
    assert fact.dependency_bar_indices == expected_dependency_indices
    assert "dependency_bar_indices" not in fact.canonical_id_payload()
```

- [ ] Run the focused test and observe import/behavior failures:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_structure_v1_formula.py
```

- [ ] Implement the complete pure API in one formula file. Keep it unexported from `indicators/__init__.py` and absent from `registry.py` in Stage A.

```python
FORMULA_VERSION = "symmetric_pivot_atr_filter_v1"
FORMULA_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    clamp=0,
)

@dataclass(frozen=True, slots=True)
class MarketStructurePolicy:
    policy_id: str
    span: int
    min_move_atr: Decimal
    atr_length: Literal[14] = 14


def compute_market_structure(
    context: MarketStructureSeriesContext,
    bars: Sequence[MarketStructureBar],
    policy: MarketStructurePolicy,
) -> MarketStructureResult: ...
```

- [ ] Build canonical ids from sorted compact JSON and stable logical/physical/segment identity. Exclude source, calculated time, and segment coverage end.

- [ ] For every fact, return deterministic ordered `dependency_bar_indices` as non-identity metadata. The transitive closure must cover every input bar used by strict left/right predicates, Wilder ATR seed/recursion, prior structure/active-leg state, and the confirmation window through `confirmed_at`. Quant-core exposes indices only—it never knows Canonical/Live source—and these indices are excluded from canonical fact serialization and id hashing.

- [ ] Add a prefix test that computes every prefix and asserts all earlier confirmed facts retain identical ids, values, and dependency-index closures.

- [ ] Run formula tests under at least two ambient Decimal contexts, then run existing indicator registry/kernel regressions to prove no registration or behavior change:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

- [ ] Commit the exact A0 formula and tests, then record the commit and LF-normalized formula digest. Do not edit the formula file after this commit without restarting Stage A.

```bash
git add packages/quant-core/guiyi_quant/indicators/market_structure_v1.py \
  services/quant-api/tests/test_market_structure_v1_formula.py
git commit -m "feat(indicators): add causal market structure evaluator"
git rev-parse HEAD
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
p = Path("packages/quant-core/guiyi_quant/indicators/market_structure_v1.py")
print(sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
PY
```

### Task 3: Implement mechanical calibration, holdout, and artifact generation

**Files:**

- Create: `services/quant-api/app/research/market_structure/calibration.py`
- Create: `services/quant-api/app/research/market_structure/calibration_runner.py`
- Create: `services/quant-api/app/research/market_structure/policy_artifacts.py`
- Create: `services/quant-api/tests/research/test_market_structure_calibration.py`
- User-authorized input: `data/research_fixtures/market_structure_v1/manifest.json`
- Generated after a passing corpus: `data/research_policies/<immutable-policy-id>.json`
- Generated after a passing corpus: `data/research_reports/market_structure_v1_calibration.json`

- [ ] Write failing tests for exact event matching, FP/FN, zero-support class handling, per-frequency macro F1, per-split range applicability, active-leg denominator, tie set selection, holdout isolation, confirmation-delay Gate, and reproducible report/policy digests.

```python
def test_holdout_never_reselects_the_calibration_winner() -> None:
    result = calibrate(corpus_with_holdout_favoring_another_candidate())
    assert result.selected_candidate_id == "s3-a0p5"
    assert result.status == "calibration_threshold_failed"


def test_prediction_only_class_has_zero_f1() -> None:
    assert class_f1(tp=0, fp=2, fn=0) == Decimal("0")
```

- [ ] Run and observe failures:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_calibration.py
```

- [ ] Implement the 20-candidate grid and exact selection algorithm. Import and call the Stage A formula module directly; no copied pivot implementation is permitted.

- [ ] Implement the runner as internal research tooling, not a `guiyi` command. It accepts only the fixed corpus/protocol paths and writes only the two fixed repository artifact paths after all Gates pass. It must refuse overwrite when the new digest differs from an existing immutable id.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api python -m \
  app.research.market_structure.calibration_runner
```

- [ ] If the authorized acceptance manifest is absent or insufficient, verify the runner exits non-zero and serializes the stable machine reason `calibration_evidence_insufficient`; set task conclusion to `阻塞` and do not create fake policy/report files.

- [ ] If evidence is present, run calibration twice and byte-compare the report/policy, then verify policy id contains the selected span/factor and corpus/formula digest prefixes.

- [ ] Run focused tests and commit code plus only genuine generated artifacts:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/research/test_market_structure_calibration.py
git add services/quant-api/app/research/market_structure \
  services/quant-api/tests/research/test_market_structure_calibration.py
git add data/research_fixtures/market_structure_v1/manifest.json \
  data/research_policies/market_structure_v1-*.json \
  data/research_reports/market_structure_v1_calibration.json
git commit -m "feat(research): calibrate market structure policy"
```

### Task 4: Close the Stage A review/approval Gate

**Files:**

- Create after independent review: `docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-a.md`
- Create after independent review: `data/research_policies/market_structure_v1_approvals.json`
- Update: `services/quant-api/tests/research/test_market_structure_calibration.py`

- [ ] Run fresh Stage A verification from the exact review head:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_calibration_contract.py \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/research/test_market_structure_calibration.py \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_registry_v1.py
uv run --project services/quant-api python -m ruff check \
  packages/quant-core/guiyi_quant/indicators/market_structure_v1.py \
  services/quant-api/app/research/market_structure \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/research/test_market_structure_*.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] Dispatch an independent read-only reviewer with base/head, the Spec, formula digest, corpus/split digest, calibration and holdout metrics. Fix every Critical/Important finding and rerun verification.

- [ ] After the preliminary review passes, record its exact evaluator/policy head and findings in the review document. Add an approval-manifest test that recomputes the immutable policy SHA-256, formula digest, corpus/split digest, and alias target.

- [ ] Create the approval manifest, run the focused and full Stage A checks again, then commit the tracked review/approval state:

```bash
git add docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-a.md \
  data/research_policies/market_structure_v1_approvals.json \
  services/quant-api/tests/research/test_market_structure_calibration.py
git commit -m "docs(research): approve market structure stage A"
```

- [ ] Dispatch the final read-only reviewer against that exact commit. Do not change any tracked file after a passing review. If the reviewer finds a Critical/Important issue, fix it in a new commit, rerun all Stage A verification, and repeat exact-head review; store the final review outcome in the PR review/timeline rather than making a post-review documentation commit.

- [ ] Open a PR to `develop`. Do not merge. Recommended conclusion is `允许集成 develop` only if the exact final head passes; otherwise `要求修正后再集成` or `阻塞`.

---

## Stage B — Approved kernel registration

### Task 5: Load the approved policy and register fail-closed capabilities

**Files:**

- Create: `services/quant-api/app/research/market_structure/policy.py`
- Update: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Update: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Update: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Update: `docs/INDICATOR_KERNEL.md`
- Create: `services/quant-api/tests/research/test_market_structure_policy.py`
- Update: `services/quant-api/tests/test_indicator_registry_v1.py`

- [ ] After Stage A is merged, create the Stage B worktree from current `origin/develop`; verify the formula digest equals the approved manifest before editing any file.

- [ ] Write failing tests for immutable alias resolution, policy/artifact digest mismatch, unapproved policy, consumer guard, registry metadata, seven intervals, completed-Live observation input, and blocked Runtime/backtest/strategy/Alert/notification/order consumers.

```python
def test_unapproved_policy_fails_closed() -> None:
    with pytest.raises(MarketStructurePolicyError) as exc:
        load_market_structure_policy("market_structure_v1", approvals=empty_approvals())
    assert exc.value.code == "MARKET_STRUCTURE_POLICY_UNAPPROVED"


def test_completed_live_observation_does_not_enable_runtime_live() -> None:
    capability = market_structure_capabilities("market_structure_research_observation")
    assert capability.completed_live_observation_input is True
    assert capability.runtime_live_consumer is False
```

- [ ] Implement policy/approval loading in the application layer. Pass a typed `MarketStructurePolicy` into the formula; never read files inside quant-core.

- [ ] Register `market_structure_v1` as `compatibility_validated`, marker/signal-state, seven-frequency, closed-completed-bar input, known unstable preview, `web_capable=false`, and every formal trading capability false.

- [ ] Export only the typed formula API required by reviewed consumers; keep calibration runner/application imports out of quant-core.

- [ ] Update `docs/INDICATOR_KERNEL.md` in the same Stage B PR with the approved formula/policy ids, immutable approval resolution, allowed research-observation consumer, blocked consumer matrix, and `web_capable=false`. Do not describe the Stage C service/CLI before they exist.

- [ ] Run focused policy/registry/formula tests and assert the formula file digest is unchanged:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/research/test_market_structure_policy.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

- [ ] Before committing, run the complete Stage B Gate. The policy test must recompute the formula digest from the checked-in bytes and compare it with the approval manifest:

```bash
uv run --project services/quant-api python -m ruff check \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/app/research/market_structure/policy.py \
  services/quant-api/tests/research/test_market_structure_policy.py \
  services/quant-api/tests/test_indicator_registry_v1.py
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add packages/quant-core/guiyi_quant/indicators \
  services/quant-api/app/research/market_structure/policy.py \
  services/quant-api/tests/research/test_market_structure_policy.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  docs/INDICATOR_KERNEL.md
git commit -m "feat(indicators): register approved market structure policy"
```

- [ ] Dispatch an independent read-only reviewer against the exact Stage B commit. If fixes are needed, commit them, rerun the full Stage B Gate, and repeat exact-head review. Open an unmerged Stage B PR only after the reviewer recommends `允许集成 develop`.

---

## Stage C — Internal read service, CLI, and evidence

### Task 6: Build the full-context, segment-safe research service

**Files:**

- Create: `services/quant-api/app/research/market_structure/models.py`
- Create: `services/quant-api/app/research/market_structure/service.py`
- Update: `services/quant-api/app/research/composition.py`
- Create: `services/quant-api/tests/research/test_market_structure_service.py`

- [ ] After Stage B is merged, create the Stage C worktree from current `origin/develop`.

- [ ] Write failing service tests for logical selector/full identity mapping, continuous `MAIN`, contract identity, actual-dominant true segments, roll reset, W1 segment restoration, full coverage-start calculation before crop, source/segment failures, and window-independent fact ids/dependency closures.

- [ ] Add completed-Live seam tests using existing `MarketReadService` semantics: continuous remains Canonical-only; contract requires exact contract/trading-day; actual-dominant requires exact current rank1 contract and unique current segment; incomplete or mismatched Live fails closed.

```python
def test_actual_dominant_live_contract_mismatch_is_unavailable() -> None:
    result = service.snapshot(selector, observation_at=cutoff)
    assert result.rows["15m"].status == "unavailable"
    assert result.rows["15m"].status_reason == "segment_unresolved"


def test_visible_window_does_not_change_confirmed_fact_ids() -> None:
    assert service.history(short_window).facts == service.history(long_window).facts[-len(expected):]


def test_dependency_sources_follow_engine_closure_across_live_seam() -> None:
    fact = service.history(canonical_plus_completed_live_request).facts[-1]
    assert fact.fact_dependency_sources == ("canonical", "live")
```

- [ ] Implement immutable request/result models and map `SeriesKind` to canonical `DatasetKey` fields. Keep `segment_coverage_end_trading_day` in response provenance, never fact identity.

- [ ] Compose `MarketDataService`, `ActualDominantResearchSegmentLoader`, and the existing `MarketReadService`/resolver seam. Do not read Parquet or Redis directly in the new service.

- [ ] Calculate each segment from authoritative start through `resolved_cutoff`, then crop output. For snapshot, capture one UTC observation instant and resolve seven independent row cutoffs.

- [ ] Map each engine `dependency_bar_indices` closure back to the full-context bars, then project distinct `fact_dependency_sources` in first-dependency order. Never infer dependencies from the cropped response and never reproduce formula rules in the service. Separate immutable fact fields from this point provenance, response source mix, resolver decision, `resolved_cutoff`, and `calculated_at`.

- [ ] Add source-provenance tests where a fact crosses the Canonical/completed-Live seam, where ATR recursion introduces the second source, and where a prior pivot/active-leg seed introduces the second source. Assert identical facts retain their ids while their provenance may upgrade after Live materializes as Canonical.

- [ ] Run focused service tests plus actual-dominant loader and Market read regressions, then commit:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_service.py \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py
git add services/quant-api/app/research/market_structure \
  services/quant-api/app/research/composition.py \
  services/quant-api/tests/research/test_market_structure_service.py
git commit -m "feat(research): add market structure read service"
```

If either referenced regression test path has been renamed on the then-current `develop`, locate the canonical test with `rg --files services/quant-api/tests | rg 'market_read|actual_dominant'` and record the exact replacement in the task evidence before running it.

### Task 7: Add the stdout-only internal research CLI

**Files:**

- Update: `services/quant-api/app/guiyi_cli/research_parser.py`
- Update: `services/quant-api/app/guiyi_cli/research_requests.py`
- Update: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Update: `services/quant-api/app/guiyi_cli/main.py`
- Update: `services/quant-api/tests/research/test_research_cli_parser_requests.py`
- Create: `services/quant-api/tests/research/test_market_structure_cli.py`

- [ ] Write failing parser tests for exact enum/date/RFC3339 input, contract requirements, no output-path flag, and stable error codes.

- [ ] Write failing payload tests for logical/physical identities, segments, confirmed facts, snapshot, preview, policy/corpus/formula digests, cutoff/provenance/status, Decimal strings, and deterministic JSON excluding only `calculated_at`.

- [ ] Add `market-structure` to `RESEARCH_COMMAND_NAMES`, request union, dispatch, and serializer. Keep it read-only and stdout-only.

- [ ] Run parser/CLI boundary tests and a mocked end-to-end command:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_market_structure_cli.py \
  services/quant-api/tests/test_research_cli_boundaries.py
```

- [ ] Commit:

```bash
git add services/quant-api/app/guiyi_cli \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_market_structure_cli.py
git commit -m "feat(cli): expose market structure research projection"
```

### Task 8: Produce Stage C seam and benchmark evidence

**Files:**

- Create: `services/quant-api/app/research/market_structure/benchmark.py`
- Create: `services/quant-api/tests/research/test_market_structure_benchmark.py`
- Create after real read-only run: `docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-c.md`
- Update after acceptance: `PROJECT_SOURCE.md`
- Update after acceptance: `docs/INDICATOR_KERNEL.md` (append Stage C service/CLI projection facts only)
- Update after acceptance: `TESTING.md`

- [ ] Write failing benchmark tests for three warm-ups, 30 serial measurements, nearest-rank p95, exact fixture/cutoff/input counts, environment metadata, and no cache/checkpoint writes.

- [ ] Implement a stdout-only benchmark module. It receives a fixed request fixture from code, reads existing local Canonical/metadata read-only, and emits JSON. It must not initialize RQData or mutate DB/Redis/files.

- [ ] Run the complete Stage C evidence matrix from the Spec. If local Canonical/metadata cannot support it, report `阻塞`; do not substitute mocks for Gate evidence.

- [ ] Verify common-prefix parity: Canonical and Canonical+completed-Live facts/state are identical through the Canonical cutoff; Live may add only a strict suffix; provenance is the only permitted difference on identical facts.

- [ ] Run the frozen benchmark and require `history p95 <= 500 ms` and seven-row `snapshot p95 <= 1500 ms`. A miss is `阻塞`; do not add cache/checkpoints in this plan.

- [ ] Record exact commands, machine facts, digests, request fixtures, outcomes, and known unavailable cases in the Stage C review document.

- [ ] Update stable canonical docs only after evidence passes. Add the new CLI as internal research; keep public overlays at four and state that Web projection remains gated.

- [ ] Run fresh Stage C verification, commit, and dispatch independent review:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_market_structure_*.py \
  services/quant-api/tests/test_market_structure_v1_formula.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/test_research_cli_boundaries.py
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/research/market_structure \
  services/quant-api/app/guiyi_cli \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/tests/research
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
git add services/quant-api/app/research/market_structure/benchmark.py \
  services/quant-api/tests/research/test_market_structure_benchmark.py \
  docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-c.md \
  PROJECT_SOURCE.md docs/INDICATOR_KERNEL.md TESTING.md
git commit -m "docs(research): record market structure stage C evidence"
```

- [ ] Open an unmerged Stage C PR to `develop`. Independent review must recommend `允许集成 develop`. After merge, stop and request the separate human decision for Stage D; absent that decision, final conclusion is `阻塞` for Web work.

---

## Stage D — Market context API and Web projection

Do not execute this section unless Stage C is merged and the user explicitly says `允许继续实现` for Stage D.

### Task 9: Add source-specific history/snapshot HTTP projections

**Files:**

- Create: `services/quant-api/app/schemas/market_structure.py`
- Create: `services/quant-api/app/api/market_structure.py`
- Update: `services/quant-api/app/main.py`
- Update: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Update: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Update: `data/research_policies/market_structure_v1_approvals.json`
- Create: `services/quant-api/tests/test_market_structure_api.py`
- Update: `services/quant-api/tests/test_indicator_registry_v1.py`

- [ ] Create the Stage D worktree from current `origin/develop` and record the explicit Stage D authorization in task evidence.

- [ ] Write failing API tests for request validation, selector versus single-frequency identity, trading-date inclusivity, one observation instant, limit `1..500`, opaque cursor ordering, seven partial statuses, 4xx versus typed insufficiency, Decimal-string wire values, and no formula work in schemas/router.

- [ ] Implement Pydantic DTOs and the two routes under `/api/v1/market/research/market-structure`. Router code only validates/maps and calls the reviewed service.

- [ ] Encode cursor from canonical JSON `(pivot_time, confirmed_at, id)` with URL-safe base64; reject malformed/non-canonical cursors and keep stable ordering.

- [ ] Enable only `web_capable`/Web API projection in the approved capability manifest. Keep Runtime live, backtest, strategy, Alert, notification, and order false. Verify the formula digest is unchanged.

- [ ] Run focused API, service, registry, and existing research-overlay regression tests, then commit:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_structure_api.py \
  services/quant-api/tests/research/test_market_structure_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git add services/quant-api/app/schemas/market_structure.py \
  services/quant-api/app/api/market_structure.py \
  services/quant-api/app/main.py \
  packages/quant-core/guiyi_quant/indicators/registry.py \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  data/research_policies/market_structure_v1_approvals.json \
  services/quant-api/tests/test_market_structure_api.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat(api): project market structure observations"
```

### Task 10: Add Web types, API normalization, preference v4, and request orchestration

**Files:**

- Update: `apps/quant-web/src/types/market.ts`
- Update: `apps/quant-web/src/api/market.ts`
- Create: `apps/quant-web/src/utils/marketStructure.ts`
- Create: `apps/quant-web/src/composables/useMarketStructure.ts`
- Update: `apps/quant-web/src/utils/mainIndicators.ts`
- Create: `apps/quant-web/tests/marketStructure.test.ts`
- Update: `apps/quant-web/tests/mainIndicators.test.ts`

- [ ] Write failing tests for wire DTOs, Decimal display conversion without altering fact ids, marker mapping, stable dedupe, seven-row order, stale-generation discard, identity reset, partial row errors, and no local formula calculation.

- [ ] Write failing v3→v4 preference tests: preserve overlay/EMA/period/follow values, default `marketStructureVisible=false`, migrate legacy keys once, and fail safely on corrupt/unknown data.

- [ ] Add readonly TypeScript DTOs. Preserve wire prices/range values as strings in the fact model; convert only in display helpers.

- [ ] Implement `useMarketStructure` with separate history and snapshot generations. Request identity is selector + row frequency + policy + observation instant; clear markers before starting a mismatched identity request.

- [ ] Bump `MAIN_CHART_PREFERENCES_KEY` and version to v4 without changing `ResearchOverlayId` or `RESEARCH_OVERLAY_DEFINITIONS`.

- [ ] Run focused tests and commit:

```bash
pnpm --dir apps/quant-web test \
  tests/marketStructure.test.ts \
  tests/mainIndicators.test.ts \
  tests/historicalResearchMarkers.test.ts \
  tests/marketOverlayConvergence.test.ts
git add apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/utils/marketStructure.ts \
  apps/quant-web/src/composables/useMarketStructure.ts \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/tests/marketStructure.test.ts \
  apps/quant-web/tests/mainIndicators.test.ts
git commit -m "feat(web): model market structure context"
```

### Task 11: Render the chart context layer and seven-frequency panel

**Files:**

- Create: `apps/quant-web/src/components/market/MarketStructurePanel.vue`
- Update: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Update: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Update: `apps/quant-web/src/components/kline/KlineChart.vue`
- Update: `apps/quant-web/src/pages/market/chart.vue`
- Update: `apps/quant-web/tests/productCheck.test.ts`
- Update: `apps/quant-web/tests/kline-view-model.test.ts`
- Update: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Create: `apps/quant-web/e2e/market-structure.spec.mjs`

- [ ] Write failing component tests for the independent toggle, seven fixed rows, ready/insufficient/unavailable states, range field reason, provenance/cutoff text, preview warning, and keyboard/ARIA labels.

- [ ] Write failing chart tests for confirmed marker ids, `pivot_time` placement, `confirmed_at` tooltip, preview marker separation, dashed candidate price line cleanup, pagination dedupe, and coexistence with SuBing/JDJ/HTDY markers.

- [ ] Implement `MarketStructurePanel.vue` as a presentation-only component. It receives normalized rows and emits no network/formula action.

- [ ] Add the toggle to `ProductWorkspaceToolbar.vue` without adding an overlay option. Wire it through v4 preferences in `chart.vue`.

- [ ] Extend `KlineChart.vue` with explicit structure-marker and preview-line props. Create/remove the Lightweight Charts price line on identity/visibility changes; never append it to confirmed marker arrays.

- [ ] Integrate the composable in `chart.vue`: K-line load stays independent, source requests clear on identity changes, history sync follows replace/prepend, and snapshot rows fail independently.

- [ ] Add a route-intercepted Playwright scenario that verifies product/frequency/series switches discard stale structure responses and do not change the selected strategy overlay.

- [ ] Run focused Web tests, e2e, and production build; then commit:

```bash
pnpm --dir apps/quant-web test \
  tests/marketStructure.test.ts \
  tests/productCheck.test.ts \
  tests/kline-view-model.test.ts \
  tests/marketOverlayConvergence.test.ts \
  tests/mainIndicators.test.ts
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs e2e/market-structure.spec.mjs
pnpm --dir apps/quant-web build
git add apps/quant-web/src/components/market/MarketStructurePanel.vue \
  apps/quant-web/src/components/market/ProductCheckSidebar.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/productCheck.test.ts \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/tests/marketOverlayConvergence.test.ts \
  apps/quant-web/e2e/market-structure.spec.mjs
git commit -m "feat(web): render market structure context layer"
```

### Task 12: Close Stage D verification, docs, review, and PR

**Files:**

- Update: `PROJECT_SOURCE.md`
- Update: `DECISIONS.md`
- Update: `docs/ARCHITECTURE.md`
- Update: `docs/INDICATOR_KERNEL.md`
- Update: `TESTING.md`
- Create: `docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-d.md`

- [ ] Update canonical docs to say Market Structure is a separate read-only context layer, public overlays remain four, preview is unstable, no Alert/Runtime/order capability exists, and current formula/policy ids are exact.

- [ ] Do not update `STATUS.md` unless a real release/Runtime/current-state change occurs in a separately authorized task.

- [ ] Run full fresh verification:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql" services/quant-api/tests
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests \
  packages/quant-core/guiyi_quant tests/engineering
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] Re-run the frozen Stage C benchmark against the exact Stage D head; both p95 targets must still pass.

- [ ] Dispatch a preliminary independent read-only reviewer with base/head, Spec, this plan, formula/policy/corpus digests, Stage C evidence, test/build output, and benchmark. Fix every Critical/Important issue and rerun affected plus full verification.

- [ ] Record the exact review result and residual known limitations. Commit docs only after facts match the final code:

```bash
git add PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md \
  docs/INDICATOR_KERNEL.md TESTING.md \
  docs/superpowers/reviews/2026-08-25-market-structure-v1-stage-d.md
git commit -m "docs: record market structure v1 capability"
```

- [ ] Re-run the full verification matrix against this exact commit, then dispatch the final read-only exact-head review. Do not change tracked files after it passes. If it finds a Critical/Important issue, fix and commit, rerun full verification, and repeat exact-head review; leave the final result in the PR review/timeline.

- [ ] Compare the final branch to its exact `develop` base and confirm no migration, DB/Redis/runtime/alert/order/release files changed unexpectedly.

- [ ] Open a PR to `develop`; do not merge. Final recommendation is `允许集成 develop` only when the exact head passes every Gate. Otherwise use `要求修正后再集成` or `阻塞`.

## Plan Completion Criteria

The implementation is complete only when all four stage PRs have passed their independent Gates and the Stage D PR is accepted into `develop` by a human. This plan never authorizes `main`, tag, release, Runtime promotion, real notification, Scope mutation, real data mutation, or order execution.
