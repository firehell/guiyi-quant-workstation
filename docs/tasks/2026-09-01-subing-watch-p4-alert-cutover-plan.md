# P4 — Alert Rule 正交化、Watch Event/通知与 Forward Migration 计划

> **Execution:** Lane 3 TDD. All send tests use fakes. Isolated migration tests use only a dedicated disposable PostgreSQL database.

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 3 Alert contract / migration / notification code path。

## Goal

让同一 release 安全支持 pre/post migration 单一 lineage，将 Rule `kind` 与 `scope_authority` 正交化；在 post-migration active 模式下，把 Watch Candidate 以 observation-only `AlertEvent` commit-first 持久化并向 owner 最多发送一次 PushPlus；增加 forward-only `20260901_0043` migration 代码和 isolated tests。

P4 不执行 production migration，不修改生产 Scope，不发送真实 PushPlus，不切 Runtime，不触及 `main`、tag 或 Release。

## Workspace

```text
base: P3 合入后的最新 origin/develop
branch: feature/subing-watch-alert-cutover
worktree: 新 task worktree
integration: develop
PR: Draft PR required
review: independent Sol/high whole-branch exact-head Review
human Gate: 允许集成 develop
```

## File Map

### Backend

```text
services/quant-api/app/alerts/registry.py
services/quant-api/app/alerts/service.py
services/quant-api/app/alerts/notification.py
services/quant-api/app/alerts/runtime.py
services/quant-api/app/alerts/composition.py
services/quant-api/app/schemas/alerts.py
services/quant-api/app/api/alerts.py
services/quant-api/alembic/versions/20260901_0043_subing_watch_alert.py
services/quant-api/tests/test_alert_registry.py
services/quant-api/tests/test_alert_service.py
services/quant-api/tests/test_alert_notification.py
services/quant-api/tests/test_alert_runtime.py
services/quant-api/tests/test_alert_notification_composition.py
services/quant-api/tests/test_alert_api.py
services/quant-api/tests/alembic/test_subing_watch_alert_migration.py
```

### Web ownership/compatibility

```text
apps/quant-web/src/api/alerts.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/alertRules.ts
apps/quant-web/scripts/checkAlertRuleOwnership.mjs
apps/quant-web/tests/alertRuleOwnership.test.ts
apps/quant-web/tests/alerts.test.ts
apps/quant-web/e2e/alert-v1.spec.mjs
```

## Task 1 — Orthogonalize Rule kind and Scope authority

### Contracts

```python
class AlertRuleKind(StrEnum):
    INDICATOR_OBSERVATION = "indicator_observation"
    STRATEGY_ACTION = "strategy_action"

class AlertScopeAuthority(StrEnum):
    PRODUCT = "product"
    PRODUCT_FREQUENCY = "product_frequency"

@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    rule_code: str
    display_name: str
    kind: AlertRuleKind
    scope_authority: AlertScopeAuthority
    input_frequencies: tuple[str, ...]
    series_kind: str
```

Fixed definitions:

```text
HTDY_RULE:
  rule_code=htdy_original_15m
  kind=indicator_observation
  scope_authority=product_frequency

LEGACY_SUBING_RULE:
  rule_code=subing_strategy_v1
  kind=strategy_action
  scope_authority=product

SUBING_WATCH_RULE:
  rule_code=subing_watch_15m_v1
  kind=indicator_observation
  scope_authority=product
```

`kind` decides Event payload validation. `scope_authority` decides Scope read/write. They must never be inferred from each other.

### Valid lineages

```text
PRE_MIGRATION = {htdy_original_15m, subing_strategy_v1}
POST_MIGRATION = {htdy_original_15m, subing_watch_15m_v1}
```

```python
class AlertRuleLineage(StrEnum):
    PRE_MIGRATION = "pre_migration"
    POST_MIGRATION = "post_migration"

def resolve_alert_rule_lineage(rule_codes: tuple[str, ...]) -> AlertRuleLineage: ...
```

Reject with `ALERT_RULE_LINEAGE_INVALID`:

- both SuBing codes;
- missing HTDY;
- missing SuBing lineage;
- duplicate codes;
- third/unknown Rule;
- malformed code order/identity after normalization.

### Scope RED tests

- HTDY product toggle fails;
- HTDY product-frequency toggle works;
- legacy Strategy product toggle works;
- Watch product toggle works even though Watch kind is observation;
- Watch frequency toggle fails;
- malformed Rule with both Scope columns populated fails closed;
- Watch allows only frequency `15m`;
- HTDY existing seven frequencies remain unchanged.

