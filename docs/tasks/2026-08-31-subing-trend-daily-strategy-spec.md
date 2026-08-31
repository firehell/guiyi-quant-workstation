# 苏冰趋势策略-日 Strategy Spec

状态：`SPEC_REVIEW_PENDING`

日期：2026-08-31

基线：`develop@33d01e94265566ff3e806e5521aec199e04c39f2`

内部稳定 ID：`subing_daily_trend_v1`

正式名称：`苏冰趋势策略-日`

## 1. 文档职责

本文件定义 `subing_daily_trend_v1` 的第一版正式策略合同。

本版本目标不是一次性完成 Web、Alert 或 Runtime，而是先用最小、可解释、可复算的日线趋势公式生成 Historical Projection 和研究效果，回答：

> 只使用“非震荡 + EMA21 方向/斜率 + MACD 零轴附近金死叉”这套最小趋势规则，在 active universe 的真实主力历史上是否具有继续投入开发的研究价值？

本 Spec 对 `docs/tasks/2026-08-31-subing-dual-strategy-range-detector-design.md` 中 `subing_daily_trend_v1` 的入场公式进行收敛并具有更高优先级。此前设计中以下条件不再属于 V1：

- 不要求同一根 D1 突破 Lux Range 上/下沿；
- 不要求当根 D1 穿越 EMA21；
- 不要求 `abs(close - EMA21) / ATR14 <= 1.5`；
- 不要求“Range 突破 + EMA 突破 + MACD 交叉”三者同 Bar；
- 不使用成交量、持仓量、BOLL、加仓、减仓、分段止盈或时间止损。

Range Detector 在本策略中只承担“当前是否处于震荡区间”的 regime gate，不承担方向或突破触发职责。

未经实现、测试、独立 Review 和用户对 Historical 结果的人工接受，本 Spec 不授权 API、Web、Alert Rule、migration、main/tag、Runtime promotion 或真实通知。

## 2. 来源与策略意图

用户提供的交易资料反复出现以下共同原则：

- 均线之上只做多，均线之下只做空；
- 均线斜率用于判断多空；
- MACD 在零轴附近形成金叉/死叉用于寻找入场；
- 价格围绕均线反复运行属于震荡，震荡阶段不做趋势；
- 趋势策略应保持简单，先证明核心公式，再决定是否增加成交量、持仓量等二次过滤。

对应资料包括：

- `交易系统.pdf`
- `交易开平仓口诀.pdf`
- `交易理念.pdf`
- `执行力训练.pdf`
- `盯盘需要关注的点.pdf`

这些资料同时也提到成交量、BOLL、突破后 3 根 K 线确认、前高前低和分段止盈等规则；这些内容本 V1 明确不采用。原因不是否定这些规则，而是本阶段只验证最小核心是否有效，避免把多个假设一次性混在同一公式版本中。

## 3. 产品与身份

### 3.1 产品边界

苏冰仍然是一个产品。

现行策略：

```text
页面名称：震荡策略
内部 ID：subing_strategy_v1
正式身份：actual_dominant + 15m
```

新增策略：

```text
正式名称：苏冰趋势策略-日
页面短名称：趋势策略-日
内部 ID：subing_daily_trend_v1
正式身份：actual_dominant + 1d
```

两套策略不共享 Action、Episode、Historical result、Current state、Performance snapshot 或未来 Alert lineage。

本任务不得修改 `subing_strategy_v1` 的公式、历史、Alert Rule、Scope 或 Runtime。

### 3.2 稳定公式身份

```text
strategy_id: subing_daily_trend_v1
formula_version: subing_daily_trend_v1
policy_id: subing_daily_trend_v1
public_name: 苏冰趋势策略-日
series_kind: actual_dominant
decision_frequency: 1d
research_only: true
formal_decision_bar: completed D1
reference_fill: next existing same-physical-contract D1 open
auto_order: false
```

任何改变以下项目的修改都必须建立新版本，不能继续沿用 V1 identity：

- EMA period / seed / slope window；
- MACD 参数、seed 或 near-zero threshold；
- Range policy 或“震荡”定义；
- 入场真值表；
- 退出规则；
- reference fill 时序；
- 主力段处理语义。

## 4. 数据与因果边界

### 4.1 唯一数据入口

Historical 只通过 `MarketDataService` 读取：

```text
series_kind = actual_dominant
frequency = 1d
```

`actual_dominant` 必须由 `MainContractMap rank=1` 有效区间解析；不得 glob、自判主力、跨频回退或绕过 Canonical/Catalog。

