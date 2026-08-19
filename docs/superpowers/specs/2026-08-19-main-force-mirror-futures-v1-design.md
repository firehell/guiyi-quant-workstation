# 主力照妖镜·期货 V1 设计规格

> 状态：Design basis approved；本文为书面 Spec，待用户审阅后再进入 implementation plan。
>
> 日期：2026-08-19
>
> 规划基线：`develop@16d09ac0dad295763bf7552e07e06f3222c41c80`
>
> 现有版本：`main_force_mirror_v0` / `designed-v0`
>
> 新版本：`main_force_mirror_futures_v1` / `futures-research-v1`
>
> 公式与生命周期边界：本设计只建立期货专用 observation V1，不修改已经发布的 V0，不授权 Alert、通知、回测晋升、release、tag 或 Runtime promotion。

## 1. 结论

现有 `main_force_mirror_v0` 是一套 causal、Web-only、OHLCV 设计代理：

```text
CLV × 相对成交量
→ 六色观察状态
→ 单侧 HHV5 / BARSLAST10 “小心”
```

它满足“股票式高位警戒原型”的复现需要，但不适合作为期货长期版本，原因是：

1. “小心”只在短期高点状态重新激活时出现，只有追多一侧的风险语义；
2. 在 60m 图上固定使用 `HHV5 / BARSLAST10`，信号过密，不能表达一个完整方向 Episode；
3. 六色柱没有使用期货现成的 `open_interest`，无法区分上涨中的增仓与减仓，也无法区分下跌中的增仓与减仓；
4. `actual_dominant` 跨真实合约拼接时，若不显式按物理合约重置，价格与持仓跳变会伪造“主力行为”；
5. “70% 主力流出”不是当前 Bar 数据可以直接测量的事实，不能继续作为数值字段或确定性结论。

因此新增独立版本：

```text
main_force_mirror_futures_v1

OHLCV + Open Interest + Physical Contract Segment
→ 多头增仓 / 空头增仓 / 空头回补 / 多头减仓 / 换手
→ 追多小心 / 追空小心
→ 0..100 风险证据评分
→ 可解释 reason codes
→ Historical Shadow 统计
```

V1 的“70”表示**风险证据评分阈值 70/100**，不是资金流出比例、概率、会员席位结论或账户级事实。

## 2. 当前仓库事实

规划基线下：

- production Git release 与 Runtime 为 `v1.6.1`；V0 已随 v1.6.0 发布并继续存在于当前 Runtime 的 Web 观察面；
- Python Indicator Kernel 位于 `packages/quant-core/guiyi_quant/indicators/`，是指标业务口径唯一权威；
- V0 Python authority 为 `main_force_mirror.py`，Web mirror 为 `apps/quant-web/src/utils/mainForceMirror.ts`；
- 当前副图在 Lightweight Charts 最底部 pane 内通过 `MACD / 主力照妖镜` Tab 二选一；
- Canonical Bar 与 Web `BarData` 已包含 `open_interest / openInterest`；
- 5m/15m/30m/60m 聚合的 OI 取桶内最后一根 Canonical 1m Bar；
- `/api/v1/market/bars/page` 已返回 `resolved_contract_segments`，但 Web `useMarketSeries()` 当前只保留 bars 和 coverage，没有把每根 Bar 的真实物理合约身份传到指标层；
- WebSocket `snapshot` 已返回精确 `contract`，可用于给 completed Live/Post-close Bars 绑定物理合约；
- 当前没有会员多空持仓排名、逐笔主动买卖、Level-2 或账户身份数据。

所以 V1 可以使用现有可信数据完成“方向性持仓压力代理”，但不能声称识别了具体主力账户。

## 3. 产品目标

V1 首版只解决四个问题：

1. **识别价格运动由增仓还是减仓驱动**：区分多头增仓、空头增仓、空头回补和多头减仓；
2. **把“小心”改造成期货双向追价风险**：分别提示“追多小心”和“追空小心”；
3. **降低固定 HHV/BARSLAST 的重复噪声**：使用方向 Episode latch 与 re-arm，而不是每隔固定 K 线机械重发；
4. **积累可复盘证据**：输出分数、原因码、状态和后续 1/3/5/10 Bar 结果分布。

