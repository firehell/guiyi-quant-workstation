# 苏冰同花顺 15m 预警 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to execute this plan task-by-task. Every behavior change follows RED → GREEN → REFACTOR, and every completion claim requires fresh verification.

**Goal:** 在不恢复任何旧苏冰策略域的前提下，实现 `subing_ths_alert_15m_v1`：对 operational universe 的 completed `actual_dominant + 15m` 按同花顺 MACD CROSS + SMA21 公式产生不可变 AlertEvent、one-shot PushPlus，并在 Market Web 显示最近预警和 `S↑/S↓` marker，最终由用户人工判断是否交易。

**Architecture:** 公式 authority 放在纯 Quant Core `SubingThs15mKernel`。Alert Runtime 仍为单进程，但由当前单 HTDY evaluator 收敛为精确 `rule_code → evaluator → event mode → notification policy`。SuBing evaluator 只维护最小的每品种 MACD/SMA 递归 cursor，并通过 `MarketReadService` 的 typed physical-contract replay seam 在首次触发、重启、漏中间 Bar 或主力换月时因果重建。API、notification formatter 和 Web 只消费 AlertEvent，不复制正式 BUY/SELL 公式。

**Tech Stack:** Python 3.12、SQLAlchemy/Alembic、PostgreSQL、Redis、FastAPI/Pydantic、Quant Core dataclass kernels、Vue 3 + TypeScript + Naive UI + Lightweight Charts、Node test runner、Playwright。

**Spec:** `docs/tasks/2026-09-02-subing-ths-alert-15m-v1-spec.md`

**Issue:** #307

**Approved Spec merge:** PR #308

**Planning baseline:** `develop@a4737658917406ef9d36b4599e7971d41f3a23d0`

**Plan status:** `PLAN_READY_FOR_USER_REVIEW`

---

## 1. Global Constraints

- 正式身份固定：`rule_code=subing_ths_alert_15m_v1`、`formula_version=subing_ths_15m_v1`、`kind=indicator_observation`、`series_kind=actual_dominant`、`frequency=15m`、`completed_only=true`、`auto_order=false`。
- 唯一 Candidate 公式固定：

```text
DIFF = EMA(CLOSE, 12) - EMA(CLOSE, 26)
DEA  = EMA(DIFF, 9)
MACD = 2 * (DIFF - DEA)
MA21 = SMA(CLOSE, 21)

BUY  = previous_DIF <= previous_DEA
       AND current_DIF > current_DEA
       AND CLOSE > MA21

SELL = previous_DIF >= previous_DEA
       AND current_DIF < current_DEA
       AND CLOSE < MA21
```

- `MA21` 必须是 SMA21，不是 EMA21。
- 工程参数固定：`ema_seed_policy=sma_window`、`histogram_scale=2`、`round_digits=6`。正式 Candidate 比较使用 Quant Core 对每根 Bar 输出的六位确定性 DIF/DEA/MA21 projection；隐藏递归状态只用于下一步计算。
- V1 不允许零轴、Range、量能/OI、ATR、斜率、5m/30m/60m/D1、Daily Watch、评分、胜率或其它隐藏过滤。
- 不恢复 `subing_strategy_v1`、旧 `subing_watch_15m_v1`、Strategy Runtime、Action/Episode/Position、`scope_products`、`action_id`、`strategy_payload` 或任何旧 cache/API/CLI/Web。
- 不新增第二 Alert 进程、scheduler、queue、outbox、retry、replay、backfill、fallback 或订单路径。
- 数据必须走 `MarketDataService` / `MarketReadService` / `MainContractMap rank1`；不得 glob、自判主力、跨频 fallback 或跨物理合约继承递归状态。
- Event 必须先 commit，随后 transport 最多尝试一次；provider accepted 不等于微信实际送达。
- 0044 只插入 disabled + empty-scope 新 Rule；migration 不硬编码“当前 60 个品种”。
- 当前 production 仍是 Alembic `20260826_0042`，Rule 为 `htdy_original_15m + subing_strategy_v1`。最新 Release 为 v1.9.12；当前 v1.9.12 API/Web/Live 已加载 exact tag，但 Alert 因公开回退码 `CLI_INTERNAL_ERROR` 仍停在 `spawn_scheduled` 且没有建立新 heartbeat。该 Runtime 故障是独立生产事实，本 Program 不得把源码开发当作隐式生产修复，也不得自行触发重启、rollback 或 migration。
- 每个 Packet = 一个新 Codex 会话 = 一个从执行时最新 `origin/develop` 创建的 task branch/worktree = 一个 Draft PR = 一个 exact-head independent Review = 一个 owner `允许集成 develop` Gate。
- Packet 顺序固定 `S1 → S2 → S3 → S4 → S5`。前一个 Packet 未合入 `develop`，不得开始后一个。
- 实现阶段不得触碰 `main`、tag、GitHub Release、production PostgreSQL/Redis/Scope、Git-external notification config、真实 PushPlus 或 Runtime promotion。

### 1.1 Normative safety amendment: G10 must precede G9

批准 Spec 存在一个必须 fail-closed 处理的 Gate 顺序冲突：

- Spec §20 明确规定：同花顺兼容性 evidence 未通过，不得启用真实 SuBing Rule；
- Spec §22 的编号列表却把 `G9 production Scope activation + Rule enable` 排在 `G10 同花顺兼容性 evidence` 之前。

本 Plan 采用更严格且与 §20 直接安全要求一致的执行顺序：

```text
0044 DB + exact-tag Runtime 就绪
→ SuBing Rule 仍 disabled + empty scope
→ G10 同花顺兼容性 evidence（只读、不发消息）
→ compatibility 通过
→ G9 Scope activation + Rule enable
→ G11 自然 15m Event / one-shot transport
→ G12 用户人工微信送达确认
```

Gate 名称沿用批准 Spec，只调整执行顺序。批准本 Plan 即表示批准这一 fail-closed 修正；若不批准该修正，必须先修订 Spec/Plan，不能进入 S1。

---

## 2. Current Repository Facts Driving The Plan

执行者开工前必须重新读回当前代码；以下是本 Plan 成稿时的真实基线：

