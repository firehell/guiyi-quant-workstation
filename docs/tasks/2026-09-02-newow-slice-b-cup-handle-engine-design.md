# Newow Slice B · 杯柄 Kernel 与统一 D1 Engine Spec

日期：2026-09-02  
状态：`SPEC_INTERNAL_REVIEW_PASSED / IMPLEMENTATION_NOT_STARTED`  
规划基线：`develop@a65836138d178c01da5e398559fbbe92d857198f`  
父级设计：`docs/tasks/2026-09-01-newow-trend-v1-design.md`  
父级计划：`docs/tasks/2026-09-01-newow-trend-v1-implementation-plan.md`  

> 本文件是 Newow V1 **Slice B** 的唯一精确设计源。它只覆盖杯柄专用 Kernel 与统一 `NewowTrendD1Engine`。与父级设计第 14 节、父级计划 Task 4–5 发生冲突时，以本文为准；Slice A 已进入 `develop` 的黄蓝趋势带与 D1/D2/D3 合同保持不变。

## 1. Slice B 目标

Slice B 完成牛哇日线趋势策略计算核心的最后两块：

```text
Slice A 已完成
├── 黄蓝趋势带
├── 建仓 / 清仓
└── D1 / D2 / D3

Slice B 本次完成
├── 杯柄专用 Kernel
└── 统一 NewowTrendD1Engine
```

完成后形成唯一逐 Bar 入口：

```python
NewowTrendD1Engine.step(completed_d1_bar)
```

它在同一根 `actual_dominant + completed D1` 上依次产生：

```text
黄蓝趋势状态
建仓 / 清仓 Marker
D1 / D2 / D3 Marker
杯柄 FORMING / READY / BREAKOUT / WEAKENED / INVALIDATED / EXPIRED
统一 NewowTrendFrame
```

本 Slice 不接真实 MarketDataService、HTTP、Web、全市场扫描、Shadow、Alert、Runtime 或通知。

## 2. 产品价值与设计原则

杯柄不是牛哇趋势策略本身，而是牛哇趋势主图中的唯一命名形态 Setup。Slice B 的价值是：

1. 将 v3.6 明确强调的前置趋势、10% 杯深、V 形扣分、柄长收紧、柄部缩量和突破放量转成透明可复算规则；
2. 严格区分 `pivot_at` 与 `confirmed_at`，避免历史图看起来准确、实际信号依赖未来数据；
3. 将 Slice A 的三个独立 Kernel 组合为唯一增量引擎，避免 Historical、API 和 Web 后续各自复制公式；
4. 在不建设通用 Pattern 平台的前提下，提供足够完整的杯柄形成、确认、突破和失效生命周期；
5. 保持个人项目可理解、可测试和可维护。

核心原则：

```text
只做杯柄，不做通用形态平台
只使用 completed D1
只使用同一真实物理合约段
FORMING 可以演化
READY 后冻结
未来数据不能改写旧事实
杯柄 Kernel 不读取黄蓝带，二者在 Engine 中并列汇总
牛哇蓝色仍表示空仓，不产生期货空单
```

## 3. 明确范围

### 3.1 包含

```text
杯柄专用 Wilder ATR14
杯柄专用因果 Pivot Tracker
看涨 / 看跌杯柄方向归一化
L / B / R / H / P 锚点
前置趋势过滤
杯体深度、时长与杯口过滤
U 形纯度与 V 形扣分
宽幅震荡过滤
柄部长度、深度、位置与回撤过滤
柄部缩量
突破实体与突破放量
100 分透明评分
FORMING / READY / BREAKOUT / WEAKENED / INVALIDATED / EXPIRED
不可变杯柄 Marker
统一 D1 Engine
完整 prefix / batch-incremental / restore / rollover 测试合同
```

### 3.2 不包含

```text
其他命名形态
通用 Swing / Structure Graph
Lux Range
Phase Lite
目标价与止损价
真实仓位、OPEN/CLOSE、订单、Episode、PnL
MarketDataService application service
API / Web / UI
active60 / Shadow / Alert / PushPlus / Runtime
参数自动优化、收益择优或机器学习
```

## 4. Slice A 依赖合同

Slice B 只消费当前 `develop` 已存在的：

```text
packages/quant-core/guiyi_quant/newow/models.py
packages/quant-core/guiyi_quant/newow/profile.py
packages/quant-core/guiyi_quant/newow/trend_band.py
packages/quant-core/guiyi_quant/newow/escape_d123.py
```

Slice A 已冻结：

```text
NewowDailyBar
TrendBandState / TrendTransition
NewowMainMarker / NewowMarkerType
NewowTrendBandPoint
NewowTrendFrame
NewowTrendProfile / NEWOW_TREND_D1_V1
TrendBandStateValue / step_trend_band
EscapeState / step_escape_d123
```

