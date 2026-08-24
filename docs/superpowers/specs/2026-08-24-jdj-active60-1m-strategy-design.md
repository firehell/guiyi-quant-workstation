# 日进斗金 Active60 1m Strategy Replay 设计

更新时间：2026-08-24  
状态：Review 完成后的正式阶段一 Strategy Spec；授权后续 implementation planning，不授权代码实现、真实 RQAlpha smoke、prospective OOS 消费、Alert/Runtime、main/tag/release、正式数据写入或订单能力。

## 1. 目标与当前事实

当前 `develop` 已完成一条窄的、research-only、deterministic JDJ reference replay：

```text
strategy_id = jdj_intraday_futures_v1
profile_id  = jdj_jm_1m_v1
symbol      = jm
series_kind = actual_dominant
execution   = 1m
trend       = 5m
```

现有实现已经具备：

- 三类冻结 JDJ Candidate Entry：
  - `jdj_trend_follow_1m_candidate_v1`
  - `jdj_trend_reentry_6_1m_candidate_v1`
  - `jdj_key_level_breakout_1m_candidate_v1`
- Entry authorization、最低 R:R、以损定量、部分止盈、最多两次盈利加仓、保护位、daily pause/stop 与 session flatten；
- `MarketDataService -> ActualDominantResearchSegmentLoader` 的 confirmed Historical 主力分段；
- `/api/v1/market/research/jdj-strategy/history`；
- Market 主图 `ENTRY/ADD/REDUCE/EXIT` reference marker；
- `reference_execution=true`，且不进入 DB、Redis、Alert、Execution Review、Runtime 或订单路径。

阶段一只解决：

> **在不改变 JDJ V1 策略语义的前提下，把完整 Strategy Reference Replay 从 JM 扩展为当前 active universe 中任意单产品的 `actual_dominant + 1m` Historical replay。**

当前 active universe 唯一入口仍为 `data/universe/active_products.txt`，现为 active60。已有 JDJ active60 robustness protocol 证明三个 Candidate 已具有跨品种 research 输入路径；它不证明完整 Strategy Replay，也不得被解释为策略盈利、有效或可交易结论。

## 2. Review 后的关键修正

本次 Review 在原方案 A 基础上冻结以下修正。

### 2.1 active60 是当前准入范围，不是永久 OOS universe manifest

Strategy profile 只声明 `product_scope_source=active_products`。当前哪些品种可调用由 `load_active_products()` 决定。

未来 prospective OOS / candidate version 必须由自己的 protocol/manifest 冻结 exact product set；不得拿动态 active universe 代替 OOS universe identity。active universe 将来变化，不等于 Strategy Core 版本自动变化，也不得改写既有 OOS 样本。

### 2.2 Replay 直接复用现有 `ResolvedContractSegment`

不新建第二个 segment DTO，也不把 `contract/start/end` 作为四散参数重复传递。

`run_jdj_reference_segment(...)` 新增：

```python
symbol: str
segment: ResolvedContractSegment
```

由现有 loader 已验证的 segment 直接传入。这样可删除当前无 event/pivot 时的 `JM0000 / date.min` fallback，同时保持单一 identity 类型。

### 2.3 Composition 不得在 builder 时绑定单一 exchange

当前 builder 先固定 `symbol="jm"` 再查 DCE。active60 后必须改成 callback 执行时按传入 `symbol` 解析 exchange；同一个 `JdjStrategyReplayService` 实例顺序处理 `jm -> rb -> cf -> sc` 时，不得残留前一个品种的 exchange/session 状态。

### 2.4 HTTP error mapping 必须覆盖 service admission

`JDJ_STRATEGY_PROFILE_UNAVAILABLE` 不再只可能由 Request 构造产生。非 active product 将在 service admission 阶段产生同一 typed error，因此 route 必须同时捕获 request 和 service 阶段的该错误并保持 HTTP 422。

