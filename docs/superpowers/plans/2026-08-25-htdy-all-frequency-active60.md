# HTDY 全周期 × Active60 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 HTDY original 数学公式、不增加自动交易或重型基础设施的前提下，让当前 operational universe 的全部品种在 `1m / 5m / 15m / 30m / 60m / 1d / 1w` 都能显示 HTDY；Web 上唯一一个 HTDY 开关只控制当前 `symbol × current frequency` 的 Alert Scope；D1/W1 在盘后 Canonical 更新完成后检查；同一时刻不同已开启周期分别形成 Event 和分别通知。

**Architecture:** 保留单一 `htdy_original_15m` 稳定 Rule identity、单一 HTDY original Kernel 与现有 Alert Application Domain。HTDY Scope 在既有 `alert_rules` 增加轻量 `scope_product_frequencies` JSON map；SuBing 继续独占原 `scope_products`。日内五周期复用已有 completed Live Bar Pub/Sub，D1/W1 复用盘后 Canonical 更新后的 `market:state(reason=canonical_updated)` seam。AlertEvent 存储唯一键包含 frequency；SuBing 的 bar-level formal business identity 继续由 Service fail-closed 保护。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Alembic / PostgreSQL / Redis / NumPy / pytest / Vue 3 / TypeScript 6 / Naive UI / Node test / Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`

## Global Constraints

- 本任务是 Lane 3：指标可信口径、Alert Runtime、数据库 migration contract 同时变化。
- 实现从包含已批准 Spec 的最新 `develop` 创建独立 task branch/worktree；不得在本 Plan 文档分支实现。
- 推荐实现 branch：`feature/htdy-all-frequency-active60`；源 branch：最新 `develop`；目标 branch：`develop`。
- 实现阶段可以编写 Alembic migration，只允许在仓库指定的隔离 PostgreSQL 测试库执行 migration tests。
- 不执行 production migration；不修改真实 Scope；不发送真实 PushPlus；不切 Runtime；不发布 `main`；不创建 tag；不运行真实 canary；不启用订单能力。
- `auto_order=false` 不得改变。
- 不修改 `packages/quant-core/guiyi_quant/indicators/htdy_original.py` 的公式、XMA、25-period、三连 K 线观察语义、24-bar future dependency 或 repaint metadata。
- 不修改冻结的 JM/15m `RealtimeRepaintingObservationPolicy` / `ClosedBarRealtimeObservationPolicy` 及其 exact identity/hash。
- 不新增 Scope 表、scheduler、queue、retry、replay、backfill、outbox、fallback、跨周期通知合并或第二套 D1/W1 聚合。
- Rule code 继续为 `htdy_original_15m`；名称中的 `15m` 是 legacy stable identity，不再代表 capability 范围。
- 图表可以显示 `continuous / actual_dominant / contract`；Alert 始终只使用 `actual_dominant + rank1`。
- `STATUS.md` 只能记录真正发生的实现、验证、Review、集成、release、Runtime 事实。
- 每个 Task 使用 TDD：先写失败测试并确认失败，再写最小实现，再跑定向测试，再提交当前 Task。
- 不全量暂存无关工作树修改。

---

## Task 1: Add the Alert schema migration and ORM storage contract

**Files:**

- Create: `services/quant-api/alembic/versions/20260825_0040_htdy_frequency_scope.py`
- Create: `services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py`
- Modify: `services/quant-api/app/alerts/models.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

### Step 1.1: Write migration tests first

- [ ] Assert revision identity:

```python
assert migration.revision == "20260825_0040"
assert migration.down_revision == "20260815_0039"
```

- [ ] Assert only `alert_rules` and `alert_events` change.
- [ ] Assert `alert_rules.scope_product_frequencies` is non-null JSON with empty-object server default.
- [ ] Assert `uq_alert_events_rule_symbol_bar_end` is dropped and `uq_alert_events_rule_symbol_frequency_bar_end` is created over `(rule_id, symbol, frequency, bar_end)`.
- [ ] Assert downgrade raises exactly `HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED`.
- [ ] In isolated PostgreSQL, upgrade through `20260815_0039`, seed HTDY `scope_products=["jm","rb"]` and SuBing `scope_products=["ag"]`, upgrade to `0040`, then assert:

