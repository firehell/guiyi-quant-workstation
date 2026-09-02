# 苏冰同花顺 15m 预警 V1 — Strategy Observation Spec

状态：`SPEC_READY_FOR_USER_REVIEW`

日期：2026-09-02

Issue：#307

规划基线：`develop@8a05ae1a3c8c25c56428874e00fa99260a4708e1`

任务车道：Lane 3

产品身份：`subing_ths_alert_15m_v1`

公式身份：`subing_ths_15m_v1`

---

## 1. 目的

本 Spec 定义一个全新的、最小化的苏冰预警产品。它只解决一个问题：

> 对 `operational_products.txt` 授权的国内期货品种持续盯盘；每根正式 completed 15m K 完成后，按用户正在同花顺期货通使用的 MACD + MA21 公式判断；出现信号时创建正式 AlertEvent、最多尝试一次 PushPlus，并在 Market Web 中显示，最终是否交易由用户人工判断。

稳定闭环只有：

```text
operational products
→ completed actual_dominant 15m
→ 同花顺公式
→ 苏冰多/空预警
→ immutable AlertEvent
→ one-shot PushPlus
→ Market Web
→ 用户人工判断
```

本产品不是交易策略执行系统，不模拟持仓，也不创建订单。

---

## 2. 与既有苏冰的关系

当前 active canonical 已退役既有策略域，并规定未来策略/观察产品必须使用新身份、新合同和新版本。

因此本任务：

- 不恢复 `subing_strategy_v1`；
- 不恢复旧 Daily Watch、5m/15m Factor、Lifecycle、Action、Episode、Position、Historical Strategy Projection、Strategy Runtime、Strategy Scope、Strategy API/CLI/Web 或派生 cache；
- 不继续旧 `subing_watch_15m_v1` Implementation Program；
- 不复用已退役策略模块作为隐藏实现；
- 只允许复用通用 MarketDataService、通用指标 primitive、Alert Application Domain、PushPlus transport 和 Market Web 基础设施。

本 Spec 与 Issue #307 是新的 active 设计 authority。Issue #286 及其旧 Watch 设计只保留 Git 历史语义，不再作为实现依据。

---

## 3. V1 产品身份

固定身份：

```text
public_name      = 苏冰预警
rule_code        = subing_ths_alert_15m_v1
formula_version  = subing_ths_15m_v1
kind             = indicator_observation
series_kind      = actual_dominant
frequency        = 15m
completed_only   = true
auto_order       = false
```

用户可见语义只有：

```text
15m 多头预警
15m 空头预警
```

不得把它描述为：

- 建多 / 建空；
- 开仓 / 平仓；
- 持仓中；
- 止盈 / 止损；
- 目标价；
- 仓位建议；
- 自动交易信号。

`buy` / `sell` 只作为 AlertEvent 的内部方向结果码，不代表系统执行交易。

---

## 4. 唯一正式公式

用户提供的同花顺期货通公式是 V1 唯一业务来源：

```text
DIFF = EMA(CLOSE, 12) - EMA(CLOSE, 26)
DEA  = EMA(DIFF, 9)
MACD = 2 * (DIFF - DEA)
MA21 = MA(CLOSE, 21)

BUY  = CROSS(DIFF, DEA) AND CLOSE > MA21
SELL = CROSS(DEA, DIFF) AND CLOSE < MA21
```

其中：

```text
MA(CLOSE, 21) = SMA21
```

不是 EMA21。

原公式中的：

```text
幅度
偏移
DRAWTEXT
零轴绘制
```

只服务于同花顺图形显示，不属于预警 Gate。

### 4.1 CROSS 精确定义

```text
golden_cross[t] =
    DIFF[t-1] <= DEA[t-1]
    AND
    DIFF[t] > DEA[t]

dead_cross[t] =
    DIFF[t-1] >= DEA[t-1]
    AND
    DIFF[t] < DEA[t]
```

正式 Candidate：

```text
LONG_ALERT[t] =
    golden_cross[t]
    AND close[t] > SMA21[t]

SHORT_ALERT[t] =
    dead_cross[t]
    AND close[t] < SMA21[t]
```

