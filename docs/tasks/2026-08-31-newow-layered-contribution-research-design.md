# 苏冰双策略的 Newow 分层复原与贡献验证设计

状态：`DESIGN_REVIEW_PENDING`

日期：2026-08-31

任务：Issue #259

基线设计：`docs/tasks/2026-08-31-subing-dual-strategy-range-detector-design.md`

> 本任务为 Lane 3 / Plan-only。它只定义 research-only 消融候选、因果时序和 OOS 贡献口径，不代表牛哇财经的私有原始公式，不声明策略盈利，不授权修改现有 Alert、Runtime、main、tag、数据库、Canonical 或真实订单。

## 1. 当前判断

仓库已经固定了苏冰双策略的产品方向：

- 页面“震荡策略”继续使用现行 `subing_strategy_v1`，不改名、不改生产 lineage；
- 页面“趋势策略”使用独立日线候选 `subing_daily_trend_v1`；
- 日线趋势 V1 使用因果 Lux Range、EMA21、EMA21 5-bar 斜率、MACD 零轴附近交叉和 ATR14 距离约束；
- 不建立第三个 Newow 产品、UniversalStrategyAdapter、通用回测平台、账户或订单域。

因此，本任务不能按此前讨论另建一套 `newow_*` 正式策略。正确做法是把外部手册中的概念转化为**现有苏冰双策略的分层研究假设**：

```text
趋势：基础条件 → 增加 Lux Range 突破 → 增加跟踪退出 → 增加阶段过滤
震荡：现行 subing_strategy_v1 → 增加偏离过滤 → 增加偏度/峰度过滤
```

其中：

- 趋势 T1 必须与基线设计中的 `subing_daily_trend_v1` 完全一致，不允许出现两个相同名称、不同语义的实现；
- 震荡 R0 必须直接复用现行 `subing_strategy_v1` 的 Action/Episode，不重写其状态机；
- T0/T2/T3、R1/R2 都是 research-only 候选；任何公式改变必须使用新版本，不能原地修改现有策略。

## 2. 来源支持与推断边界

《牛哇财经操盘手册2026》明确支持：

- 蓝变黄买入、黄变黄持有、黄变蓝卖出、蓝变蓝观望；
- 趋势运行、整理突破、假突破退出；
- 吸筹、洗盘、拉高、出货的阶段化表达；
- 基于波动率，使用偏度和峰度量化涨跌风险；
- 偏离、反弹、调整信号及信号衰减后的反转解释；
- 杯柄、矩形、三角形、旗形等突破 Setup。

手册没有公开完整公式、窗口、阈值、参数选择过程、成交时序和全样本结果。因此：

- 本文所有数值阈值都是归一量化的预注册研究假设；
- 只能称为“受 Newow 手册启发的候选”，不得称为“复刻原公式”；
- 网页精选案例、年化收益匹配或单标的历史绑定不能作为正式盈利证据；
- 任何 retrospective 结果不能回填 prospective OOS，也不能自动晋升。

## 3. 候选图与唯一身份

### 3.1 趋势族

```text
T0  subing_daily_trend_t0_no_range_candidate_v1
 ↓  仅增加 Lux Range 突破
T1  subing_daily_trend_v1
 ↓  仅增加 ATR 单向跟踪退出
T2  subing_daily_trend_t2_trailing_candidate_v1
 ↓  仅增加量价/OI 阶段过滤
T3  subing_daily_trend_t3_stage_filter_candidate_v1
```

约束：

- T1 是基线设计已经固定的正式 candidate identity；
- T0 是 T1 的无 Range 消融版本；
- T2 与 T1 的入场完全相同，只改变退出；
- T3 与 T2 的入场时序相同，只增加同一信号 Bar 可知的过滤；
- T0/T2/T3 不得被 Alert、Current 或 Runtime 当作正式策略读取。

### 3.2 震荡族

```text
R0  subing_strategy_v1
 ↓  仅增加偏离与收缩过滤
R1  subing_range_r1_deviation_filter_candidate_v1
 ↓  仅增加偏度/峰度尾部风险过滤
R2  subing_range_r2_moments_filter_candidate_v1
```

约束：

- R0 是现行正式策略和唯一生产 baseline；
- R1/R2 只筛选 R0 已形成的 Action，不重新定义苏冰机会、方向、确认或退出；
- R1/R2 的 child event 必须引用 parent `subing_strategy_v1` Action identity；
- child 保留事件时，`confirmed_at`、`effective_at`、reference price、exit 和 Episode 必须与 R0 相同；
- 本任务不新建独立高抛低吸状态机。若未来要做纯区间均值回归，必须另开 Lane 3 设计任务。