1. `services/quant-api/app/alerts/runtime.py` 构造参数仍是单个 `htdy_evaluator`，DB Rule 循环会复用同一个 evaluator；新增第二 Rule 前必须消除此耦合。
2. `services/quant-api/app/alerts/notification.py` 的 dispatcher 标题、formatter 和 audience 仍写死 HTDY；新增第二 Rule 前必须改为 rule policy。
3. `services/quant-api/app/schemas/alerts.py` 与 `app/api/alerts.py` 仍是 HTDY-only wire contract，包含 `Literal["htdy_original_15m"]` 和 hard-coded serializer。
4. `apps/quant-web/src/types/market.ts`、`utils/alertRules.ts`、`utils/alertMarkers.ts` 仍把持久 AlertEvent 定义成 HTDY-only；当前 `alertMarkersForOverlay()` 在 `overlay=none` 时会隐藏全部 persistent marker。
5. `services/quant-api/alembic/versions/20260902_0043_retire_subing.py` 已存在，forward-only 删除旧策略 Rule/Event、`scope_products`、`action_id`、`strategy_payload`；production 尚未执行。
6. `alert:runtime-status` 当前 schema v5 只有全局处理/通知字段；本 Plan 只升级到 schema v6 的 bounded per-rule projection，不恢复 Boundary Ledger。
7. `KlineChart.vue` 已公开 `revealTime(iso)`；S3 deep link 必须复用它，不建立第二套图表定位系统。
8. Quant Core 已有通用 EMA/MACD incremental primitive，但没有通用 SMA state/step。
9. `MarketReadService.bars_until()` 已能对当前 `actual_dominant` trigger 构造 Canonical + Live cutoff window，并带 `bar_contracts`；但没有“当前物理合约从上市历史到 cutoff”的 typed replay seam。

若执行时 active canonical、批准 Spec、实际代码与本基线出现实质冲突，必须停止并报告，不得按旧行号机械修改。

---

## 3. Packet Map

| Packet | Branch | 目标 | 不包含 |
|---|---|---|---|
| S1 | `feature/subing-ths-s1-kernel` | SMA21 + `SubingThs15mKernel` + current-contract replay | Rule/Event/Push/Web/DB mutation |
| S2 | `feature/subing-ths-s2-alert-runtime` | evaluator dispatch + exact Event + notification policy + rule health | 0044 migration/Web/prod send |
| S3 | `feature/subing-ths-s3-web` | generic Alert API + recent alerts + S markers + deep link | formula duplication/migration |
| S4 | `feature/subing-ths-s4-migration-scope` | 0044 + dry-run/atomic Scope activation seam | production migration/apply |
| S5 | `docs/subing-ths-s5-canonical-rc` | canonical/OpenSpec/full verification/independent Review | release/main/Runtime/prod DB/real send |

---

# 4. Packet S1 — Formula Kernel + Same-Contract Replay

**Branch/worktree:** execution-time latest `origin/develop` → `feature/subing-ths-s1-kernel` in a new task worktree.

**Deliverable:** 一个无 I/O 的精确 `SubingThs15mKernel`，以及一个只读 typed physical-contract replay seam。S1 不注册 Alert Rule，不写 DB，不接 Runtime/Push/Web。

## 4.1 Add a generic incremental SMA primitive

**Files:**

- Modify `packages/quant-core/guiyi_quant/indicators/models.py`
- Create `packages/quant-core/guiyi_quant/indicators/sma.py`
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Create `services/quant-api/tests/test_subing_ths_kernel.py`

- [ ] **Step 1: Write failing SMA tests**

```python
from guiyi_quant.indicators import initial_sma_state, step_sma


def test_sma_warms_then_rolls_exactly() -> None:
    state = initial_sma_state(3, round_digits=6)
    for value in (1.0, 2.0):
        state, point = step_sma(state, value, bar_end=None)
        assert point.ready is False
        assert point.valid is True
        assert point.value is None
        assert point.reason == "warming_up"

    state, point = step_sma(state, 3.0, bar_end=None)
    assert point.ready is True
    assert point.valid is True
    assert point.value == 2.0
    assert point.reason is None

    state, point = step_sma(state, 6.0, bar_end=None)
    assert point.value == 3.666667


def test_sma_invalid_input_breaks_continuity() -> None:
    state = initial_sma_state(3)
    for value in (1.0, 2.0, 3.0):
        state, _ = step_sma(state, value, bar_end=None)

    state, invalid = step_sma(state, None, bar_end=None)
    assert invalid.ready is False
    assert invalid.valid is False
    assert invalid.reason == "input_invalid"

    state, next_point = step_sma(state, 4.0, bar_end=None)
    assert next_point.ready is False
    assert next_point.valid is True
    assert next_point.reason == "warming_up"
```

- [ ] **Step 2: Run focused test and confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k sma
```

Expected RED reason: import/definition failure for `initial_sma_state` or `step_sma`.

- [ ] **Step 3: Implement `SmaState` and the complete minimal primitive**

Add to `models.py`:

```python
@dataclass(frozen=True, slots=True)
class SmaState:
    period: int
    values: tuple[float, ...]
    round_digits: int = 6
```

Create `sma.py` with behavior equivalent to:

```python
from __future__ import annotations

import math

from .models import IndicatorPoint, SmaState


def initial_sma_state(period: int, *, round_digits: int = 6) -> SmaState:
    if period <= 0:
        raise ValueError("SMA period must be positive")
    if round_digits < 0:
        raise ValueError("round_digits must be non-negative")
    return SmaState(period=period, values=(), round_digits=round_digits)


def step_sma(
    state: SmaState,
    value: float | int | None,
    *,
    bar_end: str | None,
) -> tuple[SmaState, IndicatorPoint]:
    if value is None:
        number = None
    else:
        candidate = float(value)
        number = candidate if math.isfinite(candidate) else None

    if number is None:
        return (
            SmaState(period=state.period, values=(), round_digits=state.round_digits),
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=False,
                valid=False,
                reason="input_invalid",
            ),
        )

    values = (*state.values, number)[-state.period :]
    next_state = SmaState(
        period=state.period,
        values=values,
        round_digits=state.round_digits,
    )
    if len(values) < state.period:
        return (
            next_state,
            IndicatorPoint(
                bar_end=bar_end,
                value=None,
                ready=False,
                valid=True,
                reason="warming_up",
            ),
        )
    return (
        next_state,
        IndicatorPoint(
            bar_end=bar_end,
            value=round(sum(values) / state.period, state.round_digits),
            ready=True,
            valid=True,
        ),
    )
```

Do not add pandas/numpy or an unbounded history.

- [ ] **Step 4: Export the primitive and make focused tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k sma
```

- [ ] **Step 5: Commit**

```bash
git add packages/quant-core/guiyi_quant/indicators/models.py \
        packages/quant-core/guiyi_quant/indicators/sma.py \
        packages/quant-core/guiyi_quant/indicators/__init__.py \
        services/quant-api/tests/test_subing_ths_kernel.py
git commit -m "feat(indicators): add incremental SMA primitive"
```

## 4.2 Implement `SubingThs15mKernel` as the only Candidate authority

**Files:**

- Create `packages/quant-core/guiyi_quant/indicators/subing_ths.py`
- Modify `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify `services/quant-api/tests/test_subing_ths_kernel.py`
- Create `tests/fixtures/subing_ths_15m_v1_golden.json`

- [ ] **Step 1: Write RED tests for identity and formula edges**

Committed tests must construct state only through ordinary `initial_state()` + `step()` calls. Freeze these constants:

```python
kernel = SubingThs15mKernel()
assert kernel.formula_version == "subing_ths_15m_v1"
assert kernel.fast == 12
assert kernel.slow == 26
assert kernel.signal == 9
assert kernel.sma_period == 21
assert kernel.ema_seed_policy == "sma_window"
assert kernel.histogram_scale == 2
assert kernel.round_digits == 6
```

Tests must cover:

```text
previous DIF == previous DEA then current DIF > DEA can be golden CROSS
previous DIF == previous DEA then current DIF < DEA can be dead CROSS
current DIF == DEA is not a completed CROSS
close == SMA21 never triggers
buy and sell can never coexist on one Bar
invalid input breaks CROSS continuity
```

- [ ] **Step 2: Confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py -k "formula or cross or equality"
```

