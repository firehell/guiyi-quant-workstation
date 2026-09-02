# Newow 牛哇版本 · 日线趋势详情页 V1 Implementation Plan

日期：2026-09-02  
状态：`SLICE_A_IN_DEVELOP / SLICE_B_PLAN_ALIGNED / SLICE_B_IMPLEMENTATION_NOT_STARTED`  

> 本文是 `docs/tasks/2026-09-01-newow-trend-v1-design.md` 的父级实施计划。Slice B 的精确设计源为 `docs/tasks/2026-09-02-newow-slice-b-cup-handle-engine-design.md`；本文 Task 4–5 已与该 Spec 对齐。两者冲突时，Slice B Spec 优先。

> **For agentic workers:** Slice 内必须按 TDD 执行，完成前使用 verification-before-completion，完成后进行独立 formula/causality 与 scope/maintenance Review。一个 Slice 使用一个独立 branch/worktree，不并行推进后续 Slice。

## 1. 总目标

在不影响当前版本、HTDY、Alert、Runtime 或任何生产事实的前提下，实现独立的“牛哇版本 · 趋势策略 · 日线详情页”。V1 的纯计算链路为：

```text
actual_dominant + completed D1
→ 黄蓝趋势带
→ 建仓 / 清仓
→ D1 / D2 / D3
→ 杯柄 FORMING / READY / BREAKOUT / WEAKENED / INVALIDATED / EXPIRED
→ NewowTrendFrame
→ 后续只读数据服务 / API / Web
```

当前实施焦点仅为 Slice B：

```text
Task 4：杯柄专用 Kernel
Task 5：统一 NewowTrendD1Engine
```

## 2. 总体工程边界

- 唯一产品身份：`strategy_code=newow_trend_v1`、`profile_id=newow_trend_d1_v1`。
- 唯一数据身份：`series_kind=actual_dominant`、`frequency=1d`、`completed_only`。
- Newow 只复用数据底座，不读取或继承 SuBing、HTDY、Alert、Context、Episode、现有趋势 Overlay 或前端指标结果。
- 黄蓝趋势带：`newow_trend_band_cleanroom_v1`。
- D1/D2/D3：`newow_escape_d123_v1`。
- 杯柄：`newow_cup_handle_v1`。
- 蓝色仅表示牛哇语义中的空仓/风险阶段，不创建期货空单。
- V1 不实现其他形态、Phase、Lux Range、目标价、吸筹价、底部三个副图、收益曲线、全市场扫描、Shadow、PushPlus、Runtime 或自动交易。
- 不新增 PostgreSQL 表、Alembic migration、Redis key、队列、Worker、账户、订单、仓位或 PnL。
- 所有正式输出必须满足 completed-only、strict-before、prefix invariance、batch/incremental parity、restore parity、same-physical-contract isolation、rollover reset、first-seen immutable 和 fail-closed。
- 参数不得根据历史收益静默调整；任何公式或阈值变化必须创建新公式版本。

## 3. 交付 Slice

```text
Slice A — 已进入 develop
  Task 1：Reference / Contracts / Profile
  Task 2：黄蓝趋势带与 BUILD/CLEAR
  Task 3：VAR4 与 D1/D2/D3

Slice B — 当前唯一可执行 Slice
  Task 4：杯柄专用 Kernel
  Task 5：统一 D1 Engine

Slice C — Slice B 通过后才可启动
  Task 6–8：actual-dominant D1 数据服务、无状态 Gate、只读 API

Slice D — Slice C 通过后才可启动
  Task 9–12：Web 类型、独立详情页、主图和弹层

Slice E — Slice D 通过后才可启动
  Task 13–14：E2E、视觉对照、全量因果和最终 Review
```

## 4. Slice A 已有事实，不得重做

当前 `develop` 已有：

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py
├── profile.py
├── trend_band.py
└── escape_d123.py

