# Market Home 盘后派生快照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Market Home completed D1/W1 overview 的常态读取从约 120 次 historical query 的 read-time compute 改为 shared Canonical-root derived projection，同时保证任何 projection 缺失、损坏、同日 refresh/update 或写失败都只能造成性能退化，不能造成旧事实误命中。

**Architecture:** `MarketHomeOverviewService` 继续作为唯一 compute authority。Projection 固定在 `<canonical_root>/.derived/market-home-overview.json`。正式 `data update/refresh --apply` 与自然 after-market 在 manager action 前先失效旧 projection；API projection hit 直接返回，miss 回退现有 compute 且永不写；自然 after-market 仅在 `canonical_updated + rank1/Live reconciliation + cleanup` 全部完成后 best-effort 重建 projection。

**Tech Stack:** Python 3.13、FastAPI、Pydantic v2、SHA-256、UTF-8 JSON、`tempfile + fsync + os.replace`、pytest、Ruff、Mypy、OpenSpec。

**Spec:** `docs/tasks/2026-09-02-market-home-derived-snapshot-spec.md`

## Global Constraints

- 事实基线：`develop@fa04c5524b57a3512d7163612972099eda96e0c4`；提交 PR 前必须重新比较最新 `develop`。
- Lane 3：本任务只授权仓库代码、测试、文档、task branch 与 PR；不得执行真实 `data ... --apply`、after-market、RQData、Canonical、production DB/Redis/Scope/notification、main/tag/Release/Runtime promotion。
- `MarketHomeOverviewService` 是唯一 D1/W1 compute authority；禁止复制指标或 actual-dominant 逻辑。
- Projection 不是 Canonical/Catalog/策略事实；可删除、可重建。
- Projection path 跟随 shared canonical root，禁止 checkout-local `.run` 方案。
- 所有正式 apply 入口必须在 manager action 前 invalidate projection；invalidator 失败必须在真实 mutation 前停止。
- API miss 必须保留原 compute correctness，但不得 publish/write projection。
- after-market refresh failure只影响性能，不 retry、不发 projection-specific notification、不改变已成功 core maintenance。
- natural refresh 默认关闭；只有 owner-written exact activation marker 才允许 factory 装配 refresh callback，本任务不创建 marker 或 production projection。
- 不新增 Redis cache、PostgreSQL/Alembic、queue、worker、线程池或 Web UI 改动。
- `PROJECT_SOURCE.md` 与 `STATUS.md` 不修改。

---

### Task 1: 冻结 Market Home authority identity

**Files:**
- Modify: `services/quant-api/app/market_data/market_home_overview.py`
- Test: `services/quant-api/tests/data_foundation/test_market_home_projection.py`

**Interfaces:**
- Consumes: existing validated products/taxonomy/latest_complete_day.
- Produces: `MarketHomeAuthorityIdentity` and `MarketHomeOverviewService.authority_identity()`.

- [ ] **Step 1: Write failing identity tests**

Cover deterministic digest and changes caused by product order, taxonomy name and taxonomy sector.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  -k authority_identity
```

- [ ] **Step 3: Implement identity**

```python
@dataclass(frozen=True, slots=True)
class MarketHomeAuthorityIdentity:
    target_as_of: date
    authority_digest: str
```

Digest input exactly:

```python
records = [
    {
        "symbol": symbol,
        "name": taxonomy[symbol].name,
        "sector": taxonomy[symbol].sector,
    }
    for symbol in products
]
json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
sha256(encoded).hexdigest()
```

Refactor target day resolution into one helper so existing public error code remains unchanged.

- [ ] **Step 4: Run GREEN and commit**

Run full Market Home overview/projection targeted tests; commit only after output is actually read.

---

### Task 2: 实现 strict shared-root projection store

**Files:**
- Create: `services/quant-api/app/market_data/market_home_projection.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Test: `services/quant-api/tests/data_foundation/test_market_home_projection.py`
- Test: `services/quant-api/tests/test_market_home_projection_invalidation.py`

**Interfaces:**
- Produces:
  - `market_home_projection_path(canonical_root)`
  - `MarketHomeProjectionStore.load/invalidate/publish`
  - `MarketHomeProjection.read/refresh`
  - `market_home_response(snapshot)` pure mapper
  - `build_market_home_projection(session)`

- [ ] **Step 1: Write failing store tests**

Cover:

```text
round trip
Decimal/null wire preservation
missing -> miss
projection symlink -> miss
.derived parent symlink -> miss/invalidation failure
empty/oversize/corrupt -> miss
schema/target/digest/payload mismatch -> miss
atomic replace failure preserves old file and removes temp
projection hit -> zero snapshot calls
miss -> one snapshot call and zero file writes
target race -> refuse publish
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
```

- [ ] **Step 3: Implement path and envelope**

Path:

```text
canonical_root.resolve()/.derived/market-home-overview.json
```

Envelope:

```text
schema_version = 1
generated_at aware datetime
target_as_of
authority_digest 64 lowercase hex
payload = strict MarketHomeOverviewResponse
```

Read constraints:

```text
parent not symlink
file not symlink
regular file
0 < size <= 2 MiB
strict Pydantic validation
exact target/digest
payload target/data_as_of match envelope
```

- [ ] **Step 4: Implement atomic publish**

```text
validate
→ mkdir .derived
→ reject symlink parent
→ same-dir mkstemp
→ write UTF-8
→ flush/fsync
→ os.replace
→ cleanup temp
```

- [ ] **Step 5: Implement pure response mapper/read/refresh**

