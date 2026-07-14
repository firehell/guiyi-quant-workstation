# Architecture

更新时间：2026-07-14

事实来源：`docs/ARCHITECTURE.md`

当前状态：current，运行和部署仍有外部 Gate。

## 主链路

```text
RQData 1m
-> raw parquet
-> standard 1m parquet + quality Gate
-> local aggregation
-> manifest / checksum / PostgreSQL metadata
-> DuckDB read_parquet
-> vn.py CTA / FastAPI
-> PostgreSQL report / trade / order / signal / review facts
-> Vue Web
```

## live 分层

```text
RQData live 1m
-> live_minute_bars
-> confirmed 5m/15m/30m/60m/1d/1w
-> preview
-> optional formal live_confirmed event
-> optional notification queue
```

live 表不自动登记为 historical active，不进入可信回测。

## 模块

- `apps/quant-web`：Vue 3 + Vite + TypeScript + Naive UI。
- `services/quant-api`：FastAPI、SQLAlchemy、Alembic、RQ、DuckDB。
- `packages/quant-core`：指标和 vn.py 策略草稿。
- `scripts`：数据、审计、开发和运维入口。
- `workstation` / `tasks`：工作站协作协议。

## Gate 边界

代码和模板存在不等于真实运行通过。当前 `T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY` 均未达成。

