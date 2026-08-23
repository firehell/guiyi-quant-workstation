# 日进斗金 Active60 1m Strategy Replay 设计

更新时间：2026-08-24  
状态：Design approved；本文件只冻结阶段一设计，不授权代码实现、真实 RQAlpha smoke、prospective OOS 消费、Alert/Runtime、main/tag/release、正式数据写入或订单能力。

## 1. 当前事实与阶段一问题

当前 `develop` 已完成日进斗金 JM 1m 的完整、research-only deterministic reference replay：

```text
strategy_id = jdj_intraday_futures_v1
profile_id  = jdj_jm_1m_v1
symbol      = jm
series_kind = actual_dominant
execution   = 1m
trend       = 5m
```

现有链路已经具备：

- 三类冻结 JDJ Candidate Entry：
  - `jdj_trend_follow_1m_candidate_v1`
  - `jdj_trend_reentry_6_1m_candidate_v1`
  - `jdj_key_level_breakout_1m_candidate_v1`
- Entry authorization、最低 R:R、以损定量、部分止盈、最多两次盈利加仓、保护位、日内 pause/stop、session flatten；
- `MarketDataService -> ActualDominantResearchSegmentLoader` 的 confirmed Historical 主力分段；
- `/api/v1/market/research/jdj-strategy/history`；
- Market 主图中的 `ENTRY/ADD/REDUCE/EXIT` reference marker；
- `reference_execution=true`，且不进入 DB、Redis、Alert、Execution Review、Runtime 或订单路径。

阶段一的缺口不是 JDJ Candidate 公式，也不是交易管理规则，而是 **Strategy Replay 的产品身份仍被 JM 写死**：

- `data/strategy_profiles/jdj_v1.json` 只有 `jdj_jm_1m_v1`，且 profile 内含 `symbol=jm`；
- `JdjStrategyReplayRequest` 只接受 `jm + actual_dominant + 1m`；
- `build_jdj_strategy_replay_service()` 从 composition 层绑定 `symbol = "jm"`；
- exchange、contract multiplier 与 trading session resolver 都按 JM 写死；
- replay 在缺少 event/pivot 身份时仍存在 `JM0000 / date.min` fallback。

与此同时，仓库已经有唯一 active universe `data/universe/active_products.txt`，当前为 active60；三个 JDJ Candidate 的 active60 robustness protocol 也已冻结，且明确禁止按品种调参、参数扰动、自动排名和自动晋升。

因此阶段一只解决一个问题：

> **在不改变 JDJ V1 策略语义的前提下，把完整 Strategy Reference Replay 从 JM 扩展为 active60 的任意单品种 1m 主力历史回放。**

## 2. 核心决策

采用方案 A：**单一 JDJ V1 + active60 动态准入 + 禁止品种级策略参数 override**。

目标合同：

```text
strategy_id     = jdj_intraday_futures_v1
profile_id      = jdj_active60_1m_v1
product_scope   = active_products
series_kind     = actual_dominant
execution       = 1m
trend_context   = 5m
strategy_rules  = globally frozen
product facts   = resolved from Catalog / Session facts
```

最重要的边界是：

> **品种是输入身份，不是策略参数。**

active60 中每个产品允许不同的只有市场客观事实，例如：

- exchange；
- physical contract；
- contract multiplier；
- trading session；
- actual-dominant rank1 segment；
- Historical coverage / typed availability。

以下内容不得按品种分叉：

- `minimum_reward_risk`；
- planned trade risk 上限；
- `base_risk_fraction`；
- 首段止盈比例；
- 盈利后才允许加仓；
- 部分止盈后才允许加仓；
- add fraction；
- max add count；
- daily pause / stop；
- one-bar admissible limit；
- terminal flatten lead；
- Candidate 公式、event identity、priority 或 reducer 语义。

阶段一不建立 60 份 Strategy Profile，也不增加任何 product override 表、JSON map 或动态参数 API。

## 3. 事实来源与不改动边界

### 3.1 仓库 canonical

实现时优先遵守：

1. `STATUS.md`：当前 release、Runtime、evidence 与 pending Gate；
2. `AGENTS.md`：工程硬规则和外部操作边界；
3. `docs/DEVELOPMENT.md`：个人开发流程；
4. `PROJECT_SOURCE.md`：稳定产品、数据和 Research 边界；
5. `DECISIONS.md`：长期决策；
6. 当前 JDJ/N policy、reducers、Strategy profile/replay tests。

