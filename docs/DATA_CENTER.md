# Canonical 数据基础

更新时间：2026-09-04

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
交易日事实即失败；不得用 `get_price` 的期货日/周 `close` 或 `settlement` 互相替代。

## 2. Canonical 物理合同

```text
canonical/
  kind={continuous|contract}/
  symbol={product}/
  series={MAIN|actual-contract-code}/
  frequency={1m|5m|15m|30m|60m|1d|1w}/
  year=YYYY/
  month=MM/
  part.parquet
```

行字段为 `bar_end`、`trading_day`、`open`、`high`、`low`、`close`、`volume`、`turnover` 和
`open_interest`。价格和金额用 Decimal，`bar_end` 是 UTC timestamp，identity 不在行内重复。

发布前必须完成 schema、主键单调唯一、OHLCV、交易日/session/frequency、coverage 和物理可读性
校验。发布成功的月通过 Catalog 的 `coverage_start`、`coverage_end`、`row_count` 与可读
`file_uri` 表示；没有旁路的内容摘要、发布清单或缺口状态。

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

`effective_start(symbol)=max(product_window_start(symbol), active_history_floor)`，其中
`active_history_floor=2023-01-01`。`update` 使用显式 `--through` 固定水位，先同步 metadata，后
优先完成基础 provider 日线 `1d` 与由其聚合的 `1w`，再按 active universe、Dataset、年月顺序续传基础
provider 分钟线 `1m`。每完成一个 1m dataset-month，立即生成四个日内派生月。

18:05 Runtime 先以只依赖 Calendar 的 `latest_metadata_day(operational 60)` 判断当天是否为交易日，
再由持 maintenance lock 的 `HistoricalDataManager.update` 同步 metadata 后规划 coverage；不得先用可能
尚未同步的当天 TradingSession 判定 `NON_TRADING_DAY`。受限 metadata 同步准备 operational 60 品种：
Calendar 覆盖当天至 ISO 周日或下一交易日（取较晚者），TradingSession 精确替换当天与下一交易日，
MainContractMap 仍只发布当天 rank1。
下一交易日 Session 尚未由 provider 发布时精确返回 `NEXT_TRADING_SESSION_NOT_READY`，最多一小时后再
尝试一次；格式、重复或身份异常仍 fail-closed。这样夜盘 phase resolver 在夜盘前取得下一交易日 Session
事实，同时不会提前发布未来主力映射，也不写 Dataset、Partition 或 Parquet。

既有月等于 expected bars 时跳过；合法子集只下载缺失 bars 并重写完整月；不可读、extra bar 或
identity 冲突时重建相交整月。明确的 RQData 额度异常映射为 `PROVIDER_QUOTA_EXHAUSTED`：本轮
立即停止 provider 调用，保留已发布月，不发布当前未完成月，并返回 `status=partial` 与
`stop_reason=provider_quota_exhausted`。下一次完全相同命令从首个缺失目标续传。

缺失完整 ISO 周的 `1w` 时，同一 maintenance 批次会把该周对应的 `1d` 作为 refresh context；
RQData adapter 先读取完整周日行情，并在调用内按 `(contract, trading_day)` 复用同一 source
snapshot 生成 1d/1w。发布前先验证整组完整性，再按涉及的 1d 月分区、1w 月分区顺序原子替换；
跨月周会刷新两侧日线月分区。`continuous` 日线仍按每日 rank1 拼接；最终 owner 合约用于
`actual_dominant 1w` 整周聚合时，非 rank1 日只作为该周内部 source context，不进入
`actual_dominant 1d` 的可读结果。dry-run 会显式列出由缺失周线带动的日线 refresh 窗口。

`refresh --symbol --since --through --apply` 强制重建窗口相交月中的 continuous 与所涉 rank1
contract 的基础 provider `1m/1d` 和日线派生 `1w`，再由 1m 重建四个日内派生周期。它不接受 repair plan，
也不产生额外进度或证据文件。

`contract-warmup` 只维护一个已验证 identity 的 physical contract：窗口从 `listed_date` 到不晚于最近完整
交易日的 `through`，获取该 contract 的 `1m/1d` 基础事实；`1w` 只由同一交易所完整日行情聚合，四个日内
派生周期只由同 contract `1m` 生成。dry-run 只读输出稳定 plan hash；apply 必须在 maintenance lock 内重算并
匹配该 hash，且不会写 continuous、其它 contract、MainContractMap、Redis Live、Rule、Scope、Event 或 notification。
分区失败可明确部分成功，不能自动重试。

### 盘后 Runtime 状态合同

`.run/after-market-status.json` 写 schema v2；读取兼容旧 schema v1。schema v2 在受监督自然盘后运行开始、任何
coverage/RQData/update 尝试之前写入
`current_run={scheduled_date,started_at,products}`，只在 run 完成终态写入时清除。每次写入都在同目录创建
临时文件后 `os.replace`；中途崩溃保留 `current_run`，不冒充已完成。`last_run.failure_notification`
只允许 `{attempted_at,state=provider_accepted|failed,error_type}` 公开字段，不保存 provider reference。

只读 Runtime health 从 `operational_products.txt` 对应的 `Instrument.exchange_code` 与权威
`TradingCalendar` 唯一解析 expected trading day：上海时间 18:20 前只考虑先前交易日，18:20
起当日可成为 expected day；交易所结果不唯一、产品/日历事实不完整或 chronology 无效时均
fail-closed。从未产生过状态时，只有当日为交易日且上海时间已到 18:20、当日已 due 才是
`degraded/missed`；周末/节假日和首次应执行时点前仍是 `pending`。已有状态时，最后成功日落后于
expected day 才是 `degraded/missed`。`current_run` age 不超过 2h 为 `pending/running`，超过 2h 为
`degraded/stuck`。

盘后失败通知是与 Alert Rule/Application Domain 分离的运维能力。公共手工 `guiyi data after-market`
不启用该能力；只有受监督自然执行的主业务失败才向 owner 发起最多一次 PushPlus 请求。
通知使用固定脱敏内容，含 trading day、公开 error code、attempts 与“系统运维提醒，非交易指令”；
不用 Topic、`AlertEvent`、DB、retry、replay 或 fallback。provider accepted 不等于送达；通知失败只记录
`failure_notification=failed`，不改写或重试主 after-market 结果。`missed/stuck` 只是 health，不会发送。

## 5. 唯一查询入口

```text
series_kind = continuous | actual_dominant | contract
symbol
contract       # 只有 contract 必填
frequency
start
end
```

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

```bash
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data refresh --symbol X --since DATE --through DATE [--apply]
guiyi data contract-warmup --symbol X --contract CONTRACT --through DATE [--expected-plan-sha256 HASH] [--apply]
guiyi data audit (--symbol X | --universe active) [--through DATE] [--progress]
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
session。修复继续使用唯一 Canonical V2，不创建并行 data-version。

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
