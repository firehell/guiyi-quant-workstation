# Indicator Kernel V1-D GPT Safety Review Prompt

生成时间：2026-07-11

用途：复制给浏览器 GPT，作为 `Indicator Kernel V1-D` 的外部安全复核 Prompt。

BEGIN GPT REVIEW PROMPT

请作为归一量化项目的外部安全审查 GPT，复核 `Indicator Kernel V1-D`。

本轮结论候选：V1-D 只应作为迁移设计和 golden vector 对照 checkpoint，不应继续替换策略、扫描、live evaluator、Web 或报告链路。若继续，必须另开 `V1-E`，且一次只迁移一个调用方。

## 背景

- V1-A 新增 `packages/quant-core/guiyi_quant/indicators/`，实现 EMA 公共内核和指标注册表。
- V1-B 完成 MACD / ATR 差异审计，确认 Web、FastAPI strategy 和 quant-core strategy 的 seed、histogram、smoothing 口径不一致。
- V1-C 新增可复刻多口径的 `macd_series()` / `atr_series()` draft 公共函数，但不迁移任何调用方。
- V1-D 新增逐调用方迁移设计和 synthetic golden vector 对照测试，只证明公共函数可以复刻现有口径。
- MACD / ATR 仍不写入 `indicator_registry`，不注册为 `validated`。
- `jm_v1b_daily_direction_fast_entry` 与 `live_signal_evaluator` 属 P0 可信链路，只做对照，不迁移。
- 火天大有仍为 `observation_only`，不进入回测、`signal_events`、live evaluator 或企业微信。

## 请阅读的文件

1. `docs/INDICATOR_KERNEL.md`
2. `docs/INDICATOR_KERNEL_V1B_DIFF.md`
3. `docs/INDICATOR_KERNEL_V1C_PLAN.md`
4. `docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md`
5. `services/quant-api/tests/test_indicator_kernel.py`
6. `services/quant-api/tests/test_indicator_kernel_v1b_diff.py`
7. `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
8. `services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py`
9. `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
10. `tasks/current.md`

## 请重点审查

1. 是否存在未来函数、数据泄露、信号时点提前、confirmed bar 边界不清。
2. MACD / ATR 多口径公共函数是否只是 draft 复刻层，是否仍不应注册为 `validated`。
3. V1-D golden vector 是否足以证明“可复刻现有口径”，但不足以证明“可安全替换整条策略链”。
4. `jm_v1b_daily_direction_fast_entry` 与 `live_signal_evaluator` 是否应继续保持 P0 可信链路，只对照不迁移。
5. 是否同意后续 `V1-E` 只能选择单一调用方，并固定兼容 policy、迁移前后输出、策略回归和必要的版本升级规则。
6. 是否存在 P0：未来函数、静默改策略口径、误把 Web 展示口径用于信号或回测、一次替换整条策略链。

## 当前测试证据

- V1-D golden vector：`5 passed`
- Indicator Kernel V1-A/B/C/D：`27 passed`
- JM V1-B + live evaluator：`13 passed`
- 策略族回归：`33 passed`
- `git diff --check`：passed
- 禁止目录 diff 核对：无输出

## 请输出

- 总结论：通过 / 不通过 / 有条件通过。
- P0：必须先修复的问题。
- P1：进入 V1-E 前建议修复的问题。
- 是否允许关闭 V1-D。
- 若允许继续，推荐的第一个 V1-E 单一调用方，以及原因。
- 明确禁止项：是否禁止一口气替换整条策略链。

END GPT REVIEW PROMPT
