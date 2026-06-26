# Current Task — Codex 接手与任务交接文档统一

## 1. 当前任务

统一 Codex 接手、账号切换和任务交接文档，确保新的 Codex 账号只依赖仓库文件也能理解项目上下文、V1 路线、禁止边界和下一步执行方式。

---

## 2. 当前 V1 路线

- 主数据源：米筐 RQData。
- 回测底座：vn.py / VeighNa CTA BacktestingEngine。
- 数据仓：PostgreSQL + Parquet + DuckDB。
- 后端：FastAPI + SQLAlchemy 2 + Alembic + Redis/RQ。
- 前端：Vue 3 + Vite + TypeScript + Naive UI。
- 图表：TradingView Lightweight Charts + ECharts。
- V1 不做实盘，不做无人值守自动交易。

---

## 3. 本任务允许修改

- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`
- `docs/AGENT_WORKFLOW.md`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`

---

## 4. 本任务禁止修改

- `.env`
- `data/`
- `apps/quant-web/`
- `services/quant-api/`
- `packages/quant-core/`
- `strategies/`
- 任何真实账号密码相关文件

---

## 5. 验收标准

- 新 Codex 账号能通过 `README.md` 找到接手入口。
- `docs/CODEX_HANDOFF.md` 明确项目定位、V1 路线、必读文件、账号切换流程和禁止事项。
- `docs/AGENT_WORKFLOW.md` 明确 Agent 协作边界和任务完成输出格式。
- `AGENTS.md` 明确 Codex 每次任务完成后必须写修改文件、运行命令、测试命令、风险点和下一步。
- `CLAUDE.md` 如存在，只作为兼容入口，不另起一套项目规则。

---

## 6. 当前风险点

- `.env.example` 仍可能有旧数据源口径，后续需要单独任务处理。
- 路线图和代码实际进度可能不完全同步，后续应做状态对齐。
- 任何涉及回测、策略、信号的任务都必须单独做未来函数、数据泄露、成交错位和成本项审查。

---

## 7. 下一步建议

完成本文档任务后，建议下一步单独处理：

1. `.env.example` 数据源口径统一为 RQData V1 主链路。
2. `docs/ROADMAP.md` 与当前已存在代码模块做状态对齐。
3. 对 `data_sources`、`vnpy_integration`、苏冰 EMA21 vn.py 策略草稿进行只读审查，再决定下一步小任务。
