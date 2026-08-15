# 当前状态

更新时间：2026-08-15

## 当前结论

- Data Foundation 的 DFD-01～DFD-07 已全部完成并归档：active universe 的 **60/60** 个品种在固定
  `T0=2026-08-11` 完成 Canonical 闭环，全域 audit 为 `passed`、0 findings。
- 历史事实链固定为 `RQData -> staging + 六项硬校验 -> Canonical Parquet -> 八表 Catalog ->
  MarketDataService`；物理 Dataset 只有 `continuous|contract`，`actual_dominant` 只按 rank1 map 查询拼接。
- Market Runtime V1 只提供行情研究观察。Historical Canonical 与 Redis Live Overlay 分离，Live 不写
  Parquet，`auto_order=false`，仓库不存在订单创建或提交路径。
- SuBing Factor Observation V1 已在 `develop` 完成只读代码闭环：只展示 current rank1
  segment 的 Kline/EMA/MACD/Factor，且有效当前合约视图不覆盖用户的 Market series
  preference；盘中仅合并同当前合约的 completed Live Bar，不做 pre-rank1 warm-up 或
  cross-roll 指标状态。Calibration Gate A 已通过并冻结
  `5m=0.688190651160584793944957992`、`15m=1.329531078893356968545882036`
  两个 exact Decimal 作为 EMA21 flat / trend-persistence filter；Gate B-R 也已由用户人工批准，
  intraday V1 接受 slope-only Calibration promotion。随后完成 intraday Zero-Band
  Discovery 与冻结候选 C 对 NO-BAND 的非重叠 OOS Validation：5m 没有表现出增量价值，15m 只有
  5K 局部改善且三个 horizon failure 均更高、样本稀疏，因此当前设计已**拒绝 intraday V1
  zero-band hard gate**；`macd_zero_distance_abs/bps` 继续保留为 Factor/Web/research 字段，不进入
  executable Signal 条件或 accepted intraday Calibration。15m LONG/SHORT OOS asymmetry 只记录为
  observation risk，不创建方向特例、方向阈值或禁用 LONG。slope-only Calibration 已以
  `data/research_policies/subing_calibration_intraday_v1.json` 成为 Git-tracked 仓库事实；
  MACD Gate C 已由用户人工批准，且只批准 SuBing V1 Entry Signal 的 scoped consumer；generic MACD
  继续保持 `compatibility_validated`，backtest/live/alert capability 均未改变。scoped policy 固定为
  `subing_macd_sma_window_scale2_v1`，数学 equivalence tuple 为
  `("sma_window", 2, "fast12_slow26_signal9", True)`。Gate C 不批准 Alert V2 或 Runtime。SuBing V1
  slope-only formal Signal pure core、tracked Calibration 注入及 Product Workspace
  只读 Signal observation 已完成并通过独立 Lane 3 Review：5m/15m 的 `primary_signal` 始终保留
  requested timeframe evaluation，`resolved_signal` 只表示可选的实际 MATCHED opportunity；same READY
  boundary 会评估完整 reciprocal opportunity，因此 reciprocal-only MATCHED 不会遗漏，双 MATCHED
  同方向时 15m wins、反方向 fail-closed，普通 reciprocal NOT_MATCHED 不覆盖 requested primary。1d
  继续 `RESEARCH_PENDING`，是独立 non-blocking future research track。本实现不持久化 Signal，不接
  Alert V1/V2，不部署或晋升 SuBing Runtime，不写 DB/Canonical，`auto_order=false`。该 SuBing
  Task 7 状态本身不批准 Alert V2、Runtime、Strategy、Backtest 或任何交易能力。
- 连续两个交易日的 17:00 首次盘后尝试都以 `ValueError` 进入一小时 retry，第二次均成功；
  现有时序与 18:00 后补齐证据高置信指向下一交易日 Session 尚未就绪，但历史日志无子码无法直接证实。
  `develop` 已将目标调度收敛为 18:05，并把该时点缺口精确分类为
  `NEXT_TRADING_SESSION_NOT_READY`；当前隔离 Runtime 已运行包含 18:05 模板的 `v1.3.0^{}`。
- Alert V1 已在 `develop` 完成代码实现：server-side Scope、actual-dominant confirmed 15m 的 Python HTDY
  current-bar evaluator、幂等 AlertEvent、单次简洁 WeCom sender、独立 Runtime/health/launchd 边界，以及
  Product Workspace persistent 🔔 Marker。它不 replay/backfill/retry，也不恢复 Signal/Review/Strategy。
