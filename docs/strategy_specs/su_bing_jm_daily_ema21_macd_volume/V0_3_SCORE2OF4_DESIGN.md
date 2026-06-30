# V0_3_SCORE2OF4_DESIGN

## 1. 策略定位

`v0.3.0-daily-score2of4` 是一个独立研究版本，用于验证用户提出的“4 个条件满足任意 2 个即可开仓”的 JM 日线策略想法。

它不替换 `v0.2.0-daily`，不做参数优化，不输出实盘建议，不接入自动下单。本版本只验证入场评分逻辑，离场沿用 v0.2.0 的 EMA21 失败退出，便于归因。

## 2. 做多条件

long 条件：

- `long_trend_ok`: close > EMA21
- `macd_near_zero`: abs(DIF) <= `macd_zero_threshold` 且 abs(DEA) <= `macd_zero_threshold`，默认 25
- `long_macd_cross`: DIF 上穿 DEA
- `volume_expanded`: current_volume > previous_volume

`long_score` 是上述 4 个条件中 True 的数量。

## 3. 做空条件

short 条件：

- `short_trend_ok`: close < EMA21
- `macd_near_zero`: abs(DIF) <= `macd_zero_threshold` 且 abs(DEA) <= `macd_zero_threshold`，默认 25
- `short_macd_cross`: DIF 下穿 DEA
- `volume_expanded`: current_volume > previous_volume

`short_score` 是上述 4 个条件中 True 的数量。

## 4. 开仓规则

默认参数：

- `min_entry_score = 2`
- `require_directional_anchor = true`
- `ambiguous_tie_action = reject`

做多开仓：

- `long_score >= min_entry_score`
- 且至少满足一个方向锚点：`long_trend_ok` 或 `long_macd_cross`

做空开仓：

- `short_score >= min_entry_score`
- 且至少满足一个方向锚点：`short_trend_ok` 或 `short_macd_cross`

方向冲突处理：

- 如果 long 和 short 同时满足入场分数与方向锚点：
  - `long_score > short_score`：做多
  - `short_score > long_score`：做空
  - `long_score == short_score`：不交易，记录 `reject_reason = ambiguous_direction_score_tie`

该规则避免只有 `macd_near_zero + volume_expanded` 这类无方向组合直接开仓。

## 5. Skill 灵活标签

Skill 不作为更多硬过滤。Skill 只用于信号解释、复盘和分层。

每个候选信号输出：

- `entry_score`
- `entry_grade`: A = 4, B = 3, C = 2
- `satisfied_conditions`
- `failed_conditions`
- `scene_tags`
- `skill_notes`

第一版 scene tags：

- `standard_trend`
- `trend_continuation`
- `weak_two_condition`
- `chase_risk`
- `range_risk`
- `volume_only_confirm`
- `no_macd_cross`
- `no_trend_alignment`

`immediate_failure_later` 只能在交易结束后的报告复盘中标注，不允许进入同一时点 `on_bar`。

## 6. 默认离场

第一版 v0.3.0 保持 v0.2.0 的离场逻辑：

- 多单：close < EMA21 后下一根日线 open 平仓。
- 空单：close > EMA21 后下一根日线 open 平仓。

本轮不启用 ATR stop、fast-fail 或 profit protection，避免同时改变入场和离场造成归因混乱。

## 7. 风控说明

本版本只验证入场评分逻辑。

- 不启用 ATR stop。
- 不启用 fast-fail。
- 不启用 profit protection。
- 不做参数优化。
- 不做实盘或模拟盘下单。

报告必须输出 chase/range/weak-signal 等标签、MFE、MAE 和 trusted metrics，供下一轮判断是否进入 `v0.3.1` 风控增强。

## 8. Rollover / cross-contract 处理

当前没有 fresh rollover-safe baseline。本轮回测必须同时输出：

- raw metrics
- trusted excluding cross-contract metrics
- cross_contract_trades
- excluded_trades
- metric_scope

可信结论必须基于 trusted excluding cross-contract metrics。跨合约交易可以展示在 raw metrics 中，但不得混入 trusted 收益结论。

## 9. 未来函数与数据泄露边界

- 指标只使用当前及过去已完成日线 K 线。
- 当前日线 close 产生信号，下一根日线 open 成交。
- 同一根 bar 不允许开仓后立即用未来信息标记失败。
- Review Tags、MFE、MAE、`immediate_failure_later` 和交易后复盘结论不得参与同一时点入场/出场判断。

## 10. 默认参数

| parameter | default |
|---|---:|
| `strategy_code` | `su_bing_jm_daily_ema21_macd_volume` |
| `strategy_version` | `v0.3.0-daily-score2of4` |
| `interval` | `1d` |
| `ema_period` | 21 |
| `macd_fast` | 12 |
| `macd_slow` | 26 |
| `macd_signal` | 9 |
| `macd_zero_threshold` | 25 |
| `min_entry_score` | 2 |
| `require_directional_anchor` | true |
| `ambiguous_tie_action` | `reject` |
| `emit_skill_tags` | true |
| `maximum_position` | 1 |
| `slippage_ticks` | 1 |
| `submit_vnpy_orders` | false |
| `live_trading_enabled` | false |
| `auto_order_enabled` | false |
