# Canonical 数据基础

更新时间：2026-08-08

## 1. 唯一 active 数据语言

```text
DatasetKey
MarketDataset
MarketPartition
Manifest
DataGap
MainContractMap
ContractSpec
MarketDataService
```

一个物理 Dataset 由四字段唯一确定：

```text
(kind, symbol, series_or_contract, frequency)
```

- `kind`: `continuous | contract`
- `series_or_contract`: 主连固定为 `MAIN`，真实合约为其 RQData 合约代码
- `frequency`: `1m | 5m | 15m | 30m | 60m | 1d | 1w`

provider、schema version 和 source digest 属于 Manifest，不是 Dataset 身份。

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
  manifest.json
```

Parquet 行只保存：

```text
bar_end, trading_day, open, high, low, close,
volume, turnover, open_interest
```

OHLCV 和金额使用 Decimal；`bar_end` 是带时区的 UTC timestamp。Dataset 身份不在每行重复。

每个自然月只保留一个当前分区。Manifest 保存 DatasetKey、schema version、source kind、
coverage、row count、Parquet checksum 和 source digest；聚合分区另存 source 1m digest 与 session digest。

## 3. PostgreSQL 最小目录

active 数据表只有：

```text
exchanges
instruments
contracts
trading_calendars
trading_sessions
main_contract_map
contract_specs
market_datasets
market_partitions
data_gaps
```

- `main_contract_map`: active 69、rank=1、`volume_open_interest`，`symbol + trade_date` 唯一。
- `contract_specs`: 每个被映射真实合约每交易日一行。
- `market_datasets`: 四字段 DatasetKey 唯一。
- `market_partitions`: `dataset_id + year + month` 唯一，存 coverage、URI、row count、checksum 和 manifest digest。
- `data_gaps`: 只存当前未解决缺口；repair 复验成功后删除。

Alembic `20260808_0036` 是不可逆的候选迁移，删除计划中的旧数据表。它尚未应用到
生产数据库；执行需要新的、精确表范围的一次性意图。

## 4. 增量与修复语义

```text
metadata current facts
-> latest complete trading day
-> continuous direct
-> rank1 contract direct
-> derived frequencies
-> strict read verification
```

- `--since` 只限定检查下界，不授权覆盖已正确分区。
- `--through` 是固定水位；缺省只选最新已完成交易日。
- 空 Dataset 从 `data/universe/product_window_starts.csv` 起算。
- 品种期望交易日是实际交易所开市日与该品种真实合约上市期的交集；无上市合约的交易所开市日不是数据缺口。
- MainContractMap 显式使用 RQData `rule=2`；continuous 可早于首个 rank1 事实，actual_dominant 在首个映射前保持 fail-closed。
- 已有 Dataset 计算月度全窗口精确缺口，不只追加尾部。
- 相同 fixed through 重跑必须零目标、零写入、零 RQData。
- 真实合约只保存 `MainContractMap rank=1` 的有效窗口。
- Derived 只读 Canonical 1m；source 1m 失败则对应 Derived blocked。

## 5. 六项发布硬校验

1. Canonical schema、Decimal 与 timestamp 正确。
2. `bar_end` 严格单调且主键唯一。
3. OHLCV 关系合法。
4. trading day、session 和周期边界正确。
5. 请求窗口覆盖完整。
6. row count、checksum、Manifest 与原子发布一致。

校验失败不覆盖最后有效分区，并建立当前 DataGap。

## 6. 唯一查询入口

```text
series_kind = continuous | actual_dominant | contract
symbol
contract       # 只有 contract 必填
frequency
start
end
```

- `continuous`: 读取 `SYMBOL.MAIN` 物理 Dataset。
- `contract`: 读取指定真实合约 Dataset。
- `actual_dominant`: 按 `MainContractMap` 查询时拼接；`1w` 使用完整 ISO 周最后交易日的 rank1 合约。

返回 request identity、bars、coverage、partition digests、resolved contract segments 和 main-map digest。
映射、Dataset、日历或分区缺失，以及 DataGap 相交时 fail-closed。

## 7. CLI 与 bootstrap 边界

```bash
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data bootstrap --universe active [--through DATE] [--apply]
guiyi data repair --plan exact-plan.json [--apply]
guiyi data audit --universe active
```

`bootstrap` 的临时白名单读取器只用于 Gate A 候选根。日常组装不注入该读取器；最终收口后
bootstrap 只保留 RQData 全量重建能力。旧 raw/processed 本次不删除，也不被 active Catalog
、MarketDataService 或日常更新引用。

## 8. 当前迁移状态

代码、schema 和本地 fixture 验证属于候选实现。下列外部 Gate 尚未执行：

- Gate A：69 品种候选 Canonical 构建。
- Gate B：不可逆生产 schema/drop 与 Canonical 原子切换。
- Gate C：69 品种、七周期、DataGap=0 和 fixed-through NOOP 最终验收。

日调度、live、通知和自动订单保持关闭。