长期价值必须至少实现：

- 减少个人盯盘时对“上涨是多增还是空减、下跌是空增还是多减”的人工判断成本；
- 让追多/追空风险具有对称、可解释、可回看结构；
- 为后续研究“持仓确认是否提高警戒质量”积累事件证据。

## 4. 首版范围

首版精确范围：

```text
frequency   = 60m only
series_kind = contract | actual_dominant
status      = observation_only
web         = true
backtest    = false
live        = false
alert       = false
notification= false
auto_order  = false
```

说明：

- `web=true` 允许浏览器对 Historical 与 completed Live/Post-close Bars 做只读观察；
- `live=false` 表示不获得正式 live consumer、Runtime evaluator 或交易能力；
- `actual_dominant` 必须按真实 `physical_contract` 分段重置；
- `continuous` 首版明确不可用，不做 OI 解释；
- 1m/5m/15m/30m/1d/1w 首版明确不可用，不把 60m 参数机械复用到其他周期。

## 5. 明确不做

V1 首版不做：

- 不修改或删除 `main_force_mirror_v0`；
- 不把 V1 结果写回 V0 code、version 或 golden；
- 不引入交易所会员多空持仓排名、席位、Level-2、逐笔主动买卖或第二数据 provider；
- 不把 OI 增减解释成具体账户的净多、净空或资金净流入；
- 不创建 `outflow_ratio`、`main_force_ratio` 或“70% 已流出”字段；
- 不新增 Market Catalog 表、Canonical 字段、Parquet 副本或长期派生数据表；
- 不新增 API 写路径、数据库、migration、Redis 状态、worker、queue、outbox；
- 不新增 Alert Rule、Scope、Clawbot 通知、Execution Review 自动入口；
- 不恢复通用 backtest API/Web/worker；
- 不产生订单，不连接账户，不自动改变仓位；
- 不自动把 Shadow 结果晋升为正式策略或通知规则。

未来若要接会员持仓或 L2，必须作为独立 Data Foundation / provider 合同任务，不属于 V1 的补丁。

## 6. 指标身份与生命周期

### 6.1 Indicator Registry

新增定义：

```text
indicator_code    = main_force_mirror_futures_v1
indicator_version = futures-research-v1
display_name      = 主力照妖镜·期货 V1
display_type      = subpane
status            = observation_only
repainting_risk   = none
closed_bar_only   = true
confirmed_only    = true
web_capable       = true
backtest_capable  = false
live_capable      = false
alert_capable     = false
default_visible   = false
output_schema     = signal_state
formal_policy_id  = main_force_mirror_futures_observation_v1
```

精确输入：

```text
open
high
low
close
volume
open_interest
physical_contract
```

支持周期精确为：

```text
("60m",)
```

完整 warning 输出首次可用需要 31 根同一物理合约、连续有效的 60m Bars：

```text
lookback_bars = 31
warmup_bars   = 30
```

基础状态可在第 21 根 Bar 首次 ready；完整 caution divergence 还需要前 10 个 ready pressure points，因此 Registry 以完整 V1 输出的 31 根为准。

### 6.2 Formal Policy

新增：

```text
policy_id        = main_force_mirror_futures_observation_v1
indicator_family = MAIN_FORCE_MIRROR_FUTURES
confirmed_only   = true
allowed_consumers:
  - Web_manual_observation
blocked_consumers:
  - formal_backtest
  - live
  - alert
  - notification
  - auto_order
```

未知 consumer 必须 fail-closed。

## 7. 数据身份与物理合约分段

### 7.1 为什么必须绑定 physical contract

`actual_dominant` 是查询时按 rank1 拼接的逻辑序列。换月时：

- 价格可能跳变；
- 成交量规模可能跳变；
- OI 绝对值通常大幅变化；
- 新合约 warm-up 不应继承旧合约状态。

因此 V1 的任何 rolling、EMA、ATR、Episode 和 caution latch 都不能跨真实合约段继承。

### 7.2 Web Bar 身份

`BarData` 增加可选字段：

```ts
physicalContract?: string
```

它是每根 Bar 的物理合约身份，不等同于用户选择的 `series_kind` 或查询参数 `contract`。

映射规则：

#### `series_kind=contract`

