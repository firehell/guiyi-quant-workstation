# Alert V2 Backend / Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Design source: `docs/superpowers/specs/2026-08-14-decision-compression-alert-v2-design.md`  
Design review: user-approved in conversation on 2026-08-14  
Lane: **Lane 3**

**Goal:** 把 v1.2 已自然验收的 HTDY Alert V1 扩展为 code-defined Alert V2，使现有 SuBing 5m/15m `resolved_signal` 能在逐品种显式 Scope 下形成唯一 AlertEvent、one-shot WeCom 和只读 current views，同时不恢复 Signal/Review/Strategy、不复制 SuBing 公式、不改变 Data Foundation。

**Architecture:** Alert 静态规则定义收回代码 Registry，PostgreSQL `alert_rules` 只保存 `rule_code/enabled/scope_products/timestamps`；`alert_events` 保存不可变应用事实。单一 Alert Runtime 消费 completed 5m/15m Pub/Sub：HTDY 保持 event-cutoff evaluator，SuBing 读取当前 `SubingReadService.snapshot()`，先执行 incoming event identity stale guard，再消费既有 `resolved_signal`。当前交易日由已有 `MarketPhaseResolver` 对 operational products 唯一解析，供首页 Formal Signal 和 Product 当前事件两个专用只读 API 共用。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic / PostgreSQL / Redis PubSub / pytest / Ruff / Mypy；现有 `MarketReadService`、`MarketPhaseResolver`、`SubingReadService`、Indicator Kernel；企业微信现有 webhook sender。

## Global Constraints

- `STATUS.md` 当前确认正式 Runtime 仍运行 `v1.2.0`；本计划只实现和验证仓库代码，不执行 production migration、Runtime switch、release/tag、真实 Scope 写入或真实 WeCom。
- Data Foundation Frozen：不得修改 `DatasetKey`、八表 Market Catalog、Canonical Parquet、MainContractMap 或 `MarketDataService` 历史读取合同。
- Alert V2 仍是独立 Application Domain；不得恢复旧 Signal/Review/Strategy HTTP、worker、DB 表或任务中心。
- `auto_order=false` 始终成立；不得新增账户、仓位、订单创建/提交或自动交易路径。
- SuBing 数学事实继续只由现有 Factor / accepted Calibration / FormalPolicy / resolver 决定；Alert 不复制 slope、MACD、volume、companion 或 same-boundary 15m-wins 逻辑。
- SuBing V2 不实现 `snapshot_at()`、event-time reconstruction、replay/backfill、queue、outbox、retry worker 或 dead-letter。
- SuBing 实时路径必须执行 stale-event identity guard：current primary `bar_end/trading_day` 与 incoming completed Bar 不一致时直接 drop。
- 最终 Session 收线 Bar 在 `bar_end + 2s` 后才由 Live 发布，此时 `MarketPhaseResolver` 已可能为 `CLOSED`。Runtime 必须复用 Live 既有 60 秒 Session-end arrival grace 与该 Bar 的真实 TradingSession：只在 `processing_now ∈ [bar_end, bar_end + grace]` 且 `bar_end == session.end` 时，用 `bar_end - 1 microsecond` 作为 `SubingReadService.snapshot()` 的 phase-observation `now`，使刚发布的 current Live Bar 可见；仍读取完整 current snapshot 并执行相同 identity guard。超过 grace 直接 drop，不得借此恢复旧消息、构造 cutoff 或实现 `snapshot_at()`。
- HTDY 必须保持 v1.2 已验收的 `MarketReadService.bars_until(event cutoff)` 行为，不因为 SuBing 的实时取舍而退化。
- 一个 SuBing Rule 开关覆盖 5m + 15m；同一 15m boundary 的 5m Pub/Sub 只做触发抑制，等待 15m message 后消费既有 resolver；不得新增第二套 Signal 优先规则。
- `subing_entry_signal_v1` migration seed 必须 `enabled=true, scope_products=[]`；不得复制 HTDY 当前 Scope，也不得自动扩到 operational 60。
- AlertEvent 唯一身份固定为 `(rule_id, symbol, bar_end)`；`frequency` 是 resolved result 属性。
- 新 Event 直接保存 incoming completed Bar 的 `trading_day`；legacy V1 Event 不从 `bar_end` 猜测或回填。
- 当前交易日 resolver 必须复用 `MarketPhaseResolver + operational_products`；无法得到唯一交易日时返回 `unavailable`，不得猜最近交易日。
- Rule Scope 开启/关闭是生产 DB 写入；代码测试只能使用隔离数据库。真实 Scope activation 留给独立 rollout plan。
- 普通代码可以按当前 `AGENTS.md` 直接在 `develop` 日常流实现；Lane 3 建议新会话 + Sol 高推理 + Plan 批准后执行 + 独立 Review。worktree/PR 是按需工具，不是仓库强制 Gate。
- 所有测试命令以执行时 `TESTING.md` 为准；不得执行 `runtime alert-canary`、`--confirm-alert-runtime` 或 production Alembic upgrade 作为普通测试。

---

## Start Readback

Task 1 开始前只读确认：

```text
1. STATUS.md 仍确认 v1.2.0 Runtime、HTDY jm Scope 与 SuBing accepted calibration 事实
2. AGENTS.md / docs/DEVELOPMENT.md 外部 mutation Gate 无新冲突
3. PROJECT_SOURCE.md / DECISIONS.md 仍冻结八表、MarketDataService、auto_order=false
4. docs/ARCHITECTURE.md 仍显示单 Alert Runtime、Alert V1 两张 Application Domain 表
5. subing_calibration_intraday_v1.json 仍是 accepted slope-only identity
6. services/quant-api/app/market_data/subing_read_service.py 的 primary/resolved semantics 无变化
7. LiveMarketService 仍按 TradingSession 完成 5m/15m aggregation 并 publish
```

