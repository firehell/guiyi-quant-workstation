# Market Home Overview Specification

## Purpose

定义 Market 首页在不恢复任何退役策略的前提下读取 completed D1/W1 市场事实和当前 HTDY
immutable Event 的两个 bulk、只读 HTTP 合同。该能力只为用户复核提供事实，不构成交易建议，
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
  `MAPPED_CONTRACT_DATASET_MISSING`
- **THEN** response MUST 保留该 product item 并返回 `weekly_trend=unavailable`；D1 的同类
  integrity failure 仍 MUST fail closed

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

### Requirement: Current HTDY Event endpoint is a global read projection

`GET /api/alerts/current-events?limit=30` SHALL 复用现有 current trading day resolver，并且只读
registry-owned HTDY Rule 的 exact trading day `AlertEvent`。`limit` MUST 在 1 到 100（含）之间，
结果 MUST 按 `detected_at DESC, bar_end DESC, id DESC` 排序。endpoint MUST perform SELECT only，
不得修改 Event writer、Rule、Scope、audience、transport、Runtime 或表结构。

#### Scenario: Current day has HTDY Events

- **WHEN** registry HTDY Rule 存在当前交易日 Event
- **THEN** response 返回 `status=ready` 和按固定排序的 typed HTDY Event items，legacy/non-registry
  Rule Event 不出现

#### Scenario: Current trading day cannot be resolved

- **WHEN** existing resolver 返回 unavailable
- **THEN** response 返回 `status=unavailable`、`trading_day=null`、`items=[]`，不得伪装为 ready 空列表

#### Scenario: Current day has no HTDY Event

- **WHEN** current trading day 已解析且没有 registry HTDY Event
- **THEN** response 返回 `status=ready` 和空 items；这不代表 Runtime 正常静默
