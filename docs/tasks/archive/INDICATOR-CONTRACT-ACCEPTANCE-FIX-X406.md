# INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406

更新时间：2026-07-19

状态：`COMPLETED / INDICATOR_CONTRACT_READY`

## 目标

修复 X4-06 独立验收发现的 Registry lifecycle、formal policy consumer、HTDY formal Profile lineage 和 C5-01 最终冻结缺口。

## 结果

```text
INDICATOR_REGISTRY_V1_READY
STRATEGY_INDICATOR_POLICY_READY
HTDY_STRICT_FORMAL_REPORT_READY
INDICATOR_CONTRACT_READY
STRATEGY_VALIDATION_PROTOCOL_FROZEN
```

HTDY original 继续 observation-only，D4-00 继续 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。strict 只取得 formal historical backtest/report 输入资格，不构成策略有效、OOS、live、alert 或企业微信 Ready。

## 验证

- 后端受影响回归：132 passed。
- Web indicators：13 passed。
- Ruff、C5 Schema/hash、report14 frozen hash、`git diff --check`：passed。
- 证据：`data/reports/indicator_contract_v1/INDICATOR_CONTRACT_ACCEPTANCE_X406.md` 与 `indicator_contract_acceptance_x406.json`。

## 边界

未创建真实 BacktestReport，未写 canonical DB、Parquet、Profile binding，未运行 OOS，未接 live、SignalEvent、企业微信或订单。

## 下一任务

阶段 5 按 `STRATEGY_VALIDATION_PROTOCOL_FROZEN` 创建独立 HTDY 候选报告并立即执行 trust audit；任何 canonical PostgreSQL 写入仍需独立批准。
