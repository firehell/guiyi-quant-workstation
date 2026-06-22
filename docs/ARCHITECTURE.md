# 归一量化系统架构

## 技术栈

前端：
- Vue 3
- Vite
- TypeScript
- Naive UI
- Lightweight Charts
- ECharts

后端：
- FastAPI
- SQLAlchemy 2
- Alembic
- Pydantic
- Redis + RQ

数据：
- 天勤专业版 / TqSdk
- PostgreSQL
- Parquet
- DuckDB

## 数据流

天勤数据下载
→ 原始数据保存
→ 清洗为标准 K线
→ Parquet 存储
→ DuckDB 查询
→ 回测引擎读取
→ 生成报告
→ PostgreSQL 保存元数据和报告
→ Web 展示