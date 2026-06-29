# BACKTEST_REVIEW_CONTEXT: su_bing_jm_v1b_short_hold

## 1. 策略来源

- 策略来源：`su-bing-strategy` Skill。
- Strategy Spec: `docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md`。
- 本策略是独立 V1-B 策略，不继承旧 `su_bing_ema21` 的参数、路径、测试或成交假设。

## 2. 策略版本

- strategy_code: `su_bing_jm_v1b_short_hold`
- strategy_version: `v0.1.1-spec`
- project_stage: `V1-B`
- entry setup: `pullback_only`
- disabled in this version: breakout / breakdown / volume confirmation / MACD filter
- holding rule: planned time exit at bar 8 unless stop loss, take profit, or signal failure exits first

## 3. 回测数据范围

- Spec target window: `2023-06-28` -> `2026-06-28`
- Actual local primary/passed data window used: `2023-06-28T00:00:00` -> `2025-12-31T15:00:00`
- Coverage gap: local primary/passed JM data did not cover `2026-01-01` -> `2026-06-28`; no synthetic or replacement data was used.
- Product: JM 焦煤。
- Research contract: `jm.MAIN`; trades are enriched to concrete JM contracts through main-contract mapping.

## 4. 数据角色

- data_source: `local_parquet` from RQData standard parquet chain.
- data_role: `primary`
- quality_status: `passed`
- Excluded: `legacy_reference`, validation source, failed quality data, live data, TqSdk formal backtest data.

## 5. 15m 结果摘要

| metric | value |
| --- | --- |
| report_id | 7 |
| report_no | BTV-20260628150010-7c9669a8-RPT-40a06e67 |
| strategy_version | v0.1.1-spec |
| data_role / quality | primary / passed |
| window | 2023-06-28T00:00:00+00:00 -> 2025-12-31T15:00:00+00:00 |
| initial_capital | 1,000,000.00 |
| final_equity | 881,975.90 |
| total_return | -11.80% |
| annual_return | -4.87% |
| max_drawdown_pct | 11.80% |
| trade_count | 763 |
| win_rate | 29.75% |
| profit_loss_ratio | 0.992 |
| expectancy | -154.68 |
| max_consecutive_losses | 11 |
| gross_pnl | -50,910.00 |
| net_pnl | -118,024.10 |
| commission | 21,334.10 |
| slippage | 45,780.00 |
| cost / abs(gross_pnl) | 131.83% |
| rejected_signals | 11379 |

## 6. 5m 结果摘要

| metric | value |
| --- | --- |
| report_id | 8 |
| report_no | BTV-20260628150041-a1170dbc-RPT-8aab365d |
| strategy_version | v0.1.1-spec |
| data_role / quality | primary / passed |
| window | 2023-06-28T00:00:00+00:00 -> 2025-12-31T15:00:00+00:00 |
| initial_capital | 1,000,000.00 |
| final_equity | 815,706.22 |
| total_return | -18.43% |
| annual_return | -7.78% |
| max_drawdown_pct | 18.43% |
| trade_count | 1186 |
| win_rate | 25.72% |
| profit_loss_ratio | 0.788 |
| expectancy | -155.39 |
| max_consecutive_losses | 19 |
| gross_pnl | -79,020.00 |
| net_pnl | -184,293.78 |
| commission | 34,113.78 |
| slippage | 71,160.00 |
| cost / abs(gross_pnl) | 133.22% |
| rejected_signals | 36982 |

## 7. 主要亏损交易特征

### 15m Top Losses

