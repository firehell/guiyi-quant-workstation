---
kind: Task
schema_version: "2.0"
task_id: DEMO-20260715-002-github-native-v3-usage
status: REQUIREMENT_READY
risk_level: R3
work_level: L2
approval_scope:
  - plan
github_issue: "#20"
branch: task/demo-20260715-002-github-native-v3-usage
allowed_paths:
  - docs/tasks/DEMO-20260715-002-github-native-v3-usage.md
  - docs/workstation/demos/GITHUB_NATIVE_V3_USAGE_DEMO.md
forbidden_paths:
  - apps/**
  - packages/**
  - services/**
  - data/**
  - database/**
  - migrations/**
  - .env*
required_tests:
  - python3 scripts/ai/lib/schema_validator.py docs/tasks/DEMO-20260715-002-github-native-v3-usage.md
  - git diff --check
---

# DEMO-20260715-002-github-native-v3-usage

## 目标

验证 GitHub Native V3 控制平面链路：

GPT + GitHub
→ Issue
→ TASK
→ Draft PR
→ CodeBuddy
→ Codex
→ Result
→ GPT Review

## 执行约束

- 不修改业务代码。
- 不修改数据。
- 不修改数据库。
- 不修改配置。
- 不直接写 main。
- 不 merge。

## 当前阶段

REQUIREMENT_READY。

本 TASK 仅完成需求定义和 Schema V2 验证，不填写虚假的 PLAN_READY，不代表已进入开发执行阶段。

## Deliverables

- GitHub Issue #20
- Branch: task/demo-20260715-002-github-native-v3-usage
- TASK Schema V2 文档
- Draft PR #21
