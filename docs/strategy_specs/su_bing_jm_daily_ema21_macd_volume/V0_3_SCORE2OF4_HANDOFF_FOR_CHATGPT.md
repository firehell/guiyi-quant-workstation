# V0_3_SCORE2OF4_HANDOFF_FOR_CHATGPT

## 本轮做了什么

- 新增并回测 `v0.3.0-daily-score2of4`。
- 保留 `v0.2.0-daily` 冻结基线。
- 输出 raw 与 trusted excluding cross-contract 指标。

## 规则摘要

- 4 个条件任意 2 个满足，且必须有方向锚点。
- 同分方向冲突拒绝。
- 离场沿用 EMA21 失败退出。

## raw vs trusted

{
  "report_id": 11,
  "strategy_code": "su_bing_jm_daily_ema21_macd_volume",
  "strategy_version": "v0.3.0-daily-score2of4",
  "metric_scope": "trade_level_only",
  "raw_trade_count": 47,
  "trusted_trade_count": 39,
  "excluded_trade_count": 8,
  "raw_net_pnl": 52798.083,
  "trusted_net_pnl": -34914.555,
  "raw_win_rate": 0.3191489362,
  "trusted_win_rate": 0.2051282051,
  "raw_profit_loss_ratio": 3.4583804266,
  "trusted_profit_loss_ratio": 2.1928229665,
  "raw_max_drawdown": 0.1375073065,
  "trusted_max_drawdown": 0.3728810309,
  "raw_max_consecutive_losses": 7,
  "trusted_max_consecutive_losses": 8,
  "cross_contract_trades": 8,
  "excluded_trade_ids": "SB-JM-S2OF4-D-2;SB-JM-S2OF4-D-8;SB-JM-S2OF4-D-21;SB-JM-S2OF4-D-26;SB-JM-S2OF4-D-31;SB-JM-S2OF4-D-36;SB-JM-S2OF4-D-38;SB-JM-S2OF4-D-45",
  "conclusion": "V0.3 score2of4 trusted metrics exclude cross-contract PnL; raw metrics are shown for audit only."
}

## score 分布

# V0.3 Score Distribution

| score | signal_count | trade_count | trusted_net_pnl |
|---|---:|---:|---:|
| score=2 | 33 | 32 | -42716.19 |
| score=3 | 14 | 14 | -4748.826 |
| score=4 | 1 | 1 | 12550.461 |

## Condition Combos

| combo | count |
|---|---:|
| short_trend_ok+macd_near_zero | 12 |
| long_trend_ok+volume_expanded | 9 |
| short_trend_ok+macd_near_zero+volume_expanded | 8 |
| short_trend_ok+volume_expanded | 8 |
| long_trend_ok+macd_near_zero+volume_expanded | 5 |
| long_trend_ok+macd_near_zero | 4 |
| long_trend_ok+macd_near_zero+long_macd_cross+volume_expanded | 1 |
| short_trend_ok+short_macd_cross+volume_expanded | 1 |


## Skill 标签结论

{
  "trend_continuation": {
    "trade_count": 14,
    "trusted_trade_count": 11,
    "net_pnl": 16689.618,
    "trusted_net_pnl": -4748.826,
    "win_rate": 0.3571428571,
    "average_pnl": 1192.1155714286,
    "max_loss": -4213.548,
    "suggested_action": "keep_for_review"
  },
  "no_macd_cross": {
    "trade_count": 45,
    "trusted_trade_count": 37,
    "net_pnl": 43383.03,
    "trusted_net_pnl": -44329.608,
    "win_rate": 0.3111111111,
    "average_pnl": 964.0673333333,
    "max_loss": -5900.976,
    "suggested_action": "keep_for_review"
  },
  "weak_two_condition": {
    "trade_count": 32,
    "trusted_trade_count": 27,
    "net_pnl": 23558.004,
    "trusted_net_pnl": -42716.19,
    "win_rate": 0.28125,
    "average_pnl": 736.187625,
    "max_loss": -5900.976,
    "suggested_action": "review_or_restrict"
  },
  "volume_only_confirm": {
    "trade_count": 17,
    "trusted_trade_count": 15,
    "net_pnl": -27972.714,
    "trusted_net_pnl": -33937.734,
    "win_rate": 0.1764705882,
    "average_pnl": -1645.4537647059,
    "max_loss": -5900.976,
    "suggested_action": "keep_for_review"
  },
  "range_risk": {
    "trade_count": 17,
    "trusted_trade_count": 15,
    "net_pnl": -27972.714,
    "trusted_net_pnl": -33937.734,
    "win_rate": 0.1764705882,
    "average_pnl": -1645.4537647059,
    "max_loss": -5900.976,
    "suggested_action": "review_or_restrict"
  },
  "standard_trend": {
    "trade_count": 1,
    "trusted_trade_count": 1,
    "net_pnl": 12550.461,
    "trusted_net_pnl": 12550.461,
    "win_rate": 1.0,
    "average_pnl": 12550.461,
    "max_loss": 12550.461,
    "suggested_action": "keep_for_review"
  }
}

## 下一步建议

- A. 调整 2-of-4 规则
- B. 增加 v0.3.1 ATR stop / fast-fail
- C. 做 rollover-safe 数据任务
- D. 做条件组合消融
- E. 回到日线方向 + 5m/15m 入场

# V0.2 vs V0.3 Score2Of4 Comparison

| metric | v0.2 baseline | v0.3 score2of4 trusted |
|---|---:|---:|
| trade_count | 7 | 39 |
| net_pnl | 9356.616 | -34914.555 |
| win_rate | 0.4285714286 | 0.2051282051 |
| profit_loss_ratio | 2.1817815805 | 2.1928229665 |
| max_consecutive_losses | 3 | 8 |