## 4. 数据、主力段与共同时间合同

### 4.1 趋势族

- 身份：`actual_dominant + completed D1`；
- 只通过 `MarketDataService` 读取；
- Range、EMA21、MACD、ATR 可以按基线设计使用 rank1 stitched raw D1 warm-up；
- Action、pending fill、trail、持有状态和 Episode 不得跨物理主力段；
- 新物理段第一根 completed D1 禁止入场；
- 任一 identity、coverage、时间单调、物理可读性或 warm-up 异常均 fail-closed。

### 4.2 震荡族

- R0 继续使用现行 `subing_strategy_v1` 的 `actual_dominant + 15m` 正式身份和既有 1m/5m 内部输入；
- R1/R2 只读取 R0 已确认 Action 以及同一物理段、同一完成边界可见的 15m EMA21/ATR/收益窗口；
- 不跨 rank1 物理段寻找极端偏离、偏度或峰度；
- 不因 R1/R2 过滤结果改变 R0 的历史 Action、Episode、Alert Event 或效果快照。

### 4.3 时间字段

所有研究层统一记录：

```text
observed_at   = 当前完成 Bar 的 bar_end
confirmed_at  = 条件最早全部可知的完成 Bar
recognized_at = 研究层接受/拒绝 parent event 的时间，通常等于 confirmed_at
effective_at  = 下一根同物理合约正式 Bar 的 open；对 R1/R2 复用 R0 effective_at
closed_at     = 退出条件首次在完成 Bar 确认的 bar_end
close_effective_at = 下一根同物理合约 Bar open
```

禁止：

- 用信号 Bar 的突破价、最高价、最低价或收盘价冒充下一 Bar 成交；
- 把后续确认的 Range、Pivot、尾部风险或反转回画到过去；
- 使用 centered rolling、负 shift、backfill、未来高低点、未来 D1 或未来目标价；
- 缺少下一同物理合约 Bar 时跨段补成交；
- 将研究 child event 补写成历史正式 Event 或通知。

## 5. 趋势四层公式

## 5.1 T0：趋势基础版

T0 复制 `subing_daily_trend_v1` 的非 Range 条件，唯一删除的是 Range existence 与 Range breakout。

在 completed D1 `t` 上，多头条件全部成立：

```text
previous_close <= previous_ema21
current_close  > current_ema21
ema21_slope_5_bps_per_bar > 0
MACD 在当前 Bar 形成 golden cross
max(abs(DIF), abs(DEA)) / ATR14 <= 0.25
abs(close - EMA21) / ATR14 <= 1.5
当前不是新物理段第一根 D1
状态 flat，且无 pending entry/exit
全部输入 ready、同一 source identity、同一 completed D1 边界
```

空头完全对称。

- 信号在 `t` 收盘后确认；
- reference fill 为下一根同物理合约 D1 open；
- 退出与 T1 一致，只认 completed D1 的 `EMA21_OPPOSITE_CROSS`；
- 反向信号只先退出，不同 Bar 反手。

T0 的用途是测量“EMA21 + slope + near-zero MACD”本身的基线，不作为产品策略。

## 5.2 T1：增加突破

T1 **就是**基线设计的 `subing_daily_trend_v1`，不得另写近似版本。

相对 T0 只新增：

```text
截至 t-1 存在 intact、已确认的 Lux Range
range.confirmed_at < bar_end[t]
多头：previous_close <= frozen_upper 且 current_close > frozen_upper
空头：previous_close >= frozen_lower 且 current_close < frozen_lower
```

同时仍要求 T0 的 EMA21 cross、5-bar slope、MACD cross、near-zero、not-far 等条件在同一 completed D1 `t` 上全部成立。

关键合同：

- `t` 自身新形成或 revision 的 Range 不能被 `t` 使用；
- Range 的 `visual_start_at` 仅用于回画，不是策略可见时间；
- 一个 `range_id + revision` 最多生成一次机会；
- 突破 Bar 条件不完整时不得在后续 Bar 追认；
- T1 的 Action、Episode、fill、退出必须与基线设计 golden parity。

T1-T0 只回答：**同 Bar 的因果箱体突破是否提高基线事件质量。**

## 5.3 T2：增加跟踪

T2 的 entry Action、signal Bar、effective open 与 T1 完全相同。只增加 ATR14 Chandelier 式退出：

```text
long_candidate_t  = highest_high_since_effective_entry_t - 3.0 * ATR14_t
short_candidate_t = lowest_low_since_effective_entry_t  + 3.0 * ATR14_t

long_trail_t  = max(long_trail_(t-1),  long_candidate_t)
short_trail_t = min(short_trail_(t-1), short_candidate_t)
```

