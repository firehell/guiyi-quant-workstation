# N Structure 与 Multi-Candidate Robustness 退役 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从归一量化 active repository surface 中完整删除 N Structure 与专用于 SuBing↔N 比较的 Multi-Candidate Robustness，同时保持当前 SuBing Strategy Stage 2、SuBing Candidate Validation、HTDY、Market、Alert 与 production Runtime 语义不变。

**Architecture:** 按 approved Spec 的“consumer 从外向内收敛”顺序执行：先移除 Web 用户入口和渲染状态，再移除 HTTP/CLI public seam，再断开 research composition，随后删除 Multi-Candidate Robustness、N Candidate/policy/protocol 与 N Structure core。最后收敛 canonical/doc，并用 retained SuBing Stage 2 全链路回归和 active-reference scan 证明这只是 repository retirement，不是策略公式、Runtime、DB 或通知变更。

**Tech Stack:** Python 3.13+, FastAPI/Pydantic, frozen dataclasses, `Decimal`, Vue 3/Vite/TypeScript/Naive UI/Lightweight Charts, pytest, Ruff, Mypy, Node test runner, Playwright, pnpm.

**Spec:** [`../specs/2026-08-27-retire-n-structure-design.md`](../specs/2026-08-27-retire-n-structure-design.md)

**Planning base:** `develop@3e8800c83b26e994fead262e47beee70f55db29c`（PR `#236` 已把 SuBing Strategy V1 Stage 2 合入 `develop`）。执行时必须从 then-latest `origin/develop` 创建 task worktree，并证明本 planning base 是其祖先。

## Global Constraints

- 本任务是 **Lane 2 跨模块退役/收敛**。不修改策略公式，但横跨 Web、API、CLI、Research、Candidate、canonical，使用 **Sol + 高推理**。
- 这是 deletion/refactor，不建立 archive、backup、legacy、disabled implementation、compatibility wrapper 或“以后可能用”的 generic shell；恢复只依赖 Git history + 新任务。
- 完整删除 `services/quant-api/app/research/n_structure/`、`services/quant-api/app/research/robustness/` 及 N/Multi-Candidate 的 policy/candidate/protocol active assets。
- 完整删除 `GET /api/v1/market/research/n-structure/bands` 与 `guiyi research n-structure`；不能改成 410、feature-disabled 或兼容 reader。
- 完整删除 Web “N字区间”开关、API client、types、composable、primitive、Kline render/hover/overlap/diagnostics 和 active preference state。
- Main chart preference 从 v6 升到 v7；v7 只保留 `selectedOverlay`、optional EMA、`showSubingInternalProcess`、`period`、`realtimeFollow`；v6 迁移只复制这些 retained 字段。
- 不创建 single-candidate robustness；SuBing Candidate Validation 与 SuBing prospective OOS 保留原 manifest/protocol/service。
- **禁止删除或改写** `services/quant-api/app/market_data/subing_structure.py`。它是 SuBing 自己的 confirmed Pivot/breakout/retest，不属于 N Structure。
- **禁止改变当前 Stage 2 语义**：Historical 与 completed-Live 继续共享同一个增量 Strategy machine；公开身份保持 `actual_dominant + 15m`；1m/5m 仅为内部权威输入；普通 Action 继续绑定下一实际同物理合约 15m 区间第一根 completed 1m 的 open。
- 不修改 `services/quant-api/alembic/versions/20260826_0042_subing_strategy_alert.py`，不执行 migration，不修改 Alert Rule/Scope/audience/transport，不发送真实通知，不写 production PostgreSQL/Redis/Canonical，不下载 RQData。
- 不发布 `main`、不创建 tag/GitHub Release、不做 Runtime promotion。release 与 Runtime promotion 仍是独立人工 Gate。
- `STATUS.md` 必须区分 repository code 与 production `v1.8.6 + migration 0041`。production 仍可包含 N Structure Historical layer，直到未来独立 release + Runtime promotion 完成。
- 当前 `develop` 有一处已验证的 canonical drift：PR `#236` 已合入 `develop`，但 `STATUS.md` 仍写 Stage 2 “仅存在于 feature branch / 允许集成 develop pending”。Task 0 必须先修正这一 repository-state 事实；不得借此改变 production 事实。
- Approved Spec 写于 Stage 2 merge 之前；若 Spec 对“retained SuBing 行为”的简写与当前 `PROJECT_SOURCE.md`、`DECISIONS.md`、Stage 2 code/tests 冲突，**当前 active canonical + code/test facts 优先**。本 retirement 不得把 Stage 2 回退成 Stage 1。

---

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话；实现完成后新开独立 Review 会话
- Plan：Plan-then-execute
- 工作区：从 then-latest `origin/develop` 创建新 task branch/worktree
- Task branch：`refactor/retire-n-structure`
- 集成目标：`develop`
- 自动 task → `develop`：允许，但仅限全部测试/CI 通过、独立 exact-head Review 无阻塞项、范围未扩大之后
- PR：需要
- 人工 Gate：Plan 批准；release / Runtime promotion 仍另行批准
- 禁止工作区：`main` worktree、detached Runtime worktree

Worktree lifecycle：

```text
latest origin/develop
→ refactor/retire-n-structure task worktree
→ implementation PR to develop
→ independent exact-head Review
→ tests + CI + review green
→ merge develop
→ verify merge commit contains task head
→ remove task worktree and merged task branch

not in this task:
develop → main/tag/release
release/tag → Runtime promotion
```

---

## Target File Map

### Delete — backend N Structure

