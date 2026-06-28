# Su Bing JM V1-B Short Hold Strategy Spec

> 本文是基于 `su-bing-strategy` Skill 和 `STRATEGY_TARGET.md` 重新生成的独立 Strategy Spec。
> 本文不是旧 `su_bing_ema21` 的修复版，不是旧 `SU_BING_QUANT_SPEC_V0_1.md` 的续写版，也不授权直接写策略代码或直接下单。

## 1. strategy_code

- strategy_code: `su_bing_jm_v1b_short_hold`
- target_code: `su_bing_jm_v1b_short_hold`
- project_stage: `V1-B`
- strategy_stage: `strategy_spec`
- status: `light_review_passed_for_separate_implementation`
- generated_on: `2026-06-28`

## 2. strategy_name

- strategy_name: `苏冰 JM V1-B 短持有策略`
- display_name: `焦煤 JM 3 年真实数据短持有策略`
- research_goal: 在 V1-B 研究闭环内，验证苏冰课程规则候选在焦煤 JM 的 15m / 5m 短持有场景下是否具备可复盘的正期望。

## 3. strategy_version

- strategy_version: `v0.1.1-spec`
- version_type: `new_independent_spec`
- change_reason: 在 `v0.1.0-spec` 基础上固化未决参数，形成第一版可回测、低自由度、冻结参数的独立 Strategy Spec。
- legacy_boundary:
  - 不允许默认继承旧 `su_bing_ema21`。
  - 不默认继承旧 `su_bing_ema21` 的参数、周期、路径、测试或成交假设。
  - 不默认继承旧 `SU_BING_QUANT_SPEC_V0_1.md` 的工程默认值。
  - 旧材料如被后续引用，只能标记为 `history_draft`、`legacy_reference` 或 `engineering_reference`。

## 4. skill_source

- skill: `.agents/skills/su-bing-strategy/SKILL.md`
- generation_protocol: `.agents/skills/su-bing-strategy/references/STRATEGY_GENERATION_PROTOCOL.md`
- rulebook: `.agents/skills/su-bing-strategy/references/SU_BING_RULEBOOK.md`
- review_tags: `.agents/skills/su-bing-strategy/references/SU_BING_REVIEW_TAGS.md`
- strategy_target: `docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_TARGET.md`

Source separation:

- Course-derived rule candidates: `RULE-001` through `RULE-014` may seed direction, system, EMA21, MACD, entry, exit, risk, and review fields.
- Manual-review-only content: `RULE-015` through `RULE-018` may only enter discipline checks, review notes, or rejected-signal explanations.
- Post-trade review tags: `TAG-001` through `TAG-014` are post-trade diagnostics only.
- Current-spec decisions: JM, V1-B, recent 3-year data, 1d direction, 15m / 5m independent entries, frozen v0.1.1 parameters, 8-bar planned time exit, and bar execution assumptions are defined by this spec and `STRATEGY_TARGET.md`.

v0.1.1 frozen parameter summary:

| Field | v0.1.1 decision | Source type | Optimization status |
|---|---|---|---|
| trade_direction | `long_short` | current_spec_assumption | frozen for v0.1.1 |
| enabled_entry_setup | `pullback_only` | current_spec_assumption | frozen for v0.1.1 |
| breakout_breakdown_setup | `disabled` | current_spec_assumption | future version only |
| macd_usage | `record_only_not_filter` | course_candidate_boundary | future version only |
| pullback_lookback_bars | `3` completed entry bars including signal bar `t` | current_spec_assumption | frozen for v0.1.1 |
| pullback_interaction_distance | `1 * price_tick` from entry EMA21 | current_spec_assumption | frozen for v0.1.1 |
| max_entry_ema_distance | `8 * price_tick` at signal close | current_spec_assumption | frozen for v0.1.1 |
| stop_loss_model | signal bar extreme plus `1 * price_tick` | current_spec_assumption | frozen for v0.1.1 |
| max_initial_stop_distance | `30 * price_tick` | current_spec_assumption | frozen for v0.1.1 |
| take_profit_enabled | `true` | current_spec_assumption | frozen for v0.1.1 |
| take_profit_r_multiple | `1.5` | current_spec_assumption | frozen for v0.1.1 |
| planned_time_exit_bar | `8` completed holding bars | target_decision_refined | frozen for v0.1.1 |
| slippage | `1 * price_tick` per side | current_spec_assumption | frozen for v0.1.1 |
| account_equity_source | fixed backtest initial capital | current_spec_assumption | frozen for v0.1.1 |
| initial_capital | `1_000_000 CNY` | current_spec_assumption | frozen for v0.1.1 |
| risk_per_trade_ratio | `0.005` | current_spec_assumption | frozen for v0.1.1 |
| maximum_position | `1` contract | current_spec_assumption | frozen for v0.1.1 |
| max_entries_per_trading_day_per_interval | `2` | current_spec_assumption | frozen for v0.1.1 |
| max_drawdown_review_threshold | `10%` of initial capital | current_spec_assumption | review gate, not signal filter |
| max_consecutive_losses_review_threshold | `8` trades | current_spec_assumption | review gate, not signal filter |

