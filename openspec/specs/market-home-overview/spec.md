# Market Home Overview Specification

## Purpose

定义 Market 首页在不恢复任何退役策略的前提下读取 completed D1/W1 市场事实、独立 completed 1m
行情以及 immutable Alert Events 的只读合同。Market Home overview 使用可删除、可重建的 derived projection
加速常态读取，但 `MarketHomeOverviewService -> MarketDataService` 始终是唯一计算 authority。
该能力只为用户复核提供事实，不构成交易建议，且 `auto_order=false`。

## Requirements

### Requirement: Market Home overview uses one authoritative completed snapshot

`MarketHomeOverviewService` SHALL 从 `load_active_products()`、`load_product_taxonomy()`、
`DatabaseCoverageSource.latest_complete_day()` 和 `MarketDataService` 组合 completed D1/W1 response。
现场 compute 时指标 Bar 查询 MUST 为每个 active product 至多一次目标日 rank1 physical contract D1 和一次 W1；
D1 历史缺失时 MAY 额外一次只查询目标日端点以独立证明报价，该报价不得用于替代完整指标窗口；
同一物理合约成为主力前的合法历史 MAY 用于 warm-up，但不得跨合约计算价差、量比、OI 变化或 ATR。
目标日、主力合约和统计合约身份 MUST 显式可复核；日线与周线都按统一 target day 截止。
dominant summary MUST 只读取一次。该 service MUST NOT 建立 provider、Redis Live 或写服务。

每个 participant 都是有统一 target day completed D1、并通过 dominant identity 校验的 product；它不要求
`price_change_1d` 可计算。summary 的 `price_up_count`、`price_down_count`、`price_flat_count` 与
必填、非负整数 `price_unavailable_count` MUST 精确分割 `participant_count`。`price_change_1d=null`
仅计入 `price_unavailable_count`，不得视为 flat；这包括已保留的 authoritative all-zero、zero-volume
D1 predecessor 使 target-day 变动率不可计算的情况。

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

- **WHEN** product 有 target-day D1，但该合约没有已提交 W1 历史
- **THEN** response MUST 保留该 product item并返回 `weekly_trend=unavailable`；D1 的同类
  非缺失完整性错误仍 MUST fail closed；W1 已确认历史缺失须仅禁用周趋势并显式披露

### Requirement: Historical D1 price interruptions do not hide a recovered quote

Market Home SHALL use the explicit MDS D1 quality window for the target-day physical owner.
The requested window MUST be covered exactly by valid Bars and authoritative source exceptions;
missing endpoints MUST fail the affected history read; corrupt partitions or missing identity/Calendar/Session MUST still fail the snapshot closed.
The last authoritative D1 source-exception endpoint, including `PRICE_UNAVAILABLE` and
`NONPOSITIVE_CLOSE`, is a calculation boundary. D1 metrics SHALL use only the continuous suffix
after that endpoint and retain their existing warm-up/null rules. No price is synthesized and no
older valid Bars are fetched to replace exceptional endpoints. W1 remains an
independent strict read with no D1 substitution. Missing W1 history disables only weekly metrics and emits `weekly_history_unavailable`; source-price failures emit `weekly_price_unavailable`. Newow formulas and reference trades are unchanged.

An item with a valid target-day D1 Bar SHALL remain a participant even when its historical window
contains source exceptions. Its `reason_codes` SHALL include `daily_price_interrupted`, and
`daily_rewarming` when the post-interruption daily trend is not ready. Desktop and mobile SHALL
show the interruption disclosure.
If D1 history has unknown missing endpoints, a separately verified target-day quote MAY remain
visible, but ALL D1 metrics MUST be null/unavailable and `daily_history_unavailable` MUST be shown,
never normal rewarming. This does not repair the historical data or prove strategy readiness.
Only an error with both code and reason `DATASET_OR_PARTITION_MISSING` is eligible; extra, duplicate,
wrong-day endpoints and missing Calendar/Session remain integrity failures. The headline SHALL identify participants as target-day D1 quote
availability, not Newow strategy readiness or complete historical indicator coverage.
The metric policy identity SHALL be `physical_owner_quality_v4`, invalidating older projections
without rewriting production data or projection files from HTTP reads.

#### Scenario: A historical gap is followed by a valid target-day quote

- **WHEN** a verified source exception is followed by only one valid D1 Bar at target day
- **THEN** the product and its close remain visible; daily change and daily trend are unavailable
- **AND** subsequent sufficient continuous Bars restore each metric under its existing warm-up rules

