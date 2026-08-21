# Phase 6 — JDJ 1m Research & Candidate V1 Design

状态：DESIGN_APPROVED / IMPLEMENTATION_PENDING  
日期：2026-08-21  
设计冻结时点：2026-08-21T09:34:00+08:00  
目标分支：`develop`  
阶段属性：research-only / historical-only / no promotion

## 1. 目标

Phase 6 把用户明确保留的三条“日进斗金”1m 入场方法转换为可因果复算、可独立验证、可形成 Candidate baseline 的研究合同：

1. `TREND_FOLLOW` — 趋势跟随；
2. `TREND_REENTRY_6` — 顺势而为 6；
3. `KEY_LEVEL_BREAKOUT` — 关键位突破后的第二次机会。

本阶段不是重建原资料全部交易系统，也不是建立仓位、止盈止损、撮合或订单系统。它只回答：

> 在归一量化既有期货事实链上，这三条 source-derived setup 能否被转换为严格 causal 的 1m Candidate，并形成可冻结的 retrospective / rolling / prospective research baseline？

完成后最多允许声明三条 exact Candidate 已可复算并形成研究基线；不得声明策略有效、盈利、可交易、可通知或可晋升。

## 2. 来源边界

### 2.1 本阶段唯一策略来源

本阶段只采用用户在 2026-08-21 明确给出的两张“交易计划”截图及同消息中的逐字范围说明。用户明确要求：

> 交易策略只做下面三个，其他不用考虑。

三条来源语义为：

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

### 2.2 明确不导入其他资料规则

用户文件库中的其他交易资料可作为背景材料，但不得自动进入 JDJ V1 公式。尤其不得因为其他资料出现 MACD、BOLL、成交量倍数、持仓量、10/21/60MA、3 根确认、盈亏比、仓位或止损等规则，就把它们混入本 Candidate。

若未来要引入这些规则，必须新建明确的 Candidate / Policy 版本。

### 2.3 `SOURCE_DERIVED` 与 `GUIYI_ENGINEERING_V1`

Spec、代码注释和 evidence 必须区分：

- `SOURCE_DERIVED`：用户原始资料明确支持的交易语言；
- `GUIYI_ENGINEERING_V1`：原资料没有精确公式，为了机器因果复算而冻结的工程语义。

例如原资料写“20 均线”，而用户在设计讨论中明确决定“所有 MA 都使用 EMA”，因此：

```text
SOURCE_DERIVED: 20MA
GUIYI_ENGINEERING_V1: close-based EMA20
```

不得把 EMA20 反向表述成原资料作者的明确公式。

## 3. 项目边界与架构约束

Phase 6 必须服从当前仓库长期合同：

```text
RQData
→ Canonical Parquet
→ eight-table Catalog
→ MarketDataService
→ read-only research
```

研究对象固定为国内期货，不增加 QQQ、美股 provider 或第二套 Data Foundation。

禁止：

```text
直接读取 Parquet
glob / 自选主力
新增 Market Catalog 表
写 Canonical / DB / Redis
接 Live Overlay 作为历史事实
新增 Web / API 业务面
新增 Alert Rule / Scope
PushPlus 通知
Execution Review
订单 / 撮合 / 仓位 / 资金 / 费用 / 盈亏
release main / tag
Runtime promotion / switch
```

`auto_order=false` 始终成立。

## 4. Phase 6 的领域结构

推荐结构：一个 JDJ 1m Research Domain，共享公共事实，产生三个独立 Candidate。