Slice B 不修改黄蓝趋势带和 D1/D2/D3 公式。仅在兼容前提下扩展杯柄、统一 Engine 和它们所需的 typed contracts/profile 参数。

## 5. 父级设计 Review 后的规范性修正

本次设计 Review 发现并修正十一项实现歧义：

1. **FORMING 评分矛盾。** 父级设计要求 `FORMING >= 65`，但杯柄未形成时前三项满分只有 60；本文改为 `body_score >= 45 / 60`。
2. **锚点类型不足。** 当前 `NewowCupHandleOverlay` 只保存日期，无法同时表达价格、`pivot_at`、`confirmed_at` 和 Pivot 索引；本文增加 typed `CupPivot`。
3. **EXPIRED 事件缺失。** `CupHandleState` 有 `EXPIRED`，但 `NewowMarkerType` 没有对应 Marker；本文要求增加 `CUP_HANDLE_EXPIRED`。
4. **前置趋势窗口不明确。** “20–60 根”此前没有确定如何选；本文冻结候选窗口、方向斜率、强度计算与排序。
5. **突破位 P 不明确。** 本文冻结 P 的取值区间并排除 READY 确认 Bar，防止同 Bar 自引用。
6. **量能窗口不明确。** 本文冻结右侧上涨、柄部、柄前 20 日与突破前 20 日的精确窗口。
7. **柄部时长口径不完整。** 父级设计只描述柄部视觉长度；本文用 `H.confirmed_index - R.pivot_index` 作为可执行柄长，确认延迟也计入 5–15 根限制。
8. **READY 后生命周期不完整。** 本文冻结 WEAKENED、INVALIDATED、EXPIRED 和内部 archive 行为。
9. **Marker priority 与 Engine 顺序冲突。** Slice A 的 D1 priority 高于 BUILD；本文规定 Engine 使用 family order，不按全局 priority 混排。
10. **杯柄 warm-up 与几何资格混淆。** 同合约 rank1 前 Bar 只预热 ATR，不得参与 Pivot、杯体、柄部或量能几何。
11. **测试无法观察拒绝原因。** 本文增加 `CupHandleStepResult.diagnostics` 与 `candidate_checks`，硬负例无需把无效形态伪装成主图 Overlay。

这些修正不改变用户已经确认的产品范围，只把不确定实现点收敛为可测试合同。

## 6. 源码边界

Slice B 只允许新增或修改：

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py       # 导出 Slice B 类型与函数
├── models.py         # 扩展 Cup typed contracts / EXPIRED marker / frame metadata
├── profile.py        # 增加杯柄精确参数
├── cup_handle.py     # 杯柄专用实现
└── engine.py         # 唯一 completed-D1 编排入口

services/quant-api/tests/newow/
├── fixtures.py
├── test_models_profile.py
├── test_cup_handle.py
└── test_engine_causality.py
```

禁止创建：

```text
patterns/ 通用目录
swing.py
structure.py
phase.py
target_risk.py
execution.py
数据库、缓存、API、Web 或 Runtime 文件
```

## 7. 数据与身份合同

杯柄和 Engine 只接受已经由 Slice A 校验的 `NewowDailyBar`：

```text
series_kind = actual_dominant
frequency   = 1d
completed   = true
product     = lowercase
physical_contract = uppercase
segment_id  = non-empty
bar_end     = timezone-aware
OHLC        = finite positive Decimal
volume / OI = non-negative
```

额外顺序要求由 Engine 负责：

```text
bar_end 严格递增
trading_day 严格递增
同一 bar_end 不得重复
同一 segment 内 observation_eligible 只能 False → True，不能 True → False
```

错误码：

```text
NEWOW_BAR_DUPLICATE
NEWOW_BAR_OUT_OF_ORDER
NEWOW_TRADING_DAY_OUT_OF_ORDER
NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION
NEWOW_ENGINE_STATE_INVALID
```

## 8. Profile 扩展

`NewowTrendProfile` 增加以下字段，全部冻结在 `NEWOW_TREND_D1_V1`：

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

保留 Slice A 已存在：

```text
cup_reversal_atr                  = 1.25
cup_min_leg_bars                  = 3
cup_history_limit                 = 220
cup_max_confirmed_pivots          = 32
cup_max_candidate_checks_per_step = 256
```

所有阈值属于 `newow_cup_handle_v1` clean-room 版本；不得根据历史收益在实现阶段修改。

## 9. Typed contracts

### 9.1 `CupPivot`

```python
@dataclass(frozen=True, slots=True)
class CupPivot:
    kind: CupPivotKind              # HIGH | LOW
    price: Decimal
    pivot_at: datetime
    confirmed_at: datetime
    pivot_index: int                # eligible D1 index in the physical segment
    confirmed_index: int
    atr_at_pivot: float
