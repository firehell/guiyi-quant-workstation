# 当前任务：INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406

生成时间：2026-07-19

状态：`COMPLETED / INDICATOR_CONTRACT_READY`

Codex 从已接受 checkpoint `b2b2e35a` 创建独立分支，补全 Registry lifecycle capability invariants、formal policy consumer allow/block、HTDY strict formal Profile lineage 端到端证据，并按用户批准将 C5-01 协议转为 `final_frozen`。

Gate：

```text
INDICATOR_REGISTRY_V1_READY
STRATEGY_INDICATOR_POLICY_READY
HTDY_STRICT_FORMAL_REPORT_READY
INDICATOR_CONTRACT_READY
STRATEGY_VALIDATION_PROTOCOL_FROZEN
```

original 继续 `observation_only / HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。本任务未创建真实报告、未运行 OOS，未写 canonical DB、Parquet、Profile binding、live、SignalEvent、企业微信或订单。

证据：`data/reports/indicator_contract_v1/INDICATOR_CONTRACT_ACCEPTANCE_X406.md`、`indicator_contract_acceptance_x406.json`。任务记录：`docs/tasks/INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406.md`。

下一入口：阶段 5 独立 HTDY 候选报告 + trust audit Plan；任何 canonical PostgreSQL 写入需独立批准。

---

# 前一任务：CURSOR-WAVE-INDEPENDENT-REVIEW-X001

生成时间：2026-07-19

状态：`COMPLETED / ACCEPT_CURSOR_WAVE_AFTER_CODEX_FIXES / CODEX_ACCEPTED_CURSOR_WAVE`

Codex 已从冻结接管点 `b76791bf` 创建隔离分支，独立读取 Cursor checkpoints、diff、D4-00 与 handoff，并复跑声明及完整受影响测试。原 checkpoint 的 `git diff --check`、Web production build 和 formal snapshot fail-closed 存在缺陷，已由 Codex 修正后通过。

D4-00 继续为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；本 Gate 不是阶段 4、HTDY formal report、OOS、Review closed loop 或 live/archive Ready。

证据：`data/reports/ai_handoff/CODEX_CURSOR_WAVE_INDEPENDENT_REVIEW.md`、`data/reports/ai_handoff/codex_cursor_wave_independent_review.json`。任务记录：`docs/tasks/CURSOR-WAVE-INDEPENDENT-REVIEW-X001.md`。

下一入口：阶段 4 指标契约与 formal candidate Codex 正式验收 Plan；报告/DB 写入仍需独立批准。

---

# 前一任务：CURSOR-WAVE-HANDOFF-C999

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_WAVE_READY_FOR_CODEX_REVIEW`

Cursor Wave 统一交接包已落盘；定向测试与禁止范围审计通过；本地 checkpoint 已创建（不 push / 不 merge）。**不是**阶段 4 Ready。

产物：`data/reports/ai_handoff/CURSOR_WAVE_HANDOFF.md`、`data/reports/ai_handoff/cursor_wave_manifest.json`。任务记录：`docs/tasks/CURSOR-WAVE-HANDOFF-C999.md`。

下一入口：Codex `X0-01` / `CURSOR-WAVE-INDEPENDENT-REVIEW-X001`（独立复核，不信任 Cursor 自报）。

---

# 前一任务：CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED`

Market/Runtime 只读观察契约已预构建：面板、四态 fixture、targets 路径脱敏、前后端定向测试与 gap 报告。未启 runtime、未调 RQData、未写 DB，不得宣称 JM Live Archive Observation Ready。

产物：`apps/quant-web/src/components/market/MarketRuntimeObservationPanel.vue`、`data/reports/market_runtime/cursor_market_runtime_foundation_gap.md`。任务记录：`docs/tasks/CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A.md`。

下一 Cursor 入口：手册 `C-HANDOFF`。

---

# 前一任务：CURSOR-REVIEW-FOUNDATION-C506A

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_REVIEW_FOUNDATION_PREPARED`

Review/Web 正式上下文通用能力已预构建：面板、四态 fixture、deep-link/foundation 单测、报告可选只读透传与 gap 报告。未写 DB、未硬编码未来 report id、未宣称 closed-loop Ready。

产物：`apps/quant-web/src/components/review/ReviewFoundationPanel.vue`、`data/reports/strategy_review/cursor_review_foundation_gap.md`。任务记录：`docs/tasks/CURSOR-REVIEW-FOUNDATION-C506A.md`。

下一 Cursor 入口：手册 `C6-07A`。

---

# 前一任务：CURSOR-HTDY-VALIDATION-PROTOCOL-C501

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_VALIDATION_PROTOCOL_PREPARED`

HTDY strict JM 15m 验证协议与机器可读冻结配置已落盘（含 hard reject、E5-05 分支、SHA-256、schema/测试）。未跑正式回测/OOS，未写 DB，未改 report14，不得标记最终 frozen。

产物：`docs/strategy_specs/htdy/VALIDATION_PROTOCOL_V1.md`、`configs/oos/htdy_strict_validation_protocol_v1.json`、`configs/oos/schemas/htdy_validation_protocol_v1.schema.json`、`data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json`。任务记录：`docs/tasks/CURSOR-HTDY-VALIDATION-PROTOCOL-C501.md`。

下一 Cursor 入口：手册 `C5-06A`（Review/Web 通用能力预构建）。

---

# 前一任务：CURSOR-HTDY-FORMAL-PREFLIGHT-C405

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED`

HTDY strict 正式报告前只读证据包已落盘：九项定向复验 57 passed、golden 窗口 dry-run 摘要、申请包草案（无 packet_hash）、report14 隔离回归。未写 DB、未创建 BacktestReport、未宣称正式报告资格。D4-00 Gate 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。

产物：`data/reports/indicator_contract_v1/{htdy_formal_preflight.md,htdy_formal_apply_packet_draft.json,htdy_report14_regression.md}`。任务记录：`docs/tasks/CURSOR-HTDY-FORMAL-PREFLIGHT-C405.md`。

下一 Cursor 入口：手册 `C5-01`（策略验证协议和冻结配置）。

---

# 前一任务：CURSOR-STRATEGY-INDICATOR-POLICY-C404

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_STRATEGY_INDICATOR_POLICY_IMPLEMENTED`

