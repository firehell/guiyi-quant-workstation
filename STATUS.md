# 当前状态

更新时间：2026-08-25

## 正式 release 与 production Runtime

- 已发布的正式 tag 为
  `v1.8.2@58e0f596a5b425e15697abc72b71c83cc878796c`；annotated tag object 为
  `d48bdd3d2d7fad8d41d876896b76624918273ac3`，message=`Release v1.8.2`。
- 2026-08-25 已将本机五个 launchd label 切到 clean/detached
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.2@58e0f596a5b425e15697abc72b71c83cc878796c`。
  API、Web、Live 与 Alert 均从该根运行，API=`200 / 1.8.2 / readonly`、Web=`200`；after-market
  `not_running`，只读 Runtime health=`ok`。本次未手工触发 after-market，下一次自然盘后与 Daily
  Watch artifact 仍是独立未完成 evidence，不能由本机部署推导为已完成。
- `GUIYI_SUBING_OBSERVATION_ROOT` 已精确配置为扩展盘
  `/Volumes/扩展盘/guiyi-quant-data/observations/subing-daily-v1`；配置文件为 `0600`，目录为 `0700`，
  production resolver 通过。当前目录为空，current API 返回
  `200 / unavailable / SUBING_DAILY_WATCH_NOT_GENERATED / expected=2026-08-25`，等待下一次自然盘后生成。
- 旧 `v1.8.0` 与 `v1.7.0` Runtime worktree 保留为 clean/detached rollback 资产，但当前没有 label 指向；未执行
  回滚、after-market、canary、人工通知、真实 RQAlpha smoke、migration、Canonical/production DB/Redis
  写入或 Alert Scope/transport 变更。
- RQAlpha research workbench 代码已包含在 `v1.8.0`，但本地 sidecar 仍未加载、未进入 Runtime；真实
  RQAlpha smoke 继续 `pending`，不得由代码包含或其他 Runtime 验收推导为已完成。
- Market/Alert marker 继续 enabled；Alert notification channel 仍为 pushplus 且 config=`ready`、
  audience_count=`2`，Execution Review roll 仍为 `disabled`。本机端口/HTTP 与 FRPC local tunnel 最新只读
  验收均为 `passed`；ECS FRPS/Nginx 与公网 HTTPS 本轮没有可用执行入口，且 `PUBLIC_BASE_URL` 未配置，
  因此保持 `not verified`，不得由本机或 tunnel 读回推导为公网验收通过。

## v1.8.2 release and Runtime deployment

- release preparation commit 为 `fba78fed4`；main integration 与 annotated tag peeled commit 均为
  `58e0f596a5b425e15697abc72b71c83cc878796c`。本版包含 Market 首页中文化、全市场价格变化 × 持仓变化
  四象限名单、移除自选入口、RQAlpha 回测入口、以及 K 线初始 300 根与桌面工作区满高布局。
- exact candidate 验证为 backend（排除需要独立 PostgreSQL 的两项迁移/并发套件）
  `3720 passed / 3 skipped`、版本与工程契约 `19 passed`、Web unit `280 passed / 1 skipped`、Playwright
  `100 passed / 1 skipped`；Ruff、Mypy `154 source files / 0 issues`、Web production build、OpenSpec
  `6 passed`、secret scan、diff check 均通过。隔离 PostgreSQL 套件未执行：本版没有 migration，且未取得对
  独立数据库写入的授权。
- 五个现有 launchd label 已切换到精确 tag Runtime；`/market`、`/market/chart`、`/backtests` 均读回
  HTTP `200`，local-services-status=`overall=passed`。不加载或执行 RQAlpha sidecar，不运行手工
  after-market、真实通知、migration、Canonical/production DB/Redis 写入，也不改变 Alert Scope/transport
  或 Execution Review roll，`auto_order=false` 不变。

## v1.8.1 release and Runtime deployment

- release preparation commit 为 `4d67c1f6d`；main integration 与 annotated tag peeled commit 均为
  `7e05d7d63f1e3437852fdcd56d6a3401fd7bcd16`。本版包含 JDJ active60 Historical reference replay、
  No-Watch Reliability V1、SuBing Daily Watch V1 及其 5 个 Important 窄修复。
- exact main merge tree 验证为 backend `3659 passed / 3 skipped / 16 deselected`、engineering `63 passed`、
  Web unit `276 passed / 1 skipped`、Playwright `98 passed / 1 skipped`、Mypy
  `154 source files / 0 issues`；Ruff、Web build、OpenSpec `6 passed`、secret scan 与 diff check 均通过。
- 五个现有 launchd label 已切换到精确 tag Runtime；不加载 RQAlpha sidecar，不运行手工 after-market、
  真实通知、migration、Canonical/production DB/Redis 写入，也不改变 Alert Scope/transport 或 Execution
  Review roll，`auto_order=false` 不变。首次自然盘后与 Daily Watch artifact 验收继续 `pending`。

## v1.8.0 release closeout

- release preparation commit `91246004cb4c2c8d72cf8729edca8a99b3e6982b` 已合入 `develop`；main release
  integration 与 tag peeled commit 均为 `8fac0a5f22951715711680b554a635d76166af24`，并已完成远端读回。
- exact candidate 验证为 backend `3409 passed / 3 skipped / 16 deselected`、engineering `62 passed`、Web
  unit `255 passed / 1 skipped`、Playwright `93 passed / 1 skipped`；Ruff、Mypy、Web build、OpenSpec、
  secret scan、launchd render/lint 均通过。
- Runtime 补齐前端 lockfile 依赖与 production build 后，仅重启 Web label；五个 label 的 exact root/commit
  读回一致，local-services-status 与 local-tunnel-healthcheck 均为 `overall=passed`。
- 本 release 不含 migration、Canonical/production DB/Redis 写入、Scope/transport 变化、通知
  retry/replay/backfill 或订单能力，`auto_order=false` 不变。

## v1.7.0 release closeout

- release PR `#197` 已合入 main；release commit、annotated tag peeled commit 与 Runtime checkout
  精确一致。最终 Standards/Spec review 均为 `C0/I0/M0`。
