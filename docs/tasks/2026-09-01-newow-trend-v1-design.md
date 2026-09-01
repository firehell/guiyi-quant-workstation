# Newow 牛哇趋势策略 V1 设计

日期：2026-09-01  
状态：`DESIGN_APPROVED / IMPLEMENTATION_NOT_STARTED`  
任务：Issue #293

> 本文是 Newow V1 唯一有效设计源。历史 Newow 草案、分层研究、完整双策略 Spec、观察优先修正及其 amendment 仅从 Git history 追溯，不再保留多份互相覆盖的 active 文档。

## 1. 最终结论

Newow V1 不是“日线杯柄扫描器”，也不是第二套完整量化平台。

第一版交付：

```text
一套完整的牛哇日线趋势观察策略
+
一组未来牛哇震荡策略确实会复用的轻量底层
+
一个杯柄趋势 Setup
+
Historical / Web / active60 盘后 Shadow
```

正确关系：

```text
newow_trend_v1
├── 黄 / 蓝 / 中性趋势状态
├── 趋势启动、延续、回调、再增强、减弱、失效
├── 普通整理区突破
├── 量能、持仓量与 Phase Lite 解释
└── newow_cup_handle_v1 Setup
```

杯柄是牛哇趋势策略消费的一种高质量 Setup，不等于牛哇趋势策略。

## 2. 产品初心与价值

项目中心保持：

> 自动盯盘，辅助决策。机器负责发现和整理机会，用户负责最终判断和下单。

Newow V1 只解决：

1. 盘后自动扫描 active60 的 completed D1，避免人工逐张翻图；
2. 用黄蓝趋势状态、均线、MACD、整理区、成交量/OI 和 Phase Lite 整理第一层判断；
3. 额外识别高质量杯柄，说明杯、柄、枢轴、量能与扣分项；
4. 把少量值得看的变化放进 Web 复核清单；
5. 明确“没有观察”与“系统没有正常扫描”的区别。

与现有产品分工：

```text
SuBing：15m 短线观察与既有正式状态机
Newow：D1 中期趋势和趋势整理观察
HTDY：独立指标观察
```

Newow 不读取、筛选、继承或修改 SuBing/HTDY 的任何 Action、Episode、Snapshot、Alert、Scope 或 Runtime 状态。

## 3. 来源边界

来源材料明确支持：

- 牛哇的蓝变黄、黄变黄、黄变蓝、蓝变蓝四状态表达；
- 基于波动率、偏度和峰度量化涨跌风险的思路；
- 均线转强、均线支撑、突破助涨、涨多乖离、跌深买点等阶段观察；
- 杯柄的上涨背景、平缓杯底、柄部浅回调、缩量、突破和假突破；
- 用户交易资料中的均线方向、MACD 零轴附近交叉、放量突破、持仓量变化、顺势和减少过度交易。

来源材料没有公开：

- 黄蓝带私有公式；
- 偏度峰度窗口与阈值；
- 吸筹、洗盘、拉高、出货的完整算法；
- 牛哇 v3.6 杯柄评分公式；
- 网页收益的全样本、成本、参数选择和样本外证据。

因此本文所有公式、阈值和状态机均是归一量化 clean-room 研究定义，不得描述成牛哇原始公式或已证明盈利能力。

## 4. 产品身份与范围

```text
display_name       = 牛哇趋势策略
strategy_code      = newow_trend_v1
formula_version    = v1
profile_id         = newow_tf_1d_v1
series_kind        = actual_dominant
frequency          = 1d
bar_policy         = completed_only
live_capable       = false
alert_capable      = false
auto_order         = false
```

杯柄身份：

```text
setup_code         = newow_cup_handle_v1
setup_profile      = newow_cup_handle_d1_v1
```

第一版不实现：

```text
牛哇震荡上层策略
15m / 60m Newow
其他命名形态
完整 Structure Graph
通用 Pattern Engine
A/B 仓位与加仓
Target/Risk 执行
Episode / 模拟开平仓
账户、保证金、订单或资金曲线
自动参数优化、winner 选择或晋升
```

## 5. 面向个人维护的架构原则

