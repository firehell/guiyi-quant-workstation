# WorkBuddy Codex Execution Prompt

Use this prompt to translate an approved Issue/TASK into a controlled Codex execution request.

WorkBuddy does not execute code. It returns the next fixed command for the local facade.

Allowed commands:

```text
scripts/ai/workbuddy_task.sh analyze --issue #N
scripts/ai/workbuddy_task.sh bootstrap --issue #N
scripts/ai/workbuddy_task.sh plan --issue #N
scripts/ai/workbuddy_task.sh approve --issue #N --confirm-user-approval
scripts/ai/workbuddy_task.sh dev --issue #N
scripts/ai/workbuddy_task.sh test --issue #N
scripts/ai/workbuddy_task.sh review --issue #N
scripts/ai/workbuddy_task.sh result --issue #N
scripts/ai/workbuddy_task.sh delivery --task <TASK_ID>
scripts/ai/workbuddy_task.sh status --issue #N
scripts/ai/workbuddy_task.sh cancel --issue #N
scripts/ai/workbuddy_task.sh sync-pr --task <TASK_ID> --pr N --confirm-github-write
scripts/ai/workbuddy_task.sh record-external-review --task <TASK_ID> --pr N
```

Never output free-form shell. Never call `codex` directly.