处理顺序：

1. 在 Bar open 应用前一 Bar 已确认的 pending Action；
2. 对当前 completed D1，先用 `trail_(t-1)` 判断是否退出；
3. 再用当前 high/low/ATR 更新 `trail_t`；
4. 第一根 effective-entry D1 没有 prior trail，不得以同一 Bar 新生成的 trail 退出；
5. trail 只能向盈利方向移动；
6. `EMA21_OPPOSITE_CROSS` 与 trail breach 任一成立均退出；同 Bar 时记录稳定 reason precedence；
7. 退出仍在下一根同物理合约 D1 open 生效。

T2-T1 使用同一 entry opportunity 做 paired Episode 比较，只回答：**增加跟踪退出是否改善持有质量。**

## 5.4 T3：增加阶段过滤

手册的“吸筹/洗盘/拉高/出货”没有公开可复算公式，因此不得输出真实主力结论。研究字段只允许：

```text
EXPANSION_CONFIRMED
LOW_PARTICIPATION
EXHAUSTION_RISK
STAGE_UNAVAILABLE
```

在 T1 entry signal Bar `t` 上，只使用完成数据计算：

```text
ER20 = abs(close_t - close_(t-20))
       / sum(abs(close_i - close_(i-1)), i=t-19..t)

VolumeRatio20 = volume_t / median(volume_(t-20)..volume_(t-1))
OIDelta5      = open_interest_t - open_interest_(t-5)
```

T3 允许 T2 entry 的固定 Gate：

```text
ER20 >= 0.35
VolumeRatio20 >= 1.20
OIDelta5 > 0
```

- previous-volume median 为零、OI 缺失、ATR/窗口不完整或任一值非有限时 `STAGE_UNAVAILABLE`，fail-closed；
- 多头和空头都要求突破时 OI 增加，因为这里测量的是新资金参与，而不是推测多空持仓归属；
- `EXHAUSTION_RISK` 只作为诊断，不生成反向 Action；
- T3 不改变 T2 exit；
- T3 child event 保留 T2 的 signal/effective identity。

T3-T2 只回答：**量能、持仓量与方向效率过滤能否区分较好的突破。**

## 6. 震荡三层公式

## 6.1 R0：震荡基础版

R0 直接使用现行 `subing_strategy_v1`：

- 不改公式、阈值、Daily Context、15m 决策、1m/5m 内部输入、Lifecycle、Action、Episode、Alert 或 Runtime；
- 不复制一份“近似 R0”；
- 研究 harness 只消费现有 Historical Projection 的完整 Action/Episode；
- 只把完整 Episode 纳入 reference-change 统计，open Episode 不计入完成效果。

R0 是唯一正式 baseline，不因后续 child 结果被改写。

## 6.2 R1：增加偏离

对每个 R0 entry Action，在其 `confirmed_at=t` 之前同物理段最近 8 根 completed 15m 上计算：

```text
DeviationATR_i = (close_i - EMA21_i) / ATR14_i
```

多头 child 保留条件：

```text
min(DeviationATR_(t-8)..DeviationATR_(t-1)) <= -1.0
DeviationATR_t > DeviationATR_(t-1)
DeviationATR_t - prior_min >= 0.25
```

空头对称：

```text
max(DeviationATR_(t-8)..DeviationATR_(t-1)) >= +1.0
DeviationATR_t < DeviationATR_(t-1)
prior_max - DeviationATR_t >= 0.25
```

约束：

- R1 只在 R0 已经确认时接受或拒绝，不延后等待新的 Bar；
- R1 不生成新的方向、确认时间或退出规则；
- parent window 不完整、ATR<=0、跨物理段或值非有限时 child unavailable；
- 过滤未通过不影响 R0 正式事实。

R1-R0 只回答：**先出现逆向极端偏离、随后收缩，是否能区分较好的苏冰 15m 机会。**

## 6.3 R2：增加偏度/峰度

使用同物理段、截至当前 completed 15m 的最近 60 个对数收益：

```text
r_i = ln(close_i / close_(i-1))
Skew60_t = 明确定义的有限样本无偏偏度
ExcessKurtosis60_t = 明确定义的有限样本无偏超额峰度
```

不得依赖 pandas/scipy 不同版本的默认 bias 或 Fisher 设置；公式、最小样本数和 Decimal/float 边界必须在 contract 中固定并以 golden fixtures 验证。

在 R1 通过的同一 `t` 上：

多头 child 保留条件：

```text
Skew60_(t-1) <= -0.50
ExcessKurtosis60_(t-1) >= 1.00
abs(Skew60_t) < abs(Skew60_(t-1))
```

