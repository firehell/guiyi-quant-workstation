# 日进斗金 JM 1m Shared Strategy Kernel 设计

更新时间：2026-08-23
状态：Review 后正式 Strategy Spec；授权后续代码实现，不授权真实 RQAlpha 回测、Runtime、通知、main/tag 或任何正式数据写入

## 1. 目标与 V1 完整性定义

本 Spec 将现有 `jdj_1m_v1` 从“只读 Candidate Research”扩展为第一套完整、可复算、可由多个消费者复用的交易策略语义，同时保持已经冻结的 JDJ/N Candidate 因果公式不变。

第一版只落地：

```text
strategy_id = jdj_intraday_futures_v1
profile_id  = jdj_jm_1m_v1
symbol      = jm
series_kind = actual_dominant
execution   = 1m
trend       = 5m
```

这里的“完整策略”严格指：对当前已经工程化的三类 JDJ Entry Setup，完整覆盖 Candidate → Entry Authorization → 仓位 → 部分止盈 → 最多两次盈利加仓 → 保护位 → 日风险 → Exit → Attribution 的交易生命周期。

V1 **不等于**把《股票日内交易入门》中的 VWAP、ABC、三角形、盘整区间、Trap、Camarilla 等全部 Entry 战法同时实现。那些战法以后只能以新的、可单独验证的 setup 进入同一个 Kernel。

同一套 Strategy Kernel 最终服务三个消费者：

1. 现有 JDJ Candidate Research；
2. Canonical `actual_dominant` Historical Strategy Replay / Market 主图；
3. RQAlpha Plus local-only、research-only 回测 adapter。

本阶段不证明策略盈利、有效、可交易、OOS-ready 或可晋升。

## 2. Review 后的关键修正

正式实现必须遵守以下修正：

1. N/JDJ 公式迁移不能依赖 old/new 不同 dataclass 类型的直接 equality；先冻结 golden projection，再 `git mv` 纯模块并对 golden 逐字段复算。
2. Shared Candidate Kernel 当前是 batch 语义；RQAlpha adapter 之前必须增加 streaming evaluator，并证明 streaming 输出与 batch 输出逐事件一致。禁止每根 1m Bar 从 segment 起点全量重算的 O(n²) 实现。
3. V1 取消“Bar 内按 stop/target 精确成交”的 reference fill。所有策略管理决策均在 completed 1m Bar 后确认，统一用下一可执行 Bar open 作为 reference fill；RQAlpha 固定使用 `next_bar`。原因是 RQAlpha Plus 公共 OrderStyle 只有 Market/Limit/TWAP/VWAP，没有本 Spec 可依赖的原生 stop-order 语义，V1 不制造无法跨引擎复现的 intrabar 精确性。
4. 原作者规则与 JM 工程适配分层：策略理念参数进入 `JdjStrategyPolicy`，JM/1m 的确定性适配进入 `JdjStrategyProfile`。
5. 每笔交易必须有 `episode_id`；所有 ADD/REDUCE/EXIT 和 source event 去重属于同一 Trade Episode。
6. RQAlpha 主力映射不得直接查询 `MainContractMap` 自行选主力；必须复用 `MarketDataService` / `ActualDominantResearchSegmentLoader` 已验证的 actual_dominant identity，再导出只含身份的 schedule。
7. Entry 在 decision close 通过 R:R 并不代表 next-bar gap 后仍合法；必须计算 admissible entry bound，并在 reference/RQAlpha fill 前重新校验。
8. “当日亏损达到 1%”原始资料只明确停止继续交易，没有明确必须立即强平。V1 若选择平掉现有仓位，必须明确标记为 JM 工程适配，不能冒充原作者原文。
9. 日内不隔夜与 `next_bar` 组合必须有 session-aware terminal guard；不能等最终 Bar 完成后才下平仓决定。

## 3. 事实来源分域

不要用一个全局优先级把不同语义混在一起。

### 3.1 Entry Setup 事实源

Entry Setup 只看仓库已经冻结的：

- `data/research_policies/jdj_1m_policy_v1.json`；
- 当前 JDJ/N pure reducers 与 event identity；
- 对应 Candidate validation / robustness evidence。

《股票日内交易入门》不得用来静默改写现有 Candidate 的 EMA、N、strict-before、trigger 或 event identity。

