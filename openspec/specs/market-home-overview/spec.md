# Market Home Overview Specification

## Purpose

定义 Market 首页在不恢复任何退役策略的前提下读取 completed D1/W1 市场事实和当前 Alert Events
的两个 bulk、只读 HTTP 合同。该能力只为用户复核提供事实，不构成交易建议，
且 `auto_order=false`。

## Requirements

### Requirement: Market Home overview uses one authoritative completed snapshot

`GET /api/v1/market/research/home-overview` SHALL 从 `load_active_products()`、
`load_product_taxonomy()`、`DatabaseCoverageSource.latest_complete_day()` 和
`MarketDataService` 组合一个 response。Bar 查询 MUST 为每个 active product 至多一次
`actual_dominant` D1 和一次 W1；dominant summary MUST 只读取一次；该 endpoint MUST NOT
建立 provider、Redis Live、cache writer 或任何写服务。

#### Scenario: A complete active universe is available

- **WHEN** 每个 active product 都有 target day 的 completed D1，且 dominant identity 完整唯一
- **THEN** response 返回 `status=ready`、统一 `target_as_of/data_as_of`、全部 participants 和
  D1/W1 generic metrics

#### Scenario: A product has no target-day D1 fact

- **WHEN** product 的 D1 缺失或其最新 trading day 早于统一 target day
- **THEN** response MUST 为 `degraded`，计入 unavailable 或 stale，且不得伪造该 product item

#### Scenario: Weekly history is insufficient

- **WHEN** product 有 target-day D1 但 W1 EMA warm-up 不足或 W1 无数据
- **THEN** product item 仍存在，`weekly_trend=unavailable`，并且所有缺失 metrics 保持 null

#### Scenario: Weekly mapped dataset is absent

- **WHEN** product 有 target-day D1，但 W1 actual-dominant query 报告
  `ACTUAL_DOMINANT_WEEKLY_DATASET_ABSENT`
- **THEN** response MUST 保留该 product item 并返回 `weekly_trend=unavailable`；D1 的同类
  integrity failure 和 W1 的 `MAPPED_CONTRACT_DATASET_MISSING` 仍 MUST fail closed

### Requirement: Overview preserves generic market authority and transparent degradation

Overview item 的名称与 sector MUST 来自 taxonomy；dominant summary 仅提供 current actual
contract、mapping date 与 exchange。Item SHALL 只包含 completed D1 close、generic
`ResearchMetrics`、D1/W1 trend 与 generic reason codes；不得包含 strategy、buy/sell、entry/exit、
position、target、order 或任何退役策略事实。

构造时 universe MUST 非空、normalized、唯一，taxonomy keys MUST 精确匹配。缺失或重复
dominant identity、coverage failure、mapping/physical integrity failure MUST fail closed as a typed
HTTP 409; API 不得泄露内部异常。

#### Scenario: Authority configuration cannot be loaded

- **WHEN** active universe 或 taxonomy loader 失败
- **THEN** API MUST 返回 `409` 和 `MARKET_HOME_AUTHORITY_UNAVAILABLE`，不得返回内部 `500`

#### Scenario: Taxonomy and dominant facts disagree

- **WHEN** dominant summary 的名称或 sector 与 taxonomy 不同
- **THEN** response item 使用 taxonomy 的名称和 sector，仍使用 dominant 的 contract identity

#### Scenario: No browser N+1 path exists

- **WHEN** browser 请求首页 overview
- **THEN** 它只需一次此 bulk endpoint HTTP 请求，HTTP 请求数不随 universe size 增长

### Requirement: Current Alert Events endpoint is a global read projection

`GET /api/alerts/current-events?limit=30` SHALL 复用现有 current trading day resolver，并且只读
registry-owned active Alert Rules 的 exact trading day `AlertEvent`。`limit` MUST 在 1 到 100（含）之间，
结果 MUST 按 `detected_at DESC, bar_end DESC, id DESC` 排序。endpoint MUST perform SELECT only，
不得修改 Event writer、Rule、Scope、audience、transport、Runtime 或表结构。

#### Scenario: Current day has mixed current Alert Events

- **WHEN** registry-owned HTDY 或 SuBing Rule 存在当前交易日 Event
- **THEN** response 返回 `status=ready` 和按固定排序的 typed Alert Event items，legacy/non-registry
  Rule Event 不出现，且不因 Rule 当前 disabled 而改写既有 Event 事实

#### Scenario: Current trading day cannot be resolved

- **WHEN** existing resolver 返回 unavailable
- **THEN** response 返回 `status=unavailable`、`trading_day=null`、`items=[]`，不得伪装为 ready 空列表

#### Scenario: Current day has no HTDY Event

- **WHEN** current trading day 已解析且没有 registry HTDY Event
- **THEN** response 返回 `status=ready` 和空 items；这不代表 Runtime 正常静默

### Requirement: Market Home Web preserves independent read authorities

`/market` SHALL 在首屏并行读取且只读取一次 Market Home overview、Runtime health 和 current Alert
Events。页面 MUST 保留各资源最后一次成功快照，并把失败单独标识为 stale/unavailable；它不得由
Runtime heartbeat 推导 overview/Alert 状态，也不得由 Event 空列表推导 Runtime 正常静默。浏览器不得调用
product dominants、发起 per-product 请求、WebSocket 或任何写请求。

#### Scenario: A resource becomes unavailable after a successful snapshot

- **WHEN** overview、Runtime 或 current Event 任一刷新失败
- **THEN** 页面保留该资源的最后成功快照并仅将该资源标为 stale；其他两项事实保持独立

### Requirement: Market Home uses frozen non-trading visual semantics

图标色值 SHALL 为上行 `#E63935`、周期同向 `#FF9601`、下行 `#35C759`、中性 `#017AFF`、数据不足
`#98A2B3`，对应尺寸为 Legend 40px、表格状态 28px、Trend/HTDY micro 24px。图标必须有中文可访问语义，
业务文案只能使用上行、周期同向、下行、中性、数据不足；不得改写为买入、持股、卖出、空仓、建仓、清仓或订单语义。

#### Scenario: A user reads a state icon without color

- **WHEN** Market Home displays a frozen state icon
- **THEN** it has the approved size, color and Chinese accessible label, while adjacent HTDY/SuBing Event copy remains an observation rather than a trading instruction
