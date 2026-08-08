# Su Bing JM V1-B Short Hold Strategy Target

> 本文只定义策略目标边界，不是完整 Strategy Spec，不是可执行策略，不授权写策略代码。

## 1. 目标身份

- strategy_target_code: `su_bing_jm_v1b_short_hold`
- target_stage: `strategy_target`
- project_stage: `V1-B`
- product: `JM`
- strategy_source: `su-bing-strategy` Skill
- target_name: 焦煤 JM 3 年真实数据短持有策略

本目标用于定义第一个新苏冰策略的研究边界：在当前 V1-B 研究闭环内，验证苏冰课程规则候选在焦煤 JM 短持有场景下是否具备正期望。

## 2. 来源与边界

本目标来自以下材料的抽象规则候选和边界要求：

- `.agents/skills/su-bing-strategy/SKILL.md`
- `.agents/skills/su-bing-strategy/references/STRATEGY_GENERATION_PROTOCOL.md`
- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
- `.agents/skills/su-bing-strategy/references/SU_BING_REVIEW_TAGS.md`

未发现 `docs/strategy_knowledge/su_bing/SKILL_ACCEPTANCE_REVIEW.md`，本文不补造该验收 review 的结论。

本文只使用 Skill 中的课程摘要、规则候选、复盘标签和生成协议边界，不复制课程原文、长段摘录、截图、图片案例内容或私有 Notion 内容。

## 3. 当前策略目标

本策略目标收敛为：

- 品种：`JM`
- 数据范围：最近 3 年真实数据，具体起止日期由后续 Strategy Spec 固化。
- 数据来源：RQData / local standard parquet。
- 数据质量：仅允许 `data_role = primary` 且 `quality_status = passed` 的数据。
- 方向周期：`1d`，只用于确定方向。
- 入场周期：`15m` / `5m`，两条入场链路可独立生成后续规格。
- 持有周期：入场后持有 5-8 根对应入场周期 K线。
- 不利行情处理：必须按后续 Strategy Spec 中明确的止损方法退出。
- 研究目标：验证苏冰课程规则候选在 JM 短持有场景下是否有正期望。

`1d` 方向只能使用已确认日线，不得提前读取未来日线或当前未完成日线。`15m` 与 `5m` 不得混用交易明细、入场结果或报告结论。

## 4. 不是旧策略修复

本目标明确不是以下事项：

- 不是旧 `su_bing_ema21` 的修复版。
- 不是旧 `SU_BING_QUANT_SPEC_V0_1.md` 的续写版。
- 不是当前已有 `jm_v1b_daily_direction_fast_entry` 的重命名版。
- 不是直接复制苏冰课程内容。
- 不是把课程案例、口诀、心理纪律或复盘结论直接转成买卖信号。

旧 `su_bing_ema21`、旧 Quant Spec、旧代码、旧测试、旧报告和旧参数只能作为 `history_draft`、`legacy_reference` 或 `engineering_reference`，不得作为本目标的规则来源、参数默认来源、周期默认来源、持有周期默认来源或成交假设来源。

## 5. 允许进入后续 Strategy Spec 的候选方向

后续 Strategy Spec 可以从 Rulebook 中选择规则候选，但必须重新审查并明确量化方式：

- 趋势与周期：大周期方向、小周期择时、周期职责和多周期对齐。
- 系统框架：方向判断、辅助确认、入场背景、过滤条件、持仓依据和退出管理。
- EMA21 候选：均线方向、价格相对 EMA21 的位置、回踩、突破、斜率和偏离约束。
- MACD 候选：只作为辅助确认，不得脱离趋势、均线和过滤条件独立生成交易。
- 入场候选：回调入场和突破入场只能作为候选，不得在未补充确认时点、成交时点、止损参照和失败条件前实现。
- 风控候选：止损、止盈、资金管理、最大回撤和连续亏损统计必须在规格阶段显式定义。

Review Tags 只能用于交易后诊断、K线复盘、交易明细或复盘 note，不得进入同一时点 `on_bar` 的入场、出场、过滤、加仓、减仓或反手判断。

## 6. 禁止事项

本目标阶段不做：

- 不生成完整 Strategy Spec。
- 不写策略代码。
- 不修改回测、Web、数据库、API、migration 或测试代码。
- 不做实盘。
- 不自动下单。
- 不接 CTP / TqSdk 交易接口。
- 不做参数暴力优化或全样本寻优后直接验收。
- 不使用天勤旧数据作为正式回测数据。
- 不使用交易练习者数据作为正式回测数据。
- 不使用 `quality_status = failed` 的数据。
- 不把 `TAG-*`、人工复核结论或复盘结论回写为同一笔交易的信号条件。

## 7. 后续流程

后续必须按以下顺序推进：

1. 基于本文生成新的独立 Strategy Spec。
2. 在 Strategy Spec 中明确品种、数据范围、周期、交易方向、持有周期、风控约束、回测引擎、成交假设和禁止事项。
3. 审查 Strategy Spec：未来函数、数据泄露、过拟合、信号时点、成交时点、手续费、滑点、合约乘数、保证金、单笔风险、最大回撤、连续亏损和复盘标签边界。
4. Strategy Spec 通过审查后，另开实现任务，并由用户明确允许修改的代码范围。

在 Strategy Spec 通过审查前，本目标不授权任何策略实现、回测实现、信号扫描实现、Web 展示实现或数据库变更。

## 8. 当前未决项

以下内容需要在后续 Strategy Spec 阶段决定，不得从旧 `su_bing_ema21` 或旧代码中自动继承：

- 最近 3 年数据的精确起止日期。
- 多空方向：多空双向、只做多、只做空或仅观察。
- `1d` 方向规则的可观察定义。
- `15m` / `5m` 入场触发规则。
- 止损方法、止盈方法和同 bar 冲突处理。
- 信号生成时点、成交时点、订单类型和滑点假设。
- 手续费、合约乘数、保证金、最小变动价位和仓位规则。
- 单笔风险、最大回撤和最大连续亏损阈值。
- 复盘 note 和 Review Tags 的记录字段。
