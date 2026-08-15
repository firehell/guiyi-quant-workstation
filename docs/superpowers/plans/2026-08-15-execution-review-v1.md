# Execution Review V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1.4 Execution Review V1 loop from immutable SuBing AlertEvent through human decision, real manual execution records, bounded TradeEpisode lifecycle, structured review, reconstruction, and lightweight execution analytics without creating an account/risk/order system.

**Architecture:** Add a separate PostgreSQL Execution Review Application Domain with four tables and a single backend service authority. Keep Alert V2 immutable and independent; all historical market reads go through `MarketDataService`. Add one `/trade-records` Web surface and reuse the existing five-service Runtime topology. DOMINANT_ROLL background reconciliation is an independently gated, default-off follow-up to successful after-market runs, never part of `AfterMarketUpdater` itself.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, PostgreSQL/SQLite-test variants, Decimal, Vue 3, TypeScript, Naive UI, Vitest, Playwright, macOS launchd shell tooling.

**Design source:** `docs/superpowers/specs/2026-08-15-execution-review-v1-design.md` at/after commit `99497677264d4a240e69e3c937262a6898802590`.

## Global Constraints

- Current formal release baseline is `v1.3.1`; current production DB revision recorded by `STATUS.md` is `20260814_0038`.
- `AlertEvent` remains immutable; do not modify Alert V2 schema, event identity, Scope, WeCom sender, or Runtime dispatch.
- Only `subing_entry_signal_v1` with exactly one `buy|sell` result, non-null trading day/contract, and `5m|15m` frequency is eligible.
- `htdy_original_15m` stays observation-only and never enters Decision/Episode/statistics.
- Data Foundation is frozen: do not modify DatasetKey, Canonical semantics, eight-table Market Catalog, monthly partition rules, or Historical Gateway boundaries.
- All new historical reads use `MarketDataService`; Execution Review must not directly read Parquet, Redis, RQData, or MainContractMap.
- Live remains observation-only and is never persisted as Execution Review market truth.
- All price/cost/PnL arithmetic uses `Decimal`; PnL is explicitly `Estimated Gross PnL`, never account PnL.
- No Account / Position / Risk / Order / manual-trade domain, no reverse/lock workflow, no auto-order path; `auto_order=false` always.
- One symbol may have at most one OPEN Episode; Episode symbol/contract/direction are immutable lineage fields.
- Signal-driven OPEN/ADD must have `executed_at >= AlertEvent.bar_end`.
- DOMINANT_ROLL reference is fixed for implementation: use the **last confirmed Canonical `1m` bar of the old contract on the old rank1 segment's final trading day**. Do not let each caller choose a reference frequency.
- Background DOMINANT_ROLL follow-up is default-off and is enabled only by exact marker `.run/execution-review-roll-enabled` containing `enabled\n`, mode `0600`.
- Gate D marker activation must not reload or add a launchd service. The existing five-service topology remains API/Web/Live/after-market/Alert.
- Background roll reconciliation failure must not turn a successful Market after-market result into failure and must not trigger provider/Canonical retry.
- Defensive reconciliation during an explicit user `EXECUTED` action is part of that bounded interactive write and is not controlled by the background marker.
- Expected read unavailability (reconstruction or roll-reference unavailable) is fail-closed/read-state behavior, not fabricated data.
- Tasks 1-5 are repository development only: isolated DB/fixtures/temp files, no production migration, real RQData, Runtime switch, Scope mutation, WeCom send, main/tag, or roll-activation marker write.
- Task 6 is the only rollout task; release, production migration, Runtime promotion, and background roll activation are four independent human Gates.

---

## File Structure Locked by This Plan

### Backend domain

- Create: `services/quant-api/app/execution_review/__init__.py`
- Create: `services/quant-api/app/execution_review/contracts.py`
- Create: `services/quant-api/app/execution_review/models.py`
- Create: `services/quant-api/app/execution_review/pnl.py`
- Create: `services/quant-api/app/execution_review/service.py`
- Create: `services/quant-api/app/execution_review/reconciler.py`
- Create: `services/quant-api/app/schemas/execution_review.py`
- Create: `services/quant-api/app/api/execution_review.py`
- Modify: `services/quant-api/app/main.py`

### Market/read seam

- Modify: `services/quant-api/app/market_data/market_data_service.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`

### Data and migration

- Create: `data/reference/product_trade_multipliers.csv`
- Create: `services/quant-api/alembic/versions/20260815_0039_execution_review_v1.py`

If the Alembic head is no longer `20260814_0038` when Task 1 starts, stop and rebase/re-plan the migration identity; do not silently create a branch in the migration graph.

### Ops seam

- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`

### Backend tests

- Create: `services/quant-api/tests/test_execution_review_contracts.py`
- Create: `services/quant-api/tests/test_execution_review_models.py`
- Create: `services/quant-api/tests/test_execution_review_pnl.py`
- Create: `services/quant-api/tests/test_execution_review_service.py`
- Create: `services/quant-api/tests/test_execution_review_api.py`
- Create: `services/quant-api/tests/test_execution_review_reconstruction.py`
- Create: `services/quant-api/tests/test_execution_review_reconciler.py`
- Create: `services/quant-api/tests/alembic/test_execution_review_v1_migration.py`
- Create: `tests/engineering/test_execution_review_roll_activation.py`
- Modify as required for regression only: existing MarketDataService / after-market tests.

### Web

- Create: `apps/quant-web/src/types/executionReview.ts`
- Create: `apps/quant-web/src/api/executionReview.ts`
- Create: `apps/quant-web/src/pages/trade-records/index.vue`
- Create: `apps/quant-web/src/components/execution-review/DecisionForm.vue`
- Create: `apps/quant-web/src/components/execution-review/ExecutionForm.vue`
- Create: `apps/quant-web/src/components/execution-review/EpisodeDetail.vue`
- Create: `apps/quant-web/src/components/execution-review/TradeReviewForm.vue`
- Create: `apps/quant-web/src/components/execution-review/ReconstructionPanel.vue`
- Create: `apps/quant-web/src/components/execution-review/ExecutionStats.vue`
- Modify: `apps/quant-web/src/app/router.ts`
- Modify: `apps/quant-web/src/layouts/MainLayout.vue`
- Modify only the existing formal-signal surface needed for state/action links: `apps/quant-web/src/components/market/MarketAttentionList.vue` and/or its current parent composition.
- Create: `apps/quant-web/tests/executionReview.test.ts`
- Create: `apps/quant-web/e2e/execution-review.spec.mjs`

### Canonical/documentation closure

- Create: `docs/EXECUTION_REVIEW.md`
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `TESTING.md`
- Modify: `README.md`
- Modify: `services/quant-api/README.md`
- Modify: `apps/quant-web/README.md`
- Modify: `STATUS.md` only for actual code/develop facts; never claim production Gate execution from Tasks 1-5.

---

### Task 1: Domain Core, Decimal PnL, Multiplier Reference, and Additive Migration

**Lane:** Lane 3

**Files:** domain/data/migration/model tests listed above.

**Interfaces:**

- Produces scalar contract constants and validators used by Task 2.
- Produces ORM models `TradeDecision`, `TradeEpisode`, `TradeExecution`, `TradeReview`.
- Produces pure PnL API:

```python
@dataclass(frozen=True, slots=True)
class ExecutionFact:
    execution_type: str
    price: Decimal
    quantity: int

@dataclass(frozen=True, slots=True)
class PositionState:
    remaining_quantity: int
    average_cost: Decimal | None
    realized_points: Decimal
    realized_gross_pnl: Decimal | None


def calculate_position_state(
    *,
    direction: str,
    executions: Sequence[ExecutionFact],
    multiplier: Decimal | None,
) -> PositionState: ...


def calculate_roll_estimate(
    *,
    direction: str,
    position: PositionState,
    exit_price: Decimal,
    multiplier: Decimal | None,
) -> Decimal | None: ...
```

- Produces multiplier API:

```python
def load_product_trade_multipliers(path: Path) -> dict[str, Decimal]: ...
```

- [ ] **Step 1: Verify the migration head before writing tests**

Run read-only:

```bash
ls services/quant-api/alembic/versions | tail -20
grep -R 'revision = "20260814_0038"\|revision: str = "20260814_0038"' services/quant-api/alembic/versions
```

Expected: `20260814_0038` is the single current head. If a newer migration exists, stop Task 1 and update this plan before implementation.

- [ ] **Step 2: Write contract tests first**

Create `test_execution_review_contracts.py` with explicit cases for:

```python
def test_not_executed_requires_primary_reason(): ...
def test_other_reason_requires_note(): ...
def test_secondary_reasons_are_unique_and_exclude_primary(): ...
def test_executed_requires_at_least_one_reason(): ...
def test_unknown_reason_or_review_tag_is_rejected(): ...
def test_review_normal_tags_are_mutually_exclusive(): ...
```

Use exact V1 vocabularies from the design; do not invent runtime-extensible tag registries.

- [ ] **Step 3: Run contract tests to verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_contracts.py
```

Expected: import/module failures because the domain does not exist yet.

- [ ] **Step 4: Implement `contracts.py` minimally**

Use immutable frozensets/string constants plus validation functions. Required scalar values include:

```python
DECISION_DISPOSITIONS = frozenset({"EXECUTED", "NOT_EXECUTED"})
EPISODE_DIRECTIONS = frozenset({"LONG", "SHORT"})
EXECUTION_TYPES = frozenset({"OPEN", "ADD", "REDUCE", "CLOSE"})
CLOSE_REASONS = frozenset({"EXECUTION_NET_ZERO", "DOMINANT_ROLL"})
```

Keep the complete non-execution, execution-reason, stop-basis, and review-tag sets exactly aligned with the approved spec.

- [ ] **Step 5: Write PnL tests before implementation**

Create `test_execution_review_pnl.py` covering at least:

```python
def test_long_open_add_reduce_close_uses_weighted_average_cost():
    facts = [
        ExecutionFact("OPEN", Decimal("100"), 1),
        ExecutionFact("ADD", Decimal("110"), 1),
        ExecutionFact("REDUCE", Decimal("120"), 1),
        ExecutionFact("CLOSE", Decimal("130"), 1),
    ]
    state = calculate_position_state(
        direction="LONG", facts=facts, multiplier=Decimal("10")
    )
    assert state.remaining_quantity == 0
    assert state.realized_points == Decimal("40")
    assert state.realized_gross_pnl == Decimal("400")


def test_short_is_mirrored(): ...
def test_over_reduce_and_reverse_are_rejected(): ...
def test_missing_multiplier_keeps_points_but_amount_unavailable(): ...
def test_roll_estimate_only_values_remaining_quantity(): ...
```

- [ ] **Step 6: Implement `pnl.py` and make tests pass**

The implementation must iterate the timeline in order, update weighted average cost only on OPEN/ADD, realize points on REDUCE/CLOSE, and reject any topology that makes remaining quantity negative or leaves an OPEN/ADD after a zero position.

