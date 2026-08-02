# GY-DATA-CORE-V2 Task 06 Production Migration Approval Packet

更新时间：2026-08-02

状态：`BLOCKED_LIVE_EOD_CONTRACT`

本 packet 只申请恢复 Task 06 schema 到已审查候选 head；不申请 RQData、live/EOD 业务写入、
scheduler、Runtime、SignalEvent、通知、删除、release、订单或自动交易。
当前仍缺 owner 冻结的 causal live/EOD evaluator 合同，因此本 packet 不可用于 apply；
即使后续合同通过，仍须先解决未批准 `0028` incident 并刷新 exact-head 证据。

## Exact scope

- task branch：`feature/live-review-loop-clean-start`
- base：`develop@b64453eab89692e5250a4275f04cac1bd26f02d4`
- production 当前 revision：`20260802_0028`（未事前批准的 incident；见 incident packet）
- candidate head revision：`20260802_0031`
- `0028` SHA-256：`f09fc15ef09f260ebff1aa0b5065bbe8386e4670db96adbb12b23e54bfa095e5`
- `0029` SHA-256：`89b7e0f92b79d5d2a87cfd513e9c40b0f1aa2458c1b176d0e03f4f811be37ac5`
- `0030` SHA-256：`0a6ac92665210e9a1b8cfe3a3cbd9f957ae5daf3b3f839a123025d049f0ecfac`
- `0031` SHA-256：`b46fcb20263efd155589630848aab91097bd1dc1c156c3f800009614284964fc`

`0028` 新增五张空表：

- `live_observation_bars`
- `signal_decisions`
- `signal_decision_reconciliations`
- `research_samples`
- `retention_runs`

并向 `signal_events` 新增 nullable `decision_id` 与索引。`0029` 只把 `revision + confirmed`
加入 `live_observation_bars` immutable identity 唯一约束；`0030` 新增拒绝 SignalDecision UPDATE 的
PostgreSQL trigger；`0031` 增加 provider-final data version/request digest 与 completed-row lineage
约束。三者均不读取、转换或导入旧业务记录。

## 已完成证据

- isolated PostgreSQL：exact head `0031` 完成 `0027 -> 0031 -> 0027 -> 0031`，6 passed，
  19 warnings（既有 `Column.copy()` deprecation），临时库已删除；
- 全后端：2560 passed，37 skipped；
- Task 06 focused/offline migration：42 passed，32 skipped；
- Ruff、docs、diff check、secret scan：passed；
- production readback：revision=`0028`，五张新表均 0 行，六个相关 flags 均 false；
- 未执行 RQData、live/EOD/sample 业务写入、scheduler、Runtime、SignalEvent 或通知。

## Owner 必须先选择 incident 处置

推荐：先批准 fresh backup，再把 empty/disabled production 从 `0028` 降回 `0027`；完成回读后，
另行批准从 exact reviewed source 升级到 head `0031`。

备选：明确 ratify 当前 empty/disabled `0028` incident，再对 `0028 -> 0031` 单独批准。ratification
不能改写为事前合规，也不授权任何业务开关。

## 备份与 apply 前停止条件

先按 `docs/LOCAL_BACKUP_RESTORE.md` 对仓库既有 backup CLI 做 dry-run。真正 `--execute` 需要 owner
单独批准并产生新 receipt。以下任一条件不满足即停止：

- production revision 与所选路径不一致；
- 任一 Task 06 新表非空，或存在 `signal_events.decision_id IS NOT NULL`；
- live/EOD/retention/SignalEvent/WeCom 任一 flag 为 true；
- migration SHA、task source、独立 Review 或 CI 漂移；
- fresh backup receipt、回滚可用性或数据库连接身份无法确认。

## Disabled/empty smoke

获批 migration 后只允许在同一受控会话回读：

- Alembic revision 精确为 `20260802_0031`；
- 五张新表仍全空；
- `signal_events.decision_id` 存在且所有值为空；
- 六个相关 flags 仍为 false；
- health 返回 `disabled / observation_only=true / auto_order=false`；
- 不启动任何 worker、scheduler、Runtime 或通知通道。

## 回滚

只有在五张表仍空、`signal_events.decision_id` 全空且 flags 全 false 时，才允许按 owner 批准的
exact scope 降级到 `20260730_0027`。`0031` 先在 reconciliation 空表条件下移除 provider lineage，
`0030` 再移除 immutable trigger；`0029` downgrade 对多 revision 同 bucket 数据 fail-closed；
`0028` downgrade 对任一新表业务行或非空 `decision_id` fail-closed。任何数据出现后不得把 migration
downgrade 当成业务删除工具。

## 尚缺 Gate

- owner 对 incident 的 downgrade 或 ratification 决策；
- exact source 独立 Review 结论；
- task PR/CI 与 `develop` integration；
- fresh backup receipt；
- owner 对生产 schema 操作的 exact approval。
