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

### Normative safety amendment for the approved Spec

批准 Spec 内部存在一个必须 fail-closed 处理的 Gate 顺序冲突：

- §20 明确规定：同花顺兼容性 evidence **未通过不得启用真实 SuBing Rule**；
- §22 的列表却把 `G9 production Scope activation + Rule enable` 排在 `G10 同花顺兼容性 evidence` 之前。

本 Plan 不猜测“哪一条可以忽略”，而采用更严格且与 §20 的直接安全要求一致的执行顺序：

```text
0044 DB + exact-tag Runtime 就绪，但 SuBing Rule 保持 disabled + empty scope
→ 先完成同花顺兼容性 evidence（Spec G10，read-only，不发送）
→ evidence 通过后才允许 Scope activation + Rule enable（Spec G9）
→ 再等待自然 15m Event / one-shot transport
```

因此未来执行顺序是 **G10 before G9**。Gate 名称仍沿用 Spec，只有顺序被安全收紧。本 Plan 的用户批准即视为对这一冲突处理方式的明确批准；若用户不同意，必须先修订 Spec/Plan，不能进入实现。

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
- Modify `services/quant-api/app/alerts/service.py`：沿现有 exact Event 创建路径复用，不复制数据库写逻辑。
- Modify `services/quant-api/app/alerts/notification.py`：rule notification policy、SuBing formatter、shared observers audience。
- Modify `services/quant-api/app/alerts/notification_composition.py`：构造支持两条 Rule 的 dispatcher，不改变私有配置 schema。
- Modify `services/quant-api/app/alerts/runtime.py`：evaluator map、event mode、rule status v6、SuBing 15m only。
- Modify `services/quant-api/app/alerts/composition.py`：构造两 evaluator + 两 notification policy。
- Modify `services/quant-api/app/services/runtime_health.py`：只读暴露 v6 `rule_status`。
- Modify focused Alert tests：`test_alert_registry.py`、`test_alert_evaluator.py`、`test_alert_service.py`、`test_alert_notification.py`、`test_alert_runtime.py`、`test_runtime_health.py`、`test_alert_pushplus.py`。

### S3 — Generic Alert API + Market Web

- Modify `services/quant-api/app/schemas/alerts.py`：两条 Rule 的 exact union DTO。
- Modify `services/quant-api/app/api/alerts.py`：真实 rule_code serializer、mixed current-events。
- Modify `services/quant-api/tests/test_alert_api.py`。
- Modify `apps/quant-web/src/types/market.ts`、`src/api/alerts.ts`、`src/utils/alertRules.ts`、`src/utils/alertMarkers.ts`、`src/composables/usePersistentAlertMarkers.ts`。
- Create `apps/quant-web/src/components/market/MarketRecentSubingAlerts.vue`。
- Modify `apps/quant-web/src/pages/market/index.vue`、`src/pages/market/chart.vue`。
- Modify `apps/quant-web/scripts/checkAlertRuleOwnership.mjs` 与相关 unit/E2E tests。

### S4 — Migration 0044 + atomic Scope activation seam

- Create `services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py`。
- Create `services/quant-api/tests/alembic/test_subing_ths_alert_migration.py`。
- Create `services/quant-api/app/alerts/subing_scope_activation.py`。
- Create `services/quant-api/tests/test_subing_scope_activation.py`。
- Modify `services/quant-api/app/guiyi_cli/main.py`、`services/quant-api/tests/test_alert_cli.py`。

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

