# 当前状态

更新时间：2026-08-22

## 正式 release 与 production Runtime

- 当前正式 release 为
  `v1.6.5@b0be6364580b4ed509cfe76573b4085c3b5a7924`；annotated tag object 为
  `0ab86e64f01f6e0f0b423c6cf1b86be4791a6360`，message=`Release v1.6.5`。
- production Runtime 为 clean/detached
  `/Volumes/扩展盘/guiyi-quant-runtime-v1.6.5@b0be6364580b4ed509cfe76573b4085c3b5a7924`。
- 2026-08-21 最终只读读回：API/Web/Live/after-market/Alert 五个 label 的 root 与 loaded commit
  均匹配；Market/Alert marker enabled；API=`200 / 1.6.5 / readonly`、Web=`200`、Runtime
  health=`ok / readonly`、PushPlus config=`ready`、overall=`passed`、Market dominants=`60`。
  after-market 已加载但当前未运行属于定时服务正常空闲；该 switch 未发送 canary 或人工通知。
- production migration 为 head `20260815_0039`。Alert 两条 Rule Scope 均精确为 `jm`；Execution
  Review roll marker 为 `disabled / not activated`。

## v1.7.0 release candidate

- `develop` 已准备代码版本 `v1.7.0`：版本身份、canonical/README/TESTING、Web B1 使用说明、
  Research/Execution Review/Runtime seam 与测试治理已进入本地 release-candidate 变更。
- 当前状态为 `CODE_COMPLETE_FULL_VERIFICATION_REVIEW_PENDING`。前一轮本地 health/version、
  engineering、定向 backend、Research CLI、Web unit/build、Ruff、Mypy、OpenSpec、secret/diff 验证
  已通过；独立审查修正后仍须 fresh full verification 与 independent review。尚未创建 main merge、tag、release，也未
  push、部署或切换 Runtime；production 继续保持 `v1.6.5`。
- 本 candidate 不含 migration、Canonical/production DB/Redis 写入、Scope/transport 变化、通知
  retry/replay/backfill、Runtime promotion/switch 或订单能力，`auto_order=false` 不变。

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
- Market Web 的 B1 流程已进入 `develop`：首页为“需要处理 → 优先检查 → 全市场研究”，详情页使用
  “当前检查栏”；正式 Event、研究观察和 Research-only 事实保持分层，不产生综合分或交易推荐。

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
- 所有 evidence 都只是可复算 research facts：不生成盈利、有效性、可交易、Alert Rule、release 或
  Runtime-ready 结论；不写 Canonical/DB/Redis，不消费 prospective OOS，`auto_order=false`。

已冻结 evidence 的 exact protocol、window、hash、count 和 artifact identity 由对应 policy、report 与
测试保存，不在本文件复制；下方只保留唯一尚未执行的 MFM Gate 完整执行合同。

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

- v1.7.0 candidate 只达到 `CODE_COMPLETE_FULL_VERIFICATION_REVIEW_PENDING`；fresh full verification
  与 independent review 通过后，才允许进入彼此独立的 main/tag/release 与 Runtime promotion/switch
  Gates；这些外部操作仍需各自新的明确执行意图。
- MFM 60m sequence forensic 的真实 JM + active60 Historical read-only evidence Gate `pending`；本次不
  运行、不生成临时 evidence、不输出 Phase Gate 结论。
- 自然 HTDY Topic Event 与自然 SuBing owner Event 的 production 验收 `pending`；不得用 synthetic
  Event、manual send、replay、backfill 或 retry 补证，历史 canary 不重复。
- SuBing 自然 Live seam 仍需真实时点观察；Canonical-only HTTP smoke 不替代自然 Live evidence。
- v1.6.5 API/Web/Market Runtime root 的下一次自然 18:05 盘后业务证据待观察；不得人工触发、回填或
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
- 最小下一步：在当前 exact candidate 上运行 fresh full verification 并完成 independent review；两者
  都通过后才进入独立 release Gates。当前不执行 push、release/tag、Runtime、通知、DB/data 或真实
  research evidence。