services/quant-api/tests/newow/
├── fixtures.py
├── test_models_profile.py
├── test_trend_band.py
└── test_escape_d123.py
```

Task 4–5 必须直接消费这些合同，不复制或改变黄蓝、VAR4、MA120、D1/D2/D3 公式。允许的兼容扩展仅限：

- 增加杯柄 typed contracts；
- 增加杯柄 Profile 参数；
- 增加 `CUP_HANDLE_EXPIRED`；
- 扩展 `NewowTrendFrame` 的 rollover 与 diagnostics；
- 新增 `cup_handle.py` 和 `engine.py`。

---

# Task 4：实现杯柄专用 Kernel

## 4.1 文件范围

允许创建或修改：

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py
├── profile.py
└── cup_handle.py

services/quant-api/tests/newow/
├── fixtures.py
├── test_models_profile.py
└── test_cup_handle.py
```

禁止创建：

```text
patterns/
swing.py
structure.py
phase.py
target_risk.py
execution.py
任何 API / Web / DB / Redis / Runtime 文件
```

## 4.2 必须先冻结的合同

### `CupPivotKind`

```python
class CupPivotKind(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"
```

### `CupPivot`

```python
@dataclass(frozen=True, slots=True)
class CupPivot:
    kind: CupPivotKind
    price: Decimal
    pivot_at: datetime
    confirmed_at: datetime
    pivot_index: int
    confirmed_index: int
    atr_at_pivot: float
```

约束：

```text
price > 0
atr_at_pivot > 0 且 finite
confirmed_at >= pivot_at
confirmed_index >= pivot_index
同一 tracker 的 Pivot 必须 HIGH / LOW 交替
```

### `NewowCupHandleOverlay`

```python
@dataclass(frozen=True, slots=True)
class NewowCupHandleOverlay:
    candidate_id: str
    direction: CupHandleDirection
    state: CupHandleState
    left_rim: CupPivot
    bottom: CupPivot
    right_rim: CupPivot
    handle_start_at: datetime
    handle_extreme: CupPivot | None
    pivot_price: Decimal | None
    pivot_frozen_at: datetime | None
    confirmed_at: datetime
    first_seen_at: datetime
    state_changed_at: datetime
    score: float
    score_breakdown: Mapping[str, float]
    hard_failures: tuple[str, ...]
    diagnostics: tuple[str, ...]
    volume_facts: Mapping[str, float]
    formula_version: str
```

合同要求：

- FORMING 必须已有 L/B/R，允许 H/P 为空；
- READY 及以后必须已有 H/P；
- 合法主图 Overlay 的 `hard_failures` 必须为空；
- READY 后 L/B/R/H/P、`confirmed_at`、score、breakdown 和 volume facts 永久冻结；
- 后续只允许改变 `state` 与 `state_changed_at`。

### Marker 与 Frame

`NewowMarkerType` 增加：

```text
CUP_HANDLE_EXPIRED
```

`NewowTrendFrame` 扩展：

```python
rollover_started: bool
diagnostics: tuple[str, ...]
```

不得增加 OPEN、CLOSE、POSITION、ORDER 或 PnL 合同。

## 4.3 Profile 参数

在 `NEWOW_TREND_D1_V1` 中增加并冻结：

```text
cup_atr_period                         = 14
cup_pretrend_min_bars                  = 20
cup_pretrend_max_bars                  = 60
cup_pretrend_min_return                = 0.10
cup_pretrend_min_move_atr              = 4.0
cup_min_bars                           = 25
cup_max_bars                           = 90
cup_depth_min_pct                      = 0.10
cup_depth_preferred_max_pct            = 0.35
cup_depth_hard_max_pct                 = 0.50
cup_depth_min_atr                      = 3.0
cup_rim_gap_max_pct                    = 0.05
cup_rim_gap_max_atr                    = 1.50
cup_bottom_zone_ratio                  = 0.25
cup_bottom_span_ready_min              = 3
cup_leg_ratio_soft_min                 = 0.50
cup_leg_ratio_soft_max                 = 2.00
cup_leg_ratio_hard_min                 = 1 / 3
cup_leg_ratio_hard_max                 = 3.00
cup_midline_crossings_soft_max         = 3
cup_midline_crossings_hard_max         = 5
cup_handle_min_bars                    = 5
cup_handle_max_bars                    = 15
cup_handle_depth_max_pct               = 0.15
cup_handle_retrace_max_ratio           = 1 / 3
cup_handle_upper_half_ratio            = 0.50
cup_handle_right_volume_max_ratio      = 0.80
cup_handle_baseline_volume_max_ratio   = 0.90
cup_breakout_buffer_atr                = 0.10
cup_breakout_volume20_min_ratio        = 1.20
cup_breakout_handle_volume_min_ratio   = 1.50
cup_forming_min_body_score             = 45
cup_ready_min_score                    = 80
cup_breakout_min_score                 = 85
cup_ready_expiry_bars                  = 20
cup_post_breakout_archive_bars         = 20
cup_recent_terminal_ids_limit          = 32
```

