# V0_2_BASELINE_FINDINGS

## Baseline Identity

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.2.0-daily`
- report_id: `10`
- sample: 7 trades, 476 rejected signals
- purpose: baseline review, not parameter optimization

## Strengths

- Rules are simple and traceable: daily close vs EMA21, MACD near-zero cross, and volume expansion.
- Signal time and fill time are separated: completed daily close creates next daily open fill.
- Long and short logic is symmetric.
- Review tags are post-trade only and do not feed same-bar signal logic.
- Costs, slippage, contract multiplier, margin, MFE/MAE context, and main-contract labels are visible in the report package.

## Main Weaknesses

- One cross-contract trade, SB-JM-D-3, makes headline PnL unsuitable for optimization.
- Old report persistence has `holding_bars=0`; this is now corrected in export as `holding_bars_current_value`, but the original report remains a trust issue.
- No fixed stop means R units are not available for v0.2.
- No anti-chase filter allows entries far from EMA21, most visibly SB-JM-D-7.
- No range filter or setup-quality label means whipsaw trades pass the same hard conditions as trend trades.
- No profit protection means profitable trends can give back a large part of MFE.

## Loss and Risk Scenes

| scene | trades | evidence | likely_missing_control |
|---|---|---|---|
| immediate_failure | SB-JM-D-2 | 1 holding bar, MFE `-30`, MAE `-7710` | ATR stop, fast-fail exit |
| range_whipsaw | SB-JM-D-5 | 5 holding bars, MFE `1530`, MAE `-2670` | range filter, setup-quality filter |
| chase_entry | SB-JM-D-6, SB-JM-D-7 | EMA distance about 1.66 ATR and 2.37 ATR | max EMA distance by ATR |
| giveback | SB-JM-D-1 | MFE `24960`, realized net `12550.461` | optional floating-profit protection |
| cross-contract review | SB-JM-D-3 | `JM2405 -> JM2409` | rollover-safe exit or exclusion |

## False Entry Types

- Trend label too shallow: close above/below EMA21 does not describe trend strength.
- Setup type missing: breakout, pullback, reclaim, and continuation are not distinguished.
- Volume is too rough: one-bar expansion does not prove quality.
- MACD near-zero is too mechanical: `±25` is not a course-derived threshold.
- Risk pre-check missing: entries are allowed without stop distance or EMA distance guard.

## Possible Missed Signal Types

This package cannot prove missed profitable signals without running controlled ablations. Candidate missed-signal types to study:

- Signals rejected by MACD `±25` that may still be valid in a wider background band.
- Signals rejected by one-bar volume even when volume is above a moving average.
- EMA21 pullback or reclaim scenes that do not happen on the exact MACD cross bar.

## Why Not Optimize Directly

- The trusted sample has at most 6 same-contract trades.
- One profitable trade is cross-contract and currently untrusted.
- There is no sample-out split or multi-product validation.
- The most urgent fixes are risk and trust controls, not threshold tuning.
- Choosing the best MACD band or volume rule from this report would be overfitting.