```text
Historical Canonical
       │
MarketDataService
       │
┌──────┴─────────────────────┐
│                            │
actual-dominant 1m      actual-dominant 5m
│                            │
EMA20                  existing N Structure
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

不建立第二套趋势引擎，不复制 1m N，不新建通用 Strategy Platform。

## 5. Exact identity

### 5.1 Source policy

建议 exact source policy identity：

```text
jdj_1m_policy_v1
```

其不可变核心包括：

- `source_timeframe = 1m`；
- `trend_context_timeframe = 5m`；
- `trend_context = existing N Structure V1`；
- `ma_kind = EMA`；
- `ma_period = 20`；
- strict previous-bar trigger；
- same-day / same-contract / same-rank1-segment state boundary；
- no fixed setup timeout；
- no volume threshold；
- no fill model；
- no parameter sweep。

### 5.2 Three Candidate identities

三条 Candidate 必须独立：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

不能合并成一个 `jdj_1m_candidate_v1`，否则后续 evidence 无法判断是哪一种 setup 产生差异。

### 5.3 Validation protocol

三条 JDJ Candidate 共享同一套时间冻结和 price-outcome 语义，建议 protocol identity：

```text
jdj_candidate_validation_v1
```

Protocol 必须列出三个 exact candidate id，运行时不得接收任意未知 Candidate。

## 6. Market identity 与数据输入

### 6.1 研究市场

```text
market = domestic_futures
series = actual_dominant
anchor_symbol = jm
```

Phase 6 baseline 只对 `jm` 形成真实 evidence；active60 cross-symbol robustness 留到下一阶段。

### 6.2 频率

```text
entry/setup facts = 1m
trend facts = 5m
```

1m 和 5m 都只能通过 `MarketDataService` / 既有 actual-dominant research seam 读取。

### 6.3 身份一致性

任何 1m setup 必须与其读取的 5m trend/key-level context 满足：

```text
same symbol
same physical contract
same rank1 segment
```

roll、segment identity 不一致或源数据身份异常必须 fail-closed。

## 7. EMA 统一规则

用户已明确冻结：JDJ 中出现的所有 MA 均解释为 EMA。

V1 只实际需要 EMA20：

```text
EMA20[t] = existing project exact EMA implementation over completed 1m close
```

不得：

- 自己复制一份 EMA 公式；
- 使用 SMA20；
- 引入 EMA10/50/200 作为趋势过滤；
- 因 source 资料其他章节出现其他均线而扩展 V1。

EMA20 未 ready 时属于正常“无 setup”，不是 source error。

## 8. 趋势上下文：复用 existing 5m N Structure

JDJ 不用 EMA 斜率定义趋势。

Exact mapping：

```text
NStructureKind.BULL
→ only LONG JDJ setup

NStructureKind.BEAR
→ only SHORT JDJ setup

NStructureKind.RANGE
NStructureKind.UNDEFINED
→ no JDJ setup
```

JDJ 只消费 existing N Structure V1 的 immutable facts，不修改其 5m policy、Swing、N Pattern、BULL/BEAR/RANGE 公式或 Candidate identity。

## 9. 5m → 1m strict-before 时序 Gate

这是 Phase 6 最重要的未来函数防线。

当前 1m bar 只能使用在该 1m bar 开始前已经完成并确认的最新 5m N Structure / Pivot facts。

定义：

```text
eligible_5m_fact.observed_at < current_1m.bar_end
```

并且实现必须保证同一个 5m boundary 上刚产生的结构事实不能反向喂给构成该 boundary 的最后一根 1m。

例：

```text
09:35 这根 1m
→ 最多使用 <=09:30 已知的 5m context

