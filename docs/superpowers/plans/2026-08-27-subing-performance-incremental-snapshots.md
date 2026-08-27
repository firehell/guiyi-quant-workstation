# SuBing Performance Incremental Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with review checkpoints.

**Goal:** Replace SuBing Performance full-window request-time replay with atomic schema-v3 snapshots, direct read-only API serving, and after-market physical-segment-tail refresh while preserving the current strategy, data-lineage, and authorization semantics.

**Architecture:** Keep the existing Historical projection as the only strategy replay implementation and as the one-time full bootstrap path. Add a deep snapshot module that owns immutable artifact encoding, strict legacy-v2 adoption, hash/path validation, and atomic current-manifest publication. Add a lineage resolver and incremental refresher that compare ordered rank1 physical segments, replay only the earliest affected tail, merge immutable-prefix facts, and fail closed on broad drift. The API uses a separate read-only snapshot query and never constructs or calls Historical replay.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Ruff, Mypy, SHA-256 JSON envelopes, POSIX `fsync` + `os.replace`.

**Spec:** `docs/superpowers/specs/2026-08-27-subing-performance-incremental-snapshots-design.md`

## Global constraints

- Work only in `.worktrees/subing-performance-incremental-snapshots` on `feature/subing-performance-incremental-snapshots`.
- Preserve the user's untracked `.pnpm-store/` and every unrelated dirty change in the primary worktree.
- Do not signal, stop, restart, inspect private state of, or compete with the active full warm.
- Do not read, write, list, rename, migrate, adopt, or delete the real Git-external performance cache during repository implementation.
- All tests use `tmp_path` and fake Catalog/Historical seams. They must not source production configuration or connect to RQData, production PostgreSQL, Redis, Runtime, Scope, or notification transports.
- Do not change SuBing formula, Factor, Lifecycle, Action, Episode, fill timing, exit semantics, causality, or physical-contract isolation.
- Do not add a DB table, migration, scheduler, worker, queue, generic backtest platform, automatic full fallback, or frontend compatibility layer.
- A missing/corrupt/stale current snapshot or immutable-prefix drift fails closed. It is never repaired by the HTTP path.
- Real schema-v2 adoption, active60 refresh, Runtime promotion, main merge, release, tag, notification, and production writes remain separate explicit Gates.

## Task 0: Enforce the running-warm safety gate

**Files:**

- Read: process table only
- Read: `.git`, worktree metadata
- Modify: none

- [ ] Confirm the exact active warm before any code or test execution:

```bash
pgrep -afil 'guiyi research subing-strategy-performance --scope active --warm-cache'
```

Expected while the current job is active: one process whose command matches the approved full warm.

- [ ] If the command returns any matching process, stop this implementation session with `BLOCKED_BY_ACTIVE_FULL_WARM`. Do not run pytest, Ruff, Mypy, builds, cache inspection, or resource-intensive verification. Do not send a signal.

- [ ] After the process exits naturally, verify isolation and base state:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base HEAD origin/develop
git worktree list --porcelain
```

Expected: the feature worktree contains only planned task changes, the primary worktree is untouched, and the feature branch descends from `origin/develop@f896730554d57149b27b675e5346b59563a951b9`.

- [ ] Run the narrow pre-change baseline only after the warm has exited:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS. A baseline failure stops implementation for diagnosis; it is not patched around.

## Task 1: Define the schema-v3 snapshot domain and strict codec

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/performance_snapshot.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py`
- Read: `services/quant-api/app/market_data/subing_strategy/performance.py`
- Read: `services/quant-api/app/market_data/subing_strategy/service.py`

- [ ] Write failing codec tests for:

  - exact schema versions and fixed public error codes;
  - round-trip of full display payload, Episodes, prefix counts, ordered tail facts, cutoff, identities, and aware UTC generation time;
  - duplicate JSON keys, unknown fields, absolute paths, `..`, wrong product/frequency/strategy, future/stale dates, malformed values, and all hash mismatches;
  - deterministic hashes independent of dictionary insertion order;
  - no absolute paths, credentials, provider references, DB IDs, account/order facts, or machine-state serialization in the encoded artifact.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py
