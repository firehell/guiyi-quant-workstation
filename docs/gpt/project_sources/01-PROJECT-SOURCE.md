# Project Source

更新时间：2026-07-14

事实来源：`PROJECT_SOURCE.md`

当前状态：current，仍有外部 Gate。

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。当前重点是 V1 / V1-B 的可信研究闭环：数据更新、质量检查、标准化存储、K 线查看、策略/信号、回测、报告、复盘、人工观察和前向验证。

## 边界

- 不是 SaaS。
- 不做无人值守自动交易。
- 不接实盘账户自动下单。
- 不把企业微信提醒写成买卖指令。
- 不把回测或信号结果写成实盘准入。

## 主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 数据入口：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究默认 `quality_status=passed`。

