# 当前任务：HTDY-INDICATOR-CORE（火天大有 Web 观察层已合并）

生成时间：2026-07-11

Worktree：`/Volumes/扩展盘/guiyi-parallel/htdy-core`

分支：`codex/htdy-indicator-core`

主工程来源：`codex/web-main-indicators`（已从主仓同步 Web 实现）

状态：`DELIVERY_READY`

## 任务单

- 规范与风险：`docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`（Issue #10）
- Web 交付：`docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`

## 目标

火天大有作为 **Web 观察专用指标** 落地：主图多选叠加 `EMA10/EMA21/EMA60/火天大有`，默认 `EMA21`；火天大有展示 `ZK1/ZD1/ZD2`、色带、K 线染色与 `观察专用 · 会重绘` 标签。

## 已完成

- [x] 主工程 `codex/web-main-indicators` 实现已同步到本 worktree。
- [x] `mainIndicators.ts` 注册 `huo_tian_da_you`，标记 `observationOnly`。
- [x] `KlineChart.vue` 动态主图指标 series；火天大有观察层与 EMA 多选共存。
- [x] Market 页多选菜单、本地持久化、hover/十字线快照联动。
- [x] 风险边界：不接入信号、回测、live、企业微信。

## 硬边界

- 火天大有基于 XMA，存在未来函数和重绘风险。
- 不得写入 `signal_events`、正式报告或通知链路。
- 策略化/信号化须另开 Plan + backward-looking 改写。

## 验收证据

```bash
npm --prefix apps/quant-web run test:indicators
npm --prefix apps/quant-web run build
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

- 指标测试：8 passed
- Web Node tests：31 passed
- XMA 风险测试：4 passed
- Vite build：passed

## 遗留项

1. 通达信截图逐像素视觉校准（可选独立任务）。
2. `docs/strategy_specs/htdy/` 正式 Spec 文档（若用户补充私有公式后可继续 Codex Dev）。

## 关键文件

- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
