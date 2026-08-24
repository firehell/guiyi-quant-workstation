# SuBing Daily Watch V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-after-market, immutable active60 D1+60m EMA21 trend admission ledger and replace the Market home-page Trend Focus entry with the current `苏冰今日观察` list.

**Architecture:** Extract the existing SuBing EMA21/5-Bar/10-Bar slope math into a frequency-neutral pure seam while preserving exact 5m/15m Factor parity. A narrow `SubingDailyWatchBuilder` reads confirmed `actual_dominant` D1 and 60m facts through `MarketDataService -> ActualDominantResearchSegmentLoader`, classifies every active product, and publishes an immutable target-trading-day ledger to an explicitly configured mounted `/Volumes/...` root. The existing after-market Runtime invokes generation only after `AfterMarketResult.status == passed`; a read-only API projects the current valid target day to the Web, which replaces Trend Focus without changing Alert Scope or global chart preferences.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Pydantic / `Decimal` / pytest; existing Indicator Kernel, `MarketDataService`, `ActualDominantResearchSegmentLoader`, TradingCalendar and after-market Runtime; Vue 3 / TypeScript / Naive UI / Node test runner / Playwright.

**Spec:** `docs/superpowers/specs/2026-08-24-subing-daily-watch-v1-design.md`

## Global Constraints

- Lane 3. Use **Sol + high reasoning** in a new implementation session.
- Before editing, read `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/DATA_CENTER.md`, the Spec, and this plan.
- Start from the then-current `develop` in an isolated task worktree; recommended branch: `feature/subing-daily-watch-v1`.
- If active canonical changed incompatibly after this plan, stop and report the conflict. Do not silently adapt formula, Runtime, storage or product scope.
- Task 0 must close the current contradiction in which `STATUS.md` still marks the old four-system plan resumable. No production code task may start first.
- Do not modify `main`, any Runtime worktree, release tags, launchd bindings, production Alert Scope/transport, production DB/Redis/Canonical data, prospective OOS artifacts or order paths.
- Do not run real RQData, real after-market, real notification, migration, Runtime switch/promotion or write to the real extension drive during implementation or tests.
- All tests for storage must use `tmp_path` plus injected mount/root validation. No test may create or write under real `/Volumes`.
- Active scope is exactly `data/universe/active_products.txt`; generation requires set equality with `operational_products.txt` and production active count 60.
- Data identity is exactly `actual_dominant + 1d + 60m`, confirmed Canonical, current rank1 segment-local, no continuous fallback and no cross-contract warm-up.
- EMA period is 21 with existing `sma_window` seed. Slopes are exact 5-Bar and 10-Bar linear-regression EMA slopes normalized to bps/bar. V1 uses sign only and adds no threshold.
- Admission uses only price side and EMA21 slope signs. No MACD, BOLL, volume, open interest, N Structure, score, rank, PnL or recommendation.
- Durable artifacts are only `history/*.json`, `current.json` and `generation-status.json` under `GUIYI_SUBING_OBSERVATION_ROOT`; no repository/system-disk fallback, DB or Redis persistence.
- V1 exposes only the current observation through HTTP and Web. Do not add history list/detail API or UI.
- The Market home page removes the Trend Focus request/component, but this task does not delete the Trend Focus backend implementation or route.
- Daily Watch generation failure must not change a successful after-market result, process exit code, public stdout payload or Execution Review roll follow-up.
- Code complete does not mean released, Runtime-ready, extension-drive-configured or empirically validated. First real files wait for a separately approved Runtime promotion and the next natural after-market run.

## Worktree and Integration

```text
source branch: develop
recommended task branch: feature/subing-daily-watch-v1
task worktree: isolated
integration target: develop
```

- Require an independent Review conclusion of `允许集成 develop` before integration.
- A reviewed Lane 3 implementation may be integrated to `develop`; that does not authorize main/tag/release, Runtime promotion, environment configuration or real writes.
- After integration is confirmed in `develop`, delete the merged task worktree and branch.

---

## File Structure / Responsibility Map

### New backend files

- `services/quant-api/app/market_data/subing_ema_trend.py` — pure EMA21, price-side and 5/10 regression-slope facts.
- `services/quant-api/app/market_data/subing_daily_watch_calendar.py` — next common trading day and expected current target day.
- `services/quant-api/app/market_data/subing_daily_watch.py` — domain types, per-product classification, complete-ledger builder and current read service.
- `services/quant-api/app/market_data/subing_daily_watch_store.py` — extension-drive root validation, canonical JSON, immutable history/current/status store.
- `services/quant-api/tests/test_subing_ema_trend.py` — formula and existing Factor parity.
- `services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py` — multi-exchange calendar behavior.
- `services/quant-api/tests/data_foundation/test_subing_daily_watch.py` — builder, identity and classification.
- `services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py` — mount policy, atomicity, immutability and read validation.
- `services/quant-api/tests/test_subing_daily_watch_api.py` — current API ready/unavailable contract.

### New Web files

- `apps/quant-web/src/components/market/SubingDailyWatch.vue` — current list, counts, expansion and unavailable presentation.
- `apps/quant-web/src/utils/subingDailyWatch.ts` — stable reason labels and six-item presentation helpers.
- `apps/quant-web/src/utils/marketChartEntry.ts` — one-shot `subing-daily-watch` route override.
- `apps/quant-web/tests/subingDailyWatch.test.ts` — DTO normalization and presentation helpers.
- `apps/quant-web/tests/marketChartEntry.test.ts` — strict one-shot route parsing.

