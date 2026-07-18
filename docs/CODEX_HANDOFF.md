# CODEX_HANDOFF.md

更新时间：2026-07-18

## 接手结论

当前工作树的事实源同步任务为 `V1-NEXT-WAVE-FACT-SYNC-000`，状态为 `COMPLETED / NEXT_WAVE_CANONICAL_SYNCED`。工作目录应从执行时最新 `origin/main` 创建独立任务 worktree；不得在 `main` 直接开发。

当前可依赖的消费者数据结论：

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
```

前两项是 strict formal Market、Backtest、Signal、Review consumer Gate；最后一项是全历史 residual 的独立维护 backlog。它们可并存，且不构成 OOS、真实 live、企业微信、长稳、自动交易或全历史 zero-residual Ready。

历史 Phase 3 数字、旧 Audit V2 / Profile / consumer 任务与报告均保留作历史审计快照；不得重写或把它们重新排入当前 P0。

## 下一轮顺序

1. 阶段 4：指标契约与 formal candidate 封板。
2. 阶段 5：策略可信验证，包含独立候选报告、trust audit、OOS/walk-forward 与 Review 回链。
3. 阶段 6：重建稳定 runtime 副本后，执行 JM T3/T4 真实 Gate。

每个代码任务先 Plan；OOS/walk-forward 默认仅写文件或隔离数据库。canonical PostgreSQL、T3 live 表/checkpoint、T4 archive 均需各自的 hash-bound approval packet 和用户明确批准。`report_id=14` 永远只能读取和核对，不能覆盖、回填或为提高收益而改参。

## Issue 生命周期

- Issue #10、#11：代码已被当前主干覆盖；本任务只给出人工关闭/归档建议，不自动修改 Issue。
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
11. `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`

## 最小验证

```bash
git status --short --branch
git diff --check
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|CONSUMER_DATA_CONTRACT_READY|OOS|T3_REAL|JM_RUNTIME_READY" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md tasks/current.md docs --glob '*.md'
```
