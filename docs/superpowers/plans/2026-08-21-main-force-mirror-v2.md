# Main Force Mirror V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the historical-only Main Force Mirror V2 from immutable exact-contract RQData member-rank snapshots, one Python formula authority, a read-only Market API, and a two-tab MACD/V2 Web pane while retiring all active V0/V1 implementations.

**Architecture:** `MarketDataService` remains the only Canonical bar reader. A separate `MemberRankSnapshotRepository` reads one pinned immutable Parquet snapshot; `MainForceMirrorV2Service` aligns T-day 60m physical-contract bars with T-1 member data and invokes the Python Kernel. The Web requests paged V2 results and only projects server fields into Lightweight Charts.

**Tech Stack:** Python 3.13, NumPy, PyArrow/Parquet, FastAPI/Pydantic, existing `guiyi` CLI, Vue 3, TypeScript 6, Lightweight Charts 5, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-21-main-force-mirror-v2-design.md`

## Global Constraints

- Read `AGENTS.md`, `STATUS.md`, `docs/INDICATOR_KERNEL.md`, `docs/DATA_CENTER.md`, and the approved spec before editing.
- Start on `develop`; preserve unrelated dirty/index state and stage only task-owned files.
- Use RED→GREEN for every executable behavior; run the named failing test before implementation.
- Exact identities are `main_force_mirror_v2`, `futures-member-research-v2`, `main_force_mirror_observation_v2`, `main_force_mirror_v2_retrospective_v1`, and `main_force_member_rank_v1`.
- Support only `60m + actual_dominant|contract + confirmed Canonical Historical`; reject `continuous` and all other frequencies.
- Python is the only V2 formula authority. TypeScript may normalize DTOs, label states, and map points to chart series, but must contain no ATR/OI/pressure/member formula.
- T-day bars use only `physical_contract(T) × previous_trading_day(T)` member rows. Never use a product aggregate, same-day hindsight, stale carry-forward, zero fill, or old-contract fallback.
- The member snapshot is outside Canonical and the eight-table Catalog. Do not add an Alembic migration or PostgreSQL member-rank table.
- Keep “小心” score, conflict, latch, re-arm, and block-reset semantics point-for-point equal during migration. Member state never creates, suppresses, delays, or repeats a caution.
- V0/V1 active implementations are deleted only after V2 replacement tests pass. Keep historical `CHANGELOG.md` entries.
- No real RQData call, external snapshot write, Runtime reload, notification, release, tag, or promotion during code implementation without a new exact external-operation authorization.
- Test fixtures use fake member rows and temporary directories; never read credentials, the configured research-data root, or live provider state.
- `auto_order=false`; no Signal, Alert, notification, Execution Review, order, PnL, or generic backtest surface.

---

## File Map

### New Python files

- `services/quant-api/app/market_data/member_rank_snapshot.py` — immutable descriptor/row types, exact-path Parquet reader, daily aggregation and causal history lookup.
- `services/quant-api/app/market_data/member_rank_snapshot_builder.py` — exact-contract plan, provider normalization, staging validation and atomic immutable publish.
- `services/quant-api/app/market_data/main_force_mirror_v2_service.py` — page/window orchestration over MarketDataService and member repository.
- `services/quant-api/app/market_data/main_force_mirror_v2_research_service.py` — retrospective comparisons and horizon summaries.
- `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py` — sole V2 instant/accumulated/member/caution formula.
- `services/quant-api/tests/data_foundation/test_member_rank_snapshot.py` — reader and physical-integrity tests.
- `services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py` — plan/dry-run/provider/atomic-publish tests.
- `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py` — segment-prefix, T-1 and page-slicing tests.
- `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py` — cohort/horizon tests.
- `services/quant-api/tests/test_main_force_mirror_v2.py` — Kernel and V1→V2 caution migration tests.
- `tests/fixtures/main_force_mirror_v2_golden.json` — new V2 golden identity and expected points.

### New Web files

- `apps/quant-web/src/composables/useMainForceMirrorV2.ts` — independent paged API state with generation protection.
- `apps/quant-web/src/utils/mainForceMirrorV2Presentation.ts` — DTO-to-chart projection and descriptive labels only.
- `apps/quant-web/tests/mainForceMirrorV2.test.ts` — API state, pagination, stale-response and render projection tests.
- `apps/quant-web/e2e/main-force-mirror-v2.spec.mjs` — two-tab, API-only calculation, marker, unavailable and Live-cutoff browser acceptance.

### Existing files modified before retirement

- `packages/quant-core/guiyi_quant/indicators/__init__.py`
- `packages/quant-core/guiyi_quant/indicators/registry.py`
- `packages/quant-core/guiyi_quant/indicators/policy.py`
- `services/quant-api/app/market_data/composition.py`
- `services/quant-api/app/market_data/coverage_source.py`
- `services/quant-api/app/guiyi_cli/data_parser.py`
- `services/quant-api/app/guiyi_cli/data_commands.py`
- `services/quant-api/app/guiyi_cli/research_parser.py`
- `services/quant-api/app/guiyi_cli/research_commands.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/tests/data_foundation/test_cli.py`
- `services/quant-api/tests/data_foundation/test_market_api.py`
- `services/quant-api/tests/test_indicator_registry_v1.py`
- `services/quant-api/tests/test_research_cli.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- `apps/quant-web/src/utils/klineViewModel.ts`
- `apps/quant-web/tests/kline-view-model.test.ts`
- `apps/quant-web/tests/marketSeries.test.ts`

### Deleted in the retirement task

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py`
- `packages/quant-core/guiyi_quant/indicators/main_force_mirror.pyi`
- `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- `services/quant-api/app/market_data/main_force_mirror_futures_research_service.py`
- `apps/quant-web/src/utils/mainForceMirror.ts`
- `apps/quant-web/src/utils/mainForceMirrorFutures.ts`
- `services/quant-api/tests/test_main_force_mirror.py`
- `services/quant-api/tests/test_main_force_mirror_futures.py`
- `services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py`
- `apps/quant-web/tests/mainForceMirror.test.ts`
- `apps/quant-web/tests/mainForceMirrorFutures.test.ts`
- `apps/quant-web/e2e/main-force-mirror.spec.mjs`
- `apps/quant-web/e2e/main-force-mirror-futures.spec.mjs`
- `tests/fixtures/main_force_mirror_futures_v1_golden.json`

---

## Approved-Spec Coverage

- Spec §5 snapshot contract and RQData boundary → Tasks 1–2.
- Spec §6 identities/capabilities and §7–10 pressure, EMA5, member context and
  frozen “小心” semantics → Tasks 3–4.
- Spec §11 read-only service/API, full segment prefix and error boundary → Task 5.
- Spec §13 retrospective comparison, fixed horizons, heterogeneity and
  sensitivity discipline → Task 6.
- Spec §12 MACD/V2-only pane, historical cutoff and server-value projection →
  Tasks 7–8.
- Spec §14–18 V0/V1 retirement, replacement proof, full verification and
  external-Gate boundary → Task 9.

---

### Task 1: Immutable member-rank snapshot reader

**Files:**
- Create: `services/quant-api/app/market_data/member_rank_snapshot.py`
- Create: `services/quant-api/tests/data_foundation/test_member_rank_snapshot.py`

**Interfaces:**
- Consumes: explicit research-data `root: Path`, explicit `dataset_id: str`, normalized physical contract and `date`. The only resolved dataset path is `root / "main_force_member_rank_v1" / dataset_id`.
- Produces: `MemberRankRow`, `MemberRankDay`, `MemberRankSnapshotDescriptor`, `MemberRankSnapshotRepository`, `MemberRankSnapshotError`.
- Exact public method surface (the concrete class implements each line below; no
  alternate “latest snapshot” constructor is allowed):

```python
MemberRankSnapshotRepository(root: Path, dataset_id: str)
MemberRankSnapshotRepository.descriptor -> MemberRankSnapshotDescriptor
MemberRankSnapshotRepository.day(physical_contract: str, trade_date: date) -> MemberRankDay | None
MemberRankSnapshotRepository.contract_days_before(
    physical_contract: str, before: date, *, limit: int
) -> tuple[MemberRankDay, ...]
MemberRankSnapshotRepository.rank1_days_before(
    symbol: str,
    before: date,
    *,
    limit: int,
    contract_by_day: Mapping[date, str],
) -> tuple[MemberRankDay, ...]
```

