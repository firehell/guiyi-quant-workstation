# 当前状态

更新时间：2026-08-15

## 当前结论

- 归一量化是本地、单用户的国内期货研究工作站。所有信号、页面和通知只用于人工观察，
  `auto_order=false`，仓库不存在订单创建或提交路径。
- Data Foundation DFD-01～DFD-07 已完成：active universe 为 60 品种，历史事实链固定为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`。
- 当前 release 为 `v1.3.1`；Market Web 已提供 Radar、品种 K 线、EMA/MACD/HTDY、
  SuBing Factor/Signal 观察与 Alert V2 上下文。
- Market Runtime V1 已在本地工作站启用，只处理 `operational_products.txt` 的 active 60；
  Historical Canonical 与 Redis Live Overlay 分离，Live 不写 Parquet/DB。
- Alert Runtime V2 的 Code Registry 精确为 `htdy_original_15m` 与
  `subing_entry_signal_v1`；production 两条 Rule 的 Scope 当前均精确为 `jm`。
- HTDY 自然 Event/WeCom 闭环已验收。SuBing Scope 已由用户通过 Product Workspace 单独激活，
  但尚未观察到自然 SuBing Event；Natural Canary 仍为 pending，不得用 synthetic Event、
  replay、backfill 或 retry 代替。

## 当前可执行面

- Web：`/market` 与 `/market/chart`。
- HTTP：`/api/v1/market/*`、`/api/alerts/*`、`/api/runtime/health` 和轻量 health。
- CLI：`guiyi data update|refresh|audit|after-market`；只读
  `guiyi research subing-calibration`、`guiyi runtime status|live|alert`。
- `guiyi runtime alert-canary` 是真实 WeCom Gate，不是普通测试命令。
- Runtime：Live 与盘后更新共用同一 `operational_products.txt`；盘后时点为 18:05，
  只对 `NEXT_TRADING_SESSION_NOT_READY` 允许最多一次一小时后 retry。

已退役且不得恢复为兼容入口：backtest API/Web/worker/queue、Signal/Review/Strategy
HTTP·Web·worker、data-center HTTP、旧 RQ worker/scheduler、自动交易与真实订单。

## 已冻结合同

- 基础 provider 周期只有 `1m/1d`；`1w` 只从完整同源 Canonical `1d` 聚合，
  `5m/15m/30m/60m` 只从质量通过的同 Dataset Canonical `1m` 按 TradingSession 聚合。
- 物理 Dataset 只有 `continuous|contract`；`actual_dominant` 只在查询时按
  `MainContractMap rank=1` 拼接。
- 每 Dataset 每自然月只有一个 `part.parquet`。schema、identity、session/frequency、OHLCV、
  coverage、row count、Catalog URI 和物理可读性不一致时 fail-closed。
- Market Catalog 精确为八表；`alert_rules` / `alert_events` 是独立 Alert Application Domain，
  不属于且不改变八表合同。production DB revision 当前为 `20260814_0038`。
- SuBing 只使用 current-rank1-segment-local Historical/completed Live，不做 pre-rank1 warm-up、
  cross-roll EMA/MACD 继承或 zero-band hard gate；1d 仍为 `RESEARCH_PENDING`。
- Alert HTDY 保持 event-cutoff；SuBing 只复用 accepted Calibration、FormalPolicy 和
  `SubingReadService` resolver。incoming Event Bar 与读回的当前最后 Bar 必须整体相同。
- Alert Event 先提交，然后最多尝试一次 WeCom；不建 replay/backfill/retry/outbox/queue。

## 当前 Runtime 事实

- `2026-08-15 19:29 +08:00` 最后一次已授权读回：五服务 Runtime 绑定 clean/detached
  `51b1f44f8ffb3580054ed591053e7eda451506f3`，根为
  `/Volumes/扩展盘/guiyi-quant-runtime-51b1f44f8`。API/Web/Live/Alert running，after-market 为
  schedule-only `not running`，API version=`1.3.1`，Runtime health=`ok/readonly=true`。
- 当时为周末：Live `CLOSED=60/subscribed=0`，dominants=60，Radar active/participant=60/60、
  stale/unavailable=0；JM 的 HTDY/SuBing Rule 均 enabled，Event 数分别为 3/0。
- 当前 develop 中的收敛修正只是仓库代码/文档事实，尚未 Runtime switch；不得将其表述为
  已部署或 Runtime Ready。

## 未执行 Gate 与最小下一步

- 本轮不执行 migration、真实 RQData/Canonical/DB 写入、Scope mutation、WeCom、Runtime switch、
  `main`、tag 或 release。
- 唯一待自然事件：继续等待 `subing_entry_signal_v1 × jm` 的后续自然 completed Bar 验收；
  无事件就保持 pending，不人工补证。
