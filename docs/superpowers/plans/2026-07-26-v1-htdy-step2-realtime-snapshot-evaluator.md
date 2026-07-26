# V1 HTDY Step 2 实时快照与候选评估器实施计划

## Task 1: 实现只读实时快照与候选评估器

### 目标与边界

在分支 `codex/v1-htdy-realtime-snapshot` 上基于 Step 1 commit `4cbb769e`
新增纯只读 HTDY realtime context。不得修改旧 `LiveSignalEvaluator`，不得写
`StrategySignal`、`SignalEvent`、Notification、Runtime、DB schema、migration、
EOD 或 Profile，不得修改 report 14/15，最终只保留一个 Step 2 checkpoint。

数据流固定为：

```text
live_observation_v1 actual-contract 15m primary/passed 尾部 128 根
+
显式 trading_day 的 confirmed/passed live 1m
→ TradingSessionClock session-aware 15m snapshot
→ 完整桶 confirmed / 当前桶 partial
→ 全序列 HTDY original
→ 最后 27 根扫描
→ current first-seen candidates / conflict blocks
```

### Public interfaces

新增：

- `services/quant-api/app/services/htdy_realtime_models.py`
  - `SourceMinuteRef`
  - `BucketIdentity`
  - `HtDy15mBarSnapshot`
  - `HistoricalWarmupIdentity`
  - `HtDyRealtimeSnapshot`
  - `HtDyObservationCandidate`
  - `BlockedObservation`
  - `HtDyEvaluationResult`
- `services/quant-api/app/services/htdy_realtime_snapshot.py`
  - `HtDyRealtimeSnapshotResolver.resolve(*, trading_day: date, detected_at: datetime, requested_contract: str | None = None) -> HtDyRealtimeSnapshot`
- `services/quant-api/app/services/htdy_realtime_evaluator.py`
  - `HtDyRealtimeCandidateEvaluator.evaluate(snapshot: HtDyRealtimeSnapshot, *, detected_at: datetime) -> HtDyEvaluationResult`

两个 `detected_at` 均必须带时区，evaluator 的 detected_at 必须与 snapshot as-of
时间一致。

Candidate 固定包含 Step 1 strategy/indicator/policy identity、actual/continuous
contract、mapping date、稳定观察桶 identity/OHLCV/status、`observed_bar_close`、
`direction=long|short`、`detected_at`、`detection_price`、本轮全部 source 1m
identity/revision/time/OHLCV/confirmed_at、historical profile/binding/file id/data
version/checksum/128-bar window hash、snapshot/source/policy hash、
`repaint_scan_bars=27`、`future_dependency_horizon_bars=24` 和
future/repainting/first-seen 声明。稳定 observation key 不包含 direction、
revision 或 snapshot hash。

### Canonical models and hash

- 数值使用 `Decimal`；hash 输入规范化为稳定十进制文本。
- bar/session 时间输出 Asia/Shanghai ISO-8601；confirmed/detected 时间输出 UTC。
- `session_id="DCE:jm:<session_name>"`，不得使用数据库自增主键。
- snapshot hash 使用 sorted-key、compact UTF-8 canonical JSON，覆盖 mapping、
  historical identity/hash、所有 15m 桶及本轮全部 source 1m。
- detected_at 不进入 snapshot hash；相同数据状态重启后 hash 必须一致。
- source revision、OHLCV、confirmed_at、成员或桶状态变化必须改变 hash。

### Session-aware snapshot

- 精确查询 `jm/rqdata/volume_open_interest/rank=1/trade_date=目标日` mapping。
- 无当日 mapping：完全无 mapping 为 `HTDY_MAPPING_MISSING`；只有旧 mapping 为
  `HTDY_MAPPING_STALE`；同日重复为 `HTDY_MAPPING_DUPLICATE`；同日不同合约为
  `HTDY_MAPPING_CONFLICT`。
- actual contract 必须非空且不是 `*.MAIN`；requested contract 必须精确匹配。
- 用 `ProfileLineageResolver` 强制解析
  `live_observation_v1 + actual_contract + 15m + primary/passed`。
- 用 `MarketDataReader` 加载目标交易日首个 session 前的尾部 128 根；最大
  historical trading day 必须为前一 DCE 交易日。历史 bars 必须属于合法
  session/bucket，禁止跨 actual contract warm-up。
