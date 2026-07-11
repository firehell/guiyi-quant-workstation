# 当前任务：WEB-MAIN-INDICATORS-V1

生成时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`

分支：`main`（从 `codex/data-target-coverage-audit-main` 合并）

状态：`DELIVERY_READY`

## 目标

在 Web K 线主图增加主图指标多选叠加，支持 `EMA10`、`EMA21`、`EMA60`、`火天大有` 任意组合；默认只启用 `EMA21`；`MACD` 继续固定在副图。

- C0：对齐任务源，记录当前 Market K 线数据流和风险边界。
- C1：实现主图指标展示框架，支持 EMA10 / EMA21 / EMA60 多选、图例/hover/current value、版本化 localStorage 偏好和火天大有 disabled 占位。
- C2：新增只读 `GET /api/v1/market/indicators`，后端复用 `quant-core` 统一 EMA 内核，前端消费统一指标结果并实现 visible bars + warm-up bars 规则。

- [x] 主图指标选择 UI：`主图指标 (n)`、立即切换、清空、恢复默认。
- [x] 用户选择写入浏览器本地，刷新页面后保留。
- [x] `KlineChart.vue` 从单条硬编码 `emaSeries` 改为动态主图指标 series map。
- [x] `EMA10 / EMA21 / EMA60` 复用既有 `calculateEMA(bars, period)`。
- [x] 火天大有前端观察层：`ZK1 / ZD1 / ZD2`、色带、K 线观察染色、三连观察提示。
- [x] 火天大有显示 `观察专用 · 会重绘`，不接入正式 marker 点击逻辑。
- [x] hover-strip 和 Market 十字线快照展示当前启用主图指标值。

## Data-audit 合并状态

- 已从 `codex/data-target-coverage-audit` cherry-pick 目标提交 `fd881bac` 到主工程承接分支。
- 已带入独立只读目标覆盖矩阵审计器：
  - `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
  - `scripts/rqdata_target_coverage_audit.py`
  - `services/quant-api/tests/test_target_coverage_audit.py`
- 已带入目标覆盖矩阵任务单和报告目录：
  - `docs/tasks/TASK-2026-07-11-002-data-target-coverage-audit.md`
  - `data/reports/target_coverage_audit_20260711/`
- 后续数据审计、DB/API/parquet 覆盖矩阵工作只在主工程 `/Volumes/扩展盘/guiyi-quant-workstation` 继续，不再在 `/Volumes/扩展盘/guiyi-parallel/data-audit` 增量执行。

- 本轮允许修改 `packages/quant-core`、`services/quant-api`、`apps/quant-web` 和任务文档。
- 不修改 PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- 不修改策略、回测、信号、风控、企业微信或任何交易执行逻辑。
- 主图 EMA10 / EMA21 / EMA60 使用后端统一指标结果；Web 不再把本地 `calculateEMA()` 作为正式主图 EMA 来源。
- Live 模式不接 C2 统一 EMA，显示“Live 指标待 C3”语义。
- 火天大有只做 disabled / observation-only 占位，不计算、不提醒、不进回测。

- Web 指标任务不修改 FastAPI、PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- Data-audit 合并不写 DB、不写 Parquet、不调用 RQData 下载、不读取 `.env` 或凭据。
- 不修改策略信号、回测、成交、成本、风控计算。
- 不执行信号扫描、回测、复盘写入、企业微信发送或任何交易动作。
- 火天大有基于 XMA，存在未来函数和重绘风险，只能作为 Web 人工观察指标，不得进入正式信号、live evaluator、回测报告或企业微信。

- [x] 对齐 `tasks/current.md` 到当前任务。
- [x] 更新任务单为 C0+C1 入口。
- [x] 新增主图指标 registry 与 localStorage 偏好工具。
- [x] 将 `KlineChart.vue` 从固定 EMA21 series 改为主图指标 series map。
- [x] 在 Market K 线页增加“主图指标”多选控件和“趋势均线”快捷入口。
- [x] 补充前端单元测试。
- [x] 运行 Node tests。
- [x] 运行 Vite build。
- [x] 运行 `git diff --check`。
- [x] 浏览器 smoke：`/market/chart?symbol=jm&contract=JM2609&period=15m`。
- [x] C2：引入 `quant-core` EMA 指标内核与 registry。
- [x] C2：新增只读 Market indicators API 与 warm-up 裁剪服务。
- [x] C2：前端切换为后端指标 series，KlineChart 仅渲染 `ready && valid` 点。
- [x] C2：补充指标内核、Market indicators API、前端 mainIndicators 测试。

## 验证记录

Web 指标任务验收：

```bash
npm --prefix apps/quant-web run test:indicators
npm --prefix apps/quant-web run build
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

- `test:indicators`：8 passed。
- Web 全量 Node tests：31 passed。
- XMA 风险测试：4 passed。
- Vite production build：passed；仍有既有约 651 kB chunk warning。
- Browser smoke：`/market/chart?symbol=jm&contract=JM2609&period=15m` 默认 EMA21 + MACD；EMA10 切换、火天大有观察标签、清空、恢复默认、刷新持久化均通过；console 仅 API info，无 error/warn。

Data-audit 主工程复跑命令：

```bash
uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py --products-file data/universe/full_products_90.txt --output-dir data/reports/target_coverage_audit_20260711
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
git diff --check
```

Data-audit 主工程复跑结果：

- CLI 完成，`db_snapshot_source=database`。
- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：2091 rows。
- `test_target_coverage_audit.py`：5 passed。
- `test_full_universe_active_gate.py`：8 passed。

## 风险记录

1. 火天大有视觉复刻仍需用户主观验收；如要与通达信截图逐像素校准，应另开视觉校准任务。
2. 火天大有不得升级为正式信号；若未来需要策略化，必须另开 strictly backward-looking 改写和安全审查。
3. 目标覆盖矩阵已在主工程以 `database` 口径复跑；后续需分别处理 `source_interval_unverified`、`missing_db_registration`、`quality_failed` 和元数据缺口。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`
- `docs/tasks/TASK-2026-07-11-002-data-target-coverage-audit.md`
- `docs/DATA_CENTER.md`
- `docs/gpt/CURRENT_STATE.md`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/tests/indicators.test.ts`
- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
- `data/reports/target_coverage_audit_20260711/coverage_summary.md`
- `data/reports/target_coverage_audit_20260711/target_coverage_matrix.csv`
- `data/reports/target_coverage_audit_20260711/issue_register.csv`
