# SuBing Daily Watch Cross-Roll V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SuBing Daily Watch 的 D1/60m EMA21 warm-up 从“当前 rank1 segment 内”升级为“截至来源交易日的最近 30 根 raw rank1 stitched actual-dominant Bars”，同时以严格 V2 contract、独立 `v2/` artifact namespace 和 fail-closed Web normalizer 冻结 V1 历史语义。

**Architecture:** 在 `MarketDataService` 增加精确交易日截止的 recent-bars 只读入口，复用既有 actual-dominant page resolver 对 MainContractMap、Catalog 与物理分区的校验；新增 Daily Watch 专用 stitched loader 与 V2 EMA trend 纯函数，不改变 V1 segment-local loader/公式及其他 SuBing consumer；Store、API、Web 同步升级为单一 active V2 contract，V1 文件保持原字节且不回退。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Pydantic、pytest、ruff、mypy、Vue 3、TypeScript、Node test、vue-tsc、Vite。

**Spec:** `docs/superpowers/specs/2026-08-26-subing-daily-watch-cross-roll-v2-design.md`

## Global Constraints

- [ ] 每个任务先新增或修改测试并观察预期失败，再写最小实现使其通过；不得先改生产代码。
- [ ] V1 `ActualDominantResearchSegmentLoader`、`calculate_subing_ema_trend()` 和既有 segment-local consumer 行为不变。
- [ ] V2 只能读取 `trading_day <= source_trading_day` 的 confirmed Canonical actual-dominant Bars；不得使用 continuous、Live preview、当前合约非 rank1 历史或任何复权/平滑。
- [ ] V2 固定身份：`schema_version=2`、`projection_version=subing_daily_watch_v2`、`formula_version=subing_ema21_rank1_stitched_raw_v2`、`history_mode=rank1_stitched_raw`。
- [ ] V2 Store 根固定为已校验 base root 下的 `v2/`；不得移动、改写、删除或回退读取 base root 中的 V1 文件。
- [ ] 不改 PostgreSQL schema，不写 Canonical，不启用 Runtime，不发送通知，不修改 Scope，不做 release/tag/main merge。
- [ ] 当前 worktree 有用户的 N-structure 等未提交改动。每次编辑前重新读取目标文件；只 stage 本任务明确文件；严禁 `git add -A`、批量 restore、clean 或覆盖用户 index。
- [ ] `apps/quant-web/src/types/market.ts`、`PROJECT_SOURCE.md`、`STATUS.md` 已有用户修改，必须以最小 hunk 叠加；若同一区域冲突，停止该文件的修改并报告，不猜测覆盖。
- [ ] 每个 commit 前运行 `git diff --check -- <task files>`、`git diff --cached --name-only`，确认 index 只含当步文件。

---

## Task 1: Add the exact-through recent actual-dominant query contract

**Files:**

- Modify: `services/quant-api/app/market_data/domain.py`
- Modify: `services/quant-api/app/market_data/market_data_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_domain.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_pagination.py`

### 1.1 RED: specify request validation

- [ ] Add domain tests for normalization and strict validation:

```python
def test_actual_dominant_recent_bars_query_normalizes_identity() -> None:
    query = ActualDominantRecentBarsQuery(
        symbol="RB",
        frequency="1d",
        through=date(2026, 8, 25),
        limit=30,
    )
    assert query.symbol == "rb"
    assert query.frequency is BarFrequency.D1
    assert query.through == date(2026, 8, 25)
    assert query.limit == 30


@pytest.mark.parametrize("limit", [True, 0, -1, 2001, 1.5])
def test_actual_dominant_recent_bars_query_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ContractError):
        ActualDominantRecentBarsQuery("rb", BarFrequency.D1, date(2026, 8, 25), limit)  # type: ignore[arg-type]
```

- [ ] Cover invalid symbol, unsupported frequency value and `datetime` passed as `through`.
- [ ] Run and confirm failure because the class does not yet exist:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_domain.py \
  -k actual_dominant_recent_bars
