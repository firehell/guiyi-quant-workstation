# V0_3_DAILY_STRATEGY_DESIGN

## Summary

`v0.3.0-daily` should be a new version, not a parameter-tuned replacement of `v0.2.0-daily`. The design goal is "Su Bing scene recognition + risk protection" for JM daily research. It must keep V1 boundaries: research, backtest, review, and signal alert only. No auto order path is allowed.

Implementation is blocked until rollover-safe handling or explicit cross-contract PnL exclusion is available.

## Version Identity

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- proposed_strategy_version: `v0.3.0-daily`
- baseline_reference: `v0.2.0-daily`
- target product: JM only for first validation
- timeframe: daily bars only for this design
- fill policy: completed daily close signal, next daily open fill
- live trading: disabled
- auto order: disabled

## Layer 1: Data Trust

Rules:

- Reject or force-exit trades that cross main-contract mappings unless a rollover-safe mode is explicitly enabled.
- Every trade must have `holding_bars`, `holding_trading_days`, `holding_calendar_days`, MFE, MAE, and R fields.
- R is computed only after an initial stop exists.

Parameters:

| parameter | default | reason |
|---|---:|---|
| `force_rollover_exit` | `true` for v0.3 tests | Prevent mixed continuous-contract PnL. |
| `exclude_cross_contract_pnl_from_metrics` | `true` | Keep research metrics trusted when forced exit cannot be applied. |

## Layer 2: Trend Environment

Rules:

- Long background: close above EMA21.
- Short background: close below EMA21.
- EMA21 slope should agree with direction or at least not oppose it.
- Entry is blocked when price is too far from EMA21 by ATR.

Parameters:

| parameter | default | reason |
|---|---:|---|
| `ema_period` | `21` | Preserve baseline identity. |
| `require_ema_slope_confirmation` | `true` | Avoid flat or opposing EMA trend. |
| `ema_slope_lookback` | `3` | Smooth one-day noise without using future bars. |
| `atr_period` | `14` | Standard volatility normalization. |
| `max_entry_ema_distance_atr` | `2.0` | Blocks SB-JM-D-7 style chase entries; must be sample-out validated. |

## Layer 3: Scene Recognition

Scene labels are computed from current and past completed bars only:

- `standard_zero_axis_resonance`
- `ema21_pullback`
- `ema21_reclaim`
- `trend_continuation`
- `anti_chase_reject`
- `range_risk_reject`

Scene labels are not review tags. They must be deterministic rule outputs and logged with the trade or rejected signal.

## Layer 4: Entry Trigger

Rules:

- MACD golden/dead cross remains an entry confirmation candidate.
- MACD zero-axis context becomes a tier score:
  - `strong`: both DIF and DEA within `25`
  - `medium`: both within `50`
  - `weak`: both within `100`
- Default entry allows `strong` and `medium`; `weak` is background only.
- Volume confirmation becomes a score, not only `current > previous`.

Parameters:

| parameter | default | reason |
|---|---:|---|
| `macd_strong_zero_band` | `25` | Preserves baseline strong tier. |
| `macd_medium_zero_band` | `50` | Observation tier for ablation. |
| `macd_weak_zero_band` | `100` | Background-only tier. |
| `allowed_macd_tiers_for_entry` | `["strong", "medium"]` | Avoid hard overfit while not forcing one threshold. |
| `volume_ma_short` | `5` | Smooths one-day volume noise. |
| `volume_ma_long` | `20` | Context for baseline participation. |
| `volume_ma20_ratio` | `0.8` | Conservative initial design, not optimized. |

Volume is confirmed when any of these are true:

- current volume > previous volume
- current volume > volume MA5
- current volume > volume MA20 * `volume_ma20_ratio`

## Layer 5: Risk and Exit

Rules:

- Initial ATR stop is defined before entry.
- Fast-fail exit closes if entry premise fails within the first N bars.
- EMA21 failure exit remains available.
- Profit protection is optional and disabled until separately tested.
- Forced rollover exit takes precedence over ordinary strategy exits.

Parameters:

| parameter | default | reason |
|---|---:|---|
| `stop_loss_enabled` | `true` | Required for R and risk control. |
| `stop_atr_multiple` | `2.0` | Conservative starting point; requires sample-out review. |
| `fast_fail_enabled` | `true` | Addresses SB-JM-D-2. |
| `fast_fail_bars` | `3` | Early failure window, not optimized from 7 trades. |
| `profit_protection_enabled` | `false` | Design candidate, not first implementation default. |
| `profit_protection_trigger_atr` | `3.0` | Review-only default if enabled later. |

## Difference From v0.2.0

| area | v0.2.0-daily | v0.3.0-daily design |
|---|---|---|
| Versioning | Frozen baseline | New version only |
| Rollover | Not applied | Forced exit or exclusion policy |
| EMA21 | close position only | slope, distance, setup scenes |
| MACD | hard `±25` and fresh cross | tiered scoring plus cross confirmation |
| Volume | hard current > previous | multi-rule score |
| Stop | disabled | ATR initial stop |
| Fast fail | disabled | enabled |
| Profit protection | disabled | optional, default off |
| R unit | not available | available after stop |

## Expected Improvements

- SB-JM-D-2: ATR stop or fast-fail should reduce uncontrolled immediate failure.
- SB-JM-D-5 and SB-JM-D-6: range/setup filters may reduce whipsaw entries.
- SB-JM-D-7: ATR distance filter should reject chase entry.
- SB-JM-D-1: optional profit protection may reduce giveback, but must be tested carefully.
- SB-JM-D-3: rollover-safe policy removes cross-contract PnL ambiguity.

## Possible Opportunity Loss

- Anti-chase filter may remove real trend-continuation entries.
- EMA slope confirmation may delay valid early reversals.
- Wider MACD tiers may increase noisy signals if risk filters are weak.
- Fast-fail exit may exit trades that later recover.

## Anti-Overfitting Controls

- Do not tune defaults from 7 trades.
- Freeze v0.2 baseline.
- Run same window with rollover-safe or cross-contract exclusion before judging PnL.
- Add sample-out and later multi-product review before any simulation recommendation.
- Report trade count, drawdown, consecutive losses, expectancy, and loss-size distribution, not only net PnL.

## Test Plan

Required tests before implementation is accepted:

- v0.2 parameter validation still rejects changed v0.2 defaults.
- v0.2 trade count and signal decisions are unaffected.
- anti-chase rejects entries beyond `max_entry_ema_distance_atr`.
- MACD tier scoring classifies strong, medium, weak, and outside bands.
- volume scoring passes each allowed branch and fails when none pass.
- ATR stop records stop price and R.
- fast-fail exit uses only current and past completed bars.
- forced rollover exit closes before contract switch and records `rollover_forced_exit=true`.
- Review tags remain post-trade only.

## Implementation Decision

Do not implement `v0.3.0-daily` in this round unless the rollover P0 is closed by either a versioned forced-exit implementation or a documented exclusion policy with fresh report output.