| trade_no | direction | contract | open_time | close_time | exit_reason | hold_bars | net_pnl | cost | entry_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SB-JM-218 | long | JM2409 | 2024-04-16T21:15:00+00:00 | 2024-04-16T21:15:00+00:00 | stop_loss | 1 | -1,001.65 | 101.65 | daily_long_ema21_pullback_distance_guard |
| SB-JM-76 | long | JM2401 | 2023-09-28T13:45:00+00:00 | 2023-10-09T09:15:00+00:00 | stop_loss | 7 | -981.98 | 81.98 | daily_long_ema21_pullback_distance_guard |
| SB-JM-123 | short | JM2401 | 2023-12-05T14:30:00+00:00 | 2023-12-05T21:15:00+00:00 | stop_loss | 4 | -948.17 | 108.17 | daily_short_ema21_pullback_distance_guard |
| SB-JM-248 | long | JM2409 | 2024-05-23T09:30:00+00:00 | 2024-05-23T09:30:00+00:00 | stop_loss | 1 | -943.01 | 103.01 | daily_long_ema21_pullback_distance_guard |
| SB-JM-121 | long | JM2401 | 2023-11-28T23:00:00+00:00 | 2023-11-29T09:45:00+00:00 | stop_loss | 4 | -895.53 | 85.53 | daily_long_ema21_pullback_distance_guard |
| SB-JM-633 | long | JM2601 | 2025-08-20T21:15:00+00:00 | 2025-08-20T21:15:00+00:00 | stop_loss | 1 | -890.87 | 80.87 | daily_long_ema21_pullback_distance_guard |
| SB-JM-128 | short | JM2405 | 2023-12-15T10:15:00+00:00 | 2023-12-15T10:15:00+00:00 | stop_loss | 1 | -886.12 | 106.12 | daily_short_ema21_pullback_distance_guard |
| SB-JM-174 | short | JM2405 | 2024-02-05T09:30:00+00:00 | 2024-02-05T09:30:00+00:00 | stop_loss | 1 | -881.31 | 101.31 | daily_short_ema21_pullback_distance_guard |

### 5m Top Losses

| trade_no | direction | contract | open_time | close_time | exit_reason | hold_bars | net_pnl | cost | entry_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SB-JM-977 | long | JM2509 | 2025-07-25T22:05:00+00:00 | 2025-07-25T22:10:00+00:00 | stop_loss | 2 | -765.15 | 75.15 | daily_long_ema21_pullback_distance_guard |
| SB-JM-978 | long | JM2509 | 2025-07-28T22:45:00+00:00 | 2025-07-28T22:55:00+00:00 | signal_failure_exit | 2 | -762.93 | 72.93 | daily_long_ema21_pullback_distance_guard |
| SB-JM-374 | long | JM2409 | 2024-04-12T23:00:00+00:00 | 2024-04-15T09:05:00+00:00 | stop_loss | 2 | -710.52 | 80.52 | daily_long_ema21_pullback_distance_guard |
| SB-JM-195 | long | JM2401 | 2023-11-23T11:10:00+00:00 | 2023-11-23T11:10:00+00:00 | stop_loss | 1 | -707.83 | 107.83 | daily_long_ema21_pullback_distance_guard |
| SB-JM-225 | short | JM2405 | 2023-12-15T09:20:00+00:00 | 2023-12-15T09:25:00+00:00 | stop_loss | 2 | -706.09 | 106.09 | daily_short_ema21_pullback_distance_guard |
| SB-JM-419 | long | JM2409 | 2024-05-22T22:40:00+00:00 | 2024-05-22T23:00:00+00:00 | stop_loss | 5 | -703.37 | 103.37 | daily_long_ema21_pullback_distance_guard |
| SB-JM-292 | short | JM2405 | 2024-02-05T09:10:00+00:00 | 2024-02-05T09:25:00+00:00 | signal_failure_exit | 3 | -701.29 | 101.29 | daily_short_ema21_pullback_distance_guard |
| SB-JM-1138 | short | JM2601 | 2025-11-26T21:10:00+00:00 | 2025-11-26T21:10:00+00:00 | stop_loss | 1 | -679.51 | 79.51 | daily_short_ema21_pullback_distance_guard |

## 8. 主要盈利交易特征