- [ ] **Step 7: Write ORM model tests before models**

Create `test_execution_review_models.py` using the existing isolated SQLite test pattern. Assert:

- one Decision per AlertEvent;
- one origin Decision per Episode;
- one Review per Episode;
- nullable `trigger_decision_id` allows many manual executions, but non-null trigger is unique;
- partial unique OPEN Episode index rejects two simultaneous OPEN Episodes for the same symbol;
- scalar checks reject illegal disposition/direction/execution type/close reason and non-positive quantity.

- [ ] **Step 8: Implement `models.py`**

Use SQLAlchemy 2 mapped models, timezone-aware `DateTime`, `Numeric(24, 8)` for prices/multipliers, `Integer` quantity, and `ARRAY(String(...)).with_variant(JSON(), "sqlite")` for tag arrays, matching the existing Alert model portability pattern.

Required tables:

```text
trade_decisions
trade_episodes
trade_executions
trade_reviews
```

Do not add market bars or mutable Signal snapshots.

- [ ] **Step 9: Write migration test before migration**

Create `test_execution_review_v1_migration.py` based on the existing alert migration test style. It must prove upgrade from `20260814_0038` creates only the four new application tables and leaves the exact eight Market Catalog tables plus `alert_rules/alert_events` intact.

- [ ] **Step 10: Implement additive migration `20260815_0039_execution_review_v1.py`**

Set:

```python
revision = "20260815_0039"
down_revision = "20260814_0038"
```

Create only the four approved tables, checks, FKs, unique constraints and the partial unique OPEN-Episode index. Do not alter Alert or Market tables.

- [ ] **Step 11: Add multiplier loader tests**

Test strict CSV parsing:

```text
product,multiplier
jm,60
```

Requirements: lowercase normalized product code, positive Decimal multiplier, no duplicates, malformed rows fail closed. Missing product is allowed at runtime and produces unavailable RMB PnL.

- [ ] **Step 12: Populate the multiplier reference from public official exchange specifications**

Create `data/reference/product_trade_multipliers.csv` with `product,multiplier` only. Use official exchange contract specifications for the current active 60; do **not** call real RQData as part of ordinary implementation. Add an engineering/unit assertion that every symbol in `data/universe/active_products.txt` appears exactly once. If an official multiplier cannot be verified for an active product, leave that symbol absent and make the coverage test explicitly list the unresolved symbol as a blocking finding rather than guessing a value.

- [ ] **Step 13: Run Task 1 verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_contracts.py \
  services/quant-api/tests/test_execution_review_models.py \
  services/quant-api/tests/test_execution_review_pnl.py \
  services/quant-api/tests/alembic/test_execution_review_v1_migration.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/execution_review \
  services/quant-api/tests/test_execution_review_contracts.py \
  services/quant-api/tests/test_execution_review_models.py \
  services/quant-api/tests/test_execution_review_pnl.py \
  services/quant-api/tests/alembic/test_execution_review_v1_migration.py

git diff --check
python3 scripts/engineering/secret_scan.py --json
```

Expected: all pass; no production Alembic command is run.

- [ ] **Step 14: Commit Task 1**

```bash
git add \
  services/quant-api/app/execution_review \
  services/quant-api/alembic/versions/20260815_0039_execution_review_v1.py \
  services/quant-api/tests/test_execution_review_contracts.py \
  services/quant-api/tests/test_execution_review_models.py \
  services/quant-api/tests/test_execution_review_pnl.py \
  services/quant-api/tests/alembic/test_execution_review_v1_migration.py \
  data/reference/product_trade_multipliers.csv
git commit -m "feat: add execution review domain core"
```

**Task acceptance:** isolated schema/core/pure PnL complete; no production migration or Runtime mutation. Require independent Lane 3 Review before integration to `develop`.

---

### Task 2: ExecutionReviewService, Business Mutations, Read Models, and HTTP API

**Lane:** Lane 3

**Files:** `service.py`, `schemas/execution_review.py`, `api/execution_review.py`, `main.py`, service/API tests.

**Interfaces:**

Create immutable command dataclasses in `service.py`:

```python
@dataclass(frozen=True, slots=True)
class NotExecutedCommand:
    primary_reason: str
    secondary_reasons: tuple[str, ...] = ()
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    note: str | None = None

@dataclass(frozen=True, slots=True)
class ExecutedCommand:
    executed_at: datetime
    price: Decimal
    quantity: int
    execution_reason_tags: tuple[str, ...]
    first_viewed_at: datetime | None = None
    planned_stop_price: Decimal | None = None
    stop_basis: str | None = None
    note: str | None = None
```

Primary service methods:

```python
class ExecutionReviewService:
    def record_not_executed(self, event_id: int, command: NotExecutedCommand) -> TradeDecision: ...
    def record_executed(self, event_id: int, command: ExecutedCommand) -> ExecutedResult: ...
    def append_execution(self, episode_id: int, command: ExecutionCommand) -> TradeExecution: ...
    def replace_execution_timeline(self, episode_id: int, commands: tuple[ExecutionCommand, ...]) -> TradeEpisode: ...
    def update_decision(self, decision_id: int, command: DecisionUpdateCommand) -> TradeDecision: ...
    def correct_disposition(self, decision_id: int, command: DispositionCorrectionCommand) -> TradeDecision: ...
    def submit_review(self, episode_id: int, command: ReviewCommand) -> TradeReview: ...
    def update_review(self, review_id: int, command: ReviewCommand) -> TradeReview: ...