每根 Historical Bar：

```text
physicalContract = request.contract
```

Live Bar 只在 WebSocket physical identity 与请求合约一致时绑定；否则该 Bar 对 V1 unavailable。

#### `series_kind=actual_dominant`

Historical page 对每根 Bar 使用其 `trading_day` 在 `resolved_contract_segments` 中查找：

```text
start_trading_day <= trading_day <= end_trading_day
```

必须精确命中一个 segment：

- 0 个命中：该 Bar 无 physical contract，V1 fail-closed；
- 多于 1 个命中：视为 segment contract 冲突，V1 fail-closed；
- 1 个命中：绑定该 segment 的 contract。

每次 initial page、prepend page 都独立完成映射；不依赖页面外猜测。

Completed Live/Post-close `snapshot` 直接使用 payload 的精确 `contract`；普通 `bar` 消息只允许复用此前已经建立的 WebSocket overlay physical identity。若 bar 先于 identity 到达，不使用 `live_contract` 猜测，当前 V1 point unavailable。

#### `series_kind=continuous`

```text
physicalContract = undefined
V1 unavailable
```

不自动回退到 V0。

### 7.3 计算 block

Python 与 Web 都把输入切分成 maximal contiguous calculation blocks。以下任一事件开始新 block：

- `physical_contract` 改变；
- required input 缺失或非有限；
- `open_interest < 0`；
- OHLC 关系无效；
- volume 无效；
- datetime/Bar 顺序不严格递增。

新 block 必须从零 warm-up，以下状态全部重置：

```text
ATR14
SMA(volume,20)
EMA(abs(delta_oi),20)
HHV/LLV20
prior pressure window
long/short caution armed latch
re-arm counters
```

无效 Bar 自身输出 unavailable；下一根有效 Bar 不能继承无效 Bar 之前的状态。

## 8. Exact 60m 数学口径

所有公式仅使用当前及过去的 completed Bars，不使用未来 Bar。

### 8.1 True Range 与 ATR14

对同一 calculation block：

```text
TR_t = max(
  high_t - low_t,
  abs(high_t - close_{t-1}),
  abs(low_t - close_{t-1})
)
```

第一根 TR 使用：

```text
TR_0 = high_0 - low_0
```

ATR14 使用 Wilder SMA seed：

```text
ATR14_13 = SMA(TR_0..TR_13)
ATR14_t  = (ATR14_{t-1} * 13 + TR_t) / 14
```

`ATR14 <= 0` 时相关 point unavailable。

### 8.2 Price Impulse

```text
price_impulse_t = clip(
  (close_t - close_{t-1}) / ATR14_t,
  -3,
  3
)
```

### 8.3 Close Location Value

```text
if high_t > low_t:
  clv_t = clip(
    (2 * close_t - high_t - low_t) / (high_t - low_t),
    -1,
    1
  )
else:
  clv_t = 0
```

### 8.4 Direction

```text
direction_t = 0.7 * price_impulse_t + 0.3 * clv_t
```

方向 deadband：

```text
DIRECTION_DEADBAND = 0.15
```

### 8.5 Relative Volume

```text
volume_ratio_t = clip(
  volume_t / SMA(volume,20)_t,
  0,
  3
)

participation_t = sqrt(volume_ratio_t)
```

滚动 volume mean 小于等于 0 时 point unavailable。

### 8.6 Open Interest Impulse

```text
delta_oi_t = open_interest_t - open_interest_{t-1}
```

先计算：

```text
oi_abs_baseline_t = EMA(abs(delta_oi),20)
```

EMA20 使用 SMA seed：前 20 个有效 `abs(delta_oi)` 的平均值作为第一点，之后：

```text
EMA_t = alpha * value_t + (1-alpha) * EMA_{t-1}
alpha = 2 / 21
```

然后：

```text
if oi_abs_baseline_t == 0:
  oi_impulse_t = 0
else:
  oi_impulse_t = clip(delta_oi_t / oi_abs_baseline_t, -3, 3)
```

OI deadband：

```text
OI_DEADBAND = 0.25
```

### 8.7 20 Bar 位置

```text
range_high_t = HHV(high,20)
range_low_t  = LLV(low,20)

range_position_t = clip(
  (close_t - range_low_t) / (range_high_t - range_low_t),
  0,
  1
)
```

