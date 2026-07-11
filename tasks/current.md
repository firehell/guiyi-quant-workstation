# 当前任务：WEB-MAIN-INDICATORS-V1

生成时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`

分支：`codex/web-main-indicators`

状态：`DELIVERY_READY`

## 目标

在 Web K 线主图增加主图指标多选叠加，支持 `EMA10`、`EMA21`、`EMA60`、`火天大有` 任意组合；默认只启用 `EMA21`；`MACD` 继续固定在副图。

## 已完成

- [x] 主图指标选择 UI：`主图指标 (n)`、立即切换、清空、恢复默认。
- [x] 用户选择写入浏览器本地，刷新页面后保留。
- [x] `KlineChart.vue` 从单条硬编码 `emaSeries` 改为动态主图指标 series map。
- [x] `EMA10 / EMA21 / EMA60` 复用既有 `calculateEMA(bars, period)`。
- [x] 火天大有前端观察层：`ZK1 / ZD1 / ZD2`、色带、K 线观察染色、三连观察提示。
- [x] 火天大有显示 `观察专用 · 会重绘`，不接入正式 marker 点击逻辑。
- [x] hover-strip 和 Market 十字线快照展示当前启用主图指标值。

## 硬边界

- 不修改 FastAPI、PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- 不修改策略信号、回测、成交、成本、风控计算。
- 不执行信号扫描、回测、复盘写入、企业微信发送或任何交易动作。
- 火天大有基于 XMA，存在未来函数和重绘风险，只能作为 Web 人工观察指标，不得进入正式信号、live evaluator、回测报告或企业微信。

## 验收证据

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

## 遗留项

1. 火天大有视觉复刻仍需用户主观验收；如要与通达信截图逐像素校准，应另开视觉校准任务。
2. 火天大有不得升级为正式信号；若未来需要策略化，必须另开 strictly backward-looking 改写和安全审查。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/tests/indicators.test.ts`
- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