`load_active_products()` 本身损坏属于 active universe 事实异常，必须保持 `409 / ACTIVE_UNIVERSE_INVALID`，不能伪装为“不支持该品种”。

### 2.5 Reference replay 不新增“可执行成交”含义

仓库当前没有 JDJ 所需的统一最小变动价位、保证金率、手续费/滑点正式合同。阶段一不能为了 active60 顺手补一个交易所执行模型。

因此继续明确：

- `reference_price` 是 deterministic reference fill price，不保证满足真实交易所最小变动价位；
- `quantity` 是基于冻结 equity、structural stop 和 contract multiplier 的 planned-risk reference quantity，不保证满足真实保证金约束；
- 当前 PnL/drawdown 语义不新增 commission、slippage、margin call 或 account availability；
- `better_open / limit_touch / next_open` 仍是 research replay basis，不是券商/交易所成交回执。

如果未来正式回测、RQAlpha 策略或人工执行辅助需要 tick/margin/fees，则必须单独定义可复算 execution contract，不能静默扩写本阶段语义。

### 2.6 JM golden 必须先于生产代码修改冻结

JM parity 不是“改完以后看测试大致没变”。实施第一笔代码提交必须只增加测试/fixture，把当前 JM 行为冻结成 immutable golden；随后才能修改 profile、service、composition 或 replay。

Golden 一旦冻结，active60 实施过程中不得重新生成；若必须更新，视为 Strategy semantics change，需停止本任务并另行设计。

## 3. 不变的策略语义

### 3.1 Candidate Entry 不重写

继续直接复用当前三类 Candidate reducer。以下语义不得改变：

- source timeframe=`1m`；
- trend context=`5m`；
- EMA20 当前 seed / rounding / close input；
- 5m N Structure strict-before；
- same trading day / same physical contract / same rank1 segment；
- previous-bar dynamic trigger，equal 不算 breach；
- Trend Follow / Trend Reentry 6 / Key Level Breakout reducer 语义；
- Candidate event id、direction、`observed_at`、trigger level、source event kind 与 priority。

本阶段不得重新解释原始资料来修改已经冻结的 Entry 公式。

### 3.2 Trade Management 不重定参数

当前完整策略中已经机械化的交易管理原样冻结，包括：

```text
minimum_reward_risk                 = 2.0
max_planned_trade_risk_fraction     = 0.01
base_risk_fraction                  = 0.005
first_profit_take_fraction          = 0.40
require_profit_before_add           = true
require_partial_profit_before_add   = true
add_fraction_of_current_qty         = 0.25
max_add_count                       = 2
losing_position_add_forbidden       = true
daily_pause_drawdown_fraction       = 0.005
daily_pause_bars                    = 15
daily_stop_drawdown_fraction        = 0.01
historical_reference_start_equity   = 1000000
entry_limit_valid_bars              = 1
terminal_flatten_lead_bars          = 1
```

这些规则与当前实现已经一致。本阶段不比较哪个品种“适合”哪组参数，不使用 active60 历史结果反向调参。

原始资料支持的只是交易理念与风险管理来源，例如入场前明确止损/潜在盈利、重视盈亏比、盈利后再加仓、分段止盈、控制每日亏损；它们不提供“60 个国内期货品种分别应使用什么参数”的依据。因此 active60 扩展不能从资料推导 per-product override。

## 4. 目标架构

```text
Market Web 当前 symbol
        │
        ▼
GET /api/v1/market/research/jdj-strategy/history
        │
        ▼
JdjStrategyReplayRequest
  - normalize request shape
  - actual_dominant + 1m only
        │
        ▼
JdjStrategyReplayService
  - current active-products admission
  - exact JDJ/N policy
        │
        ▼
ActualDominantResearchSegmentLoader
        │
        ├── confirmed 1m bars
        ├── confirmed 5m bars
        └── validated ResolvedContractSegment
        │
        ▼
现有 JDJ Context + Candidate Reducers
        │
        ▼
run_jdj_reference_segment(
  symbol,
  segment,
  bars/contexts/events,
  multiplier,
  session terminal,
  frozen config
)
        │
        ▼
reference-only JdjAction[]
        │
        ▼
现有 Web marker projection
```

