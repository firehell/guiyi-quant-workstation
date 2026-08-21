# Phase 6 — JDJ 1m Research & Candidate V1 Design

状态：DESIGN_APPROVED / IMPLEMENTATION_PENDING  
日期：2026-08-21  
设计冻结：2026-08-21T09:34:00+08:00  
阶段属性：research-only / historical-only / no promotion

## 1. 目标

Phase 6 只把用户明确保留的三条“日进斗金”1m 入场方法转换为可因果复算、可独立验证、可形成 Candidate baseline 的研究合同：

1. `TREND_FOLLOW` — 趋势跟随；
2. `TREND_REENTRY_6` — 顺势而为 6；
3. `KEY_LEVEL_BREAKOUT` — 关键位突破后的第二次机会。

本阶段只回答：

> 在归一量化既有国内期货事实链上，这三条 source-derived setup 能否被转换为严格 causal 的 1m Candidate，并形成冻结的 retrospective / rolling / prospective research baseline？

完成后最多允许声明三条 exact Candidate 已可复算并形成研究基线；不得声明策略有效、盈利、可交易、可通知或可晋升。

## 2. 来源边界

### 2.1 唯一策略来源

本阶段唯一业务来源是用户 2026-08-21 提供的两张“交易计划”截图与同消息中的明确范围说明：

> 交易策略只做下面三个，其他不用考虑。

来源语义固定为：

```text
1. 趋势跟随（开盘和盘中）
上涨 or 下跌，等回撤，找入场点，入场
回撤：到 20 均线看反应
入场点：20 均线有支撑/阻力后，可能有信号
入场：过上一根 k 线高/低

2. 顺势而为 6（盘中）
过了 20 均线平仓后，再一次入场
20 均线以上，更高的低点做多
20 均线以下，更低的高点做空
找入场点入场和趋势跟随一样

3. 关键位突破（盘中）
找到关键位，价格再一次到达关键位附近，等待突破的机会
放量突破不要追
等回撤的机会，即第二次
如果不回撤，放弃这次机会
```

截图中的资金总量、单笔资金、每日盈利目标、止盈止损、移动止损、加仓、每日最多交易次数和额外保护措施全部不进入本阶段。

### 2.2 不导入其他资料规则

用户文件库中的其他交易资料只能作为背景，不能自动进入 JDJ V1 公式。尤其不得把其他资料中的 MACD、BOLL、成交量倍数、持仓量、10/21/60MA、3 根确认、盈亏比、仓位或止损规则混入本 Candidate。

未来若要引入这些规则，必须创建新的 Candidate / Policy 版本。

### 2.3 来源语义与工程语义分离

所有实现和 evidence 必须区分：

- `SOURCE_DERIVED`：用户原始材料明确写出的规则；
- `GUIYI_ENGINEERING_V1`：原材料未给机器公式、但为严格复算而冻结的规则。

例如：

```text
SOURCE_DERIVED: 20MA
GUIYI_ENGINEERING_V1: close-based EMA20
```

不得把 EMA20 反向描述为原资料作者明确规定。

## 3. 项目边界

研究对象固定为国内期货，不增加 QQQ、美股 provider 或第二套 Data Foundation。

唯一历史事实链保持：

```text
RQData
→ Canonical Parquet
→ eight-table Catalog
→ MarketDataService
→ read-only research
```

禁止：

```text
直接读取 Parquet
glob / 自选主力
新增 Market Catalog 表
写 Canonical / DB / Redis
把 Live Overlay 当历史事实
新增 Web / API 业务面
新增 Alert Rule / Scope
PushPlus 通知
Execution Review
订单 / 撮合 / 仓位 / 资金 / 费用 / 盈亏
release main / tag
Runtime promotion / switch
```

`auto_order=false` 始终成立。

## 4. 领域架构

一个 JDJ 1m Research Domain 共享公共事实，产生三个独立 Candidate：

