# 火天大有（HTDY）指标说明

## Web 观察层（已交付）

主图指标 ID：`huo_tian_da_you`（见 `apps/quant-web/src/utils/mainIndicators.ts`）

实现位置：

- 计算：`apps/quant-web/src/utils/indicators.ts`（`calculateHuoTianDaYou` / XMA 通道）
- 渲染：`apps/quant-web/src/components/kline/KlineChart.vue`
- 交互：`apps/quant-web/src/pages/market/chart.vue`

UI 约束：

- 标签：`观察专用 · 会重绘`
- 不接入正式 marker、信号扫描、回测或企业微信

## 风险审查

必读：[`docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`](../tdx_xma_bands/INDICATOR_RISK_REVIEW.md)

## 私有公式（可选）

若需补充通达信原文对照 Spec，放入：

```text
private_sources/htdy/formula.txt
```

该目录 gitignore，不会提交。

## 公共指标内核关系

`docs/INDICATOR_KERNEL.md` 已建立 `Indicator Kernel V1-A`：

- `EMA10 / EMA21 / EMA60` 已进入 `packages/quant-core/guiyi_quant/indicators/` 公共内核。
- 火天大有当前只在注册表中保留 `observation_only` 风险边界。
- 在 `private_sources/htdy/formula.txt` 缺失时，不生成正式公式 Spec、不实现 Python PoC、不进入 backward-looking 改写。
- 即使后续补充公式，原始 XMA 版本也不得写入 `strategy_signals`、`signal_events`、正式回测报告或企业微信通知。

## 任务追踪

- Issue #10：`TASK-2026-07-11-002-htdy-indicator-core.md`
- Web 交付：`TASK-2026-07-11-003-web-main-indicators.md`