1. **只有一个实际消费者时不建平台。** V1 不创建 UniversalStrategyAdapter、插件体系或策略 DSL。
2. **只抽取已有两个明确消费者会复用的底层。** 当前趋势策略消费，未来震荡策略复用；不为未知策略预建扩展点。
3. **复用已有数学 Kernel。** EMA、ATR、MACD、`range_detector_lux_v1` 只调用现有权威实现，不复制公式。
4. **一个周期、一个 Profile。** 当前只注册和验证 D1；未来 60m/15m 另建不可变 Profile，不在 V1 写频率分支。
5. **同一逐 Bar 引擎。** Historical 和盘后增量均调用同一个 `step(completed_bar)`。
6. **文件快照优先。** V1 不增加 PostgreSQL 表、Alembic migration、Redis 状态或新 worker queue。
7. **输出观察事实，不输出交易事实。** 不出现 OPEN/CLOSE、仓位、成本、止盈止损指令和 PnL。
8. **先证明盯盘价值。** Web 与 Shadow 先于真实提醒；真实通知必须另行授权。

## 6. 总体架构

```text
MarketDataService
      │
      ▼
actual_dominant + completed D1
      │
      ▼
Newow Shared Core V1
├── Feature Snapshot
├── Phase Lite
├── Structure Lite
├── Key Levels / Evidence
└── Observation Lifecycle
      │
      ▼
Newow Trend V1
├── Trend Band
├── Trend State Machine
├── Generic Lux Range Breakout
├── Pullback / Re-strengthening
└── Cup Handle Setup V1
      │
      ▼
Immutable Historical Snapshot
      │
      ├── Read-only API
      ├── Market Web
      └── active60 After-market Shadow
```

## 7. 共享底层 V1

### 7.1 Profile 与身份

`NewowTimeframeProfile` 只保存真实变化参数，不创建动态注册平台：

```text
profile_id
frequency
atr_period
ema_fast_period
ema_mid_period
ema_slow_period
macd_fast / slow / signal
moment_window
range_parameters_hash
formula_digest
```

当前唯一 Profile：

```text
newow_tf_1d_v1
ATR14
EMA10 / EMA21 / EMA60
MACD 12 / 26 / 9
Moments 60
```

策略实例身份至少绑定：

```text
strategy_code
formula_version
profile_id / profile_hash
series_kind
indicator_policy_digest
```

新增周期不得继承旧周期的事件、Snapshot、Shadow 结果或 OOS 身份。

### 7.2 Feature Snapshot

共享特征：

```text
EMA10
EMA21
EMA60
EMA21 OLS slope（最近5根）
MACD DIF / DEA / histogram
ATR14
DeviationATR
ER20
RV10 / RV40
VolumeRatio20
OIDelta5（可用时）
Skew60
ExcessKurtosis60
```

标准化公式：

```text
spread_atr = (EMA10 - EMA21) / ATR14
slope21_atr = OLS_Slope(EMA21[t-4:t]) / ATR14
DeviationATR = (close - EMA21) / ATR14
ER20 = abs(close_t - close_t-20) / sum(abs(close_i - close_i-1), 20)
VolatilityRatio = RV10 / RV40
VolumeRatio20 = volume_t / median(volume_t-20:t-1)
OIDelta5 = (OI_t - OI_t-5) / abs(OI_t-5)
```

偏度、峰度使用 60 根同物理合约完成 D1 对数收益，固定无偏公式；方差过小、样本不足或非有限值返回 `MOMENTS_UNAVAILABLE`。权威实现不依赖 pandas/SciPy 默认参数。

### 7.3 Phase Lite

技术状态：

```text
BALANCED
EXPANSION_UP
EXPANSION_DOWN
LOWER_EXTREME
LOWER_CONTRACTION
UPPER_EXTREME
UPPER_CONTRACTION
UNAVAILABLE
```

V1 初始研究阈值：

```text
extreme_deviation_atr = 1.00
extreme_skew = 0.50
extreme_excess_kurtosis = 1.00
contraction_delta_atr = 0.20
er_expansion = 0.35
volatility_ratio_expand = 1.10
progress_atr_expand = 2.00
```

下侧极端：

```text
DeviationATR <= -1.00
AND Skew60 <= -0.50
AND ExcessKurtosis60 >= 1.00
```

下侧收缩：

```text
上一根为下侧极端
AND DeviationATR 向0收缩至少0.20
AND abs(Skew60) 下降
```

上侧完全镜像。

Phase Lite 主要进入理由、风险和质量说明，不作为唯一触发器；只有明确的反向扩张可阻塞新趋势观察。

