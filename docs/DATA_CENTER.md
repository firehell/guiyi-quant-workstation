# Canonical 数据基础

更新时间：2026-09-09

## 1. 唯一 active 数据语言

```text
DatasetKey
MarketDataset
MarketPartition
TradingCalendar
TradingSession
MainContractMap
MarketDataService
```

物理 Dataset 由 `(kind, symbol, series_or_contract, frequency)` 唯一确定。`kind` 只允许
`continuous|contract`；主连的 `series_or_contract=MAIN`；`actual_dominant` 是查询模式，不是物理
Dataset。

`1m` 的 `continuous/MAIN` 输入固定为 `{SYMBOL}88` 未平滑主力连续；`{SYMBOL}99` 持仓量加权指数
不是可替代来源，任何空窗都必须显式失败。期货 `1d` 的事实固定为 RQData
`futures.get_exchange_daily`：真实合约直接读取，`continuous/MAIN` 按每个交易日 rank1
`MainContractMap` 拼接对应真实合约。`1w` 仅由同一交易所日行情在完整 ISO 周内聚合，缺任一应有
交易日事实即失败。RQData 对零成交日返回 `volume=0`、有效正 `close` 且 O/H/L 同时为空或同时为零时，adapter
只允许用同一行 `close` 规范成平价 OHLC；交易所原始的全零 O/H/L/close 零成交行保留其事实，非零成交、部分价格缺失、部分零价或无效 `close` 仍须失败。
不得用 `get_price` 的期货日/周 `close` 或 `settlement` 互相替代。

## 2. Canonical 物理合同

```text
canonical/
  kind={continuous|contract}/
  symbol={product}/
  series={MAIN|actual-contract-code}/
  frequency={1m|5m|15m|30m|60m|1d|1w}/
  year=YYYY/
  month=MM/
  part.<sha256>.parquet
```

行字段为 `bar_end`、`trading_day`、`open`、`high`、`low`、`close`、`volume`、`turnover` 和
`open_interest`。价格和金额用 Decimal，量额聚合必须精确求和且不得继承进程 Decimal context；
无法无损表示为 Canonical Decimal 的来源必须在发布前拒绝。`bar_end` 是 UTC timestamp，identity 不在行内重复。

发布前必须完成 schema、主键单调唯一、OHLCV、交易日/session/frequency、coverage 和物理可读性
校验。新发布文件以实际 Parquet bytes 的全小写 SHA-256 命名为 `part.<sha256>.parquet`，不可变、
无覆盖，先完成文件与目录 durability，再在既有 DB 事务内 register/flush，并通过真实
`MarketDataService` strict-read 校验候选 Catalog URI。事务 commit 是该月新指针唯一可见点。
每 DatasetKey 每月只有一个 active Catalog pointer，记录 `coverage_start`、`coverage_end`、
`row_count` 与精确 `file_uri`；不要求目录中只有一个物理文件，不新增 schema、version table、
history API、sidecar 或发布清单。

提交前失败必须保持旧 pointer 与旧文件不变。commit 异常必须报告 `COMMIT_OUTCOME_UNKNOWN` 并停止
本批次，不自动重试、删除候选文件或回滚可能已提交的指针；必须另开独立只读事务确认提交结果。
旧文件保留以支持已经取得旧 URI 的 reader；本阶段没有 GC。原子单位是单个 partition，
不是多月、多周期或 metadata 的全局 snapshot。

真实更新前必须完成所有 consumer 升级并停止旧 writer；新 URI 发布后，不得盲目回退到无法读取新 URI
的旧 Runtime。代码集成不授权生产迁移、真实更新、release 或 Runtime promotion。

`contract` partition 必须包含全部 rank1 required Bar，同时其中每一条 Bar 都必须在该 Contract 的 active
lifecycle、TradingCalendar 与 TradingSession 内。这个 superset 合同允许保留同物理合约、上市有效期内的真实
warm-up prefix，但不改变 `actual_dominant` 的 rank1 owner；`continuous` 继续使用 exact expected equality。

## 3. 八表 Catalog

```text
exchanges
instruments
contracts
trading_calendars
trading_sessions
main_contract_map
market_datasets
market_partitions
```

`main_contract_map` 以 `(symbol, trade_date)` 唯一保存 rank1 当前事实。`market_datasets` 以四字段
identity 唯一；`market_partitions` 以 `(dataset_id, year, month)` 唯一，保存 coverage、URI、row count
和创建时间。未来回测所需参数应由新的回测合同设计，不阻塞 K 线底座。

RQData 的 `1m` Session start 是该段首根 `bar_end` 标签，例如 `09:01/10:31/13:31/21:01`。
adapter 在唯一 metadata 边界将其减一分钟后写入 DB，因此 active `TradingSession.start_time` 是统一
`SessionWindow(start, end]` 的排他边界 `09:00/10:30/13:30/21:00`。Historical expected bars、四种日内
聚合与 Live 首根分钟共用该 DB authority；任何层不得再次补偿。分钟不对齐、无效区间、重叠或不可解释
跨午夜布局都 fail-closed。

## 4. 更新、刷新与自然续传

`UpdateRequest.mode` 默认 `full`，公开 update 继续全历史核查；内部 `daily` 模式不接受 `since`。
daily 要求已有 continuous `1m/1d` Catalog baseline，并以完整 Calendar、连续 rank1 映射及 Catalog
分区索引选择当月、缺月、精确首尾落后月；新主力补已证明的 mapped 日期及缺失 W1 所需的同合约完整
ISO 周 D1 context（限制在有效生命周期内），不自动执行 lifecycle warm-up。
缺 baseline、映射断裂或无法确定边界时要求显式历史维护，不执行广域 metadata bootstrap；受限当天/下一
交易日 metadata seam 保留。旧月内部损坏由 full update/audit 检出，daily 不以 row count 或首尾完好声明
全月物理完整。完整 ISO 周仍通过既有 D1/W1 同源批次补齐，必要时读取跨月的 D1 context。