#### Scenario: The target day itself has no usable source price

- **WHEN** the target-day endpoint is `PRICE_UNAVAILABLE` or `NONPOSITIVE_CLOSE`
- **THEN** the product is counted unavailable; an older close MUST NOT be labeled as the target-day quote

### Requirement: Market Home derived projection is removable and never authoritative

Projection SHALL 固定存放在 active Canonical root 下：

```text
<canonical_root>/.derived/market-home-overview.json
```

该文件 MUST NOT 被视为 Canonical Bar、Catalog row、MainContractMap 或策略事实。文件删除后，
系统 MUST 能完全依赖 authoritative compute 返回同一 HTTP contract。

Projection envelope MUST 使用 schema version 3，并绑定统计口径版本；schema 2 的旧统计缓存 MUST 被拒绝并重算。

- timezone-aware `generated_at`；
- `target_as_of`；
- 对 active product 顺序与 taxonomy `name/sector` 的 deterministic SHA-256 digest；
- strict `MarketHomeOverviewResponse` payload。

`payload.target_as_of` 与 `payload.data_as_of` MUST 等于 envelope target day。文件 MUST 为普通文件，
不得通过 symlink 读取或写出 Canonical root 的 `.derived` 边界；文件大小 MUST 大于 0 且不超过 2 MiB。
v1 或其他 schema version 的 envelope MUST 作为 projection miss；`MarketHomeProjection.read()` MUST
只回退 authoritative compute，且不得因该 fallback 写入或升级旧文件。

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
dominant identity、mapping/physical integrity failure MUST fail closed as a typed
HTTP 409；API 不得泄露内部异常。已分类的指标窗口历史缺失仅隔离相应指标，报价须独立证明，不能宣称完整历史。

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

#### Scenario: Current day has no Alert Event

- **WHEN** current trading day 已解析且没有 registry-owned Alert Event
- **THEN** response 返回 `status=ready` 和空 items；这不代表 Runtime 正常静默

### Requirement: Market Home Web preserves independent read authorities

`/market` SHALL 独立读取 Market Home overview、Runtime health、消息和本规范定义的批量行情资源。
品种目录 SHALL 独立读取既有 `/market/dominants` 批量接口，只用于搜索、导航和消息品种筛选，
不得从 overview 的参与行情行推导目录，也不得用目录补造缺失行情。消息按需加载且不阻塞市场列表。页面 MUST 保留各资源最后一次成功快照，并把失败单独标识为
stale/unavailable；它不得由 Runtime heartbeat 推导 overview/Alert 状态，也不得由 Event 空列表推导
Runtime 正常静默。品种目录只使用上述单一批量目录读取；日周策略事实另外读取只读
`/api/v1/market/newow/home-cards`，每次请求一个品种、最多两个并发，逐卡显示，不复用详情连接。
不得发起其他 per-product 行情请求或任何写请求；行情增量
只允许一个 server 固定 operational Scope 的批量 WebSocket，不复用60个单品种详情连接。

返回首页 SHALL 立即恢复已成功的列表、筛选、排序和滚动位置；有效缓存不得因重新挂载或浏览器重新
可见而被清空并强制全量刷新。缓存 MUST 有有界失效条件；必要刷新在保留旧结果的同时执行，旧结果
仍保持自己的时间与 freshness。并发请求 MUST 去重，过期身份响应不得覆盖新资源；timer/listener/socket
由单一生命周期 owner 管理。可见页面 SHALL 在既有 60 秒周期检查 overview 和目录的五分钟缓存
及失败状态；未过期的成功快照不重读，失败资源至多每周期发起一次合并后的恢复读取，隐藏页停止定时器。

#### Scenario: Overview is slow or has no participating quote rows

- **WHEN** overview 首载未完成、请求失败或有效响应的参与行情行为零
- **THEN** 独立目录成功时，黄金和焦煤仍可搜索、导航与消息筛选；目录仅发起一个合并后的批量读取，
  目录失败/加载状态独立呈现，不影响其他资源

#### Scenario: A resource becomes unavailable after a successful snapshot

- **WHEN** overview、Runtime、消息或批量行情任一资源刷新失败
- **THEN** 页面保留该资源的最后成功快照并仅将该资源标为 stale；其他资源事实保持独立

#### Scenario: Maintenance progress and historical audit remain distinct

