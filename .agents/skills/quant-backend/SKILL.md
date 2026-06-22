---
name: quant-backend
description: 当任务涉及 FastAPI、PostgreSQL、SQLAlchemy、Alembic、Redis、RQ、后端接口、WebSocket、任务队列时使用。
---

# 归一量化后端开发 Skill

## 技术栈

- Python 3.12
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

1. 数据中心
2. 合约管理
3. 品种池
4. 数据下载任务
5. 数据质量检查
6. 策略中心
7. 回测任务
8. 回测报告
9. 信号扫描
10. 复盘记录

## 规则

1. 不接实盘自动下单。
2. API 结构要清晰。
3. 任务耗时操作必须进入 RQ。
4. 数据下载、回测、扫描不能阻塞 Web 请求。
5. 修改后必须提供启动命令和测试命令。