```

约束：

```text
confirmed_at >= pivot_at
confirmed_index >= pivot_index
price > 0
atr_at_pivot > 0 且 finite
同一 tracker 的 Pivot 必须 HIGH / LOW 交替
```

### 9.2 `NewowCupHandleOverlay`

将现有日期型锚点升级为：

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

时间语义：

```text
FORMING.confirmed_at = max(L/B/R.confirmed_at)
FORMING.first_seen_at = body Gate 首次通过的当前 Bar
READY.confirmed_at = H、P、柄部与缩量 Gate 首次全部可知的当前 Bar
state_changed_at = 当前状态最近一次变化的 Bar
```

约束：

- FORMING 必须已有 L/B/R，但允许 `handle_extreme` 与 `pivot_price` 为 `None`；
- READY 及以后必须已有 H 和 P；
- READY 后锚点、P、`confirmed_at`、score、breakdown、volume facts 不得改变；
- `state_changed_at` 随后续状态变化更新，其他冻结字段保持原值；
- 进入主图的 FORMING/READY/BREAKOUT 等合法 Overlay 的 `hard_failures` 必须为空；拒绝原因只放在 Step diagnostics。

### 9.3 `NewowMarkerType`

增加：

```text
CUP_HANDLE_EXPIRED
```

不增加 OPEN、CLOSE、POSITION 或 ORDER。

### 9.4 `NewowTrendFrame`

扩展为：

```python
@dataclass(frozen=True, slots=True)
class NewowTrendFrame:
    bar: NewowDailyBar
    trend_band: NewowTrendBandPoint
    markers: tuple[NewowMainMarker, ...]
    cup_handle: NewowCupHandleOverlay | None
    rollover_started: bool
    diagnostics: tuple[str, ...]
```

## 10. 杯柄公开接口与内部状态

### 10.1 公开接口

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

### 10.2 内部状态

`cup_handle.py` 使用私有、tuple-based、可序列化状态：

```python
@dataclass(frozen=True, slots=True)
class CupHandleStateValue:
    atr_state: WilderAtrState
    pivot_tracker: CupPivotTrackerState
    eligible_bars: tuple[CupBarSnapshot, ...]
    confirmed_pivots: tuple[CupPivot, ...]
    active_candidate: NewowCupHandleOverlay | None
    emitted_milestones: tuple[str, ...]
    recent_terminal_candidate_ids: tuple[str, ...]
    physical_contract: str | None
    segment_id: str | None
    eligible_started: bool
