# 任务契约归档索引（INDEX）

> **这是历史任务归档，不是当前工作。** 本目录下所有文档为已完成 / 已收口 / 已被取代的历史任务契约，仅作证据与追溯保留，正文未改动（移动时仅用 `git mv` 保留 Git 历史）。
>
> **当前仍在推进的活跃任务**见 `docs/tasks/`（根目录）；**项目当前状态与未关闭 Gate** 以 `STATUS.md` 为准，历史叙事见 `STATUS_ARCHIVE.md`。
>
> 归档不改变任何已冻结结论：report 14/15、task 23 冻结项、S6-07 recovery、各类 receipt/hash 一律以原文为准。

---

## 1. Cursor Wave（指标/策略验证协议基础）

- `CURSOR-CANONICAL-SYNC-C001.md` — canonical 同步准备，`CURSOR_CANONICAL_SYNC_PREPARED`，已收口。
- `CURSOR-INDICATOR-CALLER-INVENTORY-C401.md` — 指标调用方盘点，`CURSOR_INDICATOR_CALLERS_AUDITED`，已收口。
- `CURSOR-INDICATOR-REGISTRY-C402.md` — 指标 Registry v1，`INDICATOR_REGISTRY_V1_READY`，已收口。
- `CURSOR-FIRST-FORMAL-CALLER-C403.md` — 首个正式调用方评估，`NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED`，已收口。
- `CURSOR-STRATEGY-INDICATOR-POLICY-C404.md` — 策略/指标 policy，`STRATEGY_INDICATOR_POLICY_READY`，已收口。
- `CURSOR-HTDY-FORMAL-PREFLIGHT-C405.md` — HTDY 正式化预检，`CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED`，已收口。
- `CURSOR-INDICATOR-CALLER-INVENTORY-C401.md` / `CURSOR-HTDY-VALIDATION-PROTOCOL-C501.md` — 验证协议冻结，`STRATEGY_VALIDATION_PROTOCOL_FROZEN`，已收口。
- `CURSOR-REVIEW-FOUNDATION-C506A.md` — 复盘基础，`CURSOR_REVIEW_FOUNDATION_PREPARED`，已收口。
- `CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A.md` — runtime observation 基础，`CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED`，已收口。
- `CURSOR-SWITCH-GATE-REVIEW-S001.md` — 切换 Gate 评审，已收口。
- `CURSOR-WAVE-INDEPENDENT-REVIEW-X001.md` — 独立评审波次，已收口。
- `CURSOR-WAVE-HANDOFF-C999.md` — Cursor→Codex 波次交接，`CURSOR_WAVE_READY_FOR_CODEX_REVIEW`，已收口。

## 2. 数据层最终审计 / Direction A / 全历史治理