正式策略 indicator policy 不可变 snapshot 与 fail-closed 校验已接入 formal 创建/报告读取；JM v1b.0 frozen legacy；HTDY strict 强制 strict_v1。未写 Alembic、未回填、未改 report 14。不得宣称 Codex 正式 Ready Gate。

定向测试见任务记录。任务记录：`docs/tasks/CURSOR-STRATEGY-INDICATOR-POLICY-C404.md`。

下一 Cursor 入口：手册 C4-05 / Cursor Wave 后续项。

---

# 前一任务：CURSOR-FIRST-FORMAL-CALLER-C403

生成时间：2026-07-19

状态：`COMPLETED / NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED`

证据型 no-op：C4-01 的 10 条 `formal_must_migrate` 无一满足低风险单 caller 迁移条件；未改业务代码、策略、DB、报告或 live。未进入 `MIGRATION_BLOCKED_OUTPUT_DIFF`。

任务记录：`docs/tasks/CURSOR-FIRST-FORMAL-CALLER-C403.md`。审计备注：`data/reports/indicator_contract_v1/INDICATOR_CALLER_AUDIT.md` §9。

下一 Cursor 入口：`C4-04`。

---

# 前一任务：CURSOR-INDICATOR-REGISTRY-C402

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_INDICATOR_REGISTRY_IMPLEMENTED`

扩展 Registry V1 生命周期、formal policy fail-closed 与 HTDY 双 code；未改数值算法、策略、DB、Parquet、Profile、live 或通知。不得宣称 `INDICATOR_REGISTRY_V1_READY`。

定向测试：`37 passed`。任务记录：`docs/tasks/CURSOR-INDICATOR-REGISTRY-C402.md`。

下一 Cursor 入口：`C4-03`。

---

# 前一任务：CURSOR-INDICATOR-CALLER-INVENTORY-C401

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_INDICATOR_CALLERS_AUDITED`

只读盘点指标调用方与 D4-00 HTDY 双版本边界；未修改业务代码、DB、Parquet、Profile binding、runtime 或 Issue。当前矩阵 36 条 caller（相对 7/18 基线 +3 experiment、1 锚点更名）。D4-00 最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；HTDY readiness 仅 provisional。

产物：`data/reports/indicator_contract_v1/{caller_inventory.csv,policy_matrix.csv,INDICATOR_CALLER_AUDIT.md}`。任务记录：`docs/tasks/CURSOR-INDICATOR-CALLER-INVENTORY-C401.md`。

下一 Cursor 入口：`C4-02`。

---

# 前一任务：CURSOR-CANONICAL-SYNC-C001

生成时间：2026-07-19

状态：`COMPLETED / CURSOR_CANONICAL_SYNC_PREPARED`

本任务只对齐 canonical 文档和任务池，不修改业务代码、DB、Parquet、Profile binding、runtime、Issue 状态或历史验收证据。继续确认 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 formal Market、Backtest、Signal、Review 的消费者准入 Gate；`DATA_LAYER_REAUDIT_REQUIRED` 同时保留为全历史 residual 的非阻塞维护 backlog。二者均不可扩写为 OOS、live、企业微信、长稳或自动交易 Ready。

D4-00（`HTDY-SOURCE-XMA-AUDIT-400`）审计产物已落盘，**不重新打开**公式审计。最终 Gate 诚实保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；不得宣称 `HTDY_XMA_SEMANTICS_AUDITED` 或 original formal 化。

本轮执行顺序固定为：完整 Cursor Wave → Cursor/Codex 单次交接 → Codex Wave。业务主线仍是阶段 4 指标契约封板、阶段 5 策略可信验证、阶段 6 JM T3/T4 真实 Gate。下一 Cursor 入口：`C4-01` 指标调用方盘点。

任务记录：`docs/tasks/CURSOR-CANONICAL-SYNC-C001.md`。

---

# 前一任务：V1-NEXT-WAVE-FACT-SYNC-000

生成时间：2026-07-18

状态：`COMPLETED / NEXT_WAVE_CANONICAL_SYNCED`

本任务只对齐 canonical 文档和任务池，不修改业务代码、DB、Parquet、Profile binding、runtime、Issue 状态或历史验收证据。已确认 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 formal Market、Backtest、Signal、Review 的消费者准入 Gate；`DATA_LAYER_REAUDIT_REQUIRED` 同时保留为全历史 residual 的非阻塞维护 backlog。

下一轮必须串行执行：阶段 4 指标契约与 formal candidate 封板、阶段 5 策略可信验证、阶段 6 在新稳定 runtime 副本上的 JM T3/T4 真实 Gate。OOS/walk-forward、T3 live 写入与 T4 archive 均不在本任务执行，且仍需其独立审批与用户授权。`report_id=14`、旧 audit 数字和历史证据保持不变。

Issue 生命周期建议：Issue #10（HTDY indicator/strategy spec）和 #11（Web EMA overlay）对应代码已并入当前主干，建议用户人工复核后关闭或归档；Issue #12 保持 open，后续应指向新稳定 runtime 副本及 T3/T4 Gate，不授权 live SignalEvent、企业微信、长稳或自动交易。

任务记录：`docs/tasks/V1-NEXT-WAVE-FACT-SYNC-000.md`。历史段落中“下一入口：手册 D4-00”已由 `CURSOR-CANONICAL-SYNC-C001` 接替为 Cursor Wave。

---

# 前一任务：CONSUMER-GOLDEN-QUERY-FINAL-GATE-005

生成时间：2026-07-18

状态：`COMPLETED / CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`

已从合入后的 `origin/main@f7f8ad2b` 在 direct PostgreSQL `READ ONLY` 事务和 Stage B 同一 data root 独立复跑 12 组 Golden Query。49 条消费者矩阵与 13 个 Hard Gate 全部通过；Market bars/EMA、Backtest resolver、适用的 Signal actual-confirmed source 和 Review exact-bars 使用相同 file ID、data version、binding snapshot 与显式 source interval。

arbitrary formal path、warning 进入 Backtest/Signal、`.MAIN` 作为 actual、daily duplicate、duplicate active binding、bars/indicator mismatch 和不同值冲突静默吞掉均为 0。Browser warning 显式可见；binding missing 样本 fail-closed；report 14 MD5 仍为 `ae807ef77f7d9a4ce3067996558b57e8`，155 trades / 239 orders 未变。

