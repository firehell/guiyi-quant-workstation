# 任务状态机说明（17 状态 V2）

> 版本：V2.0 (2026-07-13) | 升级自：10 状态 Baseline v1.0
> 配套：`configs/ai/schemas/task-v2.0.schema.json`、`TASK_SCHEMA_V2.md`
> 适用：WorkBuddy 维护状态机；CodeBuddy/Codex 按状态调用脚本；用户在每个确认点决策。

---

## 1. 状态机总图（17 状态）

```text
正向主线：
DRAFT → REQUIREMENT_READY → PLAN_READY → APPROVED → EXECUTING → TESTING → REVIEWING → DELIVERY_READY → CLOSED

批准分离：
PLAN_READY ──approval_scope=[plan]──▶ APPROVED
PLAN_READY ──approval_scope=[plan,code]──▶ APPROVED（含代码许可）
PLAN_READY ──approval_scope=[plan,code,production_write]──▶ APPROVED（含生产写入许可）

终端跳过：
DRAFT ──▶ SKIPPED_NOT_APPLICABLE
DRAFT ──▶ SKIPPED_WITH_REASON
任何状态 ──▶ CANCELLED

阻塞路径：
任何工作态 ──▶ BLOCKED ──▶ (恢复原状态)
任何状态 ──▶ BLOCKED_BY_DEPENDENCY ──▶ (前置 CLOSED 后自动恢复)

失败恢复：
EXECUTING/TESTING/REVIEWING ──▶ FAILED → REPLAN → PLAN_READY
FAILED → CANCELLED / DRAFT

Gate 标记：
REVIEWING → GATE_PASSED → DELIVERY_READY
```

---

## 2. 完整状态定义

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

---

## 3. 状态权限矩阵

| 状态 | route | plan | dev | fix | test | review | result |
|------|-------|------|-----|-----|------|--------|--------|
| DRAFT | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| REQUIREMENT_READY | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| PLAN_READY | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| APPROVED | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| EXECUTING | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| TESTING | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| REVIEWING | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| DELIVERY_READY | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| GATE_PASSED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| CLOSED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| BLOCKED | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| BLOCKED_BY_DEPENDENCY | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| FAILED | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| REPLAN | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| CANCELLED | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SKIPPED_NOT_APPLICABLE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| SKIPPED_WITH_REASON | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 4. V1 → V2 状态映射

| V1 状态（10） | V2 状态（17） | 说明 |
|-------------|-------------|------|
| IDEA | **DRAFT** | 更通用的命名 |
| REQUIREMENT_READY | REQUIREMENT_READY | 不变 |
| PLAN_READY | PLAN_READY | 不变 |
| APPROVED_DEV | **APPROVED** | 去 _DEV 后缀，approval_scope 独立声明 |
| CODING | **EXECUTING** | 更通用 |
| TESTING | TESTING | 不变 |
| — | **REVIEWING** | 新增：Code Review 阶段 |
| DELIVERY_READY | DELIVERY_READY | 不变 |
| — | **GATE_PASSED** | 新增：Gate 通过标记 |
| CLOSED | CLOSED | 不变 |
| PAUSED | **BLOCKED** | 更语义化 |
| — | **BLOCKED_BY_DEPENDENCY** | 新增：自动检测前置依赖 |
| FAILED | FAILED | 不变 |
| REPLAN | REPLAN | 不变 |
| CANCELLED | CANCELLED | 不变 |
| — | **SKIPPED_NOT_APPLICABLE** | 新增：静默跳过 |
| — | **SKIPPED_WITH_REASON** | 新增：带原因跳过 |

---

## 5. 风险等级 (R0-R3)

| 等级 | 名称 | 触发条件 | Gate 行为 |
|------|------|---------|----------|
| **R0** | 致命风险 | .env / token / 自动交易 / rm -rf data | 阻断所有自动执行，需 external_review |
| **R1** | 高风险 | strategies/ / backtest/ / 数据库 / 风控 | 需 approval_scope=[plan,code]，Review 强制执行 |
| **R2** | 中风险 | services/ / scripts/ / config/ | 标准流程，需 approval_scope=[plan,code] |
| **R3** | 低风险 | 纯文档 / .ai/ / 任务单 | 快速通道，可 approval_scope=[plan] 跳过 Dev/Test/Review |

---

## 6. approval_scope

`approval_scope` 与 `status` 完全分离，独立声明审批范围：

| approval_scope | plan | dev | fix | test | review | result |
|---------------|------|-----|-----|------|--------|--------|
| `[plan]` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `[plan, code]` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `[plan, code, production_write]` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (允许生产写入) |
| `[plan, code, external_review]` | ✅ | ✅ | ✅ | ✅ | ✅ (强制) | ✅ |

---

## 7. 代码实现

状态机由以下文件实现：
- `scripts/ai/lib/status_machine.py` — 17 状态枚举 + 流转校验 + 权限矩阵
- `scripts/ai/lib/risk_resolver.py` — R0-R3 自动推断 + 混合风险归一化
- `scripts/ai/lib/schema_validator.py` — JSON Schema 校验
- `scripts/ai/dispatch_task.sh` — Risk Gate + V2 状态 Gate
- `scripts/ai/_approve_lib.sh` — approval_scope + task_sha256 审批记录

---

> 最后更新：2026-07-13 | V2.0