09:35 新确认的 5m context
→ 最早供 09:36 1m 使用
```

禁止 same-boundary future use。

## 10. 状态生命周期边界

所有 JDJ reducer state 只在以下 identity 内存在：

```text
symbol
physical_contract
rank1 segment
trading_day
```

任一变化立即 reset：

- trading day change；
- physical contract roll；
- rank1 segment change；
- source identity unavailable / inconsistent。

JDJ setup 不跨 trading day。

## 11. 公共 EMA20 reaction

### 11.1 LONG support reaction

前提：pre-known 5m N = `BULL`。

某 completed 1m bar：

```text
low <= EMA20 <= high
AND
close > EMA20
```

产生：

```text
EMA20_SUPPORT_REACTION
```

### 11.2 SHORT resistance reaction

前提：pre-known 5m N = `BEAR`。

```text
low <= EMA20 <= high
AND
close < EMA20
```

产生：

```text
EMA20_RESISTANCE_REACTION
```

### 11.3 V1 不增加“附近”参数

不使用：

- ATR tolerance；
- bp / percentage distance；
- tick distance；
- 连续两根确认；
- K 线颜色。

必须真实触及 EMA20，并收回当前趋势一侧。

## 12. 公共 previous-bar trigger

用户已确认严格按“上一根 K”动态解释，而不是固定 reaction bar。

### 12.1 LONG

setup 在前一 completed 1m 已经 `ARMED_LONG` 后，当前 1m：

```text
current.high > previous_completed_1m.high
```

产生 LONG trigger candidate fact。

### 12.2 SHORT

```text
current.low < previous_completed_1m.low
```

产生 SHORT trigger candidate fact。

### 12.3 Strict breach

```text
current.high == previous.high
current.low == previous.low
```

均不算突破。

若某一分钟未触发，下一分钟使用新的 previous completed 1m high/low；不永远盯最初 reaction bar。

### 12.4 Trigger 不是 fill

只记录：

```text
trigger_level = previous 1m high/low
trigger_observed_at = current 1m bar_end
observation_close = current 1m close
```

不得生成：

```text
fill_price
order_price
slippage
fee
position
pnl
```

`trigger_level` 只是价格事实，不是模拟成交价。

## 13. 公共 ARMED 失效语义

不增加 3/5/10 根固定 timeout。

### 13.1 LONG

`ARMED_LONG` 只在以下事实之一出现时失效：

```text
pre-known 5m trend no longer BULL
OR
completed 1m close <= EMA20
```

### 13.2 SHORT

```text
pre-known 5m trend no longer BEAR
OR
completed 1m close >= EMA20
```

### 13.3 same-bar trigger / invalidation 冲突

若同一 completed 1m OHLC 同时满足：

```text
previous-bar strict trigger
AND
EMA invalidation
```

只有 OHLC 无法证明先后顺序，因此：

```text
AMBIGUOUS_TRIGGER_INVALIDATION
→ no Candidate Entry Event
→ setup terminal / invalidated
```

不得以乐观顺序假设“先成交后失效”。

5m context 使用 strict-before 语义，因此当前 1m bar 结束时新形成的 5m trend change 只影响下一根 1m，不反向取消本 bar 在旧已知 context 下的因果判断。

## 14. Strategy A — TREND_FOLLOW

### 14.1 LONG state machine

```text
IDLE
  │ pre-known 5m N = BULL
  │ EMA20_SUPPORT_REACTION
  ▼
ARMED_LONG
  ├─ current.high > previous.high
  │    AND no same-bar EMA invalidation
  │    → TRIGGERED
  │
  ├─ completed close <= EMA20
  │    → INVALIDATED
  │
  └─ pre-known 5m trend != BULL
       → INVALIDATED
