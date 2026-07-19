# HTDY R45-02 Sample-End Accounting Liquidation Audit

- Structural Gate: `OOS_STRUCTURAL_AUDIT_AMENDED`
- Numeric Gate: `NUMERIC_HARD_REJECT_PRESERVED`
- Accounting liquidation: `True`
- Window end: `2026-07-10T15:00:00`
- Event: `HTDY-179`
- Trade: `HTDY-179`
- Max consecutive losses: `12`
- Profit factor: `0.16355909337101607`

The one excluded close is an accounting-only sample-end liquidation, not an ordinary next-bar fill.
All entries and all other signal-bearing events/trades retain strict `fill > signal` checks.
The numeric hard reject and rejected research outcome remain unchanged.