### Modified backend files

- `services/quant-api/app/market_data/subing_research.py` — delegate EMA facts to the new seam without changing public Factor identity.
- `services/quant-api/app/market_data/composition.py` — compose builder/store/current reader without provider or Runtime side effects.
- `services/quant-api/app/runtime_entry.py` — isolated post-success generation follow-up.
- `services/quant-api/app/api/market.py` — current read-only route.
- `services/quant-api/app/schemas/market.py` — Pydantic current-response projection.
- `services/quant-api/tests/test_runtime_entry.py` — after-market follow-up isolation and no offline research import.
- `.env.example` — explicit extension-drive root placeholder.

### Modified Web files

- `apps/quant-web/src/types/market.ts` — Daily Watch wire/display DTOs and normalization.
- `apps/quant-web/src/api/market.ts` — current read function.
- `apps/quant-web/src/pages/market/index.vue` — replace Trend Focus with Daily Watch.
- `apps/quant-web/src/pages/market/chart.vue` — consume strict one-shot entry override.
- `apps/quant-web/e2e/market-radar.spec.mjs` — home-page current list and unavailable behavior.
- `apps/quant-web/e2e/market-research.spec.mjs` — chart entry and non-persistence behavior.

### Canonical closeout files

- `STATUS.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- delete old four-system Design Spec and Implementation Plan in Task 0.

### Explicitly unchanged

- Alert registry/evaluator/scope/transport and Alert database tables.
- `HistoricalDataManager`, Canonical schema, Market Catalog schema and Redis schemas.
- N Structure, JDJ, HTDY formula, RQAlpha and Execution Review business semantics.
- `main`, tags, Runtime worktrees and launchd definitions.

---

## Task 0: Close the Old Four-System Canonical Conflict

**Files:**
- Delete: `docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md`
- Delete: `docs/superpowers/plans/2026-08-24-four-system-all-frequency-market-observation.md`
- Modify: `STATUS.md`

**Interfaces:**
- Produces: one unambiguous active direction: `SuBing Daily Watch V1`.
- Blocks: every later task until the old Stage 2 `resumable` and Task 1 wording is removed.

- [ ] **Step 1: Verify the conflict exists at the task head**

Run:

```bash
git status --short
git log -5 --oneline
grep -n "四系统\|四体系\|resumable\|implementation plan Task 1" STATUS.md
test -f docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md
test -f docs/superpowers/plans/2026-08-24-four-system-all-frequency-market-observation.md
```

Expected: the old files exist and `STATUS.md` still exposes the old implementation as active/resumable. If the facts differ, stop and reconcile against current canonical before deleting anything.

- [ ] **Step 2: Delete only the two superseded active documents**

```bash
rm docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md
rm docs/superpowers/plans/2026-08-24-four-system-all-frequency-market-observation.md
```

Do not create backup, `superseded/`, archive or duplicate copies. Git history is the recovery path.

- [ ] **Step 3: Replace the active status wording**

Update `STATUS.md` so it states exactly:

```text
- The prior Four-System Active60 All-Frequency Observation direction was withdrawn by the user before implementation and its active Spec/Plan were removed.
- SuBing Daily Watch V1 is the approved replacement design/plan.
- No implementation, release, Runtime promotion, extension-drive configuration, real file generation or Alert Scope change has occurred yet.
- The next step is Task 1 of the SuBing Daily Watch V1 implementation plan in an isolated Lane 3 task.
```

Preserve existing release, Runtime, No-Watch, evidence and pending-Gate facts.

- [ ] **Step 4: Verify no active reference still instructs execution of the old plan**

```bash
git grep -n "four-system-all-frequency-market-observation\|Four-System Active60\|四系统全周期" -- \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md docs ':!CHANGELOG.md' || true
```

Expected: no active instruction remains. Historical changelog references are allowed only if clearly historical.

- [ ] **Step 5: Commit**

```bash
git add STATUS.md \
  docs/superpowers/specs/2026-08-24-four-system-all-frequency-market-observation-design.md \
  docs/superpowers/plans/2026-08-24-four-system-all-frequency-market-observation.md
git commit -m "docs: supersede four-system observation stage"
```

---

## Task 1: Extract the Frequency-Neutral SuBing EMA21 Trend Seam

**Files:**
- Create: `services/quant-api/app/market_data/subing_ema_trend.py`
- Create: `services/quant-api/tests/test_subing_ema_trend.py`
- Modify: `services/quant-api/app/market_data/subing_research.py`
- Regression: `services/quant-api/tests/test_subing_api.py`
- Regression: `services/quant-api/tests/test_subing_calibration.py`
- Regression: `services/quant-api/tests/data_foundation/test_subing_read_service.py`

**Interfaces:**
- Produces:

```python
class SubingEmaTrendStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"

@dataclass(frozen=True, slots=True)
class SubingEmaTrendSnapshot:
    timeframe: BarFrequency
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    close: Decimal
    ema21: Decimal
    price_side: PriceSide
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal

@dataclass(frozen=True, slots=True)
class SubingEmaTrendResult:
    status: SubingEmaTrendStatus
    snapshot: SubingEmaTrendSnapshot | None