daily 按品种、数据族、月份展开目标并使用既有校验与原子发布入口；Calendar/Session 校验使用 batch
查询。派生源仅在当前 family-month 内复用已验证的 1m，Catalog pointer 改变立即失效，离开批次即丢弃。
可选 `MaintenanceObserver` 只报告 planning/reading/provider/publishing/aggregation 的有界身份、
计数和耗时，不决定处理范围。completed 是各阶段成功操作累计数，provider 按 fetch_many 批次计，
publishing 只在单分区 Catalog commit 后计数；这些数字不是去重分区数。total 未知时字段缺席，不伪造百分比。
阶段可嵌套，`stage_durations` 不得相加推导本轮墙钟时间。observer 失败停止本轮，不能当作
单族 provider 故障继续。无 observer 的既有调用保持兼容，last-success/status 文件不是进度权威。

`effective_start(symbol)=max(product_window_start(symbol), active_history_floor)`，其中
`active_history_floor=2023-01-01`。`update` 使用显式 `--through` 固定水位，先同步 metadata，后
优先完成基础 provider 日线 `1d` 与由其聚合的 `1w`，再按 active universe、Dataset、年月顺序续传基础
provider 分钟线 `1m`。每完成一个 1m dataset-month，立即生成四个日内派生月。

18:05 Runtime 先以只依赖 Calendar 的 `latest_metadata_day(operational 60)` 判断当天是否为交易日。
该判断要求每个相关交易所存在当天精确的 `provider=rqdata` Calendar 行；缺行或非权威行返回
`TRADING_CALENDAR_MISSING`，以 `attempts=0` 终止并保留失败事实，不能回退到昨天后伪装成
`NON_TRADING_DAY`。相关交易所解析出的维护日期不一致时返回 `TRADING_CALENDAR_CONFLICT`，不能用
最早日期跳过仍开市的交易所。只有所有相关交易所的权威结果一致且当天明确为非交易日时才允许跳过。
交易日再由持 maintenance lock 的
`HistoricalDataManager.update` 同步 metadata 后规划 coverage；不得先用可能尚未同步的当天
TradingSession 判定 `NON_TRADING_DAY`。受限 metadata 同步准备 operational 60 品种：
Calendar 覆盖当天至 ISO 周日或下一交易日（取较晚者），TradingSession 精确替换当天与下一交易日，
MainContractMap 仍只发布当天 rank1。
共享 Calendar 的夜盘字段只用同交易所、同交易日的 Session 正证据；不得把某日夜盘扩散到整个
请求区间，也不得从请求品种子集仅有日盘推导交易所无夜盘。交易日 false 必须由原始
`all_instruments(type="Future")` 完整合约集合及逐日生命周期确定当日品种全集，并由该全集每个
品种的当日 Session 完整覆盖且均无夜盘；缺失生命周期或任一品种 Session 时为 UNKNOWN。
该全集在筛选请求品种之前取得，不增加 provider 请求。非交易日可直接确定 false。
UNKNOWN 仅可保留 trading-day 身份一致的已有 Calendar；缺键报 `CALENDAR_NIGHT_AUTHORITY_MISSING`。
有证据的源事实与已有 Calendar 任一布尔字段冲突则整事务 `CALENDAR_SOURCE_CONFLICT`，不得自动
覆盖已更正的共享历史；实际纠正仍需绑定源证据、精确前像和独立执行意图。首次 bootstrap 或未来
交易日缺键不能靠猜测填充，必须补齐上述逐日权威证据后再同步。
下一交易日 Session 尚未由 provider 发布时精确返回 `NEXT_TRADING_SESSION_NOT_READY`，最多一小时后再
尝试一次；格式、重复或身份异常仍 fail-closed。这样夜盘 phase resolver 在夜盘前取得下一交易日 Session
事实，同时不会提前发布未来主力映射，也不写 Dataset、Partition 或 Parquet。

after-market 是可写命令。其进程边界若在会话、组装、状态持久化或维护阶段收到未处理异常，公开错误载荷
必须使用 `readonly=false`，不得因最终结果未知而声称本轮只读；weekly-audit 仍保持 `readonly=true`。

既有月等于 expected bars 时跳过；合法子集只下载缺失 bars 并重写完整月；不可读、extra bar 或
identity 冲突时重建相交整月。明确的 RQData 额度异常映射为 `PROVIDER_QUOTA_EXHAUSTED`：本轮
立即停止 provider 调用，保留已发布月，不发布当前未完成月，并返回 `status=partial` 与
`stop_reason=provider_quota_exhausted`。下一次完全相同命令从首个缺失目标续传。

缺失完整 ISO 周的 `1w` 时，同一 maintenance 批次会把该周对应的 `1d` 作为 refresh context；
RQData adapter 先读取完整周日行情，并在调用内按 `(contract, trading_day)` 复用同一 source
snapshot 生成 1d/1w。发布前先验证整组完整性，再按涉及的 1d 月分区、1w 月分区顺序分别提交 active Catalog pointer；不提供整组 snapshot 原子性；
跨月周会刷新两侧日线月分区。`continuous` 日线仍按每日 rank1 拼接；最终 owner 合约用于
`actual_dominant 1w` 整周聚合时，非 rank1 日只作为该周内部 source context，不进入
`actual_dominant 1d` 的可读结果。physical contract 的完整 ISO 周可因此包含成为 rank1 之前的 D1 日期，
但仍以 Contract lifecycle 为硬边界，不构成完整 lifecycle warm-up。dry-run 会显式列出由缺失周线带动的日线 refresh 窗口。

`refresh --symbol --since --through --apply` 强制重建窗口相交月中的 continuous 与所涉 rank1
contract 的基础 provider `1m/1d` 和日线派生 `1w`，再由 1m 重建四个日内派生周期。它不接受 repair plan，
也不产生额外进度或证据文件。