### 4.2 completed D1 only

正式策略只消费 completed D1。

禁止：

- 未完成 D1；
- intraday Live 临时聚合成 D1；
- 盘中预判直接形成正式 Action；
- 使用未来 D1 high/low/close 补写过去信号。

### 4.3 stitched warm-up 与物理段状态

EMA21、MACD、ATR14 和 Range ATR500 可以使用 rank1 stitched raw D1 历史做指标 warm-up。

但：

- position、pending action、Episode 不跨物理主力段；
- 策略可用的 Range regime 必须在当前物理主力段内重新形成；
- Range ATR500 可继承 stitched warm-up，但 Range close-window/active range 在物理段起点重置；
- 当前物理段至少形成一个当前段内 causal Range confirmation 后，Range regime 才可用于入场；
- 主力段第一根 completed D1 永远禁止新开仓。

这样既保留长周期指标 warm-up，又避免旧合约的震荡箱体直接作用于新主力价格。

## 5. 指标政策

### 5.1 EMA21

```text
period = 21
seed = sma_window
source = close
slope_window = latest 5 valid EMA21 points
slope_method = linear regression
normalized_slope = bps_per_bar
```

方向条件：

```text
LONG:
close_t > EMA21_t
and slope_5_bps_per_bar_t > 0

SHORT:
close_t < EMA21_t
and slope_5_bps_per_bar_t < 0
```

`close == EMA21` 不允许新入场。

10-bar slope 不参与 V1。

### 5.2 MACD

固定：

```text
fast = 12
slow = 26
signal = 9
EMA seed = sma_window
histogram_scale = 2
```

金叉：

```text
previous_dif <= previous_dea
and current_dif > current_dea
```

死叉：

```text
previous_dif >= previous_dea
and current_dif < current_dea
```

### 5.3 零轴附近

“零轴附近”固定定义为：

```text
max(abs(DIF_t), abs(DEA_t)) / ATR14_t <= 0.25
```

ATR14：

```text
period = 14
smoothing = wilder_sma_seed
```

ATR14 必须 ready、finite 且 `> 0`，否则当根策略事实 unavailable。

### 5.4 Lux Range 震荡 Gate

使用现有：

```text
range_detector_lux_v1
minimum_range_length = 20
range_width_atr_multiplier = 1.0
range_atr_length = 500
source = close
atr_smoothing_policy = wilder_sma_seed
```

Range 只负责 regime，不负责方向。

对决策 Bar `t`，在完成本 Bar 的 Range causal step 后定义：

```text
CHOP:
当前段存在 active Range snapshot
and state == intact

TREND_ELIGIBLE:
当前段存在 active Range snapshot
and state in {broken_up, broken_down}

RANGE_UNAVAILABLE:
当前段尚无 causal Range confirmation
or Range warm-up / source identity 不完整
```

含义：

- `CHOP`：禁止新开仓；
- `TREND_ELIGIBLE`：允许继续检查 EMA/MACD；
- `RANGE_UNAVAILABLE`：不把“没有箱体”猜成“趋势”，fail-closed 禁止新开仓。

Range 的 `broken_up` / `broken_down` 方向不约束最终多空方向。最终方向只由 EMA21 位置/斜率和 MACD 金死叉决定。

`visual_start_at` 永远只是图表回画起点；策略只认 Range causal state，不读取视觉回画作为过去事实。

## 6. V1 最小入场真值表

### 6.1 多头

在 completed D1 `t` 收盘后，当前状态为 flat 且无 pending action 时，以下条件全部成立才产生：

```text
ENTRY_LONG_CONFIRMED
```

条件：

1. 当前物理主力段不是第一根 D1；
2. Range regime == `TREND_ELIGIBLE`；
3. `close_t > EMA21_t`；
4. `slope_5_bps_per_bar_t > 0`；
5. 当前 D1 形成 MACD golden cross；
6. MACD 满足 near-zero：`max(abs(DIF_t), abs(DEA_t)) / ATR14_t <= 0.25`；
7. EMA、MACD、ATR14、Range 全部 ready 且 source identity 一致；
8. 当前 Bar 不是权威物理段终点。

### 6.2 空头

完全对称：

1. 当前物理主力段不是第一根 D1；
2. Range regime == `TREND_ELIGIBLE`；
3. `close_t < EMA21_t`；
4. `slope_5_bps_per_bar_t < 0`；
5. 当前 D1 形成 MACD dead cross；
6. near-zero <= `0.25 × ATR14`；
7. 所有输入 ready 且 identity 一致；
8. 当前 Bar 不是权威物理段终点。