不新增：

- Strategy base/plugin framework；
- batch active60 Strategy API；
- Portfolio Engine；
- worker/queue/scheduler；
- Strategy DB；
- per-product strategy config；
- second active universe；
- second dominant resolver；
- tick/margin/commission execution model。

“支持 active60”精确定义为：**现有单产品 endpoint 可以对当前 active universe 任意 symbol 使用同一 Strategy V1 replay。** 不是一次请求计算 60 品种。

## 5. Strategy Profile Contract V2

`data/strategy_profiles/jdj_v1.json` 升级 exact schema：

```json
{
  "schema_version": 2,
  "strategy_id": "jdj_intraday_futures_v1",
  "core_rules": {
    "minimum_reward_risk": "2.0",
    "max_planned_trade_risk_fraction": "0.01",
    "require_profit_before_add": true,
    "require_partial_profit_before_add": true,
    "add_fraction_of_current_qty": "0.25",
    "max_add_count": 2,
    "losing_position_add_forbidden": true,
    "daily_pause_drawdown_fraction": "0.005",
    "daily_pause_bars": 15,
    "daily_stop_drawdown_fraction": "0.01"
  },
  "profiles": {
    "jdj_active60_1m_v1": {
      "product_scope_source": "active_products",
      "series_kind": "actual_dominant",
      "execution_frequency": "1m",
      "trend_context_frequency": "5m",
      "base_risk_fraction": "0.005",
      "first_profit_take_fraction": "0.40",
      "historical_reference_start_equity": "1000000",
      "entry_limit_valid_bars": 1,
      "terminal_flatten_lead_bars": 1
    }
  }
}
```

冻结规则：

- `_DEFAULT_PROFILE_ID = "jdj_active60_1m_v1"`；
- 删除 `JdjStrategyProfile.symbol`；
- 新增 `product_scope_source: str`，只允许 exact `active_products`；
- 不把 60 个 symbol 复制进 profile；
- 不保留长期 `jdj_jm_1m_v1` compatibility profile；
- 不增加 profile 选择 HTTP 参数；
- Core values 逐值保持当前 V1；
- profile id 当前不进入 public action identity，内部 id 变化不得导致 JM public replay action 漂移。

## 6. Request、Service Admission 与错误合同

### 6.1 Request 只验证静态形状

`JdjStrategyReplayRequest` 继续验证：

```text
series_kind == actual_dominant
frequency   == 1m
symbol      == trimmed lowercase non-empty str
since/through are exact date
since <= through
```

Request 不读文件、不查 DB、不判断 active membership。

### 6.2 Service 注入当前 active universe

构造：

```python
JdjStrategyReplayService(
    segment_loader,
    *,
    products: tuple[str, ...],
    jdj_policy: JdjPolicy,
    n_policy: NStructurePolicy,
    contract_multiplier_for_contract: ...,
    terminal_bar_ends_for_segment: ...,
    config: JdjV1Config | None = None,
)
```

`products` 由 composition 的 `load_active_products()` 一次注入。Service 不维护第二份 allowlist。

`history()` 在调用 loader 前先判断 `request.symbol in products`。非 active product：

```text
JDJ_STRATEGY_PROFILE_UNAVAILABLE
```

不得访问 Historical。

### 6.3 HTTP error matrix

