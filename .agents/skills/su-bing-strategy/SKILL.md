---
name: su-bing-strategy
description: 用于归一量化项目中，将苏冰课程 MD / Notion 导出内容整理为通用、稳定、可复用的课程知识 Skill。适用于苏冰资料索引、Rulebook 规则候选、复盘标签、Strategy Spec 生成协议和策略规格审查边界；不适用于直接生成策略代码、默认继承旧策略规格、绑定单一品种或绑定某个项目阶段。
---

# Su Bing Strategy Skill

## 1. Skill 定位

本 Skill 是通用苏冰课程知识资产，用于把苏冰课程 MD / Notion 导出内容整理成可审查、可复用、可继续生成 Strategy Spec 的知识结构。

本 Skill 不是一个可回测策略，不代表任何单一策略版本，也不直接生成策略代码。它的作用是帮助后续在明确当前策略目标后，重新生成独立 Strategy Spec，再经审查后进入代码实现。

本 Skill 可以在私人仓库中读取本地课程源材料，但 Skill 文档、Rulebook、Review Tags 和 Strategy Spec 草案不得复制课程原文、长段摘录、截图、图片案例内容或私有 Notion 大段内容。

## 2. 固定边界

- 不绑定任何单一品种。
- 不绑定 JM 或任何具体期货品种。
- 不绑定 V1-B 或任何单一项目阶段。
- 不绑定 5m、15m 或任何固定周期组合。
- 不绑定 5-8 根 bar 或任何固定持有周期。
- 不直接生成 vn.py、回测、Web、数据库或实盘代码。
- 不直接代表某个可回测策略。
- 不把旧策略代码、旧回测实现或旧规格当作 Skill 规则来源。
- 不把 `SU_BING_QUANT_SPEC_V0_1.md` 当作后续策略实现的默认规格。
- 不把旧 `su_bing_ema21` 当作默认策略、默认参数或默认实现目标。
- 不把主观课程内容直接转成买卖信号。
- 不把 `TAG-*`、人工复核结论或复盘结论写入同一时点 `on_bar` 信号判断。

## 3. 知识来源

Skill 的原始知识来源只能是苏冰课程 MD / Notion 导出内容，以及由这些资料整理出的公开索引、短摘要和人工复核状态。

本项目是私人仓库时，`private_sources/` 可作为本地私有源存在；但进入 Skill 体系的内容只能是 source_id、短摘要、抽象规则候选、量化状态、人工复核状态和边界说明。

允许读取和维护：

- `references/source-map.md`
- `docs/strategy_knowledge/su_bing/SOURCE_INDEX.md`
- `docs/strategy_knowledge/su_bing/NOTION_EXTRACTION_SUMMARY.md`
- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
- `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`
- `references/STRATEGY_GENERATION_PROTOCOL.md`

禁止把以下内容作为 Skill 规则来源：

- 当前已有苏冰策略代码。
- 旧回测实现。
- 旧信号扫描实现。
- 旧数据库字段设计。
- 旧 `SU_BING_QUANT_SPEC_V0_1.md` 的工程默认参数。
- 旧 `su_bing_ema21` 的策略行为、参数、周期、实现文件路径或测试路径。
- `SU_BING_REVIEW_REPORT.md` 中针对旧 Quant Spec 的 P0/P1/P2 修复建议。

旧 `SU_BING_QUANT_SPEC_V0_1.md` 和旧 `su_bing_ema21` 只能作为：

- `history_draft`：历史策略规格草稿。
- `legacy_reference`：旧阶段参考资料。
- `engineering_reference`：接口形态、文件组织或字段命名参考。

这些旧资产不得作为课程规则来源、参数默认来源、新 Strategy Spec 默认来源或代码实现准入依据。

## 4. 适用任务

使用本 Skill 处理以下任务：

- 整理苏冰课程资料索引、摘要和来源状态。
- 将课程内容拆分为理念边界、规则候选、复盘标签和人工复核项。
- 维护通用 Rulebook，明确哪些内容只是规则候选。
- 维护 Review Tags，明确哪些内容只能用于复盘或交易后诊断。
- 基于当前用户给定的策略目标，辅助生成新的独立 Strategy Spec。
- 审查新 Strategy Spec 是否越界继承旧策略、旧规格或主观内容。