### 6.3 V1 明确不要求

入场不要求：

- 当日刚刚突破 Range 上/下沿；
- Range break 与 MACD cross 同 Bar；
- 当日刚刚穿越 EMA21；
- previous close 在 EMA21 另一侧；
- 突破后等待 3 根 K 线；
- 价格距离 EMA21 不超过 1.5 ATR；
- 成交量放大；
- 持仓量增加；
- BOLL 中轨；
- 前高/前低突破；
- 二次确认；
- 多周期共振。

这意味着 V1 的唯一入场触发事件是：

```text
MACD 零轴附近金叉 / 死叉
```

而 Range 与 EMA21 只承担前置过滤：

```text
不是震荡
+ 方向正确
```

## 7. Action 生效时序

### 7.1 decision 与 reference fill

completed D1 `t` 只形成确认事实：

```text
ENTRY_LONG_CONFIRMED
ENTRY_SHORT_CONFIRMED
```

参考生效：

```text
next existing same-physical-contract D1 open
```

不得使用信号日 close 冒充入场参考价。

记录：

```text
signal_bar_end
signal_trading_day
signal_close
effective_bar_end
effective_open_at
reference_price
gap_abs
gap_atr14
```

### 7.2 跳空

下一 D1 大幅跳空不取消入场。

原因：V1 已经删除额外的追价/距离过滤，第一阶段应真实观察这种最小规则在 gap 下的表现，而不是再加入一个新的阈值。

gap 只进入分析，不改变 Action 是否生效。

### 7.3 无下一同合约 Bar

如果没有下一根同物理合约 D1：

```text
pending entry -> canceled
cancel_reason = NO_SAME_CONTRACT_EFFECTIVE_BAR
```

不创建 Episode。

## 8. 持仓与退出

### 8.1 状态

第一版只允许：

```text
FLAT
PENDING_LONG_ENTRY
PENDING_SHORT_ENTRY
LONG
SHORT
PENDING_LONG_EXIT
PENDING_SHORT_EXIT
```

不加仓、不减仓、不 pyramiding、不自动反手。

### 8.2 唯一普通退出

普通退出只认 EMA21 反向穿越。

LONG：

```text
previous_close >= previous_ema21
and current_close < current_ema21
```

SHORT：

```text
previous_close <= previous_ema21
and current_close > current_ema21
```

形成：

```text
EMA21_OPPOSITE_CROSS
```

参考退出价同样是下一根同物理合约 D1 open。

### 8.3 明确不退出的情况

以下情况不能单独触发普通退出：

- 反向 MACD 金叉/死叉；
- Range 重新进入 intact；
- 价格回到旧 Range；
- EMA slope 变平或暂时反向；
- 前一根 K 线高低点；
- Pivot；
- 成交量/持仓量；
- 固定持有天数；
- 盈利比例或亏损比例。

如果持仓期间出现反向完整入场条件，也不直接反手。持仓状态优先只检查 EMA21 exit；退出完成后，等待未来新的 MACD 交叉和完整入场条件。

### 8.4 物理段终止

如果在权威物理主力段最后一根 completed D1 收盘后仍持有：

```text
CONTRACT_SEGMENT_END
```

以旧物理段最后一根 D1 close 作为行政终止 reference price。

它不是普通市场退出信号，不跨段、不迁移到新主力。

如果同一终点 Bar 同时满足 EMA21 opposite cross：

```text
CONTRACT_SEGMENT_END 优先
```

因为普通退出不存在下一同合约 D1 open 可生效。

## 9. 每 Bar 处理优先级

每根 completed D1 固定按以下顺序：

1. 在 Bar open 应用上一决策 Bar 已确认且同物理合约的 pending entry/exit；
2. 计算/推进 EMA21、slope、MACD、ATR14 和 Range；
3. 校验 source identity、segment 和 ready；
4. 如果当前 Bar 是权威物理段终点：终止 position、取消 pending entry、禁止新 entry；
5. 如果当前已持仓：只检查 EMA21 exit；
6. 如果 flat：先检查 Range regime；
7. Range == `TREND_ELIGIBLE` 时检查 EMA direction；
8. 最后检查 MACD near-zero cross；
9. 同一 decision Bar 最多生成一个普通 Action。

## 10. 策略状态与研究解释

