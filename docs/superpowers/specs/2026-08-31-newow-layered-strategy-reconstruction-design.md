# 牛哇趋势/震荡策略逐层复原研究设计

> 状态：Lane 3 / Plan-only / 待人工批准
>
> 本设计只定义 research-only 候选、因果时序和评价口径，不代表牛哇财经原始私有公式，不声明盈利，不授权接入 Alert、Runtime、main、tag、数据库或真实订单。

## 1. 目标

基于《牛哇财经操盘手册2026》与已观察到的网页表现，按固定顺序建立七个透明、可复算、可否证的研究候选：

1. `newow_trend_t0_baseline_v1`
2. `newow_trend_t1_breakout_v1`
3. `newow_trend_t2_trailing_v1`
4. `newow_trend_t3_stage_filter_v1`
5. `newow_range_r0_baseline_v1`
6. `newow_range_r1_deviation_v1`
7. `newow_range_r2_moments_v1`

每层只增加一个可归因模块，并与直接前驱在完全相同的数据身份、窗口和事件时序下比较增量贡献。

## 2. 事实边界

手册明确支持以下概念：

- 蓝变黄买入、黄变黄持有、黄变蓝卖出、蓝变蓝观望；
- 趋势运行、区间突破、假突破止损、回踩后的二次确认；
- 吸筹/洗盘/拉高/出货的阶段表达；
- 基于波动率，以偏度和峰度量化涨跌风险；
- 黄色反弹信号和紫色调整信号消失后确认反转；
- 杯柄、矩形、三角形、旗形等整理后突破。

手册未公开可直接复现的完整公式、窗口、阈值、成交时序和参数选择过程。因此本文所有数值公式均为归一量化的透明研究假设，不能描述为“牛哇原公式”。

## 3. 研究身份与边界

### 3.1 数据身份

- 数据入口：只通过 `MarketDataService`。
- 物理数据：Canonical `contract` / `continuous`，研究身份为 `actual_dominant`。
- 趋势族：`actual_dominant + 1d`。
- 震荡族：`actual_dominant + 15m`。
- 只消费 confirmed、按时间单调的完成 Bar。
- 每次 rank1 物理合约切换立即结束未完成状态并重新 warm-up；信号、跟踪线、区间和滚动统计均不得跨物理合约段继承。
- 本阶段不加入 5m 入场确认、不加入周线共振；这两项只能在七层完成后另开任务验证，避免混淆层贡献。

### 3.2 非交易边界

输出仅允许：

- 因果状态；
- 候选事件；
- 完整 reference episode；
- 固定 horizon 的 directional return、MFE、MAE；
- rolling fold 与 prospective OOS 报告。

不得建立账户、资金曲线、复利、仓位、撮合 worker、订单、自动年化收益排名或自动晋升。

## 4. 统一时序合同

所有层共享以下时间字段：

- `observed_at`：完成 Bar 的 `bar_end`；
- `confirmed_at`：规则全部满足、事件最早可知的完成 Bar；
- `effective_at`：`confirmed_at` 之后下一根同物理合约、同频率 Bar 的 open；
- `closed_at`：退出条件在完成 Bar 上首次确认的 `bar_end`；
- `close_effective_at`：`closed_at` 之后下一根同物理合约 Bar 的 open。

禁止：

- 在确认 Bar 内按突破价、最高价、最低价或新生成的跟踪线假设成交；
- 将后续确认的 Pivot、突破或反转回画成过去可执行事件；
- 在缺少下一根同物理合约 Bar 时跨段补成交；
- 使用 centered rolling、负 shift、backfill、未来 D1、未来高低点或未来目标价。

## 5. 趋势候选族

### 5.1 T0：趋势基础版

对每根 D1 Bar 计算：

```text
P_t = (3*C_t + O_t + H_t + L_t) / 6
W_t = (20*P_t + 19*P_{t-1} + ... + 1*P_{t-19}) / 210
S_t = SMA(W, 5)_t
```

状态：

```text
BULLISH  := W_t > S_t
BEARISH  := W_t < S_t
UNAVAILABLE := warm-up、数据身份或物理段不完整
```

事件仅在 `W/S` 完成 Bar 交叉时确认；网页黄色/蓝色只作为显示映射，不等同于真实仓位。

Reference episode：下一同段 D1 open 生效；反向交叉后下一同段 D1 open 关闭。

### 5.2 T1：增加突破

在 T0 上新增、且只新增 20 根前置完成 Bar 的冻结边界：

```text
Upper_t = max(H_{t-20}, ..., H_{t-1})
Lower_t = min(L_{t-20}, ..., L_{t-1})
```

- 多头 setup：T0=`BULLISH` 且 `close_t > Upper_t`；
- 空头 setup：T0=`BEARISH` 且 `close_t < Lower_t`；
- setup 边界在首次突破时冻结；
- 只有首次突破 Bar 加后续两根完成 Bar 均未收回冻结边界，才在第三根完成 Bar 确认；
- 任何一根收回边界则 setup 失效，不回画、不补信号。