- Alert V1 的 G1/G2/G3 已分别按单次授权执行：production migration 与真实 WeCom canary 已完成，Alert
  Runtime 已仅以 `jm`（焦煤）Scope 激活。`2026-08-13 22:31 +08:00` 已自然产生 `JM2609` confirmed
  15m HTDY `sell` observation：唯一 AlertEvent 落库、统一行情 32-bar 窗口重算一致、用户确认 WeCom
  实际收到，Event API 可读 persistent 🔔 事实。`2026-08-14` 又按单次授权将 Alert label 切换到
  clean/detached `4f1598e9...`，API health 读回 `components.alert.status=ok`。Alert V1 自然通知闭环已验收。
- 前述 SuBing Factor/Signal 开发轮未修改 Rule/Scope/Event、WeCom 或 Alert Runtime，不改变上述
  Alert V1 业务语义；其后完成的 Alert 自然闭环与 detached switch 也不授权 Alert V2 或
  SuBing Runtime。
- `2026-08-14` 完成 Alert/HTDY/SuBing 跨代码、测试、运维与文档的彻底 Review 收口：SuBing Historical
  同时校验 current rank1 segment 起止、production Calibration exact identity 与独立 EMA21 标签分母，已知
  Signal 条件失败不再误报 `RESEARCH_PENDING`；HTDY Alert evaluator 增加 scoped FormalPolicy，Alert
  message/heartbeat 改为短 Session，WeCom sender/health 共用严格目标校验；launchd 状态改为核对实际已加载
  root/commit；Web 标记稳定排序并把 SuBing/Alert 页面生命周期拆入 composable，删除只被测试引用的死代码
  和三个已完成的一次性实施 Plan。上述均是 `develop` 代码/文档收口，不执行 migration、通知、数据写入、
  release 或 Runtime switch。
- Alert V2 backend 已在 `v1.3.0` 达到 `CODE_COMPLETE / TEST_COMPLETE`：Code Registry 精确为
  `htdy_original_15m + subing_entry_signal_v1`，AlertRule V2 只保留可变 Scope，AlertEvent V2
  保留事件 identity/trading-day/result/confirmation 事实；current trading day 复用
  `MarketPhaseResolver + operational_products.txt` 且不可用时 fail-closed。HTDY 保持 event-cutoff；
  SuBing 只复用 Factor/accepted Calibration/FormalPolicy/`SubingReadService` resolver，没有复制公式或
  same-boundary 规则，stale identity、final Session arrival grace 和 TradingSession bucket defer 都已按合同
  fail-closed。Event commit 先于 one-shot WeCom，无 replay/backfill/retry/outbox/queue/Signal Center/
  订单，`auto_order=false`。migration `20260814_0038` 只修改两张 Alert Application Domain 表，
  SuBing seed Scope 为 `[]`，不属于且不改变八表 Market Catalog。release tree 最终验证为 backend
  `782 passed, 14 skipped`、Engineering `29 passed`、Ruff/Mypy/Web unit/selected Playwright/Web build/
  secret scan/diff check/render-only/plist lint
  全部通过。
- `v1.3.0` 已发布：annotated tag object 为 `75580bf69527a657539d563373f40341be41d505`，
  peeled target、`origin/main` 与 release 时的 `origin/develop` 均为 release merge
  `d7b45ffcd563abe37963620de45fe41978e6c839`。
- `v1.3.1` Market Web 品牌重设计补丁已通过 release PR #166 发布：annotated tag
  object 为 `6b6476ffa9f1bec5bb6a90dcc0608c42426a8c96`，peeled target 与 `origin/main` 均为
  `aebb8da211961d7385618f8f6c46d5cd373482bc`；`origin/develop` 为发布准备提交
  `ead3adc28981d278f961050ba47d969ac6e126f4`。本补丁只收口前端视觉、Radar 加载/失败恢复、
  板块 Tab 与图表/Marker 语义色，未改指标公式、Signal 判断或 Alert API。