```

Expected: collection/import failure naming `ActualDominantRecentBarsQuery`.

### 1.2 GREEN: implement the immutable request

- [ ] Add the following value object beside `ActualDominantTradingDayQuery`:

```python
@dataclass(frozen=True, slots=True)
class ActualDominantRecentBarsQuery:
    symbol: str
    frequency: BarFrequency
    through: date
    limit: int

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, field="symbol")
        if _SYMBOL.fullmatch(symbol.upper()) is None:
            raise ContractError(field="symbol", reason="invalid", value=symbol)
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        if type(self.through) is not date:
            raise ContractError(field="through", reason="date_required")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 2000
        ):
            raise ContractError(field="limit", reason="out_of_range", value=self.limit)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)
```

- [ ] Re-run the focused domain tests and confirm pass.

### 1.3 RED: specify source-day cutoff and page delegation

- [ ] In pagination tests, build a service fixture whose `_trading_day_window(rb, through, through)` ends at the source-day final Session instant and whose page contains multiple rank1 segments.
- [ ] Assert the new method:
  - requests `SeriesKind.ACTUAL_DOMINANT`;
  - uses `before == session_end + timedelta(microseconds=1)`;
  - returns at most `limit` Bars in strict chronological order;
  - includes a final Bar with `trading_day == through`;
  - retains raw closes and resolved contract segments across rollover;
  - rejects empty results, a latest Bar before `through`, any future trading day, or non-increasing `bar_end` with `MarketDataError("ACTUAL_DOMINANT_RECENT_BARS_INVALID")`.
- [ ] Add a regression fixture where a later natural timestamp belongs to the next trading day and prove it is excluded by the source-day Session cutoff.
- [ ] Run and confirm failure because the service method does not exist:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_pagination.py \
  -k actual_dominant_recent_bars
```

### 1.4 GREEN: implement recent-bars through the canonical page resolver

- [ ] Import the new request and add:

```python
def query_actual_dominant_recent_bars(
    self,
    request: ActualDominantRecentBarsQuery,
) -> MarketSeriesPageResult:
    _, session_end = self._trading_day_window(
        symbol=request.symbol,
        since=request.through,
        through=request.through,
    )
    result = self.query_page(
        SeriesPageQuery(
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            symbol=request.symbol,
            frequency=request.frequency,
            before=session_end + timedelta(microseconds=1),
            limit=request.limit,
        )
    )
    bars = result.bars
    if (
        not bars
        or bars[-1].trading_day != request.through
        or any(bar.trading_day > request.through for bar in bars)
        or any(
            current.bar_end <= previous.bar_end
            for previous, current in zip(bars, bars[1:], strict=False)
        )
    ):
        raise MarketDataError("ACTUAL_DOMINANT_RECENT_BARS_INVALID")
    return result
```

- [ ] Do not reimplement map/partition ownership checks; `query_page()` remains the authority.
- [ ] Run domain and pagination focused tests; then run the entire two files.

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_domain.py \
  services/quant-api/tests/data_foundation/test_market_pagination.py
```

### 1.5 Commit Task 1

- [ ] Inspect and stage only the four Task 1 files.
- [ ] Commit:

```bash
git commit -m "feat(data): add recent actual-dominant query"
```

---

## Task 2: Add the stitched Daily Watch loader and V2 EMA lineage

**Files:**

- Modify: `services/quant-api/app/market_data/actual_dominant_research.py`
- Modify: `services/quant-api/app/market_data/subing_ema_trend.py`
- Modify: `services/quant-api/tests/data_foundation/test_actual_dominant_research.py`
- Modify: `services/quant-api/tests/test_subing_ema_trend.py`

### 2.1 RED: specify stitched loader identity

- [ ] Extend the research reader fake with both methods:

```python
def query_actual_dominant_recent_bars(
    self,
    request: ActualDominantRecentBarsQuery,
) -> MarketSeriesPageResult: ...

