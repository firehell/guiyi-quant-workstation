# market-series-query Specification

## Purpose

定义 Market Web、指标和未来研究共用的唯一历史查询语言、主力映射解析规则、最小可复算响应，以及数据不完整时的 fail-closed 读取行为。

## Requirements

### Requirement: Shared chart history remains independent of strategy records

HTDY, SuBing and free chart workspaces SHALL use the same authoritative paged market
series controller. The initial page SHALL remain bounded. Explicit earlier-history loading
and left-edge loading SHALL preserve chronological deduplication, cancel obsolete identities,
and retain the successful chart and retry cursor when an earlier request fails. An exhausted
cursor SHALL be distinguishable from an error. Reference-record pagination SHALL NOT replace
or truncate the chart series, including SuBing D1. Strategy warm-up and record statistics SHALL
retain their own source and window contracts. Free chart SHALL NOT fabricate strategy trades.

#### Scenario: Earlier-page failure is recoverable

- **WHEN** loading an earlier page fails after a successful chart load
- **THEN** the chart and earlier cursor remain available and an explicit retry is shown
- **AND** retry loads that page without resetting the newest completed Bar

#### Scenario: SuBing daily browsing outlives the record window

- **WHEN** the user loads D1 Bars earlier than the reference-record window
- **THEN** chart history continues through the market paging API
- **AND** the record window and historical trade results remain unchanged


### Requirement: Ordinary historical reads prove every promised endpoint

Physical and actual-dominant interval queries and pages SHALL compare returned Bar identities with the Calendar, Session, lifecycle and rank1 owner endpoints for the requested committed window. A missing interior minute, session tail or page-adjacent endpoint MUST fail closed; a later Bar MUST NOT conceal the earlier gap. Page cursors retain their existing inclusive/exclusive contract. Maintenance strict readback MAY use its already frozen authoritative target endpoints rather than querying Calendar a second time, but MUST compare the complete returned sequence exactly. An all-zero `NO_TRADE` Bar does not become a usable research price solely because its endpoint exists.

#### Scenario: One minute is absent between returned Bars

- **GIVEN** five completed 1m Session endpoints and a committed physical partition containing only the first and fifth
- **WHEN** an ordinary range or page query reads the window
- **THEN** the read fails with a typed missing-data error instead of returning a shortened successful series

### Requirement: Narrow D1 quality-aware read never weakens strict market series

普通 historical series 读取遇到含 `PRICE_UNAVAILABLE` 的月分区 MUST 保持 fail-closed，
不得将有来源记录但无合法价格的交易日伪装成零价 Bar、无交易日或完整价格序列。
显式的 Newow D1 与 Market Home D1 质量感知路径 MAY 从同一 MarketDataService 读取合法 Bar、
逐日异常、完整端点覆盖与 rank1 owner，并在各自计算中形成断点。Market Home MUST 以目标日结束的最近至多 300 个权威端点定义窗口（异常也占一个端点），先精确验证合法 Bar 与异常的互斥完整并集，再使用最后缺价之后的连续 Bar。不得按已提交尾部缩短窗口、跳过未知缺口或向前凑足合法 Bar 数。W1、盘中周期及其他
未适配消费者不得借此绕过原完整性条件；映射、Calendar/Session 或物理身份不足时
仍 MUST 拒绝部分回放。

#### Scenario: Source price is unavailable on a completed D1 trading day

- **GIVEN** a month partition records an authoritative `PRICE_UNAVAILABLE` day without a valid OHLC Bar
- **WHEN** an ordinary historical series consumer reads that window
- **THEN** the read fails closed and does not synthesize a price or silently skip the day
- **AND** only the explicit Newow / Market Home D1 quality-aware reads may return the verified D1 interruption as a calculation boundary

### Requirement: Candidate Newow W1 quality replay proves the complete D1 source week

