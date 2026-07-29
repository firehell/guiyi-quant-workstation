# Worktree 与 Release 工作流

本地 worktree 工具不操作远端；受控发布只由 `release-flow.sh` 执行。GitHub ruleset、auto-merge、
tag、Release 和 Runtime promotion 都不属于该脚本能力。

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

release 必须以用户批准的 PR 合入 main。仅在 main 与 develop 都 clean 且精确指向同一 commit 后，
用户可将该 SHA 绑定到一次原子远端发布：

```bash
bash scripts/engineering/release-flow.sh publish --expected-sha <40位小写SHA> --json
bash scripts/engineering/release-flow.sh publish --expected-sha <40位小写SHA> --apply --json
```

默认是 dry-run；`--apply` 只以精确 SHA 原子更新 `origin/main` 与 `origin/develop`，随后验证远端
两分支。它不打 tag、不创建 Release、不合并 PR，也不切换 Runtime。annotated tag 与 Runtime promotion
继续使用独立批准和业务 Gate；不可用 worktree 工具、release 批准或 S6-11 计划替代。
