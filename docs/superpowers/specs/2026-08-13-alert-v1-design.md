# Alert V1 — 盘中观察预警设计

日期：2026-08-13  
状态：Design Approved / Implementation Not Started

## 1. Purpose

Alert V1 是归一量化在 Market Runtime 与 Market Research Workspace 已稳定后的第一个独立盘中提醒模块。

目标链路：

```text
Live completed bar
    -> Indicator Evaluator
    -> Alert Event
    -> 企业微信人工提醒
    -> 用户自行判断
```

Alert 只记录和通知“当时观察到了什么”，不是交易信号、策略结论或订单指令：

```text
Alert != StrategySignal != Order != Trading Decision
auto_order=false
```

V1 首个且唯一真实 Rule 为火天大有 original：

```text
huotian_dayou_original_v0
actual_dominant
15m
confirmed completed bar only
buy / sell observation
```

本设计不恢复已经退役的 Signal / Review / Strategy 应用链，不以旧表、旧 worker、旧 notification gate 或 Git history 中的旧 runtime 作为兼容入口。

---

## 2. Baseline and Frozen Boundaries

实施前继续遵守当前 active canonical：

- Data Foundation 已完成 60/60，Canonical 与 Market Catalog 不因 Alert 重构；
- `DatasetKey`、Data Foundation 八表、Canonical Parquet、月分区模型保持 Frozen；
- `MarketDataService` 仍是唯一 Historical Gateway；
- Historical Canonical 与 Redis Live Observation 保持分离；
- Alert 不写 Canonical，不修改 rank1 规则，不新增第二套行情 resolver；
- Signal / Review / Strategy HTTP、Web、worker、DB 旧语义继续退役；
- 真实通知和 Runtime activation 默认关闭；
- `auto_order=false` 始终成立，仓库继续不存在订单创建或提交路径。

Alert 新增的 PostgreSQL 表属于 **Application Domain**，不是 Data Foundation / Catalog 表。

---

## 3. V1 Non-goals

V1 明确不实现：

- replay / backfill / 历史补评；
- AlertRuntime 离线期间的漏报补发；
- 企业微信自动重试；
- delivery 成功/失败业务状态；
- retry count / retry queue；
- Redis Streams、Kafka、Celery、APScheduler 或其他消息/任务平台；
- checkpoint / offset / consumer cursor；
- 通用 Notification Platform；
- 多通知渠道；
- Rule DSL / 表达式解析器 / 可视化规则编排；
- Web Alert 一级页面；
- 任意 Rule 创建或编辑器；
- K 线输入快照；
- HTDY 指标输出快照；
- Alert Event 自动 TTL、归档或清理；
- 自动交易、订单、仓位或交易建议。

AlertRuntime 不在线时错过的 15m 预警永久错过，这是 V1 明确接受的行为，不视为待修复缺陷。

---

## 4. Architecture

```text
LiveMarketService
        |
        | completed 15m Pub/Sub
        v
      Redis
        |
        v
+---------------------------+
|       AlertRuntime        |
|                           |
| AlertRule / Scope         |
|        |                  |
|        v                  |
| MarketReadService         |
|        |                  |
|        v                  |
| Indicator Evaluator       |
|        |                  |
|        v                  |
| AlertService              |
+-----------+---------------+
            |
            +--> PostgreSQL alert_events
            |
            +--> WeComWebhookSender --> 企业微信
```

### 4.1 Component responsibilities

`LiveMarketService`

- 继续负责 Live 行情、Session 聚合、completed bars 与 Pub/Sub；
- 不知道 HTDY、AlertRule、PostgreSQL Alert 表或企业微信；
- Alert 失败不得反向影响 Live 行情采集。

`MarketReadService`

- 继续作为 Canonical history + Redis Live overlay 的统一只读模型；
- Alert 不自行实现 Historical/Live seam；
- 为 server-side evaluator 增加一个通用“截至指定 bar_end 的统一窗口”读取能力。