```

Expected RED: module or domain types do not exist.

- [ ] Implement immutable domain objects with validated constructors:

```python
@dataclass(frozen=True)
class SubingStrategyPerformanceSegmentFact:
    contract: str
    effective_start: date
    effective_end: date
    loaded_through: date
    bar_count_1m: int
    bar_count_5m: int
    bar_count_15m: int
    context_unavailable_count: int
    source_identity: str


@dataclass(frozen=True)
class SubingStrategyPerformanceSnapshot:
    symbol: str
    coverage_since: date
    coverage_through: date
    resolved_cutoff: datetime
    projection: SubingStrategyPerformanceProjection
    immutable_prefix_segment_count: int
    immutable_prefix_counts: SubingStrategyPerformancePrefixCounts
    segment_facts: tuple[SubingStrategyPerformanceSegmentFact, ...]
    source_manifest_sha256: str
    identity_sha256: str
    payload_sha256: str
    snapshot_sha256: str
    generated_at: datetime
```

- [ ] Keep serialization and parsing in this module. Use canonical JSON (`sort_keys=True`, compact separators, UTF-8), reject duplicate keys through `object_pairs_hook`, and derive hashes from explicitly separated identity, payload, and envelope objects.

- [ ] Convert between the existing `SubingStrategyPerformanceProjection` and snapshot payload without changing the public response DTO.

- [ ] Run the test and make it GREEN. Then run:

```bash
uv run --project services/quant-api --no-sync python -m ruff check \
  services/quant-api/app/market_data/subing_strategy/performance_snapshot.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py
```

Expected: PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance_snapshot.py services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py
git commit -m "feat: define SuBing performance snapshots"
```

## Task 2: Build the atomic filesystem snapshot store

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/performance_snapshot_store.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py`
- Read: `services/quant-api/app/market_data/subing_strategy/cache.py`

- [ ] Add failing tests using only `tmp_path` for:

  - immutable path `snapshots/<symbol>/<through>/<snapshot_sha256>.json`;
  - manifest path `current/<symbol>.json`;
  - snapshot publication before manifest replacement;
  - tempfile cleanup and preservation of the prior manifest after write, readback, hash, `fsync`, or replace failure;
  - successful publication followed by read through the same parser;
  - no write from `read_current`;
  - owner-controlled regular files/directories, `0700` directories, `0600` files, symlink rejection, root-containment enforcement, and no glob/mtime selection;
  - exact `expected_through`, symbol, relative path, and manifest-hash checks.

Expected RED: store is absent.

- [ ] Implement only this public store seam:

```python
class SubingStrategyPerformanceSnapshotStore(Protocol):
    def read_current(
        self, *, symbol: str, expected_through: date
    ) -> SubingStrategyPerformanceSnapshot: ...

    def publish_current(
        self, snapshot: SubingStrategyPerformanceSnapshot
    ) -> SubingStrategyPerformanceSnapshotReceipt: ...
```

- [ ] Implement `SubingStrategyPerformanceFileSnapshotStore` with normalized root validation, exclusive temporary files, file `fsync`, directory `fsync`, `os.replace`, immutable collision equality checks, and readback before manifest switch.

- [ ] Ensure exceptions expose only fixed public categories and never absolute paths, hashes, JSON contents, or stack traces.

- [ ] Run the snapshot test file and Ruff; expected PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance_snapshot_store.py services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py
git commit -m "feat: publish atomic SuBing performance snapshots"
```

## Task 3: Resolve lightweight lineage and select a safe mutable tail

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/performance_lineage.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_performance_lineage.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Read: `services/quant-api/app/market_data/market_data_service.py`
- Read: `services/quant-api/app/market_data/actual_dominant_research.py`
- Read: `services/quant-api/app/market_data/coverage_source.py`
- Read: Catalog and `MainContractMap` models already consumed by those modules

- [ ] Write failing tests for an explicit metadata-only resolver that returns:

