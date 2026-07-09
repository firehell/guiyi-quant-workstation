# GitHub Label 体系

> V1.2 任务留痕用标签。与 [`status_machine.md`](status_machine.md) 状态、`TASK_TEMPLATE.md` 元信息对齐。

---

## 标签分类

### type/* — 任务类型

| Label | 颜色 | 说明 |
|-------|------|------|
| `type/task` | `#1D76DB` | 标准开发任务 |
| `type/bug` | `#D73A4A` | 缺陷修复 |
| `type/refactor` | `#FBCA04` | 重构 |
| `type/docs` | `#0075CA` | 文档 |
| `type/test` | `#0E8A16` | 测试 |

### status/* — 任务状态（与状态机对齐）

| Label | 对应状态 | 说明 |
|-------|----------|------|
| `status/requirement-ready` | `REQUIREMENT_READY` | 任务单就绪 |
| `status/plan-ready` | `PLAN_READY` | 只读 Plan 完成 |
| `status/approved-dev` | `APPROVED_DEV` | 用户批准开发 |
| `status/coding` | `CODING` | 开发中 |
| `status/testing` | `TESTING` | 测试中 |
| `status/delivery-ready` | `DELIVERY_READY` | 可交付 |
| `status/closed` | `CLOSED` | 已完成 |
| `status/failed` | `FAILED` | 执行失败 |
| `status/replan` | `REPLAN` | 需重新 Plan |

### area/* — 涉及模块

| Label | 说明 |
|-------|------|
| `area/workstation` | AI 工作站、流程、脚本 |
| `area/data` | 数据中心、Parquet、RQData |
| `area/strategy` | 策略、信号 |
| `area/realtime` | 实时监听 |
| `area/alert` | 企业微信、通知 |
| `area/backtest` | 回测 |
| `area/deploy` | 部署、运维 |

### risk/* — 风险级别

| Label | 说明 |
|-------|------|
| `risk/low` | 低风险，文档或小修 |
| `risk/medium` | 中风险，局部功能 |
| `risk/high` | 高风险，数据/策略/风控 |

### ai/* — AI 协作角色

| Label | 说明 |
|-------|------|
| `ai/workbuddy` | WorkBuddy 生成任务单或交付报告 |
| `ai/codebuddy` | CodeBuddy 本地执行 |
| `ai/codex` | Codex 开发执行 |

---

## 状态 → Label 映射（脚本用）

`scripts/ai/update_issue_status.sh` 使用下表：

```text
REQUIREMENT_READY → status/requirement-ready
PLAN_READY        → status/plan-ready
APPROVED_DEV      → status/approved-dev
CODING            → status/coding
TESTING           → status/testing
DELIVERY_READY    → status/delivery-ready
CLOSED            → status/closed
FAILED            → status/failed
REPLAN            → status/replan
```

---

## 一次性创建 Labels

在仓库根目录执行（需已 `gh auth login`）：

```bash
# type/*
gh label create "type/task"      --description "标准开发任务" --color "1D76DB" 2>/dev/null || true
gh label create "type/bug"       --description "缺陷修复"   --color "D73A4A" 2>/dev/null || true
gh label create "type/refactor"  --description "重构"       --color "FBCA04" 2>/dev/null || true
gh label create "type/docs"      --description "文档"       --color "0075CA" 2>/dev/null || true
gh label create "type/test"      --description "测试"       --color "0E8A16" 2>/dev/null || true

# status/*
gh label create "status/requirement-ready" --description "任务单就绪"     --color "C5DEF5" 2>/dev/null || true
gh label create "status/plan-ready"        --description "Plan 完成"      --color "BFD4F2" 2>/dev/null || true
gh label create "status/approved-dev"      --description "批准开发"       --color "FEF2C0" 2>/dev/null || true
gh label create "status/coding"            --description "开发中"         --color "FBCA04" 2>/dev/null || true
gh label create "status/testing"           --description "测试中"         --color "F9D0C4" 2>/dev/null || true
gh label create "status/delivery-ready"    --description "可交付"         --color "C2E0C6" 2>/dev/null || true
gh label create "status/closed"            --description "已完成"         --color "0E8A16" 2>/dev/null || true
gh label create "status/failed"            --description "执行失败"       --color "D73A4A" 2>/dev/null || true
gh label create "status/replan"            --description "需重新 Plan"    --color "E99695" 2>/dev/null || true

# area/*
gh label create "area/workstation" --description "AI 工作站" --color "5319E7" 2>/dev/null || true
gh label create "area/data"        --description "数据中心"  --color "1D76DB" 2>/dev/null || true
gh label create "area/strategy"    --description "策略"      --color "B60205" 2>/dev/null || true
gh label create "area/realtime"    --description "实时监听"  --color "FBCA04" 2>/dev/null || true
gh label create "area/alert"       --description "通知告警"  --color "D93F0B" 2>/dev/null || true
gh label create "area/backtest"    --description "回测"      --color "0E8A16" 2>/dev/null || true
gh label create "area/deploy"      --description "部署运维"  --color "006B75" 2>/dev/null || true

# risk/*
gh label create "risk/low"    --description "低风险" --color "C2E0C6" 2>/dev/null || true
gh label create "risk/medium" --description "中风险" --color "FBCA04" 2>/dev/null || true
gh label create "risk/high"   --description "高风险" --color "D73A4A" 2>/dev/null || true

# ai/*
gh label create "ai/workbuddy" --description "WorkBuddy" --color "D4C5F9" 2>/dev/null || true
gh label create "ai/codebuddy" --description "CodeBuddy" --color "C5DEF5" 2>/dev/null || true
gh label create "ai/codex"     --description "Codex"     --color "BFDADC" 2>/dev/null || true
```

验证：

```bash
gh label list | grep -E '^(type|status|area|risk|ai)/'
```

---

## 相关文档

- 状态机：[`status_machine.md`](status_machine.md)
- Issue 留痕流程：[`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)
- 状态同步脚本：`scripts/ai/update_issue_status.sh`
