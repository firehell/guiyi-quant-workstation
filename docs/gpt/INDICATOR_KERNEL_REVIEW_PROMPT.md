# Indicator Kernel V1-A / V1-B GPT Review Prompt

生成时间：2026-07-11

用途：复制给浏览器 GPT，作为指标内核审计 checkpoint 的外部安全复核 Prompt。

BEGIN GPT REVIEW PROMPT

请作为归一量化项目的外部安全审查 GPT，复核 Indicator Kernel V1-A / V1-B checkpoint。

## 背景

- V1-A 新增 `packages/quant-core/guiyi_quant/indicators/`，只实现 EMA 公共内核和指标注册表。
- V1-B 只做 MACD / ATR 差异审计，不把 MACD / ATR 注册为 `validated`，不替换策略、扫描、live evaluator、Web 或通知链路。
- 火天大有仍为 `observation_only`，不进入回测、`signal_events`、live evaluator 或企业微信。
- 当前测试：Indicator Kernel V1-A `7 passed`；V1-B diff audit `5 passed`；JM V1-B `7 passed`；XMA 风险 `4 passed`；合并运行 `23 passed`。
- 当前工作区中，`packages/quant-core/guiyi_quant/strategies/`、`services/quant-api/app/`、`apps/`、`data/` 无 diff。

## 请阅读的文件

1. `docs/INDICATOR_KERNEL.md`
2. `docs/INDICATOR_KERNEL_V1B_DIFF.md`
3. `services/quant-api/tests/test_indicator_kernel.py`
4. `services/quant-api/tests/test_indicator_kernel_v1b_diff.py`
5. `tasks/current.md`
6. `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
7. `docs/INDICATOR_KERNEL_V1C_PLAN.md`

## 请重点审查

1. V1-A 的 EMA seed、warm-up、NaN、future-tail 不重绘、注册表能力边界是否足够清楚。
2. V1-B 是否准确识别 MACD / ATR 口径差异，包括 Web `sma_window` seed、Web `histogram * 2`、Python `first_value` seed、ATR `wilder_sma_seed` / `wilder_first_tr` / `ema_first_tr`。
3. 是否同意结论：MACD / ATR 当前不能直接统一替换。
4. 是否允许进入 V1-C：只新增可复刻多口径的 `macd.py` / `atr.py` 和测试，不迁移任何调用方。
5. 是否存在 P0：未来函数、静默改策略口径、误把 Web 展示口径用于信号或回测。

## 请输出

- 总结论：通过 / 不通过 / 有条件通过。
- P0：必须先修复的问题。
- P1：建议 V1-C 前修复的问题。
- 是否允许进入 V1-C。
- 若允许，是否同意 `docs/INDICATOR_KERNEL_V1C_PLAN.md` 的范围和测试 Gate。

END GPT REVIEW PROMPT