空头对称：

```text
Skew60_(t-1) >= +0.50
ExcessKurtosis60_(t-1) >= 1.00
abs(Skew60_t) < abs(Skew60_(t-1))
```

约束：

- 尾部风险必须在前一完成 Bar 已存在，当前 Bar 只确认其收缩；
- 信号不回画到偏度极端 Bar；
- R2 不改变 R1/R0 的 signal、fill 或 exit；
- 少于 60 个同段收益、零/负价格、值非有限或窗口异常时 unavailable。

R2-R1 只回答：**偏度/峰度尾部风险及其收缩，是否为偏离过滤增加可重复贡献。**

## 7. 无未来函数、前缀不变性与一致性 Gate

每一层必须单独通过：

1. **completed-only**：只消费当前及过去已完成 Bar；
2. **strict-before**：上级周期、Range 与 parent 状态必须严格早于或按基线合同可见；
3. **no future dependency**：无 centered rolling、负 shift、未来 Pivot、未来目标价或回填；
4. **prefix invariance**：对每个 fixture 和自然窗口逐 Bar 截断，prefix 输出必须等于 full-run 的对应前缀；
5. **batch/incremental golden parity**：批量 Historical 与逐 Bar 状态机逐字段相同；
6. **prepend invariance**：补入更早历史只允许填充原先 warm-up unavailable 区，不得漂移已完整 warm-up 的输出；
7. **physical-segment isolation**：Action、trail、偏离窗口、moments、effective fill 和 Episode 不跨 rank1 物理段；
8. **parent-child identity**：T1/T3/R1/R2 child 必须引用稳定 parent opportunity/action；T2 entry 必须与 T1 完全一致；
9. **outcome isolation**：future horizon 不完整时 unavailable，不缩短、不跨段补齐；
10. **anti-backpaint**：追加未来 Bar 不得改变旧事件的 `confirmed_at/effective_at/reason/identity`。

任一 Gate 失败：

```text
CONTRACT_FAILED
```

该层不得生成贡献结论，也不得继续下一个依赖层。

## 8. 冻结的 OOS 与分层贡献协议

### 8.1 双重验证关系

本研究协议是对基线设计 chronological 80/20 holdout 的补充，不替代它：

- `subing_daily_trend_v1` 仍必须满足原设计的 80/20 retrospective holdout；
- 分层贡献另外采用 rolling 12m reference + 3m test + 3m step；
- prospective OOS 在候选 manifest、公式、参数、cohort 和 protocol 全部冻结后的下一 Canonical 交易日开始；
- retrospective 和 rolling 结果不得回填 prospective OOS；
- 修改任一公式或阈值必须新 candidate/version，旧 OOS 不迁移。

### 8.2 固定 cohort

冻结时保存：

```text
active_products snapshot
product order
source identity
freeze commit
formula digests
protocol digest
```

- 主报告覆盖冻结 cohort 的全部产品；
- JM/AG/RB/EG 只作详细案例和边界审阅，不作为参数调优专用样本；
- cohort 后续变化不改写旧报告。

### 8.3 窗口与 horizon

```text
retrospective since: 2023-01-01
retrospective through: freeze 前最后一个完整 Canonical 交易日
rolling reference: 12 months
rolling test: 3 months
rolling step: 3 months
prospective OOS: freeze 后第一个 Canonical 交易日
```

- 趋势 fixed horizons：3 / 5 / 10 / 20 个 D1 Bar；
- 震荡 fixed horizons：3 / 5 / 8 个 15m Bar；
- Episode 只在 entry 和 exit 均完整、同物理段时进入完成统计；
- fold 只统计 entry trading day 位于 test 的事件，reference 开仓但跨入 test 的 Episode 不计入 test。

### 8.4 固定比较

```text
T1 - T0：Lux Range 突破过滤贡献
T2 - T1：跟踪退出的 paired Episode 贡献
T3 - T2：阶段过滤贡献
R1 - R0：偏离收缩过滤贡献
R2 - R1：偏度/峰度过滤贡献
```

不得跨层跳跃选择最优版本，不做 `T3-T0` 后直接宣布组合有效。

### 8.5 贡献口径

共同输出：

- parent/child event 数；
- complete Episode 数；
- coverage retention；
- directional return、MFE、MAE 中位数；
- 完整 Episode reference change 中位数；
- 有样本 fold 数、正向 fold 数；
- product concentration；
- unavailable/fail-closed 原因分布；
- prospective OOS maturity。

过滤层 T1/T3/R1/R2 额外报告：

- retained parent events 与 rejected parent events 的结果分布；
- child 对 parent 的保留率；
- 不得只展示 child，不展示被过滤样本。