- [ ] **Step 1: Write descriptor and exact-path failure tests**

```python
def test_repository_requires_exact_dataset_id_and_never_selects_newest(tmp_path):
    write_snapshot(tmp_path, "older", admitted_products=("jm",))
    write_snapshot(tmp_path, "newer", admitted_products=("ag",))

    repository = MemberRankSnapshotRepository(tmp_path, "older")

    assert repository.descriptor.dataset_id == "older"
    assert repository.descriptor.admitted_products == ("jm",)


def test_repository_rejects_descriptor_path_escape(tmp_path):
    write_descriptor(tmp_path, "broken", relative_uri="../outside.parquet")

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_SNAPSHOT_ROOT_ESCAPE"):
        MemberRankSnapshotRepository(tmp_path, "broken")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py
```

Expected: collection fails because `app.market_data.member_rank_snapshot` does not exist.

- [ ] **Step 3: Add immutable descriptor and row types**

```python
RANK_BY_VALUES = ("volume", "long", "short")
MEMBER_RANK_SCHEMA_VERSION = 1

@dataclass(frozen=True, slots=True)
class MemberRankRow:
    physical_contract: str
    trade_date: date
    rank_by: Literal["volume", "long", "short"]
    rank: int
    member_name: str
    value: Decimal
    change: Decimal

@dataclass(frozen=True, slots=True)
class MemberRankDay:
    physical_contract: str
    trade_date: date
    rows: tuple[MemberRankRow, ...]

    def rows_for(self, rank_by: str) -> tuple[MemberRankRow, ...]:
        return tuple(row for row in self.rows if row.rank_by == rank_by)

@dataclass(frozen=True, slots=True)
class MemberRankPartitionDescriptor:
    relative_uri: str
    row_count: int
    coverage_start: date
    coverage_end: date
    quality_status: Literal["passed"]

@dataclass(frozen=True, slots=True)
class MemberRankSnapshotDescriptor:
    schema_version: int
    dataset_id: str
    provider: Literal["rqdata"]
    provider_client_version: str
    created_at: datetime
    requested_since: date
    requested_through: date
    requested_products: tuple[str, ...]
    admitted_products: tuple[str, ...]
    physical_contracts: tuple[str, ...]
    partitions: tuple[MemberRankPartitionDescriptor, ...]
```

Parse `snapshot.json` with explicit type/allowlist checks. Resolve every descriptor URI and require `path == snapshot_root or snapshot_root in path.parents`.

- [ ] **Step 4: Add exact Parquet schema and strict day validation**

```python
MEMBER_RANK_SCHEMA = pa.schema([
    pa.field("physical_contract", pa.string(), nullable=False),
    pa.field("trade_date", pa.date32(), nullable=False),
    pa.field("rank_by", pa.string(), nullable=False),
    pa.field("rank", pa.int16(), nullable=False),
    pa.field("member_name", pa.string(), nullable=False),
    pa.field("value", pa.decimal128(38, 0), nullable=False),
    pa.field("change", pa.decimal128(38, 0), nullable=False),
    pa.field("provider", pa.string(), nullable=False),
    pa.field("dataset_id", pa.string(), nullable=False),
])

def _validate_day(day: MemberRankDay) -> None:
    for rank_by in RANK_BY_VALUES:
        rows = tuple(sorted(day.rows_for(rank_by), key=lambda row: row.rank))
        if tuple(row.rank for row in rows) != tuple(range(1, 21)):
            raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_INCOMPLETE")
        if any(
            not row.member_name.strip()
            or row.value < 0
            or not row.change.is_finite()
            for row in rows
        ):
            raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_INVALID")
```

Require unique `(contract, date, rank_by, rank)`, official TradingCalendar
membership, Catalog contract-validity coverage, descriptor schema, Parquet schema,
row count, coverage, provider and dataset id to match before exposing rows. Inject
the calendar/contract-validity verifier into the repository rather than importing
a second resolver.

- [ ] **Step 5: Add complete/incomplete/history tests**

```python
def test_day_requires_three_complete_top20_rank_sets(tmp_path):
    repository = repository_with_rows(tmp_path, complete_rows()[:-1])

    with pytest.raises(MemberRankSnapshotError, match="MEMBER_CONTRACT_DAY_INCOMPLETE"):
        repository.day("JM2609", date(2026, 8, 20))


def test_contract_history_is_strictly_before_and_bounded(tmp_path):
    repository = repository_with_days(tmp_path, dates=(18, 19, 20, 21))

    result = repository.contract_days_before(
        "JM2609", date(2026, 8, 21), limit=2
    )

    assert [item.trade_date.day for item in result] == [19, 20]
```

- [ ] **Step 6: Run reader tests GREEN**

Run the Task 1 command. Expected: all tests pass and no configured project research-data path is touched.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  services/quant-api/app/market_data/member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py
git commit -m "feat(data): add immutable member rank snapshot reader"
```

---

### Task 2: Snapshot planner, provider boundary, atomic builder, and dry-run CLI

**Files:**
- Create: `services/quant-api/app/market_data/member_rank_snapshot_builder.py`
- Modify: `services/quant-api/app/market_data/rqdata_adapter.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/data_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/data_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Create: `services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`

**Interfaces:**
- Consumes: exact Catalog rank1 maps and contract active windows, RQData only behind an apply-only provider port.
- Produces: `MemberRankSnapshotRequest`, `MemberRankSnapshotPlan`, `MemberRankSnapshotResult`, `MemberRankSnapshotBuilder`, `RQDataMemberRankProvider`.
- CLI: `guiyi data member-rank snapshot --dataset-id ID --products jm ag cu m --since YYYY-MM-DD --through YYYY-MM-DD [--apply]`.

- [ ] **Step 1: Write dry-run and provider-isolation tests**

```python
def test_member_rank_snapshot_defaults_to_plan_without_provider_or_write(tmp_path):
    provider = FailingIfCalledProvider()
    builder = snapshot_builder(tmp_path, provider=provider)
    request = MemberRankSnapshotRequest(
        dataset_id="mfm-member-20260821",
        products=("jm", "ag"),
        since=date(2026, 1, 1),
        through=date(2026, 8, 20),
        apply=False,
    )

    result = builder.snapshot(request)

    assert result.status == "planned"
    assert result.provider_calls == 0
    assert not (tmp_path / "main_force_member_rank_v1").exists()


def test_member_rank_cli_requires_explicit_apply_for_mutation():
    args = build_parser().parse_args([
        "data", "member-rank", "snapshot",
        "--dataset-id", "mfm-member-20260821",
        "--products", "jm", "ag", "cu", "m",
        "--since", "2023-01-03",
        "--through", "2026-08-20",
    ])
    assert args.apply is False


@pytest.mark.parametrize("rank_by", ("volume", "long", "short"))
def test_rqdata_provider_normalizes_each_supported_member_rank_shape(rank_by):
    provider = rqdata_provider_with_frame(rank_by_frame(rank_by))

    rows = provider.fetch(member_fetch(rank_by=rank_by))

    assert len(rows) == 20
    assert {row.rank_by for row in rows} == {rank_by}
    assert all(row.physical_contract == "JM2609" for row in rows)
```

- [ ] **Step 2: Run builder/CLI tests RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

Expected: imports or parser assertions fail because the builder and nested command do not exist.

- [ ] **Step 3: Define request, plan, provider protocol and result**

```python
RANK_BY_VALUES = ("volume", "long", "short")

@dataclass(frozen=True, slots=True)
class MemberRankSnapshotRequest:
    dataset_id: str
    products: tuple[str, ...]
    since: date
    through: date
    apply: bool = False

@dataclass(frozen=True, slots=True)
class MemberRankFetch:
    symbol: str
    physical_contract: str
    since: date
    through: date
    rank_by: Literal["volume", "long", "short"]

class MemberRankProvider(Protocol):
    fetch: Callable[[MemberRankFetch], tuple[MemberRankRow, ...]]

@dataclass(frozen=True, slots=True)
class MemberRankSnapshotResult:
    status: Literal["planned", "published"]
    dataset_id: str
    products: tuple[str, ...]
    contract_count: int
    provider_calls: int
    partition_count: int

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.member-rank.snapshot",
            "status": self.status,
            "dataset_id": self.dataset_id,
            "products": list(self.products),
            "contract_count": self.contract_count,
            "provider_calls": self.provider_calls,
            "partition_count": self.partition_count,
            "readonly": self.status == "planned",
        }
```

