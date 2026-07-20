# GitHub Draft PR 任务工作区协议

> WS-GH-007：Draft PR 是任务从 GPT 设计到 Codex 交付的共享工作区。它承载 TASK、设计、diff、CI、review 和交付讨论，但不自动 merge。

## 1. 定位

GitHub Native V3 中，一个正式 TASK 对应：

| 对象 | 数量 | 职责 |
|---|---:|---|
| GitHub Issue | 1 | 生命周期、远程入口、状态、讨论 |
| task branch | 1 | TASK、设计文档和后续实现所在分支 |
| TASK file | 1 | dispatcher / Codex 执行契约 |
| Draft PR | 1 | 设计、diff、CI、review、交付摘要的共享容器 |
| `.ai/results/<TASK_ID>/` | 1 local-first | 本地执行证据，不完整上传 GitHub |

Issue 不取代 TASK，Draft PR 不取代本地 evidence。PR 的存在不代表已经允许 merge、deploy、生产写入或真实交易。

## 2. 标准生命周期

```text
GPT creates Draft PR
-> Plan complete
-> User approval
-> Codex implementation
-> Test / Review / Result
-> Ready for Review
-> GPT external review
-> User merge
```

### 2.1 GPT creates Draft PR

GPT 可以在任务分支初始提交：

- `docs/tasks/<TASK_ID>.md`
- `docs/design/**` 或 `docs/workstation/**` 中的设计文档
- 必要的 ADR / workflow 文档

GPT 默认不得提交：

- 业务代码
- 数据、DB、Parquet、runtime 文件
- `.env`、token、webhook、cookie、账号凭据
- 自动 merge / deploy / release 配置

Draft PR 初始必须关联：

- Related Issue
- Task ID
- TASK path
- risk / work level
- branch
- 初始 scope 和 non-goals

### 2.2 Plan complete

本地 CodeBuddy / Codex 接管 Issue、TASK_ID 或 PR 后：

```bash
scripts/ai/dispatch_task.sh <TASK_ID> plan --json
```

Plan 产物保存在 `.ai/results/<TASK_ID>/plan_result.md`。PR 只同步脱敏摘要和路径引用，不粘贴完整本地日志。

### 2.3 User approval

用户审查 Issue、TASK、Draft PR 和 Plan 摘要后，明确批准进入实现。

批准记录仍以本地 approval gate 为准：

```bash
scripts/ai/approve_task.sh --task <TASK_ID>
```

生产写入、merge、deploy 和真实交易相关授权必须单独确认，不能由 PR 模板勾选项自动推导。

### 2.4 Codex implementation

Codex 是唯一编码执行器。实现必须在同一个 task branch / worktree 内进行：

```bash
scripts/ai/dispatch_task.sh <TASK_ID> dev
scripts/ai/dispatch_task.sh <TASK_ID> test
scripts/ai/dispatch_task.sh <TASK_ID> review
scripts/ai/dispatch_task.sh <TASK_ID> result
```

Codex 不得：

- 改写 `main`
- 超出 TASK allowed paths
- 绕过 approval、scope、resource lock、runtime gate 或 evidence gate
- 自动 push、merge、deploy 或关闭 Issue

### 2.5 Test / Review / Result

PR 必须记录：

- changed files 摘要
- TASK `required_tests`
- CI 结果
- `.ai/results/<TASK_ID>/result_bundle.json` 的脱敏摘要
- evidence index 摘要
- security / data impact
- 未完成项

Result Bundle 保持 local-first。PR comment / body 只同步摘要、路径和关键 Gate 结论，不上传完整日志、凭据、数据库连接、webhook 或本地绝对路径中的敏感信息。

### 2.6 Ready for Review

Draft PR 转 Ready for Review 的条件：

1. TASK 与 Issue 字段一致。
2. Plan 已完成且用户已批准。
3. Codex 实现、测试、review、result 已完成或明确标注未运行原因。
4. CI 已运行或明确标注不可运行原因。
5. PR 模板中的 security / data impact 已填写。
6. R0/R1 已标记 external GPT review required。
7. 未解决项清单已写明。

转 Ready for Review 不等于允许 merge。

### 2.7 GPT external review

R0/R1 任务必须记录外部 GPT Review。R2 任务如涉及 dispatcher、runtime gate、数据链路、策略、回测或生产边界，也建议记录 GPT Review。

GPT Review 输入：

- Related Issue
- TASK file
- PR diff
- CI 结果
- 脱敏 Result Bundle 摘要
- changed files
- unresolved items

GPT Review 输出必须是以下之一：

```text
APPROVE
COMMENT
REQUEST_CHANGES
```

GPT Review 不得直接修改 `main`、自动 merge、deploy、关闭 Issue 或授权生产写入。

### 2.8 User merge

merge gate 只由用户或 Cursor 人工执行。merge 前至少确认：

- PR Ready for Review
- required tests / CI 满足本 TASK 风险级别
- R0/R1 外部 GPT Review 已记录
- 没有未解决的 security / data / runtime blocker
- 用户明确同意 merge

禁止启用 auto-merge。禁止通过 Agent 自动 merge、deploy、release 或触发真实交易。

## 3. 字段一致性

Issue、TASK 和 PR 必须保持下列字段一致：

| 字段 | Issue | TASK | PR |
|---|---|---|---|
| Task ID | required | `task_id` | required |
| TASK path | required | file path | required |
| Related Issue | self | `github_issue` | required |
| Draft PR | required / pending | `github_pr` or runtime cache | self |
| branch | required | `branch` | source branch |
| risk level | required | `risk_level` | required |
| work level | required | `work_level` | required |
| scope | summary | `allowed_paths` / `forbidden_paths` | summary |

如果字段冲突，执行入口必须 fail-closed 或退回人工确认，不得凭聊天记忆继续。

## 4. Label 建议

PR 关联的 Issue 推荐使用：

- `type/task`
- `area/workstation` 或任务主 area
- `status/draft` -> `status/plan-ready` -> `status/approved` -> `status/executing` -> `status/testing` -> `status/reviewing` -> `status/delivery-ready`
- `risk/r0` / `risk/r1` / `risk/r2` / `risk/r3`
- `review/gpt-required`（R0/R1 或关键边界任务）
- `ai/gpt-authored` / `ai/codex-executed`

详见 [`github_labels.md`](github_labels.md)。

## 5. 禁止项

- 禁止一个正式 TASK 对应多个并行 Draft PR。
- 禁止用 PR 描述替代 TASK 执行契约。
- 禁止把 `.ai/results` 完整上传到 PR。
- 禁止自动 merge、auto-merge、自动 deploy、自动 release。
- 禁止 PR 合并触发真实交易或生产写入。
- 禁止 GPT、WorkBuddy、CodeBuddy 或 Codex 关闭高风险 Issue。

## 6. 相关文档

- [`../workstation/GITHUB_NATIVE_CONTROL_PLANE.md`](../workstation/GITHUB_NATIVE_CONTROL_PLANE.md)
- [`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)
- [`github_labels.md`](github_labels.md)
- [`../workstation/TASK_SCHEMA_V3_DESIGN.md`](../workstation/TASK_SCHEMA_V3_DESIGN.md)
- [`.github/PULL_REQUEST_TEMPLATE.md`](../../.github/PULL_REQUEST_TEMPLATE.md)
