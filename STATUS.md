# 当前状态

更新时间：2026-08-20

## 当前结论

- 归一量化是本地、单用户的国内期货研究工作站。所有信号、页面和通知只用于人工观察，
  `auto_order=false`，仓库不存在订单创建或提交路径。
- Data Foundation DFD-01～DFD-07 已完成：active universe 为 60 品种，历史事实链固定为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`。
- 当前 Git release 与 production Runtime 均为
  `v1.6.2@dbdf6da49d75353a478675a3584de0f91c8bd85c`。
  production Alert 的唯一 active transport 仍为 `clawbot-openclaw-weixin`。
  develop 的 PushPlus transport 尚未 release/promotion，production 收件人仍精确只有 `owner`。
  Market Web 已提供 Radar、品种 K 线、EMA/MACD/HTDY、
  SuBing Factor/Signal 观察与 Alert V2 上下文。
- Market Runtime V1 已在本地工作站启用，只处理 `operational_products.txt` 的 active 60；
  Historical Canonical 与 Redis Live Overlay 分离，Live 不写 Parquet/DB。
- Alert Runtime V2 的 Code Registry 精确为 `htdy_original_15m` 与
  `subing_entry_signal_v1`；production 两条 Rule 的 Scope 当前均精确为 `jm`。
- `v1.6.0` 已包含并完成仓库原生验证的 `main_force_mirror_v0`（主力照妖镜 observation V0）：
  Python Indicator Kernel 为唯一口径，Web 在现有最底部副图通过 `MACD / 主力照妖镜` Tab 二选一，
  默认 MACD；“小心”保持 `rising_edge(BARSLAST(HIGH=HHV(HIGH,5))<10)`。六色柱仅为 OHLCV
  设计代理，不是实测资金流；该指标仍为 `observation_only`，未进入 Alert、backtest、live
  或 notification consumer。production Runtime 仅部署其 Web 观察面，不改变能力边界。
- `develop` 已完成 `main_force_mirror_futures_v1` 的 60m Web observation 与 Historical-only Shadow
  实现及仓库原生验证；只支持 `contract / actual_dominant`。换月 Pane 状态严格取可见范围最右侧当前
  physical-contract block，真实 AG2601→AG2612 回归锁定新 block 第 10/21/31 根 warm-up/readiness、
  Hover 身份与 marker 不继承。V0 runtime 已逐字恢复为 V1 开发前冻结源码，静态类型由同名 `.pyi`
  facade 承载，因此 code/version/formula/golden/capability 保持不变。V1 仍为 `observation_only`，未进入
  Alert、notification、正式 backtest、Runtime consumer 或订单路径。本次未运行真实代表矩阵 Shadow，
  未形成策略有效性、正式证据或晋升结论。
- `v1.6.0` 同时包含完整 SuBing Lifecycle V2 research-only 代码链：exact policy、
  不可变领域合同、causal ConfirmedPivot/Breakout/Retest/lifecycle reducer、additive API/Web 投影与
  Historical-only Shadow CLI。V1 Factor/Signal/resolver、Alert Rule/Scope 和 `AlertRuntime` 消费边界不变；
  Lifecycle 无 DB/Redis/queue/notification 路径。本版未运行真实 `jm` Shadow/current-market
  observation，因此无 live `jm` 证据，不表示策略有效、正式 Rule ready 或可晋升。
- `develop` 已包含 reviewed N Structural Domain V1：5m causal Swing/epoch、N Pattern、level break/
  Range Band、BULL/BEAR/RANGE Structure、Historical-only research CLI 与第二条独立 Candidate producer。
  Task 10 已形成并通过 Evidence Review 的 deterministic `jm` retrospective/rolling baseline；prospective
  OOS 从 `2026-08-21` 开始且仍为 `pending`，不形成效果、盈利、晋升、release 或 Runtime 结论。
- HTDY 自然 Event/WeCom 闭环已验收。SuBing Scope 已由用户通过 Product Workspace 单独激活，
  但尚未观察到自然 SuBing Event；Natural Canary 仍为 pending，不得用 synthetic Event、
  replay、backfill 或 retry 代替。

## Alert PushPlus transport（DEVELOP CODE_COMPLETE / TEST_COMPLETE；EXTERNAL GATES PENDING）

- develop 的通知边界已收敛为 `AlertNotificationDispatcher -> NotificationTransport -> PushPlus SDK`，
  不保留 OpenClaw/Clawbot 或 WxPusher 兼容路径。HTDY 每个 Event 只向逻辑 audience
  `htdy_observers` 发起一次 Topic 请求；SuBing 每个 Event 只向不带 Topic 的 `owner` 发起一次请求。
- provider 只使用官方 Python SDK `perk-pushplus-sdk==1.2.1`、`wechat` channel 与 `txt` template。
  SDK 返回的 shortCode 仅表示 PushPlus 接受请求，不能解释为微信最终送达；公开输出只含脱敏后缀。
- Git 外唯一 private JSON 只保存消息 token 与 HTDY Topic code，要求 parent `0700`、file `0600`、
  current uid。launchd/API/Alert 只传同一个 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`；health 仅做结构检查，
  不联网、不读取 Topic 成员、不公开 token 或 Topic code。