### 3.2 JDJ Entry Setup 不重写

阶段一继续直接复用现有三类 Candidate reducer。以下语义必须保持不变：

- source timeframe=`1m`；
- trend context=`5m`；
- EMA20 当前 seed / rounding / close input；
- 5m N Structure strict-before；
- same trading day / same physical contract / same rank1 segment；
- previous-bar dynamic trigger；equal 不算 breach；
- Trend Follow / Trend Reentry 6 / Key Level Breakout 当前 reducer 语义；
- Candidate event id、direction、`observed_at`、trigger level、source event kind。

不得因为 active60 扩展重新解释《股票日内交易入门》、`交易系统.pdf`、`交易理念.pdf`、`资金管理.pdf` 等材料来改写已经冻结的 Entry 公式。

### 3.3 Trade Management 不重定参数

当前完整策略中已经机械化的交易管理继续原样使用。其原始材料包括《股票日内交易入门》中关于盈亏比、风险管理、订单管理、加仓和每日最大亏损的章节，以及用户整理的交易系统材料中“顺势、止损、盈利后加仓、分段止盈”等规则。

阶段一的任务不是重新从原始材料推导参数，而是验证：**同一组已冻结规则能否以同一实现安全作用于 active60。**

因此本阶段不讨论新的最佳参数，不使用 active60 历史表现反向修改 Strategy Core。

## 4. 目标架构

阶段一保持窄链路，不建设通用 Strategy Framework：

```text
Market Web 当前 symbol
        │
        ▼
GET /api/v1/market/research/jdj-strategy/history
        │
        ▼
JdjStrategyReplayRequest
  - normalize symbol
  - actual_dominant + 1m only
        │
        ▼
JdjStrategyReplayService
  - active_products admission
  - exact JDJ/N policy
        │
        ▼
ActualDominantResearchSegmentLoader
        │
        ├── confirmed 1m bars
        ├── confirmed 5m bars
        └── validated physical rank1 segments
        │
        ▼
现有 JDJ Context + Candidate Reducers
        │
        ▼
run_jdj_reference_segment(
  explicit symbol + contract + segment identity,
  dynamic multiplier,
  dynamic session terminal
)
        │
        ▼
reference-only JdjAction[]
        │
        ▼
现有 Web marker projection
```

不新增：

- Strategy Base class；
- plugin registry；
- batch active60 Strategy endpoint；
- Portfolio Engine；
- worker / queue / scheduler；
- Strategy DB；
- per-product config；
- second active universe；
- second dominant resolver。

“支持 60 品种”指：**同一个单品种 endpoint 可以对 active60 任意当前 symbol 执行同一 Strategy Replay**，不是一次请求批量计算 60 个品种。

## 5. Strategy Profile Contract

### 5.1 Profile 从 JM 身份改为 active60 scope

`data/strategy_profiles/jdj_v1.json` 进入新的 exact contract shape。建议使用：

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
      "product_scope": "active_products",
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

关键规则：

- 删除 profile 的 `symbol` 字段；
- 不把 60 个 symbol 复制进 Strategy profile；
- `product_scope="active_products"` 只声明准入来源，实际产品集合仍唯一读取 `data/universe/active_products.txt`；
- 不保留长期 `jdj_jm_1m_v1` compatibility profile；
- 不暴露 profile 选择 API；仍只有一个 JDJ V1 active profile。

该 profile id 不在当前 HTTP response 中公开，因此内部 profile identity 变化不得改变 JM 既有 public replay action。

## 6. Request 与 active60 准入

### 6.1 Request 只做输入形状标准化

`JdjStrategyReplayRequest` 继续要求：

```text
series_kind = actual_dominant
frequency   = 1m
since <= through
symbol      = trimmed lowercase non-empty string
```

Request dataclass 不自行加载 active universe，避免 domain object 产生文件系统依赖。

### 6.2 Service 做 active universe admission

`JdjStrategyReplayService` 构造时由 composition 注入一次 `products=load_active_products()` 的不可变 tuple。

`history(request)` 在读取 Historical 前先验证：

```text
request.symbol in products
```

不在 active universe：

