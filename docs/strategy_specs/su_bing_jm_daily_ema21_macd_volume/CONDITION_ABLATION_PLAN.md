# CONDITION_ABLATION_PLAN

## Purpose

This is a design plan for condition ablation, not parameter optimization. The goal is to understand rule contribution, signal count, risk exposure, and failure scenes. No experiment result may be selected as "best" by net profit alone.

## P0 Preconditions

Before producing PnL conclusions:

- `holding_bars` must be available in report exports or fresh persisted trades.
- Cross-contract PnL must be handled by rollover-safe exit or excluded from performance metrics.
- Costs, slippage, multiplier, and margin must remain included.
- Each experiment must record `experiment_id`, data window, strategy version or config hash, and cross-contract trade count.

Current status: rollover-safe is not implemented for daily v0.2, so this stage may be used as a plan or signal-count study only.

## Experiment Matrix

| experiment_id | description | allowed_conclusion |
|---|---|---|
| A_v020_baseline | Current `v0.2.0-daily` baseline. | Baseline traceability and failure scene review. |
| B_v020_rollover_safe | Baseline plus forced rollover exit or cross-contract exclusion. | Required before PnL comparison. |
| C_ema21_only | EMA21 direction only. | Signal volume and noise floor. |
| D_ema21_macd_cross_no_zero_band | EMA21 plus MACD cross, no zero-band restriction. | Effect of zero-band hard filter. |
| E_ema21_macd_zero_no_fresh_cross | EMA21 plus MACD near-zero, no fresh cross requirement. | Effect of fresh cross requirement. |
| F_ema21_volume | EMA21 plus volume confirmation only. | Effect of volume as hard filter. |
| G_ema21_macd_volume_score | EMA21 plus MACD, with volume as score not hard reject. | Whether volume should be soft evidence. |
| H_macd_50_with_anti_chase | EMA21 plus MACD `±50`, with EMA/ATR anti-chase filter. | Whether wider MACD band needs risk filter. |
| I_macd_25_with_atr_anti_chase | Current MACD `±25`, plus ATR distance filter. | Whether anti-chase reduces bad entries without retuning MACD. |
| J_daily_direction_intraday_entry_design | Daily direction only, 5m/15m entry design. | Design only; not implemented in this ablation. |

## Required Metrics

Each implemented experiment must output:

- data_start, data_end, source, data_role, quality_status
- strategy_code, strategy_version, experiment_id
- total trades, same-contract trades, cross-contract trades
- net PnL, gross PnL, total commission, total slippage
- max drawdown, win rate, profit/loss ratio, expectancy
- average win, average loss, max consecutive losses
- average holding bars, max holding bars
- rollover exit count, delivery risk exit count
- rejected signal counts by reason

## Reporting Rules

- Do not announce a winning parameter.
- Do not compare PnL while SB-JM-D-3 style cross-contract PnL remains mixed in.
- Prefer side-by-side risk explanation over ranking.
- If a variant reduces losses by filtering SB-JM-D-7, verify whether it also removes trend winners such as SB-JM-D-1.
- Any v0.3 rule must be justified by rule logic and safety, not just backtest profit.

## Suggested Implementation Later

Implement a small research-only ablation runner that reuses the indicator candidate frame from `scripts/export_su_bing_report_10_review_package.py`, writes CSV outputs under `backtests/reports/`, and never modifies `v0.2.0-daily` defaults.