Expected RED reason: `SubingThs15mKernel` does not exist.

- [ ] **Step 3: Add frozen state/result contracts**

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

The `tuple[Literal[...], ...]` syntax above is a Python variadic tuple type and is not an unresolved implementation marker.

`SubingThs15mKernel` constants are exactly the values in Step 1. `initial_state()` creates MACD/SMA state only; symbol、contract、frequency and Runtime identity do not enter Quant Core state.

- [ ] **Step 4: Implement exact step semantics**

The code path must be equivalent to this sequence:

```text
macd_state, (dif_point, dea_point, histogram_point) = step_macd(current state, close)
sma_state, ma21_point = step_sma(current state, close)

if any required current point is invalid:
    emit valid=false, no result code
    set previous_dif=None and previous_dea=None
elif MACD or SMA21 is not ready:
    emit ready=false, no result code
else:
    use dif_point.value, dea_point.value, ma21_point.value and rounded close
    golden = previous_dif <= previous_dea and dif > dea and close > ma21
    dead   = previous_dif >= previous_dea and dif < dea and close < ma21
    emit only buy, only sell, or no result
    update previous_dif/dea to current projected values
```

`histogram_point` is returned for observation/debug facts only and must not participate in Candidate logic. No zero-axis、Range、volume、OI、ATR or slope access is permitted in this file.

- [ ] **Step 5: Add a frozen golden fixture and parity tests**

Fixture top-level schema:

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
  "bars": []
}
```

The committed fixture must populate `bars` with a deterministic synthetic sequence containing warm-up、equality/no-cross、at least one buy、at least one sell and a future tail. Each Bar record freezes `bar_end`、close、DIF、DEA、MA21 and result codes. Expected fixture values must be computed independently during test authoring and committed as literals; the test must never call the production kernel to create its own expected values.

Required parity assertions:

```python
assert incremental_results == golden_results
assert run(prefix) == run(prefix + future_tail)[: len(prefix)]
assert run(all_bars) == run(all_bars)
```

- [ ] **Step 6: Run full kernel tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py
```

- [ ] **Step 7: Commit**

```bash
git add packages/quant-core/guiyi_quant/indicators/subing_ths.py \
        packages/quant-core/guiyi_quant/indicators/__init__.py \
        services/quant-api/tests/test_subing_ths_kernel.py \
        tests/fixtures/subing_ths_15m_v1_golden.json
git commit -m "feat(indicators): add SuBing THS 15m kernel"
```

## 4.3 Add a typed physical-contract replay seam

**Files:**

- Modify `services/quant-api/app/market_data/market_read_service.py`
- Modify `services/quant-api/tests/test_market_read_service.py`

**New value object:**

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
```

**New method signature:**

```text
MarketReadService.current_contract_replay_window(
    decision_window: MarketReadWindow,
    *,
    after: datetime | None,
) -> CurrentContractReplayWindow
```

- `decision_window` must already be a valid current `actual_dominant` intraday window ending at the trigger Bar。
- `after=None` means replay all available current physical-contract history through `cutoff`; used for first evaluation after process start or contract rollover。
- `after=<previous cursor timestamp>` means return same-contract bars satisfying `bar_end > after` and `bar_end <= cutoff`; this advances indicator state across one or more missed intermediate Bar without producing historical Events。
- Historical pages use `SeriesKind.CONTRACT` + `decision_window.contract` through existing `history_page()`/MarketDataService and paginate backward until `after` is reached or physical history is exhausted。
- Current trading-day Live bars are merged from the existing Live store and deduped exactly；same timestamp with unequal facts is an error。
- Returned non-empty bars are strictly increasing and the last Bar must equal `cutoff`。

- [ ] **Step 1: Write RED tests for pre-dominant warm-up and rollover isolation**

Create fixture conditions where current rank1 is RB2610, RB2610 has Canonical 15m history from before rank1 activation, and previous rank1 was RB2605. Assert:

```text
after=None includes available RB2610 pre-dominant history
no RB2605 Bar is returned
last replay Bar equals trigger cutoff
every returned physical owner is RB2610 by construction
```

Also cover multi-page physical history and `after` filtering.

- [ ] **Step 2: Confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py -k current_contract_replay
```

Expected RED reason: `current_contract_replay_window` is absent.

- [ ] **Step 3: Implement backward pagination and Live merge**

Use `SeriesPageQuery` with:

```text
series_kind=CONTRACT
symbol=decision_window.symbol
contract=decision_window.contract
frequency=BarFrequency(decision_window.frequency)
limit=2000
first before=cutoff + 1 microsecond
```

Continue paging only while earlier data are still required. Each next `before` cursor must be strictly earlier than the previous cursor; otherwise raise `MARKET_READ_PAGINATION_STALLED`. Do not inspect filesystem paths or create a second storage reader.

- [ ] **Step 4: Prove reconciliation and duplicate safety**

Tests:

```text
after == previous processed Bar → only newer same-contract bars returned
after == cutoff → empty replay allowed and treated as duplicate/stale input
after > cutoff → fail closed
naive after timestamp → fail closed
Canonical/Live same timestamp + same facts → dedupe
Canonical/Live same timestamp + different facts → MARKET_READ_LIVE_UNAVAILABLE
non-empty replay missing cutoff → fail closed
```

- [ ] **Step 5: Run MarketRead tests GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/market_data/market_read_service.py \
        services/quant-api/tests/test_market_read_service.py
git commit -m "feat(market): add current-contract replay window"
```

## 4.4 S1 verification and Gate

- [ ] Run focused S1 regression:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- [ ] Run Ruff/Mypy on touched source:

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

- [ ] Verify hygiene:

```bash
git diff --check origin/develop...HEAD
git status --short
```

- [ ] Create Draft PR to `develop`, run exact-head independent Review, then STOP. S1 may be labeled `CODE_COMPLETE/TEST_COMPLETE` only after fresh commands pass. It does not authorize S2 or any external operation。

---

# 5. Packet S2 — Alert Runtime, Event Dispatch, Notification, Per-Rule Health

**Branch/worktree:** after S1 is merged, latest `origin/develop` → `feature/subing-ths-s2-alert-runtime` in a new task worktree.

**Deliverable:** 当前单进程 Alert Runtime 可以安全运行两条 Rule；HTDY 保持现有 first-seen 语义，SuBing 只在 completed 15m current Bar 上按 S1 kernel 产生 exact Event，并使用同一 observers Topic one-shot 推送。

## 5.1 Extend Alert registry without changing DB schema

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

- [ ] **Step 2: Confirm RED, then implement**

Add:

```python
class AlertEventMode(StrEnum):
    FIRST_SEEN = "first_seen"
    EXACT = "exact"