`Indicator Kernel`

- `packages/quant-core/guiyi_quant/indicators/` 继续是指标业务权威；
- 不感知 Redis、Alert DB、Webhook 或 Web UI。

`Alert Evaluator`

- 定义某个 code-defined Rule 如何判断“当前刚收完的 Bar”是否形成观察；
- V1 只有 `HtdyOriginal15mEvaluator`；
- 不负责持久化和发送。

`AlertService`

- 读取 Rule 与 Scope；
- 管理 Scope 增删；
- 持久化 AlertEvent；
- 以数据库唯一约束完成幂等。

`AlertRuntime`

- 独立常驻进程；
- 消费 completed 15m Pub/Sub；
- 编排 Rule -> MarketReadService -> Evaluator -> AlertEvent -> WeCom；
- 写 `alert:heartbeat`；
- 不做 replay、补评或重试。

`WeComWebhookSender`

- 只接收标准 Alert Event；
- 固定简洁模板；
- 单次 HTTP POST；
- 不理解 HTDY 公式、Scope 或 MarketDataService。

---

## 5. AlertRule Model

V1 第一条内置 Rule：

```text
rule_code       = htdy_original_15m
indicator_code  = huotian_dayou_original_v0
frequency       = 15m
series_kind     = actual_dominant   # code-defined, Web 不可修改
enabled         = true
scope_mode      = watchlist
scope_products  = []
```

每个 AlertRule 独立维护自己的 `scope_products`，不与其他 Rule 共用全局预警名单。

未来可以出现：

```text
HTDY Rule -> AG / JM / AP
EMA Rule  -> AU / AG
```

但 V1 不提供 Rule 创建/编辑 API。Rule 定义由代码注册，Web 只允许管理当前品种是否位于某个已存在 Rule 的 Scope 中。

### 5.1 Scope semantics

V1：

```text
runtime scope
= rule.scope_products
  intersect operational products
  intersect products with valid completed target bar
```

当前 `scope_mode=watchlist`。

数据模型允许未来存在 `operational_all`，但 V1 Web 和 API 不开放切换入口。

现有 browser-local “自选”继续只是 Market Workspace 偏好，不是 Alert Runtime 的配置事实源。

---

## 6. HTDY V1 Semantics

### 6.1 Indicator capability

`huotian_dayou_original_v0` 保持：

```text
status               = observation_only
future_looking       = true
repainting_risk      = known
web_capable          = true
alert_capable        = true
backtest_capable     = false
live_capable         = false
auto_order           = false
```

只放开 `alert_capable=true` 并取消 Registry 中“禁止 notifications”的描述。

不把 HTDY original 升级为正式策略、正式 live strategy 或可回测指标。

### 6.2 Observation types

Python Kernel 已有权威输出：

```text
buy_observation
sell_observation
```

V1 只保留两类：

```text
buy  -> 买入观察
sell -> 卖出观察
```

当前 Web 额外存在的 `xgObservation`、VAR23 / callbackBuy 与 XG marker 全部删除，不迁移进 Python Kernel。

### 6.3 Confirmed-close only

HTDY Alert 只接受：

```text
actual_dominant
15m
confirmed completed bar
```

不接受 partial / unconfirmed 15m，不从 tick 或未收盘 K 线触发。

### 6.4 Current-bar only

收到例如 `10:45` 的 completed 15m 后：

```text
读取截至 10:45 的行情
    -> 计算 HTDY original
    -> 只检查最后一根 10:45
```

**绝不扫描之前的 repaint 区域。**

例如 10:30 新数据导致 09:45 历史 Bar 因重绘新出现买入观察，而当前 10:30 没有观察，则完全忽略 09:45，不创建 Event、不发企微。

### 6.5 Repainting after notification

若 10:45 当前 Bar 当时出现买入观察：

```text
10:45 -> AlertEvent -> WeCom
```

