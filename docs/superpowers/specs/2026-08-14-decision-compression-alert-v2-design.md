# v1.3 Decision Compression / Alert V2 设计规格

> 状态：Design Approved
>
> 日期：2026-08-14
>
> 基线：`v1.2.0` 已发布；本文以当前 `develop` 的 `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md` 以及现有 Alert V1 / SuBing 实现为事实源。

## 1. 背景与目标

`v1.2.0` 已经完成两条关键能力：

1. 火天大有 Alert V1 已形成自然 `confirmed 15m -> AlertEvent -> WeCom -> Web persistent marker` 闭环；
2. SuBing 已完成 current-rank1 segment-local Factor、slope-only accepted Calibration、scoped MACD FormalPolicy 和 5m/15m Formal Entry Signal，Web 已能读取 `primary_signal` / `resolved_signal`，但 Signal 仍只用于只读观察，不持久化、不接 Alert。

因此 v1.3 不再扩展“更多研究信息”，而是进入 **Decision Compression（决策压缩）**：

```text
可信数据
-> Market Research
-> SuBing Formal Signal
-> 只把真正需要处理的结果送到用户面前
-> 用户打开 K 线人工确认
```

产品目标不是增加一个 Signal Center，而是把已有可信结果接到现有 Alert Application Domain：

```text
SuBing resolved MATCHED
-> Alert Scope
-> immutable AlertEvent
-> WeCom one-shot
-> Market 首页「需要处理」
-> Product Workspace persistent marker / 今日记录
```

项目边界保持不变：所有信号、通知和 Web 均为研究观察，`auto_order=false`，不存在自动下单或订单创建路径。

---

## 2. 设计原则

### 2.1 减少选择

盘中用户不选择 SuBing 的 5m/15m 周期，也不调整 Calibration、MACD policy 或阈值。一个“苏冰入场信号”开关同时覆盖 5m + 15m。

### 2.2 先给结论，再给细节

信息优先级固定为：

```text
Formal Signal = 需要处理
Radar Attention = 值得看
HTDY = 观察提醒
Research Facts = 需要时再展开
```

### 2.3 Rule 只定义一次

- SuBing 自己拥有 Factor / Calibration / FormalPolicy / multi-timeframe resolver；
- Alert 不复制 SuBing 条件，不重新实现 5m/15m 优先规则；
- Alert 只负责 `Rule Scope -> result -> Event -> notification/marker`。

### 2.4 只持久化有业务价值的应用事实

- 不保存每根 Factor；
- 不保存 `NOT_MATCHED` / `RESEARCH_PENDING` / `INSUFFICIENT_DATA`；
- 只在最终值得提醒时创建 AlertEvent；
- 不增加 Signal DB、delivery queue、retry worker、已读/未读或处理状态。

### 2.5 本地单用户优先于理论完备

SuBing Alert V2 采用本地实时消费模型，不建设 event-time reconstruction、replay 或 backfill。系统明确接受：极端情况下 Alert Runtime 长时间阻塞后，旧 Pub/Sub 消息按处理时的最新 completed snapshot 计算，不承诺审计级 event-time 可重放性。

这项取舍只适用于 SuBing V2 实时 Alert；现有 HTDY Alert V1 的 event cutoff 行为不因本设计而回退。

---

## 3. 明确非目标

v1.3 不实现：

- Signal Center / Signal DB / Signal worker；
- Strategy / Backtest / Orders / Positions / Risk；
- Outcome Review、3K/5K/8K 统计、MFE/MAE 页面；
- 通用 Rule DSL、Rule Builder 或通知平台；
- WeCom delivery queue、retry、outbox、dead-letter；
- Alert replay/backfill；
- 已读/未读、已处理/未处理、任务工作流；
- SuBing 独立 Runtime、第二个 launchd、第二套 heartbeat；
- 自选列表自动成为 Alert Scope；
- SuBing 自动扩大到 operational 60；
- AI 自动选参数或自动晋升 Rule；
- 新 Market Catalog 表或 Canonical 语义修改；
- 新的 Web 模块/路由（“品种”“研究”“设置”等概念稿导航不得据此创建新应用面）；
- 全局搜索平台；
- signal score、星级、confidence、“信号质量高”等评分语义。

