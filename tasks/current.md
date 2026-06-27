# Current Task — V1 真实回测闭环打通阶段

## 1. 当前阶段

当前阶段名称：

```text
V1 真实回测闭环打通阶段
```

阶段目标是把已有骨架推进为一条可验证的真实回测链路：

```text
标准 Parquet 样本数据
→ MarketDataReader / LocalParquetProvider 读取
→ vn.py BacktestingEngine 真实执行
→ 苏冰 EMA21 策略真实跑回测
→ result_converter 转归一量化标准结果
→ 写入 PostgreSQL reports / trades / equity_curve / drawdown_curve
→ FastAPI 查询
→ Vue Web 展示真实报告
→ K线显示真实买卖点 marker
```

本阶段不扩大产品范围，只打通 V1 单策略、单品种、单周期的真实研究闭环。

---

## 2. 当前真实状态

已具备：

- V1 路线已确定为 RQData + Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Vue Web。
- Web / API / 信号 / 复盘 / 回测报告页面已有骨架。
- `data_role` 隔离已存在，默认正式研究读取 `primary`，`validation` / `legacy_reference` 需要显式研究标记。
- `vnpy_integration` adapter、strategy loader、symbol mapper、result converter 已存在。
- 苏冰 EMA21 vn.py 策略草稿已存在。
- 回测任务 API、RQ worker 函数和 Web 回测页面已存在。

尚未打通：

- 真实 vn.py `BacktestingEngine` 尚未执行。
- 当前 `VnpyBacktestRunner.run()` 仍是 `prepared/executed=false` 的准备态返回。
- vn.py raw result 到 `backtest_reports` / `backtest_trades` / `equity_curve` / `drawdown_curve` 的正式持久化尚未闭环。
- 本地 DB migration 未对齐，已观察到 `backtest_tasks.engine_type` 缺列风险。
- Python 版本口径已统一为 Python 3.13；后续新环境按 3.13 准备。

---

## 3. 本阶段不做

本阶段禁止：

- 不新增新策略。
- 不做参数优化。
- 不做多品种批量回测。
- 不做 AI 策略生成。
- 不接天勤实盘。
- 不接 CTP。
- 不做自动下单。
- 不继续扩 Web 大屏。
- 不修改 vn.py 源码。
- 不把信号直接变成实盘委托。

---

## 4. 当前任务：更新任务状态和路线图

本次任务只更新文档和任务状态，避免后续 Codex 被旧 `tasks/current.md` 误导。

允许修改：

- `tasks/current.md`
- `docs/ROADMAP.md`
- `docs/PROJECT_PROGRESS.md`
- `docs/V1_REFACTOR_VNPY_RQDATA.md`

禁止修改：

- Python / Vue / TypeScript 业务代码。
- `pyproject.toml`、`uv.lock`、`package.json`、`pnpm-lock.yaml`。
- Alembic migration。
- `.env`。
- `data/`。
- 实盘、CTP、TqSdk 交易相关代码。
- 自动下单逻辑。

---

## 5. 下一阶段任务顺序

1. 更新任务状态和路线图，也就是本次文档任务。
2. 只读检查 Alembic 当前 head 与本地 DB 状态，形成 migration 对齐方案，不直接迁移。
3. 准备标准 Parquet 样本数据 fixture，确保不触碰真实 `data/`。
4. 接真实 vn.py `BacktestingEngine` 执行，替换 `prepared/executed=false` 的占位返回。
5. 打通 normalized result 到 `backtest_reports`、`backtest_trades`、`equity_curve`、`drawdown_curve` 的持久化。
6. 用 FastAPI 查询真实报告与交易明细。
7. 用 Vue Web 展示真实报告、资金曲线、回撤曲线和真实 K线买卖点 marker。
8. 做回测严谨性审查：未来函数、成交时点、手续费、滑点、合约乘数、保证金、最大回撤、连续亏损。

---

## 6. 验收标准

- [ ] 当前阶段写成“V1 真实回测闭环打通阶段”。
- [ ] 已完成内容和未完成内容区分清楚。
- [ ] 下一阶段顺序明确。
- [ ] 明确真实 vn.py 执行尚未打通。
- [ ] 明确 DB migration 未对齐。
- [ ] 明确 V1 不做实盘、不自动下单。
- [ ] 本次不修改业务代码、不修改依赖文件、不运行数据库迁移。

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
