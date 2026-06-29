# REPORT_10_SKILL_TRADE_CLASSIFICATION

## Summary

This classification uses report 10 trade review data for post-trade diagnosis only. It does not create same-trade entry or exit rules. SB-JM-D-3 is separated from performance interpretation because it crosses from `JM2405` to `JM2409`.

## Trade Classification

| trade_id | direction | net_pnl | entry_contract | exit_contract | is_cross_contract | code_entry_reason | skill_scene_type | skill_match_status | issue_reason | suggested_action |
|---|---:|---:|---|---|---|---|---|---|---|---|
| SB-JM-D-1 | long | 12550.461 | JM2401 | JM2401 | false | close above EMA21 + MACD near-zero golden cross + volume expansion | trend_continuation | partially_matched | Large MFE `24960` vs realized net `12550.461`; held 28 bars. | Keep as valid trend example, but design profit protection review. |
| SB-JM-D-2 | long | -4823.208 | JM2405 | JM2405 | false | close above EMA21 + MACD near-zero golden cross + volume expansion | immediate_failure | partially_matched | Exit after 1 holding bar; MFE `-30`, MAE `-7710`. | Design fast-fail exit and ATR stop. |
| SB-JM-D-3 | short | 4060.38 | JM2405 | JM2409 | true | close below EMA21 + MACD near-zero dead cross + volume expansion | cross_contract_review | unclear | Entry and exit contracts differ; PnL is `untrusted_cross_contract_pnl`. | Exclude from optimization metrics until rollover-safe report exists. |
| SB-JM-D-4 | short | 7449.663 | JM2409 | JM2409 | false | close below EMA21 + MACD near-zero dead cross + volume expansion | standard_trend | matched_candidate | Entry close is near EMA21 with low adverse excursion. | Use as one positive baseline case for rule review, not as parameter target. |
| SB-JM-D-5 | short | -1933.308 | JM2505 | JM2505 | false | close below EMA21 + MACD near-zero dead cross + volume expansion | range_whipsaw | partially_matched | Short fails within 5 bars; small MFE and larger MAE. | Design range filter and fast-fail exit. |
| SB-JM-D-6 | short | -1842.909 | JM2505 | JM2505 | false | close below EMA21 + MACD near-zero dead cross + volume expansion | chase_entry | partially_matched | EMA distance about 1.66 ATR; MFE only `600`. | Add anti-chase filter candidate and setup-quality label. |
| SB-JM-D-7 | long | -6104.463 | JM2601 | JM2601 | false | close above EMA21 + MACD near-zero golden cross + volume expansion | chase_entry | partially_matched | EMA distance about 2.37 ATR; MFE only `180`, MAE `-8280`. | Strong candidate for ATR distance anti-chase filter. |

## Diagnostic Notes

- `standard_trend`: SB-JM-D-4 is the cleanest example, but one trade is not enough for validation.
- `trend_continuation`: SB-JM-D-1 validates that v0.2 can capture trend legs, but it also shows giveback risk.
- `immediate_failure`: SB-JM-D-2 supports fast-fail and pre-defined stop review.
- `range_whipsaw`: SB-JM-D-5 and possibly SB-JM-D-6 suggest missing range or setup-quality filtering.
- `chase_entry`: SB-JM-D-7 is the clearest anti-chase example by EMA/ATR distance and adverse outcome.
- `cross_contract_review`: SB-JM-D-3 must not influence parameter or version selection.

## Safety Boundary

This file is a post-trade classification. None of the scene labels may be used in `on_bar` for the same trades. Future implementation must convert any label into a separate reviewed rule candidate and versioned strategy spec.
