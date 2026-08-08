# GY-DATA-CORE-V2：Canonical Data Foundation active 合同

更新时间：2026-08-09

## 目标

以 RQData → staging → 六项校验 → 月度 Canonical Parquet → 八表 Catalog →
`MarketDataService` 完成个人期货研究工作站的数据底座。active universe 是
`data/universe/active_products.txt` 的 69 品种，active 历史从 `2023-01-01` 开始。

## 冻结合同

- 物理 Dataset 是 `continuous|contract` 和四字段 `DatasetKey`；`actual_dominant` 只在查询时拼接。
  `continuous`、`contract` 与 `actual_dominant` 是不同查询模式，不可互换。
- Direct 是 `1m/1d/1w`，Derived 是 `5m/15m/30m/60m`，Derived 只从同 Dataset Canonical 1m 聚合。
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

当前代码与 DFD-01 target 仍有差异；只有已完成并经验证的 DFD 才能写入 `STATUS.md`。日调度、live、
通知与自动订单不在本 change 授权内，`auto_order=false`。