- `2026-08-15` 按四个独立单次 Gate 完成 release、maintenance、production `20260814_0038`
  migration 与五服务 Runtime promotion，其中维护窗口为 `11:56–12:16 +08:00`；Runtime 根精确为
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.3.0`，API health version=`1.3.0`。HTDY Scope 保持仅 `jm`，
  migration 与 Runtime promotion 完成时 `subing_entry_signal_v1` Scope 仍为 `[]`，且这两个 Gate
  未执行 Scope PUT。随后用户通过 Product Workspace 的“苏冰入场信号”开关，主动完成
  `subing_entry_signal_v1 × jm` 的精确 Scope activation。production 读回确认
  `scope_products=["jm"]`、SuBing AlertEvent=0、Alert health=`ok`，且没有隐式加入其他品种。该操作构成
  v1.3 Task 8 的 exact Rule + Product Gate；从激活成功后，Alert Runtime 获得对
  `subing_entry_signal_v1 × jm` 后续自然 completed Bar 的有界持续处理与一次性 WeCom 尝试授权。
  当前尚无自然 SuBing Event，Task 9 Natural Canary 仍为 pending；未创建 synthetic Event，未执行
  replay/backfill/retry。测试路由 Scope PUT 不构成真实 Scope mutation 授权。
- 九个退役品种 `br/cs/ic/if/ih/im/lu/nr/sp` 已完成生产清退且 residual=0；运行时继续保留退役名单防护，
  不再保留重复执行生产删除的 CLI。

## 当前可执行面

- Web：Market 列表与 K 线工作台。
- HTTP：production `v1.3.1` 包含历史分页、dominants、Historical/Live state、WebSocket、Alert V2 Rule Scope/
  Event/current formal-signals/product current-events API 和只读 Runtime health。
- CLI：`guiyi data update|refresh|audit|after-market`、只读 `guiyi research subing-calibration`、
  `guiyi runtime status|live|alert|alert-canary`；其中 `alert-canary` 是真实通知 Gate，不能作为普通测试执行。
- Runtime：`operational_products.txt` 是 Live 与目标 18:05/最多一次一小时后 retry 盘后更新的唯一范围入口；
  该文件已与 active 60 完全对齐，当前隔离 Runtime 已加载 18:05 模板。
- Alert Runtime：production `v1.3.1` 的 code-defined Rule 为 `htdy_original_15m` 与
  `subing_entry_signal_v1`；HTDY server-side Scope 精确为 `jm`，SuBing Scope 精确为 `jm`。两条 Rule 都不从
  `operational_products.txt` 自动扩大 Alert Scope。

已退役且不得恢复为兼容入口：backtest API/Web/worker/queue、Signal/Review/Strategy HTTP·Web·worker、
data-center HTTP、旧 RQ worker、旧 scheduler、自动交易与真实订单。

## 已冻结的数据合同

- 基础 provider：`1m` 使用 RQData `get_price`，`1d` 使用交易所日行情。
- 派生：`1w` 只从完整同源日线聚合；`5m/15m/30m/60m` 只从同 Dataset、质量通过的 Canonical `1m` 按 TradingSession 聚合。
- 每个 Dataset 每自然月只有一个 `part.parquet`；schema、identity、session/frequency、OHLCV、coverage、
  row count 与物理可读性全部通过后才能原子发布。
- Data Foundation / Market Catalog 精确为八表：`exchanges`、`instruments`、`contracts`、`trading_calendars`、
  `trading_sessions`、`main_contract_map`、`market_datasets`、`market_partitions`。
- `2026-08-13 14:19 +08:00` 已按单次授权将 production PostgreSQL 从 `20260808_0036` 升级到
  `20260813_0037`。只读读回确认八表 Market Catalog 全部仍在，`alert_rules` / `alert_events` 两张独立
  Application Domain 表存在；唯一 seed 为 enabled 的 `htdy_original_15m`、`watchlist`、空 Scope，
  AlertEvent=0，Event 幂等唯一约束与 `symbol,bar_end` 查询索引存在。此次未发送通知或启用 Alert Runtime。
- `2026-08-15` 已按独立单次 DB Gate 将 production 从 `20260813_0037` 升级到
  `20260814_0038`。读回确认 AlertRule/Event V2 columns、checks、唯一约束与索引正确；HTDY `jm`
  Scope 和 3 条历史 Event 保留，SuBing Rule 在 migration 时已 seed 且初始 Scope=`[]`、Event=0，八表
  Catalog 计数逐项不变。随后用户通过 Product Workspace 独立开启 `subing_entry_signal_v1 × jm`；当前
  production 读回为 Scope=`["jm"]`、Event=0，没有隐式加入其他品种。
- `2026-08-13 14:35 +08:00` 已将 WeCom webhook 写入本机 Runtime secret source（权限 `600`，值不入仓库、
  DB 或日志），随后按单次 G2 授权尝试 `guiyi runtime alert-canary`。手工命令缺少 `packages/quant-core`
  的 `PYTHONPATH`，CLI 在导入阶段以 `ModuleNotFoundError` 停止，sender 未构造且未发起 HTTP；因此没有
  企业微信消息，G2 未完成且该次授权已消耗。只读读回继续为 Scope 为空、AlertEvent=0、Alert Runtime
  activation marker 不存在；正确的 CLI 依赖路径已通过只读 import 验证，未自行重试。
- `2026-08-13 14:42 +08:00` 已按新的单次授权使用完整项目 `PYTHONPATH` 重试 G2；固定
  `runtime alert-canary` 返回 `status=ok`，企业微信接口接受测试文案。发送后只读读回仍为 Scope 为空、
  AlertEvent=0、Alert Runtime activation marker 不存在；未修改 Rule/Scope、未伪造正式 Event、未启用
  或切换 Runtime。G2 至此完成，但不授权 G3。
- `2026-08-13 14:47 +08:00` 已按单次 G3 授权将 `htdy_original_15m` Scope 从空集精确更新为仅 `jm`，
  并只安装/启动 `com.guiyi.quant-alert`。Alert label 根为当前 `develop` 提交 `9c310599...`，独立 activation
  marker 为 enabled；API/Web/Live/after-market 未由此次脚本分支重载或改根。按 launchd wrapper 的真实
  Redis 环境只读读回 `components.alert.status=ok`、webhook configured、enabled_rule_count=1、
  scope_product_count=1，heartbeat 从 `06:47:00Z` 推进到 `06:47:10Z`；数据库仍为 AlertEvent=0。
  `2026-08-13 22:31 +08:00` 自然到达交易日 `2026-08-14` 的 `JM2609` confirmed 15m Bar，Runtime 在
  `22:31:03.977 +08:00` 检出 `sell` 并创建唯一 Event id=1；只读读回 Event 总数=1、Scope 仍仅 `jm`。
  `MarketReadService.bars_until()` 以 event-day rank1 取得精确截止该 Bar 的 32 根 actual-dominant 15m，
  HTDY current-bar 独立重算仍为 `sell`；用户确认 WeCom 实际收到。未 replay/backfill/retry 或手工造 Event。

## 历史验收事实

- 60 品种均完成 `apply -> audit -> fixed-T0 no-apply NOOP`，最终全域 audit 为 0 findings。逐品种过程、
  故障诊断和 provider 请求量只从 Git history 追溯，不再复制到当前状态页。
- 四品种阶段的 10:15 BREAK/10:31 恢复、11:30 BREAK/13:33 恢复、17:00 自然盘后、rank1 reconciliation、
  Canonical seam 更新和 Live 不写 Parquet 均已验收；这些是历史阶段证据，不冒充本轮 60 品种部署证据。
- 周末 CLOSED 与 `non_trading_day skipped` 按既有决定接受，未制造新的自然现场证据。
- 部署、生产数据写入、真实通知、`main`、tag/release 与未来 Runtime switch 仍是相互独立的人工 Gate。

## 当前 Runtime 读回

- `2026-08-15 19:29 +08:00` 已按单次授权将五服务 Runtime 统一切换到 clean/detached exact
  commit `51b1f44f8ffb3580054ed591053e7eda451506f3`，独立根为
  `/Volumes/扩展盘/guiyi-quant-runtime-51b1f44f8`。该提交修复非交易日盘后返回
  `skipped/NON_TRADING_DAY` 时 CLI 误退出 1 的问题；目标工程 122 项 Runtime/盘后回归、Ruff、
  Web production build、bundle topology 与 render/plist lint 通过。API/Web/Live/after-market/Alert
  五个 label 的 loaded root 与完整 loaded commit 全部一致；API/Web/Live/Alert 为 running，
  after-market 保持 schedule-only `not running`，状态脚本 `overall=passed`，API version=`1.3.1`，
  Runtime health=`ok/readonly=true`，production revision 仍为 `20260814_0038`。周末 Live 为
  `CLOSED=60/subscribed=0`，JM actual-dominant 不暴露 Live overlay；dominants=60 且品种唯一、
  `jm -> JM2609`，Radar=`ready`、active/participant=60/60、stale/unavailable=0。`jm` 的
  HTDY/SuBing 两条 Rule 仍均 enabled，Event 仍为 3/0，周末 current 接口明确 `unavailable`。
  新根没有复制旧根的 18:05 状态，因此 after-market 为可读 `pending/last_run=null`；未手工
  补跑、未执行 migration、Scope mutation、真实 WeCom、replay/backfill/retry 或 Canonical 写入，
  `auto_order=false` 不变。旧 `aebb8da2...` Runtime worktree 保留，未执行回切。
- `2026-08-15 17:01 +08:00` 已复用现有 `/Volumes/扩展盘/guiyi-quant-runtime-v1.3.0`
  Runtime 根完成 `v1.3.1` switch；目录名保留历史名称，运行身份以 clean/detached
  exact tag=`v1.3.1` 与 peeled commit
  `aebb8da211961d7385618f8f6c46d5cd373482bc` 为准。API/Web/Live/after-market/Alert 五个应用 label
  的 loaded root 与完整 loaded commit 全部一致；API/Web/Live/Alert 为 running，after-market 保持
  schedule-only `not running`，状态脚本 `overall=passed`。API health version=`1.3.1`；Runtime
  health=`ok/readonly=true`，DB/Redis/Live/Alert 均为 `ok`，after-market 为可读 `pending`。当时为周末
  CLOSED=60/subscribed=0；dominants=60 且品种唯一，`jm -> JM2609`；Radar=`ready`、
  active/participant=60/60、stale/unavailable=0。`jm` 的 HTDY/SuBing 两条 Rule 仍均 enabled；
  当前交易日 resolver 在周末不可用时，formal-signals/current-events 明确返回 `unavailable`。
  本次未执行 migration、Scope mutation、真实 WeCom、replay/backfill/retry、手工盘后、Canonical 写入或
  Runtime 目录迁移；`auto_order=false` 不变。
- `2026-08-15 14:03 +08:00` 此前只读读回：exact `v1.3.0` Runtime 身份与五服务 loaded root/commit
  无 deployment drift，状态脚本 `overall=passed`，API version=`1.3.0`，production revision=
  `20260814_0038`；DB/Redis/Live/Alert 均为 `ok`。Code Registry 仍精确为
  `htdy_original_15m + subing_entry_signal_v1`；两条 Rule 的 production Scope 均精确为 `jm`，HTDY Event=3、
  SuBing Event=0。SuBing Scope 是用户通过 Product Workspace 主动完成的 Task 8 exact activation；Task 9
  Natural Canary 尚未完成，未观察到自然 SuBing Event，未创建 synthetic Event 或执行 replay/backfill/retry。
- `2026-08-15 12:16 +08:00` 最终读回：Runtime worktree clean/detached 且 exact tag=`v1.3.0`，
  API/Web/Live/after-market/Alert 五个应用 label 的 loaded root 均为
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.3.0`，完整 loaded commit 均为
  `d7b45ffcd563abe37963620de45fe41978e6c839`。API/Web/Live/Alert 为 running，after-market 保持
  schedule-only `not running`；状态脚本 `overall=passed`，API/Web HTTP 200，API version=`1.3.0`。
  Runtime health 为 `ok/readonly=true`：DB/Redis/Live/Alert 为 `ok`，after-market 为可读的 `pending`
  且尚无本 Runtime 根的自然 run；operational=60、当前周末 CLOSED=60/subscribed=0，Alert
  enabled_rule/scope=2/1。该激活前时点的业务读回确认 `jm` 的 HTDY enabled、SuBing disabled；当前交易日 resolver
  unavailable 时 formal-signals/current-events 明确返回 unavailable。production revision=`20260814_0038`，
  HTDY Event 仍为 3、SuBing Event=0；该次 Runtime promotion 未修改 Scope、发送真实 WeCom、
  replay/backfill/retry、手工盘后、写 Canonical 或执行 natural SuBing canary。其后独立的 Product Workspace
  activation 事实以上述 14:03 最新读回为准。