```python
@dataclass(frozen=True)
class SubingStrategyPerformanceLineage:
    symbol: str
    coverage_since: date
    coverage_through: date
    ordered_segments: tuple[SubingStrategyPerformanceSourceSegment, ...]
    source_manifest_sha256: str
```

The tests must prove it uses Catalog coverage and rank1 `MainContractMap`, not Canonical Bar reads, file globs, active-file guesses, or consumer-side dominant logic.

- [ ] Add comparison cases for normal append, unchanged same-day, rollover, immutable-prefix mapping drift, immutable-prefix Canonical lineage drift, coverage regression, reordered/overlapping/gapped segments, and strategy/engine identity drift.

- [ ] Implement a small resolver protocol plus the SQLAlchemy/Catalog adapter in composition. If the existing `MarketDataService` exposes only a private segment helper, promote one validated metadata method rather than calling a private method or copying resolver logic.

- [ ] Implement a pure tail-decision function that returns one of:

  - `UNCHANGED`;
  - `REPLAY_FROM_SEGMENT(index)`;
  - `FULL_REBUILD_REQUIRED`.

Only the current mutable segment, or the previous mutable segment at rollover, may be replayed. Any earlier drift is `FULL_REBUILD_REQUIRED`.

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_lineage.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

Expected: PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance_lineage.py services/quant-api/app/market_data/composition.py services/quant-api/tests/data_foundation/test_subing_strategy_performance_lineage.py services/quant-api/tests/data_foundation/test_composition.py
git commit -m "feat: resolve SuBing performance lineage"
```

## Task 4: Strictly adopt the exact schema-v2 warm artifact

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/performance_adoption.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py`
- Read: `services/quant-api/app/market_data/subing_strategy/cache.py`
- Read: `services/quant-api/app/market_data/subing_strategy/performance.py`

- [ ] Write failing tests that construct schema-v2 artifacts under `tmp_path` and verify:

  - exactly one regular candidate for exact symbol/through/identity is required;
  - temporary files, multiple candidates, symlinks, wrong hashes, wrong identities, bad payloads, missing segments, or segment-order mismatch fail with `SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED`;
  - the source schema-v2 artifact is byte-identical after adoption;
  - only the last mutable segment is replayed to obtain tail facts;
  - prefix counts plus tail counts equal the legacy full totals;
  - adoption publishes schema v3 only after all checks pass;
  - the HTTP query never calls the adopter.

- [ ] Implement an explicit write-capable adopter. It may inspect only the exact legacy directory derived from validated identity; it must not recursively scan, choose by mtime, or move/rewrite the legacy file.

- [ ] Reuse the existing schema-v2 parser/hash rules from `SubingStrategyPerformanceCache`. Refactor those rules into shared pure codec helpers if needed; do not maintain two subtly different parsers.

- [ ] Pass a Historical-tail replay dependency into the adopter. Do not construct production dependencies inside it.

- [ ] Run the snapshot/adoption tests and Ruff; expected PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/cache.py services/quant-api/app/market_data/subing_strategy/performance_adoption.py services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py
git commit -m "feat: adopt legacy SuBing performance snapshots"
```

## Task 5: Implement incremental tail refresh and full-replay parity

**Files:**

- Create: `services/quant-api/app/market_data/subing_strategy/performance_incremental.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_strategy_performance_incremental.py`
- Modify: `services/quant-api/app/market_data/subing_strategy/performance.py`
- Read: `services/quant-api/app/market_data/subing_strategy/service.py`
- Read: `services/quant-api/app/market_data/subing_strategy/machine.py`

- [ ] First extract a pure `summarize_performance(projection)` helper from the current full service, covered by existing tests. No behavior changes are allowed.

- [ ] Write failing incremental tests with deterministic multi-segment fixtures:

  - same-day/no-change returns the current snapshot with zero Historical calls and zero writes;
  - a new day calls Historical exactly once from the prior mutable segment start to the new through date;
  - only Episodes from the affected tail are replaced;
  - merged Actions, Episodes, stats, total Bar counts, unavailable counts, cutoff, and source identities equal an independent full replay;
  - duplicate, out-of-order, cross-contract, or mismatched Episodes fail closed;
  - rollover replays old tail plus new segment, ends the old segment flat, cancels pending cross-segment actions, and starts the new segment from isolated flat state;
  - after successful rollover, the closed old tail is compacted into the immutable prefix;
  - source drift before the seam, engine drift, coverage regression, incomplete tail, or corrupt current snapshot preserves the previous manifest and raises `FULL_REBUILD_REQUIRED`;
  - a publication failure preserves the previous current snapshot.

Expected RED: refresher is absent.

- [ ] Implement:

```python
class SubingStrategyPerformanceIncrementalRefresher:
    def refresh(
        self, *, symbol: str, through: date
    ) -> SubingStrategyPerformanceProjection: ...