隔离候选的 Newow W1 质量路径 MAY 从 MDS 读取已存正常 W1 Bar 与由物理 D1 来源确定性重建的周中断。
每个已完成 ISO 周 MUST 使用 Contract lifecycle、Calendar/Session 给出的全部应有 D1 端点，要求正常 Bar 与
合法 `PRICE_UNAVAILABLE` 事实互斥且并集精确等于应有集合。质量周 MUST 只返回无 OHLC 的中断，
不得同时返回 W1 Bar；普通 strict W1 查询继续 fail-closed。正常周的已存 W1 数值 MUST 与同源 D1
聚合一致；查询不得临时聚合替代 W1 Bar。缺日、重复、错合约、旧 W1 冲突和来源 revision 不明 MUST 拒绝。

#### Scenario: A proven price gap and an ordinary missing day share a week

- **WHEN** 某周有合法 D1 缺价事实，但另一个权威 D1 端点没有 Bar 或质量事实
- **THEN** 该周仍为缺失来源，不能仅因存在缺价事实而认作完整中断周

### Requirement: Replay diagnostics preserve stable codes and distinguish missing facts

`MarketDataError.code` MUST remain backward compatible. Physical contract replay validation SHALL
add a bounded reason and sanitized context without changing accepted Bars or the lifecycle/session authority.
Missing prefix or interior/suffix endpoints SHALL be distinguished from extra endpoints, order/duplicates,
cutoff mismatch and metadata identity failures. Known missing Calendar/Session/contract metadata SHALL retain
their missing classification; unknown infrastructure exceptions MUST NOT become recoverable gaps.
Diagnostic context SHALL contain only validated symbol, physical contract, frequency, dates/instants and
bounded nonnegative counts; exception text, storage paths, SQL and adapter samples MUST NOT be public.

#### Scenario: A replay lacks its lifecycle prefix

- **GIVEN** the authoritative lifecycle endpoints include earlier Bars absent from a valid ordered suffix
- **WHEN** physical replay coverage is validated
- **THEN** the service preserves `CONTRACT_REPLAY_COVERAGE_UNAVAILABLE` and reports `REPLAY_PREFIX_MISSING`
- **AND** it includes only safe contract/frequency/time/count context and returns no partial replay

#### Scenario: A replay contains an extra endpoint

- **GIVEN** a replay contains an endpoint outside the authoritative lifecycle/session facts
- **WHEN** physical replay coverage is validated
- **THEN** the service reports `REPLAY_ENDPOINTS_EXTRA` without classifying it as recoverable missing data

### Requirement: Catalog URI byte integrity
Historical reader MUST 只打开 Catalog 精确引用的 URI，不得 glob、自选最新文件或回退固定路径。
`part.<sha256>.parquet` MUST 校验实际文件 bytes SHA-256，并从同一份 bytes 解析 Parquet，随后执行
既有 strict validation。旧 `part.parquet` MUST 仅在 Catalog 明确引用时兼容。

#### Scenario: Hash URI bytes mismatch
- **WHEN** 精确 Catalog URI 的文件 bytes 与文件名 SHA-256 不符
- **THEN** 查询 fail-closed，不尝试旧路径或其他月文件

#### Scenario: Reader holds the previous URI
- **WHEN** 新 pointer 已提交，而 reader 已取得旧 URI
- **THEN** reader 仍可读取保留的旧不可变文件，不把该行为表述为全局 snapshot

### Requirement: 三种 SeriesQuery
查询 SHALL 接受 `continuous|actual_dominant|contract`、symbol、frequency、start、end；contract
模式必须有 contract，其他模式不得提供 contract。连续/真实合约查询直接读取同频 Catalog 月分区；
actual_dominant MUST 按 rank1 Map 拼接真实 contract，不得存储重复 Parquet。

#### Scenario: 缺失真实合约分区
- **WHEN** actual_dominant 映射片段缺月、coverage 或可读文件
- **THEN** 整个查询 fail-closed，不回退 continuous

