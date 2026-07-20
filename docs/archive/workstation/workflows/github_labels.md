# GitHub Label 体系

> WS-GH-006：GitHub Issue 是生命周期和远程入口；TASK 仍是执行契约。标签用于远程筛选、状态同步和审查路由，不替代 TASK Schema。

## 原则

1. `type/*` 标识 Issue 类型，不表示执行权限。
2. `status/*` 标识生命周期状态，不自动触发 merge、deploy 或真实交易。
3. `risk/*` 与 TASK `risk_level` 对齐，用于 Gate 和 Review 分流。
4. `area/*` 只描述影响范围；跨多个 area 时优先选择主影响面。
5. Legacy 标签保留，历史 Issue 不需要批量迁移或关闭。

## Canonical Labels

### type/*

| Label | 颜色 | 说明 |
|---|---|---|
| `type/task` | `1D76DB` | 标准 TASK 生命周期 Issue |
| `type/bug` | `D73A4A` | 可复现缺陷 |
| `type/design` | `5319E7` | 架构、流程或 ADR 设计 |

### area/*

| Label | 颜色 | 说明 |
|---|---|---|
| `area/workstation` | `5319E7` | AI 工作站、dispatcher、TASK、Issue、PR、Gate |
| `area/data` | `1D76DB` | 数据中心、RQData、Parquet、DuckDB、质量检查 |
| `area/web` | `0E8A16` | Web 工作台、页面、前端交互 |
| `area/indicator` | `B60205` | 指标、策略信号、K 线 marker |
| `area/runtime` | `FBCA04` | 本地 runtime、worker、scheduler、实时观察 |

### status/*

| Label | TASK / Issue 状态 | 说明 |
|---|---|---|
| `status/draft` | `DRAFT` | 远程入口草稿 |
| `status/requirement-ready` | `REQUIREMENT_READY` | TASK 或需求入口已可读 |
| `status/plan-ready` | `PLAN_READY` | Plan 已产出，等待或已进入审批 |
| `status/approved` | `APPROVED` / `APPROVED_DEV` | 用户已批准进入实现或执行 |
| `status/executing` | `CODING` / `EXECUTING` | Codex / CodeBuddy 正在执行 |
| `status/testing` | `TESTING` | 测试或 Gate 验证中 |
| `status/reviewing` | `REVIEWING` | GPT / 人工 / 外部 Review 中 |
| `status/delivery-ready` | `DELIVERY_READY` | 已形成可审查交付 |
| `status/blocked` | `BLOCKED` / `FAILED` / `REPLAN` | 阻塞、失败或需要重做 Plan |
| `status/closed` | `CLOSED` | 用户确认关闭 |

### risk/*

| Label | TASK 风险级别 | 说明 |
|---|---|---|
| `risk/r0` | `R0` | 最高风险，必须外部审查和强审批 |
| `risk/r1` | `R1` | 高风险，涉及核心 Gate 或生产边界 |
| `risk/r2` | `R2` | 中风险，局部代码或规则调整 |
| `risk/r3` | `R3` | 低风险，文档、模板或只读治理 |

### ai/* and review/*

| Label | 说明 |
|---|---|
| `ai/gpt-authored` | GPT 创建或主导需求 / 架构草稿 |
| `ai/codex-executed` | Codex 执行实现或验证 |
| `review/gpt-required` | 需要 GPT 外部审查 |

## Legacy Compatibility Labels

以下标签保留给历史 Issue、V1.2 / V2 脚本和旧查询，不做批量删除：

| Legacy Label | 兼容含义 |
|---|---|
| `type/refactor` | 旧重构类型 |
| `type/docs` | 旧文档类型 |
| `type/test` | 旧测试类型 |
| `area/strategy` | 旧策略 area；新任务优先用 `area/indicator` |
| `area/realtime` | 旧实时 area；新任务优先用 `area/runtime` |
| `area/alert` | 旧通知告警 area |
| `area/backtest` | 旧回测 area |
| `area/deploy` | 旧部署 area |
| `status/approved-dev` | 旧 `APPROVED_DEV` 标签；新任务优先用 `status/approved` |
| `status/coding` | 旧 `CODING` 标签；新任务优先用 `status/executing` |
| `status/failed` | 旧失败标签；新任务优先用 `status/blocked` |
| `status/replan` | 旧重做 Plan 标签；新任务优先用 `status/blocked` |
| `risk/low` | 旧低风险标签；新任务优先用 `risk/r3` |
| `risk/medium` | 旧中风险标签；新任务优先用 `risk/r2` |
| `risk/high` | 旧高风险标签；新任务优先用 `risk/r1` 或 `risk/r0` |
| `ai/workbuddy` | 旧 WorkBuddy 标识 |
| `ai/codebuddy` | 旧 CodeBuddy 标识 |
| `ai/codex` | 旧 Codex 标识 |

## 状态同步

`scripts/ai/update_issue_status.sh` 可继续识别旧 TASK 状态。WS-GH-006 之后推荐映射：

```text
DRAFT             -> status/draft
REQUIREMENT_READY -> status/requirement-ready
PLAN_READY        -> status/plan-ready
APPROVED_DEV      -> status/approved
APPROVED          -> status/approved
CODING            -> status/executing
EXECUTING         -> status/executing
TESTING           -> status/testing
REVIEWING         -> status/reviewing
DELIVERY_READY    -> status/delivery-ready
BLOCKED           -> status/blocked
FAILED            -> status/blocked
REPLAN            -> status/blocked
CLOSED            -> status/closed
```

历史 Issue 上的 legacy `status/*` 标签不需要人工清理；同步脚本在后续写入状态时会移除已知旧状态标签。

## Bootstrap

默认 dry-run：

```bash
scripts/ai/bootstrap_github_labels.sh
```

实际写入 GitHub（需 `gh auth login`）：

```bash
scripts/ai/bootstrap_github_labels.sh --apply
```

脚本幂等：已存在的 label 使用 `gh label edit` 对齐描述和颜色，缺失 label 使用 `gh label create` 创建，不删除历史 Issue 或关闭 Issue。

## 相关文档

- GitHub Native 控制平面：[`../workstation/GITHUB_NATIVE_CONTROL_PLANE.md`](../workstation/GITHUB_NATIVE_CONTROL_PLANE.md)
- Issue 留痕流程：[`github_issue_trace_workflow.md`](github_issue_trace_workflow.md)
- 状态机：[`status_machine.md`](status_machine.md)
- 状态同步脚本：`scripts/ai/update_issue_status.sh`