```

边界：

```text
eligible_bars <= 220
confirmed_pivots <= 32
recent_terminal_candidate_ids <= 32
```

不持久化数据库，不依赖系统时钟、网络、文件或 UI。

## 11. Wilder ATR14

杯柄内部只为 Pivot 与标准化使用 Wilder ATR14：

```text
TR_t = max(
    High_t - Low_t,
    abs(High_t - Close_t-1),
    abs(Low_t - Close_t-1)
)
```

Seed：

```text
首个 ATR14 = 前 14 个有限 TR 的简单平均
```

递推：

```text
ATR_t = (13 × ATR_t-1 + TR_t) / 14
```

规则：

- 同一物理合约的 `observation_eligible=False` Bar 可以预热 ATR；
- 这些 Bar 不进入 Pivot、杯体、柄部、成交量窗口或候选 ID；
- 物理合约或 segment 改变时 ATR 也重置；
- ATR 不足时只返回 `CUP_ATR_UNAVAILABLE`，不猜测 Pivot。

## 12. 专用因果 Pivot Tracker

### 12.1 状态

```text
SEEK_DIRECTION
UP_LEG
DOWN_LEG
```

状态保存：

```text
当前最高 / 最低极值
极值发生 Bar
极值 ATR
上一已确认 Pivot
当前 eligible index
```

### 12.2 高点确认

在 `UP_LEG`：

1. 若当前 high 创新高，更新 extreme、`pivot_at` 与 `atr_at_extreme`；
2. 当前 completed close 满足：

```text
close <= extreme_high - 1.25 × atr_at_extreme
```

3. 从上一 Pivot 到该极值至少 3 根 eligible D1；
4. 在当前 Bar 结束时确认此前高点。

输出：

```text
kind            = HIGH
pivot_at        = 极值 Bar 时间
confirmed_at    = 当前 Bar 时间
pivot_index     = 极值 eligible index
confirmed_index = 当前 eligible index
```

随后进入 `DOWN_LEG`，当前 Bar 的 low 成为新下降腿初始极值。

### 12.3 低点确认

完全镜像：

```text
close >= extreme_low + 1.25 × atr_at_extreme
```

### 12.4 初始方向

`SEEK_DIRECTION` 同时跟踪起始最高与最低：

- 价格从已跟踪低点上升达到确认距离时，先确认 LOW，进入 UP_LEG；
- 价格从已跟踪高点下跌达到确认距离时，先确认 HIGH，进入 DOWN_LEG；
- 同一 completed Bar 两侧条件同时成立时，选择归一化反转距离更大的方向；若仍相同，选择极值 `pivot_at` 更早者；仍相同则 HIGH 优先。

### 12.5 因果边界

```text
pivot_at 是绘制位置
confirmed_at 是最早可使用时间
```

候选枚举只能使用 `confirmed_at <= current_bar_end` 的 Pivot。任何未确认极值不得进入 L/B/R/H。

## 13. 候选枚举

### 13.1 方向归一化

使用：

```text
sign = +1  看涨
sign = -1  看跌
normalized_price = sign × actual_price
```

在归一化空间中，两种方向都表现为：

```text
高位左杯口 L
→ 低位杯底 B
→ 高位右杯口 R
→ 较浅柄部低点 H
→ 向上突破 P
```

看跌结果只作为风险形态展示，不生成期货空单动作。

### 13.2 枚举范围

最多 32 个确认 Pivot，因此同方向 rim Pivot 最多 16 个。

每个步骤：

1. 枚举同方向的 L/R rim Pivot 对；
2. 只保留 `25 <= R.index - L.index + 1 <= 90`；
3. B 取 L/R 之间归一化价格最低的反方向 Pivot，价格相同时取更早的 Pivot；
4. H 取 R 之后、**从 R 到 H 确认 Bar 共 5–15 根**范围内归一化价格最低的已确认反方向 Pivot，价格相同时取更晚的 Pivot；
5. 若 H 尚未确认，可以产生 FORMING，但不能产生 READY；
6. 看涨和看跌总候选检查数不得超过 256。

若下一次检查会超限：

```text
返回 CUP_CANDIDATE_LIMIT_EXCEEDED
本 Bar 不产生新的 READY / BREAKOUT Marker
保留上一合法 active candidate
```

### 13.3 Candidate ID

FORMING 到终态共享：

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

H 不参与 ID，以保证 FORMING 到 READY 期间 ID 稳定。一个 L/B/R 组合终止后不得使用另一个 H 重新激活；新的候选必须有新的 R。

### 13.4 Primary 选择

已有 READY / BREAKOUT / WEAKENED active candidate 在终止前优先，不被后来更高分候选替换。

没有冻结 candidate 时，排序：

```text
1. hard-valid
2. BREAKOUT > READY > FORMING
3. score 降序
4. confirmed_at 降序
5. candidate_id 升序
```

FORMING 可随新 Bar 切换为更优候选，不产生不可变 Marker。

## 14. 前置趋势

对 L 前的每个可用窗口 `k = 20..60`：

```text
start = L.index - k
move  = sign × (L.price - close_start)
return_pct = move / close_start
move_atr   = move / median(ATR[start..L])
normalized_slope = OLS_Slope(sign × close[start..L])
```

窗口合法条件：

```text
normalized_slope > 0
AND
(return_pct >= 10% OR move_atr >= 4.0)
```

从合法窗口中按以下顺序选择：

```text
1. max(return_pct / 0.10, move_atr / 4.0) 最大
2. min(return_pct / 0.10, move_atr / 4.0) 最大
3. k 更小（更接近 L）
```

无合法窗口：

```text
PRETREND_NOT_CONFIRMED
```

该 OLS 方向条件是归一量化对 v3.6“左高前趋势确认 / 过滤下跌反弹”的 clean-room 解释，不声称来自牛哇私有公式。

## 15. 杯体几何

归一化定义：

```text
rim_price      = (L + R) / 2
cup_depth      = rim_price - B
cup_depth_pct  = cup_depth / abs(rim_price)
cup_depth_atr  = cup_depth / median(ATR[L..R])
rim_gap_pct    = abs(L - R) / abs(rim_price)
rim_gap_atr    = abs(L - R) / median(ATR[L..R])
cup_bars       = R.index - L.index + 1
```

硬条件：

```text
25 <= cup_bars <= 90
10% <= cup_depth_pct <= 50%
cup_depth_atr >= 3.0
rim_gap_pct <= 5%
rim_gap_atr <= 1.5
```

失败码：

```text
CUP_DURATION_OUT_OF_RANGE
CUP_DEPTH_BELOW_10_PERCENT
CUP_DEPTH_ABOVE_50_PERCENT
CUP_DEPTH_BELOW_3_ATR
RIM_GAP_PERCENT_EXCEEDED
RIM_GAP_ATR_EXCEEDED
```

## 16. U 形纯度

### 16.1 底部停留

```text
bottom_zone_top = B + 0.25 × cup_depth
```

使用归一化 completed close，计算包含 B.pivot_index 的最大连续区间：

```text
close <= bottom_zone_top
```

得到 `bottom_span_bars`：

```text
>= 5 根：满分
3–4 根：合格
2 根：明显扣分
1 根：V_BOTTOM_SINGLE_BAR，不能 READY
```

### 16.2 左右腿比例

```text
left_leg_bars  = B.index - L.index
right_leg_bars = R.index - B.index
leg_ratio      = left_leg_bars / right_leg_bars
```

```text
0.50..2.00：正常
1/3..3.00：允许但扣分
范围外：LEG_RATIO_EXTREME，拒绝
```

### 16.3 中轴往返

```text
midline = B + 0.50 × cup_depth
```

统计 L 到 R 之间归一化 close 在中轴上下的有效符号变化，等于中轴的 Bar 沿用上一个非零方向：

```text
0–3 次：允许
4–5 次：宽幅震荡重扣分
>5 次：MIDLINE_CROSSINGS_EXCEEDED，拒绝
```

## 17. 柄部与突破位

### 17.1 柄部时长与深度

柄长以系统真正可确认 H 的时间为准：

```text
handle_bars = H.confirmed_index - R.pivot_index
```

这样确认延迟也计入 v3.6 的“柄部长短收紧”，不会把视觉上 10 根、实际到第 18 根才确认的柄部当作合格短柄。

归一化定义：

```text
handle_depth       = R - H
handle_depth_pct   = handle_depth / abs(R)
handle_retrace     = handle_depth / (R - B)
```

硬条件：

```text
5 <= handle_bars <= 15
handle_depth_pct <= 15%
handle_retrace <= 1/3
H >= B + 0.50 × cup_depth
```

失败码：

```text
HANDLE_DURATION_OUT_OF_RANGE
HANDLE_DEPTH_EXCEEDED
HANDLE_RETRACE_EXCEEDED
HANDLE_BELOW_CUP_MID
```

### 17.2 突破位 P

READY 确认时冻结：

```text
P = 看涨时 max(high)，看跌时 min(low)
```

取值窗口：

```text
R.pivot_index + 1
到
H.confirmed_index - 1
```

明确排除：

```text
R Pivot Bar
H 的 READY 确认 Bar
```

这样 P 只使用 READY 确认前已经完成的数据，允许当前 READY Bar 同时成为突破 Bar，而不会用当前 high 反向抬高 P。

窗口为空或 P 非有限：

```text
HANDLE_PIVOT_UNAVAILABLE
```

## 18. 成交量窗口

全部只使用 eligible、同物理合约 completed D1：

```text
right_leg_volume:
  B.pivot_index + 1 .. R.pivot_index