### Requirement: 周线 owner
actual_dominant 的 1w SHALL 只返回完整 ISO 周，并以该周最后交易日 rank1 contract 作为整周 owner。
分页读取 SHALL 在本次请求内复用同品种同 ISO 周日历，候选过滤与分页边界验证共用该事实；不得跨请求
缓存，后续读取必须能观察到日历更新。复用不改变缺失映射、缺失日历、物理完整性与游标语义。
完整周候选解析 MUST 先读取精确整周 Calendar。若该周最后交易日仍晚于 `as_of` 的上海本地日期，
该周明确尚未完成，MUST 返回未完成而不要求未来最后交易日的 Session；消费者可继续选择已完成的前周。
最后交易日已到时仍 MUST 使用权威 Session end 加一个微秒证明截止点，不得因 Session 缺失跳过该周。

#### Scenario: 周一尚未发布本周最后交易日 Session

- **WHEN** 9/28 盘后 Calendar 证明本周最后交易日为 9/30，而正式 Session 只覆盖 9/28 与 9/29
- **THEN** 当前周候选为未完成，已完成前周仍可按自身 Session 读取；9/30 已到后缺 Session 则显式失败

#### Scenario: 周中换月
- **WHEN** rank1 在完整 ISO 周内变更
- **THEN** 系统返回周最后交易日 owner 的真实合约周线

### Requirement: 最小可复算响应
成功响应 SHALL 返回规范化请求、bars、实际 coverage 与 resolved contract segments；不得返回
profile、binding、quality report、content digest、access-mode 或 legacy selector 字段。

`resolved contract segments` SHALL 仅表达该周期实际返回 Bar 的 owner 事实。需要跨周期研究和
query-invariant segment identity 的消费者 SHALL 另由 `MarketDataService.actual_dominant_segments`
读取与请求交易日窗口相交的完整 rank1 MainContractMap 分段。不同周期的 owner 子集 MAY 不相等；
每根返回 Bar MUST 同时被唯一的响应 owner 和全局权威 owner 覆盖，且 contract 一致。消费者不得以
D1 owner 推断 W1/60m，也不得把各周期 owner 子集的并集冒充全局 MainContractMap。

#### Scenario: 多月连续查询
- **WHEN** 所有相交月完整且可读
- **THEN** 服务按时间有序合并并去重返回窗口 bars

#### Scenario: 短主力段没有完整周线 Bar
- **WHEN** 一个 rank1 分段短于完整 ISO 周且该段没有 W1 Bar，但 D1/60m 存在 Bar
- **THEN** 全局权威分段仍包含该段，W1 响应 owner 子集可以省略它，逐 Bar owner 校验通过

### Requirement: Source quality union is an explicit opt-in authority

Catalog source quality SHALL 支持有界、版本化的 `PRICE_UNAVAILABLE` 与 `NONPOSITIVE_CLOSE` union；每个
expected D1 endpoint 必须精确属于有效 Canonical Bar 或一个已证实质量事实。普通 strict reader 继续拒绝
任何质量事实，既有 Newow reader 继续只接受其既有类型；只有显式 SuBing D1 seam 可读取完整 union。
未知分类、重复端点、缺端点、额外端点或 evidence identity 冲突 MUST fail closed。

#### Scenario: A partition mixes valid bars and nonpositive source facts

- **WHEN** 同月 expected endpoints 由有效 Bar 与带完整来源证据的 NONPOSITIVE_CLOSE 共同覆盖
- **THEN** opt-in reader 返回有序互斥 union，strict reader 拒绝该分区，且系统不制造 OHLC 或 NO_TRADE

### Requirement: Completed viewport windows use batched authoritative sessions

