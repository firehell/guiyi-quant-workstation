# HTDY 全周期 × Active60 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 HTDY original 数学公式、不增加自动交易或重型基础设施的前提下，让当前 operational universe 的全部品种在 `1m / 5m / 15m / 30m / 60m / 1d / 1w` 都能显示 HTDY，并让 Web 上唯一一个 HTDY 开关精确控制当前 `symbol × current frequency` 的 Alert Scope；D1/W1 在盘后 Canonical 更新完成后检查，同一时刻不同已开启周期分别形成 Event 和分别通知。

**Architecture:** 继续保留单一 `htdy_original_15m` 稳定 Rule identity、单一 HTDY original Kernel 与现有 Alert Application Domain。HTDY Scope 在既有 `alert_rules` 增加一个轻量 `scope_product_frequencies` JSON map；SuBing 继续独占原 `scope_products`。日内五周期复用已有 completed Live Bar Pub/Sub，D1/W1 复用盘后 Canonical 更新后的 `market:state(reason=canonical_updated)` seam。AlertEvent 存储唯一键扩大为包含 frequency，但 SuBing 的 bar-level formal business identity 继续由 Service fail-closed 保护。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Alembic / PostgreSQL / Redis / NumPy / pytest / Vue 3 / TypeScript 6 / Naive UI / Node test / Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`

## Global Constraints

- 本任务是 Lane 3：指标可信口径、Alert Runtime、数据库 migration contract 同时变化。
- 实现必须从包含已批准 Spec 的最新 `develop` 创建独立 task branch/worktree；不得在本 Plan 文档分支直接实现。
- 推荐实现 branch：`feature/htdy-all-frequency-active60`；源 branch：最新 `develop`；完成后目标仍是 `develop`。
- 实现阶段可以编写 Alembic migration，并且只允许在仓库指定的隔离 PostgreSQL 测试库执行 migration tests。
- 不执行 production migration；不修改真实 `scope_products` / `scope_product_frequencies`；不发送真实 PushPlus；不切换 Runtime；不发布 `main`；不创建 tag；不运行真实 canary；不启用订单能力。
- `auto_order=false` 不得改变。
- 不修改 `packages/quant-core/guiyi_quant/indicators/htdy_original.py` 的公式、XMA、25-period、三连 K 线观察语义、24-bar future dependency 或 repaint metadata。
- 不修改冻结的 JM/15m `RealtimeRepaintingObservationPolicy` / `ClosedBarRealtimeObservationPolicy` 及其 exact identity/hash。
- 不新增 Scope 表、scheduler、queue、retry、replay、backfill、outbox、fallback、跨周期通知合并或第二套 D1/W1 聚合。
- Rule code 继续为 `htdy_original_15m`；该字符串是 legacy stable identity，不再代表 capability 只支持 15m。
- 图表可以显示 `continuous / actual_dominant / contract`；Alert 始终只使用 `actual_dominant + rank1`。
- `STATUS.md` 只能记录真正发生的实现、验证、Review、集成、release、Runtime 事实；Plan/代码存在不能提前推导 Ready。
- 每个 Task 使用 TDD：先写或修改失败测试，运行确认失败，再写最小实现，运行定向测试确认通过，再提交该 Task。
- 每个 commit 只包含当前 Task 的文件；禁止全量暂存无关工作树修改。

---

## Task 1: Add the Alert schema migration and ORM storage contract

**Files:**

- Create: `services/quant-api/alembic/versions/20260825_0040_htdy_frequency_scope.py`
- Create: `services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py`
- Modify: `services/quant-api/app/alerts/models.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

### Step 1.1: Write the migration tests first

- [ ] Add a migration test that loads revision `20260825_0040` and asserts:
  - `down_revision == "20260815_0039"`;
  - only `alert_rules` and `alert_events` are changed;
  - `alert_rules.scope_product_frequencies` is added as non-null JSON with empty-object default;
  - `uq_alert_events_rule_symbol_bar_end` is dropped;
  - `uq_alert_events_rule_symbol_frequency_bar_end` is created over `(rule_id, symbol, frequency, bar_end)`;
  - downgrade raises exactly `HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED`.

Use the repository's existing isolated migration guard rather than creating a new safety mechanism.

- [ ] Add an isolated PostgreSQL test that upgrades through `20260815_0039`, seeds:

```python
htdy.scope_products = ["jm", "rb"]
subing.scope_products = ["ag"]
```

then upgrades to `20260825_0040` and asserts exactly:

```python
htdy.scope_products == []
htdy.scope_product_frequencies == {
    "jm": ["15m"],
    "rb": ["15m"],
}
subing.scope_products == ["ag"]
subing.scope_product_frequencies == {}
```

- [ ] In the same isolated PostgreSQL test, seed two HTDY Event rows with the same `rule_id + symbol + bar_end` but different frequencies after migration and prove the DB accepts both. Seed the same frequency twice and prove the unique constraint rejects the duplicate.

