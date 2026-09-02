# Market Home 盘后派生快照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Market Home completed D1/W1 overview 从常态 read-time compute 改为 after-market update-time runtime-local derived projection，并在 projection miss 时保留现有只读 compute fallback。

**Architecture:** `MarketHomeOverviewService` 保持唯一计算 authority；新增 `.run/market-home-overview.json` strict/atomic projection store。after-market 在 Canonical maintenance `passed/noop` 后 best-effort refresh projection；overview API 先按 exact authority identity 读 projection，miss/corrupt/mismatch 时调用原 `snapshot()`，API 永不写 projection。

**Tech Stack:** Python 3.13、FastAPI、Pydantic v2、dataclasses、SHA-256、UTF-8 JSON、atomic `tempfile + fsync + os.replace`、pytest、Ruff、Mypy、OpenSpec。

**Spec:** `docs/tasks/2026-09-02-market-home-derived-snapshot-spec.md`

## Global Constraints

- 任务基线为执行时最新 `develop`；本 Plan 起草事实基线为 `fa04c5524b57a3512d7163612972099eda96e0c4`。
- Lane 3：代码/测试可以进入 task branch；不得执行真实 after-market、production RQData/Canonical/DB/Redis/Scope/notification、main/tag/Release/Runtime promotion。
- `MarketHomeOverviewService` 是唯一 D1/W1 compute authority；不得复制指标或 actual-dominant 逻辑。
- Projection 固定为 `PROJECT_ROOT/.run/market-home-overview.json`，schema_version `1`，单文件、runtime-local、可删除、可重建。
- API projection miss 必须 compute fallback，但不得 publish/write projection。
- Projection refresh failure 只影响性能，不得把已成功 Canonical maintenance 改判失败，不 retry、不通知。
- 不新增 Redis cache、PostgreSQL、Alembic、derived external root、queue、worker、thread pool、Web UI 改动。
- `STATUS.md` 不修改。

---

### Task 1: 冻结 Market Home authority identity

**Files:**
- Modify: `services/quant-api/app/market_data/market_home_overview.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_home_overview.py`

**Interfaces:**
- Consumes: existing validated `products`, `taxonomy`, `latest_complete_day` dependencies inside `MarketHomeOverviewService`.
- Produces: `MarketHomeAuthorityIdentity(target_as_of: date, authority_digest: str)` and `MarketHomeOverviewService.authority_identity() -> MarketHomeAuthorityIdentity`.

- [ ] **Step 1: Write failing identity tests**

Add tests that construct the existing fake service and assert:

```python
identity = service.authority_identity()
assert identity.target_as_of == TARGET
assert len(identity.authority_digest) == 64
assert identity.authority_digest == service.authority_identity().authority_digest
```

Add independent service instances proving digest changes for:

```text
products order change
taxonomy.name change
taxonomy.sector change
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py
```

Expected: fail because `authority_identity` / `MarketHomeAuthorityIdentity` do not exist.

- [ ] **Step 3: Implement deterministic identity**

Add imports:

```python
from hashlib import sha256
import json
```

Add:

```python
@dataclass(frozen=True, slots=True)
class MarketHomeAuthorityIdentity:
    target_as_of: date
    authority_digest: str
```

Refactor target resolution into:

```python
def _target_as_of(self) -> date:
    try:
        return self._latest_complete_day(self._products)
    except InfrastructureError as exc:
        raise MarketHomeOverviewError("MARKET_HOME_TARGET_AS_OF_UNAVAILABLE") from exc
```

Add:

```python
def authority_identity(self) -> MarketHomeAuthorityIdentity:
    records = [
        {
            "symbol": symbol,
            "name": self._taxonomy[symbol].name,
            "sector": self._taxonomy[symbol].sector,
        }
        for symbol in self._products
    ]
    encoded = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return MarketHomeAuthorityIdentity(
        target_as_of=self._target_as_of(),
        authority_digest=sha256(encoded).hexdigest(),
    )
```

Change `snapshot()` to call `self._target_as_of()` so target error mapping remains single-source.

- [ ] **Step 4: Run GREEN**

Run the Task 1 command and existing `test_market_home_api.py`.

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/market_data/market_home_overview.py \
        services/quant-api/tests/data_foundation/test_market_home_overview.py