随后 11:00 数据进入并导致 10:45 的 HTDY current marker 消失：

```text
AlertEvent 不修改
历史 Alert marker 不删除
不撤回企微
不补发其他旧 Bar
```

AlertEvent 表达的是“当时系统确实触发并发起过提醒”，而不是“现在重新计算仍然存在该指标观察”。

### 6.6 Consecutive bars

不同 confirmed Bar 独立：

```text
10:15 buy -> 发一次
10:30 buy -> 再发一次
```

不维护 signal-active / signal-clear / rearm 状态机。

同一 Rule × 同一 Bar 最多一条 Event、一条企微。

如果极端情况下同一 Bar 同时出现 buy + sell：

```text
observation_types = ["buy", "sell"]
```

形成一个 Event 和一条企微。

---

## 7. MarketRead Input Contract

Pub/Sub payload 只承担“某根 15m 已完成”的触发职责；HTDY 计算上下文必须通过 `MarketReadService` 读取。

建议为 `MarketReadService` 增加通用 server-side read method，概念接口：

```text
bars_until(identity, end=event.bar_end, limit=N)
```

要求：

- identity 为 `actual_dominant + symbol + 15m`；
- 内部复用现有 `history_page`、`live_snapshot`、Canonical/Live seam 与 bar_end 去重；
- 所有返回 Bar 满足 `bar_end <= event.bar_end`；
- 最后一根必须满足 `last.bar_end == event.bar_end`；
- 无法满足时 fail-closed；
- Alert 不直接读 Parquet；
- Alert 不自行拼 Redis + Canonical；
- Alert 不保存读取到的输入 Bars。

HTDY evaluator 使用固定、代码定义的最小充分 lookback，不向用户暴露窗口配置。具体窗口必须通过 differential test 证明：在目标测试集合上，有限窗口的最后一根 buy/sell 与截至同一 bar_end 的完整历史计算一致。

对于 repainting 指标，`event.bar_end` 是硬截断边界。即使 AlertRuntime 延迟处理旧 event，也绝不能读取更晚的 Bar。

---

## 8. Redis Transport

现有 Live channel 继续使用：

```text
live:bar:{symbol}:{frequency}
```

AlertRuntime V1 订阅：

```text
live:bar:*:15m
```

Transport 可以看见全部 operational 产品的 15m completed event，但第一步必须查询 Rule/Scope：

```text
rule enabled?
symbol in scope_products?
```

只有命中 Scope 后才进入 MarketReadService 与 HTDY Kernel。

因此：

```text
Transport universe = operational completed 15m
Evaluator universe = AlertRule scope
```

V1 不维护动态 Pub/Sub subscription manager。Web 修改 Scope 后，下一个 completed 15m 直接读取 PostgreSQL 最新 Scope 即生效，不需要重启 Runtime、配置事件或 cache invalidation。

---

## 9. PostgreSQL Application Tables

V1 新增两张 Alert Application Domain 表。Data Foundation / Market Catalog 继续固定八表，不修改 `market_tables.py` 的八表业务合同。

### 9.1 alert_rules

建议字段：

```text
id              PK
rule_code       TEXT / VARCHAR, UNIQUE, NOT NULL
indicator_code  TEXT / VARCHAR, NOT NULL
frequency       TEXT / VARCHAR, NOT NULL
enabled         BOOLEAN, NOT NULL
scope_mode      TEXT / VARCHAR, NOT NULL
scope_products  TEXT[], NOT NULL, default []
created_at      timestamptz, NOT NULL
updated_at      timestamptz, NOT NULL
```

V1 seed：

```text
rule_code       = htdy_original_15m
indicator_code  = huotian_dayou_original_v0
frequency       = 15m
enabled         = true
scope_mode      = watchlist
scope_products  = []
```

`enabled=true` 不会自动产生通知，因为默认 Scope 为空且 Alert Runtime 默认未激活。

### 9.2 alert_events