默认图表窗口 MUST 由MarketDataService经Catalog和Session clock批量解析completed交易日。
候选日历、下一交易日夜盘身份、Session有效区间和前交易日锚点必须保留；单日与批量窗口转换 MUST 共用权威逻辑。
不能为每个候选日重复读取同一Session/Calendar，再由consumer逐日重复查询。
completed筛选必须使用精确session end≤as-of以及coverage上限；周末、未完成日、缺失session/前交易日保持既有fail-closed。
批量优化不得改变物理合约、owner边界、周线完成或跨频回退规则，也不建立常驻行情cache。

显式 `calendar_since` SHALL 同时约束 Session 候选的交易日下界；上下界之外的交易日 MUST 在解析 Session
之前排除。该下界不得裁切属于首个合法交易日、但发生在前一自然日的夜盘；夜盘前交易日锚点仍须真实存在。
上市前交易日没有 Session 不应阻断合法区间；区间内缺失 Calendar/Session 仍 MUST fail closed。

#### Scenario: Listed product does not require a prelisting session

- **GIVEN** 品种及其 Session 从11月27日生效，日历中存在11月26日
- **WHEN** completed查询为夜盘覆盖从前一自然日开始，但明确交易日下界为11月27日
- **THEN** 不要求11月26日身份的Session，保留归属11月27日的合法夜盘，且只返回已完成交易日

#### Scenario: A one-Bar chart has a long available history

- **GIVEN** 960个权威交易日覆盖且只请求最新1根或500根图表
- **WHEN** 解析默认viewport
- **THEN** Session/Calendar数据库查询次数保持有界，不随逐日重复查询线性增长，窗口结果与既有completed语义一致


### Requirement: WebSocket reads are bounded and isolated from the event loop
WebSocket SHALL subscribe before reading its initial snapshot. Synchronous Catalog, Parquet and Redis
reads, including Session and client construction and cleanup, MUST run on a worker thread. Each read
MUST own a fresh resource scope; no Session may be shared across worker calls. Admission SHALL be
bounded to four outstanding reads per process, without an unbounded queue. Saturation MUST close the
connection as unavailable; it MUST NOT bypass Live eligibility, snapshot deduplication or state reset.
An accepted detail connection SHALL periodically reacquire one bounded display snapshot, so a connection
opened while Live is unavailable can recover without relying on a later state Pub/Sub event. Internal Bar
Pub/Sub payloads MUST carry physical-contract provenance; the detail socket SHALL reject a payload whose
contract or trading day differs from its current display authority. An authority change SHALL emit reset
before any Bar owned by the replacement segment; the reset's non-null trading day and contract SHALL
establish that replacement authority for following Bar frames.
Periodic refresh output MUST retain the display snapshot source: delayed post-close Bars SHALL remain a
`post_close` snapshot and MUST NOT be emitted as ordinary realtime Bar frames.

#### Scenario: A read is slow or its caller disconnects
- **WHEN** a synchronous read blocks or the awaiting connection is cancelled
- **THEN** the event loop remains responsive and admission remains held until the actual worker finishes
- **AND** all per-read clients close on their owning worker, while all asynchronous Pub/Sub clients close on exit

#### Scenario: Live recovers without another state event
- **GIVEN** a detail connection was accepted while its Live overlay was unavailable
- **WHEN** a later bounded refresh proves Live available under the same authority
- **THEN** the same connection emits the changed state and completed Bars after its existing watermark

#### Scenario: A late writer publishes after an owner change
- **WHEN** the bounded refresh or state event proves a new trading day or physical contract
- **THEN** the socket emits reset before replacement-owner Bars and rejects late old-owner Pub/Sub payloads


### Requirement: Runtime health represents loaded deployment identity

A formal Runtime health response SHALL independently verify installed and loaded identities
for its fixed local services. It SHALL expose matched, mismatch, unknown or proven disabled
identity diagnostics rather than interpret an absent marker in the API's version tree as
proof that a service running from another release tree is disabled. Unverified required
Market identities SHALL make operational health degraded unless it is already failed.
Optional weekly/reference services and Alert delivery diagnostics SHALL NOT redefine
Market operational health. Disabled SHALL require explicit loaded-label absence, absent
installed definition and absent relevant activation marker; permission or identity failures
SHALL remain unknown. The check SHALL NOT start, stop, promote or send anything.