- `2026-08-14 14:24 +08:00` 已按本次明确授权将隔离 Runtime 切换到 annotated tag `v1.2.0` 的
  peeled commit `ba111533f2502cbead02770f7fc8f363adb03a55`；checkout clean/detached 且
  `git describe --exact-match=v1.2.0`。API/Web/Live/after-market/Alert 五个应用 label 的 loaded root
  只指向该 worktree，loaded commit 均精确为 `ba111533`；API/Web/Live/Alert 为 running，after-market
  保持 schedule-only 的 not running，状态脚本 `overall=passed`。API `/api/health` 读回 version=`1.2.0`，
  Runtime health 为 `ok/readonly=true`，DB/Redis/Live/after-market/Alert 均为 `ok`；Live
  operational/subscribed=60/60，Alert enabled_rule/scope=1/1。业务读回为 dominants=60、`jm -> JM2609`，
  火天大有 `htdy_original_15m` 仍仅对 `jm` 启用，苏冰 `jm/15m` 为 current-rank1 `JM2609`、
  calibration=`accepted`、只读 signal=`not_matched`。本地 FRPC 链通过。本次未执行 migration、手工盘后或
  Canonical 写入、真实 canary/通知、Nginx/公网配置变更。
- `2026-08-14 13:54 +08:00` 已按单次授权将本机隔离 Runtime 固定到 clean/detached
  `d82e06ccca0b596c0147549fc93422a0e7794577`，并统一重载 API/Web/Live/after-market 与已启用 Alert。
  五个应用 label 的 loaded root 均为该隔离 worktree，`GUIYI_RUNTIME_COMMIT` 均精确匹配 `d82e06cc`；
  API/Web/Live/Alert 为 running，after-market 保持 schedule-only 的 not running，状态脚本
  `overall=passed`。API/Web HTTP 200，Runtime health 为 `ok/readonly=true`，DB/Redis/Live/after-market/
  Alert 均为 `ok`；Live operational/subscribed=60/60，Alert enabled_rule/scope=1/1。业务读回为 dominants
  60、`jm -> JM2609`，火天大有 `htdy_original_15m` 仍仅对 `jm` 启用，苏冰 `jm/15m` 为
  current-rank1 `JM2609`、calibration=`accepted`、只读 signal=`not_matched`。本次未执行 migration、
  手工盘后或 Canonical 写入、真实 canary/通知、`main`、tag/release。
