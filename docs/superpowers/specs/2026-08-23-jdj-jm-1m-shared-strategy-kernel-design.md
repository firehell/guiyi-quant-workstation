# 日进斗金 JM 1m 轻量策略设计

更新时间：2026-08-23
状态：Review 后正式 Strategy Spec；授权后续代码实现，不授权真实 RQAlpha 回测、Runtime、通知、main/tag 或任何正式数据写入

## 1. 架构原则

> **先写业务逻辑，重复真实出现后再抽象；先满足个人研究闭环，不为未来多人、分布式、通用策略平台预建设。**

本项目是本地、单用户、个人开发维护的量化研究工作站。除通知最多涉及 owner + 三位朋友外，本策略相关能力只服务个人研究。因此 V1 不建设通用 Strategy Framework、插件系统、策略数据库、动态 Profile API、队列、Portfolio Engine 或提前的 Streaming Framework。

## 2. V1 目标

第一版只实现：

```text
strategy_id = jdj_intraday_futures_v1
profile_id  = jdj_jm_1m_v1
symbol      = jm
series_kind = actual_dominant
execution   = 1m
trend       = 5m
```

“完整策略”仅指：在现有三类 JDJ Candidate Entry 之上，补齐一笔交易从授权开仓、仓位、部分止盈、最多两次盈利加仓、保护位、日风险到退出的完整生命周期，并可在历史主力合约主图上做 deterministic reference replay。

V1 不把《股票日内交易入门》中的 VWAP、ABC、三角形、盘整突破、Trap、Camarilla 等其他 Entry 战法一次性塞入策略。

## 3. 事实来源与不改动边界

### 3.1 Entry Setup 继续复用当前仓库实现

V1 只使用现有：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

以下语义不得改变：

- source timeframe=`1m`；trend context=`5m`；
- EMA20 当前 seed / rounding / close input；
- 5m N Structure strict-before；
- same trading day / same physical contract / same rank1 segment；
- previous-bar dynamic trigger，equal 不算 breach；
- Trend Follow / Trend Reentry 6 / Key Level Breakout 当前 reducer 语义；
- Candidate event id、direction、`observed_at`、trigger level。

**V1 不迁移 `app/research/n_structure/**` 或 `app/research/jdj/**`。** 现有 JDJ/N Research 仍是 Entry 公式唯一实现。新的完整交易模块直接消费已有 Candidate event/context，不复制公式。

### 3.2 交易管理原始依据

本 Spec 只采用《股票日内交易入门》中能够确定机械化的规则：

- 书页 28～33：入场前明确止损和潜在盈利，通常只做盈亏比高于 2:1 的交易；
- 书页 34～37：单笔 planned risk 不超过账户总资金 1%，仓位受风险和资金共同限制；
- 书页 134～140：亏损仓禁止加仓；已有盈利并完成部分止盈后，前两次有效回到 20MA 的机会可各增加当前持仓约 1/4，第三、第四次不再加；
- 书页 141～143：当日亏损超过 0.5% 暂停 15 分钟，达到 1% 后停止当天继续交易。

书中 500 股先减 200、再减 200、保留 100 是示例，不足以证明所有交易都固定 40%/40%/20%。因此 V1 只把第一次 40% 减仓作为焦煤工程适配。

## 4. 最小架构

不新增 `app.strategy_kernel`。只新增一个窄模块：

```text
services/quant-api/app/research/jdj_strategy/
├── __init__.py
├── contract.py   # 一个配置文件的 exact contract + DTO
├── engine.py     # 交易生命周期与状态机
├── replay.py     # deterministic reference fills
└── service.py    # actual_dominant orchestration
```

依赖方向：

```text
现有 N/JDJ Research reducers
          ↓ Candidate events / contexts
app.research.jdj_strategy.engine
          ↓
reference replay / API / Web
```

硬约束：

- `jdj_strategy` 不重新计算第二套 EMA/N/JDJ Entry；
- 不创建 StrategyBase、plugin、optimizer、Portfolio、scheduler；
- 不创建数据库表或 migration；
- 不接 Alert、PushPlus、Execution Review、Runtime；
- 不修改现有 Candidate Research 的输出语义。