#### Scenario: API and Market services run from different exact release trees
- **GIVEN** API v1.14.3 and a verified loaded Market service from v1.14.0
- **WHEN** the API's local Market activation marker is absent
- **THEN** health exposes the identity mismatch and unknown Market state with degraded overall
- **AND** it does not claim disabled Market services with a healthy operational path

### Requirement: Closed release warmup reads confirmed Canonical without Live fabrication

A stopped-world release warmup MAY use a private Canonical-only reader when authoritative operational
Calendar/Session proves a known rest interval, including CLOSED with no current trading day. It SHALL use
the existing quality, physical-prefix, mapping and completed cutoff checks and SHALL NOT create Redis
subscriptions, emit an Event, invoke transport or change the normal live signal reader.

#### Scenario: Confirmed historical day has already been cleaned from Live
- **WHEN** the release candidate warms a completed historical prefix in a proven closed interval
- **THEN** it reads the same validated Canonical values and physical mapping without requiring retired Live subscriptions
- **AND** unknown authority, quality or physical-prefix gaps fail closed and natural Live readiness remains unverified

### Requirement: Incompatible all-service releases require a bounded stopped cohort

The cohort installer SHALL freeze exact old and new identities for all ten services, preserve existing enabled
states and schedules, and support no schema change. It SHALL require all six continuous services enabled,
authoritative rest for all operational products and at least 660 seconds before the next Session.
The plan SHALL expire after fifteen minutes and be revalidated after read-only prewarm and immediately before
CAS. Downtime SHALL be bounded to 600 seconds. All old owners SHALL drain and exit before the sole registry CAS,
with maintenance and owner guards held; new consumers SHALL start before Feed and calendars register last.

#### Scenario: Prewarm or installation outlives the safe execution window
- **WHEN** the plan expires or the downtime budget is exhausted before CAS
- **THEN** the registry remains old and suspended definitions restore only their frozen prior loaded state

#### Scenario: Registry commit or new cohort outcome is unknown
- **WHEN** failure occurs after entering CAS
- **THEN** the attempt is retained as unknown, new work is cooperatively halted and automatic rollback or replay is forbidden
- **AND** closed idle evidence cannot substitute for a natural completed Bar, Event or recipient delivery

#### Scenario: A complete closed weekly calculation segment is still warming
- **WHEN** the cohort-only warmup validates a SuBing D1/W1 quality-v2 Canonical segment and the unchanged evaluator returns exactly WARMING_UP
- **THEN** it records the stream identity and bar count as warming, excludes it from calculated and keeps natural_signals_verified false
- **AND** default native warmup remains strict, while any quality, mapping or other error still blocks the cohort

### Requirement: Asynchronous teardown and precommit recovery remain evidence gated

The cohort host SHALL request each bootout once and wait for actual label absence and old PID exit within its budget. Before restoring a requested source, it SHALL wait for that teardown to finish before cancelling drain and restoring the frozen loaded state.

#### Scenario: A successful bootout response precedes actual job removal
- **WHEN** the old definition remains visible while launchd is still terminating it
- **THEN** the controller waits instead of treating the response as an exit or starting a duplicate owner

#### Scenario: A precommit unknown restoration is independently proved complete
- **WHEN** both original journals identify the same restore_unknown attempt with no CAS effects, and exact old registry/config/loaded state, fresh live PID/owner locks and scoped candidate absence are verified
- **THEN** an identity-only audit MAY use the historical plan after expiry, retain the original attempt bytes, publish a unique private recovery readback and update only the global checkpoint
- **AND** it SHALL NOT execute the old plan or accept post-CAS unknown; any new switch requires a fresh plan and attempt