def calculate_subing_ema_trend_series(
    bars: Sequence[CanonicalBar],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
) -> tuple[SubingEmaTrendResult, ...]: ...

def calculate_subing_ema_trend(...) -> SubingEmaTrendResult: ...
```

- Existing `SubingFactorSnapshot` and public Factor/Signal API remain unchanged.

- [ ] **Step 1: Write deterministic EMA and slope tests**

In `test_subing_ema_trend.py`, create 40 monotonically rising `CanonicalBar` values with `Decimal` closes and assert:

```python
result = calculate_subing_ema_trend(
    bars,
    timeframe=BarFrequency.H1,
    contract="JM2609",
    segment_start_trading_day=bars[0].trading_day,
)
assert result.status is SubingEmaTrendStatus.READY
assert result.snapshot is not None
assert result.snapshot.price_side is PriceSide.ABOVE
assert result.snapshot.slope_5_bps_per_bar > 0
assert result.snapshot.slope_10_bps_per_bar > 0
```

Add descending, flat/zero-slope, insufficient warm-up, empty contract, non-increasing `bar_end`, and bar-before-segment tests.

- [ ] **Step 2: Freeze existing Factor parity before refactoring**

Create a deterministic bar fixture that makes the existing Factor ready, call both APIs, and require exact equality for:

```python
assert factor.snapshot.ema21 == trend.snapshot.ema21
assert factor.snapshot.price_side is trend.snapshot.price_side
assert factor.snapshot.slope_5_raw == trend.snapshot.slope_5_raw
assert factor.snapshot.slope_10_raw == trend.snapshot.slope_10_raw
assert factor.snapshot.slope_5_bps_per_bar == trend.snapshot.slope_5_bps_per_bar
assert factor.snapshot.slope_10_bps_per_bar == trend.snapshot.slope_10_bps_per_bar
```

The test should initially fail because the trend module does not exist.

- [ ] **Step 3: Run the focused RED tests**

```bash
pytest -q services/quant-api/tests/test_subing_ema_trend.py
```

Expected: FAIL on missing module/interfaces.

- [ ] **Step 4: Implement the pure trend seam**

Use the existing Indicator Kernel exactly:

```python
ema = ema_series(
    [float(bar.close) for bar in bars],
    21,
    bar_ends=[bar.bar_end.isoformat() for bar in bars],
    seed_policy="sma_window",
    indicator_code="ema21",
)
```

For each index, require the latest 10 EMA points ready/valid/non-null, compute existing `_regression_slope` semantics for the last 5 and 10 values, and normalize with `Decimal(10000)`. Do not import MACD or volume logic into this module.

- [ ] **Step 5: Refactor `calculate_subing_factor_series` to delegate EMA facts**

Keep MACD and volume calculations in `subing_research.py`. For each bar index, consume the aligned `SubingEmaTrendResult`; if it is insufficient, return the existing `_insufficient()` Factor result. Copy the six trend fields into the unchanged `SubingFactorSnapshot`.

Do not change:

```text
FormalPolicy ids
MACD policy equivalence
volume ratio
Signal conditions
same-boundary resolution
public API fields
```

- [ ] **Step 6: Run focused and regression tests**

```bash
pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/test_subing_calibration.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
ruff check \
  services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_ema_trend.py
mypy services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_research.py
```

Expected: PASS with exact parity.

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_ema_trend.py \
  services/quant-api/app/market_data/subing_research.py \
  services/quant-api/tests/test_subing_ema_trend.py
git commit -m "refactor(subing): extract EMA21 trend facts"
```

---

## Task 2: Add the Common Trading-Day Resolver

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_watch_calendar.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py`

**Interfaces:**
- Produces:

```python
class SubingDailyWatchCalendarError(RuntimeError):
    def __init__(self, code: str) -> None: ...

def resolve_next_common_trading_day(
    session: Session,
    *,
    products: tuple[str, ...],
    source_trading_day: date,
) -> date: ...

def resolve_expected_daily_watch_day(
    session: Session,
    *,
    products: tuple[str, ...],
    now: datetime,
    cutover: time = time(18, 20),
) -> date: ...
```

- Errors use only:

```text
OPERATIONAL_PRODUCT_EXCHANGE_UNAVAILABLE
NEXT_TRADING_DAY_UNAVAILABLE
EXPECTED_TRADING_DAY_UNAVAILABLE
```

- [ ] **Step 1: Write RED tests for next common day**

Use the existing test database fixtures to insert two active products on different exchanges and matching `TradingCalendar` rows. Require Friday → Monday:

```python
assert resolve_next_common_trading_day(
    session,
    products=("jm", "rb"),
    source_trading_day=date(2026, 8, 28),
) == date(2026, 8, 31)
```

Add tests for missing product exchange, missing calendar row and exchanges returning different next dates.

- [ ] **Step 2: Write RED tests for the 18:20 expected-day cutover**

Require:

```text
Friday 18:19 Asia/Shanghai -> Friday
Friday 18:20 Asia/Shanghai -> Monday
Saturday any time -> Monday
Monday 08:00 Asia/Shanghai -> Monday
naive datetime -> EXPECTED_TRADING_DAY_UNAVAILABLE
```

- [ ] **Step 3: Run RED tests**

```bash
pytest -q services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py
```

Expected: FAIL on missing module.

- [ ] **Step 4: Implement with existing `Instrument` and `TradingCalendar` only**

Normalize products, require one exchange per product, derive the unique exchange set, query each exchange separately, and require all resolved dates equal. Do not use provider calls, Market Live, a new table or a calendar cache.

- [ ] **Step 5: Run tests and static checks**

```bash
pytest -q services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py
ruff check \
  services/quant-api/app/market_data/subing_daily_watch_calendar.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py