```text
Historical Canonical
       │
MarketDataService
       │
┌──────┴─────────────────────┐
│                            │
actual-dominant 1m      actual-dominant 5m
│                            │
EMA20                  existing N Structure V1
│                      BULL/BEAR/RANGE
└──────────────┬─────────────┘
               │
          JDJ 1m Domain
               │
   ┌───────────┼────────────┐
   │           │            │
TREND_FOLLOW  TREND_REENTRY_6  KEY_LEVEL_BREAKOUT
   │           │            │
   ▼           ▼            ▼
Candidate A  Candidate B  Candidate C
```

不建立第二套趋势引擎，不复制 1m N，不建立通用 Strategy Platform。

## 5. Exact identities

### 5.1 Source policy

Exact source policy：

```text
jdj_1m_policy_v1
```

冻结：

```text
source_timeframe = 1m
trend_context_timeframe = 5m
trend_context = existing N Structure V1
ma_kind = EMA
ma_period = 20
previous_bar_trigger = strict
timeout_bars = none
volume_threshold = none
fill_model = none
parameter_sweep = false
state_boundary = same trading_day + physical_contract + rank1 segment
```

### 5.2 Candidate identities

三条 Candidate 必须独立：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

不能合并成单一 `jdj_1m_candidate_v1`。

### 5.3 Validation protocol

Exact protocol：

```text
jdj_candidate_validation_v1
```

该 protocol 只允许上述三个 exact Candidate；未知 candidate id 必须 fail-closed。

## 6. Market identity 与输入

```text
market = domestic_futures
series = actual_dominant
anchor_symbol = jm
entry/setup timeframe = 1m
trend/key-level timeframe = 5m
```

Phase 6 真实 baseline 只对 `jm`；active60 robustness 留到 Phase 7。

1m 与 5m 必须通过既有 `ActualDominantResearchSegmentLoader` / `MarketDataService` 一次加载同一 requested window。共享 loader 已支持多频率并验证恢复出的 rank1 segment identity 完全一致；JDJ 不复制 resolver。

任何联合事实必须满足：

```text
same symbol
same physical contract
same rank1 segment
```

身份不一致、roll mapping 异常或 source unavailable 必须 fail-closed。

## 7. EMA20 exact contract

用户已明确：JDJ 中所有 MA 都解释为 EMA。V1 只使用 EMA20。

必须复用 Indicator Kernel 公共 `guiyi_quant.indicators.ema_series`，不得复制 EMA 公式。

Exact call 语义：

```text
ema_series(
    completed_1m_closes,
    period=20,
    seed_policy="sma_window",
    round_digits=6,
)
```

Kernel 语义保持：

```text
first ready index = 19
seed = first 20 completed closes 的 SMA
alpha = 2 / (20 + 1)
closed_bar_only = true
repainting_risk = none
```

Reducer 与 `CanonicalBar` Decimal 价格比较时，只允许把 ready/valid `IndicatorPoint.value` 经稳定十进制字符串转换为 `Decimal`；禁止在业务比较中继续传播二进制 float。

不得：

- 使用 SMA20；
- 使用 `first_value` seed；
- 引入 EMA10/50/200；
- 修改 Indicator Kernel EMA V1。

EMA20 未 ready 属于正常“无 setup”。

## 8. 趋势上下文：existing 5m N Structure V1

JDJ 不用 EMA 斜率判断趋势。

```text
NStructureKind.BULL
→ only LONG JDJ setup

NStructureKind.BEAR
→ only SHORT JDJ setup

NStructureKind.RANGE / UNDEFINED
→ no JDJ setup
```

JDJ 只消费 existing 5m N Structure V1 的 immutable Swing / Pattern / Structure facts，不修改其 exact policy、公式、Candidate identity 或既有 evidence。

## 9. 5m → 1m strict-before Gate

当前 1m bar 只能使用该分钟开始前已经确认的最新 5m N Structure / Pivot facts。

对连续 1m bars，exact eligibility 为：

```text
eligible_5m_fact.observed_at <= previous_1m.bar_end
```

等价的必要条件：

```text
eligible_5m_fact.observed_at < current_1m.bar_end
```

例：

```text
09:35 这一根 1m
→ 最多使用 <=09:30 已知的 5m context

09:35 新确认的 5m context
→ 最早供 09:36 1m 使用
```

