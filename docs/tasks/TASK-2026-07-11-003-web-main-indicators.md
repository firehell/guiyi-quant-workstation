# TASK-2026-07-11-003 Web 主图指标多选叠加

生成时间：2026-07-11

状态：`DELIVERY_READY`

## 目标

在不修改 API、数据链路、回测、策略信号或企业微信链路的前提下，为 Web K 线主图增加主图指标多选叠加：

- `EMA10`
- `EMA21`
- `EMA60`
- `火天大有`

`MACD` 继续固定在副图，不参与主图指标选择。

## 交付内容

- `KlineChart.vue` 增加 `主图指标 (n)` 多选菜单，支持立即切换、清空、恢复默认。
- 默认只启用 `EMA21`，用户选择持久化到浏览器本地。
- 主图指标 series 改为按选择动态创建/移除，避免旧线和重复线残留。
- hover-strip 和 Market 右侧十字线快照改为展示当前启用主图指标值。
- `EMA10 / EMA21 / EMA60` 复用既有 `calculateEMA(bars, period)` 口径。
- 火天大有按前端观察层实现 `ZK1 / ZD1 / ZD2`、色带、K 线观察染色和三连观察提示。
- 火天大有在 UI 标记 `观察专用 · 会重绘`，不进入正式 marker 点击逻辑。

## 安全边界

- 不修改 FastAPI、PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- 不修改回测引擎、策略信号、live evaluator、企业微信或交易逻辑。
- 火天大有基于 XMA，存在未来函数和重绘风险，只能作为 Web 人工观察指标。
- 火天大有不得写入 `signal_events`、正式报告、回测结果或通知链路。

## 验证

```bash
npm --prefix apps/quant-web run test:indicators
npm --prefix apps/quant-web run build
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

结果：

- 前端指标测试：8 passed。
- 前端全量 Node tests：31 passed。
- XMA 风险测试：4 passed。
- Vite build：passed；仍有既有约 651 kB chunk warning。
- Browser smoke：`/market/chart?symbol=jm&contract=JM2609&period=15m` 默认 EMA21 + MACD；EMA10 切换、火天大有观察标签、清空、恢复默认、刷新持久化均通过；console 仅 API info，无 error/warn。

## 遗留项

- 火天大有的 K 线染色为 Web 观察层复刻，仍应由用户视觉验收；如要逐像素对齐通达信截图，需要后续单独拿原始截图做视觉校准。
- XMA/火天大有不得升级为正式信号，除非另开任务重写为严格 backward-looking 指标并通过安全审查。
