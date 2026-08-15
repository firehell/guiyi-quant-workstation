# Execution Review V1 — 苏冰信号执行与复盘闭环设计

> 状态：Design Approved / Implementation Not Started  
> 日期：2026-08-15  
> 当前基线：`develop`，当前正式 release 为 `v1.3.1`  
> 当前生产事实：Alert V2 的 `htdy_original_15m` 与 `subing_entry_signal_v1` Scope 均精确为 `jm`；SuBing Natural Canary 仍 pending  
> 事实源：`STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`、`docs/CODE_REVIEW.md`、`TESTING.md`

## 1. Purpose

Execution Review V1 是 `v1.3.x` Decision Compression / Alert V2 之后的下一条个人核心闭环。

`v1.3.x` 已解决：

```text
可信行情
→ completed Live Bar
→ SuBing Formal Signal
→ AlertEvent
→ WeCom / Market persistent fact
→ 机会主动找用户
```

V1.4 目标是继续解决：

```text
AlertEvent
→ 人工判断
→ 已执行 / 未执行
→ 实际执行过程
→ 交易结束
→ 结构化复盘
→ 轻量执行统计
```

项目价值不是建设一个通用交易平台，而是让系统替用户持续盯盘，并把用户面对机会时的真实决策和执行积累为可复盘、可统计、未来可供 AI 辅助研究的个人数据资产。

本模块直接满足当前 `PROJECT_SOURCE.md` 的功能价值 Gate：

- 提高人工观察与研究执行的一致性；
- 增加未来复盘研究的证据；
- 间接降低盘中记录和事后回忆成本。

因此值得作为长期模块维护。

## 2. Product Boundary

Execution Review V1 不是旧 Review Center 的恢复，也不是 Strategy / Account / Position / Risk / Order 系统。

精确业务链：

```text
subing_entry_signal_v1 AlertEvent
        │
        ▼
TradeDecision
        │
        ├── NOT_EXECUTED
        │       └── 未执行原因 → DONE
        │
        └── EXECUTED
                │
                ▼
          TradeEpisode
                │
                ▼
          TradeExecution[]
                │
        net=0 / DOMINANT_ROLL
                │
                ▼
          Structured Review
                │
                ▼
               DONE
```

### 2.1 V1 只接 SuBing Formal Signal

唯一 eligible source：

```text
rule_code = subing_entry_signal_v1
```

`htdy_original_15m` 继续只是 `indicator_observation`：

```text
HTDY Event
→ WeCom / Market observation / Marker
→ 不进入 TradeDecision / TradeEpisode / 执行率统计
```

原因是 HTDY original 具有已知 repainting 风险，且当前合同不是 Formal Entry Signal。V1 不得用交易记录功能暗中提升 HTDY capability。

### 2.2 Non-goals

V1 明确不实现：

- CTP、期货公司或交易软件账户接入；
- 自动同步订单、成交、持仓、权益、保证金或风险度；
- 自动下单、改单、撤单、止损单、止盈单；
- Strategy / Position / Risk / Account Domain；
- 手工创建无 AlertEvent 来源的新交易；
- Episode 内反手或锁仓；
- 通用 Signal Center；
- 恢复旧 Signal / Review / Strategy HTTP、Web、worker 或旧 DB 合同；
- K 线 Snapshot Store；
- Signal replay/backfill；
- 盈亏对账、平今/平昨、手续费精确核算；
- Sharpe、最大回撤、Profit Factor、MFE/MAE、策略胜率等绩效研究；
- AI 自动评价、AI 自动修改或晋升规则；
- 新常驻 worker、scheduler 或 launchd service；
- 修改 Data Foundation、八表 Market Catalog、Canonical 或 SuBing / Alert 计算语义。

`auto_order=false` 始终成立。

## 3. Architecture

### 3.1 Application Domain

新增独立 Application Domain：

```text
services/quant-api/app/execution_review/
├── models.py
├── contracts.py
├── service.py
├── pnl.py
└── reconciler.py
```

职责：

- `models.py`：四个 PostgreSQL Application Domain ORM model；
- `contracts.py`：稳定状态值、原因词表、Review 标签词表与校验；
- `service.py`：Decision / Episode / Execution / Review 的唯一写业务权威；
- `pnl.py`：zero-I/O、Decimal-only 的持仓与估算毛盈亏纯计算；
- `reconciler.py`：只判断已存在 OPEN Episode 是否因正式 current rank1 切换而需要 `DOMINANT_ROLL`。

### 3.2 Dependency Direction

```text
Web
├── Alert API
└── Execution Review API
          │
          ▼
ExecutionReviewService
├── AlertEvent read-only
├── Execution Review application tables
└── MarketDataService / existing Market read capability
```

禁止：

```text
AlertRuntime → ExecutionReviewService
AlertService → ExecutionReviewService
ExecutionReview → direct Parquet / Redis / RQData
ExecutionReview → direct MainContractMap self-resolution
```

Alert V2 即使 Execution Review 整体不可用，也必须继续正常创建 AlertEvent 和执行既有 one-shot WeCom。

### 3.3 PostgreSQL Boundary