视觉概念稿中的额外导航、全局搜索和“信号质量/趋势强度”等块只用于表达视觉层级，不属于 v1.3 功能合同。

---

## 4. 总体架构

```mermaid
flowchart LR
    LIVE["LiveMarketService\ncompleted 5m / 15m"] --> REDIS["Redis Pub/Sub"]
    REDIS --> AR["Single Alert Runtime"]

    AR --> REG["Code-defined Alert Rule Registry"]
    REG --> HTDY["HTDY evaluator\nindicator observation"]
    REG --> SUB["SubingReadService.snapshot()\nformal signal"]

    SUB --> RES["existing resolved_signal"]
    HTDY --> EVAL["buy / sell observation"]
    RES --> MATCH{"MATCHED?"}

    EVAL --> EVENT["AlertEvent"]
    MATCH -->|yes| EVENT
    MATCH -->|no| DROP["no event"]

    EVENT --> DB["PostgreSQL Alert App tables"]
    EVENT --> WC["WeCom one-shot"]
    DB --> API["Alert API"]
    API --> HOME["Market 首页\n需要处理"]
    API --> PRODUCT["Product Workspace\nMarker / 今日记录"]
```

### 4.1 责任边界

**SuBing**：

- current rank1 segment identity；
- Historical/completed Live seam；
- EMA/MACD/Slope Factor；
- accepted Calibration；
- scoped FormalPolicy；
- 5m/15m companion relationship；
- same-boundary resolver；
- `resolved_signal`。

**Alert**：

- code-defined Rule 静态定义；
- server-side Scope；
- Runtime dispatch；
- immutable Event；
- one-shot WeCom；
- Web persistent facts。

Alert 不读取 SuBing threshold，不判断 slope/MACD/volume，不重建 multi-timeframe Signal。

---

## 5. Code-defined Alert Rule Registry

### 5.1 为什么需要 Registry

Alert V1 当前数据库把 `indicator_code`、单一 `frequency` 存在 `AlertRule` 中，这只适合固定 15m 的 HTDY。SuBing 是 Formal Signal，并且一个 Rule 同时覆盖 5m + 15m；继续扩 DB metadata 会产生代码与数据库的双重事实源。

v1.3 将 Rule 的静态定义收回代码。

### 5.2 Registry 最小合同

逻辑上每个 RuleDefinition 只需要：

```text
rule_code
- stable code identity

display_name
- Web / WeCom 可读名称

kind
- indicator_observation
- formal_signal

input_frequencies
- HTDY: [15m]
- SuBing: [5m, 15m]

series_kind
- current V2 固定 actual_dominant

dispatch binding
- 对应既有 evaluator / read service 入口
```

第一版精确存在两条代码定义 Rule：

```text
htdy_original_15m
  kind = indicator_observation
  display_name = 火天大有
  input_frequencies = [15m]

subing_entry_signal_v1
  kind = formal_signal
  display_name = 苏冰入场信号
  input_frequencies = [5m, 15m]
```

不得把 SuBing 伪装成 `indicator_code="subing"`。

---

## 6. AlertRule 数据模型

v1.3 后 `alert_rules` 只保存可变配置事实，不保存计算定义。

```text
AlertRule
- id
- rule_code
- enabled
- scope_mode
- scope_products
- created_at
- updated_at
```

### 6.1 Scope 语义

两个 Rule Scope 完全独立：

```text
火天大有 · 15m      [开 / 关]
苏冰入场信号        [开 / 关]
```

禁止隐式联动：

- 开启 HTDY 不得自动开启 SuBing；
- 加入自选不得自动开启 SuBing；
- operational 60 不得自动扩大 SuBing Scope。

### 6.2 SuBing seed

migration 创建：

```text
rule_code = subing_entry_signal_v1
enabled = true
scope_mode = watchlist
scope_products = []
```

空 Scope 是正式默认状态。因此：

```text
migration != SuBing notification activation
```

生产 migration 与首次给某个品种开启 SuBing Scope 是两个独立人工 Gate。

---

## 7. AlertEvent 数据模型

### 7.1 V2 字段