- `2026-08-14 12:31 +08:00` 已按单次授权只将 `com.guiyi.quant-alert` 从可变 develop 根切换到现有
  clean/detached Runtime `4f1598e9d84578f3a4468f1d859ed60106b5cae2`；该提交与当前 develop 的 Alert、
  health、MarketRead seam 和 installer 代码逐文件一致。只在 detached 根写入 Alert activation marker，
  只重载 Alert label，并清除旧 develop 根的失效 marker；API/Web/Live/after-market 未重载。launchd 根与
  marker 唯一指向 detached Runtime，API Runtime health 为 `ok/readonly=true`，Alert 为
  `status=ok`、webhook configured、enabled_rule_count=1、scope_product_count=1，heartbeat 新鲜可用。
- `2026-08-13 17:00:02 +08:00` 的 60 品种自然盘后首次尝试在实际分区处理前以 `ValueError` 退出；未人工
  补跑，唯一一小时 retry 随后完成，并于 `19:20:23 +08:00` 写入 `status=passed`、`attempts=2`、
  `last_successful_trading_day=2026-08-13`，launchd exit code=0。只读验收确认 continuous
  `1m/5m/15m/30m/60m/1d` 全部 60/60 推进至 `2026-08-13T07:00:00Z`，Radar=`ready`、participant=60、
  stale/unavailable 为空，当日 Live bar/subscription keys 均已清理；`1w` 正确停在已完整周
  `2026-08-07T07:00:00Z`。