- Topic 成员完全由 PushPlus 管理；owner 与最多三位朋友都通过 PushPlus 页面/二维码加入同一专用 Topic，
  当前已由用户确认 Topic 内有 3 人，第 4 人可后续加入；每次由人工核对且总人数不得超过 4。归一量化
  不建逐人 directory、pairing、fan-out、送达表、Open API、callback、
  retry、queue、replay、backfill 或 fallback；Alert Application Domain 仍只有两张表。
- 当前实现的无副作用验证已覆盖 dispatcher/config/SDK adapter/composition/CLI/health 与 launchd/ops：
  Alert focused `170 passed`，全 engineering `53 passed`；全后端 Ruff PASS，Mypy `78 source files`
  PASS，全部 ops shell `bash -n`、6 个 launchd templates `plutil -lint`、secret scan
  `finding_count=0` 与 diff check PASS。
- Git 外 private config 已按单次授权原子写入并只读验证：parent=`0700`、file=`0600`、current uid、
  strict schema、Topic identity、SDK sender composition 与 structural health 均 PASS；验证明确
  `network_called=false / would_send=false`。本轮未连接 production DB，未执行 Scope、
  main/release/tag、Runtime promotion/switch 或外部旧配置清理。
- 专用 Topic 已创建且当前 3 人由用户确认；第 4 人允许后续加入。`owner` 单次真实 canary 已由
  PushPlus 接受（公开回执后缀 `b82d85`），且用户已确认微信实际收到，`delivery_confirmed=true`；
  未重试且未发送 Topic。独立 pending Gate 为：执行 `htdy_observers` 真实 canary、取得精确 Rule + Scope +
  audience + transport 持续授权、main/release/tag、exact-tag Alert Runtime promotion/switch/readback 与
  自然 HTDY 验收。代码和测试不授权其中任何一步。
- production 事实保持不变：仍为
  `v1.6.2@dbdf6da49d75353a478675a3584de0f91c8bd85c` 的单 `owner` exact Runtime，两条 Rule 的 Scope
  仍精确为 `jm`。没有 PushPlus Topic 已发送、已 release/promotion 或已自然验收的证据。

## SuBing Lifecycle V2 Review 修复（DEVELOP CODE_COMPLETE / TEST_COMPLETE）

- `develop` 已在不改变 V1 Signal、Alert、Web API 字段、DB、Canonical 或 Runtime 的边界内完成
  Lifecycle V2 最终 Review 修复：下一交易日首个可评价 boundary 由同方向 `FORMAL_V1` 优先确认旧
  Setup 并标记 `crossed_trading_day=true`；无同方向 Formal 才执行 rollover，不可用 boundary 继续暂停。
- Lifecycle 输入合同已 fail-closed：5m/15m Bar 与 Factor 任一长度错配均返回
  `UNAVAILABLE / SUBING_LIFECYCLE_SERIES_ALIGNMENT_INVALID`；非法 identity 的 Trace 三项身份字段全部为
  `None`，且不携带 Pivot、Opportunity 或 Transition，不再推断或伪造身份。
- Confirmed Pivot reducer 改为单向 cursor，breakout 只读取当前交易日最新 HIGH/LOW Pivot；Trace validator
  使用 set/dict 关联，均保持线性消费。Policy loader 将非 UTF-8、文件与 JSON 损坏统一降级为
  `SubingLifecyclePolicyError`，composition 只禁用 Lifecycle Policy，V1 SuBing service 仍可构造。
