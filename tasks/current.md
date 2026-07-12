# 当前任务：TASK-2026-07-11-003-web-overlay-indicators

生成时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`

分支：`codex/web-overlay-indicators`

代码基线：`main @ f29de0dd（含 WEB-VISUAL-REFACTOR）`

状态：`C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW`

## 目标

将 Web C 线从 C0+C1 主图指标展示框架推进到 C2：

- C0：对齐任务源，记录当前 Market K 线数据流和风险边界。
- C1：实现主图指标展示框架，支持 EMA10 / EMA21 / EMA60 多选、图例/hover/current value、版本化 localStorage 偏好和火天大有 disabled 占位。
- C2：新增只读 `GET /api/v1/market/indicators`，后端复用 `quant-core` 统一 EMA 内核，前端消费统一指标结果并实现 visible bars + warm-up bars 规则。

## 当前边界

- 本轮允许修改 `packages/quant-core`、`services/quant-api`、`apps/quant-web` 和任务文档。
- 不修改 PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- 不修改策略、回测、信号、风控、企业微信或任何交易执行逻辑。
- 主图 EMA10 / EMA21 / EMA60 使用后端统一指标结果；Web 不再把本地 `calculateEMA()` 作为正式主图 EMA 来源。
- Live 模式不接 C2 统一 EMA，显示“Live 指标待 C3”语义。
- 火天大有只做 disabled / observation-only 占位，不计算、不提醒、不进回测。

## 执行步骤

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
- [x] C2 收尾：生成浏览器 GPT 审查包，明确 C3 单独开题 Gate。
- [x] C2 closeout fix：修正 EMA 能力语义、完整 active asset 计算锚点、API 语义字段和 100/500 根稳定性测试。

## 验证记录

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
git diff --check 442aa70e^..442aa70e
```

- Node tests：31 passed。
- Vite production build：passed；仍有既有约 651 kB chunk warning。
- C2 Node tests：34 passed。
- C2 closeout backend tests：`test_indicator_kernel.py`、`test_market_indicators_api.py`、`test_market_data_api.py` 共 21 passed。
- C2 closeout frontend Node tests：34 passed。
- C2 closeout Vite production build：passed；仍有既有约 650.95 kB chunk warning。
- EMA 稳定性：同一 `symbol/contract/period/end` 下请求 100 根和 500 根，重叠区间 EMA10 / EMA21 / EMA60 的 `time/value/ready/valid/reason` 完全一致。
- API 语义字段：`seed_policy`、`calculation_start`、`warmup_bars`、`confirmed_only`、`data_version` 已返回并有测试覆盖。
- Browser smoke：本次使用 `http://127.0.0.1:5175` Web + `http://127.0.0.1:8001` API；API 环境来自本机运行时 `project.env`，未打印任何凭据。
- Market smoke：`/market/chart?symbol=jm&contract=JM2609&period=15m`，趋势均线打开 EMA10/EMA21/EMA60，MACD 副图保留，21 个 canvas，console 0 error / 0 warning。
- Backtest smoke：`/backtest?report_id=14`，K 线报告视图打开，成交 marker 页面路径可渲染，23 个 canvas，console 0 error / 0 warning。
- Review smoke：`/review` 选中 `#3106`，K 线定位、交易点备注、MACD 显示可见，21 个 canvas，console 0 error / 0 warning。
- C2 closeout smoke 截图：`output/playwright/web-main-indicators-c2-market.png`、`output/playwright/web-main-indicators-c2-backtest.png`、`output/playwright/web-main-indicators-c2-review.png`。

## 风险记录

- `KlineChart.vue` 被 Market/Backtest/Review 共享，因此默认 props 必须保持 EMA21 可见，避免旧页面失去基准指标。
- localStorage 只保存 UI 偏好，不保存 K 线、指标值、live bar、quality status 或业务订阅状态。
- C3/C4 必须另设 Gate：实时跟随、火天大有正式/观察接入都不在本轮完成。
- MACD/ATR 未进入统一指标内核，本轮不迁移现有 Web 副图或策略口径。
- C3 不得混入当前 C2 收尾；必须等浏览器 GPT 审 C2 diff 与测试结果通过后，另开任务/会话/Plan。
- 当前状态不是 `C2_ACCEPTED`；必须由浏览器 GPT 复审 closeout diff、测试结果和三页面 smoke 后决定。

## GPT 同步清单

- `docs/gpt/WEB_INDICATORS_C2_REVIEW_PACKAGE.md`
- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/tests/mainIndicators.test.ts`
- `packages/quant-core/guiyi_quant/indicators/*`
- `services/quant-api/app/services/market_indicators.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/tests/test_indicator_kernel.py`
- `services/quant-api/tests/test_market_indicators_api.py`
- `docs/INDICATOR_KERNEL.md`
- `output/playwright/web-main-indicators-c2-market.png`
- `output/playwright/web-main-indicators-c2-backtest.png`
- `output/playwright/web-main-indicators-c2-review.png`
