# WS-SIMPLIFY-00-BASELINE-INVENTORY

| Field | Value |
|---|---|
| Task ID | WS-SIMPLIFY-00-BASELINE-INVENTORY |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Baseline | `964a961a` |
| Status | `DELIVERY_READY` |
| Risk | R1（只读盘点 + 文档） |
| Date | 2026-07-20 |

## Objective

在不改业务代码与现有控制脚本行为的前提下，完成工作站控制面盘点，输出依赖与迁移矩阵，作为 Step 1–7 的唯一删除/迁移依据。

## Allowed paths

```text
docs/workstation/WORKSTATION_SIMPLIFICATION_INVENTORY.md
docs/tasks/WS-SIMPLIFY-00-BASELINE-INVENTORY.md
```

## Forbidden paths

```text
apps/** services/** packages/** strategies/** data/**
database/** migrations/** scripts/** tests/**
README.md AGENTS.md STATUS.md PROJECT_SOURCE.md DECISIONS.md
CODEX_TASKS.md tasks/current.md
```

## Deliverables

1. [`docs/workstation/WORKSTATION_SIMPLIFICATION_INVENTORY.md`](../workstation/WORKSTATION_SIMPLIFICATION_INVENTORY.md)
2. 本 TASK 记录

## Verification

```bash
git diff --check
git status --short --branch
```

## Result

- Inventory 已覆盖：文档矩阵、状态源、脚本调用图、安全能力保留清单、可归档项、须先 deprecated 项、Step 1–7 风险。
- 未修改任何脚本或业务代码。
- 当前仓库已处于 `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`；本任务是进一步精简的基线，不是重建。

## Stop Gate

盘点未合并 / 未验收前，不得进入 Step 1。

## Next

用户确认 Step 0 后，在同一分支继续 Step 1（Canonical 文档收敛）。
