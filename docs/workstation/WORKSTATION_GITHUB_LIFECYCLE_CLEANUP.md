# WorkBuddy V3 GitHub 生命周期人工清理清单

更新时间：2026-07-17

状态：`WORKSTATION_NON_BLOCKING_SUPPORT_MODE`

本文基于 GitHub 只读盘点记录人工处理建议。本任务不执行 close、merge、mark ready、label、push 或 deploy；生命周期清理不阻塞全历史盘点或 Audit V2。

## 读取证据

只读检查覆盖当前 open Issue、open PR 和最近 merged PR。报告不包含 token、cookie、webhook 或凭据值。

## 分类规则

| 分类 | 含义 |
|---|---|
| KEEP_ACTIVE | 当前真实业务仍需保留 |
| KEEP_ACTIVE_NON_BLOCKING | 支持轨仍可继续，但不得成为业务 Gate |
| CLOSE_AFTER_USER_APPROVAL | 交付已合并或任务已被替代；用户核对后关闭或归档 |
| SUPERSEDED | 已被后续 Demo、TASK 或 PR 替代 |
| REVIEW_REQUIRED | 属于业务任务，需按业务证据独立复查 |

## Open Issues

| Issue | 标题 | 分类 | 理由 | 建议动作 |
|---:|---|---|---|---|
| #29 | `TASK-2026-07-16-001: 工作站控制平面修复` | CLOSE_AFTER_USER_APPROVAL | 实现提交 `c209cdbf` 已通过 `d54e0198` 合并到 `main`；2026-07-17 定向复核 `63 passed` | 先回填 merge commit 与测试证据，再由用户关闭或归档 |
| #27 | `DEMO-WB-V3-001: WorkBuddy Unified V3 harmless E2E demo` | CLOSE_AFTER_USER_APPROVAL | 对应 Draft PR #28；主工程已收口归档为 `WORKBUDDY_V3_DEMO_ARCHIVED_INCOMPLETE`，不再作为活跃支持轨 | 用户确认后关闭或归档 |
| #24 | `DEMO-20260715-004-github-native-v3-final-acceptance` | CLOSE_AFTER_USER_APPROVAL | 对应 PR #25 已合并 | 用户确认后关闭 |
| #22 | `DEMO-20260715-003-github-native-v3-final-e2e` | SUPERSEDED | 对应 Draft PR #23 仍 open，已被后续 Demo 路径替代 | 用户确认后关闭 Issue 与 Draft PR，或归档作历史对照 |
| #20 | `DEMO-20260715-002-github-native-v3-usage` | CLOSE_AFTER_USER_APPROVAL | 对应 PR #21 已合并 | 用户确认后关闭 |
| #12 | `TASK-2026-07-11-004: JM 实时 1m 真实 Gate（T1/T3）` | KEEP_ACTIVE | JM runtime / T3-real 真实业务 Gate | 保留 |
| #11 | `TASK-2026-07-11-003: Web 主图多指标切换（EMA overlay）` | REVIEW_REQUIRED | 业务/前端任务，需要页面验收判断 | 独立业务复查 |
| #10 | `TASK-2026-07-11-002: 火天大有指标与策略规范` | REVIEW_REQUIRED | 业务/策略规范任务，需保持 observation-only 边界 | 独立业务复查 |
| #9 | `TASK-2026-07-11-001: 全量历史数据资产盘点（只读审计）` | REVIEW_REQUIRED | 旧数据审计任务需在 Audit V2 口径下重新判断 | 不在工作站清理中关闭 |
| #8 | `GUIYI-DEMO-001: 为 GET /api/health 补充自动化测试` | CLOSE_AFTER_USER_APPROVAL | 旧 Lean / Demo 任务 | 核对无独有未交付内容后关闭 |
| #7 | `[Demo] Lean V1 全链路验证` | CLOSE_AFTER_USER_APPROVAL | 旧 Lean V1 Demo | 核对后关闭 |
| #6 | `归一量化单项目工作站精简收口与 Demo 前置修复` | CLOSE_AFTER_USER_APPROVAL | 已被当前控制平面与支持模式替代 | 核对后关闭 |

## Open Pull Requests

| PR | 标题 | 分类 | 理由 | 建议动作 |
|---:|---|---|---|---|
| #28 | `DEMO-WB-V3-001` | CLOSE_AFTER_USER_APPROVAL | WorkBuddy Demo 交付容器；主工程仅保留未完成归档事实，不合并通过结论 | 用户确认后关闭或归档，不建议作为可合并 PR 继续推进 |
| #23 | `DEMO-20260715-003-github-native-v3-final-e2e` | SUPERSEDED | 对应 Issue #22，已被后续 Demo 路径替代 | 用户确认后关闭，不合并 |

## 命名迁移

GitHub Issue #27 / Draft PR #28 使用 `DEMO-WB-V3-001`。主工程已新增 `docs/tasks/DEMO-WB-V3-001.md` 作为真实命名归档，并保留 `DEMO-WB-V3-FINAL-001` 作为历史占位快照；不得把任一文档解释为 Demo 已通过。

## 人工处理顺序

1. 为 Issue #29 回填 `c209cdbf`、`d54e0198` 和 `63 passed` 的脱敏交付证据，再由用户关闭或归档。
2. 用户确认后关闭或归档 Issue #27 / Draft PR #28；linked worktree 可删除。
3. 用户核对后关闭 #24、#20，以及被替代的 #22 / PR #23。
4. 核对无独有未交付内容后关闭或归档 #6、#7、#8。
5. #9、#10、#11、#12 留给对应业务 Gate，不在工作站清理中处理。

对业务阶段 B 的影响：`不阻塞`。