```python
assert htdy.scope_products == []
assert htdy.scope_product_frequencies == {
    "jm": ["15m"],
    "rb": ["15m"],
}
assert subing.scope_products == ["ag"]
assert subing.scope_product_frequencies == {}
```

- [ ] After migration, prove two HTDY rows with same `rule_id + symbol + bar_end` and different frequencies can coexist, while a duplicate same-frequency row violates the new unique key.

Run:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL="$GUIYI_ISOLATED_MIGRATION_DATABASE_URL" \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

Expected before implementation: failure because revision `0040` and the new schema do not exist.

### Step 1.2: Implement migration `0040`

- [ ] Add the JSON field first:

```python
op.add_column(
    "alert_rules",
    sa.Column(
        "scope_product_frequencies",
        sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'::json"),
    ),
)
```

- [ ] Read only the `htdy_original_15m` row, convert each existing product to `symbol -> ["15m"]`, persist that JSON, then clear only that row's `scope_products`.
- [ ] Do not derive or add `1m/5m/30m/60m/1d/1w` during migration.
- [ ] Leave SuBing `scope_products` unchanged and its JSON `{}`.
- [ ] Replace the Event unique constraint only after the Scope data transformation succeeds:

```python
op.drop_constraint(
    "uq_alert_events_rule_symbol_bar_end",
    "alert_events",
    type_="unique",
)
op.create_unique_constraint(
    "uq_alert_events_rule_symbol_frequency_bar_end",
    "alert_events",
    ["rule_id", "symbol", "frequency", "bar_end"],
)
```

- [ ] Do not update/delete historical AlertEvent rows.
- [ ] Downgrade must be:

```python
def downgrade() -> None:
    raise RuntimeError("HTDY_FREQUENCY_SCOPE_DOWNGRADE_UNSUPPORTED")
```

### Step 1.3: Update ORM

- [ ] Add:

```python
scope_product_frequencies: Mapped[dict[str, list[str]]] = mapped_column(
    JSON,
    default=dict,
    nullable=False,
)
```

- [ ] Change `AlertEvent.__table_args__` unique constraint to frequency-aware identity.
- [ ] Update test fixtures constructing AlertRule so both Scope fields have deterministic values.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

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

## Task 2: Make AlertService the single authority for pair Scope and rule-specific Event identity

**Files:**

- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

### Step 2.1: Add failing Scope tests

- [ ] Extend `ProductAlertRuleState` with:

```python
enabled_frequencies: tuple[str, ...]
```

Exact semantics:

```text
HTDY INDICATOR_OBSERVATION
  enabled_frequencies = exact normalized pair Scope for current symbol
  enabled_for_product = bool(enabled_frequencies)

SuBing FORMAL_SIGNAL
  enabled_frequencies = ()
  enabled_for_product = symbol in scope_products
```

- [ ] Test HTDY mutations: 15m ON; 5m ON preserving 15m; 5m OFF preserving 15m; repeated ON/OFF idempotent; removing the last frequency removes the symbol key; another symbol is untouched.
- [ ] Lock exact public errors:

```text
ALERT_SCOPE_MODE_INVALID
ALERT_SCOPE_FREQUENCY_INVALID
ALERT_SCOPE_STATE_INVALID
ALERT_SCOPE_PERSIST_FAILED
```

Required cases:
  - product-level setter called for HTDY -> `ALERT_SCOPE_MODE_INVALID`;
  - frequency-level setter called for SuBing -> `ALERT_SCOPE_MODE_INVALID`;
  - unknown/non-input HTDY frequency -> `ALERT_SCOPE_FREQUENCY_INVALID`;
  - HTDY row has non-empty `scope_products` -> `ALERT_SCOPE_STATE_INVALID`;
  - SuBing row has non-empty `scope_product_frequencies` -> `ALERT_SCOPE_STATE_INVALID`.
