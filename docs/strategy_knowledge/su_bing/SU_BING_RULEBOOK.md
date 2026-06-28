# SU_BING_RULEBOOK

## Purpose

This document is the public, structured Su Bing strategy rulebook for Guiyi Quant.

It converts the public structured summaries in `SOURCE_INDEX.md` and `NOTION_EXTRACTION_SUMMARY.md` into auditable rule candidates. It does not copy private Notion exports, course text, long passages, screenshots, executable logic, runtime strategy code, buy/sell points, backtest code, or live trading instructions.

## Boundaries

- Use this rulebook as a course rule library and rule-candidate library for future Strategy Spec generation, review tags, and future backtest design.
- Every `RULE-*` entry is a rule candidate only. It is not an executable rule, a hard-coded strategy, a buy/sell signal, or an implementation requirement.
- Do not treat any rule here as a direct trade signal.
- Do not turn cases, slogans, psychology notes, or extreme-position topics into executable entry rules without manual review.
- Mark missing thresholds, parameters, confirmation bars, execution timing, and case-image details as `待补充`.
- If product, timeframe, holding period, threshold, execution timing, fill policy, stop/take-profit priority, or data range is missing, mark it as `requires_spec_decision` or `requires_user_decision`.
- Do not fill missing decisions from old `su_bing_ema21`, old strategy code, old tests, old reports, or `SU_BING_QUANT_SPEC_V0_1.md`.
- Review tag candidates named here are post-trade diagnostic candidates only; they must not become same-bar `on_bar` entry, exit, filter, add, reduce, or reverse conditions.
- Any future implementation must use only current and past completed bars and must separate signal time from execution time.

## Source Policy

- Primary public sources: `SOURCE_INDEX.md` and `NOTION_EXTRACTION_SUMMARY.md`.
- Source IDs follow `sbn-001` through `sbn-016`.
- `quantization_hint` values are limited to `可量化`, `部分可量化`, `不可量化`, and `待人工复核`.
- `strategy_spec_candidate` values are limited to `yes`, `partial`, `no`, and `needs_review`. It marks whether a course rule candidate may seed a future independent Strategy Spec.
- Private source material may exist in the local/private repository, but this Rulebook may contain only short summaries, abstract candidates, source IDs, quantization status, and manual-review status. Do not copy original course text, long passages, screenshots, or image-only case content.

# 可量化或部分可量化规则候选

## RULE-001：交易理念层

- source_hint: `sbn-002` 交易理念；`sbn-004` 原则。
- rule_type: 理念边界 / 系统化前提。
- condition: 当整理、审查或实现苏冰策略规则时，先判断规则是否服务于系统化交易、趋势前提和纪律执行。
- logic: 规则必须避免抄底摸顶、逆势加仓、亏损加仓、重仓和报复性行为；趋势行情可作为系统发挥的主要场景，震荡环境应回避或降低频率。
- quantization_hint: 部分可量化。趋势和震荡过滤可在后续规格中量化，理念本身不直接生成交易触发。
- strategy_spec_candidate: partial
- risk_note: 摘要没有提供震荡识别阈值、趋势定义和降频参数，必须标记为待补充，不能凭经验补造。
- review_tag_candidate: 系统化前提 / 逆势行为 / 震荡降频 / 纪律偏差。

## RULE-002：交易系统层

- source_hint: `sbn-003` 交易系统。
- rule_type: 策略框架 / 规则候选。
- condition: 当构建苏冰策略规格时，以均线方向、MACD 确认、量能变化、震荡区间、突破有效性、持仓依据和退出管理为系统要素。
- logic: 一个可审查策略必须同时声明方向判断、辅助确认、入场背景、过滤条件、持仓依据和退出管理，不能只保留单个入场触发。
- quantization_hint: 可量化。各要素可转为字段和规则候选，但当前摘要没有完整参数。
- strategy_spec_candidate: yes
- risk_note: 不能直接把系统框架压缩成买卖点；确认时点、成交时点、参数和失败条件均待补充。
- review_tag_candidate: 系统完整性 / 指标确认 / 持仓依据 / 退出管理。

## RULE-003：趋势判断

- source_hint: `sbn-003` 交易系统；`sbn-012` 不同周期的交易策略；`sbn-013` 周期选择。
- rule_type: 趋势过滤 / 方向判断。
- condition: 当生成方向规则时，先使用大周期判断方向，再用小周期寻找介入窗口，并结合均线方向、周期共振和趋势稳定性描述。
- logic: 大周期方向优先，小周期只承担择时或观察角色；趋势判断应区分趋势延续、趋势失败和震荡环境。
- quantization_hint: 部分可量化。周期层级、均线方向和共振可量化，趋势强弱阈值与失败定义待补充。
- strategy_spec_candidate: partial
- risk_note: 不能使用未来趋势结果或事后走势确认当前方向；趋势失败必须等待可观察确认。
- review_tag_candidate: 趋势方向 / 周期共振 / 趋势失败 / 震荡识别。