建议字段：

```text
id                  PK
rule_id             FK -> alert_rules.id, NOT NULL
symbol              NOT NULL
contract            NOT NULL
frequency           NOT NULL
bar_end             timestamptz, NOT NULL
observation_types   TEXT[], NOT NULL
detected_at         timestamptz, NOT NULL
notified_at         timestamptz, NOT NULL
created_at          timestamptz, NOT NULL
```

唯一身份：

```text
UNIQUE(rule_id, symbol, frequency, bar_end)
```

建议读取索引：

```text
INDEX(symbol, bar_end)
```

`contract` 是当时 resolved actual-rank1 的事件事实，但不参与唯一身份。如果相同 identity 再次出现且 contract 不一致，应视为一致性异常并 fail-closed，不能插入第二条 Event。

`observation_types` V1 只允许非空的 `buy` / `sell` 子集。

### 9.3 What is not stored

不保存：

- OHLCV snapshot；
- 输入 Bar window；
- HTDY zk1 / zd1 / zd2 等输出快照；
- indicator snapshot；
- delivery status；
- HTTP status；
- retry count；
- response body；
- webhook secret。

### 9.4 notified_at semantics

`notified_at` 的语义固定为：

> AlertRuntime 已经进入该 Event 的一次 WeCom 通知动作的时间。

它不代表企业微信确认成功接收，也不代表用户看到消息。

V1 不记录成功/失败结果。

`alert_events` 永久保留，不设置 TTL、不自动归档、不自动删除。

---

## 10. Idempotency and Send Ordering

AlertEvent 的 PostgreSQL unique constraint 是唯一的业务幂等边界。

执行顺序：

```text
current bar triggers
    -> construct AlertEvent
    -> INSERT / COMMIT
    -> unique duplicate? stop
    -> invoke WeCom exactly once
    -> stop regardless of result
```

同一个 Rule × symbol × frequency × bar_end 再次被 Pub/Sub 消费时：

```text
UNIQUE duplicate -> 不再发送
```

V1 主动接受一个极小窗口：Event 已经落库，但进程在真正完成 HTTP 调用前退出，因此可能出现“有 Event 但实际企微未收到”。不会补发。

这是明确的简化选择：宁可接受极少量漏报，也不引入事务消息、outbox、可靠队列或 retry worker。

---

## 11. WeCom Message Design

企微是盘中提醒，不是研究报告。V1 固定短消息，不提供模板编辑器。

买入示例：

```text
【归一量化】AG 白银

火天大有 · 买入观察
主力：AG2610
15m · 10:45 收线
```

卖出示例：

```text
【归一量化】JM 焦煤

火天大有 · 卖出观察
主力：JM2609
15m · 14:15 收线
```

同一 Bar 同时 buy + sell：

```text
【归一量化】AG 白银

火天大有 · 买入观察 + 卖出观察
主力：AG2610
15m · 10:45 收线
```

每条消息只回答四件事：

```text
哪个品种
什么观察
哪个实际主力合约
哪根 15m 收线
```

不发送：

- 大段 HTDY 解释；
- 重绘说明长文；
- OHLCV；
- zk1 / zd1 / zd2；
- Radar 指标；
- Runtime 状态；
- URL；
- 买卖建议、开仓建议、止盈止损或其他交易指令。

消息用词固定为“买入观察 / 卖出观察”，不用“买入信号 / 开多 / 做空”。

---

## 12. WeCom Secret and Failure Boundary

真实 Webhook 只从本机 Runtime 环境读取：

```text
WECOM_WEBHOOK_URL
```

正式 Runtime 优先使用当前本地 wrapper 已支持的：

```text
~/Library/Application Support/GuiyiQuant/project.env
```

禁止写入：

- Git；
- PostgreSQL；
- Web UI；
- API response；
- Runtime log；
- exception text。

`WeComWebhookSender` 使用固定有界 timeout，只调用一次。