```text
AlertEvent
- id
- rule_id
- symbol
- contract
- trading_day
- frequency
- bar_end
- result_codes
- lower_tf_confirmation
- detected_at
- notification_attempted_at
- created_at
```

### 7.2 `trading_day`

新 Event 直接保存触发 completed Bar 自带的 `trading_day`，不根据 `bar_end` 重新推导。

原因：国内期货夜盘的自然日期和交易日并不等价，Event 发生上下文属于 Alert Application Domain 的明确业务事实。

为了不伪造历史事实，migration 不要求根据旧 `bar_end` 猜测 legacy V1 Event 的 `trading_day`：

- DB 列可为 legacy compatibility 保持 nullable；
- v1.3 `AlertService.create_event()` 创建的新 Event 必须提供非空 `trading_day`；
- current formal-signals 查询只读取具有明确 `trading_day` 的 V2 Formal Signal Event。

### 7.3 `result_codes`

统一允许：

```text
buy
sell
```

HTDY 可能是：

```text
["buy"]
["sell"]
["buy", "sell"]
```

SuBing Formal Signal 精确为：

```text
MATCHED LONG  -> ["buy"]
MATCHED SHORT -> ["sell"]
```

Event 字段不决定业务语义；Rule Registry 决定：

```text
HTDY buy   -> 买入观察
SuBing buy -> 买入信号
```

### 7.4 `lower_tf_confirmation`

- SuBing `resolved_signal.lower_tf_confirmation` 原样持久化；
- HTDY 固定为 `false`；
- 不保存 companion Factor、阈值或条件明细。

### 7.5 `notification_attempted_at`

现有 `notified_at` 的真实语义是 Event commit 后进入一次 WeCom 请求阶段，并不能证明对端成功送达。

v1.3 将字段语义校正为：

```text
notification_attempted_at
= Runtime 已进入该 Event 的一次通知尝试阶段
```

不新增：

```text
delivered
failed
retry_count
provider_response
```

### 7.6 幂等身份

V2 唯一约束：

```text
UNIQUE(rule_id, symbol, bar_end)
```

`frequency` 是 resolved Event 的结果属性，不再参与 identity。

该约束保证：

> 同一个 Rule、同一个品种、同一个时间边界，最多存在一个需要处理的业务事实。

建议保留现有 `(symbol, bar_end)` 查询索引，并增加面向首页的 `(trading_day, bar_end)` 索引。

---

## 8. Migration 语义

下一条 production migration 基于当前 `20260813_0037` 演进，不修改 Market Catalog 八表。

逻辑变更：

1. `alert_rules` 删除静态计算 metadata：`indicator_code`、单一 `frequency`；
2. `alert_events.observation_types` 收敛为 `result_codes`，历史值原样保留；
3. `notified_at` 重命名/迁移为 `notification_attempted_at`，历史值原样保留；
4. 新增 `trading_day`；legacy Event 不猜测，不强行回填；
5. 新增 `lower_tf_confirmation`，legacy 默认为 `false`；
6. 将唯一约束从 `(rule_id, symbol, frequency, bar_end)` 改为 `(rule_id, symbol, bar_end)`；
7. 在替换唯一约束前先检查既有数据是否存在新 identity 冲突；存在冲突则 migration fail-closed，不静默删除/合并；
8. seed `subing_entry_signal_v1`，Scope 为空；
9. 保持已有 HTDY Rule 的 enabled/scope 原值，不从 HTDY Scope 复制到 SuBing。

migration 文件进入仓库不代表允许执行 production migration；真实 migration 仍是单独一次性人工 Gate。

---

## 9. Alert Runtime V2

### 9.1 单 Runtime

继续只有现有 Alert Runtime：

```text
single process
single activation marker
single heartbeat
single WeCom sender
```

不得新增 SuBingRuntime 或第二套 launchd。

### 9.2 输入

Runtime 只消费 completed：

```text
5m
15m
```

未知 frequency、非法 channel、非法 payload、非 operational symbol 均在业务计算前拒绝。

### 9.3 Rule dispatch

```text
5m event
  -> eligible SuBing Rule

15m event
  -> eligible HTDY Rule
  -> eligible SuBing Rule
```