- [ ] Prove both setters use row-level locking.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_service.py
```

### Step 2.2: Implement the HTDY frequency setter

- [ ] Implement this exact public method contract:

```python
def set_product_frequency_enabled(
    self,
    rule_code: str,
    symbol: str,
    frequency: str,
    enabled: bool,
) -> ProductAlertRuleState:
    normalized_symbol = self._require_operational_symbol(symbol)
    rule = self._rule_by_code(rule_code, for_update=True)
    definition = _definition(rule.rule_code)
    if definition.kind is not AlertRuleKind.INDICATOR_OBSERVATION:
        raise AlertScopeError("ALERT_SCOPE_MODE_INVALID")
    normalized_frequency = str(frequency).strip()
    if normalized_frequency not in definition.input_frequencies:
        raise AlertScopeError("ALERT_SCOPE_FREQUENCY_INVALID")
    scope = self._normalized_frequency_scope(rule, definition)
    current = set(scope.get(normalized_symbol, ()))
    if enabled:
        current.add(normalized_frequency)
    else:
        current.discard(normalized_frequency)
    if current:
        scope[normalized_symbol] = tuple(
            value for value in definition.input_frequencies if value in current
        )
    else:
        scope.pop(normalized_symbol, None)
    rule.scope_product_frequencies = {
        key: list(values) for key, values in sorted(scope.items())
    }
    return self._commit_scope(rule, normalized_symbol)
```

- [ ] `_normalized_frequency_scope()` validates JSON shape, normalized operational symbols, Rule-supported frequency values, and the HTDY/SuBing authority split; it never unions both stores.
- [ ] `_commit_scope()` centralizes existing commit/refresh/rollback behavior and maps SQLAlchemy failures to `ALERT_SCOPE_PERSIST_FAILED`.
- [ ] Restrict existing `set_product_enabled()` to `FORMAL_SIGNAL` and keep SuBing behavior unchanged.

### Step 2.3: Implement the Runtime authorization predicate

- [ ] Add:

```python
def rule_allows_event(
    self,
    rule: AlertRule,
    *,
    symbol: str,
    frequency: str,
) -> bool:
    normalized_symbol = self._require_operational_symbol(symbol)
    definition = _definition(rule.rule_code)
    if frequency not in definition.input_frequencies:
        return False
    if definition.kind is AlertRuleKind.INDICATOR_OBSERVATION:
        scope = self._normalized_frequency_scope(rule, definition)
        return frequency in scope.get(normalized_symbol, ())
    self._require_product_scope_authority(rule, definition)
    return normalized_symbol in set(rule.scope_products or [])
```

Runtime must use this method instead of parsing Scope JSON itself.

### Step 2.4: Preserve SuBing business identity while widening HTDY identity

- [ ] For `FORMAL_SIGNAL`, pre-read existing Event by `rule_id + symbol + bar_end`; exact same Event returns `None`, any changed contract/frequency/trading_day/result/lower_tf state raises `ALERT_EVENT_CONSISTENCY_ERROR`.
- [ ] For `INDICATOR_OBSERVATION`, read/resolve identity by `rule_id + symbol + frequency + bar_end`.
- [ ] On `IntegrityError`, rollback, re-read the same rule-specific identity, return `None` only when all attributes match, otherwise raise `ALERT_EVENT_CONSISTENCY_ERROR`.
- [ ] Add regression: same-time HTDY 15m and 60m both persist; duplicate 15m is idempotent; SuBing frequency-only drift at same bar still fails closed.

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

## Task 3: Expose pair Scope through the HTTP contract

**Files:**

- Modify: `services/quant-api/app/schemas/alerts.py`
- Modify: `services/quant-api/app/api/alerts.py`
- Modify: `services/quant-api/tests/test_alert_api.py`

### Step 3.1: Add failing API tests

- [ ] Product-state DTO returns `enabled_frequencies`; SuBing returns `[]`; HTDY returns exact enabled set.
- [ ] Add pair mutation route:

```text
PUT /api/alerts/rules/{rule_code}/scope/{symbol}/{frequency}
body={"enabled": true|false}
```

Tests must prove HTDY `jm/15m` ON changes only 15m; `jm/5m` ON/OFF preserves 15m; invalid frequency -> 422 `ALERT_SCOPE_FREQUENCY_INVALID`; pair endpoint for SuBing -> 422 `ALERT_SCOPE_MODE_INVALID`; product endpoint for HTDY -> 422 `ALERT_SCOPE_MODE_INVALID`; existing SuBing product endpoint remains valid.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py
```