`range_high == range_low` 时 point unavailable。

### 8.8 压力与柱体强度

```text
long_open_pressure_t =
  max(direction_t, 0)
  * max(oi_impulse_t, 0)
  * participation_t

short_open_pressure_t =
  max(-direction_t, 0)
  * max(oi_impulse_t, 0)
  * participation_t
```

柱体强度：

```text
strength_t = clip(
  abs(direction_t)
  * abs(oi_impulse_t)
  * participation_t
  * 25,
  0,
  100
)
```

输出按 6 位小数稳定 round。

## 9. 五状态模型

### 9.1 状态分类

先判断 deadband：

```text
if abs(direction) < 0.15
or abs(oi_impulse) < 0.25:
  state = TURNOVER
```

否则：

| Direction | OI impulse | 状态 | 解释 |
| --- | --- | --- | --- |
| `>= +0.15` | `>= +0.25` | `LONG_BUILD` | 上涨伴随增仓，多头方向新增压力 |
| `<= -0.15` | `>= +0.25` | `SHORT_BUILD` | 下跌伴随增仓，空头方向新增压力 |
| `>= +0.15` | `<= -0.25` | `SHORT_COVER` | 上涨伴随减仓，更偏空头回补 |
| `<= -0.15` | `<= -0.25` | `LONG_LIQUIDATION` | 下跌伴随减仓，更偏多头减仓 |

`TURNOVER` 表示方向或 OI 变化不足，不解释为具体主导行为。

### 9.2 signed score

```text
LONG_BUILD / SHORT_COVER:
  signed_score = +strength

SHORT_BUILD / LONG_LIQUIDATION:
  signed_score = -strength

TURNOVER:
  signed_score = sign(direction) * strength
```

图形方向只表示价格运动方向；颜色/状态名表示增仓或减仓性质。

## 10. 双向“小心”风险评分

V1 不使用 V0 的 `HHV5 / BARSLAST10` 作为触发器。V0 原公式继续只属于 `main_force_mirror_v0`。

V1 每个 ready Bar 同时计算：

```text
long_caution_score  ∈ {0,15,25,30,...,100}
short_caution_score ∈ {0,15,25,30,...,100}
```

触发阈值：

```text
CAUTION_THRESHOLD = 70
```

这个 70 是加权证据评分，不是百分比或概率。

### 10.1 追多小心

#### A. 高位位置，30 分

```text
LONG_UPPER_EXTREME:
range_position >= 0.85
```

#### B. 空头回补主导，30 分

```text
LONG_SHORT_COVER_DOMINATED:
state == SHORT_COVER
and oi_impulse <= -0.50
```

含义：价格上涨，但总持仓显著下降，本轮上涨更偏向对手方退出，而不是新增多头持续确认。

#### C. 多头开仓压力背离，25 分

使用当前 Bar 之前的 10 个 ready points：

```text
prior_high = max(high_{t-10}..high_{t-1})
prior_long_pressure = max(long_open_pressure_{t-10}..long_open_pressure_{t-1})

LONG_OPEN_PRESSURE_DIVERGENCE:
high_t > prior_high
and prior_long_pressure > 0
and long_open_pressure_t <= 0.70 * prior_long_pressure
```

#### D. 高量能衰竭，15 分

```text
upper_wick_ratio =
  (high - max(open,close)) / (high-low)
```

`high==low` 时 wick ratio 为 0。

```text
LONG_HIGH_VOLUME_EXHAUSTION:
volume_ratio >= 1.50
and (
  clv <= 0.25
  or upper_wick_ratio >= 0.35
)
```

### 10.2 追空小心

完全对称。

#### A. 低位位置，30 分

```text
SHORT_LOWER_EXTREME:
range_position <= 0.15
```

#### B. 多头减仓主导，30 分

```text
SHORT_LONG_LIQUIDATION_DOMINATED:
state == LONG_LIQUIDATION
and oi_impulse <= -0.50
```

#### C. 空头开仓压力背离，25 分