Webhook timeout / HTTP error / WeCom error：

```text
写脱敏 runtime log
不 retry
不补发
不修改 AlertEvent 为失败状态
```

日志只使用稳定错误码/错误类型，不输出 webhook URL、key、完整 response body 或 stack trace。

---

## 13. HTTP API

V1 只开放最小 API 面。

### 13.1 Product alert state

```text
GET /api/alerts/products/{symbol}
```

返回当前品种可用的内置 AlertRule、固定规则描述和 `enabled_for_product`。

Web 可看到：

```text
rule_code
显示名
indicator_code
series_kind=actual_dominant
frequency=15m
enabled_for_product
```

### 13.2 Scope toggle

```text
PUT /api/alerts/rules/{rule_code}/scope/{symbol}
```

请求：

```json
{"enabled": true}
```

只允许：

- 将合法 operational symbol 加入 `scope_products`；
- 从该 Rule `scope_products` 中移除 symbol。

不允许通过 API 修改：

- `rule_code`；
- `indicator_code`；
- `frequency`；
- `series_kind`；
- Rule trigger；
- indicator formula；
- `scope_mode`；
- 任意 Rule 创建。

### 13.3 Event markers

```text
GET /api/alerts/events
    ?symbol=ag
    &rule_code=htdy_original_15m
    &start=...
    &end=...
```

只读取 `alert_events`，用于 Product Workspace Persistent Alert Marker。

---

## 14. Product Workspace UX

V1 不新增 Alert 一级页面。

在现有 Product Workspace / Research Sidebar 中增加一个轻量控制：

```text
预警

火天大有 · 15m 实际主力      [开启]
Alert Runtime                 ● 正常
```

开关语义始终是：

```text
当前 symbol
是否加入 htdy_original_15m 的 scope_products
```

与当前图表正在查看的 Series/Frequency 完全无关。

例如当前页面正在看：

```text
AG continuous 5m
```

开关控制的仍然是：

```text
AG actual_dominant 15m HTDY Alert
```

关闭浏览器、清理 localStorage 或切换图表不会改变 server-side Alert Scope。

Alert Runtime 未启用时仍允许用户先配置 Scope；UI 必须明确显示 Runtime“未启用/不可用”，不能把 Scope 开启误显示成后台正在发送。

---

## 15. Persistent Alert Markers

Product Workspace 存在两类语义不同的 Marker。

### Current HTDY marker

```text
来自当前 HTDY 重算
会随 repaint 改变或消失
```

### Persistent Alert marker

```text
来自 PostgreSQL alert_events
表示“当时系统触发并发起过企微提醒”
永久保留
```

Persistent Marker 只在：

```text
actual_dominant + 15m
```

显示。

不投影到 continuous、contract、5m、30m、60m 等其他 Series/Frequency。

建议使用短标签，避免遮挡 K 线：

```text
🔔买
🔔卖
🔔买/卖
```

Persistent Alert Marker 与 HTDY overlay 开关独立。即使用户关闭 HTDY current overlay，历史 🔔 仍然显示。

Web 不需要 Alert 专属 WebSocket。进入/切换 `actual_dominant + 15m`、加载更早历史时按当前 loaded bar range 查询 Alert Events；盘中页面可用轻量周期刷新保持新 Alert marker 最终可见，不建立第二套实时通道。

---

## 16. Alert Runtime

新增统一 CLI：

```text
guiyi runtime alert
```

新增 launchd service：

```text
com.guiyi.quant-alert
```

沿用现有 Runtime 模式：Python foreground blocking process，由 launchd `RunAtLoad + KeepAlive` 托管，Python 自己不 daemonize。

Alert 使用独立 activation marker：

```text
.run/alert-runtime-enabled
```

不得复用：

```text
.run/market-runtime-enabled
```

代码存在、migration 完成、Rule Scope 开启都不代表 Alert Runtime 已获得真实发送授权。

