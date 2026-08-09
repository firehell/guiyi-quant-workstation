# Market Runtime V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变已冻结 Canonical Data Foundation 的前提下，把当前 Market-only 个人量化工作站打通为“高性能历史分页 + operational 品种盘后自动更新 + 当日 rank1 主力实时 1m/Derived + Redis Live Overlay + FastAPI WebSocket + Web 历史/实时无缝显示”的完整日常使用链路。

**Architecture:** 正式历史继续由 `HistoricalDataManager -> Canonical Parquet + 八表 Catalog -> MarketDataService` 负责；实时行情由独立 `LiveMarketService -> Redis` 负责；展示层新增 `MarketReadService` 合并“历史读模型 + Live Overlay 状态”，但 Live 永不写入或提升为 Canonical。盘后由 macOS `launchd` 每日 17:00 启动一次短生命周期 `AfterMarketUpdater`，失败后仅 1 小时再试一次。当前 operational scope 固定为 J/JM/AP/AG，代码能力上限直接支持 active 60 品种。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy/PostgreSQL、Redis/redis-py、RQData/rqdatac、PyArrow/Parquet、Vue 3、TypeScript、Naive UI、Lightweight Charts 5、Node test、Playwright、macOS launchd。

## Global Constraints

- 已批准设计源：`docs/tasks/GY-MARKET-RUNTIME-V1.md`。
- Data Foundation 不重构：四字段 `DatasetKey`、continuous/contract 物理数据、actual_dominant 查询拼接、七周期、月分区、八表 Catalog 均保持不变。
- 不新增 PostgreSQL 表，不新增 Alembic migration。
- `active_products.txt` 仍为 60；新增 `operational_products.txt` 当前只能为 `j/jm/ap/ag`。
- Live V1 只监听 operational 品种当日 `rule=2, rank=1` 真实主力合约，不监听 continuous/SYMBOL88，不监听非主力合约。
- RQData Live 只订阅 completed `1m`；`5m/15m/30m/60m` 必须本地按现有 TradingSession 聚合；`1d/1w` historical-only。
- Live Redis 只是当日临时观察层，禁止写 Canonical、禁止新增 Live Parquet、禁止 PostgreSQL Live 表。
- 不恢复 RQ worker、业务队列、APScheduler、任务中心、checkpoint、DLQ、复杂恢复工作流。
- 所有真实 RQData Live、正式 Canonical 自动写入、launchd 实际加载都留到 MR-08；MR-01～MR-07 只允许 fixture、mock、临时 Redis/隔离 DB、render-only 验证。
- 个人项目优先简单与响应速度；抽象只服务真实复用。TradingSession、trading_day、rank1、聚合和 Canonical/Live seam 属于严格语义，不能简化成猜测。
- `auto_order=false` 始终成立。

---

## File Structure Map

### New backend files

```text
services/quant-api/app/market_data/operational_universe.py
services/quant-api/app/market_data/market_phase.py
services/quant-api/app/market_data/live_market.py
services/quant-api/app/market_data/market_read.py
services/quant-api/app/market_data/after_market.py
services/quant-api/app/api/market_live.py

services/quant-api/tests/data_foundation/test_market_pagination.py
services/quant-api/tests/data_foundation/test_operational_universe.py
services/quant-api/tests/data_foundation/test_market_phase.py
services/quant-api/tests/data_foundation/test_after_market.py
services/quant-api/tests/data_foundation/test_live_market.py
services/quant-api/tests/data_foundation/test_market_read.py
services/quant-api/tests/data_foundation/test_market_websocket.py
```

### New frontend files

```text
apps/quant-web/src/composables/useMarketSeries.ts
apps/quant-web/tests/marketSeries.test.ts
apps/quant-web/e2e/market-runtime.spec.mjs
```

### New runtime/config files

```text
data/universe/operational_products.txt
deploy/launchd/com.guiyi.quant-live.plist.template
deploy/launchd/com.guiyi.quant-after-market.plist.template
```

### Existing files expected to change

```text
services/quant-api/app/market_data/domain.py
services/quant-api/app/market_data/catalog.py
services/quant-api/app/market_data/service.py
services/quant-api/app/market_data/aggregation.py
services/quant-api/app/market_data/session_clock.py
services/quant-api/app/market_data/infrastructure.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/api/market.py
services/quant-api/app/main.py
services/quant-api/app/queue.py
services/quant-api/app/schemas/market.py
services/quant-api/app/schemas/runtime.py
services/quant-api/app/services/runtime_health.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/app/guiyi_cli/data_parser.py
services/quant-api/app/guiyi_cli/data_commands.py

services/quant-api/tests/data_foundation/test_domain.py
services/quant-api/tests/data_foundation/test_catalog_and_service.py
services/quant-api/tests/data_foundation/test_market_api.py
services/quant-api/tests/data_foundation/test_aggregation.py
services/quant-api/tests/data_foundation/test_cli.py
services/quant-api/tests/data_foundation/test_composition.py
services/quant-api/tests/test_runtime_health.py

apps/quant-web/src/api/market.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/network.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/pages/market/index.vue
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/vite.config.ts
apps/quant-web/tests/network.test.ts

scripts/ops/macos/run-local-service.sh
scripts/ops/macos/install-local-services.sh
scripts/ops/macos/local-services-status.sh

AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/tasks/GY-MARKET-RUNTIME-V1.md
TESTING.md
STATUS.md
```

---

## Task 1 — MR-01A: Backend Historical Cursor Pagination

**Files:**
- Modify: `services/quant-api/app/market_data/domain.py`
- Modify: `services/quant-api/app/market_data/catalog.py`
- Modify: `services/quant-api/app/market_data/service.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/market_data/__init__.py`
- Create: `services/quant-api/tests/data_foundation/test_market_pagination.py`
- Modify: `services/quant-api/tests/data_foundation/test_domain.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

### Step 1: Write failing domain tests for the page contract

- [ ] Add tests for a new immutable `SeriesPageQuery`:
  - normalize symbol/contract/frequency exactly like `SeriesQuery`;
  - `before` is optional but timezone-aware when present;
  - `limit` default is 1200;
  - valid range is `1..2000`;
  - contract is required only for `series_kind=contract`.

Representative test:

```python
def test_series_page_query_validates_cursor_and_limit() -> None:
    request = SeriesPageQuery(
        series_kind="actual_dominant",
        symbol=" JM ",
        frequency="15m",
        before=datetime(2025, 1, 3, 7, tzinfo=UTC),
    )
    assert request.symbol == "jm"
    assert request.limit == 1200
    assert request.before == datetime(2025, 1, 3, 7, tzinfo=UTC)

    with pytest.raises(ContractError):
        SeriesPageQuery(
            series_kind="actual_dominant",
            symbol="jm",
            frequency="15m",
            limit=2001,
        )
