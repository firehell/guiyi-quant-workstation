# CODEX_HANDOFF.md

更新时间：2026-07-19

## 接手结论

Cursor Wave 交接已完成：`CURSOR_WAVE_READY_FOR_CODEX_REVIEW`（**不是**阶段 4 Ready）。

手册 §9 切换 Gate 审查结论：`CURSOR_TO_CODEX_SWITCH_GATE_PASSED`（见下方切换审查包）。允许进入 Codex Wave；Cursor 自报测试不得直接采信。

统一交接包：

- `data/reports/ai_handoff/CURSOR_WAVE_HANDOFF.md`
- `data/reports/ai_handoff/cursor_wave_manifest.json`

切换 Gate 审查包：

- `data/reports/ai_handoff/CURSOR_TO_CODEX_SWITCH_GATE_REVIEW.md`
- `data/reports/ai_handoff/cursor_to_codex_switch_gate_review.json`
- `docs/tasks/CURSOR-SWITCH-GATE-REVIEW-S001.md`

推荐分支：`cursor/v1-indicator-strategy-prep`。冻结接管点：`b76791bf`（handoff checkpoint `5e1609b` + docs SHA backfill）。Codex Wave 应从该 tip 创建独立 worktree，不得在 `main` 直接开发；首任务为 **X0-01**（`CURSOR-WAVE-INDEPENDENT-REVIEW-X001`）独立复核，不信任 Cursor 自报。

当前可依赖的消费者数据结论：

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
```

前两项是 strict formal Market、Backtest、Signal、Review consumer Gate；最后一项是全历史 residual 的独立维护 backlog。它们可并存，且不构成 OOS、真实 live、企业微信、长稳、自动交易或全历史 zero-residual Ready。

D4-00（`HTDY-SOURCE-XMA-AUDIT-400`）证据已落盘于 `data/reports/indicator_contract_v1/`；最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。不重新打开公式审计，不宣称 `HTDY_XMA_SEMANTICS_AUDITED`。

历史 Phase 3 数字、旧 Audit V2 / Profile / consumer 任务与报告均保留作历史审计快照；不得重写或把它们重新排入当前 P0。

## 本轮工具顺序

```text
完整 Cursor Wave（已完成交接）
  -> Cursor → Codex 单次交接 Gate（CURSOR_WAVE_READY_FOR_CODEX_REVIEW）
  -> 切换 Gate 审查（CURSOR_TO_CODEX_SWITCH_GATE_PASSED）
  -> Codex Wave（首任务 X0-01 独立复核）
```

Cursor Wave 入口已关闭；切换 Gate 已审查通过；Codex 首任务为独立复核，而不是并行另开业务线。

## 业务主线顺序

1. 阶段 4：指标契约与 formal candidate 封板。
2. 阶段 5：策略可信验证，包含独立候选报告、trust audit、OOS/walk-forward 与 Review 回链。
3. 阶段 6：重建稳定 runtime 副本后，执行 JM T3/T4 真实 Gate。

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
13. `docs/tasks/CURSOR-WAVE-HANDOFF-C999.md`
14. `docs/tasks/CURSOR-SWITCH-GATE-REVIEW-S001.md`
15. `docs/tasks/CURSOR-CANONICAL-SYNC-C001.md`
16. `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`

## 最小验证

```bash
git status --short --branch
git diff --check
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|D4-00|HTDY|OOS|T3_REAL|JM_RUNTIME_READY" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md tasks/current.md docs --glob '*.md'
```