`contract-warmup` 只维护一个已验证 identity 的 physical contract：请求窗口从 `listed_date` 到不晚于最近完整
交易日的 `requested_window.through`；计划的 `effective_window.through` 再按 `expired_date - 1 day` 截断，获取该
contract 的 `1m/1d` 基础事实。CLI schema v2 必须同时公开两个窗口，不使用含义不明的单一 `through`；两者也进入
plan hash identity。省略 `--frequency` 时维持七周期；显式 `1d` 只规划/执行 `1d`，显式 `1w`
只规划/执行同源 `1d + 1w`，显式 `15m` 或 `60m` 仍只规划/执行同 contract `1m` 基础与所选
日内派生。payload 与 plan hash 必须同时绑定所选频率、完整 frequency scope 及其依赖，即使没有 target
也不得跨 scope 复用 hash。其它显式 frequency 均 fail-closed。`1w` 只由同一交易所完整日行情聚合，四个日内派生周期只由同 contract `1m` 生成。dry-run
只读输出稳定 plan hash；apply 必须在 maintenance lock 内重算并匹配该 hash，且不会写 continuous、其它 contract、
MainContractMap、Redis Live、Rule、Scope、Event 或 notification。任一显式 scope 的 provider、发布或派生失败
必须立刻停止该 contract 的后续 target。仅当同族同月存在待补 `1m` 目标时，才在开始派生前推迟到源发布后；
已经开始的派生/发布失败不得按缺源错误码推迟重试。额度耗尽返回 `partial`，不得报告 `passed`。分区失败可明确部分成功，不能自动重试。

同物理合约派生使用的 Session 窗口与 warm-up coverage 一致：按上市日、到期日前一日和 `through`
限制，日内数据另受 `RQDATA_INTRADAY_HISTORY_START` 限制，不套用 active history floor。
Calendar/Session 必须具备逐日权威事实，缺失即失败；`continuous` Session 查询仍保留既有维护起点。

warm-up 只读结果的 `scope_diagnostics` 保留整个 frequency scope 的逐分区有界原因及是否为计划目标，
包括不缺 endpoint 但含原始非正价格的 source companion。该诊断不改变维护目标、apply 规则或既有 plan hash。

### 当日 Live 缺口恢复

`GUIYI_LIVE_RECOVERY_ENABLED` 默认关闭，只有精确值 `1` 才组合恢复 worker。启用必须单独确认同一
approved Runtime root/version 下 Live 与 Alert 同时具备恢复水位及共享锁协议；已有订阅授权不自动包含
补取数据或恢复 Redis 写入。关闭时不实例化恢复 adapter/worker；只读诊断不创建锁或调用 provider。

恢复只处理 operational 品种、当日冻结 rank1 subscription snapshot 对应物理合约。Calendar/Session
定义完整 completed 1m 前缀，保留正常 Live 的两秒确认延迟，夜盘请求使用交易日；通过既有 RQData
公开 `get_price` 1m adapter 补取。身份、日期、重复、OHLCV、Session、coverage 或重叠事实冲突全部
fail-closed，不跨合约、不插值、不缩短前缀。数据仅进入当日 Live observation，不发布 Canonical。

一个后台 worker 合并待检查品种，调度间隔至少 60 秒；每品种每 Session 最多三次 provider 尝试，计数
存入当日 Redis，重启不重置。初始化及查询阶段的权限/额度失败停止当日后续 provider 请求。已有完整
1m 但派生周期缺失时，直接用原 1m 重建完整桶，不下载、不消耗 provider 次数。

缺失 1m、完整的 5m/15m/30m/60m 桶及单调恢复水位通过一次 Lua CAS 提交；提交前核对冻结订阅、原
series 与 recovery revision。已有相同内容幂等跳过，冲突拒绝，正常 completed 写入同样不得覆盖冲突。
恢复不发布历史 Bar 消息。数据查询在锁外，最终 CAS 和提交时钟在同品种进程间锁内；Alert 的窗口读取、
Event commit 与 one-shot send 持有同一锁，因此水位不能穿过 Event/send。锁由 OS 持有，无超时租约；
进程退出自动释放。锁文件限于 Runtime `.run/live-recovery-guards/{symbol}.lock`，按品种有界复用，不在
运行中删除。锁或身份不可证明时不继续提交。

诊断复用 MarketReadService、MDS lifecycle/session coverage 与已有物理分页入口：历史使用 Catalog
MainContractMap，盘中使用既有冻结 rank1 Live snapshot；当日 MainContractMap 尚未由盘后发布不构成
新的隐藏 Gate。分别报告历史 15m、当日 1m/15m 缺口；不可读历史保持未知，不能假装缺失数为零。

### 已捕获源数据的五根 Live 恢复

显式人工入口 `runtime recover-live-captured` 默认只读规划；`--apply` 必须携带新计划及精确计划哈希，
每次真实写入仍需 owner 对目标、环境、范围的一次执行意图。计划与源哈希仅绑定内容，不授予执行权限。
该入口不是后台 worker 的 retry/fallback，不改变正常 CLOSED 调度限制，也不扩大持续 Runtime 授权。

范围限同一自然日/交易日、operational 冻结 rank1 物理合约、收盘后完整 completed 1m 前缀，
捕获文件至多 512 KiB、225 行；增量必须恰为 1m/5m/15m/30m/60m 各一根。
CLI 读取显式绝对路径的当前用户普通文件，拒绝符号链接、硬链接、超限和读取期间变化；
源内容以 SHA-256 固定，复用 RQData 行规范化、Session/Calendar 与正式聚合。
额外行、缺行、重复、身份/日期、OHLCV/OI、完整桶及任一重叠事实冲突全部拒绝。
源文件来自先前经授权的真实查询；该入口无 provider/callback 能力，不能为了补齐输入重新下载。

provider 已耗尽的三次预算保持原值；零下载模式不 claim、不重置或借用其他 Session 预算。
计划冻结各 Session 预算及当日 circuit；权限/额度 circuit 非空、已记录预算消失或并发变化都停止。
在既有提交 Lua 中核对这些原值以及订阅、所有原序列/score、key 类型、有效 TTL、恢复 revision 后，
才允许一次追加五根并写实际提交时间的单调恢复水位。已有键不得过期后重建。
五个 ZSET 及恢复水位沿用 3 天 TTL，成功时会刷新，预算 TTL 不刷新；水位同时绑定源和计划哈希供只读 NOOP 证明。
这六个键的修改与共享锁文件使用均须包含在实际执行范围中。

