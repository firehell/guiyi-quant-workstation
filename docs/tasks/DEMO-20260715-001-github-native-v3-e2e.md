---
kind: Task
schema_version: "2.0"
task_id: "DEMO-20260715-001-github-native-v3-e2e"
title: "GitHub Native V3 全链路验证"
status: REQUIREMENT_READY
risk_level: R3
work_level: L2
approval_scope: [plan, code]
depends_on: []
allowed_paths:
  - "docs/tasks/DEMO-20260715-001-github-native-v3-e2e.md"
  - "docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md"
forbidden_paths:
  - ".env"
  - ".env.*"
  - "data/**"
  - "apps/**"
  - "services/**"
  - "packages/**"
  - "alembic/**"
  - "deploy/**"
  - "infra/**"
resource_locks: ["writer_lock:codex"]
required_tests:
  - "grep -F 'DEMO-20260715-001-github-native-v3-e2e' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md"
  - "grep -F 'Codex 是唯一编码执行器' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md"
  - "grep -F '未修改业务代码' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md"
  - "grep -F '未自动 merge、deploy 或真实写入' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md"
  - "git diff --check"
model_profile: fast
critical: false
production_write_approved: false
github_issue: "#18"
github_pr: "#19"
branch: "task/demo-20260715-001-github-native-v3-e2e"
base_branch: "main"
owner: "GPT + GitHub / CodeBuddy / Codex"
created_at: "2026-07-15"
---

# DEMO-20260715-001：GitHub Native V3 全链路验证

> Historical demo note: this task records the pre-WorkBuddy V3 CodeBuddy Issue-first demo path. Current active remote coordination uses WorkBuddy Unified V3 and `scripts/ai/workbuddy_task.sh`; CodeBuddy is compatibility-only.

> 这是无害的文档类 E2E 任务，用于验证 GitHub Native V3 控制平面。GPT 只创建 Issue、任务分支、TASK、占位文档和 Draft PR；最终 Demo 内容必须由 Codex 通过 dispatcher 完成。

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | DEMO-20260715-001-github-native-v3-e2e |
| Work Level | L2 |
| Risk Level | R3 |
| Approval Scope | plan, code |
| GitHub Issue | #18 |
| GitHub PR | #19 |
| Branch | task/demo-20260715-001-github-native-v3-e2e |
| Base Branch | main |
| Worktree | 由本地 GitHub task bootstrap 回填 |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-15 |
| Owner | GPT + GitHub / CodeBuddy / Codex |

## 1. 任务状态

`REQUIREMENT_READY`

## 2. 背景

工作站已完成 GitHub Native V3 架构升级。本任务验证是否真正消除了以下人工操作：

- 手动复制 GPT 设计到 TASK。
- 手动把 TASK 粘贴给 WorkBuddy / CodeBuddy。
- 手动把 Codex diff 或结果上传给 GPT。
- 在多个 AI 会话维护不同任务状态。

## 3. 目标

完整验证：

```text
GPT + GitHub
→ Issue / task branch / TASK / Draft PR
→ WorkBuddy / CodeBuddy Issue-first 接管
→ dispatcher Plan
→ 用户批准
→ Codex Dev / Test / Review / Result
→ Issue / PR 脱敏回填
→ GPT 直接 PR Review
→ 用户决定是否 merge
```

## 4. 不做事项

- 不修改任何业务代码。
- 不修改数据、数据库、Parquet、manifest、checksum 或 quality status。
- 不调用 RQData。
- 不修改 `.env`、凭据、token、webhook、license 或账号配置。
- 不执行真实行情写入、企业微信真实发送、部署或交易。
- 不自动 push、merge、deploy、关闭 Issue。
- 不绕过 dispatcher、approval、scope、worktree 或 evidence Gate。

## 5. 唯一交付文件

Codex 只需完成：

```text
docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md
```

TASK 文件只允许由标准状态同步机制更新，不能扩大任务范围。

## 6. 最终 Demo 文件要求

最终文件必须包含：