若事实源变化与本计划冲突，停止并回到设计，不自行兼容旧/新两套语义。

---

## File Map

### New backend files

- Create: `services/quant-api/app/alerts/registry.py` — 两条 code-defined Rule 的唯一静态 metadata Registry。
- Create: `services/quant-api/app/alerts/current_trading_day.py` — 基于现有 `MarketPhaseResolver` 的 current trading day 纯编排逻辑。
- Create: `services/quant-api/alembic/versions/20260814_0038_alert_v2.py` — V1 → V2 Application Domain destructive migration；不触碰 Market Catalog。
- Create: `services/quant-api/tests/test_alert_registry.py`。
- Create: `services/quant-api/tests/test_alert_current_trading_day.py`。
- Create: `services/quant-api/tests/alembic/test_alert_v2_migration.py`。

### Existing backend files to modify

- Modify: `services/quant-api/app/alerts/models.py` — AlertRule/AlertEvent V2 ORM。
- Modify: `services/quant-api/app/alerts/service.py` — Registry-backed Scope、V2 Event、current read methods。
- Modify: `services/quant-api/app/alerts/evaluators.py` — HTDY evaluator contract 只保留 HTDY 责任；不加 SuBing 数学。
- Modify: `services/quant-api/app/alerts/runtime.py` — 5m/15m parser、Rule dispatch、boundary defer、stale guard、fault isolation。
- Modify: `services/quant-api/app/alerts/composition.py` — 注入 HTDY evaluator、`build_subing_read_service` 和 shared sender。
- Modify: `services/quant-api/app/alerts/wecom.py` — code-defined HTDY/SuBing renderer + shared transport。
- Modify: `services/quant-api/app/market_data/live_market.py` — 将现有 60 秒 Session-end arrival grace 提升为 Live/Alert 共用的 public constant；不改变 Live 发布、finalization 或 grace 行为。
- Modify: `services/quant-api/app/schemas/alerts.py` — V2 Scope/Event/current DTO。
- Modify: `services/quant-api/app/api/alerts.py` — Product Scope、history events、current formal signals、product current-events。
- Modify: `services/quant-api/app/services/runtime_health.py` only if heartbeat validation needs V2 count semantics; do not add per-rule health platform.
- Modify: `services/quant-api/app/guiyi_cli/main.py` only if Alert Runtime factory contract changes require typing/import adaptation; CLI command names remain unchanged.

### Existing tests to modify

- Modify: `services/quant-api/tests/test_alert_models.py`。
- Modify: `services/quant-api/tests/test_alert_service.py`。
- Modify: `services/quant-api/tests/test_alert_evaluator.py` only for HTDY regression if interface changes。
- Modify: `services/quant-api/tests/test_alert_wecom.py`。
- Modify: `services/quant-api/tests/test_alert_runtime.py`。
- Modify: `services/quant-api/tests/data_foundation/test_live_market.py` — 锁定 public grace 仍为 60 秒，并让既有超时拒绝测试引用同一常量；不改变 Live 行为。
- Modify: `services/quant-api/tests/test_alert_api.py`。
- Modify: `services/quant-api/tests/test_alert_cli.py` only if composition signature changes affect CLI fixtures。
- Modify: `services/quant-api/tests/test_runtime_health.py` only if heartbeat behavior changes。

### Canonical/docs after executable code is complete

- Modify: `AGENTS.md`。
- Modify: `PROJECT_SOURCE.md`。
- Modify: `DECISIONS.md`。
- Modify: `docs/DEVELOPMENT.md`。
- Modify: `docs/ARCHITECTURE.md`。
- Modify: `TESTING.md`。
- Modify: `STATUS.md` only after code/tests are actually complete; record code readiness and explicitly state production migration / Runtime promotion / SuBing Scope remain unexecuted.

---

### Task 1: Code-defined Rule Registry and V2 ORM contract

**Lane:** Lane 3  
**Recommended:** Sol / 高推理 / 独立 Review

**Files:**
- Create: `services/quant-api/app/alerts/registry.py`
- Modify: `services/quant-api/app/alerts/models.py`
- Create: `services/quant-api/tests/test_alert_registry.py`
- Modify: `services/quant-api/tests/test_alert_models.py`

**Interfaces:**

```python
class AlertRuleKind(StrEnum):
    INDICATOR_OBSERVATION = "indicator_observation"
    FORMAL_SIGNAL = "formal_signal"

@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    rule_code: str
    display_name: str
    kind: AlertRuleKind
    input_frequencies: tuple[str, ...]
    series_kind: str


def alert_rule_definitions() -> tuple[AlertRuleDefinition, ...]: ...
def get_alert_rule_definition(rule_code: str) -> AlertRuleDefinition: ...
```

Exact definitions:

```python
HTDY_RULE = AlertRuleDefinition(
    rule_code="htdy_original_15m",
    display_name="火天大有",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    input_frequencies=("15m",),
    series_kind="actual_dominant",
)
SUBING_RULE = AlertRuleDefinition(
    rule_code="subing_entry_signal_v1",
    display_name="苏冰入场信号",
    kind=AlertRuleKind.FORMAL_SIGNAL,
    input_frequencies=("5m", "15m"),
    series_kind="actual_dominant",
)
```

V2 ORM target:

```python
class AlertRule(Base):
    id
    rule_code
    enabled
    scope_products
    created_at
    updated_at

class AlertEvent(Base):
    id
    rule_id
    symbol
    contract
    trading_day       # nullable in DB for legacy V1 compatibility
    frequency
    bar_end
    result_codes
    lower_tf_confirmation
    detected_at
    notification_attempted_at
    created_at
```

- [ ] **Step 1: Write Registry tests before implementation**