Validate ASCII dataset id, unique lower-case products, `since <= through`, and
the active product allowlist. Freeze the first admission policy as exactly
`("jm", "ag", "cu", "m")`; reject any other requested product with
`MEMBER_SNAPSHOT_PRODUCT_NOT_ADMITTED`. The reader/service remains generic for
active-60 products, so products outside the pinned snapshot return point-level
unavailable rather than acquiring a second implementation. A future admission
change requires new evidence and a new immutable dataset id.

- [ ] **Step 4: Add a thin RQData member-rank call**

Add to `RQDataClient`:

```python
def member_rank(
    self,
    order_book_id: str,
    start: date,
    end: date,
    rank_by: str,
):
    return self.api.futures.get_member_rank(
        order_book_id,
        start_date=start,
        end_date=end,
        rank_by=rank_by,
    )
```

`RQDataMemberRankProvider.fetch()` converts provider-specific columns into `MemberRankRow`, normalizes the contract to uppercase, converts values through `Decimal(str(value))`, and maps provider exceptions to stable infrastructure codes. It is constructed lazily only on `apply=True`.
Adapter tests use fixture DataFrames for all three `rank_by` response shapes,
including MultiIndex/date normalization, empty frames, non-finite `change`,
duplicate ranks and provider exceptions. Record `rqdatac.__version__` in the
descriptor; do not make a network call merely to discover the version.

- [ ] **Step 5: Implement exact rank1 planning and atomic publish**

```python
def snapshot(self, request: MemberRankSnapshotRequest) -> MemberRankSnapshotResult:
    plan = self.plan(request)
    if not request.apply:
        return plan.as_result(status="planned", provider_calls=0, partition_count=0)
    staging = self._staging_path(request.dataset_id)
    final = self._final_path(request.dataset_id)
    if final.exists():
        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_ALREADY_EXISTS")
    rows = tuple(
        row
        for fetch in plan.fetches
        for row in self.provider.fetch(fetch)
    )
    self._write_and_read_back(staging, request, plan, rows)
    os.replace(staging, final)
    return plan.as_result(
        status="published",
        provider_calls=len(plan.fetches),
        partition_count=len(plan.partitions),
    )
```

Planning groups contiguous `MainContractMap rank=1` days into exact physical-contract windows and creates exactly three fetches per window. The write phase partitions by physical contract/year, writes `snapshot.json` last inside staging, reopens every Parquet file through the Task 1 reader, then atomically renames the completed snapshot directory. On failure, remove only the exact sibling staging directory created by this call; never touch an existing final snapshot.

- [ ] **Step 6: Register the nested CLI without widening HistoricalDataManager**

```python
member_rank = commands.add_parser("member-rank")
member_rank_commands = member_rank.add_subparsers(
    dest="member_rank_command", required=True
)
snapshot = member_rank_commands.add_parser("snapshot")
snapshot.add_argument("--dataset-id", required=True)
snapshot.add_argument("--products", nargs="+", required=True)
snapshot.add_argument("--since", required=True)
snapshot.add_argument("--through", required=True)
snapshot.add_argument("--apply", action="store_true")
```

Add a separate `member_rank_snapshot_builder_factory` to `main()`. In `_run_data`, route only `data_command == "member-rank"` to that builder; keep `HistoricalDataManager` unchanged.
Extend the existing successful-status set in `main()` with `"published"`; do not
special-case process exit outside the shared CLI result path.

- [ ] **Step 7: Add atomicity, quality and CLI JSON tests**

```python
def test_apply_rejects_one_missing_rank_without_publishing(tmp_path):
    provider = FakeProvider(rows=complete_rows()[:-1])
    builder = snapshot_builder(tmp_path, provider=provider)

    with pytest.raises(MemberRankSnapshotBuildError, match="MEMBER_CONTRACT_DAY_INCOMPLETE"):
        builder.snapshot(valid_request(apply=True))

    assert not final_snapshot_path(tmp_path).exists()


def test_cli_plan_reports_zero_provider_calls_and_readonly_true():
    code, payload = run_member_rank_cli(apply=False)

    assert code == 0
    assert payload["status"] == "planned"
    assert payload["provider_calls"] == 0
    assert payload["readonly"] is True
```

- [ ] **Step 8: Run Task 2 tests GREEN**

Run the Task 2 command. Expected: all focused tests pass; fake provider call count is zero for dry-run and no external path is used.

- [ ] **Step 9: Commit Task 2**

```bash
git add \
  services/quant-api/app/market_data/member_rank_snapshot_builder.py \
  services/quant-api/app/market_data/rqdata_adapter.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/data_parser.py \
  services/quant-api/app/guiyi_cli/data_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_cli.py
git commit -m "feat(data): add member rank snapshot builder"
```

---

### Task 3: V2 instant pressure, accumulated pressure, and frozen caution migration

**Files:**
- Create: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`
- Create: `services/quant-api/tests/test_main_force_mirror_v2.py`
- Create: `tests/fixtures/main_force_mirror_v2_golden.json`
- Read during migration: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py`
- Read during migration: `tests/fixtures/main_force_mirror_futures_v1_golden.json`

**Interfaces:**
- Consumes: aligned 60m bar arrays and optional per-bar `MemberRankObservation` values.
- Produces: `compute_main_force_mirror_v2(...) -> MainForceMirrorV2Result` and exact V2 dataclasses/enums.

- [ ] **Step 1: Write identity, block, EMA5 and caution-equivalence tests**

```python
def test_v2_accumulated_pressure_uses_sma_seed_and_resets_on_contract_switch():
    result = compute_main_force_mirror_v2(**bars_with_contract_switch())
    first_block_ready = ready_points(result, contract="AG2601")
    second_block_ready = ready_points(result, contract="AG2602")

    assert first_block_ready[3].accumulated_pressure is None
    assert first_block_ready[4].accumulated_pressure == mean(
        point.instant_pressure for point in first_block_ready[:5]
    )
    assert second_block_ready[0].accumulated_pressure is None


def test_v2_caution_is_pointwise_equal_to_frozen_v1_before_retirement():
    bars = load_v1_golden_bars()
    old = compute_main_force_mirror_futures(**kernel_inputs(bars))
    new = compute_main_force_mirror_v2(**kernel_inputs(bars))

    assert tuple(point.caution_ready for point in new.points) == tuple(old.caution_ready)
    assert tuple(point.long_caution_score for point in new.points) == tuple(old.long_caution_score)
    assert tuple(point.short_caution_score for point in new.points) == tuple(old.short_caution_score)
    assert tuple(point.caution for point in new.points) == tuple(old.caution)
    assert tuple(point.caution_reason_codes for point in new.points) == tuple(old.caution_reason_codes)
    assert tuple(point.caution_conflict for point in new.points) == tuple(old.caution_conflict)
```

- [ ] **Step 2: Run Kernel tests RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py
```

Expected: import fails because `main_force_mirror_v2` does not exist.

- [ ] **Step 3: Define exact V2 parameter and result contracts**

```python
INDICATOR_CODE = "main_force_mirror_v2"
INDICATOR_VERSION = "futures-member-research-v2"
FORMAL_POLICY_ID = "main_force_mirror_observation_v2"

DEFAULT_PARAMETERS = MappingProxyType({
    "atr_period": 14,
    "volume_window": 20,
    "oi_impulse_ema_period": 20,
    "range_window": 20,
    "pressure_divergence_window": 10,
    "accumulated_ema_period": 5,
    "direction_price_weight": 0.7,
    "direction_clv_weight": 0.3,
    "direction_deadband": 0.15,
    "oi_deadband": 0.25,
    "caution_threshold": 70,
    "rearm_score_threshold": 40,
    "rearm_low_score_bars": 3,
    "rearm_build_bars": 2,
    "member_neutral_strength": 0.5,
    "member_strong_strength": 2.0,
    "member_baseline_days": 60,
    "member_min_baseline_days": 20,
    "round_digits": 6,
    "rounding_policy": "half_away_from_zero_binary64",
})