handle_volume:
  R.pivot_index + 1 .. H.confirmed_index - 1

handle_baseline_volume:
  截至 R.pivot_index 的最近 20 根（含 R）

breakout_volume20:
  突破 Bar 之前最近 20 根（不含当前突破 Bar）
```

所有比值使用中位数。

READY 量能硬条件：

```text
median(handle_volume) <= 0.80 × median(right_leg_volume)
median(handle_volume) <= 0.90 × median(handle_baseline_volume)
```

若任一分母为 0、窗口不足或数据非有限：

```text
HANDLE_VOLUME_UNAVAILABLE
```

候选可以保持 FORMING，但不能 READY。

突破硬条件：

```text
当前 normalized close > P + 0.10 × ATR_current
前一 eligible close <= P + 0.10 × ATR_previous
当前 volume >= 1.20 × median(breakout_volume20)
当前 volume >= 1.50 × frozen median(handle_volume)
```

几何突破但量能未通过：

```text
记录 BREAKOUT_VOLUME_UNCONFIRMED diagnostic
保持 READY
不生成 BREAKOUT Marker
```

只有之后先重新回到阈值下方、再重新放量上穿，才可产生 BREAKOUT。

## 19. 100 分评分

### 19.1 前置趋势：15 分

```text
return 与 ATR 条件都通过：15
只通过一个，且通过项强度 >= 1.5 倍阈值：12
只通过一个：10
都不通过：硬失败
```

### 19.2 杯体几何：25 分

```text
时长：
  35–70 根 = 5
  25–34 或 71–90 = 3

深度百分比：
  10%–35% = 8
  >35%–50% = 4

深度 ATR：
  >=4 ATR = 5
  3–<4 ATR = 3

杯口对齐：
  gap <=2.5% 且 <=0.75 ATR = 7
  其余但通过硬 Gate = 5
```

### 19.3 U 形纯度：20 分

```text
底部停留：
  >=5 = 8
  3–4 = 6
  2 = 2
  1 = 0 且不能 READY

左右腿：
  0.75–1.33 = 6
  0.50–2.00 = 4
  1/3–3.00 = 2

中轴穿越：
  <=1 = 6
  2 = 4
  3 = 2
  4–5 = 0
```

### 19.4 柄部质量：20 分

```text
柄长：
  7–10 = 6
  5–6 或 11–15 = 4

柄深：
  <=8% = 5
  >8%–12% = 3
  >12%–15% = 1

回撤比例：
  <=20% = 5
  >20%–28% = 3
  >28%–1/3 = 1

位于杯体上半部：4
```

### 19.5 量能结构：20 分

READY 前最多 14 分：

```text
柄部 / 右侧上涨：
  <=0.65 = 7
  >0.65–0.75 = 5
  >0.75–0.80 = 3