每条 Rule 单独检查：

```text
registry definition exists
AND DB rule.enabled = true
AND symbol in rule.scope_products
```

Rule 之间共享 Runtime，但故障隔离：一个 Rule 失败不得阻止同一 completed Bar 上另一个 Rule 正常处理。

### 9.4 HTDY 路径

HTDY 保持 v1.2 已验收语义：

```text
15m completed event
-> MarketReadService.bars_until(event cutoff)
-> HtdyOriginal15mEvaluator
-> observation_types/result_codes
-> Event
```

不因为 Alert V2 改成“最新 snapshot”。

### 9.5 SuBing 路径

SuBing Alert 不读取任何具体 Factor 条件，只调用现有 read model：

```text
SubingReadService.snapshot(SubingReadRequest(symbol, event_frequency), now)
-> snapshot.resolved_signal
```

Runtime 只解释：

```text
resolved_signal is None
-> no event

status != MATCHED
-> no event

MATCHED LONG
-> result_codes=["buy"]

MATCHED SHORT
-> result_codes=["sell"]
```

并原样使用：

```text
trigger_timeframe -> AlertEvent.frequency
lower_tf_confirmation -> AlertEvent.lower_tf_confirmation
```

### 9.6 不新增 5m/15m Signal 优先规则

现有 SuBing resolver 已定义：

- same READY boundary 双 MATCHED 同方向：15m wins；
- 反方向：fail-closed；
- reciprocal-only MATCHED：不能遗漏；
- 非 same boundary：正常保留 primary MATCHED。

Alert V2 不重复实现上述规则，只消费 `resolved_signal`。

### 9.7 同 boundary 防双触发

Live 在同一个 15m boundary 会先发布 completed 5m，再发布 completed 15m。为了避免 Alert 在 5m 消息上先发一次、随后 15m 再发一次：

```text
普通 5m boundary
-> 立即做 SuBing notification evaluation

同时也是 15m close 的 5m boundary
-> 该 5m 消息不做最终 SuBing notification evaluation
-> 等紧接着的 15m completed event
-> 由现有 SuBing resolved_signal 给出唯一结果
```

“是否为 15m close boundary”必须复用现有 TradingSession / aggregation bucket 口径，禁止使用 `minute % 15` 等另一套时间判断。

这只是触发去重，不是新的 Signal 业务规则。

### 9.8 SuBing 实时取舍

本项目是本地、单用户、单 Runtime。v1.3 选择：

```text
Pub/Sub -> immediate current snapshot -> resolved_signal
```

不实现：

- `snapshot_at()`；
- SuBing event-time cutoff reconstruction；
- Signal replay/backfill；
- Pub/Sub backlog 恢复。

如果 Runtime 长时间阻塞，旧 SuBing Pub/Sub event 可能按处理时最新 completed snapshot 判断；这是 v1.3 明确接受的工程取舍。

---

## 10. Event 与 WeCom 顺序

固定顺序：

```text
Rule result
-> create unique AlertEvent
-> commit succeeds
-> WeCom attempt once
```

### 10.1 DB 创建失败

```text
no Event -> no WeCom
```

### 10.2 duplicate Event

相同 `(rule_id, symbol, bar_end)` 已存在：

```text
no second Event
-> no second WeCom
```

### 10.3 WeCom 失败

```text
Event stays committed
-> warning only
-> no retry
```

### 10.4 接受的极小崩溃窗口

Event commit 与实际 HTTP request 之间如果进程崩溃，可能出现 Event 已存在但消息没有真正发送。v1.3 接受此极小窗口，不为此建设 outbox/delivery state machine。

---

## 11. WeCom 文案

### 11.1 HTDY

已自然验收的火天大有文案尽量保持不变，不为“统一模板”做无关改写。

### 11.2 SuBing

Formal Signal 通知只负责把结论送到用户面前，不输出研究过程。

建议精确短格式：

```text
【苏冰】焦煤 · JM2609

5m 买入信号 · 10:25
```

如果 higher timeframe wins 且有低周期确认：

```text
【苏冰】焦煤 · JM2609

15m 买入信号 · 10:30
5m 同向确认
```

卖出镜像。