```python
from guiyi_quant.indicators import initial_sma_state, step_sma


def test_sma_warms_then_rolls_exactly() -> None:
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
    assert point.value == 3.666667


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

Create `sma.py`:

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

Committed tests must construct state only through ordinary `initial_state()` + `step()` calls. Freeze:

```python
kernel = SubingThs15mKernel()
assert kernel.formula_version == "subing_ths_15m_v1"
assert kernel.ema_seed_policy == "sma_window"
assert kernel.histogram_scale == 2
assert kernel.round_digits == 6
```

Also cover `prev_dif == prev_dea` crossing, current equality no-cross, `close == ma21`, buy and sell exclusivity.

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

- [ ] **Step 4: Implement the exact step semantics**

```text
1. step MACD and SMA with current close
2. if any required current point invalid → valid=false, no Candidate, clear previous DIF/DEA continuity
3. if MACD/SMA not ready → ready=false, no Candidate
4. use six-decimal point.value for Candidate comparisons
5. golden = prev_dif <= prev_dea and dif > dea and close > ma21
6. dead   = prev_dif >= prev_dea and dif < dea and close < ma21
7. emit exactly () / ("buy",) / ("sell",)
8. update previous DIF/DEA only from a ready+valid current MACD pair
```

Do not read MACD histogram, zero axis, volume, Range or any other fact in Candidate logic.

- [ ] **Step 5: Add the frozen golden fixture and parity tests**

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
    {"bar_end": "2026-01-01T01:00:00+00:00", "close": "100", "dif": null, "dea": null, "ma21": null, "result_codes": []}
  ]
}
```

Use a deterministic synthetic sequence containing warm-up, equality/no-cross, at least one buy, at least one sell, and a tail after both events. Expected values are frozen in JSON and must not be generated by the production kernel during the test.

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
- `after=None` means replay all available current physical-contract history through `cutoff`；used on first evaluation after process start or contract rollover。
- `after=<cursor>` returns all same-contract bars with `bar_end > after && bar_end <= cutoff`；used to reconcile missed intermediate bars without historical Events。
- Historical pages use `SeriesKind.CONTRACT + decision_window.contract` through existing `history_page()`/MarketDataService and paginate backward until the requested `after` is reached or physical history is exhausted。
- Current trading-day Live bars are merged from the existing Live store and deduped exactly；same timestamp with unequal facts is an error。
- Returned bars are strictly increasing and the last Bar must equal the decision-window cutoff Bar。

- [ ] **Step 1: Write RED tests for pre-dominant warm-up and rollover isolation**

Test a current RB2610 decision window where RB2610 has Canonical 15m bars from before rank1 activation. `after=None` must include only RB2610 history and never RB2605.

Also cover multi-page physical history and `after` filtering.

- [ ] **Step 2: Run focused RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py -k current_contract_replay
```

- [ ] **Step 3: Implement backward pagination and Live merge**

Use `SeriesPageQuery(SeriesKind.CONTRACT, ..., contract=decision_window.contract, frequency=...)` with page size `2000` and first `before=cutoff + 1 microsecond`. Continue until `after` is reached or physical history is exhausted. Each next cursor must strictly decrease or raise `MARKET_READ_PAGINATION_STALLED`.

Do not add a second storage reader or inspect canonical filesystem paths.

- [ ] **Step 4: Prove reconciliation and duplicate safety**

```text
after == previous processed Bar → only missing/new bars returned
after == cutoff → empty replay allowed; duplicate/stale trigger
after > cutoff → fail closed
Canonical/Live same timestamp + same facts → dedupe
Canonical/Live same timestamp + different facts → MARKET_READ_LIVE_UNAVAILABLE
last non-empty replay Bar must equal cutoff
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

- [ ] **Step 1: Run complete S1 focused set**

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

S1 may be labeled `CODE_COMPLETE/TEST_COMPLETE` only after fresh commands pass. It does not authorize S2 or any external operation.

---

# Task 2 / Packet S2: Alert Runtime, Event Dispatch, Notification, Per-Rule Health

**Branch/worktree:** `feature/subing-ths-s2-alert-runtime` from latest `origin/develop` after S1 integration.

**Deliverable:** 当前单进程 Alert Runtime 安全运行两条 Rule；HTDY 保持 first-seen 语义，SuBing 只在 completed 15m current Bar 上按 S1 kernel 产生 exact Event，并使用同一 observers Topic one-shot 推送。

## S2.1 Extend the Alert registry without changing DB schema

**Files:**
- Modify `services/quant-api/app/alerts/registry.py`
- Modify `services/quant-api/tests/test_alert_registry.py`

- [ ] **Step 1: Write RED registry tests**

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

## S2.2 Add generic evaluator dispatch and stateful SuBing evaluation

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