### 3.2 Trade Management 原始依据

交易管理以用户提供的《股票日内交易入门》为主要原始依据。本 Spec 只采用文件中能够明确机械化的规则：

- 书页 28～33：开仓前明确止损与潜在盈利，作者一般只做盈亏比高于 2:1 的交易；
- 书页 34～37：单笔 planned risk 不超过账户总资金 1%，仓位由风险约束与资金约束共同决定；
- 书页 134～140：亏损仓禁止加仓；已有盈利并完成部分止盈后，前两次有效回到 20MA 的机会可以各增加当前持仓约 1/4，第三、第四次不再增加；加仓后提高保护位；
- 书页 141～143：当日亏损超过 0.5% 暂停 15 分钟，达到 1% 后停止当天继续交易。

文件中的仓位示例包含第一次目标减 200/500、第二次目标再减 200、保留 100，但它是示例，不足以证明“每一笔都固定 40%/40%/20%”。因此 V1 的 40% 首次减仓只属于 profile engineering adaptation。

### 3.3 JM V1 工程适配

以下规则是为了把人工体系变成一个确定、可复算的焦煤 1m 研究策略，不宣称为作者唯一原始参数：

- `base_risk_fraction=0.5%`；
- 首次结构目标完成后 reference reduce 40%；
- completed-bar stop/target 判定 + next-bar-open reference fill；
- Entry gap admissibility；
- daily 1% 达到后 V1 选择退出剩余仓位；
- session terminal guard；
- Historical Replay 的 reference account/cost/margin assumptions。

## 4. 架构与依赖方向

采用方案 B，但保持个人项目所需的最小边界：

```text
MarketDataService Canonical Bars                  RQAlpha Bundle Bars
             │                                           │
             └────────── normalized CanonicalBar value ──┘
                                  │
                         Shared N/JDJ Kernel
                                  │
                    Candidate + Strategy Decisions
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
               Research      Historical      RQAlpha
                             Reference Replay Adapter
                                  │
                                  ▼
                              Market Web
```

`CanonicalBar` 在 Kernel 中仅作为已经存在的不可变 OHLCV/domain value shape 使用，不代表 Kernel 可以读取 Canonical 存储。V1 **不再创建第二套 `JdjMarketBar` DTO**，避免为了命名重新复制一套 Bar 类型。RQAlpha adapter 只能把 Bundle Bar 转成内存中的 `CanonicalBar` value；不得从 Canonical 文件/DB读取价格。

硬约束：

- 不建立通用 `StrategyBase`、插件框架、Portfolio Engine、参数优化平台或自动晋升系统；
- 不复制 JDJ/N 公式到 Web 或 RQAlpha strategy file；
- `app.strategy_kernel` 不依赖 FastAPI、SQLAlchemy、RQAlpha、Redis、Alert、Execution Review 或 Runtime；
- Research 可以依赖 Strategy Kernel，Strategy Kernel 不得反向依赖 `app.research.*`；
- RQAlpha adapter 只负责 Bundle facts、order/fill translation 和 strategy state 回灌。

## 5. 模块边界

目标代码边界：

```text
services/quant-api/app/strategy_kernel/
├── n_structure/
│   ├── n_structure_policy.py
│   ├── n_structure_pattern.py
│   ├── n_structure_swing.py
│   ├── n_structure_state.py
│   └── n_structure_segment.py
└── jdj/
    ├── jdj_policy.py
    ├── jdj_context.py
    ├── jdj_events.py
    ├── jdj_trend_follow.py
    ├── jdj_trend_reentry.py
    ├── jdj_key_level_breakout.py
    ├── strategy_policy.py
    ├── strategy_profile.py
    ├── target.py
    ├── risk.py
    ├── execution.py
    ├── engine.py
    └── streaming.py
```

只下沉 pure causal N/JDJ modules。Candidate validation、Research request/outcome、robustness、dossier、CLI、HTTP projection 继续位于 `app.research`。

最终不得保留第二份公式实现或长期 compatibility shim。

## 6. 现有 Candidate 语义必须原样保持

V1 Entry 只启用：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

必须保持：

