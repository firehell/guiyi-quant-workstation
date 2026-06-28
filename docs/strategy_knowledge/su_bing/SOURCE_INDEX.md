# SOURCE_INDEX

## Purpose

This public index tracks structured extraction from local Notion exports placed
under `private_sources/su_bing_notion_export/`.

The private source files are not committed to git. This document stores only
short summaries, abstract classification notes, and extraction status. It must
not copy course text, long notes, or source passages.

## Source Index

| source_id | notion_page_title | source_type | section_name | raw_topic_summary | extracted_rule_candidate | quantizable | target_doc | status |
|---|---|---|---|---|---|---|---|---|
| sbn-001 | 交易从此开始 | pdf | 交易从此开始 | 目录型入口，列出苏冰体系的理念、系统、原则、案例、资金、盯盘、心理、复盘、周期和反人性主题。 | 作为 Skill 导航与资料索引，不形成规则。 | no | NOTION_EXTRACTION_SUMMARY.md | extracted |
| sbn-002 | 交易理念 | pdf | 交易理念 | 聚焦常见错误、趋势前提、系统化交易、回测优化、震荡回避和纪律执行。 | 可抽象为理念边界、震荡过滤、系统验证和纪律约束候选。 | partial | SU_BING_SKILL.md; SU_BING_RULEBOOK.md | extracted |
| sbn-003 | 交易系统 | pdf | 交易系统 | 围绕均线方向、MACD 确认、量能、震荡区间、突破有效性、持仓和退出约束组织系统框架。 | 可归入趋势过滤、指标确认、震荡过滤、退出管理和持仓管理候选。 | yes | SU_BING_RULEBOOK.md | extracted |
| sbn-004 | 原则 | pdf | 原则 | 强调开仓克制、止损优先、趋势把握、仓位控制、等待确认和执行固定盈亏比框架。 | 可归入风控原则、执行纪律、等待确认和交易频率控制候选。 | partial | SU_BING_SKILL.md; SU_BING_RULEBOOK.md | extracted |
| sbn-005 | 经典开仓案例 | pdf | 经典开仓案例 | PDF 文本层仅抽到案例标题，关键图形内容疑似在图片中。 | 需要人工看图或 OCR 后再判断是否能转为案例标签。 | needs_review | NOTION_EXTRACTION_SUMMARY.md | needs_manual_review |
| sbn-006 | 资金管理 | pdf | 资金管理 | 聚焦最大可承受亏损、仓位轻重、隔夜风险、止损参照、趋势和震荡下的资金处理。 | 可归入仓位约束、单笔风险、隔夜风险和回撤控制候选。 | partial | SU_BING_RULEBOOK.md; SU_BING_REVIEW_TAGS.md | extracted |
| sbn-007 | 盯盘需要关注的点 | pdf | 盯盘需要关注的点 | 覆盖复盘、盯盘、成交量、持仓量、涨跌幅、外盘、熟悉品种和多周期切换。 | 可归入盘前检查、盘中观察、品种筛选和复盘清单候选。 | partial | SU_BING_SKILL.md; SU_BING_REVIEW_TAGS.md | extracted |
| sbn-008 | 执行力训练 | pdf | 执行力训练 | 聚焦按计划执行、止盈止损、假突破处理、等待机会、减少冲动和长期训练。 | 主要归入纪律训练、执行偏差和复盘标签，不转成交易触发。 | partial | SU_BING_SKILL.md; SU_BING_REVIEW_TAGS.md | extracted |
| sbn-009 | 交易心理 | pdf | 交易心理 | 聚焦亏损厌恶、成本执念、补仓冲动、杠杆压力、轻仓试错和心理账户。 | 主要归入心理偏差、风险认知和执行纪律，不转成交易触发。 | no | SU_BING_SKILL.md; SU_BING_REVIEW_TAGS.md | extracted |
| sbn-010 | 交易日志与复盘 | pdf | 交易日志与复盘 | 覆盖交易日志、计划、仓位、最大亏损、系统优化、反手条件和复盘记录要素。 | 可归入复盘字段、日志模板、执行检查和系统优化流程候选。 | partial | SU_BING_REVIEW_TAGS.md | extracted |
| sbn-011 | 交易反思 | pdf | 交易反思 | 围绕是否坚持系统、是否按信号与持仓原则执行、固定盈亏比和二次确认复盘。 | 可归入交易后检查、执行偏差、系统一致性和复盘问题清单候选。 | partial | SU_BING_REVIEW_TAGS.md | extracted |
| sbn-012 | 不同周期的交易策略 | pdf | 不同周期的交易策略 | 强调大周期定方向、小周期择时、多周期情绪描述、支撑压力和操作后处理问题。 | 可归入周期分层、方向过滤、择时观察和持仓后处理候选。 | partial | SU_BING_RULEBOOK.md | extracted |
| sbn-013 | 周期选择 | pdf | 周期选择 | 讨论均线周期、时空平衡、周期大小、共振条件、趋势反转和底部顶部判断。 | 可归入周期选择、均线周期、共振过滤和极端位置识别候选。 | partial | SU_BING_RULEBOOK.md | extracted |
| sbn-014 | 交易开平仓口诀 | pdf | 交易开平仓口诀 | 提供高度压缩的方向、指标、斜率、量能、周期共振、假突破和偏离约束口径。 | 只能作为人工规则化线索，不直接生成触发规则。 | needs_review | SU_BING_RULEBOOK.md | extracted |
| sbn-015 | 反人性的交易策略 | pdf | 反人性的交易策略 | 聚焦杠杆、人性弱点、结算周期、庄家思维、抄底摸顶冲动和趋势等待。 | 主要归入心理纪律、等待周期和风险认知，少量可进入 Skill 边界。 | partial | SU_BING_SKILL.md; SU_BING_REVIEW_TAGS.md | extracted |
| sbn-016 | 怎么抄底摸顶 | pdf | 怎么抄底摸顶 | 区分大周期估值底部和短期反弹，提到跌不动、空头平仓、消息刺激和均线附近平衡。 | 高风险主题，仅作为极端位置识别和人工复核线索，不生成触发规则。 | needs_review | SU_BING_RULEBOOK.md | extracted |