Data Foundation / Market Catalog 继续精确为八表。

V1.4 后逻辑上存在：

```text
Market Foundation
  8 tables

Alert Application Domain
  alert_rules
  alert_events

Execution Review Application Domain
  trade_decisions
  trade_episodes
  trade_executions
  trade_reviews
```

不得称为“14 表 Market Catalog”。

## 4. Core Data Model

### 4.1 `trade_decisions`

一个 eligible SuBing AlertEvent 最多一个 Decision。

```text
id
alert_event_id                  UNIQUE, FK alert_events.id

disposition
  EXECUTED
  NOT_EXECUTED

first_viewed_at                 nullable
decided_at                      required

primary_not_execute_reason      nullable
secondary_not_execute_reasons[]
decision_note                   nullable

execution_reason_tags[]
planned_stop_price              nullable Decimal
stop_basis                      nullable

created_at
updated_at
```

`first_viewed_at` 只表示用户第一次在归一量化里进入该机会处理界面的已知时间；不能解释成“企业微信已读时间”。如果无法可靠获得则保持 `NULL`，不得伪造成 `detected_at` 或 `notification_attempted_at`。

### 4.2 `trade_episodes`

```text
id
origin_decision_id              UNIQUE, FK trade_decisions.id

symbol
contract
direction                       LONG | SHORT

opened_at
closed_at                       nullable
close_reason                    nullable
  EXECUTION_NET_ZERO
  DOMINANT_ROLL

roll_reference_exit_price       nullable Decimal
roll_reference_bar_end          nullable

contract_multiplier_snapshot    nullable Decimal
multiplier_policy_id            nullable

created_at
updated_at
```

固定不变量：

```text
Episode.symbol     = origin AlertEvent.symbol
Episode.contract   = origin AlertEvent.contract
Episode.direction  = origin AlertEvent single result code
```

Episode 生命周期内不得改变 `symbol / contract / direction`。

数据库增加 partial unique constraint / index：

```text
UNIQUE(symbol) WHERE closed_at IS NULL
```

因此同一个品种最多存在一个 OPEN Episode，不支持 hedge / lock / 同品种多方向并行仓位模型。

### 4.3 `trade_executions`

```text
id
episode_id                       FK trade_episodes.id
trigger_decision_id              nullable, FK trade_decisions.id

execution_type
  OPEN
  ADD
  REDUCE
  CLOSE

executed_at
price                            Decimal
quantity                         integer > 0
note                             nullable

created_at
updated_at
```

当 `trigger_decision_id` 非空时必须唯一，保证同一个 Event/Decision 不会被重复执行两次。

逻辑 lineage：

```text
TradeExecution
→ TradeDecision
→ AlertEvent
```

### 4.4 `trade_reviews`

```text
id
episode_id                       UNIQUE, FK trade_episodes.id

signal_execution_adherence
  ALIGNED
  DEVIATED

entry_tags[]
holding_tags[]
exit_tags[]
market_context_tags[]
psychology_tags[]

summary                          nullable
submitted_at
created_at
updated_at
```

不设置星级、总分、confidence 或 AI score。

### 4.5 Array implementation

PostgreSQL 可使用 `TEXT[]`；隔离 SQLite 测试采用 JSON variant，沿用当前 Alert models 的兼容模式。所有数组元素仍必须通过 Python domain contracts 的唯一允许词表校验，不接受任意字符串。

## 5. Event Eligibility and Direction

执行闭环创建前必须读取不可变 AlertEvent 与其 AlertRule。

合法事件：

```text
rule_code = subing_entry_signal_v1
trading_day != NULL
contract 非空
result_codes = ["buy"]  或 ["sell"]
frequency in ["5m", "15m"]
```

映射：

```text
["buy"]  → LONG
["sell"] → SHORT
```

以下全部 fail-closed：

```text
HTDY Event
result_codes = []
result_codes = ["buy", "sell"]
legacy / invalid trading_day
缺失 contract
unsupported frequency
```

首次执行方向必须和 Formal Signal 一致。Signal SHORT 不能把实际 LONG 记录为该 Event 的 `EXECUTED`。

## 6. Decision Semantics

### 6.1 NOT_EXECUTED

必须存在一个 Primary Reason：

```text
WORK_MISSED
TOO_LATE
PRICE_ACTION_REJECTED
POOR_LOCATION
POOR_RISK_REWARD
EXISTING_SAME_DIRECTION_TRADE
EXISTING_OPPOSITE_DIRECTION_TRADE
RISK_CAPACITY
HESITATION
OTHER
```

语义：

- `WORK_MISSED`：工作中或未及时看到；
- `TOO_LATE`：看到时机会已经过去；
- `PRICE_ACTION_REJECTED`：价格行为不认可；
- `POOR_LOCATION`：位置不好，不愿追单；
- `POOR_RISK_REWARD`：当时风险收益关系不接受；
- `EXISTING_SAME_DIRECTION_TRADE`：已有同方向 Episode；
- `EXISTING_OPPOSITE_DIRECTION_TRADE`：已有反方向 Episode；
- `RISK_CAPACITY`：当前不适合继续承担风险；
- `HESITATION`：看到机会但主观犹豫未执行；
- `OTHER`：其他。

