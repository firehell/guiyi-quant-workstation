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
缺失、损坏或 identity 不匹配时，MUST 返回lastgood及独立projection_status；完全无结果时明确不可用。HTTP endpoint 本身 MUST NOT
创建、更新、失效或修复 projection。

#### Scenario: A valid projection exists

- **WHEN** projection 的 schema、target day、active/taxonomy digest 与当前 authority identity 精确一致
- **THEN** endpoint 返回 frozen `MarketHomeOverviewResponse`，且不得调用 expensive `snapshot()`、
  `query_page()` 或 `list_latest_dominants()`

#### Scenario: Projection is absent or invalid

- **WHEN** projection 不存在、损坏、超限、来自 symlink、schema 不兼容或 identity 不匹配
- **THEN** endpoint 返回lastgood及独立过期/失败状态；完全无结果时明确不可用，不调用 authoritative compute，不执行任何写入

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
older valid Bars are fetched to replace exceptional endpoints. W1 SHALL use the existing MDS `query_contract_weekly_replay_quality` with
`weekly-d1-quality-v2` for the same physical owner and authoritative target-day Session close.
The full lifecycle quality window SHALL be validated before retaining the last 80 weekly
endpoints (normal Bars and interruptions together). Only persisted W1 Bars matching their
complete D1 source are accepted; no W1 Bar is synthesized. The latest proved anomalous week
is a calculation boundary. Weekly metrics use only the continuous suffix after that boundary,
with unchanged EMA21 readiness (22 valid consecutive weeks for adjacent EMA comparison).
The metric cache identity SHALL include the validated W1 Bars and interruption evidence.
Unknown missing endpoints disable weekly metrics; duplicate/extra endpoints, missing authority
or contradictory source values SHALL fail closed. HTTP reads SHALL NOT rebuild projections.
An interruption emits `weekly_price_interrupted`; insufficient post-interruption input also emits
`weekly_rewarming`. PC Web SHALL show only current rewarming or unavailable-history notices. Recovered
historical source anomalies SHALL NOT display a notice or be moved into a detail disclosure. Missing W1 history disables only weekly metrics and emits `weekly_history_unavailable`; source-price failures emit `weekly_price_unavailable`. Newow formulas and reference trades are unchanged.

An item with a valid target-day D1 Bar SHALL remain a participant even when its historical window
contains source exceptions. Its `reason_codes` SHALL include `daily_price_interrupted`, and
`daily_rewarming` when the post-interruption daily trend is not ready. PC desktop Web SHALL show interruption notices only while the affected trend is rewarming;
recovered interruptions remain in reason codes but SHALL NOT display a notice.
If D1 history has unknown missing endpoints, a separately verified target-day quote MAY remain
visible, but ALL D1 metrics MUST be null/unavailable and `daily_history_unavailable` MUST be shown,
never normal rewarming. This does not repair the historical data or prove strategy readiness.
For the D1 quote-only fallback, only an error with both code and reason
`DATASET_OR_PARTITION_MISSING` is eligible; extra, duplicate,
wrong-day endpoints and missing Calendar/Session remain integrity failures. The headline SHALL identify participants as target-day D1 quote
availability, not Newow strategy readiness or complete historical indicator coverage.
The metric policy identity SHALL be `physical_owner_quality_v5`, invalidating older projections
without rewriting production data or projection files from HTTP reads.

#### Scenario: A historical gap is followed by a valid target-day quote

- **WHEN** a verified source exception is followed by only one valid D1 Bar at target day
- **THEN** the product and its close remain visible; daily change and daily trend are unavailable
- **AND** subsequent sufficient continuous Bars restore each metric under its existing warm-up rules

#### Scenario: The target day itself has no usable source price

- **WHEN** the target-day endpoint is `PRICE_UNAVAILABLE` or `NONPOSITIVE_CLOSE`
- **THEN** the product is counted unavailable; an older close MUST NOT be labeled as the target-day quote

### Requirement: Market Home derived projection is removable and never authoritative

首页概览和策略摘要 SHALL 使用同一 `newow_home_projection_v1` 持久资产，其文件安全、
构建与版本校验合同见下文。旧 `.derived/market-home-overview.json` 不再作为首页active读入口；
旧数据维护路径的legacy失效清理不改变新资产的lastgood语义。删除派生文件后，只能由显式构建或
后续部署的盘后成功节点恢复，不得由HTTP请求重算。