- fresh 验证为 SuBing backend canonical 测试 `613 passed`、Ruff PASS、Mypy `52 source files`、
  Web unit `173 passed / 1 skipped`、production build `2996 modules`、完整 Playwright `66 passed`、
  secret scan `finding_count=0` 与 diff check PASS；独立 Standards Review 为
  Critical=`0` / Important=`0` / Minor=`0`。
- 该 Review 修复当时未执行 release、tag、Runtime promotion/reload、migration、DB/Canonical 写入、
  Scope/通知或订单操作；当前 release/Runtime 身份以本文“当前结论”为准。

## Candidate Validation V1（PHASE 4B COMPLETE；RESEARCH BASELINE ONLY）

- `develop` 已新增 `subing_lifecycle_v2_candidate_v1 × candidate_validation_v1` 的 exact
  Candidate/Protocol、不可变 report contracts、10 个 12m reference + 3m test rolling folds、从
  `2026-08-20` 开始的 prospective OOS 编排，以及只读 `guiyi research candidate-validation`。
  全链保持 `research_only / Historical-only`，只复用既有 `SubingLifecycleResearchService ->
  MarketDataService -> Historical Canonical`，不新增第二套 lifecycle/outcome/rank1 算法或存储路径。
- 实现前的真实 `jm / 2023-01-01..2026-08-18` Shadow baseline preflight 已只读通过：rank1
  segments=`11`、evaluable boundaries=`58862`、entries=`463`，3/5/8 Bar outcome samples 分别为
  `439 / 424 / 402`。preflight 暴露的自然日窗口越过 trading-day Session 边界问题已收敛到
  `MarketDataService` 的 exact trading-day query；未使用消费者侧夜盘时刻或 fallback。
- implementation Gate 为 Candidate focused `118 passed`、上游 SuBing `474 passed`、Ruff PASS、Mypy
  `41 source files`、secret scan `finding_count=0`、diff check PASS；独立 implementation Review 为
  Critical=`0` / Important=`0` / Minor=`0`。
- exact-develop 真实只读 CLI 已生成唯一版本化 evidence：
  `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json`。
  artifact 包含 frozen retrospective、10 个 rolling
  reference/test folds 与 threshold-free stability；Task 9 独立 Evidence Review 为 Critical=`0` /
  Important=`0` / Minor=`0`，并确认 identity、窗口、完整性及禁止结论字段全部通过。
- Phase 4B 的唯一结论是：已形成可复算的 `jm` retrospective / rolling historical baseline；
  prospective OOS 为 `pending`，尚无 prospective OOS evidence。相关代码与历史 evidence 已随 v1.6.2
  发布，但这不表示策略有效、Candidate 可晋升、Alert Rule ready 或 Runtime ready；未执行 Runtime/Alert
  扩张、DB/Canonical/Redis 写入、通知或订单。

## N Structural Domain V1（DEVELOP CODE_COMPLETE / TEST_COMPLETE / EVIDENCE_COMPLETE；PROSPECTIVE OOS PENDING）

- reviewed implementation 已通过 merge commit
  `706274ebcf8abed90600288dc44db204437f2e5d` 合入 `develop`，统一收口变更进一步关闭了 public Pattern
  输入可信边界、segment 重复计算与 shared actual-dominant loader seam。public Pattern 只接受由同一组 bars
  精确复算得到的 Swing trace，malformed trace 统一 fail-closed；正式 segment producer 对 Swing / Pattern /
  Structure 各计算一次，并使用线性 partition、reset epoch map 与 bar index。SuBing 对历史 5m gap 文案的兼容
  只保留在自身 consumer adapter，不再污染 shared loader。
- N 是第二条独立 Candidate producer：`n_structure_5m_candidate_v1 × n_structure_validation_v1` 复用共享
  rolling/prospective schedule，但由 `NStructureResearchService` 生成 source-specific report，不复用或
  改写 SuBing lifecycle/outcome 事实源。retrospective 截止 `2026-08-19`，`2026-08-20` 为 embargo，
  prospective OOS 从 `2026-08-21` 开始。
