# 远程开发流程（Remote Development）

更新时间：2026-07-12

> 配套：[`CODEBUDDY.md`](../../CODEBUDDY.md)、[`ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)、[`AI_WECHAT_WORKFLOW.md`](../AI_WECHAT_WORKFLOW.md)

远程是 **L2 默认入口**（企业微信 / Mac mini 本地仓库）。居家 L1 见 [`HOME_DEVELOPMENT.md`](HOME_DEVELOPMENT.md)。

## 1. 链路

```text
用户想法
  → WorkBuddy：需求拆解、TASK 单、QA 清单、CodeBuddy Prompt
  → 用户审查范围与安全
  → CodeBuddy：只调用 dispatch_task.sh
  → Codex CLI：plan / dev / review（经 dispatcher 子脚本）
  → WorkBuddy：交付报告
  → 用户 / Cursor：人工批准 merge / deploy
```

CodeBuddy 是**远程执行控制器**，不是产品负责人。WorkBuddy **不直接改仓库**。

## 2. CodeBuddy 硬边界

1. 只调用 `scripts/ai/dispatch_task.sh`；不直调 `codex_plan.sh` / `codex_dev.sh`。
2. 不重新解释或扩大 TASK。
3. 不拼接自由 shell 绕过 Gate。
4. 不降低模型档位、不放宽 sandbox。
5. 不 push、merge、deploy。
6. 任一阶段失败立即停止，不循环重试。
7. 返回 `execution_summary.md` 与 `.ai/results/<TASK_ID>/{stage}.log` 路径。

完整规则见 [`CODEBUDDY.md`](../../CODEBUDDY.md)。

## 3. 标准远程序列

```bash
# 会话开始：报告环境
pwd
git rev-parse --show-toplevel
git status --short --branch

# Plan（只读）
scripts/ai/dispatch_task.sh <TASK_ID> plan --json

# 用户批准后
scripts/ai/approve_task.sh --task <TASK_ID>
scripts/ai/dispatch_task.sh <TASK_ID> dev --json
scripts/ai/dispatch_task.sh <TASK_ID> test --json
scripts/ai/dispatch_task.sh <TASK_ID> review --json
scripts/ai/dispatch_task.sh <TASK_ID> result --json
scripts/ai/make_delivery_summary.sh --task <TASK_ID>
```

## 4. 可复制远程 Prompt 模板

### Plan 阶段

```text
执行 TASK-xxx 的 plan 阶段。只调用 scripts/ai/dispatch_task.sh，不重新解释任务，不修改权限，不进入 dev。
```

### Dev 及后续（用户已批准 Plan）

```text
已批准 TASK-xxx 开发。执行 dev、test、review、result；任一阶段失败立即停止，不自动 push、merge 或 deploy。
```

将 `TASK-xxx` 替换为实际 Task ID（如 `TASK-2026-07-12-020-codex-review-results`）。

## 5. L2 Issue 留痕（可选同步）

Plan / Test / Delivery 完成后，CodeBuddy 可同步 GitHub Issue：

```bash
scripts/ai/comment_issue_result.sh <TASK_ID> plan <task_file>
scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY <task_file>
# ... dev/test 后同理
scripts/ai/comment_issue_result.sh <TASK_ID> delivery <task_file>
```

Issue 是远程留痕源；TASK 文件是本地标准源。详见 [`github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)。

## 6. CodeBuddy 回报字段

每次远程执行结束，必须返回：

| 字段 | 来源 |
|------|------|
| TASK Status | TASK 元信息 / 状态机 |
| Branch | `git branch --show-current` |
| Changed files | `git diff --name-only` 或 Result Bundle |
| diff stat | `git diff --stat` |
| 执行的 dispatch 命令 | 实际运行的 stage 列表 |
| 测试结果 | `.ai/results/<TASK_ID>/test.log` 或 execution summary |
| execution_summary | `.ai/results/<TASK_ID>/execution_summary.md` |
| stage logs | `.ai/results/<TASK_ID>/{plan,dev,test,review,result}.log` |
| 风险与未完成项 | 如实报告，不隐藏失败 |
| 是否需人工 review | 策略/回测/DB/风控默认 yes |

## 7. Merge / Deploy

**不在 Agent 链路内。** 用户或 Cursor 在本地审查 diff、Result Bundle 和交付报告后，人工决定 commit、push、merge、deploy。

## 8. 相关文档

- 工作站架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 模型路由：[`ROUTING_POLICY.md`](ROUTING_POLICY.md)
- 故障处理：[`dispatcher_fault_handling.md`](../workflows/dispatcher_fault_handling.md)
- WorkBuddy Prompt：[`prompts/workbuddy-delivery-team.md`](../../prompts/workbuddy-delivery-team.md)
- CodeBuddy Prompt：[`prompts/codebuddy-execution.md`](../../prompts/codebuddy-execution.md)