通过证据：`data/reports/consumer_golden_query_final_gate_20260718_rerun/`。修复前失败证据继续保留在 `data/reports/consumer_golden_query_final_gate_20260718/`。

本次 rerun 只写审计证据与 canonical 状态文档；未修改业务代码、数据库、Parquet、manifest、Profile binding、report 14、Signal/Review 历史记录或 live runtime。`DATA_LAYER_REAUDIT_REQUIRED` 继续保留，不声明 live runtime 或企业微信真实发送 Ready。

---

# 前一任务：MARKET-INDICATOR-DUAL-MODE-004

生成时间：2026-07-18

状态：`COMPLETED / MARKET_RESEARCH_MODE_READY / INDICATOR_BINDING_CONSISTENT`

Market coverage、bars、EMA 与 MACD 已显式区分 `access_mode=browser|research` 和 `data_mode=historical|live`。Browser 默认允许 active primary 且 non-failed 的 warning/unchecked 资产只读展示，并返回质量、actual/continuous、source mode、asset evidence 与 `strict_research_ready=false`；Research 强制显式 Profile，由 `ProfileLineageResolver` 执行 passed-only、identity、物理文件和 coverage Gate，失败返回稳定错误码。

Research bars 只解析一次 binding，随后以固定 `market_data_file_id` 和 immutable binding snapshot 读取；EMA/MACD visible window 与 warm-up 必须携带 bars 的 file ID 和 `lineage_token`，binding 漂移返回 409。后端对同 key 同值重复防御性合并，不同 OHLCV 冲突返回脱敏 asset evidence；Web 不再静默覆盖不同值，并在 indicator lineage 不一致时拒绝渲染。

Web route 保存 `access_mode/profile_id/data_mode`；Research 无 Profile 不发请求，Live 强制 Browser 并清除严格研究上下文。Browser warning、Research blocked/passed、route reload 和 historical/live 切换均完成浏览器 smoke，控制台 0 error / 0 warning。

验证：后端定向 `38 passed`；Web `59 passed / 1 skipped`（既有可选 HTDY golden bundle 环境项）；production build、Ruff、浏览器 smoke、`git diff --check` 通过。本任务无 Alembic、canonical DB、Parquet、manifest、Profile binding 或 live runtime 写入。长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`，不声明全数据层或 live runtime ready。

任务记录：`docs/tasks/MARKET-INDICATOR-DUAL-MODE-004.md`。

---

# 前一任务：SIGNAL-REVIEW-PROFILE-LINEAGE-003

生成时间：2026-07-18

状态：`COMPLETED / SIGNAL_REVIEW_LINEAGE_READY`

Formal historical Signal、live-confirmed SignalEvent 和 Review 已收口到既有 `ProfileLineageResolver` 与 `MarketDataReader`：只有 active / primary / passed、actual-contract mapping 一致、覆盖目标 bar window 且确认价匹配的资产才能生成 formal event。Signal task/signal/event 复用 migration `0023` 已有 lineage 列，immutable snapshot 保存于现有 JSON；本任务未新增 migration，未回填旧记录。

Review 新增 report/trade/signal/event 来源 lineage 解析和 exact-bars 读取，创建 note 时冻结 source snapshot；旧 report 14、旧 signal/event/review 缺 snapshot 时明确返回 `lineage_unavailable`，不猜测 `.MAIN`、provider 或最新 binding。Formal 流程不调用企业微信、Redis publish 或订单逻辑；Stage 9 Gate 已强制完整 lineage 和 confirmed-bar proof。

Canonical Gate 已完成：revision=`20260718_0024`；JM2609 actual-contract `2026-07-08..2026-07-10` 从 passed 1m 派生并登记 `5m/15m`（MarketDataFile `103924/103925`，DataQualityReport `115988/115989`），并切换 `intraday_research_v1` / `live_observation_v1` 的 actual-contract `5m/15m` active bindings（binding `4803..4806`）。`ProfileLineageResolver`、`SignalFormalLineageResolver`、Review exact-bars 和 Stage 9 Gate 复验均通过；旧 5 个 scan task、5 个 signal、3 个 event、6 个 review 的 lineage 仍为空，未机械回填。本 Gate 不调用 RQData、不触发 live runtime、不发送企业微信、不生成订单、不修改历史报告或策略参数。

证据：`data/reports/full_history_audit_v2_20260710/signal_review_lineage_gate_003/`。长期数据层状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`，仍不得声明 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。

---

# 前一任务：BACKTEST-PROFILE-CONTRACT-002

生成时间：2026-07-18

状态：`COMPLETED / BACKTEST_PROFILE_CONTRACT_READY`

Backtest formal API、fixed JM、inline、batch、task/report persistence 与 runner 已统一使用 `ProfileLineageResolver`、严格 `passed_only` 和 immutable binding snapshot。公开 API 不再接受主/辅助本地路径或 warning override；低层路径模式仅保留给显式 `research_only` 的 legacy/experiment/test fixture。

Formal contract 拒绝现已提供稳定错误码，覆盖 path forbidden、Profile/binding/file missing、quality blocked、range not covered、identity mismatch 和 inline binding changed；错误 context 只含 Profile 与行情 identity，不泄露本地路径。snapshot 显式记录 `ProfileLineageResolver / backtest_profile_v1 / passed_only`。

新增 migration `20260718_0024_backtest_binding_snapshot.py` 仅添加 nullable JSON snapshot，不回填历史行；已有 `0023` lineage 列已映射至 ORM。`report_id=14`、历史报告、Signal、Review、Market Indicator、策略参数、actual mapping 和行情资产均未修改。

定向验证：68 passed、0 skipped。包含 `report_id=14` 的隔离 PostgreSQL 已完成 `0023 -> head -> 0023 -> head` roundtrip；测试同时固定 Alembic `DATABASE_URL` 到 isolated 数据库，禁止 destructive roundtrip 被 canonical URL 覆盖。Canonical PostgreSQL 已升级到 `20260718_0024`，只新增两个 nullable snapshot 列；report 14、155 trades、239 orders 与迁移前副本哈希一致，trust audit SHA-256 一致，历史 task/report 非空 snapshot 均为 0。长期数据层状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。

---

# 前一任务：CONSUMER-DATA-CONTRACT-AUDIT-001

生成时间：2026-07-18

状态：`COMPLETED / CONSUMER_CONTRACT_GAPS_IDENTIFIED`