- `docs/superpowers/specs/2026-08-20-n-structure-v1-design.md` 是唯一 active 长期语义事实源；已迁入
  same-boundary Structure establishment / defense advance / break 顺序与 full-producer own-N break
  reachability ruling，并删除完成态 Plan 与 Task contract。统一收口独立 Review 为 Critical=`0` /
  Important=`0` / Minor=`0`；最终验证为 N 全链 `343 passed`、SuBing zero-regression `601 passed`、Ruff
  PASS、Mypy `70 source files` PASS，secret scan 与 diff check 均通过。
- same-boundary completion 加自身 N2/origin break 保留为 Pattern 层的 local defensive contract；在冻结的
  完整 Swing→Pattern producer 顺序下，正例会先成为 outside epoch reset，或由新 opposite base 替换 attempt，
  因而不可达。该 canonical reachability ruling 未改变 Swing、Pattern、Structure 公式或边界顺序。
- Task 10 的 exact-develop 真实只读 CLI 已生成唯一版本化 evidence：
  `reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json`，
  SHA256=`12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6`。真实 `jm`
  retrospective 包含 `12` 个 rank1 segments、`60075` 根 evaluable 5m bars，3/5/8 Bar outcome samples
  分别为 `3987 / 3985 / 3983`；10 个 rolling folds 均按冻结 schedule 生成。retrospective 截止
  `2026-08-19`，`2026-08-20` 仅作为 embargo/request-through context，prospective OOS 仍为 `pending`，
  首个 eligible trading day 为 `2026-08-21`。
- 统一收口最终代码再次执行 exact command，输出 `35982` bytes，SHA256 仍为
  `12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6`，与 tracked artifact
  byte-identical；独立 Evidence Review 为 Critical=`0` / Important=`0` / Minor=`0`。该 accepted baseline
  只证明 exact Candidate/Protocol 下的可复算 Historical
  retrospective/rolling evidence，不形成 profitability、effectiveness、KEEP/PROMOTE、可交易、第三条
  Alert Rule、release 或 Runtime ready 结论。
- 本阶段未执行 RQData download、Canonical/DB/Redis write、Alert/Scope/notification/order、
  main/tag/release、Runtime switch/promotion 或其他真实外部 mutation。

## v1.6.2 主力照妖镜·期货 V1（RELEASED / RUNTIME PROMOTED）

- Release PR #183 已将 reviewed `develop@72f9c03f79c4c982473da80b0d9f6cc6351bba84` 合入
  `main@dbdf6da49d75353a478675a3584de0f91c8bd85c`；annotated `v1.6.2` peeled commit 精确为同一
  main commit，tag message=`Release v1.6.2`，API/Web 版本面均为 `1.6.2`。
- release tree 包含 Futures Main-Force Mirror V1、Candidate Validation V1、N Structure V1 规划文档、
  rollover availability 修复与 V0 exact-source restoration；未包含未合并的
  `codex/alert-fixed-recipients` 实现。
- G1 前完整验证为 backend `1581 passed`（隔离 PostgreSQL）、engineering `56 passed`、Mypy
  `65 source files`、Web unit `199 passed / 1 skipped`、指定 Playwright `47 passed`、build
  `2997 modules`，Ruff/secret/shell/plist/diff 均通过；独立 Spec 与 Standards/Architecture Review
  均为 Critical=`0` / Important=`0` / Minor=`0`。
- 独立 Runtime worktree `/Volumes/扩展盘/guiyi-quant-runtime-v1.6.2` 为 clean/detached 的精确
  `dbdf6da49d75353a478675a3584de0f91c8bd85c`。锁定 API/Web 依赖安装完成，Runtime 专项
  `229 passed`、Ruff/secret/diff 通过，Web build 为 `2997 modules` 且拓扑无环；render-only 已验证
  五个应用 plist 的 root/commit 与六项既有 Clawbot 私有路径一致。
- 本次单次 G2 依次执行 base、Market 与 Alert promotion；读回确认 API/Web/Live/after-market/Alert
  五个正式 label 均加载 v1.6.2 root 与 `dbdf6da4`，Runtime checkout clean/detached。API version=`1.6.2`，
  API/Web=`200`，Runtime health=`ok/readonly`，Market/Alert enabled，operational/phase 总数均为 `60`，
  Clawbot/owner ready，Execution Review roll disabled。
