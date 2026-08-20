# 主力照妖镜·期货 V1 设计规格

> 状态：Design approved after user review；9 项实现歧义已逐条关闭，可作为 implementation plan 的唯一设计输入。
>
> 日期：2026-08-19
>
> 最新审阅基线：`develop@768fd3786df63b925d589302a943144c552870bc`
>
> GitHub Issue：`#179`
>
> 现有版本：`main_force_mirror_v0` / `designed-v0`
>
> 新版本：`main_force_mirror_futures_v1` / `futures-research-v1`
>
> 本文只定义期货专用 observation V1；不修改已经发布的 V0，不授权 Alert、通知、正式回测晋升、release、tag、main 或 Runtime promotion。

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
→ stable reason codes
→ Historical Shadow 统计
```

V1 的“70”精确定义为**风险证据评分阈值 70/100**，不是资金流出比例、反转概率、会员席位结论或账户级事实。

## 2. 当前仓库事实

设计基线下：

- production Git release 与 Runtime 为 `v1.6.1`；
- V0 已发布并存在于当前 Web 观察面；
- Python Indicator Kernel 是指标业务口径唯一权威；
- V0 authority 为 `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py`；
- V0 Web mirror 为 `apps/quant-web/src/utils/mainForceMirror.ts`；
- 当前最底部 pane 通过 `MACD / 主力照妖镜` Tab 二选一；
- Canonical Bar 与 Web `BarData` 已包含 `open_interest / openInterest`；
- 5m/15m/30m/60m 聚合时 OI 取桶内最后一根 Canonical 1m Bar；
- `/api/v1/market/bars/page` 已返回 `resolved_contract_segments`；
- `useMarketSeries()` 当前尚未把每根 Bar 的真实物理合约身份传入指标层；
- WebSocket `snapshot` 已返回精确 `contract`；
- 当前没有会员多空持仓排名、逐笔主动买卖、Level-2 或账户身份数据。

因此 V1 只能定义为**方向性持仓压力代理**，不能声称识别了具体“主力”账户。

## 3. 产品目标

V1 首版只解决四个问题：

1. 区分价格运动由增仓还是减仓驱动；
2. 建立对称的“追多小心 / 追空小心”；
3. 以方向 Episode latch 降低固定 K 线冷却产生的重复噪声；
4. 输出可解释状态、分数、原因和后续结果，积累复盘证据。

它必须明确提高至少一项长期价值：

- 减少个人盯盘时判断“多增、空增、空减、多减”的成本；
- 提高追多/追空风险识别的一致性；
- 增加后续 Shadow 与人工复盘可用的结构化证据。

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

`web=true` 允许浏览器对 Historical 与 completed Live/Post-close Bars 做只读观察。

`live=false` 表示没有正式 live consumer、Runtime evaluator、Alert evaluator 或交易能力。

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
- 不生成 `outflow_ratio`、`main_force_ratio` 或“70% 已流出”字段；
- 不新增 Market Catalog 表、Canonical 字段、Parquet 副本或长期派生数据表；
- 不新增 DB、migration、Redis 状态、worker、queue、outbox；
- 不新增 Alert Rule、Scope、Clawbot、Execution Review 自动入口；
- 不恢复通用 backtest API/Web/worker；
- 不连接账户，不产生订单，不自动改变仓位；
- 不根据 Shadow 结果自动晋升；
- 不修改 `main`、release、tag 或 production Runtime。

未来若接会员持仓或 L2，必须另立 Data Foundation/provider 合同任务。

## 5. Indicator Registry、固定参数与 readiness

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

当前 `test_indicator_registry_v1.py` 中“所有指标都支持七周期”的全局断言改为**逐指标支持集断言**：

- 现有指标继续保持原七周期合同；
- `main_force_mirror_futures_v1` 精确为 `("60m",)`。

这不改变 Data Foundation 的七周期，只允许具体指标声明支持子集。

### 5.2 Exact parameters

Registry `default_parameters`、Python metadata 与 Web constant 精确冻结为：

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
  "liquidation_dominated_oi_threshold": 0.5,
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
  "round_digits": 6,
  "rounding_policy": "half_away_from_zero_binary64"
}
```

原草案参数名 `closing_dominated_oi_threshold` 正式更名为：

```text
liquidation_dominated_oi_threshold
```

该参数只描述“减仓主导”阈值，不涉及收盘价形态。

同一 indicator code/version 下不得静默修改任何参数；任何研究调整必须产生新 version。

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

未知 consumer 必须 fail-closed。

### 5.4 readiness 的闭式定义

在单个 calculation block 内，以零基 `block_index` 表示当前 Bar 在该 block 中的位置。