保留 Slice A 已有：

```text
cup_reversal_atr                  = 1.25
cup_min_leg_bars                  = 3
cup_history_limit                 = 220
cup_max_confirmed_pivots          = 32
cup_max_candidate_checks_per_step = 256
```

## 4.4 公开接口

```python
@dataclass(frozen=True, slots=True)
class CupHandleStepResult:
    state: CupHandleStateValue
    active_overlay: NewowCupHandleOverlay | None
    markers: tuple[NewowMainMarker, ...]
    diagnostics: tuple[str, ...]
    candidate_checks: int


def initial_cup_handle_state() -> CupHandleStateValue: ...


def step_cup_handle(
    state: CupHandleStateValue,
    bar: NewowDailyBar,
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> CupHandleStepResult: ...


def calculate_cup_handle_series(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[CupHandleStepResult, ...]: ...
```

内部状态必须是 frozen、tuple-based、可序列化，且只保留：

```text
ATR最小递推状态
eligible Bars <= 220
confirmed Pivots <= 32
active candidate <= 1
terminal candidate IDs <= 32
每Bar candidate checks <= 256
```

## 4.5 TDD 实施顺序

### Step 1：先写合同和 Profile 失败测试

至少覆盖：

```text
CupPivot immutable 与字段约束
Overlay 各 state 字段完整性
CUP_HANDLE_EXPIRED enum
全部新增 Profile 参数精确值
非法比例、窗口、NaN 参数拒绝
```

运行：

```bash
cd services/quant-api
PYTHONPATH=.:../../packages/quant-core uv run pytest \
  tests/newow/test_models_profile.py -q
```

预期：新合同尚未实现，测试失败。

### Step 2：建立合成 fixture

`fixtures.py` 至少提供：

```text
bullish_true_cup_handle
bearish_true_cup_handle
ready_and_breakout_same_bar
breakout_then_weakened
ready_then_invalidated
ready_then_expired
v_bottom_rejected
wide_range_rejected
downtrend_rebound_rejected
shallow_cup_rejected
cup_too_deep_rejected
rim_gap_rejected
handle_too_short_rejected
handle_too_long_rejected
handle_too_deep_rejected
handle_below_mid_rejected
handle_volume_not_contracting
breakout_volume_not_confirmed
rollover_split_candidate
candidate_limit_exceeded
```

每个 fixture 固定锚点日期、预期状态或诊断码，不使用未来收益作为标签。

### Step 3：实现 Wilder ATR14 与因果 Pivot Tracker

ATR：

```text
TR = max(H-L, abs(H-prevC), abs(L-prevC))
首个ATR14 = 前14个有限TR简单平均
后续ATR = (13×prevATR + TR) / 14
```

Pivot：

```text
高点确认：close <= extreme_high - 1.25 × ATR_at_extreme
低点确认：close >= extreme_low  + 1.25 × ATR_at_extreme
最小腿长：3根 eligible D1
```

必须测试：

```text
pivot_at 与 confirmed_at 分离
确认前 prefix 看不到 Pivot
追加未来数据不移动已确认 Pivot
HIGH/LOW交替
初始方向 tie-break 稳定
ineligible Bar 只预热 ATR，不进入几何
rollover 清空 ATR/Pivot
batch / step / restore 一致
```