CLI 仅从 clean detached annotated exact-tag Runtime 运行，Live/Alert/After-market 已加载 root/commit 必须匹配；
launchd 身份读取须保持块层级：识别 `= {` 与嵌套定时触发块 `=> {`，但 root/commit 只取
服务直接 `environment = {`，state/PID/WorkingDirectory 只取服务顶层；重复字段与不平衡块仍拒绝。
两条独立心跳须新鲜且明确证明该进程实际组合了恢复共享锁。缺字段的旧版本不合格；不能仅凭 shell
开关推断另一进程状态。心跳新增 `runtime_root`、`runtime_commit`、`recovery_guard_enabled`，
不改变 `alert:runtime-status` schema v6 或 Rule health 语义。未运行/已过期/未来心跳均拒绝。
盘后任务正在运行、同日盘后维护已尝试或状态不可证明时，要求重新诊断消费者与 Canonical/Live 边界。
使用既有 OS 锁协议的 `.run/live-recovery-guards/after-market.lock` 串行化盘后维护与人工恢复：
恢复先非阻塞获取此全局锁，再取品种锁，在两把锁内检查盘后状态并提交；盘后任务先获取全局锁，
从写 current_run 前一直持有到终态（含既有受限 retry），避免检查和提交之间启动维护。
该有界锁文件是新增的运行副作用，随新版本部署和后续 apply 分别确认；dry-run 不创建锁文件。

apply 重新解析权威身份并生成当前 cutoff，锁内提交时钟必须在 cutoff 后 60 秒内。
跨日、订阅/版本/源/预算/数据变化使计划失效；已有五根全一致且对应恢复水位可证明时仅只读 NOOP，
不重复刷新 TTL 或 revision。部分写入、Lua 错误、网络响应不确定均停止，不自动重试或回滚；人工入口专用 Redis client 关闭底层重试，连接/读写超时分别为 3/5 秒。
Lua 隔离不是错误回滚保证；结果未知后仅只读核对五根及水位，再由 owner 决定新处置。

恢复不发布历史消息、不调用 evaluator、不改游标/Scope/AlertEvent、不清健康故障或 acknowledgment、
不补发通知。输入恢复与自然 completed Bar 评估、通知实际送达及 RUNTIME_READY 分别验收。
具体命令和隔离测试入口只见 `TESTING.md`。

### 盘后 Runtime 状态合同

`.run/after-market-status.json` 写 schema v3；读取兼容旧 schema v1/v2。schema v3 在受监督自然盘后运行开始、任何
coverage/RQData/update 尝试之前写入 `current_run`，白名单化保留 `attempt/stage/updated_at/stage_started_at/elapsed_seconds`、
`current_symbol/current_partition/counters/stage_durations/retry_at`。阶段转换立即写，普通进度最多每 5 秒写一次；
中途崩溃保留 `current_run`，进度不续传也不是 checkpoint。建立新 run 前，writer 先有界读取旧摘要，
再安全地将同一自有普通文件 truncate/fsync 持久失效，然后原子发布初始 v3。初始、中间或终态权威写失败都以
`AFTER_MARKET_PROGRESS_UNAVAILABLE` 停止；已成功失效后不得重新暴露旧 passed。若连同文件失效都无法产生任何持久变化，
启动在新 run 建立前被拒绝；纯文件 reader 物理上无法观测这次未留下任何字节变化的尝试。`last_run.failure_notification`
只允许 `{attempted_at,state=provider_accepted|failed,error_type}` 公开字段，不保存 provider reference。

只读 Runtime health 从 `operational_products.txt` 对应的 `Instrument.exchange_code` 与权威
`TradingCalendar` 唯一解析 expected trading day：上海时间 18:20 前只考虑先前交易日，18:20
起当日可成为 expected day；交易所结果不唯一、产品/日历事实不完整或 chronology 无效时均
fail-closed。从未产生过状态时，只有当日为交易日且上海时间已到 18:20、当日已 due 才是
`degraded/missed`；周末/节假日和首次应执行时点前仍是 `pending`。已有状态时，最后成功日落后于
expected day 才是 `degraded/missed`。合法 `current_run` 也只是已持久的未验证摘要，不能证明 writer 存活或后续写会成功；
`updated_at` age 不超过 2h 为 `degraded/running`，超过 2h 为 `degraded/stuck`。无效、损坏或不可读状态一律 fail-closed 为 degraded。
与 expected day 匹配的终态失败保持 `failed/failed`，不能由旧成功日覆盖。

盘后失败通知是与 Alert Rule/Application Domain 分离的运维能力。公共手工 `guiyi data after-market`
不启用该能力；只有受监督自然执行的主业务失败才向 owner 发起最多一次 PushPlus 请求。
通知使用固定脱敏内容，含 trading day、公开 error code、attempts 与“系统运维提醒，非交易指令”；
不用 Topic、`AlertEvent`、DB、retry、replay 或 fallback。provider accepted 不等于送达；通知失败只记录
`failure_notification=failed`，不改写或重试主 after-market 结果。`missed/stuck` 只是 health，不会发送。
Canonical commit 结果不确定时，盘后状态保留 `COMMIT_OUTCOME_UNKNOWN`，本次停止且不重试，
不发布 `canonical_updated` 或执行成功后的 Live 清理；须用独立只读事务确认 Catalog 结果。

### 中断盘后运行的显式收尾