页面只显示“多头扩张、下侧极端、下侧风险收缩”等统计解释，不声称真实识别主力吸筹或出货。

### 7.4 Structure Lite

共享结构只有两部分。

#### CausalExtremeLite

```text
reversal_atr = 1.0
min_leg_bars = 3
```

上涨腿持续跟踪最高 high；completed close 从该高点回撤至少 `1 ATR_at_extreme` 且腿长满足时，才确认此前高点。下降腿完全镜像。

必须区分：

```text
pivot_at       极值发生时间
confirmed_at   后续反转后首次确认时间
```

已确认极值不可被未来数据修改；未确认极值仅供 preview，不进入正式观察。

最近两个同类确认点按 `0.35 ATR` 容差标记 `HH/HL/LH/LL/EQUAL`，不建设完整 BOS/CHOCH/Zone Graph。

#### Lux Range Adapter

直接复用现有 `range_detector_lux_v1`：

```text
range_id
revision
confirmed_at
visual_start_at
frozen_upper
frozen_lower
frozen_mid
status
```

Newow 不复制 Range 公式。当前 Bar 新确认或 revision 的 Range 不得被当前 Bar 同时用于突破。

### 7.5 Key Levels 与 Evidence

`NewowKeyLevelContext` 只整理复核线索：

```text
EMA10 / EMA21 / EMA60
最近确认高点 / 低点
Range upper / middle / lower
当前突破位
趋势失效参考位
杯柄 left rim / bottom / right rim / handle / pivot（存在时）
```

`NewowEvidenceSnapshot` 只输出：

```text
direction
trend_band
phase_state
structure_state
reason_codes
blockers
key_levels
participation_status
cup_handle_setup optional
```

不输出仓位、下单数量、盈亏比或自动交易建议。

### 7.6 Observation Lifecycle

共享生命周期：

```text
NONE
ARMED
CONFIRMED
ACTIVE
PULLBACK
RESTRENGTHENED
WEAKENED
INVALIDATED
EXPIRED
UNAVAILABLE
```

职责：

```text
first_seen_at
confirmed_at
当前是否仍有效
去重
关联失效事件
Shadow / future Alert eligibility
```

Observation Event 永远不可变。后续失效、减弱或恢复使用新事件和 `related_event_id`，不更新原事件。

## 8. 牛哇趋势策略 V1

### 8.1 黄蓝趋势带

```text
spread_atr = (EMA10 - EMA21) / ATR14
slope21_atr = OLS_Slope(EMA21[t-4:t]) / ATR14
```

黄色：

```text
spread_atr >= +0.05
AND slope21_atr >= +0.02
AND close > EMA21
```

蓝色：

```text
spread_atr <= -0.05
AND slope21_atr <= -0.02
AND close < EMA21
```

其余为 `NEUTRAL`。

EMA60 只作为中期质量理由：

```text
EMA21 > EMA60  → 多头质量增强
EMA21 < EMA60  → 空头质量增强
```

不作为 V1 硬开关，避免把趋势初期全部过滤掉。

最近20根忽略 NEUTRAL 后的黄蓝直接切换次数超过3次时输出 `CHOP_BLOCK`，阻塞新的趋势启动和普通突破观察。

### 8.2 MACD 支持

多头支持：

```text
DIF > DEA
AND histogram > 0
```

趋势启动优先要求最近3根内发生金叉，且：

```text
max(abs(DIF), abs(DEA)) / ATR14 <= 0.25
```

已经处于趋势中的延续突破允许：

```text
histogram_t > histogram_t-1 >= 0
```

空头完全镜像。

### 8.3 趋势状态与事件

当前 Snapshot 状态：

```text
NEUTRAL
LONG_STARTED / SHORT_STARTED
LONG_ACTIVE / SHORT_ACTIVE
LONG_PULLBACK / SHORT_PULLBACK
LONG_RESTRENGTHENED / SHORT_RESTRENGTHENED
LONG_WEAKENED / SHORT_WEAKENED
INVALIDATED
UNAVAILABLE
```

重要 first-seen 事件：

```text
TREND_LONG_STARTED
TREND_SHORT_STARTED
TREND_BREAKOUT_LONG
TREND_BREAKOUT_SHORT
TREND_PULLBACK_LONG_WATCH
TREND_PULLBACK_SHORT_WATCH
TREND_RESTRENGTHENED_LONG
TREND_RESTRENGTHENED_SHORT
TREND_LONG_WEAKENED
TREND_SHORT_WEAKENED
TREND_INVALIDATED
```