- source timeframe=`1m`；trend context=`5m`；
- EMA20 的现有 SMA seed、rounding、close input；
- 5m N Structure strict-before；
- same trading day / same physical contract / same rank1 segment；
- previous-bar dynamic trigger，equal 不算 breach；
- Trend Follow reaction/invalidation；
- Trend Reentry 6 excursion/reclaim/first-reaction；
- Key Level first-break 不追、retest、same-pivot single episode；
- event id、candidate id、source event kind、direction、`observed_at`、trigger level 与现有计数。

重构和 streaming evaluator 均必须对相同输入得到同一 golden projection。

## 7. Policy 与 Profile

### 7.1 Strategy Policy：交易理念不可按品种调参

`data/strategy_policies/jdj_intraday_futures_v1.json` 至少冻结：

```text
policy_id                         = jdj_intraday_futures_v1
candidate_policy_id               = jdj_1m_policy_v1
minimum_reward_risk               = 2.0
max_planned_trade_risk_fraction   = 0.01
require_profit_before_add         = true
require_partial_profit_before_add = true
add_fraction_of_current_qty       = 0.25
max_add_count                     = 2
losing_position_add_forbidden     = true
daily_pause_drawdown_fraction     = 0.005
daily_pause_minutes               = 15
daily_stop_drawdown_fraction      = 0.01
```

这些字段不能在 Web 或按品种 profile 中被覆盖。

### 7.2 JM 1m Profile：工程适配可版本化

`data/strategy_profiles/jdj_jm_1m_v1.json`：

```text
profile_id                         = jdj_jm_1m_v1
symbol                             = jm
series_kind                        = actual_dominant
execution_frequency                = 1m
trend_context_frequency            = 5m
base_risk_fraction                 = 0.005
first_profit_take_fraction         = 0.40
reference_stop_buffer_ticks        = 0
terminal_flatten_lead_bars         = 1
no_new_entry_lead_bars             = 1
opening_profit_giveback_guard      = disabled
historical_reference_cost_model    = excluded
historical_reference_margin_check  = disabled
```

`reference_stop_buffer_ticks=0` 是 Review 后的收敛：仓库当前没有版本化历史 tick-size contract 可保证跨历史时期正确，V1 不用“当前 tick”回填旧历史。真实 RQAlpha 运行可以使用 Bundle instrument facts，但不得借此改变 Shared structural stop。

未来 5m/15m/其他周期必须新增 versioned profile，不允许自动按倍率缩放 1m 参数。

## 8. Historical 数据合同