禁止在 WeCom 中发送：

- slope 数值；
- MACD DIF/DEA/histogram；
- EMA21 数值；
- volume ratio；
- Calibration ID；
- condition PASS/FAIL；
- score/confidence；
- 仓位、止盈止损或下单建议。

### 11.3 Renderer 边界

不建设 MessageTemplate 表或模板 DSL。

采用 code-defined renderer：

```text
HTDY Rule -> HTDY renderer
SuBing Rule -> SuBing renderer
renderer -> plain text -> shared WeCom transport
```

---

## 12. Alert API V2

### 12.1 Product Rule State

保留现有产品级 Scope API 语义：

```text
GET /api/alerts/products/{symbol}
PUT /api/alerts/rules/{rule_code}/scope/{symbol}
```

返回静态 metadata 必须来自 Code Rule Registry，而不是 DB 副本。

推荐最小 DTO：

```text
rule_code
display_name
kind
input_frequencies
enabled_for_product
```

不再把 DB `indicator_code` / 单 `frequency` 暴露为规则事实。

### 12.2 Persistent Event API

现有 `/api/alerts/events` 继续负责：

```text
one symbol
+ one rule
+ explicit time range
```

主要 consumer 是 Product Workspace K 线 Marker / 历史记录。

V2 Event DTO 改为：

```text
id
rule_code
symbol
contract
trading_day
frequency
bar_end
result_codes
lower_tf_confirmation
detected_at
notification_attempted_at
```

### 12.3 Market 首页专用 Formal Signal API

新增专用只读 endpoint，语义固定为：

```text
GET /api/alerts/formal-signals/current
```

它不是通用 Event 搜索接口。

响应建议：

```text
status = ready | unavailable
trading_day = YYYY-MM-DD | null
items = [...]
```

每个 item：

```text
id
rule_code
display_name
symbol
product_name
contract
trading_day
frequency
bar_end
result_codes
lower_tf_confirmation
```

查询规则：

```text
Code Rule Registry.kind == formal_signal
AND AlertEvent.trading_day == current trading day
ORDER BY bar_end DESC
```

当前交易日只复用现有 TradingCalendar / MarketPhase 事实，不从 Event `bar_end` 重新推导；若不能唯一、可靠地解析当前交易日，则 `status=unavailable` 且 items 为空，前端必须展示“正式信号暂不可用”，不能误报“当前无正式信号”。

不支持：

- 任意日期筛选；
- 任意 Rule 查询；
- symbol filter；
- 分页中心；
- 已读/处理状态；
-全文检索。

---

## 13. Web 信息架构

### 13.1 设计目标

本轮 Web 改造不是增加更多信息，而是重新排列优先级：

```text
1. 用户现在要不要看一个正式信号？
2. 市场还有哪些值得看？
3. 需要时再看研究细节和运行上下文。
```

### 13.2 视觉概念稿与真实产品合同

已确认的视觉概念稿作为：

- 信息层级；
- 亮色主题方向；
- 卡片密度；
- 对比度；
- 组件形态；
- Product Workspace 布局

的视觉参考。

但以下概念稿内容不得照搬，因为与 active canonical / 当前产品面冲突：

- 不新增不存在的“品种 / 研究 / 设置”等路由；
- 不新增全局“搜索品种/合约/指标”平台；
- 不展示“信号质量高”“趋势强度较强”等 score/confidence；
- 不改变已有 SuBing Formal Signal 数学语义；
- 不根据概念图改变 K 线涨跌颜色合同。

---

## 14. Web 视觉系统升级

当前 Web 使用暗色 token。v1.3 将 active Market Web 统一切到高可读亮色体系；不增加亮/暗模式切换。

### 14.1 Surface / Type

推荐目标 token：

```text
page background      #F8FAFC
panel/card            #FFFFFF
primary text          #111827
secondary text        #374151
muted text            #667085
subtle border         #E4E7EC
strong border         #D0D5DD
neutral accent        #2563EB
observation orange    #F79009
```

字号目标：

```text
页面标题      26~28 / Bold
区块标题      18 / Semibold
正文          14 / Regular
辅助说明      12~13 / Regular
```

不再依赖低对比灰字和纯色差表达状态。