```

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_domain.py
```

Expected: FAIL because `SeriesPageQuery` does not exist.

### Step 2: Implement page value objects

- [ ] Add to `domain.py`:

```python
@dataclass(frozen=True, slots=True)
class SeriesPageQuery:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    before: datetime | None = None
    limit: int = 1200
    contract: str | None = None


@dataclass(frozen=True, slots=True)
class MarketSeriesPageResult:
    request_identity: Mapping[str, object]
    bars: tuple[CanonicalBar, ...]
    canonical_coverage: tuple[datetime, datetime] | None
    has_more_before: bool
    next_before: datetime | None
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]
```

Implementation rules:
- `before` normalized to UTC;
- `limit` bool values are rejected even though `bool` is an `int` subclass;
- contract validation reuses `DatasetKey` exactly as `SeriesQuery` does;
- add a `physical_key` property with the same semantics as `SeriesQuery`.

- [ ] Re-export `SeriesPageQuery` only if tests/API benefit; do not turn `app.market_data.__init__` into a large re-export surface.
- [ ] Re-run the domain tests; expected PASS.

### Step 3: Write failing pagination service tests

- [ ] Create `test_market_pagination.py` with explicit fixtures covering:
  1. latest physical page returns last N bars ascending;
  2. `before` is exclusive;
  3. crossing monthly partitions works;
  4. `has_more_before=True` when an older bar exists;
  5. `has_more_before=False` at history start;
  6. actual_dominant filters bars by formal MainContractMap owner;
  7. actual_dominant page crosses a contract switch;
  8. W1 uses formal weekly owner semantics;
  9. missing map or mapped partition remains fail-closed.

Representative assertion:

```python
result = service.query_page(
    SeriesPageQuery(
        series_kind="continuous",
        symbol="jm",
        frequency="1d",
        before=datetime(2025, 2, 2, 7, tzinfo=UTC),
        limit=2,
    )
)
assert [bar.close for bar in result.bars] == [Decimal("101"), Decimal("102")]
assert result.next_before == result.bars[0].bar_end
assert result.has_more_before is True
```

- [ ] Run only this file. Expected: FAIL because `query_page()` and Catalog helpers do not exist.

### Step 4: Add reverse partition lookup to Catalog

- [ ] Add:

```python
def partitions_before(
    self,
    key: DatasetKey,
    before: datetime | None,
) -> tuple[CatalogPartition, ...]:
    ...


def contract_partitions_before(
    self,
    symbol: str,
    frequency: BarFrequency,
    before: datetime | None,
) -> tuple[CatalogPartition, ...]:
    ...
```

Required semantics:
- query only Catalog rows; never glob files;
- filter `coverage_start < before` when a cursor exists;
- order newest partition first;
- `contract_partitions_before` joins `MarketDataset` and `MarketPartition`, constructs the exact `DatasetKey` for every result, and only includes `kind=contract`, requested symbol/frequency.

No pagination table/index migration is needed at current data scale.

### Step 5: Implement `MarketDataService.query_page()`

- [ ] Physical sequence algorithm:
  1. get reverse partitions;
  2. read each month through `CanonicalMonthlyStore`;
  3. verify `row_count` exactly like normal query;
  4. walk bars newest-to-oldest, applying `bar_end < before`;
  5. collect `limit + 1` at most;
  6. return the newest `limit` in ascending order;
  7. the extra bar determines `has_more_before`.

- [ ] actual_dominant algorithm:
  1. read formal MainContractMap facts up to the cursor trading day into `mapping_by_day`;
  2. get reverse physical contract partitions for requested symbol/frequency;
  3. read each partition and retain a bar only when `mapping_by_day[bar.trading_day] == dataset.contract`;
  4. for W1, retain only bars whose `trading_day` is the complete ISO-week owner under the same existing weekly mapping rule;
  5. collect `limit + 1`, dedupe by `bar_end`, sort ascending;
  6. over the returned page trading-day span, verify there is no formal MainContractMap gap;
  7. build resolved segments from the map facts represented by returned bars.

Do not call historical RQData and do not materialize actual_dominant.

- [ ] Re-run pagination and existing service tests.

### Step 6: Add the REST response contract

- [ ] Add Pydantic models:

```python
class MarketPageMetaOut(BaseModel):
    has_more_before: bool
    next_before: datetime | None


class MarketBarsPageResponse(BaseModel):
    request: dict[str, object]
    bars: list[MarketBarOut]
    canonical_coverage: CoverageOut | None
    page: MarketPageMetaOut
    resolved_contract_segments: list[ContractSegmentOut]
```

Define `canonical_coverage` here as the formal coverage of the returned page; the latest page's `end` is the formal seam used by the Web/MarketRead layer.

- [ ] Add endpoint:

```text
GET /api/v1/market/bars/page
```

with default `limit=1200`, API max `2000`, optional RFC3339 `before`.

- [ ] Keep `/bars/canonical` unchanged for explicit diagnostic windows.

### Step 7: API tests and regression

- [ ] Add endpoint tests for:
  - default limit;
  - before parsing;
  - contract validation;
  - invalid limit -> 422;
  - response fields exactly `request/bars/canonical_coverage/page/resolved_contract_segments`.

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_domain.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_market_pagination.py \
  services/quant-api/tests/data_foundation/test_market_api.py
```

Expected: PASS.

### Step 8: Commit

- [ ] Commit only MR-01A files:

```bash
git add services/quant-api/app/market_data/domain.py \
        services/quant-api/app/market_data/catalog.py \
        services/quant-api/app/market_data/service.py \
        services/quant-api/app/market_data/__init__.py \
        services/quant-api/app/schemas/market.py \
        services/quant-api/app/api/market.py \
        services/quant-api/tests/data_foundation/test_domain.py \
        services/quant-api/tests/data_foundation/test_catalog_and_service.py \
        services/quant-api/tests/data_foundation/test_market_pagination.py \
        services/quant-api/tests/data_foundation/test_market_api.py
