# SKILL_SCOPE_RESET

## Why This Reset Exists

This reset corrects a scope mix-up in the Su Bing knowledge work.

The current goal is not to repair an existing Su Bing strategy, implement vn.py code, or force `SU_BING_QUANT_SPEC_V0_1.md` to match the current project stage. The current goal is to turn Su Bing course MD / Notion export material into a general, stable, reusable Codex Skill.

## What Was Mixed Together

Two different tasks were previously blended:

- Skill 建设：organize Su Bing course knowledge into source indexes, rule candidates, review tags, and reusable generation boundaries.
- 具体策略实现：define a tradable/backtestable strategy for a specific product, data range, timeframe, holding period, engine, and execution assumption.

The Skill can support future strategy generation, but it is not itself a strategy implementation.

## Current Scope

This stage only does:

- 苏冰课程 MD / Notion -> Skill.
- Skill -> Rulebook.
- Skill -> Review Tags.
- Skill -> protocol for generating future independent Strategy Specs.

The Rulebook remains a course rule library and rule-candidate library. Review Tags remain review and post-trade diagnostic labels.

## Out Of Scope Now

This stage does not:

- 修当前策略。
- 实现 vn.py。
- 对齐 JM V1-B。
- 修 `SU_BING_REVIEW_REPORT.md` 中针对旧 Quant Spec 的 P0。
- 修改回测引擎。
- 修改 Web。
- 修改数据库。
- 修改实盘交易代码。

`SU_BING_QUANT_SPEC_V0_1.md` is retained only as an archived or example spec. It must not be treated as the default specification for future implementation.

## Future Strategy Development Flow

When a real strategy is needed:

1. Use the `su-bing-strategy` Skill as the course knowledge source.
2. Provide the current strategy target: product, data range, timeframe, holding period, direction, risk constraints, backtest engine, execution assumptions, and prohibitions.
3. Generate a new independent Strategy Spec.
4. Review the Strategy Spec for future functions, data leakage, overfitting, execution assumptions, risk controls, and V1 live-trading boundaries.
5. Implement code only after the Strategy Spec passes review and the user explicitly authorizes the code-change scope.

Old strategy code and old specs can be engineering references for interfaces, but not rule sources.