### 14.2 中国期货方向颜色必须保留

仓库现有方向合同是中国期货约定：

```text
上涨 / LONG / 买入方向 -> red
下跌 / SHORT / 卖出方向 -> green
```

因此概念稿中的“买绿卖红”只作为视觉占位，实际实现必须继续遵守现有 `--gy-up` / `--gy-down` 方向合同，并且始终搭配文字。

建议：

```text
buy / LONG badge      -> red directional accent + "买入信号"
sell / SHORT badge    -> green directional accent + "卖出信号"
HTDY observation      -> orange category surface + 明确买入/卖出文字
neutral CTA/navigation -> blue/charcoal neutral accent
```

这样品牌/操作色不和交易方向混淆。

### 14.3 卡片

统一：

- white surface；
- 1px 明确边框；
- 8~12px radius；
- very subtle shadow；
- hover 只用于可点击卡片；
- Formal Signal 可以用方向色左边线/顶部 chip 强化，但正文仍以深色文字为主。

### 14.4 Button

- 中性导航/“查看 K 线”使用 neutral primary；
- 不用按钮底色承担交易方向含义；
- 次按钮使用清晰边框，不使用低对比 ghost；
- disabled 必须有明显 disabled 对比。

---

## 15. Market 首页设计

### 15.1 页面顺序

```text
页面标题 / freshness

需要处理              <- highest priority

Radar Attention       <- secondary priority

Market Summary / Scatter / Sector / Detail
                       <- existing research capabilities preserved
```

现有 Market Radar P0 的 scatter、sector summary、detail table 不删除，只降低视觉优先级；不得为了套概念图回退 v1.1 已封板功能。

### 15.2 「需要处理」

标题：

```text
需要处理
只显示当前交易日的正式信号
```

只消费 `/api/alerts/formal-signals/current`。

第一版只会出现 `subing_entry_signal_v1`，但 UI 按 `kind=formal_signal` 合同实现，不硬编码“只有苏冰才可显示”。

卡片最小内容：

```text
苏冰
JM 焦煤 · JM2609
5m 买入信号
10:25
[查看 K 线]
```

当 `lower_tf_confirmation=true` 时可追加：

```text
5m 同向确认
```

禁止在首页 Formal Signal 卡片显示：

- Factor 数值；
- 信号质量；
- score/confidence；
- Radar reasons；
- slope/MACD/volume 条件。

### 15.3 空状态与不可用状态必须区分

`status=ready, items=[]`：

```text
当前没有需要处理的正式信号
```

`status=unavailable` / API error：

```text
正式信号暂不可用
```

不得把依赖故障渲染成“没有信号”。

### 15.4 Radar Attention

继续明确标注：

```text
值得关注，但尚未形成正式信号
```

Attention 不是 Formal Signal，也不进入“需要处理”。

### 15.5 今日 Formal Signal 生命周期

首页只显示 `AlertEvent.trading_day == current trading day` 的 Formal Signal。

进入下一交易日后，旧 Event 自然退出首页视图；数据库 Event 不删除、不改状态，K 线历史 Marker 仍可读取。

---

## 16. Product Workspace 设计

K 线仍是页面绝对主视觉，不缩小成普通卡片。

推荐结构：

```text
Left / Center
- 品种 + 当前主力
- 主力 / 主连
- 1m / 5m / 15m / 30m / 60m / 1d / 1w
- Kline + EMA overlay
- Volume
- MACD

Right
1. 正式信号
2. 提醒开关
3. 火天大有观察
4. 今日记录
5. 研究明细（existing data, secondary/collapsible）
6. Contract / Runtime context
7. 边界说明
```

### 16.1 正式信号卡

只展示当前 `resolved_signal`：

```text
苏冰
5m 买入信号 · 10:25
```

如果无 MATCHED：

```text
当前无正式入场信号
```

`NOT_MATCHED / RESEARCH_PENDING / INSUFFICIENT_DATA` 的技术状态可以在研究明细中解释，不占主卡片视觉焦点。

### 16.2 两个独立开关

精确为：

```text
火天大有 · 15m      [switch]
苏冰入场信号        [switch]
```