Run:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL="$GUIYI_ISOLATED_MIGRATION_DATABASE_URL" \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

Expected before implementation: failure because revision `0040`, the column, and the new unique constraint do not exist.

### Step 1.2: Implement the migration

- [ ] Create revision `20260825_0040` with this exact migration order:

```python
revision = "20260825_0040"
down_revision = "20260815_0039"

# 1. Add JSON scope field with {} server default.
# 2. Read only the htdy_original_15m row.
# 3. Convert every existing scope_products symbol to ["15m"].
# 4. Clear HTDY scope_products after JSON is persisted.
# 5. Leave SuBing scope_products untouched and JSON empty.
# 6. Replace AlertEvent unique constraint with frequency-aware storage identity.
```

The migration must never infer six new frequencies from the new capability. Existing HTDY Scope only inherits 15m.

- [ ] Use a normal JSON mapping, not pair-encoded values such as `jm@15m`.
- [ ] Do not modify historical AlertEvent data.
- [ ] Make downgrade fail closed:

```python
def downgrade() -> None:
    raise RuntimeError("HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED")
```

### Step 1.3: Update ORM models

- [ ] Add to `AlertRule`:

```python
scope_product_frequencies: Mapped[dict[str, list[str]]] = mapped_column(
    JSON,
    default=dict,
    nullable=False,
)
```

- [ ] Change `AlertEvent.__table_args__` to:

```python
UniqueConstraint(
    "rule_id",
    "symbol",
    "frequency",
    "bar_end",
    name="uq_alert_events_rule_symbol_frequency_bar_end",
)
```

- [ ] Update SQLite test fixtures that instantiate `AlertRule` so both Scope fields have deterministic empty defaults where explicit construction is clearer.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

Expected: all non-isolated assertions pass; isolated test passes when the required isolated DB URL is supplied.

### Step 1.4: Commit

```bash
git add \
  services/quant-api/alembic/versions/20260825_0040_htdy_frequency_scope.py \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py \
  services/quant-api/app/alerts/models.py \
  services/quant-api/tests/test_alert_service.py
git commit -m "feat: add HTDY frequency scope storage"
```

---

## Task 2: Make AlertService the single authority for HTDY pair Scope and rule-specific Event identity

**Files:**

- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

### Step 2.1: Add failing Scope normalization tests

- [ ] Extend `ProductAlertRuleState` expectations with:

```python
enabled_frequencies: tuple[str, ...]
```

Semantics are exact:

```text
HTDY INDICATOR_OBSERVATION:
  enabled_for_product = bool(enabled_frequencies)
  enabled_frequencies = exact normalized frequency Scope for this symbol

SuBing FORMAL_SIGNAL:
  enabled_for_product = symbol in scope_products
  enabled_frequencies = ()
```

- [ ] Add tests for HTDY pair mutation:
  - `jm + 15m ON` produces `{"jm": ["15m"]}`;
  - then `jm + 5m ON` produces fixed-order `{"jm": ["5m", "15m"]}`;
  - `jm + 5m OFF` returns to `{"jm": ["15m"]}`;
  - repeated ON/OFF is idempotent;
  - empty frequency set removes the `jm` key entirely;
  - another symbol's entries are untouched.

- [ ] Add failure tests with exact public error codes:

```text
ALERT_SCOPE_MODE_INVALID
ALERT_SCOPE_FREQUENCY_INVALID
ALERT_SCOPE_STATE_INVALID
ALERT_SCOPE_PERSIST_FAILED
```

Required cases:
  - product-level `set_product_enabled()` called for HTDY -> `ALERT_SCOPE_MODE_INVALID`;
  - frequency-level mutation called for SuBing -> `ALERT_SCOPE_MODE_INVALID`;
  - HTDY unknown/non-input frequency -> `ALERT_SCOPE_FREQUENCY_INVALID`;
  - HTDY row has non-empty `scope_products` after migration -> `ALERT_SCOPE_STATE_INVALID`;
  - SuBing row has non-empty `scope_product_frequencies` -> `ALERT_SCOPE_STATE_INVALID`;
  - never union the two stores.

- [ ] Prove row-level locking remains present for both mutation methods.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_service.py
```

Expected before implementation: new tests fail.

### Step 2.2: Implement one narrow Scope normalizer

- [ ] Add one internal normalizer in `service.py` that receives the DB row plus its code-defined `AlertRuleDefinition` and validates the authority split.
- [ ] Use the existing `AlertRuleKind`; do not introduce a generic Scope strategy class hierarchy.
- [ ] Normalize frequency order from the Rule definition, so stored arrays always follow:

```text
1m, 5m, 15m, 30m, 60m, 1d, 1w
```

for HTDY.

- [ ] Add:

```python
def set_product_frequency_enabled(
    self,
    rule_code: str,
    symbol: str,
    frequency: str,
    enabled: bool,
) -> ProductAlertRuleState:
    ...