各基础序列首次可用位置：

```text
ATR14:
  block_index >= 13
  需要 14 根 Bar

SMA(volume,20):
  block_index >= 19
  需要 20 根 Bar

HHV/LLV20:
  block_index >= 19
  需要 20 根 Bar

delta_oi:
  block_index >= 1

EMA(abs(delta_oi),20) 的 SMA seed:
  第一批 delta_oi 为 index 1..20
  因此首次可用 block_index = 20
  需要 21 根 Bar
```

基础状态 readiness：

```text
state_ready_t =
  valid_t
  and block_index_t >= 20
  and ATR14_t finite and > 0
  and volume_ratio_t finite
  and oi_impulse_t finite
  and range_position_t finite
```

因此第一根 `state_ready=true` 的 Bar 是：

```text
block_index = 20
block_bar_count = 21
```

压力背离需要当前 Bar 之前连续 10 个 `state_ready` points：

```text
pressure_divergence_window = 10
```

完整警戒 readiness：

```text
caution_ready_t =
  state_ready_t
  and previous 10 Bars in the same block all state_ready
```

因此第一根 `caution_ready=true` 的 Bar 是：

```text
block_index = 30
block_bar_count = 31
```

通用完整输出 readiness：

```text
ready_t = caution_ready_t
```

Registry 两个数字的精确含义：

```text
warmup_bars = 30
```

表示每个 calculation block 前 30 根 Bar 不可能产生 `ready=true` 的完整 V1 point。

```text
lookback_bars = 31
```

表示产生第一根完整 `ready=true` point 所需的最少同 block、连续 valid Bars 数。

为了保留观察价值，输出合同同时暴露：

```text
state_ready
caution_ready
ready
```

规则：

- `state_ready=true && caution_ready=false` 时可以输出五状态、基础特征、strength 与 signed score；
- 该阶段 `long_caution_score / short_caution_score / caution` 均为 unavailable；
- 只有 `caution_ready=true` 才计算完整四项评分、candidate、conflict、latch 与 re-arm；
- 不允许把缺失的 caution 分量当 0 形成“部分评分”。

## 6. 物理合约身份、输入有效性与 calculation block

### 6.1 Web Bar 身份

`BarData` 增加：

```ts
physicalContract?: string
```

它表示每根 Bar 的真实物理合约，不等同于页面查询参数中的逻辑 `series_kind`。

#### `series_kind=contract`

Historical Bar：

```text
physicalContract = normalized request.contract
```

Completed Live/Post-close Bar 仅在 WebSocket physical identity 与请求合约一致时绑定。

#### `series_kind=actual_dominant`

Historical page 对每根 Bar 按 `trading_day` 在 `resolved_contract_segments` 中查找：

```text
start_trading_day <= trading_day <= end_trading_day
```

必须精确命中一个 segment：

- 0 个：`MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING`；
- 多于 1 个：`MFM_FUTURES_V1_SEGMENT_CONFLICT`；
- 1 个：绑定规范化后的 segment contract。

initial page 与每个 prepend page 都独立映射，不依赖页外猜测。

Completed Live/Post-close `snapshot` 使用 payload 的精确 `contract`。

普通 `bar` 消息只复用已经建立的 overlay physical identity；若 bar 先于 identity 到达，不使用 `live_contract` 猜测，当前 V1 point unavailable。

#### `series_kind=continuous`

不绑定 physical contract，V1 unavailable。

### 6.2 valid input 与 OI 缺失

一根 Bar 只有同时满足以下条件才是 valid input：

```text
time 可解析
time 严格大于此前所有已见的可解析 timestamp
physical_contract 为非空规范化合约字符串
open/high/low/close/volume/open_interest 均为有限数
high >= max(open, close)
low <= min(open, close)
high >= low
volume >= 0
open_interest >= 0
```

`open_interest` 是 V1 的必需输入。

以下任一情况：

```text
open_interest missing
open_interest null
open_interest NaN / Infinity
open_interest < 0
```

均表示整根 Bar invalid，并结束当前 calculation block。

不支持以下部分降级：

```text
state 能算但 caution 不能算
```

原因是 V1 的五状态本身就依赖 OI 方向。

`MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE` 是 `INPUT_INVALID` 的**诊断细分码**，不是部分可用状态。

原因优先级见第 15 节；OI 失败时输出专用码，不再输出泛化 `INPUT_INVALID`。

### 6.3 valid、state_ready、caution_ready 与 ready

```text
valid =
  当前 Bar 的数据、timestamp 与 physical identity 全部有效

state_ready =
  valid 且满足第 5.4 节基础状态 warm-up

caution_ready =
  state_ready 且满足第 5.4 节完整警戒 warm-up

ready =
  caution_ready
```

