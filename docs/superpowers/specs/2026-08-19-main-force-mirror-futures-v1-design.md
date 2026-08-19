# 主力照妖镜·期货 V1 设计规格

> 状态：Design basis approved；书面 Spec 已完成自审，待用户审阅后再进入 implementation plan。
>
> 日期：2026-08-19
>
> 规划基线：`develop@16d09ac0dad295763bf7552e07e06f3222c41c80`
>
> 现有版本：`main_force_mirror_v0` / `designed-v0`
>
> 新版本：`main_force_mirror_futures_v1` / `futures-research-v1`
>
> 本文只定义期货专用 observation V1；不修改已经发布的 V0，不授权 Alert、通知、回测晋升、release、tag 或 Runtime promotion。

## 1. 设计结论

现有 V0 是 causal、Web-only 的 OHLCV 设计代理：

```text
CLV × 相对成交量
→ 六色观察状态
→ 单侧 HHV5 / BARSLAST10 “小心”
```

它适合作为股票式原型和历史复现版本，但不适合作为期货长期版本：

1. “小心”只有追多一侧；
2. 固定 `HHV5 / BARSLAST10` 在 60m 图上过密；
3. 未使用期货现成的 `open_interest`；
4. 无法区分上涨中的多头增仓与空头回补，也无法区分下跌中的空头增仓与多头减仓；
5. 未显式按真实合约段重置，换月价格/OI 跳变可能伪造行为；
6. “70% 主力流出”不是当前 Bar 数据可以直接测量的事实。

新增独立 V1：

```text
OHLCV + Open Interest + Physical Contract Segment
→ 多头增仓 / 空头增仓 / 空头回补 / 多头减仓 / 换手
→ 追多小心 / 追空小心
→ 0..100 风险证据评分
→ reason codes
→ Historical Shadow 统计
```

V1 的“70”精确定义为**风险证据评分阈值 70/100**，不是资金流出比例、概率、会员席位结论或账户级事实。

## 2. 当前仓库事实

规划基线下：

- production Git release 与 Runtime 为 `v1.6.1`；V0 已发布并存在于当前 Web 观察面；
- Python Indicator Kernel 是指标业务口径唯一权威；
- V0 authority 为 `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py`，Web mirror 为 `apps/quant-web/src/utils/mainForceMirror.ts`；
- 当前最底部 pane 通过 `MACD / 主力照妖镜` Tab 二选一；
- Canonical Bar 与 Web `BarData` 已包含 `open_interest / openInterest`；
- 5m/15m/30m/60m 聚合时 OI 取桶内最后一根 Canonical 1m Bar；
- `/api/v1/market/bars/page` 已返回 `resolved_contract_segments`，但 `useMarketSeries()` 尚未把每根 Bar 的物理合约身份传入指标层；
- WebSocket `snapshot` 已返回精确 `contract`；
- 当前没有会员多空持仓排名、逐笔主动买卖、Level-2 或账户身份数据。

因此 V1 只能定义为**方向性持仓压力代理**，不能声称识别了具体“主力”账户。

## 3. 产品目标

V1 首版只解决四个问题：

1. 区分价格运动由增仓还是减仓驱动；
2. 建立对称的“追多小心 / 追空小心”；
3. 以 Episode latch 降低固定 K 线冷却产生的重复噪声；
4. 输出可解释状态、分数、原因和后续结果，积累复盘证据。

它必须明确提高至少一项长期价值：减少盯盘判断成本、提高方向风险识别一致性、增加未来研究证据。

## 4. 首版范围与禁止范围

### 4.1 精确范围

```text
frequency    = 60m only
series_kind  = contract | actual_dominant
status       = observation_only
web          = true
backtest     = false
live         = false
alert        = false
notification = false
auto_order   = false
```

`web=true` 允许浏览器对 Historical 与 completed Live/Post-close Bars 做只读观察；`live=false` 表示没有正式 live consumer、Runtime evaluator 或交易能力。

首版明确不支持：

```text
continuous
1m / 5m / 15m / 30m / 1d / 1w
```

不把 60m 参数机械复用到其他周期，也不自动回退 V0。

### 4.2 严格禁止