git commit -m "feat(market): add Market Home projection identity"
```

---

### Task 2: 实现 strict atomic projection store 和 read model

**Files:**
- Create: `services/quant-api/app/market_data/market_home_projection.py`
- Create: `services/quant-api/tests/data_foundation/test_market_home_projection.py`
- Modify: `services/quant-api/app/market_data/composition.py`

**Interfaces:**
- Consumes: `MarketHomeOverviewService.authority_identity()`, `MarketHomeOverviewService.snapshot()`, existing `MarketHomeOverviewResponse` schema.
- Produces:
  - `DEFAULT_MARKET_HOME_PROJECTION_PATH`
  - `MarketHomeProjectionError`
  - `market_home_response(snapshot) -> MarketHomeOverviewResponse`
  - `MarketHomeProjectionStore.load(identity) -> MarketHomeOverviewResponse | None`
  - `MarketHomeProjectionStore.publish(identity, payload, generated_at) -> None`
  - `MarketHomeProjection.read() -> MarketHomeOverviewResponse`
  - `MarketHomeProjection.refresh() -> MarketHomeOverviewResponse`
  - `build_market_home_projection(session) -> MarketHomeProjection`

- [ ] **Step 1: Write failing store/read-model tests**

Tests must cover:

```text
round trip
missing file -> None
symlink -> None
empty file -> None
>2MiB -> None
corrupt JSON -> None
wrong schema -> None
wrong target -> None
wrong digest -> None
payload target/data_as_of mismatch -> None
projection hit does not call service.snapshot()
projection miss calls snapshot()
refresh writes valid current envelope
refresh refuses target identity race
os.replace failure preserves last-good file and removes temp
```

Use a fake service with counters:

```python
class _Service:
    def __init__(self, identity, snapshot):
        self.identity = identity
        self.snapshot_value = snapshot
        self.snapshot_calls = 0

    def authority_identity(self):
        return self.identity

    def snapshot(self):
        self.snapshot_calls += 1
        return self.snapshot_value
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_projection.py
```

Expected: import/module missing.

- [ ] **Step 3: Implement projection module**

Use:

```python
DEFAULT_MARKET_HOME_PROJECTION_PATH = (
    PROJECT_ROOT / ".run" / "market-home-overview.json"
)
_MAX_PROJECTION_BYTES = 2 * 1024 * 1024
```

Envelope:

```python
class MarketHomeProjectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    generated_at: datetime
    target_as_of: date
    authority_digest: str
    payload: MarketHomeOverviewResponse

    @model_validator(mode="after")
    def validate_identity(self):
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if not re.fullmatch(r"[0-9a-f]{64}", self.authority_digest):
            raise ValueError("authority_digest invalid")
        if (
            self.payload.target_as_of != self.target_as_of
            or self.payload.data_as_of != self.target_as_of
        ):
            raise ValueError("payload identity mismatch")
        return self
```

Pure mapper must contain the exact current API mapping for summary/items/sectors and no I/O.

`load()` must reject symlink/non-file/size bounds before reading, catch only file/JSON/Pydantic validation failures and return `None`.

`publish()` must construct/validate the envelope before touching disk, then same-directory `mkstemp → write → flush → fsync → os.replace`; on failure raise `MarketHomeProjectionError("MARKET_HOME_PROJECTION_WRITE_FAILED")`, preserve previous current file, and cleanup temp.

`MarketHomeProjection.read()`:

```python
identity = self.service.authority_identity()
cached = self.store.load(identity)
if cached is not None:
    return cached
return market_home_response(self.service.snapshot())
```

`refresh()`:

```python
identity = self.service.authority_identity()
response = market_home_response(self.service.snapshot())
if response.target_as_of != identity.target_as_of:
    raise MarketHomeProjectionError("MARKET_HOME_PROJECTION_IDENTITY_CHANGED")
self.store.publish(identity, response, generated_at=self.now())
return response
```

Composition:

```python
def build_market_home_projection(session: Session) -> MarketHomeProjection:
    return MarketHomeProjection(
        service=build_market_home_overview_service(session),
        store=MarketHomeProjectionStore(DEFAULT_MARKET_HOME_PROJECTION_PATH),
    )
```

- [ ] **Step 4: Run GREEN**

Run projection tests + existing overview domain/API tests + Mypy/Ruff on touched modules.

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/market_data/market_home_projection.py \
        services/quant-api/app/market_data/composition.py \
        services/quant-api/tests/data_foundation/test_market_home_projection.py
git commit -m "feat(market): add atomic Market Home projection"
```

---

### Task 3: Switch overview API to projection-first read

**Files:**
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/tests/test_market_home_api.py`

**Interfaces:**
- Consumes: `build_market_home_projection(session).read()`.
- Produces: unchanged `GET /api/v1/market/research/home-overview -> MarketHomeOverviewResponse`.

- [ ] **Step 1: Write failing API tests**

Replace API service monkeypatch with projection monkeypatch and cover:

```python
response = client.get("/api/v1/market/research/home-overview")
assert response.status_code == 200
assert projection.read_calls == 1
```

Add projection fake raising `MarketHomeOverviewError("MARKET_HOME_DATA_INTEGRITY_ERROR")` and assert existing typed 409 remains unchanged.

Add a projection integration-style unit test with a real `MarketHomeProjectionStore(tmp_path/...)` and fake service showing exact hit avoids `snapshot()` and miss calls it once. This may live in Task 2 test file if already covered there; API test only proves router composition.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_home_api.py
```

Expected: API still calls `build_market_home_overview_service`.

- [ ] **Step 3: Implement minimal API switch**

Import `build_market_home_projection` and replace endpoint body with:

```python
try:
    return build_market_home_projection(session).read()
except MarketHomeOverviewError as exc:
    raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
```

Remove no-longer-used `MarketHomeItemOut`, `MarketHomeSectorOut`, `MarketHomeSummaryOut` imports from the router.