### Step 3.2: Implement schema and route

- [ ] Add `enabled_frequencies: list[str]` to `ProductAlertRuleStateOut` and serialize from Service.
- [ ] Keep `AlertScopeUpdate(enabled: bool)` unchanged.
- [ ] Pair route calls `set_product_frequency_enabled()`; product route continues to call `set_product_enabled()`.
- [ ] Reuse current public `AlertScopeError` envelope; never expose DB or stack details.

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

## Task 4: Generalize Rule, evaluator, and Market event-cutoff reads

**Files:**

- Modify: `services/quant-api/app/alerts/registry.py`
- Modify: `services/quant-api/app/alerts/evaluators.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/market_data/market_read_service.py`
- Modify: `services/quant-api/tests/test_alert_evaluator.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_read.py`
- Modify: `services/quant-api/tests/test_indicator_registry_v1.py`

### Step 4.1: Lock HTDY Rule capability

- [ ] Assert:

```python
assert HTDY_RULE.input_frequencies == (
    "1m", "5m", "15m", "30m", "60m", "1d", "1w"
)
assert SUBING_RULE.input_frequencies == ("5m", "15m")
assert HTDY_RULE.rule_code == "htdy_original_15m"
```

- [ ] Update only the Rule capability metadata; do not change quant-core HTDY formula metadata.

### Step 4.2: Generalize evaluator

- [ ] Rename `HtdyOriginal15mEvaluator` to `HtdyOriginalEvaluator` in production and tests.
- [ ] Accept a `MarketReadWindow` only when `series_kind == "actual_dominant"`, frequency belongs to `HTDY_RULE.input_frequencies`, at least 32 bars exist, and the last bar equals the cutoff.
- [ ] Keep formal-policy validation with `HTDY_ALERT_OBSERVATION_CONSUMER`.
- [ ] Keep current-bar-only evaluation:

```python
observations: list[str] = []
if bool(result.buy_observation[-1]):
    observations.append("buy")
if bool(result.sell_observation[-1]):
    observations.append("sell")
return AlertEvaluation(observation_types=tuple(observations))
```

- [ ] Preserve the existing 32-bar vs full-history current-observation regression.

### Step 4.3: Generalize intraday `bars_until()`

- [ ] Allow exactly `1m/5m/15m/30m/60m` for `actual_dominant` with no explicit contract.
- [ ] Read Canonical history and Live Redis at the exact same requested frequency; never cross-frequency aggregate/fallback.
- [ ] Resolve event contract from the immutable current-day Live subscription snapshot.
- [ ] Dedupe by `bar_end`, cap to limit, and require exact cutoff bar.

### Step 4.4: Add canonical-only D1/W1 window reader

- [ ] Add exact method:

```python
def latest_canonical_window(
    self,
    identity: SeriesPageQuery,
    *,
    trading_day: date,
    limit: int = 32,
) -> MarketReadWindow:
    if (
        identity.series_kind is not SeriesKind.ACTUAL_DOMINANT
        or identity.frequency not in {BarFrequency.D1, BarFrequency.W1}
        or identity.contract is not None
    ):
        raise MarketReadWindowError("MARKET_READ_IDENTITY_UNSUPPORTED")
    page = self.history_page(replace(identity, before=None, limit=limit))
    if not page.bars or page.bars[-1].trading_day != trading_day:
        raise MarketReadWindowError("MARKET_READ_CUTOFF_BAR_MISSING")
    latest = page.bars[-1]
    owners = tuple(
        segment
        for segment in page.resolved_contract_segments
        if segment.start_trading_day <= latest.trading_day <= segment.end_trading_day
    )
    if len(owners) != 1:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    contract = normalize_contract_for_symbol(identity.symbol, owners[0].contract)
    if contract is None:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    return MarketReadWindow(
        symbol=identity.symbol,
        series_kind=identity.series_kind.value,
        frequency=identity.frequency.value,
        trading_day=trading_day,
        contract=contract,
        cutoff=latest.bar_end,
        bars=page.bars[-limit:],
    )
```