## 5. data_scope

- data_source: `RQData / local standard parquet`
- data_role: `primary`
- quality_status: `passed`
- excluded_sources:
  - 天勤旧数据：只能作为 validation source，不能用于正式回测。
  - 交易练习者数据：只能作为 legacy_reference，不能用于正式回测。
  - `quality_status = failed` 的数据不得进入回测。
- date_range:
  - spec_window_start: `2023-06-28`
  - spec_window_end: `2026-06-28`
  - final_backtest_window: 以后续本地数据湖中可用且质量通过的交易日裁剪。
- required_fields:
  - datetime
  - open
  - high
  - low
  - close
  - volume
  - open_interest
  - symbol
  - contract_multiplier
  - price_tick
  - commission_rule
  - margin_rate
  - data_role
  - quality_status

## 6. symbol_scope

- product: `JM`
- symbol_family: 焦煤期货合约族。
- contract_universe: 由 RQData / local standard parquet 的主力映射和合约基础信息决定。
- contract_selection:
  - 回测不得直接交易抽象连续合约。
  - 如使用主力连续映射，只能用于确定每个交易时点对应的可交易具体合约。
  - 换月、主力切换和复权处理必须在数据中心或回测适配层显式记录。
- excluded_symbols:
  - 非 JM 品种。
  - 无交易参数、无合约乘数、无最小变动价位或手续费规则的数据。
  - 数据质量失败的合约区间。

## 7. interval_scope

- direction_interval: `1d`
- entry_intervals:
  - `15m`
  - `5m`
- independent_chains:
  - `15m` 入场链路独立生成信号、成交、交易明细和报告。
  - `5m` 入场链路独立生成信号、成交、交易明细和报告。
  - `15m` 和 `5m` 不得混用交易明细、入场结果或绩效结论。
- holding_window:
  - `15m`: 入场后持有 5-8 根 15m K线，除非止损、止盈或失效退出先触发。
  - `5m`: 入场后持有 5-8 根 5m K线，除非止损、止盈或失效退出先触发。
- multi_timeframe_alignment:
  - 小周期 K 线只能使用当时已经确认的日线方向。
  - 当日未完成日线不得用于过滤当日小周期信号。
  - 若交易时点属于某交易日 `D`，日线过滤只能使用 `D-1` 或更早已经收盘确认的日线。

## 8. daily_direction_filter

Rule sources: `RULE-003` 趋势判断、`RULE-004` EMA21 相关规则、`RULE-013` 周期选择。

Current-spec decision:

- indicator: daily `EMA21`
- available_daily_bar: 只使用已确认日线。
- long_direction_valid:
  - confirmed_daily_close > confirmed_daily_ema21
  - confirmed_daily_ema21 >= previous_confirmed_daily_ema21
- short_direction_valid:
  - confirmed_daily_close < confirmed_daily_ema21
  - confirmed_daily_ema21 <= previous_confirmed_daily_ema21
- neutral_direction:
  - 不满足 long 或 short 条件时，当日小周期入场信号全部降级为 `rejected_signal`。
- forbidden:
  - 不允许使用当前未收盘日线。
  - 不允许使用未来日线。
  - 不允许用回测结束后才知道的趋势结果反推当时方向。

## 9. entry_logic

Rule sources: `RULE-002` 交易系统层、`RULE-004` EMA21、`RULE-005` MACD 辅助判断、`RULE-006` 回调入场、`RULE-007` 突破入场、`RULE-008` 开仓过滤。

Shared entry rules:

- signal_bar: 当前已收盘的 `15m` 或 `5m` K 线，记为 bar `t`。
- fill_bar: 下一根同周期 K 线，记为 bar `t+1`。
- fill_price: bar `t+1` 的 open，加滑点后形成回测成交价。
- hard_forbidden:
  - 不允许使用未来 K 线生成入场信号。
  - 不允许使用 bar `t+1` 的 high / low / close 生成 bar `t` 的入场信号。
  - 不允许使用交易后 Review Tags、复盘 note 或人工复盘结论影响 bar `t` 的入场判断。