- `DATA-LAYER-FINAL-ACCEPTANCE.md` — 数据层最终验收，data Gate 收口（后续 residual 独立处理）。
- `DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md` — 数据部分目标收口，`DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
- `DATA-PROFILE-FULL-HISTORY-RULES-007.md` — 全历史 Profile 规则，已收口。
- `DATA-PROFILE-ROLLOUT-APPLY-008B.md` — Profile rollout apply，已收口。
- `DIRECTION-A-FINAL-ACCEPTANCE.md` — Direction A 最终验收，已收口。
- `DIRECTION-A1-FINAL-DATA-SEALING-AUDIT.md` — 数据封存审计（A1），已收口。
- `DIRECTION-A2-A4-A5-FULL-PROFILE-BINDING-ROLLOUT.md` — 全量 Profile binding rollout，已收口。
- `DIRECTION-A2-A5-PROFILE-REGISTRY-CORRECTNESS.md` — Profile Registry 正确性（A2–A5），已收口。
- `DIRECTION-A3-DATA-CONTRACT-AND-RESIDUAL-ROOT-CAUSE.md` — 数据契约与 residual 根因（A3），已收口；residual triage 仍以 `STATUS.md` 与根目录 `V1-DATA-REAUDIT-STATUS-001.md` 为准。
- `FULL-HISTORY-PHYSICAL-INVENTORY-001.md` — 全历史物理盘点，`FULL_HISTORY_PHYSICAL_INVENTORY_READY`。
- `FULL-HISTORY-AUDIT-V2-PREFLIGHT-000.md` — Audit V2 预检，已收口。
- `FULL-HISTORY-AUDIT-V2-ENGINE-002.md` — Audit V2 动态矩阵引擎，`FULL_HISTORY_AUDIT_V2_READY`。
- `FULL-HISTORY-AUDIT-V2-RUN-003.md` — Audit V2 只读复跑，已收口（residual 仍 `DATA_LAYER_REAUDIT_REQUIRED`）。
- `FULL-HISTORY-RESIDUAL-REPAIR-004B.md` — 全历史 residual 修复，已收口。
- `FULL-HISTORY-DERIVED-PERIODS-005.md` — 派生周期，已收口。
- `ACTUAL-DOMINANT-ROLL-V2-006.md` — 实际主力换月 v2，已收口。
- `CONSUMER-CONTRACT-FINAL-CLOSEOUT-006.md` — 消费者契约最终收口，`CONSUMER_DATA_CONTRACT_READY`。
- `B-01-DIRECT-DB-FINAL-BASELINE-AUDIT.md` — direct DB 基线审计（B-01），已收口。
- `MARKET-INDICATOR-DUAL-MODE-004.md` — Market/Indicator 双模式契约，已收口。
- `V1-FULL-HISTORY-DATA-CONTRACT-002.md` — V1 全历史数据契约，`V1_DATA_CONTRACT_FROZEN`。

## 3. HTDY 阶段 4/5 可信验证

- `INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406.md` — 指标契约验收修正，`INDICATOR_CONTRACT_READY / STAGE4_COMPLETED`。
- `HTDY-TRUSTED-REPORT-APPLY-PACKET-X502.md` — 可信报告 apply packet，已收口。
- `HTDY-TRUSTED-BACKTEST-CANDIDATE-X503.md` — 可信回测候选，已收口。
- `HTDY-OOS-VALIDATION-X504.md` — OOS 验证，已收口。
- `HTDY-ROLLING-OOS-X505.md` — 滚动 OOS，已收口。
- `HTDY-STRATEGY-REVIEW-CLOSED-LOOP-X506B.md` — 策略复盘闭环，已收口。
- `HTDY-STAGE5-ACCEPTANCE-X507.md` — 阶段 5 验收，已收口。
- `HTDY-FROZEN-DATA-IDENTITY-DRIFT-TRIAGE-R4501A.md` — 冻结数据身份漂移 triage，已收口。
- `HTDY-FROZEN-DATA-WINDOW-EQUIVALENCE-R4501B.md` — 冻结数据窗口等价，`HTDY_FROZEN_DATA_WINDOW_EQUIVALENT`。
- `TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502.md` — 样本末清算语义，已收口。
- `TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503.md` — 滚动 OOS 决策语义，已收口。
- `TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504.md` — 阶段 5 验收 v2，`STAGE5_CLOSEOUT_V2_READY`。
- `TASK-STAGE45-FINAL-ACCEPTANCE-R4505.md` — 阶段 4/5 最终验收，`STAGE5_COMPLETED / READY_TO_ENTER_STAGE6`。
- `HTDY-STAGE45-CONTRACT-CLOSEOUT-R45.md` — 阶段 4/5 合同收口，HTDY 定为 `REJECTED_RESEARCH_CANDIDATE`（可信管道淘汰当前候选，不得翻转）。

## 4. JM Stage 6 主线（历史增量 / T3 / T4 / EOD）

- `JM-HISTORICAL-CATCHUP-FOUNDATION-S6-02.md` — 历史 catch-up 基础（S6-02），已收口。
- `JM-HISTORICAL-CATCHUP-S6-03.md` — 历史 catch-up（S6-03），`JM_HISTORICAL_CATCHUP_READY`。
- `JM-LIVE-CONTEXT-S6-04.md` — 历史/实时上下文（S6-04），`JM_LIVE_CONTEXT_READY`。
- `JM-LIVE-T3-S6-05.md` — T3 单次真实 live Gate（S6-05），`T3_REAL_PASSED`。
- `JM-AFTER-MARKET-ARCHIVE-S6-06.md` — T4 盘后归档（S6-06），`JM_ARCHIVE_PASSED`。
- `JM-EOD-INCREMENTAL-AUTOMATION-S6-07.md` — EOD 增量自动化（S6-07），`JM_EOD_INCREMENTAL_AUTOMATION_READY`（不代表 Runtime/长稳/通知/交易 Ready）。
- `JM-LIVE-GATE-EVIDENCE.md` — T1/T3 早期真实 Gate 证据账本，Historical Snapshot / Superseded。

## 5. TASK-2026-07-*（数据层 / Web / live 计划与修复）

- `TASK-2026-07-10-004-web-visual-refactor-v1b.md` — Web 视觉重构 v1b，已收口。
- `TASK-2026-07-11-001-data-asset-audit.md` — 数据资产审计，已收口。
- `TASK-2026-07-11-002-data-target-coverage-audit.md` — 目标覆盖审计，已收口。
- `TASK-2026-07-11-002-htdy-indicator-core.md` — HTDY 指标核心，已收口。
- `TASK-2026-07-11-003-web-main-indicators.md` / `TASK-2026-07-11-003-web-overlay-indicators.md` — Web 主图/叠加指标，已收口。
- `TASK-2026-07-11-004-jm-live-runtime-gate.md` — JM live runtime gate 计划，已收口（现以 STATUS + S6 系列为准）。
- `TASK-2026-07-11-005-target-coverage-gap-triage.md` — 覆盖缺口 triage，已收口。
- `TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile.md` / `-002-...-metadata-row-count-repair.md` — 周线行数/元数据对账修复，已收口。
- `TASK-2026-07-12-003-residual-data-risk-disposition.md` — residual 数据风险处置，已收口。
- `TASK-2026-07-12-004-source-interval-provenance-repair-dry-run.md` / `-005-...-apply.md` — source/interval provenance 修复（dry-run + apply），已收口。
- `TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run.md` — LPV 实际合约登记 dry-run，已收口。
- `TASK-2026-07-12-007-residual-data-risk-closeout-dry-run.md` — residual 风险收口 dry-run，已收口。
- `TASK-2026-07-12-008-reference-metadata-gap-apply-plan.md` / `-009-...-apply.md` — 参考元数据缺口 apply，已收口。
- `TASK-2026-07-12-010-quality-warning-consumption-boundary.md` — quality warning 消费边界，已收口（strict 入口仅 passed）。
- `TASK-2026-07-12-012-stage8-6-pending-reconcile.md` — Stage 8.6 pending 对账，已收口。
- `TASK-2026-07-12-015-supervisor-service-gate.md` — supervisor service gate，已收口。
- `TASK-2026-07-12-016-oos-validation-plan.md` — OOS 验证计划，已收口。
- `TASK-2026-07-12-017-jm-single-live-gate-plan.md` — JM 单次 live gate 计划，已收口。
- `TASK-2026-07-12-018-macos-long-running-plan.md` — macOS 长稳计划，已收口（长稳仍以 S6-10 为准）。
- `TASK-2026-07-12-019-macos-scheme-b-migration-impl.md` — macOS 方案 B 迁移实现，已收口。
- `TASK-2026-07-12-024-data-layer-final-audit-phase1.md` / `-025-...-phase2-remediation.md` / `-026-...-phase3-final-acceptance.md` — 数据层最终审计三阶段，已收口（最终以 `DATA-LAYER-FINAL-ACCEPTANCE.md` 为准）。
- `TASK-2026-07-13-001-data-stage-closure-doc-audit.md` — 数据阶段收口文档审计，已收口。

## 6. V1-HTDY 实时集成 Step 0–3 / V1 收口

- `V1-HTDY-00-INTEGRATION-AND-CONTRACT-FREEZE.md` — Step 0 合同冻结，`HTDY_REALTIME_EXCEPTION_CONTRACT_FROZEN / OLD_S6_08_AUTHORIZATION_REVOKED`。
- `V1-HTDY-01-PRODUCTION-KERNEL-AND-POLICY.md` — Step 1 production kernel/policy，`HTDY_ORIGINAL_PRODUCTION_KERNEL_READY / HTDY_REALTIME_REPAINTING_POLICY_READY`。
- `V1-HTDY-02-REALTIME-SNAPSHOT-AND-EVALUATOR.md` — Step 2 只读 snapshot/evaluator，`HTDY_REALTIME_15M_SNAPSHOT_READY / HTDY_FIRST_SEEN_CANDIDATE_EVALUATOR_READY`。
- `V1-HTDY-03-FIRST-SEEN-EVENT-LEDGER.md` — Step 3 first-seen writer/lineage v2，`HTDY_FIRST_SEEN_EVENT_WRITER_READY / HTDY_SIGNAL_REVIEW_LINEAGE_V2_READY`（未接 Runtime）。
- `V1-NEXT-WAVE-FACT-SYNC-000.md` — 下一波事实同步基线，已收口。
- `V1-TRUSTED-CLOSURE-ACCEPTANCE.md` — V1 可信收口验收，已收口。
- `V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md` — V1 live runtime 收口验收，已收口（长期 Runtime/长稳仍 pending，见根目录 S6-10）。

## 7. WEB-V1-*（前端交付）

- `WEB-V1-00-INVENTORY.md` — 前端盘点，已收口。
- `WEB-V1-01-GLOBAL-FOUNDATION.md` — 全局基础，已收口。
- `WEB-V1-02-DATA-CENTER.md` … `WEB-V1-11-E2E.md` — 数据中心 / 行情 / 实时观察 / 策略 / 回测 / 批量 / 信号 / 复盘 / Runtime / E2E 各页面交付，`WEB_V1_READY / WEB_V1_BROWSER_ACCEPTANCE_PASSED`。
- `WEB-V1-12B-REMEDIATION.md` — WEB-V1-12 修复，历史 Gate 保留。
- `WEB-V1-13-FINAL-ACCEPTANCE.md` / `WEB-V1-13-PERSONAL-WORKSPACE-CLOSURE.md` / `WEB-V1-13-W13-01..06-*.md` — 个人工作台收口与品牌/壳/仪表盘/行情/研究回路/质量分课，`WEB_V1_13_PARTIAL`（真实关联样本缺口未闭合）。
- `WEB-V1-14-00-BASELINE-AND-COLLISION-AUDIT.md` / `WEB-V1-14-JM-1D-DIAGNOSIS.md` / `WEB-V1-14-FINAL-ACCEPTANCE.md` — 研究工作台 polish 与 JM 1D 诊断，`WEB_V1_RESEARCH_WORKSPACE_POLISHED`。
- `WEB-V1-FINAL-ACCEPTANCE.md` — Web V1 最终验收，历史 Gate 保留。
- `WEB-HTDY-ORIGINAL-OBSERVATION-W4501.md` — HTDY 原版 observation-only 前端呈现，已收口。

## 8. web-market-ux/（行情页 UX 子专题）

- `web-market-ux/WEB-MARKET-UX-001.md` / `WEB-MARKET-UX-002.md` — 行情页 UX 迭代，已收口。
