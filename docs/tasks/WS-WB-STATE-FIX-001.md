---
kind: Task
schema_version: "2.0"
task_id: WS-WB-STATE-FIX-001
title: WorkBuddy Unified V3 status loop fix
status: REQUIREMENT_READY
risk_level: R2
work_level: L1
approval_scope: [plan, code]
allowed_paths:
  - scripts/ai/lib/task_status_transition.py
  - scripts/ai/lib/dispatch_control.py
  - scripts/ai/lib/task_meta.py
  - scripts/ai/lib/route_task.py
  - scripts/ai/lib/github_task_resolver.py
  - scripts/ai/dispatch_task.sh
  - scripts/ai/approve_task.sh
  - scripts/ai/_approve_lib.sh
  - scripts/ai/_work_level_lib.sh
  - tests/workstation/
  - docs/workflows/status_machine.md
  - docs/workflows/ai_delivery_workflow.md
  - docs/workstation/TASK_SCHEMA_V2.md
  - configs/ai/schemas/task-v2.0.schema.json
forbidden_paths:
  - docs/tasks/DEMO-WB-V3-001.md
  - data/**
  - database/**
  - migrations/**
  - strategies/**
  - apps/**
  - services/**
  - .env*
required_tests:
  - python3 -m pytest -q tests/workstation
  - git diff --check
branch: codex/ws-wb-state-fix-001
base_branch: main
base_commit: 3586db39d452043243c3c1b8ee610eee6a450bee
worktree: /Volumes/扩展盘/guiyi-quant-workstation
model_profile: balanced
critical: false
production_write_requested: false
production_write_approved: false
owner: Codex
created_at: "2026-07-16"
updated_at: "2026-07-16"
---

# WS-WB-STATE-FIX-001: WorkBuddy Unified V3 status loop fix

## Goal

Fix the WorkBuddy Unified V3 control-plane status loop so successful single-stage dispatcher operations advance the canonical TASK status, while failed stages never advance success states.

## Scope

- Add one canonical TASK status mutation layer.
- Route all status writes through that layer.
- Update YAML frontmatter status and legacy Markdown `| Status |` compatibility fields together.
- Record status transition evidence under `.ai/results/<TASK_ID>/status_transition.json`.
- Preserve approval gates and ensure approval SHA is bound to the current TASK after Plan promotion.
- Replace free-text production write detection with structured metadata and explicit operation/path rules.

## Out Of Scope

- Do not modify Demo #27 / `DEMO-WB-V3-001`.
- Do not modify business code, data, DB, strategy, or Web app code.
- Do not write DB, Parquet, manifest, checksum, or runtime market data.
- Do not weaken approval, writer lock, dirty workspace, production write, or scope gates.
- Do not implement phased dispatcher status transitions in this task.
- Do not push, merge, deploy, or close remote Issues.

## Acceptance

- `plan` success promotes `REQUIREMENT_READY -> PLAN_READY`.
- `approve_task.sh` success promotes `PLAN_READY -> APPROVED` after approval is generated and validated against the current TASK SHA.
- `dev` single-stage success promotes `APPROVED -> EXECUTING -> TESTING`.
- `test` single-stage success promotes `TESTING -> REVIEWING`.
- `review` single-stage success promotes `REVIEWING -> DELIVERY_READY`.
- Failed stages do not promote success status.
- `production_write_requested` defaults to false and is not inferred from negative natural-language sentences.
- Docs-only tasks classify as production write false.
- Database migration and production deploy tasks classify as production write true.

## Tests

```bash
python3 -m pytest -q tests/workstation
git diff --check
```