```python
from app.alerts.registry import AlertRuleKind, alert_rule_definitions, get_alert_rule_definition


def test_registry_has_exact_two_v2_rules() -> None:
    definitions = alert_rule_definitions()
    assert tuple(item.rule_code for item in definitions) == (
        "htdy_original_15m",
        "subing_entry_signal_v1",
    )
    assert get_alert_rule_definition("htdy_original_15m").kind is AlertRuleKind.INDICATOR_OBSERVATION
    subing = get_alert_rule_definition("subing_entry_signal_v1")
    assert subing.kind is AlertRuleKind.FORMAL_SIGNAL
    assert subing.input_frequencies == ("5m", "15m")
    assert subing.series_kind == "actual_dominant"


def test_unknown_rule_definition_fails_closed() -> None:
    with pytest.raises(KeyError):
        get_alert_rule_definition("unknown_rule")
```

- [ ] **Step 2: Run Registry tests and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py
```

Expected: FAIL because `app.alerts.registry` does not exist.

- [ ] **Step 3: Implement the minimal immutable Registry**

Create only the exact two definitions above. `get_alert_rule_definition()` normalizes `str(rule_code).strip()` and raises `KeyError` for anything outside the fixed mapping. Do not add dynamic registration, plugins, DB-driven metadata, rule DSL or generic handler discovery.

- [ ] **Step 4: Update ORM tests for the exact V2 schema**

Add assertions equivalent to:

```python
rule_columns = set(AlertRule.__table__.columns.keys())
assert rule_columns == {
    "id", "rule_code", "enabled", "scope_products", "created_at", "updated_at"
}

event_columns = set(AlertEvent.__table__.columns.keys())
assert event_columns == {
    "id", "rule_id", "symbol", "contract", "trading_day", "frequency",
    "bar_end", "result_codes", "lower_tf_confirmation", "detected_at",
    "notification_attempted_at", "created_at",
}
assert AlertEvent.__table__.c.trading_day.nullable is True
```

Also assert the unique constraint column tuple is exactly `("rule_id", "symbol", "bar_end")` and existing `(symbol, bar_end)` index remains.

- [ ] **Step 5: Implement ORM V2 contract**

Use `Date()` for `trading_day`, existing ARRAY-with-SQLite-JSON pattern for `result_codes`, and `Boolean(default=False, nullable=False)` for `lower_tf_confirmation`. Keep PostgreSQL check constraint `result_codes` subset of `buy/sell` and cardinality 1..2. Remove `indicator_code`, `frequency`, `scope_mode` from `AlertRule`.

- [ ] **Step 6: Run focused tests to GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_models.py
```

- [ ] **Step 7: Commit focused domain changes**

```bash
git add \
  services/quant-api/app/alerts/registry.py \
  services/quant-api/app/alerts/models.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_models.py
git commit -m "refactor: define alert v2 rule contracts"
```

---

### Task 2: Destructive V1 → V2 Alembic migration with fail-closed collision check

**Lane:** Lane 3  
**Recommended:** Sol / 高推理 / 独立 Review

**Files:**
- Create: `services/quant-api/alembic/versions/20260814_0038_alert_v2.py`
- Create: `services/quant-api/tests/alembic/test_alert_v2_migration.py`
- Reuse as historical baseline: `services/quant-api/alembic/versions/20260813_0037_alert_v1.py`

**Interfaces / exact migration contract:**

```text
revision = 20260814_0038
down_revision = 20260813_0037

alert_rules:
  keep id/rule_code/enabled/scope_products/created_at/updated_at
  drop indicator_code/frequency/scope_mode and related check constraints

alert_events:
  rename observation_types -> result_codes
  rename notified_at -> notification_attempted_at
  add trading_day DATE NULL
  add lower_tf_confirmation BOOLEAN NOT NULL DEFAULT false
  replace unique(rule_id,symbol,frequency,bar_end)
       with unique(rule_id,symbol,bar_end)
  replace observation check constraint with result_codes check
  preserve ix_alert_events_symbol_bar_end

seed:
  insert subing_entry_signal_v1, enabled=true, scope_products=[]
  preserve existing htdy row and scope exactly
```

- [ ] **Step 1: Write migration recording tests**

Create a recorder that captures `drop_constraint`, `alter_column`, `add_column`, `drop_column`, `create_unique_constraint`, `create_check_constraint`, `bulk_insert` and `get_bind`. Assert no Market Catalog table is changed.

Test target:

```python
def test_alert_v2_upgrade_changes_only_alert_application_schema() -> None:
    migration = _load_migration()
    recorder = RecordingOperations(conflict_rows=[])
    migration.op = recorder
    migration.upgrade()

    assert migration.revision == "20260814_0038"
    assert migration.down_revision == "20260813_0037"
    assert recorder.market_table_mutations == []
    assert ("alert_rules", "indicator_code") in recorder.dropped_columns
    assert ("alert_rules", "frequency") in recorder.dropped_columns
    assert ("alert_rules", "scope_mode") in recorder.dropped_columns
    assert ("alert_events", "observation_types", "result_codes") in recorder.renamed_columns
    assert ("alert_events", "notified_at", "notification_attempted_at") in recorder.renamed_columns
    assert recorder.seed_rows == [{
        "rule_code": "subing_entry_signal_v1",
        "enabled": True,
        "scope_products": [],
    }]
```

- [ ] **Step 2: Add collision precheck test**

The migration must query before replacing the unique constraint:

```sql
SELECT rule_id, symbol, bar_end, COUNT(*) AS n
FROM alert_events
GROUP BY rule_id, symbol, bar_end
HAVING COUNT(*) > 1
LIMIT 1
```

Test:

```python
def test_alert_v2_upgrade_refuses_new_identity_collision() -> None:
    migration = _load_migration()
    recorder = RecordingOperations(conflict_rows=[(1, "jm", "2026-08-14T02:30:00+00:00", 2)])
    migration.op = recorder
    with pytest.raises(RuntimeError, match="ALERT_V2_EVENT_IDENTITY_CONFLICT"):
        migration.upgrade()
    assert recorder.destructive_schema_started is False
```

- [ ] **Step 3: Run migration tests and verify RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_alert_v2_migration.py
```

Expected: FAIL because migration does not exist.

- [ ] **Step 4: Implement `20260814_0038_alert_v2.py`**

Use `op.get_bind()` for collision query first. Only after zero conflicts, perform Alert Application schema operations. Do not create `(trading_day, bar_end)` index in V2. Do not touch eight Market Catalog tables.

For legacy rows:

```text
result_codes = renamed observation_types value
notification_attempted_at = renamed notified_at value
lower_tf_confirmation = false
trading_day = NULL
```

For new Rule seed, use a minimal `sa.table` with only `rule_code`, `enabled`, `scope_products`.

- [ ] **Step 5: Make downgrade explicitly fail closed rather than inventing lossy V1 semantics**

Because V2 can contain a multi-frequency SuBing Rule and V2-only Event facts, do not silently squash them into V1 columns. Implement:

```python
def downgrade() -> None:
    raise RuntimeError("ALERT_V2_DOWNGRADE_UNSUPPORTED")
```

Add a test that asserts the stable code. This repository does not require rollback artifacts as an authorization mechanism; future rollback is a separately designed operation.

- [ ] **Step 6: Run V1 and V2 migration tests together**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_alert_v1_migration.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py
```

- [ ] **Step 7: Commit migration only after tests pass**

```bash
git add \
  services/quant-api/alembic/versions/20260814_0038_alert_v2.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py
git commit -m "feat: migrate alert application to v2"
```

Do **not** run production `alembic upgrade` in this task.

---

### Task 3: AlertService V2 and current trading day resolver

**Lane:** Lane 3  
**Recommended:** Sol / 高推理

**Files:**
- Create: `services/quant-api/app/alerts/current_trading_day.py`
- Modify: `services/quant-api/app/alerts/service.py`
- Create: `services/quant-api/tests/test_alert_current_trading_day.py`
- Modify: `services/quant-api/tests/test_alert_service.py`

**Interfaces:**

```python
class CurrentTradingDayStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True, slots=True)
class CurrentTradingDayResult:
    status: CurrentTradingDayStatus
    trading_day: date | None

class ProductPhaseResolver(Protocol):
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase: ...


def resolve_current_trading_day(
    phase_resolver: ProductPhaseResolver,
    *,
    products: tuple[str, ...],
    now: datetime,
) -> CurrentTradingDayResult: ...
```

Alert service DTO target:

```python
@dataclass(frozen=True, slots=True)
class ProductAlertRuleState:
    rule_code: str
    display_name: str
    kind: str
    input_frequencies: tuple[str, ...]
    enabled_for_product: bool

@dataclass(frozen=True, slots=True)
class AlertEventCreate:
    rule_id: int
    symbol: str
    contract: str
    trading_day: date
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime
```

- [ ] **Step 1: Write current trading day resolver tests**

Use a fake phase resolver and explicit dates:

```python
def test_resolver_prefers_unique_trading_break_day() -> None:
    result = resolve_current_trading_day(
        FakePhases({
            "jm": ProductMarketPhase("jm", MarketPhase.TRADING, date(2026, 8, 15), None, None),
            "rb": ProductMarketPhase("rb", MarketPhase.BREAK, date(2026, 8, 15), None, None),
        }),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )
    assert result.status is CurrentTradingDayStatus.READY
    assert result.trading_day == date(2026, 8, 15)


def test_resolver_conflicting_active_days_is_unavailable() -> None:
    result = resolve_current_trading_day(
        FakePhases({
            "jm": ProductMarketPhase("jm", MarketPhase.TRADING, date(2026, 8, 15), None, None),
            "rb": ProductMarketPhase("rb", MarketPhase.TRADING, date(2026, 8, 14), None, None),
        }),
        products=("jm", "rb"),
        now=aware("2026-08-14T21:10:00+08:00"),
    )
    assert result.status is CurrentTradingDayStatus.UNAVAILABLE
    assert result.trading_day is None
```

Also cover CLOSED unique day, UNKNOWN-only, weekend/no day.

- [ ] **Step 2: Run resolver test to RED, implement exact spec algorithm, then GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_current_trading_day.py
```

Implementation must choose unique `{TRADING,BREAK}` day first; only when there is no active day may it consider unique CLOSED day. `UNKNOWN` never contributes.

- [ ] **Step 3: Rewrite AlertService tests around Registry metadata and V2 Event identity**

Add focused cases:

```python
def test_product_rules_exposes_registry_metadata_and_independent_scopes(session) -> None:
    seed_v2_rules(session, htdy_scope=["jm"], subing_scope=[])
    states = AlertService(session, operational_products=("jm",)).product_rules("jm")
    assert [(s.rule_code, s.kind, s.enabled_for_product) for s in states] == [
        ("htdy_original_15m", "indicator_observation", True),
        ("subing_entry_signal_v1", "formal_signal", False),
    ]


def test_create_event_duplicate_identity_returns_none(session) -> None:
    rule = seed_rule(session, "subing_entry_signal_v1")
    request = event_request(rule.id, frequency="15m", bar_end=BAR_END)
    assert AlertService(session, operational_products=("jm",)).create_event(request) is not None
    assert AlertService(session, operational_products=("jm",)).create_event(request) is None
```

Add a consistency test where same `(rule,symbol,bar_end)` has different contract/result/frequency and must raise `ALERT_EVENT_CONSISTENCY_ERROR`.

- [ ] **Step 4: Implement service V2**

Requirements:

```text
product_rules():
  DB rows must have Registry definitions; unknown rule_code fails closed
  state metadata comes from Registry only

