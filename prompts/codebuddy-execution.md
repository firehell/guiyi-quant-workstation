# CodeBuddy Execution Prompt

Use this prompt in Enterprise WeChat after the user has reviewed an Issue / TASK / Draft PR or WorkBuddy PM/QA summary.

## Plan phase

```text
请在 Mac mini 本地 guiyi-quant-workstation 仓库中执行下面 Issue / TASK。

执行规则：
1. 先运行 pwd、git rev-parse --show-toplevel、git status --short --branch。
2. 先阅读 AGENTS.md、CODEBUDDY.md、docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md、docs/workstation/REMOTE_DEVELOPMENT.md、docs/CODEX_HANDOFF.md、tasks/current.md。
3. 不允许修改 .env、密钥、token、webhook、账号、cookie、license。
4. 不允许删除或重写 data/raw/、data/processed/、data/parquet/。
5. 不允许自动交易、自动下单、订单草稿、自动 push、merge、release、部署。
6. 只调用 scripts/ai/dispatch_task.sh，不直调 codex_plan.sh / codex_dev.sh，不裸 codex exec。
7. 第一轮只执行 plan 阶段，不进入 dev。
8. 不重新解释或扩大 TASK 范围。
9. 优先解析 Issue #N 对应的 TASK / branch / worktree；如果当前脚本尚不支持 Issue-first，则请求 TASK_ID 并使用兼容路径。
10. 执行：scripts/ai/dispatch_task.sh <TASK_ID> plan --json
11. 返回 Issue、TASK_ID、branch、worktree、plan 输出路径、route.json、git status 和 execution_summary 路径供我确认。

任务入口：
【粘贴 Issue #N / TASK_ID / PR #N / WorkBuddy 输出的 CodeBuddy Prompt】
```

Shorter template (verbatim):

```text
执行 Issue #N 对应任务的 plan 阶段。优先解析 Issue 对应 TASK / branch / worktree；若当前脚本尚不支持 Issue-first，则请求 TASK_ID 并使用兼容路径。只调用 scripts/ai/dispatch_task.sh，不重新解释任务，不修改权限，不进入 dev。
```

## Dev phase (after user approves plan)

```text
我已确认这个 plan。请继续开发，但必须遵守：

1. 确认 git status --short --branch。
2. 先运行 scripts/ai/approve_task.sh --task <TASK_ID>（仅在我已明确批准后）。
3. 依次执行：
   scripts/ai/dispatch_task.sh <TASK_ID> dev --json
   scripts/ai/dispatch_task.sh <TASK_ID> test --json
   scripts/ai/dispatch_task.sh <TASK_ID> review --json
   scripts/ai/dispatch_task.sh <TASK_ID> result --json
4. 任一阶段失败立即停止，不循环重试。
5. 不要 push，不要 merge，不要 release，不要部署。
6. 输出：
   - 分支名
   - 修改文件
   - git diff --stat
   - 测试命令与结果
   - .ai/results/<TASK_ID>/execution_summary.md
   - .ai/results/<TASK_ID>/{stage}.log 路径
   - 风险点
   - 需要同步给浏览器 GPT 的文件
```

Shorter template (verbatim):

```text
已批准 Issue #N / TASK-xxx 开发。执行 dev、test、review、result；任一阶段失败立即停止，不自动 push、merge 或 deploy。
```
