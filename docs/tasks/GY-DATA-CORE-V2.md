# GY-DATA-CORE-V2：Canonical Data Foundation active 合同

更新时间：2026-08-09

## 目标

以 RQData → staging → 六项校验 → 月度 Canonical Parquet → 八表 Catalog →
`MarketDataService` 完成个人期货研究工作站的数据底座。active universe 是
`data/universe/active_products.txt` 的 60 品种，active 历史从 `2023-01-01` 开始。

## 冻结合同

- 物理 Dataset 是 `continuous|contract` 和四字段 `DatasetKey`；`actual_dominant` 只在查询时拼接。
  `continuous`、`contract` 与 `actual_dominant` 是不同查询模式，不可互换。
- `1m` 是 RQData `get_price` 输入；`1d` 是 RQData 交易所日行情事实，`continuous/MAIN` 按当日 rank1
  真实合约拼接；`1w` 只由同一日线完整 ISO 周聚合；`5m/15m/30m/60m` 只从同 Dataset Canonical 1m 聚合。
- 每 Dataset 每月只有一个 `part.parquet`。完整 coverage、row count、Catalog identity 与文件可读性
  共同定义可用月；不存在额外发布/缺口/参数数据语言。
- 月分区先完成候选文件校验，再以同文件系统临时文件原子替换；任何失败保留最后一个有效
  `part.parquet`。
- PostgreSQL active 数据表固定为八张，不保存 Bar 或运行历史。
- `MetadataSynchronizer` 维护交易所、合约、Calendar、Session 和 rank1 map；
  `HistoricalDataManager` 承担 update、refresh、audit；`MarketDataService` 是唯一读入口。
- `update` 的 Catalog + Parquet 是唯一续传水位。`--through` 省略时解析为本轮最新完整交易日；相同
  fixed through 完整重跑必须零目标、零写入、零 provider 请求；明确的 provider 额度耗尽停止当前轮
  并由下次命令自然续传。

## 公开 CLI

```text
guiyi data update (--symbol X | --universe active) [--since DATE] [--through DATE] [--apply]
guiyi data refresh --symbol X --since DATE --through DATE [--apply]
guiyi data audit --universe active
```

无 `--apply` 的 update/refresh 只计划，零 RQData、零写入；audit 只读。

## 实施顺序

1. DFD-01 已重置文档和 OpenSpec 合同。
2. DFD-02 删除退出的维护面、legacy 和生成工件。
3. DFD-03 收口 Parquet storage、Catalog、ORM 和候选 `20260808_0036`。
4. DFD-04 收口 MarketDataService、Market API 和 Market Web。
5. DFD-05 实现最终 update/refresh/audit 与 quota natural resume。
6. DFD-06 运行全量验证并清除 active 死引用。
7. DFD-07 仅在获得单次外部执行意图后，确认生产 revision、执行正式数据清理/migration，并从
   RQData 重建。

DFD-01～DFD-06 的仓库收口已完成并写入 `STATUS.md`；DFD-07 的生产重建与完整品种验收仍在进行。
日调度、live、通知与自动订单不在本 change 授权内，`auto_order=false`。
当前实现与事实以 `STATUS.md`、`docs/DATA_CENTER.md` 和 `app/market_data/` 为准。

## DFD-07 四交易所 Canary 验收清单

本清单只固定下一轮受控重建的目标与验收顺序；它不是 `--apply`、RQData、生产 PostgreSQL 或
Canonical 写入授权。每个 canary 必须独立完成并验收后，才可请求下一个品种的单次执行意图。
固定水位为 `T0=2026-08-07`，品种按下表顺序执行：

| 顺序 | 交易所 | 品种 | 元数据同步范围 | 正式数据目标 |
| --- | --- | --- | --- | --- |
| 1 | CZCE | `ap` | 从 `effective_start(ap)` 至 T0 的 Instrument/Contract、交易日历、历史 Session facts 与 rank1 MainContractMap | `continuous/ap/MAIN`，及 rank1 映射到的真实合约 |
| 2 | SHFE | `ag` | 从 `effective_start(ag)` 至 T0 的 Instrument/Contract、交易日历、历史 Session facts 与 rank1 MainContractMap | `continuous/ag/MAIN`，及 rank1 映射到的真实合约 |
| 3 | INE | `ec` | 从 `effective_start(ec)` 至 T0 的 Instrument/Contract、交易日历、历史 Session facts 与 rank1 MainContractMap | `continuous/ec/MAIN`，及 rank1 映射到的真实合约 |
| 4 | GFEX | `lc` | 从 `effective_start(lc)` 至 T0 的 Instrument/Contract、交易日历、历史 Session facts 与 rank1 MainContractMap | `continuous/lc/MAIN`，及 rank1 映射到的真实合约 |

其中 `effective_start(symbol)=max(product_window_start(symbol), 2023-01-01)`。Calendar 是交易所事实，
Session 是品种的历史有效窗口；两者都必须覆盖该 canary 自己的完整历史窗口。合约元数据和
`MainContractMap rank=1` 只允许来自 RQData 同步事实，真实合约集合以写后映射为准，不预先猜测合约代码。

每个 canary 的完成标准完全相同：

1. `MetadataSynchronizer` 已为该品种在 `[effective_start, T0]` 同步 Instrument/Contract、Calendar、
   historical Session facts 和连续 rank1 map；任何缺口都停止，不用当前交易时段或自然日补写历史事实。
2. `HistoricalDataManager` 已发布 `continuous/MAIN` 与每个 rank1 映射真实合约的七个正式周期：`1m` 取
   `get_price`，`1d` 取交易所日行情，`1w` 只由完整日线事实聚合，以及只从质量通过 Canonical `1m`
   聚合的 `5m/15m/30m/60m`。不得创建
   `actual_dominant` 的物理 Dataset 或 Parquet。
3. 写后运行 `guiyi data audit --symbol <symbol>`；必须 `status=passed`、`finding_count=0`、
   `provider_requests=0`。若为 partial、failed 或出现任何 Session/Calendar/MainContractMap/partition/
   physical finding，则停止该 canary，不进入下一个品种。
4. 以相同 T0 运行无 `--apply` 的 `guiyi data update --symbol <symbol> --through 2026-08-07`；必须为
   `status=noop`、零 target、零 provider request、零写入。这是 fixed-T0 收敛检查，不授权重建。
5. 通过 `MarketDataService` 做只读回检：对七个周期分别验证 `continuous`；再使用写后
   `MainContractMap rank=1` 选择实际存在的早期、近期及跨换月区间，验证 `contract` 与
   `actual_dominant`。每个读窗必须完全位于 `[effective_start, T0]`、已有 coverage 内，且
   `actual_dominant` 的 resolved segments 与 rank1 映射一致。缺失映射、分区、coverage 或物理文件必须
   fail-closed，不得缩短窗口或改查其他序列冒充通过。

执行前只读 preflight 必须再次核对 production revision、Canonical 根、active=60、J/JM 的 1,364 个
分区和该 canary 当前零分区状态；执行后复核相同基线。任何意外变化均停止并报告，不做自动 repair、
Runtime、live、通知或订单操作。