1. Task ID 和关联 Issue / PR。
2. 实际执行日期。
3. GitHub Native V3 验证链路。
4. 明确声明 Codex 是唯一编码执行器。
5. 明确声明未修改业务代码。
6. 明确声明未自动 merge、deploy 或真实写入。
7. Plan、Dev、Test、Review、Result 五阶段的状态表。
8. changed files 和测试结论。
9. 未完成项或阻塞项；禁止伪造通过。
10. 用户仍需人工决定是否 merge。

## 7. 允许与禁止路径

### 允许

- `docs/tasks/DEMO-20260715-001-github-native-v3-e2e.md`
- `docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md`

### 禁止

- `.env*`
- `data/**`
- `apps/**`
- `services/**`
- `packages/**`
- `alembic/**`
- `deploy/**`
- `infra/**`
- 其他全部业务与运行文件

## 8. Codex Plan 要求

Plan 阶段只读，必须确认：

- 当前 Issue、TASK、branch、worktree 和 Draft PR 是否一致。
- 只需修改一个 Demo 文档和必要的 TASK 状态。
- required tests 是否可执行。
- 不存在生产写入、数据写入或业务代码风险。
- 若 Issue-first、runtime overlay、PR 回填或 external review Gate 缺失，必须报告并停止伪造通过。

## 9. Codex Dev 要求

用户明确批准 Plan 后：

- 仅完善 Demo 文档。
- 使用实际执行结果填写阶段状态。
- 不写虚假证据。
- 不改变 HEAD、branch 或 TASK 范围。
- 任一 Gate 失败立即停止。

## 10. 测试清单

### 10.0 自动化测试命令

```bash
grep -F 'DEMO-20260715-001-github-native-v3-e2e' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md
grep -F 'Codex 是唯一编码执行器' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md
grep -F '未修改业务代码' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md
grep -F '未自动 merge、deploy 或真实写入' docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md
git diff --check
```

## 11. 验收标准

只有以下条件全部满足才算 Demo 通过：

- [x] GPT 已创建 Issue、task branch、TASK 和 Draft PR。
- [ ] 用户未向 WorkBuddy / CodeBuddy 粘贴 TASK 正文。
- [ ] CodeBuddy 仅通过 Issue `#18` 接管任务。
- [ ] Plan 经 dispatcher 只读执行。
- [ ] Dev 前存在用户明确批准和有效审批凭证。
- [ ] Codex 完成唯一交付文件。
- [ ] Test、Codex Review、Result 全部完成。
- [ ] Issue 和 PR 收到脱敏结果摘要。
- [ ] GPT 直接读取 PR 完成外部 Review。
- [ ] 用户没有上传仓库文件或复制 diff 给 GPT。
- [ ] 没有业务代码、数据、配置或敏感信息改动。
- [ ] 没有自动 merge、deploy、真实写入或交易。

## 12. 失败判定

出现任一情况即为失败或阻塞：

- CodeBuddy 无法通过 Issue 编号解析 TASK。
- 要求用户重新粘贴 TASK 正文。
- 未经批准进入 Dev。
- Codex 绕过 dispatcher。
- 修改允许范围外文件。
- Issue / PR 结果无法回填。
- GPT 无法读取 PR diff 或提交 Review。
- 测试失败却宣称通过。

## 13. 当前执行记录

| 阶段 | 状态 | 证据 |
|---|---|---|
| GPT 创建 Issue | PASSED | Issue #18 |
| GPT 创建 task branch | PASSED | `task/demo-20260715-001-github-native-v3-e2e` |
| GPT 创建 TASK | PASSED | 本文件 |
| GPT 创建占位文档 | PASSED | `docs/workstation/demos/GITHUB_NATIVE_V3_DEMO.md` |
| GPT 创建 Draft PR | PASSED | PR #19 |
| CodeBuddy Issue-first bootstrap | PENDING | — |
| Dispatcher Plan | PENDING | — |
| 用户批准 | PENDING | — |
| Codex Dev/Test/Review/Result | PENDING | — |
| GPT External Review | PENDING | — |
| 用户 Merge | PENDING | 不自动执行 |
