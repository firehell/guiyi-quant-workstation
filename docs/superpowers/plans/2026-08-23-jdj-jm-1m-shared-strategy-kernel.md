# 日进斗金 JM 1m 轻量策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不迁移现有 N/JDJ Research 公式、不预建通用策略平台，用最小新增代码完成 `jdj_jm_1m_v1` 的完整交易生命周期、JM actual_dominant Historical Reference Replay 和 Market 主图展示。

**Architecture:** 现有 `app.research.jdj` / `app.research.n_structure` 继续作为 Entry 公式唯一来源；新增窄模块 `app.research.jdj_strategy` 消费已有 Candidate event/context，负责交易管理和 reference replay。当前 Plan 不实现 RQAlpha adapter 或 streaming framework。

**Tech Stack:** Python 3.13、FastAPI/Pydantic、`Decimal`、现有 `MarketDataService` / `ActualDominantResearchSegmentLoader` / TradingSession resolver、Vue 3/TypeScript/Lightweight Charts。

**Spec:** `docs/superpowers/specs/2026-08-23-jdj-jm-1m-shared-strategy-kernel-design.md`

## Global Constraints

> **先写业务逻辑，重复真实出现后再抽象；先满足个人研究闭环，不为未来多人、分布式、通用策略平台预建设。**

- 本任务为 Lane 3：交易公式、风险、成交时序、主力 identity 均按可信口径处理。
- V1 只支持 `jm / actual_dominant / 1m / 5m context`。
- 现有 N/JDJ reducer、policy、event identity 不迁移、不复制、不修改公式。
- 所有价格、资金、风险、PnL 使用 `Decimal`；手数使用 `int`。
- 不创建 `app.strategy_kernel`、StrategyBase、plugin、optimizer、Portfolio、queue、scheduler。
- 不预建 streaming evaluator，不实现 RQAlpha adapter。
- 不创建数据库表/migration，不写 Canonical/Redis，不接 Alert/PushPlus/Execution Review/Runtime。
- 不执行真实 RQAlpha Bundle，不发布 main/tag，不做 Runtime promotion。

---

## File Structure

### Create

```text
data/strategy_profiles/jdj_v1.json

services/quant-api/app/research/jdj_strategy/__init__.py
services/quant-api/app/research/jdj_strategy/contract.py
services/quant-api/app/research/jdj_strategy/engine.py
services/quant-api/app/research/jdj_strategy/replay.py
services/quant-api/app/research/jdj_strategy/service.py

services/quant-api/tests/research/test_jdj_strategy_contract.py
services/quant-api/tests/research/test_jdj_strategy_engine.py
services/quant-api/tests/research/test_jdj_strategy_replay_service.py
```

### Modify backend

```text
services/quant-api/app/research/composition.py
services/quant-api/app/research/historical_overlay_api.py
services/quant-api/app/schemas/research_overlays.py
services/quant-api/tests/test_market_research_overlays_api.py
```

### Modify Web only; do not create a second marker pipeline

```text
apps/quant-web/src/api/market.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/mainIndicators.ts
apps/quant-web/src/utils/historicalResearchMarkers.ts
apps/quant-web/src/composables/useHistoricalResearchMarkers.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/tests/historicalResearchMarkers.test.ts
apps/quant-web/e2e/market-research.spec.mjs
```

### Explicitly do not create in this Plan

```text
services/quant-api/app/strategy_kernel/**
services/quant-api/app/backtest/** JDJ adapter
profile discovery API
new strategy DB tables
new Web strategy management pages
```

---

## Task 1: Freeze One JDJ V1 Contract Without Moving Existing Formulas

**Files:**
- Create: `data/strategy_profiles/jdj_v1.json`
- Create: `services/quant-api/app/research/jdj_strategy/__init__.py`
- Create: `services/quant-api/app/research/jdj_strategy/contract.py`
- Create: `services/quant-api/tests/research/test_jdj_strategy_contract.py`
- Read-only regression targets: current JDJ/N policy/reducer tests

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class JdjCoreRules:
    minimum_reward_risk: Decimal
    max_planned_trade_risk_fraction: Decimal
    require_profit_before_add: bool
    require_partial_profit_before_add: bool
    add_fraction_of_current_qty: Decimal
    max_add_count: int
    losing_position_add_forbidden: bool
    daily_pause_drawdown_fraction: Decimal
    daily_pause_bars: int
    daily_stop_drawdown_fraction: Decimal

@dataclass(frozen=True, slots=True)
class JdjStrategyProfile:
    profile_id: str
    symbol: str
    series_kind: str
    execution_frequency: BarFrequency
    trend_context_frequency: BarFrequency
    base_risk_fraction: Decimal
    first_profit_take_fraction: Decimal
    historical_reference_start_equity: Decimal
    entry_limit_valid_bars: int
    terminal_flatten_lead_bars: int