规则：

```text
Primary          必填
Secondary        0..N、去重、不得重复 Primary
Primary=OTHER    decision_note 必填
```

一个 Event 保存 `NOT_EXECUTED` 后即属于 DONE，不要求再创建 TradeReview。

### 6.2 EXECUTED

“已执行”只表示真实首次开仓或真实同方向加仓已经发生，不表示“准备执行”。

必须同时提交：

```text
executed_at
price
quantity
至少 1 个 execution_reason_tag
```

执行理由词表：

```text
HIGHER_TIMEFRAME_ALIGNED
KEY_LEVEL_BREAKOUT
PULLBACK_RECONFIRMED
VOLUME_CONFIRMED
MULTITF_STRUCTURE_ALIGNED
LOCATION_ACCEPTABLE
OTHER
```

可选记录：

```text
planned_stop_price
stop_basis
  EMA
  PREVIOUS_BAR_EXTREME
  RANGE_BOUNDARY
  MOVE_ORIGIN
  OTHER

decision_note
```

这些只是 Decision-time Context，不建立真实止损单或 Risk Runtime。

### 6.3 Causal Time

所有由 AlertEvent 驱动的 `OPEN / ADD` 必须：

```text
execution.executed_at >= AlertEvent.bar_end
```

不得把 Signal 收盘确认之前的成交伪装成“执行了该 Signal”。

## 7. Episode and Execution State Machine

### 7.1 Status is derived

数据库不保存 `OPEN / PENDING_REVIEW / DONE` workflow column。

读模型：

```text
OPEN
= closed_at IS NULL

PENDING_REVIEW
= closed_at IS NOT NULL
  AND TradeReview 不存在

DONE
= closed_at IS NOT NULL
  AND TradeReview 存在
```

待决策：

```text
eligible SuBing AlertEvent
AND TradeDecision 不存在
```

因此不新增 Task / Workflow 表。

### 7.2 First execution

没有同品种 OPEN Episode 时，Event 的 `EXECUTED` 必须在一个事务内创建：

```text
TradeDecision(EXECUTED)
+
TradeEpisode
+
TradeExecution(OPEN)
```

要求：

```text
OPEN 是 Episode 第一条 Execution
OPEN.trigger_decision_id = origin_decision_id
OPEN direction = Episode direction
```

任何一步失败，全部 rollback。

### 7.3 Same-direction subsequent Event

已存在：

```text
JM SHORT Episode OPEN
```

又出现同 `symbol + contract + direction` SuBing Event：

- Event 仍必须独立记录 Decision；
- 选择 `NOT_EXECUTED` 正常结束该 Event；
- 选择 `EXECUTED` 时不得创建第二个 Episode；
- 在单事务内创建 `TradeDecision(EXECUTED) + TradeExecution(ADD)`；
- `ADD.trigger_decision_id` 指向该后续 Decision。

人工根据自己的价格行为/二次确认进行 ADD 也允许：

```text
ADD.trigger_decision_id = NULL
```

因为 V1 的目标是记录真实执行，不要求每次真实加仓都必须再次出现 Formal Signal。

### 7.4 Opposite-direction Event

已存在同 symbol 的反方向 OPEN Episode 时，新 Event 仍可记录 `NOT_EXECUTED`。

尝试 `EXECUTED` 必须返回稳定 conflict：

```text
OPPOSITE_EPISODE_OPEN
```

系统不得提供“平仓并反手”快捷动作。用户必须先以真实 Execution 将旧 Episode 净手数归零，再处理新的反方向 Event。

### 7.5 REDUCE / CLOSE

设当前净手数为 `Q > 0`：

```text
ADD      quantity > 0
REDUCE   0 < quantity < Q
CLOSE    quantity = Q
```

任何操作不得使净手数 < 0。

`CLOSE` 成功后：

```text
closed_at    = CLOSE.executed_at
close_reason = EXECUTION_NET_ZERO
```

没有手工“结束交易”按钮。

## 8. Manual Correction Contract

系统事实与人工事实边界：

```text
AlertEvent
→ immutable

TradeDecision / TradeExecution / TradeReview
→ 可事后纠错
```

但“可编辑”不能破坏 lineage 或 position topology。

### 8.1 Immutable lineage fields

普通编辑不得改变：

```text
TradeDecision.alert_event_id
TradeEpisode.origin_decision_id
TradeEpisode.symbol / contract / direction
TradeExecution.episode_id
```

### 8.2 Simple field correction

价格、时间、备注、原因、Decision-time Context、Review 标签等可编辑，但保存前必须重新验证全部领域约束。

### 8.3 Topology correction

已经存在多个 Execution 的 Episode，如果要纠正 `quantity / execution_type / sequence`，Web 必须编辑完整 timeline 后一次提交。

服务在单个 transaction 中：

```text
验证完整 timeline
→ 重新推导净手数 / avg cost / close state
→ 全部替换或全部失败
```

不得通过逐条 PUT 暂时制造负仓位、超平或反手状态。

### 8.4 Wrong disposition correction