def dominant_segment_for_day(
    self,
    symbol: str,
    trading_day: date,
) -> DominantContractSegmentSummary: ...
```

- [ ] Add tests proving `ActualDominantStitchedResearchLoader.load()`:
  - rejects an empty frequency list;
  - requests exactly 30 D1 and 30 H1 Bars through the same source day;
  - accepts D1 and H1 results with different historical segment tuples;
  - requires both last Bars on the source day;
  - requires both last Bars to be owned by the same current contract;
  - requires that contract and source day to match `dominant_segment_for_day()`;
  - preserves each page result without reconstructing physical data.
- [ ] Include one valid fixture where D1 covers two segments while H1 covers only the current segment.
- [ ] Run and confirm import/attribute failure:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  -k stitched
```

### 2.2 GREEN: implement a separate recent-history loader

- [ ] Extend the reader Protocol with `query_actual_dominant_recent_bars()`; do not change `ActualDominantResearchSegmentLoader.load()`.
- [ ] Add:

```python
@dataclass(frozen=True, slots=True)
class ActualDominantStitchedResearchSeries:
    results: Mapping[BarFrequency, MarketSeriesPageResult]
    current_segment: ResolvedContractSegment


class ActualDominantStitchedResearchLoader:
    def __init__(self, market_data: ActualDominantResearchReader) -> None:
        self._market_data = market_data

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        through: date,
        limit: int = 30,
    ) -> ActualDominantStitchedResearchSeries:
        requested = tuple(frequencies)
        if not requested:
            raise ActualDominantResearchSegmentIdentityError(
                "rank1 stitched identity is missing or inconsistent"
            )
        results = {
            frequency: self._market_data.query_actual_dominant_recent_bars(
                ActualDominantRecentBarsQuery(symbol, frequency, through, limit)
            )
            for frequency in requested
        }
        summary = self._market_data.dominant_segment_for_day(symbol, through)
        current_segment = ResolvedContractSegment(
            summary.contract,
            summary.start_trading_day,
            summary.end_trading_day,
        )
        _validate_stitched_current_identity(
            symbol=symbol,
            through=through,
            results=results,
            current_segment=current_segment,
        )
        return ActualDominantStitchedResearchSeries(
            MappingProxyType(results),
            current_segment,
        )
```

- [ ] Implement `_validate_stitched_current_identity()` using each result's Bars and `resolved_contract_segments`; it must identify the segment containing each final Bar and compare its owner with `current_segment.contract`. It must not require complete D1/H1 historical segment tuple equality.
- [ ] Run stitched loader tests and all existing V1 loader tests.

### 2.3 RED: specify raw cross-roll EMA parity and lineage

- [ ] Add V2 tests with 30 strictly increasing Bars:
  - first 20 belong to `RB2605`, last 10 to `RB2610`;
  - close jumps visibly at the rollover, for example `3100..3119` then `3500..3509`;
  - `current_segment_start_trading_day` is the first `RB2610` trading day;
  - expected EMA21 and slopes come from `ema_series(raw_closes, 21, seed_policy="sma_window")`, not manually smoothed closes.
- [ ] Assert 29 Bars are insufficient and 30 are ready.
- [ ] Assert ready snapshot lineage exactly includes:

```python
assert snapshot.contract == "RB2610"
assert snapshot.current_segment_start_trading_day == date(2026, 8, 12)
assert snapshot.warmup_start_trading_day == bars[0].trading_day
assert snapshot.warmup_bar_count == 30
assert snapshot.warmup_segment_count == 2
assert snapshot.history_mode == "rank1_stitched_raw"
```