@dataclass(frozen=True, slots=True)
class JdjV1Config:
    strategy_id: str
    core: JdjCoreRules
    profile: JdjStrategyProfile


def load_jdj_v1_config(profile_id: str = "jdj_jm_1m_v1") -> JdjV1Config: ...
```

- [ ] **Step 1: Write the exact JSON fixture** with the Spec values and no additional knobs.

```json
{
  "schema_version": 1,
  "strategy_id": "jdj_intraday_futures_v1",
  "core_rules": {
    "minimum_reward_risk": "2.0",
    "max_planned_trade_risk_fraction": "0.01",
    "require_profit_before_add": true,
    "require_partial_profit_before_add": true,
    "add_fraction_of_current_qty": "0.25",
    "max_add_count": 2,
    "losing_position_add_forbidden": true,
    "daily_pause_drawdown_fraction": "0.005",
    "daily_pause_bars": 15,
    "daily_stop_drawdown_fraction": "0.01"
  },
  "profiles": {
    "jdj_jm_1m_v1": {
      "symbol": "jm",
      "series_kind": "actual_dominant",
      "execution_frequency": "1m",
      "trend_context_frequency": "5m",
      "base_risk_fraction": "0.005",
      "first_profit_take_fraction": "0.40",
      "historical_reference_start_equity": "1000000",
      "entry_limit_valid_bars": 1,
      "terminal_flatten_lead_bars": 1
    }
  }
}
```

- [ ] **Step 2: Write RED exact-contract tests**: accepted profile loads exact Decimals; unknown profile、missing/extra/drifted field fail closed.

- [ ] **Step 3: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_jdj_strategy_contract.py
```

- [ ] **Step 4: Implement `contract.py` using `app.core.exact_json_contract`**. Do not create separate policy/profile loaders.

- [ ] **Step 5: Run contract + existing Candidate regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_research_service.py
```

Expected: all existing JDJ Candidate tests stay green; no production JDJ/N file moved.

- [ ] **Step 6: Commit**

```bash
git add data/strategy_profiles/jdj_v1.json services/quant-api/app/research/jdj_strategy services/quant-api/tests/research/test_jdj_strategy_contract.py
git commit -m "feat(strategy): define lean JDJ JM 1m contract"
```

---

## Task 2: Implement the Complete JDJ JM 1m Trade Engine and Reference Fill Model

**Files:**
- Create: `services/quant-api/app/research/jdj_strategy/engine.py`
- Create: `services/quant-api/app/research/jdj_strategy/replay.py`
- Create: `services/quant-api/tests/research/test_jdj_strategy_engine.py`

**Consumes existing types:**

```text
app.research.jdj.jdj_context.JdjBarContext
app.research.jdj.jdj_events.JdjTriggerEvent / JdjDirection / JdjSetupKind
CanonicalBar
```

Do not copy their formulas.

**Public result contracts in `engine.py`:**

```python
class JdjActionKind(StrEnum):
    ENTRY = "entry"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    DAILY_PAUSE = "daily_pause"
    DAILY_STOP = "daily_stop"
    REJECTED = "rejected"

@dataclass(frozen=True, slots=True)
class JdjAction:
    event_id: str
    episode_id: str | None
    kind: JdjActionKind
    source_event_ids: tuple[str, ...]
    primary_setup: str | None
    supporting_setups: tuple[str, ...]
    direction: JdjDirection | None
    contract: str
    trading_day: date
    segment_start_trading_day: date
    decision_at: datetime
    effective_bar_end: datetime | None
    reference_price: Decimal | None
    quantity: int
    position_quantity_after: int
    stop_price: Decimal | None
    target_price: Decimal | None
    reward_risk: Decimal | None
    reason: str
    fill_basis: str | None

@dataclass(frozen=True, slots=True)
class JdjReferenceReplay:
    actions: tuple[JdjAction, ...]