@dataclass(frozen=True, slots=True)
class MemberRankObservation:
    status: Literal["ready", "unavailable"]
    member_trade_date: date | None
    direction: Literal["long", "short", "neutral"] | None
    change_bias: float | None
    strength: float | None
    position_skew: float | None
    top5_volume_share: float | None
    relation_to_accumulated: Literal[
        "strong_aligned", "aligned", "divergent", "neutral", "unavailable"
    ]
    relation_to_caution: Literal[
        "strong_aligned", "aligned", "divergent", "neutral", "unavailable"
    ]
    unavailable_reason: str | None

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2Point:
    bar_end: datetime
    trading_day: date
    physical_contract: str | None
    pressure_ready: bool
    pressure_state: MainForceMirrorV2State | None
    instant_pressure: float | None
    accumulated_ready: bool
    accumulated_pressure: float | None
    caution_ready: bool
    caution: MainForceMirrorV2Caution | None
    caution_conflict: bool
    long_caution_score: float | None
    short_caution_score: float | None
    caution_reason_codes: tuple[str, ...]
    member: MemberRankObservation | None
    unavailable_reason: str | None

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2Result:
    indicator_code: Literal["main_force_mirror_v2"]
    indicator_version: Literal["futures-member-research-v2"]
    formal_policy_id: Literal["main_force_mirror_observation_v2"]
    parameters_hash: str
    points: tuple[MainForceMirrorV2Point, ...]
```

Include the existing diagnostic raw fields required by hover (`price_impulse`, `clv`, `volume_ratio`, `delta_oi`, `oi_impulse`, `range_position`) in the concrete dataclass.

- [ ] **Step 4: Port the pressure and caution code under V2 names**

Copy the mathematical implementation, not the old public identity. Rename stable errors to `MFM_V2_*`, retain binary64 unrounded comparisons, preserve block rules, and calculate:

```python
instant_pressure = _signed_pressure(state, strength, direction)
accumulated_pressure = _ema_sma_seed(
    ready_instant_pressures,
    DEFAULT_PARAMETERS["accumulated_ema_period"],
)
```

The first accumulated value appears on the fifth state-ready point in the same block. Caution continues to use raw pressure values and never consumes the EMA5 result.

- [ ] **Step 5: Freeze the new golden fixture**

Generate `tests/fixtures/main_force_mirror_v2_golden.json` from the deterministic old fixture bars. Store V2 metadata, instant/accumulated fields, and the pointwise-equal caution expectations. Do not copy V1 identity fields into the new fixture.

- [ ] **Step 6: Run old and new Kernel suites GREEN together**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror_v2.py
```

Expected: both suites pass; the migration equivalence test proves the retained caution before V1 deletion.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  tests/fixtures/main_force_mirror_v2_golden.json
git commit -m "feat(indicators): add main force mirror v2 kernel"
```

---

### Task 4: Causal member features and V2 Registry/Policy

**Files:**
- Modify: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `services/quant-api/tests/test_main_force_mirror_v2.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`

**Interfaces:**
- Consumes: `MemberRankDailyInput` containing the current T-1 aggregate and prior causal baseline values selected by the service.
- Produces: `compute_member_rank_observation(...)`, member direction/strength/relation fields, and V2 observation-only Registry/Policy entries.

- [ ] **Step 1: Write feature thresholds and non-interference tests**

```python
def test_member_strength_uses_only_prior_values_and_exact_thresholds():
    result = compute_member_rank_observation(
        current=member_day(change_bias=Decimal("0.020")),
        prior_change_biases=(Decimal("0.010"),) * 20,
        accumulated_pressure=25.0,
        caution="long_chase_caution",
    )

    assert result.direction == "long"
    assert result.strength == 2.0
    assert result.relation_to_accumulated == "strong_aligned"
    assert result.relation_to_caution == "strong_aligned"


def test_member_input_never_changes_caution_or_instant_pressure():
    without_member = compute_main_force_mirror_v2(**bars(), member_inputs=None)
    with_member = compute_main_force_mirror_v2(
        **bars(), member_inputs=member_inputs_for_all_bars()
    )

    assert [point.instant_pressure for point in with_member.points] == [
        point.instant_pressure for point in without_member.points
    ]
    assert [point.caution for point in with_member.points] == [
        point.caution for point in without_member.points
    ]
    assert [point.caution_reason_codes for point in with_member.points] == [
        point.caution_reason_codes for point in without_member.points
    ]
```

- [ ] **Step 2: Run feature/Registry tests RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

Expected: feature import or V2 Registry assertion fails.

- [ ] **Step 3: Implement daily aggregation and strength**

```python
def compute_member_rank_observation(
    current: MemberRankDailyInput,
    prior_change_biases: Sequence[Decimal],
    *,
    accumulated_pressure: float | None,
    caution: MainForceMirrorV2Caution | None,
) -> MemberRankObservation:
    if len(prior_change_biases) < 20:
        return MemberRankObservation.unavailable("MFM_V2_MEMBER_WARMUP")
    baseline_values = tuple(abs(value) for value in prior_change_biases[-60:])
    baseline = median(baseline_values)
    if baseline <= 0:
        return MemberRankObservation.unavailable("MFM_V2_MEMBER_WARMUP")
    strength = abs(current.change_bias) / baseline
    direction = "neutral" if strength < Decimal("0.5") else (
        "long" if current.change_bias > 0 else "short"
    )
    return _member_relations(current, direction, strength, accumulated_pressure, caution)
```

Use Decimal for member totals/bias/baseline and convert only final dimensionless public fields through the V2 rounding helper.

- [ ] **Step 4: Add the V2 Registry and Formal Policy alongside V0/V1 temporarily**

```python
"main_force_mirror_v2": build_indicator_definition(
    indicator_code="main_force_mirror_v2",
    indicator_version="futures-member-research-v2",
    display_name="主力照妖镜 V2",
    display_type="subpane",
    input_fields=(
        "open", "high", "low", "close", "volume", "open_interest",
        "physical_contract", "member_rank_t_minus_1",
    ),
    supported_intervals=("60m",),
    default_parameters=dict(MFM_V2_PARAMETERS),
    lookback_bars=31,
    warmup_bars=30,
    calculation_source=(
        "guiyi_quant.indicators.main_force_mirror_v2."
        "compute_main_force_mirror_v2"
    ),
    closed_bar_only=True,
    confirmed_only=True,
    status="observation_only",
    repainting_risk="none",
    repainting_notes="Historical exact-contract pressure and T-1 member context only.",
    web_capable=True,
    backtest_capable=False,
    live_capable=False,
    alert_capable=False,
    default_visible=False,
    default_color="#22c55e",
    output_schema="main_force_mirror_v2_point",
    formal_policy_id="main_force_mirror_observation_v2",
    seed_policy="sma_window",
    smoothing_policy=None,
    histogram_scale=None,
)
```

Policy allowed consumer is exactly `("Web_manual_observation",)`; block formal backtest, live, alert, notification and auto order.

- [ ] **Step 5: Run Task 4 tests GREEN**

Run the Task 4 command. Expected: feature and capability tests pass; V0/V1 remain temporarily available for the later retirement task.

- [ ] **Step 6: Commit Task 4**

```bash
git add \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  packages/quant-core/guiyi_quant/indicators/registry.py \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat(indicators): add causal member context to mirror v2"
```

---

### Task 5: V2 page service and read-only Market API

**Files:**
- Create: `services/quant-api/app/market_data/main_force_mirror_v2_service.py`
- Modify: `services/quant-api/app/market_data/coverage_source.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

**Interfaces:**
- Consumes: `SeriesPageQuery`, `MarketDataService`, `ActualDominantResearchSegmentLoader`, `DatabaseCoverageSource`, `MemberRankSnapshotRepository`.
- Produces: `MainForceMirrorV2PageResult` and `GET /api/v1/market/research/main-force-mirror`.

