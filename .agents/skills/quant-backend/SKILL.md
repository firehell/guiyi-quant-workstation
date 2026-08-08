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
- Redis + RQ（signal worker 入口已退役）
- DuckDB
- Parquet
- pytest / ruff / mypy

## Current mounted modules

- Market Canonical 读（bars/coverage/dominants/indicators）
- data 治理 API + `guiyi data *`
- runtime 只读状态 + `guiyi runtime status`
- 盘后 scheduler（默认关闭）

已卸 / 退役：signals、strategies、dashboard、reviews、watchlists、futures_research HTTP；backtest API/worker；`guiyi data live`；poll Live。

## 分层

- `api/`：路由和依赖注入。
- `schemas/`：Pydantic 请求/响应。
- `models/`：SQLAlchemy 模型。
- `services/`：业务逻辑。
- `data_core/`：Catalog / Canonical / MarketDataService。
- `repositories/`：数据库读写。

## 规则

- 不接实盘自动下单。
- 路由函数不要堆业务逻辑。
- DataGap / failed quality fail-closed；dominants coverage 与 Catalog 同口径。
- 禁止在日志与错误中暴露密钥、路径、SQL、stack。
- 产品面以 `STATUS.md` / `services/quant-api/README.md` 为准。
