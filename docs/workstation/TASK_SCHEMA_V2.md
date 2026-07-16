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
model_profile: balanced
critical: false
production_write_approved: false
production_write_requested: false
github_issue: "#1"
github_pr: ""
branch: "feature/my-task"
base_branch: "main"
base_commit: "c564234d8298ba33198c3820d204f67f4e4ac584"
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
| `task_id` / `epic_id` | string | 全局唯一标识；`task_id` 在 GitHub Native V3 中必须遵守受控 namespace 契约，基础字符集仅允许字母数字和 `_-` |
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
| `model_profile` | 模型能力：`economy` / `balanced` / `deep` |
| `critical` | 策略/回测/数据库标记 |
| `production_write_requested` | 是否明确请求生产写入；默认 `false`，不得由全文自然语言关键词扫描推断 |
| `production_write_approved` | 生产写入许可 |
| `github_issue` | 格式 `#N` |
| `github_pr` | 格式 `#N`，未创建 PR 时可为空 |
| `branch` | git 分支 |
| `base_branch` | 任务分支基准分支，默认 `main` |
| `base_commit` | 可选的工作站基础设施基线 commit；声明后 Issue-first bootstrap 必须验证它是 task branch HEAD 的祖先 |
| `worktree` | worktree 绝对路径 |
| `owner` | 任务负责人，默认 `WorkBuddy` |

---

### GitHub Native V3 Task ID Contract

GitHub Native V3 的 `task_id` 必须使用受控 namespace：

- 允许：`TASK-*`、`WS-GH-*`、`WS-WB-*`、`DEMO-*`、`DATA-*`、`JM-*`。
- 首字符必须是字母，且只能包含 ASCII 字母、数字、下划线和短横线。
- 不允许纯数字；`123` 只能表示 GitHub Issue number，不能表示 Task ID。
- 不允许空值、空 suffix、特殊字符或未知 namespace。

resolver / dispatcher 入口读取 Issue Metadata 时必须按该契约 fail-closed。TASK Schema V2 的历史任务可继续通过兼容层读取，但新建 GitHub Native V3 任务应使用上述 namespace。

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

## Gate 元信息读取顺序

Dispatcher / Worktree Gate 读取 TASK 元信息时必须避免双事实源：

```text
完整 Python task_meta 层（含 runtime overlay）
-> YAML frontmatter
-> 旧 Markdown table
```

规则：

- 当 `.ai/task-runtime/<TASK_ID>.json` 存在时，runtime overlay 仍优先于静态 TASK 中的 `worktree` / `branch`。
- 当 Python metadata 层在精简 worktree 中不可用时，shell Gate 必须能直接读取 YAML frontmatter。
- 只有 YAML frontmatter 不存在或缺少对应字段时，才 fallback 到旧 `## 0. 元信息` Markdown table。
- 如果 YAML frontmatter 与旧 table 同时存在且同一字段冲突，YAML frontmatter 胜出，并输出 warning；不得要求 TASK 维护两套一致字段。

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

---

## V3 静态 / 运行时分层预告

WS-GH-004 已冻结 Task Schema V3 设计，详见 [`TASK_SCHEMA_V3_DESIGN.md`](TASK_SCHEMA_V3_DESIGN.md)。

V2 中 `worktree` 是可选 YAML 字段，值通常是本机绝对路径。该设计适合本地 dispatcher，但不适合 GitHub Native V3 中由 GPT 先创建 TASK / Issue / Draft PR 的场景，因为 GPT 不知道本机 worktree 路径，同一个 TASK 也可能被不同设备接管。

V3 采用静态契约和本地 runtime overlay 分层：

| 层级 | 位置 | 是否提交 | 示例字段 |
|---|---|---:|---|
| 静态任务契约 | `docs/tasks/<TASK_ID>.md` | 是 | `task_id`、`status`、`risk_level`、`work_level`、`approval_scope`、`allowed_paths`、`forbidden_paths`、`required_tests`、`branch`、`base_branch`、`base_commit`、`github_issue`、`github_pr` |
| 本地运行时状态 | `.ai/task-runtime/<TASK_ID>.json` | 否 | `worktree`、`local_branch`、`issue_number`、`pr_number`、`last_dispatch_stage`、`last_sync_at` |

合并优先级：

```text
runtime overlay > static task > compatibility defaults
```

兼容规则：

- V2 TASK 继续有效，不强制迁移历史任务。
- 旧 Markdown TASK 继续通过 `compat_reader.py` 兼容。
- V2 inline `worktree` 继续可读，作为 legacy inline runtime。
- 若新建 V3 / Issue-first TASK 声明 `base_commit`，本地 bootstrap 必须确认该 commit 是 task branch HEAD 的祖先；否则 fail-closed 并提示 rebase。
- 新建 V3 TASK 不应写入 `worktree`；应由本地 bootstrap 写入 `.ai/task-runtime/<TASK_ID>.json`。
- runtime overlay 不得覆盖 `allowed_paths`、`forbidden_paths`、`required_tests`、`risk_level`、`approval_scope` 等安全契约字段。
- `.ai/` 已在 `.gitignore` 中忽略，因此 `.ai/task-runtime/` 默认不提交。

本节只是设计预告；WS-GH-004 不修改现有解析行为。
