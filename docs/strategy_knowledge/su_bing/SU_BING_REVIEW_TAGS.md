# SU_BING_REVIEW_TAGS

## Purpose

This document defines the Su Bing strategy review tag system for Guiyi Quant trade-detail review.

The tags are derived from `SU_BING_RULEBOOK.md` and are intended for reviewing backtest trades, simulated trades, and manually recorded trades. They do not contain course text, executable strategy logic, trade signals, buy/sell points, backtest code, or live trading instructions.

## Boundaries

- Use tags to explain a completed trade, not to generate a new trade.
- Apply tags at the trade-detail level with strategy version, symbol, period, direction, entry reason, exit reason, stop-loss, take-profit, and PnL context.
- Treat quantizable tags as review fields or post-trade diagnostics only; do not feed them back into signal generation without a separately reviewed rule update.
- Do not copy Notion source text or infer unprovided thresholds.

## Severity Scale

- low: Observation or context label.
- medium: Review warning that may affect trade quality.
- high: Clear rule, risk, or execution problem.
- critical: Severe out-of-system behavior or risk-control violation.

## TAG-001：趋势判断

- category: trend
- description: 标记该笔交易是否有明确的大周期方向、小周期择时和趋势/震荡判断依据。
- trigger_condition: 复盘成交明细时，检查入场记录是否说明趋势方向、周期职责、趋势延续或趋势失败背景。
- severity: medium
- applicable_to: entry_review / trade_context / backtest_trade_detail
- example_review_sentence: 本笔交易入场前有大周期方向说明，但趋势失败条件仍待补充。
- quantizable: partial

## TAG-002：EMA21 位置

- category: ema21
- description: 标记入场、持仓或出场时价格与 EMA21 的关系是否被记录，包括方向、回踩、突破、斜率和偏离。
- trigger_condition: 复盘成交明细时，检查交易记录是否包含 EMA21 方向和价格相对 EMA21 的位置描述。
- severity: medium
- applicable_to: entry_review / exit_review / kline_marker_review
- example_review_sentence: 本笔交易记录了价格位于 EMA21 附近，但没有补充斜率和确认 bar。
- quantizable: partial

## TAG-003：MACD 共振

- category: macd
- description: 标记 MACD 是否作为趋势、入场或过滤的辅助确认，而不是单独开仓依据。
- trigger_condition: 复盘成交明细时，检查 MACD 方向、确认、背离或失效记录是否与趋势和 EMA21 背景一致。
- severity: medium
- applicable_to: entry_review / filter_review / signal_review
- example_review_sentence: 本笔交易有 MACD 辅助确认，但未说明 MACD 失效后的处理方式。
- quantizable: partial

## TAG-004：回调质量

- category: pullback_entry
- description: 标记回调入场是否具备方向背景、回调位置、确认信号、失效条件和止损参照。
- trigger_condition: 交易以回调为入场理由时，检查是否仅因接近均线或支撑压力而入场。
- severity: high
- applicable_to: entry_review / setup_quality / backtest_trade_detail
- example_review_sentence: 本笔回调入场有方向背景，但确认信号和止损参照待补充。
- quantizable: partial

## TAG-005：突破质量

- category: breakout_entry
- description: 标记突破入场是否检查方向、指标确认、量能、震荡区间和假突破风险。
- trigger_condition: 交易以突破为入场理由时，检查突破有效性是否用当时可见信息确认。
- severity: high
- applicable_to: entry_review / setup_quality / backtest_trade_detail
- example_review_sentence: 本笔突破入场记录了方向和量能观察，但突破确认方式待补充。
- quantizable: partial

## TAG-006：是否追高追空

- category: entry_error
- description: 标记入场是否存在冲动追逐、价格偏离过大或没有等待回调/确认的行为。
- trigger_condition: 入场发生在快速上涨后追多、快速下跌后追空，且记录中缺少回调、确认或风险约束。
- severity: high
- applicable_to: entry_review / error_tag / execution_review
- example_review_sentence: 本笔交易存在追高追空嫌疑，入场理由没有说明等待确认过程。
- quantizable: partial