`read()` is projection-first compute fallback. `refresh()` computes once and publishes only if target identity remained stable.

- [ ] **Step 6: Run GREEN and commit**

Include targeted Mypy/Ruff on projection module before commit.

---

### Task 3: API projection-first + manual apply invalidation

**Files:**
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/guiyi_cli/data_commands.py`
- Modify: `services/quant-api/tests/test_market_home_api.py`
- Create: `services/quant-api/tests/test_market_home_projection_api.py`
- Create: `services/quant-api/tests/test_market_home_projection_invalidation.py`

**Interfaces:**
- HTTP remains `GET /api/v1/market/research/home-overview`.
- CLI commands remain unchanged; only `update/refresh --apply` gain pre-action projection invalidation.

- [ ] **Step 1: Write failing API tests**

Router must call `build_market_home_projection(session).read()` once and preserve existing `MarketHomeOverviewError -> 409` mapping.

- [ ] **Step 2: Write failing CLI invalidation tests**

For update and refresh:

```text
apply=True  -> projection absent when manager action starts
dry-run     -> projection untouched
invalidator failure -> manager action not called
```

- [ ] **Step 3: Implement API switch**

Remove duplicated Snapshot → response mapping from router and reuse `market_home_response()`.

- [ ] **Step 4: Implement CLI invalidation**

After `build_request()` and before manager action:

```python
if isinstance(request, (UpdateRequest, RefreshRequest)) and request.apply:
    MarketHomeProjectionStore(
        market_home_projection_path(manager.catalog.canonical_root)
    ).invalidate()
```

Audit/dry-run remain read-only.

- [ ] **Step 5: Run GREEN and commit**

Run API + CLI targeted regression and static checks.

---

### Task 4: 自然 after-market invalidation / refresh ordering

**Files:**
- Modify: `services/quant-api/app/market_data/after_market.py`
- Create: `services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py`

**Interfaces:**
- Existing `AfterMarketResult`、status schema、`canonical_updated` payload and notification contract remain unchanged.

- [ ] **Step 1: Write failing ordering tests**

Required behavior:

```text
provider not ready -> no invalidate, no manager, no refresh
provider ready -> invalidate before manager.update
manager failed -> projection stays invalidated, no refresh
invalidation failure -> manager not called
passed/noop -> canonical_updated/reconcile/cleanup complete, then refresh exactly once
refresh failure -> AfterMarketResult still passed
refresh failure log contains exception_type only
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py
```

- [ ] **Step 3: Implement testable callbacks**

`AfterMarketUpdater` adds optional:

```python
market_home_projection_invalidate: Callable[[], None] | None
market_home_projection_refresh: Callable[[], object] | None
```

Existing direct constructors remain compatible via default `None`.

- [ ] **Step 4: Implement final ordering**

`_attempt()` after provider readiness but before manager update calls invalidator. It does not refresh projection.

`run()` calls refresh only after `_attempt()` returns success, which proves the existing `canonical_updated` / reconciliation / cleanup path is complete.

Factory refresh callback must acquire the existing Catalog maintenance lease for the complete compute/check/publish interval; unavailable lease skips best-effort refresh.

- [ ] **Step 5: Factory composition**

Factory uses manager Catalog canonical root for invalidator and lazy `build_market_home_projection(session).refresh()` for publisher. No projection composition before provider readiness/manager success.

- [ ] **Step 6: Run GREEN and commit**

Run after-market, runtime-entry and CLI relevant regressions.

---

### Task 5: Canonical sync, verification, review, PR

**Files:**
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `openspec/specs/market-home-overview/spec.md`
- Modify: `TESTING.md`
- Modify: this Spec/Plan if Review changed implementation
- Do not modify: `PROJECT_SOURCE.md`, `STATUS.md`

**Interfaces:** no new product surface.

- [ ] **Step 1: Synchronize canonical docs**

Freeze:

```text
MarketHomeOverviewService = only compute authority
shared canonical-root .derived projection = removable performance read model
API hit read-only / miss compute-only
all official apply paths invalidate first
after-market refresh after core success
```

- [ ] **Step 2: Run targeted verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_market_home_projection.py \
  services/quant-api/tests/data_foundation/test_market_home_projection_after_market.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py \
  services/quant-api/tests/test_market_home_api.py \
  services/quant-api/tests/test_market_home_projection_api.py
```

- [ ] **Step 3: Run full non-external verification**

```bash
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

这些命令不得连接真实 RQData、production PostgreSQL/Redis 或执行 `--apply`。

- [ ] **Step 4: Manual performance acceptance remains separate**

未来仅在明确授权的本地 Runtime 环境测：

```text
projection decode/validation < 50ms
projection-hit HTTP endpoint < 200ms
```

普通 unit test 不用时间断言冒充真实性能证据。

- [ ] **Step 5: Exact-head Review**

Review axes：

```text
authority separation
same-day rewrite invalidation
shared-root identity
API read-only behavior
atomic/path safety
after-market canonical_updated ordering
failure isolation
no hidden retry/notification
no Redis/DB/cache framework
no MarketDataService rewrite
tests/canonical scope
```

Critical/Important 全部修复并重跑受影响验证。

- [ ] **Step 6: Create Draft PR to develop**

PR body 必须包含：

```text
Refs #315
exact base/head
Review amendment (.run -> canonical-root/.derived; invalidation before apply)
changed files
hit/miss behavior
manual apply invalidation
after-market ordering
实际运行过的验证输出；未运行的必须明确 pending
manual benchmark status
review findings/fixes
no production mutation
```

不得自动 merge；不得触碰 main/tag/Release/Runtime。