git commit -m "feat(market): add cursor pagination for canonical bars"
```

---

## Task 2 — MR-01B: Web Historical Pagination and Kline Performance

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Create: `apps/quant-web/src/composables/useMarketSeries.ts` initially historical-only
- Create: `apps/quant-web/tests/marketSeries.test.ts`
- Create/extend: `apps/quant-web/e2e/market-runtime.spec.mjs`

### Step 1: Write failing model tests

- [ ] In `marketSeries.test.ts`, test exported pure helpers from the future composable:
  - `mergeInitialPage` sorts/dedupes;
  - `prependHistoricalPage` prepends without duplicate `bar_end`;
  - generation mismatch rejects stale data;
  - `next_before` tracks earliest formal bar.

- [ ] Run:

```bash
npm --prefix apps/quant-web test
```

Expected: FAIL because composable/helpers do not exist.

### Step 2: Add page DTOs and API call

- [ ] Add `MarketBarsPageRequest`, `MarketBarsPageResponse`, `MarketPageMeta` to `types/market.ts`.
- [ ] Add:

```ts
export function getMarketBarsPage(params: MarketBarsPageRequest) {
  return request.get<never, MarketBarsPageResponse>('/market/bars/page', { params })
}
```

### Step 3: Implement historical-only `useMarketSeries`

- [ ] V1 shape for this task:

```ts
export function useMarketSeries() {
  const bars = ref<BarData[]>([])
  const hasMoreBefore = ref(false)
  const nextBefore = ref<string | null>(null)
  const loadingInitial = ref(false)
  const loadingBefore = ref(false)
  let generation = 0

  async function replaceSeries(identity: MarketSeriesIdentity): Promise<void> { /* latest page */ }
  async function loadMoreBefore(): Promise<void> { /* cursor page */ }

  return { bars, hasMoreBefore, loadingInitial, loadingBefore, replaceSeries, loadMoreBefore }
}
```

- [ ] Default request limit exactly 1200.
- [ ] Switching symbol/series/frequency increments generation; late HTTP responses from old generation are ignored.
- [ ] Do not open WebSocket yet in this task.

### Step 4: Refactor KlineChart to imperative mutations

- [ ] Replace the deep watch that does `setData + fitContent` on every bars mutation.
- [ ] Expose exactly:

```ts
replaceBars(bars: BarData[]): void
prependBars(bars: BarData[]): void
updateBar(bar: BarData): void
scrollToLatest(): void
```

Rules:
- `replaceBars`: setData + fitContent;
- `prependBars`: capture logical visible range, set combined data once, shift the visible logical range by `prependedCount`, do not fit;
- `updateBar`: `candles.update` + `volume.update`, no full setData and no fit;
- daily/weekly time mapping stays unchanged.

- [ ] Emit `need-more-before` when visible logical `from` approaches the left boundary and no load is already in progress.

### Step 5: Replace date-range-as-main-navigation in chart.vue

- [ ] Main chart opening should call `replaceSeries()` and immediately display the latest page.
- [ ] The date range picker may remain only as an explicit diagnostic/manual-window control if still useful; it must not drive the default full-history load.
- [ ] Wire `need-more-before -> loadMoreBefore -> KlineChart.prependBars`.
- [ ] Keep route identity synchronization but remove `applyCoverageRange()` as the automatic full-range trigger.

### Step 6: Browser smoke

- [ ] Add Playwright mock routes for two historical pages.
- [ ] Assert:
  - first render requests `/bars/page` without `before`;
  - dragging/triggering left-load requests second page with the exact earliest cursor;
  - first-page bars stay visible after prepend;
  - no request asks for 2023→today full start/end range.

### Step 7: Validate

- [ ] Run:

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run build
npm --prefix apps/quant-web run test:e2e -- --grep "historical pagination"
```

If package.json uses a different Playwright script, use its existing script rather than adding a duplicate command.

### Step 8: Commit

- [ ] Commit:

```bash
git add apps/quant-web/src/types/market.ts \
        apps/quant-web/src/api/market.ts \
        apps/quant-web/src/composables/useMarketSeries.ts \
        apps/quant-web/src/pages/market/chart.vue \
        apps/quant-web/src/components/kline/KlineChart.vue \
        apps/quant-web/tests/marketSeries.test.ts \
        apps/quant-web/e2e/market-runtime.spec.mjs
git commit -m "feat(web): paginate market history and optimize kline updates"
```

---

## Task 3 — MR-02: Operational Universe and MarketPhaseResolver

**Files:**
- Create: `data/universe/operational_products.txt`
- Create: `services/quant-api/app/market_data/operational_universe.py`
- Create: `services/quant-api/app/market_data/market_phase.py`
- Modify: `services/quant-api/app/market_data/session_clock.py`
- Create: `services/quant-api/tests/data_foundation/test_operational_universe.py`
- Create: `services/quant-api/tests/data_foundation/test_market_phase.py`

### Step 1: Add the explicit operational configuration

- [ ] Create exact file:

```text
j
jm
ap
ag
```

No comments or generated state in this file.

### Step 2: Write failing universe tests

- [ ] Test exact current tuple/order `("j", "jm", "ap", "ag")`.
- [ ] Test duplicate code -> `OPERATIONAL_UNIVERSE_INVALID`.
- [ ] Test operational code outside active -> error.
- [ ] Test retired overlap -> error.
- [ ] Test a fixture with all 60 active codes passes without code changes.

### Step 3: Implement loader

- [ ] Public API:

```python
class OperationalUniverseError(ValueError):
    code = "OPERATIONAL_UNIVERSE_INVALID"


def load_operational_products(path: Path | None = None) -> tuple[str, ...]:
    ...
```

Use `PROJECT_ROOT/data/universe/operational_products.txt` by default; preserve file order; normalize lowercase; validate against existing active/retired files.

### Step 4: Refactor session_clock only enough to expose session metadata

- [ ] Add a metadata-rich immutable value without changing existing callers:

```python
@dataclass(frozen=True, slots=True)
class ResolvedSessionWindow:
    name: str
    window: SessionWindow
    is_night: bool
```

- [ ] Add `resolved_session_windows_for_trading_day(...)` as the canonical resolver.
- [ ] Reimplement existing `session_windows_for_trading_day(...)` as a thin projection of `.window`, preserving every historical test/behavior.