`disposition` 不属于普通 PUT 字段。

如用户确实误记 `EXECUTED / NOT_EXECUTED`，必须走专用的原子 correction action：

- `NOT_EXECUTED → EXECUTED`：必须同时提供合法 OPEN/ADD 执行事实，并重新检查 OPEN Episode 冲突；
- `EXECUTED → NOT_EXECUTED`：只有在移除其 trigger Execution 不会破坏后续 Episode topology / Review lineage 时才允许；否则返回 conflict，要求先修正 Execution timeline。

不开放通用 DELETE API；内部 correction 可以在单事务内重建错误录入的人工事实。

## 9. Structured Review Contract

只有实际执行过并已关闭的 Episode 才能创建 Review。

V1 每组至少需要一个结构化选择：

### 9.1 Entry

```text
REASONABLE
TOO_EARLY
TOO_LATE
CHASED
BREAKOUT_CONFIRMATION_INSUFFICIENT
```

`REASONABLE` 不得与其余 entry error tags 同时出现。

### 9.2 Holding

```text
NORMAL
COULD_NOT_HOLD
REDUCED_TOO_EARLY
UNPLANNED_ADD
MISSED_VALID_ADD
```

`NORMAL` 不得和其他 holding error tags 同时出现。

### 9.3 Exit / Risk

```text
NORMAL
STOP_DELAYED
STOP_MOVED
PROFIT_TO_LOSS
EXIT_TOO_EARLY
MISSED_PROFIT_REDUCTION
```

`NORMAL` 不得和其他 exit/risk error tags 同时出现。

### 9.4 Market Context

```text
WITH_HIGHER_TIMEFRAME
AGAINST_HIGHER_TIMEFRAME
VALID_BREAKOUT
FALSE_BREAKOUT
RANGE
TREND
```

本组允许组合事实，例如 `TREND + WITH_HIGHER_TIMEFRAME + VALID_BREAKOUT`。

### 9.5 Psychology

```text
NONE
HESITATION
LOSS_AVERSION
FOMO
REVENGE
PREDICTION_BIAS
OVERTRADING
```

`NONE` 不得和其他 psychology tags 同时出现。

### 9.6 Review Completion

Review 至少要求：

```text
signal_execution_adherence
entry_tags >= 1
holding_tags >= 1
exit_tags >= 1
market_context_tags >= 1
psychology_tags >= 1
```

`summary` 可选。

Review 提交后 Episode 才进入 DONE；Review 以后仍可编辑纠错，不保存完整 revision history。

## 10. PnL Contract

V1 不建设账户账本，只提供：

```text
Estimated Gross PnL
```

所有价格、成本、数量相关金额运算使用 `Decimal`。

### 10.1 Weighted Average Cost

同 Episode 永远只有一个方向，因此使用加权平均持仓成本即可。

LONG：

```text
realized += (exit_price - avg_cost) × quantity × multiplier
```

SHORT 镜像。

ADD 更新平均成本；REDUCE/CLOSE 不改变剩余仓位的 avg cost，只实现对应数量的 gross PnL。

### 10.2 Product Multiplier Reference

允许新增一个极小、Git-tracked、research-only 的参考文件：

```text
data/reference/product_trade_multipliers.csv
```

最小字段：

```text
product,multiplier
```

边界：

- 不属于八表 Market Catalog；
- 不建立 ContractSpec / Account / Risk Domain；
- 不保存保证金、手续费、tick value、交易所限仓或交割规则；
- 具体 multiplier 数值必须在实现阶段从当前可核验的交易所/RQData 合约规格中确认，不由本设计文档猜测；
- Episode 创建时 snapshot 当前 multiplier 与 `multiplier_policy_id`，历史 Episode 不随文件变化重新漂移；
- multiplier 缺失不能阻止记录真实 Decision/Execution，只让人民币 gross PnL 显示 `unavailable`；
- 价格点数、持仓手数、Execution timeline 仍可正常使用。

因此人民币金额只是辅助复盘，不是账户对账事实。

### 10.3 Open Episode

OPEN Episode 的浮动 PnL 只在 read-time 使用当前可读参考价计算，不持久化到 DB。

## 11. Dominant Roll Contract

### 11.1 Fixed contract identity

一个 Episode 从创建到结束始终绑定 origin AlertEvent 的真实合约。

```text
Episode.contract = origin_event.contract
```

禁止：

```text
JM2609 Episode
→ 将 JM2701 Event/Execution 合并进同一个 Episode
```

### 11.2 DOMINANT_ROLL

若 OPEN Episode 的 `contract` 已不再等于该 symbol 正式 current rank1：

```text
close_reason = DOMINANT_ROLL
closed_at = old contract 最后一根可唯一确认 reference bar 的 bar_end
roll_reference_exit_price = reference bar close
roll_reference_bar_end = reference bar bar_end
```

不伪造 `TradeExecution(CLOSE)`。

页面必须明确：

```text
主力换月自动结束
参考退出价 = 系统估算，非真实成交
```

### 11.3 Fail-closed

如果无法通过既有 MarketDataService / formal market identity 唯一确认：