同一 5m boundary 刚产生的事实不得反向喂给组成该 boundary 的最后一根 1m。

## 10. Reducer 生命周期

所有 JDJ state 只存在于：

```text
symbol
physical_contract
rank1 segment
trading_day
```

以下任一发生立即结束或 reset 当前状态：

- trading day change；
- physical contract roll；
- rank1 segment change；
- source identity unavailable / inconsistent。

任何 setup 不跨 trading day。

## 11. 公共 EMA20 reaction

### LONG

前提：pre-known 5m N = `BULL`。

```text
low <= EMA20 <= high
AND
close > EMA20
→ EMA20_SUPPORT_REACTION
```

### SHORT

前提：pre-known 5m N = `BEAR`。

```text
low <= EMA20 <= high
AND
close < EMA20
→ EMA20_RESISTANCE_REACTION
```

V1 不增加 ATR、bp、percentage、tick proximity、连续两根确认或 K 线颜色。必须真实 touch EMA20 并收回趋势一侧。

## 12. 公共 previous-bar trigger

用户已确认“上一根 K”是动态 previous completed 1m，不是固定 reaction bar。

### LONG

setup 已在上一 boundary `ARMED_LONG` 后：

```text
current.high > previous_completed_1m.high
→ strict trigger
```

### SHORT

```text
current.low < previous_completed_1m.low
→ strict trigger
```

相等不算突破。

若当前未触发，下一分钟 trigger reference 更新为新的 previous completed 1m high/low。

只记录：

```text
trigger_level = previous 1m high/low
trigger_observed_at = current 1m bar_end
observation_close = current 1m close
```

不得生成 `fill_price`、order、slippage、fee、position、PnL。`trigger_level` 不是模拟成交价。

## 13. 公共 ARMED invalidation

不增加固定 N-bar timeout。

LONG：

```text
pre-known 5m trend != BULL
OR
completed 1m close <= EMA20
→ INVALIDATED
```

SHORT：

```text
pre-known 5m trend != BEAR
OR
completed 1m close >= EMA20
→ INVALIDATED
```

若同一 completed 1m OHLC 同时满足 previous-bar strict trigger 和 EMA invalidation，OHLC 无法证明先后顺序：

```text
AMBIGUOUS_TRIGGER_INVALIDATION
→ no Candidate Entry Event
→ episode terminal
```

不得用乐观顺序假设“先成交后失效”。当前 1m 结束时新确认的 5m context 只影响下一根 1m，不反向取消本 bar 使用旧 pre-known context 得到的判断。

## 14. Strategy A — TREND_FOLLOW

### LONG

```text
IDLE
  │ pre-known 5m N = BULL
  │ EMA20_SUPPORT_REACTION
  ▼
ARMED_LONG
  ├─ strict current.high > previous.high
  │    AND no same-bar EMA invalidation
  │    → TRIGGERED
  ├─ close <= EMA20
  │    → INVALIDATED
  └─ pre-known trend != BULL
       → INVALIDATED
```

### SHORT

完全镜像：

```text
BEAR
→ EMA20_RESISTANCE_REACTION
→ ARMED_SHORT
→ strict current.low < previous.low
```

Episode `TRIGGERED` / `INVALIDATED` 后结束；后续新的独立 EMA reaction 可以在同一 trading day 新建新 episode。V1 不加入每日次数限制。

Source event kind：

```text
JDJ_TREND_FOLLOW_TRIGGERED
```

## 15. Strategy B — TREND_REENTRY_6

来源中的“过了 20 均线平仓后”不能在 research-only 系统中伪造成真实仓位，因此只建立 `EMA20_EXIT_PROXY`；不要求此前存在真实或模拟 Trend Follow trade。

### 15.1 LONG prerequisite

pre-known 5m N = `BULL`，且必须先真实观察到至少一个 ready boundary：

```text
close > EMA20
→ TREND_SIDE_CONFIRMED_LONG
```

若日内一开始已在 EMA20 下方，不得事后推断“刚刚发生过跌破离场”。

### 15.2 Below-EMA excursion

之后首次：