不得把 invalid、unsupported、unavailable 或 warm-up 输出成数值 0。

### 6.4 timestamp 失败的精确处理

序列按输入顺序处理，并维护：

```text
max_seen_parseable_time
```

若当前时间：

```text
不可解析
或
<= max_seen_parseable_time
```

则：

1. 当前 Bar 自身 invalid；
2. 当前 Bar 输出 `MFM_FUTURES_V1_TIMESTAMP_INVALID`；
3. 当前 Bar 立即结束旧 calculation block；
4. 当前 Bar**不得**作为新 block 的第一根；
5. 所有 rolling、EMA、pressure、latch、re-arm 状态清空；
6. 第一根后续同时满足所有输入条件、且 timestamp `> max_seen_parseable_time` 的 Bar 才能成为新 block 的 `block_index=0`。

可解析但乱序的 timestamp 仍更新 `max_seen_parseable_time` 的历史最大值，不允许后续 Bar 仅因大于“乱序 Bar”但仍小于此前历史最大值而被接纳。

### 6.5 calculation block

Python 与 Web 都切分 maximal contiguous blocks。

以下任一事件结束旧 block：

- `physical_contract` 改变；
- physical identity missing/conflict；
- required input invalid；
- OI unavailable；
- timestamp invalid/non-increasing。

合约变化时：

- 新合约当前 Bar 若本身 valid，可直接作为新 block 的 `block_index=0`；
- 这是合法 identity transition，不把该 Bar标记为 invalid。

输入或 timestamp 失败时：

- 失败 Bar 自身 unavailable；
- 真正的新 block 从之后第一根 valid Bar 开始。

新 block 从零 warm-up，并重置：

```text
ATR14
SMA(volume,20)
EMA(abs(delta_oi),20)
HHV/LLV20
prior pressure window
long/short armed latch
all re-arm counters
```

无效 Bar 之后的有效 Bar不得继承无效 Bar之前的状态。

## 7. Exact 60m 数学口径

所有公式只使用当前及过去 completed Bars。

所有阈值判断使用未 round 的内部 binary64 数值；round 只发生在公开数值输出阶段。

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

`ATR14 <= 0` 时当前 derived point unavailable，但只要原始输入 valid，不结束 calculation block。

### 7.2 Price impulse、CLV 与 direction

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
direction_t =
  0.7 * price_impulse_t
  + 0.3 * clv_t
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

滚动均值 `<=0` 时当前 derived point unavailable，但原始输入 valid 时不结束 block。

### 7.4 OI impulse

```text
delta_oi_t = open_interest_t - open_interest_{t-1}
```

```text
oi_abs_baseline_t = EMA(abs(delta_oi),20)
```

EMA20 使用 SMA seed：

```text
seed = mean(abs(delta_oi_1)..abs(delta_oi_20))
alpha = 2 / 21
EMA_t = alpha * value_t + (1-alpha) * EMA_{t-1}
```

```text
if oi_abs_baseline_t == 0:
  oi_impulse_t = 0
else:
  oi_impulse_t = clip(
    delta_oi_t / oi_abs_baseline_t,
    -3,
    3
  )
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

`range_high == range_low` 时当前 derived point unavailable，不结束 valid input block。

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

### 7.7 统一舍入算法

公开数值输出统一采用：

```text
rounding_policy = half_away_from_zero_binary64
round_digits     = 6
```

精确算法：

```text
scale = 10 ** digits

if value == 0:
  result = 0
else:
  result =
    sign(value)
    * floor(abs(value) * scale + 0.5)
    / scale
```

其中：

```text
sign(value) =
  +1 when value > 0
  -1 when value < 0
   0 when value == 0
```

规则：

- Python 与 TypeScript 必须使用相同 binary64 运算顺序；
- 不使用 Python 内建 `round()`；
- 不使用 JavaScript `toFixed()` 作为数学实现；
- round 后的 `-0` 规范化为 `0`；
- 状态、candidate、阈值、reason 判断全部基于未 round 原值；
- 仅公开数组、golden fixture、hover 数值和 JSON 输出执行该 round；
- parity 测试必须包含正负 half-tie 用例。

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
| `>= +0.15` | `>= +0.25` | `LONG_BUILD` | 上涨伴随增仓，更偏多头新增压力 |
| `<= -0.15` | `>= +0.25` | `SHORT_BUILD` | 下跌伴随增仓，更偏空头新增压力 |
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

`TURNOVER` 的零方向边界精确为：

```text
direction == 0
→ sign(direction) == 0
→ signed_score == 0
```

即使未来 strength 公式调整导致非零中间值，该分支仍固定输出 0；V1 当前公式下 `direction==0` 同时会令 strength 为 0。

状态解释始终使用“更偏向”，不表述为账户级确定事实。

## 9. 双向风险评分

V1 不使用 V0 的 `HHV5 / BARSLAST10` 作为触发器。

V0 原公式继续只属于 V0。

```text
long_caution_score  = 四项证据加权和
short_caution_score = 四项证据加权和
CAUTION_THRESHOLD   = 70
```

只有 `caution_ready=true` 时才计算完整分数。

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

`0.50` 来自：

```text
liquidation_dominated_oi_threshold
```

#### `LONG_OPEN_PRESSURE_DIVERGENCE`，25 分

使用当前 Bar 之前同一 block 的 10 个连续 `state_ready` points：

```text
prior_high = max(high_{t-10}..high_{t-1})
prior_long_pressure =
  max(long_open_pressure_{t-10}..long_open_pressure_{t-1})

