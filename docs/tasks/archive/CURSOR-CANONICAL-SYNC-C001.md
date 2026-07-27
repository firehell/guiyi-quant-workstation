# CURSOR-CANONICAL-SYNC-C001

更新时间：2026-07-19

对应手册任务：`C0-01` / `CURSOR-CANONICAL-SYNC-C001`（原 `N0-01` 追平后的 Cursor Wave 入口）

## 结论

状态：`COMPLETED / CURSOR_CANONICAL_SYNC_PREPARED`

本任务只对齐 canonical 文档与任务池，不修改业务代码、DB、Parquet、Profile binding、runtime、Issue 状态或历史验收证据。

## 对齐后的事实

- `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 仍是 strict formal consumer Gate（C2-05 rerun 证据不变）。
- `DATA_LAYER_REAUDIT_REQUIRED` 仍是全历史 residual 的非阻塞维护 backlog；不否定 consumer Gate，也不能被 Ready 抹去。
- 两个状态都不表示 OOS、T3/T4、live SignalEvent、企业微信正式发送、`JM_RUNTIME_READY` 或 `LONG_RUNNING_READY`。

## D4-00 记录（不重开公式审计）

`HTDY-SOURCE-XMA-AUDIT-400` / 手册 D4-00 的审计产物已落盘，任务执行完成；**不重新打开**通达信源码或 XMA 公式审计。

| 项 | 状态 |
|---|---|
| 证据目录 | `data/reports/indicator_contract_v1/` |
| 最终 Gate | `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` |
| source freeze / original-strict boundary / XMA(25) window offset | evidence confirmed，**不是** pass Gate |
| 禁止宣称 | `HTDY_XMA_SEMANTICS_AUDITED`、`HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`、original formal 化 |

Cursor Wave 只消费既有 D4-00 证据；original 保持 observation-only，strict 仅可作为 formal candidate 预构建输入。

## 执行顺序（本轮固定）

```text
完整 Cursor Wave
  -> Cursor → Codex 单次交接 Gate
  -> Codex Wave（正式验收 / 报告写入 / OOS / T3/T4）
```

业务主线阶段不变：

1. 阶段 4：指标契约与 formal candidate 封板
2. 阶段 5：策略可信验证
3. 阶段 6：JM T3 / T4 真实 Gate

## 已处理漂移

| 位置 | 原有漂移 | 对齐结果 |
|---|---|---|
| 任务池 / handoff | 仍停在 `NEXT_WAVE_CANONICAL_SYNCED`，下一入口写“手册 D4-00” | 记录 D4-00 证据已落盘；下一入口改为 Cursor Wave（C4-01 起） |
| 执行工具顺序 | 未写 Cursor Wave → Codex Wave | 固定先完整 Cursor Wave，再单次交接给 Codex Wave |
| D4-00 Gate | 手册假定 pass 标签与仓库证据冲突 | 以仓库最终 Gate `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` 为准，不扩写 Ready |

N0-01 / `V1-NEXT-WAVE-FACT-SYNC-000` 的 consumer Gate 并列语义保持不动；历史快照中的“尚未通过”不改写。

## 验证

```bash
git diff --check
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|D4-00|HTDY|OOS|T3_REAL|JM_RUNTIME_READY" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md tasks/current.md docs --glob '*.md'
```