- 不修改或删除 `main_force_mirror_v0`；
- 不把 V1 结果写回 V0 code/version/golden；
- 不新增会员席位、L2、逐笔或第二 provider；
- 不生成 `outflow_ratio`、`main_force_ratio` 或“70% 已流出”；
- 不新增 Market Catalog 表、Canonical 字段、Parquet 副本或长期派生数据表；
- 不新增 DB、migration、Redis 状态、worker、queue、outbox；
- 不新增 Alert Rule、Scope、Clawbot、Execution Review 自动入口；
- 不恢复通用 backtest API/Web/worker；
- 不连接账户，不产生订单，不自动改变仓位；
- 不根据 Shadow 结果自动晋升。

未来若接会员持仓或 L2，必须另立 Data Foundation/provider 合同任务。

## 5. Indicator Registry 与固定参数

### 5.1 Registry 定义

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
lookback_bars     = 31
warmup_bars       = 30
```

输入：

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

当前 `test_indicator_registry_v1.py` 中“所有指标都支持七周期”的全局断言需要改为**逐指标支持集断言**：现有指标仍保持现有七周期合同，V1 精确为 `("60m",)`。这不改变 Data Foundation 的七周期，只允许具体指标声明子集。

### 5.2 Exact parameters

Registry `default_parameters` 与 Python metadata 精确冻结为：

```json
{
  "atr_period": 14,
  "volume_window": 20,
  "oi_impulse_ema_period": 20,
  "range_window": 20,
  "pressure_divergence_window": 10,
  "direction_price_weight": 0.7,
  "direction_clv_weight": 0.3,
  "direction_deadband": 0.15,
  "oi_deadband": 0.25,
  "volume_ratio_clip": 3.0,
  "price_impulse_clip": 3.0,
  "oi_impulse_clip": 3.0,
  "strength_scale": 25.0,
  "turnover_display_cap": 15.0,
  "upper_location_threshold": 0.85,
  "lower_location_threshold": 0.15,
  "closing_dominated_oi_threshold": 0.5,
  "pressure_confirmation_ratio": 0.7,
  "high_volume_threshold": 1.5,
  "clv_rejection_threshold": 0.25,
  "wick_rejection_threshold": 0.35,
  "caution_threshold": 70,
  "rearm_score_threshold": 40,
  "rearm_low_score_bars": 3,
  "rearm_build_bars": 2,
  "long_rearm_range_threshold": 0.65,
  "short_rearm_range_threshold": 0.35,
  "round_digits": 6
}
```

同一 indicator code/version 下不得静默修改这些值；任何研究调整必须产生新 version。

### 5.3 Formal Policy

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

未知 consumer fail-closed。

## 6. 物理合约身份与计算 block

### 6.1 Web Bar 身份

`BarData` 增加：

```ts
physicalContract?: string
```

#### `series_kind=contract`

Historical Bar：

```text
physicalContract = request.contract
```

Completed Live Bar 仅在 WebSocket physical identity 与请求合约一致时绑定。

#### `series_kind=actual_dominant`

Historical page 对每根 Bar 按 `trading_day` 在 `resolved_contract_segments` 中查找：

```text
start_trading_day <= trading_day <= end_trading_day
```

必须精确命中一个 segment：

- 0 个：`PHYSICAL_CONTRACT_MISSING`；
- 多于 1 个：`SEGMENT_CONFLICT`；
- 1 个：绑定 segment contract。

initial page 与每个 prepend page 都独立映射，不依赖页外猜测。

Completed Live/Post-close `snapshot` 使用 payload 的精确 `contract`。普通 `bar` 消息只复用已经建立的 overlay physical identity；若 bar 先于 identity 到达，不使用 `live_contract` 猜测，当前 V1 point unavailable。

#### `series_kind=continuous`

不绑定 physical contract，V1 unavailable。

### 6.2 输入有效性

一根 Bar 只有同时满足以下条件才是 valid input：

```text
time 可解析且按序列严格递增
physical_contract 为非空规范化合约字符串
open/high/low/close/volume/open_interest 均为有限数
high >= max(open, close)
low <= min(open, close)
high >= low
volume >= 0
open_interest >= 0
```

### 6.3 valid 与 ready

```text
valid = 当前 Bar 输入及身份有效
ready = valid 且当前 calculation block 已满足对应 warm-up
```

不得把 invalid、unsupported、unavailable 或 warm-up 输出成数值 0。

### 6.4 calculation block

Python 与 Web 都切分 maximal contiguous blocks。以下任一事件结束旧 block：

- `physical_contract` 改变；
- required input invalid；
- timestamp 非严格递增。

新 block 从零 warm-up，并重置：

```text
ATR14
SMA(volume,20)
EMA(abs(delta_oi),20)
HHV/LLV20
prior pressure window
long/short caution latch
re-arm counters
```

无效 Bar 自身 unavailable；下一根有效 Bar 不能继承无效 Bar 之前的状态。

## 7. Exact 60m 数学口径

所有公式只使用当前及过去 completed Bars。

### 7.1 ATR14

```text
TR_0 = high_0 - low_0