## RULE-004：EMA21 相关规则

- source_hint: `sbn-003` 交易系统；`sbn-013` 周期选择；`sbn-014` 交易开平仓口诀。
- rule_type: 均线规则 / EMA21 候选。
- condition: 当整理 EMA21 策略规格时，将均线方向、价格与 EMA21 的关系、回踩、突破、斜率和偏离约束作为候选字段。
- logic: EMA21 可作为趋势和入场背景的核心观察线，但必须结合方向、周期、确认和过滤条件，不能单独作为开仓触发。
- quantization_hint: 部分可量化。EMA21 方向、价格关系、斜率和距离可计算；摘要未给出具体阈值、周期或确认 bar。
- strategy_spec_candidate: partial
- risk_note: `sbn-014` 属于口诀型摘要，只能作为人工规则化线索；任何阈值、斜率定义和偏离范围都待补充。
- review_tag_candidate: EMA21方向 / EMA21回踩 / EMA21突破 / 均线偏离。

## RULE-005：MACD 辅助判断

- source_hint: `sbn-003` 交易系统；`sbn-014` 交易开平仓口诀。
- rule_type: 指标确认 / 辅助过滤。
- condition: 当趋势或入场规则需要辅助确认时，可将 MACD 方向、确认、背离和失败作为候选检查项。
- logic: MACD 只作为辅助判断，不应脱离趋势、均线、周期和过滤条件独立生成交易规则。
- quantization_hint: 部分可量化。MACD 指标字段可计算，但摘要未提供金叉死叉、柱体、背离或失败的正式定义。
- strategy_spec_candidate: partial
- risk_note: 背离和失败类判断容易使用未来结构，后续实现必须明确确认 bar 和信号可用时点。
- review_tag_candidate: MACD确认 / MACD背离 / 指标失效 / 辅助确认不足。

## RULE-006：回调入场

- source_hint: `sbn-003` 交易系统；`sbn-012` 不同周期的交易策略；`sbn-014` 交易开平仓口诀。
- rule_type: 入场候选 / 回调场景。
- condition: 当大周期方向成立且小周期出现介入窗口时，可将均线附近回调、支撑压力和周期共振作为回调入场候选。
- logic: 回调入场必须先有方向背景，再检查回调位置、确认信号和失效条件；不能因为价格接近均线就直接开仓。
- quantization_hint: 待人工复核。摘要支持“回调/择时/均线附近”框架，但没有给出可执行触发和确认细节。
- strategy_spec_candidate: needs_review
- risk_note: 不能直接作为买卖点；必须补充确认时点、成交时点、止损参照和参数证据。
- review_tag_candidate: 回调入场候选 / 周期择时 / 支撑压力 / 入场证据不足。

## RULE-007：突破入场

- source_hint: `sbn-003` 交易系统；`sbn-014` 交易开平仓口诀。
- rule_type: 入场候选 / 突破场景。
- condition: 当趋势背景、指标确认和过滤条件满足时，可将突破有效性作为入场候选。
- logic: 突破入场必须检查方向、指标、量能、震荡区间和假突破风险；突破本身不能脱离确认和过滤条件。
- quantization_hint: 待人工复核。摘要提到突破有效性和假突破，但未提供突破阈值、确认方式或失败条件。
- strategy_spec_candidate: needs_review
- risk_note: 突破有效性不能用未来高低点或事后走势判断；必须补充确认 bar 和可执行成交假设。
- review_tag_candidate: 突破入场候选 / 假突破 / 突破确认不足 / 量能确认。

## RULE-008：开仓过滤

- source_hint: `sbn-002` 交易理念；`sbn-003` 交易系统；`sbn-004` 原则；`sbn-014` 交易开平仓口诀。
- rule_type: 入场过滤 / 风控前置。
- condition: 当出现任何入场候选时，必须先检查趋势背景、震荡环境、MACD 或量能确认、等待确认、开仓克制和交易频率。
- logic: 开仓过滤优先于触发；不满足趋势、确认、风控和纪律条件时，入场候选应降级为观察或放弃。
- quantization_hint: 部分可量化。趋势、震荡、确认和频率可设计字段；开仓克制与等待确认需转为审查项。
- strategy_spec_candidate: partial
- risk_note: 摘要未给出频率上限、确认参数和震荡过滤阈值，后续不能补造默认值。
- review_tag_candidate: 开仓过滤 / 震荡回避 / 等待确认 / 交易频率。