`SubingThs15mEvaluator` only keeps this transient cursor:

```python
@dataclass(slots=True)
class _SubingCursor:
    contract: str
    last_bar_end: datetime
    state: SubingThs15mState
```

No Redis state, DB state or strategy cache.

- [ ] **Step 1: Write RED tests for HTDY adapter and SuBing behavior**

Prove:

```text
HTDY evaluate_candidates preserves existing first-seen output
SuBing non-15m / non-actual_dominant → input error
first call / no cursor → replay after=None
same contract next call → replay after=cursor.last_bar_end
same contract with missed intermediate bars → step all silently; only final cutoff may emit
contract changes → rebuild from after=None; no old state inheritance
stale/duplicate cutoff <= cursor.last_bar_end → no Candidate; no rewind
warming/invalid final Bar → no Candidate and stable evaluation error
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py -k "subing or evaluate_candidates"
```

- [ ] **Step 3: Implement generic candidate + HTDY adapter**

Keep HTDY-specific helpers if needed by existing tests, but Runtime will use `evaluate_candidates()`.

- [ ] **Step 4: Implement `SubingThs15mEvaluator`**

```text
validate current decision window
cursor missing/contract changed → full same-contract replay from after=None + fresh kernel state
same contract and cutoff newer → replay after cursor cutoff using existing state
cutoff <= cursor cutoff → return ()
step replay bars chronologically
ignore intermediate Candidate results
require final replay Bar == current cutoff
update cursor
return only final result as zero/one candidate
```

If final replay is warming/invalid, preserve enough kernel state for the next Bar but raise/return the fixed unavailable outcome so `last_evaluated_bar_at` does not advance.

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
- Modify `services/quant-api/app/alerts/pushplus.py` only if an audience alias is needed; do not change config keys.
- Modify `services/quant-api/tests/test_alert_notification.py`
- Modify `services/quant-api/tests/test_alert_pushplus.py`
- Modify `services/quant-api/tests/test_alert_notification_config.py` only for non-regression if touched.

- [ ] **Step 1: Write RED policy/formatter tests**

Freeze:

```python
assert dispatcher.supported_rule_codes == (
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
)
```

SuBing buy/sell copy must contain only approved V1 facts and use the existing observers audience backed by `htdy_topic`.

- [ ] **Step 2: Implement `AlertNotificationPolicy`**

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationPolicy:
    rule_code: str
    title: str
    audience: str
    formatter: Callable[[AlertNotificationMessage], str]
```

`AlertNotificationDispatcher.send()` exact-lookups `message.rule_code`; unknown rule raises `ALERT_NOTIFICATION_RULE_INVALID`.

- [ ] **Step 3: Preserve PushPlus transport semantics**

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
```

Commit only the files actually touched.

## S2.4 Replace the single evaluator runtime seam and preserve Event semantics

**Files:**
- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/alerts/composition.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_alert_service.py`

**Constructor:**

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

Fail closed when DB Rule set, registry Rule set, evaluator keys or sender policy keys do not match exactly.

- [ ] **Step 2: Write RED live dispatch tests**

```text
HTDY invokes only HtdyOriginalEvaluator
SuBing invokes only SubingThs15mEvaluator
SuBing ignores non-15m live triggers
SuBing never runs on canonical_updated
Scope disabled/no symbol-frequency → no evaluator call
startup drain emit_events=false → no Event/no send
```

- [ ] **Step 3: Generalize Event persistence by event mode**

```python
if definition.event_mode is AlertEventMode.FIRST_SEEN:
    created = service.create_first_seen_observation_event(request)
elif definition.event_mode is AlertEventMode.EXACT:
    created = service.create_event(request)
else:
    raise RuntimeError("ALERT_RUNTIME_COMPOSITION_INVALID")
```

Do not weaken exact conflict checks.

- [ ] **Step 4: Generalize evaluator lookup and candidate validation**

Validate candidate bar_end/contract/trading_day/result code against the decision window before persistence.

- [ ] **Step 5: Preserve Event-first one-shot failure behavior**

Tests must prove Event survives taxonomy/formatter/transport failures, and repeated identity never sends twice.

- [ ] **Step 6: Run Runtime/Service tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py
```