- **WHEN** the existing Runtime response contains schema-v3 after-market progress and optional `weekly_audit`
- **THEN** the mounted trust strip uses that same Runtime request to show attempt/stage/product/partition/elapsed, successful read and committed-publish operation counts, optional known totals/retry time, plus a separately labelled `operational` full-history audit cutoff/findings summary
- **AND** unverified running is visibly degraded, unknown totals do not become percentages, cached Runtime remains marked stale, and weekly findings do not imply current Runtime failure or healthy history

### Requirement: Market Home uses frozen non-trading visual semantics

共享图标默认色值 SHALL 为上行 `#E63935`、周期同向 `#FF9601`、下行 `#35C759`、中性 `#017AFF`、数据不足
`#98A2B3`，默认尺寸为 Legend 40px、表格状态 28px、Trend/HTDY micro 24px。白色首页 SHALL 仅在自身根节点将上行设为 `#FF403A`、下行设为 `#22B95D`、中性蓝设为 `#365AF5`、Legend 压缩为28px，保留表格28px与方向 micro 24px；不得改变详情页或全局指标颜色。图标必须有中文可访问语义，
业务文案只能使用上行、周期同向、下行、中性、日周未同向、数据不足；不得改写为买入、持股、卖出、空仓、建仓、清仓或订单语义。

日周不同向 SHALL 使用浅灰底分向图标与“日周未同向”可访问语义，不使用无解释横线；数据不足
MUST 保持独立图标与状态，不得改写为未同向。桌面与窄屏 SHALL 使用一致映射。

#### Scenario: A user reads a state icon without color

- **WHEN** Market Home displays a frozen state icon
- **THEN** it has the approved size, color and Chinese accessible label, while adjacent HTDY/SuBing Event copy remains an observation rather than a trading instruction


### Requirement: Market Home uses approved daily and weekly strategy cards

`/market` SHALL 使用白色全宽布局、市场/消息 Tab、全局品种搜索、期货板块选择、报价和本地排序。
市场主体显示日周策略卡，替代旧行情表格；不恢复研究观察侧栏或底部移动导航。板块与总数来自
overview authority，卡片仅为真实参与行情品种生成；目录不得补造缺失报价。卡片标题进入 Newow
趋势 actual_dominant 1d；各策略图表入口保留自身策略与选定周期。板块按钮换行不得拉伸尾项。

#### Scenario: A user compares independent daily and weekly strategy facts

- **WHEN** 用户读取或展开品种策略卡
- **THEN** 趋势、震荡分别显示D1/W1状态；展开后分别选择周期并显示四阶段、目标、吸筹、参考成本、目标空间和事实截止
- **AND** 所有价格绑定同物理合约、owner、计算段及输入身份，参考成本仅来自有效BUILD；预热或缺事实不补造状态、价格或成本
- **AND** 策略事实保留page_parity=true、executable=false，不代表成交、真实仓位或因果收益；报价截止与策略截止独立显示

#### Scenario: A user sorts or filters the available futures locally

- **WHEN** 用户点击默认、价格、涨跌幅、成交量或持仓量排序按钮或板块筛选
- **THEN** 保留既有本地排序、缺值末尾和稳定symbol规则；按钮支持键盘操作，刷新及返回恢复有效偏好
- **AND** 策略读取集合仅来自当前板块筛选后的行，并保留页面排序顺序；板块、排序或authority变化取消旧generation，旧响应不得覆盖新集合；趋势/震荡切换复用同一已接受双策略快照，不重新读取

#### Scenario: A user scrolls to additional strategy rows

- **WHEN** 首次进入首页或滚动到新的品种行
- **THEN** 初始仅提交前8行，后续通过视口观察增量入队；离屏未读取的行标记待查看，不伪装为已确认或正在读取
- **AND** 同一authority内增量入队不取消已开始请求、不重复已入队品种；新可见行取得下一空闲slot，保持至多两并发
- **AND** 没有视口观察能力时仅提交前8行，由用户显式读取更多；不得自动启动全60品种重算
- **AND** 运行健康独立读取，不阻塞报价显示、行情刷新完成或后续策略刷新；旧策略保留仍明确标注其事实截止和刷新失败

#### Scenario: One strategy request fails during refresh

- **WHEN** 卡片或某周期读取失败
- **THEN** 周期独立失败，不隐藏其他品种；刷新失败保留已接受策略快照并明确标注，首次失败不造数
- **AND** loader至多两并发、可取消，旧generation响应不得覆盖新快照；不修改策略参数或行情事实