一个 SuBing switch 同时覆盖 5m + 15m，用户不选择周期。

### 16.3 火天大有观察卡

HTDY 明确降级为 observation category：

```text
火天大有
卖出观察 · 14:45
```

使用 observation orange surface/border，与 Formal Signal 方向卡视觉区分。

HTDY current overlay 可能 repaint；persistent Marker 仍只代表真实 AlertEvent，两者不得混为一类事实。

### 16.4 今日记录

Product Workspace 的“今日记录”可以同时展示本品种当前交易日的：

- SuBing Formal Signal Event；
- HTDY Observation Event。

每行必须明确 Rule + 语义：

```text
10:25  苏冰      买入信号
14:45  火天大有  卖出观察
```

这不会改变 Market 首页“只展示 Formal Signal”的合同。

### 16.5 研究明细

现有：

- SuBing Factor；
- Trend / Position；
- Volume / OI；
- Contract / Runtime context

不删除，但从第一视觉层移到次级区域，可采用折叠/下移方式实现“先结论，再细节”。

不得新增 score、星级或自动建议。

---

## 17. K 线 Marker

Persistent AlertEvent Marker 按 Rule 解释：

```text
SuBing Event
-> 买入信号 / 卖出信号 marker

HTDY Event
-> 买入观察 / 卖出观察 marker
```

原则：

- Marker 必须包含文字/形状，不能只靠颜色；
- SuBing 与 HTDY 的 category 视觉不同；
- 同一个 `(rule, symbol, bar_end)` 不会出现两个 Event marker；
- 历史 Marker 只来自持久 Event，不从当前 repaint overlay 反推历史 Alert。

---

## 18. Layout 与响应式

当前系统仍是桌面 Web，不新增手机 App。

推荐断点行为：

- >= 1200：K 线主区 + 右侧固定研究栏；
- 980~1199：侧栏保持已有折叠策略，右侧面板可收紧；
- < 980：Product Workspace 右侧信息堆叠到 K 线下方；Market Formal Signal 卡单列；
- 不要求为极窄手机屏提供全功能交易终端式布局。

当前 active Web 只有 Market 工作台路由；视觉稿中的多模块侧边栏不得引入不存在的产品模块。

---

## 19. Error Handling

### 19.1 Runtime

```text
invalid Pub/Sub payload
-> drop

unsupported frequency
-> drop

non-operational symbol
-> drop

Rule disabled / out of scope
-> skip

SuBing snapshot unavailable
-> no event

SuBing resolved_signal None / non-MATCHED
-> no event

one Rule evaluator exception
-> stable warning
-> continue other Rules

Event DB create failure
-> no WeCom

duplicate Event
-> no second WeCom

message render/taxonomy failure
-> Event remains
-> no WeCom

WeCom failure
-> Event remains
-> no retry
```

### 19.2 Web

- Formal Signal API unavailable 与“没有信号”必须分开；
- Rule Scope 保存失败必须恢复 switch UI 并给出明确失败提示；
- Radar 故障不影响 Formal Signal 区；Formal Signal 故障不影响 Radar；
- Product Workspace SuBing read error 不得伪装为 `NOT_MATCHED`。

---

## 20. 测试合同

### 20.1 Migration / Models

必须覆盖：

- AlertRule V2 schema；
- Event `result_codes` contract；
- `trading_day` new-event required；
- legacy nullable trading_day compatibility；
- `lower_tf_confirmation`；
- `(rule_id, symbol, bar_end)` uniqueness；
- migration collision precheck；
- legacy HTDY Event 字段值保持；
- SuBing seed Scope 精确为空。

### 20.2 Rule Registry

必须证明：

- HTDY 为 `indicator_observation`；
- SuBing 为 `formal_signal`；
- metadata 与 handler binding 都来自代码；
- 未知 DB `rule_code` fail-closed；
- DB 不需要复制 indicator/frequency 计算 metadata。

### 20.3 Alert Service / API

覆盖：

- HTDY / SuBing Scope 相互独立；
- Product Rule State metadata 来自 Registry；
- legacy Event query；
- current formal-signals 只返回 Formal Signal；
- 只返回 current trading_day；
- HTDY 不进入首页 endpoint；
- current trading_day 无法可靠解析时返回 unavailable；
- current endpoint 不提供通用查询参数。

