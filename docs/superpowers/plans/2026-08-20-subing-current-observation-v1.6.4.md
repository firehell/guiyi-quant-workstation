# SuBing Current Observation Seam + v1.6.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan sequentially. Use `superpowers:test-driven-development` for every behavior change and one independent reviewer before release.

**Goal:** 修复 SuBing current-read 的 Canonical/Live seam 与 Web error fallback，修复 fresh-root Runtime activation 顺序，并把已验证的完整 `develop` 作为 v1.6.4 发布和部署。

**Architecture:** `SubingReadService` 继续独占 SuBing 私有编排：先读取每个频率的 `MarketReadState.canonical_end`，只在 current cutoff 已到达 Canonical edge 时使用 latest-page bootstrap；历史 cutoff 与并发发布竞态继续落回 strict cursor。Web 只在 SuBing 请求明确失败后保留基础 K 线。Runtime installer 在服务启动前原子建立 activation marker，并在失败时恢复调用前状态。

**Tech Stack:** Python 3.13、FastAPI、MarketDataService、pytest、Vue 3/TypeScript、Playwright、macOS launchd。

**Spec:** `docs/superpowers/specs/2026-08-20-subing-current-observation-canonical-live-seam-fix-design.md`

## Global Constraints

- 不修改 `MarketDataService` strict cursor/coverage 合同、Canonical/Catalog/Redis 模型、SuBing Factor/Signal/Lifecycle 公式或 Alert Rule/Scope。
- 不执行 migration、RQData/Canonical/生产 DB 写入、历史 Event 补发、手工通知或订单操作。
- v1.6.4 发布范围为修复完成后的完整 `develop`；research-only 资产不因此获得效果、盈利或晋升结论。
- Alert 持续边界固定为 `htdy_original_15m × jm × htdy_observers × PushPlus Topic` 与 `subing_entry_signal_v1 × jm × owner × PushPlus`。

---

### Task 1: Baseline and Spec

- [x] 在 clean/synced `origin/develop` 创建隔离 task worktree。
- [x] 更新 spec 的 develop/production 基线、Canonical 并发发布合同和真实 `MarketDataService` RED 要求。
- [x] 运行现有 SuBing/API 与 installer focused tests，确认基线为绿。

### Task 2: Backend RED -> GREEN

- [x] 用临时 Catalog/Parquet 与真实 `MarketDataService` 写 5m/15m RED；旧代码必须精确失败为 `DATASET_OR_PARTITION_MISSING`。
- [x] 让 5m/15m 各自依据 `MarketReadState.canonical_end` 选择 `before=None` 或 `cutoff+1us`。
- [x] latest page 若在 state 之后推进到 cutoff 之后，改用 strict cursor 重读。
- [x] 放宽的只有第一页 null cursor pagination validation；所有后续 cursor/identity/continuity 检查保持严格。
- [x] 覆盖 Lifecycle enabled/disabled、future leakage、asymmetric edge 与真实缺口。

### Task 3: Web and Installer RED -> GREEN

- [x] Web E2E 先证明 SuBing 503 会把已加载 bars 清空，再改为仅 error 后保留基础 bars；loading 与 canLoadEarlier 不变。
- [x] installer engineering test 先证明 kickstart 发生时 marker 不存在，再将 marker 原子写入移动到启动前。
- [x] 模拟 launchctl 失败并证明 marker 恢复调用前 absent/existing 状态；Market/Alert 模式互不污染。

### Task 4: Verification and Review

- [x] 运行 SuBing、Alert、engineering、全 backend、Ruff、Mypy、Web unit、完整 Playwright、build、shell/plist、OpenSpec、secret scan 与 diff check。
- [ ] 一名独立 reviewer 审查 spec、未来泄漏、installer rollback 与完整 release diff；Critical/Important 必须为 0。
- [ ] 合入并 push `develop`，读回 exact remote SHA。

### Task 5: v1.6.4 Release and Runtime

- [ ] 从 exact `origin/develop` 创建 release worktree，更新所有 version surfaces、CHANGELOG/README/STATUS/TESTING 后重跑 release verification。
- [ ] Release PR 合入 `main`，创建并 push annotated `v1.6.4`，读回 tag object、peeled commit、`origin/main`；再同步 develop。
- [ ] 创建 clean/detached exact-tag Runtime，锁定依赖、build、test、render-only，再单次执行 base -> Market -> Alert switch。
- [ ] 读回五服务 exact root/commit、API/Web/Runtime、DB head、60 品种、两个 exact Scope、PushPlus transport 和无意外 notification attempt。

### Task 6: Fail-Closed Cleanup and Closeout

- [ ] 删除前扫描 launchd/plist/PID/open files，确认无正式服务引用目标根。
- [ ] 仅用 `git worktree remove` 删除 v1.6.3 release worktree、v1.6.2 Runtime 和本次临时 worktree；保留 v1.6.3 Runtime 回滚源。
- [ ] 更新 STATUS，push develop，并读回最终 remote SHA；自然 SuBing/HTDY/after-market 验收保持真实 pending 状态。