## RULE-009：平仓规则

- source_hint: `sbn-003` 交易系统；`sbn-010` 交易日志与复盘；`sbn-011` 交易反思。
- rule_type: 出场候选 / 持仓管理。
- condition: 当持仓依据变化、退出管理触发、交易计划不再成立或复盘发现未按系统执行时，需要定义平仓候选。
- logic: 平仓必须关联入场依据、持仓依据、退出规则和系统一致性检查；不能只按盈亏结果事后解释。
- quantization_hint: 部分可量化。持仓依据、信号失败和计划一致性可转字段；具体退出触发待补充。
- strategy_spec_candidate: partial
- risk_note: 不能使用未来收益、最大利润或事后回撤来判断当时是否应平仓。
- review_tag_candidate: 持仓依据 / 信号失败退出 / 系统一致性 / 平仓纪律。

## RULE-010：止损规则

- source_hint: `sbn-004` 原则；`sbn-006` 资金管理；`sbn-008` 执行力训练。
- rule_type: 风控规则 / 止损候选。
- condition: 每笔交易在开仓前必须明确最大可承受亏损、止损参照和不利行情处理方式。
- logic: 止损优先于盈利预期；仓位、隔夜风险和趋势/震荡误判都必须服从最大亏损约束。
- quantization_hint: 部分可量化。最大亏损、止损价差和仓位可量化；摘要未给出具体比例、点数或账户约束。
- strategy_spec_candidate: partial
- risk_note: 未定义止损参数前不得进入回测实现；止损不能因执行心理或亏损厌恶被后移。
- review_tag_candidate: 止损优先 / 单笔风险 / 止损执行偏差 / 隔夜风险。

## RULE-011：止盈规则

- source_hint: `sbn-004` 原则；`sbn-008` 执行力训练；`sbn-011` 交易反思。
- rule_type: 风控规则 / 止盈候选。
- condition: 当交易计划包含盈利保护、固定盈亏比或止盈止损执行要求时，需要在开仓前定义止盈候选。
- logic: 止盈规则必须与初始风险、持仓依据和执行纪律绑定，不能在盈利后随意改变计划。
- quantization_hint: 部分可量化。固定盈亏比和盈利保护可量化；具体盈亏比、移动保护和分批规则待补充。
- strategy_spec_candidate: partial
- risk_note: 摘要只支持框架，不支持具体收益目标；不得事后用最高浮盈生成止盈规则。
- review_tag_candidate: 止盈执行 / 盈利保护 / 固定盈亏比 / 计划偏离。

## RULE-012：资金管理

- source_hint: `sbn-004` 原则；`sbn-006` 资金管理。
- rule_type: 仓位规则 / 风险管理。
- condition: 在确定是否开仓和开仓数量前，必须先评估可承受亏损、仓位轻重、隔夜风险、止损参照和资金回撤。
- logic: 先确定风险承受，再决定仓位；仓位不得脱离止损距离、账户风险和行情环境独立设定。
- quantization_hint: 部分可量化。账户风险、单笔风险、保证金和回撤可转字段；具体比例待补充。
- strategy_spec_candidate: partial
- risk_note: 没有资金约束的回测结果不可用于策略验收；隔夜风险和保证金占用后续必须显式处理。
- review_tag_candidate: 仓位约束 / 最大可承受亏损 / 回撤控制 / 隔夜风险。

## RULE-013：周期选择

- source_hint: `sbn-012` 不同周期的交易策略；`sbn-013` 周期选择。
- rule_type: 周期规则 / 多周期过滤。
- condition: 当策略需要方向和择时时，应区分大周期方向、小周期介入窗口、均线周期、时空平衡和周期共振。
- logic: 周期越大信号越慢但更稳定，小周期更易频繁止损；策略必须说明每个周期承担的职责。
- quantization_hint: 部分可量化。周期映射和多周期字段可实现；具体周期组合、共振阈值和切换规则待补充。
- strategy_spec_candidate: partial
- risk_note: 不得用未来大周期收盘结果提前过滤小周期信号；多周期数据必须严格按时间对齐。
- review_tag_candidate: 大周期方向 / 小周期择时 / 周期共振 / 周期错位。

## RULE-014：盯盘观察点

