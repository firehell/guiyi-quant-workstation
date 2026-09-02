# 苏冰同花顺 15m 预警 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不恢复任何旧苏冰策略域的前提下，实现 `subing_ths_alert_15m_v1`：对 operational universe 的 completed `actual_dominant + 15m` 按同花顺 MACD CROSS + SMA21 公式产生不可变 AlertEvent、one-shot PushPlus，并在 Market Web 显示最近预警和 `S↑/S↓` marker。

**Architecture:** 公式 authority 放在纯 Quant Core `SubingThs15mKernel`；Alert Runtime 仍为单进程，但从单 HTDY evaluator 改为精确 `rule_code → evaluator → event mode → notification policy`。SuBing evaluator 只维护最小的每品种 MACD/SMA 递归 cursor，并通过 `MarketReadService` 的 typed physical-contract replay seam 在首次触发、重启、漏中间 Bar 或主力换月时因果重建；API/Web 只读取 AlertEvent，不复制公式。

**Tech Stack:** Python 3.12、SQLAlchemy/Alembic、PostgreSQL、Redis、FastAPI/Pydantic、Quant Core dataclass kernels、Vue 3 + TypeScript + Naive UI + Lightweight Charts、Node test runner/Playwright。

**Spec:** `docs/tasks/2026-09-02-subing-ths-alert-15m-v1-spec.md`

**Issue:** #307

**Planning baseline:** `develop@ec63d2fa5ace6dc87fae6d01bc50ce9eb83769d0`（PR #308 已合入）

**Plan status:** `PLAN_READY_FOR_USER_REVIEW`

## Global Constraints

- 正式身份固定：`rule_code=subing_ths_alert_15m_v1`、`formula_version=subing_ths_15m_v1`、`kind=indicator_observation`、`series_kind=actual_dominant`、`frequency=15m`、`completed_only=true`、`auto_order=false`。
- 唯一 Candidate 公式固定：`BUY=CROSS(DIFF,DEA) AND close>SMA21`；`SELL=CROSS(DEA,DIFF) AND close<SMA21`；`DIFF=EMA12-EMA26`；`DEA=EMA9(DIFF)`；`MACD=2*(DIFF-DEA)`；`MA21=SMA(close,21)`。
- `CROSS` 固定：golden 为 `prev_dif <= prev_dea && dif > dea`；dead 为 `prev_dif >= prev_dea && dif < dea`。
- 工程参数固定：`ema_seed_policy=sma_window`、`histogram_scale=2`、`round_digits=6`。递归状态使用 Quant Core 内部精度；正式 Candidate 比较使用每 Bar 六位确定性 projection，避免不同消费者读取隐藏浮点状态。
- V1 不允许零轴、Range、量能/OI、ATR、斜率、5m/30m/60m/D1、Daily Watch、评分、胜率或其它隐藏过滤。
- 不恢复 `subing_strategy_v1`、旧 Watch、Strategy Runtime、Action/Episode/Position、`scope_products`、`action_id`、`strategy_payload` 或任何旧 cache/API/CLI/Web。
- 不新增第二 Alert 进程、scheduler、queue、outbox、retry、replay、backfill、fallback 或订单路径。
- 数据必须走 `MarketDataService` / `MarketReadService` / `MainContractMap rank1`；不得 glob、自判主力、跨频 fallback 或跨物理合约继承递归状态。
- Event 必须先 commit，随后 transport 最多尝试一次；provider accepted 不等于微信实际送达。
- 0044 只插入 disabled + empty-scope Rule；首次全量 Scope activation 是后续独立 production Gate，不硬编码“当前 60 个品种”。
- 当前 production 事实仍是 Alembic `20260826_0042`、Rule `htdy_original_15m + subing_strategy_v1`；当前最新 Release 是 v1.9.12，五项服务仍由 v1.9.11 承载。Implementation 不得把这些事实提前改写成已迁移/已 Runtime-ready。
- 每个 Packet = 一个新 Codex 会话 = 一个从执行时最新 `origin/develop` 创建的 task branch/worktree = 一个 Draft PR = 一个 exact-head independent Review = 一个 owner `允许集成 develop` Gate。
- Packet 顺序固定 `S1 → S2 → S3 → S4 → S5`。前一个 Packet 未合入 `develop`，不得开始后一个。
- 普通实现阶段不得触碰 `main`、tag、GitHub Release、production PostgreSQL/Redis/Scope、Git-external notification config、真实 PushPlus 或 Runtime promotion。

---

## Current Repository Facts That Drive The Plan

当前代码事实必须由实现者先重新读回，以下仅是本 Plan 的规划基线：

1. `services/quant-api/app/alerts/runtime.py` 构造参数仍是单个 `htdy_evaluator`，DB Rule 循环会复用同一个 evaluator；第二 Rule 上线前必须消除此耦合。
2. `services/quant-api/app/alerts/notification.py` 的 dispatcher 标题、formatter 和 audience 仍写死 HTDY；第二 Rule 上线前必须改成 rule policy。
3. `services/quant-api/app/schemas/alerts.py` / `app/api/alerts.py` 的 wire DTO/serializer 仍是 HTDY-only，尤其 `Literal["htdy_original_15m"]` 和 hard-coded serializer。
4. `apps/quant-web/src/utils/alertRules.ts`、`alertMarkers.ts`、`types/market.ts` 仍把持久 AlertEvent 定义成 HTDY-only；`alertMarkersForOverlay()` 当前在 `overlay=none` 时会隐藏全部 persistent marker。
5. `services/quant-api/alembic/versions/20260902_0043_retire_subing.py` 已存在并 forward-only 删除旧策略 Rule/Event 和专用列；production 尚未执行。
6. `alert:runtime-status` 当前 schema v5 只有全局处理/通知字段；本 Plan 只升级到 schema v6 的 bounded per-rule projection，不恢复 Boundary Ledger。
7. `KlineChart.vue` 已提供 `revealTime(iso)`，S3 deep link 应复用它，不另写图表定位系统。

若执行时 active canonical、Spec、实际代码与以上基线发生实质冲突，必须 fail-closed，先报告，不得按旧行号机械修改。

---

## File / Responsibility Map

### S1 — Formula Kernel + typed physical-contract replay