- [ ] **Step 1: Write unsupported, T-1, prefix and member-unavailable tests**

```python
def test_service_rejects_continuous_and_non_60m_before_reading_data():
    service = mirror_service(FailingMarketData(), empty_repository())

    with pytest.raises(MainForceMirrorV2Error, match="MFM_V2_UNSUPPORTED_SERIES_KIND"):
        service.query_page(SeriesPageQuery("continuous", "jm", "60m"))
    with pytest.raises(MainForceMirrorV2Error, match="MFM_V2_UNSUPPORTED_FREQUENCY"):
        service.query_page(SeriesPageQuery("actual_dominant", "jm", "15m"))


def test_service_uses_new_contract_previous_trading_day_on_roll():
    service = mirror_service_with_roll("JM2609", "JM2701")

    result = service.query_page(actual_dominant_page_request())
    rolled = next(point for point in result.points if point.physical_contract == "JM2701")

    assert rolled.member_trade_date == date(2026, 8, 20)
    assert rolled.member_status == "ready"
    assert service.repository.requests[-1] == ("JM2701", date(2026, 8, 20))


def test_service_computes_latch_from_true_segment_start_before_slicing_page():
    service = mirror_service_with_prior_caution_outside_page()

    result = service.query_page(page_after_prior_caution())

    assert result.points[0].caution is None
    assert result.points[0].caution_ready is True
```

- [ ] **Step 2: Run service/API tests RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py
```

Expected: service import and route assertions fail.

- [ ] **Step 3: Expose a public previous-trading-day resolver**

In `DatabaseCoverageSource` add:

```python
def previous_trading_day(self, symbol: str, trading_day: date) -> date:
    exchange = self._exchange_for_symbol(symbol)
    return self._previous_trading_day(exchange, trading_day)
```

Keep the existing TradingCalendar continuity checks and stable missing-calendar error. Do not infer from `trading_day - timedelta(days=1)`.

- [ ] **Step 4: Implement full-prefix calculation then exact page slicing**

```python
@dataclass(frozen=True, slots=True)
class MainForceMirrorV2PageResult:
    request_identity: Mapping[str, object]
    points: tuple[MainForceMirrorV2Point, ...]
    member_dataset: MemberDatasetState
    has_more_before: bool
    next_before: datetime | None
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]

def query_page(self, request: SeriesPageQuery) -> MainForceMirrorV2PageResult:
    self._validate_request(request)
    target = self.market_data.query_page(request)
    full = self._full_calculation_prefix(request, target)
    member_inputs = self._member_inputs(request, full)
    observation = compute_main_force_mirror_v2(
        **_bar_inputs(full.bars, full.resolved_contract_segments),
        member_inputs=member_inputs,
    )
    target_ends = {bar.bar_end for bar in target.bars}
    points = tuple(
        point for point in observation.points if point.bar_end in target_ends
    )
    if tuple(point.bar_end for point in points) != tuple(bar.bar_end for bar in target.bars):
        raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")
    return _page_result(target, points, self.member_repository)
```

For `actual_dominant`, call `ActualDominantResearchSegmentLoader.load()` with the target first/last trading days so it restores the true first segment start. For `contract`, call `query_contract_trading_days()` from the configured active history floor through the target last day; MarketDataService performs contract validity narrowing.

Build T-1 inputs by exact bar `physical_contract`, `previous_trading_day`, and repository day. For the member strength baseline:

- actual dominant: use `rank1_days_before(symbol, member_trade_date, limit=60, contract_by_day=...)`;
- contract: use `contract_days_before(contract, member_trade_date, limit=60)`.

Product-not-admitted, missing day and fewer than 20 baseline days return point-level unavailable. Descriptor/Parquet corruption raises `MFM_V2_MEMBER_DATASET_INVALID` for the whole request.

In composition, `member_rank_repository_from_env()` has three explicit cases:

- both `GUIYI_RESEARCH_DATA_ROOT` and
  `GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID` absent → repository is `None` and
  core pressure returns with `member_dataset.status=unavailable`;
- exactly one present → fail closed with
  `MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT`;
- both present → construct the exact pinned repository, and propagate any
  descriptor/readback error as a request-level 409.

- [ ] **Step 5: Add Pydantic DTOs and route**

```python
@router.get(
    "/research/main-force-mirror",
    response_model=MainForceMirrorV2PageResponse,
)
def main_force_mirror_v2_page(
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    before: str | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=2000),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MainForceMirrorV2PageResponse:
    request = SeriesPageQuery(
        series_kind=cast(SeriesKind, series_kind),
        symbol=symbol,
        contract=contract,
        frequency=cast(BarFrequency, frequency),
        before=parse_rfc3339_instant(before, field="datetime") if before else None,
        limit=limit,
    )
    return to_main_force_mirror_v2_response(
        build_main_force_mirror_v2_service(session).query_page(request)
    )
```

Map contract/request errors to 422, market/dataset identity errors to 409, and never return file paths or exception messages.

- [ ] **Step 6: Add API payload and error tests**

```python
def test_main_force_mirror_v2_api_returns_dataset_identity_and_t_minus_one():
    response = client_with_fake_mirror().get(
        "/api/v1/market/research/main-force-mirror",
        params={"series_kind": "actual_dominant", "symbol": "jm", "frequency": "60m"},
    )

    assert response.status_code == 200
    assert response.json()["indicator"]["indicator_code"] == "main_force_mirror_v2"
    assert response.json()["member_dataset"]["dataset_id"] == "fixture-member-v1"
    assert response.json()["points"][0]["member_trade_date"] == "2026-08-20"


def test_main_force_mirror_v2_api_hides_corrupt_snapshot_details():
    response = client_with_mirror_error("MFM_V2_MEMBER_DATASET_INVALID").get(
        "/api/v1/market/research/main-force-mirror",
        params={"series_kind": "contract", "symbol": "jm", "contract": "JM2609", "frequency": "60m"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "MFM_V2_MEMBER_DATASET_INVALID"}}
```

- [ ] **Step 7: Run Task 5 tests GREEN**

Run the Task 5 command. Expected: all service/API tests pass with fake MarketDataService and tmp snapshot only.

- [ ] **Step 8: Commit Task 5**

```bash
git add \
  services/quant-api/app/market_data/main_force_mirror_v2_service.py \
  services/quant-api/app/market_data/coverage_source.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py
git commit -m "feat(market): expose read-only main force mirror v2"
```

---

### Task 6: Historical comparison service and V2 research CLI

**Files:**
- Create: `services/quant-api/app/market_data/main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Create: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/tests/test_research_cli.py`

**Interfaces:**
- Consumes: exact `MainForceMirrorV2ResearchRequest` and the same service/repository identity as the API.
- Produces: grouped `1/3/5/10` horizon summaries and `guiyi research main-force-mirror-v2` JSON.

- [ ] **Step 1: Write grouping, no-cross-roll and parser-retirement tests**

```python
def test_research_groups_caution_by_member_relation_without_crossing_roll():
    result = research_service_with_roll().run(research_request())

    assert result.pooled["all_caution"][5].sample_count == 2
    assert result.pooled["caution_member_strong_aligned"][5].sample_count == 1
    assert result.pooled["all_caution"][10].sample_count == 0


def test_research_parser_exposes_v2_name_not_v1_name():
    choices = research_command_choices(build_parser())

    assert "main-force-mirror-v2" in choices
    assert "main-force-mirror-futures" not in choices
```

- [ ] **Step 2: Run research tests RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py
```

Expected: service import or parser assertion fails.

- [ ] **Step 3: Define exact research result types and horizons**