```text
prior_low = min(low_{t-10}..low_{t-1})
prior_short_pressure = max(short_open_pressure_{t-10}..short_open_pressure_{t-1})

SHORT_OPEN_PRESSURE_DIVERGENCE:
low_t < prior_low
and prior_short_pressure > 0
and short_open_pressure_t <= 0.70 * prior_short_pressure
```

#### D. 低位吸收，15 分

```text
lower_wick_ratio =
  (min(open,close) - low) / (high-low)
```

```text
SHORT_LOW_PRICE_ABSORPTION:
volume_ratio >= 1.50
and (
  clv >= -0.25
  or lower_wick_ratio >= 0.35
)
```

### 10.3 事件

```text
long_caution_candidate  = long_caution_score  >= 70
short_caution_candidate = short_caution_score >= 70
```

事件名称：

```text
LONG_CHASE_CAUTION  → 追多小心
SHORT_CHASE_CAUTION → 追空小心
```

同一 Bar 若因为异常数据出现两个 candidate，必须 fail-closed 为 `CAUTION_DIRECTION_CONFLICT`，不选择优先级。

## 11. Episode latch 与重新武装

V1 不使用固定 10 Bar cooldown。多空两侧各自维护独立 latch。

### 11.1 初始状态

每个 calculation block 开始：

```text
long_armed  = true
short_armed = true
```

### 11.2 触发顺序

每根 ready completed Bar：

1. 先判断当前 armed side 是否满足 score `>=70`；
2. 满足则输出一次 caution event，并将该 side `armed=false`；
3. 事件 Bar 不同时执行 re-arm；
4. 另一方向 latch 保持独立。

### 11.3 Long re-arm

`long_armed=false` 后，仅在以下条件同时成立时重新武装：

```text
long_caution_score < 40
连续 3 根 ready Bars
```

并且满足任一：

```text
range_position < 0.65
```

或：

```text
state == LONG_BUILD
连续 2 根 ready Bars
```

re-arm 在当前 Bar 结束后生效，最早从下一根 Bar 再触发。

### 11.4 Short re-arm

```text
short_caution_score < 40
连续 3 根 ready Bars
```

并且满足任一：

```text
range_position > 0.35
```

或：

```text
state == SHORT_BUILD
连续 2 根 ready Bars
```

### 11.5 unavailable Bar

unavailable Bar：

- 不触发；
- 不推进 low-score count；
- 不推进 build count；
- 不擅自 re-arm；
- 若由 required input invalid 引起，则该 Bar 后开始新 calculation block，全部 latch 重置。

## 12. Python Kernel 输出合同

新增模块建议：

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
```

公开类型：

```python
MainForceMirrorFuturesState = Literal[
    "long_build",
    "short_build",
    "short_cover",
    "long_liquidation",
    "turnover",
]

MainForceMirrorFuturesCaution = Literal[
    "long_chase_caution",
    "short_chase_caution",
]

@dataclass(frozen=True)
class MainForceMirrorFuturesResult:
    datetimes: np.ndarray
    physical_contract: np.ndarray
    ready: np.ndarray
    valid: np.ndarray
    reason: np.ndarray
    state: np.ndarray
    signed_score: np.ndarray
    strength: np.ndarray
    price_impulse: np.ndarray
    clv: np.ndarray
    volume_ratio: np.ndarray
    delta_oi: np.ndarray
    oi_impulse: np.ndarray
    direction: np.ndarray
    range_position: np.ndarray
    long_open_pressure: np.ndarray
    short_open_pressure: np.ndarray
    long_caution_score: np.ndarray
    short_caution_score: np.ndarray
    caution: np.ndarray
    caution_reason_codes: tuple[tuple[str, ...], ...]
    metadata: dict[str, Any]
```

公开函数：

```python
def compute_main_force_mirror_futures(
    datetimes: Sequence[Any],
    physical_contract: Sequence[str | None],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    open_interest: Sequence[float | None],
) -> MainForceMirrorFuturesResult:
    ...