### Step 4：实现有界候选枚举与身份

方向归一化后统一寻找：

```text
L 高位左杯口
→ B 低位杯底
→ R 高位右杯口
→ H 浅柄低点
→ 向上突破 P
```

规则：

```text
L/R同方向
25 <= R.index - L.index + 1 <= 90
B = L/R之间最低反方向已确认Pivot
H = R之后、以 H.confirmed_index 计5–15根内最低反方向已确认Pivot
H未确认时最多FORMING
看涨+看跌每Bar总检查 <=256
```

Candidate ID：

```text
sha256(
  strategy_code |
  cup_formula_version |
  physical_contract |
  segment_id |
  direction |
  L.pivot_at |
  B.pivot_at |
  R.pivot_at
)
```

H 不进入 ID。相同 L/B/R 一旦终止不得使用另一个 H 重生。

Primary 排序：

```text
已有 READY/BREAKOUT/WEAKENED 优先且不可替换
否则 hard-valid
→ BREAKOUT > READY > FORMING
→ score降序
→ confirmed_at降序
→ candidate_id升序
```

### Step 5：实现前置趋势、杯体和 U 形 Gate

前置趋势：对 L 前 `k=20..60` 的每个窗口计算方向回归、return 和 ATR 推动：

```text
normalized_slope > 0
AND
(return_pct >= 10% OR move_atr >= 4.0)
```

合法窗口固定排序：

```text
max(return/0.10, move_atr/4.0) 最大
→ min(...) 最大
→ k更小
```

杯体硬条件：

```text
25–90根
10%–50%杯深
杯深 >=3 ATR
杯口差 <=5%
杯口差 <=1.5 ATR
```

U 形：

```text
底部25%深度区域连续停留 >=3根才可READY
单根V形底不可READY
左右腿硬范围1/3–3.0；0.5–2.0为正常区
中轴穿越>5拒绝；4–5重扣分
```

所有拒绝原因放入 `CupHandleStepResult.diagnostics`；不得把带 hard failure 的 Overlay 返回主图。

### Step 6：实现柄部、P 与量能 Gate

柄长：

```text
handle_bars = H.confirmed_index - R.pivot_index
5 <= handle_bars <= 15
```

柄部硬条件：

```text
柄深 <=15%
柄部回撤 <=右侧上涨的1/3
H位于杯体上半部
```

P 在 READY 时冻结：

```text
看涨：max(high)
看跌：min(low)
窗口：R.pivot_index+1 .. H.confirmed_index-1
排除 R Bar 与 H确认Bar
```

量能窗口：

```text
right_leg_volume = B+1 .. R
handle_volume = R+1 .. H.confirmed-1
handle_baseline_volume = 截至R最近20根（含R）
breakout_volume20 = 突破前20根（不含突破Bar）
```

READY 缩量：

```text
median(handle) <= 0.80 × median(right_leg)
median(handle) <= 0.90 × median(handle_baseline)
```

BREAKOUT：

```text
当前归一化close > P + 0.10×ATR_current
前一eligible close <= P + 0.10×ATR_previous
当前volume >= 1.20×突破前20日中位量
当前volume >= 1.50×冻结柄部中位量
```

几何突破但无量：记录 `BREAKOUT_VOLUME_UNCONFIRMED`，保持 READY。必须先回到阈值下，再次合法上穿才可确认突破。

### Step 7：实现评分与生命周期

评分：

```text
pretrend          15
cup_geometry      25
u_shape_purity    20
handle_quality    20
volume_structure  20
```

状态门槛：

```text
FORMING：body_score >=45/60
READY：base_score >=80/94
BREAKOUT：full_score >=85/100
```

状态：

```text
NONE → FORMING → READY → BREAKOUT → WEAKENED → INVALIDATED
READY → INVALIDATED
READY → EXPIRED
```

同 Bar 首次 READY 且突破时，依次产生：

```text
CUP_HANDLE_READY
CUP_HANDLE_BREAKOUT
```

READY 后 20 根没有突破：`CUP_HANDLE_EXPIRED`。

突破后：