T1 episode 退出：反向 T0 交叉，或突破确认后重新收回冻结边界；两者均以下一同段 D1 open 生效。

### 5.3 T2：增加跟踪

T1 入场不变，新增 Wilder ATR(14) Chandelier 式单向跟踪：

```text
LongCandidate_t  = HighestHighSinceConfirmation_t - 3 * ATR14_t
LongTrail_t      = max(LongTrail_{t-1}, LongCandidate_t)
ShortCandidate_t = LowestLowSinceConfirmation_t + 3 * ATR14_t
ShortTrail_t     = min(ShortTrail_{t-1}, ShortCandidate_t)
```

- 初始 trail 由确认 Bar 收盘后建立；
- Bar `t` 的退出只比较 `close_t` 与 `trail_{t-1}`，之后才更新 `trail_t`，避免同一 Bar 用新高/新低收紧并反向退出；
- trail 只向有利方向移动；
- 退出下一同段 D1 open 生效。

### 5.4 T3：增加阶段过滤

不得把统计标签描述为真实“主力吸筹/出货”。候选仅使用 `*_LIKE` / `*_RISK` 标签。

完成 Bar 上计算：

```text
ER20 = abs(C_t - C_{t-20}) / sum(abs(C_i - C_{i-1}), 20)
VolumeRatio20 = V_t / median(V_{t-20:t-1})
OIDelta5 = OI_t - OI_{t-5}
BiasATR = (C_t - EMA21_t) / ATR14_t
```

T3 只允许 T1 setup 进入确认流程，当且仅当：

```text
ER20 >= 0.35
VolumeRatio20 >= 1.20
directional OIDelta5 >= 0
abs(BiasATR) <= 2.50
```

其中多头 `directional OIDelta5 = OIDelta5`，空头同样要求持仓量不下降。缺少 OI、成交量中位数为零或任一特征 unavailable 时 fail-closed。

`DISTRIBUTION_RISK` 仅作为可解释标签：`abs(BiasATR) > 2.50`，或放量但 5-Bar 方向进展小于 `0.5*ATR14`；它不得单独生成反向交易事件。

## 6. 震荡候选族

### 6.1 R0：震荡基础版

对 15m Bar 计算：

```text
Center_t = EMA21_t
ER20 = abs(C_t - C_{t-20}) / sum(abs(C_i - C_{i-1}), 20)
CrossCount20 = 最近20根 close 对 Center 的方向切换次数
Upper_t = max(H_{t-20}, ..., H_{t-1})
Lower_t = min(L_{t-20}, ..., L_{t-1})
WidthATR_t = (Upper_t - Lower_t) / ATR14_t
SlopeATR_t = abs(EMA21_t - EMA21_{t-5}) / (5*ATR14_t)
```

Range-ready：

```text
ER20 <= 0.35
CrossCount20 >= 4
2.0 <= WidthATR_t <= 8.0
SlopeATR_t <= 0.10
```

事件：

- 多头均值回归候选：`low_t < Lower_t` 且 `close_t >= Lower_t`；
- 空头均值回归候选：`high_t > Upper_t` 且 `close_t <= Upper_t`。

边界与 `Center_t` 在确认时冻结。下一同段 15m open 生效；首次触及冻结中轴后下一 open 结束。失败条件为收盘越过冻结边界 `0.5*ATR_at_signal`，或 8 根完成 Bar 内未触及中轴；两者均在下一同段 open 结束。

### 6.2 R1：增加偏离

在 R0 上增加 ATR 标准化偏离状态：

```text
DeviationATR_t = (C_t - EMA21_t) / ATR14_t
```

- 多头 extreme：`DeviationATR <= -1.25`；
- 空头 extreme：`DeviationATR >= +1.25`；
- 事件不能在 extreme 首次出现时确认；必须等到偏离绝对值开始收缩、价格重新收回 R0 冻结边界的首根完成 Bar；
- `confirmed_at` 是收缩确认 Bar，不回写 extreme Bar。

### 6.3 R2：增加偏度/峰度

使用同物理段内最近 60 个完成 15m 对数收益，少于 60 个收益时 unavailable。计算确定性的样本偏度与 excess kurtosis，禁止依赖平台默认 `rolling.skew/kurt` 的版本差异。

- 多头尾部风险 active：`Skew60 <= -0.50` 且 `ExcessKurtosis60 >= 1.00`；
- 空头尾部风险 active：`Skew60 >= +0.50` 且 `ExcessKurtosis60 >= 1.00`；
- R2 事件要求：前一完成 Bar 尾部风险 active，当前 Bar 偏度绝对值收缩，同时满足 R1 的偏离收缩与边界回收；
- 信号在风险收缩 Bar 确认，不回画至极端 Bar。

## 7. 因果性与前缀不变性 Gate

每个候选必须独立通过：