SUBING_THS_ALERT_RULE_CODE: Final[Literal["subing_ths_alert_15m_v1"]] = (
    "subing_ths_alert_15m_v1"
)
```

Extend `AlertRuleDefinition` with `event_mode: AlertEventMode` and define SuBing as `indicator_observation`, `input_frequencies=("15m",)`, `series_kind="actual_dominant"`, `event_mode=EXACT`。

- [ ] **Step 3: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py

git add services/quant-api/app/alerts/registry.py \
        services/quant-api/tests/test_alert_registry.py
git commit -m "feat(alerts): register SuBing THS observation rule"
```

## 5.2 Add generic evaluator dispatch and stateful SuBing evaluation

**Files:**

- Modify `services/quant-api/app/alerts/evaluators.py`
- Modify `services/quant-api/tests/test_alert_evaluator.py`

**New candidate contract:**

```python
@dataclass(frozen=True, slots=True)
class AlertObservationCandidate:
    bar_end: datetime
    trading_day: date
    contract: str
    observation_types: tuple[Literal["buy", "sell"], ...]
```

**Evaluator call contract:**

```text
evaluate_candidates(
    market_read: MarketReadService,
    window: MarketReadWindow,
) -> tuple[AlertObservationCandidate, ...]
```

`SubingThs15mEvaluator` keeps only this transient cursor per symbol:

```python
@dataclass(slots=True)
class _SubingCursor:
    contract: str
    last_bar_end: datetime
    state: SubingThs15mState
```

No Redis state、DB state or strategy cache.

- [ ] **Step 1: Write RED tests**

Prove:

```text
HTDY evaluate_candidates preserves existing first-seen output exactly
SuBing non-15m or non-actual_dominant → stable input error
first call/no cursor → replay after=None
same-contract next call → replay after=cursor.last_bar_end
same-contract missed intermediate bars → step all silently; only final cutoff may emit
contract changes → fresh kernel + replay after=None; no old state inheritance
cutoff <= cursor.last_bar_end → no Candidate and no state rewind
warming final Bar → no Candidate, cursor state preserved for next Bar, fixed warming outcome
invalid final Bar → no Candidate, CROSS continuity broken, fixed input outcome
```

- [ ] **Step 2: Confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py -k "subing or evaluate_candidates"
```

- [ ] **Step 3: Make evaluation failures explicit**

Extend the existing `AlertEvaluationError` to carry one stable public code. Preserve current HTDY codes; add only these SuBing-facing codes as needed:

```text
ALERT_EVALUATION_INPUT_INVALID
ALERT_EVALUATION_WARMING_UP
ALERT_EVALUATION_FAILED
```

Do not store raw exceptions or provider details in Runtime status.

- [ ] **Step 4: Implement HTDY adapter and `SubingThs15mEvaluator`**

SuBing algorithm:

```text
validate actual_dominant + 15m + cutoff/current-contract identity
lookup cursor by symbol
if cursor missing or contract changed:
    state = kernel.initial_state()
    replay after=None
elif cutoff <= cursor.last_bar_end:
    return no candidate
else:
    state = cursor.state
    replay after=cursor.last_bar_end

step replay bars chronologically
ignore any intermediate replay Candidate
require the final replay Bar to equal current cutoff
update cursor to final state/cutoff
only the final cutoff result may become zero or one AlertObservationCandidate
```

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py

git add services/quant-api/app/alerts/evaluators.py \
        services/quant-api/tests/test_alert_evaluator.py
git commit -m "feat(alerts): add SuBing THS evaluator"
```

## 5.3 Generalize notification policy without changing private config

**Files:**

- Modify `services/quant-api/app/alerts/notification.py`
- Modify `services/quant-api/app/alerts/notification_composition.py`
- Modify `services/quant-api/app/alerts/pushplus.py` only if an audience constant name must be generalized; config keys must remain unchanged。
- Modify `services/quant-api/tests/test_alert_notification.py`
- Modify `services/quant-api/tests/test_alert_pushplus.py`
- Modify `services/quant-api/tests/test_alert_notification_config.py` only if touched for non-regression。

- [ ] **Step 1: Write RED policy/formatter tests**

Dispatcher must expose exactly these supported policy keys:

```python
assert dispatcher.supported_rule_codes == (
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
)
```

SuBing buy copy contains:

```text
【苏冰预警】<SYMBOL> <产品名>
15m 多头预警
触发：
MACD 金叉
收盘价位于 MA21 上方
当前主力：<contract>
信号K线：<Asia/Shanghai timestamp>
请打开归一量化图表复核。
研究观察，非交易指令
```

Sell is symmetrical with `空头预警 / MACD 死叉 / MA21 下方`。Formatter 不读取 DIFF/DEA 数值，不重新计算公式。

- [ ] **Step 2: Implement exact policy lookup**

Add:

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationPolicy:
    rule_code: str
    title: str
    audience: str
    formatter: Callable[[AlertNotificationMessage], str]
```

`AlertNotificationDispatcher.send()` exact-lookups `message.rule_code`; missing policy raises `ALERT_NOTIFICATION_RULE_INVALID` rather than falling back to HTDY。

- [ ] **Step 3: Preserve existing transport mapping**

Both HTDY and SuBing V1 use the existing observers audience, which `PushPlusTransport` maps to the existing `htdy_topic` private config value. Owner canary continues topic-free. Do not add `subing_topic`、new token、member table or retry。

- [ ] **Step 4: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_pushplus.py \
  services/quant-api/tests/test_alert_notification_config.py
```

Stage and commit only files actually modified in this step.

## 5.4 Replace single-evaluator Runtime seam and preserve Event modes

**Files:**

- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/alerts/composition.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_alert_service.py`

**Target constructor parameters relevant to dispatch:**

```text
session_factory: AlertSessionFactory
market_read_factory: AlertMarketReadFactory
evaluators: Mapping[str, AlertRuleEvaluator]
sender: AlertNotificationSender
operational_products: tuple[str, ...]
taxonomy: Mapping[str, ProductTaxonomyEntry]
message_source: AlertMessageSource | None
heartbeat_store: AlertHeartbeatStore | None
runtime_status_store: AlertRuntimeStatusStore | None
clock: Callable[[], datetime] | None
stop_requested: Callable[[], bool] | None
```

- [ ] **Step 1: Write RED startup-composition tests**

Startup fails closed when any of these exact sets differ:

```text
DB Rule codes
registry Rule codes
evaluator map keys
notification dispatcher policy keys
```

Unknown DB Rule、missing evaluator、missing formatter are all `ALERT_RUNTIME_COMPOSITION_INVALID`。

- [ ] **Step 2: Write RED live dispatch tests**

```text
HTDY Rule invokes only HtdyOriginalEvaluator
SuBing Rule invokes only SubingThs15mEvaluator
SuBing ignores non-15m live triggers
SuBing is never evaluated on canonical_updated
Rule/frequency outside Scope → evaluator not called
startup drain with emit_events=false → no Event and no sender call
```

- [ ] **Step 3: Generalize Event persistence by `AlertEventMode`**

Runtime persistence branch is exactly:

```python
if definition.event_mode is AlertEventMode.FIRST_SEEN:
    created = service.create_first_seen_observation_event(request)