```text
close <= EMA20
→ BELOW_EMA_EXCURSION
```

并在连续 excursion 期间维护：

```text
excursion_low = min(low while close <= EMA20)
```

### 15.3 Reclaim

第一次重新：

```text
close > EMA20
→ EMA20_RECLAIMED
```

reclaim bar 不能同时作为 higher-low reaction；必须从下一根 completed 1m 开始寻找新回撤。

### 15.4 Higher-low setup

reclaim 后第一次 LONG EMA reaction：

```text
low <= EMA20 <= high
AND
close > EMA20
```

只有：

```text
reaction.low > excursion_low
```

才产生：

```text
HIGHER_LOW_REENTRY_SETUP
→ ARMED_LONG
```

若这第一次 post-reclaim reaction 的 `reaction.low <= excursion_low`，episode 直接失败；不得跳过它再挑后面的更好 reaction。

### 15.5 Reclaim failure

reclaim 后、尚未确认 higher-low 前再次出现：

```text
close <= EMA20
```

旧 reclaim 失败；从当前 bar 开始新 `BELOW_EMA_EXCURSION`，新的 `excursion_low` 独立计算。

### 15.6 Trigger

`ARMED_LONG` 后复用公共 trigger/invalidation：

```text
current.high > previous.high
→ JDJ_TREND_REENTRY_6_TRIGGERED
```

### 15.7 SHORT

严格镜像：

```text
pre-known N = BEAR
先有 close < EMA20
→ close >= EMA20
→ ABOVE_EMA_EXCURSION
→ excursion_high = max(high)
→ first close < EMA20 = EMA20_RECLAIMED_SHORT
→ reclaim 后第一次 resistance reaction
→ reaction.high < excursion_high
→ LOWER_HIGH_REENTRY_SETUP
→ ARMED_SHORT
→ strict current.low < previous.low
```

若 first post-reclaim reaction 的 `high >= excursion_high`，该 episode 失败。

## 16. Strategy C — KEY_LEVEL_BREAKOUT

V1 不建立主观关键位 detector；key level 只来自 existing causal 5m N Swing Pivot。

### 16.1 Key level

LONG：

```text
pre-known 5m N = BULL
key_level = latest eligible confirmed 5m N HIGH pivot
```

SHORT：

```text
pre-known 5m N = BEAR
key_level = latest eligible confirmed 5m N LOW pivot
```

必须携带：

```text
pivot_id
price
confirmed_at
epoch
physical_contract
segment_start_trading_day
```

并服从 strict-before Gate。

### 16.2 “再次到达关键位附近”

来源没有 proximity 数字，V1 不加 ATR/bp/tick distance。

pivot 确认后，系统必须先观察价格重新处于 breakout 原侧：

```text
LONG:  post-confirmation close <= key_level
SHORT: post-confirmation close >= key_level
```

只有这一步发生后，pivot 才能进入 first-break eligibility。这样不会把 pivot 确认时价格已经越过 level 的状态事后补标成 breakout。

### 16.3 FIRST_BREAK

LONG：

```text
previous close <= key_level
AND
current close > key_level
→ FIRST_BREAK_CONFIRMED
```

SHORT：

```text
previous close >= key_level
AND
current close < key_level
→ FIRST_BREAK_CONFIRMED
```

first-break bar 只生成 observation fact，绝不直接形成 Candidate Entry Event。

### 16.4 “放量突破不要追”

来源没有定义何为放量，因此 V1 不发明 1.5x/2x/N-bar volume threshold。

采取保守 exact 规则：

```text
ALL FIRST_BREAK
→ DO_NOT_CHASE
→ must wait retest / second chance
```

first-break 原始 volume 可作为 provenance 保存，但不能生成 `high_volume` 判定。

### 16.5 Freeze level

`FIRST_BREAK_CONFIRMED` 后冻结：

```text
key_level_pivot_id
key_level_price
first_break_at
```

后续新 N pivot 不得替换当前 episode 的 level。

### 16.6 Retest / second chance

first-break 后下一根 1m 起才允许 retest；first-break bar 不能同时当 retest。

LONG accepted retest：