```text
services/quant-api/app/research/n_structure/__init__.py
services/quant-api/app/research/n_structure/n_candidate_validation.py
services/quant-api/app/research/n_structure/n_candidate_validation_policy.py
services/quant-api/app/research/n_structure/n_candidate_validation_service.py
services/quant-api/app/research/n_structure/n_structure_pattern.py
services/quant-api/app/research/n_structure/n_structure_policy.py
services/quant-api/app/research/n_structure/n_structure_research_service.py
services/quant-api/app/research/n_structure/n_structure_segment.py
services/quant-api/app/research/n_structure/n_structure_state.py
services/quant-api/app/research/n_structure/n_structure_swing.py
```

### Delete — Multi-Candidate Robustness

```text
services/quant-api/app/research/robustness/__init__.py
services/quant-api/app/research/robustness/multi_candidate_events.py
services/quant-api/app/research/robustness/multi_candidate_robustness.py
services/quant-api/app/research/robustness/multi_candidate_robustness_policy.py
services/quant-api/app/research/robustness/multi_candidate_robustness_service.py
```

### Delete — frozen N/Multi assets

```text
data/research_policies/n_structure_5m_v1.json
data/research_candidates/n_structure_5m_candidate_v1.json
data/research_protocols/n_structure_validation_v1.json
data/research_protocols/multi_candidate_robustness_v1.json
```

Retain exactly:

```text
data/research_candidates/subing_lifecycle_v2_candidate_v1.json
data/research_protocols/candidate_validation_v1.json
services/quant-api/app/research/subing/candidate_validation.py
services/quant-api/app/research/subing/candidate_validation_policy.py
services/quant-api/app/research/subing/subing_candidate_validation_service.py
```

### Delete — N-only HTTP/Web implementation

```text
services/quant-api/app/research/historical_overlay_api.py
apps/quant-web/src/composables/useNStructureBands.ts
apps/quant-web/src/components/kline/NStructureBandPrimitive.ts
apps/quant-web/tests/nStructureBands.test.ts
apps/quant-web/tests/nStructureBandPrimitive.test.ts
```

### Modify — shared backend seams

```text
services/quant-api/app/main.py
services/quant-api/app/schemas/research_overlays.py
services/quant-api/app/research/composition.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_requests.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/research_payloads.py
services/quant-api/tests/test_market_research_overlays_api.py
services/quant-api/tests/test_research_composition.py
services/quant-api/tests/test_research_cli_boundaries.py
services/quant-api/tests/research/test_research_cli_parser_requests.py
services/quant-api/tests/research/research_cli_fixtures.py
tests/engineering/test_canonical_consistency.py
```

### Modify — shared Web seams

```text
apps/quant-web/src/api/market.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/utils/mainIndicators.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/tests/mainIndicators.test.ts
apps/quant-web/tests/marketOverlayConvergence.test.ts
apps/quant-web/e2e/market-research.spec.mjs
```

### Delete — N/Multi tests

```text
services/quant-api/tests/test_n_structure_*.py
services/quant-api/tests/test_n_candidate_validation*.py
services/quant-api/tests/research/test_n_structure_research_service.py
services/quant-api/tests/research/test_n_candidate_validation_service.py
services/quant-api/tests/test_multi_candidate_events.py
services/quant-api/tests/test_multi_candidate_robustness.py
services/quant-api/tests/test_multi_candidate_robustness_policy.py
services/quant-api/tests/research/test_multi_candidate_robustness_service.py
```

The shell globs above are intentional: before `git rm`, Task 0 records the exact tracked files matched by each glob. If a matched file contains retained SuBing/HTDY behavior rather than N/Multi-only tests, stop and classify it instead of deleting it.

### Modify — canonical/docs

```text
STATUS.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
TESTING.md
```

Do not modify Stage 2 Strategy/Alert implementation solely because these files are nearby:

```text
services/quant-api/app/market_data/subing_structure.py
services/quant-api/app/market_data/subing_strategy/**
services/quant-api/app/alerts/**
services/quant-api/alembic/versions/20260826_0042_subing_strategy_alert.py
apps/quant-web/src/composables/useSubingStrategyCurrent.ts
apps/quant-web/src/composables/useCurrentStrategyActions.ts
apps/quant-web/src/components/market/SubingStrategyRecords.vue
```

---

## Dependency Order

```text
Task 0  isolated workspace + canonical drift correction + pre-change baseline
  ↓
Task 1  retire Web N surface + preference v7
  ↓
Task 2  retire HTTP + research CLI public surface
  ↓
Task 3  remove research composition wiring + Multi-Candidate Robustness
  ↓
Task 4  remove N Candidate/policy/protocol/core + N-only tests
  ↓
Task 5  converge canonical/docs without changing production claims
  ↓
Task 6  full retained regression + active-reference scan
  ↓
Task 7  independent exact-head Review + PR/CI + develop integration/cleanup
```

---

### Task 0: Create the isolated workspace, correct the Stage 2 repository-state drift, and capture a deletion baseline

**Files:**
- Modify only if still stale: `STATUS.md`
- No business-code changes.

**Interfaces:**
- Consumes: approved Spec and latest `origin/develop` containing planning base `3e8800c83b26e994fead262e47beee70f55db29c`.
- Produces: clean task worktree, verified retained Stage 2 baseline, exact tracked deletion inventory, truthful repository-vs-production status.

- [ ] **Step 1: Fetch and prove the planning base is contained in current develop.**

```bash
git fetch origin
git merge-base --is-ancestor \
  3e8800c83b26e994fead262e47beee70f55db29c \
  origin/develop
git show --stat --oneline origin/develop
git status --short
```

Expected: `merge-base` exits `0`; no assumption that `origin/develop` is still exactly `3e8800c`.

- [ ] **Step 2: Create the isolated task worktree from current `origin/develop`.**

```bash
git worktree add ../guiyi-retire-n-structure \
  -b refactor/retire-n-structure \
  origin/develop
cd ../guiyi-retire-n-structure
git status --short
git rev-parse HEAD
```