边界：

- `close == SMA21`：不触发；
- 当前 `DIFF == DEA`：不算完成 CROSS；
- 上一根或当前任一必需指标未 ready / invalid：不触发；
- 同一 completed 15m Bar 不允许同时生成 long 和 short；若实现产生双向结果，视为公式一致性失败并 fail-closed。

---

## 5. V1 明确不允许的隐藏过滤

V1 的正式 Candidate Gate 只能来自第 4 节。

以下任何内容都不得参与是否产生 Candidate：

```text
MACD 是否靠近零轴
MACD 柱强弱
EMA21
MA21 斜率
5m 共振
30m 共振
60m 共振
D1 方向
Daily Watch
Range Detector
震荡过滤
成交量
持仓量 OI
量比
ATR 距离
前高/前低
突破强度
三根 K 确认
评分
历史胜率
```

未来如需增加过滤，必须建立新的 `formula_version`，不能静默修改 `subing_ths_15m_v1`。

---

## 6. 数值合同

### 6.1 复用现有 Quant Core primitive

V1 不新建第二套 EMA/MACD 数学实现。

正式 Python authority 应复用当前 Quant Core：

- `initial_ema_state` / `step_ema`；
- `initial_macd_state` / `step_macd`；
- 新增一个最小 SMA21 incremental primitive，或复用已有同等通用 primitive（若实现时已存在）。

不得让：

- Runtime；
- API；
- Web；
- notification formatter

各自复制公式。

### 6.2 V1 工程参数

在没有同花顺逐 Bar seed 证据前，V1 工程计算固定为当前仓库可复算、Web-compatible 的通用 MACD 口径：

```text
fast             = 12
slow             = 26
signal           = 9
ema_seed_policy  = sma_window
histogram_scale  = 2
round_digits     = 6
sma_period       = 21
```

说明：

- `histogram_scale=2` 只影响 MACD 柱，不影响 DIFF/DEA CROSS 本身；
- 用户提供的同花顺公式没有定义历史序列第一根 EMA 的初始化细节；
- 因此本 Spec 不声称 `sma_window` 是同花顺内部 seed 实现；
- V1 对外只声明“按用户公式 clean-room 实现，并通过真实同花顺样本做启用前兼容性验收”。

如果真实样本证明同花顺 seed 与本工程口径在正式 Candidate 上存在稳定差异：

```text
BLOCK activation
→ 修订设计
→ 新 formula_version
```

不得为了对齐结果静默修改 V1 历史语义。

---

## 7. 数据身份与因果边界

正式决策输入固定：

```text
series_kind = actual_dominant
frequency   = 15m
bar_status  = completed
```

主力身份只认：

```text
MainContractMap rank = 1
```

不得使用：

- continuous 价格替代 actual_dominant；
- 次主力；
- 未完成 15m；
- preview Bar；
- 其他周期 fallback；
- consumer 自判主力；
- 文件 glob。

Historical 读取必须通过 `MarketDataService` / 既有 typed Market read seam。

### 7.1 物理合约隔离

Candidate 的决策 Bar 必须属于当前 rank1 物理合约。

指标递归状态不得跨物理合约继承。

为了避免主力切换后等待数十根 15m 才重新 ready，允许使用“当前 rank1 物理合约自身的 pre-dominant 历史”只做 numeric warm-up，但必须满足：

- 只读取同一 physical contract；
- 只读取当前决策 Bar 之前的数据；
- 不使用未来 Bar；
- 不把 pre-dominant Bar 本身变成 Candidate / Event；
- 不跨合约拼接 EMA/MACD/SMA state；
- 数据仍通过正式 MarketDataService / Catalog 身份读取。

如果当前物理合约自身历史不足以使 MACD/SMA ready，则该 Bar 正常返回 `warming_up`，不猜测、不跨合约补齐。

---

## 8. Evaluator 架构

当前 Alert Runtime 只有 HTDY evaluator，且运行时会遍历 DB Rules 后调用同一个 HTDY evaluator。新增第二条 Rule 后，必须将该耦合收敛为明确的 evaluator registry：