| 情况 | HTTP | code |
|---|---:|---|
| 非 `actual_dominant` / 非 `1m` / 非法窗口 | 422 | `JDJ_STRATEGY_PROFILE_UNAVAILABLE` |
| symbol 不是当前 active product | 422 | `JDJ_STRATEGY_PROFILE_UNAVAILABLE` |
| active universe 文件/合同损坏 | 409 | `ACTIVE_UNIVERSE_INVALID` |
| Strategy profile/policy/context fact 无效 | 409 | `JDJ_STRATEGY_CONTEXT_INVALID` |
| dominant segment identity 无效 | 409 | `JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID` |
| session terminal identity 无效 | 409 | `JDJ_STRATEGY_SESSION_IDENTITY_INVALID` |

Route 必须在 **service.history() 调用周围** 捕获 `JdjStrategyProfileUnavailableError`，不能只在 request construction 阶段捕获。

## 7. Composition：按 symbol 动态解析市场事实

`build_jdj_strategy_replay_service(session)` 仍返回一个 service，但不得预先固定任一品种。

### 7.1 `exchange_for_symbol(symbol)`

局部 helper 通过 `Instrument` 查询：

```text
Instrument.symbol == symbol
Instrument.is_active == true
-> exactly one non-empty exchange_code
```

失败统一为 `JDJ_STRATEGY_CONTEXT_INVALID`。

### 7.2 Multiplier callback

```python
contract_multiplier_for_contract(*, symbol: str, contract: str) -> Decimal
```

每次调用先 `exchange_for_symbol(symbol)`，再验证唯一 `Contract`：

```text
contract_code == contract
instrument_symbol == symbol
exchange_code == exchange_for_symbol(symbol)
contract_multiplier is positive int
```

不得按 contract code 单独取 multiplier 后跳过 owner/exchange 校验。

### 7.3 Session terminal callback

```python
terminal_bar_ends_for_segment(
    *,
    symbol: str,
    bars_1m: Sequence[CanonicalBar],
) -> Mapping[date, datetime]
```

每次调用根据 `exchange_for_symbol(symbol)` 和当前 `symbol` 调 `resolved_session_windows_for_trading_day()`。

每个 trading day 的最后 session end 必须精确存在于当前 segment 的 1m Bars；否则 `JDJ_STRATEGY_SESSION_IDENTITY_INVALID`。

### 7.4 不提前抽象 Repository

以上 resolver 可以继续留在 `app.research.composition` 的窄 builder 内。只有第二个真实消费者需要同一组合事实时才重新评估抽象；本阶段不新建 Instrument Facts Repository。

## 8. Replay：显式 validated segment identity

目标签名：

```python
def run_jdj_reference_segment(
    *,
    symbol: str,
    segment: ResolvedContractSegment,
    bars_1m: Sequence[CanonicalBar],
    contexts: Sequence[JdjBarContext],
    candidate_events: Sequence[JdjTriggerEvent],
    contract_multiplier: Decimal,
    terminal_bar_end_by_day: Mapping[date, datetime],
    config: JdjV1Config,
) -> JdjReferenceReplay:
    ...
```

### 8.1 输入校验

必须验证：

- `symbol` 是非空 normalized str；
- `segment` 是 `ResolvedContractSegment`；
- 所有 1m Bars 的 `trading_day` 都在 segment start/end 内；
- Candidate Event 的 `symbol/contract/segment_start_trading_day/trading_day` 与显式 identity 一致；
- Context 中使用的 pivot/fact identity 与 `segment.contract + segment.start_trading_day` 一致；
- terminal map 与 bars trading days exact 对齐；
- multiplier 为正 finite `Decimal`。

任一不一致 fail-closed。

### 8.2 删除 fake identity

删除 `_context_segment_identity()` 对 `JM0000 / date.min` 的 fallback。

无 Candidate Event、无 eligible pivot 的合法 segment 仍可以返回空 actions；identity 始终来自 `segment`，不能用假 contract 表示“没有事件”。

### 8.3 不改变 Action identity 算法

本阶段不新增 symbol 到现有 action hash，也不重写 `event_id/episode_id` 算法。现有 source Candidate identity 已包含 symbol/contract/segment identity。

