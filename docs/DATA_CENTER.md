# Canonical 数据基础

更新时间：2026-08-12

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
guiyi data audit (--symbol X | --universe active) [--through DATE] [--progress]
```

无 `--apply` 的 update/refresh 仅计划，零 RQData、零 PostgreSQL 写入、零 Parquet 写入；audit
始终只读。audit 对每个请求品种独立返回结构化 finding（`code`、`category`、dataset、year、month）：已知
Session、Calendar 与产品窗口元数据缺口分别归为 `metadata_session`、`metadata_calendar`、
`metadata_window`，但不会中断其余品种；主力映射、预期分区缺失与物理一致性问题分别归为
`main_contract_map`、`partition`、`physical`。未知基础设施异常仍 fail-closed。已退役品种
`br/cs/ic/if/ih/im/lu/nr/sp` 已完成一次性生产清退；系统只保留精确拒绝防护，不再公开重复删除入口。
`--progress` 是 audit 专用 opt-in：最终 stdout JSON 与未传该参数时完全兼容；stderr 每品种输出
started/completed 两条 compact NDJSON 进度记录。该观察不接 provider，audit 的 provider requests 仍为零；
若 stderr 自身不可写，后续进度静默而审计和最终 stdout 保持正常业务结果。
省略 `--through`
时，update 在规划开始解析最新完整交易日，并将该值作为本轮固定水位；相同解析值的再次完整运行
必须为 NOOP。真实 `--apply`、生产 schema migration 与正式数据删除/重建仍各自需要范围明确的
单次意图。

active universe 为 `data/universe/active_products.txt` 的 60 品种；退役精确名单为
`data/universe/retired_products.txt`，与 active 互斥。