```

metadata 必须包含：

```text
indicator_code
indicator_version
status=observation_only
supported_frequency=60m
supported_series_kind=[contract,actual_dominant]
future_looking=false
repainting_risk=none
historical_backtest_allowed=false
alert_capable=false
notification_capable=false
auto_order=false
interpretation=directional_position_pressure_proxy_not_measured_fund_flow
caution_threshold=70
parameters_hash
```

## 13. Web mirror 与一致性

新增：

```text
apps/quant-web/src/utils/mainForceMirrorFutures.ts
```

Web mirror：

- 只服务浏览器显示；
- 函数签名与 Python 公式字段一一对应；
- 不成为 Factor、Signal、Alert 或 Runtime 事实源；
- 每次修改必须同时更新 Python/Web golden；
- 口径冲突时以 Python Kernel 为准。

建议 Web result：

```ts
interface MainForceMirrorFuturesPoint {
  time: Time
  physicalContract: string | null
  ready: boolean
  valid: boolean
  reason: string | null
  state: MainForceMirrorFuturesState | null
  signedScore: number | null
  strength: number | null
  volumeRatio: number | null
  deltaOi: number | null
  oiImpulse: number | null
  direction: number | null
  rangePosition: number | null
  longCautionScore: number | null
  shortCautionScore: number | null
  caution: MainForceMirrorFuturesCaution | null
  cautionReasonCodes: MainForceMirrorFuturesReasonCode[]
}
```

## 14. Web 交互设计

### 14.1 副图 Tab

稳定期使用一行三个 Tab：

```text
MACD | 主力照妖镜 | 原型V0
```

含义：

- `MACD`：保持默认；
- `主力照妖镜`：期货 V1；
- `原型V0`：已发布股票式原型，只用于历史复现和并行观察。

V1 Tab 可用条件：

```text
frequency == 60m
series_kind in {contract, actual_dominant}
所有可见目标 Bars 能绑定 physicalContract
当前 ready 区域存在 openInterest
```

不可用时 Tab 禁用并显示精确原因，不自动回退 V0。

### 14.2 柱体语义

```text
零轴上方：
  LONG_BUILD  多头增仓，强上行色
  SHORT_COVER 空头回补，弱上行色

零轴下方：
  SHORT_BUILD      空头增仓，强下行色
  LONG_LIQUIDATION 多头减仓，弱下行色

零轴附近：
  TURNOVER 换手/方向不足，中性色
```

颜色必须使用 chart theme token，不在业务函数中硬编码。

V1 price scale 固定覆盖：

```text
[-105, +105]
```

避免不同窗口 autoscale 导致相同强度视觉不一致。

### 14.3 Caution marker

```text
LONG_CHASE_CAUTION:
  +92 附近
  文案：追多小心 {score}

SHORT_CHASE_CAUTION:
  -92 附近
  文案：追空小心 {score}
