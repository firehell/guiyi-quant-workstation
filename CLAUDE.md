# CLAUDE.md — 兼容入口

> 本项目的主规则文件是 `AGENTS.md`。本文件只作为 Claude / 其他 Agent 进入仓库时的兼容入口，不另起一套项目规则。

接手前必须先读：

1. `AGENTS.md`
2. `docs/CODEX_HANDOFF.md`
3. `tasks/current.md`
4. `docs/AGENT_WORKFLOW.md`
5. `docs/ROADMAP.md`
6. `docs/V1_REFACTOR_VNPY_RQDATA.md`
7. `docs/ARCHITECTURE.md`
8. `docs/DATA_CENTER.md`
9. `docs/BACKTEST_ENGINE.md`

当前 V1 路线：

- 米筐 RQData 是 V1 主数据源。
- vn.py / VeighNa CTA BacktestingEngine 是 V1 回测底座。
- 数据仓是 PostgreSQL + Parquet + DuckDB。
- 后端是 FastAPI，前端是 Vue 3 + Vite + TypeScript + Naive UI。
- V1 不做实盘，不做无人值守自动交易，不让信号直接下单。
- 当前阶段是 V1-B：焦煤 JM 3 年真实数据短持有策略闭环。
- V1-B 目标是 JM 最近 3 年真实数据、日线定方向、15m / 5m 独立入场、持有 5-8 根本周期 K线、止损退出、回测报告入库、Web 复盘和信号扫描提醒。
- 旧的 V1-A 焦煤 1 年样板只作为历史参考，不再作为当前目标。

接手后先总结理解和计划，不要直接改代码。

禁止写入账号、密码、token、license、API Key、CTP 密码、米筐账号、天勤账号；禁止修改 `.env`；禁止触碰真实数据目录；禁止大范围重写项目。
