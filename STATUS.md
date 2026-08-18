# 当前状态

更新时间：2026-08-19

## 当前结论

- 归一量化是本地、单用户的国内期货研究工作站。所有信号、页面和通知只用于人工观察，
  `auto_order=false`，仓库不存在订单创建或提交路径。
- Data Foundation DFD-01～DFD-07 已完成：active universe 为 60 品种，历史事实链固定为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`。
- 当前 release 为 `v1.4.2`；Market Web 已提供 Radar、品种 K 线、EMA/MACD/HTDY、
  SuBing Factor/Signal 观察与 Alert V2 上下文。
- Market Runtime V1 已在本地工作站启用，只处理 `operational_products.txt` 的 active 60；
  Historical Canonical 与 Redis Live Overlay 分离，Live 不写 Parquet/DB。
- Alert Runtime V2 的 Code Registry 精确为 `htdy_original_15m` 与
  `subing_entry_signal_v1`；production 两条 Rule 的 Scope 当前均精确为 `jm`。
- HTDY 自然 Event/WeCom 闭环已验收。SuBing Scope 已由用户通过 Product Workspace 单独激活，
  但尚未观察到自然 SuBing Event；Natural Canary 仍为 pending，不得用 synthetic Event、
  replay、backfill 或 retry 代替。
- `develop` 已完成 Clawbot single-shot D1 code PASS，并在 `d82ea43dd` 修复多行 Alert 正文的 LF
  校验合同。rollout G2 owner bootstrap 与 G3 zero-send preflight 已完成；`2026-08-19` 的唯一一次新授权
  G4 canary 已获 provider acceptance，等待用户确认微信中恰好收到一条，因此 G4 尚未 PASS。
  尚未执行 G5～G9、release 或 Runtime promotion；production 继续保持 `v1.4.2 + WeCom`。

## Clawbot Single-Shot D1（CODE PASS / NOT RELEASED）

- `develop` 的唯一 active 通知 transport 已改为 `AlertEvent commit -> ClawbotAlertSender -> one Node
  child -> openclaw-weixin private seam -> sendMessageWeixin()`；每个 Event 最多一个 child、一次发送
  primitive，失败不回滚 Event，也不 retry、queue、replay、backfill、fan-out 或 fallback。
- 非敏感 manifest 冻结 G1 实际读回的 OpenClaw `2026.7.1-2 (0790d9f)`、Node `v24.15.0`、
  `openclaw-weixin 2.4.6`、exact plugin root/module shape。OpenClaw 是既有外部依赖，不由归一量化
  安装、更新、登录、启动、停止或监督。
- owner 采用 Git 外 `0700` parent / `0600` file 的严格不可变 schema，公开只使用别名 `owner`；
  后续 rollout 已完成 G2 写入和 G3 zero-send preflight。早先 G4 尝试因 single-shot seam 误将正文 LF
  视为非法控制字符而在调用腾讯 primitive 前失败；`d82ea43dd` 已通过真实 Node seam RED→GREEN 修复，
  新授权的单次 G4 返回 `attempted=1 / provider_accepted=1 / failed=0`，人工收件确认仍 pending。
  本次 LF 修复与 G4 未修改 OpenClaw、未 load/reload launchd、未切换 Runtime。
- Courier active source/tests/tooling 已从 D1 代码删除，active WeCom sender source/config 仍为零；
  production exact-tag/hotfix Runtime 的 WeCom 事实未改变。D1 完整验证及独立 R1 为
  Critical=`0` / Important=`0` / Minor=`0`；当前 rollout 为 G2/G3 PASS、G4 机器接受且人工回执待确认，
  G5～G9 均未执行。

## After-Market Bounded Retry V1.4.2（RELEASED / RUNTIME PROMOTED）

- release PR #169 已合入 main；annotated tag `v1.4.2` 的 peeled commit 与 `origin/main` 均为
  `fb96506493763340e082ed85e8112b60d6670d65`，并包含批准候选
  `e890e3bd29f4db8e1646387a3227a71a9eccf02e`。
- 一小时后 retry 仅允许 `NEXT_TRADING_SESSION_NOT_READY`；RQData readiness、额度、普通更新异常、
  rank1/Live mismatch 与 Live cleanup 失败均在首试后结束，并按实际执行次数公开 `attempts=1`。
- 发布候选与 exact-tag Runtime 验证：Market Runtime/health/retry 定向 `112 passed`，Ruff、Mypy、
  Web production build、launchd render/plist lint、secret scan（0 findings）与 diff check 通过。
- 正式五服务 Runtime 已按本次明确执行意图 promotion 至 `v1.4.2`；未执行 migration、RQData/
  Canonical/DB 写入、Scope mutation、真实 WeCom、手工盘后、replay/backfill/retry 或订单操作。

## Shared Optional EMA Overlays V1.4.1（RELEASED / RUNTIME PROMOTED）

- release PR #168 已合入 main；annotated tag `v1.4.1` 的 peeled commit 与 `origin/main` 均为
  `60d7c5b35565b29114dd55355762dddebb852fd5`，并包含批准候选
  `14637e0fffb6ba74e9b111c91e95bcee145043af`。
- Product Workspace 新增一组共享的 EMA10 / EMA60 显示开关；切换苏冰或火天大有时保持同一选择，
  苏冰继续固定显示 EMA21，火天大有继续固定显示原始观察层，选择“无”时不显示主图指标但保留偏好。
- 主图偏好升级至 v3；v2/v1 安全迁移后可选 EMA 默认关闭。localStorage 属性访问、读取或写入失败
  均不会阻塞 K 线，SuBing unsupported 周期继续 fail-closed。
- 发布候选验证：Web unit `150 passed / 1 conditional skip`；Market/Alert E2E `30 passed`；
  backend health/engineering `47 passed`；Web production build、secret scan（0 findings）与 diff check 通过；
  final branch review 及 scoped fix re-review 均通过。
- 正式五服务 Runtime 已按独立明确执行意图 promotion 至 `v1.4.1`；本次未执行 DB/Canonical 写入、
  Alert Scope 变更、WeCom、手工盘后、通知或订单操作，`auto_order=false` 不变。

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
- SuBing Natural Canary 继续 pending；Task 6 Gate A release、Gate B production migration、
  Gate C Runtime promotion 与 Gate C External Review（`PASS`，Critical=`0`、Important=`0`、
  Minor=`0`）均已完成。`v1.4.0` rollout 主体完成，Gate D 仍为 `disabled / not activated`。

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
- production Alert Event 先提交，然后最多尝试一次 WeCom；develop Clawbot D1 保持相同
  Event-first/at-most-once 语义；两者都不建 replay/backfill/retry/outbox/queue。

## 当前 Runtime 事实

- `2026-08-18 23:32 +08:00` 已按明确单次授权将本机统一五服务 Runtime 从
  `579cb034222b44e45f4a365c534428d58c1cf252` 切换至 UI-only 补丁提交
  `1bbd70e3bf6705df196a53fde5184ac3de8fbde0`。该提交仅为 `579cb034` 基线加入本次 HTDY
  的 6 个 Web 代码/测试文件，未携带 `develop` 上尚未 promotion 的 Clawbot/Alert 变更。
- 正式 Web production build 通过；API/Web/Live/Alert 均 `running`，after-market 为 schedule-only
  `not running`，五个 launchd label 的 root/loaded commit 均精确为 `1bbd70e3`，Runtime
  checkout 为 clean/detached，API/Web=200，Runtime health=`ok/readonly=true`，只读状态脚本
  `overall=passed`。Alert 在首次 3 秒验收时短暂为 `spawn_scheduled`，未执行第二次重载即
  自然进入 `running`；正式 `5173` JM 页面已读回 HTDY 高对比三轨/图例，原顶部风险提示横幅不再
  出现。本次未执行 DB/Canonical/Scope/通知渠道变更、手工通知、手工盘后或订单操作。
- 上述 `ok/overall=passed` 是切换后的瞬时读回；`23:35 +08:00` 起 Live 自动重连被 RQData
  以 `4003 quota exceeded` 拒绝，当前仍为单一 Live 进程、心跳持续更新，但
  `TRADING=11/subscribed=0`、Runtime health=`degraded/live_unavailable`。API、Web、Redis、DB、
  after-market 与 Alert 保持 `ok`。现有十秒自动重连尚未恢复。`23:41:23 +08:00` 按新的单次
  授权仅卸载 Live，冷却 60 秒后于 `23:42:23 +08:00` 加载一次；新 PID 正常运行，但最终仍为
  `TRADING=11/subscribed=0`、`overall=failed failures=1`，未再执行重启或其他 Runtime mutation。
- `2026-08-18 22:16 +08:00` 已按本次明确授权把 API/Web/Market Live/after-market/
  现有 Alert Runtime 统一重载至 clean/detached Runtime 根
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.4.2` 的 Live hotfix 提交
  `579cb034222b44e45f4a365c534428d58c1cf252`。该提交的父提交是 `v1.4.2` peeled commit
  `fb96506493763340e082ed85e8112b60d6670d65`；release/tag 未变，API version 仍为 `1.4.2`。
