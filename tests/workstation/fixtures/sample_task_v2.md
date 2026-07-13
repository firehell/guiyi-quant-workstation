---
kind: Task
schema_version: "2.0"
task_id: "EXAMPLE-TASK-V2"
epic_id: "EXAMPLE-EPIC"
title: "示例 V2 任务：补充健康检查测试"
status: PLAN_READY
risk_level: R2
work_level: L2
approval_scope: [plan, code]
depends_on: ["EXAMPLE-001"]
allowed_paths: ["services/quant-api/tests/test_health.py"]
forbidden_paths: ["services/quant-api/app/main.py", ".env", "data/"]
resource_locks: ["writer_lock:codex"]
required_tests: ["cd services/quant-api && python -m pytest tests/test_health.py -v"]
model_profile: standard
critical: false
production_write_approved: false
github_issue: "#99"
branch: "feature/example-v2"
worktree: "/tmp/example-worktree"
owner: "WorkBuddy"
created_at: "2026-07-13"
updated_at: "2026-07-13"
---

# EXAMPLE-TASK-V2: 示例 V2 任务

> 任务状态：PLAN_READY

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | EXAMPLE-TASK-V2 |
| GitHub Issue | #99 |
| Branch | feature/example-v2 |
| Status | PLAN_READY |
| Risk Level | R2 |
| Work Level | L2 |
| Approval Scope | plan, code |
| Critical | false |

---

## 1. 任务状态
PLAN_READY — 这是一个示例 V2 任务，展示 YAML frontmatter + Markdown body 格式。

## 2. 任务类型
补充自动化测试

## 7. Scope（允许/禁止修改）
- `services/quant-api/tests/test_health.py`
- **禁止修改**: `services/quant-api/app/main.py`, `.env`, `data/`

## 10. 数据影响
无（仅测试文件）

## 14. 开发步骤
1. 在分支工作
2. 修改测试文件
3. 不提交，等待人工处理

## 18. 测试命令
```bash
cd services/quant-api && python -m pytest tests/test_health.py -v
```
