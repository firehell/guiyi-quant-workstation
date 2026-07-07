# ROADMAP.md

生成时间：2026-07-07

## 1. V1 当前目标

归一量化 V1 目标是形成本地可信研究闭环：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py / FastAPI
-> Vue Web
-> 回测报告 / 信号提醒 / 复盘 / 人工观察
```

V1 不做：

- 自动下单。
- 无人值守实盘。
- SaaS。
- 多用户权限。
- 手机 App。
- tick 高频。

## 2. 当前阶段：Stage 3 前置

Stage 2C / 2D / 2E 已完成，JM v2 六周期数据已具备进入 Stage 3 的条件。

当前最小目标：

1. 补强 active 数据过滤测试。
2. 在 Web Data 页面 smoke 最新 JM v2 覆盖和质量状态。

## 3. V1 数据路线

```text
RQData
-> raw parquet
-> standard parquet
-> manifest / checksum / quality report
-> PostgreSQL market_data_files / data_quality_reports
-> DuckDB read_parquet
-> Market / Backtest / Signal / Review
```

active 入口：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

## 4. 阶段计划

| order | stage | target |
|---:|---|---|
| 1 | Data converge | active 数据过滤测试和 Data 页面 smoke |
| 2 | Realtime design | RQData 实时 1m 入库最小骨架 |
| 3 | Aggregation | 1m 聚合多周期 |
| 4 | Strategy evaluator | 策略版本和 live_evaluator 收敛 |
| 5 | Signal events | 信号事件化 |
| 6 | Data-chain gate | 真实合约、trigger price、盘后归档和 Stage 9 前置 Gate |
| 7 | Notification | 企业微信只读提醒 |
| 8 | Market UI | Web Market 策略展示增强 |
| 9 | Runtime | 本地长期运行、worker、scheduler、health check |
| 10 | Remote access | Cloudflare Access 验收 |
| 11 | Trusted backtest | 可信回测主线复核 |

## 5. 已具备资产

- FastAPI / Vue Web MVP。
- RQData ingest、JM v2 parquet、manifest、quality report、DB 登记。
- DuckDB + standard parquet 读取。
- vn.py CTA 回测适配、报告入库、交易明细。
- Market K 线、指标、marker。
- JM V1-B 信号扫描。
- 复盘 note。
- WebSocket 进度和信号通道。

## 6. 当前风险

- 企业微信前必须先通过 Stage 8.5 数据主链路 Gate。
- 当前 `signal_events` 仍缺少真实主力合约、trigger price 和 confirmed bar 边界的显式字段。
- Dashboard、策略管理、Settings 仍有占位性质。
- Cloudflare Access 只是文档准备项，仍需部署验收。
- 可信回测主线需要在新 JM v2 数据基础上复核。
