# V1-HTDY-03 Immutable First-Seen Event Ledger

日期：2026-07-26

## 结论

```text
HTDY_FIRST_SEEN_EVENT_WRITER_READY
HTDY_FIRST_SEEN_EVENT_LEDGER_READY
SIGNAL_REVIEW_LINEAGE_V2_READY
HTDY_STAGE9_OBSERVATION_EXCEPTION_READY
NO_DATABASE_MIGRATION_REQUIRED
NO_RUNTIME_WRITE_AUTHORIZATION_ACTIVE
```

这些状态只表示 Step 3 的本地 code/test checkpoint，不表示 Runtime、真实 PostgreSQL
SignalEvent、通知、企业微信、长稳、盈利或交易 Ready。

## 实现

- `HtDyFirstSeenEventService` 接收 Step 2 的 `HtDyEvaluationResult`。
- 一轮 candidates 全部预校验后，复用现有 `strategy_signals` 与 `signal_events`。
- dedupe 使用 `htdy-first-seen:<observation_key>`；direction、revision、snapshot hash
  不进入 dedupe。
- 第一次写入 `signal_created` 后永久冻结；后续同桶只返回 unchanged，不修改
  StrategySignal，不产生 `signal_changed`。
- candidates 与双向冲突同时出现时整轮 fail-closed；纯 blocked 轮次只返回 blocked，
  不写数据库。
- 多进程竞争依赖既有 `strategy_signals.dedupe_key` 唯一键；savepoint 捕获
  `IntegrityError` 后只在既存 signal/event 完整且未漂移时返回 unchanged。
- `signal_review_lineage_v2` 冻结 Profile/file/window、实际主力、观察桶、首次
  detection price、观察桶 OHLCV、完整 source 1m identity/revision/OHLCV/confirmed_at、
  source 1m collection hash 和 policy hash。
- ReviewNote 仍只由人工入口创建；lineage v2 原样冻结，Review bar 接口读取首次
  observed snapshot，不按当前 HTDY 重算。
- Stage 9 保留 formal v1 合同并增加 exact HTDY Preview 例外；HTDY
  `allowed=true / delivery_allowed=false`，直接 delivery 在创建 SignalNotification 前阻断。
- Signal、Market、Review 和通知 Preview 统一展示未来函数、重绘、首次冻结、
  不撤回及非交易边界。
- 不写 `signal_notifications`，不新增 migration，不接 Runtime，不自行 commit。

## 验证

目标测试覆盖首次创建、首次 snapshot 冻结、direction/revision/repaint unchanged、
并发唯一键竞争、冲突整轮阻断、批次预校验、forged result、同批重复 candidate、
既有冻结 Signal/Event 漂移、缺失 created event fail-closed、Stage 9 allow/deny、
Review frozen snapshot、前端风险文案与 notification 零写入。

集成 provenance：本分支基于 `c3702e00`；其中 Step 2 commit `9cbac58c` 与最终
checkpoint `3c6cd723` 通过 `git diff --quiet` 验证 tree 等价，不重写既有历史。

Step 4 必须在独立 checkpoint 中完成 schema-v3 packet/verifier；真实 Runtime 或数据库
写入仍需其精确 hash-bound Gate 与用户批准。
