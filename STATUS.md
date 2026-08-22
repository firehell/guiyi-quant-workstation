# 当前状态

更新时间：2026-08-22

## 当前身份

- 归一量化是本地、单用户的国内期货研究工作站。所有信号、页面和通知只用于人工观察；
  `auto_order=false`，仓库不存在订单创建或提交路径。
- 当前正式 release 为
  `v1.6.5@b0be6364580b4ed509cfe76573b4085c3b5a7924`；annotated tag object 为
  `0ab86e64f01f6e0f0b423c6cf1b86be4791a6360`，message=`Release v1.6.5`。
- production Runtime 为 clean/detached
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.6.5@b0be6364580b4ed509cfe76573b4085c3b5a7924`。
  2026-08-21 最终只读读回：API/Web/Live/after-market/Alert 五个 label 的 root 与 loaded commit
  均匹配；Market/Alert marker enabled；API=`200 / 1.6.5 / readonly`、Web=`200`、
  Runtime health=`ok / readonly`、PushPlus config=`ready`、overall=`passed`；Market dominants=`60`。
  after-market 当前未运行属于定时服务的正常空闲状态。Alert 的首次 fail-closed 后，已修复 Git 外配置引用并以
  新的一次性授权完成 switch；未发送 canary 或人工通知。

## 当前产品与 Runtime 面

- Data Foundation DFD-01～DFD-07 已完成，active universe 为 60 品种。历史事实链固定为
  `RQData -> staging/校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`；
  Historical Canonical 与 Redis Live Overlay 分离，Live 不写 Parquet/DB。
- 当前用户接口为 Market Web、独立 `/trade-records`、`/api/v1/market/*`、`/api/alerts/*`、
  `/api/execution-review/*`，以及 `guiyi data`、只读 `guiyi research` 与 `guiyi runtime` 子命令；
  精确清单和边界见 `PROJECT_SOURCE.md`。
- Market Runtime V1 已启用，只处理与 active 60 一致的 `operational_products.txt`：Live 观察当日
  rank1 completed 1m；盘后在 18:05 及最多一次一小时后 retry 更新同一范围。
- Alert Runtime V2 已启用，Code Registry 只含 `htdy_original_15m` 与
  `subing_entry_signal_v1`。production 两条 Rule Scope 均精确为 `jm`；HTDY 每个自然 Event
  最多向 `htdy_observers` Topic 发起一次 PushPlus 请求，SuBing 最多向不带 Topic 的 owner 发起一次。
  无逐人状态、retry、queue、replay、backfill、fallback 或订单路径。
- Execution Review V1 保持独立 Application Domain；production migration 已在 head
  `20260815_0039`，但 roll marker 仍为 `disabled / not activated`。
- v1.6.5 已包含 Market Radar freshness、SuBing Canonical/Live current-read seam 修复、Web
  error-only K 线 fallback、PushPlus transport、installer fail-closed activation，以及 SuBing overlay 不再侵占
  Market display identity 的修复。SuBing 的历史 cutoff
  仍为 strict cursor，任何 Factor/Lifecycle Historical Bar 都必须满足 `bar_end <= cutoff`；
  `MarketDataService`、Factor/Signal/Lifecycle 公式、Alert Rule/Scope 与 Event 语义未放宽。
- 主力照妖镜唯一 active identity 为 `main_force_mirror_v2`：仅支持 `60m +
  contract|actual_dominant` Historical confirmed observation，并只读钉住的不可变
  `main_force_member_rank_v1` snapshot。Web 底部副图只保留 `MACD | 主力照妖镜 V2`；
  V0/V1 已退役，仅可从 Git history 追溯。真实 member snapshot 与 retrospective matrix 未执行，
  Live/Alert/notification 仍不接入，`auto_order=false`。
- SuBing Lifecycle V2、N Structure V1 与 JDJ 1m Candidate V1 仍只属于
  observation/research 面；不进入订单路径，也不因已有代码或 retrospective evidence 自动晋升。

## 当前研究证据

- SuBing exact Candidate baseline：
  `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json`，
  SHA256=`1a1b3064dcb9084adc7347e024c001a2fe7c4bb7ba909c6c80f31659ecc3b3d1`。
  prospective OOS 从 `2026-08-20` 开始，当前为 `pending`。
- N Structure exact Candidate baseline：
  `reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json`，
  SHA256=`12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6`。
  prospective OOS 从 `2026-08-21` 开始，当前为 `pending`。
- JDJ 1m 三条 exact Candidate baseline 均冻结于 `jm / through=2026-08-21`，retrospective
  为 `2023-01-01..2026-08-20`，10-fold rolling 已形成，prospective 首日固定为
  `2026-08-24` 且当前为 `pending`：
  - Trend Follow：
    `reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json`，
    SHA256=`63a9f3021ae30eab777d838c39493f1ef195c07edc49f5471cbbb2de98621fef`；
  - Trend Reentry 6：
    `reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json`，
    SHA256=`63f9dfdd29eabfa2c7b44fbe24aa31198dddffae60fab856e9d1b2684cb35bea`；
  - Key-Level Breakout：
    `reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json`，
    SHA256=`6e06b894bb05a0de2c857be0143cdd44d0b7479b33ad712a0db88197bbdcab10`。
  三份 evidence 均为 `research_only=true / readonly=true`，horizons 固定为 `3/5/8/20`；
  不包含 decision、fill、order、PnL 或自动 ranking/promotion。
- Multi-Candidate Robustness V1 evidence：
  `reports/research/candidate_robustness/multi_candidate_robustness_v1/anchor-jm-active60-retrospective-freeze-2026-08-20.json`，
  SHA256=`6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433`。
  exact protocol 为 `multi_candidate_robustness_v1`，冻结于 `2026-08-20T21:33:00+08:00`；
  active60 矩阵完整保留 `2 × 60 = 120` cells（`98` available、`22` typed unavailable），
  `jm` 双向关系只在 same symbol + same physical contract + same rank1 segment 内比较。
- JDJ Active60 Robustness V1 evidence：
  `reports/research/candidate_robustness/jdj_active60_robustness_v1/active60-retrospective-freeze-2026-08-21.json`。
  exact protocol 为 `jdj_active60_robustness_v1`，只读窗口为 `2023-01-01..2026-08-20`；
  `3 × 60 = 180` cells 完整，其中 `147` available、`33` typed unavailable
  （`11` 个品种 × 三条 Candidate，reason=`JDJ_SOURCE_UNAVAILABLE`）。两次未改输入的只读复算
  parsed JSON 语义相等；prospective 首日仍为 `2026-08-24` 且当前 `pending`、未消费。
  该 evidence 不生成 score/rank/KEEP/DROP/PROMOTE，不改变 Alert、Runtime 或订单边界。
- Phase 8A artifact-only Five-Candidate dossier evidence 已冻结：
  `reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`，
  SHA256=`632c7b88bc3dfaf15d9640f32d014b9af0665376959e10c73101956cdc81ee99`。该 artifact
  只组装 `5` 份 Candidate dossier、`7` 份已冻结 source artifact 与 `10` 个显式
  comparability pair；保留 SuBing `2023-01-01..2026-08-18`、N
  `2023-01-01..2026-08-19` 与三条 JDJ `2023-01-01..2026-08-20` 的 source-specific
  retrospective window，不改写为 five-Candidate common window。完整保留
  `300-cell inventory/count invariants`：`300` source cells = `245` available + `55` typed
  unavailable；详细 matrices 按 dossier 合同省略。不新算 metric 或 relationship，不消费
  prospective OOS。Phase 8B 明确尚未完成。
- 以上证据都只是可复算的 retrospective/rolling research facts：不生成自动排名、winner、
  KEEP/DROP/PROMOTE、盈利、有效性、可交易、Alert Rule、release 或 Runtime-ready 结论；
  不写 Canonical/DB/Redis，不回填 prospective OOS。

## 待完成 Gate

- 自然 HTDY Topic Event 与自然 SuBing owner Event 的 production 验收仍为 `pending`；不得用
  synthetic Event、manual send、replay、backfill 或 retry 补证。历史 owner/Topic canary 已完成，
  后续 release/switch 不重复 canary。
- SuBing 自然 Live seam 仍需在 Live observation 可用的真实时点观察；已有 Canonical-only HTTP 200
  smoke 只证明无未来 Bar，不替代自然 Live evidence。
- v1.6.5 API/Web/Market Runtime root 的下一次自然 18:05 盘后业务证据待观察；2026-08-18 的既有自然成功
  证据保留，但不冒充新 root 的自然运行。不得人工触发、回填或补证。
- SuBing、N 与 JDJ 三条 Candidate 的 prospective OOS 继续按各自 exact protocol 独立累积，
  当前均为 `pending`；不得用 retrospective 或 embargo 日回填。
- Phase 8B relationship-topology 研究仍为 `incomplete`；Phase 8A artifact freeze 不自动启动或
  完成 Phase 8B。
- Execution Review Gate D 继续 `disabled / not activated`。

## 事实源与边界

- 当前阶段与可变 Runtime 事实只看本文件；产品边界看 `PROJECT_SOURCE.md`；长期决策看
  `DECISIONS.md`；架构与数据语义看 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md` 和
  `openspec/specs/`；命令看 `TESTING.md`。
- 已完成的 spec、plan、task 与逐次 release/promotion 流水不再作为 active 文档维护；历史事实由
  `CHANGELOG.md`、Git tag、commit 与 Git history 追溯。
- 代码、测试、retrospective evidence、健康绿灯或历史授权都不授予新的 migration、数据写入、
  Scope 变化、真实通知、release/tag、Runtime switch/promotion 或订单能力。
- 最小下一步：等待并只读记录 v1.6.5 Runtime 的下一次自然 18:05 盘后结果；在自然时点之前不人工补证。