```text
rule_code
→ AlertRuleDefinition
→ evaluator
```

稳定映射：

```text
htdy_original_15m
→ HtdyOriginalEvaluator

subing_ths_alert_15m_v1
→ SubingThs15mEvaluator
```

要求：

- evaluator 必须由 `rule_code` 精确选择；
- unknown Rule：startup fail-closed；
- missing evaluator：startup fail-closed；
- 一个 Rule 不能误用另一个 Rule 的 evaluator；
- HTDY 现有 repaint/first-seen 语义保持不变；
- SuBing THS 是 non-repainting current-completed-bar observation，不需要 HTDY 的 repaint scan。

### 8.1 SuBing evaluator 输入

只接受：

```text
actual_dominant
15m
current completed Bar == trigger Bar
current contract == rank1 contract
sufficient same-contract warm-up
```

输出：

```text
()
("buy",)
("sell",)
```

不得输出两项。

---

## 9. Live Runtime

不新增第二个 Alert 进程、不新增 scheduler、不新增队列。

复用当前单进程 Alert Runtime：

```text
Market Runtime
→ completed Live Bar Pub/Sub
→ Alert Runtime
→ DB enabled Rules
→ rule scope check
→ rule evaluator
→ AlertEvent
→ one-shot notification
```

苏冰只消费：

```text
15m completed Live trigger
```

它不响应：

- 1m / 5m / 30m / 60m；
- `canonical_updated`；
- startup drain；
- repair；
- replay；
- after-market recalculation。

### 9.1 Startup / restart

启动或重启可以为了计算准备读取历史 warm-up，但：

```text
restore/catch-up != Event creation
restore/catch-up != PushPlus
```

只有 Runtime 正常运行期间新到达、经过正式校验的自然 completed 15m trigger，才允许产生新的苏冰 Event。

历史上已经完成但 Runtime 当时离线的 Bar：不补 Event、不补通知。

---

## 10. Rule 与 Scope

0043 后通用 Rule schema 已收敛为：

```text
rule_code
enabled
scope_product_frequencies
```

新苏冰必须复用该结构。

禁止恢复：

```text
scope_products
action_id
strategy_payload
```

### 10.1 正式 Scope

产品目标 Scope：

```text
current operational_products
× 15m
```

实际有效集合仍然是：

```text
operational_products
∩ Rule.scope_product_frequencies
```

`operational_products.txt` 是 Runtime authorization；Rule Scope 是通知授权。两者不能合并为一个概念。

### 10.2 初始化与启用

新 migration 不能把某一天的 60 品种硬编码成永久数据库事实。

0044 只创建：

```text
rule_code = subing_ths_alert_15m_v1
enabled = false
scope_product_frequencies = {}
```

后续单独的 production Scope Gate 必须在一个事务中：

1. 只读加载当时最新 `operational_products.txt`；
2. 生成精确 `symbol -> ["15m"]` 映射；
3. 原子替换新 Rule 的完整 Scope；
4. 校验 DB 读回与 operational universe 完全一致；
5. 再将 Rule enabled 设为 true。

不允许通过 60 个独立、可留下半完成状态的手工 HTTP 调用完成首次全量激活。

具体实现可以是一个窄范围、可 dry-run 的 runtime administration seam；不得建设通用 workflow 平台。

---

## 11. AlertEvent 合同

复用当前 `alert_events`，不新增表。

正式字段：

```text
rule_id
symbol
contract
trading_day
frequency = 15m
bar_end
result_codes = ["buy"] | ["sell"]
detected_at
notification_attempted_at
created_at
```

唯一业务身份继续使用：

```text
rule_id
× symbol
× frequency
× bar_end
```

### 11.1 幂等

同一 identity 再次出现：

- facts 完全一致：no-op；
- contract / trading_day / result_codes 等事实冲突：fail-closed；
- 不改写原 Event；
- 不重发通知。

### 11.2 Event 与 Notification 的关系

必须保持：

```text
Event commit first
→ transport attempt at most once
```