set_product_enabled():
  same exact product scope mutation behavior
  no scope_mode

create_event():
  event frequency must be in Registry definition.input_frequencies
  new trading_day required
  normalize result_codes to buy/sell order
  duplicate identity query uses rule_id + symbol + bar_end only
  duplicate is idempotent only when contract/frequency/trading_day/result_codes/lower_tf_confirmation all match
```

Add read methods:

```python
def list_current_formal_signal_events(self, *, trading_day: date) -> tuple[AlertEvent, ...]: ...
def list_current_product_events(self, *, symbol: str, trading_day: date) -> tuple[AlertEvent, ...]: ...
```

`list_current_formal_signal_events` derives the allowed formal rule codes from Registry, joins/filter DB rows, and orders `bar_end DESC`. It does not accept arbitrary filters.

- [ ] **Step 5: Run resolver + service tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_service.py
```

- [ ] **Step 6: Commit service read-model changes**

```bash
git add \
  services/quant-api/app/alerts/current_trading_day.py \
  services/quant-api/app/alerts/service.py \
  services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_service.py
git commit -m "feat: add alert v2 event read model"
```

---

### Task 4: V2 HTTP contracts and two current-view endpoints

**Lane:** Lane 3  
**Recommended:** Sol / 高推理

**Files:**
- Modify: `services/quant-api/app/schemas/alerts.py`
- Modify: `services/quant-api/app/api/alerts.py`
- Modify: `services/quant-api/tests/test_alert_api.py`

**Interfaces:**

```python
class ProductAlertRuleStateOut(BaseModel):
    rule_code: str
    display_name: str
    kind: str
    input_frequencies: list[str]
    enabled_for_product: bool

class AlertEventOut(BaseModel):
    id: int
    rule_code: str
    symbol: str
    contract: str
    trading_day: date | None
    frequency: str
    bar_end: datetime
    result_codes: list[str]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime

class CurrentAlertEventsResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    trading_day: date | None
    items: list[AlertEventOut]
```

Formal current item additionally contains `display_name` and `product_name`.

- [ ] **Step 1: Write failing API tests for Product Rule State V2**

```python
def test_product_alert_state_returns_registry_metadata(client, db_session) -> None:
    seed_v2_rules(db_session)
    response = client.get("/api/alerts/products/jm")
    assert response.status_code == 200
    rules = response.json()["rules"]
    assert rules == [
        {
            "rule_code": "htdy_original_15m",
            "display_name": "火天大有",
            "kind": "indicator_observation",
            "input_frequencies": ["15m"],
            "enabled_for_product": False,
        },
        {
            "rule_code": "subing_entry_signal_v1",
            "display_name": "苏冰入场信号",
            "kind": "formal_signal",
            "input_frequencies": ["5m", "15m"],
            "enabled_for_product": False,
        },
    ]
```

- [ ] **Step 2: Write failing current endpoint tests**

Inject a fixed phase resolver/clock using the existing API dependency override pattern. Assert:

```python
formal = client.get("/api/alerts/formal-signals/current").json()
assert formal["status"] == "ready"
assert formal["trading_day"] == "2026-08-15"
assert [item["rule_code"] for item in formal["items"]] == ["subing_entry_signal_v1"]

product = client.get("/api/alerts/products/jm/current-events").json()
assert {item["rule_code"] for item in product["items"]} == {
    "htdy_original_15m",
    "subing_entry_signal_v1",
}
```

Also assert `unavailable` returns `items=[]` rather than a false empty-signal success.

- [ ] **Step 3: Run API tests to RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py
```

- [ ] **Step 4: Implement schemas and API endpoints**

Keep existing routes:

```text
GET /api/alerts/products/{symbol}
PUT /api/alerts/rules/{rule_code}/scope/{symbol}
GET /api/alerts/events?symbol=&rule_code=&start=&end=
```

Add only:

```text
GET /api/alerts/formal-signals/current
GET /api/alerts/products/{symbol}/current-events
```

Both current endpoints call the same `resolve_current_trading_day()` helper. `product_name` comes from existing `load_product_taxonomy()`; do not duplicate taxonomy in Web or Alert tables.

- [ ] **Step 5: Run API + service tests GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_current_trading_day.py
```

- [ ] **Step 6: Commit HTTP contract**

```bash
git add \
  services/quant-api/app/schemas/alerts.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/tests/test_alert_api.py
git commit -m "feat: expose current alert v2 views"
```

---

### Task 5: Code-defined WeCom renderers without a template platform

**Lane:** Lane 3  
**Recommended:** Sol / 高推理

**Files:**
- Modify: `services/quant-api/app/alerts/wecom.py`
- Modify: `services/quant-api/tests/test_alert_wecom.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationMessage:
    rule_code: str
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool = False

class WeComWebhookSender:
    def send(self, event: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> None: ...
```

- [ ] **Step 1: Preserve exact HTDY formatting in a regression test**

```python
def test_htdy_message_keeps_v1_copy() -> None:
    text = format_alert_message(AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=aware_utc("2026-08-13T14:30:00+00:00"),
        result_codes=("sell",),
    ))
    assert "火天大有 · 卖出观察" in text
    assert "15m" in text
```

- [ ] **Step 2: Write exact SuBing copy tests**

```python
def test_subing_5m_message_is_short() -> None:
    text = format_alert_message(AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="5m",
        bar_end=aware_shanghai("2026-08-14T10:25:00+08:00"),
        result_codes=("buy",),
    ))
    assert text == "【苏冰】焦煤 · JM2609\n\n5m 买入信号 · 10:25"


def test_subing_15m_lower_tf_confirmation_adds_one_line() -> None:
    text = format_alert_message(AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=aware_shanghai("2026-08-14T10:30:00+08:00"),
        result_codes=("buy",),
        lower_tf_confirmation=True,
    ))
    assert text.endswith("15m 买入信号 · 10:30\n5m 同向确认")
```

