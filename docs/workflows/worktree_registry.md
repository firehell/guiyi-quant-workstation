# Worktree Registry

> 自动生成：`scripts/ai/list_worktrees.sh --write-registry`
> 更新时间：2026-07-11T13:23:42Z

## 规范

- 默认根目录：`../guiyi-parallel/`（`GUIYI_WORKTREE_ROOT` 可覆盖）
- L1/L2 新任务：`scripts/ai/init_task_worktree.sh --task <TASK_ID>`
- 主仓库 worktree 仅用于只读验收；新开发请用 parallel worktree

## 当前 worktree

| Path | Branch | Dirty | Notes |
|------|--------|-------|-------|
| `/Volumes/扩展盘/guiyi-quant-workstation` | `codex/web-main-indicators` | dirty | 主仓库；新 L1/L2 任务勿在此开发 |
| `/Volumes/扩展盘/guiyi-parallel/data-audit` | `codex/data-asset-audit` | clean | 数据资产审计 |
| `/Volumes/扩展盘/guiyi-parallel/htdy-core` | `codex/htdy-indicator-core` | clean | 火天大有 core |
| `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` | `codex/jm-live-runtime-gate` | clean | JM live runtime gate |
| `/Volumes/扩展盘/guiyi-parallel/web-indicators` | `codex/web-overlay-indicators` | clean | legacy overlay indicators |
| `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime` | `codex/v1-live-runtime-closure` | clean | v1 live runtime closure |

## TASK 登记

- **TASK-2026-07-10-003-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=REQUIREMENT_READY
- **TASK-2026-07-11-001-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-002-lean-v1-demo** — L2, branch=`feature/lean-v1-demo`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-004-work-levels-home-direct** — L1, branch=`codex/web-main-indicators（已合并 @ cb3a5d44）`, worktree=`已移除（2026-07-11；内容已在主工程）`, status=CLOSED