### 15m Top Wins

| trade_no | direction | contract | open_time | close_time | exit_reason | hold_bars | net_pnl | cost | entry_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SB-JM-625 | long | JM2601 | 2025-08-06T22:00:00+00:00 | 2025-08-06T22:45:00+00:00 | take_profit | 4 | 1,200.33 | 74.67 | daily_long_ema21_pullback_distance_guard |
| SB-JM-257 | short | JM2409 | 2024-05-30T09:45:00+00:00 | 2024-05-30T09:45:00+00:00 | take_profit | 1 | 1,128.93 | 101.07 | daily_short_ema21_pullback_distance_guard |
| SB-JM-78 | short | JM2401 | 2023-10-11T11:15:00+00:00 | 2023-10-11T14:00:00+00:00 | take_profit | 4 | 993.16 | 101.84 | daily_short_ema21_pullback_distance_guard |
| SB-JM-334 | short | JM2501 | 2024-08-16T13:45:00+00:00 | 2024-08-16T14:30:00+00:00 | take_profit | 4 | 957.57 | 92.43 | daily_short_ema21_pullback_distance_guard |
| SB-JM-148 | short | JM2405 | 2024-01-10T21:30:00+00:00 | 2024-01-10T21:30:00+00:00 | take_profit | 1 | 948.00 | 102.00 | daily_short_ema21_pullback_distance_guard |
| SB-JM-229 | long | JM2409 | 2024-04-24T21:30:00+00:00 | 2024-04-24T22:00:00+00:00 | take_profit | 3 | 946.93 | 103.07 | daily_long_ema21_pullback_distance_guard |
| SB-JM-105 | long | JM2401 | 2023-11-09T14:15:00+00:00 | 2023-11-09T14:30:00+00:00 | take_profit | 2 | 942.66 | 107.34 | daily_long_ema21_pullback_distance_guard |
| SB-JM-42 | long | JM2401 | 2023-08-11T21:15:00+00:00 | 2023-08-11T21:15:00+00:00 | take_profit | 1 | 910.87 | 94.13 | daily_long_ema21_pullback_distance_guard |

### 5m Top Wins

| trade_no | direction | contract | open_time | close_time | exit_reason | hold_bars | net_pnl | cost | entry_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SB-JM-189 | long | JM2401 | 2023-11-17T21:15:00+00:00 | 2023-11-17T21:25:00+00:00 | take_profit | 3 | 850.46 | 109.54 | daily_long_ema21_pullback_distance_guard |
| SB-JM-215 | long | JM2401 | 2023-12-06T22:20:00+00:00 | 2023-12-06T22:35:00+00:00 | take_profit | 4 | 806.75 | 108.25 | daily_long_ema21_pullback_distance_guard |
| SB-JM-402 | long | JM2409 | 2024-05-09T09:55:00+00:00 | 2024-05-09T10:40:00+00:00 | take_profit | 7 | 767.15 | 102.85 | daily_long_ema21_pullback_distance_guard |
| SB-JM-430 | short | JM2409 | 2024-05-30T10:40:00+00:00 | 2024-05-30T10:45:00+00:00 | take_profit | 2 | 723.78 | 101.22 | daily_short_ema21_pullback_distance_guard |
| SB-JM-216 | long | JM2405 | 2023-12-07T22:00:00+00:00 | 2023-12-07T22:15:00+00:00 | take_profit | 4 | 716.55 | 108.45 | daily_long_ema21_pullback_distance_guard |
| SB-JM-199 | long | JM2401 | 2023-11-24T22:05:00+00:00 | 2023-11-24T22:40:00+00:00 | take_profit | 8 | 715.01 | 109.99 | daily_long_ema21_pullback_distance_guard |
| SB-JM-97 | long | JM2401 | 2023-09-01T21:30:00+00:00 | 2023-09-01T21:40:00+00:00 | take_profit | 3 | 680.61 | 99.39 | daily_long_ema21_pullback_distance_guard |
| SB-JM-975 | long | JM2509 | 2025-07-24T22:20:00+00:00 | 2025-07-24T22:50:00+00:00 | take_profit | 7 | 660.21 | 74.79 | daily_long_ema21_pullback_distance_guard |