Long setup candidates:

- daily filter: `long_direction_valid = true`。
- entry bar context:
  - entry close > entry EMA21。
  - entry EMA21 >= previous entry EMA21。
  - MACD 仅记录为复盘和辅助观察字段，v0.1.1 不作为入场过滤或触发条件。
- pullback setup enabled in v0.1.1:
  - setup_type: `pullback`。
  - use the latest `3` completed entry-interval bars, including signal bar `t`。
  - price has interacted with entry EMA21 when the lowest low in this 3-bar window is <= the corresponding EMA21 reference plus `1 * price_tick`。
  - bar `t` closes back above entry EMA21.
  - bar `t` close must be no more than `8 * price_tick` above entry EMA21.
- breakout candidate:
  - status: `disabled_in_v0.1.1`。
  - bar `t` closes above a prior completed local resistance reference is retained only as a future rule candidate.
  - local resistance lookback: `not_used_in_v0.1.1`。
  - volume confirmation: `disabled_in_v0.1.1`。

Short setup candidates:

- daily filter: `short_direction_valid = true`。
- entry bar context:
  - entry close < entry EMA21。
  - entry EMA21 <= previous entry EMA21。
  - MACD 仅记录为复盘和辅助观察字段，v0.1.1 不作为入场过滤或触发条件。
- pullback setup enabled in v0.1.1:
  - setup_type: `pullback`。
  - use the latest `3` completed entry-interval bars, including signal bar `t`。
  - price has interacted with entry EMA21 when the highest high in this 3-bar window is >= the corresponding EMA21 reference minus `1 * price_tick`。
  - bar `t` closes back below entry EMA21.
  - bar `t` close must be no more than `8 * price_tick` below entry EMA21.
- breakdown candidate:
  - status: `disabled_in_v0.1.1`。
  - bar `t` closes below a prior completed local support reference is retained only as a future rule candidate.
  - local support lookback: `not_used_in_v0.1.1`。
  - volume confirmation: `disabled_in_v0.1.1`。

Entry state output:

- `entry_signal = long | short | none`
- `entry_reason = daily_direction + ema21_context + pullback_setup + distance_guard`
- `setup_type = pullback | rejected`
- `entry_interval = 15m | 5m`

## 10. exit_logic

Rule sources: `RULE-009` 平仓规则、`RULE-010` 止损规则、`RULE-011` 止盈规则、`RULE-017` 复盘规则。

Exit priority:

1. Stop loss.
2. Take profit.
3. Signal failure exit.
4. Time exit.

Signal failure exit:

- Long position:
  - completed bar closes below entry EMA21, or
  - daily direction no longer valid on the next confirmed daily update.
- Short position:
  - completed bar closes above entry EMA21, or
  - daily direction no longer valid on the next confirmed daily update.
- If signal failure is detected on bar `t`, exit order is filled at bar `t+1` open under the same bar execution assumption.

Same-bar conflict:

- If both stop loss and take profit are touched within the same bar under bar-level data, use conservative priority: stop loss first.
- This priority is a current-spec risk decision and must be recorded in backtest metadata.

## 11. stop_loss_logic

Rule sources: `RULE-010` 止损规则、`RULE-012` 资金管理。

Stop loss must be defined before entry.

Initial stop loss model for v0.1.1:

- Long:
  - initial_stop_price = signal bar `t` low - `1 * price_tick`。
- Short:
  - initial_stop_price = signal bar `t` high + `1 * price_tick`。

Frozen parameters:

- swing lookback bars: `not_used_in_v0.1.1`
- maximum stop distance: `30 * price_tick`; if abs(entry_price - initial_stop_price) > `30 * price_tick`, reject signal.
- ATR-based stop alternative: `disabled_in_v0.1.1`

Forbidden:

- Stop loss may not be moved farther away after entry.
- Stop loss may not use future high / low.
- Stop loss may not be overridden by心理纪律、复盘结论或 Review Tags。

## 12. take_profit_logic

Rule sources: `RULE-011` 止盈规则、`RULE-009` 平仓规则。

Take profit must be defined before entry if enabled.

Current-spec decision:

- take_profit_mode: `fixed_r_multiple`
- take_profit_enabled: `true`
- r_multiple: `1.5`