```text
JDJ_STRATEGY_PROFILE_UNAVAILABLE
HTTP 422
```

active 产品但 Historical / Catalog / segment / session 事实不完整：保持当前 409 类 fail-closed 语义，不能降级成其它 dataset、其它 frequency 或 continuous。

## 7. Composition：去除 JM 写死

`build_jdj_strategy_replay_service(session)` 不再绑定 `symbol="jm"`。

### 7.1 Exchange resolver

根据传入 `symbol` 从 `Instrument` 查询唯一 active exchange：

```text
Instrument.symbol == symbol
Instrument.is_active == true
-> exactly one non-empty exchange_code
```

0 行、多行或无效字段均 fail-closed 为 Strategy context invalid。

### 7.2 Contract multiplier resolver

按当前 physical contract 查询 `Contract`，并验证：

```text
contract_code == requested contract
instrument_symbol == request symbol
exchange_code == resolved exchange
contract_multiplier is positive int
```

不得仅凭 `contract_code` 找到 multiplier 后跳过 owner/exchange identity 校验。

### 7.3 Session terminal resolver

`resolved_session_windows_for_trading_day(...)` 必须使用当前：

```text
exchange = exchange_for(symbol)
symbol   = request.symbol
```

每个 trading day 的 terminal 必须精确对应当前 segment 的 1m Bar；无法解析时保持 `JDJ_STRATEGY_SESSION_IDENTITY_INVALID`。

### 7.4 个人项目复杂度约束

本阶段不为上述三项新建通用 Instrument Facts Repository。可以在 composition 中使用少量局部 resolver / helper；只有后续第二个真实消费者出现后才考虑抽象。

## 8. Replay：显式 Segment Identity，删除 JM fallback

当前 replay 在没有 Candidate Event / eligible pivot 时可以回退到：

```text
contract = JM0000
segment_start = date.min
```

这在 active60 下属于错误身份，必须删除。

### 8.1 新的 segment replay 输入

`run_jdj_reference_segment(...)` 必须由 Service 显式传入已经由 loader 验证的：

```text
symbol
contract
segment_start_trading_day
segment_end_trading_day
```

并与：

- 1m Bars；
- 5m-derived contexts；
- Candidate Events；
- session terminal；
- multiplier

做一致性校验。

### 8.2 无事件 / 无 pivot 仍然是合法空结果

一个有效 physical segment 可以没有 Candidate Event，也可以在 warm-up 期间没有 eligible pivot。

这种情况下：

- segment identity 仍来自 loader；
- replay 返回空 action 或仅真实可形成的 risk/action；
- 不构造假 contract；
- 不使用 `date.min`；
- 不把 identity unavailable 伪装成“无信号”。

### 8.3 Action identity 不为 active60 重新设计

不增加新的 action identity 算法，不因为加 `symbol` 字段而重算现有 JM `event_id` / `episode_id`。

现有 action identity 已从 Candidate source event / episode / physical contract 链接到产品身份。只要没有真实碰撞证据，不新增 identity version。

这是保证 JM parity 的必要边界。

## 9. API Contract

Endpoint 保持：

```text
GET /api/v1/market/research/jdj-strategy/history
```

Request 保持：

```text
series_kind=actual_dominant
symbol=<active product>
frequency=1m
since=YYYY-MM-DD
through=YYYY-MM-DD
```

Response shape 保持：

```text
request
reference_execution = true
actions[]
```

阶段一不新增：

- profile 参数；
- strategy 参数；
- batch products；
- PnL summary；
- score/rank；
- OOS status；
- recommendation；
- promotion status。

非 active product 使用 `422 / JDJ_STRATEGY_PROFILE_UNAVAILABLE`；已准入但事实不完整继续使用当前 typed 409 errors。

## 10. Web Contract

现有 Web 已把当前图表 `symbol` 原样传给 `getJdjStrategyHistoricalActions()`，并且 overlay capability 已固定为：

```text
jdj_strategy
series_kind = actual_dominant
frequency = 1m
```

因此阶段一不重新设计 UI，也不增加“策略品种选择器”。

目标行为：

```text
rb -> 1m -> 日进斗金策略 -> rb reference markers
ag -> 1m -> 日进斗金策略 -> ag reference markers
jm -> 1m -> 日进斗金策略 -> 与扩展前相同的 jm markers
```