mypy services/quant-api/app/market_data/subing_daily_watch_calendar.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_watch_calendar.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py
git commit -m "feat(market): resolve daily watch trading day"
```

---

## Task 3: Build the Complete Active-Universe Daily Watch Ledger

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_watch.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_daily_watch.py`

**Interfaces:**
- Consumes: Task 1 trend seam, Task 2 next-day resolver, `ActualDominantResearchSegmentLoader`.
- Produces:

```python
class SubingDailyWatchDecision(StrEnum):
    LONG_WATCH = "long_watch"
    SHORT_WATCH = "short_watch"
    EXCLUDED = "excluded"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True, slots=True)
class SubingDailyWatchProduct:
    symbol: str
    product_name: str
    sector: str

@dataclass(frozen=True, slots=True)
class SubingDailyWatchItem: ...

@dataclass(frozen=True, slots=True)
class SubingDailyWatchSnapshot:
    source_trading_day: date
    target_trading_day: date
    generated_at: datetime
    items: tuple[SubingDailyWatchItem, ...]

class SubingDailyWatchBuilder:
    def __init__(
        self,
        *,
        segment_loader: ActualDominantResearchSegmentLoader,
        products: tuple[str, ...],
        product_metadata: Mapping[str, SubingDailyWatchProduct],
        expected_universe_size: int = 60,
    ) -> None: ...

    def build(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date,
        generated_at: datetime,
    ) -> SubingDailyWatchSnapshot: ...
```

- [ ] **Step 1: Write RED classification tests**

Create deterministic ready `SubingEmaTrendSnapshot` fixtures and test the pure classifier:

```python
assert classify_daily_watch(d1_long, h1_long).decision is LONG_WATCH
assert classify_daily_watch(d1_short, h1_short).decision is SHORT_WATCH
assert classify_daily_watch(d1_neutral, h1_long).reason_codes == ("D1_TREND_NEUTRAL",)
assert classify_daily_watch(d1_long, h1_short).reason_codes == ("D1_H1_DIRECTION_MISMATCH",)
```

Require zero slope and `close == ema21` to be neutral, not long/short.

- [ ] **Step 2: Write RED builder tests for segment-local input**

Use a fake segment loader that records requests. Require each product call to be exactly:

```python
loader.load(
    symbol=symbol,
    frequencies=(BarFrequency.D1, BarFrequency.H1),
    since=source_day,
    through=source_day,
)
```

Provide full segment-local bars and assert the latest D1/60m fact uses the source day and same physical contract/segment start.

- [ ] **Step 3: Write RED complete-ledger tests**

For a four-product test universe with `expected_universe_size=4`, return one long, one short, one excluded and one unavailable. Require:

```python
assert [item.symbol for item in snapshot.items] == ["a", "b", "c", "d"]
assert snapshot.counts == {
    "universe": 4,
    "long_watch": 1,
    "short_watch": 1,
    "excluded": 1,
    "unavailable": 1,
}
```

Add tests for duplicate products, missing metadata, wrong source trading day, D1/60m contract mismatch, probe identity failure and unexpected exceptions. Known data/identity failures become typed unavailable; programming errors propagate.

- [ ] **Step 4: Run RED tests**

```bash
pytest -q services/quant-api/tests/data_foundation/test_subing_daily_watch.py
```

Expected: FAIL on missing domain/builder.

- [ ] **Step 5: Implement the domain, classifier and builder**

Use only the latest ready D1 and 60m trend facts from the restored current segment. Map known conditions to the exact codes in the Spec. Never call:

```text
evaluate_subing_signal
resolve_subing_matched_signal
load_accepted_subing_calibration
MACD functions
volume/open-interest logic
```

Validate the full ledger in `SubingDailyWatchSnapshot.__post_init__` or one explicit validator.

- [ ] **Step 6: Run tests and static checks**

```bash
pytest -q \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py
ruff check \
  services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py
mypy services/quant-api/app/market_data/subing_daily_watch.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py
git commit -m "feat(subing): build daily watch ledger"
```

---

## Task 4: Add the Extension-Drive Immutable Store

**Files:**
- Create: `services/quant-api/app/market_data/subing_daily_watch_store.py`
- Create: `services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py`

**Interfaces:**
- Produces:

```python
SUBING_OBSERVATION_ROOT_ENV = "GUIYI_SUBING_OBSERVATION_ROOT"

class SubingDailyWatchStoreError(RuntimeError):
    def __init__(self, code: str) -> None: ...

class MountInspector(Protocol):
    def is_mount(self, path: Path) -> bool: ...
    def is_symlink(self, path: Path) -> bool: ...

@dataclass(frozen=True, slots=True)
class SubingDailyWatchPublishResult:
    status: Literal["published", "idempotent"]
    target_trading_day: date

class SubingDailyWatchStore:
    def publish(self, snapshot: SubingDailyWatchSnapshot) -> SubingDailyWatchPublishResult: ...
    def read_current(self) -> SubingDailyWatchSnapshot | None: ...
    def read_generation_status(self) -> Mapping[str, object] | None: ...
    def record_failure(...) -> None: ...

def resolve_subing_observation_root(
    *,
    environ: Mapping[str, str],
    inspector: MountInspector,
) -> Path: ...
```