```text
close回到P下方但未破H-0.10ATR → WEAKENED
close跌破H-0.10ATR → INVALIDATED
```

V1 不实现 WEAKENED 后恢复 BREAKOUT。BREAKOUT 连续20根未弱化/失效时内部归档，不产生新 Marker。

### Step 8：实现 Marker 身份与关联

Marker ID：

```text
sha256(candidate_id | marker_type | bar_end)
```

关系：

```text
BREAKOUT → READY
WEAKENED → READY + BREAKOUT
INVALIDATED → READY + 已有BREAKOUT/WEAKENED
EXPIRED → READY
```

Marker facts 至少包含 candidate、direction、state before/after、L/B/R/H/P、score、breakdown、volume facts 与 formula version。

### Step 9：运行 Task 4 验证

```bash
cd services/quant-api
PYTHONPATH=.:../../packages/quant-core uv run pytest \
  tests/newow/test_models_profile.py \
  tests/newow/test_cup_handle.py -q

uv run ruff check \
  ../../packages/quant-core/guiyi_quant/newow \
  tests/newow/test_models_profile.py \
  tests/newow/test_cup_handle.py

uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

全部通过后进行 formula/causality Review。不得以 UI 或历史收益代替这一 Gate。

### Step 10：Task 4 提交

只提交本任务文件：

```text
feat(newow): add causal cup handle kernel
```

Review 必须拒绝：未来 Pivot、centered window、READY 后改锚点、跨合约杯柄、无量突破晋升、通用 Pattern 平台或任何交易语义。

---

# Task 5：组合唯一 Newow D1 Engine 并证明因果性

## 5.1 文件范围

允许创建或修改：

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py
└── engine.py

services/quant-api/tests/newow/
└── test_engine_causality.py
```

Task 5 不修改三个子 Kernel 的公式。

## 5.2 Engine 合同

```python
@dataclass(frozen=True, slots=True)
class NewowTrendD1EngineState:
    trend_band_state: TrendBandStateValue
    escape_state: EscapeState
    cup_handle_state: CupHandleStateValue
    physical_contract: str | None
    segment_id: str | None
    last_bar_end: datetime | None
    last_trading_day: date | None
    eligibility_started: bool


@dataclass(frozen=True, slots=True)
class NewowTrendD1StepResult:
    state: NewowTrendD1EngineState
    frame: NewowTrendFrame


class NewowTrendD1Engine:
    @classmethod
    def initial(
        cls,
        *,
        profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
    ) -> "NewowTrendD1Engine": ...

    def step(self, bar: NewowDailyBar) -> NewowTrendD1StepResult: ...


def calculate_newow_trend_frames(
    bars: tuple[NewowDailyBar, ...],
    *,
    profile: NewowTrendProfile = NEWOW_TREND_D1_V1,
) -> tuple[NewowTrendFrame, ...]: ...
```

Historical 与后续盘后增量只能调用同一 `step`。

## 5.3 固定处理顺序

```text
1. 校验 Engine state
2. 校验 completed D1、bar_end、trading_day 和 eligibility 顺序
3. 检测 physical_contract / segment rollover
4. rollover 时统一重置三个 sub-state
5. step_trend_band
6. step_escape_d123
7. step_cup_handle
8. 按 family order 汇总 Marker
9. 冻结 NewowTrendFrame
10. 保存最后 Bar identity
```

Marker family order：

```text
1. BUILD / CLEAR
2. D1 / D2 / D3（D1 > D2 > D3）
3. CUP READY / BREAKOUT / WEAKENED / INVALIDATED / EXPIRED
```

不得直接按全局 `priority` 混排。

## 5.4 输入与状态错误

调用错误抛 `ValueError`：

```text
NEWOW_BAR_DUPLICATE
NEWOW_BAR_OUT_OF_ORDER
NEWOW_TRADING_DAY_OUT_OF_ORDER
NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION
```

恢复状态损坏：

```text
当前Frame = UNAVAILABLE
markers = ()
diagnostics += NEWOW_ENGINE_STATE_INVALID
返回initial state
```

不得在损坏状态上继续计算或只重置单个子模块。