Historical Replay 继续使用正式 Historical 事实链：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ validated physical-contract rank1 segments
→ Shared Strategy Kernel
```

要求：

- 不直接查询 `main_contract_map` 自行挑主力；
- 不使用 continuous 代替 actual_dominant；
- 不跨 physical contract 传播 EMA、N、Candidate、Episode、Daily Risk；
- loader identity/coverage 异常 fail-closed；
- API `since` 可以位于 segment 中间，但计算必须从 loader 提供的真实 segment start warm up；只抑制 requested `since` 之前的输出，不能从 `since` 冷启动 EMA/N；
- Replay 不写 Canonical、DB 或 Redis。

## 9. Candidate → Entry Authorization

```text
Candidate
→ same-bar conflict resolution
→ structural stop
→ known target
→ signal-time R:R
→ admissible fill bound
→ daily/session gate
→ reference quantity
→ ENTRY_INTENT
→ next executable bar open revalidation
→ ENTRY or REJECTED_CANDIDATE
```

### 9.1 冲突

- 同方向多个 Setup：只产生一个 intent；归因优先级固定 `key_level_breakout > trend_reentry_6 > trend_follow`，其余作为 supporting setups；该顺序只用于 attribution，不代表强弱排名。
- 同一 decision Bar 同时 LONG/SHORT：拒绝，`AMBIGUOUS_DIRECTION`。

### 9.2 Structural Stop

Stop 只使用 decision time 已知事实，且 V1 不加历史 tick buffer：

- Trend Follow：reaction Bar adverse extreme；
- Trend Reentry 6：frozen excursion extreme；
- Key Level Breakout：frozen key level。

这些是 JM V1 的 execution mapping，不修改 Candidate 本身。

### 9.3 Target

Decision time 可用 target candidates 只有：

1. 同 physical segment、已 confirmed 的 favorable 5m N pivots；
2. 当前 trading day 截至 decision Bar 已知的 favorable 1m session high/low。

选择离 entry reference 最近的 favorable known level 作为 `target_1`。没有 forward level：`TARGET_UNAVAILABLE`。

V1 不用未来 pivot、不预测目标、不实现第二个固定 target。

### 9.4 R:R 与 admissible fill bound

Signal-time `entry_reference = Candidate.observation_close`。

```text
planned_risk   = abs(entry_reference - stop)
planned_reward = abs(target_1 - entry_reference)
reward_risk    = planned_reward / planned_risk
```

`reward_risk < 2` 拒绝。

为了避免 next-bar gap 把合法 signal 变成不合法交易，必须计算保持 `minimum_reward_risk=r` 的最大/最小可接受成交价：

```text
boundary = (target_1 + r * stop) / (1 + r)
LONG  : next_open <= boundary 且 next_open > stop
SHORT : next_open >= boundary 且 next_open < stop
```

超出边界取消 intent，reason=`ENTRY_GAP_INVALIDATED`。Reference quantity 应按最不利 admissible price 计算，确保允许范围内成交不会因 gap 静默突破 planned risk cap。

## 10. Instrument / Account Facts

策略 Kernel 不拥有交易所主数据来源，只消费明确提供的 facts：

```text
InstrumentExecutionFacts(
    contract_multiplier,
    price_tick | None,
    estimated_round_trip_cost,
    available_cash,
    margin_required_per_contract | None,
)
```

- Historical Replay：contract multiplier 优先来自项目 Catalog/已验证 reference；V1 reference cost 排除、reference margin check 关闭，并在输出标记 `reference_execution=true`。主图 marker 不冒充真实撮合/PnL。
- RQAlpha：使用 Bundle/instrument/account 的 multiplier、费用、保证金和 available cash，不从 Historical Replay 的 reference assumption 继承。
- 任一 consumer 不能猜 multiplier。

基础 planned quantity：

```text
risk_cash = account_equity × base_risk_fraction
per_contract_risk = abs(admissible_worst_price - stop) × contract_multiplier
                    + estimated_round_trip_cost