已只读审计 Market、Backtest、Signal、Review、Web、CLI、scripts 与 experiments 的 formal consumer escape paths。确认 generic Backtest 任意本地路径、fixed JM latest-file、task/report 缺 immutable Profile lineage、runner 缺字段默认 primary/passed，以及 Signal、Review、Market indicator 和 actual mapping 的后续契约缺口。

证据：`data/reports/consumer_data_contract_audit_20260718/`。

本收口只修改审计证据和任务状态，不修改业务代码、数据库、Profile binding、历史报告或行情资产。下一任务仅允许先处理 `BACKTEST-PROFILE-CONTRACT-002`；Signal、Review、Market Indicator 和 actual mapping 保持禁止修改。长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。

---

# 前一任务：DATA-ASSET-PROFILE-ACCEPTANCE-009

生成时间：2026-07-18

状态：`COMPLETED / DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT`

资产 Gate 9/9、Profile Gate 5/5 通过，hard blocked register=0。265 个 current candidate 与 direct PostgreSQL active binding 全部匹配，duplicate active=0、passed-only non-passed=0、historical/live boundary violation=0、unexplained superseded active=0；`report_id=14` 与冻结摘要一致。

证据：`data/reports/full_history_audit_v2_20260710/acceptance_009/`。

该结论仅允许进入阶段 C consumer contract；长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`，尚未通过 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。

---

# 前一任务：DATA-PROFILE-ROLLOUT-APPLY-008B

生成时间：2026-07-18

状态：`COMPLETED / PROFILE_ACTIVE_BINDINGS_VERIFIED`

B2-08A 冻结的 265 个 current candidate 已完成受控 rollout：241 个变更、24 个 unchanged，660 个 blocked 未写入。Pilot 与 JM2605 new-identity rollback 演练通过，最终 265/265 active 匹配、duplicate active=0、Golden Query 8/8 passed。写入仅限 `profile_active_bindings`，其他数据/质量/live/report14 内容摘要未变化。

证据：`data/reports/full_history_audit_v2_20260710/profile_rollout_008b/`。

长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。

---

# 前一任务：DATA-PROFILE-FULL-HISTORY-RULES-007

生成时间：2026-07-18

状态：`COMPLETED / PROFILE_FULL_HISTORY_SELECTION_READY`

## Profile 全历史 target-aware 语义与候选选优

B2-07 将三套 Profile 配置改为 Audit V2 target-aware 语义，正式目标来自 B2-03/B2-05/B2-06 evidence，不再使用旧 `target_asset_catalog.csv` 或 start 时间符号排序。candidate 必须覆盖全部 target ranges，并通过 provider/role/quality/physical/checksum/metadata/sealing/lineage Gate；frozen report 14 reference 与 conflicting duplicates fail-closed。

本任务不执行 binding apply，不写 DB、Parquet 或 manifest，不调用 RQData，不修改 `report_id=14`。长期状态保持 `DATA_LAYER_REAUDIT_REQUIRED`。

```text
products_count=90
target_rows=734
current_covering_rows=265
blocked_rows=660
dry_run_would_change=241
dry_run_unchanged=24
dry_run_errors=0
transaction_read_only=true
binding_apply_executed=false
status=PROFILE_FULL_HISTORY_SELECTION_READY
```

正式报告：`data/reports/full_history_audit_v2_20260710/profile_rules_007_final_002/`。

任务记录：`docs/tasks/DATA-PROFILE-FULL-HISTORY-RULES-007.md`。

---

# 前一任务：ACTUAL-DOMINANT-ROLL-V2-006

生成时间：2026-07-18

状态：`COMPLETED / ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED`

## Actual rank=1 与换月 Audit V2

B2-06 已完成只读 audit engine、受控 repair ledger/apply CLI、定向/回归测试，以及 Mac mini direct PostgreSQL 的 canonical 90-product final full。formal scope 是 canonical 90 品种 mapping/roll inventory，JM 是唯一 V1-B hard consumer；旧 actual `45` 只保留为历史审计模型快照，不参与本 Gate。

```text
audit_end=2026-07-10
products_file=data/universe/full_products_90.txt
product_count=90
rank1_mapping_count=287608
parameter_scope=jm_hard_consumer_window
hard_jm_residual_count=0
formal_residual_count=0
inventory_residual_count=1054
mapping_rows_inserted=11
manifest_rows_added=10
superseded_db_rows=3
local_rebuild_files=2
status=ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED
db_snapshot_source=direct_postgresql
calls_provider_api=false
calls_rqdata=false
profile_binding_changed=false
final_verify_writes_database=false
final_verify_writes_parquet=false
final_verify_writes_manifest=false
```

最终报告位于 `data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006_final_002/`。受控修复只使用冻结的本地证据：统一 historical/live resolver 语义，补登记 11 个 JM rank=1 日期，新增 10 行 repair manifest，将 3 条窄窗口重复 primary 标为 superseded，并从本地 raw 重建 JM2609 `2026-07-08..2026-07-10` 的 1m/1d。最终 JM hard 与 formal residual 均为 0；1054 条 90 品种 inventory residual 保持非 hard。未调用 RQData，未切换 Profile binding，长期数据层状态仍为 `DATA_LAYER_REAUDIT_REQUIRED`。

任务记录：`docs/tasks/ACTUAL-DOMINANT-ROLL-V2-006.md`。

---

# 前一任务：FULL-HISTORY-DERIVED-PERIODS-005

生成时间：2026-07-17

状态：`COMPLETED / DERIVED_PERIOD_TARGETS_VERIFIED`

## 派生周期核验与必要补齐

已完成独立 verify、session metadata repair 和 derived repair 流程，并在 direct PostgreSQL 与实际外置盘完成 90 品种最终 full。JM hard `5m/15m` 复用既有正确资产；仅新增一份 exact-lineage JM derived 1d candidate，不切换 binding。

```text
audit_end=2026-07-10
product_count=90
consumer_target_count=548
hard_target_count=8
hard_residual_count=0
session_metadata_actions=832
derived_repair_operations=1
new_derived_1d_file_id=103921
status=DERIVED_PERIOD_TARGETS_VERIFIED
writes_database=false
writes_parquet=false
writes_manifest=false
calls_rqdata=false
profile_binding_changed=false
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
```

正式 full 报告位于 `data/reports/full_history_audit_v2_20260710/derived_periods_005_final_001/`。session repair 与 derived 1d repair 均有冻结 ledger、before/after 和 rollback evidence；最终 verify 本身只读。

任务记录：`docs/tasks/FULL-HISTORY-DERIVED-PERIODS-005.md`。

---

# 前一任务：FULL-HISTORY-RESIDUAL-REPAIR-004B

生成时间：2026-07-17

状态：`COMPLETED / FULL_HISTORY_RESIDUAL_REPAIR_004B`

## 受控 residual 修复

B2-04A 四个队列已按 SHA-256 冻结。本轮完成 3 个 audit model code action，并按用户给出的 7 条精确 ledger 批准执行 metadata、local rebuild 和 RQData 批次。

90 品种 direct PostgreSQL 只读 Audit V2 重跑已确认三类 code residual 分别从 `483 / 140 / 90` 收敛为 `0 / 0 / 0`；数据层状态仍保持 `DATA_LAYER_REAUDIT_REQUIRED`。

```text
code_fix=IMPLEMENTED_TESTED
metadata_repair=EXECUTED_VERIFIED
local_data_rebuild=EXECUTED_VERIFIED_252_OF_252
rqdata=EXECUTED_VERIFIED_479_OF_479
profile_binding_changed=false
final_audit_v2_gap_count=0
final_full_checksum_mismatch_rows=0
final_full_checksum_declared_conflict_rows=0
final_missing_physical_rows=0
final_path_drift_rows=0
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
```

Closure dry-run 已冻结三个新批次：

```text
db-stale-retirement-002: 389 operations
local-rebuild-tf-002: 1 atomic operation / 5 candidate assets
rqdata-missing-actual-002: 71 operations (36 raw reuse / 35 RQData)
```

证据目录：`data/reports/full_history_residual_repair_20260710/closure_004b/`。下一 Gate 是用户分别批准三个新 ledger SHA-256；批准前不得写 DB、Parquet、manifest 或调用 RQData。

最终执行：DB retirement 389/389、TF candidate rebuild 5/5、`rqdata-missing-actual-004` 71/71 均完成并验证。RQData 批次为 4 daily raw reuse + 32 new 1m local-daily rebuild + 35 direct daily download；所有新 canonical 与 quality report 均为 candidate+passed，Profile binding 变化为 0。post-repair full-checksum inventory 的 27,837 行全部 matched/readable/schema_ok，Audit V2 gap_count=0。

任务记录：`docs/tasks/FULL-HISTORY-RESIDUAL-REPAIR-004B.md`。

---

# 前一任务：FULL-HISTORY-AUDIT-V2-RUN-003

生成时间：2026-07-17

状态：`FULL_HISTORY_AUDIT_V2_EXECUTED / AUDIT_BLOCKED`

## 全品种 Audit V2 重跑

本任务在 Mac mini 实际数据环境完成 quick 与 full 只读运行，使用 direct PostgreSQL，完整模式对 24763 个 canonical Parquet 执行 DuckDB 可读性与 SHA-256 校验。

```text
execution_status=FULL_HISTORY_AUDIT_V2_EXECUTED
gate_status=AUDIT_BLOCKED
db_snapshot_source=direct_postgresql
checksum_mismatch_rows=382
checksum_declared_conflict_rows=1384
outside_canonical_root_rows=4
missing_physical_rows=4
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
writes_database=false
writes_parquet=false
writes_manifest=false
calls_rqdata=false
```

硬 Gate 因 checksum failure 与 DB-only path drift 触发，因此本任务未宣布 Audit ready 或数据层 final ready。正式输出位于 `data/reports/full_history_audit_v2_run_20260710/`，B2-04A 只允许先做 residual root-cause triage。

任务记录：`docs/tasks/FULL-HISTORY-AUDIT-V2-RUN-003.md`。

---

# 前一任务：FULL-HISTORY-AUDIT-V2-ENGINE-002

生成时间：2026-07-17

状态：`FULL_HISTORY_AUDIT_V2_READY`

## 全历史 Audit V2 引擎

本任务已以冻结的 V1 全历史数据契约和 `FULL-HISTORY-PHYSICAL-INVENTORY-001` 物理事实盘点为输入，完成动态 expected window、actual rank=1、五层状态、reference metadata 与 Profile eligibility 分层审计。

硬边界：不写生产 DB、不写 canonical Parquet、不调用 RQData；保留旧 final audit 与历史报告，只新增 V2 输出。

固定审计终点：`2026-07-10`。

正式结果：

```text
status=FULL_HISTORY_AUDIT_V2_READY
data_gate_status=DATA_LAYER_REAUDIT_REQUIRED
db_snapshot_source=direct_postgresql
expected_window_count=720
target_year_row_count=7964
gap_count=180
writes_database=false
writes_parquet=false
calls_rqdata=false
```

任务记录：`docs/tasks/FULL-HISTORY-AUDIT-V2-ENGINE-002.md`。

---

# 前一任务：FULL-HISTORY-PHYSICAL-INVENTORY-001

生成时间：2026-07-17

状态：`FULL_HISTORY_PHYSICAL_INVENTORY_READY`

## 全历史物理事实盘点

本任务已完成只读 inventory 工具开发和 Mac mini 实际数据环境运行。正式结果位于 `data/reports/full_history_audit_v2_20260710/`，状态保持 `DATA_LAYER_REAUDIT_REQUIRED`。

---

# 前一任务：V1-WORKSTATION-SUPPORT-MODE-003

生成时间：2026-07-17

状态：`WORKSTATION_NON_BLOCKING_SUPPORT_MODE`

## 工作站转非阻塞支持模式

控制面 P0/P1 修复已经通过实现提交 `c209cdbf` 和 `main` 合并提交 `d54e0198` 落地，定向验证为 `63 passed`。WorkBuddy / GitHub Native V3 不再是数据重审前置建设。

支持模式边界：

- WorkBuddy Demo（Issue #27 / Draft PR #28）已收口为未完成归档；旧 Issue / PR 清理仍可继续，但不阻塞全历史物理事实盘点或 Audit V2。
- 后续只修复真实业务 Task 可复现暴露的控制面问题，并独立建立 follow-up。
- 不扩展多项目、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟。
- 本任务未修改 `scripts/ai`，未自动关闭 Issue / PR，未修改业务代码、数据、DB 或配置。

阶段 A Gate：

```text
V1_DATA_CONTRACT_FROZEN
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