- exact candidate 验证为 backend `2703 passed / 3 skipped / 16 deselected`、isolated PostgreSQL
  `16 passed`、engineering `58 passed`、Web unit `208 passed / 1 skipped`、Playwright `74 passed`，
  Ruff、Mypy、Web build、OpenSpec、secret scan 与 launchd render 均通过。
- 本 release 不含 migration、Canonical/production DB/Redis 写入、Scope/transport 变化、通知
  retry/replay/backfill 或订单能力，`auto_order=false` 不变。

## Market Trend Focus V1 v1.8.0 integration

- Market Trend Focus V1 implementation exact head `b4330123d8483ebdd42583d1816ac15cf99b61db`
  已随 v1.8.0 release 合入；它仍是只读 Market research surface，不接 Alert、Runtime 或订单。
- 2026-08-23 Lane 3 exact-head 验证为 Trend Focus/API `77 passed`、backend
  `2808 passed / 3 skipped / 16 deselected`、Web unit `221 passed / 1 skipped`、B1 Playwright
  `48 passed`；Ruff、Mypy、Web build、OpenSpec 与 secret scan 均通过。真实 active60 只读快照为
  Radar `ready/current / 60 active / 60 participant`、结构可评估 `32`、typed unavailable `11`
  且全部为 `HOURLY_HISTORY_INSUFFICIENT`、long/short opportunity=`1/0`、
  setup/breakout/retest/ready=`1/0/0/0`、running/weakening=`10/11`；六个 completed 15m cutoff
  共 `192` 次 prefix 比较，`0 mismatch`，无 future/same-boundary/cross-contract identity 冲突。
- prospective shadow 仍是下一受控 Gate，当前未启用；本状态不授权真实通知或任何正式数据写入。

## JDJ active60 1m reference replay v1.8.1 integration

- pre-status implementation/plan exact head 为
  `683c98a21bd70b2231cbf8975147bad358a73e77`。当前 active60 中单产品的
  `actual_dominant + 1m` JDJ Historical reference replay 已完成实现，JM Golden exact parity 通过。
- 固定 smoke window `2026-08-18..2026-08-20` 的唯一授权 retry 观察到 `60 ok / 0
  typed_unavailable / 0 command_failed`，合计 `2004` 个 action；该数量只表示 reference replay
  capability coverage，不构成排名、PnL 或策略有效性结论。
- 该能力已随 v1.8.1 合入 main/release，但仍是 research-only，未消费 prospective OOS，也不成为
  Alert、Runtime、RQAlpha、Canonical、data、DB、Redis 或 order consumer。

## 当前 Runtime 与产品面

