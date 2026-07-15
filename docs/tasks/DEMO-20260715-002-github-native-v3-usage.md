# DEMO-20260715-002-github-native-v3-usage

## 0. 元信息

- task_id: DEMO-20260715-002-github-native-v3-usage
- risk_level: R0
- work_level: L2
- github_issue: #20
- branch: task/demo-20260715-002-github-native-v3-usage
- status: PLAN_READY

## 1. 目标

验证 GitHub Native V3 控制平面链路：

GPT + GitHub
→ Issue
→ TASK
→ Draft PR
→ CodeBuddy
→ Codex
→ Result
→ GPT Review

## 2. approval_scope

仅允许创建和验证流程文档资产。

需要用户确认后才能进入任何开发阶段。

## 3. allowed_paths

- docs/tasks/DEMO-20260715-002-github-native-v3-usage.md
- docs/workstation/**（仅限必要说明文档）

## 4. forbidden_paths

- apps/**
- packages/**
- services/**
- data/**
- database/**
- migrations/**
- .env*
- 任何生产配置

## 5. required_tests

- git diff --check
- 文档结构检查
- GitHub Issue / TASK / Draft PR 链路检查

## 6. 执行限制

- 不修改业务代码。
- 不修改数据。
- 不修改数据库。
- 不修改配置。
- 不自动 merge。
- 不自动 deploy。

## 7. Deliverables

- GitHub Issue #20
- task branch
- TASK Schema V2 文档
- Draft PR

## 8. Result

待 CodeBuddy / Codex 流程验证后补充。