```

- [ ] **Step 1: Write service eligibility and NOT_EXECUTED tests**

Create `test_execution_review_service.py` fixtures for isolated `AlertRule/AlertEvent`. Cover exact errors:

```text
EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE
EVENT_DIRECTION_INVALID
DECISION_ALREADY_EXISTS
UNKNOWN_DECISION_REASON
```

Prove HTDY and malformed/multi-result events are rejected without creating any Execution Review rows.

- [ ] **Step 2: Run service tests to verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_service.py
```

- [ ] **Step 3: Implement event loading/eligibility and `record_not_executed`**

Join `AlertEvent.rule` or query `AlertRule`; normalize only through existing product/contract helpers. Commit exactly one Decision transaction. Catch database infrastructure errors, rollback, and surface stable domain errors; never expose SQL/stack detail.

- [ ] **Step 4: Add first-execution tests**

Cover:

```python
def test_executed_creates_decision_episode_and_open_atomically(): ...
def test_open_time_before_event_bar_end_is_rejected(): ...
def test_direction_is_derived_from_event_and_not_client_selected(): ...
def test_second_open_episode_same_symbol_conflicts(): ...
```

The client request must not contain a direction field; direction comes from Event result code.

- [ ] **Step 5: Implement `record_executed` first-entry path**

If no OPEN Episode exists for the symbol, create `Decision(EXECUTED) + Episode + OPEN` in one transaction. Snapshot the verified multiplier if available; absence leaves multiplier fields null and does not block the record.

- [ ] **Step 6: Add same/opposite existing-Episode tests**

Prove:

```text
same symbol + same contract + same direction -> Decision + ADD
same symbol + opposite direction -> OPPOSITE_EPISODE_OPEN
same symbol + different contract while old Episode remains OPEN -> OPEN_EPISODE_CONFLICT until Task 3 defensive reconcile can resolve it
```

- [ ] **Step 7: Implement same-direction ADD transaction**

Lock the current OPEN Episode row, create the new Decision and one ADD with `trigger_decision_id` in the same transaction. Map duplicate triggers/unique races to stable 409-style domain conflicts.

- [ ] **Step 8: Add manual ADD/REDUCE/CLOSE tests**

Prove `POST execution` never accepts OPEN, REDUCE must be `< Q`, CLOSE must equal `Q`, and CLOSE sets:

```text
closed_at = executed_at
close_reason = EXECUTION_NET_ZERO
```

Manual ADD uses `trigger_decision_id = NULL`.

- [ ] **Step 9: Implement `append_execution` and topology validation by replaying pure PnL/position core**

Never update a stored mutable position balance. Derive current quantity/cost from Execution timeline each mutation.

- [ ] **Step 10: Add correction tests**

Cover simple price/time/note edits, atomic timeline replacement, invalid replacement rollback, and bounded disposition correction. Ensure immutable lineage fields cannot be updated through API/service commands.

- [ ] **Step 11: Implement correction methods**

Timeline replacement must validate the complete candidate sequence before replacing rows. `EXECUTED -> NOT_EXECUTED` may internally remove the trigger Execution only when the resulting Episode/review lineage remains valid; otherwise raise `DECISION_CORRECTION_CONFLICT`.

- [ ] **Step 12: Add structured Review tests and implement Review commands**

Require closed Episode and all five groups. Enforce `REASONABLE/NORMAL/NONE` mutual exclusions and unknown-tag rejection. Review creation makes read-model state DONE; editing stays allowed.

- [ ] **Step 13: Create Pydantic HTTP contracts**

In `schemas/execution_review.py`, define request/response DTOs with Decimal fields serialized as strings or FastAPI Decimal-compatible JSON consistently. Do not accept client-supplied Event direction, contract, symbol, multiplier, Episode close_reason, or lineage IDs.

- [ ] **Step 14: Write API tests before router**

Create `test_execution_review_api.py` covering all command/query paths plus exact envelope:

```json
{"detail": {"code": "OPPOSITE_EPISODE_OPEN"}}
```

Assert 404/422/409/503 mappings from the approved stable codes.

- [ ] **Step 15: Implement `/api/execution-review` router and register it in `app/main.py`**

Required routes:

```text
GET  /api/execution-review/items
GET  /api/execution-review/event-states
GET  /api/execution-review/episodes/{episode_id}
GET  /api/execution-review/stats
POST /api/execution-review/events/{event_id}/not-executed
POST /api/execution-review/events/{event_id}/executed
POST /api/execution-review/episodes/{episode_id}/executions
POST /api/execution-review/episodes/{episode_id}/review
PUT  /api/execution-review/decisions/{decision_id}
PUT  /api/execution-review/executions/{execution_id}
PUT  /api/execution-review/episodes/{episode_id}/execution-timeline
PUT  /api/execution-review/reviews/{review_id}
POST /api/execution-review/decisions/{decision_id}/correct-disposition
```

The reconstruction route is added in Task 3.

- [ ] **Step 16: Implement read-model classification and statistics exactly**

Definitions:

```text
pending_decision = eligible SuBing Event with no Decision
open             = Episode.closed_at is NULL
pending_review   = closed Episode without Review
done             = NOT_EXECUTED Decision OR closed Episode with Review

processed_events = count(Decision)
execution_rate   = EXECUTED / processed_events
```

Stats group by `AlertEvent.trading_day`, not natural `bar_end` date. Secondary non-execution reasons never enter the primary denominator.