TR_t = max(
  high_t - low_t,
  abs(high_t - close_{t-1}),
  abs(low_t - close_{t-1})
)

ATR14_13 = SMA(TR_0..TR_13)
ATR14_t  = (ATR14_{t-1} * 13 + TR_t) / 14
```

`ATR14 <= 0` 时相关 point unavailable。

### 7.2 Price impulse 与 CLV

```text
price_impulse_t = clip(
  (close_t - close_{t-1}) / ATR14_t,
  -3,
  3
)
```

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

```text
direction_t = 0.7 * price_impulse_t + 0.3 * clv_t
```

### 7.3 Relative volume

```text
volume_ratio_t = clip(
  volume_t / SMA(volume,20)_t,
  0,
  3
)

participation_t = sqrt(volume_ratio_t)
```

滚动均值 `<=0` 时 unavailable。

### 7.4 OI impulse

```text
delta_oi_t = open_interest_t - open_interest_{t-1}
```

```text
oi_abs_baseline_t = EMA(abs(delta_oi),20)
```

EMA20 使用 SMA seed：前 20 个有效 `abs(delta_oi)` 的平均值为第一点，之后：

```text
alpha = 2 / 21
EMA_t = alpha * value_t + (1-alpha) * EMA_{t-1}
```

```text
if oi_abs_baseline_t == 0:
  oi_impulse_t = 0
else:
  oi_impulse_t = clip(delta_oi_t / oi_abs_baseline_t, -3, 3)
```

### 7.5 20 Bar 位置

```text
range_high_t = HHV(high,20)
range_low_t  = LLV(low,20)

range_position_t = clip(
  (close_t - range_low_t) / (range_high_t - range_low_t),
  0,
  1
)
```

`range_high == range_low` 时 unavailable。

### 7.6 压力与强度

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

全部数值按 6 位小数稳定 round。

## 8. 五状态模型

先判断 deadband：

```text
if abs(direction) < 0.15
or abs(oi_impulse) < 0.25:
  state = TURNOVER
```

否则：

| Direction | OI impulse | 状态 | 解释 |
| --- | --- | --- | --- |
| `>= +0.15` | `>= +0.25` | `LONG_BUILD` | 上涨伴随增仓，多头新增压力 |
| `<= -0.15` | `>= +0.25` | `SHORT_BUILD` | 下跌伴随增仓，空头新增压力 |
| `>= +0.15` | `<= -0.25` | `SHORT_COVER` | 上涨伴随减仓，更偏空头回补 |
| `<= -0.15` | `<= -0.25` | `LONG_LIQUIDATION` | 下跌伴随减仓，更偏多头减仓 |

signed score：

```text
LONG_BUILD / SHORT_COVER:
  +strength

SHORT_BUILD / LONG_LIQUIDATION:
  -strength

TURNOVER:
  sign(direction) * min(strength, 15)
```

状态解释始终使用“更偏向”，不表述为账户级确定事实。

## 9. 双向风险评分

V1 不使用 V0 的 `HHV5 / BARSLAST10` 作为触发器。V0 原公式继续只属于 V0。

```text
long_caution_score  = 四项证据加权和
short_caution_score = 四项证据加权和
CAUTION_THRESHOLD   = 70
```

### 9.1 追多小心

#### `LONG_UPPER_EXTREME`，30 分

```text
range_position >= 0.85
```

#### `LONG_SHORT_COVER_DOMINATED`，30 分

```text
state == SHORT_COVER
and oi_impulse <= -0.50
```

#### `LONG_OPEN_PRESSURE_DIVERGENCE`，25 分

使用当前 Bar 之前的 10 个 ready points：

```text
prior_high = max(high_{t-10}..high_{t-1})
prior_long_pressure = max(long_open_pressure_{t-10}..long_open_pressure_{t-1})