- [ ] **Step 1: Write root-policy RED tests without touching `/Volumes`**

Use a fake inspector and assert rejection of:

```text
missing env
relative path
/Users/... path
/Volumes/<volume> not mounted
symlink volume
symlink existing parent
```

The root-policy tests may construct `Path('/Volumes/Fake/...')` values but must not call `mkdir` or write there.

- [ ] **Step 2: Write store RED tests using `tmp_path` directly**

Instantiate the core `SubingDailyWatchStore(tmp_path)` only after bypassing the production resolver. Cover:

```text
publish creates history/<target>.json + current.json + generation-status.json
all Decimal values serialize as strings
file modes are 0600 and directories 0700 where supported
same snapshot -> idempotent
same target, different bytes -> SNAPSHOT_IDENTITY_CONFLICT
new target older than current -> CURRENT_TARGET_REGRESSION
invalid existing current/history -> SNAPSHOT_INVALID
atomic replace failure preserves the last valid file
```

- [ ] **Step 3: Run RED tests**

```bash
pytest -q services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
```

Expected: FAIL on missing store.

- [ ] **Step 4: Implement canonical serialization and strict parsing**

Use:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

Append one trailing newline. Convert all `Decimal` values to plain decimal strings; convert dates/timestamps to ISO. Strictly validate schema version, projection version, formula version, item order, unique symbols and counts when reading.

- [ ] **Step 5: Implement same-directory atomic writes**

Use `tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")`, write/flush/fsync, `os.fchmod(descriptor, 0o600)` where supported, then `os.replace`. Clean only the exact temporary path on failure.

- [ ] **Step 6: Implement production root resolution**

Parse `/Volumes/<volume>/...`, validate the volume before creating feature directories, and provide no fallback. Do not reuse `PROJECT_ROOT/.run`.

- [ ] **Step 7: Run tests and static checks**

```bash
pytest -q services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
ruff check \
  services/quant-api/app/market_data/subing_daily_watch_store.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
mypy services/quant-api/app/market_data/subing_daily_watch_store.py
```

Expected: PASS and no real `/Volumes` write.

- [ ] **Step 8: Commit**

```bash
git add \
  services/quant-api/app/market_data/subing_daily_watch_store.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py
git commit -m "feat(subing): persist immutable daily watch"
```

---

## Task 5: Compose Generation and Expose the Current Read API

**Files:**
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/market_data/subing_daily_watch.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Create: `services/quant-api/tests/test_subing_daily_watch_api.py`
- Modify: `.env.example`

**Interfaces:**
- Produces composition functions:

```python
def build_subing_daily_watch_generator(session: Session) -> SubingDailyWatchGenerator: ...
def build_subing_daily_watch_current_service(session: Session) -> SubingDailyWatchCurrentService: ...
```

- Produces route:

```text
GET /api/v1/market/research/subing-daily-watch/current
```

- Produces response:

```python
class SubingDailyWatchCurrentResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    expected_target_trading_day: date | None
    latest_target_trading_day: date | None
    error_code: str | None
    snapshot: SubingDailyWatchWebSnapshotOut | None
```

- [ ] **Step 1: Write API RED tests**

Use `monkeypatch` on `app.api.market.build_subing_daily_watch_current_service` and cover:

```python
assert ready.status_code == 200
assert ready.json()["status"] == "ready"
assert ready.json()["snapshot"]["counts"]["universe"] == 60
assert "excluded_items" not in ready.json()["snapshot"]
```

Add 200 responses for missing, stale, invalid, root unavailable and expected-day unavailable. Assert no response contains a physical extension-drive path or exception text.

- [ ] **Step 2: Run API RED tests**

```bash
pytest -q services/quant-api/tests/test_subing_daily_watch_api.py
```

Expected: FAIL on missing route/schema/service.

- [ ] **Step 3: Add composition without side effects**

`build_subing_daily_watch_generator` must:

1. load active and operational products and require set equality;
2. build the read-only `MarketDataService` and shared segment loader;
3. obtain product metadata from `list_latest_dominants()`;
4. resolve the next common target day;
5. resolve the validated store from `GUIYI_SUBING_OBSERVATION_ROOT`;
6. create no files until `.run(source_trading_day)` is called.

`build_subing_daily_watch_current_service` may read the store and calendar but must not initialize RQData, Redis, a provider or any write path.

- [ ] **Step 4: Implement current read semantics**

`SubingDailyWatchCurrentService.current(now)` must:

```text
resolve expected target day
validate/read current.json
compare current target to expected
return ready projection or typed unavailable
```

The Web projection includes long, short and unavailable items plus counts; it omits excluded details.

- [ ] **Step 5: Add Pydantic DTOs and route**

Append Daily Watch DTOs near the existing Market Radar/Trend Focus DTOs. Keep `Decimal` fields as `Decimal`, allowing the existing FastAPI wire format to serialize exact values.