- current rank1；或
- old contract 的最后 confirmed reference bar；

则：

```text
不猜 contract
不猜 exit price
不自动关闭
Episode 保持 OPEN
```

读模型显示稳定状态：

```text
ROLL_RECONCILIATION_REQUIRED
```

### 11.4 Real close overrides roll estimate

若系统已经 `DOMINANT_ROLL` 估算关闭，用户随后补录真实平仓：

- 允许以真实 CLOSE timeline 纠正 Episode；
- 真实 Execution 成为正式人工事实；
- `close_reason` 回到 `EXECUTION_NET_ZERO`；
- `closed_at` 使用真实成交时间；
- roll reference fields 清空。

### 11.5 Runtime placement

不新增第六个常驻 Runtime、worker 或 scheduler。

自动 roll reconciliation 如果启用，只允许作为现有 18:05 after-market 成功之后的**独立 bounded application follow-up**：

```text
existing after-market schedule
→ Market data after-market 完成
→ 若 Market outcome passed/noop
→ ExecutionReviewRollReconciler
```

架构硬边界：

- `AfterMarketUpdater` 本身不得依赖或调用 Execution Review；
- follow-up 放在运维/composition seam，而不是 Market Data Domain 内；
- reconcile 失败不得把已经成功的 Market after-market 改报失败；
- reconcile 失败不得触发 RQData/Canonical retry；
- 不新增 launchd label；
- 新主力 Event 被用户尝试执行之前仍要做 defensive reconcile，避免后台 follow-up 漏失。

该自动 Application DB mutation 默认关闭，必须在 production migration/runtime 已就绪后取得独立的、范围明确的一次性 activation intent，才能获得此后有界持续授权。它不能从既有 Market Runtime V1 授权推导。

## 12. K-line Post-hoc Reconstruction

V1 不保存 Signal 时刻 Live Bars 或截图。

复盘根据 immutable AlertEvent identity 做 post-hoc reconstruction：

```text
symbol
contract
trading_day
frequency
bar_end
```

唯一 Historical Gateway 继续是 `MarketDataService`。不得直接读 Parquet、Redis 或自行解析 MainContractMap。

### 12.1 Segment identity

必须使用 MarketDataService 已有能力解析“包含 Event.trading_day 且与 Event.contract 一致的 rank1 segment”。

禁止：

- 使用当前最新主力 segment 替代历史 Event segment；
- 跨 roll warm-up；
- continuous 数据替代 real contract；
- 读取 Event 之后才完成的 companion bar。

### 12.2 Two-stage view

复盘默认：

```text
[信号当时]
```

硬 cutoff：

```text
bar.bar_end <= AlertEvent.bar_end
```

用户主动切换后才显示：

```text
[完整走势]
```

完整走势用于看 Signal 后面发生了什么，但不得反向改变 AlertEvent、Decision 或历史 Signal 结论。

### 12.3 Multi-timeframe

复盘允许 5m / 15m。

5m Event：15m 只能读取当时已经 confirmed 的最后一个 15m。  
15m Event：5m / 15m 均不得超过 Event boundary。

### 12.4 Availability

Reconstruction 是辅助 read model：

```text
status = READY | UNAVAILABLE
```

可预期不可用返回 `200` + stable reason，例如：

```text
MARKET_HISTORY_NOT_READY
MARKET_IDENTITY_CONFLICT
MARKET_PARTITION_UNAVAILABLE
```

Reconstruction unavailable 不得阻止用户记录 Execution 或完成 Review。

## 13. Web Product Design

### 13.1 New surface

用户一级导航新增：

```text
交易记录
```

建议 route：

```text
/trade-records
```

不得恢复旧 `/review`、Signal Center 或 Strategy 页面。

### 13.2 Task-state-first layout

固定四个状态：

```text
待决策
进行中
待复盘
已完成
```

状态来自 read model，不建 Workflow 表。

默认进入“待决策”。

### 13.3 Pending Decision

卡片最小信息：

```text
品种 / contract
LONG | SHORT
SuBing 入场信号
resolved frequency
lower_tf_confirmation
Signal bar_end
距 Signal 时间
```

动作：

```text
看K线
处理
```

不显示信号评分、预计收益、AI 建议或胜率。

### 13.4 Fast intraday input

盘中记录目标：5～10 秒完成。

首次 EXECUTED 必填：

```text
成交时间
价格
手数
至少一个执行理由
```

止损计划与备注可选。

后续 ADD / REDUCE / CLOSE 只要求：

```text
动作
时间
价格
手数
```

完整复盘只在交易结束后填写。

### 13.5 Existing episode UX

同方向 Event：点击已执行时 UI 明示“本次将记录为加仓”，不得提供第二个 Episode 选项。

反方向 Event：点击已执行时硬阻断并显示 `OPPOSITE_EPISODE_OPEN` 对应文案，不提供“平仓并反手”。

### 13.6 Pending Review

展示：

```text
Signal
Decision-time Context
Execution Timeline
Estimated Gross PnL
Structured Review
```

DOMINANT_ROLL 必须显著区分真实 CLOSE 与系统参考退出价。

