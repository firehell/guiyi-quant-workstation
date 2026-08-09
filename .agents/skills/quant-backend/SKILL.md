---
name: quant-backend
description: 当任务涉及归一量化 FastAPI、PostgreSQL、SQLAlchemy、Alembic、Redis、RQ、后端接口、任务队列时使用。
---

# 归一量化后端开发 Skill

## 技术栈

- Python 3.13（当前仓库）/ Python 3.12+（项目兼容口径）
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL
- Redis（runtime 探测；signal/notification worker 已退役）
- Canonical Parquet + MarketDataService
- pytest / ruff / mypy

## Current mounted modules

- Market Canonical 读：`/api/v1/market/bars|coverage|dominants`
- `guiyi data update|refresh|audit`
- runtime 只读状态：`/api/runtime/health` + `guiyi runtime status`
- 轻量 liveness：`/health`、`/api/health`、`/healthz`（同一 payload）

已卸 / 退役：signals、strategies、dashboard、reviews、watchlists、futures_research、data_center HTTP；backtest API/worker；`guiyi data live`；poll Live；RQ signal/notification worker 启动面。

## 分层

- `api/`：路由和依赖注入（当前仅 market + runtime）。
- `schemas/`：Pydantic 请求/响应。
- `models/market_tables.py`：八表 ORM。
- `market_data/`：Catalog / Storage / MarketDataService / maintenance。
- `guiyi_cli/`：统一 CLI。
- `services/runtime_health.py`：只读 runtime 探测（含退役组件 stub）。

## 规则

- 不接实盘自动下单；`auto_order=false`。
- 路由函数不要堆业务逻辑；Market 读路径经 `MarketDataService`。
- Catalog / coverage / 物理完整性异常 fail-closed。
- 禁止在日志与错误中暴露密钥、路径、SQL、stack。
- 产品面以 `STATUS.md`、`docs/DATA_CENTER.md`、`services/quant-api/README.md` 为准。
