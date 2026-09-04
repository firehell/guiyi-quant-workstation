---
task_id: DEMO-20260715-003-github-native-v3-final-e2E
risk_level: R0
work_level: demo
approval_scope: task-space-only
allowed_paths:
  - docs/tasks/DEMO-20260715-003-github-native-v3-final-e2e.md
forbidden_paths:
  - main
  - business_code
  - production_data
  - dispatcher_execution
required_tests:
  - task-schema-validation
  - github-native-v3-artifact-check
  - draft-pr-existence-check
github_issue: 22
branch: task/demo-20260715-003-github-native-v3-final-e2e
worktree: task/demo-20260715-003-github-native-v3-final-e2e
---

# DEMO-20260715-003-github-native-v3-final-e2e

## Purpose

验证 GitHub Native V3 完整任务流的任务空间创建能力。

## Scope

本任务只创建 GitHub Native 工作空间，不执行实际开发。

禁止：

- Codex 执行
- dispatcher 执行
- approval 执行
- 修改 main

## Target Flow

GPT + GitHub
→ Issue
→ TASK Schema V2
→ task branch
→ Draft PR
→ CodeBuddy Issue-first
→ dispatcher route
→ dispatcher plan
→ approval
→ Codex dev
→ test
→ review
→ result
→ Issue/PR 回填
→ GPT Review