柄部 / 柄前20日：
  <=0.75 = 7
  >0.75–0.85 = 5
  >0.85–0.90 = 3
```

突破时增加 6 分：

```text
两个突破量能 Gate 同时通过 = 6
否则 = 0 且不能 BREAKOUT
```

### 19.6 状态门槛

修正父级设计中的 FORMING 矛盾：

```text
body_score = 前置趋势 + 杯体几何 + U形纯度，满分60
base_score = body_score + 柄部质量 + READY量能，满分94
full_score = base_score + 突破量能，满分100
```

```text
FORMING：
  杯体硬 Gate 通过
  U形无硬失败
  body_score >= 45 / 60

READY：
  FORMING Gate 通过
  H 已确认
  柄部与缩量硬 Gate 通过
  base_score >= 80 / 94

BREAKOUT：
  READY Gate 通过
  实体与量能突破硬 Gate 通过
  full_score >= 85 / 100
```

固定 breakdown keys：

```text
pretrend
cup_geometry
u_shape_purity
handle_quality
volume_structure
```

## 20. 杯柄生命周期

```text
NONE
  ↓
FORMING
  ↓
READY
  ↓
BREAKOUT
  ↓
WEAKENED
  ↓
INVALIDATED
```

READY 还可以：

```text
READY → INVALIDATED
READY → EXPIRED
```

### 20.1 FORMING

- L/B/R 已确认；
- body Gate 通过；
- H 尚未确认，或柄部/缩量尚未满足 READY；
- 可以随新 Bar 更新、切换候选或消失；
- 不生成 Marker。

### 20.2 READY

首次满足 READY Gate：

- 冻结 L/B/R/H/P；
- 冻结 `confirmed_at`、score、breakdown 与 volume facts；
- 生成 `CUP_HANDLE_READY`；
- 后续不得被更高分候选替换。

### 20.3 READY 与 BREAKOUT 同 Bar

若 H 在当前 Bar 首次确认，同时当前 completed close/volume 已满足突破：

```text
同一 Bar 依次生成：
1. CUP_HANDLE_READY
2. CUP_HANDLE_BREAKOUT
```

两个 Marker 分别不可变，BREAKOUT 关联 READY。

### 20.4 BREAKOUT

首次合法放量上穿 P：

- 生成 `CUP_HANDLE_BREAKOUT`；
- state 为 BREAKOUT；
- 不表示真实开仓。

### 20.5 WEAKENED

突破后，在方向归一化空间：

```text
normalized_close < normalized_P
AND
normalized_close >= normalized_H - 0.10 × ATR_current
```

首次成立生成 `CUP_HANDLE_WEAKENED`，之后不重新回到 BREAKOUT；V1 不实现“二次突破恢复”。

### 20.6 INVALIDATED

READY、BREAKOUT 或 WEAKENED 后，在方向归一化空间：

```text
normalized_close < normalized_H - 0.10 × ATR_current
```

首次成立生成 `CUP_HANDLE_INVALIDATED`，并终止 active candidate。

### 20.7 EXPIRED

READY 后 20 根 eligible D1 内没有合法 BREAKOUT：

```text
生成 CUP_HANDLE_EXPIRED
终止 active candidate
```

### 20.8 内部 archive

BREAKOUT 连续 20 根 eligible D1 未 WEAKENED / INVALIDATED：

- 将 candidate 从 active state 清除；
- 不生成新的用户 Marker；
- candidate_id 进入 bounded terminal set，防止相同 L/B/R 被重新发现；
- 历史 Frame 中的 BREAKOUT 事实不变。

终止 Bar 当天不选择新 candidate；从下一 eligible Bar 才可形成新候选。

## 21. 杯柄 Marker 与身份

Marker 类型：

```text
CUP_HANDLE_READY
CUP_HANDLE_BREAKOUT
CUP_HANDLE_WEAKENED
CUP_HANDLE_INVALIDATED
CUP_HANDLE_EXPIRED
```

Marker ID：

```text
sha256(candidate_id | marker_type | bar_end)
```

关系：

```text
BREAKOUT.related = READY
WEAKENED.related = READY + BREAKOUT
INVALIDATED.related = READY + BREAKOUT/WEAKENED（存在者）
EXPIRED.related = READY
```

所有 Marker `trigger_facts` 至少包括：

```text
candidate_id
direction
state_before
state_after
L/B/R/H/P
score
score_breakdown
volume_facts
formula_version
```

不得写入收益、仓位、止损执行或未来结果。

## 22. 统一 `NewowTrendD1Engine`

杯柄 Kernel 与趋势带相互独立：

```text
trend_band.py 不读取 cup_handle.py
cup_handle.py 不读取 trend_band.py
engine.py 只负责同 Bar 编排和汇总
```

杯柄几何即使与当前黄蓝状态不一致，也按自身规则计算并返回；后续 Web 可以并列展示，不能在 Slice B 中用黄蓝带静默删除杯柄。

### 22.1 Engine State

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
```