持续 `ACTIVE` 只更新 Snapshot，不逐日产生 Event。

### 8.4 趋势启动

多头：

```text
上一趋势带不是 YELLOW
当前趋势带为 YELLOW
MACD 多头支持
不存在 CHOP_BLOCK
Phase != EXPANSION_DOWN
```

空头镜像。

### 8.5 普通整理突破

多头：

```text
当前趋势带为 YELLOW
Range 已在当前 Bar 之前确认且 intact
previous_close <= frozen_upper
current_close > frozen_upper + 0.10 × ATR14
VolumeRatio20 >= 1.20
OR（OI有效且 OIDelta5 > 0）
```

空头镜像。

OI 只表示新参与度，不解释多空持仓主体。几何突破但参与度不足时只进入 Snapshot diagnostic，不产生正式突破 Event。

### 8.6 趋势回调观察

多头：

```text
趋势带仍为 YELLOW
abs(close - EMA21) / ATR14 <= 0.50
没有跌破最近确认低点和冻结 Range 失效边界
Phase != EXPANSION_DOWN
并且以下至少一项：
- LOWER_CONTRACTION
- MACD histogram 由下降转为上升
- 当前 close 重新站回 EMA10
```

输出 `TREND_PULLBACK_LONG_WATCH`。空头镜像。

### 8.7 趋势再增强

仅在已出现同方向 Pullback Watch 后：

```text
close 重新站到 EMA10 正确一侧
MACD histogram 连续增强
或 completed close 突破最近确认同方向极值
```

输出 `TREND_RESTRENGTHENED_*`。

### 8.8 趋势减弱

趋势带尚未反转，但下列三项至少两项连续两根恶化：

```text
abs(spread_atr) 收缩
abs(slope21_atr) 收缩
abs(MACD histogram) 收缩
```

或出现同方向尾部极端后收缩：

```text
多头：UPPER_CONTRACTION
空头：LOWER_CONTRACTION
```

输出 `TREND_*_WEAKENED`，仅提示复核，不等于卖出或平仓。

### 8.9 趋势失效

多头满足任一：

```text
趋势带正式转 BLUE
连续2根 completed D1 收在 EMA21 下方且 MACD 转空
completed close 跌破最近确认低点或冻结 Range 失效边界
```

空头镜像。输出新的 `TREND_INVALIDATED` 事件并关联原趋势事件。

## 9. 杯柄 Setup V1

### 9.1 角色

杯柄模块只输出 Setup：

```text
CUP_HANDLE_FORMING
CUP_HANDLE_READY
CUP_HANDLE_BREAKOUT
CUP_HANDLE_WEAKENED
CUP_HANDLE_INVALIDATED
CUP_HANDLE_EXPIRED
```

`FORMING` 只在 Web 显示；`READY` 进入 Shadow；`BREAKOUT` 才具备未来 Alert eligibility。

杯柄几何存在但趋势上下文不支持时：

```text
CUP_HANDLE_GEOMETRY_FOUND
TREND_CONTEXT_REJECTED
```

不产生 READY/BREAKOUT 事件。

### 9.2 锚点

```text
L = left rim
B = cup bottom
R = right rim
H = handle range
P = breakout pivot
```

严格时间顺序：

```text
tL < tB < tR < tH <= t
```

FORMING 可随前缀演化；进入 READY 后，候选 ID、L/B/R/H/P、confirmed_at 和 score breakdown 冻结。

### 9.3 D1 初始参数

```text
pretrend_lookback_bars       = 20..60
cup_min_bars                 = 25
cup_max_bars                 = 90
handle_min_bars              = 5
handle_max_bars              = 15
cup_depth_min_pct            = 0.10
cup_depth_preferred_max_pct  = 0.35
cup_depth_hard_max_pct       = 0.50
rim_tolerance_pct            = 0.05
rim_tolerance_atr            = 1.00
handle_max_right_leg_ratio   = 1/3
handle_max_depth_pct         = 0.15
handle_must_stay_above_mid   = true
breakout_buffer_atr          = 0.10
ready_expiry_bars            = 20
```

看跌版本使用同一方向归一化函数镜像计算，多空结果分别统计。

### 9.4 前置趋势

看涨：