Event 是业务事实；transport 是外部副作用。

`notification_attempted_at` 只表示该 Event 在首次处理 pass 已进入 one-shot 通知尝试，不表示 provider accepted，更不表示微信实际送达。

---

## 12. PushPlus

V1 继续复用当前 PushPlus transport。

不新增第二套 provider client。

### 12.1 Audience

苏冰 V1 与 HTDY 使用同一个现有观察者 Topic。

目的：

- 不增加新的 Git-external token；
- 不新增收件人数据库；
- 不新增成员同步；
- 不扩大配置复杂度。

当前私有配置中的 `htdy_topic` 是既有外部配置键；V1 不要求为了改名而迁移该私有文件。实现层可以将其视为“shared observers topic”的 legacy-named config key，但不得在 UI/文案中把苏冰伪装成 HTDY。

系统不读取 Topic 成员清单，也不声明精确送达人数。

如果未来需要 HTDY 与苏冰不同 audience，必须另开任务并新增显式配置版本。

### 12.2 消息文案

多头：

```text
【苏冰预警】RB 螺纹钢

15m 多头预警

触发：
MACD 金叉
收盘价位于 MA21 上方

当前主力：RBxxxx
信号K线：2026-09-02 10:45

请打开归一量化图表复核。
研究观察，非交易指令
```

空头：

```text
【苏冰预警】RB 螺纹钢

15m 空头预警

触发：
MACD 死叉
收盘价位于 MA21 下方

当前主力：RBxxxx
信号K线：2026-09-02 10:45

请打开归一量化图表复核。
研究观察，非交易指令
```

禁止在 V1 消息里加入：

- 评分；
- 胜率；
- 60m / D1 同向；
- Range；
- ATR；
- 零轴距离；
- 成交量/OI；
- 目标价；
- 止损；
- 仓位。

### 12.3 one-shot

保持：

```text
no retry
no queue
no outbox
no fallback
no replay
no backfill
```

原因：无法仅凭 provider response loss 区分“未送达”和“已接受但响应丢失”，盲目 retry 会产生重复通知风险。

如果 transport 失败：

- Event 仍保留；
- Runtime health 显示失败；
- Web 仍能显示该 Event；
- 不自动补发。

---

## 13. Runtime 可靠性可见性

V1 不恢复旧 Boundary Ledger，也不新增 `alert:watch-runtime-status`。

但仅靠全局 Alert heartbeat 仍不足以证明苏冰 15m evaluator 在推进，因此在现有 `alert:runtime-status` 上增加一个最小、bounded 的 per-rule runtime projection。

建议 schema v6：

```text
rule_status: {
  "htdy_original_15m": {
    "last_evaluated_bar_at": ...,
    "last_event_at": ...,
    "last_failure_at": ...,
    "error_type": ...
  },
  "subing_ths_alert_15m_v1": {
    "last_evaluated_bar_at": ...,
    "last_event_at": ...,
    "last_failure_at": ...,
    "error_type": ...
  }
}
```

约束：

- 固定 rule key，不记录 symbol 级无限列表；
- 不新增 PostgreSQL health 表；
- 不新增第二个 Redis key；
- 不统计收益、命中率或策略状态；
- SuBing 的 `last_evaluated_bar_at` 只有在当前 completed 15m Bar 完成 scope + input + evaluator 全流程后才能推进；
- warm-up unavailable / input invalid / evaluator exception 必须进入 failure/unavailable 状态，不得冒充正常评估。

这个字段只解决一个问题：

> 最近一根应处理的苏冰 15m Bar 到底有没有真正经过 evaluator。

它不是旧 Boundary Ledger 的替代实现。

---

## 14. API

当前 Alert API 和 schema 中存在 HTDY-only 类型名与 `Literal["htdy_original_15m"]`。新增第二条 active Rule 后，必须将 wire contract 泛化为两条明确允许的 observation Rule，而不是复制第二套 API。

稳定接口继续复用：

```text
GET /api/alerts/products/{symbol}
PUT /api/alerts/rules/{rule_code}/scope/{symbol}/{frequency}
GET /api/alerts/events
GET /api/alerts/current-events
GET /api/alerts/products/{symbol}/current-events
```