```

It must use `SELECT ... FOR UPDATE`, replace the normalized JSON object, commit, refresh, and map DB failures to `ALERT_SCOPE_PERSIST_FAILED`.

- [ ] Keep `set_product_enabled()` only for `FORMAL_SIGNAL` product-level Scope.

### Step 2.3: Add one read predicate for Runtime

- [ ] Add a Service method with exact responsibility:

```python
def rule_allows_event(
    self,
    rule: AlertRule,
    *,
    symbol: str,
    frequency: str,
) -> bool:
    ...
```

Behavior:

```text
HTDY -> exact symbol + frequency pair must be ON
SuBing -> symbol must be in scope_products and frequency must already be in Rule capability
invalid mixed authority -> raise ALERT_SCOPE_STATE_INVALID
```

Runtime must call this method instead of reimplementing JSON parsing.

### Step 2.4: Preserve SuBing business identity while widening HTDY identity

- [ ] Before inserting a `FORMAL_SIGNAL`, query existing Event by:

```text
rule_id + symbol + bar_end
```

If one exists:
  - exact same contract/frequency/trading_day/result/lower_tf state -> return `None`;
  - any difference -> `ALERT_EVENT_CONSISTENCY_ERROR`.

- [ ] For `INDICATOR_OBSERVATION`, use:

```text
rule_id + symbol + frequency + bar_end
```

so two HTDY frequencies at the same time are separate valid Events.

- [ ] Extend the current regression that changes only SuBing frequency so it still fails closed after the DB unique key becomes broader.
- [ ] Add HTDY regression proving same-time `15m` and `60m` can both be created, while a duplicate `15m` returns `None`.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_service.py
```

### Step 2.5: Commit

```bash
git add services/quant-api/app/alerts/service.py services/quant-api/tests/test_alert_service.py
git commit -m "feat: scope HTDY alerts by frequency"
```

---

## Task 3: Expose pair Scope through the Alert HTTP contract without changing SuBing semantics

**Files:**

- Modify: `services/quant-api/app/schemas/alerts.py`
- Modify: `services/quant-api/app/api/alerts.py`
- Modify: `services/quant-api/tests/test_alert_api.py`

### Step 3.1: Write failing HTTP contract tests

- [ ] Update product-state expected DTO so every rule has `enabled_frequencies`; for SuBing it is `[]`, for HTDY it is the exact enabled set.
- [ ] Add:

```text
PUT /api/alerts/rules/{rule_code}/scope/{symbol}/{frequency}
body={"enabled": true|false}
```

HTTP tests must prove:
  - HTDY `jm/15m` ON changes only 15m;
  - HTDY `jm/5m` ON preserves 15m;
  - HTDY `jm/5m` OFF preserves 15m;
  - invalid frequency -> 422 + `ALERT_SCOPE_FREQUENCY_INVALID`;
  - pair endpoint for SuBing -> 422 + `ALERT_SCOPE_MODE_INVALID`;
  - existing product endpoint for HTDY -> 422 + `ALERT_SCOPE_MODE_INVALID`;
  - existing product endpoint for SuBing remains functional;
  - no POST rule-definition mutation surface is introduced.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py
```

Expected before implementation: DTO and route tests fail.

### Step 3.2: Implement schema and route

- [ ] Add to `ProductAlertRuleStateOut`:

```python
enabled_frequencies: list[str]
```

- [ ] Keep `AlertScopeUpdate` unchanged (`enabled: bool`).
- [ ] Add the pair-level PUT route and call `AlertService.set_product_frequency_enabled()`.
- [ ] Map `AlertScopeError` using the existing public error envelope; do not expose DB/stack details.
- [ ] Keep `/api/alerts/rules/{rule_code}/scope/{symbol}` for SuBing only.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_service.py
```

### Step 3.3: Commit

```bash
git add \
  services/quant-api/app/schemas/alerts.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/tests/test_alert_api.py
git commit -m "feat: expose HTDY frequency alert scope"
```

---

## Task 4: Generalize HTDY Rule, evaluator, and event-cutoff Market reads to all seven frequencies

**Files:**

- Modify: `services/quant-api/app/alerts/registry.py`
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Modify: `services/quant-api/tests/test_alert_evaluator.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_read.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py` if it pins the Alert frequency contract

### Step 4.1: Lock Rule capability first

- [ ] Add a failing registry assertion that HTDY input frequencies are exactly:

```python
("1m", "5m", "15m", "30m", "60m", "1d", "1w")
```

SuBing must remain exactly `("5m", "15m")`.

- [ ] Do not rename `rule_code="htdy_original_15m"`.

### Step 4.2: Generalize the evaluator contract

- [ ] Rename production class:

```text
HtdyOriginal15mEvaluator -> HtdyOriginalEvaluator
```

- [ ] Update tests so a `MarketReadWindow` at each of the seven frequencies is accepted when:

```text
series_kind == actual_dominant
len(bars) >= 32
bars[-1].bar_end == cutoff
frequency in HTDY Rule input_frequencies
```