```

**Main function in `replay.py`:**

```python
def run_jdj_reference_segment(
    *,
    bars_1m: Sequence[CanonicalBar],
    contexts: Sequence[JdjBarContext],
    candidate_events: Sequence[JdjTriggerEvent],
    contract_multiplier: Decimal,
    terminal_bar_end_by_day: Mapping[date, datetime],
    config: JdjV1Config,
) -> JdjReferenceReplay: ...
```

- [ ] **Step 1: Write RED conflict/stop/target/R:R tests**

Require:

```text
same direction multiple setups → one entry; primary key-level > reentry > trend-follow
LONG + SHORT same decision bar → AMBIGUOUS_DIRECTION
no known favorable target → rejected
R:R < 2 → rejected
Trend Follow stop resolves reaction-bar adverse extreme
Reentry stop uses excursion_extreme
Key Level stop uses key_level_price
```

Known target uses only already-confirmed favorable N pivot or current-day known session high/low.

- [ ] **Step 2: Write RED one-Bar Entry limit tests**

For LONG limit 100:

```text
next open 99 → fill 99 / better_open
next open 101, next low 99.5 → fill 100 / limit_touch
next low 100.5 → no fill, intent expires
```

SHORT symmetric. No fill may be deferred to a second Bar.

- [ ] **Step 3: Write RED reference sizing/Episode tests**

Use trusted multiplier fixture, reference start equity 1,000,000 and base risk 0.5%. Quantity is calculated from the admissible worst price; planned episode risk >1% rejects. Actual Entry creates deterministic `episode_id`; unfilled intent creates none; consumed source id cannot be reused.

- [ ] **Step 4: Write RED partial-profit/add tests**

```text
completed close reaches target_1 → reduce decision → next legal open fill
10 lots × 40% → reduce 4
floor result 0 → no fake reduce
no actual profitable partial exit → no add
new full Trend Follow event + profitable episode → add 25%
first/second add allowed subject to risk
third / losing / repeated-source add rejected
successful reduce/add → protective stop moves to weighted average cost
```

- [ ] **Step 5: Write RED exit/daily/session tests**

```text
close crosses protective stop / EMA or 5m trend lost → next-Bar EXIT
no intrabar hard-stop fill
>0.5% drawdown → 15 subsequent in-session bars pause
>=1% → DAILY_STOP + JM V1 conservative exit
terminal lead=1 → no new entry/add; existing position flattens at final legal Bar open
intermediate session break != terminal
```

- [ ] **Step 6: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_jdj_strategy_engine.py
```

- [ ] **Step 7: Implement the minimal engine/replay** in these two files. Keep helper functions private unless another real consumer needs them.

- [ ] **Step 8: Run engine + existing Candidate regressions**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py
```

- [ ] **Step 9: Commit**

```bash
git add services/quant-api/app/research/jdj_strategy services/quant-api/tests/research/test_jdj_strategy_engine.py
git commit -m "feat(strategy): implement JDJ JM reference lifecycle"
```

---

## Task 3: Add JM actual_dominant Historical Replay Service and One Read-Only API

**Files:**
- Create: `services/quant-api/app/research/jdj_strategy/service.py`
- Create: `services/quant-api/tests/research/test_jdj_strategy_replay_service.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`

**Endpoint:**

```text
GET /api/v1/market/research/jdj-strategy/history
    ?series_kind=actual_dominant
    &symbol=jm
    &frequency=1m
    &since=YYYY-MM-DD
    &through=YYYY-MM-DD
```

No profile discovery endpoint.

- [ ] **Step 1: Write RED service tests** using `ActualDominantResearchSegmentLoader` fixtures with at least two physical JM segments.

Require:

```text
only actual_dominant accepted
no state crosses contract segment
API since mid-segment still warms from true segment start
same prefix inside longer through stays identical
contract/segment identity on every action
reference_execution=true
```

- [ ] **Step 2: Write RED session/multiplier failure tests**

Use existing TradingSession resolver for terminal identity; never hardcode 15:00. Missing session or trusted multiplier fails closed. Do not simulate historical margin or commission.

- [ ] **Step 3: Write RED API validation tests**

```text
jm + actual_dominant + 1m → 200
jm + 5m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
rb + 1m → 422 JDJ_STRATEGY_PROFILE_UNAVAILABLE
continuous → 422
segment/session/source failure → typed 409
```

- [ ] **Step 4: Implement `JdjStrategyReplayService`**

For each validated physical segment:

1. load 1m + 5m through existing loader;
2. call existing `build_jdj_context_series`;
3. call the existing three reducers;
4. combine Candidate events without changing their identity;
5. call `run_jdj_reference_segment`;
6. suppress actions before requested `since` only at output projection.

Do not query raw `MainContractMap` directly.

- [ ] **Step 5: Add only the required Pydantic DTOs and route**. Existing `/jdj/history` Candidate API stays separate.

- [ ] **Step 6: Run service/API tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/research/test_jdj_research_service.py
```

- [ ] **Step 7: Commit**

```bash
git add services/quant-api/app/research/jdj_strategy services/quant-api/app/research/composition.py services/quant-api/app/research/historical_overlay_api.py services/quant-api/app/schemas/research_overlays.py services/quant-api/tests
git commit -m "feat(research): expose JDJ JM reference replay"
```