#### Scenario: A full desktop or narrow viewport displays fixture participants

- **WHEN** 使用受控60品种fixture验收桌面及390px布局
- **THEN** 全部卡片纵向可达且无横向溢出；展开、收起、独立周期切换与数据失败均可访问
- **AND** 参与/总数、缺失和过期状态仍由各自authority提供；fixture不代表生产或原站逐像素验收

### Requirement: Home summaries and lazy reference performance have separate read contracts

`/api/v1/market/newow/home-cards` SHALL 使用 `newow_home_cards_v2`，只读取日周策略摘要、参考价格、控盘、提示和快照上下文，不计算历史参考收益。同一请求内同权威输入的行情与策略无关指标可共享，但跨请求仍验证权威身份、质量与完整预热。快照解析与摘要查询复用同一请求内已验证的service及其取消/截止条件；Calendar/Session批量验证结果保留于该请求，不逐日重查，不跨请求或事务缓存行情权威。

`/api/v1/market/newow/home-card-performance` SHALL 为只读接口，要求品种、趋势或震荡策略、带时区截止时间及对应快照 token；返回 `newow_home_performance_v1` 的精简日线页面参考收益、交易数、统计区间和来源身份，不返回曲线或交易明细。快照冲突 MUST 显式拒绝，不能拼接当前摘要和旧收益。

前端 SHALL 在品种展开时立即显示摘要，再独立补载趋势和震荡收益；未展开不请求收益，重复展开或进行中请求去重，失败不阻塞其他卡片。详情仍按分区读取完整图表、参考交易、解释与辅助指标，摘要不可作为图表缓存；可复用已验证的对应日周快照上下文。

资源存储 SHALL 仅限当前浏览器会话，最多120项、32 MiB、5分钟有效期，按最久未使用淘汰，命中不延长有效期。身份 MUST 包含品种、周期、物理合约、策略/公式版本、数据修订、快照 token、窗口及 schema。离开页面只解除订阅，不取消其他订阅共享的读取；主动刷新、参与集合或权威身份变化须失效对应资源并隔离代次。收益快照冲突至多触发一次该品种摘要恢复，不重取全量集合。

策略状态、页面参考收益与未来账户订单/成交/持仓/净收益 MUST 保持独立身份。页面结果继续标记 `page_parity=true`、`executable=false`；分钟报价不触发日周重算，页面读取不得触发订单或重建账户持仓。未来账户投影由 Ledger 与账户事件驱动，本轮不新增账户接口。

#### Scenario: A user expands and revisits a strategy summary

- **WHEN** 用户展开、收起并再次展开同一快照，或从详情返回首页
- **THEN** 未过期结果与进行中请求复用；摘要立即显示，收益加载/失败独立展示；详情图表仍须有自己的完整响应

#### Scenario: A refreshed authority rejects an old performance owner

- **WHEN** 主动刷新、权威身份变化或收益接口拒绝旧 token
- **THEN** 新旧代次隔离，失败仅保留并标记旧快照，旧请求不能覆盖新状态；token 冲突只恢复受影响品种，恢复失败不循环重试

### Requirement: Home quotes use a separate completed minute authority

`/api/v1/market/research/home-live/ws` SHALL 使用 `schema_version=1`，拒绝客户端自选品种/周期参数。
`snapshot` 包含 `scope=operational` 和完整 items；`quote` 包含单项 item；`reset` 包含新身份 items
并替换旧 overlay；`unavailable` 提供安全 typed code 并结束故障连接。各 frame 保留 observed_at。
价格和比率 MUST 以 Decimal string 或 null 传输；phase 为 TRADING/BREAK/CLOSED/UNKNOWN，source 为
completed_1m/completed_1d/none，availability 为 live/historical/unavailable。availability=live
只表示该值来自合法 completed Live 数据，不代表 tick 级即时价格或策略已确认。

`reset/AUTHORITY_CHANGED` MUST 仅用于 operational symbol 身份集合、physical contract 或 trading day
变化。相同身份的定时补读、价格更新及同 Bar 的 phase/source/availability/昨收状态修订 SHALL 使用
`quote`，不得使 overview 缓存失效；仅用于服务器缓存管理的时间不得成为可见身份变化。同批 quote
可以共享 observed_at，消费者 MUST 逐品种处理，拒绝旧 observed_at/旧 Bar 和未经 reset 的合约/交易日变化。