- [ ] **Step 6: Add the environment template entry**

Append to `.env.example`:

```text
# 苏冰今日观察：必须指向已挂载扩展盘，不提供系统盘 fallback
GUIYI_SUBING_OBSERVATION_ROOT=/Volumes/<mounted-volume>/guiyi-quant-data/observations/subing-daily-v1
```

Do not add a real machine path or modify `.env`.

- [ ] **Step 7: Run API/composition regressions**

```bash
pytest -q \
  services/quant-api/tests/test_subing_daily_watch_api.py \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/test_subing_api.py
ruff check \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/tests/test_subing_daily_watch_api.py
mypy services/quant-api/app
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  .env.example \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/market_data/subing_daily_watch.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/tests/test_subing_daily_watch_api.py
git commit -m "feat(api): expose current SuBing daily watch"
```

---

## Task 6: Replace Trend Focus on the Market Home Page

**Files:**
- Create: `apps/quant-web/src/components/market/SubingDailyWatch.vue`
- Create: `apps/quant-web/src/utils/subingDailyWatch.ts`
- Create: `apps/quant-web/tests/subingDailyWatch.test.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/e2e/market-radar.spec.mjs`

**Interfaces:**
- Produces `getSubingDailyWatchCurrent()`.
- Produces DTOs:

```ts
export type SubingDailyWatchDecision = 'long_watch' | 'short_watch'
export interface SubingDailyWatchCurrentResponse { ... }
```

- Component emits only:

```ts
open: [item: SubingDailyWatchItem]
```

- [ ] **Step 1: Write wire-normalization RED tests**

In `subingDailyWatch.test.ts`, create a ready payload with Decimal strings and require normalization to finite numbers for the current long/short facts while preserving counts, order and unavailable reasons.

Reject non-finite, missing-count and duplicate-symbol payloads with:

```text
SUBING_DAILY_WATCH_INVALID_RESPONSE
```

- [ ] **Step 2: Write six-item and reason-label RED tests**

Require:

```ts
assert.deepEqual(visibleDailyWatchItems(items, false).map(item => item.symbol), firstSix)
assert.equal(visibleDailyWatchItems(items, true).length, items.length)
assert.equal(subingDailyWatchReasonLabel('H1_HISTORY_INSUFFICIENT'), '60m 历史不足')
```

Use a stable fallback label `数据身份不可用` for unknown codes; do not display raw backend text.

- [ ] **Step 3: Run RED tests**

```bash
node --test apps/quant-web/tests/subingDailyWatch.test.ts
```

Expected: FAIL on missing types/helpers.

- [ ] **Step 4: Add TypeScript DTOs, normalization and API function**

Add `normalizeSubingDailyWatchCurrent()` in `types/market.ts` and call it from:

```ts
export function getSubingDailyWatchCurrent() {
  return request
    .get<never, SubingDailyWatchCurrentWireResponse>(
      '/market/research/subing-daily-watch/current',
    )
    .then(normalizeSubingDailyWatchCurrent)
}
```

Do not add a history endpoint.

- [ ] **Step 5: Implement `SubingDailyWatch.vue`**

Render:

```text
source/target day
four counts
long group, default 6
short group, default 6
excluded count only
unavailable collapsed list
```

Use component-local booleans for long/short/unavailable expansion. Unavailable rows contain no button and emit nothing.

- [ ] **Step 6: Replace Trend Focus state in `index.vue`**

Remove:

```text
MarketFocusList import/render
getMarketTrendFocus import/call
MarketTrendFocus types
trendFocusState / trendFocus error and invalidation
```

Add `dailyWatchState = useLatestResource({ fetch: getSubingDailyWatchCurrent })`.

Refresh matrix:

```text
refreshAll: Formal + Runtime + Radar + Daily Watch
visibility: Formal + Runtime + Daily Watch
```

Hide stale successful candidates when the latest Daily Watch request fails:

```ts
const dailyWatch = computed(() => (
  dailyWatchState.failed.value ? null : dailyWatchState.data.value
))
```

Pass a generic request-failed flag so the component shows unavailable rather than old candidates.

- [ ] **Step 7: Add the home-page route request in the component event**

Use a dedicated `openDailyWatch` function that pushes:

```ts
{
  name: 'market-chart',
  query: {
    symbol: item.symbol,
    series_kind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
    entry: 'subing-daily-watch',
  },
}
```

Do not reuse the generic Radar `openChart` preference frequency.

- [ ] **Step 8: Update Playwright home-page tests**

Intercept the new route and assert:

```text
Trend Focus heading absent
苏冰今日观察 present
counts present
only 6 cards per direction initially
expand reveals remaining cards
unavailable expands with no check button
typed unavailable leaves Runtime/Formal/Radar usable
network failure does not display prior candidates
```

- [ ] **Step 9: Run Web tests and build**

```bash
node --test apps/quant-web/tests/subingDailyWatch.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test apps/quant-web/e2e/market-radar.spec.mjs
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add \
  apps/quant-web/src/components/market/SubingDailyWatch.vue \
  apps/quant-web/src/utils/subingDailyWatch.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/tests/subingDailyWatch.test.ts \
  apps/quant-web/e2e/market-radar.spec.mjs
git commit -m "feat(web): show SuBing daily watch"
```

---

## Task 7: Add the One-Shot 15m SuBing Chart Entry

