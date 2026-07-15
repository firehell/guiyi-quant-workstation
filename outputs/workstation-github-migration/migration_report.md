# GitHub TASK Migration Report

生成时间：2026-07-14T17:09:13+00:00

Repository：`firehell/guiyi-quant-workstation`

## 范围

- Open Issues：7
- Open / Draft PRs：0 linked in matrix
- Matrix Rows：13

## 结论

本报告是 WS-GH-014 第一轮只读审计结果。未关闭 Issue，未修改标签，未写 GitHub，未修改业务代码或数据。

## 分类统计

| 分类 | 数量 |
|---|---:|
| Active | 2 |
| Completed | 5 |
| Superseded | 0 |
| Orphan Issue | 0 |
| Orphan TASK | 6 |
| Conflict | 0 |

## 迁移矩阵

| Item | Issue | Task ID | TASK path | Branch | PR | Status | Last commit | Class | Recommendation | Conflict |
|---|---|---|---|---|---|---|---|---|---|---|
| issue | #6 | TASK-2026-07-11-001-workstation-lean-v1-closeout | docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md | feature/workstation-lean-v1-closeout | - | DELIVERY_READY | 7710a51c 2026-07-12 22:47:24 +0800 | Completed | 补交付摘要和结果链接，用户确认后关闭 Issue。 | - |
| issue | #7 | TASK-2026-07-11-002-lean-v1-demo | docs/tasks/TASK-2026-07-11-002-lean-v1-demo.md | feature/lean-v1-demo | - | DELIVERY_READY | 7710a51c 2026-07-12 22:47:24 +0800 | Completed | 补交付摘要和结果链接，用户确认后关闭 Issue。 | - |
| issue | #8 | GUIYI-DEMO-001 | docs/tasks/GUIYI-DEMO-001.md | feature/lean-v1-demo | - | RESULT_READY | 7710a51c 2026-07-12 22:47:24 +0800 | Completed | 补交付摘要和结果链接，用户确认后关闭 Issue。 | - |
| issue | #9 | TASK-2026-07-11-001-data-asset-audit | docs/tasks/TASK-2026-07-11-001-data-asset-audit.md | codex/data-asset-audit | - | DELIVERY_READY_WITH_CLI_ENV_NOTE | 7710a51c 2026-07-12 22:47:24 +0800 | Completed | 补交付摘要和结果链接，用户确认后关闭 Issue。 | - |
| issue | #10 | TASK-2026-07-11-002-htdy-indicator-core | docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md | codex/htdy-indicator-core | - | DELIVERY_READY | 8e316f7d 2026-07-14 14:39:01 +0800 | Completed | 补交付摘要和结果链接，用户确认后关闭 Issue。 | - |
| issue | #11 | TASK-2026-07-11-003-web-overlay-indicators | docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md | codex/web-overlay-indicators | - | C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW | 73320a87 2026-07-12 14:48:57 +0800 | Active | 迁移到 V3，补充 Draft PR 关联后继续。 | - |
| issue | #12 | TASK-2026-07-11-004-jm-live-runtime-gate | docs/tasks/TASK-2026-07-11-004-jm-live-runtime-gate.md | codex/jm-live-runtime-gate | - | T1_OPS_PASSED_/_T3_CLOCK_IDLE_NON_TRADING_/_T3_REAL_PENDING | 374e2f32 2026-07-11 23:40:56 +0800 | Active | 迁移到 V3，补充 Draft PR 关联后继续。 | - |
| task | #5 | TASK-2026-07-10-003-workstation-lean-v1-closeout | docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md | feature/workstation-lean-v1-closeout | - | REQUIREMENT_READY | 7710a51c 2026-07-12 22:47:24 +0800 | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |
| task | - | "WS-V2-003" | docs/tasks/workstation/WS-V2-002-task-schema-plan.md | - | - | PLAN_READY | - | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |
| task | - | TASK-2026-07-09-001-workstation-scaffold | tasks/TASK-2026-07-09-001-workstation-scaffold.md | - | - | REQUIREMENT_READY | - | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |
| task | - | TASK-2026-07-09-002-readme-workstation-sync | tasks/TASK-2026-07-09-002-readme-workstation-sync.md | - | - | REQUIREMENT_READY | - | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |
| task | - | TASK-2026-07-10-001-workstation-v1.2.1-closeout | tasks/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md | - | - | REQUIREMENT_READY | - | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |
| task | - | TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon | tasks/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md | - | - | REQUIREMENT_READY | - | Orphan TASK | 补 Issue 链接或归档本地 TASK；确认是否仍需 V3 迁移。 | no open issue linked |

## 建议执行顺序

1. 先处理 `Conflict`：确认唯一 Issue / TASK / branch / PR，避免多个 active Issue 指向同一 TASK。
2. 再处理 `Completed`：补 delivery summary / result summary，用户确认后关闭。
3. 再处理 `Orphan Issue`：补 TASK 或关闭为 superseded / not planned。
4. 再处理 `Orphan TASK`：补 Issue 或归档，不删除历史 TASK。
5. 最后处理 `Active`：迁移到 V3，补齐 Draft PR 和 Issue/TASK/branch/PR 字段。

## 审计产物

- `outputs/workstation-github-migration/migration_matrix.csv`
- `outputs/workstation-github-migration/migration_matrix.json`
- `outputs/workstation-github-migration/migration_report.md`

## 禁止动作

- 本轮不关闭 Issue。
- 本轮不改 GitHub label。
- 本轮不创建或删除 TASK。
- 本轮不 push、merge、deploy。
- 本轮不删除历史 TASK。