### 13.7 Market integration

Market 页面继续从 Alert API 读取 Event；Web 额外通过 Execution Review API 批量查询 Event state。

Market 只显示动作入口：

```text
记录执行
查看交易
去复盘
查看记录
```

Alert API/Service 不反向依赖 Execution Review。

## 14. API Contract

统一前缀：

```text
/api/execution-review
```

### 14.1 Query

```text
GET /api/execution-review/items
GET /api/execution-review/event-states
GET /api/execution-review/episodes/{episode_id}
GET /api/execution-review/stats
GET /api/execution-review/events/{event_id}/reconstruction
```

`items.state` 只接受 read model：

```text
pending_decision
open
pending_review
done
```

### 14.2 Commands

```text
POST /api/execution-review/events/{event_id}/not-executed
POST /api/execution-review/events/{event_id}/executed
POST /api/execution-review/episodes/{episode_id}/executions
POST /api/execution-review/episodes/{episode_id}/review

PUT  /api/execution-review/decisions/{decision_id}
PUT  /api/execution-review/executions/{execution_id}
PUT  /api/execution-review/episodes/{episode_id}/execution-timeline
PUT  /api/execution-review/reviews/{review_id}
POST /api/execution-review/decisions/{decision_id}/correct-disposition
```

`POST .../executions` 不接受 OPEN；OPEN 只能由 Event `executed` action 创建。

### 14.3 Explicitly absent

```text
POST /trade-episodes
POST /manual-trades
POST /reverse
POST /positions
POST /orders
DELETE /alert-events/{id}
DELETE /trade-episodes/{id}
```

## 15. Error Contract

沿用当前 API 风格：

```json
{
  "detail": {
    "code": "STABLE_CODE"
  }
}
```

### 15.1 404

```text
EXECUTION_REVIEW_EVENT_NOT_FOUND
TRADE_DECISION_NOT_FOUND
TRADE_EPISODE_NOT_FOUND
TRADE_EXECUTION_NOT_FOUND
TRADE_REVIEW_NOT_FOUND
```

### 15.2 422

```text
EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE
EVENT_DIRECTION_INVALID
EXECUTION_DIRECTION_MISMATCH
EXECUTION_QUANTITY_INVALID
EXECUTION_TIME_BEFORE_SIGNAL
UNKNOWN_DECISION_REASON
UNKNOWN_EXECUTION_REASON
UNKNOWN_REVIEW_TAG
STOP_PRICE_INVALID
```

### 15.3 409

```text
DECISION_ALREADY_EXISTS
OPPOSITE_EPISODE_OPEN
OPEN_EPISODE_CONFLICT
EPISODE_ALREADY_CLOSED
EPISODE_REVIEW_NOT_READY
REVIEW_ALREADY_EXISTS
EXECUTION_TOPOLOGY_INVALID
TRIGGER_DECISION_ALREADY_USED
DECISION_CORRECTION_CONFLICT
```

### 15.4 503

只有真正的持久化/基础设施失败才使用：

```text
EXECUTION_REVIEW_PERSIST_FAILED
```

Mutation 失败后不得使用 optimistic local state 冒充成功。

## 16. Lightweight Statistics V1

统计只回答执行问题，不提前评价策略盈利能力。

默认历史筛选可使用最近 30 个 trading days / 用户时间范围，但 pending/open/pending-review 不能因为时间筛选被隐藏。

时间语义优先使用 `AlertEvent.trading_day`，不按夜盘自然日期错误分组。

基础筛选：

```text
trading day range
symbol
LONG / SHORT
5m / 15m
```

### 16.1 Opportunity Processing

```text
eligible_events
processed_events
pending_events

decision_completion_rate
= processed_events / eligible_events
```

### 16.2 Execution Rate

只在已处理 Decision 中计算：

```text
execution_rate
= EXECUTED / processed_events
```

不得用 `EXECUTED / eligible_events`，否则 pending Event 会被错误算成未执行。

### 16.3 Primary Non-execution Reasons

只用 `primary_not_execute_reason` 作为主分布分母。Secondary reasons 只用于详情，不重复计数。

### 16.4 Work State

```text
open
pending_review
done
```

### 16.5 Review Issue Top

仅统计结构化 Review tags：

```text
Entry
Holding
Exit/Risk
Psychology
```

### 16.6 Explicitly not in V1

不提供：

```text
SuBing 胜率
品种盈利排名
LONG/SHORT 胜率
Profit Factor
Sharpe
最大回撤
最佳交易时段
MFE / MAE
人工过滤提升了多少收益
```

样本积累后再进入独立 Outcome / Behavioral Analytics 设计。

## 17. Migration and Compatibility

当前 production revision 为 `20260814_0038`。实现时创建其后的下一条 additive migration；本设计不提前猜 revision id。

Migration 只允许：

```text
CREATE trade_decisions
CREATE trade_episodes
CREATE trade_executions
CREATE trade_reviews
CREATE required checks / indexes / foreign keys
```

不得：

- 修改八表 Market Catalog；
- 修改 `alert_rules` / `alert_events` 现有字段或 identity；
- 修改 Alert Scope；
- 修改 SuBing Calibration / FormalPolicy；
- 创建 Account / Position / Order / Risk tables。

