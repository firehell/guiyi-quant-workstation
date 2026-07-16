# 远程开发流程（Remote Development）

更新时间：2026-07-15

> 配套：[`GITHUB_NATIVE_CONTROL_PLANE.md`](GITHUB_NATIVE_CONTROL_PLANE.md)、[`WORKBUDDY_UNIFIED_V3.md`](WORKBUDDY_UNIFIED_V3.md)、[`WORKBUDDY_COMMAND_PROTOCOL.md`](WORKBUDDY_COMMAND_PROTOCOL.md)、[`CODEBUDDY.md`](../../CODEBUDDY.md)、[`ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)、[`AI_WECHAT_WORKFLOW.md`](../AI_WECHAT_WORKFLOW.md)

远程是 **L2 默认入口**（企业微信 / Mac mini 本地仓库）。居家 L1 见 [`HOME_DEVELOPMENT.md`](HOME_DEVELOPMENT.md)。

## 1. 链路

```text
用户想法
  → GPT + GitHub：Issue / task branch / TASK / Draft PR
  → WorkBuddy：远程 PM、需求补充、QA 清单、视觉验收、交付摘要、白名单 facade
  → 用户审查范围与安全
  → workbuddy_task.sh：只调用既有受控脚本
  → Codex CLI：plan / dev / review（经 dispatcher 子脚本）
  → WorkBuddy：交付报告
  → 用户 / Cursor：人工批准 merge / deploy
```

WorkBuddy 是**远程协调入口**，不是代码 writer。它不直接改业务代码，不创建与 GitHub Issue / TASK / Draft PR 脱节的第二套任务状态。CodeBuddy 保留 compatibility-only 回退。

## 2. WorkBuddy 硬边界

1. 默认接收 Issue #N，也兼容 TASK_ID；通过 `scripts/ai/workbuddy_task.sh` 进入固定命令。
2. 不重新解释或扩大 TASK。
3. 不拼接自由 shell 绕过 Gate。
4. 不直调 `codex_plan.sh` / `codex_dev.sh`，不裸调 Codex。
5. 不 push、merge、deploy。
6. 任一阶段失败立即停止，不循环重试。
7. 返回 Issue、Draft PR、CI、result summary、`execution_summary.md` 与 `.ai/results/<TASK_ID>/{stage}.log` 路径。

完整规则见 [`WORKBUDDY_UNIFIED_V3.md`](WORKBUDDY_UNIFIED_V3.md) 与 [`WORKBUDDY_SECURITY_BOUNDARY.md`](WORKBUDDY_SECURITY_BOUNDARY.md)。

## 3. Issue-first 远程命令

企业微信默认只发送 Issue / PR 编号，不再粘贴 TASK 全文或结果文件：

| 用户命令 | WorkBuddy facade 行为 | 禁止事项 |
|----------|----------------|----------|
| `plan --issue #123` | `workbuddy_task.sh plan --issue #123` | 不进入 dev |
| `approve --issue #123 --confirm-user-approval` | 解析 TASK → `approve_task.sh --task <TASK_ID>` | 不修改 Plan |
| `dev --issue #123` | `dispatch_task.sh '#123' dev --json` | 不绕过审批 |
| `status --issue #123` | `dispatch_task.sh '#123' status --json` | 不改变状态 |
| `result --issue #123` | `dispatch_task.sh '#123' result --json` | 不上传完整日志或敏感信息 |
| `cancel --issue #123` | `dispatch_task.sh '#123' cancel --json` | 不 reset、不删除文件 |
| `record-external-review --task <TASK_ID> --pr 124` | `record_external_review.sh --task <TASK_ID> --pr 124 --json` | 不伪造 approve、不 mark ready、不 merge |

TASK_ID 兼容：`PLAN TASK-xxx` 等旧命令仍可使用；兼容入口应回显关联 Issue / Draft PR，并建议后续改用 Issue #N。

## 4. 标准远程序列

```bash
# 会话开始：报告环境
pwd
git rev-parse --show-toplevel
git status --short --branch

# Issue-first bootstrap
scripts/ai/workbuddy_task.sh bootstrap --issue #123

# Plan（只读）
scripts/ai/workbuddy_task.sh plan --issue #123

# 用户批准后
scripts/ai/workbuddy_task.sh approve --issue #123 --confirm-user-approval
scripts/ai/workbuddy_task.sh dev --issue #123
scripts/ai/workbuddy_task.sh test --issue #123
scripts/ai/workbuddy_task.sh review --issue #123
scripts/ai/workbuddy_task.sh result --issue #123
scripts/ai/workbuddy_task.sh delivery --task <TASK_ID>
```

## 5. 可复制远程 Prompt 模板

### Plan 阶段

```text
PLAN #N

请在本地仓库先运行环境只读检查，再执行：
1. scripts/ai/bootstrap_github_task.sh --issue N --json
2. scripts/ai/dispatch_task.sh '#N' plan --json

只做 plan，不进入 dev，不修改权限，不扩大 TASK 范围。返回 Issue、TASK_ID、branch、worktree、Draft PR、CI 状态、plan/result 路径和当前 Gate。
```

### Dev 及后续（用户已批准 Plan）

```text
APPROVE #N
DEV #N

我已明确批准 Issue #N 的 Plan。请先绑定本地 approval，再按 dispatcher 执行 dev、test、review、result。任一阶段失败立即停止；返回 Issue、Draft PR、CI、result summary 和风险。不自动 push、merge、deploy 或真实写入/交易。
```

将 `Issue #N` 或 `TASK-xxx` 替换为实际任务入口。

### PR Review Gate

```text
REVIEW-PR #N

请只读取 PR #N 的真实 GitHub Review，解析关联 TASK，并运行 record_external_review.sh 记录 external review gate。返回 head SHA、review action、stale/blocking 状态。不提交 review、不 approve、不 mark ready、不 merge。
```

## 6. L2 Issue / PR 回流

Plan / Test / Delivery 完成后，受控脚本可同步脱敏摘要到 GitHub Issue / Draft PR：

```bash
scripts/ai/comment_issue_result.sh <TASK_ID> plan <task_file>
scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY <task_file>
# ... dev/test 后同理
scripts/ai/comment_issue_result.sh <TASK_ID> delivery <task_file>
scripts/ai/update_pr_from_result.sh --task <TASK_ID>
```

Issue 是生命周期源；TASK 文件是执行契约；Draft PR 是交付容器。详见 [`GITHUB_NATIVE_CONTROL_PLANE.md`](GITHUB_NATIVE_CONTROL_PLANE.md) 与 [`github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)。

## 7. 远程回报字段

每次远程执行结束，必须返回：

| 字段 | 来源 |
|------|------|
| Issue | GitHub Issue URL / number |
| Draft PR | GitHub PR URL / number |
| CI/checks | GitHub checks summary when available |
| TASK Status | TASK 元信息 / 状态机 |
| Branch | `git branch --show-current` |
| Changed files | `git diff --name-only` 或 Result Bundle |
| diff stat | `git diff --stat` |
| 执行的 dispatch 命令 | 实际运行的 stage 列表 |
| 测试结果 | `.ai/results/<TASK_ID>/test.log` 或 execution summary |
| execution_summary | `.ai/results/<TASK_ID>/execution_summary.md` |
| result summary | Issue / Draft PR 上的脱敏摘要链接或本地路径 |
| external review | R0/R1 或 `REVIEW-PR` 的 GPT Review gate 状态 |
| stage logs | `.ai/results/<TASK_ID>/{plan,dev,test,review,result}.log` |
| 风险与未完成项 | 如实报告，不隐藏失败 |
| 是否需人工 review | 策略/回测/DB/风控默认 yes |

## 8. Merge / Deploy

**不在 Agent 链路内。** 用户或 Cursor 在本地审查 diff、Result Bundle 和交付报告后，人工决定 commit、push、merge、deploy。

## 9. 相关文档

- 工作站架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- GitHub Native 控制平面：[`GITHUB_NATIVE_CONTROL_PLANE.md`](GITHUB_NATIVE_CONTROL_PLANE.md)
- 模型路由：[`ROUTING_POLICY.md`](ROUTING_POLICY.md)
- 故障处理：[`dispatcher_fault_handling.md`](../workflows/dispatcher_fault_handling.md)
- WorkBuddy Prompt：[`prompts/workbuddy-delivery-team.md`](../../prompts/workbuddy-delivery-team.md)
- WorkBuddy Prompt：[`prompts/workbuddy-delivery-team.md`](../../prompts/workbuddy-delivery-team.md)
- CodeBuddy Prompt：[`prompts/codebuddy-execution.md`](../../prompts/codebuddy-execution.md)（compatibility-only）
