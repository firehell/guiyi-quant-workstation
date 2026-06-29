# SU_BING_SKILL_RULES_EXTRACT

## Source Boundary

This extract uses structured project knowledge only:

- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
- `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`
- `docs/strategy_knowledge/su_bing/SU_BING_SKILL.md`

It does not copy course text, private Notion text, screenshots, or image-case content. All items below are rule candidates or review candidates, not executable trading signals.

## Extracted Rule Candidates

| rule_category | source_rule_ids | extracted_candidate | quantization_status | implementation_boundary |
|---|---|---|---|---|
| 趋势方向规则 | RULE-003, RULE-013 | Use larger-period direction and smaller-period timing as separate responsibilities; identify trend continuation, trend failure, and range conditions. | partial | Requires explicit timeframe and alignment decisions before implementation. |
| EMA21 使用规则 | RULE-004, RULE-006, RULE-007 | Treat EMA21 as a trend/background line with price relation, slope, pullback, breakout, reclaim, and distance fields. | partial | EMA21 alone must not become an entry trigger. |
| MACD 零轴附近规则 | RULE-005 | MACD may support trend or entry confirmation near a neutral/turning region. | partial | Rulebook gives no numeric band; current `±25` is an engineering decision, not a course-derived threshold. |
| MACD 金叉 / 死叉规则 | RULE-005 | MACD cross can be a confirmation candidate when trend and EMA context agree. | partial | Must use completed bars only and define failure handling. |
| 成交量规则 | RULE-002, RULE-007, RULE-014 | Volume can confirm breakout quality, market background, or observation context. | partial | `current > previous` is an engineering simplification; Rulebook does not provide this exact rule. |
| 突破 / 回踩 / 收回 EMA21 | RULE-004, RULE-006, RULE-007 | Breakout, pullback, and EMA reclaim are setup candidates that require confirmation and failure conditions. | needs_review | Do not implement with future high/low or post-trade outcome. |
| 禁止追高 / 杀跌 | RULE-001, RULE-008, TAG-006, TAG-009 | Avoid impulsive chasing, excessive EMA distance, and entries without confirmation. | partial | May become ATR distance filter after new spec review. |
| 震荡区过滤 | RULE-001, RULE-003, RULE-008, TAG-008 | Range or unclear trend should be avoided or reduced in frequency. | partial | Requires explicit range definition; no threshold in Rulebook. |
| 入场触发规则 | RULE-002, RULE-006, RULE-007, RULE-008 | Entry requires trend background, setup quality, confirmation, and risk pre-check. | partial | Current v0.2 has only close/EMA21 + MACD cross + volume. |
| 持仓规则 | RULE-009, RULE-017 | Holding should depend on whether the entry premise and system consistency remain valid. | partial | Do not use final PnL, future MFE/MAE, or post-trade tags. |
| 离场规则 | RULE-009 | Exit when holding premise fails or plan no longer holds. | partial | v0.2 only exits on opposite EMA21 close. |
| 止损规则 | RULE-010, RULE-012, TAG-010 | Every trade should define risk and stop-loss before entry. | partial | v0.2 has no fixed stop; R cannot be computed reliably. |
| 浮盈保护规则 | RULE-011, TAG-011 | Profit protection may be defined before entry and tied to initial risk and holding premise. | partial | Must not be derived from best historical MFE after the fact. |
| 多空对称性 | RULE-002, RULE-003 | Long/short rules should be explicit and comparable. | partial | Current code has symmetric close-vs-EMA and MACD cross checks. |
| 信号强弱评分 | RULE-002, RULE-008, RULE-014 | Multiple evidence fields can be scored for review or future spec design. | partial | Scores must not replace clear entry/exit rules without review. |
| 其他人工经验规则 | RULE-015, RULE-016, RULE-017 | Discipline, psychology, and review findings are post-trade review inputs. | no / review_only | Review tags must not enter same-bar `on_bar` logic. |

## Review-Only Tags

The following categories may be used in trade review only unless a future Strategy Spec converts them into reviewed rule candidates: trend quality, EMA21 position, MACD confirmation, pullback quality, breakout quality, chase entry, counter-trend, range whipsaw, stop-loss quality, profit protection, execution discipline, risk management, and out-of-system behavior.

## Explicit Non-Assumptions

- No numeric EMA distance, ATR multiple, MACD band, volume moving average, stop multiple, or fast-fail bar count is course-derived here.
- Old `su_bing_ema21` code and old `SU_BING_QUANT_SPEC_V0_1.md` are not rule sources for this extract.
- `TAG-*` and completed-trade review conclusions must not affect the same trade's signal.