- [ ] **Step 17: Run Task 2 verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/execution_review \
  services/quant-api/app/schemas/execution_review.py \
  services/quant-api/app/api/execution_review.py \
  services/quant-api/app/main.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/execution_review \
  services/quant-api/app/api/execution_review.py

git diff --check
```

- [ ] **Step 18: Commit Task 2**

```bash
git add services/quant-api/app/execution_review/service.py \
  services/quant-api/app/schemas/execution_review.py \
  services/quant-api/app/api/execution_review.py \
  services/quant-api/app/main.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py
git commit -m "feat: add execution review service and api"
```

**Task acceptance:** all interactive write semantics exist in isolated DB; no MarketDataService extension or background roll automation yet. Require independent Lane 3 Review before integration.

---

### Task 3: Historical Reconstruction, Deterministic DOMINANT_ROLL, Defensive Reconcile, and Default-off After-market Follow-up

**Lane:** Lane 3

**Files:** MarketDataService, `reconciler.py`, service/API reconstruction additions, CLI composition seam, ops marker/status scripts, tests.

**Interfaces:**

Add generic historical helpers to `MarketDataService`:

```python
def dominant_segment_for_day(
    self, symbol: str, trading_day: date
) -> DominantContractSegmentSummary: ...


def contract_bars_for_trading_day(
    self,
    *,
    symbol: str,
    contract: str,
    frequency: BarFrequency,
    trading_day: date,
) -> tuple[CanonicalBar, ...]: ...
```

Add reconciler:

```python
ROLL_REFERENCE_FREQUENCY = BarFrequency.M1

class ExecutionReviewRollReconciler:
    def reconcile_symbol(self, symbol: str) -> RollReconcileResult: ...
    def reconcile_open_episodes(self) -> tuple[RollReconcileResult, ...]: ...
```

Add reconstruction result:

```python
@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    status: str  # READY | UNAVAILABLE
    reason: str | None
    contract: str
    cutoff: datetime
    bars_5m: tuple[CanonicalBar, ...]
    bars_15m: tuple[CanonicalBar, ...]
```

- [ ] **Step 1: Write MarketDataService segment/day-bar tests first**

Extend `test_catalog_and_service.py` or add focused cases proving `dominant_segment_for_day` returns the rank1 segment containing a historical day, rejects missing/conflicting map facts, and never substitutes the latest segment. Test `contract_bars_for_trading_day` filters by `CanonicalBar.trading_day`, including night-session natural dates.

- [ ] **Step 2: Implement the two generic MarketDataService helpers**

Use existing Catalog/physical read internals inside `MarketDataService`; do not expose Catalog access to Execution Review. Preserve current error codes/fail-closed behavior.

- [ ] **Step 3: Write reconstruction tests**

Create `test_execution_review_reconstruction.py` covering:

```text
Event contract equals historical containing rank1 segment
signal mode returns only bar_end <= Event.bar_end
5m Event never reads future 15m
15m Event never reads future 5m
full mode stays inside the Event's rank1 segment
missing partition/map -> status UNAVAILABLE + stable public reason
UNAVAILABLE does not mutate Decision/Episode/Review
```

- [ ] **Step 4: Implement reconstruction in `ExecutionReviewService` and add GET route**

Add:

```text
GET /api/execution-review/events/{event_id}/reconstruction?mode=signal|full
```

Map expected MarketDataError classes to the approved `200 + {status:"unavailable", reason:...}` read state. Never rerun SuBing to decide whether the historical AlertEvent is still valid.

- [ ] **Step 5: Write deterministic roll-reference tests before reconciler**

Create `test_execution_review_reconciler.py`. Build an OPEN Episode whose origin Event belongs to old contract `JM2609`, then make formal latest rank1 become `JM2701`. Assert reference selection is exactly:

```text
old segment = dominant_segment_for_day(origin_event.symbol, origin_event.trading_day)
old segment.contract == episode.contract
reference bars = contract_bars_for_trading_day(... frequency=1m, trading_day=old_segment.end_trading_day)
reference = max(reference bars by bar_end)
```

No 5m/15m/current-live fallback is allowed.

- [ ] **Step 6: Implement `ExecutionReviewRollReconciler`**

Behavior:

```text
same current rank1 -> NOOP
changed current rank1 + unique old 1m reference -> close_reason=DOMINANT_ROLL and write reference fields
current identity/reference unavailable -> leave OPEN and return ROLL_RECONCILIATION_REQUIRED
```

Do not create a fake CLOSE Execution.

- [ ] **Step 7: Add real-CLOSE override tests and implementation**

When an Episode is DOMINANT_ROLL-closed, allow the bounded timeline correction path to add the user's actual final CLOSE. On valid net-zero replay set `close_reason=EXECUTION_NET_ZERO`, use actual close time, and clear roll reference fields.

- [ ] **Step 8: Add defensive reconcile before Event execution**

Before Task 2 `record_executed` decides same/opposite/cross-contract behavior, call `reconcile_symbol(event.symbol)` if an OPEN Episode exists. This interactive reconciliation is permitted even when the background marker is absent because it is part of the user's explicit write action. If reconciliation remains required, keep the conflict fail-closed.

- [ ] **Step 9: Write background activation-marker engineering tests**

Create `tests/engineering/test_execution_review_roll_activation.py`. Statical/temporary-script tests must prove:

```text
marker path = .run/execution-review-roll-enabled
marker exact contents = enabled\n
mode = 0600
--render-only never writes marker
--confirm-load/market/alert never writes marker
--confirm-execution-review-roll writes marker but does not add/reload any launchd label
```

Do not run the real confirmation mode in the repository checkout during tests.

- [ ] **Step 10: Implement exact default-off marker mode in `install-local-services.sh`**

Add accepted mode:

```text
--confirm-execution-review-roll
```

For this mode, write the marker atomically and exit **before** launchd load/reload logic. Do not create a sixth plist or label.

- [ ] **Step 11: Expose marker state in `local-services-status.sh` read-only output**

Add a public boolean/status field such as:

```text
execution_review_roll=enabled|disabled
```

Read only exact marker content; malformed content must report disabled/invalid, never auto-repair.

- [ ] **Step 12: Write CLI composition-seam tests**

Test `_run_data(... after-market ...)` with injected fake after-market result/reconciler/marker reader:

```text
Market result passed + marker disabled -> reconciler not called
Market result passed + marker enabled  -> reconciler called once
Market result skipped/failed           -> reconciler not called
reconciler raises                      -> returned Market after-market payload remains passed
```

No test may write the real marker.

- [ ] **Step 13: Implement after-market follow-up in `app/guiyi_cli/main.py`, not `AfterMarketUpdater`**

Keep `AfterMarketUpdater` unchanged. After its `.run()` returns `passed`, check marker and invoke the injected/built `ExecutionReviewRollReconciler`. Catch/log follow-up failure without changing the public Market result or invoking provider retry.

- [ ] **Step 14: Run Task 3 verification and regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_execution_review_reconstruction.py \
  services/quant-api/tests/test_execution_review_reconciler.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  tests/engineering/test_execution_review_roll_activation.py

bash -n scripts/ops/macos/install-local-services.sh
bash -n scripts/ops/macos/local-services-status.sh

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app/execution_review \
  services/quant-api/app/market_data/market_data_service.py \
  services/quant-api/app/guiyi_cli/main.py

git diff --check
```