Also assert SuBing rejects both buy+sell, unsupported frequency, unknown rule and missing identity.

- [ ] **Step 3: Run WeCom tests to RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wecom.py
```

- [ ] **Step 4: Implement two fixed code renderers and shared transport**

Keep webhook validation and HTTP transport unchanged. `format_alert_message()` dispatches by `rule_code`; no DB template, environment template, user-editable copy, JSON payload extension or Rule DSL.

- [ ] **Step 5: Run tests GREEN and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wecom.py

git add services/quant-api/app/alerts/wecom.py services/quant-api/tests/test_alert_wecom.py
git commit -m "feat: render subing alert messages"
```

---

### Task 6: Single Alert Runtime V2 dispatch, boundary defer and stale-event guard

**Lane:** Lane 3  
**Recommended:** Sol / 高推理 / 独立 Review mandatory

**Files:**
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/market_data/live_market.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/data_foundation/test_live_market.py`
- Modify only if required by signatures: `services/quant-api/tests/test_alert_cli.py`

**Interfaces:**

Runtime dependency additions:

```python
AlertSubingReadFactory = Callable[[Session], SubingReadService]

class AlertRuntime:
    def __init__(
        *,
        session_factory: AlertSessionFactory,
        market_read_factory: AlertMarketReadFactory,
        subing_read_factory: AlertSubingReadFactory,
        htdy_evaluator: HtdyOriginal15mEvaluator,
        sender: WeComWebhookSender,
        operational_products: tuple[str, ...],
        taxonomy: Mapping[str, ProductTaxonomyEntry],
        ...,
    ) -> None: ...


# app.market_data.live_market; existing value, newly public/shared
LIVE_SESSION_END_ARRIVAL_GRACE = timedelta(seconds=60)


def _event_session_window(
    session: Session,
    *,
    symbol: str,
    event_bar: CanonicalBar,
) -> SessionWindow | None: ...


def _subing_snapshot_now(
    *,
    event_bar: CanonicalBar,
    event_session: SessionWindow,
    processing_now: datetime,
) -> datetime | None: ...
```

`_event_session_window()` must resolve the active instrument exchange, require that exchange's `TradingCalendar` row for `event_bar.trading_day` to be a trading day, and call existing `resolved_session_windows_for_trading_day()`. Match `MarketPhaseResolver` by excluding `item.is_night` when that calendar row has `has_night_session != true`; then accept exactly one remaining window satisfying `window.start < event_bar.bar_end <= window.end`, otherwise return `None`. It must not copy TradingSession date anchoring or silently accept a night event on a no-night trading day.

`_subing_snapshot_now()` contract is exact:

```text
processing_now < event_bar.bar_end
-> None / drop

event_bar.bar_end != event_session.end
-> processing_now

event_bar.bar_end == event_session.end
AND processing_now <= event_bar.bar_end + LIVE_SESSION_END_ARRIVAL_GRACE
-> event_bar.bar_end - 1 microsecond

event_bar.bar_end == event_session.end
AND processing_now > event_bar.bar_end + LIVE_SESSION_END_ARRIVAL_GRACE
-> None / drop
```

The adjusted instant is only a phase-observation input to the existing current `SubingReadService.snapshot()`. It does not set a data cutoff: the service still reads the full current Redis snapshot, and the normal primary `bar_end/trading_day` guard remains mandatory.

Transport pattern becomes:

```text
live:bar:*:*
```

Parser accepts only `5m` / `15m` after validating exact channel shape and payload.

- [ ] **Step 1: Add parser and routing tests**

```python
def test_runtime_accepts_completed_5m_and_15m_channels() -> None:
    assert _parse_event("live:bar:jm:5m", payload("5m")) is not None
    assert _parse_event("live:bar:jm:15m", payload("15m")) is not None
    assert _parse_event("live:bar:jm:30m", payload("30m")) is None
```

Keep non-operational rejection.

- [ ] **Step 2: Add ordinary 5m SuBing MATCHED test**

Set DB scope to `subing_entry_signal_v1 × jm`, fake `SubingReadService.snapshot()` with primary READY matching incoming event and `resolved_signal=MATCHED/LONG/5m`.

```python
runtime.process_message("live:bar:jm:5m", event_payload)
assert event_rows(session)[0].frequency == "5m"
assert event_rows(session)[0].result_codes == ["buy"]
assert sender.messages == [expected_subing_message]
```

- [ ] **Step 3: Add stale-event guard tests before implementation**

```python
def test_stale_subing_snapshot_is_dropped_without_event_or_send() -> None:
    snapshot = subing_snapshot(primary_bar_end=INCOMING_END + timedelta(minutes=5))
    runtime = build_runtime(subing_snapshot=snapshot)
    runtime.process_message("live:bar:jm:5m", incoming_payload)
    assert event_rows(session) == []
    assert sender.messages == []
