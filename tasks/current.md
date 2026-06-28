# Current Task — V1-B 验收收尾阶段

## 1. 当前阶段

当前阶段名称：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环 — 验收收尾
```

阶段目标：在工程闭环已跑通的基础上，完成报告口径加固、浏览器级验收和外部审查，不扩大产品范围。

已跑通链路：

```text
焦煤 JM 最近 3 年真实 RQData / local standard parquet（1d / 15m / 5m）
→ MarketDataReader / LocalParquetProvider 读取
→ vn.py BacktestingEngine 真实执行（prepared_only=false）
→ jm_v1b_daily_direction_fast_entry 策略
→ result_converter 转归一量化标准结果
→ PostgreSQL reports / trades / equity_curve / drawdown_curve
→ FastAPI 查询
→ Vue Web 展示真实报告
→ K线显示真实买卖点 marker
→ 单笔交易复盘 note
→ 信号扫描提醒（不自动下单）
```

阶段详情与正式报告 ID 见：

- [`docs/PROJECT_PROGRESS.md`](../docs/PROJECT_PROGRESS.md)
- [`docs/V1B_JM_3Y_FAST_ENTRY.md`](../docs/V1B_JM_3Y_FAST_ENTRY.md)
- [`docs/PROJECT_INVENTORY.md`](../docs/PROJECT_INVENTORY.md)

---

## 2. 当前真实状态

已具备：

- V1 路线已确定为 RQData + Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Vue Web。
- `data_role` 隔离已存在；JM V1-B 1d/15m/5m 已注册为 `primary` / `passed` 数据资产。
- vn.py adapter、strategy loader、symbol mapper、result converter 已存在并已在 RQ Worker 路径真实执行。
- `VnpyBacktestRunner.run()` 在 `prepared_only=false` 时返回 `executed=true`；`prepared_only=true` 仅用于配置校验。
- JM V1-B 15m / 5m 正式回测报告已入库（`report_id=3`、`report_id=4`）。
- 回测报告、交易明细、资金曲线、回撤曲线、K 线 marker、复盘 note、信号扫描 Web/API 已打通。
- pytest 127 passed；前端 build 通过。

尚未完成（验收收尾项）：

- 浏览器截图级 UI smoke 验收。
- 报告口径：`annual_return`、`total_commission` / `total_slippage` 当前为 0.0，需审查或统一说明。
- `max_drawdown` 金额/百分比口径需在 Web 侧明确，避免误读。
- 信号扫描尚未验证真实触发信号时的提醒展示（当前多为 `no_signal`）。
- 新环境需确认 Alembic head 与本地 DB 已对齐后再跑正式任务。

---

## 3. 本阶段不做

- 不新增新策略。
- 不做参数优化、网格搜索、多品种批量扩展。
- 不做 AI 策略生成。
- 不接天勤实盘、不接 CTP、不做自动下单。
- 不继续扩 Web 大屏。
- 不修改 vn.py 源码。
- 不把信号直接变成实盘委托。

---

## 4. 下一阶段任务顺序

1. 浏览器级 Web smoke：回测报告、K 线 marker、复盘、信号扫描页面。
2. 修正或明确年化收益、手续费、滑点、最大回撤百分比的报告口径。
3. 固化 JM V1-B 定期信号扫描任务（只提醒、不自动下单）。
4. 做 V1-B 外部审查：未来函数、成交时点、成本、保证金、回撤和连亏。
5. 决定下一阶段是 V1-B.1 报告口径加固，还是 V1-C 单品种样本外验证。

---

## 5. 验收标准

- [x] vn.py BacktestingEngine 已在 RQ Worker 路径真实执行。
- [x] JM V1-B 15m / 5m 正式报告已入库并在 Web 可查看。
- [x] 回测 → 报告 → K 线 marker → 复盘 → 信号扫描链路已打通。
- [ ] 浏览器级 UI smoke 完成。
- [ ] 报告指标口径（年化、成本、回撤百分比）已修正或文档化。
- [ ] V1-B 外部审查完成。
- [ ] V1 不做实盘、不自动下单（持续遵守）。

---

## 6. 建议检查命令

```bash
rg -n "V1-B|report_id|executed|prepared_only|自动下单|自动实盘" docs tasks
```

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```