high_t > prior_high
and prior_long_pressure > 0
and long_open_pressure_t <= 0.70 * prior_long_pressure
```

#### `LONG_HIGH_VOLUME_EXHAUSTION`，15 分

```text
upper_wick_ratio =
  (high - max(open,close)) / (high-low)
```

`high==low` 时为 0。

```text
volume_ratio >= 1.50
and (
  clv <= 0.25
  or upper_wick_ratio >= 0.35
)
```

### 9.2 追空小心

#### `SHORT_LOWER_EXTREME`，30 分

```text
range_position <= 0.15
```

#### `SHORT_LONG_LIQUIDATION_DOMINATED`，30 分

```text
state == LONG_LIQUIDATION
and oi_impulse <= -0.50
```

#### `SHORT_OPEN_PRESSURE_DIVERGENCE`，25 分

```text
prior_low = min(low_{t-10}..low_{t-1})
prior_short_pressure = max(short_open_pressure_{t-10}..short_open_pressure_{t-1})

low_t < prior_low
and prior_short_pressure > 0
and short_open_pressure_t <= 0.70 * prior_short_pressure
```

#### `SHORT_LOW_PRICE_ABSORPTION`，15 分

```text
lower_wick_ratio =
  (min(open,close) - low) / (high-low)
```

```text
volume_ratio >= 1.50
and (
  clv >= -0.25
  or lower_wick_ratio >= 0.35
)
```

### 9.3 事件

```text
LONG_CHASE_CAUTION  → 追多小心
SHORT_CHASE_CAUTION → 追空小心
```

```text
candidate = corresponding_score >= 70
```

同一 Bar 若异常地产生两个 candidate，输出 `CAUTION_DIRECTION_CONFLICT`，不设优先级。

## 10. Episode latch 与 re-arm

每个 calculation block 开始：

```text
long_armed  = true
short_armed = true
```

每根 ready Bar：

1. 先判断 armed side 是否 score `>=70`；
2. 触发一次后该 side `armed=false`；
3. 事件 Bar 不执行 re-arm；
4. 多空 latch 独立。

### 10.1 Long re-arm

必须同时满足：

```text
long_caution_score < 40
连续 3 根 ready Bars
```

并满足任一：

```text
range_position < 0.65
```

或：

```text
state == LONG_BUILD
连续 2 根 ready Bars
```

### 10.2 Short re-arm

必须同时满足：

```text
short_caution_score < 40
连续 3 根 ready Bars
```

并满足任一：

```text
range_position > 0.35
```

或：

```text
state == SHORT_BUILD
连续 2 根 ready Bars
```

re-arm 在当前 Bar 结束后生效，最早下一根再触发。

warm-up/unavailable Bar 不推进计数；required input invalid 会结束 block 并在下一有效 block 重置 latch。

## 11. Python Kernel 输出合同

新增：

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

metadata 必须包含 code/version/status、supported frequency/series、future/repainting、capability、parameters、parameters_hash、`auto_order=false`，以及：

```text
interpretation = directional_position_pressure_proxy_not_measured_fund_flow
```

## 12. Web mirror 与交互

新增：

```text
apps/quant-web/src/utils/mainForceMirrorFutures.ts
```

Web mirror 只服务浏览器，逐点与 Python golden 对齐；冲突时以 Python Kernel 为准。

### 12.1 Tab

稳定观察期使用：

```text
MACD | 主力照妖镜 | 原型V0
```

- `MACD` 保持默认；
- `主力照妖镜` 指期货 V1；
- `原型V0` 用于历史复现与并行观察。

V1 Tab 仅在 60m + contract/actual_dominant 可选择。身份支持但局部 Bar 缺失 OI/segment 时，Tab 仍可打开，缺失区间逐点显示 unavailable；若当前可见窗口没有任何 ready point，则显示精确不可用说明。continuous 或其他周期直接 disabled。

切换 Tab 不得 refetch bars，不改变主图 overlay、EMA 偏好、行情 identity、Alert markers 或 pane 数量。

### 12.2 柱体与 scale

```text
零轴上方：LONG_BUILD / SHORT_COVER
零轴下方：SHORT_BUILD / LONG_LIQUIDATION
零轴附近：TURNOVER
```

颜色只使用 chart theme token；业务函数不硬编码颜色。

V1 scale 固定：

```text
[-105,+105]
```

### 12.3 caution marker

```text
LONG_CHASE_CAUTION:
  +92，文案“追多小心 {score}”