- [ ] **Step 15: Commit Task 3**

```bash
git add \
  services/quant-api/app/execution_review/reconciler.py \
  services/quant-api/app/execution_review/service.py \
  services/quant-api/app/api/execution_review.py \
  services/quant-api/app/schemas/execution_review.py \
  services/quant-api/app/market_data/market_data_service.py \
  services/quant-api/app/guiyi_cli/main.py \
  scripts/ops/macos/install-local-services.sh \
  scripts/ops/macos/local-services-status.sh \
  services/quant-api/tests/test_execution_review_reconstruction.py \
  services/quant-api/tests/test_execution_review_reconciler.py \
  tests/engineering/test_execution_review_roll_activation.py
git commit -m "feat: add execution review reconstruction and roll handling"
```

**Task acceptance:** no lookahead/cross-roll path, deterministic old-contract 1m reference, default-off background mutation, unchanged Market after-market semantics. Require independent Lane 3 Review before integration.

---

### Task 4: `/trade-records` Web Execution Workflow and Market Integration

**Lane:** Lane 2

**Files:** Web files listed in File Structure.

**Interfaces consumed:** Task 2/3 HTTP contracts only. The Web must not derive eligibility, direction, current Episode conflict, close status, PnL, or roll state independently.

- [ ] **Step 1: Add TypeScript contract tests first**

Create `apps/quant-web/tests/executionReview.test.ts` around API adapter/format helpers. Lock state literals:

```ts
type ExecutionReviewState = 'pending_decision' | 'open' | 'pending_review' | 'done'
type Direction = 'LONG' | 'SHORT'
```

Prove stable backend `detail.code` is surfaced as a typed error without exposing arbitrary response bodies.

- [ ] **Step 2: Implement `types/executionReview.ts` and `api/executionReview.ts`**

Use existing `request.ts` transport. Export functions for items, event states, episode detail, stats, reconstruction, not-executed, executed, append execution, review submit/update, and corrections. Do not duplicate business validation beyond form affordances.

- [ ] **Step 3: Add route/navigation tests and implementation**

Modify router with:

```ts
{
  path: 'trade-records',
  name: 'trade-records',
  component: () => import('@/pages/trade-records/index.vue'),
  meta: { title: '交易记录', icon: 'review' },
}
```

Add `交易记录` under the existing `工作` menu in `MainLayout.vue`. Keep `/review`, Signal Center, Strategy routes absent.

- [ ] **Step 4: Build the task-state-first page skeleton**

`index.vue` must render exactly four state tabs with counts:

```text
待决策 / 进行中 / 待复盘 / 已完成
```

Default `pending_decision`. Pending/open/pending-review items must never disappear because of the historical time filter.

- [ ] **Step 5: Implement `DecisionForm.vue` with fast intraday behavior**

NOT_EXECUTED: one required primary reason, optional secondary reasons/note.

EXECUTED: direction locked from Event; require executed time, price, quantity, at least one execution-reason tag; stop plan optional. Do not add “准备执行”.

- [ ] **Step 6: Implement same/opposite existing Episode UX from backend state**

Same-direction execution response displays `ADD` context; no second-Episode choice. For `OPPOSITE_EPISODE_OPEN`, show a blocking message and no “close-and-reverse” action.

- [ ] **Step 7: Implement `ExecutionForm.vue` and `EpisodeDetail.vue`**

Only ADD/REDUCE/CLOSE. UI constrains REDUCE to `< current quantity` and fixes CLOSE quantity to remaining quantity, while backend remains authoritative. Clearly label position/PnL as manual-record-derived and estimated.

- [ ] **Step 8: Implement `TradeReviewForm.vue`**

Render the five approved structured groups and enforce mutually exclusive neutral tags in the form. No stars, score, confidence, or AI judgement.

