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

## 任务追踪

- Issue #10：`TASK-2026-07-11-002-htdy-indicator-core.md`
- Web 交付：`TASK-2026-07-11-003-web-main-indicators.md`