```

Mirror for trading_day mismatch and primary not READY.

- [ ] **Step 4: Add exact TradingSession resolution and same-boundary 5m defer tests**

Build real Instrument / TradingCalendar / TradingSession fixtures for `jm` and a 5m incoming Bar whose end is also the end of the existing 15m bucket. Assert `_event_session_window()` returns the one resolved window; also assert missing/non-trading calendar facts and a night Bar on `has_night_session=false` return `None`. Then assert:

```python
runtime.process_message("live:bar:jm:5m", boundary_payload)
assert subing_reader.calls == []
assert event_rows(session) == []
```

Then process the 15m payload and assert exactly one SuBing evaluation/Event.

The implementation must call `resolved_session_windows_for_trading_day()` and derive the boundary with `bucket_window_for_bar(event_session, BarFrequency.M15, event_bar.bar_end).end == event_bar.bar_end`; do not use current `MarketPhaseResolver.current_session`, because exact completed boundaries may already be `BREAK/CLOSED`, and do not use `minute % 15`.

- [ ] **Step 5: Add day and cross-midnight Session-end current handoff regressions**

Use real day-session and cross-midnight TradingSession fixtures. At an incoming completed 15m Bar whose `bar_end == event_session.end`, freeze Runtime clock at `bar_end + 2 seconds` and make the fake Subing reader record its `now` argument:

```python
runtime.process_message("live:bar:jm:15m", session_end_payload)
assert subing_reader.calls[0].now == SESSION_END - timedelta(microseconds=1)
assert len(event_rows(session)) == 1
assert len(sender.messages) == 1
```

Run the same contract for a cross-midnight session final Bar. Then use fresh isolated DB/reader/sender fixtures for each fail-closed case:

```python
runtime.clock = lambda: SESSION_END + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(microseconds=1)
runtime.process_message("live:bar:jm:15m", session_end_payload)
assert subing_reader.calls == []
assert event_rows(session) == []
assert sender.messages == []

runtime.clock = lambda: ORDINARY_END + timedelta(seconds=2)
runtime.process_message("live:bar:jm:5m", ordinary_payload)
assert subing_reader.calls[0].now == ORDINARY_END + timedelta(seconds=2)
```

These tests must prove the exception is limited to a just-published final Session Bar. They must not pass an old event timestamp to an unrestricted snapshot, add a cutoff API, or make a delayed session-end message replayable after the shared grace.

In `test_live_market.py`, retain the existing accepted-within-grace and rejected-after-grace behavior tests, assert `LIVE_SESSION_END_ARRIVAL_GRACE == timedelta(seconds=60)`, and replace the hard-coded overdue `61` seconds with `LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)`. This verifies the public/shared identity without changing Live semantics.

- [ ] **Step 6: Add existing resolver semantics as runtime regression only**

Use real `SubingReadSnapshot.resolved_signal` fixtures to assert:

```text
15m same-boundary winner -> one 15m Event, lower_tf_confirmation=true
resolved direction conflict / None -> no Event
reciprocal-only matched returned by SubingReadService -> one Event
```

Do not re-test or reimplement the internal slope/MACD formula in Alert tests.

- [ ] **Step 7: Add per-rule fault isolation test**

On a 15m Bar with both rules scoped:

```python
def test_subing_failure_does_not_block_htdy() -> None:
    runtime = build_runtime(subing_error=RuntimeError("x"), htdy_observations=("sell",))
    runtime.process_message("live:bar:jm:15m", payload)
    assert [row.rule.rule_code for row in event_rows(session)] == ["htdy_original_15m"]
```

Mirror HTDY failure → SuBing still creates Event.

- [ ] **Step 8: Add idempotency and one-shot failure regressions**

Process identical Pub/Sub twice; assert one Event and one send. Make sender fail; assert Event remains committed and second processing does not retry because unique Event already exists.

- [ ] **Step 9: Run runtime tests to RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 10: Implement Runtime V2 minimally**

Implementation shape:

```text
process_message
  parse symbol/frequency/event_bar
  reject non-operational
  open one short DB session
  load enabled DB rules
  pair each row with fixed Registry definition
  filter definition.input_frequencies + explicit scope
  for each eligible Rule independently:
    HTDY -> existing bars_until + evaluator
    SuBing -> resolve event TradingSession with existing session_clock facts
    SuBing 5m at 15m boundary -> defer/skip
    SuBing final Session Bar within shared arrival grace -> bounded phase-observation now
    SuBing final Session Bar outside shared arrival grace -> drop
    SuBing otherwise -> processing_now
    SuBing current snapshot -> identity guard -> resolved_signal
    normalized result -> create_event commit
    if newly created -> render/send once outside transaction
```

A SuBing session-resolution/grace failure skips only SuBing; it must not block the HTDY event-cutoff branch on the same 15m message. A rule exception is collapsed to a stable warning and must not stop later rules. Do not create worker pools, parallel tasks or in-memory cooldown state.

Promote the existing private Live grace constant to `LIVE_SESSION_END_ARRIVAL_GRACE` and use that same object in both `LiveMarketService._session_for_bar()` and Alert Runtime. Do not create a second grace duration or change Live finalization/publication behavior.

- [ ] **Step 11: Update composition**

`build_alert_runtime()` injects:

```python
market_read_factory=build_market_read_service
subing_read_factory=build_subing_read_service
htdy_evaluator=HtdyOriginal15mEvaluator()
```

Keep existing activation marker and exact webhook validation. No new Runtime marker or launchd label.

- [ ] **Step 12: Run runtime + SuBing + HTDY regression suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_wecom.py \
  services/quant-api/tests/data_foundation/test_aggregation.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_market_phase.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/test_subing_research.py \
  services/quant-api/tests/data_foundation/test_market_read.py
```

- [ ] **Step 13: Commit Runtime V2**

```bash
git add \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/app/market_data/live_market.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/test_alert_cli.py
git commit -m "feat: dispatch subing through alert runtime v2"
```

If `test_alert_cli.py` did not change, omit it from `git add`.

---

### Task 7: Heartbeat, CLI and API compatibility regression

**Lane:** Lane 3