`guiyi runtime alert` 的真实运行路径必须 fail-closed：activation 未启用、Webhook 未配置或关键依赖不可用时不得进入真实通知消费状态。

---

## 17. Runtime Health

不新增 `/api/alerts/health`。

扩展现有：

```text
GET /api/runtime/health
```

新增：

```text
components.alert
```

建议字段：

```text
status
a configured_enabled
webhook_configured
last_heartbeat_at
enabled_rule_count
scope_product_count
error_type
```

其中字段名实现时使用正常 JSON 名 `configured_enabled`；上方 `a` 只是本行排版误差不得进入实现。

> 实现计划必须在落地前删除上述排版误差，最终 schema 只有 `configured_enabled`。

AlertRuntime 写短 TTL Redis heartbeat：

```text
alert:heartbeat
```

公开 heartbeat/health 不包含 webhook、内部地址、原始异常正文或 stack trace。

Web 简化为三种用户状态：

```text
ok                  -> Alert Runtime 正常
disabled             -> Alert Runtime 未启用
degraded / failed    -> Alert Runtime 不可用
```

Runtime 进程本身存活但 `WECOM_WEBHOOK_URL` 缺失时必须显示不可用，不能显示 healthy。

---

## 18. Event Processing State Machine

```text
Redis Pub/Sub receives completed 15m
        |
        v
validate channel + payload
        |
        v
load enabled AlertRules
        |
        v
symbol in Rule scope?
   no -> END
        |
       yes
        v
Indicator Registry alert_capable == true?
   no -> FAIL CLOSED
        |
        v
MarketReadService actual_dominant + 15m
        |
        v
hard truncate to event.bar_end
        |
        v
last.bar_end == event.bar_end?
   no -> FAIL CLOSED
        |
        v
Python HTDY original
        |
        v
inspect last point only
        |
        v
buy/sell present?
   no -> END
        |
       yes
        v
resolve current contract consistency
        |
        v
INSERT AlertEvent
        |
        v
UNIQUE duplicate?
   yes -> END / no second send
        |
       no
        v
invoke WeCom once
        |
        v
END regardless of delivery result
```

---

## 19. Fail-closed Matrix

以下情况全部不发企微：

| Condition | V1 behavior |
|---|---|
| Pub/Sub payload 非法 | skip |
| 非 completed 15m | skip |
| Rule 不存在或 disabled | skip |
| symbol 不在 Rule Scope | skip |
| symbol 非 operational | skip |
| Indicator `alert_capable != true` | fail-closed |
| MarketReadService 异常 | fail-closed |
| 当前 event Bar 无法读取 | fail-closed |
| 最后一根 `bar_end != event.bar_end` | fail-closed |
| 读取结果含 event 之后未来 Bar | fail-closed |
| actual_dominant / contract 上下文不一致 | fail-closed |
| HTDY Kernel 异常 | fail-closed |
| AlertEvent INSERT / COMMIT 失败 | fail-closed |
| UNIQUE Event 已存在 | no-op，不二次发送 |
| Webhook 未配置 | Runtime unavailable，不发送 |
| Webhook HTTP 失败 | stop，不 retry |
| AlertRuntime 当时离线 | 永久漏掉，不补 |
| 后续 HTDY repaint | Event 不变，不撤回 |

总原则：

```text
无法证明“这是合法的当前 confirmed 15m”
或
无法完成 Event 幂等落库
=> 不允许发送
```

---

## 20. Code Placement

建议新增：

```text
services/quant-api/app/alerts/
├── __init__.py
├── models.py
├── evaluators.py
├── service.py
├── runtime.py
├── wecom.py
└── composition.py

services/quant-api/app/api/alerts.py
services/quant-api/app/schemas/alerts.py
```

职责：

