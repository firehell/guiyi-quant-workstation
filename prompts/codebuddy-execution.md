# CodeBuddy Execution Prompt

Use this prompt in Enterprise WeChat after the user has reviewed an Issue / Draft PR or WorkBuddy PM/QA summary.

Default command model:

```text
PLAN #123
APPROVE #123
DEV #123
STATUS #123
RESULT #123
CANCEL #123
REVIEW-PR #124
```

TASK_ID remains compatible, but Issue #N is the default remote input.

## Plan phase

```text
请在 Mac mini 本地 guiyi-quant-workstation 仓库中执行下面 Issue。

执行规则：
1. 先运行 pwd、git rev-parse --show-toplevel、git status --short --branch。
2. 先阅读 AGENTS.md、CODEBUDDY.md、docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md、docs/workstation/REMOTE_DEVELOPMENT.md、docs/CODEX_HANDOFF.md、tasks/current.md。
3. 不允许修改 .env、密钥、token、webhook、账号、cookie、license。
4. 不允许删除或重写 data/raw/、data/processed/、data/parquet/。
5. 不允许自动交易、自动下单、订单草稿、自动 push、merge、release、部署。
6. 只调用 scripts/ai/dispatch_task.sh，不直调 codex_plan.sh / codex_dev.sh，不裸 codex exec。
7. 第一轮只执行 plan 阶段，不进入 dev。
8. 不重新解释或扩大 TASK 范围。
9. 先用 scripts/ai/bootstrap_github_task.sh 解析 Issue #N 对应的 TASK / branch / worktree / Draft PR。
10. 执行：scripts/ai/dispatch_task.sh '#N' plan --json
11. 返回 Issue、TASK_ID、branch、worktree、Draft PR、CI 状态、plan 输出路径、route.json、git status、Gate 状态和 execution_summary 路径供我确认。

任务入口：
PLAN #N
```

Shorter template (verbatim):

```text
PLAN #N

先 bootstrap Issue，再只调用 scripts/ai/dispatch_task.sh '#N' plan --json。不重新解释任务，不修改权限，不进入 dev。返回 Issue、Draft PR、CI、result 路径和当前 Gate。
```

## Dev phase (after user approves plan)

```text
我已确认这个 plan。请继续开发，但必须遵守：

1. 确认 git status --short --branch。
2. 先运行 scripts/ai/approve_task.sh --task <TASK_ID>（仅在我已明确批准后）。
3. 依次执行：
   scripts/ai/dispatch_task.sh '#N' dev --json
   scripts/ai/dispatch_task.sh '#N' test --json
   scripts/ai/dispatch_task.sh '#N' review --json
   scripts/ai/dispatch_task.sh '#N' result --json
4. 任一阶段失败立即停止，不循环重试。
5. 不要 push，不要 merge，不要 release，不要部署。
6. 输出：
   - Issue 链接
   - Draft PR 链接
   - CI/check 状态
   - 分支名
   - 修改文件
   - git diff --stat
   - 测试命令与结果
   - result summary 链接或路径
   - .ai/results/<TASK_ID>/execution_summary.md
   - .ai/results/<TASK_ID>/{stage}.log 路径
   - 风险点
   - 需要同步给浏览器 GPT 的文件
```

Shorter template (verbatim):

```text
APPROVE #N
DEV #N

我已明确批准 Issue #N 的 Plan。请先绑定 approval，再执行 dev、test、review、result；任一阶段失败立即停止，不自动 push、merge 或 deploy。
```

## Status / Result / Cancel / PR Review

```text
STATUS #N

只读返回 Issue、TASK、Draft PR、CI、当前 Gate、最近 result summary 和本地 stage log 路径。不改变状态。
```

```text
RESULT #N

运行 result stage，并将脱敏摘要同步到 Issue / Draft PR。不要上传完整日志、敏感路径、凭据、数据样本或未脱敏异常堆栈。
```

```text
CANCEL #N

取消任务生命周期并停止后续动作。不 reset、不删除本地文件、不关闭 Issue，除非用户另行明确授权。
```

```text
REVIEW-PR #N

只读取 PR #N 的真实 GitHub Review，解析关联 TASK，并记录 GPT external review gate。返回 head SHA、review action、stale/blocking 状态。不提交 review、不 approve、不 mark ready、不 merge。
```
