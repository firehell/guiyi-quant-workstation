# Worktree 与 Release 工作流

当前 bootstrap 阶段只提供本地受控操作；远端 `develop`、GitHub ruleset、auto-merge、tag、Release
和 Runtime promotion 都不是此脚本的能力。

## 拓扑

```text
guiyi-quant-workstation                 main（canonical）
GuiyiWorktrees/guiyi-develop            develop（启用后只做集成）
GuiyiWorktrees/tasks/<task-id>-<slug>   task（可清理）
GuiyiRuntime/guiyi-quant-workstation-runtime  detached Runtime
```

## 本地命令

所有命令先 dry-run；只有确认输出中的 `planned_commands`、工作区和 base SHA 无误后才加 `--apply`。

```bash
python3 scripts/engineering/worktree_flow.py audit --json

# develop 仅在当前仓库 clean、base 已验证且用户允许本地创建后执行。
python3 scripts/engineering/worktree_flow.py init --base-ref main --json

# 正式启用后 task 默认应从 origin/develop 创建。
python3 scripts/engineering/worktree_flow.py task-create \
  --kind feature --task-id ISSUE-123 --slug concise-name --json

# 手工 PR/merge 后，且 task HEAD 已成为 develop 祖先时才可清理。
python3 scripts/engineering/worktree_flow.py task-cleanup \
  --integration-branch develop \
  --task-path /Volumes/扩展盘/GuiyiWorktrees/tasks/ISSUE-123-concise-name --json
```

`--apply` 不会绕过 clean、branch prefix、ancestor 或 managed-path 检查。它也不会删除 `main`、
`develop`、detached Runtime 或历史遗留 branch。

## 发布与 Runtime

release 必须以用户批准的 PR 合入 main，并在最终 main commit 创建 annotated tag。Runtime promotion
继续使用独立业务 Gate；不可用 worktree 工具、release 批准或 S6-11 计划替代。
