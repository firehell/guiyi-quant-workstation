---
kind: Task
schema_version: "2.0"
task_id: "EXAMPLE-TASK-V2"
epic_id: "EXAMPLE-EPIC"
title: "示例：V2 Task Schema 全字段示范"
status: PLAN_READY
risk_level: R2
work_level: L2
approval_scope: [plan, code]
depends_on: ["EXAMPLE-001"]
allowed_paths:
  - "services/quant-api/tests/test_health.py"
forbidden_paths:
  - "services/quant-api/app/main.py"
  - ".env"
  - "data/"
resource_locks:
  - "writer_lock:codex"
required_tests:
  - "cd services/quant-api && python -m pytest tests/test_health.py -v"
model_profile: standard
critical: false
production_write_approved: false
github_issue: "#99"
branch: "feature/example-v2"
worktree: "/Volumes/扩展盘/guiyi-parallel/example-v2"
owner: "WorkBuddy"
created_at: "2026-07-13"
updated_at: "2026-07-13"
---

# EXAMPLE-TASK-V2: V2 Task Schema 全字段示范

> 任务状态：PLAN_READY | 风险：R2 | 级别：L2

---

## 0. 元信息（从 YAML frontmatter 自动提取）

| 字段 | 值 |
|------|-----|
| Task ID | EXAMPLE-TASK-V2 |
| Status | PLAN_READY |
| Risk Level | R2 |
| Work Level | L2 |
| Approval Scope | plan, code |
| GitHub Issue | #99 |
| Branch | feature/example-v2 |

---

## 1. 任务状态
PLAN_READY — 此任务展示 V2 YAML frontmatter 完整格式。

## 2. 任务类型
文档/示例 — V2 Task Schema 示范。

## 7. Scope（允许/禁止修改）
- `services/quant-api/tests/test_health.py`
- **禁止修改**：`services/quant-api/app/main.py`, `.env`, `data/`

## 10. 数据影响
无。

## 14. 开发步骤
1. 在 `feature/example-v2` 分支工作
2. 修改允许的文件
3. 完成后不提交、不 push，生成 Result Bundle

## 18. 测试命令
```bash
cd services/quant-api && python -m pytest tests/test_health.py -v
```

---

> 本文件为标准 V2 Task 模板。新任务可直接复制此文件并修改 YAML frontmatter。
> Schema 校验：`python3 scripts/ai/lib/schema_validator.py docs/tasks/workstation/EXAMPLE-TASK-V2.md`