首页分钟报价 MUST 使用版本化批量 read contract，固定读取 server operational products 的当日 rank1
物理合约。每项 SHALL 携带 symbol、physical contract、trading day、bar end、source、availability 和
phase，以及最新有效 completed 1m close。未完成 Bar、heartbeat、其他合约或 synthetic price 不得成为报价。
行情 overlay 不得修改 completed D1/W1 overview，也不得使其 generic 指标成为策略或账户事实。
当日 Live 冻结 subscription 与最近已发布 Historical Map 的物理合约允许不同；Historical owner
不得成为合法 Live 报价的显示 Gate。此时 SHALL 明确显示报价合约，保留原日周字段及其身份，
涨跌幅只消费该报价自身的同合约昨收结果，不借用旧 overview 基准。

价格 SHALL 显示来源与时间，明确分钟级更新而非 tick 实时。涨跌幅 MUST 由后端用 Decimal 按
`(price / previous_close - 1)` 计算；previous close MUST 来自当前 physical contract 上一完整交易日
的权威 D1，不是 actual-dominant 上一项，更不是昨结算。缺失、零基准或合约不匹配 MUST 返回 null
及可识别原因。日周趋势、量比、增仓率 SHALL 继续按 completed-period authority 展示并标明收盘口径。
前端排序 MUST 使用当前显示的价格/涨跌幅，空值始终排后，不通过浏览器重算指标或补齐基准。

该 reader MUST 复用现有 Calendar/Session、MainContractMap、MarketDataService 与 Live 读取能力；
不新增 provider、Runtime、数据副本或 production 写入。首帧和恢复读取 SHALL 有界，不能把60个
重型详情 snapshot 连接并发当作批量实现，不能每分钟重算整个 completed D1/W1 overview。

#### Scenario: A browser subscribes or reconnects

- **WHEN** 首页首次订阅或断线重连
- **THEN** server 先订阅再读取同身份快照，随后提供增量，处理快照与流间重复/乱序；前端只维护一个连接
- **AND** 断线保留最后成功值和 stale 标记；重连有界且恢复时补读快照，不等待下一根 Bar 才恢复

#### Scenario: Periodic reconciliation observes a new minute price

- **WHEN** 定时补读与新分钟 Bar 同时到达，且 operational Scope、物理合约、交易日均未改变
- **THEN** 只更新行情 overlay，不发送 authority reset，也不增加 completed D1/W1 overview 请求

#### Scenario: Live recovers without a contract change

- **WHEN** 同日同合约 Live availability 从不可用恢复且没有新的合约 state 通知
- **THEN** 批量 reader 仍能重新核对当前 availability 并恢复有效快照和后续 completed Bar，不能永久使用旧 unavailable 状态

#### Scenario: Trading day or physical contract changes

- **WHEN** server 的权威交易日或 rank1 物理合约发生变化
- **THEN** 旧 overlay 身份失效，新快照确认前不得沿用旧价格或旧昨收计算新合约变动；旧 generation 的迟到消息不得恢复旧值
- **AND** 即使完成周期 overview 仍返回旧 Historical owner，已确认的新 owner 报价仍显示；新合约无昨收时涨跌幅为 null，日周指标不变

#### Scenario: The market is closed or quotes are unavailable

- **WHEN** 品种处于休市、日间间歇、Live 不可用或数据质量异常
- **THEN** 可保留仍有效的最近 completed 值并明确 phase/source/time；没有有效分钟值时只显示明确标注的历史收盘事实或不可用
- **AND** 休市不等于断线，断线不等于已收盘，缺数据不得伪造零变动

### Requirement: Message tab reads bounded immutable event history

`GET /api/alerts/history` SHALL 接受 inclusive `start_day/end_day`、可选 symbol/rule_code、1到100
之间的 limit 和 opaque before；日期范围最多366天。响应保留查询身份、typed Event items 和
next_before；不提供无法由该查询证明的全量/未读数量。空结果为 ready 空列表，失败为安全 typed error。

消息 Tab SHALL 提供单个全局、有界、只读的历史查询，支持日期范围、品种与 registry Rule 筛选，以及
稳定游标分页。日期范围和 page size MUST 校验上下界；分页排序 SHALL 绑定 detected_at、bar_end
及唯一 Event id，游标与筛选条件绑定，不能对当前最近30条本地筛选后冒充全量历史结果或总数。

