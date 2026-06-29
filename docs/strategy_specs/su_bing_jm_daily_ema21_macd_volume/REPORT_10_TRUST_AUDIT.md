# REPORT_10_TRUST_AUDIT

## Summary

- report_id: `10`
- task_id: `17`
- strategy: `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily`
- trades: `7`
- orders: `0`
- strategy_execution_events: `14`
- rejected_signals: `476`

## Required Checks

| Check | Result |
|---|---|
| 7 笔交易中是否存在 entry_contract != exit_contract | Yes: SB-JM-D-3 |
| 跨合约 PnL 是否可信 | 需要复核；跨合约交易标记为 `cross_contract_needs_review`。 |
| 主连换月是否有真实 rollover 处理 | 当前 summary 显示 `forced_rollover_exit_policy=not_applied_for_daily_v0_2_0`。 |
| holding_bars 当前导出口径 | 旧持久化字段仍为 0；本导出保留 `holding_bars_persisted_value`，并用 K 线窗口生成 `holding_bars_current_value` 和 `holding_trading_days`。 |
| orders_count=0 是否只是 submit_vnpy_orders=False 的设计结果 | 是；研究交易来自 `strategy_trades`，不是 vn.py order ledger。 |
| strategy_execution_events_count=14 是否能完整对应 7 笔开平 | 是；7 open + 7 close。 |
| 每笔 PnL 是否可追溯到 K 线 | 同合约交易可追溯；跨合约交易需额外复核主力映射和价格连续性。 |
| 手续费、滑点、合约乘数是否正确 | 已导出字段；需外部审查交易所参数和主力映射。 |
| report_id=10 是否可以用于策略优化 | 不建议直接优化；应先做规则对齐和可信度复核。 |
| 如果不能，阻塞项 | 跨合约 PnL、旧报告持久化 holding_bars 为 0、无止损 R 单位、样本交易数仅 7。 |

## Conclusion

Report 10 可以作为规则对齐和逐笔复盘输入包，但不应直接作为参数优化依据。