`data.close-interrupted-after-market` 默认只读；必须绑定现役 Runtime root、40 位 commit 和原状态字节 SHA-256。
它要求五服务 installed/loaded 身份一致、现役 checkout 为干净 detached annotated release，Live/Alert 声明
共享恢复保护开启、盘后进程明确 idle。只处理先前自然日的合法 `current_run`，不停止进程、不创建缺失锁。
数据依赖只能由目标 Runtime 的固定外部 `project.env` 与目标 universe 文件显式构造，不能使用执行 CLI 的开发配置。
配置的变量名只接受精确白名单且不执行 shell；参与收尾依赖的值只接受字面赋值与先前 dependency source
赋值展开。文件须自有 0600、父目录自有 0700。
现场历史配置中仓库已明确识别且当前无 active consumer 的退役变量名可以存在，但必须命中精确的 inert
键白名单。另外，已有活跃进程仍可消费、但本收尾命令不消费的已列举配置键也可以存在。这两类键都必须在收尾依赖组合前
剔除，其右侧内容视为 opaque，不解析、不执行、不保存；只有精确列举的 dependency source 键可参与
PostgreSQL、Redis、Canonical 和恢复开关的变量展开，
退役键或收尾忽略键的值不得直接或间接进入这些依赖。任何未识别键仍 fail-closed，不能用前缀或通配规则扩大任何集合。
installed/loaded 启动参数必须指向相同受审 launcher；环境白名单拒绝 HOME 改址、shell startup、数据源与 libpq 覆盖。
loaded 变量仅从直接的 environment、inherited environment、default environment 块读取；
event triggers/descriptor 的 `=>` 不是环境赋值。重复块/键、畸形或嵌套环境块均拒绝。
API/Alert 可保留既有绝对、无父路径跳转的 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`，只核验路径形状，不读取配置或发送通知。
执行进程中的 PG* 覆盖亦拒绝。配置、launcher、五服务 plist 和 universe 的 inode/content/mtime/ctime 必须保持不变，
且全部源必须早于原运行。`project.env`、exact-tag launcher、universe 与目标根目录元数据还必须早于
最早当前消费者进程；分阶段安装可重写共享 launcher 副本与各服务 plist，但只有在共享 launcher
字节与 exact-tag 源完全一致，且 installed plist 的参数、工作目录和所有显式环境项均与 loaded job 一致时才合格。
连接 URL、Redis 连接参数、Canonical root 和 coverage 配置须匹配。
目标 `.env` 必须不存在（含悬空链接），目标根目录也纳入早于进程的元数据检查，防止事后删除第二配置来源掩盖覆盖。
这些检查及 fresh Live/Alert identity 在读取历史数据前和状态替换前重验；来源无法证明时停止，不回退到 `.env`。
先非阻塞获取该 Runtime 的既有 after-market OS guard，再取得 Catalog maintenance lease；在新的
repeatable-read/read-only 事务中，通过 Catalog inventory 和既有 Canonical reader 检查 operational 全部已提交指针，
包括预期窗口外的文件，并复用 audit 检查中断日 metadata、rank1 和目标窗口。只允许确认为有效子集的
`EXPECTED_PARTITION_MISSING` 留作待维护；额外端点、其他 finding、未知异常均阻断。待维护计数不证明缺失由这次中断造成。
原交易日不可变 Live snapshot 必须仍在且与 rank1 一致；缺失、过期或不一致均阻断，不使用当前日快照代替。

显式 `--apply` 在同一锁窗口重新校验身份与原状态字节，使用 pinned directory FD 原子替换并 fsync。
唯一写入是原盘后状态文件：收尾写 schema v4、`last_run.status=interrupted`、`error_code=AFTER_MARKET_INTERRUPTED`，
清除 `current_run`，保留原开始时间与最后成功日；旧 schema v2 未记录的 attempts 保持 null，v3 保留已记录次数。
不发送通知、不发布 canonical_updated、不清理 Live，不调用 provider 或写行情/DB/Redis；不自动重试。
替换前失败保留原状态；替换或其后 fsync 的结果不确定返回 `AFTER_MARKET_CLOSEOUT_OUTCOME_UNKNOWN`、
`status_written=null` 和锁内只读 readback 分类，不能假称未写入或直接重试。

reader 兼容 v1-v4；v4 与 v3 的进度字段相同，仅增加中断终态与未知 attempts 表达。
新自然运行可暂时保留 v4 的中断摘要，正常终态仍写 v3。Runtime health 保持 `degraded/interrupted`，
Web 显示收尾而非完成；promotion 仍独立检查 phase/snapshot，不把 interrupted 当作 after_market_complete。
旧 reader 不认识 v4 时应降级，不能当健康；本入口不授权部署。它确认当前已提交视图，不能还原旧 writer
每次 commit 的执行轨迹，不是 checkpoint，也不替代每日完成或每周历史审计。

### 每周 operational 全历史只读审计

`data.weekly-audit` 固定使用 `operational_products.txt` 的 `operational_full_history` scope，不借用可变的 active 研究范围。
它复用 `HistoricalDataManager.audit`、八表 Catalog/metadata、Canonical reader 与既有 maintenance lock：先原子写 running，再非阻塞取锁，
获锁后才打开 fresh read-only transaction。忙时记录 `skipped_busy`，不等待、抢占或重试；审计不调用 provider/
metadata writer/Redis，`provider_requests=0`、`data_writes=0`，只报告 finding，不修复、不通知。

`.run/weekly-audit-status.json` 是单份原子替换的最新审计状态，不是 checkpoint 或 active data selector。
它绑定 exact Runtime root/40 位 commit、operational 顺序、scope 和 `through`；运行超过 2h 映射 `stuck`，终态超过 8 天映射
`stale`，身份、计数、时序或只读计数不符合合同则映射 `invalid`，缺文件是 `not_run`。`passed` 必须有已审计 cutoff、全部品种完成且 finding 为零。
Runtime health 先独立计算现有服务 overall，再附加可选 `components.weekly_audit`摘要；旧状态缺字段不得推导历史健康，
历史 finding 也不改写当前数据新鲜度或 Runtime overall。

## 5. 唯一查询入口

```text
series_kind = continuous | actual_dominant | contract
symbol
contract       # 只有 contract 必填
frequency
start
end
```

Historical reader 只打开 Catalog 精确引用的 URI。对于 hash 文件名，必须校验实际 bytes SHA-256，
并从同一份 bytes 解析 Parquet，避免 hash 与 parse 间文件变化；不 glob、自选最新文件或回退固定路径。
旧 `part.parquet` 仅在 Catalog 明确引用时兼容读取，仍执行既有 strict validation。

`continuous` 读取 Canonical `SYMBOL.MAIN`（`1m` 由 RQData `{SYMBOL}88` 构建，`1d/1w` 由 rank1
真实合约的交易所日行情构建）；`contract` 读取指定真实合约；`actual_dominant` 由 rank1
映射拼接，`1w` 按完整 ISO 周最后交易日的 rank1 合约取整周真实合约 bar。映射、日历、分区或
coverage 缺失时 fail-closed。`actual_dominant` 按与 `(start, end]` 相交的历史 Session 选择映射日；
夜盘 bar 的身份始终是其 `trading_day`，而不是发生时刻所在的前一自然日。响应只返回请求、bars、
coverage 和 resolved contract segments。

响应中的 `resolved contract segments` 只描述该周期实际返回 Bar 的 owner 子集，不是全窗口
MainContractMap 的替代物。跨周期研究使用 `MarketDataService.actual_dominant_segments(symbol, since,
through)` 读取与窗口相交、按 MainContractMap 已知完整边界展开的全局 rank1 分段，再逐 Bar 验证响应
owner 与全局 owner 的 contract 一致。短主力段可能有 D1/60m Bar 而没有完整 W1 Bar，因此各周期 owner
子集无需相等；不得使用 D1、周期并集或任一观察结果反推全局主力分段。完整分段边界只用于 lineage、
segment identity 与换月状态隔离，不得根据未来 `end_trading_day` 提前产生信号。

按 `since/through` 交易日表达窗口的研究消费者使用
`ActualDominantTradingDayQuery` 或 `ContractTradingDayQuery`；`MarketDataService` 先要求目标自然日期区间内
每一天都有权威 TradingCalendar 行，再从其中的 `is_trading_day=True` 行解析首末 TradingSession，最后进入
同一 `SeriesQuery`。显式 `is_trading_day=False` 的周末或节假日是完整日历事实并正常跳过；首界、中间或尾界
任一 Calendar 行缺失均以 `TRADING_CALENDAR_MISSING` fail-closed，Session 缺失同样不得缩短窗口。

`ContractTradingDayQuery` 还必须由 Catalog 中同时存在的 `listed_date` 与 `expired_date` 证明物理合约有效期，
唯一 active 区间为 `[listed_date, expired_date)`。请求先收窄到该区间；任一 metadata 缺失返回
`CONTRACT_METADATA_MISSING`，active 区间非法或与请求不相交返回 `CONTRACT_ACTIVE_WINDOW_MISSING`。消费者
不得用自然日加减或固定夜盘时刻猜测查询边界，也不得因此要求窗口外下一交易日的 MainContractMap。

## 6. CLI 与外部操作

`au-calendar-correction` 是单键来源冲突的显式例外，不是通用 Calendar 编辑器，也不改变下面
`metadata-repair` 的 insert-only 语义。它只接受先前获准取得的 AU2304／2022-03-16 交易时段响应，
以代码冻结的源内容 SHA-256 和 CLI 显式文件 SHA-256 双重绑定；本地输入限当前用户普通文件、
64 KiB，不接受链接、重复 JSON 键或读取期间变化。复用既有 Session 规范化，绝不查询 provider。
唯一目标是 `trading_calendars(id=46796, exchange_code=SHFE, trade_date=2022-03-16)` 的
`has_night_session: false → true`。旧 Calendar 全字段必须匹配已核实的前像，AU2304 生命周期、
AU/SHFE 身份、活动状态和时区须有效，且该日期仍无 SHFE Session；不插入 Session 或其他元数据。

默认 dry-run 使用 fresh read-only 事务、60 秒预算、finally rollback，plan hash 绑定输入证据、
数据库身份及相关 Calendar/Contract/Instrument/Exchange 完整前像。`--apply` 还须精确 plan hash 和
新的单次真实写入意图；在新事务中以 5 秒 lock timeout 锁定上述五张 metadata 表、重新规划比对，
只修改这一字段，flush/核对后一次 commit。短事务会暂时阻塞这五表的其他 writer，不阻塞普通读取；
必须在执行计划中向 owner 明示共享 SHFE 历史 Calendar 消费者影响，不把它表述成 AU 私有数据。

提交前失败 rollback；进入 commit 后任意异常一律 `COMMIT_OUTCOME_UNKNOWN`，不重试或自动逆向
恢复。commit 返回后使用独立只读事务核对前像仅该字段改变；读回失败为
`COMMITTED_READBACK_UNVERIFIED`，不能报成功。已更正旧值使旧计划失效，不提供自动 NOOP 或撤销。
如需纠正错误执行，须另行只读核对并批准新的前向处置，不能把已证实错误的 false 自动写回。
该入口无 RQData、Canonical、MainContractMap、Runtime、Scope、通知写入；完成单键更正不意味着
其他历史日期、Session 或 Newow 历史行情已修复。

`metadata-repair` 是独立的 missing-key 三阶段入口：默认 plan 只读 Catalog；fetch 和 apply 分别要求
显式 phase、对应内容 hash 与单次外部执行意图。范围只来自最多 64 个明确的 active
`symbol/contract/through` 目标，Contract、Instrument、Exchange 和生命周期必须已有权威事实；
未知身份保持 `IDENTITY_UNKNOWN`。Calendar 上下文沿用上市月起点前一个自然月到 effective through 后
七天，按 exchange/date 去重；Session 只规划已被 Calendar 确认为交易日且整个日期无既有行的
product/date。任何已有 Session 日期都保留并单列 `existing_session_dates_preserved`，不把部分日
拼补或宣称其完整；冲突身份、非权威行和重叠 template 显式阻断。

plan hash 绑定 source targets、生命周期、相关既有事实、缺键、classification 来源和固定 provider 参数；
自然日期键数、Session 日期数、尚未知的 Session 行数与精确请求次数分开公开。未知 Calendar 只允许对
连续缺键组做 `get_trading_dates` 分类，不猜周末，也不在同次 fetch 自动增加 Session 请求。分类快照
只能经新的显式 plan 纳入新增 Session 日期并重算 hash。Calendar `has_night_session=true` 必须有当日
精确历史夜盘正证据；非交易日可为 false，单品种仅日盘不能证明交易所无夜盘，此时保留
`NIGHT_SESSION_EVIDENCE_REQUIRED`，整个 blocked snapshot 不可 apply。

上市前等 Calendar 上下文允许可选显式 `evidence_sources`（symbol/contract/date）：只给原缺键集合中
已分类为交易日的精确日期提供 Session 证据，必须独立通过 Catalog identity/lifecycle 校验并进入
request/hash；不自动搜寻合约，不从供证合约上市日再扩建 Calendar 范围，也不写供证 Session。
供证 `date` 不等于 target `through`：target 仍必须早于今天；原计划 through 后七天上下文中的
未来缺键可显式供证，但该键必须已分类为交易日、保持在原 exchange/date 范围内，且供证合约在
该日期满足 `[listed_date, expired_date)`。供证身份仍须为 active 品种及已有 RQData Catalog 合约。
完整交易所负证据可显式传入 `exchange_universes`：每项严格为 exchange/date/products/sources，
必须同时提供单份 `exchange_inventory_evidence`，严格包含 identity/response：identity 为
`{method: all_instruments_by_type, args: [], kwargs: {instrument_type: Future, market: cn}}`，response 为
该请求未经品种/交易所过滤的完整原始 futures inventory 行。原生 `_exchange_day_products` 按每个
exchange/date 重算 products，与声明集合及 source symbols 精确一致；任何 inventory 行身份或生命周期
异常（包括其他交易所）均阻断。每个物理 source 还须存在于该原文且当日有效，不能用 caller hash、
target 子集、active_products 或部分 Catalog 合约代替完整响应。原始 identity/response 只存一份，
进入 plan/hash/recheck/apply；最多 100000 行、16 MiB，不新增隐式 provider 查询。每键最多 64 个
active 品种，每品种恰好一个 symbol/contract/date 来源，最多 256 个键、4096 个唯一来源。
每个来源均须在相同交易所通过 Catalog identity/provider/lifecycle 校验，且键仅限原计划已分类为
交易日的 missing Calendar；允许来源属于另一 batch，但不得扩大 target cutoff 或 Session 写入范围。
集合、来源、基线与固定请求均进入 plan/hash/recheck/snapshot；沿用 `calendar_night_fact`：任一当日
精确来源夜盘为 true，仅完整集合全部精确来源覆盖且均为日盘才为 false，部分来源仍阻断；provider
缺行或错键直接拒绝。原有 `evidence_sources` 保持仅正证据语义，不把单品种日盘升级为负证据。
同 product/date 的多个物理来源必须一致。fetch 串行执行固定请求，每次响应立即校验，首次失败停止，
无 retry/fallback/补充调用。Session 复用中性 source-contract/day 纯转换与 start-exclusive 规范化，
不伪造或写入 MainContractMap。

apply 不构造 provider，在一个新事务锁定相关五张 metadata 表后重读计划，再只插入缺失 Calendar
和完整 Session 日期，一次 commit，失败 rollback；不覆盖、删除或合并已有行，不写 Contract、
Instrument、Exchange、MainContractMap、Dataset、Parquet、Redis 或 Runtime。重复旧 snapshot 遇到
已插入事实要求 replan，不能把相似行冒充同一 prior result 的 NOOP。commit 前失败可回滚；commit 后
保留新事实并只读 replan，不自动删除。命令与 fixture 验证入口见 `TESTING.md`。

Newow dependency audit 复用 `NewowProductReader`、共享 rank1 owner validator 和 MDS 的生命周期
endpoint authority：先枚举各 section 必需的 owner，再独立验证每个物理合约/周期的完整 prefix，
一个缺失合约不能阻止发现后续独立合约。chart/auxiliary 使用权威近期窗口，reference 使用独立统计
窗口，explanation 使用三周期输入；每个依赖保留 owner 区间及 strategy/frequency/section consumer provenance。
W1 合法零 Bar owner 标为 `NOT_APPLICABLE`，不得填 Bar 或计入 data-ready。

`newow-readiness` 只接受互斥的单 active symbol 或 active universe，必须固定带时区 `as_of`；串行工作量和
deadline 均有界。metadata 不足时返回 `UNKNOWN` 与 bounded metadata repair proposal，预计根数/请求数
为 null；预算耗尽明确 `incomplete`，保留未启动枚举/依赖/case，不能报告完整覆盖。未知异常仅公开固定内部
错误，原始非正价格单列 `SOURCE_EXCEPTION`，完整性错误单列 `INTEGRITY_ERROR`，两者不生成盲目下载目标。

仅已证明缺 replay/partition 的依赖进入精确去重的候选请求；纯 `ContractWarmupPlanner` 与
`HistoricalDataManager` 共用同一规划规则、频率 scope、计数、日周 companion 与 hash。metadata 不足或
规划未完成不得提供有效 hash/计数。该候选不执行 apply，不能调用会替换更大 Session/Map 集合的
`MetadataSynchronizer` 来补 Calendar。审计只组合 MDS/Catalog/Canonical reader/coverage/planner，
不构造 provider、Redis、metadata writer 或维护 apply pipeline；DB 使用 fresh read-only transaction、
no-autoflush、statement timeout 和 finally rollback。
审计必须检查整个 planner scope（含 W1 的 D1、60m 的 1m），任一 source/integrity finding 都使候选成为
`REVIEW_REQUIRED`，不提供 plan hash 或总下载请求数；不能借缺 W1/60m 重新纳入已排除的损坏/非正源输入。
SQLite 的 connection-level `query_only` 必须在 rollback 归还连接池前恢复原值；恢复或回读失败即丢弃该连接。

matrix 模式保留 active 60 × 三策略 × 三周期的 540 main cases，同时独立运行实际 section service，
保留 `EVIDENCE_REQUIRED`、`NOT_APPLICABLE`、`WARMING` 等业务状态。`complete=true/status=audited`
仅表示本次限定审计已完成，不表示全部数据 ready、原站 parity、Release 或 Runtime acceptance；
main ready count 只计算实际主图 READY，不把其他 section 的证据状态算作数据成功。真实只读连接亦须位于
用户授权范围，fixture 验证与命令存在不构成真实连接或数据修复授权。用法与定向测试见 `TESTING.md`。

```bash
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data refresh --symbol X --since DATE --through DATE [--apply]
guiyi data contract-warmup --symbol X --contract CONTRACT --through DATE [--frequency {1d,1w,15m,60m}] [--expected-plan-sha256 HASH] [--apply]
guiyi data audit (--symbol X | --universe {active,operational}) [--through DATE] [--progress]
guiyi data session-anchor-repair --phase plan
guiyi data session-anchor-repair --phase prepare --shadow-root PATH --manifest PATH --apply
guiyi data session-anchor-repair --phase publish --shadow-root PATH --manifest PATH --apply
```

无 `--apply` 的 update/refresh/contract-warmup 仅计划，零 RQData、零 PostgreSQL 写入、零 Parquet 写入；audit
始终只读。audit 对每个请求品种独立返回结构化 finding（`code`、`category`、dataset、year、month）：已知
Session、Calendar 与产品窗口元数据缺口分别归为 `metadata_session`、`metadata_calendar`、
`metadata_window`，但不会中断其余品种；主力映射、预期分区缺失与物理一致性问题分别归为
`main_contract_map`、`partition`、`physical`。未知基础设施异常仍 fail-closed。已退役品种
`br/cs/ic/if/ih/im/lu/nr/sp` 已完成一次性生产清退；系统只保留精确拒绝防护，不再公开重复删除入口。
`--progress` 是 audit 专用 opt-in：最终 stdout JSON 与未传该参数时完全兼容；stderr 每品种输出
started/completed 两条 compact NDJSON 进度记录，固定字段为 `schema_version=1`、
`event=data.audit.progress`、`state`、`completed`、`total`、`symbol`、`finding_count`，started 的
`finding_count=null`。该观察不接 provider，audit 的 `provider_requests=0`；若 stderr 首次 write/short
write/flush 失败，立即禁用后续进度输出，审计异常和最终 stdout 结果均保持原语义。
省略 `--through`
时，update 在规划开始解析最新完整交易日，并将该值作为本轮固定水位；相同解析值的再次完整运行
必须为 NOOP。真实 `--apply`、生产 schema migration 与正式数据删除/重建仍各自需要范围明确的
单次意图。

`contract-warmup --apply` 还必须提供 dry-run 输出的全小写 SHA-256 plan hash；锁内重算的 identity、
lifecycle、Calendar/Session 或 target 漂移都会在第一次 provider 请求和写入前阻断。dry-run 或测试不构成
真实 apply 授权，真实执行后如需重试亦须新的单次意图。

`session-anchor-repair` 是 0044→0045 的一次性 forward-only seam。`plan` 只读扫描全部日内
Dataset/partition、预计缺失首分钟与稳定 scope hash，不调用 RQData。`prepare --apply` 需要独立真实数据授权，
只把完整 Canonical 复制到外部 shadow root，再用 RQData 真实缺失 1m 重建 `1m/5m/15m/30m/60m`；不得合成，
且 D1/W1 hash 必须不变。manifest 必须位于 active/shadow root 之外。`publish --apply` 需要新的维护授权，
只在五项 Runtime 均停止且 revision、Catalog、active/shadow 文件 hash 与 scope 全部未漂移时切换 root、更新
coverage/row_count、执行精确 0045，再清理 publish 执行时由 operational phase authority 唯一解析的当前交易日旧锚点 Redis Live Bar。该 repair cleanup 只删除
`live:bars:<trading-day>:*`，必须保留同日不可变 rank1 subscription snapshot；它不清理其他交易日，且不得把
snapshot 改写为 Canonical 或合成的事实。0045 成功后失败只能保持维护状态继续 forward recovery，不能恢复错误
session。修复继续使用唯一 Canonical V2，不创建并行 data-version。该 legacy repair 的原合同保持不变，
固定 `part.parquet` 写入仅隔离在 shadow prepare，不得作为普通 update/refresh 的发布路径。

自然 after-market 是与 repair 分离的严格边界：Canonical 更新后必须用既有 immutable subscription snapshot 对
formal rank1 做 strict reconciliation。snapshot 缺失、格式错误、不完整或 identity 不匹配均失败关闭，不能以 repair、
重新查询、合成 snapshot 或其他回退替代；只有 reconciliation 完成后，才一次原子 full cleanup 删除该交易日全部
Live Bars 与 subscription snapshot。repair-only cleanup 不改变这条自然 after-market 语义。

### Market Runtime promotion preflight

`run-local-service.sh market-runtime-preflight` 是只读、bounded-JSON 的 promotion preflight。它只读取既有
operational universe、Calendar/Session phase authority、当前交易日 immutable Live subscription snapshot 与公开
after-market status；不连接 RQData，不写 Catalog、Redis 或状态文件。

跨 checkout promotion 时，after-market status 的 authority 来自当前 supervised 的、已加载 after-market
launchd root，并与已安装 plist 声明的 root 交叉校验；candidate checkout 不能自行取得 status authority。只有
launchd domain 可读、after-market label 明确为 not-found、且不存在 installed plist 的 first-install 条件下，才可
使用 candidate root。domain/permission/label 命令错误、root 缺失、畸形或彼此不一致一律为
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。preflight 的受控 status path 不受 runtime env 覆盖。

只有以下四种窗口可通过：有效 snapshot 与 operational symbols/contract identities 精确对应的
`snapshot_ready`；所有 operational 产品尚未到权威 Session 的真正最早 start 的 `before_first_session`；同一
trading day 的 after-market 已完成且 products 精确保持 operational 顺序的 `after_market_complete`；以及没有
当前 trading day、没有 active Session 的 clean `non_trading_interval`。任何 post-start 缺失 snapshot、无效或
部分 snapshot、UNKNOWN/分歧 phase、缺失或歧义 Session authority、running/corrupt/unreadable after-market
status，或不可能的 status chronology 都必须阻断；其稳定公开原因仅为
`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED`、`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID` 或
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。

这个 preflight 没有 override、repair、synthetic snapshot、retry、replay 或 fallback；它不把预检通过表述为
release、Runtime ready、formal rank1 reconciliation 或生产验证。

active universe 为 `data/universe/active_products.txt` 的 60 品种；退役精确名单为
`data/universe/retired_products.txt`，与 active 互斥。

## 批量 Session 读取的可信边界

读取成本优化只改变 SQL 批次，不改变行情事实：Calendar 完整性、精确 provider/active Session、
合约生命周期、夜盘前一交易日、重叠校验与完整预期端点必须保留。批量读取的 Session 事实仅在
请求内使用；缓存命中不能跳过 Catalog、物理分区和输入依赖验证，也不能裁剪同合约 warm-up。