Expected: clean status; do not use `main` or Runtime worktrees.

- [ ] **Step 3: Re-read active canonical and approved Spec before mutation.**

```bash
sed -n '1,240p' STATUS.md
sed -n '1,260p' AGENTS.md
sed -n '1,220p' docs/DEVELOPMENT.md
sed -n '1,260p' PROJECT_SOURCE.md
sed -n '1,260p' DECISIONS.md
sed -n '1,260p' docs/ARCHITECTURE.md
sed -n '1,520p' \
  docs/superpowers/specs/2026-08-27-retire-n-structure-design.md
```

Stop if a new canonical introduces an N consumer, production persistence contract, or strategy dependency not covered by the Spec.

- [ ] **Step 4: Correct only the verified Stage 2 repository-state drift if it still exists.**

First detect it:

```bash
git grep -n -E \
  'Stage 2 仅存在于|允许集成 develop.*pending|feature/subing-strategy-v1-stage2-v1.8.7' \
  -- STATUS.md
```

On the planning base, `STATUS.md` is stale because PR `#236` is already merged into `develop`. Replace only that repository-state claim with wording equivalent to:

```text
Repository Stage 2：PR #236 已合入 develop；当前 repository code 包含 Stage 2。
Production：仍是 v1.8.6 + migration 0041；0042 未执行；未 release、未 Runtime promotion。
```

Do **not** change the current production Rule identity, database version, Runtime tag, Scope, notification evidence, or claim Stage 2 is live.

If the stale text has already been fixed by a newer `origin/develop`, make no edit here.

- [ ] **Step 5: Record the exact current N/Multi tracked inventory without writing a report file.**

```bash
git ls-files | grep -E \
  '(^|/)(n_structure|nStructure|NStructure|n_candidate|multi_candidate|MultiCandidate)|N字区间' \
  | sort

git ls-files 'services/quant-api/tests/test_n_structure_*.py'
git ls-files 'services/quant-api/tests/test_n_candidate_validation*.py'
```

Expected: every result is attributable to the approved retirement surface, shared tests/docs, or historical plan/spec. Any production DB/Redis/Alert owner not described by the Spec is a blocker.

- [ ] **Step 6: Run the focused pre-change backend baseline.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_n_structure_swing.py \
  services/quant-api/tests/test_n_structure_policy.py \
  services/quant-api/tests/test_n_structure_segment.py \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/research/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/research/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py
```

Expected: baseline passes. A pre-existing retained SuBing/Stage 2 failure blocks retirement until classified.

- [ ] **Step 7: Run the focused pre-change Web baseline.**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/nStructureBands.test.ts \
  tests/nStructureBandPrimitive.test.ts \
  tests/mainIndicators.test.ts \
  tests/marketOverlayConvergence.test.ts

pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-research.spec.mjs
```

Expected: baseline passes.

- [ ] **Step 8: Commit the STATUS correction only if Step 4 changed it.**

```bash
git diff --check
git add STATUS.md
git diff --cached --quiet || git commit -m \
  'docs: align Stage 2 repository status'
```

No business code is changed in Task 0.

---

### Task 1: Remove the entire Web N Structure surface and migrate chart preferences to v7

**Files:**
- Delete: `apps/quant-web/src/composables/useNStructureBands.ts`
- Delete: `apps/quant-web/src/components/kline/NStructureBandPrimitive.ts`
- Delete: `apps/quant-web/tests/nStructureBands.test.ts`
- Delete: `apps/quant-web/tests/nStructureBandPrimitive.test.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/tests/mainIndicators.test.ts`
- Modify: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Consumes: existing Market bars, `none | subing | htdy`, Stage 2 current/historical Strategy DTOs and chart markers.
- Produces: N-free Market Web; preference schema `version: 7`; no N request, state, renderer, hover or settings path.

- [ ] **Step 1: Change preference tests first so v7 is required.**

In `apps/quant-web/tests/mainIndicators.test.ts`, make the default contract exactly:

```ts
assert.deepEqual(defaultMainChartPreferences(), {
  version: 7,
  selectedOverlay: 'subing',
  optionalEmaIndicators: [],
  showSubingInternalProcess: false,
  period: null,
  realtimeFollow: false,
})
```

Add/replace the migration case with a v6 → v7 retained-field test:

```ts
values.set('guiyi.market.chart.preferences.v6', JSON.stringify({
  version: 6,
  selectedOverlay: 'htdy',
  optionalEmaIndicators: ['ema_60', 'ema_10'],
  showSubingInternalProcess: true,
  period: '15m',
  realtimeFollow: true,
  retiredField: true,
}))

assert.deepEqual(loadMainChartPreferences(storage), {
  version: 7,
  selectedOverlay: 'htdy',
  optionalEmaIndicators: ['ema_10', 'ema_60'],
  showSubingInternalProcess: true,
  period: '15m',
  realtimeFollow: true,
})
```

Keep the existing v5 behavior, but its target becomes v7.

- [ ] **Step 2: Update the Web convergence test to describe only retained surfaces.**

Replace the existing N-positive convergence case with retained expectations that do not preserve an N compatibility contract:

```ts
const apiSource = read('../src/api/market.ts')
const chartSource = read('../src/pages/market/chart.vue')
const toolbarSource = read('../src/components/market/ProductWorkspaceToolbar.vue')

assert.match(apiSource, /export function getSubingStrategyHistory/)
assert.match(apiSource, /export function getSubingStrategyCurrent/)
assert.match(chartSource, /useSubingStrategyCurrent/)
assert.match(toolbarSource, /显示苏冰内部研究过程/)
```

Do not add a replacement structure layer.

- [ ] **Step 3: Run focused tests and observe RED.**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/mainIndicators.test.ts \
  tests/marketOverlayConvergence.test.ts