### Service implementation

`AlertService.set_product_enabled`, `set_product_frequency_enabled`, `rule_allows_event` and product-rule projection switch only on `scope_authority`.

Event normalization switches only on `kind`:

```text
indicator_observation:
  result codes buy/sell
  action_id null
  strategy_payload null

strategy_action:
  result codes open/close
  action_id required
  strategy_payload required and validated
```

### Startup compatibility

Runtime loads DB codes before subscription/send:

```text
pre-migration:
  legacy Strategy path remains governed by current Rule/Scope
  Watch forced shadow

post-migration:
  Watch active-capable
  legacy Strategy Alert evaluator excluded from critical path

invalid lineage:
  startup fails before Pub/Sub subscription, Event or send
```

No environment value may force active against pre-migration lineage.

### Web ownership guard

`apps/quant-web/src/utils/alertRules.ts` remains the only Web routing owner. The temporary release seam may define both SuBing codes centrally but must require exactly one server-projected lineage. Update `checkAlertRuleOwnership.mjs` expected literal counts; components cannot contain raw Rule-code routing.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py
pnpm -C apps/quant-web run check:alert-rules
pnpm -C apps/quant-web exec node --test \
  tests/alertRuleOwnership.test.ts \
  tests/alerts.test.ts

git add \
  services/quant-api/app/alerts/registry.py \
  services/quant-api/app/alerts/service.py \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/schemas/alerts.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  apps/quant-web/src/api/alerts.ts \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/utils/alertRules.ts \
  apps/quant-web/scripts/checkAlertRuleOwnership.mjs \
  apps/quant-web/tests/alertRuleOwnership.test.ts \
  apps/quant-web/tests/alerts.test.ts
git commit -m "refactor(alerts): separate Rule kind and scope authority"
```

## Task 2 — Watch Event persistence and exact owner message

### Event contract

For active Watch Candidate:

```text
rule_code=subing_watch_15m_v1
result_codes=("buy",) | ("sell",)
action_id=null
strategy_payload=null
frequency=15m
bar_end=evaluation bar_end
detected_at=Runtime first evaluation time
notification_attempted_at=commit-first attempt time
identity=rule_id × symbol × frequency × bar_end
```

Same immutable Candidate is no-op. Same identity with different direction, contract, trading day or facts raises `ALERT_EVENT_CONSISTENCY_ERROR` and never sends.

Do not add Watch context to `strategy_payload`. Context is an ephemeral typed `SubingWatchNotificationFacts` passed only to the one-shot formatter. The permanent Event remains minimal observation truth.

### Notification routing

```text
HTDY -> htdy_observers Topic
Legacy Strategy pre-migration -> owner, existing copy
Watch post-migration -> owner, no Topic
```

Title:

```text
归一量化 苏冰盯盘
```

Buy example:

```text
【苏冰盯盘】RB 螺纹钢

15m 多头观察
触发：MACD 金叉 + 收盘在 MA21 上方
主力：RBxxxx
观察K线：15m · HH:MM

环境：
- MA21：向上 / 向下 / 走平 / 不可用
- 60m：同向 / 逆向 / 中性 / 不可用
- 箱体：箱体内 / 无活动箱体 / 已向上突破 / 已向下突破 / 不可用
- 零轴距离：N.NN ATR / 不可用
- 距 MA21：+N.NN ATR / 不可用
- 量能：N.NN × 20根均量 / 不可用

研究观察，非交易指令
```

Sell is symmetric. Every unavailable label renders `不可用`; no line is silently omitted.

Forbidden in all Watch messages:

```text
买入
卖出
建仓
清仓
仓位比例
止损价
目标价
胜率
盈利承诺
```

### Event-first order

```text
1. create/commit Event
2. ledger record event_created
3. prepare message
4. ledger record transport_attempt
5. sender called once
6. ledger record provider_accepted or fixed failure
```

Transitions:

```text
existing identical Event -> event_deduplicated, no send
persistence failure -> EVENT_PERSIST_FAILED, no send
format/taxonomy failure -> NOTIFICATION_PREPARATION_FAILED
transport exception -> NOTIFICATION_TRANSPORT_FAILED
invalid ProviderAcceptance -> NOTIFICATION_ACCEPTANCE_INVALID
valid ProviderAcceptance -> provider_accepted only, not delivery
```

A transport failure leaves Event committed and is never retried on duplicate/restart.

### RED tests

- exact buy/sell Event fields;
- duplicate and consistency conflict;
- exact ready-context message fixture;
- unavailable-context message fixture;
- forbidden words;
- owner/no Topic;
- Event commit failure means zero sender calls;
- sender failure means one call and committed Event;
- duplicate/restart means no retry;
- boundary counters match exact transitions;
- HTDY and legacy Strategy copy/routing non-regression;
- post-migration cannot pass legacy strategy payload into Watch formatter.

All sender tests use fakes.

### Verification and commit

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_alert_api.py
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/alert-v1.spec.mjs

git add \
  services/quant-api/app/alerts/service.py \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/app/alerts/composition.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  apps/quant-web/e2e/alert-v1.spec.mjs
git commit -m "feat(alerts): emit SuBing Watch observations"
```

