# 当前状态

更新时间：2026-08-16

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

## Execution Review V1 candidate（UNRELEASED）

- 状态为 `CODE_COMPLETE / TEST_COMPLETE`；这是 branch-neutral implementation candidate，不声明已经
  集成 `develop`、发布、迁移或部署。production release 仍为 `v1.3.1`，production DB 仍为
  `20260814_0038`，Runtime identity 未改变。
- 候选代码新增 `/trade-records` 与 `/api/execution-review/*`，以四张独立 Application Domain 表保存
  苏冰 Event 的人工 Decision、真实手工 Execution timeline、单品种 OPEN Episode 与结构化 Review；
  不恢复旧 Review Center，不连接账户或创建订单。
- official multiplier coverage = `7 / 60`。reference 与 official evidence 集合精确相等、无重复、
  无 unknown，逐行 derived multiplier 与 reference 相等。缺失 multiplier 只影响人民币
  Estimated Gross PnL availability；realized points、仓位拓扑、时间线与 Review 保持可用。
- trusted-partial snapshot 在 Episode 创建时冻结；当时为 NULL 的历史 Episode 不因未来 reference
  扩大自动改写。active-60 60/60 是后续独立 Lane 3 reference-data objective，不是 v1.4 release Gate。
- 完整验证：backend `1031 passed`；engineering `41 passed`；Ruff 通过；Mypy 54 files 无问题；
  Web unit `145 passed / 1 conditional skip`；Market/Alert/Execution Review E2E `50 passed`；Web
  production build、secret scan（0 findings）、shell syntax 与 diff check 通过。
- SuBing Natural Canary 继续 pending；Task 6 的 release、production migration、Runtime promotion
  与 roll marker activation 均未执行，`Gate D not activated`。

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

- 基础 provider 周期只有 `1m/1d`；`1w` 只从完整同源交易所日行情聚合，并在同一 maintenance
  批次用同一 source snapshot 刷新对应 Canonical `1d`，
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

- `2026-08-15 23:24 +08:00` 已按单次授权把 API/Web/Market Live/after-market/Alert 合并到唯一
  clean/detached Runtime 根 `/Volumes/扩展盘/guiyi-quant-runtime-v1.3.0`，统一提交为
  `3e930a032c6b880686ff1f1fccc77db61bc2803c`。该目录名仅是部署根名称；API version=`1.3.1`，
  运行身份以精确提交为准。
- API/Web/Live/Alert 均 running，after-market 为 schedule-only `not running`；Runtime
  health=`ok/readonly=true`，Market 主力目录为 active 60。旧 Runtime worktree
  `guiyi-quant-runtime-3e930a032`、`guiyi-quant-runtime-51b1f44f8` 和
  `guiyi-quant-runtime-a12ac867` 已删除，仅保留上述唯一 Runtime 根。
- 当前为周末：Live `CLOSED=60/subscribed=0`，after-market=`skipped/NON_TRADING_DAY`。本次切换未执行 migration、
  RQData/Canonical/DB 写入、Scope mutation、真实 WeCom、手工盘后、replay/backfill/retry、tag
  或 release；`auto_order=false` 不变。

## 未执行 Gate 与最小下一步

- 本轮除上述已授权 Runtime switch 外，不执行 migration、真实 RQData/Canonical/DB 写入、
  Scope mutation、WeCom、tag 或 release。
- 周线修复的部署身份已读回；业务级效果等待下一次自然 18:05 盘后更新，不手工运行、回填或补证。
- 唯一待自然事件：继续等待 `subing_entry_signal_v1 × jm` 的后续自然 completed Bar 验收；
  无事件就保持 pending，不人工补证。