正式 `rule_code` union：

```text
htdy_original_15m
subing_ths_alert_15m_v1
```

要求：

- `/events` 必须按查询 rule_code 返回真实 Rule；
- event serializer 不得再把所有 Event 强制写成 HTDY rule_code；
- current-events 可以同时返回两条 Rule 的 Event；
- unknown rule 继续 fail-closed / 404；
- HTDY wire 行为非回归。

不新增 `/api/subing/*` 顶级 API。

---

## 15. Market Web

不新增顶级 route。

仍然只有：

```text
/market
/market/chart
```

Web 只消费 typed Market / Alert API，不计算正式苏冰公式。

### 15.1 `/market`

新增一个紧凑的“最新苏冰预警”只读区域，目标数量 10–20 条：

```text
10:45  RB  多头预警
10:30  AG  空头预警
10:15  JM  多头预警
```

每条至少显示：

- 时间；
- 品种；
- 多/空；
- 15m；
- 跳转图表入口。

该区域读取 `current-events` 后按 `rule_code=subing_ths_alert_15m_v1` 投影，不发起 60 个逐品种请求。

如果当前 Market 首页正在执行独立重构，苏冰区域必须作为现有 Alert facts 的一个小组件接入，不得因此创建第二套首页数据模型。

### 15.2 `/market/chart`

正式 Event marker：

```text
S↑  多头预警
S↓  空头预警
```

Marker 必须来自 AlertEvent。

Web 不允许：

```text
if MACD cross && close > MA21:
    createOfficialMarker()
```

图表即使存在通用 MACD/EMA/Range 等 display primitive，也不能据此自行创建正式苏冰 Event marker。

Tooltip：

```text
苏冰预警
15m 多头预警
MACD 金叉
Close > MA21 (SMA21)
2026-09-02 10:45
RBxxxx
```

HTDY marker 与苏冰 marker 的视觉 tone 必须区分。

### 15.3 MA21 展示

V1 不强制新增 SMA21 主图线。

原因：用户本轮要求是“信号 Push + Web 显示”，正式 Web 价值首先是 Event 可见和快速跳转；为显示一条 SMA 线而复制/新增前端公式不是 V1 必需条件。

如果后续需要可视化 `MA21 (SMA)`，应作为通用只读指标显示能力单独实现，不能成为正式 Candidate authority。

---

## 16. Migration 0044

当前仓库 0043 的职责是 forward-only 删除旧苏冰策略 Event/Rule 与策略专用列，只保留通用 HTDY Alert schema。

新 migration：

```text
20260902_0044_subing_ths_alert.py
```

`down_revision`：

```text
20260902_0043
```

0044 只做：

1. preflight 当前 DB 正好处于 0043 后结构；
2. 验证只有 `htdy_original_15m` Rule；
3. 验证 HTDY Rule 与既有 Event 不被修改；
4. 插入 `subing_ths_alert_15m_v1`；
5. 新 Rule `enabled=false`；
6. 新 Rule `scope_product_frequencies={}`；
7. postflight 验证恰好两条 Rule。

0044 不做：

- 新表；
- 新列；
- `scope_products`；
- `action_id`；
- `strategy_payload`；
- production Scope 激活；
- Notification send。

`downgrade()`：unsupported / fail-closed。

### 16.1 0042 → 0044 production cutover

production 当前事实仍可能处于 0042，因此实施和发布计划必须把 0043 + 0044 看作一个 forward-only schema cutover 链。

新应用代码只承诺 0044 后 active schema，不建立旧策略 compatibility reader。

因此正式 cutover 必须是受控维护序列，而不是让旧 Runtime 与新 schema 长时间混跑：

```text
release main/tag
→ 准备 exact-tag Runtime root（不启用）
→ Runtime maintenance Gate：停止受影响服务
→ DB Gate：一次受控 upgrade 0042 → 0044 + readback
→ Runtime promotion Gate：切 exact approved tag
→ health / smoke
→ Scope activation Gate：原子设置 operational × 15m + enable
→ 自然 completed 15m evidence
```