- DB revision 只读保持 `20260815_0039 (head)`；Alert 两条 Rule 的 Scope 仍精确为 `jm`。实际
  `actual_dominant + 60m` Market 读回返回一根 JM Bar 与一个已解析物理合约 segment。
- 本次未执行 migration、RQData/Canonical/DB 写入、真实 Shadow、Scope/owner/transport mutation、
  通知、replay/backfill、手工盘后或订单。后续独立 cleanup Gate 在删除前确认五个正式 label、对应
  installed plist 与进程打开文件均无 v1.6.0/v1.6.1 root 引用，两个旧 worktree 均 clean/detached、
  精确匹配仍保留的 annotated tag 且已进入 main 历史；随后仅通过 `git worktree remove` 删除两者并
  执行 `git worktree prune`。当前保留 clean/detached v1.6.2 Runtime；后续完成
  `codex/alert-fixed-recipients-simple` 合入 `develop` 后，其 `.worktrees/alert-fixed-recipients`
  worktree 与本地分支也已删除。旧 `codex/alert-fixed-recipients` 仅为未合并的历史 branch
  ref；v1.6.2 cleanup 后 Runtime 状态复核为 `overall=passed`。

## v1.6.1 收盘快照交接（RELEASED / RUNTIME PROMOTED）

- Market WebSocket 新增同次读取的 `MarketDisplaySnapshot`：`realtime` 继续要求既有 live eligibility 与
  heartbeat；`post_close` 仅在 CLOSED phase、operational product、1m/5m/15m/30m/60m，以及
  actual-dominant 或 Redis subscription 精确真实合约身份下读取当日完成 Bar。
- `post_close` 只补齐 Canonical 盘后接管前的展示空窗，不进入 `live_snapshot()`、`bars_until()`、
  SuBing 或 Alert；Redis/交易日/合约异常返回 `none`。Web 在 Canonical edge 前移后按 `bar_end` 接管，
  并保持 `isLiveDisplay` 仅代表 realtime。
- Release Candidate 已通过 backend `1392 passed`（隔离 PostgreSQL 库 OID `581975`，production OID
  `16384`）、Market Runtime 专项 `130 passed`、engineering `53 passed`、Ruff、Mypy `61 source files`、
  Web unit `173 passed / 1 conditional skip`、完整 browser `66 passed`、修复后 Market browser `5 passed`、
  production build `2996 modules`、shell/plist/render-only、secret scan 0 与 diff check。独立 Review 为
  Critical=`0` / Important=`0` / Minor=`0`。
- Release PR #177 已合并；`origin/main` 与 annotated `v1.6.1` peeled commit 均为
  `75cbf37ccdb5de1a7267f024f8b9ea44ac859bda`，tag message=`Release v1.6.1`。`origin/main` 是
  最终 `origin/develop` 的祖先，API/Web 版本面均为 `1.6.1`。
- 独立 Runtime worktree `/Volumes/扩展盘/guiyi-quant-runtime-v1.6.1` 为 clean/detached 的精确
  `75cbf37ccdb5de1a7267f024f8b9ea44ac859bda`；Web production build 为 `2996 modules`，Market Runtime
  专项为 `130 passed`，launchd render/plist 验证通过。
- 首次单次 promotion 在 base 与 Market 已切换后，因新 root 的 Alert 私有路径未注入而
  fail-closed，当次未重试。随后依据用户新的精确单次授权，从旧 exact-tag Runtime plist
  只读取回并校验六项 Clawbot 私有路径，完成 base + Alert promotion；未重载 Market。
- 读回确认 API/Web/Live/after-market/Alert 五个正式服务均加载 v1.6.1 root 与
  `75cbf37c`，API version=`1.6.1`，API/Web=`200`，Runtime health=`ok/readonly`，Market/Alert
  enabled，Clawbot/owner ready，Execution Review roll disabled。DB 仍为 `20260815_0039`，两条
  Alert Rule 仍均为 enabled 且 Scope 精确为 `jm`，正式服务已无 v1.6.0 root 引用。
- 本次未执行 migration、RQData/Canonical/DB 写入、Scope/owner/transport mutation、真实通知、
  手工盘后任务、replay/backfill/retry 或订单；旧 v1.6.0 worktree 仅作可恢复资产保留。