high_t > prior_high
and prior_long_pressure > 0
and long_open_pressure_t
    <= 0.70 * prior_long_pressure
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
prior_short_pressure =
  max(short_open_pressure_{t-10}..short_open_pressure_{t-1})

low_t < prior_low
and prior_short_pressure > 0
and short_open_pressure_t
    <= 0.70 * prior_short_pressure
```

#### `SHORT_LOW_PRICE_ABSORPTION`，15 分

```text
lower_wick_ratio =
  (min(open,close) - low) / (high-low)
```

`high==low` 时为 0。

```text
volume_ratio >= 1.50
and (
  clv >= -0.25
  or lower_wick_ratio >= 0.35
)
```

### 9.3 candidate 与方向冲突

```text
long_candidate =
  caution_ready
  and long_caution_score >= 70

short_candidate =
  caution_ready
  and short_caution_score >= 70
```

正常事件：

```text
LONG_CHASE_CAUTION  → 追多小心
SHORT_CHASE_CAUTION → 追空小心
```

同一 Bar 若：

```text
long_candidate == true
and short_candidate == true
```

则：

```text
caution = null
reason  = MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT
```

精确 latch 行为：

- 不输出任一方向事件；
- 不创建 Shadow event；
- `long_armed` 与 `short_armed` 均保持进入该 Bar 前的值；
- 不消耗任一 armed latch；
- 不执行任一侧 re-arm 判断；
- 所有 re-arm counters 在该 Bar 暂停，既不递增也不清零；
- 下一根非冲突 `caution_ready` Bar 可以在原 latch 状态下立即触发合法方向事件。

该选择遵循 fail-closed：异常冲突不能隐藏下一次有效方向警戒。

## 10. Episode latch 与 re-arm

每个 calculation block 开始：

```text
long_armed  = true
short_armed = true
```

每个 side 独立维护：

```text
low_score_streak
build_streak
```

初始均为 0。

### 10.1 事件处理顺序

每根 `caution_ready` 且非 conflict Bar：

1. 使用进入当前 Bar 前的 latch 状态判断 candidate；
2. 若 `long_armed && long_candidate`，输出一次追多小心；
3. 若 `short_armed && short_candidate`，输出一次追空小心；
4. 触发侧立即 `armed=false`；
5. 触发侧两个 re-arm counters 立即清零到 0；
6. 事件 Bar 对触发侧不执行 re-arm；
7. 未触发侧继续按第 10.2/10.3 节更新自己的 re-arm；
8. re-arm 在当前 Bar 结束后生效，最早下一根才能再次触发。

多空 latch 独立；同一非 conflict Bar 最多输出一个方向事件。

### 10.2 Long re-arm

仅当：

```text
long_armed == false
```

时更新计数。

低分计数：

```text
if long_caution_score < 40:
  long_low_score_streak += 1
else:
  long_low_score_streak = 0
```

新增多头确认计数：

```text
if state == LONG_BUILD:
  long_build_streak += 1
else:
  long_build_streak = 0
```

re-arm 条件：

```text
long_low_score_streak >= 3
and (
  range_position < 0.65
  or long_build_streak >= 2
)
```

满足后：

```text
long_armed = true
long_low_score_streak = 0
long_build_streak = 0
```

### 10.3 Short re-arm

仅当：

```text
short_armed == false
```

时更新计数。

```text
if short_caution_score < 40:
  short_low_score_streak += 1
else:
  short_low_score_streak = 0
```

```text
if state == SHORT_BUILD:
  short_build_streak += 1
else:
  short_build_streak = 0