## Task 3 — Forward-only `20260901_0043` migration

### Files

- Create: `services/quant-api/alembic/versions/20260901_0043_subing_watch_alert.py`
- Create: `services/quant-api/tests/alembic/test_subing_watch_alert_migration.py`

### Revision

```python
revision = "20260901_0043"
down_revision = "20260826_0042"
_OLD_SUBING_RULE = "subing_strategy_v1"
_NEW_SUBING_RULE = "subing_watch_15m_v1"
_HTDY_RULE = "htdy_original_15m"
```

No table/column addition. This is an atomic data-lineage replacement.

### Exact valid pre-state

```text
alembic_version=20260826_0042
one HTDY Rule with valid product-frequency Scope
one subing_strategy_v1 Rule with valid product Scope and empty frequency Scope
zero subing_watch_15m_v1 Rule
no unknown third Rule
all existing Events valid under their old Rule semantics
```

Invalid preflight cases:

```text
unexpected Alembic head
missing legacy Rule
Watch already exists
both old and new SuBing Rules
unknown third Rule
malformed product Scope
malformed frequency Scope
invalid legacy Strategy Event
invalid HTDY Event/Scope
```

Every invalid case raises `SUBING_WATCH_ALERT_PREFLIGHT_FAILED` and leaves DB unchanged.

### Atomic upgrade order

```text
1. read and validate Alembic head;
2. SELECT Rule rows FOR UPDATE;
3. validate exact old lineage and all Event facts;
4. delete Events owned by old SuBing Rule;
5. preserve Rule row id/enabled/scope_products;
6. rename rule_code to subing_watch_15m_v1;
7. normalize scope_product_frequencies to {};
8. read back exact two-Rule post-state;
9. commit transaction.
```

Post assertions:

```text
Alembic head=20260901_0043
Rule codes exactly HTDY + Watch
Watch row id/enabled/scope_products preserved
Watch frequency Scope empty
old Strategy Event count for replaced row=0
HTDY Rule and Events unchanged
```

`downgrade()` always raises `SUBING_WATCH_ALERT_DOWNGRADE_UNSUPPORTED`. No archive/legacy copy/third Rule/compatibility table.

### Atomic rollback test

Inject failure after Event delete and before Rule rename; transaction must restore both Events and Rule unchanged.

### Isolated PostgreSQL verification

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_watch_alert_migration.py
```

Never run this against production during implementation.

Commit:

```bash
git add \
  services/quant-api/alembic/versions/20260901_0043_subing_watch_alert.py \
  services/quant-api/tests/alembic/test_subing_watch_alert_migration.py
git commit -m "feat(db): replace Strategy Alert with Watch"
```

## Packet Verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_composition.py \
  services/quant-api/tests/test_alert_api.py

GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_watch_alert_migration.py

pnpm -C apps/quant-web run check:alert-rules
pnpm -C apps/quant-web exec node --test \
  tests/alertRuleOwnership.test.ts \
  tests/alerts.test.ts
pnpm -C apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/alert-v1.spec.mjs
```

## Independent Exact-Head Review

Pin final branch SHA and inspect the whole Packet:

- kind/scope authority orthogonality;
- exact accepted pre/post lineages;
- no dual/third Rule steady state;
- Shadow forced before migration;
- active only after migration;
- Watch Event observation-only fields;
- consistency conflict and dedupe;
- Event-first/one-shot ordering;
- exact owner copy and forbidden words;
- provider acceptance not delivery;
- HTDY non-regression;
- legacy Strategy research preserved but Alert path removed post-migration;
- migration preflight, row preservation, Event deletion, HTDY preservation, atomicity and no downgrade;
- no real send/Scope/DB/Runtime/main/tag operation occurred.

Required Review result:

```text
Critical=0
Important=0
Minor=0 or explicitly accepted with no correctness impact
```

PR stops at `允许集成 develop`. Integration does not authorize production migration or real notification.
