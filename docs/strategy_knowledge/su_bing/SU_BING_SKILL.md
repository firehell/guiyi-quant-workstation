# SU_BING_SKILL

## Purpose

This document defines the working boundary for organizing Su Bing strategy
knowledge assets.

It is a structure document only. It does not contain course content, trading
signals, executable strategy logic, or backtest rules.

Private source files may exist locally or in the private repository. Skill-facing
documents may only preserve short summaries, source IDs, abstract rule
candidates, quantization status, manual-review status, and boundary decisions.

## Boundary

- Do not reproduce original course text.
- Do not reproduce long passages, screenshots, image-only case content, or
  private Notion page text.
- Do not directly generate trading strategies.
- Do not allow future functions.
- Do not allow data leakage.
- Do not directly generate buy or sell points.
- Do not write executable strategy code.
- Do not connect to backtest engines, Web pages, data systems, brokers, or live
  trading interfaces.

## Allowed Work

- Organize source references.
- Split knowledge into neutral categories.
- Record unresolved questions.
- Prepare rulebook placeholders for later manual review.
- Prepare review tag placeholders for later trade review.
- Mark old specs and old strategy code as history, legacy, or engineering
  references only.

## Disallowed Work

- Course transcription.
- Signal generation.
- Buy or sell point generation.
- Parameter optimization.
- Backtest result interpretation.
- Live trading advice.
- Automated order generation.
- Treating old `su_bing_ema21` as the default strategy.
- Treating `SU_BING_QUANT_SPEC_V0_1.md` as the default Strategy Spec.

## Required Review Checks

- Source material is summarized without copying original wording.
- Review Tags remain post-trade-only and do not enter same-bar `on_bar` signal
  logic.
- Any future implementation must use only current and past bars.
- Any future implementation must separate training, validation, and sample-out
  evidence.
- Any future implementation must document signal time and execution time.
- Any future implementation must state that backtest results do not equal live
  trading results.