- `models.py`：AlertRule / AlertEvent；
- `evaluators.py`：最小 evaluator contract + HTDY evaluator；
- `service.py`：Rule/Scope/Event 应用逻辑；
- `runtime.py`：Pub/Sub loop 与 heartbeat；
- `wecom.py`：固定消息格式 + 单次发送；
- `composition.py`：组装 MarketReadService、DB、Redis、Evaluator、Sender；
- `api/alerts.py`：三个 V1 HTTP surfaces；
- `schemas/alerts.py`：Pydantic IO models。

不得把 Alert ORM 加进 `app/models/market_tables.py`；该文件继续只表达 Data Foundation 八表。

Web 建议新增：

```text
apps/quant-web/src/api/alerts.ts
apps/quant-web/src/components/market/ProductAlertControl.vue
```

最小修改现有：

```text
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/utils/indicators.ts
```

不新建 Alert 页面。

---

## 21. Canonical Updates Required by Implementation

### 21.1 “PostgreSQL only eight tables” wording

当前 canonical 中“PostgreSQL active 数据模型只有八表 / PostgreSQL 只保留八张 active 数据表”的表述在 Alert 新增两张业务表后必须收紧为：

> Data Foundation / Market Catalog 始终且仅为八表；独立 Application Domain 可以按明确设计新增非行情基础表。

必须同时明确：

```text
alert_rules / alert_events
不是 Market Catalog
不进入 DatasetKey
不参与 Canonical 发布
不保存行情 Bar
不改变 MarketDataService 历史合同
```

AlertEvent 保存的是不可由当前重绘结果可靠替代的“当时发生过提醒”事实，因此不属于“可由 Canonical 按需推导、禁止长期保存的研究 read model”。

### 21.2 Alert Runtime V1 bounded continuous authorization

当前 Market Runtime V1 的持续授权明确不覆盖真实通知。

Alert V1 实施时必须新增一个独立且有界的长期决策：

```text
用户明确执行一次“启用 Alert Runtime V1”后，
允许本机 Alert Runtime 对：
htdy_original_15m
× 当前 enabled scope_products
× WeCom
持续自动发送人工观察提醒。
```

该授权不覆盖：

- 新增第二种真实 AlertRule；
- 新增其他通知渠道；
- 修改 webhook secret；
- production DB migration；
- Runtime version switch / promotion；
- main / tag / release；
- Canonical / Market 数据写入；
- 订单或自动交易。

未来新增新的真实 AlertRule 时必须重新明确其能力与持续授权边界，不能因为 Alert framework 已存在而自动获得真实发送权限。

---

## 22. Testing Requirements

实现必须覆盖以下测试组。

### 22.1 Indicator contract

- HTDY original `alert_capable=true`；
- 仍为 observation-only / known repainting / non-backtest / non-live / auto_order=false；
- Web XG 完整删除；
- Python/Web buy/sell golden 继续一致。

### 22.2 Evaluator

- 只检查最后一根；
- 旧 Bar 因 repaint 新出现观察不触发；
- current buy；
- current sell；
- current buy+sell；
- 连续两根分别产生 Event；
- event 后加入未来 Bar 导致旧 marker repaint，不修改旧 Event。

核心业务回归：

```text
10:45 completed
-> buy=true
-> AlertEvent

11:00 arrives
-> recompute makes 10:45 buy=false

must still hold:
AlertEvent exists
persistent 🔔 remains
no retraction
no old-bar backfill
```

### 22.3 MarketRead seam

- hard `<= event.bar_end`；
- last bar 必须等于 event bar；
- Canonical + Live 正确 dedup；
- future Bar 不可见；
- fixed lookback last-output differential 与 full-history 截断结果一致。

### 22.4 AlertService

- Scope add/remove；
- Rule disabled；
- invalid/non-operational symbol rejected；
- unique Event dedup；
- duplicate 不产生第二次 sender invocation；
- Event range query 正确。

### 22.5 Runtime fail-closed

非法 payload、非 15m、非 scope、MarketRead failure、Kernel failure、contract mismatch、DB failure 全部不得调用 WeCom。