为了后续 Current/Web 兼容，V1 内部研究状态建议固定为：

```text
DATA_INSUFFICIENT
CHOP
WAIT_LONG_OR_SHORT_SIGNAL
PENDING_LONG_ENTRY
PENDING_SHORT_ENTRY
LONG
SHORT
PENDING_LONG_EXIT
PENDING_SHORT_EXIT
```

未来页面可以简化映射为：

```text
数据不足
震荡中
等待信号
已确认
持有中
```

本阶段不实现页面，但 Historical 报告必须能解释每次入场为什么成立：

```text
Range regime
close vs EMA21
EMA21 slope_5
MACD cross
MACD zero distance / ATR14
segment identity
```

## 11. Action / Episode 合同

### 11.1 Action

每个 Action 至少包含：

```text
action_id
strategy_id
formula_version
policy_id
symbol
actual_contract
segment_start_trading_day
action_type
action_status
signal_bar_end
signal_trading_day
signal_close
effective_open_at
effective_bar_end
reference_price
range_id
range_revision
range_confirmed_at
range_state
ema21
ema21_slope_5_bps_per_bar
macd_dif
macd_dea
macd_cross
atr14
macd_zero_distance_atr
gap_abs
gap_atr14
reason_codes
cancel_reason
source_identity_digest
```

ID 必须确定性生成，不使用随机 UUID。

### 11.2 Episode

Episode 是一次有效 entry 到有效 exit：

- 一个 Episode 只有一个 entry；
- 不加减仓；
- 不反手；
- 不跨物理段；
- open Episode 可以展示，但不进入完成 Episode 统计；
- closed Episode 保存 entry/exit Action、reference change、holding D1 bars、entry gap 和 exit reason。

所有价格、reference change、gap ratio 使用 `Decimal`。

## 12. Historical Projection

### 12.1 核心原则

Historical 与未来 Current/Runtime 必须复用同一个日线增量状态机，不允许 Historical 用另一套批量捷径产生不同语义。

Historical 按 rank1 物理段确定性重放：

```text
stitched raw indicator warm-up
→ physical segment reset for strategy state and Range close-window
→ completed D1 step
→ pending next-open application
→ Action
→ Episode
→ segment terminal
```

### 12.2 first valid lower bound

入场资格只有在以下全部 ready 后成立：

- stitched EMA21 + 5-bar slope；
- stitched MACD 12/26/9；
- stitched ATR14；
- Range ATR500；
- 当前物理段 Range close-window 已完成并形成当前段 causal confirmation。

任何一项 unavailable 时不得缩短 lookback、使用 0 或静默替代。

### 12.3 必须证明的因果测试

至少：

- completed D1 only；
- strict-before effective fill；
- batch / incremental parity；
- prefix invariance；
- future-tail invariance；
- prepend invariance（完整 warm-up 后稳定前缀不漂移）；
- Range visual_start_at 不参与策略过去事实；
- current-segment Range gate 不继承旧物理段 active range；
- no cross-contract fill；
- segment terminal；
- no same-Bar reversal；
- exact EMA boundary no entry；
- exact near-zero threshold boundary；
- invalid identity / missing data fail-closed。

## 13. 第一阶段效果研究

本 Spec 的第一轮实现到 Historical report 为止，不先开发 API/Web/Alert。

### 13.1 顺序

先做四个代表品种：

```text
JM
AG
RB
EG
```

人工抽查逐笔 Action/Episode 和图形后，再扩展到 active60。

### 13.2 Historical 窗口

每个品种使用：

```text
从满足全部 warm-up / identity 条件的最早可用 Canonical 日期
到最新已完成 Canonical D1
```

不人为统一成 2020/2024，也不补齐不存在的数据。

### 13.3 Retrospective split

公式冻结后，每个品种按 entry trading day 做 chronological：

```text
80% development
20% retrospective holdout
```

holdout 可以读取分割点之前的指标 warm-up，但只有 entry trading day 位于 holdout 的 Episode 才计入 holdout。

不得依据 holdout 结果反调 V1 参数。需要改公式时建立新 candidate/version。

### 13.4 最小效果指标

只输出研究参考口径：

```text
完整 Episode 数
open Episode 数
long / short 数量
正向 Episode 比例
平均 reference change
中位 reference change
25% / 75% 分位
最大正向 reference change
最大反向 reference change
平均 / 中位 holding D1 bars
EMA21_OPPOSITE_CROSS 次数
CONTRACT_SEGMENT_END 次数
entry gap_abs / gap_atr14 分布
按年份 / 品种 / 方向分组
development / holdout 分组
```