```

`TRIGGERED` 或 `INVALIDATED` 后当前 episode 结束；只要之后重新形成新的独立 EMA reaction，可以在同一 trading day 建立新的 episode。Phase 6 不加入“每天最多几单”。

### 14.2 SHORT

完全镜像：

```text
BEAR
→ EMA20_RESISTANCE_REACTION
→ ARMED_SHORT
→ strict current.low < previous.low
```

### 14.3 Candidate event kind

```text
JDJ_TREND_FOLLOW_TRIGGERED
```

方向用 `LONG / SHORT` 单独字段表达，不复制两套业务实现。

## 15. Strategy B — TREND_REENTRY_6

来源描述中的“过了 20 均线平仓后，再一次入场”不能在 research-only 系统中伪造成真实仓位和平仓，因此机器事实只建立结构 proxy。

不得要求此前必须存在一笔真实/模拟 Trend Follow trade。

### 15.1 LONG prerequisite

```text
pre-known 5m N = BULL
```

先观察到至少一个 completed 1m：

```text
close > EMA20
```

才建立 `TREND_SIDE_CONFIRMED_LONG`。若一天开始时价格已经在 EMA20 下方，不得凭空认为刚刚发生了一次“跌破均线离场”。

### 15.2 Below-EMA excursion

随后出现：

```text
close <= EMA20
```

进入：

```text
BELOW_EMA_EXCURSION
```

记录：

```text
excursion_low = min(low of completed bars while close <= EMA20)
```

这只是 `EMA20_EXIT_PROXY`，不表示系统真的持有并平掉任何仓位。

### 15.3 Reclaim

第一次重新出现：

```text
close > EMA20
```

产生：

```text
EMA20_RECLAIMED
```

reclaim bar 本身不能同时充当后续 higher-low reaction；必须从下一根 completed 1m 开始寻找新的回撤结构。

### 15.4 Higher-low setup

reclaim 后第一次新的 LONG EMA reaction：

```text
low <= EMA20 <= high
AND
close > EMA20
```

要求：

```text
reaction.low > excursion_low
```

才产生：

```text
HIGHER_LOW_REENTRY_SETUP
→ ARMED_LONG
```

若这第一次 post-reclaim EMA reaction 满足：

```text
reaction.low <= excursion_low
```

则该 reentry episode 失败，不允许跳过它再挑后面的更好 reaction。

### 15.5 Reclaim failure / new excursion

reclaim 后、尚未确认 higher-low 之前再次出现：

```text
close <= EMA20
```

则此前 reclaim 失败，启动新的 `BELOW_EMA_EXCURSION`，新的 `excursion_low` 从当前 excursion 重新计算，不沿用旧 reference。

### 15.6 Trigger

`HIGHER_LOW_REENTRY_SETUP` 成为 `ARMED_LONG` 后，完全复用公共 previous-bar trigger 和 invalidation：

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
→ first close < EMA20 = RECLAIMED_SHORT
→ 下一阶段第一次 EMA resistance reaction
→ reaction.high < excursion_high
→ LOWER_HIGH_REENTRY_SETUP
→ ARMED_SHORT
→ current.low < previous.low
```

若 first post-reclaim resistance reaction 的 `high >= excursion_high`，该 episode 失败。

### 15.8 Candidate event kind

```text
JDJ_TREND_REENTRY_6_TRIGGERED
```

## 16. Strategy C — KEY_LEVEL_BREAKOUT

这是三条中最容易被主观参数污染的策略。V1 只采用 existing causal N Swing Pivot 作为 key level，不新建“关键位 detector”。

### 16.1 Key level source

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

key level 必须携带：

```text
pivot_id
price
confirmed_at
epoch
physical_contract
segment_start_trading_day
```

并服从第 9 节 strict-before Gate。

### 16.2 为什么不用“附近”参数

原资料说“再次到达关键位附近”，但没有给距离阈值。V1 不新增 ATR/bp/tick proximity。

一个 pivot 只有在它被确认后，价格随后重新处于 breakout 原侧，才可成为本次 breakout episode 的候选：

LONG：至少出现一个 post-confirmation completed 1m：

```text
close <= key_level
```

SHORT：至少出现：

```text
close >= key_level
```

这表示系统真实观察到了“关键位确认后，价格重新从原侧接近该位置”的 causal 条件，避免 pivot 刚确认时价格已经越过 level 而事后补标 first break。

### 16.3 FIRST_BREAK

LONG：在上述 eligibility 已成立后，后续 completed 1m 出现：

```text
previous completed close <= key_level
AND
current close > key_level
```

产生：

```text
FIRST_BREAK_CONFIRMED
```

SHORT 镜像：

```text
previous close >= key_level
AND
current close < key_level
```

first-break bar 只生成 observation fact，绝不直接形成 Candidate Entry Event。

### 16.4 “放量突破不要追”的 V1 处理

来源提到“放量突破不要追”，但没有机器可复算的放量阈值。

V1 不发明：

```text
1.5x volume
2x volume
N-bar average volume threshold
```

因此采取更保守的 exact 语义：

```text
所有 FIRST_BREAK 都不追
→ 必须等待 retest / second chance
```

first-break bar 的原始 volume 可以作为只读事实保留，但不得生成 `high_volume=true/false` 决策字段。

未来若要研究量能阈值，必须新 Candidate/Policy 版本。

### 16.5 Freeze key level during episode

`FIRST_BREAK_CONFIRMED` 后冻结：

```text
key_level_id
key_level_price
first_break_at
```

即使之后 existing N 产生新 pivot，也不能替换当前 episode 的 key level。

### 16.6 Retest / second chance