### 22.2 Step / Batch 接口

```python
@dataclass(frozen=True, slots=True)
class NewowTrendD1StepResult:
    state: NewowTrendD1EngineState
    frame: NewowTrendFrame


class NewowTrendD1Engine:
    @classmethod
    def initial(cls) -> NewowTrendD1Engine: ...

    def step(self, bar: NewowDailyBar) -> NewowTrendD1StepResult: ...


def calculate_newow_trend_frames(
    bars: tuple[NewowDailyBar, ...],
) -> tuple[NewowTrendFrame, ...]: ...
```

Historical 与未来盘后增量必须调用同一 `step`。

### 22.3 固定处理顺序

```text
1. 校验 Engine state 与 Bar 顺序
2. 检测物理合约 / segment rollover
3. rollover 时先统一重置三个 sub-state
4. step_trend_band
5. step_escape_d123
6. step_cup_handle
7. 按 family order 汇总 Marker
8. 冻结 NewowTrendFrame
9. 保存最后 Bar identity
```

### 22.4 Rollover

物理合约或 segment 改变：

```text
rollover_started = true
三个 sub-state 重置
当前新合约 Bar 只作为新状态第一根输入
不生成 BUILD / CLEAR
不生成 D1 / D2 / D3
不延续或完成旧杯柄
```

旧 active 杯柄不生成 INVALIDATED 或 EXPIRED，因为换月是数据身份结束，不是策略形态失效。

### 22.5 observation eligibility

同一 segment：

```text
False → False：纯数值 warm-up
False → True：正式观察开始
True → True：正常
True → False：拒绝
```

对杯柄：

```text
False Bar 只预热 ATR
Pivot / geometry / volume / candidate 全部从首根 True Bar开始
```

对 Slice A 黄蓝与 D123：保持现有已实现 warm-up 语义，不修改。

### 22.6 Marker 顺序

Engine 不按全局 `priority` 直接混排，固定 family order：

```text
1. BUILD / CLEAR
2. D1 / D2 / D3（内部 D1 > D2 > D3）
3. CUP READY / BREAKOUT / WEAKENED / INVALIDATED / EXPIRED
```

同一 family 再按：

```text
family-specific order
marker_type.value
marker_id
```

这样 D1 的 `priority=300` 不会跑到 BUILD/CLEAR 之前，同时核心仍保留同 Bar 全部 D 信号。

## 23. Engine fail-closed 行为

### 23.1 调用错误

下列问题抛 `ValueError`，调用者必须修正输入：

```text
duplicate Bar
out-of-order Bar
trading_day 逆序
observation_eligible 回退
```

### 23.2 恢复状态损坏

如果 restored Engine state 或任一 sub-state 结构不一致：

```text
当前 Frame = UNAVAILABLE
markers = ()
diagnostics += NEWOW_ENGINE_STATE_INVALID
返回 initial state
```

不得在损坏状态上继续计算或只重置其中一个子模块。

### 23.3 候选级问题

以下只影响杯柄，不抹掉同 Bar 的趋势带与 D123：

```text
CUP_ATR_UNAVAILABLE
CUP_HISTORY_INSUFFICIENT
CUP_CANDIDATE_LIMIT_EXCEEDED
HANDLE_VOLUME_UNAVAILABLE
BREAKOUT_VOLUME_UNCONFIRMED
```

它们进入 Frame diagnostics，黄蓝和 D123 仍按自己的合法结果输出。

## 24. 计算与内存边界

每个物理 segment：

```text
ATR state：14期递推所需最小状态
eligible bars：最多220
confirmed pivots：最多32
candidate checks：每Bar最多256
terminal candidate IDs：最多32
active candidate：最多1
```

禁止：

```text
全历史组合枚举
递归搜索任意 Pivot 组合
pandas / scipy / sklearn
机器学习或图像识别
按品种保存不同参数
```

## 25. 测试与验收矩阵

### 25.1 Contracts / Profile

必须测试：

```text
CupPivot 不可变与字段约束
Overlay 各 state 的字段完整性
CUP_HANDLE_EXPIRED enum
所有新 Profile 参数固定
非法比例、负窗口、NaN 参数 fail-closed
```

### 25.2 Pivot 因果性

```text
pivot_at < confirmed_at 的典型案例
确认前 prefix 不得看到 Pivot
追加未来数据不得移动已确认 Pivot
HIGH / LOW 必须交替
同 Bar 双向满足时 tie-break 稳定
ineligible Bar 不进入 geometry
rollover 清空 Pivot
batch / step / restore 一致
```

### 25.3 正例