- [ ] Prove V1 still rejects any Bar before `segment_start_trading_day`.
- [ ] Run and confirm failure because the stitched function/fields do not exist:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  -k "stitched or segment_local"
```

### 2.4 GREEN: add an explicit V2 snapshot type and pure function

- [ ] Preserve `SubingEmaTrendSnapshot` for V1. Add a distinct V2 snapshot so V1 fields cannot be silently reinterpreted:

```python
@dataclass(frozen=True, slots=True)
class SubingStitchedEmaTrendSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    current_segment_start_trading_day: date
    warmup_start_trading_day: date
    warmup_bar_count: int
    warmup_segment_count: int
    history_mode: Literal["rank1_stitched_raw"]
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
```

- [ ] Add a matching `SubingStitchedEmaTrendResult` and an independent entrypoint:

```python
def calculate_subing_ema_trend_stitched(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    current_contract: str,
    current_segment_start_trading_day: date,
    resolved_contract_segments: Sequence[ResolvedContractSegment],
) -> SubingStitchedEmaTrendResult:
```

- [ ] Validate: nonempty contract, strict `bar_end`, every input Bar covered exactly once by a resolved segment, current segment contains the latest trading day, and the latest owner equals current contract.
- [ ] Calculate from the raw close sequence with the same EMA21 seed and regression helpers as V1. Refactor only a small private helper if needed; do not add a generalized indicator framework.
- [ ] Set `warmup_bar_count=len(bars)` for a ready result (Daily Watch passes exactly 30), `warmup_segment_count` to the number of distinct resolved segments intersecting the input window, and `warmup_start_trading_day=bars[0].trading_day`.
- [ ] Run both Task 2 test files in full:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/test_subing_ema_trend.py
```

### 2.5 Commit Task 2

- [ ] Stage only the four Task 2 files and commit:

```bash
git commit -m "feat(subing): add stitched EMA trend kernel"
```

---

## Task 3: Switch only Daily Watch generation to stitched V2 history

**Files:**

- Modify: `services/quant-api/app/market_data/subing_daily_watch.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_daily_watch.py`
- Modify: `services/quant-api/tests/data_foundation/test_composition.py`

### 3.1 RED: specify builder behavior at rollover

- [ ] Replace only the Daily Watch test fake's loader contract with:

```python
class _StitchedLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        through: date,
        limit: int = 30,
    ) -> ActualDominantStitchedResearchSeries: ...
```

- [ ] Add a product fixture whose current segment has fewer than 30 D1 Bars but whose stitched result has 30. Assert it becomes a normal `long_watch`, `short_watch`, or `excluded` item rather than `D1_HISTORY_INSUFFICIENT`.
- [ ] Add 29-Bar D1 and H1 cases that keep the exact existing typed reasons.
- [ ] Add source-day missing, current owner mismatch and map identity mismatch cases; assert existing public reason mapping remains `SOURCE_TRADING_DAY_MISSING`, `DATA_IDENTITY_MISMATCH`, or `DOMINANT_SEGMENT_UNAVAILABLE` without internal details.
- [ ] Assert the builder always calls both frequencies with `limit=30` and never supplies V1's `since` argument.
- [ ] Run and confirm failure against the V1 builder:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  -k "stitched or rollover or insufficient"
```

### 3.2 GREEN: update Daily Watch's internal types and builder only

- [ ] Change `SubingDailyWatchItem.daily/hourly` to the V2 snapshot type; classification still consumes the shared price/slope attributes.
- [ ] Change `_validate_loaded_identity()` to accept `ActualDominantStitchedResearchSeries` and return `(current_segment, daily_page, hourly_page)` after checking:
  - both page results exist;
  - both final Bars equal source day;
  - every Bar is `<= source_trading_day`;
  - each result's final containing segment equals `loaded.current_segment`.
- [ ] In `_build_item()` call the stitched loader and V2 formula:

```python
loaded = self._stitched_loader.load(
    symbol=symbol,
    frequencies=(BarFrequency.D1, BarFrequency.H1),
    through=source_trading_day,
    limit=30,
)

