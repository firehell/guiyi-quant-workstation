# WorkBuddy V3 GitHub 生命周期人工清理清单

更新时间：2026-07-16

状态：`WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING`

本文是 Step 4 的只读 GitHub 生命周期报告。它只记录当前 open Issue / PR 与最近 merged PR 的人工处理建议；本轮不执行 close、merge、mark ready、label 或 deploy。

## 读取证据

只读命令：

```bash
gh auth status
gh issue list --state open --limit 50 --json number,title,state,labels,updatedAt,url
gh pr list --state open --limit 50 --json number,title,state,isDraft,headRefName,updatedAt,url
gh pr list --state merged --limit 20 --json number,title,state,isDraft,headRefName,mergedAt,url
```

当前 GitHub 登录用户为 `firehell`。报告不包含 token、cookie、webhook 或凭据值。

## 分类规则

| 分类 | 含义 |
|---|---|
| KEEP_ACTIVE | 当前真实业务或工作站后续仍需要保留 |
| CLOSE_OBSOLETE_AFTER_USER_APPROVAL | 已被新方案、merged PR 或归档文档替代；可关闭但必须用户确认 |
| MERGE_CANDIDATE_REQUIRES_REVIEW | 可能可合并，但必须人工审查 diff、CI 和业务影响 |
| SUPERSEDED | 已被 WorkBuddy V3 / 后续 PR / 新 TASK 替代 |
| REVIEW_REQUIRED | 信息不足或属于业务任务，不在本轮自动清理 |

## Open Issues

| Issue | 标题 | 分类 | 理由 | 建议动作 |
|---:|---|---|---|---|
| #24 | `DEMO-20260715-004-github-native-v3-final-acceptance` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | 对应 PR #25 已 merged；当前又被 `WS-WB-V3-FINAL-001` WorkBuddy V3 迁移替代 | 用户确认后关闭 |
| #22 | `DEMO-20260715-003-github-native-v3-final-e2e` | SUPERSEDED | 仍有关联 Draft PR #23 open，但 WorkBuddy V3 迁移已形成新 Demo 前状态 | 用户确认后关闭 Issue 与 Draft PR，或人工决定是否保留作历史对照 |
| #20 | `DEMO-20260715-002-github-native-v3-usage` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | 对应 PR #21 已 merged，属于 GitHub Native V3 demo 历史项 | 用户确认后关闭 |
| #12 | `TASK-2026-07-11-004: JM 实时 1m 真实 Gate（T1/T3）` | KEEP_ACTIVE | 当前真实业务 Gate：JM runtime / T3-real 仍 pending，不被 WorkBuddy V3 改动 | 保留 |
| #11 | `TASK-2026-07-11-003: Web 主图多指标切换（EMA overlay）` | REVIEW_REQUIRED | 业务/前端任务，可能已有 merged PR，但是否关闭需按页面验收和用户判断 | 人工复查 |
| #10 | `TASK-2026-07-11-002: 火天大有指标与策略规范` | REVIEW_REQUIRED | 业务/策略规范任务，涉及 observation-only 边界，需业务确认 | 人工复查 |
| #9 | `TASK-2026-07-11-001: 全量历史数据资产盘点（只读审计）` | REVIEW_REQUIRED | 数据资产审计历史任务，可能仍影响 DATA_LAYER_PARTIAL 后续专项 | 人工复查 |
| #8 | `GUIYI-DEMO-001: 为 GET /api/health 补充自动化测试` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | Lean / demo 旧任务，已被后续工作站和 runtime 流程替代；若无未合并代码可关闭 | 用户确认后关闭 |
| #7 | `[Demo] Lean V1 全链路验证 — TASK-2026-07-11-002-lean-v1-demo` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | Lean V1 历史 demo，当前 WorkBuddy V3 不再以 Lean V1 为 active 流程 | 用户确认后关闭 |
| #6 | `TASK-2026-07-11-001：归一量化单项目工作站精简收口与Demo前置修复` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | 旧工作站精简收口任务，已由 Commit A/B/C 的 WorkBuddy V3 迁移替代 | 用户确认后关闭 |

## Open Pull Requests

| PR | 标题 | 分类 | 理由 | 建议动作 |
|---:|---|---|---|---|
| #23 | `DEMO-20260715-003-github-native-v3-final-e2e` | SUPERSEDED | Draft PR 仍 open；对应 Issue #22 已被 WorkBuddy V3 迁移替代 | 用户确认后 close Draft PR；不 merge |

## 最近 Merged PR

| PR | 标题 | 分类 | 理由 |
|---:|---|---|---|
| #26 | `Codex/ws gh 010 issue contract` | KEEP_ACTIVE | GitHub Issue Contract 相关，仍是 current control plane 基础 |
| #25 | `DEMO-20260715-004-github-native-v3-final-acceptance` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | PR 已 merged；对应 open Issue #24 可人工关闭 |
| #21 | `DEMO-20260715-002-github-native-v3-usage` | CLOSE_OBSOLETE_AFTER_USER_APPROVAL | PR 已 merged；对应 open Issue #20 可人工关闭 |
| #19 | `DEMO-20260715-001：GitHub Native V3 全链路验证` | SUPERSEDED | 历史 demo 记录；不需要 action，除非发现关联 Issue 仍 open |
| #16 | `TASK-2026-07-11-004：JM 实时 1m 真实 Gate` | REVIEW_REQUIRED | 业务任务，仍有 #12 open；需按 JM runtime Gate 证据判断 |
| #15 | `TASK-2026-07-11-002：火天大有指标与策略规范` | REVIEW_REQUIRED | 业务任务，仍有 #10 open；需按 observation-only 规范判断 |
| #14 | `TASK-2026-07-11-001：全量历史数据资产盘点` | REVIEW_REQUIRED | 数据任务，仍可能影响 DATA_LAYER_PARTIAL 后续专项 |
| #13 | `TASK-2026-07-11-003：Web 主图多指标切换` | REVIEW_REQUIRED | 前端任务，仍需页面验收与用户判断 |

## 需要用户确认后才能执行的命令

以下命令只是建议，不在本轮执行。

```bash
gh issue close 24 --repo firehell/guiyi-quant-workstation --comment "Closed after WorkBuddy V3 migration superseded GitHub Native V3 demo acceptance; PR #25 already merged."
gh issue close 22 --repo firehell/guiyi-quant-workstation --comment "Closed as superseded by WorkBuddy V3 migration readiness; Draft PR #23 is not the current delivery path."
gh pr close 23 --repo firehell/guiyi-quant-workstation --comment "Closed as superseded by WorkBuddy V3 migration readiness; not merged."
gh issue close 20 --repo firehell/guiyi-quant-workstation --comment "Closed after GitHub Native V3 usage demo was merged in PR #21 and superseded by WorkBuddy V3 readiness."
gh issue close 8 --repo firehell/guiyi-quant-workstation --comment "Closed as obsolete Lean/demo task after WorkBuddy V3 workstation migration readiness."
gh issue close 7 --repo firehell/guiyi-quant-workstation --comment "Closed as obsolete Lean V1 demo task after WorkBuddy V3 workstation migration readiness."
gh issue close 6 --repo firehell/guiyi-quant-workstation --comment "Closed as obsolete pre-WorkBuddy V3 workstation closeout task."
```

业务 Issue #9/#10/#11/#12 不建议在本轮关闭。若要清理，应另开业务验收 pass，逐项核对 TASK、merged PR、测试和页面/数据证据。
