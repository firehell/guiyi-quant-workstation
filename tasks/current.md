# 当前任务：JM-LIVE-RUNTIME-GATE（并行 Codex 会话 D）

更新时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md`

分支：`codex/jm-live-runtime-gate`

Worktree：`/Volumes/扩展盘/guiyi-parallel/jm-live-gate`

当前状态：`CODE_COMPLETE_EXTERNAL_GATES_PENDING`（merge 完成，T1/T3 真实 Gate 待执行）

## 目标

把 once 级 live 代码收敛为默认关闭、可监督、可恢复、可审计的 JM actual-contract 运行闭环，严格按 Gate 推进 T1-ops → T3-real。

## 本轮完成的开发范围（merge 自 v1-live-runtime-closure）

- [x] T0–T7-code：scheduler、交易时钟、1m→多周期、盘后归档、live event、notification worker、launchd 模板
- [x] merge `codex/v1-live-runtime-closure` 到本分支
- [ ] T1-ops：恢复 API/Web/backtest/signal worker 的实际 launchd 监督
- [ ] T3-real：JM 单次真实 1m、全周期聚合和重启恢复 smoke
- [ ] T4-real：至少一个 JM 交易日真实盘后归档 smoke（后置）

## Feature flags（全部默认 false）

```text
GUIYI_LIVE_RUNTIME_ENABLED
GUIYI_LIVE_SIGNAL_EVENTS_ENABLED
GUIYI_AFTER_MARKET_ARCHIVE_ENABLED
GUIYI_WECHAT_AUTOSEND_ENABLED
```

## 硬边界

- 不修改 `apps/quant-web/`
- 不 CTP / 自动下单
- 每步只开一个 flag

## 验收

见 `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md` 与 `docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md`。