杯柄级问题只进入 diagnostics，不抹掉同 Bar 合法趋势带与 D123：

```text
CUP_ATR_UNAVAILABLE
CUP_HISTORY_INSUFFICIENT
CUP_CANDIDATE_LIMIT_EXCEEDED
HANDLE_VOLUME_UNAVAILABLE
BREAKOUT_VOLUME_UNCONFIRMED
```

## 5.5 Rollover 与 eligibility

物理合约或 segment 变化：

```text
rollover_started = true
趋势带、D123、杯柄三个状态全部重置
新合约当前Bar作为第一根输入
当前Bar不产生任何Marker
旧杯柄不产生INVALIDATED/EXPIRED
```

同 segment eligibility：

```text
False → False：允许
False → True：允许
True → True：允许
True → False：拒绝
```

杯柄对 False Bar 只预热 ATR；趋势带和 D123 保持 Slice A 已实现的数值 warm-up 语义。

## 5.6 TDD 实施顺序

### Step 1：先写 Engine 合同和顺序失败测试

断言：

```text
三个子Kernel收到完全相同的completed Bar
Frame.bar_end与所有结果一致
Frame.markers与Step结果一致
Marker按family order稳定
同Bar多D信号全部保留
同BarREADY+BREAKOUT顺序稳定
```

### Step 2：写 rollover 与 eligibility 测试

必须证明：

```text
换月第一Bar rollover_started=true
无BUILD/CLEAR/D/cup Marker
三个sub-state已重置
A合约杯柄不能在B合约完成
True→False被拒绝
False warm-up 不产生杯柄几何
```

### Step 3：写重复、逆序和损坏恢复状态测试

覆盖：

```text
重复bar_end
逆序bar_end
逆序trading_day
Naive或非completed Bar已由NewowDailyBar拒绝
Engine state与sub-state identity不一致
恢复状态窗口损坏
```

### Step 4：写完整不变性 Harness

对每个正例和关键负例：

```text
full run
每个prefix重跑
batch与incremental比较
多个cut point序列化/恢复
future-tail mutation
重复执行deterministic IDs
```

比较：

```text
TrendBandPoint
D123数值与Marker
Cup Overlay与Marker
Frame diagnostics
Marker顺序
Engine State
```

### Step 5：验证 RED

```bash
cd services/quant-api
PYTHONPATH=.:../../packages/quant-core uv run pytest \
  tests/newow/test_engine_causality.py -q
```

预期：`engine.py` 尚未实现，测试失败。

### Step 6：实现最小编排

Engine 只做校验、重置、顺序调用和汇总。禁止：

```text
读取MarketDataService
HTTP/Web知识
文件缓存
数据库/Redis
外部指标
仓位、PnL或交易
非D1输入
```

### Step 7：运行完整 Slice B 验证

```bash
cd services/quant-api

PYTHONPATH=.:../../packages/quant-core uv run pytest \
  tests/newow/test_models_profile.py \
  tests/newow/test_trend_band.py \
  tests/newow/test_escape_d123.py \
  tests/newow/test_cup_handle.py \
  tests/newow/test_engine_causality.py -q

uv run ruff check \
  ../../packages/quant-core/guiyi_quant/newow \
  tests/newow

uv run mypy ../../packages/quant-core/guiyi_quant/newow
```

再执行与当前仓库约定相符的 secret scan 和 `git diff --check`。

### Step 8：独立 Review

至少分开检查：

```text
公式和评分
Pivot/READY/Marker因果性
Engine/rollover/restore
范围和个人维护成本
Slice A回归
```

发现问题必须修复后重新运行完整 Slice B 验证。

### Step 9：Task 5 提交与 Slice 集成 Gate

Task 5 小提交：

```text
feat(newow): compose causal D1 trend engine
```

Slice B 最终只允许输出：

```text
SLICE_B_READY_FOR_INTEGRATION
SLICE_B_REQUIRES_FIXES
SLICE_B_BLOCKED
```

只有第一种结论才允许把 feature branch 集成到 `develop`。集成不等于 main、tag、release、Runtime、Alert 或数据写入。