每个外部 Gate 都必须得到当次明确授权；上一 Gate 成功不自动授权下一 Gate。

---

## 17. 错误与 fail-closed

以下情况不得创建 Event：

- Rule disabled；
- symbol 不在 operational universe；
- symbol/frequency 不在 Rule Scope；
- frequency 不是 15m；
- Bar 未 completed；
- actual_dominant 身份不可证明；
- rank1 contract 不匹配；
- warm-up 不足；
- SMA/MACD invalid；
- evaluator mapping 缺失；
- Event facts 冲突。

以下情况 Event 可以已经存在，但通知失败：

- taxonomy/name projection 失败；
- notification formatting 失败；
- PushPlus transport 失败；
- provider acceptance invalid。

这种情况下：

```text
Event 保留
Runtime health 记录失败
Web 仍显示 Event
不自动 retry
```

---

## 18. 安全与外部操作

设计和普通 implementation 不授权：

- production PostgreSQL 写入；
- production Redis mutation；
- production Scope 修改；
- Git-external notification config 修改；
- 真实 PushPlus；
- Runtime enable/switch/promotion；
- main merge；
- tag；
- GitHub Release。

这些仍按 `AGENTS.md` 逐项获取单次明确执行意图。

不读取、不输出、不提交 message token、Topic code、provider reference 或内部凭据。

`auto_order=false` 全程不变。

---

## 19. 测试合同

### 19.1 Formula / Quant Core

必须覆盖：

- SMA21 exact arithmetic mean；
- EMA12 / EMA26；
- DEA9；
- histogram scale 2；
- golden cross；
- dead cross；
- equality edge；
- `close == SMA21`；
- warming；
- invalid input；
- batch / incremental parity；
- prefix invariance；
- future-tail invariance；
- deterministic six-decimal projection。

### 19.2 Physical contract / data

必须覆盖：

- current rank1 identity；
- pre-dominant same-contract warm-up only；
- no cross-contract warm-up；
- rollover reset；
- incomplete/preview Bar rejected；
- wrong contract rejected；
- unavailable MDS / mapping fail-closed。

### 19.3 Alert Runtime

必须覆盖：

- rule-code evaluator dispatch；
- HTDY evaluator 非回归；
- SuBing 只消费 15m；
- SuBing 不消费 `canonical_updated`；
- startup drain 不创建 Event；
- Scope disabled no-op；
- operational universe guard；
- Event first；
- duplicate same facts no-op；
- conflicting same identity fail-closed；
- transport at most once；
- transport failure 不删 Event；
- per-rule last evaluated status；
- unknown DB Rule / registry mismatch startup fail-closed。

### 19.4 API

必须覆盖：

- 两条 Rule projection；
- generic event serializer 返回真实 rule_code；
- `/events?rule_code=subing_ths_alert_15m_v1`；
- `/current-events` 混合规则；
- product current events；
- invalid rule；
- HTDY legacy wire non-regression。

### 19.5 Web

必须覆盖：

- latest SuBing list；
- no O(N) product request；
- `S↑` / `S↓`；
- HTDY / SuBing marker tone distinction；
- deep link；
- event marker identity uses formal `bar_end`；
- Web 不包含 BUY/SELL 公式实现；
- mobile / desktop 基本布局；
- `/market/chart` 现有功能非回归。

### 19.6 Migration

isolated disposable PostgreSQL 必须覆盖：

```text
0042 → 0043 → 0044
```

验证：

- legacy SuBing Rule/Event 删除；
- strategy columns 删除；
- HTDY Rule/Event 完整保留；
- 0044 插入新 Rule；
- 新 Rule disabled + empty scope；
- 恰好两条 active-schema Rule；
- unexpected Rule / schema / version fail-closed；
- downgrade rejected。

---

## 20. 同花顺兼容性验收 Gate

代码合入 `develop` 不等于“与同花顺一致”。

真实通知激活前必须取得一组用户可核验的同花顺期货通 15m 样本。

最低验收：