```

re-arm 条件：

```text
short_low_score_streak >= 3
and (
  range_position > 0.35
  or short_build_streak >= 2
)
```

满足后：

```text
short_armed = true
short_low_score_streak = 0
short_build_streak = 0
```

### 10.4 pause、reset 与 off-by-one 规则

- ready Bar 上任一 streak 条件中断时，计数器直接清零到 0；不得递减 1，也不得保留部分值；
- `state_ready=true && caution_ready=false` 时，不推进 latch 或 re-arm；
- derived unavailable 但原始 input valid 的 Bar 暂停计数，不清零，不结束 block；
- conflict Bar 暂停所有 latch/re-arm 更新；
- input invalid、OI unavailable、identity failure、timestamp failure 会结束 block并将 latch/counters重置；
- physical contract 合法切换会开启新 block并重置 latch/counters；
- armed side 的 counters 始终保持 0。

## 11. Python Kernel 输出合同

新增：

```text
packages/quant-core/guiyi_quant/indicators/
└── main_force_mirror_futures.py
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
```

```python
@dataclass(frozen=True)
class MainForceMirrorFuturesResult:
    datetimes: np.ndarray
    physical_contract: np.ndarray

    valid: np.ndarray
    state_ready: np.ndarray
    caution_ready: np.ndarray
    ready: np.ndarray

    reason: np.ndarray
    caution_availability_reason: np.ndarray

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

输出规则：

- `state_ready=false` 时 state 与所有基础数值使用 `None/NaN`，不补 0；
- `state_ready=true && caution_ready=false` 时可输出 state/strength/features；
- 该阶段 caution scores/caution/reason codes unavailable；
- `ready` 精确等于 `caution_ready`；
- conflict 时 `caution=null`，并使用 conflict reason；
- public numeric arrays 按第 7.7 节 round；
- metadata 必须包含 code/version/status、supported frequency/series、future/repainting、capability、parameters、parameters_hash、rounding policy、`auto_order=false`；
- metadata 必须包含：

```text
interpretation =
directional_position_pressure_proxy_not_measured_fund_flow
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

V1 Tab 仅在：

```text
60m + contract
或
60m + actual_dominant
```

可选择。

身份支持但局部 Bar 缺失 OI/segment 时，Tab 仍可打开，缺失区间逐点显示 unavailable。

Pane availability 在支持集与可见范围校验后，只读取当前可见范围最右侧 point，也就是用户正在观察的
最新 physical-contract block。该 point 的 unavailable、state warm-up、caution warm-up、conflict 或 ready
状态直接决定 Pane 文案；左侧旧合约的 ready point 不得覆盖右侧新合约 warm-up。可见范围没有 point 时显示
精确无数据说明。

continuous 或其他周期直接 disabled。

切换 Tab 不得：

- refetch bars；
- 改变主图 overlay；
- 改变 EMA 偏好；
- 改变行情 identity；
- 改变 Alert markers；
- 改变 pane 数量。

### 12.2 柱体与 scale

```text
零轴上方：LONG_BUILD / SHORT_COVER
零轴下方：SHORT_BUILD / LONG_LIQUIDATION
零轴附近：TURNOVER
```

颜色只使用 chart theme token；业务函数不硬编码颜色。

V1 histogram scale 固定：

```text
[-105,+105]
```

该 scale 只约束柱体，不再承载 caution 固定数值点。

### 12.3 动态 caution marker

删除原草案固定坐标：

```text
+92 / -92
```

不创建会参与 price scale 的 caution histogram 数据点。

marker 使用 Lightweight Charts series marker，附着在 V1 histogram series 对应 Bar：

```text
LONG_CHASE_CAUTION:
  position = aboveBar
  shape    = arrowDown
  text     = 追多小心 {score}

SHORT_CHASE_CAUTION:
  position = belowBar
  shape    = arrowUp
  text     = 追空小心 {score}
```

marker 由图表布局浮在当前柱体外侧，不占用 `[-105,+105]` 数值坐标，因此 strength 95..100 时不会与固定 92 位置重叠。

conflict 不绘制方向 marker；Hover 显示 conflict reason。

图例固定：

```text
70 = 风险证据评分阈值，不是资金流比例或概率
```

### 12.4 Hover

至少展示：

```text
物理合约
状态
state_ready / caution_ready
柱体强度
价格冲击
量比20
OI变动
OI冲击
20 Bar位置
追多评分
追空评分
警戒原因
availability reason
```

缺失显示 `—`，不得补 0。

## 13. V0 共存

V0 的 code/version/formula/golden/capability 全部保持不变。

V1 实施期间：

```text
MACD        → 默认
主力照妖镜  → Futures V1
原型V0      → 当前 main_force_mirror_v0
```

只有在 V1 完成 Shadow、用户人工接受，并另开 UI 收口任务后，才允许从默认 UI 移除“原型V0”。

即使未来移除 UI，V0 Registry 与 Git 历史仍保留。

## 14. Historical Shadow

### 14.1 唯一链路

```text
MarketDataService
→ actual_dominant / contract 60m
→ resolved physical segments
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