```python
HORIZONS = (1, 3, 5, 10)
COHORTS = (
    "instant_pressure",
    "accumulated_pressure",
    "member_aligned",
    "member_strong_aligned",
    "member_divergent",
    "member_neutral",
    "member_unavailable",
    "all_caution",
    "caution_member_aligned",
    "caution_member_strong_aligned",
    "caution_member_divergent",
)

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2HorizonSummary:
    horizon_bars: int
    sample_count: int
    median_directional_return: Decimal | None
    median_reversal_return: Decimal | None
    hit_rate: Decimal | None
    median_mfe: Decimal | None
    median_mae: Decimal | None

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2GroupSpread:
    horizon_bars: int
    top_group: str
    bottom_group: str
    directional_return_spread: Decimal | None
    top_sample_count: int
    bottom_sample_count: int

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2SensitivitySummary:
    member_strength_threshold: Decimal
    by_product: Mapping[str, Mapping[int, MainForceMirrorV2HorizonSummary]]
    pooled: Mapping[int, MainForceMirrorV2HorizonSummary]

@dataclass(frozen=True, slots=True)
class MainForceMirrorV2ResearchResult:
    indicator_code: str
    indicator_version: str
    parameters_hash: str
    research_protocol: Literal["main_force_mirror_v2_retrospective_v1"]
    evaluation_classification: Literal["retrospective_walk_forward_diagnostic"]
    requested_since: date
    requested_through: date
    prospective_oos_starts_after: date
    member_dataset_id: str | None
    products: tuple[str, ...]
    member_coverage: Decimal | None
    caution_ready_bars: int
    caution_events: int
    caution_events_per_1000_ready_bars: Decimal | None
    yearly: Mapping[int, Mapping[str, Mapping[str, Mapping[int, MainForceMirrorV2HorizonSummary]]]]
    by_product: Mapping[str, Mapping[str, Mapping[str, Mapping[int, MainForceMirrorV2HorizonSummary]]]]
    pooled: Mapping[str, Mapping[int, MainForceMirrorV2HorizonSummary]]
    top_bottom_spreads: Mapping[int, MainForceMirrorV2GroupSpread]
    sensitivity: Mapping[Decimal, MainForceMirrorV2SensitivitySummary]
```

The extra nested key in `yearly` and `by_product` is the frozen pressure/caution
state, so output is explicitly grouped by product, year and state. Keep raw
forward observations internal. For every horizon, reject targets that cross a
physical-contract boundary. Evaluate sensitivity only at
`0.5/1.0/1.5/2.0/2.5`, never search per product, and keep the frozen V2 output
threshold at `2.0`. Pooled summaries never replace yearly/by-product output.

- [ ] **Step 4: Implement read-only CLI request and JSON rendering**

CLI arguments:

```python
mirror = commands.add_parser("main-force-mirror-v2")
mirror.add_argument("--symbol", required=True)
mirror.add_argument("--series-kind", choices=("actual_dominant", "contract"), required=True)
mirror.add_argument("--contract")
mirror.add_argument("--frequency", choices=("60m",), required=True)
mirror.add_argument("--since", required=True)
mirror.add_argument("--through", required=True)
```

JSON header:

```python
{
    "schema_version": 1,
    "command": "research.main-force-mirror-v2",
    "status": "ok",
    "readonly": True,
    "research_only": True,
    "indicator_code": result.indicator_code,
    "indicator_version": result.indicator_version,
    "parameters_hash": result.parameters_hash,
    "research_protocol": result.research_protocol,
    "evaluation_classification": result.evaluation_classification,
    "prospective_oos_starts_after": result.prospective_oos_starts_after.isoformat(),
    "member_dataset_id": result.member_dataset_id,
    "member_coverage": _optional_decimal(result.member_coverage),
    "caution_events_per_1000_ready_bars": _optional_decimal(
        result.caution_events_per_1000_ready_bars
    ),
    "yearly": _cohort_payload(result.yearly),
    "by_product": _cohort_payload(result.by_product),
    "pooled": _cohort_payload(result.pooled),
    "top_bottom_spreads": _spread_payload(result.top_bottom_spreads),
    "sensitivity": _sensitivity_payload(result.sensitivity),
}
```

Remove V1 imports and routing from the CLI in this task; the underlying V1 service file remains until Task 9 active-reference deletion.

- [ ] **Step 5: Run Task 6 tests GREEN**

Run the Task 6 command. Expected: V2 CLI returns read-only JSON, V1 command is rejected, and horizon targets never cross a roll.

- [ ] **Step 6: Commit Task 6**

```bash
git add \
  services/quant-api/app/market_data/main_force_mirror_v2_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/test_research_cli.py
git commit -m "feat(research): add main force mirror v2 comparison cli"
```

---

### Task 7: Web DTOs, API normalization, and paged V2 state

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Create: `apps/quant-web/src/composables/useMainForceMirrorV2.ts`
- Create: `apps/quant-web/tests/mainForceMirrorV2.test.ts`

**Interfaces:**
- Consumes: backend `MainForceMirrorV2PageResponse`.
- Produces: `getMainForceMirrorV2Page()` and `useMainForceMirrorV2()` with `replace`, `loadMoreBefore`, `clear`, `points`, `loading`, `error`, `memberDataset`, and `canonicalEnd`.

- [ ] **Step 1: Write normalization, pagination and stale-generation tests**

```typescript
it('normalizes Decimal strings once at the V2 HTTP boundary', async () => {
  const payload = mirrorPage({ instant_pressure: '36.200000', member_strength: '2.100000' })
  const result = normalizeMainForceMirrorV2Page(payload)

  assert.equal(result.points[0].instant_pressure, 36.2)
  assert.equal(result.points[0].member_strength, 2.1)
})

it('drops an older identity response after replacement', async () => {
  const pending = deferred<MainForceMirrorV2PageResponse>()
  const mirror = useMainForceMirrorV2({ fetchPage: () => pending.promise })
  const oldRequest = mirror.replace(identity('jm'))
  mirror.clear()
  pending.resolve(mirrorPage())
  await oldRequest

  assert.deepEqual(mirror.points.value, [])
})

it('prepends a V2 page without duplicating bar_end', async () => {
  const mirror = pagedMirror(latestPage(), olderOverlappingPage())
  await mirror.replace(identity('jm'))
  await mirror.loadMoreBefore()

  assert.deepEqual(mirror.points.value.map((point) => point.bar_end), expectedTimes)
})
```

- [ ] **Step 2: Run Web state tests RED**

```bash
pnpm --dir apps/quant-web test
```

Expected: the new test import fails.

- [ ] **Step 3: Add exact TypeScript DTOs**

```typescript
export type MainForceMirrorV2State =
  | 'long_build' | 'short_build' | 'short_cover' | 'long_liquidation' | 'turnover'
export type MainForceMirrorV2Caution = 'long_chase_caution' | 'short_chase_caution'
export type MainForceMemberRelation =
  | 'strong_aligned' | 'aligned' | 'divergent' | 'neutral' | 'unavailable'

export interface MainForceMirrorV2Point {
  bar_end: string
  trading_day: string
  physical_contract: string
  pressure_ready: boolean
  pressure_state: MainForceMirrorV2State | null
  instant_pressure: number | null
  accumulated_ready: boolean
  accumulated_pressure: number | null
  caution_ready: boolean
  caution: MainForceMirrorV2Caution | null
  long_caution_score: number | null
  short_caution_score: number | null
  caution_reason_codes: string[]
  member_status: 'ready' | 'unavailable'
  member_trade_date: string | null
  member_direction: 'long' | 'short' | 'neutral' | null
  member_change_bias: number | null
  member_strength: number | null
  position_skew: number | null
  top5_volume_share: number | null
  relation_to_accumulated: MainForceMemberRelation
  relation_to_caution: MainForceMemberRelation
  unavailable_reason: string | null
}
```

Define request/response/page/member-dataset types with field names identical to the API.
Keep a separate `MainForceMirrorV2PageWireResponse` whose Decimal-backed numeric
fields are `string | null`, matching the existing Market HTTP convention. The
normalized `MainForceMirrorV2PageResponse` uses `number | null`; only
`normalizeMainForceMirrorV2Page()` crosses that boundary.

- [ ] **Step 4: Implement API normalization and composable generation protection**

