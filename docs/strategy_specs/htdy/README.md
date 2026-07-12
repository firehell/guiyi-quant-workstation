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

## 公式规范（已补齐）

用户已授权将完整通达信公式写入 tracked docs。当前三份规范文件：

- [`INDICATOR_SPEC.md`](INDICATOR_SPEC.md)：原始公式、变量表和公式拆解。
- [`INDICATOR_RISK_REVIEW.md`](INDICATOR_RISK_REVIEW.md)：未来函数、重绘和接入边界审查。
- [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md)：`huotian_dayou_original_v0` observation-only 策略骨架。

结论保持不变：原始公式含 `XMA(XMA(...))`，只能 observation-only。

## 原始 Observation-Only PoC（已补齐）

PoC 位置：

- [`../../../experiments/htdy_indicator/htdy_original_core.py`](../../../experiments/htdy_indicator/htdy_original_core.py)：完整原始公式数值复刻。
- [`../../../experiments/htdy_indicator/export_htdy_original.py`](../../../experiments/htdy_indicator/export_htdy_original.py)：CSV / JSON 导出 CLI。
- [`../../../experiments/htdy_indicator/README.md`](../../../experiments/htdy_indicator/README.md)：运行方式和风险边界。

PoC 输出 `ZK1/ZD1/ZD2/黄K/白K/买多信号/卖空信号/VAR23/回调买/XG/DDX/V2/V5/V10/V20/DY/DY2/XG2`，并记录：

- `status=observation_only`
- `repainting_risk=known`
- `CAPITAL=0` 期货分支
- `FROMOPEN=1.0` PoC 默认值
- `CURRBARSCOUNT` 的 PoC 图表末端语义

本 PoC 只作为后续 Web 对齐和 Golden Sample 的数值基准，不接入正式策略、回测、扫描、live、数据库、报告或通知链路。

## Strict Backward-Looking V1（第 3 步）

第 3 步新增 `huotian_dayou_strict_v1` 研究候选：

- [`STRICT_V1_SPEC.md`](STRICT_V1_SPEC.md)：strict v1 改写方案、字段边界和 Gate。
- [`../../../experiments/htdy_indicator/htdy_strict_core.py`](../../../experiments/htdy_indicator/htdy_strict_core.py)：纯函数实验实现。
- [`../../../services/quant-api/tests/test_htdy_strict_core.py`](../../../services/quant-api/tests/test_htdy_strict_core.py)：future-tail / append consistency / warm-up 测试。

strict v1 使用 `double_trailing_ema` 替代原始双层 `XMA`，只证明当前研究候选不读取未来 bar。它仍是 `strict_research_candidate`，不接入正式策略、回测报告、扫描、live、数据库或企业微信。

## 公共指标内核关系

`docs/INDICATOR_KERNEL.md` 已建立 `Indicator Kernel V1-A`：

- `EMA10 / EMA21 / EMA60` 已进入 `packages/quant-core/guiyi_quant/indicators/` 公共内核。
- 火天大有当前只在注册表中保留 `observation_only` 风险边界。
- 公式级 Spec 已完成，原始 XMA 版本仍不得写入 `strategy_signals`、`signal_events`、正式回测报告或企业微信通知。
- 原始 observation-only PoC 已完成；strict backward-looking v1 已作为研究候选新增，不能复用原始 XMA 输出冒充可信信号。

## 任务追踪

- Issue #10：`TASK-2026-07-11-002-htdy-indicator-core.md`
- Web 交付：`TASK-2026-07-11-003-web-main-indicators.md`