conflict 不创建 caution event，只进入诊断计数。

### 14.4 Outcome

同一 physical contract segment 内：

```text
horizons = [1,3,5,10] completed 60m bars
```

追多：

```text
reversal_return_h =
  (close_t - close_{t+h}) / close_t

warning_mfe_h =
  (close_t - min(low_{t+1..t+h})) / close_t

warning_mae_h =
  (max(high_{t+1..t+h}) - close_t) / close_t
```

追空：

```text
reversal_return_h =
  (close_{t+h} - close_t) / close_t

warning_mfe_h =
  (max(high_{t+1..t+h}) - close_t) / close_t

warning_mae_h =
  (close_t - min(low_{t+1..t+h})) / close_t
```

跨 segment 的 outcome unavailable。

### 14.5 汇总

```text
bars_valid_count
bars_state_ready_count
bars_caution_ready_count
event_count_long / short
conflict_count
events_per_1000_caution_ready_bars
state_distribution
reason_code_distribution
score_distribution
forward_reversal_return distribution
warning_mfe / warning_mae distribution
missing_oi_count
segment_reset_count
timestamp_invalid_count
```

不输出盈利保证、自动参数建议或晋升结论。

### 14.6 CLI

implementation plan 增加只读命令：

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

真实代表矩阵运行和正式 evidence 保存是后续独立人工 Gate，不由代码实现任务授权。

## 15. Stable unavailable reason codes 与优先级

稳定 reason 至少包括：

```text
MFM_FUTURES_V1_FREQUENCY_UNSUPPORTED
MFM_FUTURES_V1_SERIES_UNSUPPORTED

MFM_FUTURES_V1_SEGMENT_CONFLICT
MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING

MFM_FUTURES_V1_TIMESTAMP_INVALID
MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE
MFM_FUTURES_V1_INPUT_INVALID

MFM_FUTURES_V1_WARMUP
MFM_FUTURES_V1_CAUTION_WARMUP

MFM_FUTURES_V1_ATR_INVALID
MFM_FUTURES_V1_VOLUME_BASELINE_INVALID
MFM_FUTURES_V1_RANGE_INVALID

MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT
```

同一 Bar reason 优先级：

```text
1 frequency unsupported
2 series unsupported
3 segment conflict
4 physical contract missing
5 timestamp invalid
6 open interest unavailable
7 generic input invalid
8 state warm-up
9 ATR / volume baseline / range derived unavailable
10 caution warm-up
11 caution direction conflict
12 ready
```

规则：

- OI 缺失是整根 Bar invalid，但用专用 OI reason；
- `INPUT_INVALID` 只处理除 identity、timestamp、OI 之外的 required input/OHLC/volume 失败；
- `CAUTION_WARMUP` 只影响 caution 字段，不抹掉已经 `state_ready` 的状态柱；
- conflict Bar 基础 state 可以保持 ready，但 directional caution fail-closed；
- UI 必须区分 unsupported、input unavailable、state warm-up、caution warm-up、conflict 与 ready；
- 不得把 unavailable 当 TURNOVER。

## 16. 文件边界

### 16.1 新增

```text
packages/quant-core/guiyi_quant/indicators/
└── main_force_mirror_futures.py

apps/quant-web/src/utils/
└── mainForceMirrorFutures.ts

services/quant-api/tests/
└── test_main_force_mirror_futures.py

apps/quant-web/tests/
└── mainForceMirrorFutures.test.ts

apps/quant-web/e2e/
└── main-force-mirror-futures.spec.mjs
```

Shadow：

```text
services/quant-api/app/market_data/
└── main_force_mirror_futures_research_service.py

services/quant-api/tests/data_foundation/
└── test_main_force_mirror_futures_research_service.py
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

Shadow CLI：

```text
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/test_research_cli.py
```

`STATUS.md` 只能在完整实现、仓库原生验证和独立 Review 通过后记录 develop-only 事实。

### 16.3 禁止修改

```text
main_force_mirror_v0 formula/version/golden
DatasetKey
八表 Market Catalog
Canonical schema
Alert registry / Rule / Scope / evaluator
Clawbot / owner / transport
Execution Review
production DB / migration
main / release / tag / Runtime worktree
```

## 17. 测试矩阵

### 17.1 Kernel exact math

必须覆盖：

- ATR14 Wilder SMA seed；
- volume SMA20；
- OI abs-delta EMA20 SMA seed；
- exact parameters hash；
- 参数名精确为 `liquidation_dominated_oi_threshold`；
- deadband `0.15 / 0.25`；
- 四象限与 TURNOVER；
- TURNOVER display cap 15；
- `direction==0 → signed_score==0`；
- signed score 与 100 cap；
- long/short pressure；
- 八个 caution reasons；
- score 69 不触发、70 触发；
- 正负 half-tie rounding；
- round 前阈值判断；
- prefix invariance；
- V0 output hash 不变。

### 17.2 readiness

必须覆盖闭式边界：

```text
block index 12:
  ATR not ready