```

图例固定说明：

```text
70 = 风险证据评分阈值，不是资金流比例或概率
```

### 14.4 Hover

选择 V1 时，hover 至少展示：

```text
物理合约
状态
柱体强度
价格冲击
量比20
OI变动
OI冲击
20 Bar位置
追多评分
追空评分
警戒原因
```

缺失值显示 `—`，不得补 0。

## 15. V0 共存与迁移

`main_force_mirror_v0`：

- indicator code/version 不变；
- 原“小心”公式不变；
- existing golden 不变；
- capability 不变；
- 不被 V1 静默替换。

稳定观察阶段：

```text
MACD
主力照妖镜（期货 V1）
原型V0
```

只有在 V1 完成 Shadow、用户人工接受，并另开 UI 收口任务后，才允许从默认 UI 移除“原型V0”。即使 UI 移除，V0 Registry 与 Git 历史仍保留以支持复现。

## 16. Historical Shadow 设计

V1 仍是 observation-only，但需要只读 Historical Shadow 统计验证是否降低噪声、提高双向警戒质量。

### 16.1 唯一数据链路

```text
MarketDataService
→ actual_dominant 60m bars + resolved physical segments
→ Python main_force_mirror_futures_v1
→ caution events
→ forward outcome summaries
```

不得直读 Parquet、RQData、Redis 或复制主力 resolver。

### 16.2 初始代表品种

首轮固定观察矩阵：

```text
jm  黑色
ag  贵金属
cu  有色
m   农产品
sc  能源
```

这些只是研究样本，不写入 indicator capability，也不表示其他 active 品种不支持。

### 16.3 事件身份

```text
indicator_code
indicator_version
parameters_hash
symbol
series_kind
physical_contract
trading_day
bar_end
caution_direction
score
reason_codes
state
```

### 16.4 后续结果

同一 physical contract segment 内统计：

```text
horizons = [1,3,5,10] completed 60m bars
```

追多小心：

```text
reversal_return_h = (close_t - close_{t+h}) / close_t
warning_mfe_h     = (close_t - min(low_{t+1..t+h})) / close_t
warning_mae_h     = (max(high_{t+1..t+h}) - close_t) / close_t
```

追空小心：

```text
reversal_return_h = (close_{t+h} - close_t) / close_t
warning_mfe_h     = (max(high_{t+1..t+h}) - close_t) / close_t
warning_mae_h     = (close_t - min(low_{t+1..t+h})) / close_t
```

如果 horizon 跨物理合约边界，该 outcome 为 unavailable，不跨换月拼接。

### 16.5 汇总

每个品种与合并样本输出：

```text
bars_ready_count
event_count_long
event_count_short
events_per_1000_ready_bars
state_distribution
reason_code_distribution
score_distribution
forward_reversal_return distribution
warning_mfe distribution
warning_mae distribution
missing_oi_count
segment_reset_count
```

不输出盈利、胜率保证、可晋升或自动参数建议。

### 16.6 CLI

后续 implementation plan 可以增加只读命令：

```text
guiyi research main-force-mirror-futures
```

要求显式参数：

```text
--symbol
--series-kind actual_dominant|contract
--contract（contract 时必填）
--frequency 60m
--since
--through
```

stdout JSON；不写 DB、Canonical、Redis，不自动保存正式报告，不修改 STATUS。

## 17. 失败与 unavailable reason codes

V1 必须使用稳定 reason codes，至少包括：

```text
MFM_FUTURES_V1_FREQUENCY_UNSUPPORTED
MFM_FUTURES_V1_SERIES_UNSUPPORTED
MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING
MFM_FUTURES_V1_SEGMENT_CONFLICT
MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE
MFM_FUTURES_V1_INPUT_INVALID
MFM_FUTURES_V1_WARMUP
MFM_FUTURES_V1_ATR_INVALID
MFM_FUTURES_V1_VOLUME_BASELINE_INVALID
MFM_FUTURES_V1_RANGE_INVALID
MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT
```

UI 必须区分：

- unsupported：身份或周期不支持；
- unavailable：该数据窗口缺少 OI/segment/有效输入；
- warmup：合法但历史长度不足；
- ready：可显示状态与评分。

不得把 unavailable 当成 TURNOVER。

## 18. 文件边界

### 18.1 新增

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
apps/quant-web/src/utils/mainForceMirrorFutures.ts
services/quant-api/tests/test_main_force_mirror_futures.py
apps/quant-web/tests/mainForceMirrorFutures.test.ts
apps/quant-web/e2e/main-force-mirror-futures.spec.mjs
```

如首轮同时实现 Shadow：

```text
services/quant-api/app/market_data/main_force_mirror_futures_research_service.py
services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py
```

### 18.2 修改

```text
packages/quant-core/guiyi_quant/indicators/__init__.py
packages/quant-core/guiyi_quant/indicators/registry.py
packages/quant-core/guiyi_quant/indicators/policy.py
apps/quant-web/src/types/market.ts
apps/quant-web/src/composables/useMarketSeries.ts
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/components/kline/KlineHoverLegend.vue
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/tests/marketSeries.test.ts
apps/quant-web/e2e/market-runtime.spec.mjs
docs/INDICATOR_KERNEL.md
TESTING.md
```

`STATUS.md` 只能在完整实现、仓库原生验证和独立 Review 全部通过后记录 develop-only 事实。

### 18.3 禁止修改

```text
Market DatasetKey / 八表 Catalog / Canonical schema
Alert registry / Rule / Scope / event evaluator
Clawbot / owner / transport
Execution Review
production DB / migration
main / release / tag / Runtime worktree
```

## 19. 测试与验证矩阵

### 19.1 Kernel 数学

必须覆盖：