- Modify `packages/quant-core/guiyi_quant/indicators/models.py`：增加通用 `SmaState`。
- Create `packages/quant-core/guiyi_quant/indicators/sma.py`：最小 incremental SMA primitive。
- Create `packages/quant-core/guiyi_quant/indicators/subing_ths.py`：`SubingThs15mKernel`、state/result、公式常量。
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py`：只导出新的通用/产品 kernel API。
- Modify `services/quant-api/app/market_data/market_read_service.py`：增加当前 rank1 物理合约 replay window，不引入策略语义到 MarketDataService。
- Create `services/quant-api/tests/test_subing_ths_kernel.py`：公式、边界、parity、future-tail/golden。
- Modify `services/quant-api/tests/test_market_read_service.py`：same-contract replay、分页、Live merge、rollover fail-closed。
- Create `tests/fixtures/subing_ths_15m_v1_golden.json`：冻结合成 close 序列与关键逐 Bar 期望。

### S2 — Alert Runtime dispatch + notification + per-rule health

- Modify `services/quant-api/app/alerts/registry.py`：第二 Rule、event mode。
- Modify `services/quant-api/app/alerts/evaluators.py`：generic candidate/evaluator protocol + `SubingThs15mEvaluator`。
- Modify `services/quant-api/app/alerts/service.py`：沿现有 exact Event 创建路径复用，不复制数据库写逻辑；必要时只增加窄 helper。
- Modify `services/quant-api/app/alerts/notification.py`：rule notification policy、SuBing formatter、shared observers audience。
- Modify `services/quant-api/app/alerts/notification_composition.py`：构造支持两条 Rule 的 dispatcher，不改变私有配置 schema。
- Modify `services/quant-api/app/alerts/runtime.py`：evaluator map、event mode、rule status v6、SuBing 15m only。
- Modify `services/quant-api/app/alerts/composition.py`：构造两 evaluator + 两 notification policy。
- Modify `services/quant-api/app/services/runtime_health.py`：只读暴露 v6 `rule_status`。
- Modify focused Alert tests：`test_alert_registry.py`、`test_alert_evaluator.py`、`test_alert_service.py`、`test_alert_notification.py`、`test_alert_runtime.py`、`test_runtime_health.py`、`test_alert_pushplus.py`。

### S3 — Generic Alert API + Market Web

- Modify `services/quant-api/app/schemas/alerts.py`：两条 Rule 的 exact union DTO。
- Modify `services/quant-api/app/api/alerts.py`：真实 rule_code serializer、mixed current-events。
- Modify backend API tests：`services/quant-api/tests/test_alert_api.py`。
- Modify `apps/quant-web/src/types/market.ts`：generic AlertEvent union。
- Modify `apps/quant-web/src/api/alerts.ts`：增加全局 `getCurrentAlertEvents()`。
- Modify `apps/quant-web/src/utils/alertRules.ts`：SuBing presentation。
- Modify `apps/quant-web/src/utils/alertMarkers.ts`：`S↑/S↓`、HTDY/SuBing 可见性分离。
- Modify `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`：复用两 Rule 并保持单次按 Rule 请求，不产生 per-product O(N)。
- Create `apps/quant-web/src/components/market/MarketRecentSubingAlerts.vue`：最近苏冰预警小组件。
- Modify `apps/quant-web/src/pages/market/index.vue`：一次全局 current-events 读取并注入组件。
- Modify `apps/quant-web/src/pages/market/chart.vue`：`focus_bar_end` deep link + 现有 `revealTime()`。
- Modify `apps/quant-web/scripts/checkAlertRuleOwnership.mjs` 与 Web unit/E2E tests，保证两 Rule ownership 与“Web 不算正式公式”。

### S4 — Migration 0044 + atomic Scope activation seam

- Create `services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py`：0043 后 data-only Rule insertion。
- Create `services/quant-api/tests/alembic/test_subing_ths_alert_migration.py`：0042→0043→0044、forward-only failure contract。
- Create `services/quant-api/app/alerts/subing_scope_activation.py`：dry-run + one-transaction first activation。
- Modify `services/quant-api/app/guiyi_cli/main.py`：`guiyi runtime subing-ths-scope [--apply]`。
- Modify `services/quant-api/tests/test_alert_cli.py`：只读 plan / apply fake DB seam / redaction。
- Modify `services/quant-api/tests/test_alert_service.py` only if activation helper reuses service-level validation；不要把 admin-only mutation 塞进 HTTP handler。

### S5 — Canonical / OpenSpec / full verification / RC handoff

- Modify `AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`、`TESTING.md`。
- Create `openspec/specs/subing-ths-alert/spec.md`。
- Modify `tests/engineering/test_canonical_consistency.py`。
- Run full backend/Web/isolated migration/static/OpenSpec/security verification and exact-head independent Review。
- Do **not** bump release version, merge main, create tag/Release, migrate production, activate Scope, send PushPlus or promote Runtime in S5。

---

# Task 1 / Packet S1: Formula Kernel + Same-Contract Replay

**Branch/worktree:** `feature/subing-ths-s1-kernel` from execution-time latest `origin/develop`.

**Deliverable:** 一个无 I/O 的精确 `SubingThs15mKernel`，以及一个只读 typed physical-contract replay seam。S1 不注册 Alert Rule、不写 DB、不接 Runtime/Push/Web。

**Interfaces:**

- Produces `SmaState`, `initial_sma_state()`, `step_sma()`。
- Produces `SubingThs15mState`, `SubingThs15mResult`, `SubingThs15mKernel.initial_state()`, `SubingThs15mKernel.step()`。
- Produces `CurrentContractReplayWindow` 与 `MarketReadService.current_contract_replay_window(decision_window, after=...)`。
- Later S2 consumes these exact interfaces；S1 不创建 evaluator。

## S1.1 Add a generic incremental SMA primitive

**Files:**
- Modify `packages/quant-core/guiyi_quant/indicators/models.py`
- Create `packages/quant-core/guiyi_quant/indicators/sma.py`
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test `services/quant-api/tests/test_subing_ths_kernel.py`

- [ ] **Step 1: Write the failing SMA tests**

Add tests that freeze warm-up, exact arithmetic mean, rolling eviction, invalid reset and six-decimal projection:

```python
from guiyi_quant.indicators import initial_sma_state, step_sma


def test_sma21_warms_then_rolls_exactly() -> None:
    state = initial_sma_state(3, round_digits=6)
    for value in (1.0, 2.0):
        state, point = step_sma(state, value, bar_end=None)
        assert point.ready is False
        assert point.value is None
    state, point = step_sma(state, 3.0, bar_end=None)
    assert point.ready is True
    assert point.valid is True
    assert point.value == 2.0
    state, point = step_sma(state, 6.0, bar_end=None)
    assert point.value == 11 / 3 if False else 3.666667


def test_sma_invalid_input_breaks_continuity() -> None:
    state = initial_sma_state(3)
    for value in (1.0, 2.0, 3.0):
        state, _ = step_sma(state, value, bar_end=None)
    state, invalid = step_sma(state, None, bar_end=None)
    assert invalid.valid is False
    assert invalid.reason == "input_invalid"
    state, next_point = step_sma(state, 4.0, bar_end=None)
    assert next_point.ready is False
```

The odd-looking first assertion must be written in final test as `assert point.value == 3.666667`; do not retain the dead conditional shown above when committing.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k sma
```

Expected: import/definition failure for `initial_sma_state` / `step_sma`.

- [ ] **Step 3: Implement the minimal state and step**

Add to `models.py`:

```python
@dataclass(frozen=True, slots=True)
class SmaState:
    period: int
    values: tuple[float, ...]
    round_digits: int = 6
```

Create `sma.py` with the exact public shape:

```python
def initial_sma_state(period: int, *, round_digits: int = 6) -> SmaState: ...

def step_sma(
    state: SmaState,
    value: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[SmaState, IndicatorPoint]: ...
```

Behavior:

```text
finite input → append, keep last period values
len < period → ready=false, valid=true, reason=warming_up
len == period → ready=true, valid=true, value=round(mean, round_digits)
invalid input → reset values=(), ready=false, valid=false, reason=input_invalid
```

Do not add pandas/numpy or an unbounded history.

- [ ] **Step 4: Export the primitive and make focused tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k sma
```

Expected: PASS.

- [ ] **Step 5: Commit the primitive**

```bash
git add packages/quant-core/guiyi_quant/indicators/models.py \
        packages/quant-core/guiyi_quant/indicators/sma.py \
        packages/quant-core/guiyi_quant/indicators/__init__.py \
        services/quant-api/tests/test_subing_ths_kernel.py
git commit -m "feat(indicators): add incremental SMA primitive"
```

## S1.2 Implement the product kernel as the only Candidate authority

**Files:**
- Create `packages/quant-core/guiyi_quant/indicators/subing_ths.py`
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Test `services/quant-api/tests/test_subing_ths_kernel.py`
- Create `tests/fixtures/subing_ths_15m_v1_golden.json`

- [ ] **Step 1: Write RED tests for identity, CROSS and equality edges**

Freeze the exact result API:

```python
from guiyi_quant.indicators import SubingThs15mKernel