```text
low <= key_level
AND
close > key_level
→ KEY_LEVEL_RETEST_ACCEPTED
→ ARMED_LONG
```

SHORT：

```text
high >= key_level
AND
close < key_level
→ KEY_LEVEL_RETEST_ACCEPTED
→ ARMED_SHORT
```

### 16.7 Failed retest

等待 retest 时：

```text
LONG:  close <= key_level
SHORT: close >= key_level
→ FIRST_BREAK_FAILED
→ episode terminal
```

不得把失败 retest 后的后续波动继续归入同一 first-break episode。

### 16.8 No retest / context expiry

不设 N-bar timeout。

以下任一结束 waiting episode：

```text
trading day end
physical contract / rank1 segment change
pre-known 5m trend no longer matches direction
```

分别保留稳定 reason，例如：

```text
EXPIRED_NO_RETEST
EXPIRED_CONTEXT_LOST
```

### 16.9 Second-chance trigger

accepted retest 后复用公共 previous-bar trigger：

```text
LONG:  current.high > previous.high
SHORT: current.low < previous.low
→ JDJ_KEY_LEVEL_BREAKOUT_TRIGGERED
```

### 16.10 Same pivot consumption

一个 `pivot_id` 在同一 trading day / rank1 segment 的 first-break episode 到达任一 terminal 状态后不得重新创建另一个 first-break episode；只有新的 eligible confirmed pivot 可以开始新 episode。

该规则防止在同一点位反复挑选“更好的一次”造成 hindsight selection。

## 17. Immutable source facts

JDJ Domain 必须输出不可变事实，不得只输出聚合计数。

公共 identity 至少包含：

```text
source_event_id
source_kind = jdj_1m
setup_kind
candidate_id
direction
symbol
physical_contract
segment_start_trading_day
trading_day
observed_at
segment_bar_index
```

TREND_FOLLOW provenance：

```text
trend_snapshot_observed_at
reaction_at
ema20_at_reaction
trigger_level
observation_close
```

TREND_REENTRY_6 provenance：

```text
excursion_started_at
excursion_extreme
reclaimed_at
higher_low_or_lower_high_reaction_at
trigger_level
observation_close
```

KEY_LEVEL_BREAKOUT provenance：

```text
key_level_pivot_id
key_level_price
key_level_confirmed_at
first_break_at
retest_at
trigger_level
observation_close
```

ID 必须由稳定业务 identity + timestamp/provenance 构造；相同 exact 输入重复运行保持一致。

## 18. Candidate producers

```text
JDJ_TREND_FOLLOW_TRIGGERED
→ jdj_trend_follow_1m_candidate_v1

JDJ_TREND_REENTRY_6_TRIGGERED
→ jdj_trend_reentry_6_1m_candidate_v1

JDJ_KEY_LEVEL_BREAKOUT_TRIGGERED
→ jdj_key_level_breakout_1m_candidate_v1
```

一个 source trigger 不能冒充另一个 Candidate。

## 19. Price outcome semantics

Phase 6 不重建 backtest engine。Candidate Entry Event 只做 post-event price observation。

Reference：

```text
reference_price = trigger bar completed close
```

不是 trigger level / fill。

JDJ source-specific horizons：

```text
3 / 5 / 8 / 20 subsequent completed 1m bars
```

对 horizon H：

- directional return 使用第 H 根 subsequent completed 1m 的 close；
- MFE/MAE 只看 subsequent bars `1..H`；
- 不把 trigger bar 内部 high/low 纳入后验，避免把触发前后的同 bar 路径混在一起。

所有 horizon 必须：

```text
same trading day
same physical contract
same rank1 segment
```

不足 H → 该 horizon 无样本，不跨日/roll 补齐。

输出：