**Files:**
- Create: `apps/quant-web/src/utils/marketChartEntry.ts`
- Create: `apps/quant-web/tests/marketChartEntry.test.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Produces:

```ts
export interface SubingDailyWatchChartEntry {
  symbol: string
  seriesKind: 'actual_dominant'
  frequency: '15m'
  overlay: 'subing'
}

export function resolveSubingDailyWatchChartEntry(
  query: LocationQuery,
): SubingDailyWatchChartEntry | null
```

- [ ] **Step 1: Write strict parser RED tests**

Accept only the complete exact query. Reject:

```text
missing entry
wrong overlay
wrong series kind
wrong frequency
contract present
array-valued query fields
malformed symbol
```

- [ ] **Step 2: Run RED tests**

```bash
node --test apps/quant-web/tests/marketChartEntry.test.ts
```

Expected: FAIL on missing helper.

- [ ] **Step 3: Implement the pure parser**

Normalize symbol to lower case and require the existing product-code pattern. Return `null` for any partial/invalid entry; never partially force only overlay or frequency.

- [ ] **Step 4: Apply the override before refs are initialized**

In `chart.vue`:

```ts
const dailyWatchEntry = resolveSubingDailyWatchChartEntry(route.query)
const selectedOverlay = ref<ResearchOverlayId>(
  dailyWatchEntry?.overlay ?? initialMainChartPreferences.selectedOverlay,
)
const symbol = ref(dailyWatchEntry?.symbol ?? resolveInitialSymbol())
const seriesKind = ref<SeriesKind>(dailyWatchEntry?.seriesKind ?? resolveInitialSeriesKind())
const frequency = ref<MarketFrequency>(dailyWatchEntry?.frequency ?? resolveInitialFrequency())
```

Do not call `saveMainChartPreferences` for this initialization.

- [ ] **Step 5: Consume the one-shot query after the first accepted replace**

After the initial identity is accepted, `router.replace` should retain standard `symbol/series_kind/frequency/contract` and omit `entry` and `overlay`. Subsequent user changes continue through existing preference handlers.

- [ ] **Step 6: Add browser tests**

Set localStorage to a non-SuBing Overlay, open the exact Daily Watch URL, and assert:

```text
15m selected
SuBing selected
actual_dominant selected
localStorage selectedOverlay remains the previous value after load
manual user switch still works
normal Market URL still loads the saved preference
```

- [ ] **Step 7: Run tests and build**

```bash
node --test apps/quant-web/tests/marketChartEntry.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test apps/quant-web/e2e/market-research.spec.mjs
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/src/utils/marketChartEntry.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/marketChartEntry.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): open daily watch in SuBing 15m"
```

---

## Task 8: Run Daily Watch After a Successful Natural After-Market Update

**Files:**
- Modify: `services/quant-api/app/runtime_entry.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/tests/test_runtime_entry.py`
- Regression: `services/quant-api/tests/data_foundation/test_after_market.py`

**Interfaces:**
- Adds:

```python
DailyWatchGeneratorFactory = Callable[[Any], Any]
```

- `run_after_market` receives `daily_watch_generator_factory` and invokes `.run(source_trading_day)` only on passed.

- [ ] **Step 1: Write RED follow-up tests**

Expand `test_runtime_entry.py` with fake context-managed sessions, fake after-market result, generator and roll reconciler. Require:

```text
failed/skipped after-market -> generator not called
passed -> generator called exactly once with market_result.trading_day
passed + generator exception -> returned payload still passed
passed + generator exception + roll enabled -> roll still called
passed + generator success + roll disabled -> roll not called
```

Capture logs and require only the stable marker:

```text
SUBING_DAILY_WATCH_FOLLOWUP_FAILED
```

Do not log exception text or paths.

- [ ] **Step 2: Preserve the runtime import boundary test**

Keep and rerun:

```text
test_actual_runtime_launch_module_imports_no_offline_research
```

The new modules live under `app.market_data`; `app.research` must remain unloaded.

- [ ] **Step 3: Run RED tests**

```bash
pytest -q services/quant-api/tests/test_runtime_entry.py
```

Expected: FAIL because the factory/call is absent.

- [ ] **Step 4: Implement isolated generation in `run_after_market`**

Use a fresh session after the updater session closes:

```python
if market_result.status == "passed":
    try:
        with session_factory() as daily_watch_session:
            daily_watch_generator_factory(daily_watch_session).run(
                market_result.trading_day,
            )
    except Exception:  # sanitized, isolated follow-up
        _LOGGER.warning("SUBING_DAILY_WATCH_FOLLOWUP_FAILED")
```

Then execute the existing roll follow-up independently. Return the original `market_result.as_payload()`.

- [ ] **Step 5: Wire the default composition factory**

Import only `build_subing_daily_watch_generator` from `app.market_data.composition`. Do not modify `AfterMarketUpdater` or `HistoricalDataManager` to depend on the feature.

- [ ] **Step 6: Run Runtime and after-market regressions**

```bash
pytest -q \
  services/quant-api/tests/test_runtime_entry.py \
  services/quant-api/tests/data_foundation/test_after_market.py
ruff check \
  services/quant-api/app/runtime_entry.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/test_runtime_entry.py
mypy services/quant-api/app/runtime_entry.py \
  services/quant-api/app/market_data/composition.py