T2 额外报告：

- 同一 entry opportunity 的 paired exit time；
- paired reference-change delta；
- paired MAE/MFE、持有 Bar 数和退出 reason；
- EMA21-only 与 EMA21-or-trail 的差异。

### 8.6 研究判定，不是晋升

主指标为完整 Episode reference change；MAE、MFE、coverage 和集中度是保护指标。

只有以下条件全部满足，才可标记：

```text
LAYER_CONTRIBUTION_SUPPORTED
```

- 全部 causality/prefix/golden/segment Gate 通过；
- aggregate 主指标相对直接 parent 不为负；
- 至少 60% 的有样本 rolling test folds 主指标改善；
- coverage retention 不低于 25%；
- aggregate MAE 绝对值不比 parent 恶化超过 10%；
- 任一单品种不贡献超过全部正向 reference change 的 20%。

否则只能是：

```text
LAYER_CONTRIBUTION_NOT_SUPPORTED
INSUFFICIENT_SAMPLE
OOS_PENDING
CONTRACT_FAILED
```

这些状态只决定是否继续研究，不自动修改正式策略，不授权 Alert、release 或 Runtime promotion。

## 9. 实现顺序与任务边界

所有任务独立 session、task branch/worktree 和 PR，从当时最新 `develop` 创建：

1. **Contracts/Protocol**：冻结候选 DAG、parent-child identity、cohort、rolling/prospective protocol、report schema；
2. **Lux Range Kernel prerequisite**：按基线设计独立实现并通过 causality/golden Web mirror；
3. **Trend T0/T1**：实现 T0 消融，并证明 T1 与 `subing_daily_trend_v1` 权威实现一致；
4. **Trend T2**：只增加 trailing exit；
5. **Trend T3**：只增加 stage filter；
6. **Range R1**：只在 R0 Historical Action 上增加 deviation filter；
7. **Range R2**：只在 R1 上增加 moments filter；
8. **Layer Contribution Report**：运行冻结 retrospective/rolling 报告；
9. **Independent Review**：审计公式、时序、样本边界、结果表述与未完成 prospective OOS。

依赖顺序：

```text
Contracts
  ├─ Lux Range → T0/T1 → T2 → T3
  └─ R0(existing) → R1 → R2
两条支线完成后 → Contribution Report → Independent Review
```

Lane 3 每个 PR 都必须人工批准；不得自动 task → develop。实现进入 `develop` 也不等于正式策略接受、release、main/tag 或 Runtime。

## 10. 允许复用与禁止范围

允许复用：

- `MarketDataService`、Canonical domain、MainContractMap；
- 现有 EMA/MACD/ATR 指标核；
- 基线 Lux Range Kernel；
- 现有 `subing_strategy_v1` Historical Projection、Action、Episode；
- common rolling-window schedule 与 price outcome primitives；
- 现有 prefix-invariance、golden parity fixture 模式。

禁止：

- 修改 `subing_strategy_v1` 公式、Rule、Scope、Event、Runtime 或自然 evidence；
- 建立第二套 T1 或 R0 真相；
- 创建 `newow_*` 正式产品、Overlay、Alert Rule 或 Runtime；
- 创建 UniversalStrategyAdapter、统一 Opportunity 模型、正式 backtest worker/queue、账户、资金曲线或订单；
- 修改现有 SuBing candidate/protocol JSON 的同 ID 语义；
- 写入 RQData、Canonical、production PostgreSQL/Redis；
- 发送真实通知；
- 发布 main、创建 tag 或同步 Runtime；
- 根据 retrospective 最优结果自动改参数、选 winner 或晋升。

## 11. 人工 Review 必须回答的问题

1. 是否接受趋势 T0 以“删除 Lux Range、其余完全等同 T1”作为唯一基线？
2. 是否接受 T1 继续以现有 `subing_daily_trend_v1` 作为唯一突破版本？
3. 是否接受 T2 采用 `EMA21 opposite cross OR prior ATR trail breach` 的退出？
4. 是否接受 T3 的 `ER20 / VolumeRatio20 / OIDelta5` 仅作为中性参与度过滤，而不声称识别真实主力？
5. 是否接受震荡 R1/R2 作为 `subing_strategy_v1` 的 research-only child filter，而不新建独立高抛低吸策略？
6. 是否接受 rolling 12/3/3 是对既有 80/20 holdout 的补充，而非替代？
7. 是否接受 60% 正向 folds、25% coverage、MAE 不恶化超过 10% 和 20% product concentration 仅作为继续研究标准？

以上任一项未批准，实施保持阻塞。
