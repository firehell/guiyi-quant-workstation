# CODEX_HANDOFF.md

更新时间：2026-07-20

## 接手结论

Codex 已完成阶段 4/5 最终只读验收。阶段 4 Gate：

```text
INDICATOR_REGISTRY_V1_READY
STRATEGY_INDICATOR_POLICY_READY
HTDY_STRICT_FORMAL_REPORT_READY
INDICATOR_CONTRACT_READY
STRATEGY_VALIDATION_PROTOCOL_FROZEN
STAGE4_COMPLETED
```

阶段 5 Gate 与研究结论：

```text
STRATEGY_EVALUATION_PIPELINE_READY
REJECTED_RESEARCH_CANDIDATE
STAGE5_CLOSEOUT_V2_READY
STAGE5_COMPLETED
READY_TO_ENTER_STAGE6
```

候选淘汰是可信验证管道的合法输出，不是工程失败。R45-05 对 report14/report15/task23、X5/R45 evidence、protocol、parameters、Profile binding 和绑定 Parquet 做了执行前后只读对账，未修改冻结对象。

手册 §9 切换 Gate 审查结论：`CURSOR_TO_CODEX_SWITCH_GATE_PASSED`（见下方切换审查包）。允许进入 Codex Wave；Cursor 自报测试不得直接采信。

统一交接包：

- `data/reports/ai_handoff/CURSOR_WAVE_HANDOFF.md`
- `data/reports/ai_handoff/cursor_wave_manifest.json`

切换 Gate 审查包：

- `data/reports/ai_handoff/CURSOR_TO_CODEX_SWITCH_GATE_REVIEW.md`
- `data/reports/ai_handoff/cursor_to_codex_switch_gate_review.json`
- `docs/tasks/CURSOR-SWITCH-GATE-REVIEW-S001.md`

X0-01 与 X4-06 已完成；阶段 5 的 X5-03～07 和 R45-01～04 也已闭合。最终证据见 `data/reports/stage45_final_acceptance_r4505/`。下一入口为阶段 6 JM T3/T4 独立 Plan，不得复用阶段 5 分支或把 HTDY rejection 自动翻转。

当前可依赖的消费者数据结论：

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
```

前两项是 strict formal Market、Backtest、Signal、Review consumer Gate；最后一项是全历史 residual 的独立维护 backlog。它们可并存，且不构成 OOS、真实 live、企业微信、长稳、自动交易或全历史 zero-residual Ready。

D4-00（`HTDY-SOURCE-XMA-AUDIT-400`）original 证据已落盘；最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。不重新打开公式审计，不宣称 `HTDY_XMA_SEMANTICS_AUDITED`。独立 causal strict 只取得 formal historical backtest/report 输入资格，不授权 live/alert。

历史 Phase 3 数字、旧 Audit V2 / Profile / consumer 任务与报告均保留作历史审计快照；不得重写或把它们重新排入当前 P0。

## 本轮工具顺序

```text
完整 Cursor Wave（已完成交接）
  -> Cursor → Codex 单次交接 Gate（CURSOR_WAVE_READY_FOR_CODEX_REVIEW）
  -> 切换 Gate 审查（CURSOR_TO_CODEX_SWITCH_GATE_PASSED）
  -> Codex X0-01 独立复核（已完成）
  -> Codex X4-06 指标契约正式验收修复（INDICATOR_CONTRACT_READY）
  -> 阶段 5 可信验证与 R45 closeout（REJECTED_RESEARCH_CANDIDATE）
  -> R45-05 最终只读验收（READY_TO_ENTER_STAGE6）
```

Cursor Wave 与阶段 4/5 入口均已关闭；下一业务入口为阶段 6 JM T3/T4，不得并行重开 HTDY 调参或 OOS。

## 业务主线顺序

1. 阶段 4：指标契约与 formal candidate 封板（已完成）。
2. 阶段 5：策略可信验证（已完成；工程管道 Ready，HTDY candidate rejected）。
3. 阶段 6：重建稳定 runtime 副本后，执行 JM T3/T4 真实 Gate（下一任务）。

每个代码任务先 Plan；OOS/walk-forward 默认仅写文件或隔离数据库。canonical PostgreSQL、T3 live 表/checkpoint、T4 archive 均需各自的 hash-bound approval packet 和用户明确批准。`report_id=14` 永远只能读取和核对，不能覆盖、回填或为提高收益而改参。

## Issue 生命周期

- Issue #10、#11：代码已被当前主干覆盖；只给出人工关闭/归档建议，不自动修改 Issue。
- Issue #12：保持 open，后续指向新的稳定 runtime 副本及 T3/T4 Gate。

## 必读顺序

1. `AGENTS.md`
2. `PROJECT_SOURCE.md`
3. `STATUS.md`
4. `DECISIONS.md`
5. `CODEX_TASKS.md`
6. `tasks/current.md`
7. `docs/DATA_CENTER.md`
8. `docs/INDICATOR_KERNEL.md`
9. `docs/BACKTEST_ENGINE.md`
10. `docs/SIGNAL_EVENTS.md`
11. `data/reports/ai_handoff/CURSOR_WAVE_HANDOFF.md`（及 `cursor_wave_manifest.json`）
12. `data/reports/ai_handoff/CURSOR_TO_CODEX_SWITCH_GATE_REVIEW.md`（及 `cursor_to_codex_switch_gate_review.json`）
13. `data/reports/ai_handoff/CODEX_CURSOR_WAVE_INDEPENDENT_REVIEW.md`（及 `codex_cursor_wave_independent_review.json`）
14. `data/reports/indicator_contract_v1/INDICATOR_CONTRACT_ACCEPTANCE_X406.md`（及 `indicator_contract_acceptance_x406.json`）
15. `docs/tasks/CURSOR-WAVE-HANDOFF-C999.md`
16. `docs/tasks/CURSOR-SWITCH-GATE-REVIEW-S001.md`
17. `docs/tasks/CURSOR-WAVE-INDEPENDENT-REVIEW-X001.md`
18. `docs/tasks/INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406.md`
19. `docs/tasks/TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504.md`
20. `docs/tasks/TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md`
21. `data/reports/stage45_final_acceptance_r4505/STAGE45_FINAL_ACCEPTANCE.json`
22. `docs/tasks/CURSOR-CANONICAL-SYNC-C001.md`
23. `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`

## 最小验证

```bash
git status --short --branch
git diff --check
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|D4-00|HTDY|OOS|T3_REAL|JM_RUNTIME_READY" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md tasks/current.md docs --glob '*.md'
```