从 first-break 后的下一根 completed 1m 开始寻找 retest；first-break bar 本身不能同时充当 retest。

LONG accepted retest：

```text
low <= key_level
AND
close > key_level
```

产生：

```text
KEY_LEVEL_RETEST_ACCEPTED
→ ARMED_LONG
```

SHORT：

```text
high >= key_level
AND
close < key_level
→ ARMED_SHORT
```

### 16.7 Failed retest

LONG episode 等待 retest 时若 completed 1m：

```text
close <= key_level
```

则：

```text
FIRST_BREAK_FAILED
→ episode terminal
```

SHORT 镜像为 `close >= key_level`。

不允许把失败 retest 后的后续波动继续归入同一 first-break episode。

### 16.8 No retest / expiry

不增加 3/5/10 根 timeout。

等待期间若始终没有 retest，则只在以下边界结束：

```text
trading day end
physical contract / rank1 segment change
pre-known 5m trend no longer matches direction
```

记为：

```text
EXPIRED_NO_RETEST
```

这对应来源“如果不回撤，放弃这次机会”。

### 16.9 Second-chance trigger

accepted retest 进入 `ARMED` 后，完全复用公共 previous-bar trigger：

LONG：

```text
current.high > previous.high
```

SHORT：

```text
current.low < previous.low
```

事件：

```text
JDJ_KEY_LEVEL_BREAKOUT_TRIGGERED
```

### 16.10 Same key-level consumption

一个 `pivot_id` 在同一 trading day / rank1 segment 的 first-break episode 到达任一 terminal 状态后：

```text
TRIGGERED
FIRST_BREAK_FAILED
EXPIRED_NO_RETEST
```

V1 不再用同一 pivot_id 创建第二个 first-break episode；需要新的 eligible confirmed pivot 才能开始下一次关键位 episode。

这是避免反复在同一点位挑选“更好的一次”而产生 hindsight selection 的保守规则。

## 17. Immutable source facts / events

JDJ Domain 应输出不可变事实，而不是只有最终计数。

建议公共 identity：

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

setup-specific provenance 至少包含：

TREND_FOLLOW：

```text
trend_snapshot_observed_at
reaction_at
ema20_at_reaction
trigger_level
observation_close
```

TREND_REENTRY_6：

```text
excursion_started_at
excursion_extreme
reclaimed_at
higher_low_or_lower_high_reaction_at
trigger_level
```

KEY_LEVEL_BREAKOUT：

```text
key_level_pivot_id
key_level_price
key_level_confirmed_at
first_break_at
retest_at
trigger_level
```

所有 id 必须由业务 identity + timestamp/provenance 稳定构造，同一 exact 输入重复运行字节级稳定。

## 18. Candidate 与 source fact 的关系

三个 Candidate producer 只消费自己对应的 immutable trigger fact：

```text
JDJ_TREND_FOLLOW_TRIGGERED
→ jdj_trend_follow_1m_candidate_v1

JDJ_TREND_REENTRY_6_TRIGGERED
→ jdj_trend_reentry_6_1m_candidate_v1

JDJ_KEY_LEVEL_BREAKOUT_TRIGGERED
→ jdj_key_level_breakout_1m_candidate_v1
```

不得让一个 source trigger 同时冒充另一 Candidate。

## 19. Price outcome semantics

Phase 6 不重建 backtest engine。

每个 Candidate Entry Event 只做 post-event price observation。

### 19.1 Reference price

```text
reference_price = trigger bar completed close
```

不是 trigger level，也不是 simulated fill。

### 19.2 Horizons

JDJ source-specific baseline 观察：

```text
3 / 5 / 8 / 20 completed 1m bars
```

其中 3/5/8 与现有 Candidate research 的常用 horizon 对齐；20 是 JDJ 1m 的 source-specific 中等窗口，只用于 descriptive research。

未来 Multi-Candidate Robustness V2 做跨 Candidate common comparison 时，只比较彼此语义兼容的共同 horizon，不得因为 JDJ 有 20 就修改已有 SuBing/N V1 evidence。

### 19.3 Boundary

所有 horizon 必须：