---

# Task 6–14：后续阶段边界

以下任务保持父级产品方向，但在 Slice B 完成前不得启动。后续每个 Slice 开始前应根据当时 `develop` 再形成精确计划，不得提前修改 Slice B 公式。

## Task 6：actual-dominant D1 Detail Service

只通过 `MarketDataService` 读取真实 rank1 segment；同合约 warm-up、visible range 与 rollover seam 必须明确，不允许 Parquet glob、continuous fallback、自判主力或 settlement 替代 close。

## Task 7：无状态与有界 Query Gate

V1 请求内重放，不增加文件缓存、全局 mutable cache、数据库、Redis、scheduler 或后台任务；限制最大可见和 warm-up 工作量。

## Task 8：只读 FastAPI

仅提供 D1、actual_dominant 的只读 endpoint；DTO 显式映射，不返回内部异常、路径、SQL 或任何自动交易建议。

## Task 9：Web Types / API Client / View Model

TypeScript 只消费后端结果，不重算趋势带、D123 或杯柄。D1/D2/D3 同日全保留，主图只选择最高显示优先级。

## Task 10：Current / Newow 独立详情外壳

现有详情页机械隔离，`chart.vue` 只做 `current|newow` 分流；Newow 模式不初始化当前版研究组件，当前模式不请求 Newow。

## Task 11：牛哇主图

绘制日K、成交量、黄蓝带、BUILD/CLEAR、D1/D2/D3、杯柄和 rollover seam；不实现三个副图、目标价、吸筹价、收益曲线或假按钮。

## Task 12：解读与历史弹层

只展示参考资料支持的趋势、D123、杯柄解释和动态事实；不增加仓位、自动下单、收益承诺或未确认文案。

## Task 13：E2E 与视觉对照

以用户提供的真实牛哇录屏/截图为唯一 UI 参考；手机 414×896 为首要视口。无法确认的内容标记 `REFERENCE_INSUFFICIENT`，不得自行探索替代。

## Task 14：最终因果、回归和文档 Review

运行 Newow 核心、API、Web、E2E 和现有 Market 回归；按真实命令证据更新状态。`develop` 集成不等于 release、Runtime 或 Alert 授权。

---

# Slice B 验收清单

必须全部满足：

- [ ] 只新增杯柄专用 Kernel 与统一 D1 Engine；
- [ ] 没有通用 Pattern/Structure 平台；
- [ ] 前置趋势、10%杯深、V形、柄长、宽幅震荡、下跌反弹、缩量和放量均有独立测试；
- [ ] Pivot 在 confirmed_at 前不可使用；
- [ ] READY 后 L/B/R/H/P 和 score 永不改变；
- [ ] FORMING 使用 45/60 门槛，不再使用错误的 65/100；
- [ ] H 的确认延迟计入 5–15 根柄长；
- [ ] P 排除 H 确认 Bar，避免同 Bar 自引用；
- [ ] 无量几何突破不会延迟补认；
- [ ] 同 Bar READY + BREAKOUT 生成两个关联 Marker；
- [ ] EXPIRED Marker 已加入；
- [ ] Engine Marker 使用 family order；
- [ ] Slice A golden 在 Engine 中逐字段不变；
- [ ] rollover 无伪 Marker、无跨合约杯柄；
- [ ] batch / incremental / prefix / restore / future-tail 全部一致；
- [ ] 杯柄诊断不会抹掉合法趋势带与 D123；
- [ ] 无 API、Web、DB、Redis、Worker、Runtime、Alert、通知或交易语义；
- [ ] 独立 Review 无阻塞问题。

# 当前计划状态

```text
SLICE_A_IN_DEVELOP
SLICE_B_SPEC_COMPLETE
SLICE_B_IMPLEMENTATION_PLAN_ALIGNED
SLICE_B_IMPLEMENTATION_NOT_STARTED
SLICE_C_D_E_DEFERRED
RUNTIME_NOT_CHANGED
ALERT_NOT_CHANGED
DATA_NOT_CHANGED
```