```

- [ ] Inject four dependencies only: lineage resolver, Historical tail replay, snapshot store, and optional explicit adopter. Keep tail planning and merge validation pure.

- [ ] Call the existing Historical projection with the exact affected physical-segment window and `publish_cache=True`; do not copy the strategy machine or formulas.

- [ ] Publish only after parity invariants and full merged summary recomputation succeed. Never catch `FULL_REBUILD_REQUIRED` and retry with a full window.

- [ ] Run focused tests:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_incremental.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py
```

Expected: PASS, including causality/strict-before/prefix-invariance/golden cases selected by these modules.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance.py services/quant-api/app/market_data/subing_strategy/performance_incremental.py services/quant-api/tests/data_foundation/test_subing_strategy_performance.py services/quant-api/tests/data_foundation/test_subing_strategy_performance_incremental.py
git commit -m "feat: refresh SuBing performance incrementally"
```

## Task 6: Cut the API over to direct snapshot reads

**Files:**

- Modify: `services/quant-api/app/market_data/subing_strategy/performance_snapshot.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`

- [ ] Write failing API tests that install the real filesystem store over `tmp_path` and prove:

  - a valid current snapshot returns the existing wire response exactly;
  - the request performs no Historical construction/call, no Canonical Bar read, no adoption, no repair, and creates no files;
  - stale, missing, future, corrupt, hash-mismatched, or symlinked snapshots return the existing `409` with a fixed public code;
  - invalid/non-active products retain current validation behavior;
  - errors expose no path, hash, SQL, JSON body, or stack trace.

- [ ] Introduce the read-only query:

```python
class SubingStrategyPerformanceSnapshotQuery:
    def current(self, symbol: str) -> SubingStrategyPerformanceProjection:
        expected_through = self._lineage.expected_complete_through(symbol)
        return self._store.read_current(
            symbol=symbol,
            expected_through=expected_through,
        ).projection
```

- [ ] Add `build_subing_strategy_performance_snapshot_query(session)` in composition. It must not call `build_subing_strategy_historical_service`.

- [ ] Change only the route dependency. Keep Pydantic response schemas and frontend contracts unchanged.

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

Expected: PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance_snapshot.py services/quant-api/app/market_data/composition.py services/quant-api/app/api/market_research_overlays.py services/quant-api/tests/test_market_research_overlays_api.py services/quant-api/tests/data_foundation/test_composition.py
git commit -m "feat: serve SuBing performance snapshots directly"
```

## Task 7: Replace after-market full warm with exact-product incremental refresh

**Files:**

- Modify: `services/quant-api/app/market_data/subing_strategy/performance_incremental.py`
- Modify: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_after_market.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_strategy_performance.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py` only if needed to keep the explicit full-bootstrap command separate

- [ ] Write failing batch tests that preserve exact active60 accounting and deterministic serial order while replacing each product's full warm with `incremental_refresher.refresh(symbol, through)`.

- [ ] Cover full success, cache hits, publications, one-product failure, `FULL_REBUILD_REQUIRED`, exact-product mismatch, stable batch identity, and no retry/notification/Scope/Runtime behavior.

- [ ] Keep the current CLI `--warm-cache` command as the explicit all-history bootstrap path. Do not route normal after-market maintenance through it.

- [ ] Modify `build_after_market_updater()` to construct the incremental batch refresher. Preserve canonical success and derived-only degraded semantics.

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance.py \
  services/quant-api/tests/test_runtime_health.py
```