```text
L.close > EMA21_at_L
EMA21_slope_10_at_L > 0
并且至少一项：
- pretrend_return_pct >= 10%
- pretrend_move_atr >= 4.0
```

看跌镜像。该 Gate 过滤下跌趋势中的普通反弹。

### 9.5 杯体与 U 形纯度

```text
rim_price = (L.price + R.price) / 2
cup_depth_pct = abs(rim_price - B.price) / rim_price
```

硬要求：

```text
10% <= cup_depth_pct <= 50%
cup_depth >= 3.0 × median_ATR_in_cup
abs(L.price - R.price) <= min(5% × rim_price, 1.0 × ATR_at_R)
```

10%—35%得完整深度分，35%—50%扣分，低于10%拒绝。

V 形和宽幅震荡过滤：

- 底部带至少持续3根 D1；单根尖底扣15分；
- 左右腿时长比 0.5—2.0 得满分；
- 多次完整穿越杯体中轴扣分，超过固定 crossing 上限拒绝；
- 二次曲线拟合仅进入质量分，不作为唯一硬判定。

### 9.6 柄部与量能

硬要求：

```text
5 <= handle_bars <= 15
handle_retrace <= 1/3 × right_leg_advance
handle_depth_pct <= 15%
handle_extreme 保持在杯体上半部（看跌镜像）
```

柄部缩量：

```text
median(handle_volume) <= 0.80 × median(right_leg_volume)
median(handle_volume) <= 0.90 × median(previous_20_volume)
```

突破放量：

```text
completed close 突破 P ± 0.10 ATR
breakout_volume >= 1.20 × median(previous_20_volume)
breakout_volume >= 1.50 × median(handle_volume)
```

几何突破但量能不足时仅输出 `BREAKOUT_VOLUME_UNCONFIRMED` diagnostic。

### 9.7 评分

```text
前置趋势              15
杯体深度/杯口/时长      25
U 形纯度               20
柄部质量                20
量能结构                20
总分                   100
```

```text
FORMING  >= 65 且杯体硬条件通过
READY    >= 80 且柄部、缩量及趋势上下文通过
BREAKOUT >= 85 且实体突破、放量、趋势带和 MACD 支持
```

外部“99分过线”只说明对方使用评分机制，不是本项目阈值或效果证明。

## 10. 输出合同

### 10.1 Snapshot

`NewowTrendObservationSnapshot`：

```text
schema_version
strategy_instance_id
product
physical_contract
segment_id
frequency
bar_end
trend_state
trend_band
phase_state
structure_state
primary_observation
reason_codes
blockers
key_levels
cup_handle optional
source_identity
formula_digest
profile_hash
valid
unavailable_reason
```

### 10.2 Event

`NewowObservationEvent`：

```text
event_id
strategy_instance_id
product
physical_contract
segment_id
frequency
observation_type
direction
bar_end
first_seen_at
confirmed_at
related_event_id optional
reason_codes
key_levels
setup_id optional
source_identity
formula_digest
profile_hash
```

Event ID 至少绑定：

```text
strategy_instance_id
product
physical_contract
frequency
observation_type
direction
bar_end
setup_id optional
```

同一前缀重复运行必须幂等。

## 11. Historical、盘后增量与快照

唯一权威入口：

```python
NewowDailyObserver.step(completed_d1_bar)
```

处理顺序：

```text
1. 校验 product / contract / segment / D1 / completed
2. 推进现有 EMA / ATR / MACD / Lux Range
3. 计算共享 Feature / Phase Lite / Structure Lite
4. 推进 Trend State Machine
5. 枚举与推进 Cup Handle Setup
6. 选择一个 primary observation
7. 生成新 first-seen Event 或 linked Event
8. 冻结 Snapshot
```

Historical 对每个 rank1 物理段建立新状态，逐 Bar 调用同一入口。盘后增量也调用同一入口；不建设第二套向量公式。

Snapshot 根：

```text
GUIYI_NEWOW_OBSERVATION_ROOT
```

采用现有安全原子文件模式：可信根目录、无 symlink、0700/0600、immutable payload、写后读回、原子 current manifest。

HTTP 请求路径只读 current manifest 和 snapshot，不 replay、不写 cache、不访问 provider。

## 12. 期货市场边界