阶段 B 影响：`不阻塞`。

任务记录：`docs/tasks/V1-WORKSTATION-SUPPORT-MODE-003.md`。

---

# 前一任务：V1-FULL-HISTORY-DATA-CONTRACT-002

生成时间：2026-07-16

状态：`V1_DATA_CONTRACT_FROZEN`

## 全历史 V1 数据契约冻结

本任务冻结全历史 expected start/end、weekly completed-bar、actual rank=1、derived-from-passed-1m、live/historical 分层、五层状态、消费者准入和 `report_id=14` 只读边界。

实现证据：

- `services/quant-api/app/services/rqdata_ingest/full_history_contract.py`
- `services/quant-api/tests/test_full_history_contract.py`
- `docs/DATA_CENTER.md`
- `docs/tasks/V1-FULL-HISTORY-DATA-CONTRACT-002.md`

边界：本任务未调用 RQData，未写 DB、Parquet、manifest 或 Profile binding，未修改 `data/reports/**`。`V1_DATA_CONTRACT_FROZEN` 不等于 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`；下一步仍是全历史物理事实盘点与 Audit V2。

---

# 前一任务：ALL-BRANCH-WORKTREE-MERGE

生成时间：2026-07-16

状态：`LOCAL_MERGE_COMPLETED_WORKTREES_REMOVED_VALIDATED_WORKSTATION_BASELINE_FIXED`

## 所有本地分支与 worktree 收口

本轮目标是在本地 `main` 上完成受控收口：合并所有尚未进入 `main` 的本地分支，保留 DEMO-004 `.ai` 证据链，验证后删除全部 linked worktree，包括 runtime/live 副本。不 push、不创建 PR、不删除本地分支引用。

保护分支：

```text
backup_branch=codex/backup-main-before-all-worktree-merge-20260716
```

已合并分支：

- `task/demo-20260715-004-github-native-v3-final-acceptance`
- `codex/github-task-resolver-parse-task-meta`

已覆盖分支：

- `codex/ws-gh-013-task-branch-base-validation` 已包含在 DEMO-004 分支历史中，`git merge-base --is-ancestor` 验证返回 0。

本轮保留的关键内容：

- DEMO-004 task 文档、schema / dispatcher / resolver / router test 调整。
- `.ai/results/DEMO-20260715-004-github-native-v3-final-acceptance/` 执行证据。
- `.ai/task-runtime/DEMO-20260715-004-github-native-v3-final-acceptance.json` runtime overlay。
- `codex/github-task-resolver-parse-task-meta` 中优先读取已存在 worktree task 文件的 resolver 与测试逻辑。

已完成 Gate：

1. `git diff --check` 通过。
2. `bash -n scripts/ai/dispatch_task.sh` 通过。
3. `python3 -m pytest -q tests/workstation/test_github_task_resolver.py tests/workstation/test_task_router.py` 通过：`48 passed`。
4. `git branch --no-merged main` 无输出，未发现剩余未合并本地分支。
5. `git worktree remove` / `git worktree prune` 已执行，当前 `git worktree list --porcelain` 仅剩主工程 worktree。

原验证警告（2026-07-16 已修复）：

- `python3 -m pytest -q tests/workstation` 曾为 `447 passed, 21 failed`。
- 对保护分支 `codex/backup-main-before-all-worktree-merge-20260716` 的同命令对照同样为 `447 passed, 21 failed`，说明该全量失败不是本轮合并新增。
- 本轮已修复 baseline 漂移，当前命令通过：`468 passed in 69.09s`。
- `make workstation-test` 当前失败在 strict doctor 的 `branch_not_main: current branch=main`，其余 doctor 项为 `passed=13 failed=1 warn=0 skipped=2`。

本轮追加修复范围：

- 补齐 `tests/workstation` 临时仓库夹具复制的 workstation 脚本与 Python lib 依赖。
- 将 integration routing 场景断言对齐当前 `fast` / `standard` / `critical` tier 语义。
- 修复 dirty / scope gate 内联 Python 写 `__pycache__` 导致 gate 自造未跟踪文件的问题。
- 修复显式 gate 测试被全局 bypass env 影响的问题。
- 修复 model router 降级测试把日志写入真实仓库 `.ai/results/` 的测试隔离问题。

清理结果：

- 已删除 runtime/live 等所有 linked worktree，包括 `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` 与 `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime`。
- 已 prune 两条 prunable 失效 worktree 记录。

---

# 当前任务：DIRECTION-A-MAIN-MERGE

生成时间：2026-07-15

状态：`LOCAL_MERGE_COMPLETED_VALIDATED`

## feature/direction-a1-final-sealing-audit 受控合并

本轮目标是在本地完成 `feature/direction-a1-final-sealing-audit` 到 `main` 的受控 merge commit，使 Git 视为已合并，同时保护当前 `main` 的 workstation/GitHub Native V3、Web A01/A02、cross-file conflict warning 和协作事实源。

合并策略：

- 当前 `main` 为事实源优先；旧分支造成的大规模删除默认拒收。
- Direction A 仅接入 profile registry / active binding / lineage、schema contract、residual root cause audit、multi-primary rulebook、数据 manifest/report evidence。
- 前端/API 只补 `profile_id`、`quality_policy`、`market_data_file_id`、`binding_snapshot` 等 profile 元数据通路。
- 不写 DB、不写 Parquet、不调用 RQData、不 push、不删除分支。

当前分支与保护分支：

```text
backup_branch=codex/backup-main-before-direction-a-merge-20260715
integration_branch=codex/merge-direction-a-final-sealing-main
source_branch=feature/direction-a1-final-sealing-audit
```

已完成 Gate：

1. 清除所有 conflict markers。
2. `git diff --check` 通过。
3. 后端 profile / schema / market reader 重点测试通过。
4. 前端 indicator / barTime / marketChartWindow / mainIndicators / build 通过。
5. 已在集成分支生成 merge commit，并 fast-forward 到本地 `main`。

---

# 当前任务：WEB-MARKET-UX-002

生成时间：2026-07-14

状态：`READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND`

## Web 品种行情页 1d 重复 K 只读诊断

本轮根据 `/Users/zhangzhao/Downloads/归一量化Web品种行情页交互与UI改版执行手册.md` 启动 `WEB-MARKET-UX-V1`。

A01 已通过：

```text
WEB-MARKET-UX-001 GATE_PASSED
```

当前 Step A02 已完成只读诊断：不修改代码、不写 DB、不写 Parquet、不调用 RQData 下载。

当前 Epic 后续顺序：

```text
A01 十字光标与当前 K 数据联动  # GATE_PASSED
→ A02 1d 重复 K 只读诊断       # 完成，未复现重复
→ A03 1d 重复 K 根因修复
→ B01 状态语义与顶部控制区
→ B02 图表主体布局与右侧检查器
→ B03 指标图层、信号 marker 与上下文联动
→ C01 视觉收口、完整回归与独立 Review
```

本步允许范围：

- 只读调用本地 API：`/api/v1/market/bars`
- 只读复用现有 Web normalize / merge helper 做数量对账
- Playwright 只读观察 Web 图表与 Network response
- `docs/tasks/web-market-ux/WEB-MARKET-UX-002.md`
- `.ai/results/WEB-MARKET-UX-002/result.md`
- `tasks/current.md`

本步禁止范围：

- 不修改业务代码。
- 不写 DB、Parquet、manifest、checksum 或 quality status。
- 不调用 RQData 下载。
- 不修复 1d 重复 K 根因；A02 只输出分层证据、最早重复层和 A03 最小修复范围。

当前进展：

- A01 build blocker 已修复，C2 主图指标类型已收口。
- A01 命令线通过：front-end node tests、`npm --prefix apps/quant-web run build`、`git diff --check`。
- A01 Playwright smoke 通过，当前 worktree 使用替代端口 API `8010` / Web `5174`。
- A02 已完成分层只读诊断：Web 实际 `jm.MAIN 1d` 链路在 API、Web normalize、Web merge、图表层均未复现重复 K。
- 额外只读发现：真实合约 `JM2609 1d quote_mode=true` API response 已唯一化为 76 根 K，但 `quality.status=warning` 且 `cross_file_conflicts=10`。

任务记录：

- `docs/tasks/web-market-ux/WEB-MARKET-UX-001.md`
- `.ai/results/WEB-MARKET-UX-001/result.md`
- `docs/tasks/web-market-ux/WEB-MARKET-UX-002.md`
- `.ai/results/WEB-MARKET-UX-002/result.md`

Gate 状态：

```text
WEB-MARKET-UX-001 GATE_PASSED
WEB-MARKET-UX-002 READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND
```

下一步：

1. 暂不进入前端 A03 修复，除非补充 Web 图表重复 K 可复现样本。
2. 若要处理 `JM2609 1d quote_mode=true` 的 `cross_file_conflicts=10`，必须先将 A03 `REPLAN` 为数据事实冲突审查/修复任务。
3. 若后续再次看到重复 K，先记录具体 URL query、重复日期/区间、截图和 Network request URL。
4. 进入下一阶段前建议由浏览器 GPT 复核 A01 diff、A01 smoke 证据和 A02 只读诊断结论。

---

# 前一任务：TASK-2026-07-13-001-DATA-STAGE-CLOSURE-DOC-AUDIT

生成时间：2026-07-13

状态：`DELIVERY_READY_READONLY_DOC_AUDIT`

## 数据阶段收口审计与文档事实源整理

本轮目标是只读审计和文档事实源整理，不写 DB、Parquet、manifest、checksum 或 quality status，不调用 RQData，不删除原始数据，不扩展策略、live、企业微信或自动交易。

输出目录：

```text
data/reports/data_stage_closure/
```

核心产物：

- `asset_inventory.csv`
- `product_period_coverage.csv`
- `contract_role_matrix.csv`
- `manifest_db_consistency.csv`
- `duplicate_or_conflicting_assets.csv`
- `document_inventory.csv`
- `data_stage_closure_summary.md`
- `final_audit/`（本轮复跑的 fail-closed final audit 证据）

当前事实源结论：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

Phase 3 DB 口径（`data/reports/data_layer_final_audit_phase3_20260712/`）现在仅作为旧审计模型历史快照保留，不再作为当前确定下载缺口或批量修复清单：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

本轮 final audit 复跑：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir /Volumes/扩展盘/guiyi-parallel/data-stage-closure-doc-audit/data/reports/data_stage_closure/final_audit
```