SHORT_CHASE_CAUTION:
  -92，文案“追空小心 {score}”
```

图例固定：

```text
70 = 风险证据评分阈值，不是资金流比例或概率
```

### 12.4 Hover

至少展示：

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

缺失显示 `—`，不得补 0。

## 13. V0 共存

V0 的 code/version/formula/golden/capability 全部保持不变。

只有在 V1 完成 Shadow、用户人工接受，并另开 UI 收口任务后，才允许从默认 UI 移除“原型V0”。即使移除 UI，V0 Registry 与 Git 历史仍保留。

## 14. Historical Shadow

### 14.1 唯一链路

```text
MarketDataService
→ actual_dominant 60m + resolved physical segments
→ Python V1
→ caution events
→ forward outcome summaries
```

不得直读 Parquet、RQData、Redis 或复制主力 resolver。

### 14.2 初始代表矩阵

```text
jm  黑色
ag  贵金属
cu  有色
m   农产品
sc  能源
```

只是研究样本，不限制 indicator capability。

### 14.3 事件身份

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

### 14.4 Outcome

同一 physical contract segment 内：

```text
horizons = [1,3,5,10] completed 60m bars
```

追多：

```text
reversal_return_h = (close_t - close_{t+h}) / close_t
warning_mfe_h     = (close_t - min(low_{t+1..t+h})) / close_t
warning_mae_h     = (max(high_{t+1..t+h}) - close_t) / close_t
```

追空：

```text
reversal_return_h = (close_{t+h} - close_t) / close_t
warning_mfe_h     = (max(high_{t+1..t+h}) - close_t) / close_t
warning_mae_h     = (close_t - min(low_{t+1..t+h})) / close_t
```

跨 segment 的 outcome unavailable。

### 14.5 汇总

```text
bars_ready_count
event_count_long / short
events_per_1000_ready_bars
state_distribution
reason_code_distribution
score_distribution
forward_reversal_return distribution
warning_mfe / warning_mae distribution
missing_oi_count
segment_reset_count
```

不输出盈利保证、自动参数建议或晋升结论。

### 14.6 CLI

后续 plan 可增加只读命令：

```text
guiyi research main-force-mirror-futures
```

显式参数：

```text
--symbol
--series-kind actual_dominant|contract
--contract（contract 时必填）
--frequency 60m
--since
--through
```

stdout JSON；不写 DB、Canonical、Redis，不自动保存正式 evidence，不修改 STATUS。

## 15. Stable unavailable reason codes

至少包括：

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

UI 必须区分 unsupported、unavailable、warm-up 和 ready。不得把 unavailable 当 TURNOVER。

## 16. 文件边界

### 16.1 新增

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
apps/quant-web/src/utils/mainForceMirrorFutures.ts
services/quant-api/tests/test_main_force_mirror_futures.py
apps/quant-web/tests/mainForceMirrorFutures.test.ts
apps/quant-web/e2e/main-force-mirror-futures.spec.mjs
```

Shadow 同轮实施时新增：

```text
services/quant-api/app/market_data/main_force_mirror_futures_research_service.py
services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py
```

### 16.2 修改

```text
packages/quant-core/guiyi_quant/indicators/__init__.py
packages/quant-core/guiyi_quant/indicators/registry.py
packages/quant-core/guiyi_quant/indicators/policy.py
services/quant-api/tests/test_indicator_registry_v1.py
apps/quant-web/src/types/market.ts
apps/quant-web/src/composables/useMarketSeries.ts
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/components/kline/KlineHoverLegend.vue
apps/quant-web/src/utils/klineViewModel.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/tests/marketSeries.test.ts
apps/quant-web/tests/kline-view-model.test.ts
apps/quant-web/e2e/main-force-mirror.spec.mjs
apps/quant-web/e2e/market-runtime.spec.mjs
docs/INDICATOR_KERNEL.md
TESTING.md
```

Shadow CLI 同轮实施时修改：

```text
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_research_cli.py
```