- API/Web/Live/Alert 均 running，after-market 为 schedule-only `not running`；五个 launchd label 的
  root 与 loaded commit 均精确指向 `579cb034`，Runtime health=`ok/readonly=true`，DB revision 仍为
  `20260815_0039`。旧 `v1.4.1` Runtime worktree 已在正式引用清零后通过 `git worktree remove`
  清理，当前只保留唯一正式 `v1.4.2` Runtime。
- Market Runtime V1 持续授权保持原 active 60；切换后读回为 `TRADING=45/CLOSED=15/subscribed=45`，
  RQData socket=`ESTABLISHED`。`jm` actual-dominant 1m 为
  `TRADING/live_available=true/JM2701`，Redis Bar 从 2 根持续增长至 4 根、最新 `22:20 +08:00`，
  WebSocket state/snapshot 已读回实时 Bar。重启时所在的不完整 15m bucket 不聚合，等待首个
  完整 post-restart bucket 自然完成，不用缺失分钟填充。Alert Runtime V2 保持原 Rule/Scope：
  `htdy_original_15m -> jm`、`subing_entry_signal_v1 -> jm`；抽查 `ag` 两条 Rule 均未启用。
- after-market 最新自然运行为 `2026-08-18/passed/attempts=1`，仅保留 18:05 schedule。
  本次热修切换未执行 migration、RQData/Canonical/DB
  写入、Scope mutation、真实 WeCom、手工盘后、replay/backfill/retry 或订单操作；
  Execution Review roll 继续 `disabled / not activated`，`auto_order=false` 不变。

## Gate 与最小下一步

- Gate A 已完成 release PR、main merge、annotated tag 与 main -> develop ancestry synchronization。
- Gate B 已完成 production additive `20260815_0039` migration；Execution Review 四表已存在，
  Market 八表与 Alert 两表 normalized schema signatures 保持不变。
- `v1.4.2` Runtime promotion 及 Live hotfix 切换已完成；正式五服务已统一加载 identity
  `579cb034222b44e45f4a365c534428d58c1cf252`，Market/Alert 原持续授权范围未扩大，旧
  `v1.4.1` Runtime worktree 已清理。Gate D 仍为 `disabled / not activated`。
- bounded retry 修复的部署身份已读回；`2026-08-18` 自然 18:05 盘后运行已形成
  `passed/attempts=1` 业务证据，未手工运行、回填、retry 或补证。
- SuBing Natural Canary 继续作为独立 pending evidence；无自然 Event 就保持 pending，
  不人工补证；该独立 pending 状态不改写 `v1.4.2` release/Runtime promotion 完成事实。
- 最小下一步：只等待首个完整 post-restart 15m bucket 自然完成并只读验收；不回填、
  不补证。SuBing Natural Canary 与 Gate D 继续分别保持 `pending`、
  `disabled / not activated`。