结果：`db_snapshot_source=manifest_only`，原因是 PostgreSQL 缺密码且 API snapshot 返回 502；该复跑是环境 Gate 证据，不作为数据完成度唯一口径。

关键边界：

- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论。
- 更新后的数据层封板验收为 `DATA_LAYER_REAUDIT_REQUIRED`。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只代表 manifest 强支持物理历史数据大规模下载，不代表 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 通过。
- 暂停基于旧 `1853 / 34 / 45` 数字的批量修复；下一步先做全历史物理事实盘点与 Audit V2。
- 105 条 `quality_warning` 保持 warning，不升级 passed。
- 当前不能宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- 本轮不授权 Stage 9、企业微信、live runtime、自动交易或实盘。

任务记录：`docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`

GPT 审查包：`docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`

---

# 前一任务：POST-DATA-CLOSURE-GATE-EXECUTION

生成时间：2026-07-12

状态：`DELIVERY_READY_SCHEME_B_AND_READINESS`

## 工作站 V1.5 控制平面

状态：`MERGED_TO_MAIN`（TASK-020/021/022/023 `DELIVERY_READY`）

合并记录：

```text
merge_commit=3898ec964107a54d1d62ed625e6a3688493bd174
merged_at=2026-07-12
branch=main
worktree_removed=/Volumes/扩展盘/guiyi-parallel/workstation-router
main_pytest=50 passed
origin/main=pushed
```