Web 只需要完成必要的 contract/test 对齐：

- 非 JM active symbol 不再被后端 `PROFILE_UNAVAILABLE` 拒绝；
- stale generation / full identity 防旧响应逻辑保持；
- marker 仍只投影 `ENTRY/ADD/REDUCE/EXIT` 且要求非空 `effective_bar_end + reference_price`；
- rejected / daily_pause / daily_stop intent 不画成交 marker；
- 不在 TypeScript 计算 Candidate、EMA/N、R:R、仓位、止损或 PnL。

如果当前页面存在“仅 JM 可用”类提示，应删除或改为“仅 active60 的 actual_dominant 1m 可用”；不得增加复杂 capability registry。

## 11. JM Parity Hard Gate

active60 generalization 的第一验收条件不是“其它品种能跑”，而是 **JM 零漂移**。

实现时必须先在行为修改前冻结一个 JM golden projection。固定同一组现有 test fixture / Historical fixture 输入，至少覆盖：

- entry fill；
- limit expire；
- partial reduce；
- profitable add；
- add limit expire；
- protective / EMA20 / trend-context exit；
- daily pause；
- daily stop；
- session flatten；
- rejected source event；
- multi-segment / contract boundary。

扩展后，同一输入必须逐 action 比较以下字段完全一致：

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

还必须保持：

- action 顺序一致；
- Candidate event count / identity 一致；
- JM HTTP response 语义一致；
- JM Web marker count / time / label 一致。

任一 JM 行为变化都视为阶段一失败，除非单独立项为 Strategy semantics change；不得把变化混入 active60 扩品种任务。

## 12. Active60 验收

在 JM parity 通过后，再验收 active60。

### 12.1 Admission completeness

`load_active_products()` 当前完整集合中的每个 product 都必须：

- 可以构造合法 `actual_dominant + 1m` Strategy request；
- 进入同一个 `jdj_active60_1m_v1` profile；
- 不存在 per-product Strategy override。

active universe 外产品必须 fail-closed。

### 12.2 Cross-exchange tests

测试至少覆盖多个真实交易所类别，例如：

- DCE：`jm`；
- SHFE：`rb`；
- CZCE：`cf`；
- INE：`sc`。

这些 symbol 只作为测试样例，不构成新的 allowlist。

需要验证：

- exchange 按 symbol 解析；
- contract owner + exchange 一致；
- multiplier 使用当前 physical contract；
- terminal session 使用当前 symbol；
- segment identity 不跨 contract / trading day 泄漏。

### 12.3 Full active60 read-only smoke

实现和独立 Review 通过后，应使用当前 confirmed Canonical / MarketDataService 对完整 active60 做一次只读 smoke：

- 不写 Canonical / DB / Redis；
- 不消费 prospective OOS；
- 不生成 rank / winner / KEEP / DROP / PROMOTE；
- 不选择“表现最好”的产品或参数；
- 对 source/coverage/session/multiplier unavailable 显式记录 typed reason；
- 不因某品种 unavailable 而缩小 active60 集合后宣称全量通过。

该 smoke 的目标只证明 **同一 replay contract 的身份和可执行覆盖**，不证明盈利、有效性、可交易性或泛化能力。

## 13. 测试范围

未来实现至少更新 / 新增以下测试域：

### Backend contract

- profile schema v2 exact shape；
- `jdj_active60_1m_v1` 唯一 profile；
- core rule values 与当前完全一致；
- unknown profile / drifted profile fail-closed；
- profile 不含 symbol override。

### Request / Service

- active symbol accepted；
- non-active symbol rejected before Historical load；
- `series_kind != actual_dominant` rejected；
- `frequency != 1m` rejected；
- invalid date range rejected；
- same service instance 可顺序处理不同 symbols，不残留上一个 product state。

### Composition

- unique active Instrument exchange；
- invalid/missing Instrument fail-closed；
- Contract owner mismatch fail-closed；
- Contract exchange mismatch fail-closed；
- missing/non-positive multiplier fail-closed；
- current symbol session resolution；
- missing/ambiguous terminal fail-closed。

### Replay identity

- explicit segment identity；
- no-event segment 不生成 fake JM identity；
- no-pivot segment 不使用 `date.min`；
- event contract / segment mismatch fail-closed；
- cross-segment memory 不泄漏。