未来 RQAlpha 真正接入时，如果现有 batch reducer 无法直接复用，再针对实际重复点抽取最小 streaming primitive；本阶段不预建。

## 5. 单一配置合同

第一版只维护一个 Git 跟踪文件：

```text
data/strategy_profiles/jdj_v1.json
```

结构只分“核心交易规则”和“当前落地 Profile”，工程上不再维护两套 JSON/loader：

```json
{
  "schema_version": 1,
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
    "jdj_jm_1m_v1": {
      "symbol": "jm",
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

`contract.py` 使用现有 `exact_json_contract` 模式 fail-closed。V1 没有管理页面，也没有 profile discovery API。

核心规则不能通过 Web 或按品种参数覆盖。未来第二个周期真实出现时，再在同一文件新增 versioned profile；不自动按倍率缩放 1m 参数。

## 6. Candidate → Entry Authorization

Candidate 不自动成交：

```text
Candidate
→ 同 Bar 冲突处理
→ structural stop
→ 已知 target
→ R:R >= 2
→ admissible entry boundary
→ 日风险 / session gate
→ reference quantity
→ one-bar Entry Intent
→ fill 或 expire
```

### 6.1 同 Bar 冲突

- 同方向多个 Setup：只允许一个 intent；归因固定 `key_level_breakout > trend_reentry_6 > trend_follow`，其余作为 supporting setups；只用于 attribution，不代表策略排名。
- 同 Bar LONG/SHORT 同时出现：拒绝，`AMBIGUOUS_DIRECTION`。

### 6.2 Structural Stop

只使用 decision time 已知事实，V1 不额外加历史 tick buffer：

- Trend Follow：reaction Bar adverse extreme；
- Trend Reentry 6：event 中 frozen excursion extreme；
- Key Level Breakout：event 中 frozen key level。

Trend Follow 的 reaction Bar high/low 从当前 physical segment 的已有 1m bars 按 `reaction_at` 查找；找不到即 fail-closed。

### 6.3 Target

只允许 decision time 已知的 favorable level：

1. 同 physical segment、已 confirmed 的 favorable 5m N pivot；
2. 当前 trading day 截至 decision Bar 已知的 favorable 1m session high/low。

取距离 entry reference 最近的 favorable level 为 `target_1`。没有 target 则拒绝：`TARGET_UNAVAILABLE`。

### 6.4 R:R 与 one-bar limit

`entry_reference = Candidate.observation_close`。

```text
risk   = abs(entry_reference - stop)
reward = abs(target_1 - entry_reference)
R:R    = reward / risk
```

R:R < 2 拒绝。

为了避免下一根 Bar gap 后追价破坏 2:1，令 `r=2`：

```text
admissible_boundary = (target_1 + r * stop) / (1 + r)
```

- LONG：最多买到 `admissible_boundary`；
- SHORT：最低卖到 `admissible_boundary`；
- intent 只对紧随其后的一个 1m Bar 有效，之后过期。

Historical reference fill：

- LONG：next open <= limit 时按 open；否则 next low <= limit 时按 limit；否则过期；
- SHORT 对称；
- next-Bar high/low 只用于判断一个已经存在的 Limit Intent 是否能成交，不用于反推同 Bar 策略决策。

## 7. 参考仓位与 TradeEpisode

Historical Replay 不是完整账户模拟，只为了主图和交易生命周期提供确定参考。

固定：

```text
reference_start_equity = 1,000,000
reference_cost         = excluded
reference_margin       = not simulated
```

合约乘数必须来自项目现有受信任 Catalog/reference，不能在策略代码硬编码 `JM=60`。

基础手数：

```text
risk_cash = equity × 0.5%
per_contract_risk = abs(admissible_boundary - stop) × contract_multiplier
qty = floor(risk_cash / per_contract_risk)
```

`qty < 1` 不交易。任一新增仓动作的 planned worst-case risk 不得超过 equity × 1%。

每次实际 Entry fill 创建一个最小 `TradeEpisode`：

```text
episode_id
source_event_ids
consumed_source_event_ids
primary_setup / supporting_setups
direction
contract / trading_day / segment_start_trading_day
quantity / weighted_average_cost
protective_stop / target_1
partial_profit_taken
add_count
realized_pnl
```

未成交 intent 不创建 Episode；同一个 source event 不可重复消费。

## 8. 持仓管理

### 8.1 第一次部分止盈

- LONG completed 1m close >= target_1；SHORT 对称；
- 产生 Reduce decision，在下一合法 same-segment Bar open 做 reference fill；
- `take_qty=floor(current_qty × 0.40)`；0 手不制造假减仓；
- 实际减仓后 `partial_profit_taken=true`；
- protective stop 提高到当前 weighted average cost；
- `target_1` 只执行一次。

### 8.2 盈利加仓

不另造“碰 EMA20 就加仓”的第二套公式。ADD 必须由新的、未消费的同方向 `jdj_trend_follow_1m_candidate_v1` 完整 trigger event 驱动，并同时满足：

- 已实际部分止盈；
- Episode realized PnL > 0；
- `add_count < 2`；
- `add_qty=floor(current_qty × 0.25) >= 1`；
- one-bar limit 与 1% episode risk gate 再次通过。

ADD fill 后提高 protective stop 到 post-fill weighted average cost。第三次及以后禁止；亏损摊平永久禁止。

### 8.3 Exit

completed-Bar Exit 条件：

- LONG close <= protective stop / SHORT 对称；
- LONG close <= EMA20 / SHORT 对称；
- strict-prior 5m N trend 不再支持当前方向；
- daily stop；
- session terminal guard；
- physical segment 即将切换且仍有仓位。

普通 Exit 在下一合法 same-segment Bar open reference fill。V1 不模拟盘中 hard-stop 精确成交价。

## 9. 日风险与日内平仓

每个 trading day 从 reference equity 记录 `start_equity`，当前 equity 使用 reference realized + current-close mark-to-market，不计历史手续费/保证金。

- drawdown > 0.5%：禁止新 Entry/Add 15 个后续 in-session 1m bars；已有仓位仍正常管理；
- drawdown >= 1%：原始体系明确停止当天继续交易；JM V1 额外采用保守适配，产生退出 decision，并永久禁止当天 Entry/Add；
- 新 trading day 重置 daily pause/stop；
- 不跨 physical contract segment 传播 Episode 或 daily-risk 状态。

日内不隔夜：使用现有 TradingSession resolver，不硬编码 15:00。当当前 completed Bar 之后只剩最后一个本 trading day 可执行 1m Bar 时：

- 不再新开仓或加仓；
- 有仓位则生成 `SESSION_FLATTEN`，在最终 Bar open 完成 reference close；
- 中间休市不是 terminal。

## 10. Historical 数据合同

历史回放只走：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ validated physical-contract rank1 segments
→ existing JDJ/N Research
→ jdj_strategy engine/replay
```