主入口：

```bash
scripts/ai/dispatch_task.sh <TASK_ID> <stage>
# stages: route | plan | dev | fix | test | review | result | pause | resume | cancel | status
make workstation-test   # 在 feature 分支上跑；main 上 strict doctor 会因 branch=main 失败，pytest 50 passed
```

验收文档：`docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md`（历史参考）

## 数据层最终封板 Phase 1 只读审计

状态：`DELIVERY_READY_PHASE1_READONLY_AUDIT`（TASK-2026-07-12-024）

```bash
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --output-dir data/reports/data_layer_final_audit_20260712
```

关键结论（`data/reports/data_layer_final_audit_20260712/DATA_LAYER_FINAL_AUDIT.md`）：

| 指标 | 数值 |
|---|---:|
| covered_passed | 17203 |
| covered_warning | 105 |
| not_applicable | 1943 |
| stage8_6 82/90 | 仍有效 |
| stage8_6 1326/8 pending | 仍有效 |

声明判定摘要：

- 2020+ `1m` 用户声明：`partial`（目标矩阵仅从 2023 起定义）
- 2023+ `1m` 架构口径：`confirmed`
- 2020+ `1d` / `1w`：`confirmed`
- 上市以来至 2019 年末 `1w`：`rejected`（0/63 pre-2020 covered）
- 主连 + 真实主力：`partial`（85/90 main; 1241/1244 actual）

