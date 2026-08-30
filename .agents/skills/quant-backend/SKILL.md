---
name: quant-backend
description: Use when 任务涉及归一量化 FastAPI、Pydantic、PostgreSQL 应用域、Redis、Alert、Runtime、后端接口或 guiyi CLI。
---

# 归一量化后端

用于 FastAPI、Pydantic、PostgreSQL 应用域、Redis、Alert、Runtime、后端接口或 `guiyi` CLI 任务。

先读 `AGENTS.md`、`PROJECT_SOURCE.md`、`docs/ARCHITECTURE.md`、`STATUS.md` 及相关 deep canonical。
数据、Catalog 或 Alembic 任务改用 `futures-data`；前端和浏览器任务改用 `quant-frontend`。

实现入口为 `services/quant-api/app/`；验证命令以 `TESTING.md` 为准，先运行定向 pytest，再按风险扩展
Ruff、Mypy 与非 isolated PostgreSQL 测试。
