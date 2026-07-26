# S6-07 数据库 revision 漂移事故与恢复边界

更新时间：2026-07-26

## 当前结论

```text
SCHEMA_REVISION_RESTORED_TO_0025
BUSINESS_FACT_SEMANTIC_RECOVERY_COMPLETED
DATABASE_ONLY_BACKUP_AND_DRILL_PASSED
RECOVERY_APPROVAL_CONSUMED
```

生产 PostgreSQL 曾从 `20260721_0025` 被降到 `20260712_0022`。根因是
`test_profile_active_binding_migration.py` 直接读取普通 `DATABASE_URL` 并执行 destructive
Alembic downgrade/upgrade roundtrip。后续外部流程已把 schema 恢复到 `0025`，但未恢复 downgrade
删除或丢弃的业务事实。

当前只读事实：

- `profile_active_bindings=5124`，比 Step 0 冻结证据少 7 行；
- `after_market_scheduler_checkpoints=0`；
- HTDY trusted backtest task/report 23/15 的 0023/0024 lineage 字段为空；
- SignalEvent、SignalNotification、StrategySignal 和 market data file 计数未发现新增漂移。

## 已封堵路径

- destructive migration tests 只接受 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`；
- 数据库名必须包含 `test` 或 `isolated`；
- 目标 URL 不得等于 Runtime `DATABASE_URL`；
- 实际连接后的数据库名和 PostgreSQL OID 必须与 Runtime DB 不同；
- 测试结束始终把隔离数据库升级回 `head`。

## 可证明恢复事实

- 7 条被删除 binding 的业务 identity、file、data version、activated/superseded 时间可由
  2026-07-22/23 S6-07 immutable execution/final-audit 证明；
- task/report 23/15 的 profile、file 和 binding snapshot 可由 HTDY trusted report evidence 证明；
- scheduler checkpoint 的主要状态可由 D2 completion snapshot 证明。

## 语义重建合同

没有完整数据库备份、PITR/WAL archive 或行级快照可以证明：

- 7 条 binding 的 `created_at`、`updated_at`；
- scheduler checkpoint 的 `last_result`、`created_at`、`updated_at`。

用户已明确批准继续解决该阻塞，但真实写入仍只接受新生成的精确 Approval R 哈希。恢复合同冻结为：

- 5240–5246 的业务 identity、profile、contract、period、file、version、activated/superseded
  时间来自 2026-07-22/23 S6-07 final audit；
- binding `created_at=activated_at`、`updated_at=superseded_at`，并在 manifest 中逐项声明为
  synthesized audit field；
- checkpoint 业务状态来自 D2 completion snapshot；`last_result` 只记录 semantic provenance，
  `created_at/updated_at` 绑定 packet 的 `recovered_at`；
- task 23/report 15 不写数据库，继续绑定外部 trusted-report evidence；
- 只允许插入 7 条 superseded binding 和 1 条 scheduler checkpoint；禁止 migration、Runtime
  deployment、backtest task/report、SignalEvent、通知、订单和成交写入；
- Approval R 前必须完成 database-only logical backup 与真实 Docker 隔离恢复演练，且恢复后清理
  本轮 ownership label 资源。

实现入口：

- `services/quant-api/app/services/s607_database_recovery.py`
- `scripts/backup/database_only_drill.py`
- `scripts/s607_database_recovery_gate.py`

## Approval R 执行结果

2026-07-26 已完成：

- recovery code checkpoint：`0ef20053022a85fbc320621b1fe70f8887bc0187`；
- Approval R packet：
  `443adda6d2b3f0e82edaeff1d72e9ff4a6d194b0f1d78928a034f175f513c2f3`；
- recovery receipt：
  `3d916810629a34f48cbdd488e6ace7ac5954fa16089362284d85db790f07f75d`；
- database-only backup 与 PostgreSQL 16 Docker 隔离恢复演练通过，隔离容器/卷均已清理；
- revision 保持 `20260721_0025`；
- `profile_active_bindings: 5124 -> 5131`；
- `after_market_scheduler_checkpoints: 0 -> 1`；
- 5240–5246 均按冻结合同恢复为 `superseded`；
- checkpoint 为 `jm/DCE/idle`，watermark=`2026-07-24`，retry=0；
- active Profile hash、report 14（155 trades / 239 orders）、task 23、report 15、SignalEvent、
  SignalNotification、StrategySignal、orders、trades 全部零漂移。

该 Approval R 已消费，不授权重复恢复、migration、部署或任何 HTDY SignalEvent 写入。HTDY
schema-v3 后续 packet 必须绑定上述 recovery receipt hash，并重新采集当前 DB facts。