## 5. 输出类型

根据任务输出以下结构之一：

- Source Map：资料索引、摘要状态、量化可能性和人工复核状态。
- Rulebook：课程规则库和规则候选，不是交易信号。
- Review Tags：复盘标签、执行偏差标签和人工诊断标签。
- Strategy Spec Draft：基于当前输入目标重新生成的独立策略规格草案。
- Spec Review：审查新 Strategy Spec 的未来函数、数据泄露、过拟合、成交假设、风控和版本边界。

所有输出必须标注：

- 哪些内容来自课程摘要。
- 哪些内容是规则候选。
- 哪些内容需要人工复核。
- 哪些内容只能进入复盘标签。
- 哪些内容属于当前 Strategy Spec 的新增假设。
- 哪些内容只是历史草稿或工程参考。

## 6. 规则候选处理方式

对 `quantizable = yes` 或明确可规则化的内容，只能整理为规则候选：

- 拆成方向、入场背景、出场背景、止损候选、止盈候选、过滤候选、风控候选和复盘标签候选。
- 标注来源、可量化程度、待确认问题和禁止提前使用的信息。
- 不擅自补全阈值、周期、品种、持有周期、成交假设或参数默认值。
- 不因为旧策略实现存在某个参数，就把它反推为课程规则。
- 不因为旧 `su_bing_ema21` 实现了某个周期、阈值、持有期或成交假设，就把它补成新 Strategy Spec 的默认值。

## 7. 主观内容处理方式

对 `quantizable = no`、`partial`、`needs_review` 或偏心理纪律的内容：

- 只能进入理念边界、复盘标签、执行检查、人工复核清单或规则候选。
- 不能直接进入买卖信号。
- 不能直接作为入场、出场、加仓、减仓或反手条件。
- 案例图片、口诀、抄底摸顶、心理偏差和执行力训练内容默认需要人工复核。
- 复盘结论不得回写为当时可用的信号条件。
- Review Tags 只能写入交易明细、K 线复盘、复盘 note 或后续版本评审，不得进入当前 bar 的入场、出场、过滤、加仓、减仓或反手判断。

## 8. 新策略生成要求

每次真正生成策略时，必须根据当前目标重新生成独立 Strategy Spec。必须先读取 `references/STRATEGY_GENERATION_PROTOCOL.md`，并要求当前任务明确：

- 品种。
- 数据范围。
- 周期。
- 持有周期。
- 交易方向。
- 风控约束。
- 回测引擎。
- 成交假设。
- 禁止事项。

若缺少上述关键输入，不得把旧策略、旧代码或旧 `SU_BING_QUANT_SPEC_V0_1.md` 作为默认补全来源。

若用户要求“生成苏冰策略”，也必须先生成新的独立 Strategy Spec；不得直接恢复、修补或实现旧 `su_bing_ema21`。

## 9. 安全审查要求

任何新 Strategy Spec 都必须审查：

- 是否存在未来函数。
- 是否存在数据泄露。
- 是否存在过拟合。
- 信号确认时点和成交时点是否分离。
- 成交假设是否可执行。
- 手续费、滑点、合约乘数和保证金是否纳入。
- 单笔风险、最大回撤和连续亏损是否可统计。
- 复盘标签是否只用于交易后诊断。
- `TAG-*` 是否明确不参与同一时点 `on_bar` 信号判断。
- V1 是否保持不做全自动实盘。
- 策略版本是否明确记录。

## 10. 实现边界

本 Skill 不执行代码实现。若后续用户要求实现策略，必须先有独立 Strategy Spec 和审查结论，并由用户明确允许修改代码范围。

实现任务不得默认修改：

- `packages/quant-core/`
- `services/quant-api/`
- `apps/quant-web/`
- 数据库 migration
- 回测引擎代码
- 实盘交易代码
- `private_sources/`

不得写入账号、密码、API Key、token、license 或任何私有课程原文。

即使后续 Strategy Spec 通过审查，本 Skill 本身也不授权修改策略代码、回测代码、Web、数据库 migration 或 tests；代码实现必须另开任务并由用户明确授权修改范围。
