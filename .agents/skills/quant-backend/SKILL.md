---
name: quant-backend
description: 当任务涉及归一量化 FastAPI、PostgreSQL、SQLAlchemy、Alembic、Redis、RQ、后端接口、WebSocket、任务队列时使用。
---

# 归一量化后端开发 Skill

## 技术栈

- Python 3.13（当前仓库）/ Python 3.12+（项目兼容口径）
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- PostgreSQL
- Redis + RQ
- DuckDB
- Parquet
- pytest
- ruff
- mypy

## 模块

V1 优先：数据中心、合约管理、品种池、数据下载任务、数据质量检查、策略中心、回测任务、回测报告、信号扫描、复盘记录。

## 分层

- `api/`：路由和依赖注入。
- `schemas/`：Pydantic 请求/响应。
- `models/`：SQLAlchemy 模型。
- `services/`：业务逻辑。
- `repositories/`：数据库读写。
- `tasks/`：RQ 后台任务。
- `websocket/`：任务进度和信号推送。

## 规则

- 不接实盘自动下单。
- 路由函数不要堆业务逻辑。
- 数据下载、回测、扫描必须进入 RQ，HTTP 返回 task id。
- 所有写操作有日志和可读错误。
- PostgreSQL 存元数据，Parquet 存行情，DuckDB 读研究数据。
- 修改后必须给出启动命令和测试命令。

## 验证

- `uv run ruff check .`
- `uv run pytest -q`
- `uv run python -m alembic upgrade head`
- API smoke test：`/health` 返回 `ok`。
