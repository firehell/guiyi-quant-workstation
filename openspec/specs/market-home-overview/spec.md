# Market Home Overview Specification

## Purpose

定义 Market 首页在不恢复任何退役策略的前提下读取 completed D1/W1 市场事实和当前 HTDY
immutable Event 的只读 HTTP 合同。Market Home overview 使用可删除、可重建的 derived projection
加速常态读取，但 `MarketHomeOverviewService -> MarketDataService` 始终是唯一计算 authority。
该能力只为用户复核提供事实，不构成交易建议，且 `auto_order=false`。

## Requirements

### Requirement: Market Home overview uses one authoritative completed snapshot

`MarketHomeOverviewService` SHALL 从 `load_active_products()`、`load_product_taxonomy()`、
`DatabaseCoverageSource.latest_complete_day()` 和 `MarketDataService` 组合 completed D1/W1 response。
现场 compute 时 Bar 查询 MUST 为每个 active product 至多一次 `actual_dominant` D1 和一次 W1；
dominant summary MUST 只读取一次。该 service MUST NOT 建立 provider、Redis Live 或写服务。

`GET /api/v1/market/research/home-overview` SHALL 先读取 exact-identity derived projection；projection
缺失、损坏或 identity 不匹配时，MUST 回退上述 authoritative compute。HTTP endpoint 本身 MUST NOT
创建、更新、失效或修复 projection。

#### Scenario: A valid projection exists

- **WHEN** projection 的 schema、target day、active/taxonomy digest 与当前 authority identity 精确一致
- **THEN** endpoint 返回 frozen `MarketHomeOverviewResponse`，且不得调用 expensive `snapshot()`、
  `query_page()` 或 `list_latest_dominants()`

#### Scenario: Projection is absent or invalid

- **WHEN** projection 不存在、损坏、超限、来自 symlink、schema 不兼容或 identity 不匹配
- **THEN** endpoint 忽略 projection 并调用现有 authoritative compute；该 fallback 不执行任何写入

#### Scenario: A complete active universe is computed

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
- **THEN** response MUST 保留该 product item并返回 `weekly_trend=unavailable`；D1 的同类
  integrity failure 和 W1 的 `MAPPED_CONTRACT_DATASET_MISSING` 仍 MUST fail closed

### Requirement: Market Home derived projection is removable and never authoritative

Projection SHALL 固定存放在 active Canonical root 下：

```text
<canonical_root>/.derived/market-home-overview.json
```

该文件 MUST NOT 被视为 Canonical Bar、Catalog row、MainContractMap 或策略事实。文件删除后，
系统 MUST 能完全依赖 authoritative compute 返回同一 HTTP contract。

Projection envelope MUST 使用 schema version 1，并绑定：

- timezone-aware `generated_at`；
- `target_as_of`；
- 对 active product 顺序与 taxonomy `name/sector` 的 deterministic SHA-256 digest；
- strict `MarketHomeOverviewResponse` payload。

`payload.target_as_of` 与 `payload.data_as_of` MUST 等于 envelope target day。文件 MUST 为普通文件，
不得通过 symlink 读取或写出 Canonical root 的 `.derived` 边界；文件大小 MUST 大于 0 且不超过 2 MiB。

Natural after-market refresh MUST default closed. The factory MAY compose a refresh callback only
when the owner-created local activation marker contains the exact enabled value; no API request,
test, release identity or Runtime promotion implicitly enables it. When enabled, refresh MUST hold
the same maintenance lease as authoritative apply across compute, final identity check and publish.

#### Scenario: Projection is atomically refreshed

- **WHEN** after-market core maintenance 已完成 Canonical publication、`canonical_updated`、rank1/Live
  reconciliation 与 cleanup，activation marker 已启用且 maintenance lease 可得
- **THEN** projection writer uses a trusted same-directory descriptor, writes and fsyncs the temporary
  file, atomically replaces the current file, and fsyncs the directory before releasing the lease

#### Scenario: Projection refresh is not enabled

- **WHEN** the activation marker is absent, malformed, or disabled
- **THEN** after-market MUST NOT compose or call a projection refresh callback and MUST NOT create a
  production projection

#### Scenario: Projection refresh fails after core maintenance

- **WHEN** projection compute、serialization 或 atomic publish 失败
- **THEN** after-market 仅记录安全 warning，不 retry、不发送 projection-specific notification，且已成功的
  core maintenance 结论保持成功；因为旧 projection 已在 mutation 前失效，overview API 自动回退现场 compute

### Requirement: Authoritative apply paths invalidate projection before mutation

任何正式 `guiyi data update --apply`、`guiyi data refresh --apply` 与自然 after-market apply MUST 在
`HistoricalDataManager` 已取得其 authoritative apply maintenance lease 后、任何 metadata/Canonical mutation 前失效
shared projection。Dry-run、audit 与 provider readiness 未通过的 after-market MUST NOT 为此触碰 projection。

Projection invalidation failure MUST 在任何 manager apply mutation 前 fail closed，禁止让 metadata/Canonical 已变化但旧
projection 仍可被读取。人工 apply 成功后无需同步重建 projection；在下一次自然 after-market refresh 之前，
overview API 可以使用 authoritative compute fallback。

#### Scenario: Manual refresh rewrites same trading day

- **WHEN** 用户授权 `data refresh --apply` 重写了与旧 projection 相同的 target day
- **THEN** 旧 projection 已在 manager action 前删除，因此日期未变化也不能误命中旧结果

#### Scenario: Apply invalidation cannot be completed

- **WHEN** projection 文件或 `.derived` 边界无法安全失效
- **THEN** manager apply MUST NOT 开始任何真实行情/metadata mutation

### Requirement: Overview preserves generic market authority and transparent degradation

Overview item 的名称与 sector MUST 来自 taxonomy；dominant summary 仅提供 current actual
contract、mapping date 与 exchange。Item SHALL 只包含 completed D1 close、generic
`ResearchMetrics`、D1/W1 trend 与 generic reason codes；不得包含 strategy、buy/sell、entry/exit、
position、target、order 或任何退役策略事实。

构造时 universe MUST 非空、normalized、唯一，taxonomy keys MUST 精确匹配。缺失或重复
dominant identity、coverage failure、mapping/physical integrity failure MUST fail closed as a typed
HTTP 409；API 不得泄露内部异常。

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

### Requirement: Market Home Web preserves independent read authorities

`/market` SHALL 在首屏并行读取且只读取一次 Market Home overview、Runtime health 和 current HTDY
Event。页面 MUST 保留各资源最后一次成功快照，并把失败单独标识为 stale/unavailable；它不得由
Runtime heartbeat 推导 overview/HTDY 状态，也不得由 Event 空列表推导策略正常静默。浏览器不得调用
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
- **THEN** it has the approved size, color and Chinese accessible label, while the adjacent Event copy remains an observation rather than a trading instruction