- [ ] **Step 9: Implement `ReconstructionPanel.vue`**

Default to `mode=signal`; user must explicitly switch to `mode=full`. Show `post-hoc reconstruction` semantics and `UNAVAILABLE` state without disabling Review.

- [ ] **Step 10: Integrate Execution Review state into existing Market formal-signal cards**

Batch fetch Event states and map actions only:

```text
pending_decision -> 记录执行
open             -> 查看交易
pending_review   -> 去复盘
done             -> 查看记录
```

Alert data continues to come from Alert API; do not merge the backend domains.

- [ ] **Step 11: Write/extend unit tests for all state transitions**

Cover form required fields, stable error text mapping, same/opposite behavior, DOMINANT_ROLL warning, and reconstruction mode switch.

- [ ] **Step 12: Add Playwright E2E with mocked API**

Create `e2e/execution-review.spec.mjs` covering:

```text
pending -> NOT_EXECUTED -> done
pending -> executed/open -> close -> pending review -> review -> done
same-direction Event -> ADD
opposite-direction -> hard block
signal/full reconstruction toggle
```

Use test Vite/mock routes only; do not point Playwright at deployed Runtime.

- [ ] **Step 13: Run Task 4 verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/execution-review.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

- [ ] **Step 14: Commit Task 4**

```bash
git add apps/quant-web/src apps/quant-web/tests/executionReview.test.ts \
  apps/quant-web/e2e/execution-review.spec.mjs
git commit -m "feat(web): add execution review workspace"
```

**Task acceptance:** complete human workflow in Web against mocked/isolated API, no frontend business authority. Lane 2 Review before integration.

---

### Task 5: Lightweight Statistics, Deep Canonical, Full Regression, and Develop Closure

**Lane:** Lane 2, escalate to Sol Review if any business/statistical contract changes.

**Files:** `ExecutionStats.vue` plus documentation/canonical files listed above.

- [ ] **Step 1: Add statistics UI tests before component**

Lock exact denominators with fixture:

```text
eligible = 10
processed = 8
executed = 3
pending = 2
completion = 8/10
execution_rate = 3/8
```

Primary non-execution distribution uses only primary reasons. Review issue Top does not use secondary reasons or amount/PnL ranking.

- [ ] **Step 2: Implement `ExecutionStats.vue`**

Show only opportunity processing, execution rate, primary non-execution reasons, work-state counts, and Review issue Top. Do not add strategy win rate, PnL ranking, Sharpe, MFE/MAE or “filter alpha”.

- [ ] **Step 3: Create `docs/EXECUTION_REVIEW.md` as the long-term canonical**

Canonical must concisely freeze:

```text
eligible source = subing_entry_signal_v1 only
AlertEvent immutable
four application tables
one-symbol-one-open-Episode
no reverse/cross-contract merge
real Execution vs DOMINANT_ROLL estimate
1m roll reference policy
post-hoc reconstruction/no-future
Estimated Gross PnL only
background roll marker and independent Gate
auto_order=false
```

Do not copy the 1,500-line design spec into the canonical.

- [ ] **Step 4: Update project canonicals and developer docs to the actual develop code surface**

Update `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, and `TESTING.md`. Distinguish new Execution Review from the retired legacy Review Center. Keep Market Catalog exactly eight tables.

- [ ] **Step 5: Update README surfaces**

Update root/backend/Web README only for implemented code/API/Web facts. Do not claim release, migration, Runtime promotion, roll activation, or natural Canary.

- [ ] **Step 6: Update `STATUS.md` only with code-complete facts if all verification passes**

Allowed wording: Execution Review V1 code complete/test complete on `develop`, production Gates not executed. Preserve current v1.3.1 Runtime and Natural Canary facts until independently changed.

- [ ] **Step 7: Run full backend and engineering regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/app/api/execution_review.py
```

- [ ] **Step 8: Run full Web regression**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs \
  e2e/alert-v1.spec.mjs \
  e2e/execution-review.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 9: Run repository/security checks**

```bash
python3 scripts/engineering/secret_scan.py --json
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
git diff --check
git status --short
```

Expected: only intended task changes, no secrets, all tests pass.

- [ ] **Step 10: Commit Task 5 closure**

```bash
git add AGENTS.md PROJECT_SOURCE.md DECISIONS.md STATUS.md TESTING.md README.md \
  docs/ARCHITECTURE.md docs/DEVELOPMENT.md docs/EXECUTION_REVIEW.md \
  services/quant-api/README.md apps/quant-web/README.md \
  apps/quant-web/src/components/execution-review/ExecutionStats.vue \
  apps/quant-web/tests/executionReview.test.ts
git commit -m "docs: close execution review v1 implementation"
```

**Task acceptance:** code/develop closure only. Final conclusion after independent review may be `允许集成 develop`; it is not release or production approval.

---

### Task 6: v1.4.0 Release, Additive Production Migration, Runtime Promotion, and Optional Roll-auto Activation

**Lane:** Lane 3 rollout; new independent Sol session; Plan-only before each mutation Gate.

**Precondition:** Tasks 1-5 integrated to `develop`, full regression green, independent reviews passed, and `STATUS.md` still accurately describes production. SuBing Natural Canary may still be pending; do not fabricate it.

**External Gates are independent:**

```text
Gate A  main + annotated tag v1.4.0
Gate B  production DB upgrade 20260814_0038 -> 20260815_0039
Gate C  five-service Runtime promotion to exact v1.4.0 peeled commit
Gate D  write .run/execution-review-roll-enabled in the promoted Runtime root
```

