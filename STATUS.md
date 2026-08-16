# 当前状态

更新时间：2026-08-16

## 当前结论

- 归一量化是本地、单用户的国内期货研究工作站。所有信号、页面和通知只用于人工观察，
  `auto_order=false`，仓库不存在订单创建或提交路径。
- Data Foundation DFD-01～DFD-07 已完成：active universe 为 60 品种，历史事实链固定为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`。
- 当前 release 为 `v1.4.0`；Market Web 已提供 Radar、品种 K 线、EMA/MACD/HTDY、
  SuBing Factor/Signal 观察与 Alert V2 上下文。
- Market Runtime V1 已在本地工作站启用，只处理 `operational_products.txt` 的 active 60；
  Historical Canonical 与 Redis Live Overlay 分离，Live 不写 Parquet/DB。
- Alert Runtime V2 的 Code Registry 精确为 `htdy_original_15m` 与
  `subing_entry_signal_v1`；production 两条 Rule 的 Scope 当前均精确为 `jm`。
- HTDY 自然 Event/WeCom 闭环已验收。SuBing Scope 已由用户通过 Product Workspace 单独激活，
  但尚未观察到自然 SuBing Event；Natural Canary 仍为 pending，不得用 synthetic Event、
  replay、backfill 或 retry 代替。

## Execution Review V1（RELEASED / PRODUCTION MIGRATION COMPLETE / RUNTIME PROMOTED）

- 状态为 `RELEASED`：release PR #167 已合入 main，annotated tag `v1.4.0` 的 peeled commit 为
  `3a6f4289ff08848f9177c41a649a94f877412c23`。production DB 已完成 additive `20260815_0039`
  migration，四张 Execution Review 表已存在。正式 Runtime 已 promotion 至 `v1.4.0` identity
  `3a6f4289ff08848f9177c41a649a94f877412c23`，Execution Review production Runtime surface
  已 available。
- `v1.4.0` 代码新增 `/trade-records` 与 `/api/execution-review/*`，以四张独立 Application Domain 表保存
  苏冰 Event 的人工 Decision、真实手工 Execution timeline、单品种 OPEN Episode 与结构化 Review；
  不恢复旧 Review Center，不连接账户或创建订单。
- official multiplier coverage = `7 / 60`。reference 与 official evidence 集合精确相等、无重复、
  无 unknown，逐行 derived multiplier 与 reference 相等。缺失 multiplier 只影响人民币
  Estimated Gross PnL availability；realized points、仓位拓扑、时间线与 Review 保持可用。
- trusted-partial snapshot 在 Episode 创建时冻结；当时为 NULL 的历史 Episode 不因未来 reference
  扩大自动改写。active-60 60/60 是后续独立 Lane 3 reference-data objective，不是 v1.4 release Gate。
- 完整验证：backend `1031 passed`；engineering `41 passed`；Ruff 通过；Mypy 55 files 无问题；
  Web unit `147 passed / 1 conditional skip`；Market/Alert/Execution Review E2E `57 passed`；Web
  production build、secret scan（0 findings）、shell syntax 与 diff check 通过。
- SuBing Natural Canary 继续 pending；Task 6 Gate A release、Gate B production migration 与
  Gate C Runtime promotion 已完成，Gate D 仍为 `disabled / not activated`。

## 当前可执行面

- Web：`/market`、`/market/chart` 与 `/trade-records`。
- HTTP：`/api/v1/market/*`、`/api/alerts/*`、`/api/execution-review/*`、`/api/runtime/health`
  和轻量 health。
- CLI：`guiyi data update|refresh|audit|after-market`；只读
  `guiyi research subing-calibration`、`guiyi runtime status|live|alert`。
- `guiyi runtime alert-canary` 是真实 WeCom Gate，不是普通测试命令。
- Runtime：Live 与盘后更新共用同一 `operational_products.txt`；盘后时点为 18:05，
  只对 `NEXT_TRADING_SESSION_NOT_READY` 允许最多一次一小时后 retry。

已退役且不得恢复为兼容入口：backtest API/Web/worker/queue、Signal/Review/Strategy
HTTP·Web·worker、data-center HTTP、旧 RQ worker/scheduler、自动交易与真实订单。

## 已冻结合同

- 基础 provider 周期只有 `1m/1d`；`1w` 只从完整同源交易所日行情聚合，并在同一 maintenance
  批次用同一 source snapshot 刷新对应 Canonical `1d`，
  `5m/15m/30m/60m` 只从质量通过的同 Dataset Canonical `1m` 按 TradingSession 聚合。
- 物理 Dataset 只有 `continuous|contract`；`actual_dominant` 只在查询时按
  `MainContractMap rank=1` 拼接。
- 每 Dataset 每自然月只有一个 `part.parquet`。schema、identity、session/frequency、OHLCV、
  coverage、row count、Catalog URI 和物理可读性不一致时 fail-closed。
- Market Catalog 精确为八表；`alert_rules` / `alert_events` 是独立 Alert Application Domain，
  不属于且不改变八表合同。production DB revision 当前为 `20260815_0039`；
  `trade_decisions` / `trade_episodes` / `trade_executions` / `trade_reviews` 是独立
  Execution Review Application Domain，0039 未改变 Market 八表或 Alert 两表 schema identity。
- SuBing 只使用 current-rank1-segment-local Historical/completed Live，不做 pre-rank1 warm-up、
  cross-roll EMA/MACD 继承或 zero-band hard gate；1d 仍为 `RESEARCH_PENDING`。
- Alert HTDY 保持 event-cutoff；SuBing 只复用 accepted Calibration、FormalPolicy 和
  `SubingReadService` resolver。incoming Event Bar 与读回的当前最后 Bar 必须整体相同。
- Alert Event 先提交，然后最多尝试一次 WeCom；不建 replay/backfill/retry/outbox/queue。

## 当前 Runtime 事实

- `2026-08-16 21:04 +08:00` 已按单次 Gate C 授权把 API/Web/Market Live/after-market/Alert
  promotion 至 clean/detached/exact-tag Runtime 根
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.4.0`，统一提交为
  `3a6f4289ff08848f9177c41a649a94f877412c23`，API version=`1.4.0`。
- API/Web/Live/Alert 均 running，after-market 为 schedule-only `not running`；Runtime
  health=`ok/readonly=true`，Market 主力目录为 active 60。旧 Runtime 根
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.3.0` 与提交
  `3e930a032c6b880686ff1f1fccc77db61bc2803c` 继续保留，用于 Gate C 外部 Review 完成前的
  bounded rollback identity，未被删除或重载。
- Market Runtime V1 持续授权已按原 active 60 范围迁移至 `v1.4.0`；Alert Runtime V2
  持续授权已按原 Rule/Scope（`htdy_original_15m -> jm`、
  `subing_entry_signal_v1 -> jm`）迁移至 `v1.4.0`，未扩大范围。
- 当前为周末：Live `CLOSED=60/subscribed=0`，after-market=`pending`且仅保留 18:05 schedule。
  本次切换未执行 migration、
  RQData/Canonical/DB 写入、Scope mutation、真实 WeCom、手工盘后、replay/backfill/retry、tag
  或 release；`auto_order=false` 不变。

## Gate 与最小下一步

- Gate A 已完成 release PR、main merge、annotated tag 与 main -> develop ancestry synchronization。
- Gate B 已完成 production additive `20260815_0039` migration；Execution Review 四表已存在，
  Market 八表与 Alert 两表 normalized schema signatures 保持不变。
- Gate C Runtime promotion 已完成；正式五服务已统一加载 `v1.4.0` identity
  `3a6f4289ff08848f9177c41a649a94f877412c23`，Execution Review production Runtime surface
  已 available。Gate D 仍为 `disabled / not activated`。
- 周线修复的部署身份已读回；业务级效果等待下一次自然 18:05 盘后更新，不手工运行、回填或补证。
- SuBing Natural Canary 继续作为独立 pending evidence；无自然 Event 就保持 pending，
  不人工补证，也不计作 Task 6 已完成事实。
- 最小下一步：完成 Gate C 外部只读 Review；Natural Canary 继续作为独立
  pending evidence，Gate D 除非获得新的明确授权，否则保持关闭。