若 golden 发现真实 collision 或不可避免的 identity 变化，必须停止本任务，而不是在 active60 扩展中顺手 version bump。

## 9. API 与 Web Contract

Endpoint 保持：

```text
GET /api/v1/market/research/jdj-strategy/history
```

Request：

```text
series_kind=actual_dominant
symbol=<current active product>
frequency=1m
since=YYYY-MM-DD
through=YYYY-MM-DD
```

Response shape 不变：

```text
request
reference_execution=true
actions[]
```

不新增 profile 参数、strategy 参数、batch products、PnL summary、score/rank、OOS、recommendation 或 promotion 字段。

Web 当前已经把图表 `symbol` 原样传给 strategy endpoint，因此不增加“策略品种选择器”。目标行为：

```text
jm -> 1m -> 日进斗金策略 -> JM reference markers，且与扩展前一致
rb -> 1m -> 日进斗金策略 -> RB reference markers
cf -> 1m -> 日进斗金策略 -> CF reference markers
sc -> 1m -> 日进斗金策略 -> SC reference markers
```

Web 继续：

- 只支持 `actual_dominant + 1m`；
- 使用 generation/full identity 防旧响应；
- 只把 `ENTRY/ADD/REDUCE/EXIT` 且具有 `effective_bar_end + reference_price` 的 action 画成成交 marker；
- rejected/daily_pause/daily_stop 不画成交 marker；
- TypeScript 不计算 Candidate、EMA/N、R:R、仓位、stop、target 或 PnL。

如果没有现存 JM-only 前端逻辑，生产 Web 源码应保持不改，只补自动化测试；不得为了“active60”新造 capability registry。

## 10. Active Universe 与未来 OOS 的职责分离

```text
active_products.txt
= 当前产品 UI / replay admission scope

future prospective OOS protocol
= exact versioned product universe + schedule + evidence identity
```

两者不能互相替代。

因此：

- 当前 active file 新增/删除品种会改变“今天哪些 symbol 可以查看 replay”；
- 不自动改变 `jdj_intraday_futures_v1` Core；
- 不允许把新增品种的历史 retrospective 回填进已有 prospective OOS；
- 未来 Strategy/OOS freeze 时需另行冻结 exact universe，不依赖本 profile 的动态 membership。

## 11. JM Parity Hard Gate

### 11.1 先冻结 golden，再改 production code

第一任务只新增：

```text
services/quant-api/tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json
services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
```

Golden 必须由当前 `develop` 的 JM-only implementation 在任何 Strategy production file 修改前生成，并在同一 test-only commit 中锁定。

Golden 至少覆盖当前 deterministic fixture 能产生的完整 action projection，逐 action 保存：

```text
event_id
episode_id
kind
source_event_ids
primary_setup
supporting_setups
direction
contract
trading_day
segment_start_trading_day
decision_at
effective_bar_end
reference_price
quantity
position_quantity_after
stop_price
target_price
reward_risk
reason
fill_basis
```

测试还必须比较 action 顺序。

### 11.2 扩展后不允许再生成 golden

之后所有 active60 任务只运行该 parity test。JM 任一字段变化即失败。

如果确有必要改变 JM 语义，结论只能是“阶段一阻塞，另开 Strategy semantics change”，不能更新 golden 让测试变绿。

## 12. Active60 自动化验收

### 12.1 Service admission

至少验证：

- `products=("jm","rb","cf","sc")` 时四者均可进入同一 service；
- non-active `xx` 在调用 loader 前被拒绝；
- 同一 service 实例顺序处理不同 symbol 不保留前一 symbol 状态。

### 12.2 Cross-exchange composition

至少覆盖：

- DCE：`jm`；
- SHFE：`rb`；
- CZCE：`cf`；
- INE：`sc`。

它们只是样例，不形成第二份 allowlist。

验证：