def test_subing_ths_formula_identity_is_frozen() -> None:
    kernel = SubingThs15mKernel()
    assert kernel.formula_version == "subing_ths_15m_v1"
    assert kernel.ema_seed_policy == "sma_window"
    assert kernel.histogram_scale == 2
    assert kernel.round_digits == 6


def test_subing_ths_never_triggers_when_close_equals_sma21(frozen_ready_state) -> None:
    result = SubingThs15mKernel().step_from_state_for_test(
        frozen_ready_state,
        close=frozen_ready_state.ma21,
        bar_end="2026-09-02T02:45:00+00:00",
    )
    assert result.result_codes == ()
```

Do not keep a test-only production method if normal public `step()` can express the fixture; the committed tests should construct state through ordinary prior bars. The intended committed public API is only `initial_state()` + `step()`.

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k "formula or cross or equality"
```

Expected: `SubingThs15mKernel` missing.

- [ ] **Step 3: Implement frozen state/result contracts**

`subing_ths.py` must define:

```python
SUBING_THS_FORMULA_VERSION = "subing_ths_15m_v1"

@dataclass(frozen=True, slots=True)
class SubingThs15mState:
    macd: MacdState
    ma21: SmaState
    previous_dif: float | None
    previous_dea: float | None

@dataclass(frozen=True, slots=True)
class SubingThs15mResult:
    formula_version: str
    bar_end: str | None
    ready: bool
    valid: bool
    reason: str | None
    dif: float | None
    dea: float | None
    macd: float | None
    ma21: float | None
    result_codes: tuple[Literal["buy", "sell"], ...]
```

`SubingThs15mKernel` constants:

```python
formula_version = "subing_ths_15m_v1"
fast = 12
slow = 26
signal = 9
sma_period = 21
ema_seed_policy = "sma_window"
histogram_scale = 2
round_digits = 6
```

`initial_state()` must create MACD/SMA state only；no symbol/contract/time belongs in Quant Core state.

- [ ] **Step 4: Implement the exact step semantics**

The kernel must:

```text
1. step MACD and SMA with current close
2. if any required current point invalid → result valid=false, no Candidate, clear previous DIF/DEA continuity
3. if MACD/SMA not ready → ready=false, no Candidate
4. use six-decimal point.value for Candidate comparisons
5. golden = prev_dif <= prev_dea and dif > dea and close > ma21
6. dead   = prev_dif >= prev_dea and dif < dea and close < ma21
7. emit exactly () / ("buy",) / ("sell",)
8. update previous DIF/DEA only from a ready+valid current MACD pair
```

Do not use MACD histogram, zero axis, volume, Range or any other fact in Candidate logic.

- [ ] **Step 5: Add a frozen golden fixture and parity tests**

Fixture schema:

```json
{
  "formula_version": "subing_ths_15m_v1",
  "parameters": {
    "fast": 12,
    "slow": 26,
    "signal": 9,
    "sma_period": 21,
    "ema_seed_policy": "sma_window",
    "histogram_scale": 2,
    "round_digits": 6
  },
  "bars": [
    {"bar_end": "...", "close": "...", "dif": null, "dea": null, "ma21": null, "result_codes": []}
  ]
}
```

Use a deterministic synthetic sequence that contains: warm-up, equality/no-cross, at least one buy, at least one sell, and a tail after both events. Expected values must be frozen in JSON rather than generated by the production kernel during the test.

Tests must prove:

```python
assert incremental_results == golden_results
assert run(prefix) == run(prefix + future_tail)[:len(prefix)]
assert rerun_same_input == first_run
```

- [ ] **Step 6: Run S1 kernel tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py
```

Expected: PASS.

- [ ] **Step 7: Commit the kernel**

```bash
git add packages/quant-core/guiyi_quant/indicators/subing_ths.py \
        packages/quant-core/guiyi_quant/indicators/__init__.py \
        services/quant-api/tests/test_subing_ths_kernel.py \
        tests/fixtures/subing_ths_15m_v1_golden.json
git commit -m "feat(indicators): add SuBing THS 15m kernel"
```

## S1.3 Add a typed physical-contract replay seam

**Files:**
- Modify `services/quant-api/app/market_data/market_read_service.py`
- Modify `services/quant-api/tests/test_market_read_service.py`

**Interface produced:**

```python
@dataclass(frozen=True, slots=True)
class CurrentContractReplayWindow:
    symbol: str
    frequency: str
    trading_day: date
    contract: str
    cutoff: datetime
    after: datetime | None
    bars: tuple[CanonicalBar, ...]

class MarketReadService:
    def current_contract_replay_window(
        self,
        decision_window: MarketReadWindow,
        *,
        after: datetime | None,
    ) -> CurrentContractReplayWindow: ...
```

Semantics:

- `decision_window` must already be a valid current `actual_dominant` intraday window ending at the trigger Bar。
- `after=None` means replay all available current physical-contract history through `cutoff`；used for first evaluation after process start or contract rollover。
- `after=<cursor>` means return all same-contract bars with `bar_end > after && bar_end <= cutoff`；used to reconcile one or more missed intermediate bars without creating historical Events。
- Historical pages use `SeriesKind.CONTRACT + decision_window.contract` through the existing `history_page()`/MarketDataService seam and paginate backward until the requested `after` boundary is reached or physical history is exhausted。
- Current trading-day Live bars are merged from the existing Live store, deduped exactly；same timestamp with unequal facts is an error。
- Returned bars are strictly increasing, all belong to the same physical contract by construction, and the last Bar must equal the decision window cutoff Bar。
- Pagination no-progress, wrong contract, missing cutoff or non-aware `after` must fail closed with stable `MarketReadWindowError` codes。

- [ ] **Step 1: Write RED tests for pre-dominant warm-up and rollover isolation**

Tests must include:

```text
current contract RB2610 has Canonical 15m bars before becoming rank1
actual_dominant decision window ends on RB2610
replay after=None includes RB2610 pre-dominant history
replay contains no RB2605 bars
last replay Bar equals trigger Bar
```

Also cover `after` filtering and multi-page history.

- [ ] **Step 2: Run focused RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py -k current_contract_replay
```

Expected: method/type missing.

- [ ] **Step 3: Implement backward pagination and Live merge**

Use `SeriesPageQuery(SeriesKind.CONTRACT, ..., contract=decision_window.contract, frequency=...)` with page size `2000` and `before=cutoff + 1 microsecond` for the first page. Continue only while the page reports earlier data needed to reach `after`; each next cursor must strictly decrease or raise `MARKET_READ_PAGINATION_STALLED`.

Do not add a second storage reader and do not inspect canonical filesystem paths.

- [ ] **Step 4: Prove `after` reconciliation and duplicate safety**

Add tests for:

```text
after == previous processed Bar → only missing/new bars returned
after == cutoff → empty replay is allowed and means duplicate/stale trigger
after > cutoff → fail closed
duplicate Canonical/Live same timestamp + same facts → dedupe
duplicate same timestamp + different facts → MARKET_READ_LIVE_UNAVAILABLE
```

- [ ] **Step 5: Run MarketRead tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py
```

- [ ] **Step 6: Commit the read seam**

```bash
git add services/quant-api/app/market_data/market_read_service.py \
        services/quant-api/tests/test_market_read_service.py