- [ ] Keep wrong series kind, short context, cutoff mismatch, unsupported frequency, and formal-policy mismatch fail-closed.
- [ ] Preserve the existing regression proving the bounded 32-bar calculation equals full-history current-bar buy/sell truth.
- [ ] The evaluator must still inspect only `buy_observation[-1]` and `sell_observation[-1]`; it must never scan old repaint bars.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_evaluator.py
```

### Step 4.3: Split MarketReadService into intraday-event and canonical-latest paths

- [ ] Keep `bars_until()` as the intraday event-cutoff reader but allow all five intraday frequencies:

```text
1m / 5m / 15m / 30m / 60m
```

It must:
  - require `actual_dominant` and no explicit contract;
  - read Canonical page at the same frequency;
  - merge only the same-frequency Live Redis bars;
  - use immutable current-day subscription to resolve event contract;
  - dedupe by `bar_end`;
  - require exact cutoff bar;
  - never aggregate another frequency inside the reader.

- [ ] Add a separate canonical-only method for D1/W1:

```python
def latest_canonical_window(
    self,
    identity: SeriesPageQuery,
    *,
    trading_day: date,
    limit: int = 32,
) -> MarketReadWindow:
    ...
```

Its contract is:
  - only `actual_dominant + 1d|1w`;
  - read one canonical page through `MarketDataService`;
  - require at least one bar and latest `bar.trading_day == trading_day`;
  - select exactly one `resolved_contract_segment` containing the latest bar's trading day;
  - normalize that segment contract for the symbol;
  - set `cutoff = latest_bar.bar_end`;
  - return the latest `limit` bars;
  - never read Live Redis.

- [ ] Factor shared limit/time/order validation into a private helper only if it removes real duplication between these two paths; do not introduce a general Strategy reader.

Tests must prove:
  - each intraday frequency asks Redis for the exact same frequency;
  - `1d/1w` canonical reader never calls subscriptions/heartbeat/live bars;
  - D1/W1 latest trading-day mismatch fails closed;
  - zero or multiple matching owner segments fail closed;
  - cutoff missing and invalid rank1 identity fail closed.

Use stable `MarketReadWindowError` codes rather than raw storage exceptions.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/test_alert_evaluator.py
```

### Step 4.4: Wire composition

- [ ] Replace the composition import/constructor with `HtdyOriginalEvaluator()`.
- [ ] Do not touch activation-marker semantics.

### Step 4.5: Commit

```bash
git add \
  services/quant-api/app/alerts/registry.py \
  services/quant-api/app/alerts/evaluators.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/app/market_data/market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/test_indicator_registry_v1.py
git commit -m "feat: evaluate HTDY across market frequencies"
```

If `test_indicator_registry_v1.py` requires no edit after the new tests are added elsewhere, do not stage it.

---

## Task 5: Expand intraday Alert Runtime to 1m/5m/15m/30m/60m with exact pair Scope

**Files:**

- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

### Step 5.1: Write failing parser and Scope tests

- [ ] Change the parser contract tests to accept exactly:

```text
live:bar:jm:1m
live:bar:jm:5m
live:bar:jm:15m
live:bar:jm:30m
live:bar:jm:60m
```

and continue rejecting D1/W1 on the Live Bar channel.

- [ ] Add Runtime tests with HTDY JSON Scope:

```python
scope_product_frequencies={"jm": ["15m"]}
```

Then prove:
  - JM 5m completed bar does not call HTDY MarketRead/evaluator;
  - JM 15m completed bar does call HTDY;
  - adding 5m enables it without changing 15m;
  - non-operational symbol is ignored;
  - mixed HTDY `scope_products` + JSON Scope causes the rule to fail closed and produces no Event/notification.

- [ ] Keep existing SuBing behavior tests at 5m/15m including same-boundary suppression.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_runtime.py
```

### Step 5.2: Make Runtime use AlertService for Scope authorization

- [ ] Replace direct logic:

```python
symbol not in set(rule.scope_products or [])
```

with one `AlertService.rule_allows_event(...)` call after Rule capability filtering.

- [ ] `_evaluate_htdy()` must receive `event_frequency` and build:

```python
SeriesPageQuery(
    SeriesKind.ACTUAL_DOMINANT,
    symbol,
    event_frequency,
)
```

- [ ] `_window_matches_event()` must compare the window against the requested event frequency rather than literal `15m`.
- [ ] `_RuleResult.frequency` must be the actual event frequency.

### Step 5.3: Preserve heartbeat schema while counting Scope products correctly

- [ ] Keep the heartbeat payload fields unchanged.
- [ ] Compute `scope_product_count` as distinct operational products that have at least one valid Scope in any enabled Rule:
  - HTDY: any non-empty valid frequency set for symbol;
  - SuBing: current `scope_products`.
- [ ] Invalid mixed Scope authority must fail the Runtime path rather than silently count/union it.
- [ ] Do not add `scope_pair_count` to Redis status in this task.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py
```