This prevents MarketPhaseResolver from reimplementing night-session anchoring.

### Step 5: Write failing phase tests

- [ ] Build date-scoped fixtures for DCE/CZCE/SHFE.
- [ ] Exact assertions:

```text
09:00       TRADING
10:14:59    TRADING
10:15:00    BREAK
10:20       BREAK
10:29:59    BREAK
10:30:00    TRADING
11:30:00    BREAK
13:30:00    TRADING
15:00:00    CLOSED
```

Also cover:
- night session belongs to next trading_day;
- cross-midnight remains same trading_day identity;
- weekend CLOSED;
- exchange holiday CLOSED;
- missing Calendar/Session UNKNOWN.

### Step 6: Implement MarketPhaseResolver

- [ ] Exact values:

```python
class MarketPhase(StrEnum):
    TRADING = "TRADING"
    BREAK = "BREAK"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProductMarketPhase:
    symbol: str
    phase: MarketPhase
    trading_day: date | None
    current_session: SessionWindow | None
    next_session_start: datetime | None
```

- [ ] `resolve(symbol, now)` searches only nearby actual trading days from TradingCalendar, resolves windows through `resolved_session_windows_for_trading_day`, and never uses `now.date()` as trading_day.
- [ ] BREAK is only a gap between day-session segments of the same trading_day; the night-to-next-day long closed gap is CLOSED.
- [ ] UNKNOWN is returned for missing facts, not silently guessed.

### Step 7: Validate and commit

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_operational_universe.py \
  services/quant-api/tests/data_foundation/test_market_phase.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_aggregation.py
```

- [ ] Commit message:

```text
feat(market): add operational universe and market phase resolver
```

---

## Task 4 — MR-03: AfterMarketUpdater, One Retry, Status, Dry launchd Template

**Files:**
- Create: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/app/market_data/infrastructure.py`
- Modify: `services/quant-api/app/guiyi_cli/data_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/data_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Create: `services/quant-api/tests/data_foundation/test_after_market.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`
- Create: `deploy/launchd/com.guiyi.quant-after-market.plist.template`
- Modify later activation script only in MR-07; do not load it here.

### Step 1: Extend the common RQData boundary under tests

- [ ] Rename private `_RqdatacClient` to public `RQDataClient` without changing historical semantics.
- [ ] Existing `RQDataMarketAdapter` must continue to lazy-create it.
- [ ] Add methods:

```python
def is_future_data_ready(self, trading_day: date) -> bool:
    frame = self.api.is_data_ready(
        categories=["future_daybar", "future_minbar"],
        expected_date=trading_day,
        market="cn",
    )
    required = frame.loc[["future_daybar", "future_minbar"], "ready"]
    return bool(required.all())


def dominant_for_day(self, symbol: str, trading_day: date) -> str:
    frame = self.api.futures.get_dominant(
        symbol.upper(),
        start_date=trading_day,
        end_date=trading_day,
        rule=2,
        rank=1,
    )
    # normalize exactly one nonempty contract result
```

Do not initialize rqdatac in dry-run tests.

### Step 2: Write failing AfterMarketUpdater tests

- [ ] Inject dependencies so tests never sleep an hour and never call real RQData:

```python
class AfterMarketUpdater:
    def __init__(
        self,
        *,
        manager: HistoricalDataManager,
        rqdata: RQDataClient,
        status_path: Path,
        sleep: Callable[[float], None],
        notifier: Callable[[str], None],
        now: Callable[[], datetime],
    ) -> None:
        ...
```

Test exact cases:
1. Saturday/non-trading day -> `skipped`, no ready call, no update, no retry;
2. ready first attempt -> update exactly once;
3. not-ready first -> injected `sleep(3600)` -> second ready -> update once;
4. first update failure -> sleep once -> second success;
5. second failure -> final failed + one notifier call;
6. success clears previous `last_failure`;
7. weekend skipped does not clear unresolved failure.

### Step 3: Implement simple status file

- [ ] `.run/after-market-status.json` schema exactly:

```json
{
  "last_run": {
    "trading_day": "2026-08-10",
    "status": "passed",
    "attempts": 1,
    "started_at": "2026-08-10T17:00:00+08:00",
    "finished_at": "2026-08-10T17:03:00+08:00",
    "products": ["j", "jm", "ap", "ag"],
    "error_code": null
  },
  "last_successful_trading_day": "2026-08-10",
  "last_failure": null
}
```

Only public error codes go into the file; no exception messages, credentials or paths.

### Step 4: Implement the updater flow

- [ ] Load operational products.
- [ ] Resolve `T = manager.coverage.latest_complete_day(products)`.
- [ ] At 17:00 local, if `T != today`, return `skipped/non_trading_day` without retry.
- [ ] Attempt function:
  - data-ready false -> attempt failure code `RQDATA_NOT_READY`;
  - ready -> call `manager.update(UpdateRequest(products, since=None, through=T, apply=True))`;
  - `passed` or `noop` -> success;
  - any other MaintenanceResult -> failure using stable stop/failure code.
- [ ] Only one `sleep(3600)` and one second attempt.
- [ ] Final failed -> status + one macOS notification.

### Step 5: macOS notification implementation

- [ ] Use fixed executable `/usr/bin/osascript` and a fixed title.
- [ ] Message content is generated only from known public status/error codes, never provider raw text.
- [ ] Tests replace notifier with a fake; no real notification in MR-03.

### Step 6: CLI

- [ ] Add `guiyi data after-market` with no `--apply` switch: this command itself is the automation entry point and remains uninstalled/unloaded until MR-08.
- [ ] `_run_data` dispatches AfterMarketUpdater separately rather than pretending it is a `HistoricalDataManager` method.
- [ ] CLI JSON includes `command=data.after-market`, status, trading_day, attempts, error_code.

### Step 7: launchd template only

- [ ] Create `com.guiyi.quant-after-market.plist.template` with:
  - `StartCalendarInterval Hour=17 Minute=0`;
  - no KeepAlive;
  - ProgramArguments -> existing `run-local-service.sh after-market`;
  - stdout/stderr -> `__LOG_DIR__/after-market.log`;
  - project root via same environment mechanism as current services.

Do not add it to load labels yet.

### Step 8: Validate and commit

- [ ] Run test files and CLI parser tests.
- [ ] Render the plist with a local substitution and run `plutil -lint`; do not `launchctl bootstrap`.
- [ ] Commit:

```text
feat(data): add bounded after-market updater
```

---

## Task 5 — MR-04A: Shared Aggregation Primitives and RedisLiveStore

**Files:**
- Modify: `services/quant-api/app/market_data/aggregation.py`
- Create: `services/quant-api/app/market_data/live_market.py` (store + DTO portion first)
- Modify: `services/quant-api/app/queue.py`
- Modify: `services/quant-api/tests/data_foundation/test_aggregation.py`
- Create: `services/quant-api/tests/data_foundation/test_live_market.py`

### Step 1: Write failing shared-bucket tests

- [ ] Add tests for public primitives:

```python
def bucket_window_for_bar(
    session: SessionWindow,
    frequency: BarFrequency | str,
    bar_end: datetime,
) -> SessionWindow:
    ...


