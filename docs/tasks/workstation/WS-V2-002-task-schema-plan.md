# WS-V2-002 Plan：冻结 V2 Task Schema、状态机和风险模型

> 状态：RESULT_READY | 风险：R1 | 前置：WS-V2-001 GATE_PASSED
> 分支：codex/workstation-governance-v2 | Base: main @ b50e8f31
> Plan SHA：`39bdb187b13a45404d2ef039595f733055213e81ad7089d00728919bcfe21f5d`
> DEV 完成：17 新增 + 6 修改文件 | 测试：134/134 passed
> Result Bundle：`.ai/results/WS-V2-002/`

---

## 目录

1. [设计原则](#1-设计原则)
2. [Schema 总览](#2-schema-总览)
3. [3.1 状态机 17 状态](#31-状态机-17-状态)
4. [3.2 风险模型 R0-R3](#32-风险模型-r0-r3)
5. [3.3 approval_scope 与 status 分离](#33-approval_scope-与-status-分离)
6. [3.4 Task 级元数据字段](#34-task-级元数据字段)
7. [3.5 Epic 级 readiness_flags schema](#35-epic-级-readiness_flags-schema)
8. [4. 文件结构](#4-文件结构)
9. [5. backward compatibility 迁移策略](#5-backward-compatibility-迁移策略)
10. [6. 测试策略](#6-测试策略)
11. [7. 实现任务拆解](#7-实现任务拆解)
12. [8. 兼容风险评估](#8-兼容风险评估)
13. [9. 与 WS-V2-001 发现的对应](#9-与-ws-v2-001-发现的对应)

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **fail-closed** | 未通过 schema 校验的任务，Dispatcher 拒绝执行，不假设默认值 |
| **渐进兼容** | 新格式以 YAML frontmatter 嵌入现有 `.md`，旧任务零修改可继续工作 |
| **单文件自描述** | 一个 Task 文件 = 完整的机器可读契约 + 人类可读文档 |
| **approval_scope 显式化** | 不再从 status 隐式推断审批范围，`scope: [plan, code, production_write]` 独立声明 |
| **风险驱动门控** | R0/R1 任务有额外 Gate，不依赖 routing_tier（那是模型选择器） |
| **工具链不变** | `dispatch_task.sh`、`_approve_lib.sh`、`task_meta.py` 仅扩展接口，不破坏已有调用 |

---

## 2. Schema 总览

### 2.1 格式：YAML frontmatter + Markdown body

```markdown
---
kind: Task
schema_version: "2.0"
task_id: "WS-V2-003"
epic_id: "WORKSTATION-GOVERNANCE-V2"
status: PLAN_READY
risk_level: R1
work_level: L2
approval_scope: [plan, code]
depends_on: ["WS-V2-001"]
allowed_paths: ["scripts/ai/codex_dev.sh", "scripts/ai/_approve_lib.sh"]
forbidden_paths: ["services/", "data/", ".env"]
resource_locks: ["writer_lock:codex"]
required_tests: ["bash -n scripts/ai/codex_dev.sh", "pytest tests/workstation/"]
model_profile: deep
critical: false
production_write_approved: false
github_issue: "#9"
branch: "codex/workstation-governance-v2"
worktree: "/Volumes/扩展盘/guiyi-parallel/workstation-governance-v2"
owner: "WorkBuddy"
created_at: "2026-07-13"
updated_at: "2026-07-13"
---

# WS-V2-003: 任务标题

... (Markdown body, 与现有任务单 §1-21 兼容) ...
```

### 2.2 字段定义

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `kind` | enum | ✅ | — | `Task` 或 `Epic` |
| `schema_version` | string | ✅ | — | 固定 `"2.0"` |
| `task_id` / `epic_id` | string | ✅ | — | 全局唯一标识 |
| `status` | enum | ✅ | `DRAFT` | 17 状态之一 |
| `risk_level` | enum | ✅ | `R3` | `R0` / `R1` / `R2` / `R3` |
| `work_level` | enum | ✅ | `L2` | `L0` / `L1` / `L2` |
| `approval_scope` | list[enum] | ✅ | `[plan]` | 子集：`plan` / `code` / `production_write` / `external_review` |
| `depends_on` | list[string] | ❌ | `[]` | 前置 task_id 列表 |
| `allowed_paths` | list[string] | ❌ | `[]` | 允许修改的文件/目录 glob |
| `forbidden_paths` | list[string] | ❌ | `[]` | 禁止修改的文件/目录 glob |
| `resource_locks` | list[string] | ❌ | `[]` | 需要的资源锁 |
| `required_tests` | list[string] | ❌ | `[]` | 必须通过的测试命令 |
| `model_profile` | enum | ❌ | `standard` | `fast` / `standard` / `deep` / `critical` |
| `critical` | boolean | ❌ | `false` | 策略/回测/数据库标记 |
| `production_write_approved` | boolean | ❌ | `false` | 生产写入许可 |
| `github_issue` | string | ❌ | `""` | `#N` 格式 |
| `branch` | string | ❌ | `""` | git 分支名 |
| `worktree` | string | ❌ | `""` | worktree 绝对路径 |
| `owner` | string | ❌ | `"WorkBuddy"` | 任务负责人 |
| `created_at` | string | ❌ | `""` | ISO 8601 日期 |
| `updated_at` | string | ❌ | `""` | ISO 8601 日期 |

### 2.3 完整 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://guiyi-quant.dev/schemas/task-v2.0.json",
  "title": "GUIYI Task Schema V2.0",
  "type": "object",
  "required": ["kind", "schema_version", "task_id", "status", "risk_level", "work_level", "approval_scope"],
  "properties": {
    "kind": {"enum": ["Task", "Epic"]},
    "schema_version": {"const": "2.0"},
    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"},
    "epic_id": {"type": "string"},
    "status": {"$ref": "#/$defs/status"},
    "risk_level": {"$ref": "#/$defs/risk_level"},
    "work_level": {"$ref": "#/$defs/work_level"},
    "approval_scope": {
      "type": "array",
      "items": {"enum": ["plan", "code", "production_write", "external_review"]},
      "minItems": 1
    },
    "depends_on": {"type": "array", "items": {"type": "string"}},
    "allowed_paths": {"type": "array", "items": {"type": "string"}},
    "forbidden_paths": {"type": "array", "items": {"type": "string"}},
    "resource_locks": {"type": "array", "items": {"type": "string"}},
    "required_tests": {"type": "array", "items": {"type": "string"}},
    "model_profile": {"enum": ["fast", "standard", "deep", "critical"]},
    "critical": {"type": "boolean"},
    "production_write_approved": {"type": "boolean"},
    "github_issue": {"type": "string"},
    "branch": {"type": "string"},
    "worktree": {"type": "string"},
    "owner": {"type": "string"},
    "created_at": {"type": "string", "format": "date"},
    "updated_at": {"type": "string", "format": "date"}
  },
  "$defs": {
    "status": {
      "enum": [
        "DRAFT", "REQUIREMENT_READY", "PLAN_READY", "APPROVED",
        "EXECUTING", "TESTING", "REVIEWING", "DELIVERY_READY",
        "GATE_PASSED", "CLOSED", "BLOCKED", "BLOCKED_BY_DEPENDENCY",
        "FAILED", "REPLAN", "CANCELLED", "SKIPPED_NOT_APPLICABLE",
        "SKIPPED_WITH_REASON"
      ]
    },
    "risk_level": {"enum": ["R0", "R1", "R2", "R3"]},
    "work_level": {"enum": ["L0", "L1", "L2"]}
  }
}
```

---

## 3.1 状态机 17 状态

### 3.1.1 状态定义

| 状态 | 类型 | 定义 | 进入条件 | 退出条件 |
|------|------|------|---------|---------|
| **DRAFT** | 工作态 | 任务草稿，尚未结构化 | 任务创建 | 需求评审完成 |
| **REQUIREMENT_READY** | 门控态 | PRD + 验收目标就绪 | DRAFT + 需求明确 | 用户确认 PRD |
| **PLAN_READY** | 门控态 | 技术方案完成，待批准 | REQUIREMENT_READY + Plan 产出 | 用户批准 Plan |
| **APPROVED** | 门控态 | Plan 已批准，待执行 | PLAN_READY + 有效审批 JSON | 执行开始 |
| **EXECUTING** | 工作态 | 代码/资产正在生成 | APPROVED + Scope Gate 通过 | 产出完成 + 自检通过 |
| **TESTING** | 工作态 | 自动化测试运行中 | EXECUTING 完成 | 测试全部通过 |
| **REVIEWING** | 工作态 | 人工/自动 Code Review | TESTING 通过 | Review 批准 |
| **DELIVERY_READY** | 门控态 | 待交付，人工 merge/deploy | REVIEWING 通过 | 用户 merge/deploy |
| **GATE_PASSED** | 终态（子流） | 某阶段 Gate 通过标记 | 特定 Gate 通过 | —（标记用） |
| **CLOSED** | 终态 | 已完成归档 | DELIVERY_READY + merge/deploy | — |
| **BLOCKED** | 中断态 | 被外部因素阻塞 | 人工/依赖检测 | 阻塞解除 |
| **BLOCKED_BY_DEPENDENCY** | 中断态 | 前置任务未完成 | `depends_on` 任一未 CLOSED | 所有前置 CLOSED 或 SKIPPED |
| **FAILED** | 中断态 | 执行/测试/Review 不通过 | EXECUTING/TESTING/REVIEWING 失败 | 回滚/重规划/放弃 |
| **REPLAN** | 工作态 | 失败后重新规划 | FAILED + 用户决定重规划 | 新 Plan 完成 |
| **CANCELLED** | 终态 | 任务取消，不可 resume | 人工 cancel | — |
| **SKIPPED_NOT_APPLICABLE** | 终态 | 任务不适用，静默跳过 | 人工标记 | — |
| **SKIPPED_WITH_REASON** | 终态 | 任务跳过，附带原因 | 人工标记 + 填写原因 | — |

### 3.1.2 状态流转图

```text
正向主线：
DRAFT → REQUIREMENT_READY → PLAN_READY → APPROVED → EXECUTING → TESTING → REVIEWING → DELIVERY_READY → CLOSED

批准分离（APPROVED 的细分）：
PLAN_READY ──approval_scope=[plan]──▶ APPROVED
PLAN_READY ──approval_scope=[plan,code]──▶ APPROVED（含代码许可）
PLAN_READY ──approval_scope=[plan,code,production_write]──▶ APPROVED（含生产写入许可）

终端跳过路径：
DRAFT ──▶ SKIPPED_NOT_APPLICABLE
DRAFT ──▶ SKIPPED_WITH_REASON
任何状态 ──▶ CANCELLED

阻塞路径：
任何工作态 ──▶ BLOCKED ──▶ (恢复原状态)
任何状态 ──▶ BLOCKED_BY_DEPENDENCY ──▶ (自动恢复)

失败恢复路径：
EXECUTING/TESTING/REVIEWING ──▶ FAILED
FAILED ──▶ REPLAN ──▶ PLAN_READY
FAILED ──▶ CANCELLED
FAILED ──▶ DRAFT（放弃后新建）

GATE_PASSED 标记路径：
REVIEWING ──▶ GATE_PASSED ──▶ DELIVERY_READY
```

### 3.1.3 与旧状态机（12 状态）的映射

| 旧状态 | 新状态 | 说明 |
|--------|--------|------|
| IDEA | **DRAFT** | 更通用的命名 |
| REQUIREMENT_READY | REQUIREMENT_READY | 不变 |
| PLAN_READY | PLAN_READY | 不变 |
| APPROVED_DEV | **APPROVED** | 去掉 _DEV 后缀，approval_scope 独立声明 |
| CODING | **EXECUTING** | 更通用，含代码/文档/配置生成 |
| TESTING | TESTING | 不变 |
| — | **REVIEWING** | 新增：Code Review 阶段 |
| DELIVERY_READY | DELIVERY_READY | 不变 |
| — | **GATE_PASSED** | 新增：Gate 通过标记（子流） |
| CLOSED | CLOSED | 不变 |
| PAUSED | **BLOCKED** | 更语义化 |
| — | **BLOCKED_BY_DEPENDENCY** | 新增：自动检测前置依赖 |
| FAILED | FAILED | 不变 |
| REPLAN | REPLAN | 不变 |
| CANCELLED | CANCELLED | 不变 |
| — | **SKIPPED_NOT_APPLICABLE** | 新增：静默跳过 |
| — | **SKIPPED_WITH_REASON** | 新增：带原因跳过 |

### 3.1.4 状态权限矩阵

| 状态 | route | plan | dev | fix | test | review | result | pause | cancel |
|------|-------|------|-----|-----|------|--------|--------|-------|--------|
| DRAFT | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| REQUIREMENT_READY | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| PLAN_READY | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| APPROVED | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| EXECUTING | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| TESTING | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| REVIEWING | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ |
| DELIVERY_READY | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| GATE_PASSED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| CLOSED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| BLOCKED | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ |
| BLOCKED_BY_DEPENDENCY | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| FAILED | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| REPLAN | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| CANCELLED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SKIPPED_* | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 3.2 风险模型 R0-R3

### 3.2.1 风险等级定义

| 等级 | 名称 | 定义 | 触发条件（示例） | Gate 行为 |
|------|------|------|-----------------|----------|
| **R0** | 致命风险 | 自动交易/密钥泄露/数据破坏/安全红线 | 涉及 `order.send()` / `.env` 写 / `DROP TABLE` / `rm -rf data/` / token 操作 | **阻断所有自动执行**，需安全专家人工审批 + `approval_scope=[plan,code,external_review]` |
| **R1** | 高风险 | 策略/回测/数据库/风控/信号链路 | 涉及 `strategies/` / `backtest` / `postgres` / `DuckDB` 写 / 信号生成 | 需 `approval_scope=[plan,code]` + Review 阶段必须通过，Dev 前需 dry-run 预览 |
| **R2** | 中风险 | 一般代码/配置变更 | 涉及 `services/` / `apps/` / `scripts/` / `config/` | 标准流程，需 `approval_scope=[plan,code]` |
| **R3** | 低风险 | 纯文档/工作流/AI 编排 | 仅 `docs/` / `.ai/` / 任务单 | 快速通道，可设 `approval_scope=[plan]` 跳过 Dev/Test/Review |

### 3.2.2 风险自动推断规则（`resolve_risk_level`）

当任务单未显式声明 `risk_level` 时，按以下规则自动推断：

```python
def resolve_risk_level(meta: TaskMeta, text: str) -> str:
    # R0 检测：关键词 + 路径组合
    r0_paths = [".env", "token", "webhook", "secrets", "credentials"]
    r0_keywords = [
        r"自动交易", r"auto.*order", r"send_order", r"DROP\s+TABLE",
        r"rm\s+-rf\s+data", r"密钥", r"token\s*=", r"密码"
    ]
    if _matches_any_path(meta.allowed_paths, r0_paths) or _matches_any(text, r0_keywords):
        return "R0"

    # R1 检测：策略/回测/数据库写入/风控/信号
    r1_paths = ["strategies/", "backtest/", "indicators/", "signals/"]
    r1_keywords = [
        r"策略", r"回测", r"\bEMA\b", r"\bMACD\b", r"信号生成",
        r"风控", r"POSITION", r"止损", r"止盈", r"仓位"
    ]
    if _matches_any_path(meta.allowed_paths, r1_paths) or _matches_any(text, r1_keywords):
        return "R1"

    # R2 检测：代码/配置变更
    r2_paths = ["services/", "apps/", "packages/", "scripts/", "config/", "src/"]
    if _matches_any_path(meta.allowed_paths, r2_paths):
        return "R2"

    # R3 兜底
    return "R3"
```

### 3.2.3 混合风险任务归一化规则（§3.2.1）

当一个任务同时触及多个风险等级的路径时：

1. **取最高风险**：`max(R0, R1, R2, R3)` 按 `R0 > R1 > R2 > R3`
2. **R0 一票否决**：任何 R0 触发条件命中 → 任务强制 R0
3. **路径优先于关键词推断**：`allowed_paths` 中有 R1 路径 → 至少 R1，即使正文无策略关键词
4. **人工可升级不可降级**：用户可以手动声明更高的 `risk_level`（如把 R2 改为 R1），**不可以**把 R0 降为 R1
5. **Risk Resolution Record**：自动推断结果写入 `.ai/results/<ID>/risk_resolution.json`，记录推断依据

### 3.2.4 Risk Gate 在 Dispatcher 中的位置

```
route → plan → [Risk Gate] → [Issue Gate] → [Branch Gate] → [Worktree Gate] → dev/fix/test/review/result
```

Risk Gate 规则：
- R0 任务：在 `plan` 之后、**任何写操作之前**阻断。必须 `approval_scope` 包含 `external_review`
- R1 任务：在 `approve` 阶段检查 `approval_scope` 是否包含 `code`；`review` 阶段**强制**执行
- R2 任务：标准 Gate 链
- R3 任务：自动通过 Risk Gate，L0 任务可跳过 Dev/Test/Review

---

## 3.3 approval_scope 与 status 分离

### 3.3.1 问题

当前设计：`status=APPROVED_DEV` 隐式表示"代码变更已获批准"。这导致：
- 无法区分"Plan 已批准"和"代码已批准"
- 无法表达"仅批准 Plan，代码待审"
- production_write 审批与 status 绑死

### 3.3.2 新设计

`approval_scope` 是一个独立数组，与 `status` 解耦：

```yaml
status: APPROVED
approval_scope: [plan, code]         # Plan + 代码变更均已批准
# 或
status: APPROVED
approval_scope: [plan]               # 仅批准 Plan，代码待批
# 或
status: APPROVED
approval_scope: [plan, code, production_write]  # 含生产写入
```

**`status=APPROVED` 的含义变为**："任务已进入可执行状态"。具体能执行什么由 `approval_scope` 决定：

| approval_scope | plan | dev | fix | test | review | result |
|---------------|------|-----|-----|------|--------|--------|
| `[plan]` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `[plan, code]` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `[plan, code, production_write]` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (允许生产写入) |
| `[plan, code, external_review]` | ✅ | ✅ | ✅ | ✅ | ✅ (强制) | ✅ |

### 3.3.3 approval_scope 与 risk_level 的约束

| risk_level | 最低 approval_scope | 说明 |
|------------|-------------------|------|
| R0 | `[plan, code, external_review]` | 必须外部审查 |
| R1 | `[plan, code]` | 必须代码审批 |
| R2 | `[plan, code]` | 标准审批 |
| R3 | `[plan]` | 允许仅审批 Plan |

`approval_scope` 不足时，Dispatcher 在 Stage Gate 阶段报错（fail-closed）。

### 3.3.4 审批记录 JSON 扩展

```json
{
  "schema_version": "2.0",
  "task_id": "WS-V2-003",
  "task_file": "docs/tasks/workstation/WS-V2-003.md",
  "branch": "codex/workstation-governance-v2",
  "approval_scope": ["plan", "code"],
  "plan_sha256": "f7ad9fa...",
  "task_sha256": "abc123...",
  "risk_level": "R1",
  "approved_at": "2026-07-13T16:00:00Z",
  "approved_by": "human",
  "pre_existing_changes": []
}
```

关键变化：新增 `approval_scope` 字段和 `task_sha256` 字段（解决 WS-V2-001 发现的 TASK SHA 一致性 Gap）。

---

## 3.4 Task 级元数据字段

所有字段已在 §2.2 定义。以下着重说明与旧字段的差异：

| 旧字段 | 新字段 | 变化 |
|--------|--------|------|
| 无 | `schema_version` | 新增：格式版本 |
| 无 | `risk_level` | 新增：R0-R3 |
| 无 | `approval_scope` | 新增：审批范围 |
| 无 | `depends_on` | 新增：前置依赖 |
| `required_tests`（§18 fenced bash） | `required_tests`（YAML list） | 格式变化：正文 → 元数据 |
| 无 | `model_profile` | 新增：模型选择器 |
| `Critical` | `critical` | 类型不变，位置从表格到 YAML |
| `Production Write Approved` | `production_write_approved` | 类型不变 |

**硬编码模型名**：`model_profile` 使用抽象 profile 名（fast/standard/deep/critical），不在每个任务中硬编码具体模型名。映射在 `configs/ai/profile_templates/` 中。

---

## 3.5 Epic 级 readiness_flags schema

### 3.5.1 Epic YAML 结构

```yaml
---
kind: Epic
schema_version: "2.0"
epic_id: "WORKSTATION-GOVERNANCE-V2"
title: "工作站治理能力 V2 升级"
status: EXECUTING
risk_level: R1
owner: "WorkBuddy"
tasks: ["WS-V2-001", "WS-V2-002", "WS-V2-003", "WS-V2-004", "WS-V2-005",
        "WS-V2-006", "WS-V2-007", "WS-V2-008", "WS-V2-009"]
readiness_flags:
  ws_v2_001_gate_passed: true
  ws_v2_002_plan_approved: false
  all_docs_reviewed: false
  demo_passed: false
created_at: "2026-07-13"
---
```

### 3.5.2 readiness_flags 类型定义

```yaml
readiness_flags:
  type: object
  additionalProperties:
    type: boolean
  description: >
    每个 key 对应一个 readiness 条件。所有值为 true 时 Epic 可进入
    下一阶段（如合并 main）。Dispatcher 在 Epic 级 route 阶段检查。
```

### 3.5.3 readiness_flags 读写校验规则

- **写**：只能由对应 Task 的 `collect_result.sh` 或人工通过 `epic_set_flag.sh` 修改
- **读**：`dispatch_task.sh --epic <EPIC_ID> route` 返回所有 flag 状态
- **校验**：若任务要求 `readiness_flags` 有特定 key 为 true 而实际上为 false，Stage Gate 阻断
- **不可变历史**：每次 flag 变更记录到 `.ai/results/<EPIC_ID>/readiness_log.jsonl`

---

## 4. 文件结构

### 4.1 新增文件

```
scripts/ai/lib/
├── schema_validator.py          # JSON Schema 校验器（验证 YAML frontmatter）
├── risk_resolver.py             # R0-R3 自动推断 + 混合任务归一化
├── status_machine.py            # 17 状态状态机（valid_transition / allowed_stages）
├── epic_manager.py              # Epic 读写 + readiness_flags 管理
└── compat_reader.py             # 旧任务兼容读取（markdown table → TaskMeta V2）

configs/ai/schemas/
├── task-v2.0.schema.json        # Task JSON Schema（§2.3）
└── epic-v2.0.schema.json        # Epic JSON Schema（§3.5）

docs/workstation/
└── TASK_SCHEMA_V2.md            # Schema 说明文档（供人类阅读）

docs/tasks/workstation/
├── WS-V2-002-task-schema-plan.md   # 本 Plan
└── EXAMPLE-TASK-V2.md              # 示例 Task（YAML frontmatter + Markdown body）

tests/workstation/
├── test_schema_validator.py     # Schema 校验单测
├── test_risk_resolver.py        # 风险推断单测
├── test_status_machine.py       # 状态机单测
├── test_compat_reader.py        # 旧任务兼容单测
├── test_epic_manager.py         # Epic 读写单测
└── fixtures/
    ├── sample_task_v2.md        # 标准 V2 Task
    ├── sample_epic_v2.md        # 标准 V2 Epic
    ├── old_task_L2.md           # 旧格式 L2 Task（兼容测试）
    └── old_task_L0.md           # 旧格式 L0 Task（兼容测试）
```

### 4.2 修改文件

| 文件 | 修改内容 | 原因 |
|------|---------|------|
| `scripts/ai/lib/task_meta.py` | 新增 `parse_task_v2()` + `resolve_risk_level()` + `resolve_approval_scope()` | 支持 YAML frontmatter 解析 |
| `scripts/ai/_work_level_lib.sh` | `resolve_task_file()` 放宽搜索目录（保持兼容） | 不影响旧任务 |
| `scripts/ai/_approve_lib.sh` | `generate_approval()` 写入 `approval_scope` + `task_sha256` | TASK SHA 一致性 + scope 分离 |
| `scripts/ai/dispatch_task.sh` | `validate_static_gates()` 增加 Risk Gate + approval_scope 检查 | fail-closed |
| `scripts/ai/route_task.sh` | route_json 输出增加 `risk_level` / `approval_scope` | 下游可见 |
| `scripts/ai/codex_dev.sh` | 增加 TASK SHA256 vs 审批时 SHA256 一致性检查 | WS-V2-001 C1 修复 |
| `docs/workflows/status_machine.md` | 更新为 17 状态 + 风险模型 | 文档同步 |

---

## 5. backward compatibility 迁移策略

### 5.1 旧任务零影响保证

- **旧 .md 任务单**（无 YAML frontmatter）：`compat_reader.py` 从 `## 0. 元信息` 表格提取字段，转换为 V2 TaskMeta dataclass
- **缺失的 V2 字段**（risk_level/approval_scope/depends_on）：自动推断（risk_level 走 §3.2.2 推断规则，approval_scope 默认 `[plan, code]`，depends_on 默认 `[]`）
- **旧状态映射**：§3.1.3 的双向映射
- **task_meta.py** 保持 `TaskMeta` dataclass 对外接口不变，内部根据 `schema_version` 分流

### 5.2 兼容读取决策树

```
parse_task_file(path)
  │
  ├── 有 YAML frontmatter?
  │     ├── schema_version == "2.0" → 直接解析 YAML → TaskMeta V2
  │     └── 未知版本 → raise TaskMetaError("unsupported schema_version")
  │
  └── 无 YAML frontmatter?
        └── 旧格式兼容 → extract from ## 0. 元信息 table → TaskMeta V2（推断缺失字段）
```

### 5.3 迁移提示而非强制

- `task_meta.py` 在解析旧格式任务时，输出 warning（stderr）提示"建议迁移到 V2 YAML frontmatter"
- 不自动批量转换旧文件
- 提供可选脚本 `migrate_task_to_v2.sh` 做单任务迁移（读旧→写新，人工 review diff）

### 5.4 渐进迁移路径

```
Phase 1：工具链双读（本任务完成后）
  - parse_task_file() 同时支持 V1 markdown 和 V2 YAML
  - 新任务强制使用 V2 格式

Phase 2：存量迁移（由后续 Epic 覆盖）
  - 提供 migrate_task_to_v2.sh 脚本
  - 逐批迁移旧任务（人工确认每次迁移）

Phase 3：旧格式废弃（未来）
  - task_meta.py 不再支持非 YAML frontmatter 格式
  - 删除 compat_reader.py
```

---

## 6. 测试策略

### 6.1 单元测试

| 测试文件 | 覆盖 | 关键用例 |
|---------|------|---------|
| `test_schema_validator.py` | JSON Schema 校验 | 有效/无效 YAML、缺失必需字段、枚举越界、depends_on 循环检测、approval_scope 空数组 |
| `test_risk_resolver.py` | R0-R3 推断 | 混合路径取最高、.env 触发 R0、strategies/ 触发 R1、纯 docs 保持 R3、手动升级不可降级 |
| `test_status_machine.py` | 17 状态流转 | 有效/无效流转、中断态恢复、终态不可流转、BLOCKED_BY_DEPENDENCY 自动恢复 |
| `test_compat_reader.py` | 旧任务兼容 | 旧 L2 任务完整解析、旧 L0 任务无 worktree 不报错、缺失字段推断值正确 |
| `test_epic_manager.py` | Epic 读写 | readiness_flags 读写、并发安全、flag 不可变历史 |

### 6.2 集成测试

| 测试 | 内容 |
|------|------|
| Dispatcher 读 V2 Task | `dispatch_task.sh EXAMPLE-TASK-V2 route --dry-run` 输出正确 route.json |
| Dispatcher 读旧 Task | `dispatch_task.sh TASK-2026-07-11-002 route --dry-run` 输出正确 route.json |
| Risk Gate R0 阻断 | R0 任务执行 `dev` 阶段被阻断 |
| approval_scope 不足阻断 | `scope=[plan]` 的任务执行 `dev` 被阻断 |
| Status 不允许 | `CANCELLED` 任务执行 `dev` 被阻断 |

### 6.3 示例文件

`docs/tasks/workstation/EXAMPLE-TASK-V2.md` 作为完整示范，覆盖：
- YAML frontmatter 全字段
- R1 风险等级
- depends_on 依赖链
- 17 状态的注释说明

---

## 7. 实现任务拆解

| 子任务 | 产出 | 预估变更量 |
|--------|------|-----------|
| 7.1 定义 JSON Schema | `configs/ai/schemas/task-v2.0.schema.json` + `epic-v2.0.schema.json` | ~150 行 JSON |
| 7.2 实现 schema_validator.py | 校验函数 + 错误报告 | ~200 行 Python |
| 7.3 实现 risk_resolver.py | R0-R3 推断 + 混合风险归一化 | ~120 行 Python |
| 7.4 实现 status_machine.py | 17 状态流转 + 权限矩阵 | ~180 行 Python |
| 7.5 实现 compat_reader.py | 旧任务 YAML 转换 | ~150 行 Python |
| 7.6 实现 epic_manager.py | Epic 读写 + readiness_flags | ~160 行 Python |
| 7.7 扩展 task_meta.py | parse_task_v2() + 双格式分流 | 修改 ~60 行 |
| 7.8 修改 _approve_lib.sh | approval_scope + task_sha256 | 修改 ~30 行 |
| 7.9 修改 dispatch_task.sh | Risk Gate + approval_scope Gate | 修改 ~40 行 |
| 7.10 修改其他脚本 | route_task/codex_dev 等 | 修改 ~50 行 |
| 7.11 编写测试 | 5 个测试文件 + fixtures | ~600 行 Python |
| 7.12 编写示例和文档 | EXAMPLE-TASK-V2.md + TASK_SCHEMA_V2.md + status_machine.md 更新 | ~400 行 Markdown |

---

## 8. 兼容风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 旧任务 Dispatcher 调用失败 | P0 | compat_reader.py 100% 覆盖旧格式 + 集成测试 |
| status 映射导致旧流程卡死 | P1 | 双向映射表 + test_compat_reader 全覆盖 |
| approval_scope 分离后旧 Gate 放行 | P1 | fail-closed：缺失 scope → 拒绝；默认 scope=[plan,code] 仅对旧任务生效 |
| R0 推断误报（把文档任务标为 R0） | P2 | 关键词白名单保守；用户可手动降低 risk_level（除真实 R0 外） |
| YAML 解析失败静默 fallback | P1 | 解析失败抛异常，不 fallback 到旧解析器（fail-closed） |
| 46 个旧任务兼容性 | P1 | compat_reader 在 CI 中对所有 `docs/tasks/*.md` 做 dry-run 解析 |

---

## 9. 与 WS-V2-001 发现的对应

| WS-V2-001 发现 | 本任务覆盖 |
|---------------|-----------|
| M1：缺 R0-R3 风险分级 | §3.2 风险模型 + risk_resolver.py |
| C1：codex_dev.sh 不验证 TASK SHA | §3.3.4 审批记录增加 task_sha256 + codex_dev.sh 增加一致性检查（修改列表 §4.2） |
| C4：TASK 模板字段冗余 | §2.2 YAML 单一定义，消除 Status 双写 |
| M8：TASK 状态自动同步 | §3.4 `updated_at` + §3.1.4 状态权限矩阵由 status_machine.py 统一管理 |
| C3：两 lib 函数名冲突 | §3.4 approval_scope 显式化 + task_meta.py 统一入口减少 shell 函数冲突 |
| 状态机 12→17 | §3.1 完整定义 |
| 文档引用缺失 | §4.1 新增 TASK_SCHEMA_V2.md |

---

## 附录 A：与用户需求逐条对应

| 用户要求 | Plan 节 |
|---------|--------|
| 1. 新增 Epic 和 Task YAML schema | §2、§3.5 |
| 2. 定义 17 状态 | §3.1 |
| 3. 定义 R0-R3 + 混合风险归一化 | §3.2 |
| 4. approval_scope 与 status 分离 | §3.3 |
| 5. depends_on / allowed_paths / forbidden_paths / resource_locks / required_tests / model_profile | §2.2 |
| 5(b). Epic readiness_flags schema + 读写校验测试 | §3.5 |
| 6. 旧任务兼容 | §5 |
| 7. schema 校验测试 + 示例 Task | §6、§7 |
| 8. 更新工作流文档 | §4.2（status_machine.md）+ §4.1（TASK_SCHEMA_V2.md） |
| 禁止修改业务代码/数据 | ✅ 仅改 scripts/ai/ + 新增 configs/tests/docs |
| 禁止删除旧任务 | ✅ §5 兼容读取 |
| 禁止硬编码模型名 | ✅ model_profile 使用抽象名 |
| 新旧任务 Dispatcher 安全识别 | ✅ §5.2 决策树 |
| 未通过 schema 的 fail-closed | ✅ §1 原则 |
| approval scope 不再由 status 隐式推断 | ✅ §3.3 |
| 有单元测试 | ✅ §6、§7.11 |

---

> Plan 完成时间：2026-07-13 | 下一步：等待人工审批
