# GUIYI Task Schema V2.0 — 规范说明

> 版本：2.0 (2026-07-13) | 适用范围：Workstation Governance V2 及以上任务
> 配套：`configs/ai/schemas/task-v2.0.schema.json`、`configs/ai/schemas/epic-v2.0.schema.json`

---

## 概述

V2 Task Schema 引入 **YAML frontmatter + Markdown body** 格式，替代纯 Markdown table 字段定义。核心变化：

1. **机器可读**：YAML frontmatter 可直接被 JSON Schema 校验
2. **approval_scope 分离**：不再从 status 隐式推断审批范围
3. **风险模型 R0-R3**：自动推断 + 人工可升级
4. **17 状态**：新增 REVIEWING / GATE_PASSED / BLOCKED_BY_DEPENDENCY / SKIPPED_*
5. **Epic 支持**：readiness_flags + 任务分组
6. **向下兼容**：旧 Markdown 任务无需修改，compat_reader.py 自动转换

---

## 快速开始

### V2 Task 文件格式

```markdown
---
kind: Task
schema_version: "2.0"
task_id: "MY-TASK-001"
epic_id: "MY-EPIC"
title: "任务标题"
status: DRAFT
risk_level: R2
work_level: L2
approval_scope: [plan, code]
depends_on: ["PREV-TASK-001"]
allowed_paths: ["scripts/ai/"]
forbidden_paths: [".env", "data/"]
resource_locks: ["writer_lock:codex"]
required_tests: ["pytest tests/"]
model_profile: standard
critical: false
production_write_approved: false
github_issue: "#1"
branch: "feature/my-task"
worktree: "/path/to/worktree"
owner: "WorkBuddy"
created_at: "2026-07-13"
---
# MY-TASK-001: 任务标题
（以下是 Markdown body，与旧格式兼容）
```

### V2 Epic 文件格式

```markdown
---
kind: Epic
schema_version: "2.0"
epic_id: "MY-EPIC"
title: "Epic 标题"
status: EXECUTING
risk_level: R1
owner: "WorkBuddy"
tasks: ["MY-TASK-001", "MY-TASK-002"]
readiness_flags:
  all_plans_approved: false
  demo_passed: false
  docs_reviewed: true
created_at: "2026-07-13"
---
# MY-EPIC: Epic 标题
```

---

## 字段说明

### 必需字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | `"Task"` 或 `"Epic"` | 实体类型 |
| `schema_version` | `"2.0"` | 固定版本号 |
| `task_id` / `epic_id` | string | 全局唯一标识，仅允许字母数字和 `_-` |
| `status` | enum | 17 状态之一（见状态表） |
| `risk_level` | `R0` / `R1` / `R2` / `R3` | 风险等级 |
| `work_level` | `L0` / `L1` / `L2` | 工作级别 |
| `approval_scope` | list[enum] | 审批范围：`plan` / `code` / `production_write` / `external_review` |

### 可选字段

| 字段 | 说明 |
|------|------|
| `depends_on` | 前置 task_id 列表 |
| `allowed_paths` | 允许修改的路径 glob |
| `forbidden_paths` | 禁止修改的路径 glob |
| `resource_locks` | 需要的资源锁 |
| `required_tests` | 必须通过的测试命令 |
| `model_profile` | 模型能力：`fast` / `standard` / `deep` / `critical` |
| `critical` | 策略/回测/数据库标记 |
| `production_write_approved` | 生产写入许可 |
| `github_issue` | 格式 `#N` |
| `branch` | git 分支 |
| `worktree` | worktree 绝对路径 |
| `owner` | 任务负责人，默认 `WorkBuddy` |

---

## 状态校验

```bash
# 校验 Task 文件
python3 scripts/ai/lib/schema_validator.py docs/tasks/MY-TASK.md

# 校验 Epic 文件
python3 scripts/ai/lib/schema_validator.py --epic docs/epics/MY-EPIC.md

# 状态流转检查
python3 scripts/ai/lib/status_machine.py check --from DRAFT --to REQUIREMENT_READY
```

## 风险推断

```bash
# CLI 推断风险等级
python3 scripts/ai/lib/risk_resolver.py \
  --task-id MY-TASK \
  --allowed-paths services/api/app.py \
  --body "修改健康检查响应" \
  --output-dir .ai/results/MY-TASK
```

## 从旧格式迁移

旧格式（无 YAML frontmatter）可继续使用，`compat_reader.py` 自动转换。如需显式迁移：

```bash
# 将旧任务转为新格式（人工 review diff）
python3 scripts/ai/lib/compat_reader.py docs/tasks/OLD-TASK.md --json
```

---

## 17 状态速查

| 状态 | 可执行 stage |
|------|------------|
| DRAFT | plan |
| REQUIREMENT_READY | plan |
| PLAN_READY | plan |
| APPROVED | dev, fix |
| EXECUTING | dev, fix |
| TESTING | test, fix |
| REVIEWING | review, fix |
| DELIVERY_READY | result |
| GATE_PASSED | result |
| CLOSED | — |
| BLOCKED | plan, review |
| BLOCKED_BY_DEPENDENCY | plan, review |
| FAILED | fix |
| REPLAN | plan |
| CANCELLED | — |
| SKIPPED_NOT_APPLICABLE | — |
| SKIPPED_WITH_REASON | — |

---

## 风险等级速查

| 等级 | 最低 approval_scope | 说明 |
|------|-------------------|------|
| R0 | `[plan, code, external_review]` | 致命风险，必须外部审查 |
| R1 | `[plan, code]` | 高风险，必须代码审批 + Review |
| R2 | `[plan, code]` | 中风险，标准审批 |
| R3 | `[plan]` | 低风险，可仅审批 Plan |

---

> 完整规范见 `WS-V2-002-task-schema-plan.md` §2-3