- `2026-08-13 00:02 +08:00` 在不重载、不手工盘后或数据写入的情况下，已只读观察到 RQData Live
  provider 额度自然恢复：Runtime health 回到 `ok/readonly=true`，Live heartbeat 报
  operational=60、phase-scoped subscribed=11、`error_type=null`，last bar/heartbeat 均推进；DB、Redis 与
  after-market 继续为 `ok`。订阅数按当时 `TRADING=11` 动态变化，不要求 60 个 channel 同时订阅。
- `2026-08-12 23:15 +08:00` 已将隔离 Runtime 固定到 clean/detached `v1.1.0^{}`=
  `f2568ba2fc3cbcf515abba1e51f12eacd30f8ff0`；API package 读回为 `quant-api 1.1.0`，Web production
  build、API/Web reload 与四个 launchd 根一致均已确认。API/Web HTTP 200、Radar 为 `ready`（active=60、
  participant=60、stale/unavailable 为空），JM actual-dominant 15m 可读，active/operational 均为 60，
  after-market activation=true 且最近自然盘后记录仍为 60 品种 `passed`。
- 同次只读读回的 Runtime health 曾为 `degraded`：Live heartbeat 仍报告 operational=60，但当前
  subscribed=0，原因是 RQData Live provider 返回 quota exhausted；未做手工盘后、数据写入、重载或重试。
  DB、Redis、after-market 均为 `ok`，Historical/Canonical 与 Radar 读取不受影响；该外部限额已如上自然恢复。
- `2026-08-12 22:43 +08:00` 已按单次授权将隔离 Runtime 固定到 clean/detached
  `8547c0afb974a3b73b68a5207fd1d731d56a54ed`，即 P0 基线加 Runtime health 修复；运行时 API
  依赖同步和 Web production build 均通过。部署脚本在 API `kickstart` 返回一次
  `Operation not permitted` 后停止，未进行重试；随后的只读读回确认 API/Web/Live 皆 running、after-market
  等待下一时点，且四个 launchd 根均只指向该隔离 worktree。
- 此次 Runtime health 为 `ok/readonly=true`，`components.after_market.configured_enabled=true`，修复已在
  运行实例生效；Radar 仍为 `ready`、active=60、participant=60、stale/unavailable 为空，JM actual-dominant
  15m 为 operational/live_available，active 与 operational 配置均为 60。
- `2026-08-12 22:25 +08:00` 已按单次授权将隔离 Runtime 固定到 clean/detached
  `e9eedb1b93c64af4ca899e8384312de052a24637`；运行时 API 依赖同步和 P0 Web production build
  均通过，API/Web/Live/after-market 四个 launchd plist 根均只指向该隔离 worktree，且 Market Runtime
  activation marker 已启用。未执行 migration、手工盘后、数据任务、通知、release 或 `main` 操作。
- 切换后只读回读为 API/Web HTTP 200、Runtime health `ok/readonly=true`；DB/Redis/Live 均为 `ok`，
  Live heartbeat 报 operational=60（当时 phase-scoped subscribed=45）。实际 Market 业务字段可读：
  JM actual-dominant 15m 为 operational/live_available，Product Research 当前主力为 `JM2609`；Radar 为
  `ready`、active=60、participant=60、stale/unavailable 均为空、`expected_as_of=2026-08-12`。
