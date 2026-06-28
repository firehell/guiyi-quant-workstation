# SU_BING_SKILL

## Purpose

This document defines the working boundary for organizing Su Bing strategy
knowledge assets.

It is a structure document only. It does not contain course content, trading
signals, executable strategy logic, or backtest rules.

## Boundary

- Do not reproduce original course text.
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

## Disallowed Work

- Course transcription.
- Signal generation.
- Buy or sell point generation.
- Parameter optimization.
- Backtest result interpretation.
- Live trading advice.
- Automated order generation.

## Required Review Checks

- Source material is summarized without copying original wording.
- Any future implementation must use only current and past bars.
- Any future implementation must separate training, validation, and sample-out
  evidence.
- Any future implementation must document signal time and execution time.
- Any future implementation must state that backtest results do not equal live
  trading results.
