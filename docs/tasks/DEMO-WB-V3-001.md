---
kind: Task
schema_version: "2.0"
task_id: DEMO-WB-V3-001
title: WorkBuddy Unified V3 Harmless E2E Demo
status: CANCELLED
risk_level: R3
work_level: L2
approval_scope:
  - plan
  - code
  - external_review
allowed_paths:
  - docs/tasks/DEMO-WB-V3-001.md
  - docs/workstation/**
forbidden_paths:
  - apps/**
  - services/**
  - packages/**
  - strategies/**
  - experiments/**
  - data/**
  - database/**
  - migrations/**
  - scripts/ai/**
  - scripts/runtime/**
  - scripts/deploy/**
  - .github/**
  - .env*
required_tests:
  - python3 scripts/ai/lib/schema_validator.py docs/tasks/DEMO-WB-V3-001.md
  - git diff --check
base_branch: main
github_issue: "#27"
github_pr: "#28"
branch: task/demo-wb-v3-001
worktree: "/Volumes/扩展盘/guiyi-parallel/demo-wb-v3-001"
owner: WorkBuddy
created_at: "2026-07-16"
updated_at: "2026-07-18"
---

# DEMO-WB-V3-001：WorkBuddy Unified V3 无害 E2E Demo

## 0. 收口结论

```text
WORKBUDDY_V3_DEMO_ARCHIVED_INCOMPLETE
```

本文件从 `task/demo-wb-v3-001` 文档分支收口到主工程，用于保留 Issue #27 / Draft PR #28 的命名、边界和本地证据位置。该 Demo 未形成可接受的最终 E2E 通过证据，不再作为活跃工作站交付路径。

## 1. 当前事实

| 项 | 结论 |
|---|---|
| Issue | `#27` |
| Draft PR | `#28` |
| Branch | `task/demo-wb-v3-001` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/demo-wb-v3-001`，主工程收口后已删除 |
| 主工程收口日期 | `2026-07-18` |
| 最终状态 | `CANCELLED` / `WORKBUDDY_V3_DEMO_ARCHIVED_INCOMPLETE` |

本地运行证据曾存在于：

```text
.ai/results/DEMO-WB-V3-001/
.ai/approvals/DEMO-WB-V3-001.json
.ai/task-runtime/DEMO-WB-V3-001.json
```

这些 `.ai` 文件是 local-first 运行证据，未作为 Git tracked 内容合入主工程。

## 2. 原目标

原 Demo 目标是验证 WorkBuddy Unified V3 的远程协调链路：

```text
GPT + GitHub
→ Issue
→ TASK
→ WorkBuddy
→ Plan
→ 用户 Approve
→ Codex Dev
→ Test
→ Review
→ Result
→ GPT External Review
→ Merge
```

## 3. 原执行边界

允许修改：

```text
docs/tasks/DEMO-WB-V3-001.md
docs/workstation/**
```

禁止修改：

```text
apps/**
services/**
packages/**
strategies/**
experiments/**
data/**
database/**
migrations/**
scripts/ai/**
scripts/runtime/**
scripts/deploy/**
.github/**
.env*
```

本 Demo 明确不做：

- 不修改业务代码。
- 不修改数据、数据库、migration 或生产配置。
- 不修改 `scripts/ai` 核心逻辑。
- 不执行自动交易、真实通知、生产写入、自动 push / merge / deploy / close。
- 不使用 CodeBuddy 作为新流程主入口。

## 4. 未通过原因

主工程收口时，该 Demo 不能标记为 `WORKBUDDY_V3_DEMO_PASSED`，原因是：

- 证据文档仍有多个 `NOT_VERIFIED` 项。
- WorkBuddy / Test / Review / Result / Delivery / External Review 未形成完整闭环证据。
- 本地 runtime 记录显示最后一次 `dev` 阶段 `exit_code=1`。
- 旧 TASK 契约中存在 `worktree` 空值、证据写入时序不可执行等问题。

因此本次只保留文档事实，不合入任何业务实现，也不声称 Demo 通过。

## 5. 后续处理

允许的后续人工处理：

- 关闭或归档 Issue #27。
- 关闭 Draft PR #28，或将其作为历史对照保留。
- linked worktree `/Volumes/扩展盘/guiyi-parallel/demo-wb-v3-001` 已删除。

禁止将本归档文件解释为：

- WorkBuddy V3 Demo 已通过；
- 外部审查已批准；
- 可自动 merge、deploy 或关闭 Issue；
- 可跳过后续真实业务任务的 gate。