- ATR14 Wilder SMA seed；
- volume SMA20；
- OI abs-delta EMA20 SMA seed；
- deadband 精确边界 `0.15 / 0.25`；
- 四象限和 TURNOVER 五状态；
- signed score 正负与 0..100 cap；
- long/short pressure；
- 四个 long reason 与四个 short reason；
- score 69 不触发、70 触发；
- long/short conflict fail-closed；
- re-arm 三根低分 + range reset；
- re-arm 三根低分 + 两根 opening build；
- unavailable Bar 暂停或 block reset；
- prefix invariance；
- V0 output hash 不变。

### 19.2 Segment

必须覆盖：

- contract series 全部 Bar 绑定请求合约；
- actual_dominant 每根 Bar 精确命中一个 segment；
- segment 0 命中和多命中 fail-closed；
- prepend page 的 older Bars 获得正确物理合约；
- WebSocket snapshot 使用 payload contract；
- 无 overlay identity 的 bar 不猜合约；
- A→B 换月存在巨大价格/OI 跳变时，B 段重新 warm-up，不产生假柱或假 caution；
- horizon 不跨 segment。

### 19.3 Python/Web parity

使用同一 deterministic fixture 覆盖至少：

```text
两段物理合约
完整五状态
至少一个追多小心
至少一个追空小心
至少一次 re-arm
一个 missing OI gap
```

逐点核对：

```text
ready/valid/reason
state
signed_score
price_impulse
volume_ratio
delta_oi
oi_impulse
direction
range_position
long/short caution score
caution
reason codes
```

### 19.4 Web

Playwright 必须证明：

- 默认仍为 MACD；
- 三个 Tab 顺序固定；
- 60m actual_dominant 可打开 V1；
- 15m、continuous 的 V1 disabled 且原因正确；
- 切换 Tab 不 refetch bars；
- V1/V0/MACD 相互清空旧 series 与 markers；
- 追多与追空 marker 方向、文案和 score 正确；
- 页面显示“70 非资金比例”；
- 物理合约切换后 V1 warm-up；
- no horizontal overflow；
- Web production build 通过。

### 19.5 仓库回归

按 `TESTING.md` 执行受影响的：

```text
backend tests
indicator registry/policy tests
Ruff
Mypy
Web unit
Market browser E2E
Web production build
secret scan
git diff --check
```

测试不运行 provider、DB/Canonical 写入、Runtime switch 或真实通知。

## 20. 验收标准

V1 实现验收必须同时满足：

1. V0 code/version/golden/capability 零变化；
2. V1 只有 60m + contract/actual_dominant 可用；
3. 每根 ready Bar 有精确 physical contract；
4. 换月后所有指标与 latch 重新 warm-up；
5. 五状态与 OI 四象限一致；
6. 追多/追空评分由精确四项证据组成，阈值固定 70；
7. 同一 Episode 不连续刷屏，re-arm 合同通过；
8. Python/Web golden 逐点一致；
9. UI 不把 70 表述为百分比、概率或实测资金流；
10. 无 Alert、notification、DB、Canonical、Runtime 或订单新路径；
11. Shadow 输出只读、segment-local、无自动晋升；
12. 独立 Review 为 Critical=0 / Important=0。

通过以上验收只能得出：

```text
main_force_mirror_futures_v1 Web observation implementation verified on develop
```

不能得出：

```text
策略有效
可盈利
可发正式 Alert
可 Runtime promotion
可自动交易
```

## 21. 推荐实施顺序

后续 implementation plan 应拆为：

```text
Task 1  Python domain contract + exact math + RED/GREEN
Task 2  Registry/Policy + segment-local reset + V0 regression
Task 3  Web physicalContract mapping + Python/Web golden
Task 4  V1 pane/UI/hover + three-tab Playwright
Task 5  Historical Shadow CLI/service + representative matrix tests
Task 6  Full regression + docs + independent Review
```

前四个 Task 形成可用 Web observation；Task 5 形成研究证据入口；Task 6 才允许 develop-only 收口。

## 22. 人工 Gate

本 Spec 审阅通过后，下一步只允许生成 implementation plan 和 TASK contracts。

后续代码可以按批准任务集成 `develop`，但以下操作始终需要独立明确请求：

```text
release/main/tag
Runtime reload/promotion
真实 Shadow 运行并保存正式 evidence
新增 Alert Rule/Scope
真实通知
DB/Canonical 写入
```

AI 可以自动研究和生成报告，但不能自动晋升 V1。