### JM parity

- frozen golden projection exact equality。

### HTTP

- `jm` 仍成功；
- 至少三个其它 active products 成功；
- non-active 返回 422 profile unavailable；
- context/segment/session failures 保持 409 typed error；
- response request identity 与请求 exact match。

### Web

- 当前非 JM active symbol 会发出对应 `symbol` 的 strategy request；
- response identity mismatch 不渲染；
- 切品种时旧请求不能污染新图；
- Strategy marker 过滤规则不变；
- JM marker golden 不漂移。

## 14. 风险与禁止范围

### 14.1 最大风险：借扩品种偷偷改策略

禁止因为某些商品波动率、tick、乘数或 session 不同而修改 Strategy Core 参数。市场差异通过真实 contract facts 和价格数据自然进入计算，不通过 per-product strategy parameter 进入。

### 14.2 active60 不等于 60/60 必须产生交易

某品种可以合法得到：

- 0 Candidate；
- 0 Entry；
- 0 reference fill；
- typed Historical unavailable。

不得为了“有结果”放松 Candidate、R:R、risk、session 或 identity Gate。

### 14.3 不消费 prospective OOS

`STATUS.md` 当前 SuBing、N、JDJ prospective OOS 仍独立 pending。阶段一只扩 replay capability，不读取、标记、比较或回填 prospective OOS。

### 14.4 不进入 Alert / Runtime

阶段一不增加 JDJ Alert Rule，不把 reference action 当正式 Event，不接 PushPlus，不接 Market Runtime，不创建自然事件，不改变任何 production Scope。

### 14.5 不恢复通用 backtest 平台

这仍是 Historical reference replay，不新增正式 backtest engine、worker、queue、portfolio、strategy adapter 或 DB lineage。

RQAlpha 工作台继续与该链路隔离；本阶段不把 active60 replay 接入真实 RQAlpha smoke。

### 14.6 不发布

阶段一代码完成并合入 `develop` 也不自动授权：

- `main`；
- annotated tag；
- release；
- Runtime promotion；
- 真实通知；
- 正式数据写入。

## 15. 实施边界与 Lane

后续实现属于 **Lane 3**，原因是它改变策略 reference replay 的适用品种身份，并触及策略/回放可信口径、contract multiplier、session terminal 和 causal segment identity。

实施要求：

```text
模型：Sol
推理强度：高
会话：新会话
Plan：Plan-only -> 人工批准 -> 实现
工作区：从 develop 创建独立 task branch/worktree
Review：独立 Review 会话
```

普通代码在 Plan 和独立 Review 批准后可以合入 `develop`，但这不构成 release、Runtime、OOS 或真实外部操作授权。

## 16. Definition of Done

阶段一只有同时满足以下条件才算完成：

1. Strategy Core 与三个 JDJ Candidate 公式没有变化；
2. 唯一 Strategy profile 变为 active60 scope，不存在 product override；
3. `JdjStrategyReplayRequest/Service` 支持 active60 任意单产品 `actual_dominant + 1m`；
4. composition 不再出现 JM 专用 exchange/multiplier/session 绑定；
5. replay 显式接收 validated segment identity，彻底删除 `JM0000/date.min` fallback；
6. JM golden projection exact parity 全通过；
7. cross-exchange 自动化测试通过；
8. Web 不新增复杂 UI，当前品种即可直接查看 JDJ Strategy marker；
9. 完整 active60 只读 smoke 保留 unavailable，不缩集、不调参、不排名；
10. 不写 DB/Canonical/Redis，不消费 prospective OOS，不接 Alert/Runtime/订单；
11. 受影响 Backend tests、Ruff、Mypy、Web unit、Playwright、Web build 与 secret scan 全部通过；
12. 独立 Review 无阻塞问题后，才允许进入 `develop` 集成判断。

阶段一完成后的产品能力应精确表述为：

> **同一个冻结的 `jdj_intraday_futures_v1` 可以对 active60 中任意产品的 `actual_dominant 1m` confirmed Historical 数据执行 deterministic reference replay，并在现有 Market 主图显示 reference markers；JM 既有结果零漂移。**

不得表述为“active60 策略已盈利”“已验证有效”“已 OOS 通过”“可实盘”“可晋升”或“Runtime-ready”。