- [ ] Tests prove this path never calls Live subscriptions/heartbeat/bar reads, stale D1/W1 trading day fails closed, and zero/multiple owner segments fail closed.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/test_indicator_registry_v1.py
```

### Step 4.5: Wire composition and commit

- [ ] Composition constructs `HtdyOriginalEvaluator()` and leaves activation-marker semantics unchanged.

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

---

## Task 5: Expand intraday Runtime to 1m/5m/15m/30m/60m with exact pair Scope

**Files:**

- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

### Step 5.1: Add failing parser and Scope tests

- [ ] `_parse_event` accepts exactly Live Bar frequencies `1m/5m/15m/30m/60m`; it continues rejecting `1d/1w` on `live:bar:*:*`.
- [ ] With HTDY Scope `{"jm":["15m"]}`, JM 5m does not call MarketRead/evaluator and JM 15m does.
- [ ] With `{"jm":["5m","15m"]}`, both exact pairs can evaluate independently.
- [ ] Non-operational product remains ignored.
- [ ] Invalid mixed Scope state creates no Event and sends no notification.
- [ ] Existing SuBing 5m/15m and same-boundary behavior remains unchanged.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_runtime.py
```

### Step 5.2: Use AlertService for authorization

- [ ] For each enabled Rule, create one `AlertService` for the session and gate with:

```python
if event_frequency.value not in definition.input_frequencies:
    continue
if not service.rule_allows_event(
    rule,
    symbol=symbol,
    frequency=event_frequency.value,
):
    continue
```

- [ ] `_evaluate_htdy()` receives `event_frequency`, queries the same frequency, and returns `_RuleResult.frequency = event_frequency.value`.
- [ ] `_window_matches_event()` compares `window.frequency` to the event frequency rather than literal 15m.

### Step 5.3: Preserve heartbeat schema

- [ ] Keep current Redis fields unchanged.
- [ ] `scope_product_count` counts distinct operational products with at least one valid Scope in any enabled Rule. HTDY multiple frequencies for one product count once; SuBing continues product counting.
- [ ] Invalid Scope authority does not get unioned or counted as valid.

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

## Task 6: Add D1/W1 Canonical-updated trigger without a second scheduler

**Files:**

- Modify: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/tests/data_foundation/test_after_market.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

### Step 6.1: Lock the after-market seam

- [ ] After a successful Canonical write/readability point, publish exact payload:

```python
{
    "trading_day": trading_day.isoformat(),
    "reason": "canonical_updated",
}
```

- [ ] Failed/skipped maintenance before Canonical success does not publish this reason.
- [ ] Preserve current behavior that a completed Canonical write can notify the Market seam even when later Live reconciliation reports a separate failure; `canonical_updated` means Canonical is readable, not that every after-market follow-up succeeded.

Run:

```bash
uv run --offline --project services/quant-api pytest -q services/quant-api/tests/data_foundation/test_after_market.py
```

### Step 6.2: Add discriminated Runtime inputs

- [ ] Keep the Live Bar parser and Canonical-state parser separate. Introduce internal immutable values equivalent to:

```python
@dataclass(frozen=True, slots=True)
class _LiveBarTrigger:
    symbol: str
    frequency: BarFrequency
    bar: CanonicalBar

@dataclass(frozen=True, slots=True)
class _CanonicalUpdatedTrigger:
    trading_day: date
```

- [ ] Accept `_CanonicalUpdatedTrigger` only from channel `market:state` with exact reason `canonical_updated` and a valid ISO trading day.
- [ ] Malformed JSON, missing/other reason, or invalid date produces no side effects.

### Step 6.3: Subscribe to both existing channels

- [ ] `run_forever()` calls the existing `psubscribe` seam for:

```text
live:bar:*:*
market:state
```

Do not add a second Redis connection/process.

### Step 6.4: Reuse one Event/notification persistence helper

- [ ] Extract the current “create Event -> build notification message” block into one internal helper used by both Live and Canonical paths. It must preserve Event-first commit and one provider attempt per newly created Event.
- [ ] Do not create a generic event bus or queue.

### Step 6.5: Implement D1/W1 evaluation