#### Scenario: Source changes without rebuilding

- **WHEN** 源数据或配置修订后尚未完成新的构建
- **THEN** 策略摘要标记stale并保留旧值；概览接口返回lastgood及projection_status，冷启动浏览器亦可展示历史快照
- **AND** GET不得读取历史Parquet或执行策略/概览计算

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
品种目录 SHALL 独立读取 `/market/product-directory` 批量接口，只包含 active 品种的
`product`、`product_name`、`exchange`、`sector`（taxonomy 与 Instrument），不读取主力映射，
只用于搜索、导航和消息品种筛选。该静态目录的 ETag 与 Web 缓存有效期为 24 小时；旧
`/market/dominants` 快照不得迁入静态目录缓存。当前合约、映射日与报价仍须来自经验证的动态图表或研究读取，
不得从 overview 的参与行情行推导目录，也不得用目录补造缺失行情。消息按需加载且不阻塞市场列表。页面 MUST 保留各资源最后一次成功快照，并把失败单独标识为
stale/unavailable；它不得由 Runtime heartbeat 推导 overview/Alert 状态，也不得由 Event 空列表推导
Runtime 正常静默。品种目录只使用上述单一批量目录读取；日周策略事实另外读取只读
`/api/v1/market/newow/home-cards`，每次请求一个品种、最多两个并发，逐卡显示，不复用详情连接。
不得发起其他 per-product 行情请求或任何写请求；行情增量
只允许一个 server 固定 operational Scope 的批量 WebSocket，不复用60个单品种详情连接。

返回首页 SHALL 立即恢复已成功的列表、筛选、排序和滚动位置；有效缓存不得因重新挂载或浏览器重新
可见而被清空并强制全量刷新。缓存 MUST 有有界失效条件；必要刷新在保留旧结果的同时执行，旧结果
仍保持自己的时间与 freshness。并发请求 MUST 去重，过期身份响应不得覆盖新资源；timer/listener/socket
由单一生命周期 owner 管理。可见页面 SHALL 在既有 60 秒周期检查 overview 的五分钟缓存和目录的 24 小时缓存
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
generic overview及共享默认图标的业务文案只能使用上行、周期同向、下行、中性、日周未同向、数据不足，不得据此推断交易状态。下文独立身份的Newow策略卡可展示其已验证的页面买入、持股、卖出、空仓状态，不代表账户成交或订单。

日周不同向 SHALL 使用浅灰底分向图标与“日周未同向”可访问语义，不使用无解释横线；数据不足
MUST 保持独立图标与状态，不得改写为未同向。PC Web SHALL 使用一致映射。

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

#### Scenario: A user opens the composite strategy card

- **WHEN** 用户展开已发布的日周策略摘要
- **THEN** 主卡采用白底圆角、价格标题、信号胶囊、日周说明、空仓/买入/持股/卖出进度与底部控盘/普通参考收益标签
- **AND** 当前节点使用对应信号色及光环，已过节点为灰色勾选、未来节点为减号，进度蓝线止于当前节点；未知状态不绘制已完成进度
- **AND** 文案只消费既有综合状态与已绑定的成本/目标/吸筹/确认收盘事实；周线未确认不写成日周共振，缺价格不补造数值
- **AND** 成本来自有效BUILD时可显示“预估当前…附近可以买入”；没有成本时仅使用既有吸筹参考，不另算价格；卖出状态以确认收盘为观察锚点
- **AND** 数值和目标距离保留completed D1口径，分钟报价不改写策略说明、成本、收益或目标距离；普通收益不伪装成原站accuracy最佳收益
- **AND** 首页移除卡片下方截止时间折叠说明；来源、截止和非执行口径仍可在独立详情页复核，整个主卡保留详情导航

#### Scenario: A user sorts, filters, scrolls or expands the homepage

- **WHEN** 用户切换板块、排序、滚动或展开/收起卡片
- **THEN** 本地展示同一份全operational品种的双策略日周投影，不新增策略计算请求
- **AND** 日线普通页面收益已包含在投影中；没有按品种加载队列、视口准入或展开收益请求
- **AND** 刷新与返回保留偏好、已展开卡片、截止时间，晚到响应不能覆盖新代次
- **AND** 移除独立排序菜单；点击“涨跌幅”表头按降序、升序、默认循环，键盘可操作并显示当前方向；旧的其他排序偏好恢复为默认

