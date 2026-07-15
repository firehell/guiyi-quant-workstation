# GPT GitHub PR External Review Workflow

> WS-GH-011: GPT external review 是 GitHub Native V3 的外部架构审查 Gate。它补充 Codex review，但不替代 Codex review、用户批准、merge 决策或部署授权。

## 1. 职责分离

| Review | 执行者 | 主要检查 | 不做 |
|---|---|---|---|
| Codex review | 本地 Codex | 实现正确性、回归风险、测试缺口、scope 越界、安全泄露 | 不关闭 external review required，不代表用户批准 merge |
| GPT external review | 浏览器 GPT / 已授权 GitHub GPT | 目标是否偏离、架构取舍、TASK/Issue/PR 一致性、风险边界、交付摘要可信度 | 不直接改 main，不自动 merge/deploy，不替代 Codex review |
| User review | 用户 / Cursor | 最终验收、merge、deploy、生产写入授权 | 不由脚本自动推导 |

GPT 可以直接在 PR 上提交 GitHub Review：

```text
COMMENT
REQUEST_CHANGES
APPROVE
```

本地 Gate 只读取真实 PR Review 状态，不允许脚本代替 GPT approve 或伪造 review action。

## 2. 风险策略

| Risk | GPT external review 要求 |
|---|---|
| R0 | 必须 GPT external review + 用户最终批准 |
| R1 | 默认必须 GPT external review |
| R2 | 按 TASK `approval_scope`，包含 `external_review` 时必须 |
| R3 | 可选，除非 TASK 显式要求 |

R0/R1 在 external review 缺失、stale 或 `REQUEST_CHANGES` 时，不得进入 close / merge-ready 结论。

## 3. Head SHA 绑定

每条本地 external review 记录必须绑定：

- PR number
- PR head SHA
- review action
- review timestamp
- reviewer type
- blocking findings

记录路径：

```text
.ai/external-reviews/<TASK_ID>.json
```

PR 出现新 commit 后，旧记录的 `head_sha` 与当前 PR `headRefOid` 不一致，Gate 必须标记为 `stale`，需要 GPT 对新 head 重新 review 或重新确认。

## 4. 本地记录命令

```bash
scripts/ai/record_external_review.sh --task <TASK_ID> --json
scripts/ai/record_external_review.sh --task <TASK_ID> --review-author <github-login> --json
scripts/ai/record_external_review.sh --task <TASK_ID> --dry-run --json
```

脚本行为：

- 使用 `gh pr view` 读取当前 PR head SHA。
- 使用 `gh api repos/firehell/guiyi-quant-workstation/pulls/<PR>/reviews` 读取真实 PR Review。
- 只记录 GitHub 返回的 review action。
- `APPROVE` 或无阻断 `COMMENT` 可满足 external review。
- `REQUEST_CHANGES` 或 review body 中出现阻断词时 Gate 阻断。
- 不提交 Review，不 approve，不 dismiss，不关闭 Issue，不修改 PR ready 状态，不 merge。

## 5. PR 更新后的流程

```text
Codex result complete
-> update_pr_from_result.sh --task <TASK_ID> --confirm-issue-ops
-> GPT reviews PR on GitHub
-> record_external_review.sh --task <TASK_ID> --json
-> User checks Gate, CI, result summary, unresolved items
-> User decides Ready / merge / follow-up
```

如果 Codex 或用户随后 push 新 commit：

```text
record_external_review.sh --task <TASK_ID> --json
-> gate_status=stale
-> GPT external review required again
```

## 6. 禁止项

- 禁止把 GPT review 记录手写成通过。
- 禁止把 Codex review 当作 GPT external review。
- 禁止脚本自动 approve PR。
- 禁止脚本自动将 Draft PR 标记 Ready for Review。
- 禁止脚本自动 merge、deploy、release 或关闭 Issue。
- 禁止用 external review 替代用户批准。

## 7. 相关文件

- [`GITHUB_DRAFT_PR_WORKFLOW.md`](GITHUB_DRAFT_PR_WORKFLOW.md)
- [`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)
- [`../../scripts/ai/record_external_review.sh`](../../scripts/ai/record_external_review.sh)
- [`../../scripts/ai/update_pr_from_result.sh`](../../scripts/ai/update_pr_from_result.sh)
