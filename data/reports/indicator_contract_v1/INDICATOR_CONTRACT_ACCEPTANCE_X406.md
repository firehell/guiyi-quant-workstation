# X4-06 指标契约正式验收

任务：`INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406`
基线：`b2b2e35a`
状态：`COMPLETED`

## Gate

```text
INDICATOR_REGISTRY_V1_READY
STRATEGY_INDICATOR_POLICY_READY
HTDY_STRICT_FORMAL_REPORT_READY
INDICATOR_CONTRACT_READY
STRATEGY_VALIDATION_PROTOCOL_FROZEN
```

## 验收事实

- Registry 八类 lifecycle 均有 fail-closed capability invariant。
- formal policy 同时执行 allowed/blocked consumer 校验；未知 policy、Web-only policy 和伪造 legacy 身份均被拒绝。
- frozen legacy 只按封闭 code/version catalog 识别，不读取 payload 猜测。
- HTDY original 继续 observation-only；D4-00 继续为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。
- HTDY strict 保持 strategy_candidate，只取得 formal historical backtest/report 输入资格。
- HTDY strict 已经内存 SQLite、临时 primary/passed Parquet 和 `ProfileLineageResolver` 端到端验证；task/report 的 Profile、file ID、binding 与 indicator policy snapshot 一致。
- C5-01 协议经用户批准转为 `final_frozen`；这不执行正式报告、OOS、live、alert 或通知。
- report14 frozen config SHA-256 保持 `8f45991aae4c4db62dffd4f60e9fc3cf61abea0381b88b9cd44e938fda26f49a`。

## 验证

```text
backend affected: 132 passed
web indicators: 13 passed
ruff: passed
git diff --check: passed
```

本任务没有写 canonical DB、Parquet、Profile binding、formal report、OOS、live、SignalEvent、企业微信或订单。