### 22.6 WeCom

- 固定短模板；
- buy / sell / buy+sell 格式；
- 单次调用；
- timeout 有界；
- HTTP failure no retry；
- log 不包含 webhook URL、key、response body。

### 22.7 HTTP API

- Product Alert state；
- Scope PUT；
- Events GET；
- 不能经 API 修改 Rule definition、frequency、indicator 或 scope_mode。

### 22.8 Health / Ops

- activation off -> disabled；
- activation on + webhook missing -> degraded/unavailable；
- stale/missing heartbeat -> degraded；
- healthy heartbeat -> ok；
- launchd render/lint；
- secret scan 0 finding。

### 22.9 Web

- Alert scope 来自 server，不来自 localStorage；
- 切 Series/Frequency 不改变 Scope；
- Alert marker 只在 actual_dominant + 15m；
- HTDY overlay off 时 persistent 🔔 仍显示；
- repaint 后 current marker 可消失而 persistent 🔔 不消失；
- XG marker/计算完全移除。

---

## 23. Controlled External Operations and Acceptance Gates

代码开发、mock sender、临时/测试 DB migration 不构成真实运行授权。

真实闭环按独立 Gate 执行。

### Gate 1 — Production PostgreSQL migration

只允许：

```text
CREATE alert_rules
CREATE alert_events
seed empty-scope htdy_original_15m
```

验收：

- Data Foundation 八表 schema 不变；
- Alert 两表存在；
- seed Rule Scope 为空；
- 不发送企微。

### Gate 2 — Real WeCom canary

配置本机 `WECOM_WEBHOOK_URL` 后，使用专用 canary 路径发送一条明确测试消息：

```text
【归一量化】企微测试

Alert 通知通道正常
```

Canary 不伪造正式 AlertEvent。

### Gate 3 — Alert Runtime activation

显式启用：

```text
.run/alert-runtime-enabled
com.guiyi.quant-alert
```

先仅开启少量真实品种 Scope，确认 `components.alert.status=ok` 后等待自然 confirmed 15m HTDY observation。

自然验收链：

```text
completed 15m
-> Python HTDY buy/sell
-> exactly one alert_event
-> one WeCom message attempt
-> Product Workspace persistent 🔔
```

之后继续观察 repaint：

```text
HTDY current marker may disappear
AlertEvent stays
persistent 🔔 stays
no historical replay/backfill
```

再重启 AlertRuntime，确认恢复后只处理新的 completed Bar，停机期间不 replay / backfill。

Migration、真实 WeCom canary、Alert Runtime activation 是三个独立受控外部操作，不能互相授权。

---

## 24. Future Extension Boundary

Alert framework 的通用性只体现在稳定窄接口：

```text
code-defined Evaluator
    -> standard observation types
    -> AlertService
    -> AlertEvent
    -> channel sender
```

未来新增指标时，可以新增 evaluator + built-in Rule，并复用 Scope、Event、Runtime、Health 与 Web 模式。

不得因为“以后可能需要”提前增加：

- plugin framework；
- arbitrary JSON conditions；
- multi-channel delivery table；
- retry engine；
- generalized strategy/signals subsystem。

当未来真实需求出现时再单独设计。

---

## 25. Acceptance Definition

Alert V1 完成必须同时满足：

```text
Rule
-> server-side Scope
-> completed actual_dominant 15m
-> MarketReadService hard cutoff
-> Python HTDY current-bar buy/sell
-> idempotent AlertEvent
-> one concise WeCom attempt
-> persistent Web 🔔
```

并保持：

```text
no old repaint scan
no replay
no retry
no XG
no Data Foundation change
no old Signal/Review/Strategy revival
no order path
auto_order=false
```

只有在对应真实 Gate 明确执行并读回后，才能分别声称 production migration、真实 WeCom channel 或 Alert Runtime 已启用；代码和测试通过本身不授权这些外部操作。