```

Expected: failures because current preferences are v6 and N Web wiring still exists.

- [ ] **Step 4: Implement the v7 preference contract.**

`apps/quant-web/src/utils/mainIndicators.ts` must converge to this shape:

```ts
export const MAIN_CHART_PREFERENCES_KEY = 'guiyi.market.chart.preferences.v7'
export const MAIN_CHART_PREFERENCES_VERSION = 7
const MAIN_CHART_PREFERENCES_V6_KEY = 'guiyi.market.chart.preferences.v6'

export interface MainChartPreferences {
  version: 7
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showSubingInternalProcess: boolean
  period?: string | null
  realtimeFollow?: boolean
}
```

The v6 migration copies only retained fields:

```ts
const migrated: MainChartPreferences = {
  version: 7,
  selectedOverlay: normalizeResearchOverlay(parsed.selectedOverlay),
  optionalEmaIndicators: normalizeOptionalEmaIndicators(parsed.optionalEmaIndicators),
  showSubingInternalProcess: Boolean(parsed.showSubingInternalProcess),
  period: typeof parsed.period === 'string' ? parsed.period : null,
  realtimeFollow: Boolean(parsed.realtimeFollow),
}
```

If a valid v6 value is migrated and storage is writable, persist v7 and remove the v6 key. Preserve the existing failure-safe behavior for inaccessible localStorage. Adjust v5 migration to produce the same v7 shape; do not reintroduce an N-specific compatibility DTO.

Remove `nStructureBandCapability` entirely.

- [ ] **Step 5: Remove the N API/type/state layer.**

From `apps/quant-web/src/api/market.ts`, remove N type imports and the N band request function. From `apps/quant-web/src/types/market.ts`, remove all N band request/wire/response/domain types.

Delete:

```bash
git rm \
  apps/quant-web/src/composables/useNStructureBands.ts \
  apps/quant-web/src/components/kline/NStructureBandPrimitive.ts
```

No replacement API/client/composable is created.

- [ ] **Step 6: Remove N wiring from the Market chart page and toolbar while preserving Stage 2 wiring.**

In `apps/quant-web/src/pages/market/chart.vue`, remove only:

```text
getNStructureBands
useNStructureBands
nStructureBandCapability
showNStructureBands
nStructureBands / loading / error / sync / dispose
nStructureBandsSupported
visibleNStructureBands
currentNStructureBandIdentity
all N-specific watchers and mutation sync calls
N-specific props/events passed to toolbar and KlineChart
```

Preserve `getSubingStrategyHistory`, `getSubingStrategyCurrent`, `useSubingStrategyCurrent`, Stage 2 current/history reconciliation, `useHistoricalResearchMarkers`, Alert markers and Subing current/history records.

In `ProductWorkspaceToolbar.vue`, remove the N props/emits/switch/help/error/loading UI. The chart-settings popover keeps optional EMA, SuBing internal-process control, contract controls and all other retained UI.

- [ ] **Step 7: Remove N rendering, interaction, diagnostics and badges from `KlineChart.vue`.**

Remove:

```text
NStructureBandPrimitive import/instance
NStructureBand type/prop/default
attach/detach primitive
N-specific watch
renderNStructureBands
syncNStructureBandDiagnostics
hovered N band/overlap state
N overlap click/cycle handlers
N overlap badges/tooltip/diagnostic template
N rendered counts/labels
```

`renderAllSeries()` becomes conceptually:

```ts
function renderAllSeries(): void {
  if (!candles || !volume || !chart) return
  candles.setData(barValues(renderedBars))
  volume.setData(volumeValues(renderedBars))
  renderDerivedSeries()
}
```

Do not alter candle/volume/MACD/EMA/HTDY/marker viewport behavior.

- [ ] **Step 8: Delete N-only Web tests and update retained E2E assertions.**

```bash
git rm \
  apps/quant-web/tests/nStructureBands.test.ts \
  apps/quant-web/tests/nStructureBandPrimitive.test.ts
```

In `apps/quant-web/e2e/market-research.spec.mjs`, remove N band route mocks, N settings interactions, overlap assertions and N request-count assertions. Keep SuBing/HTDY/Market chart retained cases. Add a retained chart-settings assertion that opening settings still exposes EMA and, when SuBing is selected, the SuBing internal-process switch.

- [ ] **Step 9: Run focused Web verification.**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/mainIndicators.test.ts \
  tests/marketOverlayConvergence.test.ts \
  tests/historicalResearchMarkers.test.ts \
  tests/subingStrategyHistory.test.ts \
  tests/subingStrategyRecords.test.ts

pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-research.spec.mjs

pnpm --dir apps/quant-web build
```

Expected: PASS; no N API request or rendered band remains.

- [ ] **Step 10: Commit the Web retirement atomically.**

```bash
git add apps/quant-web
git diff --cached --check
git commit -m 'refactor(web): retire N structure chart surface'
```

---

### Task 2: Remove the N HTTP endpoint and `guiyi research n-structure` command

**Files:**
- Delete: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/main.py`
- Modify: `services/quant-api/app/schemas/research_overlays.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`
- Modify: `services/quant-api/tests/test_research_cli_boundaries.py`
- Modify: `services/quant-api/tests/research/test_research_cli_parser_requests.py`
- Modify: `services/quant-api/tests/research/research_cli_fixtures.py`
- Modify: `tests/engineering/test_canonical_consistency.py`

**Interfaces:**
- Consumes: retained SuBing calibration/lifecycle CLI services and Stage 2 `subing-strategy/current|history` HTTP endpoints.
- Produces: research CLI exactly `subing-calibration | subing-lifecycle`; no N-only HTTP router or DTO.

- [ ] **Step 1: Change CLI registry tests first.**

In both `services/quant-api/tests/research/test_research_cli_parser_requests.py` and `tests/engineering/test_canonical_consistency.py`, require exactly:

```python
RESEARCH_COMMANDS = {
    "subing-calibration",
    "subing-lifecycle",
}
```

and:

```python
assert tuple(command_action.choices) == (
    "subing-calibration",
    "subing-lifecycle",
)
```

In `test_research_cli_boundaries.py`, keep the module-boundary assertions for request/dispatch/payload owners, but remove any assertion that a third N serializer exists.

- [ ] **Step 2: Run the focused CLI tests and observe RED.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli_boundaries.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  tests/engineering/test_canonical_consistency.py
```