Migration 是 additive，因此旧 `v1.3.1` Runtime 不读取这些表，不需要为了 schema 兼容恢复 V1/V2 双写层。

历史已有 SuBing AlertEvent 可在 v1.4 上线后进入 Decision 处理；不做 synthetic backfill，也不为没有 AlertEvent 的历史行情造机会。

## 18. Runtime and External Gates

普通代码、测试、spec、`develop` commit/push 不属于受控外部 operation。

v1.4 rollout 继续分离：

```text
Gate A  v1.4 release main/tag
Gate B  production additive DB migration
Gate C  Runtime promotion/switch
Gate D  DOMINANT_ROLL automatic reconciliation activation
```

前一步不授权后一步，失败重试需要新的一次性 intent。

V1.4 不修改 WeCom sender、Alert Rule Scope 或 Alert Runtime 触发语义，因此不要求把真实 WeCom canary 作为本版本发布动作。

### 18.1 SuBing Natural Canary

当前 `subing_entry_signal_v1 × jm` Natural Canary 仍是独立 pending evidence。

它：

- 不阻塞 v1.4 design / coding / isolated tests；
- 不由 v1.4 测试或 synthetic Event 冒充通过；
- 也不被本设计额外升级为 production migration 的强制前置 Gate，因为 v1.4 不修改 SuBing/Alert Event 产生语义；
- 如果 v1.4 rollout 时仍未自然出现，只能继续在 `STATUS.md` 保持 pending，不能宣称“自然 Signal → Execution Review 全链验收”。

一旦自然 Event 后续出现，可作为 v1.3.x Alert 证据和 v1.4 真实入口样本继续验收。

## 19. Testing Matrix

所有写测试继续只使用隔离 DB、fixture、临时目录和 mock；不得连接 production Runtime 或把测试 Scope PUT / synthetic Event 当真实 Gate。

### 19.1 Domain / PnL

```text
LONG / SHORT OPEN
OPEN + ADD
REDUCE / CLOSE
weighted average cost
partial/final realized gross pnl
Decimal precision
missing multiplier
multiplier snapshot stability
DOMINANT_ROLL estimated pnl
```

### 19.2 Decision

```text
only SuBing eligible
HTDY rejected
buy→LONG / sell→SHORT
invalid multi-result rejected
NOT_EXECUTED requires primary reason
secondary dedup
OTHER requires note
EXECUTED requires reason + execution
execution before event.bar_end rejected
```

### 19.3 Episode / Execution

```text
one symbol one OPEN Episode
same direction Event → ADD
opposite direction Event → 409
cross-contract Event cannot merge
no reverse
over-reduce rejected
exact CLOSE closes
manual ADD allowed only inside existing Episode
trigger Decision unique
```

### 19.4 Correction

```text
simple field edit
atomic timeline replacement
invalid corrected timeline rollback
wrong disposition bounded correction
AlertEvent remains unchanged
```

### 19.5 Review

```text
closed Episode only
required groups
NORMAL/REASONABLE/NONE mutual exclusion
unknown tags rejected
Review editable
```

### 19.6 Dominant Roll

```text
same rank1 → NOOP
rank1 changed → DOMINANT_ROLL
old contract last confirmed reference
identity unavailable → fail-closed
reference unavailable → remain OPEN
real CLOSE later replaces estimate
reconcile failure cannot change Market after-market outcome
```

### 19.7 Reconstruction

```text
same Event contract / containing rank1 segment
cutoff <= Event.bar_end
5m event cannot read future 15m
15m event cannot read future 5m
no cross-roll state
UNAVAILABLE does not block Review
```

### 19.8 API

覆盖稳定 `404 / 422 / 409 / 503 + detail.code`。

### 19.9 Web

Unit / E2E 至少覆盖：

```text
pending Event → NOT_EXECUTED → DONE
pending Event → OPEN → CLOSE → PENDING_REVIEW → Review → DONE
same-direction Event → ADD
opposite-direction hard block
DOMINANT_ROLL visual distinction
signal-time / full-trajectory switch
stats denominators
Market Event state integration
```

### 19.10 Required regression

继续运行受影响的现有：

```text
MarketDataService / MarketRead
SuBing Factor / Signal
Alert V2
AfterMarketUpdater
Runtime health
Market Web
```

最终命令以实施时更新后的 `TESTING.md` 为唯一验证入口。

## 20. Acceptance Definition

V1.4 代码完成至少证明：