要求：

- `actual_dominant` only；
- 不自行直接查 `MainContractMap` 选择主力；
- 不使用 continuous 替代真实主力；
- API `since` 位于 segment 中间时，仍从 loader 提供的真实 segment start warm up，只抑制 `since` 前输出；
- segment coverage/identity 异常 fail-closed；
- Replay 不写 Canonical、DB、Redis。

## 11. API 与 Web

第一版只有一个新 API，不做 Profile 管理接口：

```text
GET /api/v1/market/research/jdj-strategy/history
    ?series_kind=actual_dominant
    &symbol=jm
    &frequency=1m
    &since=YYYY-MM-DD
    &through=YYYY-MM-DD
```

仅 `jm + actual_dominant + 1m` 接受；其他品种/周期返回 `422 JDJ_STRATEGY_PROFILE_UNAVAILABLE`。

Market 主图新增独立 overlay：`日进斗金策略`，与现有 JDJ Candidate overlay 分开。

Marker：

```text
▲ / ▼ Entry
＋     Add
－     Reduce
×      Exit
```

Hover 最小展示：setup、contract、decision/effective time、qty、stop、target、R:R、reason，并明确“参考回放”。未成交 intent 不画成交 marker。

Web 不计算任何 EMA/N/R:R/仓位/PnL 逻辑；直接扩展当前 `useHistoricalResearchMarkers` / `historicalResearchMarkers` 路径，不再新建第二套 marker composable。