Expected: current parser still exposes three commands, so retained-command assertions fail.

- [ ] **Step 3: Shrink the CLI parser/request/dispatch/payload path to the two retained SuBing commands.**

`research_parser.py`:

```python
RESEARCH_COMMAND_NAMES = (
    "subing-calibration",
    "subing-lifecycle",
)
```

`research_requests.py`:

```python
ResearchRequest: TypeAlias = CalibrationResearchRequest | LifecycleResearchRequest
```

Remove the N import and N branch. `research_commands.py` keeps only Lifecycle dispatch and Calibration fallback. `research_payloads.py` removes N imports, N serializer and any helper used only by N outcome serialization.

`guiyi_cli/main.py` removes the N service factory parameter/import/dispatch branch. Do not change runtime command authorization or Stage 2 Alert code.

- [ ] **Step 4: Delete the N-only HTTP router and unregister it from FastAPI.**

```bash
git rm services/quant-api/app/research/historical_overlay_api.py
```

From `services/quant-api/app/main.py`, remove only:

```python
from app.research.historical_overlay_api import router as research_historical_overlay_router
```

and:

```python
app.include_router(research_historical_overlay_router)
```

Keep `market_research_overlays_router`, because it owns retained Stage 2 `subing-strategy/current` and `subing-strategy/history` endpoints.

- [ ] **Step 5: Remove only N DTOs from `schemas/research_overlays.py`.**

Delete N request/policy/band/response classes. Preserve all Stage 2 fields including `effective_open_at`, current Strategy context/pending summary/current response, historical response and Strategy Episode DTOs.

- [ ] **Step 6: Remove N-only API/CLI test sections and fixture objects.**

`test_market_research_overlays_api.py` retains Stage 2 current/history tests and removes N imports, fake N service and N route cases.

`research_cli_fixtures.py` and `test_research_cli_parser_requests.py` remove N request/result/candidate fixture construction; do not remove Subing Candidate fixtures used by retained validation tests.

- [ ] **Step 7: Run focused backend tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_cli_boundaries.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  tests/engineering/test_canonical_consistency.py

uv run --project services/quant-api guiyi research subing-calibration --help
uv run --project services/quant-api guiyi research subing-lifecycle --help
```

Expected: PASS. Do not invoke any research command against real data; help is sufficient.

- [ ] **Step 8: Commit.**

```bash
git add -A \
  services/quant-api/app/main.py \
  services/quant-api/app/schemas/research_overlays.py \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/research \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_research_cli_boundaries.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/research_cli_fixtures.py \
  tests/engineering/test_canonical_consistency.py
git diff --cached --check
git commit -m 'refactor(api): retire N structure public surfaces'
```

---

### Task 3: Remove N/Multi-Candidate composition and delete Multi-Candidate Robustness

**Files:**
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/tests/test_research_composition.py`
- Delete: `services/quant-api/app/research/robustness/`
- Delete: `data/research_protocols/multi_candidate_robustness_v1.json`
- Delete: `services/quant-api/tests/test_multi_candidate_events.py`
- Delete: `services/quant-api/tests/test_multi_candidate_robustness.py`
- Delete: `services/quant-api/tests/test_multi_candidate_robustness_policy.py`
- Delete: `services/quant-api/tests/research/test_multi_candidate_robustness_service.py`

**Interfaces:**
- Consumes: retained `SubingCalibrationResearchService`, `SubingLifecycleResearchService`, `SubingCandidateValidationService`.
- Produces: research composition with exactly three retained builders; no robustness package/protocol/service.

- [ ] **Step 1: Make composition tests require only retained builders.**

Replace the builder-shape assertion with:

```python
assert _local_research_builders() == (
    "build_subing_calibration_research_service",
    "build_subing_lifecycle_research_service",
    "build_subing_candidate_validation_service",
)
```

Keep the existing tests proving calibration/lifecycle use historical MDS and Subing Candidate Validation reuses the lifecycle research service. Remove N/Multi-specific builder test cases rather than converting them into a single-candidate robustness abstraction.

- [ ] **Step 2: Run the composition test and observe RED.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_composition.py
```

Expected: current composition still exposes N and Multi builders.

- [ ] **Step 3: Remove N/Multi imports and builders from `research/composition.py`.**

Final builder surface is exactly:

```python
build_subing_calibration_research_service
build_subing_lifecycle_research_service
build_subing_candidate_validation_service
```

Do not move Multi-Candidate logic into `app/research/subing`.

- [ ] **Step 4: Delete the entire Multi-Candidate Robustness package and protocol.**

```bash
git rm -r services/quant-api/app/research/robustness
git rm data/research_protocols/multi_candidate_robustness_v1.json

git rm \
  services/quant-api/tests/test_multi_candidate_events.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/research/test_multi_candidate_robustness_service.py
```

No `single_candidate_robustness`, relationship DTO, event-proximity helper or compatibility flag is created.

- [ ] **Step 5: Verify retained Subing Candidate composition.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/research/test_subing_candidate_validation_service.py
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add -A \
  services/quant-api/app/research \
  services/quant-api/tests \
  data/research_protocols
git diff --cached --check
git commit -m 'refactor(research): remove multi-candidate robustness'
```