### 20.4 Runtime

覆盖：

- 普通 5m SuBing MATCHED -> one Event；
- 普通 5m NOT_MATCHED -> no Event；
- 15m boundary 的 5m dispatch 被抑制，随后 15m event 产生至多一个 resolved Event；
- same-boundary 双 MATCHED 同方向仍由现有 resolver 选择 15m；
- direction conflict -> no matched Event；
- reciprocal-only MATCHED 不遗漏；
- duplicate Pub/Sub -> no duplicate Event / no duplicate WeCom；
- SuBing Rule failure 不阻塞 HTDY；
- HTDY failure 不阻塞 SuBing；
- scope 为空时 SuBing 不执行通知；
- WeCom failure 保留 Event 且不 retry；
- HTDY V1 原 cutoff/evaluator 行为完整回归。

### 20.5 Web

覆盖：

- 首页 Formal Signal 区视觉优先；
- current empty 与 unavailable 两种状态；
- HTDY 不进入“需要处理”；
- 两个独立 Rule switch；
- 一个 SuBing switch 不暴露 5m/15m 子开关；
- Product “今日记录”可同时显示 SuBing / HTDY 且文案不同；
- Marker category / direction label；
- 现有 Radar scatter/attention/sector/detail 不回归；
- 不出现 signal score/confidence；
- build / existing E2E / Alert V1 regression 全通过。

测试入口仍以仓库当前 `TESTING.md` 为准。

---

## 21. 发布与人工 Gate

代码完成不等于真实启用。

建议外部操作继续分开：

```text
Gate 1: production PostgreSQL migration
Gate 2: release main/tag（如本版本进入正式发布）
Gate 3: Runtime promotion/switch 到已批准版本
Gate 4: 对精确品种开启 subing_entry_signal_v1 Scope
Gate 5: 等待自然 SuBing MATCHED，验收 Event + WeCom + 首页 + Marker
```

既有 HTDY Alert Runtime 的持续授权不能自动扩展为新 SuBing Rule 的通知授权。

首次 SuBing Scope 建议仍从极小自然 canary 开始，例如一个人工明确选择的品种；本设计不预设必须是 `jm`，也不自动复制 HTDY 当前 Scope。

自然验收后是否扩大 Scope 仍由用户逐品种决定。

---

## 22. 验收标准

v1.3 只有在以下条件全部满足时，代码层面才可认为完成：

```text
AlertRule static calculation metadata 已收回 code Registry
AlertRule DB 只保存 code identity / enabled / scope
AlertEvent V2 字段和 unique identity 正确
legacy HTDY Event 不被伪造或破坏
subing_entry_signal_v1 seed Scope 为空
HTDY 与 SuBing Scope 完全独立
single Alert Runtime 支持 5m/15m code-defined dispatch
SuBing Alert 只消费 existing resolved_signal
Alert 没有复制 SuBing 公式或 resolver
15m boundary 不产生 5m + 15m 双通知
Event commit 先于 one-shot WeCom
WeCom failure 不 retry、不删除 Event
Market 首页只显示 current trading day Formal Signal
HTDY 不进入「需要处理」
Product Workspace 两个独立开关可用
Product Workspace 正式信号 / 观察提醒 / 今日记录层级清晰
现有 Radar 与 Kline 功能无回归
Web 采用高对比亮色视觉体系
交易方向仍遵循中国期货红涨绿跌合同
不存在 score/confidence/Signal Center/replay/retry queue
不存在订单或 auto trading 路径
```

---

## 23. v1.3 之后

v1.3 自然产生一段真实 SuBing AlertEvent 后，下一项优先候选是 **Outcome Review**：

```text
AlertEvent
+ MarketDataService
-> post-hoc 3K / 5K / 8K
-> MFE / MAE / EMA21 failure
-> 判断真实提醒是否值得继续扩大
```

该能力属于后续独立设计；v1.3 不提前增加 Outcome 表或 Backtest。

长期仍遵循：

> 先让一个真实闭环产生问题，再抽象下一层能力；不因为“以后可能用”提前建设平台。
