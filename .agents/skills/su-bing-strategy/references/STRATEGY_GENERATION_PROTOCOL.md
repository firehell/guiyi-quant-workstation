# STRATEGY_GENERATION_PROTOCOL

## Purpose

This protocol defines how to use the `su-bing-strategy` Skill to generate a new strategy specification.

The Skill provides Su Bing course knowledge, rule candidates, review tags, and safety boundaries. It does not provide a default executable strategy. Every real strategy must be generated as a new, independent Strategy Spec for the current target.

Old `su_bing_ema21` materials are not a default strategy. Old specs, old code, old tests, old parameters, old timeframes, and old implementation paths may only be cited as historical or engineering references after the new Strategy Spec explicitly says why they are relevant.

## Required Inputs

Before generating any Strategy Spec, collect and record the current strategy target:

- 品种：specific product, symbol family, or contract universe.
- 数据范围：start date, end date, source, data role, and quality requirements.
- 周期：direction timeframe, entry timeframe, exit timeframe, and any multi-timeframe alignment rule.
- 持有周期：maximum, minimum, or rule-based holding period.
- 交易方向：long only, short only, long/short, or observation only.
- 风控约束：single-trade risk, stop-loss boundary, drawdown boundary, position sizing, margin, commission, slippage, and contract multiplier assumptions.
- 回测引擎：engine name and version boundary, such as vn.py / VeighNa CTA BacktestingEngine if explicitly chosen.
- 成交假设：signal timing, fill timing, order type, bar-level stop/take-profit policy, gap handling, and same-bar conflict handling.
- 禁止事项：disallowed data, disallowed rules, disallowed interfaces, and implementation boundaries.

If any required input is missing, mark it as `requires_user_decision` or `requires_spec_decision`. Do not fill it from old strategy code, old reports, or archived specs.

Do not generate a Strategy Spec by repairing `SU_BING_QUANT_SPEC_V0_1.md` or by continuing old `su_bing_ema21`. Start from the current target, then choose which Rulebook candidates are allowed to seed the new spec.

## Source Rules

- Use course MD / Notion-derived summaries as the source of Su Bing knowledge.
- Use Rulebook entries only as course rule candidates.
- Use Review Tags only as review and post-trade diagnostic candidates.
- Do not treat old strategy code as a rule source.
- Do not treat old `SU_BING_QUANT_SPEC_V0_1.md` as a default Strategy Spec.
- Do not inherit old Su Bing strategy behavior unless the current Strategy Spec explicitly chooses and justifies it.
- Treat old `su_bing_ema21` only as `history_draft`, `legacy_reference`, or `engineering_reference`.
- Do not use old implementation paths, tests, parameters, timeframes, holding periods, or fill assumptions as default requirements.
- Use private source material only to produce short summaries, abstract rule candidates, quantization status, and manual-review status. Do not copy original course text, long passages, screenshots, or image-only case content into the generated spec.

## Output Requirements

The output must be an independent Strategy Spec. It must include:

- Strategy identity and version.
- Current target and scope.
- Data source and data quality requirements.
- Timeframes and bar alignment rules.
- Entry, exit, stop-loss, take-profit, holding-period, and filter rules.
- Risk, fee, slippage, contract multiplier, and margin assumptions.
- Signal timing and execution timing.
- Backtest engine and result fields.
- Review tags and trade-note requirements.
- Future-function, data-leakage, and overfitting checks.
- Explicit list of assumptions and unresolved decisions.

The Strategy Spec must clearly separate:

- Course-derived rule candidates.
- Current-task design decisions.
- Engineering defaults.
- Manual-review-only content.
- Post-trade review tags.
- Historical draft references.
- Legacy or engineering references.

## Review Gate

A Strategy Spec must be reviewed before code implementation.

The review must check:

- No future functions.
- No data leakage.
- No all-sample optimization used as final acceptance.
- No subjective content directly converted into buy/sell signals.
- Signal time and fill time are separated.
- Commission, slippage, contract multiplier, and margin assumptions are explicit.
- Stop-loss, take-profit, and holding-period exits are executable under the chosen backtest engine.
- Review tags do not feed back into same-time signal generation.
- Review tags, manual-review conclusions, and post-trade notes are not used as entry, exit, filter, add, reduce, reverse, or same-bar `on_bar` conditions.
- V1 does not include fully automated live trading.
- Strategy version is recorded and traceable.

Only after the Strategy Spec passes review may a separate implementation task modify strategy code, backtest code, API code, Web code, or database schema.

Passing this protocol only allows a Strategy Spec draft and review. It does not authorize code implementation.

## Version Rules

- Every Strategy Spec must have a strategy code, strategy version, data range, parameter summary, and change reason.
- Every rule change must create a new version or parameter version.
- Archived specs can be cited as historical examples, but cannot be used as default implementation requirements.
- Old `su_bing_ema21` references must be labeled as `history_draft`, `legacy_reference`, or `engineering_reference` wherever they appear.
- Backtest reports, trade details, K-line markers, and review notes must trace back to the exact strategy version used.

## Live Trading Boundary

V1 does not do fully automated live trading.

Any signal generated from a future Strategy Spec is for research, review, backtesting, or alerting unless a later project phase explicitly defines a manually confirmed live-trading workflow.