- 查询目标 actual contract 当日全部 live 1m，不能预过滤 warning/failed。
- 每根 source bar 必须为 `jm + actual contract + rqdata + 1m`，trading_day
  精确匹配，confirmed/passed 且 confirmed_at 存在，时间不晚于上海时区
  `floor(detected_at)-1 minute`，OHLCV/revision/id 合法。
- 用 `TradingSessionClock.windows_for_trading_day()` 建桶：
  `bucket_start=session.start+15m*k`，
  `bucket_end=min(bucket_start+15m, session.end)`，session 使用 `(start,end]`
  的分钟结束时间。
- detected_at 前所有应到分钟必须存在；已结束桶完整才 confirmed；当前桶必须
  从 bucket_start 连续形成前缀并标记 partial。午休不建桶、夜盘归属 trading
  day、桶不跨 session。
- 缺分钟、未来分钟、跨 session、重复分钟、OHLCV 冲突、warning/failed
  source 均整轮 fail-closed。
- 不调用 `LiveMultiTfAggregationService.aggregate_once()`，不写
  `live_aggregated_bars`，不把 partial 当 historical canonical。

### Candidate evaluator

- 用 Step 1 `require_realtime_repainting_observation_policy()` 校验 exact policy。
- 每轮对 historical 128 根加当日 live 15m snapshot 运行一次完整
  `compute_htdy_original()`。
- 只检查 `[max(0,len-27),len)`。
- 单向 buy/sell 生成 long/short candidate；同桶双向只生成
  `BlockedObservation(reason="dual_direction_conflict")`。
- `detection_price` 取本轮最新完成 1m close；`observed_bar_close` 取触发桶 close。
- 允许扫描区内历史 warm-up bar因 future tail 首次出现。
- evaluator 不查询 seen 状态；信号消失不返回，单向 flip 返回当前方向。
- evaluator 无跨轮状态、无写服务、无 StrategySignal/SignalEvent/Notification。

### TDD tests

先新增失败测试，再实现：

- `services/quant-api/tests/test_htdy_realtime_snapshot.py`
  - DCE 夜盘跨自然日、午休、日盘尾桶；
  - partial、partial→confirmed；
  - 缺分钟、跨 session、未来分钟；
  - revision 改 hash、restart 相同 hash；
  - exact duplicate、OHLCV conflict；
  - mapping switch/stale/missing/duplicate/conflict；
  - missing/wrong Profile、warning/failed historical/live；
  - checksum、previous-day freshness、actual-contract isolation；
  - snapshot 含全部 source 1m lineage。
- `services/quant-api/tests/test_htdy_realtime_evaluator.py`
  - 真实 Step 1 kernel old-bar repaint appearance/disappearance；
  - current direction flip、dual conflict；
  - 第 27 根边界包含、第 28 根排除；
  - detection price 与 observed close 分离；
  - source/policy/future metadata；
  - 相同 snapshot+detected_at 输出确定；
  - SQL 监听确认无 INSERT/UPDATE/DELETE。

### Documentation and verification

更新 `docs/ARCHITECTURE.md`、`docs/INDICATOR_KERNEL.md`、`STATUS.md`，新增
`docs/tasks/V1-HTDY-02-REALTIME-SNAPSHOT-AND-EVALUATOR.md`。不得把本步表述为
Runtime、事件、通知、盈利或交易 Ready。

依次运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_realtime_snapshot.py services/quant-api/tests/test_htdy_realtime_evaluator.py
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests -k "htdy or live_signal_context or live_multi_tf_aggregation or trading_session_clock or profile_lineage"
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant services/quant-api/app services/quant-api/tests
bash scripts/engineering/check-secrets.sh
git diff --check
```

交付前比较旧 `live_signal_evaluator.py` 的任务前后 SHA-256，并确认 diff 不含
model、migration、EOD、Profile、SignalEvent、Notification 或 Runtime wiring。

最终 checkpoint 只发布：

```text
HTDY_REALTIME_15M_SNAPSHOT_READY
HTDY_FIRST_SEEN_CANDIDATE_EVALUATOR_READY
NO_SIGNAL_WRITE_PATH_ENABLED
```