- `2026-08-19` 的自然盘后任务在 Runtime 切换中断后仅完成部分品种，且原 Live snapshot
  已不存在，因此不将后续手动处理冒充为自然 18:05 验收。在用户另行精确授权后，以
  `HistoricalDataManager` 唯一写入路径执行一次 `data update --universe active --through 2026-08-19 --apply`：
  `planned=443/applied=443/failed=0/provider_requests=147`。随后全量 audit 为 `finding_count=0`，并通过
  420 次 `MarketDataService` 读取确认 active 60 的 1m/5m/15m/30m/60m/1d 均到 2026-08-19，1w 均为
  最近完整周 2026-08-14。未重载 Runtime、未执行通知、未做第二次重试或伪造盘后状态。

## v1.6.0 Release / Runtime（RELEASED / RUNTIME PROMOTED）

- Release PR #176 已合并；`origin/main` 与 `origin/develop` 均为
  `5d4c63f1c6aa68f9f93fc6137fda667f09a6d9cd`，annotated tag `v1.6.0` 的 peeled commit 与之一致。
- clean Release Candidate 验证为 backend `1376 passed`、engineering `53 passed`、Ruff、Mypy
  `61 source files`、Web unit `167 passed / 1 conditional skip`、selected browser `37 passed`、
  Web build `2996 modules`、shell/plist/render-only、secret scan 0 与 diff check 全通过；隔离
  PostgreSQL 测试库名与 OID 均与 production 不同。独立 Release Review 为
  Critical=`0` / Important=`0` / Minor=`0`。