---

### Task 4: Delete N Candidate/policy/protocol/core and all N-only tests without touching SuBing structure

**Files:**
- Delete: `services/quant-api/app/research/n_structure/`
- Delete: `data/research_policies/n_structure_5m_v1.json`
- Delete: `data/research_candidates/n_structure_5m_candidate_v1.json`
- Delete: `data/research_protocols/n_structure_validation_v1.json`
- Delete: `services/quant-api/tests/test_n_structure_*.py`
- Delete: `services/quant-api/tests/test_n_candidate_validation*.py`
- Delete: `services/quant-api/tests/research/test_n_structure_research_service.py`
- Delete: `services/quant-api/tests/research/test_n_candidate_validation_service.py`
- Modify if N fixtures remain after Task 2: `services/quant-api/tests/research/research_cli_fixtures.py`

**Interfaces:**
- Consumes: no active N consumer after Tasks 1–3.
- Produces: no N implementation/candidate/OOS policy remains; retained SuBing Pivot and Candidate paths continue unchanged.

- [ ] **Step 1: Prove no active runtime or composition import still points into the N package.**

```bash
git grep -n 'app\.research\.n_structure' -- \
  services/quant-api/app \
  apps/quant-web/src \
  tests/engineering || true
```

Expected before deletion: no active consumer outside files that will be deleted in this task. If Alert/Runtime/Stage 2 code appears, stop.

- [ ] **Step 2: Delete N frozen inputs and the full N package.**

```bash
git rm -r services/quant-api/app/research/n_structure

git rm \
  data/research_policies/n_structure_5m_v1.json \
  data/research_candidates/n_structure_5m_candidate_v1.json \
  data/research_protocols/n_structure_validation_v1.json
```

Do not delete shared candidate schedule helpers, `price_outcome.py`, `actual_dominant_research.py`, or any `subing_*` module simply because N used them.

- [ ] **Step 3: Delete N-only tests from the exact tracked glob inventory captured in Task 0.**

```bash
git ls-files -z 'services/quant-api/tests/test_n_structure_*.py' \
  | xargs -0 -r git rm --
git ls-files -z 'services/quant-api/tests/test_n_candidate_validation*.py' \
  | xargs -0 -r git rm --
git rm \
  services/quant-api/tests/research/test_n_structure_research_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py
```

If a glob is empty because an earlier task already removed a file, confirm with `git status` rather than recreating anything.

- [ ] **Step 4: Remove any N-only fixture imports left in shared CLI fixtures.**

The final `research_cli_fixtures.py` may construct only retained calibration/lifecycle/Subing Candidate fixtures. It must not import a deleted N module to preserve historical test data.

- [ ] **Step 5: Prove the protected SuBing structure implementation still exists and passes.**

```bash
test -f services/quant-api/app/market_data/subing_structure.py

git diff -- services/quant-api/app/market_data/subing_structure.py

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/research/test_subing_candidate_validation_service.py
```

Expected: file exists, diff is empty, tests PASS.

- [ ] **Step 6: Run an executable-surface N/Multi scan.**

```bash
rg -n \
  '(n_structure|NStructure|n-structure|n_structure_5m_candidate_v1|n_structure_validation_v1|multi_candidate_robustness|MultiCandidateRobustness|N字区间)' \
  services/quant-api/app \
  services/quant-api/tests \
  apps/quant-web/src \
  apps/quant-web/tests \
  apps/quant-web/e2e \
  data/research_policies \
  data/research_candidates \
  data/research_protocols \
  tests/engineering
```

Expected: no matches. If matches remain, classify and remove only N/Multi active references; do not suppress the scan.

- [ ] **Step 7: Commit.**

```bash
git add -A \
  services/quant-api/app/research \
  services/quant-api/tests \
  data/research_policies \
  data/research_candidates \
  data/research_protocols
git diff --cached --check
git commit -m 'refactor(research): retire N structure core'
```

---

### Task 5: Converge active canonical and testing docs while preserving production truth

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `DECISIONS.md`
- Modify: `STATUS.md`
- Modify: `TESTING.md`

**Interfaces:**
- Consumes: N-free repository state from Tasks 1–4 and current production `v1.8.6 + 0041` facts.
- Produces: active canonical that describes only retained repository capability while keeping production Runtime facts exact.

- [ ] **Step 1: Update `PROJECT_SOURCE.md` to the retained product surface.**

The Market Web section keeps:

```text
Overlay = none | subing | htdy
```

and no active N layer.

The research section becomes conceptually:

```text
SuBing Candidate Validation 保留 source-specific causality、strict-before、
embargo、prefix invariance、golden parity 与 prospective OOS 分离；
retrospective 不生成自动 rank/winner/promotion/可交易结论。
```

Remove Generic/Multi-Candidate relationship claims. Add N Structure and Multi-Candidate Robustness to `Retired surface`, with Git history + new-task-only restoration semantics.

Research CLI documentation becomes exactly:

```text
subing-calibration
subing-lifecycle
```

Do not weaken the already-integrated Stage 2 Strategy description.

- [ ] **Step 2: Rewrite the active dependency graph in `docs/ARCHITECTURE.md`.**

Remove these seams:

```text
MDS -> N -> MARKET
N research service
N Candidate Validation
CV -> ROB Candidate Robustness
Multi-Candidate relationship dependency
```

The retained research graph is:

```text
MDS -> SuBing calibration/lifecycle research -> research CLI
SuBing lifecycle research + candidate manifest/protocol -> SuBing Candidate Validation
```

Also preserve current Stage 2 architecture from `PROJECT_SOURCE.md`/`DECISIONS.md`: Historical + completed-Live share the Strategy machine; active60 runtime state is distinct from Alert Scope; production promotion remains external.