`STATUS.md` 只能在完整实现、仓库原生验证和独立 Review 通过后记录 develop-only 事实。

### 16.3 禁止修改

```text
DatasetKey / 八表 Catalog / Canonical schema
Alert registry / Rule / Scope / evaluator
Clawbot / owner / transport
Execution Review
production DB / migration
main / release / tag / Runtime worktree
```

## 17. 测试矩阵

### 17.1 Kernel

必须覆盖：

- ATR14 Wilder SMA seed；
- volume SMA20；
- OI abs-delta EMA20 SMA seed；
- exact parameters hash；
- deadband `0.15 / 0.25`；
- 四象限与 TURNOVER；
- TURNOVER display cap 15；
- signed score 与 100 cap；
- long/short pressure；
- 八个 caution reasons；
- score 69 不触发、70 触发；
- conflict fail-closed；
- 两种 long/short re-arm；
- invalid gap block reset；
- prefix invariance；
- V0 output hash 不变。

### 17.2 Segment

必须覆盖：

- contract Bars 绑定请求合约；
- actual_dominant 精确命中 segment；
- 0/多命中 fail-closed；
- prepend page 映射；
- snapshot contract；
- 无 identity 的 bar 不猜合约；
- A→B 巨大价格/OI 跳变后 B 重新 warm-up，无假柱/假 caution；
- outcome 不跨 segment。

### 17.3 Python/Web parity

同一 deterministic fixture 至少包含：

```text
两个 physical contracts
五状态
一个追多小心
一个追空小心
一次 re-arm
一个 missing OI gap
```

逐点核对 ready/valid/reason、state、所有核心数值、score、caution 和 reason codes。

### 17.4 Web

Playwright 必须证明：

- 默认 MACD；
- Tab 顺序 `MACD / 主力照妖镜 / 原型V0`；
- 60m actual_dominant 可打开 V1；
- 15m、continuous disabled；
- 切换不 refetch bars；
- 三类 pane series/markers 相互清理；
- 双向 marker、文案、score 正确；
- “70 非资金比例”可见；
- 换月后 warm-up；
- 无水平溢出；
- production build 通过。

### 17.5 仓库回归

按 `TESTING.md` 执行 backend、registry/policy、Ruff、Mypy、Web unit、Market E2E、Web build、secret scan、`git diff --check`。测试不运行 provider、DB/Canonical 写入、Runtime switch 或真实通知。

## 18. 验收标准

必须同时满足：

1. V0 code/version/golden/capability 零变化；
2. V1 只支持 60m + contract/actual_dominant；
3. ready Bar 具有精确 physical contract；
4. 换月和 invalid gap 后重新 warm-up；
5. 五状态与价格/OI 四象限一致；
6. 双向评分由精确四项证据组成，阈值固定 70；
7. latch/re-arm 不连续刷屏；
8. Python/Web 逐点一致；
9. UI 不把 70 表述为百分比、概率或实测资金流；
10. 无 Alert、notification、DB、Canonical、Runtime 或订单新路径；
11. Shadow 只读、segment-local、无自动晋升；
12. 独立 Review 为 Critical=0 / Important=0。

通过只能得出：

```text
main_force_mirror_futures_v1 Web observation implementation verified on develop
```

不能得出策略有效、可盈利、可发正式 Alert、可 Runtime promotion 或可自动交易。

## 19. 推荐实施顺序

后续 implementation plan 拆为：

```text
Task 1  Python domain contract + exact math + RED/GREEN
Task 2  Registry/Policy + segment reset + V0 regression
Task 3  Web physicalContract mapping + Python/Web golden
Task 4  V1 pane/hover + three-tab Playwright
Task 5  Historical Shadow CLI/service + representative matrix tests
Task 6  Full regression + docs + independent Review
```

前四项形成 Web observation；Task 5 形成研究证据入口；Task 6 才允许 develop-only 收口。

## 20. 人工 Gate

本 Spec 审阅通过后，下一步只生成 implementation plan 与 TASK contracts。

后续代码可以在批准后集成 `develop`，但以下始终是独立 Gate：

```text
release/main/tag
Runtime reload/promotion
真实 Shadow 运行并保存正式 evidence
新增 Alert Rule/Scope
真实通知
DB/Canonical 写入
```

AI 可以自动研究并生成报告，但不能自动晋升 V1。