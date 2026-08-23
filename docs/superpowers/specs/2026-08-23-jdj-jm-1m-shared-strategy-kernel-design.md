# 日进斗金 JM 1m Shared Strategy Kernel 设计

更新时间：2026-08-23
状态：正式 Strategy Spec；仅授权后续代码实现设计，不授权真实 RQAlpha 回测、Runtime、通知、main/tag 或任何正式数据写入

## 1. 目标

本 Spec 将现有 `jdj_1m_v1` 从“只读 Candidate Research”扩展为第一套完整、可复算、可在多种消费者之间复用的交易策略语义，同时保持现有 JDJ/N 因果公式不变。

第一版只落地：

```text
strategy_id = jdj_intraday_futures_v1
profile_id  = jdj_jm_1m_v1
symbol      = jm
series_kind = actual_dominant
execution   = 1m
trend       = 5m
```

同一套 Strategy Kernel 必须服务三个消费者：

1. 现有 JDJ Candidate Research；
2. Canonical actual_dominant Historical Strategy Replay / Market 主图；
3. RQAlpha Plus research-only 回测 adapter。

本阶段不证明策略盈利、有效、可交易、OOS-ready 或可晋升。

## 2. 事实来源与优先级

实现发生冲突时按以下顺序解释：

1. 仓库 active canonical：`STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`；
2. 当前冻结的 JDJ/N 代码与 exact policy：`services/quant-api/app/research/jdj/**`、`services/quant-api/app/research/n_structure/**`、`data/research_policies/jdj_1m_policy_v1.json`；
3. 本 Spec；
4. 《股票日内交易入门》作为交易管理原始依据；
5. RQAlpha 只负责市场数据、撮合、费用和模拟账户，不定义 JDJ 公式。

《股票日内交易入门》本次采用的确定性规则主要来自：

- 书页 28～33：入场前必须明确止损和潜在盈利，作者一般只做盈亏比高于 2:1 的交易；
- 书页 34～37：单笔交易最大风险不超过账户总资金 1%，仓位由“总风险 / 单位风险”和资金约束共同决定；
- 书页 134～140：只能在行情向持仓有利方向发展后增加仓位，亏损仓禁止摊平；盈利且已部分止盈后，前两次有效回到 20MA 可分别增加当前持仓的 1/4，第三、第四次不再加；加仓后保护位提高到当前成本附近；
- 书页 141～143：当天账户亏损超过 0.5% 暂停 15 分钟，达到 1% 后停止当天继续交易。

书中基于美股开盘/上午/下午/收盘时段的“开盘盈利回吐 40%”规则不直接迁移到焦煤 V1，因为国内期货 session 结构不同。

## 3. 关键架构决策

采用方案 B：把 N Structure 和 JDJ 的纯因果逻辑下沉为共享 Strategy Kernel。

```text
Canonical bars / RQAlpha bars
            ↓
      Shared N Kernel
            ↓
     Shared JDJ Facts
            ↓
   Shared JDJ Setup Engine
            ↓
   JDJ Execution Kernel
       ├── Research Candidate projection
       ├── Historical Strategy Replay
       └── RQAlpha Adapter
```

硬约束：

- 不建立通用 `StrategyBase`、插件框架、Portfolio Engine、参数优化平台或自动晋升系统；
- 不复制 JDJ/N 公式到 Web 或 RQAlpha 文件；
- Strategy Kernel 不依赖 FastAPI、SQLAlchemy、RQAlpha、Redis、Alert、Execution Review 或 Runtime；
- Research 可以依赖 Strategy Kernel，Strategy Kernel 不得反向依赖 `app.research.*`；
- RQAlpha adapter 只能翻译 Strategy Kernel 的 decisions 与 fills，不得重新计算第二套 JDJ 公式。

## 4. 模块边界

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
    └── engine.py