- 至少 2 个品种；
- 至少 5 个金叉预警样本；
- 至少 5 个死叉预警样本；
- 核对 signal direction；
- 核对 completed 15m Bar 时间；
- 核对 CROSS；
- 核对 Close 相对 MA21；
- 核对主力合约身份。

如果无法直接导出逐 Bar 指标值，可以使用截图/时间点人工核验，但必须记录样本来源与判断依据。

如果差异集中于序列初期/换月后 warm-up，优先检查 seed 与物理合约历史；不得先改公式。

未通过该 Gate：

```text
可以保留代码 / Web shadow
不得启用真实苏冰 Rule
不得发送真实苏冰 PushPlus
```

---

## 21. 完成定义

### 21.1 CODE_COMPLETE

实现、测试、migration code、Web 和 canonical sync 全部完成。

### 21.2 TEST_COMPLETE

完成对应风险范围的：

- targeted pytest；
- full non-isolated backend；
- isolated PostgreSQL migration；
- Ruff；
- Mypy；
- Web unit；
- Playwright；
- Web build；
- OpenSpec strict；
- canonical consistency；
- secret scan；
- `git diff --check`。

### 21.3 RELEASED

独立 release Gate 后，`main + annotated tag + GitHub Release + API/Web version identity` 一致。

### 21.4 RUNTIME_READY

只在 exact-tag Runtime promotion 以及自然 completed Live evidence 通过后成立。

### 21.5 BUSINESS_CLOSED

至少满足：

- 0044 production migration 已完成；
- SuBing Scope 原子激活为当时 operational universe × 15m；
- Rule enabled；
- 自然 completed 15m 已经经过 SuBing evaluator；
- 至少一条自然 SuBing Event 已持久化；
- one-shot transport 已发生；
- provider acceptance 如有只能记录为 provider acceptance；
- 用户人工确认至少一次实际微信收到；
- Web 同一 Event 可见并可打开图表复核。

---

## 22. 外部 Gate 顺序

固定顺序：

```text
G0  Spec 批准
G1  Implementation Plan 批准
G2  Code + tests + independent Review
G3  允许集成 develop
G4  Release candidate
G5  release main/tag
G6  Runtime maintenance stop（受影响服务）
G7  production DB 0042→0044 migration
G8  exact-tag Runtime promotion
G9  production Scope activation + Rule enable
G10 同花顺兼容性 evidence
G11 自然 15m Event / one-shot transport
G12 用户人工微信送达确认
```

根据实施时 production 实际状态，可以减少已经由真实 evidence 完成的 Gate，但不能用历史授权替代新 mutation 的明确授权。

---

## 23. 推荐实现拆分

后续 Implementation Plan 建议只拆五个可独立审查 Packet：

```text
S1 Formula Kernel
   SMA21 + Subing THS formula + same-contract warm-up + golden tests

S2 Alert Runtime
   rule evaluator registry + Event + formatter + per-rule health

S3 API / Web
   generic Alert DTO + recent alerts + S↑/S↓ marker + deep link

S4 Migration / Scope activation seam
   0044 + isolated PostgreSQL + atomic operational×15m activation

S5 Canonical / Full Verification / RC
   PROJECT_SOURCE / DECISIONS / ARCHITECTURE / TESTING / OpenSpec
   + full verification + independent exact-head Review
```

每个 Packet 一个独立 task branch/worktree/PR；不得在一个实现会话中一路做到 release 或 Runtime。

---

## 24. 禁止范围

V1 明确禁止：

```text
恢复 subing_strategy_v1
恢复旧 Daily Watch
恢复旧 Factor/Lifecycle/Action/Episode
恢复 Strategy Runtime / Scope
零轴过滤
Range 过滤
成交量/OI过滤
ATR过滤
斜率过滤
多周期共振
评分
胜率
回测收益
持仓状态
OPEN/CLOSE
止盈止损
目标价
加减仓
自动下单
retry
queue
outbox
fallback
replay
backfill
generic strategy framework
第二个 Alert Runtime
第二套 Market data reader
Web 复制正式公式
```

---

## 25. Spec 自审