def aggregate_bucket(
    bars: tuple[CanonicalBar, ...],
    *,
    bucket_end: datetime,
) -> CanonicalBar:
    ...
```

Assertions:
- 09:01 in 5m -> bucket end 09:05;
- 10:15 last bar ends exactly 10:15 and never crosses BREAK;
- partial session tail bucket ends at session.end;
- invalid bar outside session raises `AggregationError`.

### Step 2: Refactor historical aggregation with no behavior change

- [ ] `aggregate_from_1m()` must use the public bucket primitive and `aggregate_bucket` internally.
- [ ] Existing aggregation tests must remain byte-for-byte semantic equivalents.
- [ ] Run existing and new aggregation tests before any Live code.

### Step 3: Add Redis connection helpers

- [ ] Keep existing `get_redis_connection()`.
- [ ] Add an async connection factory for FastAPI WebSocket use later:

```python
def get_async_redis_connection():
    from redis.asyncio import Redis as AsyncRedis
    return AsyncRedis.from_url(REDIS_URL, decode_responses=True)
```

No queue is created.

### Step 4: Implement `RedisLiveStore` in live_market.py

- [ ] Exact keys:

```text
live:bars:{trading_day}:{symbol}:{frequency}
live:subscription:{trading_day}
live:heartbeat
```

- [ ] ZSET bar score = UTC `bar_end` epoch milliseconds.
- [ ] JSON member keeps Decimal values as strings so a `CanonicalBar` can be reconstructed losslessly.
- [ ] Methods required now:

```python
put_bar(trading_day, symbol, frequency, bar)
bars_after(trading_day, symbol, frequency, after)
bars_between(trading_day, symbol, frequency, start, end)
set_subscriptions(trading_day, mapping)
subscriptions(trading_day)
set_heartbeat(payload)
heartbeat()
cleanup_trading_day(trading_day)
publish_bar(symbol, frequency, bar)
publish_state(payload)
```

- [ ] Every Live bar/subscription key gets 3-day TTL on write.

### Step 5: Redis tests without requiring the developer's production Redis

- [ ] Use an in-memory fake implementing the small Redis methods or a disposable Redis URL explicitly supplied by test environment; never default test writes to configured Runtime Redis.
- [ ] Verify score ordering, `after` exclusivity, TTL calls, subscription isolation by trading_day, cleanup and compact serialization.

### Step 6: Commit

- [ ] Commit:

```text
refactor(market): share session aggregation and add live redis store
```

---

## Task 6 — MR-04B: LiveMarketService and Runtime CLI

**Files:**
- Modify: `services/quant-api/app/market_data/live_market.py`
- Modify: `services/quant-api/app/market_data/infrastructure.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/data_foundation/test_live_market.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`
- Create: `deploy/launchd/com.guiyi.quant-live.plist.template`

### Step 1: Define injectable Live provider boundary

- [ ] `RQDataClient` adds:

```python
def live_market_client(self):
    return self.api.LiveMarketDataClient()
```

- [ ] `LiveMarketService` receives a provider/client factory, phase resolver, RedisLiveStore, DB session and clock. Tests pass fakes.

### Step 2: Write failing rank1 subscription lifecycle tests

- [ ] Verify:
  - only operational products are considered;
  - entering first Session of trading_day resolves rank1 exactly once per symbol/day;
  - same trading_day does not recalculate even when phase changes TRADING->BREAK->TRADING;
  - new trading_day may switch contract;
  - subscriptions are exactly `bar_<rank1_contract>`;
  - continuous is never subscribed.

### Step 3: Implement rank1 snapshot + subscription reconciliation

- [ ] On a new trading_day:
  1. call `dominant_for_day` for every operational symbol;
  2. write one Redis subscription snapshot;
  3. compare desired channels to current channels;
  4. unsubscribe removed channels, subscribe added channels.

No PostgreSQL `MainContractMap` write occurs here.

### Step 4: Write failing completed-1m tests

- [ ] Fake LiveMarketDataClient sends repeated payloads for the same `bar_end`.
- [ ] Assert:
  - only expected 1m session boundaries are accepted;
  - latest pre-final payload wins;
  - bar finalizes only when `now >= bar_end + 2s`;
  - final bar is immutable;
  - Session final bar finalizes at session_end + 2s;
  - BREAK does not produce stale errors;
  - outside-session payload returns/records a stable rejection code.

### Step 5: Implement pending/final buffer

- [ ] Keep pending bars in process memory keyed by `(symbol, bar_end)`; this is transient and not a checkpoint system.
- [ ] The main service loop calls `flush_due(now)` every second or on each poll cycle.
- [ ] Finalized 1m is written to Redis and published once.

### Step 6: Implement incremental Derived generation

For every finalized 1m:
- [ ] find containing resolved SessionWindow;
- [ ] for each 5/15/30/60 frequency, compute its bucket window through shared `bucket_window_for_bar`;
- [ ] only when current 1m `bar_end == bucket.end`, read the required 1m range from Redis;
- [ ] verify every minute expected in `(bucket.start, bucket.end]` exists;
- [ ] call the shared aggregation logic and publish one Derived bar;
- [ ] if a Live minute is missing, skip that Derived bucket; do not call historical API and do not repair.

- [ ] Add a golden test feeding the same 1m fixture to historical `aggregate_from_1m` and the Live incremental path; 5m/15m/30m/60m OHLCV/OI outputs must match exactly.

### Step 7: Provider reconnect and phase loop

- [ ] TRADING connection failure -> fixed 10 second retry.
- [ ] BREAK/CLOSED with no new bars is normal and must not schedule provider reconnect solely for staleness.
- [ ] Redis failure marks Live unavailable; it never falls back to local files.
- [ ] Heartbeat includes generated_at, operational_count, subscribed_count, last_bar_at, phase counts; short TTL.

### Step 8: Runtime CLI

- [ ] Add `guiyi runtime live` alongside `runtime status`.
- [ ] `runtime live` runs the service foreground until process termination; no daemonization inside Python.
- [ ] CLI parser tests ensure no other worker/scheduler commands are revived.

### Step 9: Live launchd template only

- [ ] Create `com.guiyi.quant-live.plist.template` with RunAtLoad=true, KeepAlive=true, ThrottleInterval=10, and ProgramArguments `run-local-service.sh live`.
- [ ] Do not load it yet.

### Step 10: Validate and commit

- [ ] Run live tests, aggregation regression, CLI tests, Ruff/Mypy on affected modules.
- [ ] `plutil -lint` rendered live plist only.
- [ ] Commit:

```text
feat(market): add rank1 live market service
```

---

## Task 7 — MR-05: MarketReadService and FastAPI WebSocket

**Files:**
- Create: `services/quant-api/app/market_data/market_read.py`
- Create: `services/quant-api/app/api/market_live.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/main.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/queue.py`
- Create: `services/quant-api/tests/data_foundation/test_market_read.py`
- Create: `services/quant-api/tests/data_foundation/test_market_websocket.py`

### Step 1: Write failing read-state tests

- [ ] Define tests for these exact series rules:

```text
operational actual_dominant + intraday -> live_eligible=true
current rank1 contract + intraday      -> live_eligible=true
continuous                             -> live_eligible=false
other contract                         -> live_eligible=false
1d / 1w                                -> live_eligible=false
```

- [ ] Canonical seam rule test: Live bars at or before `canonical_end` are excluded; only `bar_end > canonical_end` survive.

### Step 2: Implement MarketReadService

- [ ] Immutable state object:

```python
@dataclass(frozen=True, slots=True)
class MarketReadState:
    symbol: str
    series_kind: str
    frequency: str
    operational: bool
    phase: str
    trading_day: date | None
    live_eligible: bool
    live_available: bool
    live_contract: str | None
    canonical_end: datetime | None
    after_market: Mapping[str, object]