```text
sample_count
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

交易相关计算使用 `Decimal`。

3/5/8 与既有 research 常用 horizon 对齐；20 只属于 JDJ source-specific descriptive window。Phase 7 跨 Candidate common comparison 只使用彼此语义兼容的共同 horizon，不修改 SuBing/N V1 evidence。

## 20. Temporal validation freeze

设计批准发生在 2026-08-21 盘中，因此当天不得进入 retrospective。

冻结：

```text
frozen_at = 2026-08-21T09:34:00+08:00
anchor_symbol = jm
retrospective_since = 2023-01-01
retrospective_through = 2026-08-20
embargo_trading_days = [2026-08-21]
prospective_first_eligible_trading_day = 2026-08-24
```

2026-08-24 必须由仓库 existing TradingSession / exchange calendar 验证为 freeze 后首个 eligible trading day；若验证失败，实施 fail-closed 并重新走设计 Gate，不得动态挑日期。

Rolling 必须复用现有 Candidate Validation 10-fold schedule：

```text
fold_01 ref 2023-01-01..2023-12-31 / test 2024-01-01..2024-03-31
fold_02 ref 2023-04-01..2024-03-31 / test 2024-04-01..2024-06-30
fold_03 ref 2023-07-01..2024-06-30 / test 2024-07-01..2024-09-30
fold_04 ref 2023-10-01..2024-09-30 / test 2024-10-01..2024-12-31
fold_05 ref 2024-01-01..2024-12-31 / test 2025-01-01..2025-03-31
fold_06 ref 2024-04-01..2025-03-31 / test 2025-04-01..2025-06-30
fold_07 ref 2024-07-01..2025-06-30 / test 2025-07-01..2025-09-30
fold_08 ref 2024-10-01..2025-09-30 / test 2025-10-01..2025-12-31
fold_09 ref 2025-01-01..2025-12-31 / test 2026-01-01..2026-03-31
fold_10 ref 2025-04-01..2026-03-31 / test 2026-04-01..2026-06-30
```

首次 baseline request-through 固定：

```text
through = 2026-08-21
```

因此 baseline prospective 必须是：

```text
status = pending
first_trading_day = 2026-08-24
through = 2026-08-21
result = null
```

不得把 2026-08-21 或任何 retrospective 历史数据回填为 OOS。

## 21. Read-only CLI

新增 exact source CLI：

```text
guiyi research jdj-1m \
  --candidate <exact-jdj-candidate-id> \
  --symbol <symbol> \
  --since YYYY-MM-DD \
  --through YYYY-MM-DD
```

它只允许三个 exact JDJ candidate id；stdout JSON only；无文件写入、DB、Redis、Alert、Web side effect。

Candidate baseline 复用现有入口：

```text
guiyi research candidate-validation \
  --candidate <exact-jdj-candidate-id> \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-21
```

禁止 runtime formula 参数：

```text
--ema-period
--volume-multiple
--timeout-bars
--trend-method
--key-level-distance
```

这些都属于 exact Candidate identity，不能作为 CLI 调参项。

## 22. Error / no-op semantics

必须 fail-closed：

```text
1m / 5m symbol mismatch
physical contract mismatch
rank1 segment mismatch
non-monotonic bars
same-boundary 5m future use
N Structure exact policy drift
EMA exact implementation/version drift
candidate/protocol identity mismatch
state crosses trading day/segment
unexpected source exception
reducer invariant failure
```

正常“无机会”：

```text
N = RANGE / UNDEFINED
EMA20 not ready
no EMA reaction
no previous-bar strict breach
no reentry higher-low/lower-high
key-level first break has no retest
horizon unavailable before day/segment end
```

不得为增加样本 fallback。

## 23. Determinism / causality

### Prefix causality

同一 segment：

```text
run(bars[:n])
run(bars[:n+k])
```

第二次运行不得改变 `n` 时点以前已经形成的 immutable JDJ facts。

### Deterministic identity

相同输入重复运行必须保持：

- event ordering；
- event ids；
- Decimal serialization；
- report JSON bytes。

### LONG / SHORT symmetry

三条策略必须做镜像测试，不能只验证多头。

## 24. Required tests

最低测试矩阵：

```text
Common:
  ema_series exact EMA20 parity
  warm-up / readiness
  Decimal conversion parity
  multi-frequency rank1 segment identity
  5m strict-before-1m
  same-boundary future-use rejection
  roll reset
  trading-day reset
  prefix causality

