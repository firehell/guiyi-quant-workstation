# Canonical 数据基础

更新时间：2026-08-09

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

`continuous/MAIN` 的 Direct RQData 来源固定为 `{SYMBOL}88` 未平滑主力连续；`{SYMBOL}99` 持仓量
加权指数不是可替代来源，任何空窗都必须显式失败。它与按 rule2 `MainContractMap` 拼接的
`actual_dominant` 保持不同查询语义。

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
优先完成 `1d/1w`，再补可本地生成的 Derived，最后按 active universe、Dataset、年月顺序续传 `1m`。
每完成一个 1m dataset-month，立即生成四个 Derived 月。

既有月等于 expected bars 时跳过；合法子集只下载缺失 bars 并重写完整月；不可读、extra bar 或
identity 冲突时重建相交整月。明确的 RQData 额度异常映射为 `PROVIDER_QUOTA_EXHAUSTED`：本轮
立即停止 provider 调用，保留已发布月，不发布当前未完成月，并返回 `status=partial` 与
`stop_reason=provider_quota_exhausted`。下一次完全相同命令从首个缺失目标续传。

`refresh --symbol --since --through --apply` 强制重建窗口相交月中的 continuous 与所涉 rank1
contract 的 Direct，再由 1m 重建 Derived。它不接受 repair plan，也不产生额外进度或证据文件。

## 5. 唯一查询入口

```text
series_kind = continuous | actual_dominant | contract
symbol
contract       # 只有 contract 必填
frequency
start
end
```

`continuous` 读取 Canonical `SYMBOL.MAIN`（仅由 RQData `{SYMBOL}88` 构建）；`contract` 读取指定真实合约；`actual_dominant` 由 rank1
映射拼接，`1w` 按完整 ISO 周最后交易日的 rank1 合约取整周真实合约 bar。映射、日历、分区或
coverage 缺失时 fail-closed；响应只返回请求、bars、coverage 和 resolved contract segments。

## 6. CLI 与外部操作

```bash
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data refresh --symbol X --since DATE --through DATE [--apply]
guiyi data audit --universe active
guiyi data retire-products [--apply]
```

无 `--apply` 的 update/refresh 仅计划，零 RQData、零 PostgreSQL 写入、零 Parquet 写入；audit
始终只读。`retire-products` 默认 dry-run 盘点已退役品种（`br/cs/ic/if/ih/im/lu/nr/sp`）的 Catalog 行与
Canonical 路径；显式 `--apply` 才硬删，且生产环境另需范围明确的单次执行意图。省略 `--through`
时，update 在规划开始解析最新完整交易日，并将该值作为本轮固定水位；相同解析值的再次完整运行
必须为 NOOP。真实 `--apply`、生产 schema migration 与正式数据删除/重建仍各自需要范围明确的
单次意图。

active universe 为 `data/universe/active_products.txt` 的 60 品种；退役精确名单为
`data/universe/retired_products.txt`，与 active 互斥。