### Step 5.4: Commit

```bash
git add services/quant-api/app/alerts/runtime.py services/quant-api/tests/test_alert_runtime.py
git commit -m "feat: run HTDY on all intraday frequencies"
```

---

## Task 6: Add the Canonical-updated D1/W1 trigger without creating a second scheduler

**Files:**

- Modify: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_after_market.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

### Step 6.1: Write the after-market seam test first

- [ ] Change the successful post-update state publication assertion to exact payload:

```python
{
    "trading_day": "2026-08-10",
    "reason": "canonical_updated",
}
```

- [ ] Prove failed/skipped maintenance does not publish this reason.
- [ ] Preserve the existing order: Canonical update must already be successful/readable before `canonical_updated` is published.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/data_foundation/test_after_market.py
```

Expected before implementation: exact reason assertion fails.

### Step 6.2: Define a discriminated Runtime input parser

- [ ] Keep live bar parsing separate from Canonical state parsing. Use explicit internal dataclasses or tagged tuples; do not overload a single positional tuple with incompatible meanings.
- [ ] Add exact accepted Canonical payload:

```json
{"trading_day":"2026-08-10","reason":"canonical_updated"}
```

on channel `market:state`.
- [ ] Reject missing reason, other reason, invalid date, extra channel shape, or malformed JSON without side effects.

### Step 6.3: Subscribe to the existing state channel

- [ ] `run_forever()` must subscribe to both:

```text
live:bar:*:*
market:state
```

using the existing `RedisAlertMessageSource.psubscribe` seam. Do not create a second Redis connection or process.

### Step 6.4: Implement D1/W1 batch evaluation

- [ ] Add one Runtime method that handles a single `canonical_updated(T)` trigger.
- [ ] Open one DB session, load the enabled HTDY Rule, validate Scope authority, and derive two pair sets:

```text
D1 pairs = symbols where "1d" is enabled
W1 pairs = symbols where "1w" is enabled
```

- [ ] For each enabled pair:
  - call `MarketReadService.latest_canonical_window(..., trading_day=T, limit=32)`;
  - evaluate through the same `HtdyOriginalEvaluator`;
  - create Event using the returned window's `cutoff` and contract;
  - send the same one-shot HTDY notification if an Event is newly created.

- [ ] A product with only `1d` ON must never cause a `1w` read. A product with only `1w` ON must never cause a `1d` read.
- [ ] Pair failures are isolated like existing rule failures: one unavailable product/frequency does not authorize fallback or backfill for another frequency.
- [ ] Repeated identical `canonical_updated(T)` may re-evaluate but Event idempotency must prevent duplicate notification.
- [ ] If latest D1/W1 bar has `trading_day != T`, do nothing for that pair. This is the no-backfill boundary.
- [ ] Do not synthesize D1/W1 from Live 1m.

Tests must include:
  - D1-only Scope;
  - W1-only Scope;
  - both enabled;
  - no pair enabled;
  - stale weekly bar on a non-week-final day -> no Event;
  - duplicate state message -> one Event/one notification;
  - invalid state payload -> no DB/read/evaluator calls.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_read.py
```

### Step 6.5: Commit

```bash
git add \
  services/quant-api/app/market_data/after_market.py \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_alert_runtime.py
git commit -m "feat: trigger daily weekly HTDY from canonical updates"
```

---

## Task 7: Make HTDY notifications frequency-aware while preserving one-shot routing

**Files:**

- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/tests/test_alert_notification.py`

### Step 7.1: Write failing formatter tests

- [ ] Parameterize HTDY formatter over all seven frequencies and assert the rendered line uses the actual frequency:

```text
1m · HH:MM 收线
5m · HH:MM 收线
15m · HH:MM 收线
30m · HH:MM 收线
60m · HH:MM 收线
1d · HH:MM 收线
1w · HH:MM 收线
```

- [ ] Preserve buy/sell/conflict wording and Topic audience.
- [ ] Keep invalid non-registered frequency fail-closed.
- [ ] Keep SuBing formatter unchanged.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_notification.py
```

### Step 7.2: Implement the formatter

- [ ] Replace literal `message.frequency != "15m"` with membership in the HTDY Rule input frequencies.
- [ ] Render `message.frequency` directly.
- [ ] Do not add batching or time-window merging.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
```

### Step 7.3: Commit

```bash
git add services/quant-api/app/alerts/notification.py services/quant-api/tests/test_alert_notification.py
git commit -m "feat: render HTDY alert frequency"
```

---

## Task 8: Expand Web HTDY Overlay and persistent marker identity to all seven frequencies

**Files:**

- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/utils/alertRules.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`

### Step 8.1: Add failing all-frequency Overlay tests

- [ ] Import/use `MARKET_FREQUENCIES` in the test and assert HTDY Overlay is supported for every frequency and each existing chart series kind.
- [ ] Assert no change to repaint metadata/risk messages.