qty_by_risk = floor(risk_cash / per_contract_risk)
```

若 consumer 提供受信任 margin facts，再取 `min(qty_by_risk, qty_by_margin)`；Historical reference replay 不做虚假的历史保证金精确模拟。

整个 Episode 任一新 action 前都要重算 planned worst-case risk，不能超过 `account_equity × 1%`。

## 11. Trade Episode 与 Position Management

每次 ENTRY 创建唯一 `episode_id`，至少保存：

```text
episode_id
initial_source_event_ids
primary_setup
supporting_setups
direction
contract
trading_day
segment_start_trading_day
initial_entry
current_qty
weighted_average_cost
protective_stop
target_1
add_count
partial_profit_taken
realized_pnl
consumed_source_event_ids
```

同一 source event 不能在一个 Episode 中重复产生 action。

### 11.1 首次部分止盈

V1 completed-bar target rule：

- LONG completed 1m close >= `target_1`；SHORT <= `target_1` 时产生 `REDUCE_INTENT`；
- 下一可执行 same-segment Bar open reference fill；
- `take_qty=floor(current_qty×0.40)`；0 手则不制造 action；
- 实际 reference/RQAlpha fill 后才置 `partial_profit_taken=true`；
- 保护位提高到当前 weighted average cost；
- `target_1` 只执行一次。

40% 是 JM V1 确定性适配。书中第二目标减仓示例暂不机械化为通用 target_2，避免把示例误当固定公式。

### 11.2 盈利加仓

ADD 必须由**新的、未消费的同方向 `jdj_trend_follow_1m_candidate_v1` 完整 trigger event**驱动，不使用一个更宽松、另起炉灶的“碰 EMA20 就加仓”公式。

同时要求：

- `partial_profit_taken=true`；
- Episode realized PnL > 0；
- `add_count < 2`；
- `add_qty=floor(current_qty×0.25) >= 1`；
- next-open entry bound、episode risk、margin gates 重新通过。

ADD fill 后：`add_count += 1`，保护位提高到 post-fill weighted average cost。第三次及以后不加；亏损/摊低成本加仓永久禁止。

### 11.3 Exit

V1 completed-bar exit decision：

- LONG close <= protective stop / SHORT close >= protective stop；
- LONG close <= EMA20 / SHORT close >= EMA20；
- strict-prior 5m N trend 不再支持当前方向；
- daily stop；
- session terminal guard；
- segment identity 即将切换且仍有仓位。

除 session terminal special case 外，completed-bar exit 在下一可执行 Bar open 执行。V1 不声称能模拟书中盘中 hard-stop 的精确触发价；这是一项显式研究适配。

## 12. Daily Risk

每个 `trading_day` 记录 `start_equity`。V1 使用 completed-Bar mark-to-market equity：

```text
drawdown = max(0, (start_equity - current_equity) / start_equity)
```

- `drawdown > 0.5%`：禁止 Entry/Add **15 个后续 completed in-session 1m Bars**；用 Bar 计数而非 wall-clock，午间/夜盘休市不消耗暂停时长；已有仓位继续被管理。
- `drawdown >= 1%`：原作者语义为停止当天继续交易；JM V1 额外采用保守适配 `DAILY_STOP_EXIT`，产生退出 intent 并在下一可执行 Bar open 平掉剩余 reference/RQAlpha exposure，同时本 trading day 永久禁止 Entry/Add。
- 新 trading day 重置 pause/stop；不跨主力 segment 传播。

美股 opening-profit 40% giveback guard 在 JM V1 中保持 disabled。

## 13. Session Terminal Guard

因为 V1 统一使用 next-bar execution，不能等 trading day 最后一根 Bar 完成后再决定“日内清仓”。

Historical Replay 必须从已验证的 TradingSession/实际 Bar identity 得到该 trading day 的 terminal executable 1m Bar。Profile：

```text
terminal_flatten_lead_bars = 1
no_new_entry_lead_bars     = 1
```

规则：

- 当当前 completed Bar 之后只剩 1 根本 trading_day、same-segment 可执行 Bar 时，禁止新 Entry/Add；
- 有持仓则产生 `SESSION_FLATTEN` intent，在最终可执行 Bar open 完成 reference close；
- 休市间隔（夜盘→日盘、10:15、11:30）不是 trading_day terminal，不触发 flatten；
- terminal identity 不可解析时 fail-closed，不允许“可能隔夜”。

RQAlpha adapter 不能自行猜 15:00；运行前的 identity schedule 必须携带该 trading day 的 terminal execution identity。

## 14. Historical Reference Replay Fill Model

主图是 `Historical Strategy Replay`，不是历史真实成交、不是 RQAlpha fill。

统一规则：

- ENTRY/ADD/REDUCE/普通 EXIT decision：下一根 same-trading-day、same-segment Bar open；
- Entry/Add next open 必须重新通过 admissible price/risk gate；
- decision 后无下一根合法 Bar：intent 取消并记录 typed reason；
- 不使用 Bar high/low 猜 stop 与 target 谁先成交；
- 不存在 `INTRABAR_ORDER_AMBIGUOUS`；
- session terminal flatten 按第 13 节提前一 Bar 决策。

输出至少保存 `decision_at`、`effective_at`、`reference_fill_price`、physical contract、segment identity 与 `reference_execution=true`。

## 15. Streaming Parity Gate

Historical Research/Replay 可以批量评估，但 RQAlpha `handle_bar` 是流式消费。进入 RQAlpha adapter 前必须实现 `JdjStreamingEvaluator`：

```text
push(completed_1m_bar, optional_completed_5m_bar)
→ zero or more Candidate/Strategy decisions
```

要求：

- EMA20 state、N swing/pattern/structure state、JDJ setup armed state 在同一 physical segment 内持续；
- trading day 只重置 JDJ day-scoped state/Execution state，不得错误重置 N/EMA segment state；
- physical segment change 全量 reset；
- strict-before 与 batch 完全一致；
- 同一 frozen segment 逐 Bar push 的 Candidate projection 必须与 batch reducers 逐事件一致；
- 禁止每个 Bar 从 segment start 重算全历史作为正式实现。

Streaming parity 未通过时，RQAlpha adapter Gate 为 `BLOCKED`。

## 16. RQAlpha Identity Schedule 与 Adapter

RQAlpha Bundle 提供价格、Bar、撮合、费用、保证金和模拟账户。归一量化只提供经过现有 Historical read path 验证的非价格 identity schedule。

运行前生成：

```json
{
  "schema_version": 1,
  "strategy_id": "jdj_intraday_futures_v1",
  "profile_id": "jdj_jm_1m_v1",
  "symbol": "jm",
  "series_kind": "actual_dominant",
  "mapping_source": "MarketDataService/ActualDominantResearchSegmentLoader",
  "trading_day_start": "YYYY-MM-DD",
  "trading_day_end": "YYYY-MM-DD",
  "days": {
    "YYYY-MM-DD": {
      "contract": "JMxxxx",
      "terminal_bar_end": "<offset-aware ISO datetime>"
    }
  }
}
```

可另存 artifact creation time / repository commit 到 run metadata；不把 nondeterministic timestamp 混入 schedule semantic identity。

要求：

- schedule 由 `MarketDataService` / `ActualDominantResearchSegmentLoader` 解析结果生成，不直接查表自行选主力；
- 只要求存在于实际 trading-day coverage 的日期，非交易日不创建伪 row；
- schedule 不含 OHLCV、Canonical file path、DB URL 或凭据；
- Bundle 当前 contract 与 schedule identity 不一致时拒绝 action；
- schedule coverage 缺失/冲突 fail-closed：`DOMINANT_SCHEDULE_INCOMPLETE`；
- RQAlpha adapter 把 Bundle Bar 转为内存 domain Bar，送入已通过 parity 的 streaming evaluator；不得复制 EMA/N/JDJ 公式；
- 回测固定 `frequency=1m`、`matching_type=next_bar`、`signal=false`；
- RQAlpha 公共 OrderStyle 只依赖 Market/Limit/TWAP/VWAP 能力，V1 不假设不存在的原生 stop order；
- 结果继续 `research_only=true`、`formal_evidence=false`、`promotion_eligible=false`。

当前 `services/quant-api/app/backtest/` 尚不存在时，RQAlpha adapter implementation 必须等待已批准的 Workbench Plan 先实现，不能在本任务里顺手另建第二套工作台。

## 17. Strategy Events 与 Attribution

Kernel 至少输出：

```text
ENTRY
ADD
REDUCE
EXIT
REJECTED_CANDIDATE
DAILY_PAUSE
DAILY_STOP
```

Action Event 至少包含：

```text
event_id
episode_id
profile_id
strategy_version
source_event_ids
primary_setup
supporting_setups
direction
contract
trading_day
segment_start_trading_day
decision_at
effective_at
price
qty
position_qty_after
stop_price
target_price
planned_risk_fraction
reward_risk
reason
reference_execution
```

RQAlpha completed episode attribution另外保存 gross/cost/net PnL、return_R、MFE_R、MAE_R、holding_bars；Historical主图不重新发明 RQAlpha PnL 计算器。

## 18. Market Web 与周期切换

新增独立 overlay：`日进斗金策略`，与现有 JDJ Candidate Overlay 分开。

V1 capability：

- `jm + actual_dominant + 1m`：支持 `jdj_jm_1m_v1`；
- 其他 symbol/frequency：明确“该品种/周期尚未验证”，清除旧 marker；
- 未来只有后端 Profile Registry 声明 accepted profile 后才开放对应周期；
- Web 不计算 EMA、N、R:R、stop、仓位或 PnL。

Marker：ENTRY `▲/▼`、ADD `＋`、REDUCE `－`、EXIT `×`。Hover 显示 episode/setup、contract、decision/effective time、qty、stop、target、R:R、reason 与 reference 标识。

## 19. Stable Fail-Closed Codes

至少包括：

```text
JDJ_STRATEGY_PROFILE_UNAVAILABLE
JDJ_STRATEGY_CONTEXT_INVALID
JDJ_STRATEGY_INSTRUMENT_SPEC_UNAVAILABLE
JDJ_STRATEGY_TARGET_UNAVAILABLE
JDJ_STRATEGY_REWARD_RISK_TOO_LOW
JDJ_STRATEGY_ENTRY_GAP_INVALIDATED
JDJ_STRATEGY_POSITION_SIZE_ZERO
JDJ_STRATEGY_RISK_LIMIT_EXCEEDED
JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID
JDJ_STRATEGY_SESSION_IDENTITY_INVALID
JDJ_STRATEGY_STREAMING_PARITY_REQUIRED
DOMINANT_SCHEDULE_INCOMPLETE
```

source unavailable、future fact、identity drift、unsupported profile 都不得静默降级。

## 20. 测试与验收

### 20.1 Golden Formula Parity

迁移前先把 current N/JDJ output 投影为 primitive golden facts；迁移后比较 projection，禁止比较 old/new 不同 class identity：

- N pivot/snapshot ids、epoch、kind、time、price；
- JDJ event/count/id/candidate/source kind/direction/observed_at/trigger level；
- ambiguous/invalidated/expired counts；
- strict-before、day reset、physical-segment boundary。

### 20.2 Execution

必须覆盖：

- R:R <2 / target unavailable reject；
- admissible entry boundary 与 gap reject；
- 0.5% base risk、1% planned Episode cap；
- Episode/source-event 去重；
- 40% reference first reduce；
- Add 必须来自新的完整 Trend Follow trigger；
- first/second add、third reject、losing add reject；
- protective stop move；
- 0.5% pause=15 completed in-session 1m bars；
- 1% stop + JM V1 exit adaptation；
- terminal guard；
- no intrabar favorable fill assumption。

### 20.3 Historical Replay

证明：actual_dominant only、segment warm-up、no cross-contract state、decision<effective、prefix invariant、event id stable、unsupported profile fail-closed。

### 20.4 Streaming

对同一 frozen physical segment：batch vs streaming Candidate output逐事件一致；跨 trading day 不错误重置 EMA/N；segment change 必须 reset。

### 20.5 RQAlpha Fake Adapter

真实 Bundle smoke 前至少证明：identity schedule 完整性、next_bar、no signal mode、Bundle-only prices、no duplicated formulas、research-only metadata、unsupported/missing schedule fail-closed。

## 21. Canonical Closeout

实现收口时按实际完成范围更新：

- `PROJECT_SOURCE.md`：区分 Candidate Research、Historical Strategy Replay、local RQAlpha backtest；
- `AGENTS.md`：收窄“无策略/回测入口”的绝对表述，继续禁止真实订单和自动晋升；
- `docs/ARCHITECTURE.md`：增加 Shared Kernel 单向依赖；
- `DECISIONS.md`：记录“公式唯一 Shared Kernel”与 reference/RQAlpha fill 分层；
- `docs/RQALPHA_RESEARCH_BACKTEST.md`：只允许 validated dominant/session identity schedule bridge，仍禁止 Canonical OHLCV 进入 runner；
- `TESTING.md`：增加 parity/replay/streaming/Web/fake adapter 命令。

`STATUS.md` 不在普通实现提交中提前宣布 Ready。

## 22. 禁止范围

V1 不做：

- 苏冰、HTDY 或其他策略适配；
- JDJ 书中其他 Entry setup；
- 参数优化、网格/Bayesian search；
- 其他品种或周期；
- Portfolio/multi-product allocation；
- OOS 自动消费、Candidate 自动晋升/淘汰；
- Alert、PushPlus、Execution Review、Runtime；
- main/tag/release、真实订单、真实账户。

## 23. 完成定义

只有同时满足以下条件才可声明本 Spec 实现完成：

1. N/JDJ 公式只有一个 active Shared Kernel definition；
2. frozen Candidate golden parity 全通过；
3. `jdj_jm_1m_v1` Episode/entry/risk/add/reduce/exit/session/daily-risk lifecycle 自动化通过；
4. JM actual_dominant Historical Reference Replay 可独立显示在主图；
5. unsupported profile 明确 unavailable；
6. streaming evaluator 与 batch parity 通过；
7. 在 RQAlpha Workbench prerequisite 已存在时，adapter 才可使用同一 streaming Kernel 与 validated identity schedule；
8. 无 Canonical/DB/Redis/Alert/Runtime 写入；
9. 未获得单独执行意图前不运行真实 RQAlpha Bundle smoke；
10. 所有结果保持 research-only，不产生正式 OOS、promotion 或交易结论。