git commit -m "feat(market): add current-contract replay window"
```

## S1.4 Packet verification and Review gate

- [ ] **Step 1: Run the complete S1 focused set**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- [ ] **Step 2: Run Ruff/Mypy on touched source**

```bash
uv run --project services/quant-api python -m ruff check \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/app/market_data/market_read_service.py \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  packages/quant-core/guiyi_quant/indicators \
  services/quant-api/app/market_data/market_read_service.py
```

- [ ] **Step 3: Verify branch hygiene**

```bash
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 4: Create Draft PR to `develop`, request exact-head independent Review, then STOP**

S1 may be labeled `CODE_COMPLETE/TEST_COMPLETE` only after fresh commands pass. It does not authorize S2, production reads, Scope, notification, release or Runtime.

---

# Task 2 / Packet S2: Alert Runtime, Event Dispatch, Notification, Per-Rule Health

**Branch/worktree:** `feature/subing-ths-s2-alert-runtime` from latest `origin/develop` after S1 integration.

**Deliverable:** 当前单进程 Alert Runtime 可以安全运行两条 Rule；HTDY 保持既有 first-seen 语义，SuBing 只在 completed 15m current Bar 上按 S1 kernel 产生 exact Event，并使用同一 observers Topic one-shot 推送。

**Interfaces consumed:** S1 kernel + `current_contract_replay_window()`。

## S2.1 Extend the Alert registry without changing the DB schema

**Files:**
- Modify `services/quant-api/app/alerts/registry.py`
- Modify `services/quant-api/tests/test_alert_registry.py`

- [ ] **Step 1: Write RED registry tests**

Freeze:

```python
assert tuple(rule.rule_code for rule in alert_rule_definitions()) == (
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
)
assert get_alert_rule_definition("subing_ths_alert_15m_v1").input_frequencies == ("15m",)
assert get_alert_rule_definition("subing_ths_alert_15m_v1").series_kind == "actual_dominant"
assert get_alert_rule_definition("subing_ths_alert_15m_v1").event_mode.value == "exact"
assert get_alert_rule_definition("htdy_original_15m").event_mode.value == "first_seen"
```

- [ ] **Step 2: Run RED and implement**

Add:

```python
class AlertEventMode(StrEnum):
    FIRST_SEEN = "first_seen"
    EXACT = "exact"

SUBING_THS_ALERT_RULE_CODE = "subing_ths_alert_15m_v1"
```

Extend `AlertRuleDefinition` with `event_mode` and define SuBing as `indicator_observation`, 15m only, actual_dominant, exact mode.

- [ ] **Step 3: Run registry tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_registry.py

git add services/quant-api/app/alerts/registry.py services/quant-api/tests/test_alert_registry.py
git commit -m "feat(alerts): register SuBing THS observation rule"
```

## S2.2 Add generic evaluator dispatch and a stateful SuBing evaluator

**Files:**
- Modify `services/quant-api/app/alerts/evaluators.py`
- Modify `services/quant-api/tests/test_alert_evaluator.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AlertObservationCandidate:
    bar_end: datetime
    trading_day: date
    contract: str
    observation_types: tuple[Literal["buy", "sell"], ...]

class AlertRuleEvaluator(Protocol):
    def evaluate_candidates(
        self,
        market_read: AlertEvaluationMarketReader,
        window: MarketReadWindow,
    ) -> tuple[AlertObservationCandidate, ...]: ...
```

`SubingThs15mEvaluator` keeps only this transient cursor per symbol:

```python
@dataclass(slots=True)
class _SubingCursor:
    contract: str
    last_bar_end: datetime
    state: SubingThs15mState
```

No Redis state, no DB state, no strategy cache.

- [ ] **Step 1: Write RED tests for HTDY adapter and SuBing dispatch contract**

HTDY `evaluate_candidates()` must preserve current `evaluate_first_seen()` output exactly.

SuBing tests must prove:

```text
frequency != 15m → ALERT_EVALUATION_INPUT_INVALID
series_kind != actual_dominant → invalid
first call / no cursor → replay after=None
same contract next call → replay after=cursor.last_bar_end
same contract with two missing intermediate bars → step both silently, only final Bar may emit Candidate
contract changes → rebuild from after=None, no old state inheritance
stale/duplicate cutoff <= cursor.last_bar_end → no Candidate, no state rewind
warming/invalid final Bar → no Candidate and stable evaluation error
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py -k "subing or evaluate_candidates"
```

- [ ] **Step 3: Implement generic candidate + HTDY adapter**

Keep HTDY-specific `evaluate_first_seen()` if existing focused tests still use it, but Runtime must move to `evaluate_candidates()` so the dispatcher is rule-neutral.

Do not alter HTDY current-bar/repaint logic.

- [ ] **Step 4: Implement `SubingThs15mEvaluator`**

Algorithm:

```text
validate decision window actual_dominant + 15m + current contract
lookup cursor by symbol
if no cursor or cursor.contract != window.contract:
    replay = market_read.current_contract_replay_window(window, after=None)
    state = kernel.initial_state()
else if window.cutoff <= cursor.last_bar_end:
    return ()
else:
    replay = market_read.current_contract_replay_window(window, after=cursor.last_bar_end)
    state = cursor.state

step replay bars in chronological order
ignore Candidate results on every replay bar except the final cutoff Bar
require final Bar == window.cutoff
update cursor to final state/cutoff
return final result as () / one AlertObservationCandidate
```

The evaluator may reconstruct through downtime bars, but **must never return Candidates for those intermediate replay bars**.

- [ ] **Step 5: Run evaluator tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_evaluator.py

git add services/quant-api/app/alerts/evaluators.py services/quant-api/tests/test_alert_evaluator.py
git commit -m "feat(alerts): add SuBing THS evaluator"
```

## S2.3 Generalize notification policy without changing private config

**Files:**
- Modify `services/quant-api/app/alerts/notification.py`
- Modify `services/quant-api/app/alerts/notification_composition.py`
- Modify `services/quant-api/app/alerts/pushplus.py` only if an audience alias is required；do not change config keys.
- Modify `services/quant-api/tests/test_alert_notification.py`
- Modify `services/quant-api/tests/test_alert_pushplus.py`
- Modify `services/quant-api/tests/test_alert_notification_config.py` only for non-regression if necessary.

- [ ] **Step 1: Write RED policy/formatter tests**

Freeze exact titles/audience:

```python
assert dispatcher.supported_rule_codes == (
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
)
```

SuBing buy copy must include only:

```text
【苏冰预警】<SYMBOL> <产品名>
15m 多头预警
MACD 金叉
收盘价位于 MA21 上方
当前主力：<contract>
信号K线：<Asia/Shanghai time>
请打开归一量化图表复核。
研究观察，非交易指令
```

Sell uses `空头预警 / MACD 死叉 / MA21 下方`。

Both HTDY and SuBing policy use the existing observers audience string backed by `htdy_topic`；do not add `subing_topic`.

- [ ] **Step 2: Run RED and implement `AlertNotificationPolicy`**

Public shape:

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationPolicy:
    rule_code: str
    title: str
    audience: str
    formatter: Callable[[AlertNotificationMessage], str]
```

`AlertNotificationDispatcher.send()` must exact-lookup by `message.rule_code`; unknown rule raises `ALERT_NOTIFICATION_RULE_INVALID` rather than falling back to HTDY.

- [ ] **Step 3: Preserve PushPlus transport semantics**

`PushPlusTransport` continues:

```text
observers audience → existing htdy_topic
owner audience → topic=None
```

No retry/config migration/member lookup.

- [ ] **Step 4: Run focused notification tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_notification_config.py

git add services/quant-api/app/alerts/notification.py \
        services/quant-api/app/alerts/notification_composition.py \
        services/quant-api/app/alerts/pushplus.py \
        services/quant-api/tests/test_alert_notification.py \
        services/quant-api/tests/test_alert_pushplus.py \
        services/quant-api/tests/test_alert_notification_config.py
git commit -m "feat(alerts): dispatch notifications by rule policy"
```