```text
same trading day
same physical contract
same rank1 segment
```

不足 horizon → `sample_count=0 / unavailable sample`，不跨日、不跨 roll 补齐。

### 19.4 Metrics

每个 horizon 输出：

```text
sample_count
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

全部交易相关数值使用 `Decimal`；不得使用 float。

## 20. Temporal validation freeze

### 20.1 Freeze

设计批准发生在 2026-08-21 盘中，因此当前 trading day 不允许进入 retrospective baseline。

冻结：

```text
frozen_at = 2026-08-21T09:34:00+08:00
anchor_symbol = jm
retrospective_since = 2023-01-01
retrospective_through = 2026-08-20
embargo_trading_day = 2026-08-21
prospective_first_eligible_trading_day = 2026-08-24
```

如果既有 TradingSession / exchange calendar 不能确认 2026-08-24 为 freeze 后首个可交易日，实施必须 fail-closed 并在修改 Protocol 前重新走设计 Gate；不得动态挑选一个更有利日期。

### 20.2 Rolling schedule

复用现有 Candidate Validation 10-fold rolling schedule，不建立第二套 rolling engine：

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

### 20.3 Prospective

首次 baseline evidence 只能把 prospective 描述为：

```text
pending
first_trading_day = 2026-08-24
through = 2026-08-21
```

不得在 baseline 生成时把 2026-08-21 或任何 retrospective 历史数据回填为 prospective OOS。

## 21. Research CLI

Phase 6 建议新增只读 CLI：

```text
guiyi research jdj-1m \
  --candidate <exact-candidate-id> \
  --symbol jm \
  --through YYYY-MM-DD
```

以及复用/有界扩展 Candidate Validation：

```text
guiyi research candidate-validation \
  --candidate <jdj-candidate-id> \
  --protocol jdj_candidate_validation_v1 \
  --symbol jm \
  --through 2026-08-21
```

是否采用单独 `jdj-1m` CLI 或由现有 research command router 承载，应在 Implementation Plan 根据当前 parser/composition 最小改动确定；但最终必须保持 stdout JSON、read-only、无 DB/Canonical/Redis/Alert side effect。

运行时不得提供改变 exact policy 的参数，例如：

```text
--ema-period
--volume-multiple
--timeout-bars
--trend-method
--key-level-distance
```

这些都属于 Candidate identity，而不是 runtime 调参项。

## 22. Error / unavailable semantics

以下必须 fail-closed，不能降级成“无信号”：

```text
1m / 5m symbol mismatch
physical contract mismatch
rank1 segment mismatch
non-monotonic bars
same-boundary 5m future use
N Structure exact policy drift
EMA exact implementation mismatch
candidate/protocol identity mismatch
state crosses trading day or segment
unexpected source exception
reducer invariant violation
```

以下属于正常无机会：

```text
N = RANGE / UNDEFINED
EMA20 not ready
no EMA reaction
no previous-bar strict breach
no reentry higher-low/lower-high
key-level first break has no retest
horizon unavailable before day/segment end
```

不得为增加样本而 fallback。

## 23. Determinism / causality requirements

### 23.1 Prefix causality

对同一个 segment：

```text
run(bars[:n])
run(bars[:n+k])
```

第二次运行不得改变 `n` 时点以前已经形成的 immutable JDJ facts。

### 23.2 Deterministic ordering

相同输入重复运行：

- event ordering 相同；
- event ids 相同；
- report JSON 字节稳定；
- Decimal serialization 稳定。

### 23.3 LONG / SHORT symmetry

除方向和比较符号外，三条策略必须做镜像测试，禁止只靠多头样例推断空头正确。

## 24. Required test matrix

最低测试范围：

```text
EMA20 exact parity
EMA warm-up / readiness
5m N strict-before-1m
same-boundary 5m future-use rejection
same symbol/contract/segment identity
roll reset
trading-day reset
prefix causality

TREND_FOLLOW:
  long/short EMA reaction
  strict > / < trigger
  equal not trigger
  dynamic previous-bar trigger
  trend loss invalidation
  EMA loss invalidation
  same-bar trigger+invalidation ambiguous

