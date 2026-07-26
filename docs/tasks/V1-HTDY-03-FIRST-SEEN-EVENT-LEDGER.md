# V1-HTDY-03 Immutable First-Seen Event Ledger

日期：2026-07-26

## 结论

```text
HTDY_FIRST_SEEN_EVENT_WRITER_READY
HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY
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
- 双向冲突只计 blocked，不写数据库。
- `signal_review_lineage_v2` 冻结 Profile/file/window、实际主力、观察桶、首次
  detection price、完整 source 1m identity/revision/OHLCV/confirmed_at 和 policy hash。
- 不写 `signal_notifications`，不新增 migration，不接 Runtime，不自行 commit。

## 验证

目标测试覆盖首次创建、首次 snapshot 冻结、direction/revision/repaint unchanged、
冲突零写入、批次预校验、缺失 created event fail-closed 和 notification 零写入。

Step 4 必须在独立 checkpoint 中完成 schema-v3 packet/verifier；真实 Runtime 或数据库
写入仍需其精确 hash-bound Gate 与用户批准。
