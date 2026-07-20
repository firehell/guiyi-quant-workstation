# Codex 任务模板

> 复制本模板，填写 `【】` 占位符后发给 Codex。
> 执行前请先读 `AGENTS.md`、`STATUS.md`、`docs/DEVELOPMENT.md` 和与本任务相关的 `docs/` 文档。

---

## 任务名称

【填写任务名称】

## 当前背景

这是归一量化项目，本地运行的国内期货量化研究与交易辅助系统。

当前阶段优先做：

- 数据中心
- K 线工作台
- 策略中心
- 回测任务
- 回测报告
- 信号扫描
- 复盘中心

第一版不做：

- 全自动实盘
- tick 高频回测
- 复杂多账户
- 多用户权限
- 云端 SaaS
- 手机 App

## 固定技术路线

**前端**

Vue 3 + Vite + TypeScript + Naive UI + Pinia + Vue Router + Lightweight Charts + ECharts

**后端**

FastAPI + SQLAlchemy 2 + Alembic + Pydantic + Redis/RQ + PostgreSQL + Parquet + DuckDB

**量化规则**

- 必须避免未来函数、数据泄露、过拟合
- 回测必须考虑手续费、滑点、合约乘数、保证金、最大回撤、连续亏损

## 本次任务

【填写具体任务】

## 推荐执行模式

勾选一项：

- [ ] Plan 模式（先计划，确认后再改代码）
- [ ] 直接执行
- [ ] 只审查，不修改文件

补充说明：【如有特殊要求可填写】

## 允许修改

【填写允许修改的文件或目录，建议逐条列出】

示例：

```text
packages/quant-core/guiyi_quant/strategies/su_bing_ema21/
services/quant-api/app/backtest/
```

## 禁止修改

- `.env`
- 账号、密码、API Key、License
- `data/raw/`
- `data/parquet/`
- 真实交易配置
- 与本任务无关的大范围文件

## 执行要求

1. 先阅读 `AGENTS.md` 和相关 `docs/`。
2. 修改前先说明计划。
3. 不要扩大任务范围。
4. 不要做自动实盘逻辑。
5. 修改后说明：
   - 改了哪些文件
   - 为什么这么改
   - 怎么运行
   - 怎么测试
6. 如涉及回测，必须说明如何避免未来函数和数据泄露。

## 验收标准

1. 【验收标准 1】
2. 【验收标准 2】
3. 【验收标准 3】

## 测试命令

```bash
# 【填写与本任务相关的最小测试命令】
# 示例：
# uv run --project services/quant-api pytest tests/test_xxx.py -q
# uv run --project services/quant-api ruff check services/quant-api/app/xxx
```

## 相关文档

- `AGENTS.md`
- `STATUS.md`
- `docs/DEVELOPMENT.md`
- 【本任务相关文档，如 `docs/BACKTEST_ENGINE.md`】