1. **纯过去输入**：所有高低边界显式 `shift(1)`；只使用当前及过去完成 Bar。
2. **strict-before**：如未来增加 D1/周线上下文，只能消费严格早于目标 Bar 的已完成上级周期事实。
3. **逐前缀一致**：对每个 fixture 和自然样本逐 Bar 截断，prefix 运行的状态、边界、事件、trail、moments 与 full-run 对应前缀逐字段完全相等。
4. **batch/stream golden parity**：批量计算与逐 Bar 增量状态机逐字段完全相等。
5. **物理段隔离**：rank1 切换后不得出现旧状态、旧窗口、旧 trail 或跨段 effective Bar。
6. **边界 outcome 隔离**：任何 horizon 或 episode 缺少完整未来 Bar 时为 unavailable，不缩短 horizon、不跨物理段补齐。
7. **反回画测试**：后续新增数据不得改变既有 `observed_at/confirmed_at/effective_at` 和事件 identity。

任一失败即阻塞该层，不生成贡献结论。

## 8. OOS 与逐层贡献协议

### 8.1 冻结

七个候选的公式、参数、父子关系、固定 cohort 和两套 validation protocol 必须在第一次查看 prospective OOS 前同一次提交冻结。冻结后同 ID 任意 byte drift fail-closed；修改公式必须新 candidate/version，旧 OOS 不迁移。

- Retrospective：从 `2023-01-01` 到冻结时最后一个完整 Canonical 交易日；
- Rolling：12 个月 reference + 3 个月 test，步长 3 个月；
- Prospective OOS：冻结后第一个 Canonical 交易日开始，只自然累积，不回填；
- 趋势 horizons：`3/5/10/20` 个 D1 Bar；
- 震荡 horizons：`3/5/8` 个 15m Bar。

每个 fold/window 只评价窗口内完整事件；reference 的 future outcome 不得进入 test window。

### 8.2 贡献比较

固定比较：

```text
T1 - T0
T2 - T1
T3 - T2
R1 - R0
R2 - R1
```

T0、R0只给绝对基线，不与网站截图或精选案例比较。

每对候选报告：

- event/complete-episode 数；
- coverage retention；
- directional return、MFE、MAE 的中位数；
- 完整 episode reference change 中位数；
- trend false-breakout rate；
- range center-reversion rate、boundary-failure rate、timeout rate；
- 有样本 fold 数、正向增量 fold 数；
- product concentration；
- prospective OOS 状态与质量标记。

只允许 `OOS_PENDING`、`RETAIN_FOR_RESEARCH`、`REJECTED_BY_CONTRACT`、`INSUFFICIENT_EVIDENCE` 等研究状态；不得自动输出 winner、profitability、tradable、promotion 或正式策略结论。

### 8.3 预注册保留条件

一层只有在以下条件全部满足时，才可标记 `RETAIN_FOR_RESEARCH`：

- 全部 causality/prefix/golden/segment Gate 通过；
- 至少 60% 的有样本 rolling test folds 中，核心质量指标相对直接前驱改善；
- aggregate coverage retention 不低于 25%；
- aggregate MAE 绝对值不得比前驱恶化超过 10%；
- 任一单品种不得贡献超过全部正向 reference change 的 20%；
- prospective OOS 未达样本量时必须保持 `OOS_PENDING`，不能由 retrospective 代替。

这些条件只决定是否继续研究，不授权晋升。

## 9. 实现边界

建议新增 source-specific 路径：

```text
data/research_candidates/newow_*.json
data/research_protocols/newow_*_validation_v1.json
services/quant-api/app/research/newow/
services/quant-api/tests/research/newow/
```

允许复用：`MarketDataService`、Canonical domain、EMA/MACD/ATR 指标核、rolling window schedule 和现有 price outcome primitives。

禁止：

- 修改现有 `subing_lifecycle_v2_candidate_v1.json` 或 `candidate_validation_v1.json`；
- 将 Newow 并入 SuBing 正式公式；
- 创建 UniversalStrategyAdapter、通用回测平台、订单/账户域；
- 修改数据库 migration、Alert Rule/Scope、PushPlus、Runtime、main 或 tag；
- 写入 RQData、Canonical、production PostgreSQL/Redis；
- 根据 retrospective 最优结果自动改参数或选 winner。

## 10. 任务拆分与 Gate

每个任务独立 session、branch/worktree、PR，并从最新 `develop` 创建：

1. `research/newow-contracts`：candidate/protocol/cohort、typed loader、统一时间与 report contract。
2. `research/newow-trend-t0`
3. `research/newow-trend-t1`
4. `research/newow-trend-t2`
5. `research/newow-trend-t3`
6. `research/newow-range-r0`
7. `research/newow-range-r1`
8. `research/newow-range-r2`
9. `research/newow-layer-contribution-report`

Lane 3 不允许自动合并。每层完成 TDD、独立 Review 和 CI 后，由用户决定：`要求修正后再集成`、`允许集成 develop` 或 `阻塞`。集成 develop 不等于 release、Runtime 或正式策略晋升。