```typescript
export function normalizeMainForceMirrorV2Page(
  payload: MainForceMirrorV2PageWireResponse,
): MainForceMirrorV2PageResponse {
  return {
    ...payload,
    points: payload.points.map(normalizeMainForceMirrorV2Point),
  }
}

export function getMainForceMirrorV2Page(params: MainForceMirrorV2PageRequest) {
  return request.get<never, MainForceMirrorV2PageResponse>(
    '/market/research/main-force-mirror',
    { params },
  ).then(normalizeMainForceMirrorV2Page)
}

export function useMainForceMirrorV2(dependencies: Dependencies = {}) {
  const points = ref<MainForceMirrorV2Point[]>([])
  const nextBefore = ref<string | null>(null)
  const hasMoreBefore = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0
  let identity: MainForceMirrorV2Identity | null = null

  async function replace(next: MainForceMirrorV2Identity): Promise<void> {
    const requestGeneration = ++generation
    identity = { ...next }
    points.value = []
    error.value = null
    loading.value = true
    try {
      const page = await fetchPage(toRequest(next))
      if (requestGeneration !== generation) return
      points.value = normalizePoints(page.points)
      nextBefore.value = page.page.next_before
      hasMoreBefore.value = page.page.has_more_before
    } catch {
      if (requestGeneration === generation) error.value = '主力照妖镜 V2 暂不可用'
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  return { points, nextBefore, hasMoreBefore, loading, error, replace, loadMoreBefore, clear }
}
```

`loadMoreBefore()` uses the V2 response cursor, merges by `bar_end`, and retains ascending order. `clear()` increments generation and clears points/member state immediately.

- [ ] **Step 5: Run Task 7 tests GREEN**

Run `pnpm --dir apps/quant-web test`. Expected: all Web unit tests pass and no formula import exists in the new composable.

- [ ] **Step 6: Commit Task 7**

```bash
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/composables/useMainForceMirrorV2.ts \
  apps/quant-web/tests/mainForceMirrorV2.test.ts
git commit -m "feat(web): add main force mirror v2 api state"
```

---

### Task 8: Two-tab V2 chart rendering and browser acceptance

**Files:**
- Create: `apps/quant-web/src/utils/mainForceMirrorV2Presentation.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/tests/mainForceMirrorV2.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`
- Create: `apps/quant-web/e2e/main-force-mirror-v2.spec.mjs`

**Interfaces:**
- Consumes: `MainForceMirrorV2Point[]`, member dataset state and V2 loading/error from Task 7.
- Produces: two tabs, histogram, EMA5 line, caution markers, member label, historical cutoff and timestamp-aligned hover details.

- [ ] **Step 1: Write pure presentation tests**

```typescript
it('projects instant bars, EMA5 line and caution labels without recomputing values', () => {
  const model = buildMainForceMirrorV2RenderModel([
    point({ bar_end: '2026-08-21T02:00:00Z', instant_pressure: 36.2, accumulated_pressure: 18.7 }),
    point({
      bar_end: '2026-08-21T03:00:00Z',
      caution: 'long_chase_caution',
      long_caution_score: 70,
      relation_to_caution: 'strong_aligned',
    }),
  ])

  assert.deepEqual(model.histogram[0].value, 36.2)
  assert.deepEqual(model.accumulated[0].value, 18.7)
  assert.equal(model.markers[0].text, '追多小心 70｜席位强同向')
})

it('keeps a caution marker when member data is unavailable', () => {
  const model = buildMainForceMirrorV2RenderModel([
    point({ caution: 'short_chase_caution', relation_to_caution: 'unavailable' }),
  ])

  assert.match(model.markers[0].text, /小心.*席位不可用/)
})

it('normalizes every legacy secondary-pane identity deterministically', () => {
  assert.equal(normalizeSecondaryPanelPreference('main_force_mirror_futures'), 'main_force_mirror_v2')
  assert.equal(normalizeSecondaryPanelPreference('main_force_mirror_v0'), 'macd')
  assert.equal(normalizeSecondaryPanelPreference('unknown'), 'macd')
})
```

- [ ] **Step 2: Run Web tests RED**

```bash
pnpm --dir apps/quant-web test
```

Expected: the presentation module import fails.

- [ ] **Step 3: Implement presentation-only mapping**

```typescript
const RELATION_LABELS: Record<MainForceMemberRelation, string> = {
  strong_aligned: '席位强同向',
  aligned: '席位同向',
  divergent: '席位背离',
  neutral: '席位中性',
  unavailable: '席位不可用',
}

export function buildMainForceMirrorV2RenderModel(
  points: MainForceMirrorV2Point[],
): MainForceMirrorV2RenderModel {
  return {
    histogram: points.flatMap(toInstantHistogram),
    accumulated: points.flatMap(toAccumulatedLine),
    markers: points.flatMap(toCautionMarker),
    latest: points.at(-1) ?? null,
    autoscale: { minValue: -105, maxValue: 105 },
  }
}
```

Color mapping is descriptive only: long build=up, short build=down, short cover=EMA accent, long liquidation=MACD DIF accent, turnover=muted.

- [ ] **Step 4: Move V2 loading ownership to the Market page**

In `chart.vue`:

```typescript
const selectedSecondaryPanel = ref<'macd' | 'main_force_mirror_v2'>('macd')
const mirror = useMainForceMirrorV2()

async function updateSecondaryPanel(value: 'macd' | 'main_force_mirror_v2') {
  selectedSecondaryPanel.value = value
  if (value === 'macd') {
    mirror.clear()
    return
  }
  await mirror.replace(currentIdentity())
}

async function loadEarlierBars() {
  await loadMoreBefore()
  if (selectedSecondaryPanel.value === 'main_force_mirror_v2') {
    await mirror.loadMoreBefore()
  }
}
```

Clear V2 immediately before every market identity replacement. After a successful Canonical replacement, refetch V2 only when its tab is selected. Live mutations never call a V2 computation or append V2 points.
Pass ownership into `KlineChart` explicitly:

```vue
<KlineChart
  :secondary-panel="selectedSecondaryPanel"
  :main-force-mirror-v2-points="mirror.points.value"
  :main-force-mirror-v2-loading="mirror.loading.value"
  :main-force-mirror-v2-error="mirror.error.value"
  :main-force-mirror-v2-canonical-end="mirror.canonicalEnd.value"
  @secondary-panel-change="updateSecondaryPanel"
/>
```

`KlineChart` has no duplicate local source of truth for the selected tab; its
tab click emits the requested id and the parent prop controls the rendered pane.

- [ ] **Step 5: Replace KlineChart V0/V1 render branches with V2 series**

Change the tab contract to:

```typescript
type SecondaryPanelId = 'macd' | 'main_force_mirror_v2'
const SECONDARY_PANEL_TABS = [
  { id: 'macd', label: 'MACD' },
  { id: 'main_force_mirror_v2', label: '主力照妖镜 V2' },
] as const
```

Implement `normalizeSecondaryPanelPreference(value: unknown)` with the approved
legacy mapping above. Apply it anywhere an existing selection is restored, but
do not introduce a new persistence mechanism if the current page has none.

Add one Histogram series and one Line series in pane 2. The component receives V2 points as props, renders only the presentation model, emits `secondary-panel-change`, and never imports a mirror formula.

Unsupported identity remains selectable and displays `MFM_V2_UNSUPPORTED_FREQUENCY` or `MFM_V2_UNSUPPORTED_SERIES_KIND`. It does not silently select MACD. When Live bars extend beyond the last V2 `bar_end`, leave the V2 pane empty to the right and show `历史确认截至 <bar_end>`.

- [ ] **Step 6: Replace hover details with V2 fields**

```typescript
export interface MainForceMirrorV2HoverDetails {
  physicalContract: string
  state: MainForceMirrorV2State | null
  instantPressure: number | null
  accumulatedPressure: number | null
  caution: MainForceMirrorV2Caution | null
  longScore: number | null
  shortScore: number | null
  memberStatus: 'ready' | 'unavailable'
  memberTradeDate: string | null
  memberDirection: 'long' | 'short' | 'neutral' | null
  memberChangeBias: number | null
  memberStrength: number | null
  positionSkew: number | null
  top5VolumeShare: number | null
  relationToAccumulated: MainForceMemberRelation
  relationToCaution: MainForceMemberRelation
  unavailableReason: string | null
}
```

`resolveKlineHoverContext()` finds the server point by exact `bar_end`; missing points return `null` rather than a zero-filled object.

