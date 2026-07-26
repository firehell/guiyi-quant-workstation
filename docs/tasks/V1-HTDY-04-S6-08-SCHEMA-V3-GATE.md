# V1-HTDY-04 S6-08 Schema-v3 Gate

日期：2026-07-26

## 结论

```text
HTDY_S6_08_SCHEMA_V3_CODE_COMPLETE
REAL_T5_NOT_EXECUTED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
CODE_COMPLETE_EXTERNAL_GATE_PENDING
```

本步完成 schema-v3 packet builder/verifier、CLI、独立 HTDY Runtime handler 和测试，但没有
生成真实批准文件，也没有部署、启用 SignalEvent 或发送通知。当前 Runtime/数据库事实仅用于
只读审计；PostgreSQL schema 已回到 `0025`，但 S6-07 checkpoint、7 条历史 binding 及 HTDY
trusted-backtest lineage 仍缺少逐字段原样恢复证据，因此三包生成必须 fail-closed。

## 合同

- bounded parent 最多包含五个唯一、排序后的明确交易日。
- parent 精确绑定 deployment receipt、S6-07 final receipt、service bundle、Runtime commit、
  DB revision、indicator source、policy 和 writer hash。
- exact daily child 绑定 parent hash、一个被允许交易日、实际主力合约、mapping hash 和
  `strategy_signals/signal_events/signal_notifications/signal_scan_tasks/orders/trades` baseline。
- 旧 schema-v2 packet 必须拒绝。
- execution verifier 至少要求一条 `signal_created`，且只允许
  `htdy_original_realtime_first_seen/v1.0 + live_realtime_repainting +
  signal_review_lineage_v2`。
- StrategySignal 与 SignalEvent delta 必须等于事件数；notification、scan、order、trade
  delta 必须全部为零。
- `LiveRuntimeCycleService` 只在 schema-v3 Gate 授权后调用独立 HTDY handler；旧
  `LiveSignalEvaluator` 不进入 active HTDY 路径。
- 首个自然事件后只允许一次同 observation key 幂等探测；验证
  `unchanged > 0, created = 0, changed = 0` 后消费 create-only 授权。
- source worktree 与 Runtime checkout 分别采集 commit/tree/clean facts，禁止用 source
  checkout 身份冒充 Runtime 身份。

## 未做

- 未创建或验证真实 deployment/rebind/service packet 文件；
- 未修改 Runtime env、launchd、PostgreSQL、Redis 或数据资产；
- 未执行真实 S6-08、S6-09、S6-10 Gate。

真实执行前必须先完成独立 S6-07 数据恢复合同并取得 Approval R；恢复 receipt 验证通过后，
再采集三个当前 hash、生成 create-only 三包并进行 drift review。只有取得精确 Approval A
后才能部署或写入。