```text
真看涨杯柄 FORMING → READY → BREAKOUT
真看跌杯柄方向镜像
READY 与 BREAKOUT 同 Bar
BREAKOUT → WEAKENED
READY / WEAKENED → INVALIDATED
READY → EXPIRED
BREAKOUT 20 Bar 后内部 archive
```

### 25.4 硬负例

每项独立 fixture：

```text
前置趋势不足
下跌反弹
杯体 <25 或 >90
杯深 <10%
杯深 >50%
杯深 <3 ATR
左右杯口差异过大
单根 V 形底
左右腿极端失衡
中轴往返 >5
柄部 <5 或 >15（按 confirmed handle length）
柄深 >15%
柄部回撤 >1/3
柄部跌入杯体下半部
柄部不缩量
几何突破但不放量
跨主力合约拼接
```

拒绝 fixture 通过 `CupHandleStepResult.diagnostics` 断言原因，不向主图返回带 hard failure 的假 Overlay。

### 25.5 边界与评分

```text
10%、50%、3 ATR 精确边界
5%、1.5 ATR 杯口边界
5 / 15 confirmed 柄长边界
15% 柄深边界
1/3 回撤边界
0.80 / 0.90 缩量边界
1.20 / 1.50 突破量边界
45 / 80 / 85 分门槛
score breakdown 总和精确
FORMING 不再错误要求 65/100
```

### 25.6 Candidate 稳定性

```text
FORMING 可以演化
READY 后 L/B/R/H/P/score 不变
更高分新候选不能替换 READY
终态后相同 L/B/R 不得重生
candidate_id / marker_id 确定性
候选检查超限 fail-closed
```

### 25.7 Engine

```text
Slice A 公式结果在统一 Engine 中逐字段不变
统一 Marker family order
同 Bar 多 D 信号全部保留
同 Bar READY + BREAKOUT 顺序固定
full prefix invariance
batch / incremental parity
多个 cut point restore parity
future-tail mutation 不改旧 Frame
重复 / 逆序 Bar 拒绝
eligibility 回退拒绝
rollover 无伪 Marker
杯柄错误不抹掉趋势与 D123
```

## 26. Slice B 完成定义

只有同时满足以下条件，Slice B 才可以进入下一阶段：

1. `cup_handle.py` 只实现杯柄专用逻辑，没有通用 Pattern/Structure 框架；
2. v3.6 六类改进均有独立测试：成交量、V形、前置趋势、柄长、10% 杯深、宽幅震荡/下跌反弹；
3. Pivot、候选、READY 和 Marker 通过 prefix、future-tail 与 restore 测试；
4. READY 后 L/B/R/H/P 与 score 永远不被未来数据改写；
5. 黄蓝与 D123 通过统一 Engine 后结果与 Slice A golden 完全一致；
6. 物理合约切换不能制造趋势 Marker、D123 或跨合约杯柄；
7. 核心只依赖标准库与 NumPy；
8. 没有 API、Web、数据库、Redis、Runtime、Alert 或通知修改；
9. 独立 formula/causality Review 与 scope/maintenance Review 均无阻塞问题；
10. 最终结论为 `SLICE_B_READY_FOR_INTEGRATION` 后，才允许进入 Slice C。

## 27. 下一阶段边界

Slice B 之后的唯一下一阶段是 Slice C：

```text
actual_dominant D1 MarketDataService 接入
按真实 rank1 segment 回放统一 Engine
无状态、有界 Detail Query
只读 API
```

Slice C 不得修改本文的杯柄公式、评分和生命周期；若真实牛哇参考证明算法不一致，应创建新的杯柄公式版本，而不是静默重写 V1 历史结果。

## 28. 设计自审结果

本次自审按占位符、内部一致性、范围、歧义、因果边界和个人维护成本检查，并已将问题直接修入正文：

- 未保留 TODO / TBD 或未定义公式；
- 修正 FORMING 评分不可能达到的问题；
- 修正 Overlay 无法表达每个 Pivot 确认时间的问题；
- 增加 StepResult，硬负例不再依赖伪 Overlay；
- 明确 FORMING/READY 的 `confirmed_at` 与 `first_seen_at`；
- 明确 P 与成交量窗口，消除同 Bar 自引用；
- 将柄长改为确认口径，避免确认过晚的长柄通过；
- 明确 READY、BREAKOUT、WEAKENED、INVALIDATED、EXPIRED 与内部 archive；
- 明确杯柄与黄蓝带彼此独立，只由 Engine 汇总；
- 明确 Engine family order，不复用冲突的全局 priority；
- 明确 ineligible Bar 只预热 ATR，不进入杯柄形态；
- 保持一个 active candidate、一个专用文件、固定内存上限，未引入平台化抽象；
- 没有把收益、仓位或自动交易重新带入设计。

Review 结论：

```text
SPEC_INTERNAL_REVIEW_PASSED
READY_FOR_SLICE_B_IMPLEMENTATION_PLAN_ALIGNMENT
SOURCE_IMPLEMENTATION_NOT_STARTED
```