```

- [ ] Service methods:

```python
history_page(request: SeriesPageQuery) -> MarketSeriesPageResult
state(identity, now: datetime) -> MarketReadState
live_snapshot(identity, after: datetime | None, now: datetime) -> tuple[CanonicalBar, ...]
```

`history_page` delegates to MarketDataService; it never reads Parquet directly.

- [ ] `state()` gets canonical_end through a latest-page query with limit=1, operational membership from the explicit file, phase from MarketPhaseResolver, rank1 from Redis snapshot, after-market state from `.run/after-market-status.json`.

### Step 3: State REST endpoint

- [ ] Add:

```text
GET /api/v1/market/state
```

using the same identity params as the chart.

- [ ] The endpoint is historical-safe: Redis unavailable returns `live_available=false` rather than breaking the request.

### Step 4: Write failing WebSocket protocol tests

Using FastAPI TestClient WebSocket and fake Redis/pubsub, assert exactly four message types:
- `state` first;
- `snapshot` after subscription is established;
- `bar` for each new confirmed bar;
- `reset` when trading_day or live_contract changes.

Also assert REST->WS race ordering:
1. server subscribes Pub/Sub;
2. bar arrives;
3. server reads snapshot including that bar;
4. duplicate Pub/Sub copy is deduped by bar_end.

### Step 5: Implement dedicated WebSocket router

- [ ] Create `app/api/market_live.py` because async Pub/Sub would make the existing REST-only `market.py` lose focus.
- [ ] Route:

```text
WS /api/v1/market/ws
```

- [ ] Validate query params before accepting the session; close with a stable policy code on invalid identity.
- [ ] Subscribe to:

```text
live:bar:{symbol}:{frequency}
market:state
```

before reading the snapshot.

- [ ] Initial cutoff = max(client `after`, current canonical_end), ignoring missing values.
- [ ] Snapshot is sorted ascending and deduped.
- [ ] Pub/Sub `bar` messages at/before canonical_end or last sent bar are ignored.
- [ ] On `market:state`, recompute state; if trading_day/live_contract changed send `reset`, then send current `state`.

### Step 6: FastAPI/Vite proxy path consistency

- [ ] Do not introduce a second `/ws` backend route.
- [ ] Later frontend will connect directly to `/api/v1/market/ws`.
- [ ] Modify Vite `/api` proxy to `ws: true` in MR-06 so local dev upgrades work.

### Step 7: Validate and commit

- [ ] Run market read/ws/API tests and existing MarketDataService tests.
- [ ] Commit:

```text
feat(api): add unified market read state and websocket
```

---

## Task 8 — MR-06: Unified Web Historical + Live Integration

**Files:**
- Modify: `apps/quant-web/src/composables/useMarketSeries.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/utils/network.ts`
- Modify: `apps/quant-web/vite.config.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/tests/network.test.ts`
- Modify: `apps/quant-web/tests/marketSeries.test.ts`
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs`

### Step 1: Add exact frontend state/message types

- [ ] Mirror backend state fields.
- [ ] Define discriminated WS union:

```ts
type MarketWsMessage =
  | { type: 'state'; state: MarketReadState }
  | { type: 'snapshot'; bars: CanonicalBarDto[] }
  | { type: 'bar'; bar: CanonicalBarDto }
  | { type: 'reset'; trading_day: string | null; contract: string | null }
```

No fifth event type.

### Step 2: Make WebSocket URL exact

- [ ] Update/replace current unused `resolveWsURL` so default is:

```text
ws://host/api/v1/market/ws
wss://host/api/v1/market/ws
```

- [ ] Explicit configured URLs still reject localhost when page is remote.
- [ ] Set `ws: true` on Vite `/api` proxy.
- [ ] Update network tests accordingly.

### Step 3: Write failing composable Live tests

