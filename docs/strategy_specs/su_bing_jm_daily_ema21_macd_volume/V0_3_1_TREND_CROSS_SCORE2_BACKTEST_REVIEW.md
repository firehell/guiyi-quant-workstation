# V0_3_1_TREND_CROSS_SCORE2_BACKTEST_REVIEW

## 1. 回测配置

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.3.1-daily-trend-cross-score2`
- symbol: `jm`
- period: `1d`
- data_source: `local_parquet`
- data_role: `primary`
- entry_gate: `trend_alignment + matching_macd_cross`
- metric_scope: `raw_and_trusted_excluding_cross_contract`

## 2. 核心指标

{
  "report_id": 13,
  "strategy_code": "su_bing_jm_daily_ema21_macd_volume",
  "strategy_version": "v0.3.1-daily-trend-cross-score2",
  "metric_scope": "trade_level_only",
  "raw_trade_count": 22,
  "trusted_trade_count": 19,
  "excluded_trade_count": 3,
  "raw_net_pnl": -3401.457,
  "trusted_net_pnl": -20632.125,
  "raw_win_rate": 0.3181818182,
  "trusted_win_rate": 0.2105263158,
  "raw_profit_loss_ratio": 1.9959890137,
  "trusted_profit_loss_ratio": 2.1910054873,
  "raw_max_drawdown": 0.1625486833,
  "trusted_max_drawdown": 0.2990061643,
  "raw_max_consecutive_losses": 5,
  "trusted_max_consecutive_losses": 6,
  "cross_contract_trades": 3,
  "excluded_trade_ids": "SB-JM-TC-D-8;SB-JM-TC-D-11;SB-JM-TC-D-17",
  "conclusion": "V0.3.1 trend-cross score2 trusted metrics exclude cross-contract PnL; raw metrics are shown for audit only."
}

## 3. 三版本对比

# V0.2 vs V0.3 vs V0.3.1 Trend Cross Score2 Comparison

| metric | v0.2 trusted baseline | v0.3.0 score2of4 trusted | v0.3.1 trend-cross trusted |
|---|---:|---:|---:|
| trade_count | 6 | 39 | 19 |
| net_pnl | 5296.236 | -34914.555 | -20632.125 |
| win_rate | 0.3333333333 | 0.2051282051 | 0.2105263158 |
| profit_loss_ratio | 2.7203857918 | 2.1928229665 | 2.1910054873 |
| max_consecutive_losses | 3 | 8 | 6 |



## 4. score 分布

# V0.3 Score Distribution

| score | signal_count | trade_count | trusted_net_pnl |
|---|---:|---:|---:|
| score=2 | 201 | 3 | -8719.755 |
| score=3 | 86 | 14 | -11601.852 |
| score=4 | 5 | 5 | -310.518 |

## Condition Combos

| combo | count |
|---|---:|
| short_trend_ok+short_macd_cross+volume_expanded | 6 |
| long_trend_ok+macd_near_zero+long_macd_cross | 4 |
| long_trend_ok+macd_near_zero+long_macd_cross+volume_expanded | 3 |
| short_trend_ok+macd_near_zero+short_macd_cross | 3 |
| short_trend_ok+short_macd_cross | 3 |
| short_trend_ok+macd_near_zero+short_macd_cross+volume_expanded | 2 |
| long_trend_ok+long_macd_cross+volume_expanded | 1 |


## 5. Skill 标签复盘

{
  "trend_cross_confirmed": {
    "trade_count": 22,
    "trusted_trade_count": 19,
    "net_pnl": -3401.457,
    "trusted_net_pnl": -20632.125,
    "win_rate": 0.3181818182,
    "average_pnl": -154.6116818182,
    "max_loss": -6735.246,
    "suggested_action": "keep_for_review"
  },
  "trend_cross_without_full_confirmation": {
    "trade_count": 17,
    "trusted_trade_count": 15,
    "net_pnl": -7151.319,
    "trusted_net_pnl": -20321.607,
    "win_rate": 0.2941176471,
    "average_pnl": -420.6658235294,
    "max_loss": -6735.246,
    "suggested_action": "keep_for_review"
  },
  "no_volume_expansion": {
    "trade_count": 10,
    "trusted_trade_count": 9,
    "net_pnl": -2723.235,
    "trusted_net_pnl": -6551.031,
    "win_rate": 0.3,
    "average_pnl": -272.3235,
    "max_loss": -6735.246,
    "suggested_action": "keep_for_review"
  },
  "macd_zero_band_missing": {
    "trade_count": 10,
    "trusted_trade_count": 9,
    "net_pnl": -13147.839,
    "trusted_net_pnl": -22490.331,
    "win_rate": 0.3,
    "average_pnl": -1314.7839,
    "max_loss": -6735.246,
    "suggested_action": "keep_for_review"
  },
  "minimum_trend_cross_only": {
    "trade_count": 3,
    "trusted_trade_count": 3,
    "net_pnl": -8719.755,
    "trusted_net_pnl": -8719.755,
    "win_rate": 0.3333333333,
    "average_pnl": -2906.585,
    "max_loss": -6735.246,
    "suggested_action": "keep_for_review"
  },
  "chase_risk": {
    "trade_count": 1,
    "trusted_trade_count": 1,
    "net_pnl": -6735.246,
    "trusted_net_pnl": -6735.246,
    "win_rate": 0.0,
    "average_pnl": -6735.246,
    "max_loss": -6735.246,
    "suggested_action": "consider_anti_chase_filter_in_v0_3_1"
  },
  "standard_trend": {
    "trade_count": 5,
    "trusted_trade_count": 4,
    "net_pnl": 3749.862,
    "trusted_net_pnl": -310.518,
    "win_rate": 0.4,
    "average_pnl": 749.9724,
    "max_loss": -6104.463,
    "suggested_action": "keep_for_review"
  }
}

## 6. 结论

- 本文件只记录研究回测结论，不给实盘建议。
- 可信收益结论只使用 excluding cross-contract metrics。
- 本版本只改变入场 gate，不启用止损、止盈、time exit 或自动反手。