TREND_FOLLOW:
  long/short reaction
  strict > / < trigger
  equal not trigger
  dynamic previous-bar trigger
  trend invalidation
  EMA invalidation
  same-bar trigger+invalidation ambiguous

TREND_REENTRY_6:
  trend-side prerequisite
  excursion extreme aggregation
  reclaim
  reclaim bar cannot be reaction
  higher-low / lower-high
  first failed post-reclaim reaction terminates
  reclaim failure starts new excursion
  trigger/invalidation symmetry

KEY_LEVEL_BREAKOUT:
  eligible exact N pivot
  post-confirmation origin-side requirement
  first break close transition
  first break never entry
  first-break bar cannot be retest
  accepted retest
  failed retest
  no-retest expiry
  trend/roll expiry
  frozen key level
  same pivot consumed after terminal
  new pivot opens new episode

Candidate Validation:
  three exact candidate identities isolated
  source event kind exact
  3/5/8/20 outcomes
  trigger bar excluded from future MFE/MAE
  no cross-day/roll horizon completion
  exact 10 folds
  frozen dates
  prospective pending / no backfill

Regression:
  N Structure full chain
  SuBing zero-regression
  existing Candidate Validation
  Multi-Candidate Robustness V1
```

## 25. Versioned evidence

实现、Implementation Review 通过后，在 exact `develop` 上生成三份 baseline：

```text
reports/research/candidate_validation/
  jdj_trend_follow_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json

  jdj_trend_reentry_6_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json

  jdj_key_level_breakout_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json
```

Evidence 前置：

1. exact source commit clean；
2. affected tests / Ruff / Mypy PASS；
3. existing SuBing/N baseline 可按自身 protocol 复算且不得被修改；
4. 三条 JDJ baseline 连续重复生成 byte-identical；
5. independent Evidence Review：`Critical=0 / Important=0`。

Evidence Review 只报告研究事实，不输出 winner / rank / KEEP / DROP / PROMOTE。

## 26. Phase 6 / Phase 7 boundary

Phase 6：

```text
JDJ exact domain
three Candidate producers
jm retrospective
10-fold rolling
prospective freeze
three deterministic baselines
```

Phase 6 不做：

```text
3 JDJ × active60 robustness
5-Candidate relationship matrix
parameter sweep
Candidate ranking
```

Phase 7 `Multi-Candidate Robustness V2` 再研究：

```text
SuBing
N Structure
JDJ Trend Follow
JDJ Trend Reentry 6
JDJ Key Level Breakout
```

## 27. 明确禁止范围

```text
止盈 / 止损 / 移动止损
仓位管理 / 加仓
每日最大交易次数 / 盈利目标
资金曲线
backtest fill model
手续费 / 滑点
订单 / 账户连接
Web / API
Alert / PushPlus
Execution Review
active60 robustness
AI recommendation
自动 promotion
release / tag
Runtime switch / promotion
```

## 28. 完成 Gate

Phase 6 最多允许结论：

```text
三条 JDJ source-derived 1m setup 已被转换为 exact causal Candidate；
趋势上下文复用 existing 5m N Structure；
EMA20 / previous-bar trigger / key-level second chance 均保持 causal；
已形成 jm retrospective / rolling baseline 并冻结 prospective OOS；
结果仍为 research-only。
```

禁止推出：

```text
策略有效 / 盈利
哪条 Candidate 更好
KEEP / DROP / PROMOTE
可以 Alert / PushPlus
可以进入 Execution Review
可以正式交易
可以晋升 FormalPolicy
可以 release/tag
可以 Runtime promotion
```

## 29. Design drift Gate

实施中出现以下任一需求必须停止并重新设计：

```text
修改 existing N Structure V1 formula/policy
新增 QQQ/美股 provider
修改 Data Foundation / Catalog / Canonical
引入成交量阈值才能解释 V1
引入 position/fill 才能定义 Candidate
增加 runtime tuning parameter
合并三个 Candidate identity
改变 frozen retrospective / embargo / prospective 日期
```

这些都属于 `FORMULA_OR_CANDIDATE_DRIFT` 或架构范围变化，不能在实现时自行扩张。