1. 只有 `subing_entry_signal_v1` Event 可进入 Execution Review；
2. `AlertEvent` schema、identity 与生成语义未改变；
3. 一个 Event 最多一个 Decision；
4. NOT_EXECUTED 必须有 Primary Reason；
5. EXECUTED 必须伴随真实 OPEN/ADD Execution；
6. 一个 symbol 最多一个 OPEN Episode；
7. Episode contract/direction 生命周期固定；
8. 不支持 Episode 内反手；
9. 同方向后续 Event 可安全转成 ADD；
10. 净手数归零自动关闭；
11. DOMINANT_ROLL 只使用正式 rank1 + old-contract reference，不能猜；
12. DOMINANT_ROLL 估值显著标记非真实成交；
13. 实际 CLOSE 可以纠正/替代 roll estimate；
14. 已执行 Episode 必须完成 Structured Review 才 DONE；
15. Signal-time reconstruction 默认严格 cutoff 到 Event；
16. 5m/15m reconstruction 不未来引用、不跨 roll；
17. Reconstruction unavailable 不阻止人工复盘；
18. PnL 是 Decimal-based Estimated Gross PnL，不冒充账户盈亏；
19. 没有 Account / Risk / Position / Order；
20. 没有 manual trade 创建入口；
21. 不修改八表 Market Catalog / Canonical；
22. 不修改 SuBing Signal 公式、Calibration 或 FormalPolicy；
23. 不修改 Alert Scope / WeCom / Alert Runtime dispatch；
24. 不新增常驻 Runtime / worker / scheduler；
25. `auto_order=false` 始终成立。

本设计不证明：

- SuBing 盈利；
- 长期稳定；
- 用户已具备稳定盈利能力；
- 价格行为过滤已经产生增量 alpha；
- v1.4 Runtime / production migration 已执行；
- SuBing Natural Canary 已通过。

## 21. Implementation Decomposition

推荐拆为独立可集成任务，不用一个 Codex 会话一次实现全部：

### Task 1 — Domain Core + Additive Migration

```text
models
contracts
PnL pure core
multiplier reference loader
DB checks/indexes
migration
```

Lane 3：交易事实、PnL 与 production schema 语义。

### Task 2 — Service + API

```text
Decision actions
Episode/Execution invariants
bounded correction
Review commands
read models
stats/error contracts
```

Lane 3：正式人工交易事实写入口。

### Task 3 — Reconstruction + Dominant Roll

```text
historical reconstruction
rank1-segment identity
roll reconciler
defensive reconcile
after-market composition seam
```

Lane 3：未来数据、roll identity 与自动 Application DB mutation 边界。

### Task 4 — Web Execution Review

```text
/trade-records
四状态
fast decision/execution forms
episode detail
structured review
reconstruction switch
Market integration
```

Lane 2：只消费已经冻结的 API contracts；不得在 Web 重写业务判断。

### Task 5 — Lightweight Stats + Canonical Closure

```text
stats UI
TESTING
ARCHITECTURE / deep canonical as actually required
regression closure
```

Lane 2；如统计口径或业务合同发生改变则升级 Review。

### Task 6 — Release / Production Rollout

Lane 3，独立 rollout 会话；release、migration、Runtime switch、roll-auto activation 各自停在人工 Gate。

仓库自身不要求 task branch/worktree/PR 作为普通 develop 授权条件；实际 Codex 调度可以按任务风险选择独立 worktree 和独立 Review，但不得把协作工具误写成仓库外部操作授权。

## 22. Roadmap After V1.4

### v1.5 — Outcome & Behavioral Analytics

在真实记录积累后，再分别研究：

```text
Signal Outcome
→ 3K/5K/8K directional return
→ MFE / MAE

Human Outcome
→ 执行率
→ 工作错过率
→ 主动过滤率
→ 犹豫率
→ 入场/持仓/退出问题
```

目标是区分：

```text
系统机会不好
vs
机会不错但用户没做
vs
用户执行偏差
vs
人工价格行为过滤是否真的有效
```

### v1.6 — AI-assisted Review Research

AI 只消费版本化、结构化事实：

```text
AlertEvent
Decision
Decision-time Context
Execution[]
Review
Outcome
```

允许：每日/每周总结、重复行为模式发现、研究问题建议。

禁止：AI 自动下单、AI 自动改规则、AI 自动晋升正式策略。

### Later Candidate Research

只有真实样本和 Outcome 证据足够后，才把重复经验转成 Candidate Rule：

```text
Candidate
→ Discovery
→ OOS
→ Walk-forward
→ Shadow
→ 人工批准
```

未来若确实需要交易级历史复算，再以新任务从 Canonical / MarketDataService 重建最小 Backtest Research Engine；不得从旧已退役实现恢复兼容入口。

## 23. Final Design Statement

> **Execution Review V1 是建立在 immutable SuBing AlertEvent 之上的最小个人执行与复盘 Application Domain。系统只负责保存“机会事实、人工决策、真实执行、交易过程和结构化复盘”，不建设账户、持仓、风控、订单或通用策略平台。Episode 固定真实合约和方向，一个品种最多一个 OPEN Episode；同方向后续 Signal 可成为 ADD，反方向必须先结束旧 Episode。主力换月可以在独立授权的 bounded reconcile 中用旧合约最后 confirmed reference 做非真实成交估算关闭，并允许后补实际 CLOSE。复盘 K 线只通过 MarketDataService 做 post-hoc reconstruction，默认截止 Signal 时点，不保存 Live 快照、不未来引用。V1 统计只回答“机会有没有处理、为什么没执行、执行有哪些重复问题”，不提前把少量样本包装成策略盈利结论。`auto_order=false` 始终成立。**
