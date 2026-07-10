# 任务状态机说明（10 状态）

> 提炼自：`STATE_MACHINE_TICKET.md` §1–2（归一量化产品与交付工作站 Baseline v1.0）
> 配套：`TASK_TEMPLATE.md`（21 字段）、`ai_delivery_workflow.md`（半自动交付 SOP）、`TASK_MATRIX.md`（18 类任务）
> 适用：WorkBuddy 维护状态机；CodeBuddy/Codex 按状态调用脚本；用户在每个确认点决策。

---

## 1. 状态机总图

```text
IDEA
  │  PM 编号 + 任务单草稿
  ▼
REQUIREMENT_READY  ── 用户确认 PRD / 验收目标
  │
  ▼
PLAN_READY  ── 用户批准 plan（CodeBuddy 调 Codex 只读 plan）
  │
  ▼
APPROVED_DEV  ── 后端产出 Dev / Exec Prompt，准备开发
  │
  ▼
CODING  ── CodeBuddy 调 Codex 开发（默认 dry-run）
  │
  ▼
TESTING  ── CodeBuddy 跑测试，QA 出验收结论
  │
  ▼
DELIVERY_READY  ── 用户最终 review / merge / deploy
  │
  ▼
CLOSED

失败分支：
CODING / TESTING / DELIVERY_READY ──不通过──▶ FAILED
FAILED ──用户决定重规划──▶ REPLAN ──▶ PLAN_READY
FAILED ──用户放弃──▶ IDEA / 丢弃
```

---

## 2. 各状态定义与推进责任

| 状态 | 定义 | 进入条件 | 退出条件 | 必备产物 | 必须人工确认 | 可代执行 |
|------|------|---------|---------|---------|------------|---------|
| **IDEA** | 原始想法雏形 | 用户提出想法 | 初始任务单草稿 | 编号、一句话想法 | 用户提出即默认 | WorkBuddy 起草骨架 |
| **REQUIREMENT_READY** | 需求已明确 | 含 PRD | 用户确认 PRD | PRD、验收目标、任务类型、角色 | **确认 PRD** | WorkBuddy 出 PRD |
| **PLAN_READY** | 技术方案完成待批准 | PRD 确认 + 技术方案 + Plan Prompt | 用户批准 plan | 架构、模块边界、Plan Prompt、测试点 | **批准 plan** | CodeBuddy 调 Codex 只读 plan |
| **APPROVED_DEV** | plan 已批待开发 | PLAN_READY 批准 + Dev/Exec Prompt | 开发开始 | Dev/Exec Prompt、步骤清单 | review Prompt | CodeBuddy 准备入口 |
| **CODING** | Codex 执行开发 | APPROVED_DEV + 调 Codex | 代码写完 + 自检通过 | 代码变更、dry-run、git diff --check | 真实写入/发送授权 | CodeBuddy 调 Codex |
| **TESTING** | 测试验证 | CODING 完成 | 测试通过 | 测试报告、验收结论、回归 | 真实 smoke 授权 | CodeBuddy 跑测试 |
| **DELIVERY_READY** | 待交付 | TESTING pass + 报告 + 合并前检查 | 用户 merge/deploy | 交付报告、合并前检查 | **最终 review / merge / deploy** | WorkBuddy 出报告 |
| **CLOSED** | 已完成归档 | DELIVERY_READY + merge/deploy | 任务结束 | 归档单、交付报告、changelog | merge/deploy 为用户操作 | PM 归档 |
| **FAILED** | 未达预期 | CODING/TESTING/DELIVERY 不通过 | 回滚/重规划/放弃 | 失败原因、影响范围 | **回滚/重规划/放弃决策** | CodeBuddy 回滚（授权后） |
| **REPLAN** | 重新规划 | FAILED 后用户决定重规划 | 新 plan 起草完成 | 复盘、修订 Prompt | 新 plan 仍需批准 | CodeBuddy 调 Codex 只读 replan |

---

## 3. 失败回滚规则

- **不自动回滚**：用户确认后 CodeBuddy 执行 `git revert` / `checkout`。
- 回滚范围限定本次变更；live 状态 / 数据**不自动删**。
- P0 红线级（自动交易 / 误发 / 密钥泄露 / active 污染）：立即止损 + 安全专家一票否决，不自动恢复。

---

## 4. 与脚本调用的映射

| 状态 | 触发脚本 | 模式 |
|------|---------|------|
| PLAN_READY → APPROVED_DEV | `codex_plan.sh --task <ID>` | 只读 |
| APPROVED_DEV → CODING | `codex_dev.sh --task <ID> --plan <plan>` | workspace-write |
| CODING → TESTING | `run_tests.sh --task <ID> --scope all` | dry-run 默认 |
| TESTING → DELIVERY_READY | `collect_result.sh` + `make_delivery_summary.sh` | 脱敏 |

---

> 本说明与工作站基线 Baseline v1.0（2026-07-09）严格一致。状态流转由 WorkBuddy 维护，CodeBuddy/Codex 不得自行越过用户确认点。