提交前按以下维度反向 Review：

1. 是否恢复了任何已退役旧苏冰模块；
2. 是否把 `MA(C,21)` 错写成 EMA21；
3. 是否加入用户没有要求的隐藏过滤；
4. 是否让 Web 成为第二公式 authority；
5. 是否跨物理合约继承 MACD/SMA 状态；
6. 是否允许 startup/replay 补发；
7. 是否让 migration 硬编码当前 60 品种；
8. 是否让 migration 自动启用真实通知；
9. 是否把 provider accepted 写成微信送达；
10. 是否为了“可靠”重新建设 Boundary Ledger/queue/outbox；
11. 是否遗漏当前 runtime 单 evaluator 与 HTDY-only DTO 的真实耦合；
12. 是否遗漏 0042→0043→0044 与新旧 Runtime schema 的 cutover 风险；
13. 是否留下生产 DB/Scope/通知/Runtime/release 的隐式授权；
14. 是否存在未决占位符、模糊条件或两个可解释实现。

### 25.1 本轮已关闭的 Review finding

本 Spec 在成稿前已主动关闭以下问题：

- **F1：旧 Watch 方案仍可能被误认为 implementation authority。** 处理：明确 #307 为新 authority，#286/旧 Watch 只保留历史语义。
- **F2：当前 Alert Runtime 只有一个 HTDY evaluator，直接加 Rule 会误用同一个 evaluator。** 处理：要求建立精确 `rule_code → evaluator` registry。
- **F3：当前 Alert API serializer 把所有 Event 写死为 HTDY。** 处理：要求 generic Rule union 和真实 rule_code serialization，不新增第二套 API。
- **F4：0043 已删除 `scope_products/action_id/strategy_payload`，旧 Watch migration 设计会逆向恢复 schema。** 处理：0044 只插 Rule，不新增表列。
- **F5：在 migration 中硬编码 60 品种会把当前 universe 固化成永久 schema fact。** 处理：0044 disabled + empty scope；后续原子 Scope Gate 读取当时 operational universe。
- **F6：如果新代码与 0042/0043/0044 长时间混跑，会触发 ORM/Rule composition 不兼容。** 处理：不建 legacy compatibility reader，正式 cutover 使用受控 maintenance stop → DB → exact-tag Runtime。
- **F7：为了证明“没有漏推”再次建设 Boundary Ledger。** 处理：只增加 bounded per-rule `last_evaluated_bar_at`，不新增第二 Redis key/PG history。
- **F8：PushPlus 为苏冰新增第二套 Topic 配置会扩大外部配置面。** 处理：V1 复用现有 observers Topic，不新增 token/member DB；未来不同 audience 单独版本化。
- **F9：为帮助复核而在 Web 复制 SMA/MACD 公式。** 处理：正式 marker 只读 Event；V1 不强制新增 SMA21 图线。
- **F10：直接声称与同花顺逐 Bar 完全一致，但 source formula 没给 seed。** 处理：工程 seed 固定、对外不夸大，真实通知前增加 source compatibility Gate。

自审结论：没有需要在本 Spec 内继续扩张架构才能解决的 blocker。

---

## 26. 用户 Review 决策点

本 Spec 已将工程选择冻结为：

- 新身份 `subing_ths_alert_15m_v1`；
- 只做 completed actual_dominant 15m；
- 只有 MACD CROSS + SMA21 Gate；
- 复用通用 Alert schema；
- 最终生产两条 Rule：HTDY + 新苏冰；
- 新 Rule migration 时 disabled + empty scope；
- 首次激活原子同步 operational universe × 15m；
- 苏冰与 HTDY 共用现有观察者 Topic；
- Web 只显示 recent Event + S↑/S↓ marker；
- 不恢复旧策略域；
- 不建设 Boundary Ledger / queue / retry；
- 真实通知前必须经过同花顺兼容性 evidence Gate。

用户批准本 written Spec 后，下一步才允许编写 Implementation Plan。

本 Spec 本身不授权任何源码实现、production migration、Scope mutation、真实通知、Runtime promotion、main/tag/Release 操作。