**Files:**
- Modify only if required: `services/quant-api/app/services/runtime_health.py`
- Modify only if required: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`

**Contract:** CLI command names remain exactly:

```text
guiyi runtime status
guiyi runtime alert
guiyi runtime alert-canary
```

Heartbeat remains one object:

```json
{
  "available": true,
  "enabled_rule_count": 2,
  "scope_product_count": 1
}
```

`scope_product_count` is the unique union of operational symbols present in any enabled Rule scope, not the sum of Rule×Product pairs.

- [ ] **Step 1: Add health regression for two enabled rules sharing one product**

```python
def test_alert_health_accepts_v2_heartbeat_counts() -> None:
    heartbeat = {
        "generated_at": NOW.isoformat(),
        "available": True,
        "enabled_rule_count": 2,
        "scope_product_count": 1,
    }
    health = build_runtime_health(...)
    assert health["components"]["alert"]["status"] == "ok"
    assert health["components"]["alert"]["enabled_rule_count"] == 2
    assert health["components"]["alert"]["scope_product_count"] == 1
```

- [ ] **Step 2: Keep canary behavior rule-agnostic**

`runtime alert-canary` only proves the shared WeCom transport. It must not create Event, alter Scope, or imply SuBing activation. Add/retain CLI test assertions for no DB mutation.

- [ ] **Step 3: Run CLI/health focused tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py
```

- [ ] **Step 4: Make only necessary implementation changes and commit**

If current health/CLI already satisfy V2 after Runtime changes, do not edit production files; commit only changed tests with a precise message. Do not add per-rule heartbeat detail, delivery health or a second canary command.

---

### Task 8: Canonical authorization update and backend final verification

**Lane:** Lane 3 docs/contract closeout

**Files:**
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`
- Modify: `STATUS.md` only after Tasks 1-7 are actually complete
- Modify: `docs/superpowers/specs/2026-08-14-decision-compression-alert-v2-design.md` — change status from `Design Review` to `Design Approved` now that written-spec review was explicitly accepted; do not alter approved semantics.

**Canonical authorization text must be explicit, not generic:**

```text
Alert Runtime V2 bounded sustained authorization is limited to:

htdy_original_15m × that Rule's explicit scope_products × WeCom
+
subing_entry_signal_v1 × that Rule's explicit scope_products × WeCom

A future third Rule does not inherit authorization.
```

- [ ] **Step 1: Update canonical docs without declaring external Gates executed**

Each document must preserve its own responsibility:

```text
AGENTS.md          engineering/external-operation rule
PROJECT_SOURCE.md  long-term product/runtime boundary
DECISIONS.md       long-lived explicit decision
DEVELOPMENT.md     development + external mutation flow
ARCHITECTURE.md    component/data-flow architecture
TESTING.md         no-side-effect V2 commands and explicit external Gate warnings
STATUS.md          actual develop code readiness only; production migration/runtime/scope still pending
```

Do not paste implementation plan mechanics into canonical docs.

- [ ] **Step 2: Update TESTING.md Alert section**

Replace V1-only focused set with V2 tests including:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_wecom.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py \
  services/quant-api/tests/data_foundation/test_aggregation.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_market_phase.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
```

Document explicitly that production migration, Runtime promotion, SuBing Scope write and real notifications are not test commands.

- [ ] **Step 3: Run full backend verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py

python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

- [ ] **Step 4: Run render-only launchd regression; do not reload**

```bash
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

Expected: render/lint succeeds. This does not authorize or execute Runtime switch.

- [ ] **Step 5: Independent Lane 3 Review**

Reviewer must verify at minimum:

```text
no Alert copy of SuBing formula/resolver
no future data introduced by Alert
stale-event guard is fail-closed
final Session Bar is visible only inside the shared Live arrival grace
session-end phase observation does not create snapshot_at/cutoff/replay behavior
15m boundary defer uses TradingSession bucket semantics
HTDY cutoff path remains intact
migration never touches Market Catalog
scope seed is empty
no generic Rule runtime authorization
no retry/replay/outbox/order path
no production external operation executed
```

- [ ] **Step 6: Commit canonical closeout**

```bash
git add \
  AGENTS.md PROJECT_SOURCE.md DECISIONS.md TESTING.md STATUS.md \
  docs/DEVELOPMENT.md docs/ARCHITECTURE.md \
  docs/superpowers/specs/2026-08-14-decision-compression-alert-v2-design.md
git commit -m "docs: record alert v2 code boundaries"
```

STATUS wording must say code is ready on `develop` only if tests/review actually passed; explicitly leave production migration, v1.3 release, Runtime promotion and SuBing Scope activation pending.

---

## Backend Plan Acceptance

Before handing off to Web implementation, all of the following must be true:

```text
Rule Registry has exactly HTDY + SuBing V2 definitions
AlertRule DB contract no longer contains indicator_code/frequency/scope_mode
AlertEvent V2 fields and unique identity are covered by tests
V2 migration fails closed on identity collision and does not touch eight-table Market Catalog
legacy HTDY rows are preserved without invented trading_day
current trading day resolver is deterministic/fail-closed
current formal-signals and product current-events APIs exist
SuBing Runtime consumes current SubingReadService only after event identity guard
day and cross-midnight final Session Bars use the shared bounded arrival grace, then still pass the same current-snapshot identity guard
session-end messages outside that grace are dropped and cannot be replayed
same-boundary priority remains exclusively inside existing SuBing resolver
5m-at-15m-boundary is deferred using existing session bucket semantics
HTDY cutoff evaluator remains unchanged in meaning
one Rule failure cannot block the other
Event commit precedes one-shot WeCom
sender failure does not retry or delete Event
SuBing seed Scope is empty
canonical explicitly grants only the two named Rule bounded sustained authorization after exact Scope activation
no production migration/release/runtime/scope/real-send was executed during implementation
full backend tests + Ruff + Mypy + secret scan + diff check pass
```

Next implementation dependency: `docs/superpowers/plans/2026-08-14-decision-compression-web-ui.md` must be rebased on the final backend DTOs before Web code begins.