- 独立 exact-tag Runtime Gate 已将 API/Web/Live/after-market/Alert 五个 label 统一切换到
  clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.6.0@5d4c63f1c6aa68f9f93fc6137fda667f09a6d9cd`。
  API version=`1.6.0`，API/Web 为 200，Runtime health=`ok/readonly`，Market/Alert enabled，Clawbot/owner
  ready，Execution Review roll disabled，DB 仍为 `20260815_0039`，两条 Rule Scope 仍精确为 `jm`。
- 本次没有运行 migration、RQData/Canonical/DB 写入、真实 Lifecycle Shadow/current-market
  observation、Scope/owner/transport mutation、canary/通知、replay/backfill/retry 或订单。
- `develop` 已完成 Clawbot single-shot D1 code PASS，并在 `d82ea43dd` 修复多行 Alert 正文的 LF
  校验合同。rollout G2 owner bootstrap 与 G3 zero-send preflight 已完成；`2026-08-19` 的唯一一次新授权
  G4 canary 已获 provider acceptance，用户已确认微信中恰好收到一条，因此 G4 PASS。
  G5 已完成正常微信入站后的 preflight、一次外部 restart 后的 persisted-context preflight、版本无漂移
  与 single-shot 回归。G6 已按用户批准的完整累计 `develop` 范围完成 release PR #170、独立审查与
  annotated `v1.5.0` tag；G7 已在 Gate time 读回两条 enabled Rule 的精确 Scope 均为 `jm`，并将
  bounded continuous authorization 只锁定到两条精确 Rule × `jm` × `owner` × Clawbot tuple；该 G7
  授权不授权 G8 或 G9。G8 以独立 exact-tag Runtime promotion Gate 将正式五服务统一切换至
  `v1.5.0` 并完成读回。`2026-08-19` 用户明确决定不再等待 G9 自然 Alert，并接受缺少自然送达证据
  的风险；G9 因此以 `NATURAL_EVIDENCE_WAIVED_BY_OWNER` 收口，最终 WeCom credential 与旧 Runtime
  worktree 已在正式引用清零后完成清理。该收口不把 canary、synthetic Event 或零事件冒充自然证据。

## Clawbot Single-Shot D1（RELEASED / RUNTIME PROMOTED）

- `develop` 的唯一 active 通知 transport 已改为 `AlertEvent commit -> ClawbotAlertSender -> one Node
  child -> openclaw-weixin private seam -> sendMessageWeixin()`；每个 Event 最多一个 child、一次发送
  primitive，失败不回滚 Event，也不 retry、queue、replay、backfill、fan-out 或 fallback。
- 非敏感 manifest 冻结 G1 实际读回的 OpenClaw `2026.7.1-2 (0790d9f)`、Node `v24.15.0`、
  `openclaw-weixin 2.4.6`、exact plugin root/module shape。OpenClaw 是既有外部依赖，不由归一量化
  安装、更新、登录、启动、停止或监督。
- owner 采用 Git 外 `0700` parent / `0600` file 的严格不可变 schema，公开只使用别名 `owner`；
  后续 rollout 已完成 G2 写入和 G3 zero-send preflight。早先 G4 尝试因 single-shot seam 误将正文 LF
  视为非法控制字符而在调用腾讯 primitive 前失败；`d82ea43dd` 已通过真实 Node seam RED→GREEN 修复，
  新授权的单次 G4 返回 `attempted=1 / provider_accepted=1 / failed=0`，用户确认只收到一条，G4 PASS。
  本次 LF 修复与 G4 未修改 OpenClaw、未 load/reload launchd、未切换 Runtime。
- Courier active source/tests/tooling 已从 D1 代码删除，active WeCom sender source/config 仍为零；
  在当时的 D1 code-only 阶段，production exact-tag/hotfix Runtime 仍为 WeCom。这是 G8 前的历史事实，
  不代表当前 production transport；D1 完整验证及独立 R1 为
  Critical=`0` / Important=`0` / Minor=`0`。G5 的两次 zero-send preflight 均 PASS；外部 restart 仅按用户
  明确委托执行一次，restart 后 account/context 仍 ready；OpenClaw/Node/plugin 版本精确匹配 manifest，
  Node seam `22 passed`、Clawbot/Alert `138 passed`、launchd engineering `29 passed`，禁止 active path
  为零且未执行可选第二次 canary。
- G6 按用户批准的方案 2 将 Clawbot、Market Live stale-feed repair、HTDY UI/canonical/status 与
  `v1.5.0` release identity 作为完整累计 `develop` 差异发布。clean detached 候选验证包括 backend
  `984 passed / 14 skipped`、engineering `53 passed`、Node seam `22 passed`、Web unit
  `150 passed / 1 conditional skip`、browser E2E `52 passed`、Web production build、Ruff、Mypy、
  shell/plist、render-only 六路径一致性、secret scan 0 与 diff check；17 项需要显式 isolated PostgreSQL
  test DB 的测试未使用 production DB。fresh independent review 为 Critical=`0` / Important=`0` /
  Minor=`0`。release PR #170 已合并；`origin/main` 与 annotated tag `v1.5.0` 的 peeled commit 均为
  `957d19893187c7876b88e58f82fd5656536ee214`。
- G7 Gate-time 只读核对确认 Code/DB Registry 均精确为 `htdy_original_15m` 与
  `subing_entry_signal_v1`，两条 Rule 均 `enabled=true / scope=jm`；owner 严格 schema 元数据为
  `owner × openclaw-weixin`，未输出私有 id。G7 的 bounded continuous authorization 精确记录为
  `htdy_original_15m × jm × owner × clawbot-openclaw-weixin` 与
  `subing_entry_signal_v1 × jm × owner × clawbot-openclaw-weixin`，且只覆盖 G8 后新建的自然
  AlertEvent；不覆盖新 Rule/Scope/owner、synthetic Event、replay/backfill、canary、release、Runtime
  promotion、DB/Canonical、订单、rollback 或 G9 cleanup，也不作为这些 Gate 的授权证据。
- G8 只依据独立的 exact-tag `v1.5.0` production Runtime promotion Gate 执行；fresh zero-send preflight、
  OpenClaw/Node/plugin exact-version、owner `0600/current uid`、DB revision、
  Rule/Scope、Execution Review roll 与无订单边界均通过。正式五服务已统一切换至 clean/detached
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.5.0@957d19893187c7876b88e58f82fd5656536ee214`；
  API version=`1.5.0`，notification channel=`clawbot-openclaw-weixin`，owner/OpenClaw/plugin 均 ready。
  切换后 Live 等待首根完整 Bar 时短暂 degraded，5 秒后自然收到 `2026-08-18T16:52:00+00:00`
  并恢复 health=`ok`，未重载或重试。DB=`20260815_0039`、两 Rule `scope=jm`、roll disabled 均未变，
  OpenClaw gateway PID 前后均为 `23054`。G8 执行时旧 `v1.4.2` worktree 仍保留为显式 rollback material；
  该 material 已在后续 G9 明确清理 Gate 中移除。当前 rollout 为 G2～G8 PASS、G9
  `COMPLETED_WITH_NATURAL_EVIDENCE_WAIVER`。