消息 SHALL 按全部、火天大有、苏冰分类，只有真实 registry-owned immutable Event 可以成为消息。
周末日期查询不依赖 current trading day resolver 成功。未知或不兼容身份 MUST fail closed，不把异常
当空列表。点击消息 MUST 保留 Rule、product、contract、frequency、bar_end 和 Event id 的既有定位语义。

Event 生成、notification attempted 与真实收件 MUST 分别表达；没有单条送达证据不得展示“已送达”。
该查询 MUST NOT 创建/删除 Event、重发、改变 Rule/Scope/audience/transport、执行 migration，或把
Runtime health 包装成不存在的历史系统消息。

#### Scenario: A user filters and pages through messages

- **WHEN** 用户按规则、品种、日期查询，并继续读取下一页
- **THEN** 筛选与分页在全局只读查询中执行，响应具有稳定边界且无重复跳项；筛选变化会清除旧游标，旧响应不能覆盖新查询

#### Scenario: A user returns from a later message page

- **WHEN** 用户从已经加载的第二页或后续页消息进入详情，再返回首页
- **THEN** 页面按查询身份先恢复成功列表、next cursor 与真实滚动位置，能够继续分页；不得先清空再只重取第一页
- **AND** 消息缓存具有数量与时间上限，有效缓存不重复读取；失效缓存可保留结果后台刷新，人工刷新显式重新查询
- **AND** 后台或人工刷新重新确定第一页与游标期间暂停续页请求；刷新前已发出的旧分页响应不得覆盖或追加到新结果，刷新失败仍保留可继续分页的旧完整结果

#### Scenario: Event storage is unavailable

- **WHEN** 消息查询失败或事件身份不兼容
- **THEN** 页面显示不可用/失败状态，保留已知快照的时间，不得写成“暂无消息”或展示伪造的发送成功状态

### Requirement: Persistent display snapshots revalidate independently

The browser SHALL persist successful directory, completed overview and per-product D1/W1 display cards in IndexedDB, isolated by origin/API environment, app version and schema/display contract. Budgets SHALL be at most 60 product cards, 10 MiB and seven days. Invalid, incompatible or expired entries SHALL be discarded; unavailable or stalled storage SHALL degrade to memory without blocking network reads. Restored facts SHALL show original time and remain stale until a successful current read. Runtime health SHALL NOT be persisted.

Visible resources SHALL reconcile every five minutes and after visibility/authority changes or manual refresh. Reconciliation SHALL preserve accepted rows, expanded state and scrolling, replacing changed product facts. Same-identity completed minute updates SHALL affect only the independent price overlay. Late obsolete responses SHALL NOT replace current ownership. Hidden products SHALL revalidate changed authority on readmission.

Persisted strategy tokens and reference performance SHALL NOT enable new reference queries. Cards SHALL reacquire ownership through the existing bounded authoritative read before lazy performance reads. Conditional directory/overview requests MAY reuse an in-session validated body; persisted bodies alone SHALL NOT satisfy HTTP 304.

#### Scenario: Reload with delayed or failed backend

- **WHEN** a valid persistent snapshot exists and network reads are slow or fail
- **THEN** cached facts appear first with time/stale disclosure; failures preserve them without declaring current authority or Runtime health

### Requirement: Verified reuse and conditional transfer preserve authority

Backend result reuse SHALL be bounded and occur after existing input checks. Overview metric keys SHALL bind checked D1/W1 Bars, owner, quality/interruption facts, metric policy and taxonomy. Newow shared calculation flights SHALL join only after every request lifecycle establishes its input fingerprint/dependency proof. Errors SHALL NOT become successful cached facts.

Existing unconditional derived-projection reads remain unchanged. An overview request with If-None-Match SHALL obtain a fresh authoritative snapshot before deciding 304; same-day correction SHALL remain observable. ETags SHALL NOT replace quality checks. Card tags SHALL retain token ownership; expired/renewed tokens cannot receive 304 for the old token. Period failures return typed bodies. HTTP reads MUST NOT publish/repair production projections.

#### Scenario: Same-day input correction

- **WHEN** checked Bars, quality, mapping or strategy/config versions change without changing the date
- **THEN** old calculation results cannot satisfy the new input identity; conditional transfer returns updated facts or a typed failure

#### Scenario: Concurrent valid inputs

- **WHEN** separate requests establish identical checked inputs concurrently
- **THEN** calculation may be shared while both retain authority validation and cancellation boundaries