block index 13:
  ATR ready

block index 18:
  volume/range not ready

block index 19:
  volume/range ready

block index 19:
  OI baseline not ready

block index 20:
  state_ready=true
  caution_ready=false
  ready=false

block index 29:
  只有 9 个 prior state_ready points
  caution_ready=false

block index 30:
  具有 10 个 prior state_ready points
  caution_ready=true
  ready=true
```

还必须覆盖：

- `lookback_bars=31`；
- `warmup_bars=30`；
- state 可输出但 caution 不得部分补 0；
- invalid gap 后重新从 block index 0 warm-up。

### 17.3 OI、input 与 timestamp

必须覆盖：

- missing/null/NaN/Infinity/negative OI；
- OI 失败输出专用 reason；
- OI 失败整根 invalid，state/caution 均不可用；
- OI 失败结束 block；
- generic OHLC/volume invalid 输出 `INPUT_INVALID`；
- timestamp parse failure；
- timestamp duplicate；
- timestamp regression；
- offending timestamp Bar 本身不成为新 block seed；
- 后续 timestamp 未超过历史最大值仍 invalid；
- 第一根超过历史最大值的 valid Bar成为新 block index 0。

### 17.4 conflict 与 latch

必须覆盖：

- 单 long candidate 消耗 long latch；
- 单 short candidate 消耗 short latch；
- conflict 不输出 directional event；
- conflict 不创建 Shadow event；
- conflict 不消耗任一 latch；
- conflict 不更新或清零 re-arm counters；
- conflict 后下一根合法 candidate 可立即触发；
- long/short latch 独立；
- event Bar 不对触发侧执行 re-arm；
- re-arm 在 Bar 结束后生效。

### 17.5 re-arm counters

必须覆盖：

- low-score streak 条件中断直接清零；
- build streak 条件中断直接清零；
- 不允许 `-1` 或递减语义；
- unavailable/warm-up pause；
- input invalid reset；
- 合约切换 reset；
- long range re-arm；
- long build re-arm；
- short range re-arm；
- short build re-arm；
- armed side counters 固定为 0。

### 17.6 Segment identity

必须覆盖：

- contract Bars 绑定请求合约；
- actual_dominant 精确命中 segment；
- 0/多命中 fail-closed；
- prepend page 映射；
- snapshot contract；
- 无 identity 的 bar 不猜合约；
- A→B 巨大价格/OI 跳变后 B 重新 warm-up；
- B 不产生假柱/假 caution；
- outcome 不跨 segment。

### 17.7 Python/Web parity

同一 deterministic fixture 至少包含：

```text
两个 physical contracts
五状态
一个追多小心
一个追空小心
一次 conflict
一次 re-arm
一个 missing OI gap
一个 timestamp regression
正负 half-tie round
state_ready 与 caution_ready 边界
```

逐点核对：

```text
valid
state_ready
caution_ready
ready
reason
caution_availability_reason
state
所有核心数值
signed_score
strength
long/short score
caution
reason codes
```

### 17.8 Web

Playwright 必须证明：

- 默认 MACD；
- Tab 顺序 `MACD / 主力照妖镜 / 原型V0`；
- 60m actual_dominant 可打开 V1；
- 60m contract 可打开 V1；
- 15m、continuous disabled；
- 切换不 refetch bars；
- 三类 pane series/markers 相互清理；
- 双向 marker、文案、score 正确；
- marker 不创建固定 ±92 数值点；
- strength 100 与 marker 不重叠改变 scale；
- “70 非资金比例”可见；
- 使用两个不重叠 `resolved_contract_segments` 真实经过 A→B 换月，并证明 B 第 10 根 state warm-up、
  第 21 根 state ready/caution warm-up、第 31 根完整 ready；
- B block 左右边缘 Hover 都显示 B 物理合约，且收窄到 B 后不继承 A marker；
- OI unavailable 与 warm-up 文案不同；
- Hover 缺失显示 `—`；
- 无水平溢出；
- production build 通过。

V0 冻结回归必须证明 `main_force_mirror.py` 与 V1 开发前批准基线逐字一致；为保持完整静态类型门禁，
同名 `main_force_mirror.pyi` 可作为只含公开合同的类型 facade，但不得改变运行时实现、公式、输出、
version、golden 或 capability。

### 17.9 Shadow

必须覆盖：

- 只经 `MarketDataService`；
- contract / actual_dominant 60m；
- continuous/其他周期 fail-closed；
- conflict 不进入 event；
- 1/3/5/10 outcome；
- outcome 不跨 segment；
- representative matrix 只作为 fixture/参数合同，不执行真实研究；
- stdout JSON；
- 无 DB/Canonical/Redis 写入；
- 不生成晋升结论。

### 17.10 仓库回归

按 `TESTING.md` 执行：

- backend；
- indicator registry/policy；
- Ruff；
- Mypy；
- Web unit；
- Market E2E；
- Web build；
- secret scan；
- `git diff --check`。

测试不运行 provider、production DB/Canonical 写入、Runtime switch 或真实通知。

## 18. 验收标准

必须同时满足：

1. V0 code/version/golden/capability 零变化；
2. V1 只支持 60m + contract/actual_dominant；
3. ready Bar 具有精确 physical contract；
4. OI 缺失整根 invalid，并使用专用 reason；
5. timestamp offending Bar 不成为新 block seed；
6. 换月和 invalid gap 后重新 warm-up；
7. `state_ready` 首次为第 21 根，完整 `ready` 首次为第 31 根；
8. 五状态与价格/OI 四象限一致；
9. `TURNOVER + direction=0` 输出 0；
10. 双向评分由精确四项证据组成，阈值固定 70；
11. conflict 不消耗 latch，不创建 directional event；
12. re-arm counters 中断清零，unavailable 暂停；
13. Python/Web 使用统一 half-away-from-zero round；
14. Python/Web 逐点一致；
15. caution marker 不使用固定 ±92 数值坐标；
16. UI 不把 70 表述为百分比、概率或实测资金流；
17. 无 Alert、notification、DB、Canonical、Runtime 或订单新路径；
18. Shadow 只读、segment-local、无自动晋升；
19. 独立 Review 为 Critical=0 / Important=0。

通过只能得出：

```text
main_force_mirror_futures_v1
Web observation implementation verified on develop
```

不能得出：

```text
策略有效
可盈利
可发正式 Alert
可 Runtime promotion
可自动交易
```

## 19. 推荐实施顺序

implementation plan 拆为：

```text
Task 1  Python exact policy/domain/readiness/rounding contracts
Task 2  Python math/state/caution/latch kernel + V0 regression
Task 3  Web physicalContract mapping and segment-local identity
Task 4  Web mirror + shared Python/Web golden parity
Task 5  Three-tab pane, dynamic markers and hover
Task 6  Historical Shadow service/CLI
Task 7  Full regression, docs, independent Review and develop closeout
```

Tasks 1–5 形成 Web observation。

Task 6 形成只读研究入口。

Task 7 才允许 develop-only 收口。

## 20. 人工 Gate

本 Spec 已按用户 Review 修正，可以直接进入 implementation plan 与 TASK contract。

后续代码在用户批准实现任务后，可以按 Task 集成 `develop`。

以下始终是独立人工 Gate：

```text
release / main / tag
Runtime reload / promotion
真实代表矩阵 Shadow 运行
正式 evidence 保存
新增 Alert Rule / Scope
真实通知
DB / Canonical 写入
任何订单或账户连接
```

AI 可以自动研究并生成报告，但不能自动晋升 V1。

## 21. 本轮 Review 决议记录

用户提出的 9 项问题按以下方式关闭：

| # | 问题 | 冻结决议 |
| --- | --- | --- |
| 1 | conflict 是否消耗 latch | 不消耗；不事件、不 re-arm，counters 暂停 |
| 2 | ready 门槛 | state 第 21 根；完整 caution/ready 第 31 根；闭式推导写入 5.4 |
| 3 | OI unavailable vs input invalid | OI 是必需输入；缺失整根 invalid，专用 reason 仅作诊断细分 |
| 4 | timestamp offending Bar | 当前 Bar invalid 且不作为新 block seed；后续必须超过历史最大 timestamp |
| 5 | re-arm 连续计数 | ready 条件中断直接清零到 0；unavailable 暂停 |
| 6 | TURNOVER direction=0 | `sign(0)=0`，signed score 固定 0，并列入测试 |
| 7 | 参数命名 | 改为 `liquidation_dominated_oi_threshold` |
| 8 | marker 固定 ±92 | 改为附着 histogram 的动态 series marker，不参与数值 scale |
| 9 | Python/Web 舍入 | 统一 `half_away_from_zero_binary64`，不用 `round()` / `toFixed()` |