- 同次只读范围核对为 active=60、operational=60；盘后公开状态的最近成功记录仍为
  `2026-08-12`、`passed`、attempts=2、products=60。发现一个不改变实际运行状态的 Runtime health
  响应呈现缺陷：`components.after_market.configured_enabled` 未透传 activation marker 而默认显示为 false。
  该根因已由 `8547c0af...` 修复、部署并在上述 Runtime health 读回为 true；旧 `e9eedb1b...`
  实例的 false 仅保留为切换前观察记录。
- `2026-08-12 20:38 +08:00` 已将隔离 Runtime 从 `0dea973d...` 单次切换到 clean/detached
  `v1.0.0^{}`=`423b049830087e7885736e6e5471d5e289134bbe`；`uv sync --no-dev`、Web production build 与
  bundle topology 均通过，API/Web/Live/after-market 已从同一 Runtime 根重载。API/Web/Live 为
  running，after-market 为等待下一个 17:00 的 not running。未运行 migration、手工盘后、数据任务或通知。
- production 读回为 `quant-api 1.0.0`；API/Web HTTP 200、Runtime health `ok/readonly=true`，DB/Redis/Live
  均为 `ok`。Market dominants 返回 60 个唯一且业务字段完整的品种，映射日均为
  `2026-08-12`；JM actual-dominant 15m 真实读取的 Canonical edge 为 `2026-08-12T07:00:00Z`。
- 本机 FRPC 进程、5173/8000 监听与本地 HTTP 链通过。当前 Runtime 环境未配置
  `PUBLIC_BASE_URL`/Basic Auth 验收变量，因此本次未运行公网 `public-healthcheck.sh`，也未重载
  未变更的 FRP/Nginx 配置。
- 配置读回为 active=60、operational=60 且内容相同。`2026-08-12 17:00:01 +08:00`
  launchd 自然触发 60 品种盘后更新；第一次在 Canonical update 阶段抛出 `ValueError`
  而失败，无代码变更、无人工补跑，一小时后的唯一自动 retry 于 `19:15:06 +08:00`
  完成：`status=passed`、`attempts=2`、`error_code=null`、`last_successful_trading_day=2026-08-12`，
  launchd `runs=1/last exit code=0`。公开日志按合同只保留异常类型，不将未记录的具体 provider 子原因
  升级为确定结论。
- 盘后只读核对为当天 TradingSession 60/60、MainContractMap rank1 60/60；continuous
  `1m/5m/15m/30m/60m/1d` 的 60 品种统一推进至 `2026-08-12T07:00:00Z`，`1w` 统一停在
  已完整周 `2026-08-07T07:00:00Z`；当天 rank1 真实合约的 `1m/5m/15m/30m/60m/1d`
  也为 60/60。Runtime health 读回 Live `CLOSED=60`、`subscribed_count=0`，表明当日 Live snapshot
  已清理；Live 仍未写入 Parquet。

## v1.2.0 发布范围

- 版本源、README 与 changelog 已收口为 `1.2.0`。本版本在 `v1.1.0` 的 Market Research Workspace
  基线上增加 Alert V1、火天大有窄范围自然预警、苏冰 current-rank1 Factor/Calibration/Signal 只读观察、
  18:05 盘后调度与 Runtime loaded-commit 身份核对。
- Alert V1 只保留 `htdy_original_15m × enabled scope_products × WeCom`；当前 Scope 精确为 `jm`，不从
  operational 60 自动扩大。SuBing Signal 不持久化、不接 Alert、不自动晋升参数或 Runtime，1d 继续
  `RESEARCH_PENDING`，Zero-Band hard gate 继续 rejected。
- 本版本不新增订单、自动交易、Alert V2、SuBing Runtime、Signal/Review/Strategy 兼容链或新的 Market
  Catalog 表；Historical/Live seam、`MarketDataService` 唯一入口与 `auto_order=false` 不变。
- release merge `ba111533...` 已通过双父普通 merge 保留 main/develop 历史，远端 `main` 与 `develop`
  均读回该 commit。annotated `v1.2.0` tag object 为 `1e38800a...`，远端 peeled target 精确为
  `ba111533...`；隔离 Runtime 也已按该 tag 部署并通过上文五服务/业务读回。

## v1.1.0 封板状态

- `v1.1.0` 在 `v1.0.0` 的 60 品种 Canonical/Runtime 基线上封板 Market Research Workspace P0：全市场
  Radar、Product Workspace、三层 K 线与十字线、Product Research、HTDY 原始观察层及 Runtime health
  activation 状态修复均已完成。Research/Radar 继续只读，不绕过 `MarketDataService`，不调用 RQData、
  Redis Live 或任何历史写入路径。
- 版本源、changelog 与本状态已收口为 `1.1.0`。本版本不新增数据/DB writer、migration、通知、订单或
  自动交易；`auto_order=false` 继续成立。