elif definition.event_mode is AlertEventMode.EXACT:
    created = service.create_event(request)
else:
    raise RuntimeError("ALERT_RUNTIME_COMPOSITION_INVALID")
```

Do not weaken `AlertService.create_event()` exact conflict checks。

- [ ] **Step 4: Validate candidate identity before persistence**

Require exact match with the decision window for symbol、frequency、bar_end、trading_day and contract; result codes must be one direction for SuBing. Wrong candidate facts fail closed before Event creation。

- [ ] **Step 5: Prove Event-first one-shot behavior**

Tests:

```text
Event commit + taxonomy missing → Event remains, no transport
Event commit + formatter failure → Event remains, failure recorded, no retry
Event commit + transport failure → Event remains, one attempt only
same Event identity arrives again → no second transport
HTDY first-seen immutability remains unchanged
```

- [ ] **Step 6: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py
```

## 5.5 Upgrade runtime status to schema v6 with bounded per-rule state

**Files:**

- Modify `services/quant-api/app/alerts/runtime.py`
- Modify `services/quant-api/app/services/runtime_health.py`
- Modify `services/quant-api/tests/test_alert_runtime.py`
- Modify `services/quant-api/tests/test_runtime_health.py`

- [ ] **Step 1: Write RED schema tests**

Schema v6 must retain every existing v5 field:

```text
schema_version
last_processed_bar_at
last_processing_success_at
last_processing_failure_at
processing_error_type
last_event_at
last_transport_attempt_at
last_provider_accepted_at
last_notification_failure_at
notification_acknowledged_at
notification_error_type
consecutive_notification_failures
```

and add exactly:

```python
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
}
```

v1-v5 reads normalize to v6 with fixed empty rule entries. Unknown rule-status keys fail closed。

- [ ] **Step 2: Freeze public rule error types**

```text
evaluation_input_invalid
evaluation_warming_up
evaluation_failed
```

No per-symbol history、stack trace or raw exception text。

- [ ] **Step 3: Update status at the correct point**

```text
scope skipped → no per-rule change
evaluator succeeds, including no signal → last_evaluated_bar_at advances and prior error clears
new Event → that Rule last_event_at advances
input/warmup/evaluation failure → last_failure_at + fixed error_type; last_evaluated_bar_at does not advance
notification failure remains in existing global notification fields
```

- [ ] **Step 4: Expose v6 through runtime health read model**

Health may project the validated `rule_status`, but a fresh heartbeat alone must not be labeled as proof that SuBing processed the latest 15m Bar。

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

## 5.6 S2 verification and Gate

- [ ] Run complete Alert focused set:

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