- [ ] On `canonical_updated(T)`, open one session, load enabled HTDY Rule, validate Scope, and derive only the exact enabled pairs for `1d` and `1w`.
- [ ] For each pair, call `latest_canonical_window(SeriesPageQuery(ACTUAL_DOMINANT, symbol, frequency), trading_day=T, limit=32)`.
- [ ] Evaluate with the same `HtdyOriginalEvaluator` and create Event using the returned `cutoff`, `contract`, actual frequency and T.
- [ ] If a symbol has only 1d ON, never read 1w; if only 1w ON, never read 1d.
- [ ] If latest bar trading day is not T, create no Event. This is the no-backfill boundary.
- [ ] Repeated identical `canonical_updated(T)` cannot duplicate an existing same-frequency Event or notification.
- [ ] Pair failures stay isolated; no fallback to another frequency or historical day.
- [ ] Never synthesize D1/W1 from Live 1m.

Tests cover D1-only, W1-only, both, neither, stale W1 on a non-week-final day, duplicate state message, invalid state payload, and one unavailable pair not authorizing fallback.

Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_read.py
```

### Step 6.6: Commit

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

## Task 7: Make HTDY notifications frequency-aware

**Files:**

- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/tests/test_alert_notification.py`

### Step 7.1: Add failing formatter tests

- [ ] Parameterize HTDY over all seven frequencies and assert the rendered line contains the actual value, e.g. `5m · 10:45 收线`, `60m · 10:45 收线`, `1d · 10:45 收线`, `1w · 10:45 收线`.
- [ ] Preserve buy/sell/conflict wording, `htdy_observers` Topic routing, and provider-accepted semantics.
- [ ] Keep SuBing formatter unchanged.

### Step 7.2: Implement and verify

- [ ] Replace the literal `15m` check with membership in `HTDY_RULE.input_frequencies` and render `message.frequency` directly.
- [ ] Do not batch or merge simultaneous frequencies.

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

## Task 8: Expand Web Overlay and persistent marker identity to all seven frequencies

**Files:**

- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/utils/alertRules.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`

### Step 8.1: Lock Overlay support

- [ ] Assert HTDY Overlay is supported for every `MARKET_FREQUENCIES` entry and each existing chart series kind.
- [ ] Set HTDY `supportedFrequencies` to the seven formal frequencies.
- [ ] Preserve repaint/risk metadata and optional EMA behavior.

### Step 8.2: Expand persistent marker frequency support

- [ ] Set HTDY `persistentFrequencies` to all seven frequencies, while keeping persistent Alert markers restricted to `actual_dominant`.
- [ ] Change marker/cache identity to include frequency:

```ts
const markerId = `alert:${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
const cacheKey = `${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
```

- [ ] Keep `event.frequency === current chart frequency` filtering so no cross-period projection occurs.
- [ ] Unit-test same Rule/symbol/bar_end with 15m and 60m as distinct cached Event identities.

### Step 8.3: Extend browser marker coverage

- [ ] Existing E2E must cover exact-frequency HTDY markers for intraday periods and add 1d/1w persistent Event fixtures without pretending those are Live.
- [ ] Continuous/contract can show the local HTDY Overlay, but persistent AlertEvent markers remain actual-dominant only.

Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/alert-v1.spec.mjs
```

### Step 8.4: Commit

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

## Task 9: Make the single Web Switch control only current symbol × frequency

**Files:**

- Modify: `apps/quant-web/src/api/alerts.ts`
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts`
- Modify: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`

### Step 9.1: Extend Web DTO/API

- [ ] Add exact DTO field:

```ts
enabled_frequencies: MarketFrequency[]
```

- [ ] Add exact pair API:

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

### Step 9.2: Update `useProductAlertScope`

- [ ] Add reactive `frequency` and the pair setter dependency.
- [ ] `toggle()` looks up the current Rule state. HTDY calls the pair setter with captured `symbol.value` and `frequency.value`; SuBing calls the existing product setter.
- [ ] Keep `savingRuleCodes` keyed by Rule code. This serializes writes against one HTDY JSON Rule row even if the user changes period quickly.
- [ ] A frequency change alone must make zero mutation calls.
- [ ] An in-flight HTDY response for the same symbol may replace the Rule's full `enabled_frequencies` set even if the displayed frequency changed; symbol-generation stale protection remains required.

### Step 9.3: Update the single HTDY Switch

- [ ] Add `frequency: MarketFrequency` prop to `ProductAlertRules.vue`.
- [ ] For HTDY only:

```ts
const value = rule.enabled_frequencies.includes(props.frequency)
const label = `${rule.display_name} · ${props.frequency}`
```

- [ ] For SuBing keep `enabled_for_product` and current product-level semantics.
- [ ] Never render seven HTDY switches and never display “火天大有 · 全周期”.

### Step 9.4: Thread current frequency through components

- [ ] `ProductCheckSidebar.vue` passes its existing `frequency` prop to `ProductAlertRules`.
- [ ] `chart.vue` passes `frequency` and `setAlertProductFrequencyEnabled` into `useProductAlertScope`.
- [ ] Do not add a frequency watcher that performs PUT. Switching period only recomputes the current Switch from `enabled_frequencies`.
- [ ] Symbol changes continue to refresh Alert state.

### Step 9.5: Browser acceptance sequence

- [ ] Playwright proves:

```text
JM 15m initial ON
switch JM to 5m -> 5m OFF and zero PUTs caused by switching
click 5m ON -> only /jm/5m pair PUT
switch to 15m -> 15m remains ON
switch to 5m and click OFF -> only /jm/5m pair PUT
switch to 15m -> 15m still ON
Overlay select/unselect -> zero Scope PUTs
```

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

## Task 10: Close canonical contracts and drift guards

**Files:**

- Modify: `docs/INDICATOR_KERNEL.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `DECISIONS.md`
- Modify: `tests/engineering/test_canonical_consistency.py`
- Modify: `STATUS.md` only when the recorded implementation/test/review facts have actually occurred

### Step 10.1: Add canonical consistency assertions

- [ ] Lock these facts without copying the whole Spec:

```text
HTDY stable Rule code = htdy_original_15m
HTDY capability = seven formal frequencies
HTDY Scope authority = scope_product_frequencies
SuBing Scope authority = scope_products
HTDY storage/business Event identity includes frequency
SuBing business Event identity remains bar-level in Service
D1/W1 Alert source = Canonical-updated seam, not Live daily/weekly aggregation
```

- [ ] Keep the existing “one production Rule registry per language” guard valid; new production files import registry constants instead of scattering Rule-code literals.

### Step 10.2: Update active canonical after behavior exists

- [ ] `docs/INDICATOR_KERNEL.md`: replace HTDY 15m-only Alert wording with seven-frequency current-event observation while retaining future/repaint/backtest prohibitions.
- [ ] `PROJECT_SOURCE.md`: describe pair Scope, D1/W1 Canonical trigger, and no replay/backfill/retry/order.
- [ ] `AGENTS.md`: replace old `htdy_original_15m × scope_products` formula with frequency-pair Scope while preserving external-operation gates.
- [ ] `docs/DEVELOPMENT.md`: update only the active Alert bounded-authorization wording.
- [ ] `DECISIONS.md`: record one HTDY Rule, pair Scope, Live intraday + Canonical D1/W1, no second scheduler/Scope table.
- [ ] Do not rewrite the approved Spec to pretend implementation existed during design.

### Step 10.3: STATUS discipline

- [ ] Record `CODE_COMPLETE` / `TEST_COMPLETE` only after exact-head evidence exists.
- [ ] Record `REVIEW_COMPLETE` only after independent Review completes and all Critical/Important findings are fixed and reverified.
- [ ] Never infer `RELEASED`, `RUNTIME_PROMOTED`, production migration applied, real notification verified, or natural D1/W1 evidence from code/test completion.

Run:

```bash
uv run --offline --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
git diff --check
```

### Step 10.4: Commit

```bash
git add \
  docs/INDICATOR_KERNEL.md \
  PROJECT_SOURCE.md \
  AGENTS.md \
  docs/DEVELOPMENT.md \
  DECISIONS.md \
  tests/engineering/test_canonical_consistency.py
git commit -m "docs: align HTDY all-frequency contracts"
```

If `STATUS.md` has a new true implementation/test fact at this exact head, commit that factual update separately; otherwise do not touch it.

---

## Task 11: Run focused verification, full verification, and read-only Active60 × seven-frequency coverage

### Step 11.1: Focused backend

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

- [ ] Run isolated migration coverage only against `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL="$GUIYI_ISOLATED_MIGRATION_DATABASE_URL" \
uv run --offline --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_htdy_frequency_scope_migration.py
```

### Step 11.2: Focused Web

- [ ] Run:

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/alert-v1.spec.mjs
```

### Step 11.3: Full baseline

- [ ] Run:

```bash
uv run --offline --project services/quant-api pytest -q \
  -m "not isolated_postgresql" services/quant-api/tests

uv run --offline --project services/quant-api pytest -q tests/engineering

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

### Step 11.4: Read-only Active60 × seven-frequency matrix

- [ ] Assert the current checked-in `load_operational_products()` acceptance baseline contains 60 products.
- [ ] For every operational product and all seven frequencies, verify the code-defined HTDY capability admits the pair; no HTDY product list is hard-coded outside operational universe.
- [ ] Use existing provider-free/local read paths to classify Market data as ready or typed unavailable. Do not invoke RQData, maintenance, Canonical writes, or real Scope changes to manufacture readiness.
- [ ] Verify the Web capability is frequency-universal and product-independent through existing TypeScript tests rather than creating 420 duplicated UI fixtures.
- [ ] Report matrix output only as capability/data-availability coverage, never as strategy validity, profitability, backtest validity, or notification delivery evidence.

### Step 11.5: Failure rule

If any required check fails, do not mark TEST_COMPLETE or request integration. Fix only approved-scope defects and rerun the failed check plus every check whose assumptions changed.

---

## Task 12: Independent Lane 3 Review and integration Gate

### Step 12.1: Open independent Review session

- [ ] Review exact implementation base-to-head against `STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/INDICATOR_KERNEL.md`, the approved Spec, and this Plan.
- [ ] Reviewer explicitly checks:

```text
no HTDY formula/XMA change
no future/repaint risk laundering
legacy Scope migrates only to 15m
no HTDY/SuBing dual Scope authority
SuBing same-bar identity remains protected
HTDY same-time cross-frequency Events coexist
no D1/W1 Live reaggregation
canonical_updated no-backfill behavior
single Switch mutates only current symbol × frequency
frequency/Overlay switching causes no hidden Scope writes
no retry/replay/queue/outbox/order
no production migration/real notification/Runtime mutation during implementation
```

### Step 12.2: Fix Review findings and reverify

- [ ] Fix every Critical and Important finding before integration.
- [ ] Rerun affected focused tests after each fix.
- [ ] Rerun the full verification block after the final Review fix commit.
- [ ] Update `STATUS.md` only with the exact truthful Test/Review state then achieved.

### Step 12.3: Integration Gate

- [ ] Implementation PR targets `develop`.
- [ ] Integrate only after the explicit conclusion:

```text
允许集成 develop
```

- [ ] After merge, read back remote `develop`, then clean the merged task worktree/branch.
- [ ] Do not combine integration with production migration, real HTDY Scope mutation, real notification, `main` release/tag, or Runtime promotion. Each remains a separate explicit external-operation Gate.

---

## Expected implementation commit sequence

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
11. fix: only when verification/review identifies a concrete approved-scope defect
```

## Plan self-review

- Spec coverage: every approved requirement has an implementation Task: seven-frequency Overlay, current `symbol × frequency` Switch, pair Scope persistence/API, legacy 15m-only migration inheritance, HTDY/SuBing Event identity split, intraday Live triggers, D1/W1 Canonical trigger, separate cross-frequency notifications, no-backfill, repaint boundaries, and external-operation Gates.
- Placeholder scan: no `TBD`, `TODO`, ellipsis function bodies, unresolved migration revision, unnamed core method, or unresolved Scope/error-code choice remains.
- Type consistency: backend uses Rule-definition string frequencies at HTTP/storage boundaries and `BarFrequency` in Market/Runtime internals; Web uses `MarketFrequency`; Rule code remains the stable legacy string.
- Scope check: no third Alert table, second scheduler, second daily/weekly fact chain, general Strategy adapter, generic Scope framework, retry/replay system, or order path is introduced.
- Gate check: implementation/test work is separated from production migration, real Scope mutation, real notification, release/tag, and Runtime promotion.