daily = calculate_subing_ema_trend_stitched(
    daily_result.bars,
    timeframe=BarFrequency.D1,
    current_contract=current_segment.contract,
    current_segment_start_trading_day=current_segment.start_trading_day,
    resolved_contract_segments=daily_result.resolved_contract_segments,
)
```

- [ ] Use the same call for H1. Keep `_history_unavailable_reasons()` and classification reason codes unchanged.
- [ ] Do not modify historical replay, Alert, Lifecycle, Factor or `build_subing_historical_signal_service()`.

### 3.3 RED/GREEN: composition selects stitched loader and `base/v2`

- [ ] Add composition tests proving:
  - generator receives `ActualDominantStitchedResearchLoader`;
  - `resolve_subing_observation_root()` still validates the configured base;
  - Store root is exactly `base / "v2"`;
  - root revalidation returns exactly the same `base / "v2"`, and a changed base fails closed;
  - current service also reads only `base / "v2"`.
- [ ] Observe tests fail with V1 loader/base root.
- [ ] Add a single helper to avoid root divergence:

```python
def _subing_daily_watch_v2_root() -> Path:
    return resolve_subing_observation_root(
        environ=os.environ,
        inspector=PathMountInspector(),
    ) / "v2"
```

- [ ] In the generator, capture `base_root`, pass `base_root / "v2"`, and make the validator recompute and compare `resolved_base / "v2"` through the Store's existing equality check. Do not add a new environment variable.
- [ ] In current service, build the Store from the same helper.
- [ ] Run both Task 3 files:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_composition.py
```

### 3.4 Commit Task 3

- [ ] Stage only Task 3 files and commit:

```bash
git commit -m "feat(subing): switch Daily Watch to stitched history"
```

---

## Task 4: Upgrade artifact, API and parser to a strict V2 contract

**Files:**

- Modify: `services/quant-api/app/market_data/subing_daily_watch_store.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py`
- Modify: `services/quant-api/tests/test_subing_daily_watch_api.py`

### 4.1 RED: pin V2 canonical bytes and V1 isolation

- [ ] Update store fixtures to the V2 trend type and assert canonical JSON includes:

```json
{
  "schema_version": 2,
  "projection_version": "subing_daily_watch_v2",
  "formula_version": "subing_ema21_rank1_stitched_raw_v2",
  "history_mode": "rank1_stitched_raw"
}
```

- [ ] Assert each non-null trend uses `current_segment_start_trading_day`, `warmup_start_trading_day`, `warmup_bar_count`, `warmup_segment_count`, `history_mode`; assert `segment_start_trading_day` is absent.
- [ ] Add a fixture with V1 `current.json` in the base root and no `v2/current.json`; construct the V2 Store at `base/v2` and assert `read_current()` returns `None` without modifying any V1 bytes.
- [ ] Add rejection tests for schema 1, V1 projection, V1 formula, wrong history mode, missing lineage, `warmup_bar_count != 30` on ready trend, or invalid segment count.
- [ ] Keep idempotency, identity conflict, current regression, atomic write and generation-status tests.
- [ ] Run and confirm V1 constants/payload fail:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
```

### 4.2 GREEN: make the Store/parser V2-only

- [ ] Replace active constants:

```python
_SCHEMA_VERSION = 2
_PROJECTION_VERSION = "subing_daily_watch_v2"
_FORMULA_VERSION = "subing_ema21_rank1_stitched_raw_v2"
_HISTORY_MODE = "rank1_stitched_raw"
```

- [ ] Add top-level `history_mode` to snapshots and generation status where projection identity is present.
- [ ] Serialize and parse V2 trend lineage only. Parser must require exact key sets and exact identity constants; do not keep a V1 parser branch.
- [ ] Validate ready trend `warmup_bar_count == 30`, `1 <= warmup_segment_count <= warmup_bar_count`, `warmup_start_trading_day <= trading_day`, and `current_segment_start_trading_day <= trading_day`.
- [ ] Preserve existing mount, symlink, atomic replace, conflict and generation-status behavior.
- [ ] Run the store test file in full.

### 4.3 RED: specify API V2 projection and typed unavailability

- [ ] Update API tests to assert ready responses expose exact top-level identity:

```python
assert body["projection_version"] == "subing_daily_watch_v2"
assert body["formula_version"] == "subing_ema21_rank1_stitched_raw_v2"
assert body["history_mode"] == "rank1_stitched_raw"
```

- [ ] Assert trend payloads expose all V2 lineage fields and Decimal fields remain strings.
- [ ] Assert a missing V2 current returns the existing typed unavailable shape and never reads V1.
- [ ] Assert mixed V1/V2 domain objects cannot be projected as ready.
- [ ] Run and confirm schema/output failures:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_daily_watch_api.py
```