## 12. 后续周期和 RQAlpha

### 12.1 切换周期

未来真实需要 `5m/15m/...` 时：

1. 先研究并冻结该周期参数；
2. 在 `jdj_v1.json` 新增 versioned profile；
3. 后端和 Web 显式开放该周期。

没有 profile 时显示“该品种/周期尚未验证”。不做动态插件和自动倍率转换。

### 12.2 RQAlpha

RQAlpha Adapter **不属于本轮实现 Plan**。原因：当前 RQAlpha Workbench 代码尚未存在，提前建设 streaming/adapter 是 YAGNI。

Workbench 真正落地后另开独立 Lane 3 小任务：

```text
现有 JDJ/N Entry 公式
+ jdj_strategy.engine 交易管理
→ thin RQAlpha adapter
```

只有届时实际发现 batch reducer 无法满足 `handle_bar`，才抽取最小 streaming state，并做 batch/streaming parity；不提前迁移整个 N/JDJ Research。

## 13. 最小 Fail-Closed

V1 只需要稳定区分：

```text
JDJ_STRATEGY_PROFILE_UNAVAILABLE
JDJ_STRATEGY_CONTEXT_INVALID
JDJ_STRATEGY_TARGET_UNAVAILABLE
JDJ_STRATEGY_REWARD_RISK_TOO_LOW
JDJ_STRATEGY_POSITION_SIZE_ZERO
JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID
JDJ_STRATEGY_SESSION_IDENTITY_INVALID
```

不为第一版建设大而全的错误码体系。

## 14. 测试与验收

必须覆盖：

### Existing Candidate protection

- 现有 N/JDJ reducer/Research tests 全部继续通过；
- 新模块不得改写现有 Candidate event identity；
- strict-before、same-contract、same-segment 不变。

### Strategy engine

- R:R <2 / target unavailable reject；
- one-bar limit：better open / limit touch / expire；
- 0.5% base risk、1% episode cap；
- Episode/source-event 去重；
- 40% first reduce；
- first/second profitable add、third reject、losing add reject；
- protective stop move；
- 0.5% daily pause、15 in-session bars、1% daily stop；
- terminal guard；
- no intrabar stop/target favorable assumption。

### Historical Replay/API

- actual_dominant only；
- segment warm-up；
- no cross-contract state；
- prefix-invariant / stable event ids；
- unsupported symbol/frequency fail-closed；
- reference execution 标识清楚。

### Web

- Candidate / Strategy overlay 分开；
- `jm/1m` 正常显示；
- unsupported period 清除旧 marker 并显示 unavailable；
- prepend 去重、stale response 不泄漏。

## 15. 禁止范围

V1 不做：

- N/JDJ 目录迁移或通用 Shared Strategy Kernel 平台；
- 预建 streaming evaluator；
- RQAlpha adapter；
- profile discovery/管理页面；
- 第二套 marker composable；
- 苏冰、HTDY、其他 JDJ Entry setup；
- 其他品种或周期；
- 参数搜索、自动优化、Portfolio；
- OOS 自动消费、Candidate 自动晋升；
- Alert、PushPlus、Execution Review、Runtime；
- main/tag/release、真实订单或真实账户。

## 16. 完成定义

本轮只有同时满足以下条件才可声明完成：

1. 现有 JDJ/N Candidate 代码不搬迁、不复制，原测试全部通过；
2. `app/research/jdj_strategy/` 完成 JM 1m 交易生命周期；
3. `jdj_v1.json` 是唯一新增策略配置文件；
4. JM `actual_dominant` Historical Reference Replay 可由一个只读 API 返回；
5. Market 主图可独立显示“日进斗金策略”；
6. unsupported 品种/周期明确 unavailable；
7. 无 DB/Canonical/Redis/Alert/Runtime 写入；
8. 没有提前建设 RQAlpha/streaming/通用策略平台；
9. 所有结果保持 research-only，不产生正式 OOS、promotion 或交易结论。
