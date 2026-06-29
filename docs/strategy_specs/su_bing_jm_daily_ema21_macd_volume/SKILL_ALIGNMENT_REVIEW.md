# SKILL_ALIGNMENT_REVIEW

## Summary

The current `v0.2.0-daily` implementation is a narrow engineering baseline. It matches only a small subset of the structured Su Bing rule candidates: EMA21 direction, MACD cross near zero, volume expansion, and EMA21 failure exit. It misses setup quality, anti-chase controls, range filtering, stop-loss, and profit protection.

## Alignment Table

| rule_category | current_code_rule | su_bing_skill_rule | match_status | evidence_from_report_10 | impact_on_strategy | suggested_action | priority |
|---|---|---|---|---|---|---|---|
| 趋势方向 | Long requires close > EMA21; short requires close < EMA21. | Trend should include direction, timeframe role, stability, failure, and range context. | partially_matched | All entries have correct close-vs-EMA direction. | Direction is simplified and may misread range periods. | Add EMA21 slope and optional higher-period trend only in new version. | P1 |
| EMA21 使用 | Uses price location against EMA21 only. | EMA21 candidates include direction, slope, pullback, breakout, reclaim, and distance. | partially_matched | SB-JM-D-7 entry distance is about 2.37 ATR from EMA21. | No anti-chase or setup type distinction. | Add EMA21 slope and ATR distance filter in v0.3 design. | P1 |
| MACD 零轴附近 | Hard band: `abs(DIF) <= 25` and `abs(DEA) <= 25`. | MACD is auxiliary confirmation; no numeric band is supplied by Rulebook. | code_too_strict | 476 rejected signals include MACD/entry-condition rejections. | Hard threshold may over-filter or create false precision. | Convert to scoring tiers in v0.3 design, not parameter optimization. | P1 |
| MACD 金叉 / 死叉 | Requires golden cross for long and dead cross for short. | MACD cross can confirm only with trend and setup context. | partially_matched | All 7 entries have expected cross type. | Cross alone cannot validate setup quality. | Keep as confirmation but add setup/risk layers. | P1 |
| 成交量 | Requires current volume > previous volume. | Volume can confirm setup or observation context; exact rule is unspecified. | code_too_strict | All 7 entries pass volume expansion, including losses. | One-bar volume rule is noisy. | Make volume a confirmation score using prior volume and moving averages. | P1 |
| 突破 / 回踩 / 收回 EMA21 | Not recognized. | Breakout, pullback, and reclaim are setup candidates requiring confirmation. | missing_in_code | SB-JM-D-4 looks closer to a standard trend/EMA setup; others are unclear. | No scene awareness. | Add setup_type classification before any new entry rule. | P1 |
| 禁止追高 / 杀跌 | Not implemented. | Avoid chasing and excessive EMA distance. | missing_in_code | SB-JM-D-7 has about 2.37 ATR EMA distance and large loss. | Allows poor risk/reward entries. | Add `max_entry_ema_distance_atr` in v0.3 design. | P1 |
| 震荡区过滤 | Not implemented. | Range or unclear trend should be avoided or reduced. | missing_in_code | SB-JM-D-2, SB-JM-D-5, and SB-JM-D-6 quickly fail or produce small adverse trades. | Trend system enters noisy regimes. | Add range filter design; do not overfit thresholds on 7 trades. | P1 |
| 入场触发 | EMA position + MACD cross near zero + volume expansion. | Entry should combine background, setup, confirmation, and risk pre-check. | partially_matched | Entries are traceable but not scene-aware. | Entry logic is complete enough for baseline, thin for strategy quality. | Preserve v0.2 baseline; design v0.3 layered entry. | P1 |
| 持仓 | Hold until opposite EMA21 close. | Holding should depend on premise validity and planned exits. | partially_matched | SB-JM-D-1 holds 28 bars and gives back from high MFE. | No time/risk/profit protection. | Add fast-fail and optional profit protection design. | P1 |
| 离场 | Exit next daily open after close crosses opposite side of EMA21. | Exit when premise fails or plan no longer holds. | partially_matched | Losses exit only after EMA21 failure. | Exit is late for immediate failures. | Add ATR stop and fast-fail exit in v0.3 design. | P1 |
| 止损 | Disabled. | Stop-loss should be defined before entry. | missing_in_code | R units are blank because v0.2 has no stop. | Risk cannot be normalized. | Add ATR initial stop; compute R only after stop exists. | P0/P1 |
| 浮盈保护 | Disabled. | Profit protection can be planned before entry. | missing_in_code | SB-JM-D-1 MFE is 24960 while realized net is 12550.461. | Large giveback possible. | Design optional protection; default may stay off until tested. | P1 |
| 多空对称性 | Long and short checks are symmetric. | Long/short rules should be explicit. | matched | Long/short entries and EMA exits are mirrored. | Symmetry is acceptable at baseline. | Keep tests ensuring v0.2 unaffected. | P2 |
| 信号强弱评分 | Not implemented. | Multi-evidence fields can support review and future version design. | missing_in_code | Current output is pass/reject only. | No ability to compare marginal signals. | Add scoring for review/experiment, not live orders. | P2 |
| Review Tags | Not used by signal logic. | Tags are post-trade only. | matched | Tests confirm `review_tags` and `TAG-*` are not read in signal code. | Avoids data leakage. | Preserve this boundary. | P0 |

## Safety Review

- No evidence was found that `TAG-*`, MFE/MAE, or post-trade conclusions affect same-bar signal generation.
- Current signal timing remains completed daily close to next daily open fill.
- Main open issue is not future leakage; it is strategy quality and cross-contract PnL trust.