- GitHub 远端读回：`origin/main` 已推至 `4d46c834...`，其中包含 `v1.1.0` release commit 及后续
  Runtime 恢复状态记录；annotated `v1.1.0` tag 对象 `8d72f458...` 也已存在于远端，peeled target 为
  `f2568ba2...`。因此不再将 `v1.1.0` 写作“tag 未推”；若要撤销远端 tag，须另行取得该受控 release
  操作的明确授权。
- `v1.0.0` 是已完成的历史封板基线：annotated tag 对象为 `7b573d97...`，peeled target 为
  `423b0498...`。它不再代表当前仓库版本或 Runtime；tag 不授权 migration、通知或任何数据写入。
- active OpenSpec 已与实现同步：continuous `1m` 只用 `{SYMBOL}88`，`1d` 按 rank1 真实合约交易所日行情，
  `1w` 只由完整同源日线聚合。

## Market Research Workspace P0 代码验收

- `develop` 已完成 P0-1～P0-7：共享只读 Research/Radar、Product Workspace shell、固定
  `Kline + EMA / Volume / MACD`、研究侧栏与 Price/Volume/OI、完整 active 60 Radar、Radar Web、以及默认关闭的
  HTDY 原始观察层。当前 P0 实现提交为 `7231f072...`；Radar 使用 `expected_as_of` 和
  `participant_count/active_count` 显式报告 freshness，不以缺失品种伪装完整覆盖。
- 本轮代码验收已完成：工程测试 22 passed；后端 402 passed / 13 skipped、Ruff 和 Mypy（30 个源文件）通过；
  Web 85 passed / 1 skipped、Radar/Research/Runtime seam 浏览器回归 10 passed、production build 通过；
  OpenSpec 5/5 passed、secret scan 0 finding。没有新 provider、DB migration/table、scheduler、history writer、
  订单或 `auto_order` 语义变更。
- 真实浏览器在当前前端工作树检查到：旧 Runtime API 缺少新 Research/Radar 路由时，Radar 明确显示不可用、
  Product Workspace 仍保持 Canonical/Live K 线可读；HTDY 仅在用户显式开启后展示
  “未来引用/重绘风险/仅供人工观察”。
- **P0 Runtime-integrated readback 已封板于 v1.1.0**：隔离 Runtime 已为精确 release commit
  `f2568ba2...`，P0 Web/API/Live/after-market 均指向同一 clean/detached worktree；Research/Radar、
  Historical/Live seam、60 品种范围和 after-market activation 字段均可只读验证。真实使用数日的 P1
  决策观察期也尚未开始。

## SuBing Factor / Signal Observation V1 代码验收

- `develop` 已提供薄 `SubingReadService` 与 SuBing API/Web 观察面；只从
  `MarketDataService` / `MarketReadService` 复用已有 Historical/completed Live seam，不直连
  provider/Redis，不新增 persistence、cache 或 Runtime component。`MarketResearchService` 仍为
  Historical-only。
- Factor Observation 的 primary 与 companion 都裁剪到当前 rank1 segment，companion 不晚于
  primary cutoff；日线仍为 Historical-only。Kline/EMA/MACD/Factor 因此不携带主力切换前
  warm-up 或跨换月状态。前端的 effective current-contract identity 只影响 SuBing 视图，
  不写回用户的 continuous/actual-dominant/contract 偏好。
- Task 8 将 accepted slope-only Calibration 仅从 tracked production artifact 注入
  `SubingReadService`，并在 API/Web 明确分离 primary 与 resolved Signal；Factor observation 与 scoped
  Signal MACD policy identity 分开，zero-distance 继续只作 Factor/Web 描述。reciprocal orchestration
  修复保证 same READY boundary 即使 requested primary 为 NOT_MATCHED，也会发现 companion timeframe
  的独立 MATCHED opportunity；requested primary 本身不被覆盖。最终测试数量见本次交付 commit 的验证
  记录；Playwright 使用临时 Vite 测试服务，未用已部署 Runtime 替代。
- 状态仍是 Factor Observation 完成；Calibration Gate B-R 已批准，slope-only artifact 已成为
  Git-tracked 仓库事实；MACD Gate C 已人工批准且仅限 SuBing V1 Entry Signal scoped consumer，
  generic MACD capability 未晋升。formal 5m/15m Signal pure core 与 Task 8 API/Web observation 已完成，
  1d 仍 pending/non-blocking；无 Signal persistence、Alert integration、SuBing Runtime deployment、DB/
  Canonical write，Alert V1 unchanged，`auto_order=false`。
  Task 8 当轮没有 Runtime deployment/switch；当时 `4f1598e9` 的 18:05 调度与
  `NEXT_TRADING_SESSION_NOT_READY` 分类仅在 `develop` 代码中、隔离 Runtime 仍为 `v1.1.0`
  的 17:00 模板。该历史截点已由上文 `2026-08-14 13:54 +08:00` 的 `d82e06cc` 五服务部署取代。