- [ ] **Step 3: Update `DECISIONS.md` retired-surface decision.**

Add N Structure and Multi-Candidate Robustness to the existing retired-surface row. Its invariant must explicitly state that restoration requires a new task defining consumer/formula/value/evidence and that `subing_structure.py` is retained SuBing infrastructure, not part of the retirement.

- [ ] **Step 4: Update `STATUS.md` without pretending production has changed.**

At this repository commit, state:

```text
Repository code: N Structure / Multi-Candidate retirement implemented; release pending.
Production Runtime: still v1.8.6 exact tag and migration 0041; therefore deployed N Historical layer may still exist until a later release + Runtime promotion.
```

Remove N Candidate prospective-OOS as an active repository pending gate; retain SuBing Candidate prospective OOS.

Retain production Rule/0042/Runtime/Scope facts exactly. Do not claim migration 0042, `subing_strategy_v1` production replacement, Runtime promotion or notification evidence happened.

- [ ] **Step 5: Update `TESTING.md` CLI commands.**

Research CLI help becomes:

```bash
uv run --project services/quant-api guiyi research subing-calibration --help
uv run --project services/quant-api guiyi research subing-lifecycle --help
```

No replacement N command is added.

- [ ] **Step 6: Run documentation and canonical checks.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md
git diff --cached --check
git commit -m 'docs: retire N structure active surface'
```

---

### Task 6: Run the full retained regression and prove active-reference zero

**Files:**
- No planned source changes. Any fix must be limited to a regression caused by Tasks 1–5 and committed separately with a scoped message.

**Interfaces:**
- Consumes: complete retirement branch.
- Produces: `TEST_COMPLETE` evidence for Web/backend/canonical and proof that retained SuBing Stage 2 semantics did not change.

- [ ] **Step 1: Run the executable-surface zero-reference scan again.**

```bash
rg -n \
  '(n_structure|NStructure|n-structure|n_structure_5m_candidate_v1|n_structure_validation_v1|multi_candidate_robustness|MultiCandidateRobustness|N字区间)' \
  services/quant-api/app \
  services/quant-api/tests \
  apps/quant-web/src \
  apps/quant-web/tests \
  apps/quant-web/e2e \
  data/research_policies \
  data/research_candidates \
  data/research_protocols \
  tests/engineering \
  TESTING.md \
  docs/ARCHITECTURE.md
```

Expected: zero matches.

Repository-wide historical/canonical scan:

```bash
rg -n \
  '(n_structure|NStructure|n-structure|n_structure_5m_candidate_v1|n_structure_validation_v1|multi_candidate_robustness|MultiCandidateRobustness|N字区间|N Structure|Multi-Candidate)' \
  . \
  --glob '!.git/**'
```

Allowed matches are limited to the approved retirement Spec/Plan, `PROJECT_SOURCE.md`/`DECISIONS.md` Retired surface, and `STATUS.md` statements required to describe the still-deployed production v1.8.6 fact. Any active implementation/API/CLI/Web/test/config match is a blocker.

- [ ] **Step 2: Run retained research + SuBing structure/Candidate tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_research_composition.py \
  services/quant-api/tests/test_research_cli_boundaries.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_candidate_validation_service.py \
  services/quant-api/tests/test_subing_structure.py \
  services/quant-api/tests/research/test_subing_lifecycle_causality.py \
  services/quant-api/tests/research/test_subing_lifecycle_contracts.py
```

Expected: PASS.

- [ ] **Step 3: Run retained Stage 2 Strategy parity/causality/runtime tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_subing_strategy_contracts.py \
  services/quant-api/tests/research/test_subing_strategy_engine.py \
  services/quant-api/tests/research/test_subing_strategy_causality.py \
  services/quant-api/tests/research/test_subing_strategy_historical_live_parity.py \
  services/quant-api/tests/research/test_subing_strategy_machine.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_current_service.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_replay.py \
  services/quant-api/tests/data_foundation/test_subing_strategy_service.py \
  services/quant-api/tests/test_subing_strategy_runtime.py \
  services/quant-api/tests/acceptance/test_subing_strategy_stage2_shadow.py
```

Expected: PASS with no Strategy formula/action-identity/timing changes attributable to retirement. The acceptance shadow remains sealed/no-write; do not run a real production shadow.

- [ ] **Step 4: Run retained Market/Alert API tests.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

Expected: PASS; no production service is started and no real notification is sent.

- [ ] **Step 5: Run the complete non-production backend gate.**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m 'not isolated_postgresql' \
  services/quant-api/tests

PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy \
  --explicit-package-bases \
  --ignore-missing-imports \
  services/quant-api/app \
  packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app \
  services/quant-api/tests \
  packages/quant-core/guiyi_quant \
  tests/engineering

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
```

Do not run isolated PostgreSQL unless a separate task explicitly provides and authorizes the disposable isolated DB. Do not execute migration 0042.

- [ ] **Step 6: Run the full Web gate.**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 7: Run final repository static checks.**

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected: all checks pass; only intentional committed changes exist; task worktree is clean before Review.

- [ ] **Step 8: If a regression fix was required, keep it tracked-only and rerun the affected gate.**

A regression fix in this task must not add a new module or abstraction. Starting from the clean worktree produced by Step 7:

```bash
git status --short
git add -u
git diff --cached --check
git commit -m 'fix: preserve retained surface after N retirement'
```

If a fix appears to require a new file, new abstraction, strategy change or expanded scope, stop and return to design review instead of committing it.

---

### Task 7: Independent exact-head Review, PR/CI, develop integration and cleanup

**Files:** none planned.

**Interfaces:**
- Consumes: clean, fully verified task head.
- Produces: independently reviewed retirement merged to `develop`, with task worktree/branch cleaned; no release or Runtime mutation.

