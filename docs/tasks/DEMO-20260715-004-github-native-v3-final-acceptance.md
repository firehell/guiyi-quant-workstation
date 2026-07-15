---
kind: task
schema_version: V2
task_id: DEMO-20260715-004-github-native-v3-final-acceptance
title: GitHub Native V3 Final Acceptance Demo
status: REQUIREMENT_READY
risk_level: R3
work_level: L2
approval_scope: plan
allowed_paths:
  - docs/tasks/DEMO-20260715-004-github-native-v3-final-acceptance.md
  - docs/workstation/demos/GITHUB_NATIVE_V3_FINAL_ACCEPTANCE.md
forbidden_paths:
  - apps/**
  - services/**
  - packages/**
  - data/**
  - database/**
  - migrations/**
  - .env*
  - configs/**
required_tests:
  - python3 scripts/ai/lib/schema_validator.py docs/tasks/DEMO-20260715-004-github-native-v3-final-acceptance.md
  - git diff --check
  - pytest tests/workstation
github_issue: 24
branch: task/demo-20260715-004-github-native-v3-final-acceptance
worktree: task/demo-20260715-004-github-native-v3-final-acceptance
---

# GitHub Native V3 Final Acceptance Demo

## Goal

Create the final GitHub Native V3 acceptance documentation.

## Scope

This task only validates the GitHub Native workflow artifact chain.

Flow:

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
→ Issue update
→ PR update
→ GPT Review

## Restrictions

Only documentation files are allowed to be changed.

No application code, services, packages, data, database, migrations, environment files, or configuration changes are allowed.