### Requirement: Home strategy facts are built after source publication and read as one projection

`GET /api/v1/market/newow/home-projection` SHALL 返回 `newow_home_projection_v1`，覆盖服务端
operational集合，包含趋势/震荡D1/W1摘要、控盘/提示、目标/吸筹及普通日线页面参考收益。
响应保留生成时间、逐品种computed_at、逐周期源版本、原始as_of/bar_end/输入/公式身份，
以及 `ready/updating/stale/failed/missing` 投影状态，标记page_parity=true、executable=false。
同一资产一并保存原有generic overview，旧overview HTTP协议只读该资产，新增独立projection_status区分传输成功与源有效性；概览失败保留旧值并标记failed，不阻断其他品种构建。
GET不接受客户端品种/周期范围，不读取Parquet、不回放策略、不调用构建，不因缺失触发下载或修复。
支持ETag；ready只表示持久投影完整且版本与Catalog匹配，不替代Runtime或底层存储健康验收。

投影 SHALL 存于共享Canonical根旁的 `.derived/newow-home.json`；显式开发路径通过
`GUIYI_HOME_PROJECTION_PATH` 隔离。最多60品种/2MiB，无PostgreSQL迁移或Redis权威。
严格校验文件类型、大小、schema与内容hash，拒绝符号链接；文件锁排除并发构建，临时文件+fsync+
原子替换发布。进程重启直接恢复，崩溃遗留building只有持锁时才表示仍运行，旧结果不得改称最新。

版本 SHALL 包含品种/合约/映射、Calendar/Session、Dataset/Partition及质量元数据、coverage起点、
公式/profile/输入质量/展示和参考模型版本、目标日。配置身份包含universe六文件（含active顺序、taxonomy和history floor）及概览metric policy。Catalog使用全部相关行的有序id/xmin/ctid指纹，
不使用max时间或行数推断未修改；仅当PostgreSQL完整MVCC snapshot可见性与配置均相同、时钟未回退且尚未跨权威Session收盘或午夜边界时复用指纹。
指纹只在同一数据库连续生命周期内使用；数据库恢复/重建需清除并重建派生投影。
构建时仍经唯一行情入口校验完整物理输入，指纹不成为行情或Fill权威。

`guiyi home build [--products a,ag] [--output PATH]` SHALL 显式初始化/恢复投影；仅写派生数据，
不下载或修复源数据。每个变化的周期使用原resolver/策略/参考计算，未变周期复用；周线只用已完成周。
每个品种发布前后复核所有源身份，源变化或任一周期失败不得把旧/新周期拼成已确认综合结果；
保留该品种上一完整代次并独立标明失败，其他品种继续。
派生结果不得保留snapshot token/context；详情仍独立校验，可携带原有非授权home_context用于差异提示。

盘后行情发布、核对和清理成功且成功状态已持久化后 SHALL 尝试刷新首页投影；派生失败或中断不改写
行情维护成功，不触发下载重试、通知、Scope或交易。构建取消预算每周期最多600秒；不新增常驻任务。

前端 SHALL 一次读取全部摘要，本地缓存先显示并标为历史待验证，当前结果或HTTP错误独立覆盖/标记；
缺失显示计算中，更新失败保留旧结果。仅在非ready且页面可见/市场激活时每10秒前台轮询，最多30次；
隐藏、离开或切换消息时停止轮询。报价沿用独立completed 1m链，不触发策略或收益计算。
旧home-cards/home-card-performance/home-card-display-cache及其临时缓存/按品种队列 SHALL 退出active入口。
candidate preview不得读取正式持久投影，也不得通过旧入口回退。

#### Scenario: A source correction invalidates a projection

- **WHEN** 相同行数的数据修订、质量变化、换主力、Session或公式改变
- **THEN** 旧投影显式stale，源版本变化的周期由显式构建或盘后节点重建
- **AND** GET、刷新、板块和展开不得调用策略回放，也不得因文件缺失同步重建

#### Scenario: A rebuild fails or a prior process was interrupted