## TAG-007：是否逆势

- category: trend_error
- description: 标记交易方向是否与已记录的大周期方向、趋势过滤或系统方向相冲突。
- trigger_condition: 复盘时发现交易方向和大周期方向不一致，且没有明确的人工复核理由。
- severity: high
- applicable_to: entry_review / trend_review / error_tag
- example_review_sentence: 本笔交易方向与大周期判断相反，应标记为逆势交易待复核。
- quantizable: partial

## TAG-008：是否震荡误入

- category: market_regime_error
- description: 标记交易是否发生在应回避或降频的震荡环境中。
- trigger_condition: 入场前已有震荡区间、趋势不清或过滤条件不足，但交易仍按趋势或突破逻辑入场。
- severity: high
- applicable_to: entry_review / filter_review / market_context_review
- example_review_sentence: 本笔交易疑似震荡误入，趋势过滤和震荡识别条件都未说明。
- quantizable: partial

## TAG-009：是否偏离 EMA21 过远

- category: ema21_error
- description: 标记入场时价格是否相对 EMA21 偏离过大，导致追价、盈亏比不足或止损不合理。
- trigger_condition: 入场理由依赖 EMA21，但成交价格与 EMA21 关系记录显示偏离风险，且缺少人工复核说明。
- severity: medium
- applicable_to: entry_review / risk_review / ema21_review
- example_review_sentence: 本笔入场距离 EMA21 偏远，偏离阈值待补充，先标记为风险观察。
- quantizable: partial

## TAG-010：是否止损合理

- category: stop_loss
- description: 标记止损是否在开仓前定义，并与最大可承受亏损、仓位、止损参照和不利行情处理一致。
- trigger_condition: 复盘成交明细时，检查是否存在未设止损、止损后移、止损过大、止损过小或止损依据缺失。
- severity: critical
- applicable_to: risk_review / exit_review / backtest_trade_detail
- example_review_sentence: 本笔交易有止损记录，但止损参照和单笔风险比例待补充。
- quantizable: partial

## TAG-011：是否止盈过早

- category: take_profit
- description: 标记出场是否偏离原计划，过早止盈、未遵守固定盈亏比或未说明盈利保护规则。
- trigger_condition: 盈利出场发生在持仓依据仍有效时，或复盘记录显示人工提前平仓但缺少计划内原因。
- severity: medium
- applicable_to: exit_review / execution_review / pnl_review
- example_review_sentence: 本笔交易疑似止盈过早，出场记录未说明固定盈亏比或信号失败依据。
- quantizable: partial

## TAG-012：是否执行纪律

- category: execution_discipline
- description: 标记交易是否按计划、信号、持仓原则、止盈止损和等待确认执行。
- trigger_condition: 复盘发现未按计划、冲动交易、看到信号没做、未等待确认、假突破处理偏差或人工提前干预。
- severity: high
- applicable_to: execution_review / error_tag / manual_review
- example_review_sentence: 本笔交易未完全按计划执行，等待确认和止损处理均需要复盘。
- quantizable: no

## TAG-013：是否符合资金管理

- category: risk_management
- description: 标记交易是否符合仓位、最大可承受亏损、隔夜风险、回撤控制和资金约束。
- trigger_condition: 复盘成交明细时，检查仓位是否脱离止损距离、账户风险或行情环境单独设定。
- severity: critical
- applicable_to: risk_review / position_review / backtest_trade_detail
- example_review_sentence: 本笔交易仓位依据不完整，无法确认是否符合资金管理要求。
- quantizable: partial

## TAG-014：是否规则外交易

- category: out_of_system
- description: 标记交易是否缺少策略版本、入场理由、过滤条件、风控依据或复盘所需字段。
- trigger_condition: 交易无法追溯到规则库、策略版本或计划内信号，或明显由心理冲动、抄底摸顶、补仓冲动驱动。
- severity: critical
- applicable_to: trade_review / error_tag / strategy_version_review
- example_review_sentence: 本笔交易缺少可追溯的策略版本和入场规则，应标记为规则外交易。
- quantizable: partial