- [ ] Run adjacent HTDY/Market regression:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_market_read_service.py
```

- [ ] Run Ruff/Mypy on touched modules, then:

```bash
git diff --check origin/develop...HEAD
git status --short
```

- [ ] Create Draft PR, run exact-head independent Review, STOP. S2 does not create/migrate the new DB Rule and does not send real notifications。

---

# 6. Packet S3 — Generic Alert API + Market Web Review Surface

**Branch/worktree:** after S2 is merged, latest `origin/develop` → `feature/subing-ths-s3-web`.

**Deliverable:** 现有 `/api/alerts/*` 支持两条 Rule；`/market` 一次读取 current-events 显示最近苏冰预警；`/market/chart` 在 `actual_dominant + 15m` 显示 Event-backed `S↑/S↓` 并支持 deep link 聚焦。Web 不计算正式公式。

## 6.1 Generalize backend Alert DTO and serializer

**Files:**

- Modify `services/quant-api/app/schemas/alerts.py`
- Modify `services/quant-api/app/api/alerts.py`
- Modify `services/quant-api/tests/test_alert_api.py`

- [ ] **Step 1: Write RED mixed-Rule API tests**

Wire Rule union is exactly:

```python
AlertRuleCode = Literal[
    "htdy_original_15m",
    "subing_ths_alert_15m_v1",
]
```

Tests prove:

```text
/events?rule_code=subing_ths_alert_15m_v1 returns actual SuBing rule_code
/current-events can contain HTDY + SuBing in deterministic detected_at/bar_end/id order
/products/{symbol}/current-events can contain both
unknown Rule remains 404
existing HTDY fields and values remain unchanged
```

- [ ] **Step 2: Confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py
```

- [ ] **Step 3: Replace HTDY-only DTO names/serializer with generic exact union**

Do not add `/api/subing/*`. Serializer must derive `rule_code` from actual Rule facts, never hard-code `HTDY_ALERT_RULE_CODE`. Avoid N+1 Rule reads by selecting/joining the Rule code with Events or constructing one `rule_id → rule_code` map per response。

- [ ] **Step 4: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py
```

## 6.2 Add typed Web Rule/Event presentation

**Files:**

- Modify `apps/quant-web/src/types/market.ts`
- Modify `apps/quant-web/src/api/alerts.ts`
- Modify `apps/quant-web/src/utils/alertRules.ts`
- Modify `apps/quant-web/tests/alerts.test.ts`
- Modify `apps/quant-web/tests/alertRuleOwnership.test.ts`

- [ ] **Step 1: Write RED tests**

Add exact identity:

```ts
export const SUBING_THS_ALERT_RULE_CODE = 'subing_ths_alert_15m_v1'
```

SuBing presentation:

```text
shortLabel = 苏冰预警
resultNoun = 预警
persistentFrequencies = 15m only
```

`AlertEvent` becomes the explicit union `HtdyAlertEvent | SubingThsAlertEvent`。

- [ ] **Step 2: Add `getCurrentAlertEvents()`**

Use existing `/api/alerts/current-events`; no second endpoint。

- [ ] **Step 3: Run GREEN and commit**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts \
  tests/alertRuleOwnership.test.ts
```

## 6.3 Render persistent `S↑/S↓` without a new overlay

**Files:**

- Modify `apps/quant-web/src/utils/alertMarkers.ts`
- Modify `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify `apps/quant-web/src/pages/market/chart.vue`
- Add or modify focused marker/composable tests already used by the repository。

- [ ] **Step 1: Write RED marker tests**

Freeze:

```text
SuBing buy → label S↑, shape arrowUp, position belowBar
SuBing sell → label S↓, shape arrowDown, position aboveBar
SuBing tooltip → 苏冰预警 + MACD 金叉/死叉 + Close >/< MA21 (SMA21) + contract + signal time
HTDY persistent marker remains its current square/first-seen presentation
```

The wording above derives only from Event direction and the frozen Rule definition; it does not recompute DIFF/DEA/SMA。

- [ ] **Step 2: Freeze visibility rules**

```text
SuBing persistent marker → visible on actual_dominant 15m under overlay none or htdy
HTDY persistent marker → visible only when overlay=htdy, preserving current behavior
non-actual_dominant or non-15m → no SuBing marker
```

Do not add `ResearchOverlayId='subing'`。

- [ ] **Step 3: Update selected-chart fetching**

At `actual_dominant + 15m`, `markerRuleCodes()` returns exactly HTDY + SuBing so one selected chart may make at most two rule-range requests. Do not issue product-wide requests。

- [ ] **Step 4: Run focused GREEN**

Run the exact alert-marker/composable test files present after the edit, plus:

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts \
  tests/kline-view-model.test.ts
```

## 6.4 Add `/market` recent SuBing alerts

**Files:**

- Create `apps/quant-web/src/components/market/MarketRecentSubingAlerts.vue`
- Modify `apps/quant-web/src/pages/market/index.vue`
- Add focused unit and Playwright coverage。

- [ ] **Step 1: Write RED component/page tests**

Component receives already-fetched events and product taxonomy/dominant items. Display at most 20 SuBing events with:

```text
Asia/Shanghai HH:mm
产品名 + SYMBOL
多头预警 / 空头预警
15m
```

Empty state exactly `暂无苏冰预警`。

- [ ] **Step 2: Add exactly one global current-events resource**

`market/index.vue` adds one `useLatestResource({ fetch: getCurrentAlertEvents })`; both `refreshAll()` and visible refresh include it in the existing `Promise.all`. No per-product request loop。

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

- [ ] **Step 4: Run unit tests GREEN**

```bash
pnpm --dir apps/quant-web test
```

## 6.5 Consume `focus_bar_end` through existing `KlineChart.revealTime()`

**Files:**

- Modify `apps/quant-web/src/pages/market/chart.vue`
- Modify `apps/quant-web/tests/marketChartEntry.test.ts` or add one focused test with a precise name matching the new behavior。
- Modify the relevant Playwright chart interaction spec。

- [ ] **Step 1: Write RED deep-link tests**

```text
focus_bar_end must parse as timezone-aware ISO instant
only actual_dominant + 15m consumes it
after first matching replacement load, call chart.revealTime(focus_bar_end) once
missing target Bar does not synthesize data/marker
invalid focus is ignored safely
formal Event.bar_end is never rewritten
```

- [ ] **Step 2: Implement one-shot focus**

Preserve `focus_bar_end` through initial query synchronization until one focus attempt. Then remove only `focus_bar_end` with `router.replace()` while leaving symbol/series/frequency unchanged。

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

## 6.6 S3 regression and Gate

- [ ] Run backend API/Alert regression:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py
```

- [ ] Run security/diff checks:

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] Create Draft PR, exact-head independent Review, STOP. No production Web deployment or Runtime mutation is authorized。

---

# 7. Packet S4 — Migration 0044 + Atomic First Scope Activation Seam

**Branch/worktree:** after S3 is merged, latest `origin/develop` → `feature/subing-ths-s4-migration-scope`.

**Deliverable:** forward-only 0044 Rule insertion plus一个严格、可 dry-run、单事务的首次 `operational × 15m` Scope activation CLI seam。Implementation/test only；不得执行 production migration 或 Scope mutation。

## 7.1 Add 0044 as a data-only forward migration

**Files:**

- Create `services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py`
- Create `services/quant-api/tests/alembic/test_subing_ths_alert_migration.py`

- [ ] **Step 1: Write isolated PostgreSQL RED migration test**

Build exact 0042 fixture, apply 0043, then 0044. Assert:

```text
Alembic head == 20260902_0044
Rule codes == {htdy_original_15m, subing_ths_alert_15m_v1}
HTDY row is unchanged on all retained columns
SuBing enabled == false
SuBing scope_product_frequencies == {}
scope_products column absent
action_id column absent
strategy_payload column absent
legacy SuBing Rule/Event absent
```

- [ ] **Step 2: Confirm RED only against a disposable PostgreSQL database**

```bash
test -n "${GUIYI_ISOLATED_MIGRATION_DATABASE_URL:-}" || {
  echo "GUIYI_ISOLATED_MIGRATION_DATABASE_URL is required for isolated migration tests" >&2
  exit 1
}
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py
```

If the variable is absent, record this verification as blocked. Never substitute production/local primary DB。

- [ ] **Step 3: Implement exact 0043 preflight and 0044 postflight**

```python
revision = "20260902_0044"
down_revision = "20260902_0043"
_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"
```

Preflight must require exact 0043 columns、exactly one valid HTDY Rule、valid preserved HTDY events and no unexpected Rule. Upgrade inserts one new Rule with `enabled=false` and empty `scope_product_frequencies`; no table/column/index is added. `downgrade()` raises a stable unsupported error。

- [ ] **Step 4: Test unexpected-state and forward-recovery safety**

Simulate preflight mismatch、duplicate new Rule、postflight mismatch. No failure path may recreate `subing_strategy_v1` or deleted fields. If 0043 is already committed and 0044 later fails in real operations, recovery remains forward-only；this migration provides no downgrade path。

- [ ] **Step 5: Run GREEN and commit**

```bash
test -n "${GUIYI_ISOLATED_MIGRATION_DATABASE_URL:-}" || exit 1
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py \
  services/quant-api/tests/alembic/test_subing_ths_alert_migration.py

git add services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py \
        services/quant-api/tests/alembic/test_subing_ths_alert_migration.py
git commit -m "feat(db): add SuBing THS Alert rule migration"
```

## 7.2 Add a narrow dry-run/apply Scope activation service

**Files:**

- Create `services/quant-api/app/alerts/subing_scope_activation.py`
- Create `services/quant-api/tests/test_subing_scope_activation.py`

**Result contract:**

```python
@dataclass(frozen=True, slots=True)
class SubingScopeActivationResult:
    status: Literal["planned", "published"]
    readonly: bool
    rule_code: str
    symbol_count: int
    scope_sha256: str
    enabled: bool
```

**Function signature:**

```text
activate_subing_ths_scope(
    session: Session,
    *,
    operational_products: tuple[str, ...],
    apply: bool,
) -> SubingScopeActivationResult
```

- [ ] **Step 1: Write RED dry-run tests**

Dry-run requires:

```text
Alembic head == 0044
exact Rule set == HTDY + new SuBing
SuBing enabled=false
SuBing scope={}
operational symbols normalize to lowercase, unique, sorted and non-empty
```

Build exact `{symbol: ["15m"]}` map, serialize with sorted keys and compact separators, compute SHA-256, and return count/hash without UPDATE or commit mutation。

- [ ] **Step 2: Write RED apply tests**

One transaction must:

```text
lock/re-read SuBing Rule
recheck disabled + empty scope
set exact full Scope
set enabled=true
commit once
re-read exact scope/count/hash/enabled
prove HTDY row unchanged
```

Any preflight mismatch fails before mutation；any DB exception rolls back。

- [ ] **Step 3: Implement and run GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_scope_activation.py
```

- [ ] **Step 4: Commit**

```bash
git add services/quant-api/app/alerts/subing_scope_activation.py \
        services/quant-api/tests/test_subing_scope_activation.py
git commit -m "feat(alerts): add atomic SuBing scope activation"
```

## 7.3 Wire a runtime CLI command with read-only default

**Files:**

- Modify `services/quant-api/app/guiyi_cli/main.py`
- Modify `services/quant-api/tests/test_alert_cli.py`

- [ ] **Step 1: Write RED parser/execution tests**

Commands:

```bash
uv run --project services/quant-api guiyi runtime subing-ths-scope
uv run --project services/quant-api guiyi runtime subing-ths-scope --apply
```

For dry-run, assert:

```python
assert payload["schema_version"] == 1
assert payload["command"] == "runtime.subing-ths-scope"
assert payload["status"] == "planned"
assert payload["readonly"] is True
assert payload["rule_code"] == "subing_ths_alert_15m_v1"
assert payload["symbol_count"] == len(expected_operational_products)
assert re.fullmatch(r"[0-9a-f]{64}", payload["scope_sha256"])
assert payload["enabled"] is False
```

For `--apply`, fake/injected service returns `status=published`、`readonly=false`、`enabled=true` only after its verified transaction path. Tests never access production DB。

- [ ] **Step 2: Correct readonly classification**

`runtime subing-ths-scope` without `--apply` is readonly；the same command with `--apply` is a mutation. Parse-error classification must reflect whether `--apply` was requested。

- [ ] **Step 3: Inject the activation callable and implement command**

Follow existing CLI dependency-injection style so unit tests can supply a fake activation function and fake session factory. Do not hard-wire an untestable global mutation。

- [ ] **Step 4: Run GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py
```

## 7.4 S4 verification and Gate

- [ ] Run focused activation/Alert tests:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_subing_scope_activation.py \
  services/quant-api/tests/test_alert_service.py
```

- [ ] Run full non-isolated backend:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] Run full Mypy/Ruff according to current `TESTING.md`, then:

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] Create Draft PR + exact-head independent Review + STOP. Never execute real `alembic upgrade` or `guiyi runtime subing-ths-scope --apply` in S4。

---

# 8. Packet S5 — Canonical Sync, OpenSpec, Full Verification, RC Handoff

**Branch/worktree:** after S4 is merged, latest `origin/develop` → `docs/subing-ths-s5-canonical-rc`.

**Deliverable:** active canonical 与代码事实一致，OpenSpec/TESTING 可执行，全仓 fresh verification + exact-head independent Review 完成，结论最多到“允许进入 release candidate”。

## 8.1 Synchronize active canonical only after S1-S4 exist in develop

**Files:**

- Modify `AGENTS.md`
- Modify `PROJECT_SOURCE.md`
- Modify `DECISIONS.md`
- Modify `docs/ARCHITECTURE.md`
- Modify `TESTING.md`
- Modify `tests/engineering/test_canonical_consistency.py`

- [ ] **Step 1: Write/adjust canonical consistency tests first**

Tests must require active code/document facts equivalent to:

```text
post-0044 stable Rule identities = HTDY + subing_ths_alert_15m_v1
SuBing = observation-only, completed actual_dominant 15m
MA21 = SMA21
old subing_strategy_v1 implementation remains retired
Event-first one-shot transport remains
Range/zero-axis/multi-timeframe are not SuBing V1 gates
STATUS only records actual release/Runtime/DB/evidence facts
```

- [ ] **Step 2: Confirm RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
```

Expected RED reason: active canonical still describes HTDY-only stable Alert surface。

- [ ] **Step 3: Update documents according to responsibility**

`PROJECT_SOURCE.md`: add the minimal “苏冰预警” observation product and keep manual-decision/no-order boundary。

`DECISIONS.md`: freeze new identity、exact formula class、new-not-old identity、Event-first one-shot semantics；keep old strategy retirement as a separate long-term decision。

`docs/ARCHITECTURE.md`: add the SuBing 15m evaluator branch inside the existing Alert Runtime；no second Runtime process。

`AGENTS.md`: post-0044 active Alert composition permits HTDY + new SuBing；Scope/DB/notification/Runtime/release still require explicit Gates。

`TESTING.md`: add S1-S4 focused commands、0044 isolated PostgreSQL tests、Web Alert verification and explicit warning that commands do not authorize production operations。

`STATUS.md`: do not edit merely because code exists。Only a separately observed release/Runtime/DB/evidence fact may change it。

- [ ] **Step 4: Run canonical GREEN and commit**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
```

## 8.2 Add strict OpenSpec

**File:** Create `openspec/specs/subing-ths-alert/spec.md`

- [ ] **Step 1: Write OpenSpec from the approved Spec and this approved Plan**

It must freeze:

```text
rule/formula identity
completed actual_dominant 15m only
exact CROSS + SMA21
same-physical-contract state isolation
no hidden filters
Event identity/idempotency
event_mode split: HTDY first_seen, SuBing exact
one-shot transport/no retry
Web Event authority
0044 disabled+empty scope
atomic first activation
G10 compatibility evidence before G9 activation
external Gate separation
```

- [ ] **Step 2: Validate strictly**

```bash
openspec validate --specs --strict --no-interactive
```

- [ ] **Step 3: Commit**

```bash
git add openspec/specs/subing-ths-alert/spec.md
git commit -m "docs(openspec): specify SuBing THS alert V1"
```

## 8.3 Run fresh full verification at exact head

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

- [ ] **Step 3: Full isolated PostgreSQL migration suite**

```bash
test -n "${GUIYI_ISOLATED_MIGRATION_DATABASE_URL:-}" || {
  echo "isolated PostgreSQL URL is required before TEST_COMPLETE" >&2
  exit 1
}
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m isolated_postgresql \
  services/quant-api/tests/alembic
```

If no disposable DB is configured, S5 is blocked from `TEST_COMPLETE`. Never substitute production DB。

- [ ] **Step 4: Mypy and Ruff**

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
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check origin/develop...HEAD
git status --short
```

- [ ] **Step 7: Record exact fresh outputs in Draft PR**

Distinguish `passed`、`skipped`、`deselected` and `not run` exactly。Do not summarize an unavailable isolated DB suite as passed。

## 8.4 Independent exact-head Review

- [ ] **Step 1: Freeze clean exact head**

```bash
git rev-parse HEAD
git status --short
```

- [ ] **Step 2: Request two independent review axes**

```text
Standards axis:
AGENTS / data facts / security / migration / Event-first / one-shot / Git boundaries

Spec axis:
exact formula / no hidden filters / same-contract causality / Event authority / Web / G10-before-G9
```

Review findings use Critical / High / Medium / Low with file/line evidence。Any Critical/High blocks；Medium affecting formula、causality、migration、notification or Gate safety also blocks until fixed and re-reviewed。

- [ ] **Step 3: Fix findings, rerun affected verification, freeze a new SHA, re-review**

No approval carries from an earlier SHA to a changed SHA。

## 8.5 RC handoff and STOP

- [ ] Prove S1-S4 merge commits are reachable from the S5 base `develop`。
- [ ] Draft PR may conclude only:

```text
CODE_COMPLETE
TEST_COMPLETE
independent Review approved
允许进入 release candidate（等待 owner Gate）
```

- [ ] STOP before release or external mutation。Never claim `RELEASED`、`RUNTIME_READY` or `BUSINESS_CLOSED`。

---

## 9. Future External Gate Order

This Plan intentionally stops before external execution。Future release/operator work is a separate Lane 3 task and must re-read then-current `STATUS.md`。

Expected order after S5 is approved and integrated:

```text
G5  release main/tag + GitHub Release + exact identity readback
G6  Runtime maintenance stop
G7  production DB from its then-current head forward to 0044
    - if it is still 0042, Alembic applies 0043 then 0044
    - postflight/readback required
G8  exact-tag Runtime promotion
    - SuBing remains disabled + empty scope
    - health/smoke only
G10 read-only 同花顺 compatibility evidence
    - no PushPlus
    - no Rule enable
    - compare at least 2 products, 5 golden-cross and 5 dead-cross examples when available
G9  production Scope activation + Rule enable
    - use the reviewed `guiyi runtime subing-ths-scope --apply` seam
    - one separately authorized mutation
G11 natural completed 15m Event + one-shot transport evidence
G12 user confirms actual WeChat delivery
```

The exact future release version is not preassigned. Release work must select it from then-current `main` / latest GitHub Release facts。

---

## 10. Packet Integration Protocol

For every S1-S5 Packet:

1. `git fetch origin`。
2. Read current `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、approved Spec、approved Plan and current Packet-relevant code/tests。
3. Confirm branch/worktree/dirty state and preserve unrelated user/other-task edits。
4. Create a fresh task worktree from execution-time latest `origin/develop` using `superpowers:using-git-worktrees`。
5. Use TDD for each behavior: write precise failing test → run it → confirm expected RED reason → minimal implementation → focused GREEN → adjacent regression → refactor → commit。
6. Keep commits single-purpose；do not mix another Packet or unrelated refactor。
7. Before any completion claim, use `superpowers:verification-before-completion` and run fresh commands。
8. Create Draft PR to `develop` only。
9. Self-review, then use `superpowers:requesting-code-review` for exact-head independent Review。
10. Stop and wait for owner `允许集成 develop`；no automatic merge。
11. After approved integration, prove the merge is reachable from `develop`，then clean the merged task worktree and branch。
12. Start the next Packet in a new Codex session from the new latest `develop`。

---

## 11. Implementation Plan Self-Review

The completed Plan was checked against all 26 approved Spec sections and current repo structure。Findings closed before submission:

1. **A rolling fixed-size EMA replay would violate prefix invariance.** Replaced by a tiny in-memory cursor, full same-contract rebuild on first use/rollover, and cursor-based reconciliation thereafter。
2. **Downtime reconciliation could become backfill.** Intermediate Bars may advance state but only the current trigger cutoff may return a Candidate/Event。
3. **HTDY and SuBing require different persistence semantics.** Added explicit `event_mode`: HTDY first-seen, SuBing exact facts。
4. **Missing evaluator/formatter could silently fall back to HTDY.** Startup composition requires exact registry/evaluator/policy key equality。
5. **Private PushPlus config could unnecessarily expand.** V1 keeps the existing observers Topic and config keys；no second Topic/token/member model。
6. **Per-rule health could regrow into a Boundary Ledger.** Kept exactly four bounded fields per fixed Rule in the existing status key；no symbol ledger or PostgreSQL history。
7. **Deep link could create a second chart navigation implementation.** S3 reuses existing `KlineChart.revealTime()` and preserves formal Event `bar_end`。
8. **SuBing marker could force a new overlay.** No new overlay；SuBing Event marker is visible on actual_dominant 15m while HTDY overlay semantics remain unchanged。
9. **0044 could freeze today’s operational universe.** Migration inserts disabled+empty Rule only；activation reads execution-time operational products。
10. **Initial Scope setup could leave a partial 60-call state.** Added one-transaction dry-run/apply seam with stable count/hash readback。
11. **Canonical could claim an active product before implementation exists.** Canonical sync is S5 after S1-S4 are integrated。
12. **Current production Runtime facts changed while the Plan was being written.** Final review refreshed the baseline to `develop@a473765...` and records v1.9.12 API/Web/Live loaded with Alert still failed/degraded, without treating development as a restart authorization。
13. **Release version could be guessed prematurely.** Future release selects version from then-current facts；no fixed version here。
14. **API/Web/formatter could become second formula authorities.** Only `SubingThs15mKernel` decides Candidate；other layers consume Event direction。
15. **Legacy strategy convenience reuse could violate the retirement decision.** No planned path recreates Daily Watch/Factor/Lifecycle/Action/Episode/Position/Strategy Runtime or deleted columns。
16. **Approved Spec has contradictory compatibility/activation ordering.** Resolved fail-closed as `G10 compatibility evidence → G9 Scope activation + enable` and elevated this to an explicit Plan-approval decision。
17. **Scope activation test location was ambiguous.** Fixed to `services/quant-api/tests/test_subing_scope_activation.py`。
18. **Illustrative code contained unresolved function bodies/output placeholders.** Replaced with concrete SMA code, exact interface contracts, regex hash assertions and environment-variable-based isolated DB commands。
19. **SuBing warming/error status needed deterministic mapping.** Added stable evaluator error codes and a fixed v6 rule-status mapping contract。
20. **Current production Alert is already failed/degraded.** The Program explicitly treats that as a separate production incident and forbids using S1-S5 to trigger real restart/rollback/migration without a new Gate。

Placeholder scan target before PR creation: `TBD=0`、`TODO=0`、unresolved function-body marker=0、conflict marker=0。

Interface dependency check:

```text
S1 produces kernel + replay seam
S2 consumes S1 and produces multi-rule Alert Runtime/Event wire
S3 consumes S2 Rule/Event facts and exposes Web review
S4 consumes the stable application Rule identity and adds 0044 + activation seam
S5 only synchronizes canonical after S1-S4 are integrated
```

No Packet requires a later Packet in order to compile its own touched interfaces；the combined feature is intentionally not releaseable until S5 and 0044 are present。

---

## 12. Final Gate For This Plan

This document is Implementation Plan only。User approval authorizes starting **S1 only** in a new Lane 3 implementation session。

Plan approval does not authorize:

```text
S1 auto-merge to develop
S2-S5 in the same session
production PostgreSQL/Redis/Scope
real PushPlus
Runtime restart/switch/promotion
main merge
tag
GitHub Release
```

S1 must stop at Draft PR + fresh verification + exact-head independent Review + owner `允许集成 develop` Gate。