## 9. 最大回撤区间

| interval | dd_start | dd_end | max_dd_amount | max_dd_pct | source_trade_id |
| --- | --- | --- | --- | --- | --- |
| 15m | initial_capital / backtest_start | 2025-12-31T09:15:00+00:00 | 118,024.10 | 11.80% | SB-JM-763 |
| 5m | initial_capital / backtest_start | 2025-12-30T22:30:00+00:00 | 184,293.78 | 18.43% | SB-JM-1186 |

## 10. 连亏区间

| interval | loss_streak_count | start | end | streak_net_pnl |
| --- | --- | --- | --- | --- |
| 15m | 11 | 2023-08-25T11:00:00+00:00 | 2023-09-06T11:15:00+00:00 | -5,518.43 |
| 5m | 19 | 2025-07-30T10:05:00+00:00 | 2025-08-11T21:55:00+00:00 | -6,478.80 |

## 11. 成本影响

| interval | commission | slippage | total_cost | gross_pnl | net_pnl |
| --- | --- | --- | --- | --- | --- |
| 15m | 21,334.10 | 45,780.00 | 67,114.10 | -50,910.00 | -118,024.10 |
| 5m | 34,113.78 | 71,160.00 | 105,273.78 | -79,020.00 | -184,293.78 |

## 12. 是否建议进入下一版 v0.2

建议进入 `v0.2` 研究设计阶段，但不建议进入模拟盘或实盘验证。

理由：

- 两个周期均为显著负收益，15m total return 为 -11.80%，5m total return 为 -18.43%。
- 最大回撤分别为 11.80% 和 18.43%，超过 v0.1.1 的 10% review threshold。
- 成本对短持有策略影响明显，尤其 5m 交易次数更多、成本更高。
- v0.2 应聚焦规则质量诊断、过滤条件、出场机制和成本敏感性验证；不得直接做全样本参数优化后验收。

## 13. 需要 ChatGPT 重点分析的问题

1. 15m 与 5m 的亏损是否主要来自交易成本、入场信号质量、还是出场优先级。
2. `pullback_only` 是否过于宽松，导致在震荡或弱趋势中频繁进入。
3. `time_exit_bar_8`、`signal_failure_exit`、`stop_loss`、`take_profit` 各自对盈亏的贡献。
4. 日线 EMA21 方向过滤是否滞后，是否需要加入趋势强度或波动率过滤。
5. 5m 是否因交易频率过高导致成本压制，是否应降低信号密度或提高距离/质量门槛。
6. 最大回撤和最长连亏是否集中在特定月份、合约切换、夜盘/日盘或方向侧。
7. rejected signals 的主要原因是否说明规则过窄、数据 warm-up 过长、或日线方向过滤过强。
8. v0.2 应优先改规则定义、样本切分方法、成本模型验证，还是 K 线复盘标签体系。
9. 是否存在任何未来函数、数据泄露、连续合约误用或交易参数缺失的隐患需要人工复查。
10. 在不做参数优化的前提下，下一轮最小可验证改动应是什么。

## Supporting Files

- Review package: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/`
- 15m trades CSV: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/15m/15m_trades.csv`
- 5m trades CSV: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/5m/5m_trades.csv`
- Equity/drawdown brief: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/equity_drawdown_stats.md`
- Rejected signals stats: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/rejected_signals_stats.md`
- Parameter snapshot: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/parameter_snapshot.json`
- Data scope: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/data_scope.md`
- Safety self-check: `backtests/reports/su_bing_jm_v1b_short_hold/chatgpt_review_package_20260628_230009/future_leakage_self_check.md`