Expected production change:

```ts
supportedFrequencies: ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
```

Run:

```bash
pnpm --dir apps/quant-web test
```

### Step 8.2: Expand persistent HTDY marker frequencies

- [ ] Set HTDY `persistentFrequencies` to all seven Market frequencies.
- [ ] Keep marker fetch/display restricted to `actual_dominant`; chart Overlay support for continuous/contract does not mean persistent AlertEvent identity changes.

### Step 8.3: Fix persistent Event identity keys

Because same Rule + symbol + bar_end may now have multiple HTDY frequencies:

- [ ] Change marker id to include frequency:

```ts
`alert:${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
```

- [ ] Change `usePersistentAlertMarkers` cache key to the same frequency-aware identity.
- [ ] Keep `fetchRange()` filtering `event.frequency === identity.frequency` so events never project across chart periods.

Add unit regression:

```text
same rule + symbol + bar_end + 15m
same rule + symbol + bar_end + 60m
=> two distinct cached Events globally, but only the matching frequency renders on each chart
```

### Step 8.4: Extend Playwright marker coverage

- [ ] Expand the existing Alert E2E fixture to cover at least `5m / 15m / 30m / 60m` HTDY markers and prove exact-frequency rendering.
- [ ] Add one `1d` and one `1w` history marker fixture so persistent API projection is covered for daily/weekly without pretending those are Live.
- [ ] Keep continuous/contract chart behavior: local HTDY Overlay may display, but persistent Alert markers remain actual-dominant only.

Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/alert-v1.spec.mjs
```

### Step 8.5: Commit

```bash
git add \
  apps/quant-web/src/utils/mainIndicators.ts \
  apps/quant-web/src/utils/alertRules.ts \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/tests/mainIndicators.test.ts \
  apps/quant-web/tests/alerts.test.ts \
  apps/quant-web/e2e/alert-v1.spec.mjs
git commit -m "feat: show HTDY across all chart frequencies"
```

---

## Task 9: Make the single Web HTDY switch control only current symbol × frequency

**Files:**

- Modify: `apps/quant-web/src/api/alerts.ts`
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts`
- Modify: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`

### Step 9.1: Extend the Web DTO/API contract first

- [ ] Add:

```ts
export interface ProductAlertRuleState {
  rule_code: string
  display_name: string
  kind: AlertRuleKind
  input_frequencies: MarketFrequency[]
  enabled_for_product: boolean
  enabled_frequencies: MarketFrequency[]
}
```

- [ ] Add exact API helper:

```ts
export function setAlertProductFrequencyEnabled(
  ruleCode: string,
  symbol: string,
  frequency: MarketFrequency,
  enabled: boolean,
) {
  return request.put<never, ProductAlertRuleState>(
    `/api/alerts/rules/${ruleCode}/scope/${symbol}/${frequency}`,
    { enabled },
  )
}
```

- [ ] Keep `setAlertProductEnabled()` for SuBing.

### Step 9.2: Add composable behavior tests

- [ ] Give `useProductAlertScope` a reactive `frequency` dependency and both mutation functions.
- [ ] Its `toggle(ruleCode, enabled)` must dispatch by Rule kind:
  - HTDY indicator observation -> capture current symbol + current frequency and call pair endpoint;
  - SuBing formal signal -> current product endpoint.

- [ ] Keep `savingRuleCodes` keyed by Rule code, not frequency. This intentionally serializes concurrent HTDY pair writes against one JSON Rule row.
- [ ] If the user changes frequency while a HTDY PUT is in flight, the returned state may still replace that Rule's full `enabled_frequencies` set because the response is the complete server state for the same symbol. Do not discard it merely because the displayed frequency changed.
- [ ] A symbol change must continue using the existing generation/symbol stale-response guard.

Tests must prove:
  - `JM + 15m` ON calls only the pair endpoint for 15m;
  - changing reactive frequency to 5m makes the next click call 5m;
  - changing frequency alone causes zero mutation requests;
  - SuBing still uses product endpoint;
  - stale prior-symbol response cannot overwrite current symbol.

### Step 9.3: Make ProductAlertRules frequency-aware

- [ ] Add `frequency: MarketFrequency` prop.
- [ ] For the HTDY row:

```ts
value = rule.enabled_frequencies.includes(props.frequency)
label = `${rule.display_name} · ${props.frequency}`
```

- [ ] For SuBing keep `enabled_for_product` and existing supported-frequency label semantics.
- [ ] Do not render seven HTDY switches.
- [ ] Do not display “火天大有 · 全周期”.

### Step 9.4: Thread current frequency through the existing component tree

- [ ] `ProductCheckSidebar.vue` already receives `frequency`; pass it to `ProductAlertRules`.
- [ ] `chart.vue` passes the same reactive `frequency` into `useProductAlertScope` and uses `setAlertProductFrequencyEnabled`.
- [ ] Do not add a `watch(frequency)` that writes Scope.
- [ ] A frequency switch only changes the computed Switch state from the already loaded `enabled_frequencies` read model.
- [ ] Symbol changes continue to refresh Alert state from the backend.

### Step 9.5: Add browser acceptance coverage

Playwright must prove this exact sequence:

```text
JM 15m initial ON
-> switch to 5m
-> 5m displays OFF
-> no PUT occurred from the frequency switch
-> click 5m ON
-> pair PUT /jm/5m occurs
-> switch back 15m
-> 15m still ON
-> switch 5m and OFF
-> only /jm/5m is mutated
-> 15m remains ON
```

Also prove Overlay select/unselect does not mutate Alert Scope.

Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/alert-v1.spec.mjs
```

### Step 9.6: Commit

```bash
git add \
  apps/quant-web/src/api/alerts.ts \
  apps/quant-web/src/composables/useProductAlertScope.ts \
  apps/quant-web/src/components/market/ProductAlertRules.vue \
  apps/quant-web/src/components/market/ProductCheckSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/alerts.test.ts \
  apps/quant-web/e2e/alert-v1.spec.mjs
git commit -m "feat: control HTDY alerts by current frequency"
```

---

## Task 10: Close canonical contracts and add repository-level drift guards

**Files:**

- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `DECISIONS.md`
- Modify: `tests/engineering/test_canonical_consistency.py`
- Modify: `STATUS.md` only after the implementation/test/review facts being recorded have actually occurred

### Step 10.1: Add failing canonical consistency assertions

- [ ] Add narrow engineering assertions that lock these facts without duplicating the whole Spec:

```text
HTDY Rule stable code remains htdy_original_15m
HTDY capability = seven formal frequencies
HTDY Scope authority = scope_product_frequencies
SuBing Scope authority = scope_products
HTDY Event storage identity includes frequency
SuBing business identity remains bar-level in Service
D1/W1 use Canonical-updated path, not Live daily/weekly derivation
```

- [ ] Keep the existing “one production registry per language” guard valid; do not scatter literal Rule codes into new frontend production files. Continue importing from `alertRules.ts` and backend `registry.py`.

Run:

```bash
uv run --offline --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
```

### Step 10.2: Update canonical wording after code behavior exists

- [ ] `docs/INDICATOR_KERNEL.md`: replace HTDY `actual_dominant + confirmed 15m` Alert wording with seven-frequency current-event observation; retain future/repaint/backtest prohibitions.
- [ ] `PROJECT_SOURCE.md`: describe pair Scope and D1/W1 Canonical trigger; retain no replay/backfill/retry/order.
- [ ] `AGENTS.md`: replace the old `htdy_original_15m × scope_products` Runtime formula with the pair-scoped contract; preserve external-operation gates.
- [ ] `docs/DEVELOPMENT.md`: update only the active Alert bounded-authorization description; do not turn the Plan into workflow doctrine.
- [ ] `DECISIONS.md`: record the durable choice “one HTDY Rule, pair Scope, Live intraday + Canonical D1/W1, no second scheduler/table”.
- [ ] Do not rewrite the approved Spec to pretend implementation already existed at design time.

### Step 10.3: STATUS discipline

- [ ] Before independent Review, `STATUS.md` may record `CODE_COMPLETE` / `TEST_COMPLETE` only if those facts have been produced by the exact implementation head.
- [ ] Record `REVIEW_COMPLETE` only after the independent Review has completed and all Critical/Important findings are fixed and reverified.
- [ ] Do not mark `RELEASED`, `RUNTIME_PROMOTED`, production migration applied, real notification verified, natural D1/W1 evidence, or all-frequency Scope enabled unless each event actually occurs under its separate Gate.

### Step 10.4: Commit canonical closure

```bash
git add \
  docs/INDICATOR_KERNEL.md \
  PROJECT_SOURCE.md \
  AGENTS.md \
  docs/DEVELOPMENT.md \
  DECISIONS.md \
  tests/engineering/test_canonical_consistency.py \
  STATUS.md
git commit -m "docs: align HTDY all-frequency contracts"
```

If `STATUS.md` has no new true state to record at this point, leave it unstaged and out of the commit.

---

## Task 11: Run focused verification, full verification, and the read-only Active60 × seven-frequency matrix

**Files:**

- Modify code/tests only if verification exposes a real defect within the approved Spec.
- Do not add a permanent matrix subsystem unless the existing test surface cannot express the required read-only verification.

### Step 11.1: Focused backend verification

- [ ] Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  tests/engineering/test_canonical_consistency.py
```

- [ ] Run isolated PostgreSQL migration coverage:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL="$GUIYI_ISOLATED_MIGRATION_DATABASE_URL" \
uv run --offline --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

Do not point this command at production/Runtime PostgreSQL.

### Step 11.2: Focused Web verification

- [ ] Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/alert-v1.spec.mjs
```

### Step 11.3: Full project verification

- [ ] Run the current repository baseline:

```bash
uv run --offline --project services/quant-api pytest -q \
  -m "not isolated_postgresql" services/quant-api/tests

uv run --offline --project services/quant-api pytest -q \
  tests/engineering

uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/backtest \
  services/quant-api/app/market_data \
  services/quant-api/app/research \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/runtime_entry.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

### Step 11.4: Read-only Active60 × seven-frequency capability matrix

- [ ] Use `load_operational_products()` and assert the current checked-in operational universe count is 60 for this acceptance baseline.
- [ ] For each of 60 products × seven frequencies, verify the code-defined HTDY Rule accepts the frequency and the Web Overlay capability is supported.
- [ ] For backend Market reads, use existing confirmed data/test fixtures or a provider-free read-only local verification path. A product/frequency whose Canonical coverage is unavailable must be reported as typed unavailable; do not trigger RQData, maintenance, or data writes to manufacture coverage.
- [ ] The matrix result may establish only capability coverage. It must not claim strategy validity, profitability, backtest validity, or notification delivery.
- [ ] Do not mutate any real Scope while producing the matrix.

### Step 11.5: Stop on any failure

If any required check fails:

```text
do not mark TEST_COMPLETE
do not request integration
fix only approved-scope defects
rerun the failed check and all checks whose assumptions changed
```

---

## Task 12: Independent Lane 3 Review and integration Gate

**Files:**

- No new production feature scope.
- Modify implementation/test/docs only for validated Review findings.

### Step 12.1: Open an independent Review session

- [ ] Review the exact implementation base-to-head diff against:

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/INDICATOR_KERNEL.md
docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md
this Implementation Plan
```

The reviewer must explicitly inspect:
  - no HTDY formula change;
  - no future/repaint risk laundering;
  - pair Scope migration only inherits legacy 15m;
  - no HTDY/SuBing dual Scope authority;
  - SuBing same-bar business identity is still protected;
  - HTDY same-time cross-frequency Events coexist;
  - no D1/W1 Live reaggregation;
  - canonical_updated no-backfill semantics;
  - single Switch changes only current symbol × frequency;
  - no hidden Scope writes on chart frequency/Overlay changes;
  - no retry/replay/queue/outbox/order;
  - no production migration/real notification/Runtime mutation performed during implementation.

### Step 12.2: Fix Review findings

- [ ] Fix all Critical and Important findings before integration.
- [ ] Re-run every focused test affected by a fix.
- [ ] Re-run the full verification block after the final Review fix commit.
- [ ] Only then update `STATUS.md` with the exact truthful Review/Test state.

### Step 12.3: Integration Gate

The implementation PR targets `develop`.

Allowed only after user/Review conclusion is:

```text
允许集成 develop
```

Then:

```text
implementation task branch/worktree
-> reviewed PR
-> develop
-> remote develop readback
-> clean task worktree/branch after merge
```

Do not in the same step:

```text
run production migration
change real HTDY Scope
send real notification
merge/release main
create tag
promote/switch Runtime
```

Those remain separate explicit external-operation Gates after the implementation has been integrated and a release candidate is prepared.

---

## Expected implementation commit sequence

The implementation branch should normally produce this reviewable sequence:

```text
1. feat: add HTDY frequency scope storage
2. feat: scope HTDY alerts by frequency
3. feat: expose HTDY frequency alert scope
4. feat: evaluate HTDY across market frequencies
5. feat: run HTDY on all intraday frequencies
6. feat: trigger daily weekly HTDY from canonical updates
7. feat: render HTDY alert frequency
8. feat: show HTDY across all chart frequencies
9. feat: control HTDY alerts by current frequency
10. docs: align HTDY all-frequency contracts
11. fix: <only if verification/review finds a concrete defect>
```

Do not squash the conceptual boundaries during development if doing so would make the migration, Scope semantics, Runtime trigger, or Web switch harder to review.

## Plan self-review

- Spec coverage: every approved requirement is assigned to an implementation Task: seven-frequency Overlay, current `symbol × frequency` Switch, pair Scope persistence/API, legacy 15m-only migration inheritance, HTDY/SuBing Event identity split, intraday Live triggers, D1/W1 Canonical trigger, separate cross-frequency notifications, no-backfill, repaint boundaries, and external-operation Gates.
- Placeholder scan: no `TBD`, `TODO`, unspecified migration revision, unnamed core method, or unresolved Scope/error-code choice remains in this Plan.
- Type consistency: backend uses Rule-definition string frequencies at HTTP/storage boundaries and `BarFrequency` in Market/Runtime internals; Web uses `MarketFrequency`; Rule code remains the stable legacy string.
- Scope check: the Plan does not introduce a third Alert table, second scheduler, second daily/weekly fact chain, general Strategy adapter, generic Scope framework, retry/replay system, or order path.
- Gate check: implementation/test work is separated from production migration, real Scope mutation, real notification, release/tag, and Runtime promotion.