- [ ] Inject a fake WebSocket factory into `useMarketSeries` for tests.
- [ ] Cover:
  - snapshot merges only bars after canonical seam;
  - duplicate live bar_end updates/replaces exactly once;
  - switching AG->JM increments generation and ignores late AG REST/WS messages;
  - websocket disconnect retains historical bars and sets live unavailable;
  - reconnect sends last known live bar_end as `after`;
  - state CLOSED on weekend does not treat lack of live bars as error;
  - state BREAK does not reconnect just because no bars arrive;
  - canonical_end advancement removes/replaces Live bars covered by new formal history.

### Step 4: Implement WebSocket lifecycle in useMarketSeries

- [ ] After first historical page:
  1. call state REST;
  2. if live_eligible, connect WS;
  3. process `state/snapshot/bar/reset`;
  4. fixed reconnect delay (10s) only after real disconnect while the series still needs Live;
  5. keep history usable when Live is unavailable.

- [ ] `continuous` and non-rank1 contract do not open a Live socket.
- [ ] `1d/1w` do not open a Live socket.

### Step 5: Mutation model for KlineChart

- [ ] Use the existing imperative functions from MR-01B:
  - new series -> `replaceBars`;
  - historical page -> `prependBars`;
  - confirmed Live -> `updateBar`.

- [ ] `followLatest=true` initially.
- [ ] When user scrolls materially left of the current right edge, emit/set `followLatest=false`.
- [ ] Incoming Live bars never force a historical viewer back to latest.
- [ ] Add a single lightweight “回到最新” button that calls `scrollToLatest()` and sets follow true.

### Step 6: Market state UI

- [ ] In `chart.vue`, display compact tags only:

```text
交易中 / 盘中休市 / 已收盘 / 状态未知
Live / Historical only
当前 Live 主力合约（when applicable）
最近盘后更新失败（when present）
```

No dashboard or new operations center.

### Step 7: Canonical advance behavior

- [ ] When WS `state.canonical_end` advances beyond the current formal seam:
  1. refetch the newest historical page;
  2. replace the formal right edge;
  3. retain only Live bars strictly later than new canonical_end;
  4. preserve viewport if `followLatest=false`.

### Step 8: Browser E2E

- [ ] Mock REST + WS and validate:
  - fast latest historical first paint;
  - left pagination;
  - live actual_dominant append;
  - continuous historical-only;
  - BREAK at 10:15 does not show error;
  - CLOSED weekend still browses history;
  - canonical advance replaces Live seam without duplicate candles;
  - old-series messages do not leak after symbol switch.

### Step 9: Validate and commit

- [ ] Run frontend test/build/Playwright mock suite.
- [ ] Commit:

```text
feat(web): merge canonical history with rank1 live overlay
```

---

## Task 9 — MR-07: Runtime Health, launchd Packaging, Canonical Docs and Activation Boundary

**Files:**
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`
- Modify: `scripts/ops/macos/run-local-service.sh`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Existing new templates: both Market Runtime plists
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/tasks/GY-MARKET-RUNTIME-V1.md`
- Modify: `TESTING.md`
- Modify: `STATUS.md`

### Step 1: Replace retired runtime stubs with the V1 state shape

- [ ] Remove active response dependence on retired `live_checkpoints` and `after_market_scheduler` shapes.
- [ ] Add `live_market` health read from Redis heartbeat:

```text
status
operational_count
subscribed_count
last_heartbeat_at
last_bar_at
phase_counts
```

- [ ] Add `after_market` health read from `.run/after-market-status.json`:

```text
status
last_run
last_successful_trading_day
last_failure
```

- [ ] Do not resurrect archive/notification-retry behavior. If those old stub fields have no active consumer, remove them from the active runtime response/schema in this same change.
- [ ] Keep DB/Redis probes. Keep RQ health only as existing generic local infrastructure health; `RUNTIME_QUEUE_NAMES` remains empty and no queue is added.

### Step 2: Runtime health tests

- [ ] Test fresh heartbeat -> live ok.
- [ ] Missing/stale heartbeat -> live disabled/degraded according to whether runtime is configured enabled; do not mark historical DB unhealthy.
- [ ] After-market final failure surfaces public error code.
- [ ] Secret/redaction regression stays green.

### Step 3: Wire service runner

- [ ] `run-local-service.sh` adds:

```text
live         -> Python CLI runtime live
after-market -> Python CLI data after-market
```

No shell daemon loop; launchd owns lifecycle.

### Step 4: Render/install logic with explicit activation mode

- [ ] `install-local-services.sh` renders base + Market Runtime templates in `--render-only`.
- [ ] Keep existing `--confirm-load` behavior for base api/web/log services only.
- [ ] Add one explicit mode:

```text
--confirm-market-runtime
```

which installs/enables:
- `com.guiyi.quant-live` and kickstarts it;
- `com.guiyi.quant-after-market` but does **not** kickstart it immediately; it waits for its 17:00 calendar trigger.

This mode is the one-time runtime activation action for MR-08.

- [ ] `local-services-status.sh` lists both new labels without treating absence as base-service failure until Market Runtime has been enabled; output should distinguish base vs optional market-runtime.

### Step 5: Render-only verification

- [ ] Run:

```bash
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```

Do not call `--confirm-market-runtime` in MR-07.

### Step 6: Update authorization/canonical rules before activation

- [ ] `AGENTS.md` and `DECISIONS.md` must state:
  - Market Runtime code/config is default disabled;
  - a single explicit user request to enable Market Runtime V1 authorizes the bounded persistent automation thereafter;
  - bounded scope = `operational_products`, Live rank1 subscription, daily 17:00 + one 1h retry historical update;
  - daily runs after activation do not need daily re-confirmation;
  - adding a product to `operational_products.txt` explicitly expands that automated scope;
  - this does not authorize main/tag/release, unrelated DB changes, enterprise notification channels, or orders.

- [ ] `PROJECT_SOURCE.md` / `docs/ARCHITECTURE.md`: record the implemented Historical/Live/After-market planes, but mark actual Runtime activation not yet completed until MR-08.
- [ ] `STATUS.md`: MR-01～MR-07 implemented/verified locally; Market Runtime remains disabled; operational=4.
- [ ] `GY-MARKET-RUNTIME-V1.md`: change disposition from `design_ready_for_review` to `implementation_ready_for_canary` only after all MR-01～MR-07 tests pass.
- [ ] `TESTING.md`: add focused Market Runtime commands and render-only checks.

### Step 7: Full repository verification

