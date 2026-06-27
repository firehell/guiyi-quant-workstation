# PROJECT_PROGRESS.md — 当前项目进度

> 用途：给新的 Codex 线程、Cursor 人工检查和外部审查快速确认当前真实进度。  
> 当前阶段：V1 真实回测闭环打通阶段。  
> 边界：V1 不做实盘、不自动下单、不接 CTP / TqSdk 交易接口。

---

## 1. 当前阶段

```text
V1 真实回测闭环打通阶段
```

当前要打通的最小链路：

```text
标准 Parquet 样本数据
→ MarketDataReader / LocalParquetProvider
→ vn.py BacktestingEngine 真实执行
→ 苏冰 EMA21 策略
→ result_converter
→ PostgreSQL reports / trades / equity_curve / drawdown_curve
→ FastAPI 查询
→ Vue Web 报告
→ K线真实买卖点 marker
```

---

## 2. 已完成或已有骨架

- V1 技术路线已确定：RQData + Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Vue Web。
- Web / API / 信号 / 复盘 / 回测报告页面已有骨架。
- `data_role` 隔离已存在，正式研究默认 `primary`。
- validation / legacy_reference 数据需要显式研究用途标记，不能混入正式回测。
- `vnpy_integration` adapter、strategy loader、symbol mapper、result converter 已存在。
- 苏冰 EMA21 vn.py 策略草稿已存在。
- 回测任务 API、RQ worker 函数和 Web 回测页面已存在。
- `docs/PROJECT_SNAPSHOT.md` 是一次项目现状快照，本次任务不修改该文件。

---

## 3. 未完成或待验证

- 真实 vn.py `BacktestingEngine` 尚未执行。
- 当前 `VnpyBacktestRunner.run()` 仍是 `prepared/executed=false` 的准备态返回。
- 标准 Parquet 样本数据到真实 vn.py 回测的最小链路尚未打通。
- vn.py raw result 到 `backtest_reports` / `backtest_trades` / `equity_curve` / `drawdown_curve` 的正式持久化尚未闭环。
- FastAPI 查询真实 vn.py 报告与交易明细尚未完成端到端验证。
- Vue Web 展示真实报告和真实 K线买卖点 marker 尚未完成端到端验证。

---

## 4. 当前风险

- 本地 DB migration 未对齐，已观察到 `backtest_tasks.engine_type` 缺列风险。
- Python 版本口径已统一为 Python 3.13；后续新环境按 3.13 准备。
- 真实 RQData 下载、主力映射、夜盘周期合成、交易参数仍需样本验证。
- 回测严谨性必须继续审查：未来函数、数据泄露、成交时点、手续费、滑点、合约乘数、保证金、最大回撤、连续亏损。
- 回测结果只代表研究验证，不等于实盘结果。

---

## 4.1 Python 版本口径

最终选择：

```text
Python 3.13
```

依据：

- `services/quant-api/pyproject.toml` 使用 `requires-python = ">=3.13"`。
- `services/quant-api/uv.lock` 使用 `requires-python = ">=3.13"`。
- 当前 `uv run --project services/quant-api python --version` 使用 Python 3.13.9。
- `vnpy`、`rqdatac`、`pandas`、`pyarrow`、`duckdb`、`fastapi` 在当前 Python 3.13 环境下可导入。

---

## 5. 下一步任务顺序

1. 更新任务状态和路线图。
2. 只读检查 Alembic 当前 head 与本地 DB 状态，形成 migration 对齐方案，不直接迁移。
3. 准备标准 Parquet 样本数据 fixture，确保不触碰真实 `data/`。
4. 接真实 vn.py `BacktestingEngine` 执行，替换 `prepared/executed=false` 的占位返回。
5. 打通 normalized result 到 `backtest_reports`、`backtest_trades`、`equity_curve`、`drawdown_curve` 的持久化。
6. 用 FastAPI 查询真实报告与交易明细。
7. 用 Vue Web 展示真实报告、资金曲线、回撤曲线。
8. K线显示真实 backtest trades 买卖点 marker。
9. 做回测严谨性审查。

---

## 6. 禁止事项

- 不接实盘。
- 不接 CTP / TqSdk 交易接口。
- 不自动下单。
- 不新增新策略。
- 不做参数优化。
- 不做多品种批量回测。
- 不做 AI 策略生成。
- 不继续扩 Web 大屏。
- 不修改 vn.py 源码。
- 不把账号、密码、API Key、交易密码写入仓库。

---

## 7. 建议检查命令

```bash
git diff -- docs/ROADMAP.md docs/V1_REFACTOR_VNPY_RQDATA.md tasks/current.md docs/PROJECT_PROGRESS.md
```

```bash
rg -n "V1 真实回测闭环打通阶段|prepared/executed=false|BacktestingEngine|DB migration|自动下单|实盘" docs tasks
```

完整回归建议在后续实现任务前后运行：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```