- exchange 由当前 symbol 解析；
- contract owner + exchange exact match；
- multiplier 取当前 physical contract；
- terminal session 取当前 symbol；
- owner/exchange/multiplier/session 任一不完整都 fail-closed。

### 12.3 Replay identity

验证：

- no-event segment 不再产生 `JM0000`；
- no-pivot segment 不使用 `date.min`；
- event symbol/contract/segment mismatch fail-closed；
- bars 超出 segment window fail-closed；
- segment 之间 episode/state 不泄漏。

### 12.4 HTTP / Web

验证：

- JM public response 与 marker golden 不漂移；
- 至少一个非 JM active symbol HTTP 200；
- non-active 返回 422 profile unavailable；
- active universe invalid 返回 409；
- context/segment/session typed 409 保持；
- response request identity exact match；
- 切换 symbol 后旧请求不污染新图。

## 13. Full active60 read-only capability smoke

自动化测试和独立 Review 通过后，对完整当前 active universe 做一次只读 capability smoke。

固定窗口：

```text
series_kind = actual_dominant
frequency   = 1m
since       = 2026-08-18
through     = 2026-08-20
```

该窗口止于已冻结 retrospective `through=2026-08-20`，不读取 `2026-08-21` embargo，也不触碰 `2026-08-24+` prospective OOS。

规则：

- 由仓库外层 shell loop 逐行读取 `data/universe/active_products.txt`；
- 不新增 repository batch module/script/CLI；
- 每个 symbol 只调用现有单产品 read-only replay 路径；
- 允许 `0 actions`；
- source/coverage/session/multiplier unavailable 必须保留 typed code；
- command failure 必须保留 symbol + status，不静默跳过；
- 不因 unavailable 缩小 active60 后宣称全量通过；
- 不输出 PnL/rank/winner/KEEP/DROP/PROMOTE；
- 不调参；
- 不写 Canonical/DB/Redis；
- 不生成 Candidate/OOS evidence artifact；
- 不运行 RQAlpha sidecar 或真实 Bundle。

该 smoke 只证明 **当前 active products 能否通过同一 replay contract 被确定性处理或显式 fail-closed**。它不证明策略适配性、盈利能力、泛化能力或 OOS 通过。

## 14. 文件边界

预期 implementation 主要修改：

```text
data/strategy_profiles/jdj_v1.json
services/quant-api/app/research/jdj_strategy/contract.py
services/quant-api/app/research/jdj_strategy/replay.py
services/quant-api/app/research/jdj_strategy/service.py
services/quant-api/app/research/composition.py
services/quant-api/app/research/historical_overlay_api.py
services/quant-api/tests/research/test_jdj_strategy_contract.py
services/quant-api/tests/research/test_jdj_strategy_engine.py
services/quant-api/tests/research/test_jdj_strategy_replay_service.py
services/quant-api/tests/research/test_jdj_strategy_jm_parity.py
services/quant-api/tests/research/fixtures/jdj_jm_1m_v1_reference_golden.json
services/quant-api/tests/test_research_composition.py
services/quant-api/tests/test_market_research_overlays_api.py
apps/quant-web/tests/historicalResearchMarkers.test.ts
apps/quant-web/e2e/market-research.spec.mjs
PROJECT_SOURCE.md
AGENTS.md
TESTING.md
STATUS.md  # 仅在 implementation + tests + read-only capability smoke + independent Review 全部成立后更新
```

原则上不改：

```text
app/research/jdj/** Candidate reducers
app/research/n_structure/**
apps/quant-web/src/**  # 除非测试证明存在 JM-only bug
Alert / Execution Review / Runtime / DB models / migrations
RQAlpha backtest workbench
```

如果实现需要修改上述原则上不改的策略公式或建立新基础设施，视为 scope expansion，必须停止并重新设计。

## 15. 验证顺序

实现必须按以下 Gate 顺序：