### 4.4 GREEN: expose exact identity in Pydantic and API mapping

- [ ] Add Literal types to the current response/snapshot schema rather than unconstrained strings:

```python
projection_version: Literal["subing_daily_watch_v2"]
formula_version: Literal["subing_ema21_rank1_stitched_raw_v2"]
history_mode: Literal["rank1_stitched_raw"]
```

- [ ] Replace trend field `segment_start_trading_day` with:

```python
current_segment_start_trading_day: date
warmup_start_trading_day: date
warmup_bar_count: int
warmup_segment_count: int
history_mode: Literal["rank1_stitched_raw"]
```

- [ ] Map constants explicitly in `_subing_daily_watch_snapshot()` and map V2 lineage in `_subing_daily_watch_trend()`. Keep endpoint path unchanged.
- [ ] Run API and store tests together:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py \
  services/quant-api/tests/test_subing_daily_watch_api.py
```

### 4.5 Commit Task 4

- [ ] Stage only the five Task 4 files and commit:

```bash
git commit -m "feat(subing): version Daily Watch artifacts as v2"
```

---

## Task 5: Make the Web wire boundary reject V1 and mixed payloads

**Files:**

- Modify carefully: `apps/quant-web/src/types/market.ts` (pre-existing user changes)
- Modify: `apps/quant-web/tests/subingDailyWatch.test.ts`
- Modify only if fixture compilation requires it: `apps/quant-web/tests/subingWorkbench.test.ts`

### 5.1 Protect the dirty target before editing

- [ ] Capture `git diff -- apps/quant-web/src/types/market.ts` and save the output only in the terminal/session, not a repository file.
- [ ] Re-read the Daily Watch interfaces and normalizer immediately before patching.
- [ ] Ensure the task patch does not touch unrelated N-structure or Market type regions.

### 5.2 RED: specify strict version and lineage normalization

- [ ] Update `readyPayload()` with exact V2 top-level identity and trend lineage.
- [ ] Add explicit rejection tests for:
  - V1 projection;
  - V1 formula;
  - missing or wrong top-level history mode;
  - trend-level history mode mismatch;
  - missing `warmup_start_trading_day`;
  - `warmup_bar_count != 30`;
  - invalid `warmup_segment_count`;
  - legacy-only `segment_start_trading_day`.
- [ ] Assert accepted normalization preserves V2 identity and lineage while converting only Decimal strings to finite numbers.
- [ ] Run and confirm the current V1-shaped interfaces/normalizer fail:

```bash
pnpm --dir apps/quant-web test -- subingDailyWatch.test.ts
```

### 5.3 GREEN: update wire/runtime types and guards

- [ ] Add literal identities:

```typescript
export type SubingDailyWatchProjectionVersion = 'subing_daily_watch_v2'
export type SubingDailyWatchFormulaVersion = 'subing_ema21_rank1_stitched_raw_v2'
export type SubingDailyWatchHistoryMode = 'rank1_stitched_raw'
```

- [ ] Make both snapshot/current wire and normalized shapes carry these identities.
- [ ] Replace the trend lineage interface with:

```typescript
current_segment_start_trading_day: string
warmup_start_trading_day: string
warmup_bar_count: number
warmup_segment_count: number
history_mode: SubingDailyWatchHistoryMode
```

- [ ] In `normalizeSubingDailyWatchCurrent()`, require exact top-level constants before any ready projection is accepted.
- [ ] In `isSubingDailyWatchTrendWire()`, require exact history mode, valid dates, `warmup_bar_count === 30`, integer segment count `>=1 && <=30`, and both segment/warm-up starts no later than the trend trading day.
- [ ] Preserve typed unavailable responses, existing count checks, ordering, reason-label behavior and no-recommendation wording.
- [ ] If `subingWorkbench.test.ts` has typed fixtures, update only their Daily Watch payload fields.
- [ ] Run focused Web tests:

```bash
pnpm --dir apps/quant-web test -- \
  subingDailyWatch.test.ts \
  subingWorkbench.test.ts