- G8 后 `2026-08-19 00:54～01:04 +08:00` 的只读 G9 监控覆盖 01:00 自然收线及后续评估，
  `post_g8_natural_event_count=0`，因此没有 notification attempt，也没有自然消息到达证据。用户随后
  明确豁免该自然证据并授权最终清理；删除前 fail-closed 扫描确认旧 worktree clean/detached/registered、
  五个正式服务与 launchd/process 对旧根零引用、active source/config 对 WeCom 零引用，且 private
  `WECOM_WEBHOOK_URL` 恰有一个 `0600/current uid` 键。随后旧 `v1.4.2` worktree 已通过
  `git worktree remove` 删除，private WeCom credential 键已移除且环境文件保持 `0600/current uid`。
  G9 记录为完成但自然证据被明确豁免；未来恢复 WeCom 必须重新设计、配置、发布并取得独立 Gate。

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
- production `v1.6.2` 的 `guiyi runtime alert-canary` 仍只面向历史固定 `owner`；develop 改为必须显式
  `guiyi runtime alert-canary --audience owner|htdy_observers`。二者都是独立真实通知 Gate，不是测试命令。
- develop 不再提供 `guiyi recipients *` 或 `alert-preflight`；Topic 成员只在 PushPlus 外部管理。
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
- production Alert Event 先提交，然后最多启动一个 child、调用一次 Clawbot `sendMessageWeixin()`；
  失败不回滚 Event，也不建 replay/backfill/retry/outbox/queue 或 WeCom fallback。

## 当前 Runtime 事实

- `2026-08-19 00:51～00:52 +08:00` 已按独立 G8 exact-tag Runtime promotion Gate 把
  API/Web/Live/after-market/Alert 一次性
  promotion 至 clean/detached exact-tag Runtime
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.5.0@957d19893187c7876b88e58f82fd5656536ee214`。
  五个 launchd label 的 root/loaded commit 一致；API/Web/Live/Alert running，after-market 仍为
  schedule-only not running；API/Web=200、API version=`1.5.0`、Runtime health=`ok/readonly=true`、
  状态脚本 `overall=passed`。Alert transport=`clawbot-openclaw-weixin`，owner alias=`owner`，
  OpenClaw `2026.7.1-2 (0790d9f)` / plugin `2.4.6` / owner config 均 ready。
- 切换未修改或重启 OpenClaw，gateway PID 前后均为 `23054`；未执行 migration、RQData/Canonical/DB
  写入、Scope mutation、canary、replay/backfill、Execution Review 或订单操作。DB revision 仍为
  `20260815_0039`，两 Rule 仍为 `enabled=true/scope=jm`，Execution Review roll 仍 disabled，
  `auto_order=false`。新 Runtime 根未复制旧 after-market status，G8 读回时该组件为 `pending`，但
  activation 已保留且 overall health 为 ok；下一次只接受自然 18:05 状态。旧 `v1.4.2` worktree 在
  G8 读回时仍保留且未自动 fallback，后续已按 G9 明确清理 Gate 删除。
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
- `v1.6.2` Runtime promotion 已完成；正式五服务已统一加载 identity
  `dbdf6da49d75353a478675a3584de0f91c8bd85c`，Market/Alert Scope 未扩大。v1.6.2 cleanup 已在正式
  引用归零后移除旧 v1.6.0/v1.6.1 release worktree，两个 annotated tag 仍保留可恢复；既有 G9 最终
  清理也已完成，旧 `v1.4.2` Runtime worktree 与 private WeCom credential 均已移除。Execution Review
  Gate D 仍为 `disabled / not activated`。
- bounded retry 修复的部署身份已读回；`2026-08-18` 自然 18:05 盘后运行已形成
  `passed/attempts=1` 业务证据，未手工运行、回填、retry 或补证。
- SuBing Natural Canary 继续作为独立 pending evidence；无自然 Event 就保持 pending，
  不人工补证；该独立 pending 状态不改写 `v1.6.2` release/Runtime promotion 或 G9 明确豁免收口事实。
- 最小下一步：保持 production `v1.6.2 + clawbot-openclaw-weixin` 不变；单独批准一次
  `htdy_observers` Topic canary，并由当前三位成员人工确认实际收到。