- source_hint: `sbn-007` 盯盘需要关注的点。
- rule_type: 观察清单 / 盘前盘中检查。
- condition: 盘前、盘中和复盘时，观察成交量、持仓量、涨跌幅、外盘关联、熟悉品种和多周期切换。
- logic: 盯盘观察点用于建立市场背景、品种筛选和复盘清单，不直接生成开平仓触发。
- quantization_hint: 部分可量化。成交量、持仓量、涨跌幅和多周期状态可转字段；外盘关联和熟悉品种需要人工定义。
- strategy_spec_candidate: partial
- risk_note: 观察项不能未经验证直接变成过滤参数；外盘关联和品种熟悉度尤其需要人工复核。
- review_tag_candidate: 盘前检查 / 盘中观察 / 品种筛选 / 多周期观察。

# 不可量化、复盘、心理与人工复核规则

## RULE-015：执行纪律

- source_hint: `sbn-004` 原则；`sbn-008` 执行力训练；`sbn-011` 交易反思；`sbn-015` 反人性的交易策略。
- rule_type: 执行纪律 / 复盘标签。
- condition: 当交易计划、止盈止损、等待机会、假突破处理或系统一致性被破坏时，记录执行纪律问题。
- logic: 执行纪律用于约束是否按计划交易、是否等待确认、是否减少冲动、是否遵守固定盈亏比，不作为直接交易触发。
- quantization_hint: 不可量化
- strategy_spec_candidate: no
- risk_note: 纪律内容可转为复盘标签和人工检查，不能写成自动开仓或自动平仓规则。
- review_tag_candidate: 未按计划 / 冲动交易 / 等待不足 / 假突破处理偏差。

## RULE-016：交易心理

- source_hint: `sbn-009` 交易心理；`sbn-015` 反人性的交易策略。
- rule_type: 心理偏差 / 复盘标签。
- condition: 当出现亏损厌恶、成本执念、补仓冲动、杠杆压力、心理账户、冲动追逐或抄底摸顶倾向时，记录心理偏差。
- logic: 交易心理只用于风险认知、执行纪律和复盘归因，不作为信号或过滤条件直接进入回测。
- quantization_hint: 不可量化
- strategy_spec_candidate: no
- risk_note: 心理描述不能被伪装成客观指标；若后续要量化，必须先定义可观察行为数据。
- review_tag_candidate: 亏损厌恶 / 成本执念 / 补仓冲动 / 杠杆压力 / 抄底摸顶冲动。

## RULE-017：复盘规则

- source_hint: `sbn-010` 交易日志与复盘；`sbn-011` 交易反思；`sbn-007` 盯盘需要关注的点。
- rule_type: 复盘流程 / 交易日志。
- condition: 每笔交易和每次策略迭代后，记录交易计划、仓位、最大亏损、开平依据、执行偏差、系统一致性和优化问题。
- logic: 复盘用于验证是否坚持系统、是否按信号和持仓原则行动、是否遵守固定盈亏比和二次确认流程。
- quantization_hint: 部分可量化
- strategy_spec_candidate: partial
- risk_note: 复盘结论只能用于后续改进，不能回写为当时信号生成条件，避免数据泄露。
- review_tag_candidate: 交易日志 / 系统一致性 / 二次确认 / 执行偏差 / 系统优化。

## RULE-018：不可量化内容

- source_hint: `sbn-001` 交易从此开始；`sbn-005` 经典开仓案例；`sbn-014` 交易开平仓口诀；`sbn-016` 怎么抄底摸顶。
- rule_type: 人工复核 / 禁止直接规则化。
- condition: 当材料属于目录入口、图片案例、口诀压缩表达、极端位置或抄底摸顶主题时，默认进入人工复核。
- logic: 这些内容只能作为资料导航、案例样本、规则化线索或风险提示；没有人工看图、OCR、专家确认和可观察定义前，不允许变成交易规则。
- quantization_hint: 待人工复核
- strategy_spec_candidate: needs_review
- risk_note: 案例只能作为样本，不允许直接变成交易规则；抄底摸顶主题风险高，不生成触发信号。
- review_tag_candidate: 案例待复核 / 口诀待拆解 / 极端位置待复核 / 禁止直接规则化。

# Manual Review Queue

- `sbn-005` 经典开仓案例：PDF 文本层只有案例标题，图形内容需要人工看图或 OCR 后再判断。
- `sbn-014` 交易开平仓口诀：只能作为人工规则化线索，需要拆解为可观察条件后再评估。
- `sbn-016` 怎么抄底摸顶：高风险主题，只能作为极端位置识别和人工复核线索。
- 所有入场、突破、回调、指标确认规则：确认时点、成交时点、参数阈值、止损参照和样本外验证均待补充。
