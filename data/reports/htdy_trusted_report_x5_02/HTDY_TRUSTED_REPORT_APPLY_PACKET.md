# HTDY X5-02 Trusted Report Apply Packet

- Gate: `HTDY_TRUSTED_REPORT_APPLY_PACKET_READY`
- Packet status: `READY_FOR_USER_APPROVAL`
- Pre-apply audit: `passed`
- Data version: `rqdata_jm_standard_15m_20200102_20260711_v2`
- Window: `2023-01-03T09:15:00` -> `2026-07-10T15:00:00`
- Bars: `19381`
- Trades: `1255`
- Total return: `-0.33491064870000004`
- Max drawdown: `0.33618490563265024`
- Total commission: `32735.648699999998`
- Total slippage: `75300.0`

## Boundary

- Read-only dry-run; no BacktestTask or BacktestReport was created.
- No canonical DB, Profile binding, Parquet, report14, OOS, live, notification, or order write is authorized.
- Formal report apply requires a separate task, explicit database-write approval, and post-write trust audit.