**Phase 1 不宣布最终封板完成**；pre-2020 周线、duplicate active、orphan files 等待 Phase 2。

证据：`docs/tasks/TASK-2026-07-12-024-data-layer-final-audit-phase1.md`

## 数据层 Phase 2 补齐 + Phase 3 最终验收

状态：历史快照（TASK-025/026）

```text
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 当时未达成
DATA_LAYER_PARTIAL                           # 旧状态标签，已由 A2-01 纠偏为 DATA_LAYER_REAUDIT_REQUIRED
```

Phase 2 已完成：

- duplicate active supersede + widest re-elect：`duplicate_active_rows=0`
- orphan 8 文件登记：`orphan_file_rows=0`
- pre-2020 周线 63 品种 backfill+register

Phase 3 审计（`data/reports/data_layer_final_audit_phase3_20260712/`）：

| 指标 | 数值 |
|---|---:|
| duplicate_active_rows | 0 |
| orphan_file_rows | 0 |
| weekly_pre2020_missing | 34 |
| covered_passed | 15350 |
| metadata_gap | 1853 |
| dominant_main_passed | 0/90（manifest 漂移） |

旧阻塞项写法：manifest/DB 对齐、34 品种 pre-2020 周线、actual 45 条缺口。A2-01 后这些数字保留为旧审计模型历史快照，暂停直接批量修复，等待 Audit V2 重算真实 residual。

验收：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`

## 数据内容审计 worktree 收口

状态：`MERGED_TO_MAIN`（TASK-2026-07-11-001 ~ 012 + DATA-PART-TARGET-CLOSURE `DELIVERY_READY`）

合并记录：

```text
merge_commit=8ab908ddad12aadcbe13c2aa493af0a117d5bd2f
merged_at=2026-07-11
branch=main
worktree_removed=/Volumes/扩展盘/guiyi-parallel/data-audit
后续数据审计只在主工程 /Volumes/扩展盘/guiyi-quant-workstation 继续
origin/main=pushed
```

## 前置完成

数据部分：

```text
DATA-PART-TARGET-CLOSURE DELIVERY_READY
```

Target coverage final：

```text
covered_passed=17203
covered_warning=105
metadata_gap=0
not_applicable=273
issue_register_rows=105
quality_warning=105
```

## 本轮 Cursor 执行结果

| Step | 任务 | 状态 |
|---|---|---|
| 1 | TASK-017 Phase 1 dry-run / readiness | `DELIVERY_READY_READONLY_GATE` |
| 2 | TASK-018 方案 B 本机磁盘 runtime 迁移 | `DELIVERY_READY_SCHEME_B_MIGRATION` |
| 3 | TASK-017 T3 runtime 副本 smoke（非交易时段） | `T3_CLOCK_IDLE_NON_TRADING` |
| 4 | report_id=14 trust audit 基线复现 | `DELIVERY_READY_READONLY_AUDIT` |
| 5 | OOS frozen config + CLI | `DELIVERY_READY_OOS_CLI_NO_DB_WRITE` |
| 6 | GPT 同步包刷新 | `DELIVERY_READY_DOC_SYNC` |

## 监督服务与 runtime root

```text
supervised_runtime_root=~/GuiyiRuntime/guiyi-quant-workstation-runtime
branch=ops/local-runtime-disk
dev-healthcheck=passed
post-reboot-verify=passed
```

旧 parallel 绑定 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` 已 bootout。

当前可标记：

```text
SUPERVISOR_BASE_HEALTH_PASSED
SCHEME_B_MIGRATION_PASSED
POST_DATA_CLOSURE_PHASE1_DRY_RUN_PASSED
T3_RUNTIME_COPY_SMOKE_IDLE_NON_TRADING
```

不可标记：

```text
T3_REAL_PASSED
JM_RUNTIME_READY
LONG_RUNNING_READY
```

## T3-real 待 Gate

- 需 JM 可交易时段。
- 需用户显式确认 Phase 2 真实 live 写入。
- 执行位置：`~/GuiyiRuntime/guiyi-quant-workstation-runtime`。
- 证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §11–§12。

## OOS 验证

- 基线：`scripts/backtest_trust_audit.py --report-id 14` → audit_status passed。
- 执行 CLI：`scripts/oos_validation_run.py` + `configs/oos/jm_v1b_report14_frozen.json`。
- 默认 `persist_to_db=false`；样本外窗口 `oos_fixed` 已试跑（32 trades，临时报告见 `data/reports/oos_validation_*`）。
- 全窗口批量执行需另开 Codex 任务；不得调参改善收益。

## 关键产出

- `docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`（§11–§12 更新）

## 不授权事项

- Stage 9、企业微信、formal event、自动交易
- live scheduler 长期开启
- 105 条 warning 升级为 passed
- 修改 DB schema / Parquet / manifest / quality report
- 打印或提交凭据

## 下一步建议

1. P0：JM 可交易时段 + 用户确认 → T3-real `--once`（TASK-017 Phase 2/3）。
2. P1：OOS 全窗口批量跑 `--run`（不入库）并外部审查。
3. P1：5 交易日长稳 + kill/recovery → 才可评估 `LONG_RUNNING_READY`。
4. P2：真实服务器安全 smoke（Nginx/FRP/401）。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md`（历史参考）
- `docs/workstation/ARCHITECTURE.md`
- `docs/tasks/TASK-2026-07-12-020` ~ `023`（工作站 V1.5 控制平面）
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `docs/tasks/TASK-2026-07-12-014` ~ `019`
- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