- [ ] **Step 7: Write browser acceptance with a mocked dedicated V2 route**

The Playwright test must assert:

```javascript
await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜 V2'])
await tabs.getByRole('tab', { name: '主力照妖镜 V2' }).click()
await expect.poll(() => mirrorRequests.length).toBe(1)
await expect(page.getByText('席位强同向')).toBeVisible()
await expect.poll(readCanvasText).toEqual(
  expect.arrayContaining(['追多小心 70｜席位强同向']),
)
await expect(page.getByText(/历史确认截至/)).toBeVisible()
```

Also assert MACD selection performs no V2 request, `continuous` shows explicit unavailable, T-1 date appears, and a member-unavailable caution remains rendered.
Update `alert-v1.spec.mjs` only where its shared Market-page setup or tab
expectations still name the retired panes; do not change Alert behavior.

- [ ] **Step 8: Run Web unit, build and focused E2E GREEN**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/main-force-mirror-v2.spec.mjs
```

Expected: all three commands exit 0.

- [ ] **Step 9: Commit Task 8**

```bash
git add \
  apps/quant-web/src/utils/mainForceMirrorV2Presentation.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/tests/mainForceMirrorV2.test.ts \
  apps/quant-web/e2e/alert-v1.spec.mjs \
  apps/quant-web/e2e/main-force-mirror-v2.spec.mjs
git commit -m "feat(web): render main force mirror v2"
```

---

### Task 9: Retire V0/V1, update canonicals, and run complete verification

**Files:**
- Delete every file listed in “Deleted in the retirement task”.
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`
- Modify: `services/quant-api/tests/test_research_cli.py`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/composables/useMarketSeries.ts`
- Modify: `apps/quant-web/tests/marketSeries.test.ts`
- Modify active references in: `STATUS.md`, `PROJECT_SOURCE.md`, `README.md`, `TESTING.md`, `docs/ARCHITECTURE.md`, `docs/INDICATOR_KERNEL.md`
- Preserve: `CHANGELOG.md`

**Interfaces:**
- Consumes: all green V2 replacement tests from Tasks 1–8.
- Produces: one active Main Force Mirror implementation and zero V0/V1 execution references.

- [ ] **Step 1: Add an active-reference test that fails while V0/V1 remain**

Extend `tests/engineering/test_canonical_consistency.py` with explicit active paths/tokens:

```python
RETIRED_MAIN_FORCE_ACTIVE_TOKENS = (
    "main_force_mirror_v0",
    "main_force_mirror_futures_v1",
    "main-force-mirror-futures",
    "main_force_mirror_futures.py",
    "main_force_mirror.py",
    "mainForceMirrorFutures",
    "mainForceMirror.ts",
    "原型V0",
)

RETIRED_MAIN_FORCE_SCAN_EXCLUDES = {
    "CHANGELOG.md",
    "docs/superpowers/specs/2026-08-21-main-force-mirror-v2-design.md",
    "docs/superpowers/plans/2026-08-21-main-force-mirror-v2.md",
    "tests/engineering/test_canonical_consistency.py",
}

def _retired_main_force_active_hits() -> list[str]:
    tracked = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    hits: list[str] = []
    for relative in tracked:
        if not relative or relative in RETIRED_MAIN_FORCE_SCAN_EXCLUDES:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in RETIRED_MAIN_FORCE_ACTIVE_TOKENS:
            if token in relative or token in text:
                hits.append(f"{relative}: {token}")
    return sorted(set(hits))

def test_retired_main_force_implementations_have_no_active_references():
    assert _retired_main_force_active_hits() == []
```

- [ ] **Step 2: Run the active-reference test RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
```

Expected: failure lists current V0/V1 source, tests, Registry/Policy, CLI, Web and active documentation references.

- [ ] **Step 3: Delete the old implementation and replace remaining generic identity codes**

Use `git rm` for the exact tracked files in the deletion list. Remove V0/V1 imports and Registry/Policy entries. Rename the generic Web series identity error from `MFM_FUTURES_V1_SEGMENT_CONFLICT` to `MARKET_SERIES_SEGMENT_CONFLICT` because it belongs to the market page mapper, not V2.

```bash
git rm \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror.py \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror.pyi \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py \
  services/quant-api/app/market_data/main_force_mirror_futures_research_service.py \
  apps/quant-web/src/utils/mainForceMirror.ts \
  apps/quant-web/src/utils/mainForceMirrorFutures.ts \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  apps/quant-web/tests/mainForceMirror.test.ts \
  apps/quant-web/tests/mainForceMirrorFutures.test.ts \
  apps/quant-web/e2e/main-force-mirror.spec.mjs \
  apps/quant-web/e2e/main-force-mirror-futures.spec.mjs \
  tests/fixtures/main_force_mirror_futures_v1_golden.json
```

Replace the current engineering assertions that freeze the V0 source hash and
require the V1 research service with V2 identity/capability assertions. The
retirement test must not keep either deleted path alive merely to inspect it.

Do not add wrappers, aliases, hidden tabs, compatibility routes, duplicate fixtures or backup files.

- [ ] **Step 4: Update active canonicals and commands**

Document these exact current facts:

```text
Main Force Mirror active identity = main_force_mirror_v2
surface = 60m contract|actual_dominant historical observation only
member source = pinned immutable main_force_member_rank_v1 snapshot
Web bottom tabs = MACD | 主力照妖镜 V2
V0/V1 = retired; Git history only
real member snapshot = external gate pending unless separately executed
live/alert/notification/auto_order = false
```

Update `TESTING.md` with the V2 focused commands from this plan. Do not remove historical V0/V1 entries from `CHANGELOG.md`.

- [ ] **Step 5: Run focused Python replacement suites**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_v2.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot.py \
  services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_v2_research_service.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_research_cli.py \
  tests/engineering/test_canonical_consistency.py
```

Expected: all selected tests pass and no deleted module is imported.

- [ ] **Step 6: Run complete API and engineering suites**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q tests/engineering
```

Expected: both commands exit 0.

- [ ] **Step 7: Run complete Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
```

Expected: unit, build and full browser suite all exit 0.

- [ ] **Step 8: Run final repository checks**

```bash
rg -n \
  'main_force_mirror_v0|main_force_mirror_futures_v1|main-force-mirror-futures|mainForceMirrorFutures|原型V0' \
  --glob '!CHANGELOG.md' \
  --glob '!docs/superpowers/specs/2026-08-21-main-force-mirror-v2-design.md' \
  --glob '!docs/superpowers/plans/2026-08-21-main-force-mirror-v2.md' \
  --glob '!.git/**' \
  .
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: `rg` returns no active hit, secret scan reports zero findings, `git diff --check` has no output, and status lists only Task 9 files.

- [ ] **Step 9: Commit Task 9**

```bash
git add \
  STATUS.md PROJECT_SOURCE.md README.md TESTING.md docs/ARCHITECTURE.md docs/INDICATOR_KERNEL.md \
  packages/quant-core/guiyi_quant/indicators/__init__.py \
  packages/quant-core/guiyi_quant/indicators/registry.py \
  packages/quant-core/guiyi_quant/indicators/policy.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/guiyi_cli/research_parser.py \
  services/quant-api/app/guiyi_cli/research_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_research_cli.py \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/composables/useMarketSeries.ts \
  apps/quant-web/tests/marketSeries.test.ts \
  tests/engineering/test_canonical_consistency.py
git diff --cached --name-status
git commit -m "refactor: retire legacy main force mirrors"
```

The exact `git rm` commands from Step 3 already stage only the named retired
files. Before committing, compare `git diff --cached --name-status` with the
Task 9 file map; unstage and preserve any unrelated path.

- [ ] **Step 10: Record the exact completion boundary**

Report:

```text
CODE_COMPLETE
tests = exact fresh command results
real RQData snapshot = NOT EXECUTED
real retrospective matrix = NOT EXECUTED
develop Runtime reload = NOT EXECUTED
release/tag/Runtime promotion = NOT AUTHORIZED
```

The only next external step is a new, exact authorization for one real `guiyi data member-rank snapshot ... --apply` attempt. Do not infer that authorization from green code, this plan, the approved design, or prior probes.