- 只使用 `MarketDataService` 的 `actual_dominant` rank1 物理合约段；consumer 不自判主力。
- 杯、柄、Range、趋势状态、pending lifecycle 和结果窗口不跨物理合约。
- 不使用连续合约、复权或下一主力合约补形态。
- 夜盘归属 Canonical `trading_day`；D1 不按自然日期拼接。
- 趋势与突破使用 `close`，不以 settlement 替代收盘价。
- Volume/OI 只在同一物理合约比较；OI 缺失不填0、不前向填充。
- OI 上升只表示参与度增加，不声称多头或空头机构建仓。
- 主力段切换只做行政结束，不产生卖出、平仓或反手语义。
- Historical owner 可知性无法证明的窗口可用于图形研究，但不得进入 prospective 或未来 Alert 证据。

## 13. Web 与 Shadow

### 13.1 Market 首页

增加“牛哇趋势观察”清单，单品种只显示一个 primary observation，优先级：

```text
杯柄放量突破
普通整理突破
杯柄 READY
新趋势启动
趋势再增强
趋势回调观察
趋势减弱
趋势失效
```

每项显示：

```text
品种 / 当前物理主力
方向与状态
主要原因2—4条
关键位置
杯柄分数与扣分项（存在时）
数据完整性
[查看日线图]
```

### 13.2 Market 图表

默认显示：

```text
EMA10 / EMA21 / EMA60
黄 / 蓝 / 中性趋势带
MACD
成交量与OI
最近确认高低点
Lux Range
趋势状态变化
```

存在杯柄时额外显示 L/B/R、柄部、P、失效参考位、量能比和 score breakdown。Tooltip 必须同时显示 `pivot_at` 与 `confirmed_at`。

Web 不复制任何策略公式。

### 13.3 active60 盘后 Shadow

每天盘后只运行一次 completed D1 扫描，输出：

```text
expected
processed
none
trend_started
range_breakout
pullback
restrengthened
weakened
cup_forming
cup_ready
cup_breakout
unavailable by reason
error by reason
latency
```

无观察和系统未运行必须可区分。合并 Shadow 代码不等于授权真实调度。

## 14. 验证矩阵

### 14.1 因果

- completed-only；
- strict-before；
- 无 negative shift、centered rolling、future pivot；
- prefix invariance；
- append/prepend invariance；
- batch/incremental parity；
- READY 后杯柄锚点与评分冻结；
- first-seen Event immutable；
- same-physical-contract isolation；
- 主力换月不拼接形态。

### 14.2 趋势公式

- 黄/蓝/中性边界 fixture；
- flip-count 震荡阻塞；
- MACD 启动和延续分开；
- Range 必须严格先于突破 Bar；
- Pullback、Restrengthened、Weakened、Invalidated 状态转移互斥且确定；
- 多空镜像分别验证。

### 14.3 杯柄

专用 Gold Set 80—120 个 D1 窗口，覆盖：

```text
真看涨/看跌杯柄
V形底
宽幅震荡
下跌反弹
杯深<10%
柄部过长/过深
柄部不缩量
突破不放量
换月附近
OI缺失
```

Gate：

```text
READY precision >= 80%
BREAKOUT precision >= 85%
confirmed identity stability = 100%
cross-contract candidate = 0
```

人工标注不得看到未来收益。

### 14.4 最小结果

对 first-seen 趋势和杯柄突破分别记录：

```text
3 / 5 / 10 / 20 D1 方向变化
MFE
MAE
3 Bar 内是否退回突破位
是否破坏趋势或柄部
```

结果必须标记：

```text
retrospective observation outcome
gross
pre-cost
not OOS
not tradability evidence
```

## 15. 未来牛哇震荡策略的复用边界

未来 `newow_range_v1` 只允许复用：

```text
Profile / Identity
Feature Snapshot
Phase Lite
CausalExtremeLite
Lux Range Adapter
Key Levels / Evidence
Observation Lifecycle
Snapshot / API 基础模式
```

它必须单独实现：

```text
区间方向偏置
边缘观察
偏离收缩确认
区间失效状态机
独立事件和Shadow证据
```

趋势上层、杯柄 Setup、事件身份和结果不得被震荡策略继承。

## 16. 验收结论

V1 成功首先意味着：

```text
active60 日线可靠扫描
少量、可解释的趋势观察
杯柄提供额外质量而不是替代趋势
Web 一次点击完成复核
无观察与系统异常可区分
个人可以长期维护
```

不意味着：

```text
策略已盈利
可以实盘
可以自动下单
可以自动止损
可以立即接PushPlus
```