## S2.5 Upgrade runtime status to schema v6 with bounded per-rule state

**Files:**
- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/services/runtime_health.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_runtime_health.py`

- [ ] **Step 1: Write RED schema tests**

Target:

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

v1-v5 normalize to v6; unknown Rule keys fail closed.

- [ ] **Step 2: Freeze rule evaluation error types**

```text
evaluation_input_invalid
evaluation_warming_up
evaluation_failed
```

No symbol history, stack or raw error text.

- [ ] **Step 3: Update at the correct processing point**

```text
scope skipped → no change
evaluator success/no signal → last_evaluated advances and error clears
Event created → that Rule last_event_at advances
input/warmup/evaluator failure → last_failure/error only; last_evaluated must not advance
notification failures stay in existing global notification fields
```

- [ ] **Step 4: Expose read-only through runtime health**

Do not infer business normality from heartbeat alone.

- [ ] **Step 5: Run tests GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
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

- [ ] **Step 2: Run adjacent HTDY/Market regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_market_read_service.py
```

- [ ] **Step 3: Ruff/Mypy/diff**

Use current `TESTING.md` commands narrowed to touched modules, then `git diff --check origin/develop...HEAD` and `git status --short`.

- [ ] **Step 4: Draft PR + exact-head independent Review + STOP**

S2 does not create/migrate the DB Rule and does not send real notifications.

---

# Task 3 / Packet S3: Generic Alert API + Market Web Review Surface

**Branch/worktree:** `feature/subing-ths-s3-web` from latest `origin/develop` after S2 integration.

**Deliverable:** 现有 `/api/alerts/*` 支持两条 Rule；`/market` 一次读取 current-events 显示最近苏冰预警；`/market/chart` 在 actual_dominant 15m 显示 Event-backed `S↑/S↓` 并支持 deep link 聚焦。Web 不计算正式公式。

## S3.1 Generalize backend Alert DTO and serializer

**Files:**
- Modify `services/quant-api/app/schemas/alerts.py`
- Modify `services/quant-api/app/api/alerts.py`
- Modify `services/quant-api/tests/test_alert_api.py`

- [ ] **Step 1: Write RED mixed-Rule API tests**

```python
AlertRuleCode = Literal[
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
]
```