- **WHEN** 重建失败、超时、并发冲突或未完成进程退出
- **THEN** 保留最后成功事实及原始截止；失败不显示ready，其他品种可独立完成
- **AND** 损坏/缺失文件不伪造事实；锁释放后的building标为失败，允许显式幂等恢复

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

消息 Tab SHALL 提供单个全局、有界、只读的历史查询，使用默认七个自然日与全部品种，支持消息分类、周期和搜索以及稳定游标分页；隐藏的旧日期和品种筛选不得在页面恢复时生效。API 继续支持日期范围、品种与 registry Rule 筛选。日期范围和 page size MUST 校验上下界；分页排序 SHALL 绑定 detected_at、bar_end
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
- **AND** 消息缓存具有数量与时间上限，有效缓存不重复读取；失效缓存可保留结果后台刷新，页面重新进入时按缓存有效性重新查询
- **AND** 后台或其他已有刷新入口重新确定第一页与游标期间暂停续页请求；刷新前已发出的旧分页响应不得覆盖或追加到新结果，刷新失败仍保留可继续分页的旧完整结果

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

### Requirement: Independent trend supports an explicitly identified approximation

首页 SHALL 使用 owner 接受的 `guiyi_home_close_ma60_v1` 近似方向：同一物理合约、segment 和 calculation segment 截至确认 D1 锚点的最后60根已完成日线，Close × 60 >= 收盘价总和为 bull，否则 bear。只使用统一行情入口提供的有效连续输入，不跨物理/计算段补预热，不使用分钟报价、日周状态或主升浪代替。牛哇原始 trend 公式仍 UNKNOWN，本规则 SHALL 标记 approximate=true、page_parity=false、executable=false，不能表述为已确认的牛哇公式或交易信号。

结果 SHALL 带独立公式版本、输入摘要、父输入关联、截止及物理/计算段身份，纳入持久投影和配置失效指纹；GET与前端交互只读。W1不生成第二套方向，趋势/震荡视角共用D1方向。正常显示22px红升/绿降折线及12%浅圆底，中文说明标注MA60近似与截止；历史快照可保留方向但必须标明历史状态。缺少字段/版本未知/身份不匹配保留待确认；不足60根显示预热中，不伪造空头。

#### Scenario: Approximate direction has sufficient confirmed input

- **WHEN** 同一有效计算段具备60根已完成D1且锚点Close不低于MA60
- **THEN** 两种首页策略视角均显示红色上升折线，说明标记MA60近似
- **AND** 报价变化、排序、展开与板块切换均不重新计算该方向

#### Scenario: Old or insufficient independent trend input

- **WHEN** 投影尚无近似字段、公式版本未知或输入身份不匹配
- **THEN** 显示待确认灰色时钟，不猜测方向
- **WHEN** 换合约或计算段后不足60根有效D1
- **THEN** 显示预热中及已有根数，不借用旧段数据
- **WHEN** 公式版本变化
- **THEN** 持久投影变为待更新，显式构建后发布新事实

### Requirement: Home cards disclose publication validity and daily display basis

首页 SHALL 在日周图标旁紧凑标识历史结果，仅历史结果展开显示各自截至时间及受控失效原因，正常结果的时间放入悬停说明；
重复历史提示不占折叠行。全局摘要状态与分钟连接状态独立，正常已完成周期不得因报价变化失效。
投影可增补 period_reason_codes，值限于 SOURCE_VERSION_CHANGED、SOURCE_VERSION_UNAVAILABLE、
PERIOD_PENDING_UPDATE、SUMMARY_MISSING、SUMMARY_BUILD_FAILED、SUMMARY_BUILDING、SUMMARY_BUILD_INTERRUPTED 或 null；不得暴露内部异常。
卡片 SHALL 明示日线参考收益及参考交易笔数，不称最佳准确率；距离使用摘要日线收盘价，标记日线距离，基准价及截至时间放入距离的悬停说明，不增加常驻解释行。
阶段条只表示策略状态，清仓主句采用“当前某参考价已出现卖出信号”，悬停说明该价格属于日线参考，不能解释为实时价或真实卖出价。

#### Scenario: Live prices advance while completed strategy facts stay unchanged
- **WHEN** 分钟报价推进但已发布的日周输入及版本未变化
- **THEN** 报价独立刷新，日周状态、参考收益及日线距离不变
- **AND** 卡片悬停说明继续提供日线距离基准和各周期截至时间