- [ ] Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py

npm --prefix apps/quant-web test
npm --prefix apps/quant-web run build

git diff --check
```

- [ ] Run mock Playwright Market Runtime suite.
- [ ] Confirm no real RQData Live, no launchctl Market Runtime load, and no formal Canonical mutation occurred during MR-01～MR-07.

### Step 8: Commit

- [ ] Commit:

```text
feat(runtime): package Market Runtime V1 for controlled activation
```

---

## Task 10 — MR-08: J/JM/AP/AG Real Runtime Canary

**This task changes real external Runtime and may write formal Canonical through the approved automatic updater. Do not execute it from this plan alone. It starts only after the user explicitly requests “启用 Market Runtime V1” for the identified local workstation.**

**Current canary scope:**

```text
j
jm
ap
ag
```

### Step 1: Read-only preflight

- [ ] Confirm current `develop` contains MR-01～MR-07 and all required tests passed.
- [ ] Confirm `operational_products.txt` is exactly J/JM/AP/AG and is a subset of active 60.
- [ ] Run read-only audit for all four operational products.
- [ ] Run latest normal `data update` dry-run/read-only planning as appropriate; do not use remaining 56 products.
- [ ] Render and lint both LaunchAgents.
- [ ] Confirm Redis/API/Web base services are healthy.

If any operational product no longer meets its data contract, stop before activation.

### Step 2: Explicit activation gate

- [ ] Obtain the user's one-time explicit request to enable Market Runtime V1 on the local workstation.
- [ ] Execute exactly once:

```bash
scripts/ops/macos/install-local-services.sh --confirm-market-runtime
```

- [ ] Read back launchd status. Live should be loaded; after-market should be loaded/scheduled but not manually kicked at an arbitrary time.

### Step 3: Live rank1 canary during a real trading session

- [ ] Verify Redis subscription snapshot contains exactly J/JM/AP/AG and one rank1 contract each.
- [ ] Verify no continuous/SYMBOL88 channel subscription exists.
- [ ] Verify `/api/runtime/health` shows operational_count=4 and subscribed_count=4 when applicable.
- [ ] On at least one night-session product, verify the Live snapshot trading_day is the next formal trading_day, not natural `now.date()`.

### Step 4: Real completed-bar behavior

- [ ] Observe at least one confirmed 1m bar for applicable operational products.
- [ ] Verify Web actual_dominant updates without full data reload.
- [ ] Verify current-rank1 contract view may reuse the same Live bar.
- [ ] Verify continuous page stays historical-only.
- [ ] Verify Redis 5m/15m/30m/60m outputs match session boundaries.

### Step 5: Intraday BREAK canary

On a normal trading day:
- [ ] 10:15–10:30 -> phase BREAK;
- [ ] no stale/disconnect error from lack of bars;
- [ ] same rank1 subscription remains;
- [ ] 10:30 resumes TRADING automatically.

Also verify 11:30–13:30 with the same semantics when the product has those day sessions.

### Step 6: Web history/live experience

- [ ] Open AG or JM 15m actual_dominant:
  - latest historical page appears quickly;
  - scroll left requests older page and preserves viewport;
  - confirmed Live bars append;
  - scroll into history disables follow-latest;
  - “回到最新” restores live-follow.

### Step 7: Real 17:00 after-market behavior

- [ ] Let the scheduled 17:00 process run normally; do not manually invoke a second duplicate updater.
- [ ] If RQData ready, verify only J/JM/AP/AG are updated and Canonical advances.
- [ ] If first attempt fails/not-ready, verify exactly one retry occurs one hour later.
- [ ] If final failure occurs, verify one macOS notification and `.run/after-market-status.json` contains the public failure state; no third retry.

### Step 8: Formal map and seam verification

After a successful update:
- [ ] compare the Live rank1 snapshot with formal `MainContractMap` for that trading_day;
- [ ] match -> normal success;
- [ ] mismatch -> `LIVE_DOMINANT_MISMATCH` in status + local notification, formal MainContractMap remains authoritative;
- [ ] verify Web receives canonical advancement, refetches rightmost formal page and drops Live bars now covered by Canonical;
- [ ] verify Live was not promoted or copied into Parquet.

### Step 9: Weekend/non-trading verification

- [ ] On a weekend/holiday, Historical page and left pagination remain normal.
- [ ] Market state is CLOSED and Live unavailable without an error.
- [ ] 17:00 after-market launch returns skipped/non_trading_day and performs no retry.

### Step 10: Close MR-08

- [ ] Update `STATUS.md` with exact observed canary facts only.
- [ ] Update `GY-MARKET-RUNTIME-V1.md` disposition to `active_v1` only if all required real checks passed.
- [ ] Do not mark remaining 56 active products operational.
- [ ] Final conclusion must be `允许继续运行 Market Runtime V1` or `阻塞`; do not infer readiness from partial observations.

---

## Cross-Task Acceptance Matrix

| Capability | Required completion task |
|---|---|
| latest 1200 + left cursor pagination | MR-01A/B |
| no full-history default Web load | MR-01B |
| operational J/JM/AP/AG explicit config | MR-02 |
| 10:15–10:30 / 11:30–13:30 BREAK | MR-02 |
| night trading_day resolution | MR-02 + MR-04B |
| 17:00 + one 1h retry | MR-03 |
| final failure status + macOS notification | MR-03 |
| shared Historical/Live Derived semantics | MR-04A/B |
| rank1-only completed 1m Live | MR-04B |
| Redis temporary Live Overlay | MR-04A/B |
| actual_dominant/current-rank1 live eligibility | MR-05 |
| REST/WS race-free snapshot | MR-05 |
| continuous historical-only | MR-05/06 |
| Live disconnect does not break history | MR-05/06 |
| canonical advancement replaces Live seam | MR-05/06 |
| real health + launchd packaging | MR-07 |
| bounded persistent automation policy | MR-07 |
| real J/JM/AP/AG end-to-end canary | MR-08 |

## Final Non-Goals Check

Before declaring the plan complete, search active code/docs for accidental introduction of any of these concepts:

```text
Live Canonical promotion
Live Parquet archive
Live PostgreSQL table
continuous live subscription
tick subscription
RQ business worker
scheduler database
checkpoint table
retry queue
multi-user subscription
order submission
auto_order=true
```

Any active introduction is out of scope and must be removed before MR-08.