```

Expected: PASS. No real after-market or extension-drive write occurs.

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/runtime_entry.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/tests/test_runtime_entry.py
git commit -m "feat(runtime): generate SuBing daily watch post-close"
```

---

## Task 9: Full Verification, Canonical Closeout and Independent Review

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `STATUS.md`
- Review all files changed by Tasks 1–8.

**Interfaces:**
- Produces a code-complete develop candidate only.
- Does not produce a release, tag, Runtime promotion, environment mutation or real observation file.

- [ ] **Step 1: Update stable product boundary only after code is true**

In `PROJECT_SOURCE.md`, replace the homepage Trend Focus product statement with the stable Daily Watch contract:

```text
- post-after-market D1+60m EMA21 current-target observation
- active60 complete ledger on configured extension-drive root
- current-only Web/API
- no Alert/DB/Redis/Canonical/order path
```

Keep the existing Trend Focus backend as retained read-only code, not the active homepage product.

- [ ] **Step 2: Record the long-term decision**

In `DECISIONS.md`, replace the `Web B1` row with a concise decision covering:

```text
SuBing Daily Watch is the homepage priority context;
D1+60m sign-only admission;
immutable extension-drive ledger;
no ranking, stale fallback or Alert Scope coupling.
```

Do not copy implementation details better owned by the Spec.

- [ ] **Step 3: Update current status without overclaiming**

`STATUS.md` may state:

```text
CODE_COMPLETE / TEST_COMPLETE on develop candidate
exact reviewed head
verification results
not released
not Runtime-promoted
GUIYI_SUBING_OBSERVATION_ROOT not configured by this task
no real history/current generated
natural after-market evidence pending
Alert Scope unchanged
```

Do not claim `RUNTIME_READY` or production validation.

- [ ] **Step 4: Run focused backend suite**

```bash
pytest -q \
  services/quant-api/tests/test_subing_ema_trend.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_calendar.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch_store.py \
  services/quant-api/tests/test_subing_daily_watch_api.py \
  services/quant-api/tests/test_runtime_entry.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_actual_dominant_research.py \
  services/quant-api/tests/data_foundation/test_after_market.py
```

Expected: PASS.

- [ ] **Step 5: Run full backend and engineering validation**

Use current `TESTING.md` commands. At minimum:

```bash
pytest -q services/quant-api/tests
pytest -q tests/engineering
ruff check services/quant-api/app services/quant-api/tests tests/engineering
mypy services/quant-api/app
```

If isolated PostgreSQL tests are required by current `TESTING.md`, run them exactly as documented. No migration is expected.

- [ ] **Step 6: Run full Web validation**

```bash
node --test \
  apps/quant-web/tests/subingDailyWatch.test.ts \
  apps/quant-web/tests/marketChartEntry.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test \
  apps/quant-web/e2e/market-radar.spec.mjs \
  apps/quant-web/e2e/market-research.spec.mjs
```

Then run the complete Playwright command required by current `TESTING.md`.

- [ ] **Step 7: Run contract and secret checks**

```bash
python scripts/engineering/secret_scan.py
git diff --check
git status --short
```

Run current OpenSpec validation only if `TESTING.md` requires it. This feature does not create a new OpenSpec unless current canonical ownership proves one is required.

- [ ] **Step 8: Self-review the exact diff**

Verify:

```text
no MACD/volume/OI/N/JDJ admission
no score/rank/recommendation
no real /Volumes path or credentials
no DB/Redis/migration
no Alert Scope/transport changes
no stale candidate fallback
no Trend Focus backend deletion
no after-market result contamination
no main/tag/Runtime operation
```

- [ ] **Step 9: Commit canonical closeout**

```bash
git add PROJECT_SOURCE.md DECISIONS.md STATUS.md
git commit -m "docs: record SuBing daily watch candidate"
```

- [ ] **Step 10: Open an independent Review session**

The reviewer must read the Spec, plan, canonical files and full diff, then issue one of:

```text
允许集成 develop
要求修正后再集成
阻塞
```

Review must specifically inspect future leakage, segment identity, extension-drive fail-closed behavior, immutable history, Runtime failure isolation and stale Web behavior.

- [ ] **Step 11: Integrate only after approval**

After `允许集成 develop`:

```text
task branch -> develop
verify develop contains the reviewed integration
push develop if requested
remove merged task worktree/branch
```

Do not publish `main`, create a tag or switch Runtime.

---

## Post-Implementation Gates Not Authorized by This Plan

### Release Gate

A separate user approval is required for:

```text
develop -> release candidate -> main + annotated tag
```

### Runtime Promotion Gate

A separate approval after release is required for:

```text
configure GUIYI_SUBING_OBSERVATION_ROOT
switch exact-tag Runtime
reload affected API/Web/after-market services
```

Release approval does not authorize Runtime promotion.

### First Natural Evidence Gate

After an approved Runtime promotion:

1. do not manually invoke or backfill after-market by default;
2. wait for the next natural supervised after-market run;
3. verify the after-market result remains passed;
4. verify extension-drive `history/<target>.json`, `current.json`, and status exist with 60 unique items;
5. verify API target day and Web counts/list;
6. verify no Alert Scope or notification behavior changed.

The first natural result is operational evidence only. It does not prove profitability, strategy validity or suitability for automatic trading.
