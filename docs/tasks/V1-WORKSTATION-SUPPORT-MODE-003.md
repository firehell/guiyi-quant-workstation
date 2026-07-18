# V1-WORKSTATION-SUPPORT-MODE-003

更新时间：2026-07-17

状态：`WORKSTATION_NON_BLOCKING_SUPPORT_MODE`

## 目标

将 WorkBuddy / GitHub Native V3 从业务主线前置建设调整为非阻塞支持模式。工作站能力继续服务真实业务 Task，但不再阻塞全历史物理事实盘点、Audit V2、Profile rollout 或消费者契约。

## 当前证据

- 控制面实现提交：`c209cdbf`。
- `main` 合并提交：`d54e0198`。
- 2026-07-17 定向验证：`dispatch_task.sh`、`run_tests.sh` 的 Bash syntax 通过；resolver/router/WorkBuddy 定向测试 `63 passed`。
- 未发现最新 `main` 上可复现的控制面缺陷，因此本任务未修改 `scripts/ai`。

## 支持模式边界

允许继续：

- WorkBuddy Demo 与真实业务 Pilot。
- 已合并 Issue 的人工关闭或归档。
- 旧文档和历史 Demo 生命周期的人工整理。
- 真实业务 Task 暴露且可复现的控制面缺陷独立 follow-up。

明确禁止：

- 将 Demo、旧 Issue 清理或文档迁移设为 Audit V2 前置 Gate。
- 主动扩展多项目支持、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟。
- 自动关闭 Issue / PR、自动 push、merge 或 deploy。
- 修改业务代码、数据、DB、Profile binding、真实通知或交易边界。

## GitHub 生命周期建议

- Issue #29：实现已合并；建议补充 merge commit 与测试证据后，由用户人工关闭或归档。
- Issue #27 / Draft PR #28：已收口为 WorkBuddy Demo 未完成归档，可由用户关闭或归档；不再作为活跃支持轨，也不阻塞阶段 B。
- Issue #24、#20：对应 PR 已合并，建议用户确认后关闭。
- Issue #22 / Draft PR #23：已被后续 Demo 路径替代，建议用户确认后关闭或归档。
- Issue #6、#7、#8：旧工作站 / Demo 项，建议核对无独有未交付内容后人工关闭。
- Issue #9、#10、#11、#12：属于业务审计、策略、Web 或 live Gate，不纳入工作站自动清理。

Issue #27 使用 `DEMO-WB-V3-001`。主工程已保留 `docs/tasks/DEMO-WB-V3-001.md` 作为真实命名归档；`DEMO-WB-V3-FINAL-001` 仅作为历史占位快照。

## 阶段 A Gate

```text
V1_DATA_CONTRACT_FROZEN
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

对业务阶段 B 的影响：`不阻塞`。

## 本任务未执行

- 未调用 RQData。
- 未写 DB、Parquet、manifest、Profile binding 或历史报告。
- 未修改 `scripts/ai`、业务代码或配置。
- 未自动关闭 Issue / PR，未 push、merge 或 deploy。