```

### 5.4 Verify the dirty-file merge and commit Task 5

- [ ] Compare `git diff -- apps/quant-web/src/types/market.ts` with the pre-edit diff and verify unrelated user hunks are unchanged.
- [ ] Stage with exact paths only. Inspect `git diff --cached -- apps/quant-web/src/types/market.ts` and confirm both pre-existing user changes are not accidentally staged unless already staged by the user; if index state cannot be separated safely, stop and report instead of committing.
- [ ] Commit:

```bash
git commit -m "feat(web): enforce Daily Watch v2 wire contract"
```

---

## Task 6: Update canonical docs and run real read-only acceptance

**Files:**

- Modify: `docs/DATA_CENTER.md`
- Modify carefully: `PROJECT_SOURCE.md` (pre-existing user changes)
- Modify carefully after all tests: `STATUS.md` (pre-existing user changes)
- Optional new test helper only if no existing composition entry can emit the required evidence: `services/quant-api/tests/data_foundation/test_subing_daily_watch_real_smoke.py`

### 6.1 Document the accepted semantic change

- [ ] Update `docs/DATA_CENTER.md` Daily Watch section with:
  - raw rank1 stitched actual-dominant last 30 confirmed Bars;
  - no adjustment and no rollover reset;
  - V2 identities and `base/v2` namespace;
  - exact remaining unavailable meaning;
  - V1 bytes untouched/no fallback.
- [ ] Patch only the relevant SuBing Daily Watch paragraphs in `PROJECT_SOURCE.md`; do not alter the user's unrelated current edits.
- [ ] Do not mark `STATUS.md` complete until all automated tests and read-only smoke pass. Then add only verified code/test facts and keep Runtime/release/natural V2 artifact as pending.

### 6.2 Run the complete focused backend suite

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py \
  services/quant-api/tests/test_subing_daily_watch_api.py
```

- [ ] Run all data-foundation regressions:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation
```

- [ ] Run static checks:

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app \
  services/quant-api/tests

uv run --project services/quant-api mypy services/quant-api/app
```

### 6.3 Run the complete Web verification

