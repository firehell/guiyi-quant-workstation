# JM Live Historical Context S6-04

更新时间：2026-07-20

状态：`COMPLETED / JM_LIVE_CONTEXT_READY`

## 目标与边界

JM live evaluator 现在按以下只读契约构造 5m/15m 入场窗口：

```text
live_observation_v1 bound actual-contract primary/passed historical bars
+ latest live trading day confirmed/passed bars
-> strategy evaluation
```

historical 只提供 warm-up，上下文必须覆盖 live trigger 前一 DCE 交易日；最终触发 bar 必须保持为独立保存并验证的 live confirmed bar。任务未运行真实 live，未写 historical active、live/checkpoint、StrategySignal、SignalEvent 或 SignalNotification，未修改策略、参数、migration 或持久化开关。

## 拼接契约

- key 为 `(actual_contract, period, bar_datetime)`，只允许当前 actual contract。
- 同 key OHLCV 标准化后一致时保留 historical row，并记录 exact duplicate；不一致时以 `historical_live_bar_conflict` fail-closed。
- live reader 只返回最新 live trading day 的 `confirmed / passed` rows；forming、partial、rejected、failed 均不能成为 trigger。
- historical binding/file 必须为 `primary / passed`，物理 checksum 必须匹配，且最大 `trading_day` 不早于 live trigger 的上一 DCE 交易日。
- 合并后最后一个 key 必须等于 live trigger key；主力切换重新解析新 actual contract，不回退旧主力。
- 上下文长度为 request、策略最小 bars 和 indicator window 的最大值，上限 10000。

## Lineage 与 API

`/api/signals/live-evaluator/preview` 保持只读并增加可选 typed `context`。entry signal 的 `signal_review_lineage_v1` 内新增 `context_contract_version=historical_live_context_v1`、`historical_context` 和 `live_trigger`，分别验证 historical file identity/version/checksum/window hash 与 live id/revision/confirmed time。formal lineage 不完整时返回 `no_signal / formal_lineage_blocked`，不产生可持久化 entry signal。

## 验证

- S6-04 定向回归：`51 passed`。
- 合并后端全量：`1089 passed, 3 skipped`。
- Web tests：`76 passed, 1 skipped`；production build passed。
- Ruff、canonical/status scan、sensitive scan 与 `git diff --check` 由本任务最终收口执行。

## Gate 边界

```text
JM_LIVE_CONTEXT_READY
```

该 Gate 仅表示历史 warm-up 与 live confirmed 拼接代码、lineage、只读 Web 观察和测试已闭合。它不表示 `T3_REAL_PASSED`、`JM_ARCHIVE_PASSED`、`JM_EOD_INCREMENTAL_AUTOMATION_READY`、`LIVE_SIGNAL_EVENT_GATE_PASSED`、`LIVE_WECOM_SINGLE_SEND_PASSED`、`JM_RUNTIME_READY` 或 `LONG_RUNNING_READY`。