不输出：

- 本金；
- 仓位；
- 杠杆；
- 手续费；
- 滑点模拟；
- 资金曲线；
- 年化收益；
- 最大回撤；
- Sharpe；
- 自动“可交易/不可交易”结论。

单品种完整 Episode `< 30`：

```text
INSUFFICIENT_SAMPLE
```

仍展示明细，不把样本不足藏在 active60 聚合里。

## 14. Historical Gate

第一阶段完成不等于策略正式启用。

只有同时满足以下条件，才允许讨论下一阶段 Current/API/Web：

1. `subing_daily_trend_v1` 公式和 policy 已冻结；
2. causality / strict-before / future-tail / prefix / batch-incremental tests 全通过；
3. JM/AG/RB/EG 逐笔案例 Review 完成；
4. active60 Historical 报告完成；
5. 80/20 holdout 独立展示；
6. 样本不足明确标记；
7. 用户人工审阅效果后明确决定“继续”。

历史结果不好不等于工程失败。

如果结果需要修改公式：

```text
保留 V1 研究结论
→ 建新 candidate/version
→ 不在同一 V1 identity 下调参后覆盖历史
```

## 15. 后续阶段边界

### 阶段 A：本 Spec 首次实现

只做：

```text
policy
contracts
incremental state machine
Historical Projection
Action / Episode
JM/AG/RB/EG report
active60 report
80/20 retrospective holdout
```

### 阶段 B：Historical 被用户接受后

才设计/实现：

```text
Current State
immutable performance snapshot/current manifest
read-only API
Market Web “趋势策略-日”页面
Historical markers
效果面板
```

### 阶段 C：用户再次批准后

才允许单独设计 Alert：

```text
Rule / migration
completed-D1 evaluator
Event
scope_products
one-shot PushPlus
```

Alert 设计仍必须单独 Lane 3 Review；Historical 接受不能自动授权 migration、production Scope、真实通知、release 或 Runtime promotion。

## 16. 非目标与禁止范围

本 Spec 明确禁止：

- 修改 `subing_strategy_v1`；
- 把两个策略合并成一个 strategy_id；
- 把 Lux Range 方向当作多空方向；
- 以“没有 Range”自动判为趋势；
- 未完成 D1 产生正式信号；
- 同 Bar 使用未来 open；
- 物理主力段跨仓；
- 自动反手；
- 成交量/持仓量/BOLL 条件；
- 3-Bar breakthrough confirmation；
- 加仓/减仓/仓位管理；
- 自动交易或订单；
- UniversalStrategyAdapter；
- generic strategy platform / worker / queue；
- 为了提高历史结果在 V1 内反复试阈值；
- Historical 结果自动晋升 Alert；
- 修改 production DB、Scope、main/tag 或 Runtime。

## 17. 验收标准

第一阶段实现必须同时满足：

### 公式

- 名称和 identity 与本 Spec 一致；
- Range 只做震荡 gate；
- EMA21 position + slope 只做方向 filter；
- MACD near-zero cross 是唯一 entry trigger；
- EMA21 opposite cross 是唯一普通 exit；
- 所有阈值固定、版本化、无运行时自由参数。

### 因果

- completed D1 only；
- next same-contract D1 open；
- current-segment Range confirmation；
- no future leak；
- no prefix drift；
- no cross-contract state/fill；
- no same-Bar reversal。

### 研究

- JM/AG/RB/EG 逐笔可解释；
- active60 可复算；
- development / holdout 分离；
- open Episode 不进入完成统计；
- `INSUFFICIENT_SAMPLE` 不被聚合掩盖。

### 工程边界

- 不改 production Rule/Scope/Runtime；
- 不改现行 SuBing 15m；
- 不建立账户/订单/资金曲线；
- 不修改 `STATUS.md` 宣称未发生的 release 或 Runtime 事实。

## 18. 当前结论

`苏冰趋势策略-日 / subing_daily_trend_v1` V1 被定义为一套极简日线趋势研究策略：

```text
非震荡
+ EMA21 上/下方
+ EMA21 5-bar 斜率同方向
+ MACD 零轴附近金/死叉
= 日线趋势入场确认
```

退出：

```text
反向穿越 EMA21
```

本版本的价值判断必须来自 Historical/OOS evidence，而不是继续在设计阶段增加过滤器。