- [ ] **Step 1: Capture the exact implementation head.**

```bash
git status --short
git rev-parse HEAD
git log --oneline --decorate -8
```

Expected: clean worktree.

- [ ] **Step 2: Open the implementation PR to `develop`.**

PR body must state:

```text
Scope: complete N Structure + Multi-Candidate Robustness repository retirement.
Retained: SuBing Stage 2, SuBing Candidate Validation/OOS, HTDY, Market, Alert.
No production mutation: no migration, DB/Redis/Canonical write, Scope, notification, main/tag/release or Runtime promotion.
Verification: list exact backend/Web/static commands and results.
Production note: v1.8.6 may still expose N until a later release + Runtime promotion.
```

- [ ] **Step 3: Start a new independent Review session on the exact PR head.**

Review focus:

```text
1. active N/Multi references really reach zero;
2. no dead compatibility shell or single-candidate robustness was left;
3. subing_structure.py is untouched;
4. Stage 2 current/history/runtime/action timing remains unchanged;
5. SuBing Candidate Validation + prospective OOS remain intact;
6. Web preference v6→v7 preserves retained fields only;
7. STATUS/PROJECT_SOURCE/ARCHITECTURE/DECISIONS distinguish repository from production;
8. no 0042/main/tag/Runtime/notification mutation occurred.
```

Any formula, Action identity/timing, Lifecycle, Alert Rule/Scope or Runtime semantic change is `REQUEST_CHANGES`.

- [ ] **Step 4: Require CI and independent Review green before integration.**

If Review requests changes, continue the same task branch/session only for scoped corrections, rerun affected tests plus Task 6 final gates, and re-review the new exact head.

- [ ] **Step 5: Merge task → `develop` only after the Lane 2 gate is satisfied.**

This is a normal repository integration, not a release. After merge, from any worktree where the local task branch still exists:

```bash
git fetch origin
git merge-base --is-ancestor \
  refactor/retire-n-structure \
  origin/develop
```

Expected: exit `0`.

- [ ] **Step 6: Clean the temporary worktree and merged task branch.**

From a different worktree:

```bash
git worktree remove ../guiyi-retire-n-structure
git branch -d refactor/retire-n-structure
```

Delete the remote task branch through the normal PR cleanup path if it still exists. Do not touch `main`, tags or the detached Runtime worktree.

- [ ] **Step 7: Report the final state using the repository completion vocabulary.**

Allowed repository conclusion after merge and fresh verification:

```text
CODE_COMPLETE
TEST_COMPLETE
已集成 develop
EXTERNAL_GATE_PENDING: release + Runtime promotion
```

Do not claim `RELEASED` or `RUNTIME_READY`.

---

## Final Acceptance Checklist

The implementation is acceptable only if all of the following are simultaneously true:

```text
[ ] Market Web has no N setting, request, state, renderer, hover or badge.
[ ] Main chart preference is v7 and preserves only retained fields from v6.
[ ] N HTTP endpoint is unregistered, not wrapped.
[ ] research CLI has exactly subing-calibration + subing-lifecycle.
[ ] research composition has exactly three retained SuBing builders.
[ ] robustness package and multi-candidate protocol are gone.
[ ] N core, N policy, N candidate, N validation protocol and N OOS service are gone.
[ ] No single-candidate robustness replacement exists.
[ ] SuBing Candidate Validation manifest/protocol/service remain.
[ ] subing_structure.py remains unchanged and its tests pass.
[ ] Stage 2 Historical/Live parity, machine, current service and runtime tests pass.
[ ] HTDY/Market/Alert retained tests pass.
[ ] executable-surface active-reference scan is zero.
[ ] canonical/docs describe N/Multi only as retired/history or current production v1.8.6 fact.
[ ] no production DB/Redis/Canonical/Scope/notification mutation occurred.
[ ] no 0042 execution, main merge, tag, release or Runtime promotion occurred.
```

## Codex Implementation Prompt

```text
请先阅读 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、
`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`，
以及：
- `docs/superpowers/specs/2026-08-27-retire-n-structure-design.md`
- `docs/superpowers/plans/2026-08-27-retire-n-structure.md`

本任务为 Lane 2 跨模块退役，使用 Sol + 高推理，Plan-then-execute。

目标：
完整删除 N Structure 与专用于 SuBing↔N 的 Multi-Candidate Robustness，
关闭 Web/API/CLI/research/candidate/protocol/tests/canonical 的全部 active seam。

工作区：
从 then-latest `origin/develop` 创建 `refactor/retire-n-structure`
独立 task branch/worktree。不得修改 main/runtime worktree。

关键保护：
- 不得修改 SuBing 策略公式或 Stage 2 语义；
- 不得删除/改写 `app/market_data/subing_structure.py`；
- 保留 SuBing Candidate Validation 与 prospective OOS；
- 保留 HTDY、Market、Alert；
- 不修改/执行 migration 0042；
- 不做 production DB/Redis/Canonical/Scope/通知写入；
- 不发布 main/tag/release，不做 Runtime promotion；
- 不创建 archive、compatibility shell 或 single-candidate robustness。

严格按 Implementation Plan Task 0→7 执行，每个任务先做计划中指定的 RED/基线检查，
再最小实现、运行对应验证并提交。若发现新的 production persistence/Runtime consumer、
或 current canonical 与计划存在会改变策略/生产语义的冲突，立即停止并 fail-closed。

实现完成后开独立 exact-head Review；全部测试、CI、Review 通过后，
可按 Lane 2 正式流程合入 develop 并清理 task worktree/branch。
不得触及 main、tag、release 或 Runtime。

完成后输出：
修改摘要、删除清单、retained invariants、测试结果、active-reference scan、
PR/Review/集成结果、清理结果、production 未执行 Gate、风险和未完成项。
```
