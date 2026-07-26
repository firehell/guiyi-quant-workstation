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
部署、启用 SignalEvent 或发送通知。S6-07 semantic recovery 已按精确 Approval R 完成：
PostgreSQL 保持 `0025`、7 条 superseded binding 与 1 条 scheduler checkpoint 已恢复，receipt
hash=`3d916810629a34f48cbdd488e6ace7ac5954fa16089362284d85db790f07f75d`；
task 23/report 15、report 14、active Profile 与禁止表均零漂移。

## 合同

- bounded parent 最多包含五个唯一、排序后的明确交易日。
- parent 精确绑定 deployment packet、S6-07 rebind、S6-07 final receipt、DB recovery receipt、
  service bundle、Runtime commit、DB revision、indicator source、policy 和 writer hash。
- deployment packet 冻结部署前 Runtime 与批准目标；service parent 的 `runtime` binding
  冻结批准目标 commit/tree 和既有 Runtime root，使部署完成后的 Runtime 重采集能够精确匹配，
  不得把部署前 commit 错当成目标状态。
- parent 的 Profile/actual-contract 基线使用 packet 生成日前最新且唯一的已知 rank=1 mapping；
  不查询或伪造未来窗口首日 mapping。daily child 仍须重新绑定当日 exact mapping。
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

## 外部 Gate

- 三包不内嵌到本代码 checkpoint；只在 checkpoint 后基于干净 commit create-only 生成并重载验证；
- 未修改 Runtime env、launchd、PostgreSQL、Redis 或数据资产；
- 未执行真实 S6-08、S6-09、S6-10 Gate。

所有新 deployment/rebind/service packet 都必须重载验证 recovery receipt；旧 packet 不含该
binding，不能取得运行资格。只有取得精确 Approval A 后才能部署或写入。

`20260726-14d4388c237c` 首轮审批目录保留为 superseded 审计证据：其中 service parent 在
完成前复核时发现绑定了部署前 Runtime commit，未取得任何写授权、未生成 receipt、未部署。
后续只接受修复 checkpoint 对应的新 create-only 目录和三包 hash。
