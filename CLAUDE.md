# CLAUDE.md — 兼容入口

> 主规则：`AGENTS.md`。开发流程：`docs/DEVELOPMENT.md`。当前状态：`STATUS.md`。

接手最小阅读：

1. `STATUS.md`
2. `AGENTS.md`
3. `docs/DEVELOPMENT.md`
4. `PROJECT_SOURCE.md`
5. 任务相关：`docs/ARCHITECTURE.md` / `docs/DATA_CENTER.md` / `docs/BACKTEST_ENGINE.md` / `docs/SIGNAL_EVENTS.md`

工作站模式：`WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY`。工程入口：`scripts/engineering/*`。

当前 V1 路线（摘要）：RQData → Parquet/DuckDB/PostgreSQL → FastAPI / vn.py / Vue；V1 不做实盘与无人值守交易。

接手后先总结理解和计划，不要直接改代码。禁止写入凭据；禁止修改 `.env`；禁止破坏真实数据目录；禁止大范围无关重写。
