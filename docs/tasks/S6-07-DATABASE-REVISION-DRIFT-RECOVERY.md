# S6-07 数据库 revision 漂移事故与恢复边界

更新时间：2026-07-26

## 当前结论

```text
SCHEMA_REVISION_RESTORED_TO_0025
BUSINESS_FACT_RECOVERY_BLOCKED
NO_DATABASE_RECOVERY_AUTHORIZATION_ACTIVE
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

## 阻塞字段

没有完整数据库备份、PITR/WAL archive 或行级快照可以证明：

- 7 条 binding 的 `created_at`、`updated_at`；
- scheduler checkpoint 的 `last_result`、`created_at`、`updated_at`。

因此不得用默认值、当前时间或推导值恢复，不得生成可执行 Approval R。现有 schema-only/code-only
packet 与 receipt 作为历史证据保留，但不能证明业务事实已恢复。

后续只有在补齐上述原始值，或用户另行批准“语义重建而非逐字段原样恢复”的新恢复合同后，才可：

1. 生成完整 `recovery_manifest.json`；
2. 创建 hash-bound Approval R；
3. 完整 logical backup 与隔离 restore drill；
4. 执行 data-repair-only 恢复；禁止 migration、Runtime deployment、SignalEvent 和通知写入。