Expected: PASS.

- [ ] Commit:

```bash
git add services/quant-api/app/market_data/subing_strategy/performance_incremental.py services/quant-api/app/market_data/after_market.py services/quant-api/app/market_data/composition.py services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/data_foundation/test_after_market.py services/quant-api/tests/data_foundation/test_subing_strategy_performance.py services/quant-api/tests/test_runtime_health.py
git commit -m "feat: append SuBing snapshots after market"
```

## Task 8: Converge documentation and verify the exact head

**Files:**

- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `STATUS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`

- [ ] Update only canonical ownership:

  - `PROJECT_SOURCE.md`: stable direct-snapshot product behavior;
  - `DECISIONS.md`: immutable snapshot/current-manifest and segment-tail decision;
  - `docs/ARCHITECTURE.md`: API query versus after-market refresh dependency arrows;
  - `TESTING.md`: exact deterministic repository-test command;
  - `STATUS.md`: `CODE_COMPLETE`/`TEST_COMPLETE` facts only after evidence, with real adoption and Runtime Gates still pending.

- [ ] Run the focused regression set:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/research/test_subing_strategy_direction_context.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_cache.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_snapshot.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_lineage.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_performance_incremental.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Expected: PASS.

- [ ] Run static checks:

```bash
uv run --project services/quant-api --no-sync python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
uv run --project services/quant-api --no-sync mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
```

Expected: PASS.

- [ ] Run repository gates:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  tests/engineering/test_canonical_consistency.py
uv run --with openspec openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: PASS with no secrets and no whitespace errors.

- [ ] Review exact-head behavior against the approved Spec. Use the repository `code-review` workflow locally unless the user explicitly authorizes parallel agents. Findings must cover strategy semantics, lineage, snapshot atomicity, request-time writes, external Gates, and test quality.

- [ ] Fix findings with new RED/GREEN evidence, rerun affected checks, then commit documentation and fixes:

```bash
git add PROJECT_SOURCE.md DECISIONS.md STATUS.md docs/ARCHITECTURE.md TESTING.md services/quant-api
git commit -m "docs: record incremental SuBing snapshots"
```

- [ ] Confirm exact final state:

```bash
git status --short --branch
git log --oneline --decorate -12
git diff origin/develop...HEAD --stat
git diff --check origin/develop...HEAD
```

Expected: clean feature worktree and reviewable task-only diff.

## Task 9: Integrate only to `develop`

**Files:** none beyond verified feature commits.

- [ ] Push the feature branch and create/review a PR targeting `develop` under the normal repository workflow.

- [ ] Verify CI and exact reviewed head. If CI differs or fails, stop and diagnose; do not bypass it.

- [ ] Merge to `develop`, push `develop`, verify remote ancestry, and remove only the clean disposable feature worktree/branch.

- [ ] Do not merge `main`, tag, release, promote Runtime, execute real adoption, or run an active60 refresh.

Expected final classification: `CODE_COMPLETE_EXTERNAL_GATE_PENDING` until a separately approved release, real-root schema-v2 adoption, and Runtime selection occur.

## Acceptance checklist

- [ ] API reads a validated current snapshot with zero Historical calls and zero writes.
- [ ] Normal after-market maintenance replays only the affected physical-contract tail.
- [ ] Tail merge and rollover fixtures are field-equivalent to independent full replay.
- [ ] Immutable-prefix drift fails with `SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED` and preserves the previous manifest.
- [ ] The in-progress full warm and its schema-v2 artifacts were never interrupted or mutated.
- [ ] No RQData, production DB/Redis, Canonical, Scope, notification, Runtime, release, main, or tag Gate was crossed.
- [ ] Targeted tests, Ruff, Mypy, canonical consistency, OpenSpec, secret scan, diff check, and exact-head review all pass.
