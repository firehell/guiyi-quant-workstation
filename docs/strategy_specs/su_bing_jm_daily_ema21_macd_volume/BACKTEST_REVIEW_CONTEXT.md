# BACKTEST_REVIEW_CONTEXT - su_bing_jm_daily_ema21_macd_volume

## 1. 策略来源

- 策略来源：`su-bing-strategy` Skill。
- Strategy Spec：`docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md`
- Spec Review：`docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC_REVIEW.md`
- 本策略是独立 daily-only 规格，不继承旧 `su_bing_jm_v1b_short_hold` 或旧 `su_bing_ema21`。

## 2. 策略版本

- strategy_code：`su_bing_jm_daily_ema21_macd_volume`
- strategy_version：`v0.2.0-daily`
- product：JM 焦煤
- interval：`1d only`
- live_trading_enabled：false
- auto_order_enabled：false

## 3. 策略规则摘要

- EMA21：日线收盘价位于 EMA21 上方偏多，下方偏空。
- MACD：使用 12 / 26 / 9，要求 DIF 和 DEA 位于 0 轴附近，阈值 `abs(DIF) <= 25` 且 `abs(DEA) <= 25`。
- 做多：`close > EMA21` + MACD 0轴附近金叉 + `volume > previous_volume`。
- 做空：`close < EMA21` + MACD 0轴附近死叉 + `volume > previous_volume`。
- 成交：日线收盘后确认信号，下一根日线 open 成交，按 1 tick 不利滑点处理。
- 离场：多单 `daily close < EMA21` 后下一根日线 open 平仓；空单 `daily close > EMA21` 后下一根日线 open 平仓。
- 禁止：固定止损、固定止盈、time exit、同日反手、15m / 5m、小周期信号、实盘、自动下单。

## 4. 数据范围

- report_id：9
- task_id：16
- data_source：local_parquet
- data_version：rqdata_jm_standard_1d_20230103_20251231_v1
- symbol：jm
- contract：jm.MAIN
- period：1d
- start：2023-06-28T00:00:00+00:00
- end：2025-12-31T15:00:00+00:00

## 5. 数据角色

- data_role：`primary`
- quality_status：`passed`
- 明确排除：`legacy_reference`、`validation`、`tqsdk_formal_backtest_data`。

## 6. 回测结果摘要

| Metric | Value |
|---|---:|
| trade_count | 0 |
| win_rate | 0.000000 |
| profit_loss_ratio | 0.000000 |
| gross_pnl | 0.00 |
| net_pnl | 0.00 |
| commission | 0.00 |
| slippage | 0.00 |
| max_drawdown | 0.000000 |
| max_drawdown_amount | 0.00 |
| max_consecutive_losses | 0 |
| initial_capital | 100000.00 |
| final_equity | 100000.00 |

## 7. Long / Short 分解

| Direction | Trades | Gross PnL | Net PnL | Commission | Slippage |
|---|---:|---:|---:|---:|---:|
| long | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| short | 0 | 0.00 | 0.00 | 0.00 | 0.00 |

## 8. 按 Exit Reason 分解

| Exit Reason | Trades | Gross PnL | Net PnL | Commission | Slippage |
|---|---:|---:|---:|---:|---:|
| no_trades | 0 | 0.00 | 0.00 | 0.00 | 0.00 |

## 9. 是否建议进入下一版

建议进入“下一版研究诊断”，不建议进入模拟盘或实盘。

原因：本次正式日线回测 `trade_count = 0`，说明当前 v0.2.0-daily 规则在 JM primary / passed 日线窗口内没有形成可评价的成交样本。0 回撤、0 连亏和 0 成本不是策略稳健性的证据，只是无成交结果。

下一版应优先做信号覆盖诊断和规则审查，例如统计 near-zero MACD、金叉/死叉、成交量确认、EMA21 方向过滤各条件分别出现的次数和交集，而不是直接做全样本参数优化。

## 10. 需要 ChatGPT 重点分析的问题

1. 为什么 v0.2.0-daily 在 2023-06-28 至 2025-12-31 的 JM 日线 primary / passed 数据中没有成交？
2. `jm_macd_zero_band = 25` 对 JM 日线价格尺度是否过严或过宽？是否需要先做条件覆盖统计，而不是优化参数？
3. `volume > previous_volume` 是否过度过滤了 MACD 交叉信号？
4. EMA21 方向过滤与 MACD 0 轴附近交叉是否在 JM 日线上天然冲突？
5. 当前无固定止损、只用 EMA21 失效退出的风险是否需要在下一版前先设计最小风控观测字段？
6. 下一版应继续 daily-only，还是只把 daily 作为方向过滤并回到 15m / 5m 入场？
7. 是否应该新增“拒绝信号统计/条件命中统计”报告，再决定是否生成 v0.2.1？
8. 当前无成交报告是否足以否决本版本，还是只说明需要诊断版回测？

## 11. 附件路径

- report summary：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_report_summary.md`
- report summary json：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_report_summary.json`
- trades csv：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_trades.csv`
- orders csv：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/daily_orders.csv`
- equity curve：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/equity_curve.csv`
- drawdown curve：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/drawdown_curve.csv`
- parameter snapshot：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/parameter_snapshot.json`
- data scope：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/data_scope.md`
- future leakage self-check：`backtests/reports/su_bing_jm_daily_ema21_macd_volume/future_leakage_self_check.md`