Prove SuBing `/events`, mixed `/current-events`, mixed product current-events, invalid Rule 404, and unchanged HTDY wire facts.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py
```

- [ ] **Step 3: Replace HTDY-only DTO/serializer with generic exact union**

Do not add `/api/subing/*`. Derive Rule code from DB facts, not `HTDY_ALERT_RULE_CODE`; avoid N+1 Rule lookups.

- [ ] **Step 4: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_api.py
```

## S3.2 Add typed Web Rule/Event presentation

**Files:**
- Modify `apps/quant-web/src/types/market.ts`
- Modify `apps/quant-web/src/api/alerts.ts`
- Modify `apps/quant-web/src/utils/alertRules.ts`
- Modify `apps/quant-web/tests/alerts.test.ts`
- Modify `apps/quant-web/tests/alertRuleOwnership.test.ts`

- [ ] **Step 1: Write RED tests**

Add:

```ts
export const SUBING_THS_ALERT_RULE_CODE = 'subing_ths_alert_15m_v1'
```

Presentation: `苏冰预警`、result noun `预警`、persistent frequencies only `15m`。`AlertEvent = HtdyAlertEvent | SubingThsAlertEvent`。

- [ ] **Step 2: Add `getCurrentAlertEvents()` using existing `/api/alerts/current-events`**

No new endpoint.

- [ ] **Step 3: Run focused unit GREEN and commit**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts \
  tests/alertRuleOwnership.test.ts
```

## S3.3 Render persistent `S↑/S↓` without a new overlay

**Files:**
- Modify `apps/quant-web/src/utils/alertMarkers.ts`
- Modify `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify `apps/quant-web/src/pages/market/chart.vue`
- Modify focused marker/composable tests.

- [ ] **Step 1: Write RED marker tests**

```text
SuBing buy → S↑ / arrowUp / belowBar
SuBing sell → S↓ / arrowDown / aboveBar
Tooltip → 苏冰预警 + MACD 金/死叉 + Close >/< MA21 (SMA21) + contract + time
HTDY remains square first-seen presentation
```

- [ ] **Step 2: Freeze visibility rules**

```text
SuBing markers visible on actual_dominant 15m under overlay none or htdy
HTDY persistent markers visible only under overlay htdy
other identities no marker
```

Do not add a `subing` overlay.

- [ ] **Step 3: Update marker fetch**

At actual_dominant + 15m, fetch exactly the two registered rule ranges for the selected symbol/window; do not issue product-wide calls.

- [ ] **Step 4: Run marker tests GREEN**

Run the exact focused marker/composable tests present after edits plus `alerts.test.ts` and `kline-view-model.test.ts`.

## S3.4 Add `/market` recent SuBing alerts

**Files:**
- Create `apps/quant-web/src/components/market/MarketRecentSubingAlerts.vue`
- Modify `apps/quant-web/src/pages/market/index.vue`
- Add focused unit/E2E tests.

- [ ] **Step 1: Write RED component/page tests**

Display at most 20 SuBing events with Shanghai HH:mm, product name/SYMBOL, direction and 15m. Empty state: `暂无苏冰预警`。

- [ ] **Step 2: Add exactly one global current-events resource**

Include it in existing `Promise.all` refresh; no 60 product requests.

- [ ] **Step 3: Add click navigation**

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

- [ ] **Step 4: Run focused/full unit tests GREEN**

```bash
pnpm --dir apps/quant-web test
```

## S3.5 Consume `focus_bar_end` through existing `KlineChart.revealTime()`

**Files:**
- Modify `apps/quant-web/src/pages/market/chart.vue`
- Modify `apps/quant-web/tests/marketChartEntry.test.ts` or a new exact focused test.
- Modify the relevant Playwright chart interaction spec.

- [ ] **Step 1: Write RED deep-link tests**

```text
focus_bar_end is timezone-aware parseable ISO
only actual_dominant + 15m uses it
after matching replacement load, call revealTime once
missing target bar does not synthesize data
Event.bar_end is never rewritten
invalid focus is ignored safely
```

- [ ] **Step 2: Implement one-shot focus**

Preserve `focus_bar_end` through initial query synchronization until one focus attempt, then remove only that query parameter via `router.replace()`.

- [ ] **Step 3: Run full Web checks**

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

- [ ] **Step 2: Run secret/diff checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 3: Draft PR + exact-head independent Review + STOP**

No production deployment/Runtime mutation.

---

# Task 4 / Packet S4: Migration 0044 + Atomic First Scope Activation Seam

**Branch/worktree:** `feature/subing-ths-s4-migration-scope` from latest `origin/develop` after S3 integration.

**Deliverable:** forward-only 0044 Rule insertion + strict dry-run/one-transaction first activation seam。Implementation/test only；不得执行 production migration/Scope。

## S4.1 Add 0044 as a data-only forward migration

**Files:**
- Create `services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py`
- Create `services/quant-api/tests/alembic/test_subing_ths_alert_migration.py`

- [ ] **Step 1: Write isolated PostgreSQL RED test**

Build exact 0042, run 0043 then 0044, assert:

```text
head=20260902_0044
rules={htdy_original_15m, subing_ths_alert_15m_v1}
HTDY preserved on retained fields
SuBing enabled=false, scope={}
no scope_products/action_id/strategy_payload
legacy SuBing Rule/Event absent
```

- [ ] **Step 2: Run RED only against disposable DB**

Use `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`. If absent, mark blocked; never substitute production DB.

- [ ] **Step 3: Implement exact preflight/postflight**

```python
revision = "20260902_0044"
down_revision = "20260902_0043"
_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"
```

Preflight requires exact 0043 schema and one valid HTDY Rule. Insert only the disabled+empty SuBing Rule. `downgrade()` unsupported.

- [ ] **Step 4: Test unexpected-state fail-closed and 0043-success/0044-failure safety**

No code path may recreate old SuBing or deleted fields. Forward recovery only.

- [ ] **Step 5: Run migration GREEN and commit**

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py
```

## S4.2 Add narrow dry-run/apply scope activation service

**Files:**
- Create `services/quant-api/app/alerts/subing_scope_activation.py`
- Create `services/quant-api/tests/test_subing_scope_activation.py`

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

Require head 0044, exactly two expected Rules, SuBing disabled+empty, normalized unique operational symbols; build `{symbol:["15m"]}` and return stable SHA256/count without mutation.

- [ ] **Step 2: Write RED apply tests**

One transaction must lock/recheck SuBing row, atomically set exact Scope + enabled=true, commit once, reread exact hash/count/enabled, and leave HTDY unchanged. Any mismatch/DB failure rolls back.

- [ ] **Step 3: Implement and run GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_scope_activation.py
```

- [ ] **Step 4: Commit service**

```bash
git add services/quant-api/app/alerts/subing_scope_activation.py \
        services/quant-api/tests/test_subing_scope_activation.py
git commit -m "feat(alerts): add atomic SuBing scope activation"
```

## S4.3 Wire runtime CLI with read-only default

**Files:**
- Modify `services/quant-api/app/guiyi_cli/main.py`
- Modify `services/quant-api/tests/test_alert_cli.py`

- [ ] **Step 1: Write parser/execution RED tests**

```bash
uv run --project services/quant-api guiyi runtime subing-ths-scope
uv run --project services/quant-api guiyi runtime subing-ths-scope --apply
```

Default output shape:

```json
{
  "schema_version": 1,
  "command": "runtime.subing-ths-scope",
  "status": "planned",
  "readonly": true,
  "rule_code": "subing_ths_alert_15m_v1",
  "symbol_count": 60,
  "scope_sha256": "<64 lowercase hex>",
  "enabled": false
}
```

`--apply` returns `published`, `readonly=false`, `enabled=true` only after verified commit. Tests use injected fakes/sessions, never production.

- [ ] **Step 2: Correct CLI readonly classification**

Without `--apply` → readonly true；with `--apply` → false。Parse-error classification must follow requested mutation intent.

- [ ] **Step 3: Inject activation callable for tests and implement command**

Follow existing dependency injection; no untestable global DB mutation.

- [ ] **Step 4: Run CLI GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_cli.py
```

## S4.4 Packet verification and Review gate

- [ ] **Step 1: Run focused activation/Alert tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py \
  services/quant-api/tests/test_alert_service.py
```

- [ ] **Step 2: Run full non-isolated backend**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] **Step 3: Mypy/Ruff/secret/diff**

Use full commands from current `TESTING.md`, then `python3 scripts/engineering/secret_scan.py --json` and `git diff --check origin/develop...HEAD`.

- [ ] **Step 4: Draft PR + exact-head independent Review + STOP**

Never execute real `alembic upgrade` or `guiyi runtime subing-ths-scope --apply` in this Packet.

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

Tests require:

```text
0044 active-schema rule identities are HTDY + subing_ths_alert_15m_v1
SuBing observation-only / 15m actual_dominant / SMA21
no old subing_strategy_v1 implementation restored
Event-first one-shot remains
Range/zero-axis/multi-timeframe are not V1 gates
STATUS only states real release/Runtime/DB evidence
```

- [ ] **Step 2: Run canonical test RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
```

- [ ] **Step 3: Update each canonical according to its responsibility**

`PROJECT_SOURCE.md`：新增最小“苏冰预警” observation 产品。

`DECISIONS.md`：冻结新身份/公式/one-shot observation，同时保留“旧策略整体退役”。

`docs/ARCHITECTURE.md`：现有 Alert Runtime 中增加 SuBing evaluator branch，不新增第二 Runtime。

`AGENTS.md`：0044 后 active Alert combinations 允许 HTDY + new SuBing；真实 Scope/通知/DB/Runtime 仍独立 Gate。

`TESTING.md`：增加 S1-S4 focused commands、0044 isolated test、Web checks。

`STATUS.md` 默认不改；只有新的真实运行事实才另行更新。

- [ ] **Step 4: Run canonical GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
```

## S5.2 Add strict OpenSpec

**File:** `openspec/specs/subing-ths-alert/spec.md`

- [ ] **Step 1: Write the OpenSpec from the approved Spec**

Freeze rule/formula identity, completed actual_dominant 15m, exact CROSS+SMA21, same-contract isolation, no hidden filters, Event identity, one-shot transport, Event-authoritative Web, 0044 disabled+empty scope, atomic activation, external Gates and the Plan safety amendment `G10 before G9`.

- [ ] **Step 2: Validate strictly**

```bash
openspec validate --specs --strict --no-interactive
```

- [ ] **Step 3: Commit OpenSpec**

```bash
git add openspec/specs/subing-ths-alert/spec.md
git commit -m "docs(openspec): specify SuBing THS alert V1"
```

## S5.3 Run fresh full verification at exact head

- [ ] **Step 1: Sync locked dependencies only**

```bash
uv sync --project services/quant-api --locked
```

- [ ] **Step 2: Full non-isolated backend**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] **Step 3: Isolated PostgreSQL suite**

Only with dedicated disposable DB:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://.../isolated_db' \
  PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic
```

If unavailable, S5 is blocked from `TEST_COMPLETE`；do not substitute production DB.

- [ ] **Step 4: Mypy/Ruff**

```bash
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
```

- [ ] **Step 5: Full Web**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 6: Canonical/OpenSpec/security/diff**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 7: Record exact outputs in Draft PR**

Distinguish passed/skipped/deselected/not-run exactly.

## S5.4 Independent exact-head Review

- [ ] **Step 1: Freeze clean exact head**

```bash
git rev-parse HEAD
git status --short
```

- [ ] **Step 2: Request two-axis independent Review**

```text
Standards axis: AGENTS / data facts / security / migration / one-shot / Git boundaries
Spec axis: exact formula / no hidden filters / same-contract causality / Event authority / Web / Gate ordering
```

Critical/High block；contract/causality/migration/notification Medium findings also block until fixed and re-reviewed.

- [ ] **Step 3: Fix findings, rerun affected verification, freeze a new SHA, re-review**

No approval carries across a changed SHA.

## S5.5 RC handoff and STOP

- [ ] **Step 1: Confirm S1-S4 merge ancestry in S5 base `develop`**

- [ ] **Step 2: Draft PR may conclude only**

```text
CODE_COMPLETE
TEST_COMPLETE
independent Review approved
允许进入 release candidate（等待 owner Gate）
```

Never claim `RELEASED` / `RUNTIME_READY` / `BUSINESS_CLOSED`.

- [ ] **Step 3: STOP before release/external operations**

Future separate Gate order, applying the Plan safety amendment:

```text
G5  release main/tag
G6  Runtime maintenance stop
G7  production DB current head → 0044
G8  exact-tag Runtime promotion with SuBing still disabled + empty scope
G10 同花顺兼容性 evidence（read-only comparison; no send）
G9  production Scope activation + Rule enable
G11 自然 15m Event / one-shot transport
G12 用户人工微信送达确认
```

The deliberate `G10 → G9` order is the fail-closed resolution of the approved Spec conflict described above.

---

# Packet Integration Protocol

For each S1–S5 Packet:

1. `git fetch origin`。
2. Confirm latest `origin/develop`, approved Spec, this Plan, current `STATUS.md`, branch/worktree/dirty state and conflicting in-flight work。
3. Use `superpowers:using-git-worktrees` to create a fresh task worktree from latest `origin/develop`。
4. Use TDD: RED → confirm expected failure → minimal GREEN → adjacent regression → refactor → commit。
5. Do not mix another Packet or unrelated refactor。
6. Use `superpowers:verification-before-completion` before completion claims。
7. Create Draft PR to `develop` only。
8. Self-review, then `superpowers:requesting-code-review` for exact-head independent Review。
9. Stop and wait for owner `允许集成 develop`。
10. After approved merge, prove merge reachable from `develop`, then clean merged task worktree/branch。
11. Start the next Packet in a new Codex session from the new latest `develop`。

No automatic `task → develop` merge is authorized by this Plan.

---

# External Operation Boundary

This Plan stops before external execution. Later release/operator work must be a separate Lane 3 task and re-read the then-current `STATUS.md`.

Expected shape:

```text
approved develop RC
→ separate release Gate
→ main + annotated tag + GitHub Release + identity readback
→ separate Runtime maintenance-stop Gate
→ separate production DB Gate: current production head → 0044
→ DB postflight/readback
→ separate exact-tag Runtime promotion Gate, SuBing remains disabled+empty
→ health/smoke
→ separately authorized read-only 同花顺 compatibility evidence
→ only after compatibility passes: separate Scope activation Gate using `guiyi runtime subing-ths-scope --apply`
→ natural completed 15m observation
→ Event + one-shot transport evidence
→ user confirms actual WeChat delivery
```

The exact release version is **not preassigned by this Plan**. It must be selected in the future release task from then-current `main`/Release facts；this is an explicit decision, not a placeholder.

---

# Implementation Plan Self-Review

The Plan was checked against all 26 Spec sections. Findings fixed before submission:

1. **Sliding 64-Bar EMA replay would violate prefix invariance.** Replaced with a tiny in-memory cursor plus full same-contract rebuild on first use/rollover and `after=cursor` reconciliation thereafter.
2. **Downtime reconciliation could accidentally backfill signals.** The evaluator steps intermediate Bars for state only; only the current trigger cutoff may return a Candidate.
3. **HTDY and SuBing need different persistence semantics.** Added `event_mode`: HTDY first-seen immutable, SuBing exact facts.
4. **Missing evaluator/formatter could silently fall back to HTDY.** Startup composition requires exact registry/evaluator/policy key equality.
5. **Private PushPlus config was at risk of expanding.** V1 keeps the existing observers Topic and current config keys.
6. **Per-rule health could regrow into a ledger.** Kept exactly four bounded fields per fixed Rule and one existing Redis status key.
7. **Deep link could create a second chart navigation system.** Reuses existing `KlineChart.revealTime()` and formal Event `bar_end`.
8. **SuBing marker could be tied to an unnecessary new Overlay.** No new overlay；Event marker is visible on actual_dominant 15m while HTDY overlay behavior remains unchanged.
9. **0044 could freeze today’s 60 products.** Migration inserts disabled+empty Rule only；activation reads execution-time operational universe.
10. **First activation could leave partial Scope.** Added one-transaction dry-run/apply seam with stable count/hash readback.
11. **Canonical could claim the product active before code exists.** Canonical sync is S5 after S1-S4 are integrated.
12. **Current v1.9.12/v1.9.11/0042 production facts could be overwritten by implementation status.** STATUS remains evidence-only and is not automatically updated.
13. **Release version was unnecessarily guessable.** Future release chooses the version from then-current facts；no fixed version in this Plan.
14. **API/Web/formatter could become second formula authorities.** Only `SubingThs15mKernel` decides Candidate；other layers consume Event direction.
15. **Old strategy paths could re-enter through convenience reuse.** No planned file recreates Daily Watch/Factor/Lifecycle/Action/Episode/Position/Strategy Runtime or old columns.
16. **Approved Spec had contradictory compatibility/activation Gate ordering.** Explicitly resolved fail-closed as `G10 compatibility evidence → G9 Scope activation + enable`; Plan approval is required before implementation.
17. **S4 test-file choice was ambiguous.** Fixed the plan to always create `services/quant-api/tests/test_subing_scope_activation.py`.
18. **A sample SMA test contained dead illustrative syntax.** Replaced with the exact committed assertion `3.666667`.

Placeholder scan: no `TBD`, `TODO`, unresolved product choice, “implement later”, or “similar to Task N” instruction remains intentionally in this Plan.

Interface check: S2 consumes only S1 public interfaces；S3 consumes S2 registry/Event wire；S4 assumes S2/S3 code plus 0043 lineage；S5 synchronizes canonical only after S1-S4 integration。

---

# Final Gate For This Plan

This document is Implementation Plan only. User approval authorizes starting **S1 only** in a new Lane 3 implementation session.

Plan approval does not authorize:

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