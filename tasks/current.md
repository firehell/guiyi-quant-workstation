# tasks/current.md（兼容指针）

更新时间：2026-07-20

> 本文件**不再膨胀**为 changelog。当前任务与 Gate 请看：
>
> 1. `STATUS.md`（`WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY`）
> 2. GitHub Issue / PR
> 3. 进行中高风险任务的 `docs/tasks/<TASK_ID>.md`
> 4. 开发流程：`docs/DEVELOPMENT.md`

最近业务终态（只读 closeout，非活跃控制面）：

- S6-00：`STAGE6_CANONICAL_SYNCED`（Stage 6 主线已同步；本文件不膨胀为 changelog）
- S6-03：`JM_HISTORICAL_CATCHUP_READY / JM_REFERENCE_METADATA_FRESH / JM_LIVE_TARGET_FRESHNESS_READY`
- S6-04：`JM_LIVE_CONTEXT_READY`（historical actual warm-up + live confirmed/passed context；不写 SignalEvent/notification）
- [`docs/tasks/TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md`](../docs/tasks/TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md)（`STAGE4_COMPLETED` / `STAGE5_COMPLETED` / `READY_TO_ENTER_STAGE6`）
- [`docs/tasks/TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504.md`](../docs/tasks/TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504.md)（`REJECTED_RESEARCH_CANDIDATE`）

下一业务入口：`S6-05` T3 独立 Plan 与真实写入 Gate（仅 JM live/checkpoint；不自动进入 T4、SignalEvent、通知或长稳）。

长历史快照：[`docs/archive/task-history/tasks-current-2026-07-20.md`](../docs/archive/task-history/tasks-current-2026-07-20.md)

精简终态报告：[`docs/archive/workstation/WORKSTATION_SIMPLIFICATION_FINAL_REPORT.md`](../docs/archive/workstation/WORKSTATION_SIMPLIFICATION_FINAL_REPORT.md)
