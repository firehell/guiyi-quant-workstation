# STRATEGY_CURRENT_STATE.md

生成时间：2026-06-30  
用途：上传给新的 ChatGPT 项目，作为当前苏冰/JM 策略状态和下一轮回测讨论依据。  
事实优先级：当前代码和最新报告最高；旧聊天和早期设计只作历史参考。

## 1. 当前苏冰策略版本

当前与苏冰/JM 相关的主要版本：

| strategy_code | strategy_version | 作用 | 状态 |
|---|---|---|---|
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 日线方向 + 15m/5m 短持有研究 | 已有策略包和报告上下文 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 | 不得静默修改 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 日线 4 条件任意 2 条 + 方向锚点研究版本 | 已实现、已回测、trusted 结果为负 |

当前最需要讨论的是 `v0.3.0-daily-score2of4` 是否应进入 `v0.3.1` 风控增强，还是回到更严格的入场结构。

## 2. 当前策略入场逻辑

`v0.3.0-daily-score2of4` 是日线策略，只使用已完成日线 bar。

做多 4 个条件：

- `long_trend_ok`: close > EMA21
- `macd_near_zero`: abs(DIF) <= 25 且 abs(DEA) <= 25
- `long_macd_cross`: DIF 上穿 DEA
- `volume_expanded`: current_volume > previous_volume

做空 4 个条件：

- `short_trend_ok`: close < EMA21
- `macd_near_zero`: abs(DIF) <= 25 且 abs(DEA) <= 25
- `short_macd_cross`: DIF 下穿 DEA
- `volume_expanded`: current_volume > previous_volume

开仓要求：

- `min_entry_score = 2`
- 必须有方向锚点：趋势位置或 MACD 方向交叉
- long / short 同时满足且同分时拒绝
- 信号在当前日线 close 产生，下一根日线 open 成交

该规则专门避免 `macd_near_zero + volume_expanded` 这种无方向组合直接开仓。

## 3. 当前策略出场逻辑

`v0.3.0-daily-score2of4` 第一版沿用 `v0.2.0-daily` 的 EMA21 失败退出，便于归因：

- 多单：日线 close < EMA21，下一根日线 open 平仓。
- 空单：日线 close > EMA21，下一根日线 open 平仓。

当前未启用：

- ATR stop
- fast-fail
- profit protection
- time exit
- 自动反手
- 实盘或模拟盘下单

## 4. 当前持仓逻辑

- 每次最多 1 手 / 1 个单位仓位。
- `maximum_position = 1`。
- `reverse_policy = no_same_daily_bar_reverse`。
- 开仓和平仓均为日线信号后下一根日线 open 成交。
- `submit_vnpy_orders = false`，研究交易由策略内部记录输出。
- 当前 score2of4 日线策略不是 15m/5m 短持有版本。

## 5. 当前参数

`v0.3.0-daily-score2of4` 默认参数：

| 参数 | 值 |
|---|---:|
| `ema_period` | 21 |
| `macd_fast` | 12 |
| `macd_slow` | 26 |
| `macd_signal` | 9 |
| `macd_zero_threshold` | 25 |
| `min_entry_score` | 2 |
| `require_directional_anchor` | true |
| `ambiguous_tie_action` | `reject` |
| `maximum_position` | 1 |
| `slippage_ticks` | 1 |
| `stop_loss_enabled` | false |
| `take_profit_enabled` | false |
| `time_exit_enabled` | false |
| `live_trading_enabled` | false |
| `auto_order_enabled` | false |

任何参数变化都必须创建新版本，不能直接覆盖旧版本。

## 6. 当前已跑过的回测

### v0.2.0-daily baseline

- strategy：`su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- 对比口径中 trade_count：7
- net_pnl：9356.616
- win_rate：0.4285714286
- max_consecutive_losses：3
- 说明：作为冻结基线，不应被后续实验静默改变。

### v0.3.0-daily-score2of4

- report_id：11
- 数据：JM 1d，2023-01-03 至 2025-12-31
- raw_trade_count：47
- trusted_trade_count：39
- excluded_cross_contract_trades：8
- raw_net_pnl：52798.083
- trusted_net_pnl：-34914.555
- trusted_win_rate：0.2051282051
- trusted_profit_loss_ratio：2.1928229665
- trusted_max_drawdown：0.3728810309
- trusted_max_consecutive_losses：8

可信结论：只能看 trusted excluding cross-contract。按可信口径，`v0.3` 当前不合格。

## 7. 当前策略问题

- `score=2` 交易数量大，trusted_net_pnl 为 -42716.19，是主要噪声来源。
- `volume_only_confirm` 和 `range_risk` 标签表现差，trusted_net_pnl 均为 -33937.734。
- `no_macd_cross` 标签覆盖 45 笔 raw trade，trusted_net_pnl 为 -44329.608。
- raw 指标为正但 trusted 指标为负，说明跨合约收益污染风险仍然关键。
- 当前没有 ATR stop、fast-fail、profit protection，亏损控制不足。
- 只在 JM 单品种 3 年窗口验证，存在过拟合和样本依赖风险。

## 8. 当前准备优化的方向

优先级从高到低：

1. 关闭 rollover-safe / cross-contract P0，确保指标可信。
2. 对 score=2 做限制或拆分，不允许所有 2/4 组合一视同仁。
3. 限制 `volume_only_confirm`、`range_risk`、`no_macd_cross`。
4. 评估 `score>=3` 或必须包含趋势 + MACD 方向交叉的版本。
5. 如果新增 ATR stop / fast-fail / profit protection，必须创建 `v0.3.1-*`，并保持入场逻辑可归因。
6. 回到 V1-B 主线时，优先验证日线定方向 + 15m/5m 独立入场 + 5-8 根短持有。

## 9. 下一轮建议跑哪些回测

建议按顺序跑：

1. `v0.3.0` rollover-safe 复跑或 trusted-only 复核。
2. `v0.3.1-score3only`：只允许 score >= 3。
3. `v0.3.1-no-volume-only`：禁止只有趋势 + 量能或 MACD near zero + 量能的弱组合。
4. `v0.3.1-require-macd-cross`：要求趋势锚点 + MACD 方向交叉。
5. `v0.3.1-atr-stop-fastfail`：在固定入场规则后再加入风控，避免入场/出场同时变化。
6. 与 `v0.2.0-daily` baseline 做同口径对比。

每次都必须输出 raw metrics、trusted metrics、excluded trades、score / condition / tag 分布、trade 明细和复盘上下文。

## 10. 需要重点防范的未来函数 / 数据泄露风险

- 日线 close 产生信号，只能下一根日线 open 成交。
- 15m/5m 策略使用日线方向时，只能使用已确认日线。
- 同一根 bar 不允许开仓后立即用未来信息标记失败。
- MFE、MAE、`immediate_failure_later`、复盘标签只能在交易结束后用于分析，不能进入入场/出场判断。
- 主力合约映射不能使用未来成交量/持仓信息影响过去交易。
- cross-contract PnL 不能混入 trusted 指标。
- 参数和规则不能用全样本表现反复调优后宣称稳健。
- 回测结果不等于实盘结果，实盘前必须先做模拟和小资金人工确认验证。
