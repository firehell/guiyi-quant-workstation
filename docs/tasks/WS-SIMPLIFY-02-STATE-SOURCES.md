# WS-SIMPLIFY-02-STATE-SOURCES

| Field | Value |
|---|---|
| Task ID | WS-SIMPLIFY-02-STATE-SOURCES |
| Branch | `codex/workstation-simplify` |
| Status | `DELIVERY_READY` |
| Risk | R1 |
| Date | 2026-07-20 |

## Objective

将 `CODEX_TASKS.md` 与 `tasks/current.md` 长历史归档到 `docs/archive/task-history/`，根文件改为 deprecated / 兼容指针；不改 scripts/tests。

## Result

- 归档快照已落盘且不改写历史结论。
- `CODEX_TASKS.md` ≤40 行 deprecated 指针。
- `tasks/current.md` 最小兼容指针。
- 状态源说明已在 Step 1 `docs/DEVELOPMENT.md` / `AGENTS.md` / `PROJECT_SOURCE.md` 中确立。
