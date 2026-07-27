# V1-HTDY-02 Realtime Snapshot and Candidate Evaluator

日期：2026-07-26

## 结论

`HTDY_REALTIME_15M_SNAPSHOT_READY`、`HTDY_FIRST_SEEN_CANDIDATE_EVALUATOR_READY` 与
`NO_SIGNAL_WRITE_PATH_ENABLED` 只表示 Step 2 的 read-only code/test checkpoint。

## 范围

- 精确解析 `jm/rqdata/volume_open_interest/rank=1` 当日 actual-contract mapping；缺失、陈旧、重复或冲突
  mapping fail-closed。
- 解析 `live_observation_v1` actual-contract 15m primary/passed historical 128-bar warm-up；校验 profile
  binding、checksum、上一 DCE trading day、actual-contract 隔离与 session 合法性。
- 读取显式 trading day 的全部 live 1m，使用 `TradingSessionClock` 产生完整 confirmed 或连续 partial 15m
  snapshot，保留全部 source lineage/revision 并计算 canonical snapshot hash。
- 以 frozen policy 和 Step 1 original kernel 扫描最后 27 根，返回 long/short observation candidate 或
  `dual_direction_conflict` block；无跨轮 seen state。

## 明确未做

未改旧 `LiveSignalEvaluator`、ORM/schema/migration、Profile、EOD、Runtime、SignalEvent、Notification、
report 14/15 或 strict 参数；未写 DB/runtime data、未部署、未运行真实 Gate、未发送通知，亦不代表盈利、
交易或自动下单 Ready。

## 验证

验证命令和完整结果以同一 checkpoint 的 task report 为准。重点覆盖 session/night/partial、mapping 与
source fail-closed、hash stability/revision、候选 evaluator determinism 和 no-write boundary。