```text
Gate A  JM golden frozen before production edits
  ↓
Gate B  explicit segment identity + existing JM tests + golden parity
  ↓
Gate C  profile/service active admission
  ↓
Gate D  cross-symbol exchange/multiplier/session composition
  ↓
Gate E  HTTP + Web identity tests
  ↓
Gate F  full affected backend/Web validation
  ↓
Gate G  independent Review
  ↓
Gate H  fixed-window active60 read-only capability smoke
  ↓
Gate I  STATUS/develop completion readback
```

Gate H 不授权 RQAlpha、Runtime、通知或任何写入。

## 16. 禁止范围

阶段一明确禁止：

- 修改三个 JDJ Candidate 公式；
- 按品种调 Strategy 参数；
- 波动率/tick/margin 自适应参数；
- 新 Entry setup；
- 60 品种排名或收益比较；
- 参数优化；
- prospective OOS 消费、回填或重建；
- JDJ Alert；
- Runtime 接入；
- DB/Redis/Canonical 写入；
- RQAlpha Strategy adapter / 真实 smoke；
- 正式 backtest engine；
- 自动交易、账户、订单或持仓管理；
- main/tag/release/Runtime promotion。

## 17. Lane 与人工 Gate

后续实现属于 **Lane 3**：改变 Strategy Reference Replay 的品种适用身份，同时触及 contract multiplier、session terminal、causal segment identity 和 JM parity。

固定调度：

```text
模型：Sol
推理强度：高
会话：新会话
Plan：Plan-only
工作区：从 develop 创建独立 task branch/worktree
Review：独立 Review 会话
人工 Gate：Plan 批准 + 独立 Review
```

批准实现后，代码满足测试与 Review 可以进入 `develop`；这不授权 main/tag/release、Runtime promotion、真实通知、正式数据写入或 OOS promotion。

## 18. Definition of Done

阶段一只有同时满足以下条件才完成：

1. JM golden 在 production code 修改前已经 test-only commit 冻结；
2. Strategy Core 与三个 JDJ Candidate 公式零变化；
3. profile V2 只有 `jdj_active60_1m_v1`，无 symbol/per-product override；
4. current active membership 只来自 `load_active_products()`；
5. `JdjStrategyReplayRequest/Service` 支持当前 active 任意单产品 `actual_dominant + 1m`；
6. composition 不再持有 JM 专用 exchange/multiplier/session 状态；
7. replay 复用显式 `ResolvedContractSegment`，完全删除 `JM0000/date.min` fallback；
8. JM golden projection exact parity 全通过；
9. cross-exchange 自动化测试通过；
10. HTTP 422/409 typed error matrix 通过；
11. Web 不增加复杂 UI，当前 symbol 直接查看 strategy markers；
12. reference price/quantity 仍明确是 research reference，不冒充 tick/margin/fees 意义上的可执行成交；
13. affected Backend tests、Ruff、Mypy、Web unit、Playwright、Web build 与 secret scan 全通过；
14. 独立 Review 无阻塞问题；
15. 固定 `2026-08-18..2026-08-20` active60 read-only capability smoke 完整保留每个 symbol 的 success/typed unavailable，不缩集、不调参、不排名；
16. `PROJECT_SOURCE.md` / `AGENTS.md` / `TESTING.md` 与真实实现同步；仅在以上全部成立后更新 `STATUS.md`；
17. 未触发 DB/Canonical/Redis 写入、prospective OOS、Alert、Runtime、RQAlpha sidecar 或订单能力。

阶段一完成后的唯一准确表述是：

> **同一个冻结的 `jdj_intraday_futures_v1` 可以对当前 active universe 中任意产品的 `actual_dominant 1m` confirmed Historical 数据执行 deterministic reference replay，并在现有 Market 主图显示 reference markers；JM 既有 public replay 行为保持 exact parity。**

不得表述为“active60 策略已盈利”“已验证有效”“已 OOS 通过”“可实盘”“可晋升”或“Runtime-ready”。