Do not catch `MarketHomeProjectionError` on read: `store.load()` converts invalid/missing projection to miss, while compute fallback retains existing public errors.

- [ ] **Step 4: Run GREEN**

Run Task 3 test and all Market Home targeted backend tests.

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/api/market.py \
        services/quant-api/tests/test_market_home_api.py
git commit -m "perf(api): read Market Home projection before compute"
```

---

### Task 4: Refresh projection after successful/noop after-market maintenance

**Files:**
- Modify: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/tests/data_foundation/test_after_market.py`

**Interfaces:**
- Consumes: lazy `build_market_home_projection(manager.catalog.session).refresh()` callback.
- Produces: after-market best-effort performance refresh; existing `AfterMarketResult` contract unchanged.

- [ ] **Step 1: Write failing after-market tests**

Extend `_updater()` to inject `projection_refresh` recorder.

Required assertions:

```text
passed -> ["projection", "canonical_updated"] ordering
noop -> projection exactly once
NON_TRADING_DAY -> zero projection calls
RQData not ready -> zero projection calls
update failure -> zero projection calls
projection exception -> result still passed, no notice, live reconciliation continues
projection exception emits safe warning containing exception type but not exception message
```

Use an event list shared by the projection recorder and fake live store so ordering is observable without implementation-specific mocks.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_after_market.py
```

Expected: `AfterMarketUpdater` has no projection refresh seam.

- [ ] **Step 3: Implement best-effort refresh**

Constructor adds:

```python
market_home_projection_refresh: Callable[[], object] | None
```

After successful/noop manager result and before existing `live_store.publish_state(...)`:

```python
self._refresh_market_home_projection()
```

Helper:

```python
def _refresh_market_home_projection(self) -> None:
    if self.market_home_projection_refresh is None:
        return
    try:
        self.market_home_projection_refresh()
    except Exception as exc:  # noqa: BLE001 - derived performance projection is isolated
        _LOGGER.warning(
            "market_home_projection_refresh_failed exception_type=%s",
            type(exc).__name__,
        )
```

`build_after_market_updater()` must stay lazy so projection composition cannot block startup or pre-maintenance:

```python
def refresh_market_home_projection():
    from app.market_data.composition import build_market_home_projection

    session = manager.catalog.session
    build_market_home_projection(session).refresh()
```

Pass the callable to `AfterMarketUpdater`.

Do not alter `AfterMarketResult`, status JSON schema, notification rules, retry rules or current `canonical_updated` payload.

- [ ] **Step 4: Run GREEN**

Run after-market tests plus runtime-entry/CLI tests that exercise after-market factory capability boundaries.

- [ ] **Step 5: Commit**

```bash
git add services/quant-api/app/market_data/after_market.py \
        services/quant-api/tests/data_foundation/test_after_market.py
git commit -m "perf(market): refresh home projection after maintenance"
```

---

### Task 5: Canonical sync, regression verification, exact-head review and PR

**Files:**
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `openspec/specs/market-home-overview/spec.md`
- Modify: `TESTING.md`
- Do not modify: `STATUS.md`, `PROJECT_SOURCE.md`

**Interfaces:** no new runtime interface; documents the completed architecture.

- [ ] **Step 1: Update canonical docs only after source tests are green**

`DECISIONS.md` Market Home row becomes conceptually:

```text
牛哇式有限图标 + update-time runtime-local derived overview projection + current HTDY Event
```

Invariant states projection is removable/rebuildable and never authority; API miss computes from existing authority.

`docs/ARCHITECTURE.md` adds:

```text
EOD -> MarketHomeOverviewService -> MarketHomeProjection(.run JSON)
MarketHomeProjection -> Market API -> Web
Market API --miss--> MarketHomeOverviewService
```

OpenSpec replaces the old requirement that every endpoint request composes all D1/W1 reads. New requirement: exact projection hit must avoid historical bar reads; invalid/missing projection falls back compute; HTTP endpoint remains read-only.

`TESTING.md` targeted command:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_market_home_api.py
```

- [ ] **Step 2: Run complete relevant verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_market_home_api.py

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

No production database, Redis, RQData or real after-market command may be used for verification.

- [ ] **Step 3: Manual performance Gate remains external/read-only**

Only in an explicitly authorized local Runtime read environment later, measure an exact projection hit. Acceptance target:

```text
store decode/validation < 50ms
HTTP projection hit    < 200ms
```

Do not claim these targets from unit-test timing.

- [ ] **Step 4: Exact-head review**

Review axes:

```text
authority separation
projection never becomes Canonical
API remains read-only
identity invalidation correctness
atomic last-good preservation
after-market failure isolation
no hidden retry/notification
no Redis/DB/cache framework
no MarketDataService formula/read rewrite
test coverage
canonical consistency
```

Fix every Critical/Important finding and rerun affected verification.

- [ ] **Step 5: Create Draft PR to develop**

PR must include:

```text
Refs #315
exact base/head
changed files
projection file/schema/identity
hit/miss behavior
after-market ordering/failure behavior
actual verification output
manual benchmark status
review findings/fixes
no production mutation declaration
```

Do not merge automatically. No main/tag/Release/Runtime action.
