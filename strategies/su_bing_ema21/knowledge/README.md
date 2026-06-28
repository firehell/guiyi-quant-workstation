# Su Bing Strategy Knowledge Assets

This directory is a documentation-only knowledge asset module for the Su Bing
strategy system.

It is used to collect, normalize, and review strategy knowledge before any
future quantitative implementation. It does not contain executable strategy
code, backtest wiring, Web changes, data-system changes, or trading logic.

## Directory Purpose

- `raw_materials/`: Original subjective descriptions, excerpts, interviews, or
  manually organized source material for the Su Bing system.
- `rule_cards/`: Future entry, exit, stop-loss, take-profit, and filter rule
  cards split from the source material.
- `scenario_cards/`: Future market scenario cards such as trend, range,
  pullback, breakout, and invalidation.
- `review_tags/`: Future review tags, mistake types, and trade attribution
  labels.
- `implementation_notes/`: Future design notes before quantitative
  implementation. Do not place executable code here.

## Boundary

- Do not add Python, TypeScript, Vue, JSON, YAML, or strategy runtime files in
  this module.
- Do not modify backtest engines, Web pages, data systems, or existing strategy
  code from this module.
- Treat this module as preparation for later rule clarification and review,
  not as an implementation of the strategy.