- [ ] Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec vue-tsc --noEmit
pnpm --dir apps/quant-web build
```

- [ ] If the API fixture shape is used by Market E2E, update only the Daily Watch fixture contract and run the relevant local Playwright spec. Do not edit or stage the user's unrelated `market-research.spec.mjs` hunks without first separating ownership.

### 6.4 Perform the production-data read-only smoke without publication

- [ ] Use the existing production env only to construct the read path; do not call `SubingDailyWatchGenerator.run()`, Store `publish()`, HistoricalDataManager update, RQData, DB writes, Redis writes or notification transports.
- [ ] Invoke `SubingDailyWatchBuilder.build()` directly for the latest complete common source trading day using `ActualDominantStitchedResearchLoader(build_market_data_service(session))` and active60 metadata.
- [ ] Emit only non-sensitive aggregate evidence:

```text
source_trading_day
universe
long_watch
short_watch
excluded
unavailable
unavailable reason counts
D1 warmup_bar_count distribution
H1 warmup_bar_count distribution
warmup_segment_count distribution
```

- [ ] Acceptance checks:
  - universe remains exactly 60;
  - no item becomes ready from fewer than 30 Bars;
  - each ready item ends on the source trading day and uses its source-day rank1 contract;
  - the prior 56 `D1_HISTORY_INSUFFICIENT` cases caused only by current-segment reset disappear;
  - any residual unavailable item has an explicit data/history/identity fact.
- [ ] If the 56 do not disappear, stop and diagnose; do not weaken validation, publish an artifact or relabel the result as complete.

### 6.5 Final diff, regression review and documentation commit

- [ ] Run:

```bash
git diff --check
git status --short
git diff --stat
```

- [ ] Inspect all task-owned diffs for:
  - accidental V1 consumer changes;
  - any continuous/current-contract fallback;
  - future Bar leakage;
  - implicit data/DB/Runtime writes;
  - mixed V1/V2 parser acceptance;
  - unrelated dirty-file changes.
- [ ] Stage only `docs/DATA_CENTER.md`, the exact task-owned hunks of `PROJECT_SOURCE.md` and `STATUS.md`, plus an optional task-owned smoke test file.
- [ ] Commit:

```bash
git commit -m "docs(subing): record Daily Watch cross-roll v2"
```

---

## Task 7: Completion gate and develop integration

**Files:** All task-owned files from Tasks 1–6; no new code changes unless verification exposes a defect.

### 7.1 Verify commit and worktree ownership

- [ ] Confirm every task commit is based on current `develop` and no unrelated user file was staged or committed.
- [ ] Re-run any test affected by a verification fix; do not rely on an earlier green result after code changes.
- [ ] Record exact commands, exit status, pass counts and the read-only smoke aggregates for handoff.

### 7.2 Independent review before integration

- [ ] Review the final diff against every numbered requirement in the approved Spec.
- [ ] Specifically verify:
  - V1 artifact bytes and consumer semantics are untouched;
  - V2 Store has one active parser and no V1 fallback;
  - D1/H1 may span different historical segment tuples but share current owner;
  - raw rollover gap enters EMA21/slope unchanged;
  - Web refuses mixed-version payloads;
  - no Runtime, live, data, DB, Scope or notification mutation exists.
- [ ] Resolve only findings within the approved Spec, with focused RED/GREEN tests.

### 7.3 Commit/push boundary

- [ ] If all required checks pass and dirty-file ownership is separable, commit any final review fix with an exact pathspec and push ordinary `develop` according to repository workflow.
- [ ] A successful develop push may be reported as `CODE_COMPLETE` / `TEST_COMPLETE`; it must not be called released, deployed or Runtime-ready.
- [ ] Do not create main PR/tag/release or switch local production Runtime. Those remain separate explicit external Gates.

## Final Acceptance Checklist

- [ ] Daily Watch requests exactly 30 raw actual-dominant D1 and H1 Bars through the source trading day.
- [ ] Recent-bar reads are resolved by MarketDataService and fail closed on map/Catalog/physical identity errors.
- [ ] EMA21/slope continues through rank1 rollover with no adjustment/reset and exact raw-close parity.
- [ ] 29 Bars remain insufficient; 30 Bars are ready.
- [ ] Current owner, current segment, warm-up start/count/segment count and history mode are fully traceable.
- [ ] V1 loader/formula/artifacts remain unchanged; V2 uses strict identity and `base/v2` only.
- [ ] API and Web reject V1 or mixed-version ready payloads.
- [ ] Backend focused, data-foundation, lint, mypy, Web tests, vue-tsc and build pass.
- [ ] Production Canonical/Catalog smoke is read-only and explains every residual unavailable item.
- [ ] No controlled external operation has been performed.