- [ ] **Step 1: Prepare v1.4.0 release candidate on develop without external mutation**

Bump API/Web version identity to `1.4.0`, update version consistency tests and CHANGELOG with code facts only, run the complete Task 5 regression, and commit `release: prepare v1.4.0` on develop.

- [ ] **Step 2: Read-only release candidate identity**

```bash
git status --short
git rev-parse develop
git log -1 --oneline develop
git merge-base --is-ancestor main develop || true
```

Resolve any branch divergence using the repository's current release procedure; do not force-update history.

- [ ] **Step 3: STOP for Gate A — explicit release approval**

Required approval must identify repository, `v1.4.0`, and exact develop candidate. Only then merge/release to `main` and create/push annotated `v1.4.0`. This Gate does not authorize DB/Runtime/roll marker.

- [ ] **Step 4: Prepare clean detached Runtime worktree at exact `v1.4.0` without loading it**

Build backend/Web dependencies and render/lint launchd templates. Verify clean/detached and `git describe --exact-match=v1.4.0`.

- [ ] **Step 5: Read-only production DB preflight**

Verify current revision remains exactly `20260814_0038` and read back exact Market eight-table + Alert two-table counts/shape. If not exact, stop and re-plan; do not improvise a migration path.

- [ ] **Step 6: STOP for Gate B — production additive migration approval**

Only after approval run Alembic upgrade to `20260815_0039`. Read back four Execution Review tables/constraints and prove Market/Alert schema identities unchanged. Old v1.3.1 Runtime may continue because the migration is additive.

- [ ] **Step 7: Verify roll background marker is absent in the new Runtime root before promotion**

```bash
if [[ -e .run/execution-review-roll-enabled ]]; then
  printf 'unexpected roll marker present\n' >&2
  exit 1
fi
```

This proves Runtime promotion alone cannot activate automatic Episode DB mutation.

- [ ] **Step 8: STOP for Gate C — exact Runtime promotion approval**

Promote API/Web/Live/after-market/Alert to the clean/detached exact v1.4.0 Runtime using the existing five-service process. Read back loaded roots/commits, API version, Runtime health, operational 60, Alert scopes, and Execution Review API reachability.

- [ ] **Step 9: Smoke Execution Review read-only surface**

Read lists/stats/event states. If there is a natural eligible SuBing Event, it may appear as pending; do not create a synthetic Decision or Execution merely for smoke evidence.

- [ ] **Step 10: Leave Gate D disabled unless explicitly approved**

With marker absent, the 18:05 after-market command must not invoke background roll reconciliation. Interactive user actions still use defensive reconcile as designed.

- [ ] **Step 11: STOP for Gate D — background DOMINANT_ROLL activation approval**

Required approval must identify the local v1.4.0 Runtime and the bounded behavior: after successful 18:05 Market after-market, reconcile only already-OPEN Execution Review Episodes against formal rank1 and mutate only `trade_episodes` roll-close fields when the deterministic old-contract 1m reference is available.

- [ ] **Step 12: Activate marker without reloading services**

From exact Runtime root:

```bash
scripts/ops/macos/install-local-services.sh --confirm-execution-review-roll
```

Read back local status showing `execution_review_roll=enabled`, verify marker mode `0600` and exact content `enabled`, and verify five loaded launchd labels/root/commit did not change.

- [ ] **Step 13: Record rollout facts, without overstating natural evidence**

Update `STATUS.md`/CHANGELOG only with gates actually executed. If no natural SuBing Event or no real Episode reaches a roll boundary, keep those natural acceptance facts pending; never synthesize them.

**Task acceptance:** production identities and Gates read back exactly. Release approval is separate from Runtime promotion; Runtime promotion is separate from background roll activation. `auto_order=false` remains true.

---

## Plan Self-Review Checklist

- [x] Spec coverage: all approved sections map to Tasks 1-6.
- [x] No legacy Signal/Review/Strategy restoration.
- [x] No Account/Position/Risk/Order/manual-trade surface.
- [x] AlertEvent remains immutable and Alert Runtime independent.
- [x] Market Catalog remains exactly eight tables.
- [x] Decimal Estimated Gross PnL only.
- [x] Same-direction Event -> ADD; opposite direction -> conflict; no reverse.
- [x] Historical reconstruction is MarketDataService-only and no-future.
- [x] DOMINANT_ROLL reference frequency is deterministic `1m` rather than implementation-defined.
- [x] Background roll mutation has an exact default-off marker and independent Gate D.
- [x] Background reconcile cannot contaminate Market after-market result/retry.
- [x] Natural SuBing Canary remains honest independent evidence.
- [x] No `TBD`, `TODO`, or implementation placeholders.

## Recommended Task Order

```text
Task 1 Domain Core + migration contract
→ independent Lane 3 Review
→ integrate develop

Task 2 Service + API
→ independent Lane 3 Review
→ integrate develop

Task 3 Reconstruction + roll boundary
→ independent Lane 3 Review
→ integrate develop

Task 4 Web workflow
→ Lane 2 Review
→ integrate develop

Task 5 stats + canonical/full regression
→ final code Review
→ release candidate

Task 6 independent rollout session
→ Gate A release
→ Gate B migration
→ Gate C Runtime
→ optional Gate D roll-auto activation
```

Do not parallelize Tasks 1-3 because their contracts are sequential. Task 4 may start after Task 2's API contract is integrated, but it should consume Task 3 reconstruction endpoint before final acceptance. Task 5 starts only after Tasks 1-4 are integrated.