```

`app/research/n_structure/**` 与 `app/research/jdj/**` 只保留 research request、outcome、validation、robustness、report 和 orchestration；最终不得保留第二份公式实现。

迁移过程中允许短暂存在纯 re-export compatibility shim，但同一实现任务完成前必须清除内部引用并删除 shim，确保公式只有一个 active definition。

## 5. 现有 Entry 语义必须原样保持

`jdj_jm_1m_v1` 第一版只启用当前已经工程化的三条 Setup：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

必须保持当前 `jdj_1m_policy_v1` 的以下语义完全不变：

- source timeframe = `1m`；
- trend context timeframe = `5m`；
- EMA20 使用现有 seed/rounding/input 规则；
- 5m N Structure 使用 strict-before context；
- same trading day / same physical contract / same rank1 segment；
- previous-bar dynamic trigger；
- equal 不视为突破；
- Trend Follow reaction / invalidation；
- Trend Reentry 6 excursion / reclaim / first-reaction 语义；
- Key Level first-break 不追、等待 retest、same-pivot single episode；
- existing event identity、`observed_at`、direction、trigger level 不变。

Shared Kernel 重构前后，同一输入必须得到逐事件完全一致的 Candidate output。

## 6. Profile Registry 与周期切换

完整策略公式与“某个品种/周期的落地参数”分开。

```text
JdjStrategyPolicy
    定义策略通用规则

JdjStrategyProfile
    定义 symbol / frequency / context frequency / execution adaptations
```

第一版唯一 accepted profile：

```text
profile_id                    = jdj_jm_1m_v1
symbol                        = jm
series_kind                   = actual_dominant
execution_frequency           = 1m
trend_context_frequency       = 5m
stop_buffer_ticks             = 1
base_risk_fraction            = 0.005
max_episode_risk_fraction     = 0.01
minimum_reward_risk           = 2.0
first_profit_take_fraction    = 0.40
add_fraction_of_current_qty   = 0.25
max_add_count                 = 2
daily_pause_drawdown_fraction = 0.005
daily_pause_minutes           = 15
daily_stop_drawdown_fraction  = 0.01
opening_profit_giveback_guard = disabled
```

其中：

- `max_episode_risk_fraction=1%`、`minimum_reward_risk=2`、两次 1/4 盈利加仓、0.5%/1% 日风险规则来自原始体系；
- `base_risk_fraction=0.5%`、`stop_buffer_ticks=1`、第一次结构目标减仓 40% 是 JM V1 的工程适配，用于给最多两次盈利加仓保留风险空间并形成确定性的部分止盈；
- 这些适配值不得被描述成作者唯一原始参数。

未来切换到 5m/15m/其他周期时必须新增 versioned profile，例如 `jdj_jm_5m_v1`。不得根据 1m 参数自动乘除倍率，也不得在没有 accepted profile 时显示该周期“已支持”。

## 7. Historical 数据合同

Market 主图和 Historical Strategy Replay 使用项目正式 Historical 事实链：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ physical-contract rank1 segments
→ Shared Strategy Kernel
```

要求：

- `actual_dominant` 只由 `MainContractMap rank=1` 的有效区间拼接；
- 不读取 continuous 代替真实主力；
- 不跨 physical contract 传播 EMA、N Structure、Candidate、仓位、止损或 Daily Risk 状态；
- segment identity 缺失、重叠或 coverage 不完整时 fail-closed；
- 历史 replay 不写 Canonical、DB 或 Redis。

JDJ V1 在每个 physical-contract segment 独立计算；交易日改变时重置 candidate day-state 和 daily-risk state。持仓不得跨 `trading_day` 最终边界。

## 8. RQAlpha 数据合同

RQAlpha 的价格、Bar、撮合、手续费、滑点、保证金和模拟账户均来自 RQAlpha Bundle。

为保证主图和回测使用同一个“当天主力合约身份”，JDJ RQAlpha run 允许一个窄的只读 bridge：

```text
MainContractMap / actual_dominant mapping
→ dominant_schedule.json
→ RQAlpha adapter
```

边界：

- schedule 只含 `trading_day → physical_contract` identity，不含 Canonical OHLCV；
- RQAlpha runner 不读取 Canonical Bar；
- RQAlpha 只交易 schedule 指定的 physical contract；
- schedule 任一 requested trading day 缺失或冲突时 run fail-closed：`DOMINANT_SCHEDULE_INCOMPLETE`；
- RQAlpha Bundle 与 Canonical Bar 有差异时不得强行对齐价格；两种结果分别标注 data source；
- 该 bridge 不改变“RQAlpha 结果为 research-only”的定位。

因此 `docs/RQALPHA_RESEARCH_BACKTEST.md` 实现收口时必须把“完全不接触 Canonical”收窄为“JDJ adapter 仅可只读消费 dominant identity schedule，不读取 Canonical price bars”。

## 9. Strategy Candidate → Entry Authorization

Candidate 并不自动等于交易。

每个 Candidate 依次经过：

```text
Candidate
→ conflict check
→ stop resolver
→ target resolver
→ reward:risk gate
→ daily risk gate
→ position sizing
→ ENTRY_INTENT
```

### 9.1 同 Bar 冲突

- 同方向多个 Setup：只允许一个 entry intent；attribution 固定为 `key_level_breakout > trend_reentry_6 > trend_follow`，其他同方向 Setup 记录为 supporting setups；该优先级只用于归因，不代表排名或强弱；
- 同 Bar 同时出现 LONG 与 SHORT：拒绝交易，reason=`AMBIGUOUS_DIRECTION`。

### 9.2 Stop Resolver

所有 stop 都只使用 decision time 已知事实：

- Trend Follow LONG：reaction bar low 下方 `1 tick`；SHORT：reaction bar high 上方 `1 tick`；
- Trend Reentry 6 LONG：frozen excursion extreme 下方 `1 tick`；SHORT：上方 `1 tick`；
- Key Level Breakout LONG：frozen key level 下方 `1 tick`；SHORT：上方 `1 tick`。

若 stop 与 entry reference 方向错误、距离为零或 InstrumentSpec 缺失，拒绝 Candidate。

### 9.3 Target Resolver

V1 不预测未来目标价，也不使用未来 pivot。

Decision time 可用 target candidates 只有：

1. 同 physical-contract segment 内、在 decision time 已 confirmed 的 5m N pivots；
2. 当前 trading day 截至 decision bar 已知的 1m session high / low。

LONG 只使用高于 entry reference 的已知 level；SHORT 只使用低于 entry reference 的已知 level；选择距离 entry 最近的 level 作为 `target_1`。

若没有已知 forward level，拒绝 Candidate：`TARGET_UNAVAILABLE`。

### 9.4 Reward/Risk

Entry reference 使用 Candidate `observation_close`。

```text
planned_risk   = abs(entry_reference - stop_price)
planned_reward = abs(target_1 - entry_reference)
reward_risk    = planned_reward / planned_risk
```

`reward_risk < 2` 时拒绝 Candidate：`REWARD_RISK_TOO_LOW`。

真实 RQAlpha fill 或 replay next-bar-open 可能发生 gap，因此 1% 是 planned risk hard cap，不伪造为真实最大损失保证；run 必须记录 realized fill risk 与 planned risk 的差异。

## 10. Position Sizing

所有数量为整数手，金额、价格、PnL、风险和费用使用 `Decimal`。

需要受信任的：

```text
InstrumentSpec(
    price_tick,
    contract_multiplier,
    margin_requirement,
)
```

InstrumentSpec 缺失时不得猜 JM 合约乘数或 tick，直接 fail-closed。

基础仓位：

```text
risk_cash = account_equity × base_risk_fraction
per_contract_risk = abs(entry_reference - stop_price)
                    × contract_multiplier
                    + estimated_round_trip_cost
qty_by_risk = floor(risk_cash / per_contract_risk)
qty_by_margin = floor(available_cash / margin_requirement)
base_qty = min(qty_by_risk, qty_by_margin)
```

`base_qty < 1` 则拒绝交易。

整个 episode 在任何新 action 前都要重新计算 planned worst-case risk；超过 `account_equity × 1%` 时不得开新仓或加仓。

## 11. Position Management

### 11.1 部分止盈

`target_1` 首次被成交后：

- `take_qty = floor(current_qty × 0.40)`；
- `take_qty == 0` 时不制造虚假的 1 手减仓；
- 实际完成至少 1 手盈利减仓后，`partial_profit_taken=true`；
- protective stop 提高到当前 weighted average cost；
- target_1 不重复执行。

40% 是 `jdj_jm_1m_v1` 的确定性适配，不宣称为作者唯一固定比例。

### 11.2 盈利加仓

只有同时满足以下条件才允许 ADD：

- 当前仓位方向与 trend context 相同；
- `partial_profit_taken=true`；
- 当前 episode 已有正 realized profit；
- 新出现一次有效 EMA20 reaction；
- `add_count < 2`；
- `add_qty = floor(current_qty × 0.25) >= 1`；
- 加仓后 planned episode risk 仍 <= 1%；
- 可用保证金充足。

完成 ADD 后：

- `add_count += 1`；
- protective stop 更新为最新 weighted average cost；
- 第三次及以后 EMA20 reaction 不再加仓；
- 亏损仓、负 realized episode、为了降低成本的加仓一律禁止。

### 11.3 Full Exit

任一条件成立即退出剩余仓位：

- resting protective stop 被触发；
- LONG 1m close <= EMA20 / SHORT 1m close >= EMA20；
- 5m N trend 不再支持当前方向；
- daily stop 被触发；
- trading_day 最终边界到达；
- physical-contract segment 将切换且仍有未平仓位。

Trend/structure exit 是 completed-bar decision，最早在下一可执行 Bar 生效；已存在的 stop order 可以在 Bar 内触发。

## 12. Daily Risk

每个 trading day 记录 `start_equity`，daily drawdown 使用 mark-to-market equity：

```text
daily_drawdown = max(0, (start_equity - current_equity) / start_equity)
```

规则：

- `daily_drawdown > 0.5%`：禁止新 Entry/Add 15 trading minutes；已有仓位仍执行 stop/exit 管理；
- `daily_drawdown >= 1%`：立即产生 `DAILY_STOP_EXIT`，退出剩余仓位，并禁止该 trading day 后续 Entry/Add；
- 新 trading day 重置 pause/stop；
- 1% 不是对 gap/涨跌停情况下真实损失的保证，只是策略决策阈值。

美股 opening-profit 40% giveback guard 在 JM V1 中明确 `disabled`。

## 13. Historical Replay Fill Model

主图显示的是 `Historical Strategy Replay`，不是 RQAlpha fill，也不是历史真实成交。

Replay 使用确定性 reference fill：

- completed-bar Entry/Add/Trend-Exit decision → 下一根 same-segment Bar `open`；
- 若 decision 后没有下一根 same-segment Bar，intent 取消；
- resting LONG stop：若下一 Bar `open <= stop`，按 open；否则 low <= stop 时按 stop；SHORT 对称；
- resting profit target：若下一 Bar open 已越过 target，按 open；否则 Bar range 触达 target 时按 target；
- 同一 Bar 同时触达 stop 与 target 且无法确定先后时，fail-closed 使用不利顺序：先 stop，并记录 `INTRABAR_ORDER_AMBIGUOUS`；不得用最优顺序。

Replay 输出必须同时保存：

```text
decision_at
effective_at
reference_fill_price
physical_contract
segment_start_trading_day
```

## 14. Strategy Events 与主图 Projection

Strategy Kernel 至少输出：

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
```

Web 主图只渲染 `ENTRY/ADD/REDUCE/EXIT`：

```text
▲ / ▼  Entry
＋      Add
－      Reduce
×       Exit
```

Hover 显示 setup、contract、decision/effective time、qty、stop、target、R:R 和 reason。

Candidate Overlay 与 Strategy Replay Overlay 在 V1 中继续分开，直到长期验证确认二者身份边界稳定；不得把 Strategy marker 伪装为现有 Candidate marker。

## 15. Web 周期切换

Market chart 增加独立 overlay：`日进斗金策略`。

行为：

- 当前 `symbol=jm + series_kind=actual_dominant + frequency=1m`：允许请求 `jdj_jm_1m_v1`；
- 其他 symbol/frequency：显示“该品种/周期尚未验证”，不自动降级到 1m、不跨频计算、不隐藏错误后继续显示旧 marker；
- 未来新增 profile 后，Web 只根据后端 Profile Registry 声明的 accepted capability 开放对应周期；
- 浏览器只负责 marker 渲染，不计算 EMA、N、Entry、仓位、止损或 PnL。

## 16. RQAlpha Adapter

RQAlpha adapter 只做四件事：

1. 从 Bundle 取得 1m/5m Bar、instrument、account、cost/fill facts；
2. 按 `dominant_schedule.json` 选择当天 physical contract；
3. 将 Shared Strategy Kernel decisions 转成 RQAlpha future orders；
4. 将 RQAlpha fills/account state 回灌为 Strategy execution facts，并输出 attribution。

禁止：

- 在 strategy file 中复制 N/JDJ 公式；
- 让 RQAlpha 自行选择一个与 MainContractMap 不同的 dominant identity；
- 读取 Canonical OHLCV 代替 Bundle 数据；
- signal mode、自动交易、真实账户、通知或 Runtime 接入。

RQAlpha run 继续满足 local-only、research-only 工作台合同。

## 17. 回测 Attribution

每个 completed episode 至少输出：

```text
profile_id
physical_contract
trading_day
primary_setup
supporting_setups
signal_time
entry_time
entry_price
initial_stop
initial_risk_R
add_count
reduce_count
exit_time
exit_price
exit_reason
gross_pnl
cost
net_pnl
return_R
MFE_R
MAE_R
holding_bars
```

第一轮 baseline 不做参数 sweep、自动 rank、winner、KEEP/DROP/PROMOTE。

## 18. 错误和 Fail-Closed

稳定错误至少包括：

```text
JDJ_STRATEGY_PROFILE_UNAVAILABLE
JDJ_STRATEGY_CONTEXT_INVALID
JDJ_STRATEGY_INSTRUMENT_SPEC_UNAVAILABLE
JDJ_STRATEGY_TARGET_UNAVAILABLE
JDJ_STRATEGY_REWARD_RISK_TOO_LOW
JDJ_STRATEGY_POSITION_SIZE_ZERO
JDJ_STRATEGY_RISK_LIMIT_EXCEEDED
JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID
DOMINANT_SCHEDULE_INCOMPLETE
INTRABAR_ORDER_AMBIGUOUS
```

Source unavailable、identity drift、未来事实、跨合约状态、unsupported profile 都不得静默回退。

## 19. 测试与验收

### 19.1 Formula parity

Shared Kernel 重构前后，对冻结 fixtures 必须逐项一致：

- N snapshots/pivots；
- JDJ event count；
- event id；
- candidate id / source event kind；
- direction；
- observed_at；
- trigger level；
- ambiguous / invalidated / expired counts。

覆盖 Trend Follow、Trend Reentry 6、Key Level Breakout、failed reaction、failed retest、same-bar ambiguity、strict-before、trading-day reset、physical-contract boundary。

### 19.2 Execution kernel

必须覆盖：

- R:R < 2 reject；
- target unavailable reject；
- 0.5% base sizing 与 1% hard cap；
- multiplier/tick missing fail；
- target1 40% reduce；
- 无实际盈利减仓不得 add；
- first/second 20MA add；
- third add reject；
- losing-position add reject；
- protective stop moved to weighted cost after add；
- daily 0.5% pause；
- 15 trading-minute resume；
- daily 1% stop；
- segment/trading-day reset；
- stop/target same-Bar ambiguous uses adverse ordering。

### 19.3 Historical Replay

必须证明：

- 只通过 actual_dominant physical segments；
- 不跨 contract 传播状态；
- decision_at 不晚于 effective_at；
- completed-bar decision 不回标；
- prepend/pagination 重算结果 prefix-invariant；
- same input 重跑 event identities 稳定。

### 19.4 Web

必须覆盖：

- `jm + 1m` 显示 strategy overlay；
- 5m/15m 等没有 profile 时明确 unavailable；
- overlay identity 改变时旧 markers 清除；
- prepend 去重；
- marker hover attribution；
- Candidate 和 Strategy overlay 不混淆。

### 19.5 RQAlpha

在真实 smoke 之前，自动化至少证明：

- strategy registry 只注册 `jdj_intraday_futures_v1` accepted profile；
- fixed runner config 禁止 signal/auto-update；
- dominant schedule validation fail-closed；
- strategy adapter import Shared Kernel 而不是复制公式；
- result attribution 与 run.json 标记 `research_only=true`、`formal_evidence=false`、`promotion_eligible=false`。

## 20. Canonical Closeout

代码实现通过后，同一变更更新存在真实冲突的 active canonical：

- `PROJECT_SOURCE.md`：区分 JDJ Candidate、JDJ Historical Strategy Replay 与 local-only RQAlpha research backtest；
- `AGENTS.md`：把“当前不存在策略/回测入口”的绝对表述收窄，并继续禁止正式交易和自动晋升；
- `docs/ARCHITECTURE.md`：增加 Shared Strategy Kernel 依赖方向；
- `DECISIONS.md`：记录“公式只存在 Shared Kernel；Research/Replay/RQAlpha 为消费者”的长期决策；
- `docs/RQALPHA_RESEARCH_BACKTEST.md`：允许 JDJ adapter 只读消费 dominant identity schedule，不允许读取 Canonical Bar；
- `TESTING.md`：增加 parity、strategy replay、Web 和 fake RQAlpha adapter 命令。

`STATUS.md` 不在普通实现提交中提前宣布 Ready；只有形成明确 develop RC / release 状态时再按其职责更新。

## 21. 禁止范围

V1 明确不做：

- 苏冰、HTDY 或其他策略适配；
- JDJ 书中 VWAP、ABC、三角形、Camarilla、Trap 等其他 Entry setup；
- 参数优化、网格搜索、Bayesian optimization；
- 其他品种或其他周期；
- Portfolio、多品种资金分配；
- OOS 自动消费、Candidate 晋升或自动淘汰；
- Alert、PushPlus、Execution Review、Runtime；
- main/tag/release、真实订单或任何账户连接。

## 22. 完成定义

本 Spec 的实现只有同时满足以下条件才可声明完成：

1. N/JDJ 公式已只有一个 active Shared Kernel definition；
2. 原 Candidate Research parity 全通过，无公式漂移；
3. `jdj_jm_1m_v1` 完整执行生命周期自动化通过；
4. JM actual_dominant Historical Replay 可在主图独立显示；
5. unsupported frequency 显式 unavailable；
6. RQAlpha adapter 使用同一 Kernel 和 dominant schedule identity；
7. 无 Canonical/DB/Redis/Alert/Runtime 写入；
8. 真实 RQAlpha smoke 尚未获得单独执行意图时保持未执行；
9. 所有结果继续是 research-only，不产生正式 OOS、promotion 或交易结论。