- Data Foundation DFD-01～DFD-07 已完成，active 60 与 operational 60 一致。Historical 事实链为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`；Redis Live
  与 Historical Canonical 分离，Live 不写 Parquet/DB。
- Market Runtime V1 已启用：只观察 `operational_products.txt` 的当日 rank1 completed 1m，并在
  18:05 及最多一次一小时后 retry 更新相同范围。
- Alert Runtime V2 已启用：Code Registry 只含 `htdy_original_15m` 与
  `subing_entry_signal_v1`。HTDY 每 Event 最多向 Topic 发起一次请求，SuBing 每 Event 最多向 owner
  发起一次请求；无逐人状态、retry、queue、replay、backfill、fallback 或订单路径。
- Execution Review V1 是独立 Application Domain。HTTP request-scoped composition 每请求读取一次
  roll Gate 并注入 callback；missing/`disabled`/`invalid` 时 callback 返回
  `ROLL_RECONCILIATION_REQUIRED` 且不得创建 `DOMINANT_ROLL`，只有 `enabled` 注入真实 reconciler。
- Market Web 的 B1 流程已进入 production：首页为“需要处理 → 优先检查 → 全市场研究”，详情页使用
  “当前检查栏”；正式 Event、研究观察和 Research-only 事实保持分层，不产生综合分或交易推荐。
- The prior Four-System Active60 All-Frequency Observation direction was withdrawn by the user before implementation and its active Spec/Plan were removed.

## SuBing Daily Watch V1 v1.8.1 integration

以下 Gate 只记录各自已经发生的事实，任一状态不得由其他状态推导：

| Gate | 状态 | 独立 evidence |
|---|---|---|
| `CODE_COMPLETE` | `complete` | code-complete implementation base=`ed14c5a1990f34121329b22d05e3c6b612935264`；最后一笔 Daily Watch 业务修改=`30ed956ea7a4a7db2193db61156030fea9489157` |
| `TEST_COMPLETE` | `complete` | 下述 focused/full backend、Web、Mypy、Ruff、OpenSpec、secret 与 diff checks 已完成 |
| `REVIEW_COMPLETE` | `complete` | 对 implementation base 到 `develop@421ec498a2af08ad804f03e9b8c4c84b5c16211f` 的独立 Standards/Spec Review 均为 `C0 / I0 / M0`，结论=`允许集成 develop` |
| `INTEGRATED_DEVELOP` | `complete` | implementation base、全部 Review 修复与 `30ed956ea` 均为远端 `develop@421ec498a2af08ad804f03e9b8c4c84b5c16211f` 的祖先 |
| `RELEASED` | `complete` | annotated `v1.8.1` peeled commit=`7e05d7d63f1e3437852fdcd56d6a3401fd7bcd16` |
| `RUNTIME_PROMOTED` | `complete` | 本机五个 label 已绑定 clean/detached `v1.8.1@7e05d7d63f1e3437852fdcd56d6a3401fd7bcd16` |
| `NATURAL_EVIDENCE_COMPLETE` | `pending` | 首次自然 after-market 尚未发生，Daily Watch current 仍为 `SUBING_DAILY_WATCH_NOT_GENERATED` |

`RUNTIME_PROMOTED=complete` 不表示 `RUNTIME_READY`：当前只读 health 仍是
`degraded / after_market_run_missed`。`NATURAL_EVIDENCE_COMPLETE` 必须等待真实自然盘后 artifact、API 与
Web 验收，不得由 code、tests、Review、develop integration、release 或 Runtime promotion 补证。

- SuBing Daily Watch V1 已随 v1.8.1 合入 main/release 并部署到精确 tag Runtime。2026-08-24 的窄修复补齐同 target 失败后 current
  fail-closed、目录及原子文件 mutation/replace 前扩展盘 root 重验、snapshot
  decision/reason/fact/price-side 语义校验，以及来自重构前实现的 5m/15m EMA/slope 独立 golden parity
  覆盖；Task 0–9 的代码与 canonical 已收口。
- 2026-08-24 fresh verification 为 focused backend `175 passed`、full non-isolated backend
  `3659 passed / 3 skipped / 16 deselected`、engineering `63 passed`、Mypy
  `154 source files / 0 issues`、Web unit `276 passed / 1 skipped`、full Playwright
  `98 passed / 1 skipped`；Ruff、Web build、OpenSpec `6 passed`、secret scan `0 findings`、ops shell、
  launchd plist lint 与 diff check 均通过。该 feature 不含 migration、schema 或 concurrency 变化，因此未运行
  isolated PostgreSQL，也未连接 production DB。
- 扩展盘 root 已配置并通过 production resolver，但当前尚未生成真实 `history/current/generation-status`
  文件，也未运行或回填真实盘后任务。首次自然 after-market evidence 继续 `pending`；production Alert Scope/transport、
  prospective OOS 及其他既有 Gate 均未改变。

## No-Watch Reliability V1 v1.8.1 integration

- No-Watch Reliability V1 已达到 `CODE_COMPLETE / TEST_COMPLETE` 并合入 develop：Alert 已有无 TTL Redis schema v1
  processing/notification observation；盘后已有 schema v2 crash-visible `current_run`、18:20 expected-day
  与 2h stuck health；Market 首页已有唯一完整 DTO 的 Runtime strip；data audit 已有默认
  stdout 兼容的可选 stderr NDJSON progress。
- 盘后 owner PushPlus 只针对受监督自然 execution failure、最多一次且无 retry；它与
  Alert Rule/Application Domain 分离，不用 Topic、`AlertEvent` 或 DB。missed/stuck 只是 health，
  provider accepted 不等于送达。
- 整分支 final review 首轮发现 3 个 Important；在 reviewed implementation head
  `eddd13f9999297a93286389a85805c27fc41264f` 修复后，唯一 scoped re-review 为 `APPROVED`，
  Critical/Important/Minor 均为 `0 open`。
- 最终验证为 backend non-isolated `3521 passed / 3 skipped / 16 deselected`、Ruff clean、Mypy
  `150 files / 0 issues`、Web unit `264 passed / 1 skipped`、build passed、Playwright
  `97 passed / 1 skipped`、OpenSpec `6 passed`、secret scan `0 findings` 与 diff check clean。
- develop 首次 integration 的 local 与 remote readback 均为 reviewed implementation head
  `eddd13f9999297a93286389a85805c27fc41264f`；该 SHA 不表示本次 `STATUS.md` 收口提交后的最终 remote head。
- No-Watch 已随 v1.8.1 release 与 Runtime switch 部署；新 Runtime 根当前如实报告当日 after-market
  `missed`，等待下一次自然执行。未执行真实 PushPlus、自然 HTDY/SuBing/after-market 新验收、真实 data audit、RQData、
  Canonical/production DB/Redis 写入或 migration。

## 当前 research evidence

- SuBing、N Structure 与三条 JDJ Candidate 的 retrospective baseline 已冻结；各自 prospective OOS
  独立保持 `pending`，不得用 retrospective 或 embargo 回填。
- Multi-Candidate Robustness 与 JDJ Active60 Robustness evidence 已冻结；typed unavailable 保留，
  不生成 score/rank/winner/KEEP/DROP/PROMOTE。
- Five-Candidate Phase 8 dossier 与 relationship-topology evidence 已冻结；source-specific window、
  comparability/relationship、N→JDJ dependency 与 JDJ overlap 的边界保持分离。Phase 8 已完成，
  不保留 active task/plan。
- 当前 evidence artifact 位于：
  - `reports/research/candidate_validation/`
  - `reports/research/candidate_robustness/`
  - `reports/research/candidate_dossier/five_candidate_research_dossier_v1/`
  - `reports/research/candidate_relationships/five_candidate_relationship_topology_v1/`
- 主力照妖镜唯一 active identity 为 `main_force_mirror_v2`。60m sequence forensic 代码与 CLI 已完成，
  但真实 JM/active60 read-only evidence Gate 未执行；当前不得形成 `STOP` 或
  `ALLOW_PHASE_FREEZE_DESIGN` 结论，更不得冻结正式 Phase、接入 Web/Alert/Runtime 或晋升。
- Main Force Mirror Diagnostic Phase A 的 CLI、composition、显式 payload 与端到端只读边界已
  `CODE_COMPLETE / TEST_COMPLETE`；协议仍是 `main_force_mirror_diagnostic_phase_a_v1`，底层
  indicator identity 仍是未修改的 `main_force_mirror_v2`。JM named view payload 会从同一 full causal
  input 输出 scoped label/sequence/funnel 或 typed unavailable，不运行独立 model/member/Gate。真实 JM named view 与 active60 diagnostic
  evidence 未运行，因此 empirical final Gate 仍为 `pending`；本轮未生成 evidence artifact，不得
  复用历史 sequence `STOP`/`REJECT` 或宣称 release、Runtime-ready。
- 所有 evidence 都只是可复算 research facts：不生成盈利、有效性、可交易、Alert Rule、release 或
  Runtime-ready 结论；不写 Canonical/DB/Redis，不消费 prospective OOS，`auto_order=false`。

已冻结 evidence 的 exact protocol、window、hash、count 和 artifact identity 由对应 policy、report 与
测试保存，不在本文件复制；下方分别保留尚未执行的 MFM sequence forensic
`2023-01-01..2026-08-20` 与 Diagnostic Phase A `2023-01-01..2026-08-18` 两项独立
protocol/window Gate 边界，两者均不因代码或测试完成而视为已运行。

### MFM sequence forensic 真实 evidence Gate

该 Gate 必须按以下顺序完整执行，不能拆分、缩窗或静默丢弃 unavailable：

1. 先只读运行 `jm / actual_dominant / 60m / 2026-03-10..2026-03-30 / --forensic`，核对 peak、首次
   decay/liquidation/opposite-build/accumulated-reversal 的 evidence Bar、causal delay 与 physical-contract
   continuity；member context 不可用时只记录 unavailable，不补取或猜测。
2. 再由仓库外层 shell loop 逐行读取 `data/universe/active_products.txt`，对完整 active60 运行
   `actual_dominant / 60m / 2023-01-01..2026-08-20`。只允许 OS temp 输出，不新增 repository batch
   module/script；typed-unavailable 必须显式保留，命令失败也必须保留 stderr/status，不能跳过品种。
3. 只比较 `balanced / fast / slow / loose / strict` 五个预定义 profile。每 profile 检查 sample count，
   以及 `1/3/5/10` Bar 的 `median_reversal_return / hit_rate / median_mfe / median_mae`；同时检查 yearly、
   long/short symmetry、product concentration、cross-year drift 与从 peak 到 later evidence 的 causal delay。
   禁止选择 best profile，禁止 ranking、PnL、Sharpe、winner 或按品种调参。
4. sequence facts 不稳定、因果证据过晚、样本过稀或产品特化到不能实质减少人工拼接/改善复盘
   evidence 时必须 `STOP`；只有存在跨产品、跨年度、跨方向的小而稳定区域才允许
   `ALLOW_PHASE_FREEZE_DESIGN`。最终结论只能是这两者之一。
5. `ALLOW_PHASE_FREEZE_DESIGN` 只授权未来 Lane 3 正式 Phase 的设计，不授权实现、Web/API、
   Alert/notification、Runtime、release、策略晋升或订单。
6. 临时目录只有在 real path 精确匹配 `/private/tmp/guiyi-mfm-v2-sequence-forensic.*`、无 symlink/子目录/
   device/socket、文件名与 active60 对应且只含 `.json/.stderr/.status` 后才可删除；任一检查失败必须
   fail-closed 并保留 exact directory 供检查，禁止删除 broad root、glob 或 unresolved variable。

Exact 命令见 `TESTING.md`。该协议只定义未来 read-only Gate，不构成本轮执行授权。

## 待完成 Gate

- v1.8.1 首次自然 after-market 与 Daily Watch artifact/API/Web 验收 `pending`；不得手工触发、回填或
  复制旧 Runtime 状态补证。
- MFM 60m sequence forensic 的真实 JM + active60 Historical read-only evidence Gate `pending`；本次不
  运行、不生成临时 evidence、不输出 Phase Gate 结论。
- MFM Diagnostic Phase A 的真实 JM named view + frozen active60 Historical read-only diagnostic
  evidence 及 empirical `STOP|ALLOW_PHASE_FREEZE_DESIGN` Gate `pending`；当前只有代码与测试证据。
- 自然 HTDY Topic Event 与自然 SuBing owner Event 的 production 验收 `pending`；不得用 synthetic
  Event、manual send、replay、backfill 或 retry 补证，历史 canary 不重复。
- SuBing 自然 Live seam 仍需真实时点观察；Canonical-only HTTP smoke 不替代自然 Live evidence。
- 当前 v1.8.1 API/Web/Market Runtime root 的下一次自然 18:05 盘后业务证据待观察；不得人工触发、回填或
  用旧 root evidence 补证。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 继续按各自 exact protocol 独立累积，当前均
  `pending`。
- Execution Review Gate D 继续 `disabled / not activated`。

## 事实源边界

- 当前 release、Runtime、Scope、evidence 与 pending Gate 只看本文件。
- 稳定产品边界看 `PROJECT_SOURCE.md`；长期决策理由看 `DECISIONS.md`；模块依赖看
  `docs/ARCHITECTURE.md`；命令看 `TESTING.md`。
- 已完成 spec/plan/task 与逐次 release/promotion 流水只从 Git history、`CHANGELOG.md`、tag 和 commit
  追溯，不作为 active surface。
