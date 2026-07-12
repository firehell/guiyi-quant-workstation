# Worktree Writer Lock Handoff

## 目的

同一 worktree 同一时间只允许一个 writer。writer 包括 `codex`、`cursor`、`codebuddy`。`plan` / `review` 可以保持只读，但如果当前 worktree 已有活跃 writer，调度器会拒绝进入容易冲突的阶段。

锁文件位于 `.ai/locks/worktrees/`，审计记录位于 `.ai/locks/audit.jsonl`。这些都是运行时文件，不提交到 Git。

## Cursor 人工接管

```bash
scripts/ai/writer_lock.sh status --worktree "$PWD"

scripts/ai/writer_lock.sh acquire \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --branch "$(git branch --show-current)" \
  --writer cursor \
  --stage manual-edit
```

完成人工修改后释放：

```bash
scripts/ai/writer_lock.sh release \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

## Codex / CodeBuddy 串行执行

```bash
scripts/ai/writer_lock.sh status --worktree "$PWD"
scripts/ai/dispatch_task.sh <TASK_ID> plan --json
scripts/ai/approve_task.sh --task <TASK_ID>
scripts/ai/dispatch_task.sh <TASK_ID> dev --json
scripts/ai/writer_lock.sh status --worktree "$PWD"
```

`dispatch_task.sh dev` 和 `dispatch_task.sh fix` 会自动获取 `writer=codex` 的独占写锁，并在成功、失败或常见中断信号后尽力释放自己持有的锁。

## Stale Lock 处理

不得直接删除 `.ai/locks/` 文件。先查看状态：

```bash
scripts/ai/writer_lock.sh status --worktree "$PWD" --json
```

确认 stale 后显式清理：

```bash
scripts/ai/writer_lock.sh break-stale \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

`break-stale` 会写入审计记录。活跃 PID 不会被清理。
