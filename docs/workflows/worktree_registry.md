# Worktree Registry

> 自动生成：`scripts/ai/list_worktrees.sh --write-registry`
> 更新时间：2026-07-16T11:11:22+08:00

## 规范

- 默认根目录：`../guiyi-parallel/`（`GUIYI_WORKTREE_ROOT` 可覆盖）
- L1/L2 新任务：`scripts/ai/init_task_worktree.sh --task <TASK_ID>`
- 主仓库 worktree 仅用于只读验收；新 L1/L2 任务勿在此开发

## 当前 worktree

| Path | Branch | Dirty | Notes |
|------|--------|-------|-------|
| `/Volumes/扩展盘/guiyi-quant-workstation` | `main` | clean | 主工程；ALL-BRANCH-WORKTREE-MERGE 已收口 |

## 已移除 worktree

| Path | Branch | 移除时间 | Notes |
|------|--------|----------|-------|
| `/Volumes/扩展盘/guiyi-parallel/data-audit` | `codex/data-asset-audit` | 2026-07-12 | 数据内容审计已合并 main（`8ab908dd`） |
| `/Volumes/扩展盘/guiyi-parallel/workstation-router` | `cursor/workstation-router-v1` | 2026-07-12 | 工作站 V1.5 控制平面已合并 main（`3898ec96`） |
| `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` | `ops/local-runtime-disk` | 2026-07-16 | 按用户确认删除全部 worktree；runtime 副本如需继续使用需重新初始化 |
| `/Volumes/扩展盘/CopilotWorkstation/copilot-worktrees/guiyi-quant-workstation/firehell-studious-barnacle` | `firehell-codebase-overview-plan` | 2026-07-16 | prunable 失效记录，执行 `git worktree prune` 清理 |
| `/Volumes/扩展盘/guiyi-parallel/data-stage-closure-doc-audit` | `codex/data-stage-closure-doc-audit` | 2026-07-16 | prunable 失效记录，执行 `git worktree prune` 清理 |
| `/Volumes/扩展盘/guiyi-parallel/demo-20260715-004-github-native-v3-final-acceptance` | `task/demo-20260715-004-github-native-v3-final-acceptance` | 2026-07-16 | DEMO-004 已合并 main，worktree 删除 |
| `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` | `codex/jm-live-runtime-gate` | 2026-07-16 | 分支内容已被当前 main 覆盖，worktree 删除 |
| `/Volumes/扩展盘/guiyi-parallel/lpv-actual-contract-registration-dry-run` | `codex/lpv-actual-contract-registration-dry-run` | 2026-07-16 | 分支内容已被当前 main 覆盖，worktree 删除 |
| `/Volumes/扩展盘/guiyi-parallel/reference-metadata-gap-apply-plan` | `codex/reference-metadata-gap-apply-plan` | 2026-07-16 | 分支内容已被当前 main 覆盖，worktree 删除 |
| `/Volumes/扩展盘/guiyi-parallel/residual-data-risk-closeout` | `codex/residual-data-risk-closeout` | 2026-07-16 | 分支内容已被当前 main 覆盖，worktree 删除 |
| `/Volumes/扩展盘/guiyi-parallel/workstation-governance-v2` | `codex/workstation-governance-v2` | 2026-07-16 | 分支内容已被当前 main 覆盖，worktree 删除 |
| `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime` | `codex/v1-live-runtime-closure` | 2026-07-16 | 按用户确认删除全部 worktree；live runtime 副本如需继续使用需重新初始化 |

## TASK 登记

- **TASK-2026-07-10-003-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=REQUIREMENT_READY
- **TASK-2026-07-11-001-workstation-lean-v1-closeout** — L2, branch=`feature/workstation-lean-v1-closeout`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-002-lean-v1-demo** — L2, branch=`feature/lean-v1-demo`, worktree=``, status=DELIVERY_READY
- **TASK-2026-07-11-004-work-levels-home-direct** — L1, branch=`codex/web-main-indicators（已合并 @ cb3a5d44）`, worktree=`已移除（2026-07-11；内容已在主工程）`, status=CLOSED
- **TASK-2026-07-11-001-data-asset-audit** — L1, branch=`codex/data-asset-audit`, worktree=`已移除（2026-07-12；内容已在 main）`, status=DELIVERY_READY_WITH_CLI_ENV_NOTE
- **TASK-2026-07-11-002-data-target-coverage-audit** — L1, branch=`codex/data-target-coverage-audit-main`, worktree=`已移除（2026-07-12；内容已在 main @ 8ab908dd）`, status=MERGED_TO_MAIN
