# Worktree Registry

> 自动生成：`scripts/ai/list_worktrees.sh --write-registry`
> 更新时间：2026-07-12T22:50:00+08:00

## 规范

- 默认根目录：`../guiyi-parallel/`（`GUIYI_WORKTREE_ROOT` 可覆盖）
- L1/L2 新任务：`scripts/ai/init_task_worktree.sh --task <TASK_ID>`
- 主仓库 worktree 仅用于只读验收；新 L1/L2 任务勿在此开发

## 当前 worktree

| Path | Branch | Dirty | Notes |
|------|--------|-------|-------|
| `/Volumes/扩展盘/guiyi-quant-workstation` | `main` | clean | 主仓库；数据审计与工作站 V1.5 已合并 |
| `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` | `ops/local-runtime-disk` | clean | 监督服务 runtime 副本（方案 B） |
| `/Volumes/扩展盘/guiyi-parallel/htdy-core` | `codex/htdy-indicator-core` | clean | 火天大有 core（已合并 main） |
| `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` | `codex/jm-live-runtime-gate` | clean | JM live runtime gate |
| `/Volumes/扩展盘/guiyi-parallel/web-indicators` | `codex/web-overlay-indicators` | clean | overlay indicators（已合并 main） |
| `/Volumes/扩展盘/guiyi-parallel/lpv-actual-contract-registration-dry-run` | `codex/lpv-actual-contract-registration-dry-run` | clean | LPV actual contract dry-run |
| `/Volumes/扩展盘/guiyi-parallel/reference-metadata-gap-apply-plan` | `codex/reference-metadata-gap-apply-plan` | clean | reference metadata gap apply plan |
| `/Volumes/扩展盘/guiyi-parallel/residual-data-risk-closeout` | `codex/residual-data-risk-closeout` | clean | residual data risk closeout |
| `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime` | `codex/v1-live-runtime-closure` | clean | v1 live runtime closure |

## 已移除 worktree

| Path | Branch | 移除时间 | Notes |
|------|--------|----------|-------|
| `/Volumes/扩展盘/guiyi-parallel/data-audit` | `codex/data-asset-audit` | 2026-07-12 | 数据内容审计已合并 main（`8ab908dd`） |
| `/Volumes/扩展盘/guiyi-parallel/workstation-router` | `cursor/workstation-router-v1` | 2026-07-12 | 工作站 V1.5 控制平面已合并 main（`3898ec96`） |

## TASK 登记

- **TASK-2026-07-10-003-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=REQUIREMENT_READY
- **TASK-2026-07-11-001-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-002-lean-v1-demo** — L2, branch=`feature/lean-v1-demo`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-004-work-levels-home-direct** — L1, branch=`codex/web-main-indicators（已合并 @ cb3a5d44）`, worktree=`已移除（2026-07-11；内容已在主工程）`, status=CLOSED
- **TASK-2026-07-11-001-data-asset-audit** — L1, branch=`codex/data-asset-audit`, worktree=`已移除（2026-07-12；内容已在 main）`, status=DELIVERY_READY_WITH_CLI_ENV_NOTE
- **TASK-2026-07-11-002-data-target-coverage-audit** — L1, branch=`codex/data-target-coverage-audit-main`, worktree=`已移除（2026-07-12；内容已在 main @ 8ab908dd）`, status=MERGED_TO_MAIN