---

## Task 4: Extend the Existing Market Marker Pipeline and Close the Documentation

**Files Web:**
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Files docs after behavior is verified:**
- Modify: `AGENTS.md` only to replace factual statements that become false; preserve the personal-quant architecture principle.
- Modify: `PROJECT_SOURCE.md` only where the new research-only strategy replay changes current capability facts.
- Modify: `TESTING.md` with the exact new test commands.
- Do not update `STATUS.md` unless a separate status task records an explicit develop RC.
- Do not touch `docs/RQALPHA_RESEARCH_BACKTEST.md`; RQAlpha adapter is not implemented in this Plan.

- [ ] **Step 1: Extend existing marker unit tests**

Add `jdj_strategy` mapping to the current marker utility:

```text
LONG ENTRY  → ▲
SHORT ENTRY → ▼
ADD         → ＋
REDUCE      → －
EXIT        → ×
```

Hover includes setup/supporting setup/contract/decision/effective time/qty/stop/target/R:R/reason and “参考回放”. Unfilled intents are not rendered as fills.

- [ ] **Step 2: Extend existing composable tests**

Reuse `useHistoricalResearchMarkers`; do not create `useHistoricalStrategyMarkers`.

Require:

```text
jm / actual_dominant / 1m → loads strategy history
switch to unsupported 5m → immediately clears strategy markers and shows unavailable
switch back 1m → reload without duplicates
prepend older data → dedupe by event id
stale response after identity change → ignored
```

- [ ] **Step 3: Implement Web projection minimally**

Add `日进斗金策略` as a distinct overlay from existing JDJ Candidate. No EMA/N/R:R/position/PnL calculation in TypeScript.

- [ ] **Step 4: Extend Playwright coverage** for Candidate/Strategy separation and `1m → 5m → 1m` stale-marker safety.

- [ ] **Step 5: Run Web checks**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs apps/quant-web/e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 6: Run targeted backend regression**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_jdj_strategy_contract.py \
  services/quant-api/tests/research/test_jdj_strategy_engine.py \
  services/quant-api/tests/research/test_jdj_strategy_replay_service.py \
  services/quant-api/tests/test_jdj_context.py \
  services/quant-api/tests/test_jdj_trend_follow.py \
  services/quant-api/tests/test_jdj_trend_reentry.py \
  services/quant-api/tests/test_jdj_key_level_breakout.py \
  services/quant-api/tests/research/test_jdj_research_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

- [ ] **Step 7: Run Ruff/Mypy and engineering checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/research/jdj_strategy services/quant-api/tests/research/test_jdj_strategy_*.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/research/jdj_strategy
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 8: Update only the canonical statements made false by the implementation**, add testing commands, then run `git diff --check` again.

- [ ] **Step 9: Independent Lane 3 Review before integration**

Reviewer checks only high-value correctness risks:

```text
future/same-boundary leakage
Candidate formula duplication or drift
cross-contract Episode leakage
non-Decimal financial calculations
R:R / one-Bar limit violation
favorable intrabar stop/target assumptions
session-terminal leakage
raw MainContractMap self-selection
unsupported-period silent fallback
scope creep into RQAlpha/streaming/optimization/Runtime
```

- [ ] **Step 10: Commit final Web/docs closeout**

```bash
git add apps/quant-web AGENTS.md PROJECT_SOURCE.md TESTING.md
git commit -m "feat(web): show JDJ JM reference strategy"
```

---

## Follow-up Explicitly Deferred

This Plan stops after Historical Replay + Market Web.

Only after the separately approved RQAlpha Workbench is actually implemented should a new Lane 3 task be opened for:

```text
existing JDJ/N Entry semantics
+ app.research.jdj_strategy trade management
→ thin RQAlpha adapter
```

At that time first test whether the existing logic can be reused directly. Only if a real batch/streaming duplication appears, extract the smallest shared state transition and add parity tests. Do not prebuild a general streaming or strategy framework.

## Integration and Gates

```text
fresh develop
→ Lane 3 task branch/worktree
→ Task 1
→ Task 2
→ Task 3
→ Task 4
→ independent Review
→ user reviews exact diff/test results
→ user decides whether to integrate develop
```

Allowed by this Plan: repository code/tests/docs and deterministic read-only Historical replay.

Not authorized:

```text
real RQAlpha Bundle run
RQAlpha adapter / streaming framework
parameter sweep / optimizer
other products / periods
prospective OOS consumption
main/tag/release
Runtime promotion/switch
Alert/PushPlus
Canonical/DB/Redis writes
real orders
```