TREND_REENTRY_6:
  prerequisite trend-side observed
  excursion extreme aggregation
  reclaim
  reclaim bar cannot be higher-low reaction
  higher-low / lower-high
  first failed post-reclaim reaction terminates episode
  reclaim failure starts new excursion
  trigger / invalidation symmetry

KEY_LEVEL_BREAKOUT:
  key level from exact eligible N pivot
  post-confirmation origin-side eligibility
  first break requires close transition
  first break never entry
  first-break bar cannot be retest
  accepted retest
  failed retest
  no-retest day expiry
  trend/roll expiry
  frozen level after first break
  same pivot consumed after terminal
  new pivot can open new episode

Candidate:
  three identities isolated
  source event kind exact
  3/5/8/20 same-day outcome
  no cross-day/roll horizon completion
  10 rolling folds exact
  baseline dates exact
  prospective pending / no backfill

Regression:
  N Structure full chain
  SuBing zero-regression
  existing Candidate Validation
  Multi-Candidate Robustness V1
```

## 25. Evidence plan

完成实现与独立 Review 后，在 exact `develop` 上生成三份版本化 baseline：

```text
reports/research/candidate_validation/
  jdj_trend_follow_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json

  jdj_trend_reentry_6_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json

  jdj_key_level_breakout_1m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-21.json
```

Evidence 生成前必须：

1. exact source commit clean；
2. 受影响 tests / Ruff / Mypy 通过；
3. 现有 SuBing/N baseline 可继续按自身 protocol 复算，不修改它们的冻结文件；
4. JDJ 三条 baseline 连续重复执行 byte-identical；
5. 独立 Evidence Review `Critical=0 / Important=0`。

Evidence Review 只允许研究事实结论，不输出 winner / rank / KEEP / DROP / PROMOTE。

## 26. Phase 6 与 Phase 7 边界

Phase 6 只做：

```text
JDJ exact domain
three Candidate producers
jm retrospective
10-fold rolling
prospective freeze
three deterministic baselines
```

不做：

```text
3 JDJ × active60 cross-symbol robustness
5 Candidate relationship matrix
parameter sweep
Candidate ranking
```

这些属于下一阶段 `Multi-Candidate Robustness V2`，届时研究集合为：

```text
SuBing
N Structure
JDJ Trend Follow
JDJ Trend Reentry 6
JDJ Key Level Breakout
```

## 27. 禁止范围

Phase 6 明确禁止实现：

```text
止盈 / 止损
移动止损
仓位管理
加仓
每日最大交易次数
每日盈利目标
资金曲线
回测撮合
成交模型
手续费 / 滑点
订单
账户连接
Web
Alert
PushPlus
Execution Review
active60 robustness
AI recommendation
自动 promotion
release / tag
Runtime switch/promotion
```

## 28. 完成 Gate

Phase 6 V1 完成最多允许写：

```text
三条 JDJ source-derived 1m setup 已被转换为 exact causal Candidate；
其趋势上下文复用 existing 5m N Structure，1m EMA20 与 previous-bar trigger 保持 causal；
已形成 jm retrospective / rolling baseline，并冻结各自 prospective OOS；
所有结果仍为 research-only。
```

绝不允许自动推出：

```text
JDJ 策略有效
JDJ 盈利
哪条 Candidate 更好
应该保留/淘汰哪条
可以发 Alert
可以给朋友推送
可以进入 Execution Review
可以正式交易
可以晋升 FormalPolicy
可以 release/tag
可以 Runtime promotion
```

## 29. 设计自洽性约束

任何实施中若出现以下需求，必须停止当前 Task 并重新设计：

```text
需要修改 existing N Structure V1 formula/policy
需要新增美股/QQQ data provider
需要修改 Data Foundation / Catalog / Canonical
需要引入成交量阈值才能解释 V1
需要引入 position/fill 才能定义 Candidate
需要增加 runtime tuning parameter
需要把三个 Candidate 合并成一个结果
需要改变冻结 retrospective / embargo / prospective 日期
```

这些都属于 `FORMULA_OR_CANDIDATE_DRIFT` 或架构范围变化，不能在实现时自行扩张。