## S2.4 Replace the single evaluator runtime seam and preserve event semantics

**Files:**
- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/alerts/composition.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_alert_service.py`

**Constructor after this task:**

```python
AlertRuntime(
    *,
    session_factory,
    market_read_factory,
    evaluators: Mapping[str, AlertRuleEvaluator],
    sender: AlertNotificationSender,
    operational_products,
    taxonomy,
    ...,
)
```

- [ ] **Step 1: Write RED startup-composition tests**

Fail closed when:

```text
DB Rule set != registry Rule set
registry Rule has no evaluator
sender.supported_rule_codes != registry Rule set
unknown DB Rule exists
```

- [ ] **Step 2: Write RED live dispatch tests**

Prove:

```text
HTDY rule invokes only HtdyOriginalEvaluator
SuBing rule invokes only SubingThs15mEvaluator
SuBing rule ignores non-15m live triggers
SuBing rule never runs on canonical_updated
Scope disabled/no symbol-frequency → no evaluator call
startup drain emit_events=false → no Event/no sender call
```

- [ ] **Step 3: Generalize event persistence by `AlertEventMode`**

Replace `_persist_first_seen_htdy_and_prepare_notification` with a rule-neutral helper. It must call:

```python
if definition.event_mode is AlertEventMode.FIRST_SEEN:
    created = service.create_first_seen_observation_event(request)
elif definition.event_mode is AlertEventMode.EXACT:
    created = service.create_event(request)
else:
    fail_closed
```

Do not weaken current exact conflict checks in `AlertService.create_event()`.

- [ ] **Step 4: Generalize runtime evaluator lookup**

For each enabled Rule:

```text
get definition
scope check
build/validate decision window
lookup evaluator by exact rule_code
evaluator.evaluate_candidates(market_read, window)
validate candidate identity against decision window
persist according to event_mode
prepare notification message
```

Candidate validator must reject wrong bar_end/contract/trading_day/result codes before Event persistence.

- [ ] **Step 5: Preserve Event-first one-shot behavior under partial failures**

Tests must explicitly show:

```text
Event commit succeeds + taxonomy missing → Event remains, no transport
Event commit succeeds + formatter fails → Event remains, failure recorded
Event commit succeeds + transport fails → Event remains, no retry
same Event identity repeated → no second send
```

- [ ] **Step 6: Run focused Runtime/Service tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py

git add services/quant-api/app/alerts/runtime.py \
        services/quant-api/app/alerts/composition.py \
        services/quant-api/tests/test_alert_runtime.py \
        services/quant-api/tests/test_alert_service.py
git commit -m "refactor(alerts): dispatch evaluators by rule"
```

## S2.5 Upgrade runtime status to schema v6 with bounded per-rule state

**Files:**
- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/services/runtime_health.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_runtime_health.py`

- [ ] **Step 1: Write RED status-validation tests**

Target wire:

```python
{
  "schema_version": 6,
  ...existing_v5_fields,
  "rule_status": {
    "htdy_original_15m": {
      "last_evaluated_bar_at": None,
      "last_event_at": None,
      "last_failure_at": None,
      "error_type": None,
    },
    "subing_ths_alert_15m_v1": {
      "last_evaluated_bar_at": None,
      "last_event_at": None,
      "last_failure_at": None,
      "error_type": None,
    },
  },
}
```

v1-v5 reads must normalize to v6 with empty fixed rule entries；unknown extra Rule key fails closed。

- [ ] **Step 2: Define fixed public rule error types**

Use a small set only:

```text
evaluation_input_invalid
evaluation_warming_up
evaluation_failed
```

No symbol history and no error stack/message is stored.

- [ ] **Step 3: Update runtime state at the correct point**

For each Rule:

```text
scope skipped → no rule_status change
evaluator returns successfully, even no signal → last_evaluated_bar_at advances; error_type cleared
new Event → that Rule last_event_at advances
evaluator/input/warmup failure → last_failure_at + fixed error_type; last_evaluated_bar_at must not advance
notification failure remains in existing global notification fields; do not overload rule evaluation status
```

- [ ] **Step 4: Expose status read-only through runtime health**

`runtime_health.py` may project the validated map but must not infer “business normal” from heartbeat alone.

- [ ] **Step 5: Run v5→v6 compatibility and health tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

- [ ] **Step 6: Commit status v6**

```bash
git add services/quant-api/app/alerts/runtime.py \
        services/quant-api/app/services/runtime_health.py \
        services/quant-api/tests/test_alert_runtime.py \
        services/quant-api/tests/test_runtime_health.py
git commit -m "feat(alerts): expose per-rule evaluation status"
```

## S2.6 Packet verification and Review gate

- [ ] **Step 1: Run complete Alert focused set**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_notification_config.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

- [ ] **Step 2: Run adjacent Market/HTDY regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_market_read_service.py
```

- [ ] **Step 3: Run Ruff/Mypy + diff check**

Use the repository commands in `TESTING.md` narrowed to touched modules, then:

```bash
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 4: Create Draft PR, exact-head independent Review, STOP**

S2 does not create/migrate the new DB Rule and does not send any real notification.

---

# Task 3 / Packet S3: Generic Alert API + Market Web Review Surface

**Branch/worktree:** `feature/subing-ths-s3-web` from latest `origin/develop` after S2 integration.

**Deliverable:** 现有 `/api/alerts/*` 可以返回两条 Rule；`/market` 一次读取 current-events 显示最近苏冰预警；`/market/chart` 在 actual_dominant 15m 上显示 Event-backed `S↑/S↓` 并支持 deep link 聚焦。Web 不计算正式公式。

## S3.1 Generalize backend Alert DTO and serializer

**Files:**
- Modify `services/quant-api/app/schemas/alerts.py`
- Modify `services/quant-api/app/api/alerts.py`
- Modify `services/quant-api/tests/test_alert_api.py`

- [ ] **Step 1: Write RED API tests for mixed Rules**

Freeze the wire union:

```python
AlertRuleCode = Literal[
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
]
```

Tests:

```text
GET /events?rule_code=subing_ths_alert_15m_v1 returns real rule_code
/current-events may return HTDY + SuBing in deterministic detected/bar/id order
/products/{symbol}/current-events may return both
unknown rule remains 404
existing HTDY payload fields remain unchanged
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py
```

- [ ] **Step 3: Replace HTDY-only DTO names with generic Alert DTOs**

Do not create `/api/subing/*`.

Serializer must derive Rule code from DB facts, never hard-code `HTDY_ALERT_RULE_CODE`. Avoid N+1 lookup by building a `rule_id → rule_code` map once per response or selecting rule code together with events.

- [ ] **Step 4: Run API tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py

git add services/quant-api/app/schemas/alerts.py \
        services/quant-api/app/api/alerts.py \
        services/quant-api/tests/test_alert_api.py
git commit -m "refactor(api): support multiple Alert observation rules"
```

## S3.2 Add typed Web Rule/Event presentation

**Files:**
- Modify `apps/quant-web/src/types/market.ts`
- Modify `apps/quant-web/src/api/alerts.ts`
- Modify `apps/quant-web/src/utils/alertRules.ts`
- Modify `apps/quant-web/tests/alerts.test.ts`
- Modify `apps/quant-web/tests/alertRuleOwnership.test.ts`

- [ ] **Step 1: Write RED TypeScript tests**

Add exact presentation:

```ts
export const SUBING_THS_ALERT_RULE_CODE = 'subing_ths_alert_15m_v1'
```

Expected presentation:

```text
shortLabel = 苏冰预警
resultNoun = 预警
persistentFrequencies = [15m]
```

`AlertEvent` becomes `HtdyAlertEvent | SubingThsAlertEvent`.

- [ ] **Step 2: Add `getCurrentAlertEvents()`**

Client response remains the existing `/api/alerts/current-events` shape；do not add a new endpoint.

- [ ] **Step 3: Run Web unit RED→GREEN and commit**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts \
  tests/alertRuleOwnership.test.ts

git add apps/quant-web/src/types/market.ts \
        apps/quant-web/src/api/alerts.ts \
        apps/quant-web/src/utils/alertRules.ts \
        apps/quant-web/tests/alerts.test.ts \
        apps/quant-web/tests/alertRuleOwnership.test.ts
git commit -m "feat(web): type SuBing Alert events"
```

## S3.3 Render persistent `S↑/S↓` markers without adding an overlay

**Files:**
- Modify `apps/quant-web/src/utils/alertMarkers.ts`
- Modify `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify `apps/quant-web/src/pages/market/chart.vue`
- Modify marker/composable tests and `KlineChart` tests only if needed.

- [ ] **Step 1: Write RED marker tests**

Freeze:

```text
SuBing buy → label S↑, shape arrowUp, belowBar
SuBing sell → label S↓, shape arrowDown, aboveBar
Tooltip contains 苏冰预警 / MACD 金叉或死叉 / Close > or < MA21 (SMA21) / contract / 15m time
HTDY remains square/persistent-first-seen presentation
```

- [ ] **Step 2: Freeze visibility rules**

`alertMarkersForOverlay()` must return:

```text
SuBing markers: visible on actual_dominant 15m regardless of overlay none/htdy
HTDY persistent markers: visible only when overlay=htdy, preserving current behavior
other identities: no marker
```

Do not add `ResearchOverlayId='subing'`.

- [ ] **Step 3: Update persistent marker fetch**

At `actual_dominant + 15m`, `markerRuleCodes()` returns exactly HTDY + SuBing, so the composable makes at most two rule-range calls for the selected chart identity, not 60 product calls.

- [ ] **Step 4: Run marker tests GREEN and commit**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts \
  tests/marketSeries.test.ts \
  tests/kline-view-model.test.ts
```

Also run any focused marker/composable test files present at execution time.

## S3.4 Add the `/market` recent SuBing alert card

**Files:**
- Create `apps/quant-web/src/components/market/MarketRecentSubingAlerts.vue`
- Modify `apps/quant-web/src/pages/market/index.vue`
- Add/modify focused unit/E2E tests.

- [ ] **Step 1: Write RED component/page tests**

The component receives already-fetched events + dominant products and displays at most 20 SuBing events with:

```text
Shanghai HH:mm
product_name + SYMBOL
多头预警 / 空头预警
15m
```

Empty state: `暂无苏冰预警`。

- [ ] **Step 2: Add one global resource request**

`market/index.vue` adds exactly one `useLatestResource({ fetch: getCurrentAlertEvents })` alongside runtime and dominant directory resources. `refreshAll()` / visible refresh include that resource in the existing `Promise.all`.

Do not issue product-by-product requests.

- [ ] **Step 3: Add click navigation**

The click route must be:

```ts
{
  name: 'market-chart',
  query: {
    symbol: event.symbol,
    series_kind: 'actual_dominant',
    frequency: '15m',
    focus_bar_end: event.bar_end,
  },
}
```

No signal values are computed in the component.

- [ ] **Step 4: Run focused tests GREEN and commit**

```bash
pnpm --dir apps/quant-web test
```

If the full unit suite is expensive, first run the exact new test file, then the full suite before Packet completion.

## S3.5 Consume `focus_bar_end` using existing `KlineChart.revealTime()`

**Files:**
- Modify `apps/quant-web/src/pages/market/chart.vue`
- Modify `apps/quant-web/tests/marketChartEntry.test.ts` or add a focused chart-entry test.
- Modify Playwright spec covering market chart interaction.

- [ ] **Step 1: Write RED deep-link tests**

Rules:

```text
focus_bar_end must be timezone-aware parseable ISO
only applies to actual_dominant + 15m
after first matching replacement load, call chart.revealTime(focus_bar_end)
if bar is not in loaded window, keep normal chart and do not synthesize a Bar/marker
focus does not change Event.bar_end
invalid focus value ignored fail-safe
```

- [ ] **Step 2: Implement one-shot focus**

Use the existing exposed `revealTime()`；do not add a second chart scrolling primitive. Preserve `focus_bar_end` through the initial query synchronization until focus is attempted once, then remove it from the URL with `router.replace()` without altering symbol/series/frequency.

- [ ] **Step 3: Run Web full checks for S3**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 4: Commit Web completion**

```bash
git add apps/quant-web
git commit -m "feat(web): show SuBing alerts in Market"
```

## S3.6 Packet backend/Web regression and Review gate

- [ ] **Step 1: Run backend API/Alert regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py
```

- [ ] **Step 2: Run diff/secret checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 3: Create Draft PR, independent exact-head Review, STOP**

No production Web deployment or Runtime mutation is authorized.

---

# Task 4 / Packet S4: Migration 0044 + Atomic First Scope Activation Seam

**Branch/worktree:** `feature/subing-ths-s4-migration-scope` from latest `origin/develop` after S3 integration.

**Deliverable:** forward-only 0044 Rule insertion plus一个严格、可 dry-run、单事务的首次 `operational × 15m` Scope activation CLI seam。Implementation/test only；不得执行 production migration/Scope。

## S4.1 Add 0044 as a data-only forward migration

**Files:**
- Create `services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py`
- Create `services/quant-api/tests/alembic/test_subing_ths_alert_migration.py`

- [ ] **Step 1: Write the isolated PostgreSQL RED migration test**

The test must build the exact 0042 state, run 0043, then 0044 and assert:

```text
alembic head == 20260902_0044
alert_rules == {htdy_original_15m, subing_ths_alert_15m_v1}
HTDY row byte-for-byte equivalent on preserved columns
SuBing enabled == false
SuBing scope_product_frequencies == {}
no scope_products column
no action_id column
no strategy_payload column
legacy SuBing Event/Rule absent
```

- [ ] **Step 2: Run RED only against a disposable DB**

Use exactly the `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` mechanism in `TESTING.md`. If no disposable DB URL is configured, record this step as blocked rather than substituting production/local primary DB.

- [ ] **Step 3: Implement strict preflight/postflight**

0044 constants:

```python
revision = "20260902_0044"
down_revision = "20260902_0043"
_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"
```

Preflight must require exact 0043 schema, exactly one HTDY Rule, valid HTDY scope/events and no unexpected Rule. Insert only the new Rule row.

`downgrade()` must raise a stable unsupported error.

- [ ] **Step 4: Test unexpected-state fail-closed and 0043-success/0044-failure safety**

Tests must show no code path recreates `subing_strategy_v1` or deleted columns. A simulated 0044 insertion/postflight failure leaves the already-applied 0043 DB HTDY-only; recovery is forward-only.

- [ ] **Step 5: Run migration tests GREEN and commit**

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py

git add services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py \
        services/quant-api/tests/alembic/test_subing_ths_alert_migration.py
git commit -m "feat(db): add SuBing THS Alert rule migration"
```

## S4.2 Add a narrow dry-run/apply scope activation service

**Files:**
- Create `services/quant-api/app/alerts/subing_scope_activation.py`
- Modify `services/quant-api/tests/test_alert_service.py` or add a focused `test_subing_scope_activation.py` if that keeps responsibility clearer.

**Interface:**

```python
@dataclass(frozen=True, slots=True)
class SubingScopeActivationResult:
    status: Literal["planned", "published"]
    readonly: bool
    rule_code: str
    symbol_count: int
    scope_sha256: str
    enabled: bool


def activate_subing_ths_scope(
    session: Session,
    *,
    operational_products: tuple[str, ...],
    apply: bool,
) -> SubingScopeActivationResult: ...
```

- [ ] **Step 1: Write RED dry-run tests**

Dry-run must:

```text
require alembic head 0044
require exactly HTDY + new SuBing Rule
require SuBing enabled=false and scope={}
normalize/sort/unique operational symbols
build {symbol:["15m"]}
return count + SHA256 of stable sorted JSON
perform no UPDATE/commit mutation
```

Do not print the full Scope unless an existing safe operator pattern requires it；count+hash is sufficient for Gate comparison.

- [ ] **Step 2: Write RED apply tests**

Apply must perform in one transaction:

```text
re-read/lock SuBing Rule
re-check disabled + empty scope
set exact full scope
set enabled=true
commit once
re-read and verify exact scope hash/count/enabled
HTDY row unchanged
```

Any preflight mismatch fails before mutation. Any DB exception rolls back.

- [ ] **Step 3: Implement and run focused GREEN**

No generic workflow engine, no per-symbol loop that commits repeatedly.

- [ ] **Step 4: Commit activation service**

```bash
git add services/quant-api/app/alerts/subing_scope_activation.py \
        services/quant-api/tests/test_subing_scope_activation.py
git commit -m "feat(alerts): add atomic SuBing scope activation"
```

If the implementation chooses to place tests in `test_alert_service.py`, stage that exact file instead of a nonexistent focused file.

## S4.3 Wire a runtime CLI command with read-only default

**Files:**
- Modify `services/quant-api/app/guiyi_cli/main.py`
- Modify `services/quant-api/tests/test_alert_cli.py`

- [ ] **Step 1: Write parser/execution RED tests**

Command:

```bash
uv run --project services/quant-api guiyi runtime subing-ths-scope
uv run --project services/quant-api guiyi runtime subing-ths-scope --apply
```

Default output:

```json
{
  "schema_version": 1,
  "command": "runtime.subing-ths-scope",
  "status": "planned",
  "readonly": true,
  "rule_code": "subing_ths_alert_15m_v1",
  "symbol_count": 60,
  "scope_sha256": "<64 hex>",
  "enabled": false
}
```

`--apply` returns `status=published`, `readonly=false`, `enabled=true` after verified commit. Tests use fake/session fixtures only；do not hit production.

- [ ] **Step 2: Correct CLI readonly classification**

`_execution_is_readonly()` must return `True` for the command without `--apply`, `False` with `--apply`. Parse-error classification must likewise not label a requested `--apply` as readonly.

- [ ] **Step 3: Inject the activation callable for tests**

Follow existing CLI dependency injection; do not hard-wire an untestable global DB call.

- [ ] **Step 4: Run CLI tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_cli.py

git add services/quant-api/app/guiyi_cli/main.py \
        services/quant-api/tests/test_alert_cli.py
git commit -m "feat(cli): add SuBing scope activation command"
```

## S4.4 Packet verification and Review gate

- [ ] **Step 1: Run migration + activation focused tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py \
  services/quant-api/tests/test_alert_service.py
```

Run isolated migration tests separately only against the approved disposable DB URL.

- [ ] **Step 2: Run full non-isolated backend regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] **Step 3: Ruff/Mypy/secret/diff**

```bash
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering

python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
```

- [ ] **Step 4: Draft PR + exact-head independent Review + STOP**

Do not execute `alembic upgrade`, `guiyi runtime subing-ths-scope --apply`, or any real DB/Scope command in this Packet.

---

# Task 5 / Packet S5: Canonical Sync, OpenSpec, Full Verification, RC Handoff

**Branch/worktree:** `docs/subing-ths-s5-canonical-rc` from latest `origin/develop` after S4 integration.

**Deliverable:** active canonical 与代码事实一致，OpenSpec/TESTING 可执行，全仓 fresh verification + exact-head independent Review 完成，结论最多到“允许进入 release candidate”。

## S5.1 Synchronize active canonical only after code exists in develop

**Files:**
- Modify `AGENTS.md`
- Modify `PROJECT_SOURCE.md`
- Modify `DECISIONS.md`
- Modify `docs/ARCHITECTURE.md`
- Modify `TESTING.md`
- Modify `tests/engineering/test_canonical_consistency.py`

- [ ] **Step 1: Write/adjust canonical consistency tests first**

Tests must require active facts equivalent to:

```text
stable Alert rules after 0044 schema: HTDY + subing_ths_alert_15m_v1
SuBing is observation-only, 15m actual_dominant completed-only
MA21 is SMA21
no old subing_strategy_v1 active implementation restored
Event-first one-shot transport remains
Range/zero-axis/multi-timeframe are not SuBing V1 gates
production state remains whatever STATUS.md actually says; docs cannot invent migration/Runtime completion
```

- [ ] **Step 2: Run canonical test RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
```

Expected: fail because active docs still describe HTDY-only stable product surface.

- [ ] **Step 3: Update canonical responsibilities precisely**

`PROJECT_SOURCE.md`：增加“苏冰预警”最小 observation 产品，不把它写成策略交易系统。

`DECISIONS.md`：增加长期冻结公式 identity/新身份/one-shot observation；保留“旧策略整体退役”，明确新苏冰不是恢复旧身份。

`docs/ARCHITECTURE.md`：在现有 Alert evaluator 旁增加 SuBing 15m evaluator branch；不新增第二 Runtime。

`AGENTS.md`：Alert Runtime active combinations 在 0044 后允许 HTDY + SuBing；真实 Scope/通知/DB/Runtime 仍需独立 Gate。

`TESTING.md`：增加 S1/S2/S3/S4 focused commands、0044 isolated test、Web alert checks；仍注明命令不授权真实外部操作。

`STATUS.md` **本 Packet 默认不改**。只有执行时已有新的真实 release/Runtime/DB evidence 才允许按事实另行更新；“代码完成”不是 STATUS 运行事实。

- [ ] **Step 4: Run canonical tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py

git add AGENTS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md \
        tests/engineering/test_canonical_consistency.py
git commit -m "docs: define active SuBing THS alert contract"
```

## S5.2 Add strict OpenSpec contract

**File:**
- Create `openspec/specs/subing-ths-alert/spec.md`

- [ ] **Step 1: Write the OpenSpec from the approved Spec, not from implementation convenience**

It must freeze at least:

```text
rule/formula identity
completed actual_dominant 15m only
exact CROSS + SMA21
same-contract state isolation
no hidden filters
Event identity/idempotency
one-shot transport/no retry
Web Event authority
0044 disabled+empty scope
atomic first activation
external Gate separation
```

- [ ] **Step 2: Run strict validation**

```bash
openspec validate --specs --strict --no-interactive
```

- [ ] **Step 3: Commit OpenSpec**

```bash
git add openspec/specs/subing-ths-alert/spec.md
git commit -m "docs(openspec): specify SuBing THS alert V1"
```

## S5.3 Run fresh full verification at exact head

- [ ] **Step 1: Sync locked dependencies only; do not update them**

```bash
uv sync --project services/quant-api --locked
```

- [ ] **Step 2: Run full non-isolated backend**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] **Step 3: Run isolated PostgreSQL migration suite**

Only if the dedicated disposable URL is configured:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic
```

If unavailable, S5 is **blocked from TEST_COMPLETE**；do not substitute production DB.

- [ ] **Step 4: Run Mypy/Ruff**

```bash
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

- [ ] **Step 5: Run full Web**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 6: Run canonical/OpenSpec/security/diff checks**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 7: Record exact fresh outputs in the Draft PR body**

Do not summarize skipped isolated tests as passed. Distinguish `passed / skipped / deselected / not run` exactly.

## S5.4 Independent exact-head Review

- [ ] **Step 1: Freeze exact review head**

```bash
git rev-parse HEAD
git status --short
```

Working tree must be clean.

- [ ] **Step 2: Request two-axis independent review**

Reviewer must inspect exact HEAD against:

```text
Standards axis: AGENTS / data facts / security / migration / one-shot transport / Git boundaries
Spec axis: exact formula / no hidden filters / same-contract causality / Event authority / Web / external Gates
```

Required finding severities: Critical / High / Medium / Low with file/line evidence. Any Critical/High blocks. Medium affecting contract/causality/migration/notification also blocks until fixed and re-reviewed.

- [ ] **Step 3: If fixes are required, implement in S5 branch, rerun all affected verification, freeze a new exact head, and re-review**

Do not carry an approval from an earlier SHA to a changed SHA.

- [ ] **Step 4: Final S5 commit if Review-driven docs/tests changed**

Use a narrow message such as:

```bash
git commit -m "fix: close SuBing THS release-candidate findings"
```

## S5.5 RC handoff and STOP

- [ ] **Step 1: Confirm all five Packet merge ancestry in `develop`**

At the moment S5 is ready to integrate, show that S1–S4 merge commits are reachable from the base `develop` used by S5.

- [ ] **Step 2: Create/update Draft PR to `develop` with exact evidence**

The PR may conclude only:

```text
CODE_COMPLETE
TEST_COMPLETE
independent Review approved
允许进入 release candidate（等待 owner Gate）
```

It must not claim `RELEASED` / `RUNTIME_READY` / `BUSINESS_CLOSED`.

- [ ] **Step 3: STOP before any release or external mutation**

The next operations are separate future Gates from the Spec:

```text
G5 release main/tag
G6 Runtime maintenance stop
G7 production DB 0042→0044
G8 exact-tag Runtime promotion
G9 production Scope activation + Rule enable
G10 同花顺兼容性 evidence
G11 自然 15m Event / one-shot transport
G12 用户人工微信送达确认
```

No Packet implementation session may cross these Gates automatically.

---

# Packet Integration Protocol

For **each** S1–S5 Packet:

1. `git fetch origin`。
2. Confirm latest `origin/develop`, approved Spec, this Plan, current `STATUS.md`, and no conflicting active task touches the same files.
3. Use `superpowers:using-git-worktrees` to create a fresh task worktree from latest `origin/develop`。
4. Follow TDD: RED → confirm expected failure → minimal GREEN → adjacent regression → refactor → commit。
5. Keep commits single-purpose and do not mix another Packet or unrelated refactor。
6. Run fresh verification and `superpowers:verification-before-completion` before claiming complete。
7. Create Draft PR to `develop` only。
8. Self-review, then use `superpowers:requesting-code-review` for an exact-head independent Review。
9. Stop and wait for owner `允许集成 develop`。
10. After approved merge, verify the merge is reachable from `develop`, then clean the merged task worktree/branch。
11. Start the next Packet in a **new Codex session** from the new latest `develop`。

No automatic `task → develop` merge is authorized by this Plan.

---

# External Operation Runbook Boundary

This Plan intentionally stops before external execution. Later release/operator work must be a separate Lane 3 task and re-read the then-current `STATUS.md`.

The expected *shape* is:

```text
approved develop RC
→ separate release Gate
→ main + annotated tag + GitHub Release + identity readback
→ separate Runtime maintenance-stop Gate
→ separate production DB Gate: forward-only current production head → 0044
→ DB postflight/readback
→ separate exact-tag Runtime promotion Gate
→ health/smoke
→ separate Scope activation Gate using `guiyi runtime subing-ths-scope --apply`
→ source compatibility Gate against real 同花顺 samples
→ natural completed 15m observation
→ Event + one-shot transport evidence
→ user confirms actual WeChat delivery
```

The exact release version is **not preassigned by this Plan**. It must be selected during the future release task from then-current `main`/Release facts; this is an explicit decision, not a placeholder.

---

# Implementation Plan Self-Review

The completed Plan was checked against all 26 Spec sections. Corrections captured before submission:

1. **Avoided rolling 64-Bar replay for EMA state.** A bounded sliding EMA replay would change seed history as the window moves and violate prefix invariance. The Plan instead uses a small in-memory cursor plus a typed physical-contract replay seam: full same-contract rebuild on first use/rollover, then `after=cursor` reconciliation.
2. **Downtime reconciliation does not become backfill.** Missing intermediate Bars may advance indicator state, but only the current trigger Bar may create a Candidate/Event.
3. **Event persistence semantics stay Rule-specific.** HTDY keeps first-seen immutable mode; SuBing uses exact fact matching. No shared helper weakens either contract.
4. **Notification policy is explicit.** Missing evaluator or formatter cannot silently fall back to HTDY.
5. **Private PushPlus config is not expanded.** Both observation products use the existing observers Topic in V1; no second token/Topic/member database.
6. **Per-rule health remains bounded.** Only four timestamps/error fields per fixed Rule；no symbol ledger, no second Redis key, no PostgreSQL history table.
7. **Web deep link reuses `KlineChart.revealTime()`.** No second chart navigation system and no Event time rewriting.
8. **SuBing markers are not tied to a new overlay.** They remain Event-backed review facts visible on actual_dominant 15m；HTDY overlay behavior stays unchanged.
9. **0044 does not hard-code current 60 products.** It inserts disabled+empty Rule only；first activation atomically reads the execution-time operational universe.
10. **Scope activation has one transaction and one dry-run hash.** No 60 independent HTTP writes and no generic workflow engine.
11. **Canonical is updated last.** S1–S4 code can be reviewed without prematurely claiming the product is active；S5 aligns stable docs only after implementation exists in `develop`.
12. **Current production state is not rewritten.** v1.9.12 release / v1.9.11 Runtime / production 0042 remain `STATUS.md` facts until separate real operations occur.
13. **Release version is intentionally deferred, not TBD.** The future release task chooses it from then-current facts.
14. **No formula duplicate.** API, formatter and Web derive wording/presentation from Event direction; only `SubingThs15mKernel` decides Candidate.
15. **No legacy strategy resurrection.** No planned file path recreates Daily Watch/Factor/Lifecycle/Action/Episode/Position/Strategy Runtime or old Scope columns.

Placeholder scan: no `TBD`, `TODO`, `implement later`, unresolved product choice or “similar to previous task” instruction is intentionally left in this Plan.

Type/interface check: S2 consumes only S1 public interfaces; S3 consumes S2 registry/Event wire; S4 assumes S2/S3 application code plus 0043 schema lineage; S5 only synchronizes canonical after S1–S4 are integrated.

---

# Final Gate For This Plan

This document is Implementation Plan only. User approval authorizes starting **S1 only** in a new Lane 3 implementation session.

Plan approval does **not** authorize:

```text
S1 auto-merge to develop
S2-S5 in the same session
production PostgreSQL/Redis/Scope
real PushPlus
Runtime switch/promotion
main merge
tag
GitHub Release
```

S1 must stop at Draft PR + exact-head Review + owner `允许集成 develop` Gate.