If take profit is enabled:

- Long take-profit price = entry_price + initial_risk_per_contract * r_multiple。
- Short take-profit price = entry_price - initial_risk_per_contract * r_multiple。
- Take profit may be checked only after entry fill.

Forbidden:

- 不允许使用事后最高浮盈生成止盈。
- 不允许使用未来 bar 的 high / low / close 决定入场前的止盈配置。
- 不允许因为 Review Tags 判断“止盈过早”而改写同一笔交易的原始出场。

## 13. time_exit_logic

Current-spec decision from `STRATEGY_TARGET.md`:

- 15m chain:
  - min_hold_bars: `5`
  - max_hold_bars: `8`
- 5m chain:
  - min_hold_bars: `5`
  - max_hold_bars: `8`

Execution:

- If no stop loss, take profit, or signal failure exit occurs, position exits by time rule.
- Earliest planned time exit check starts after 5 completed holding bars.
- Forced time exit occurs no later than after 8 completed holding bars.
- Time exit signal is confirmed on the completed holding bar and filled at the next bar open.

Planned time exit decision:

- v0.1.1 uses fixed planned exit at bar `8` if no stop loss, take profit, or signal failure exit has triggered earlier.
- No discretionary or performance-based exit is allowed between bar `5` and bar `8` in v0.1.1.
- The bar `5` lower bound is retained as V1-B target context and review metadata only; it is not an active exit trigger in v0.1.1.

## 14. risk_control

Rule sources: `RULE-001` 理念边界、`RULE-010` 止损、`RULE-012` 资金管理、`RULE-013` 周期选择。

Required risk fields:

- single_trade_initial_risk
- contract_multiplier
- price_tick
- commission
- slippage
- margin_rate
- max_drawdown
- max_consecutive_losses
- position_size
- exit_reason
- strategy_version

Risk constraints:

- Every trade must have an initial stop loss before entry.
- Every trade must be traceable to strategy version `v0.1.1-spec` or later approved version.
- Maximum drawdown review threshold: `10%` of initial capital; breach marks the report as `risk_review_required`, not as an intra-backtest signal filter.
- Maximum consecutive losses review threshold: `8` closed trades; breach marks the report as `risk_review_required`, not as an intra-backtest signal filter.
- Daily trade count limit: at most `2` entries per trading day per entry interval.
- Session filter / night-session handling:
  - include all exchange-valid JM day-session and night-session bars present in RQData / local standard parquet.
  - use the standard data lake trading-day assignment.
  - for any intraday bar assigned to trading day `D`, daily direction filter may use only confirmed daily bar `D-1` or earlier.
  - after exchange breaks, holidays, or night-to-day gaps, the next available same-interval bar open is the execution open under the same slippage rule.

Live boundary:

- V1-B 不做实盘，不自动下单，不接 CTP / TqSdk 交易接口。
- 不允许直接下单。
- Any generated signal is for research, backtest, review, or alerting only.

## 15. position_sizing

Rule sources: `RULE-012` 资金管理。

Position sizing policy:

- position_sizing_mode: `risk_per_trade`
- account_equity_source: fixed backtest initial capital.
- initial_capital: `1_000_000 CNY`
- risk_per_trade_ratio: `0.005`
- minimum_position: `0`
- maximum_position: `1` contract

Formula candidate:

```text
initial_risk_per_contract =
  abs(entry_price - initial_stop_price) * contract_multiplier
  + estimated_commission
  + estimated_slippage

position_size =
  floor(account_equity * risk_per_trade_ratio / initial_risk_per_contract)
```

Guards:

- If `initial_risk_per_contract <= 0`, reject signal.
- If position size is 0 after flooring and maximum-position cap, reject signal.
- If margin requirement exceeds available capital assumption, reject signal.
- Position size must not be chosen independently from stop distance.

## 16. bar_execution_assumption

Backtest engine target:

- engine: `vn.py / VeighNa CTA BacktestingEngine`
- adapter_boundary: 归一量化自定义 Adapter / Runner / ResultConverter，后续实现任务另行授权。

Signal and fill timing:

- 当前 K 线收盘确认信号。
- 下一根 K 线开盘成交。
- Signal bar `t` may use only bar `t` and earlier completed bars.
- Fill bar `t+1` open is used only for execution price after the signal already exists.
- Fill bar `t+1` high / low / close must not be used to create the entry signal.

Order assumption:

- order_type: market-on-next-bar-open in backtest.
- gap handling: if next open gaps beyond stop or take-profit reference, fill at next open plus slippage and record `gap_execution = true`。
- same-bar stop/take-profit conflict after entry: conservative stop-loss-first policy.

## 17. slippage / commission / price_tick

Source:

- Prefer RQData / local standard parquet trading parameters.
- If local trading parameters are missing, the backtest must fail fast instead of silently using zero cost or asking the implementation to invent defaults.

Required assumptions:

- price_tick: from contract metadata.
- contract_multiplier: from contract metadata.
- commission: from local trading parameter table or RQData-derived standard field.
- margin_rate: from local trading parameter table or RQData-derived standard field.
- slippage:
  - fixed v0.1.1 assumption: `1 * price_tick` per side.
  - entry long fill = next open + `1 * price_tick`; entry short fill = next open - `1 * price_tick`。
  - exit long fill = execution price - `1 * price_tick`; exit short fill = execution price + `1 * price_tick`。

Forbidden:

- 不允许手续费默认为 0。
- 不允许滑点默认为 0，除非审查任务明确批准。
- 不允许缺少合约乘数或 price_tick 仍继续正式回测。

## 18. rejected_signal_rules

Reject a signal when any condition is true:

- Daily direction is neutral or opposite.
- Data quality is not `passed`。
- Data role is not `primary`。
- Entry interval is not `15m` or `5m`。
- Current bar is not closed.
- Required daily bar is not confirmed.
- Entry would require future K-line information.
- Entry would require next bar high / low / close.
- Stop loss is missing.
- Commission, price_tick, contract_multiplier, or margin_rate is missing.
- Position size is 0.
- Maximum risk constraint is violated.
- Signal comes from Review Tags, manual review, post-trade note, psychological label, old strategy code, or old spec default.
- Setup belongs to manual-review-only content from `RULE-015` through `RULE-018` and has not been converted through a separately reviewed spec version.

Rejected signal output:

- `rejected_reason`
- `rule_source`
- `bar_datetime`
- `entry_interval`
- `daily_direction_state`
- `decision_status = frozen_v0.1.1 | rejected_by_guardrail | missing_required_data`

## 19. review_tags_mapping

Review Tags are post-trade only.

Fixed tag semantics:

- `is_post_trade_only = true`
- `can_affect_same_trade_signal = false`
- `can_affect_future_version = review_required`

Mapping:

- `TAG-001` 趋势判断: maps to daily direction and interval alignment review.
- `TAG-002` EMA21 位置: maps to EMA21 entry/exit context review.
- `TAG-003` MACD 共振: maps to auxiliary confirmation review.
- `TAG-004` 回调质量: maps to pullback setup review.
- `TAG-005` 突破质量: maps to breakout/breakdown setup review.
- `TAG-006` 是否追高追空: maps to entry distance and impulse review.
- `TAG-007` 是否逆势: maps to daily filter violation review.
- `TAG-008` 是否震荡误入: maps to market regime and filter review.
- `TAG-009` 是否偏离 EMA21 过远: maps to EMA21 distance review.
- `TAG-010` 是否止损合理: maps to stop-loss and initial risk review.
- `TAG-011` 是否止盈过早: maps to take-profit and exit discipline review.
- `TAG-012` 是否执行纪律: maps to manual execution review only.
- `TAG-013` 是否符合资金管理: maps to position sizing and margin review.
- `TAG-014` 是否规则外交易: maps to strategy-version traceability review.

Forbidden:

- 不允许 review tags 反向影响当时交易决策。
- 不允许 Review Tags 反向影响当时交易决策。
- 不允许 `TAG-*` 进入同一时点 `on_bar` 的入场、出场、过滤、加仓、减仓或反手判断。
- 不允许用复盘 note 修正同一笔交易的原始信号。

## 20. not_implemented_in_v0_1_1

The following are explicitly not implemented or not authorized in this spec:

- Strategy code implementation.
- Backtest runner implementation.
- API implementation.
- Web implementation.
- Database migration.
- Live trading.
- Direct order placement.
- CTP / TqSdk trading interface.
- Tick-level high-frequency backtest.
- Complex order-book queue matching.
- AI-generated rules that directly run without review.
- Parameter brute-force optimization followed by all-sample acceptance.
- Default inheritance from old `su_bing_ema21`。
- Default inheritance from old `SU_BING_QUANT_SPEC_V0_1.md`。

## 21. future_function_guardrails

Hard rules:

- Only current and past completed bars may be used for signal generation.
- 当前 K 线收盘确认信号。
- 下一根 K 线开盘成交。
- 不允许使用未来 K 线。
- 不允许使用下一根 K 线 high / low / close 生成入场信号。
- 当前未完成日线不得过滤小周期信号。
- Stop loss, take profit, and time exit must be derived from information available at or before the signal confirmation time.

Tests required:

- Shift all entry signals by one bar and verify fills occur only on next open.
- Assert no entry field reads `t+1.high`、`t+1.low` or `t+1.close`。
- Assert daily filter for intraday bar uses only previous confirmed daily bar.

## 22. data_leakage_guardrails

Hard rules:

- Review Tags, manual review conclusions, trade notes, and report conclusions must not feed back into same-trade signal logic.
- Full-sample statistics must not be used to decide entry thresholds for the same sample.
- Contract rollover mapping must be timestamp-aware.
- Data from excluded sources must not enter formal backtest.
- Trade result, MFE, MAE, final PnL, max favorable excursion, or max adverse excursion must not be used to decide the original exit.

Tests required:

- Verify features are computed with left-closed historical windows only.
- Verify tags are written after trade close or for review records, not before entry.
- Verify data filters require `data_role = primary` and `quality_status = passed`。

## 23. overfitting_guardrails

Hard rules:

- No all-sample parameter optimization may be used as final acceptance.
- Frozen v0.1.1 parameters must be used as written; any parameter change must create a new spec or parameter version before implementation.
- 15m and 5m chains must be evaluated separately.
- Any parameter change must create a new strategy version or parameter version.
- Backtest reports must show at least net PnL, drawdown, win rate, profit factor, average trade, max consecutive losses, trade count, fee, slippage, and symbol/interval contribution.

Validation plan:

- Use chronological split: train/design window, validation window, and final holdout window.
- Require sensitivity check around key parameters once they are approved.
- Reject results that depend on one or two extreme trades without stable broader behavior.
- Document failed variants instead of only preserving the best result.

## 24. test_plan

Spec-level tests:

- Check all required fields in this Strategy Spec are present.
- Check no unresolved `requires_user_decision` or `requires_spec_decision` fields remain in this Strategy Spec before implementation.
- Check no old `su_bing_ema21` parameter is referenced as default.

Data tests:

- Validate JM data exists for the selected 3-year window after local data-quality filtering.
- Validate all bars used by backtest have `data_role = primary` and `quality_status = passed`。
- Validate contract metadata includes multiplier, price_tick, commission, margin, and trading calendar alignment.

Signal tests:

- Verify daily direction uses only confirmed daily bars.
- Verify 15m and 5m signals are generated independently.
- Verify signal bar close creates the signal and next bar open creates the fill.
- Verify no entry signal uses future high / low / close.
- Verify rejected signals record reasons.

Execution tests:

- Verify stop loss is defined before entry.
- Verify stop-loss-first same-bar conflict policy.
- Verify commission and slippage are included.
- Verify time exit triggers no later than 8 completed holding bars.
- Verify Review Tags are written only after trade completion or in review workflows.

Review tests:

- Verify each trade can create a review note.
- Verify K-line markers can trace entry, exit, stop loss, take profit, interval, strategy version, and review tags.
- Verify report can be archived to PostgreSQL only after a separately authorized implementation task.

## 25. implementation_file_plan

This section is a future implementation plan only. It does not authorize code changes.

Allowed only after separate approval:

- Strategy implementation candidate:
  - `packages/quant-core/src/guiyi_quant/strategies/su_bing_jm_v1b_short_hold.py`
- Strategy config candidate:
  - `configs/strategies/su_bing_jm_v1b_short_hold.yaml`
- Backtest adapter / runner candidate:
  - `packages/quant-core/src/guiyi_quant/backtest/`
- Report conversion candidate:
  - `packages/quant-core/src/guiyi_quant/reports/`
- API candidate:
  - `services/quant-api/`
- Web candidate:
  - `apps/quant-web/`
- Tests candidate:
  - `tests/`

Files not authorized by this spec-generation task:

- Strategy code.
- Backtest code.
- API code.
- Web code.
- Database migration.
- Live trading code.
- `private_sources/`
- `.env` or any file containing账号、密码、API Key、token、license。

Implementation prerequisites:

- Confirm `STRATEGY_SPEC_REVIEW.md` records a passing light review for `v0.1.1-spec`.
- Use frozen v0.1.1 parameters exactly as written unless a later reviewed spec version changes them.
- Obtain explicit user approval for allowed modification files before writing code.
