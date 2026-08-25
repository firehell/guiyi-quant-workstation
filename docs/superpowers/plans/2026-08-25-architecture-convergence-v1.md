# Architecture Convergence V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保留可信数据、一个 SuBing Trading Assistant、HTDY 全品种全周期观察与 `symbol × frequency` Alert、JDJ 参考回放、Alert 和 Execution Review 的前提下，删除失去产品价值的 Web/API/CLI/Research/文档链路，使归一量化进入精简、准确、可持续维护的个人工作站形态。

**Architecture:** SuBing 统一为一个用户产品，但继续保留 Daily Context、Current Signal State 与 Formal Event 三种不同生命周期的内部投影；Web application composition 统一这些投影，后端不新增跨 Market/Alert 的 mega endpoint。HTDY 继续使用已批准的全周期 Spec/Plan，本计划不重复实现其 migration、Scope、Event identity 或 Runtime trigger。其余能力按 KEEP / INTERNALIZE / DELETE 矩阵逐条退役。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / PostgreSQL / Redis / NumPy / pytest / Vue 3 / TypeScript 6 / Naive UI / Node test / Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md`

**Required HTDY canonical:**

- `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`
- `docs/superpowers/plans/2026-08-25-htdy-all-frequency-active60.md`

---

## Global Constraints

- 本计划是 Lane 3 Program；不得作为一个巨大 PR 执行。每个 Task 是一个可独立集成单元、一个会话、一个 branch/worktree 和一个 PR。
- 当前文档基线是 `develop@fd0777672c49a856b283a0f4653519c68a35cb38`。实际代码任务必须从执行时最新 `develop` 创建。
- HTDY implementation 已由用户说明正在进行，但当前 GitHub 基线只包含 Spec/Plan。任何修改 HTDY 重叠文件的 Task 开始前，必须先发现真实在途 branch/worktree/dirty paths；不能发现时 fail-closed。
- 如果 HTDY implementation 已合入 `develop`，所有重叠任务从该 integration commit 之后创建。
- 如果 HTDY implementation 尚未合入，只允许执行不触碰 HTDY 重叠文件的 SuBing 首页独立任务；其他任务阻塞。
- 不修改 SuBing Factor、Signal、Calibration、FormalPolicy、Lifecycle、Historical replay 或 Daily Watch 数学公式。
- SuBing Alert 继续 product-level Scope；HTDY Alert 继续 `symbol × frequency` Scope。不得互换 authority。
- 不修改 HTDY original 公式、future-looking/repainting metadata、七周期 allowlist、D1/W1 `canonical_updated` trigger 或 one-shot notification 语义。
- 不建立统一 Strategy adapter、Opportunity score、Scope DSL、插件框架、消息队列、retry、replay、backfill、outbox 或逐人状态。
- 不修改 Canonical、八表 Catalog、MainContractMap、MarketDataService、RQData provider 或 Live/Historical 分界。
- 不删除 Alembic migrations、accepted policies、pending prospective OOS baseline/evidence 或 universe files。
- 实现任务可以在隔离 PostgreSQL 运行 migration tests；不得执行 production migration。
- 不修改真实 Alert Scope、owner、Topic 或 transport；不发送真实 PushPlus。
- 不运行 manual after-market、真实 RQAlpha smoke、Runtime switch/promotion、main release 或 tag。
- `auto_order=false` 不得改变。
- 所有行为任务使用 TDD：先写失败测试，确认失败原因正确，再写最小实现，再运行定向和受影响的完整测试。
- 删除任务先移除 consumer，再删除 provider；任何隐藏 consumer 出现时停止并回到任务范围审查。
- `STATUS.md` 只能记录真正发生的实现、测试、Review、integration、release、Runtime 或 evidence，不得提前宣布完成。

## Program Worktree Model

每个 Task 默认：

```text
latest develop
→ new task branch/worktree
→ local focused tests
→ self-review
→ PR to develop
→ independent Review（Lane 3 必须）
→ user allows integration
→ merge to develop
→ verify ancestry
→ remove task worktree and merged branch
```

不得自动触及：

```text
main
tag
runtime worktree
production DB/Redis/Canonical
real Scope
real notification
```

---

## Task 0: Establish the HTDY collision gate and exact convergence inventory

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `chore/convergence-v1-preflight` from latest `develop`  
**Files:**

- Create: `services/quant-api/tests/engineering/test_architecture_convergence_inventory.py`
- Modify: none outside this test in the first commit

### Step 0.1: Inspect the real workspace before changing code

Run:

```bash
git status --short --branch
git worktree list --porcelain
git branch --all --contains fd0777672c49a856b283a0f4653519c68a35cb38
git log --oneline --decorate -20 develop
git branch -a | grep -E 'htdy|architecture-convergence' || true
gh pr list --state open --search 'htdy' --json number,title,headRefName,baseRefName,url
```

Required result:

- record the exact `develop` SHA;
- identify every dirty path in the source worktree;
- identify the exact HTDY implementation branch/worktree/PR if present;
- prove whether HTDY implementation is already an ancestor of `develop`.

Stop conditions:

```text
HTDY work reported in progress but its branch/worktree cannot be identified
OR
uncommitted overlapping files exist without a named owner/task
OR
multiple divergent HTDY implementation branches exist
```

Do not guess or start a replacement implementation.

### Step 0.2: Add a failing inventory test

Create a repository-level test that expresses the **target**, not the current state. It should initially fail on current `develop` and assert:

```python
TARGET_WEB_OVERLAYS = ("none", "subing", "jdj_strategy", "htdy")
RETIRED_TOKENS = (
    "MarketTrendFocus",
    "MarketAttentionList",
    "main_force_mirror_v2",
    "candidate-dossier",
    "candidate-relationships",
)
```

The test must:

- read `apps/quant-web/src/utils/mainIndicators.ts` and assert only the four target Overlay ids remain;
- assert no active route contains `/research/trend-focus`;
- assert no active Web import references `MarketAttentionList` or `MarketFocusList`;
- assert no `guiyi research` parser command exposes `candidate-dossier`, `candidate-relationships`, `main-force-mirror-v2`, or `main-force-mirror-diagnostic`;
- assert the two HTDY canonical documents still exist until the HTDY implementation closeout gate;
- assert Alembic migration paths are excluded from deletion checks.

Run and confirm failure:

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
```

Expected: failure listing current active surfaces. A pass before implementation means the test is not checking the intended targets.

### Step 0.3: Commit only the red inventory test

```bash
git add services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
git commit -m "test: define convergence v1 target inventory"
```

Open a PR only if the repository accepts a deliberately red guard branch; otherwise keep this commit as the first commit of Task 1 and do not merge it alone. The final target inventory test must become green by Task 8.

---

## Task 1: Unify the SuBing homepage into one workbench

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `feature/subing-single-home-workbench` from latest `develop`  
**HTDY dependency:** none if only the files listed below are touched  
**Files:**

- Create: `apps/quant-web/src/composables/useSubingWorkbench.ts`
- Create: `apps/quant-web/src/components/market/SubingWorkbench.vue`
- Create: `apps/quant-web/tests/subingWorkbench.test.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/tests/currentFormalSignals.test.ts`
- Modify: `apps/quant-web/tests/subingDailyWatch.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Delete: `apps/quant-web/src/components/market/MarketFormalSignals.vue`
- Delete: `apps/quant-web/src/components/market/SubingDailyWatch.vue`

### Step 1.1: Write the failing workbench state tests

Define the composable contract:

```ts
export interface SubingWorkbenchDependencies {
  fetchFormal: typeof getCurrentFormalSignals
  fetchDailyWatch: typeof getSubingDailyWatchCurrent
  fetchEventStates: typeof getEventStates
}

export function useSubingWorkbench(
  dependencies: SubingWorkbenchDependencies,
): {
  formalStatus: Ref<'ready' | 'unavailable' | null>
  formalTradingDay: Ref<string | null>
  formalItems: Ref<CurrentFormalSignalItem[]>
  formalEventStates: Ref<Record<number, EventState>>
  formalLoading: Ref<boolean>
  formalStale: Ref<boolean>
  dailyWatch: Ref<SubingDailyWatchCurrentResponse | null>
  dailyLoading: Ref<boolean>
  dailyStale: Ref<boolean>
  refreshAll(): Promise<void>
  refreshOperational(): Promise<void>
  dispose(): void
}
```

Tests must prove:

1. Formal ready-empty is different from unavailable.
2. Daily Watch unavailable does not clear a ready Formal Event.
3. Formal failure does not clear a ready Daily Watch snapshot.
4. An older Formal response cannot overwrite a newer generation.
5. An older Daily response cannot overwrite a newer generation.
6. Event-state lookup is invalidated when the Formal item set changes.
7. `refreshOperational()` refreshes Formal + Daily only.
8. `dispose()` prevents all pending requests from mutating state.
9. The composable never filters or invents backend SuBing facts.

Run and confirm failure:

```bash
cd apps/quant-web
node --test \
  tests/subingWorkbench.test.ts \
  tests/currentFormalSignals.test.ts \
  tests/subingDailyWatch.test.ts
```

### Step 1.2: Implement the composable by reusing existing generation-safe primitives

- Reuse `useCurrentFormalSignals` for Formal state; do not duplicate its resolver or filtering.
- Reuse `useLatestResource` for Daily Watch.
- Move `formalEventStates` generation handling from `pages/market/index.vue` into the new composable.
- Preserve separate loading/stale/error state per source.
- `refreshAll()` calls Formal + Daily concurrently.
- `refreshOperational()` has the same two calls; Radar/Runtime remain page-owned.
- Do not add a backend aggregate endpoint.

### Step 1.3: Implement the unified component

`SubingWorkbench.vue` must render one top-level section:

```text
苏冰
├── 需要处理（Formal Event）
├── 今日观察（Daily Watch）
└── source-specific unavailable/stale state
```

Required behavior:

- Formal cards remain first and retain Execution Review action labels.
- Daily Watch retains long/short/excluded/unavailable counts and first-six expansion behavior.
- Formal and Daily target/source trading days remain visible.
- One source failure must be labeled locally; do not show the whole workbench as unavailable.
- Clicking a Daily Watch item still opens `actual_dominant + 15m + subing`.
- Clicking a Formal Event preserves current redirect behavior to Execution Review or chart.

### Step 1.4: Replace the two homepage siblings

In `pages/market/index.vue`:

- remove `MarketFormalSignals` and `SubingDailyWatch` imports;
- remove page-owned formal event-state generation code;
- create one `useSubingWorkbench(...)` instance;
- render exactly one `<SubingWorkbench ... />` between Runtime and full-market research;
- keep Radar and Runtime refresh ownership unchanged;
- visibility refresh calls Runtime + SuBing workbench, not Radar.

Add a source-topology assertion in `subingWorkbench.test.ts`:

```ts
assert.equal(homeSource.match(/<SubingWorkbench\b/g)?.length, 1)
assert.equal(homeSource.includes('<MarketFormalSignals'), false)
assert.equal(homeSource.includes('<SubingDailyWatch'), false)
```

### Step 1.5: Update E2E

`market-research.spec.mjs` must prove:

- one SuBing top-level region exists;
- Formal action and Daily Watch group can coexist inside it;
- Formal failure does not hide Daily Watch;
- Daily Watch failure does not hide Formal action;
- opening a Daily candidate still enters 15m SuBing;
- full-market research remains independently expandable.

### Step 1.6: Verify

```bash
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "SuBing|苏冰|Market"
pnpm build
cd ../..
git diff --check
python scripts/engineering/secret_scan.py
```

### Step 1.7: Commit and PR

```bash
git add \
  apps/quant-web/src/composables/useSubingWorkbench.ts \
  apps/quant-web/src/components/market/SubingWorkbench.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/tests/subingWorkbench.test.ts \
  apps/quant-web/tests/currentFormalSignals.test.ts \
  apps/quant-web/tests/subingDailyWatch.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs \
  apps/quant-web/src/components/market/MarketFormalSignals.vue \
  apps/quant-web/src/components/market/SubingDailyWatch.vue
git commit -m "refactor: unify SuBing homepage workbench"
```

PR conclusion required: `允许集成 develop` before merge.

---

## Task 2: Unify the SuBing product workspace panel

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `feature/subing-single-product-panel` from latest `develop` after HTDY integration  
**HTDY dependency:** hard; do not start on the 15m-only baseline  
**Files:**

- Create: `apps/quant-web/src/components/market/SubingPanel.vue`
- Create: `apps/quant-web/tests/subingPanel.test.ts`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`
- Modify: `apps/quant-web/tests/productCheck.test.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`
- Delete: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Delete: `apps/quant-web/src/components/market/SubingLifecyclePanel.vue`

### Step 2.1: Lock the SuBing panel input contract with failing tests

The panel accepts existing DTOs only:

```ts
interface SubingPanelProps {
  snapshot: SubingResearchResponse | null
  supported: boolean
  loading: boolean
  error: boolean
  currentEvents: AlertEvent[]
  currentEventStates: Record<number, EventState>
  rules: ProductAlertRuleState[]
  runtimeStatus: AlertRuntimeStatus | null
  savingRuleCodes: Set<string>
}
```

The component must not receive raw bars or indicator parameters.

Tests must prove:

- only `subing_entry_signal_v1` events are treated as SuBing Formal Events;
- resolved signal is preferred, with primary signal as fallback;
- Primary/Companion confirmation times and Factor directions are visible;
- Lifecycle stage/progress is visible inside the same panel;
- SuBing Scope uses `enabled_for_product`, never `enabled_frequencies`;
- HTDY rule state is not rendered inside the SuBing panel;
- typed unsupported/loading/error/warm-up states remain distinct;
- no formula names such as `calculateEMA` or `computeMACD` appear in the component source.

Run and confirm failure:

```bash
cd apps/quant-web
node --test tests/subingPanel.test.ts tests/productCheck.test.ts tests/alerts.test.ts
```

### Step 2.2: Implement `SubingPanel.vue`

Render one ordered flow:

```text
Formal Event / Execution Review action
→ Current Resolved or Primary Signal
→ 5m/15m Factor evidence
→ Lifecycle
→ SuBing product-level Alert switch
→ collapsed data identity/details
```

Reuse existing label utilities:

- `subingSignalLabel`
- `subingLifecycleStageLabel`
- `subingLifecycleProgressLabel`
- `executionReviewActionLabel`
- existing Factor direction/cross formatting moved from `SubingResearchSection.vue`.

Do not copy backend formula logic.

### Step 2.3: Make `ProductCheckSidebar` explicitly dispatch by Overlay

Replace generic non-SuBing fallback with an exhaustive branch:

```ts
switch (selectedOverlay) {
  case 'none':
    return 'none'
  case 'subing':
    return 'subing'
  case 'jdj_strategy':
    return 'jdj_strategy'
  case 'htdy':
    return 'htdy'
}
```

Required UI:

- common market background/participation facts may remain outside the product panel;
- SuBing branch renders exactly one `SubingPanel`;
- HTDY branch renders HTDY current observation + current frequency pair-Scope switch;
- JDJ reference branch renders reference-only explanation and no Alert switch;
- none branch renders no strategy observation or strategy Alert switch.

### Step 2.4: Preserve HTDY frequency Scope

After the existing HTDY Plan has been implemented, verify `ProductAlertRules` accepts current `frequency` and uses:

```ts
const htdyEnabled = rule.enabled_frequencies.includes(currentFrequency)
const subingEnabled = rule.enabled_for_product
```

`SubingPanel` must call the existing product-level mutation for SuBing. HTDY branch must call the pair-level mutation. Selecting an Overlay or switching frequency must not trigger either mutation.

### Step 2.5: Remove duplicate SuBing components

Move only presentation helpers needed by `SubingPanel`. Delete:

```text
SubingResearchSection.vue
SubingLifecyclePanel.vue
```

Search must show no imports of either file.

### Step 2.6: E2E

Prove:

- selecting SuBing displays one panel, not separate current/research/lifecycle regions;
- a Formal Event action is inside that panel;
- toggling SuBing calls product-level endpoint without frequency;
- selecting HTDY shows current-frequency label and calls pair endpoint;
- switching from 15m to 5m changes HTDY switch state without PUT;
- JDJ reference has no Alert mutation control.

### Step 2.7: Verify

```bash
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "SuBing|HTDY|Alert|品种工作台"
pnpm build
cd ../..
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
git diff --check
python scripts/engineering/secret_scan.py
```

### Step 2.8: Commit and PR

```bash
git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: unify SuBing product workspace"
```

Independent Review must explicitly compare SuBing and HTDY Scope semantics.

---

## Task 3: Converge the Market Overlay surface and internalize N/raw JDJ

**Lane:** Lane 2 / Terra / medium reasoning; upgrade to Sol if hidden cross-module consumers appear  
**Branch:** `refactor/market-overlay-convergence-v1` from latest `develop` after Task 2  
**Files:**

- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/utils/mainIndicators.ts`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/composables/useHistoricalResearchMarkers.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`
- Create: `apps/quant-web/tests/marketOverlayConvergence.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Modify: `services/quant-api/app/research/historical_overlay_api.py`
- Modify: `services/quant-api/app/api/market_research_overlays.py`
- Modify: `services/quant-api/tests/test_market_research_overlays_api.py`

### Step 3.1: Add failing target Overlay tests

Assert exact public ids and labels:

```ts
assert.deepEqual(
  RESEARCH_OVERLAY_DEFINITIONS.map(({ id, label }) => ({ id, label })),
  [
    { id: 'none', label: '无' },
    { id: 'subing', label: '苏冰' },
    { id: 'jdj_strategy', label: '日进斗金参考回放' },
    { id: 'htdy', label: '火天大有' },
  ],
)
```

Lock migration of old localStorage values:

```text
n_structure -> subing
jdj        -> subing
unknown    -> subing
jdj_strategy remains jdj_strategy
htdy remains htdy
```

Assert HTDY supports all formal Market frequencies after its implementation.

Run and confirm failure:

```bash
cd apps/quant-web
node --test tests/marketOverlayConvergence.test.ts tests/historicalResearchMarkers.test.ts
```

### Step 3.2: Remove Web consumers

- Remove `n_structure` and `jdj` from `ResearchOverlayId` and definitions.
- Keep stable id `jdj_strategy`; only change label.
- Remove `getNStructureHistoricalEvents` and `getJdjHistoricalEvents` from Web API.
- Remove their injected fetchers and marker branches from `useHistoricalResearchMarkers`.
- Remove imports and sync paths from `chart.vue`.
- Preserve SuBing and JDJ Strategy confirmed-window generation guards.
- Preserve HTDY local derived-data path and all-frequency capability.

### Step 3.3: Remove only the Web-owned backend projections

From the Historical Overlay router remove:

```text
/api/v1/market/research/n-structure/history
/api/v1/market/research/jdj/history
```

Retain:

```text
/api/v1/market/research/subing/history
/api/v1/market/research/jdj-strategy/history
```

Do not delete internal N/JDJ services, policies, CLI, Candidate Validation, Robustness or evidence in this Task.

Backend tests must assert removed paths return 404 and retained paths preserve exact DTOs.

### Step 3.4: Verify internal dependencies remain

Run:

```bash
git grep -n "n_structure" -- services/quant-api/app/research services/quant-api/tests/research
git grep -n "strict-before\|strict_before" -- services/quant-api/app/research/jdj services/quant-api/tests/research
```

Required: N internal reducer and JDJ dependency still exist.

### Step 3.5: Verify

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/research
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "Overlay|日进斗金|苏冰|火天大有"
pnpm build
cd ../..
git diff --check
python scripts/engineering/secret_scan.py
```

### Step 3.6: Commit and PR

```bash
git add services/quant-api/app/research/historical_overlay_api.py \
  services/quant-api/app/api/market_research_overlays.py \
  services/quant-api/tests/test_market_research_overlays_api.py \
  apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: converge Market research overlays"
```

---

## Task 4: Remove Market Attention and Market Trend Focus end to end

**Lane:** Lane 2 / Terra / medium reasoning  
**Branch:** `refactor/remove-market-attention-trend-focus` from latest `develop`  
**Files:**

- Delete: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Delete: `apps/quant-web/src/components/market/MarketFocusList.vue`
- Delete: `apps/quant-web/tests/marketFocus.test.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/tests/marketScatter.test.ts` if present
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Delete: `services/quant-api/app/market_data/market_trend_focus.py`
- Modify: `services/quant-api/app/market_data/market_radar.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Delete: `services/quant-api/tests/data_foundation/test_market_trend_focus.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

### Step 4.1: Add failing API and Web topology assertions

Backend target:

```python
response = client.get("/api/v1/market/research/trend-focus")
assert response.status_code == 404
assert "attention" not in client.get("/api/v1/market/radar").json()
```

Web target:

```ts
assert.equal(homeSource.includes('MarketAttentionList'), false)
assert.equal(homeSource.includes('MarketFocusList'), false)
assert.equal(homeSource.includes('radar.attention'), false)
```

Before deletion, run and confirm failure.

### Step 4.2: Remove consumers first

- Homepage full-market research keeps Summary + Scatter + Detail Table only.
- Remove `attention` client/type fields.
- Remove Trend Focus client/type/export even if it is not currently rendered.
- Update E2E to assert only the three retained research sections.

### Step 4.3: Remove backend projections and calculations

- Remove `/research/trend-focus` route and DTOs.
- Remove `build_market_trend_focus_snapshot` composition.
- Remove `attention` ranking/reason aggregation from Radar response.
- Preserve Radar items, summary, sector summary, freshness and typed unavailable behavior.
- Do not change threshold/formula for retained Radar facts.

### Step 4.4: Search for hidden consumers

```bash
git grep -n -E "MarketTrendFocus|market_trend_focus|trend-focus|MarketAttentionList|radar\.attention|attention:" -- . \
  ':(exclude)CHANGELOG.md'
```

Expected after implementation: no active code/test references. Historical CHANGELOG references may remain until Task 7 documentation cleanup.

### Step 4.5: Verify

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "Market|全市场研究"
pnpm build
cd ../..
git diff --check
python scripts/engineering/secret_scan.py
```

### Step 4.6: Commit and PR

```bash
git add services/quant-api/app services/quant-api/tests \
  apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: retire Market Attention and Trend Focus"
```

---

## Task 5: Retire Main Force Mirror V2 and diagnostics

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `refactor/retire-main-force-mirror-v2` from latest `develop`  
**Human Gate:** independent Review before integration  
**Files:**

- Delete: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Delete: `services/quant-api/app/market_data/main_force_mirror_v2_service.py`
- Delete: `services/quant-api/app/research/main_force/__init__.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_diagnostic.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_diagnostic_analysis.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_diagnostic_models.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_diagnostic_policy.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_diagnostic_service.py`
- Delete: `services/quant-api/app/research/main_force/main_force_mirror_v2_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Delete: `apps/quant-web/src/composables/useMainForceMirrorV2.ts`
- Delete: `apps/quant-web/src/utils/mainForceMirrorV2Presentation.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Delete: `apps/quant-web/tests/mainForceMirrorV2.test.ts`
- Delete: `apps/quant-web/e2e/main-force-mirror-v2.spec.mjs`
- Delete: all tests whose filename or test id is dedicated to `main_force_mirror_v2` or `main_force_mirror_diagnostic`, after inventory review

### Step 5.1: Prove no retained domain depends on MFM

Before deletion:

```bash
git grep -n "main_force_mirror" -- services/quant-api/app packages/quant-core apps/quant-web/src
git grep -n "MainForceMirror" -- services/quant-api/app packages/quant-core apps/quant-web/src
```

Classify every hit as one of:

```text
MFM implementation
MFM projection/export
MFM-only test
active canonical reference
unexpected retained consumer
```

If an unexpected consumer appears in SuBing, HTDY, JDJ, Alert, Runtime, Execution Review or MarketDataService, stop. Do not delete through it.

### Step 5.2: Add failing absence tests

Extend the convergence inventory test to assert:

```python
assert "main-force-mirror-v2" not in research_help
assert "main-force-mirror-diagnostic" not in research_help
assert client.get("/api/v1/market/research/main-force-mirror").status_code == 404
```

Add Web assertion:

```ts
assert.equal(chartSource.includes('useMainForceMirrorV2'), false)
assert.equal(chartSource.includes('main_force_mirror_v2'), false)
```

Confirm failure before deletion.

### Step 5.3: Remove Web and HTTP consumers

Delete Web secondary-panel state, requests and presentation. Remove Market route/schema/composition. Build must fail if any generated/type reference remains; fix only MFM-specific references.

### Step 5.4: Remove CLI and Research

Remove both CLI commands and their request/payload dispatch. Delete the complete `app/research/main_force` package and MFM Market service.

Do not modify unrelated Research commands.

### Step 5.5: Remove quant-core exports

Delete the MFM indicator module and only its registry/policy exports. Keep EMA, MACD, ATR, HTDY and generic policy helpers.

Run focused indicator tests immediately:

```bash
uv run --offline --project services/quant-api pytest -q packages/quant-core/tests
```

### Step 5.6: Remove dedicated tests and references

Delete dedicated tests only after the production symbols are gone. Do not delete shared Market/CLI tests; update them to assert the retired command/route is absent.

Search target:

```bash
git grep -n -E "main_force_mirror|MainForceMirror|MFM_V2|main-force-mirror" -- . \
  ':(exclude)CHANGELOG.md' \
  ':(exclude)docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md' \
  ':(exclude)docs/superpowers/plans/2026-08-25-architecture-convergence-v1.md'
```

Expected: no active implementation/test/canonical hits.

### Step 5.7: Verify

```bash
uv run --offline --project services/quant-api pytest -q
uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core
uv run --offline --project services/quant-api mypy services/quant-api/app packages/quant-core/guiyi_quant
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e
pnpm build
cd ../..
python scripts/engineering/secret_scan.py
git diff --check
```

### Step 5.8: Commit and PR

```bash
git add packages/quant-core services/quant-api apps/quant-web
git commit -m "refactor: retire Main Force Mirror research"
```

Review conclusion must explicitly confirm SuBing/HTDY/JDJ behavior is unchanged.

---

## Task 6: Retire Five-Candidate Dossier and Relationships

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `refactor/retire-candidate-convergence` from latest `develop`  
**Files:**

- Delete: `services/quant-api/app/research/candidate_convergence/__init__.py`
- Delete: `services/quant-api/app/research/candidate_convergence/artifact_source.py`
- Delete: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier.py`
- Delete: `services/quant-api/app/research/candidate_convergence/five_candidate_dossier_service.py`
- Delete: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships.py`
- Delete: `services/quant-api/app/research/candidate_convergence/five_candidate_relationships_service.py`
- Delete: `services/quant-api/app/research/candidate_convergence/identities.py`
- Delete: `services/quant-api/app/research/candidate_convergence/jdj_exact_overlap.py`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Delete: `services/quant-api/tests/research/test_research_cli_convergence.py`
- Delete: `services/quant-api/tests/test_five_candidate_dossier.py`
- Delete: all additional tests dedicated only to candidate dossier/relationships after inventory
- Delete: `reports/research/candidate_dossier/`
- Delete: `reports/research/candidate_relationships/`

### Step 6.1: Prove Validation/Robustness do not depend on Convergence

Run:

```bash
git grep -n "candidate_convergence" -- services/quant-api/app/research \
  services/quant-api/app/guiyi_cli services/quant-api/tests
git grep -n -E "candidate_validation|candidate_robustness" -- \
  services/quant-api/app/research services/quant-api/tests/research
```

Required:

- Candidate Validation and Robustness import no dossier/relationship service;
- source-specific SuBing/N/JDJ candidate modules remain independent;
- pending prospective artifacts do not reference dossier/relationship output as required input.

If a pending Gate consumes one of these reports, stop and reclassify that report as evidence rather than deleting it.

### Step 6.2: Add failing CLI absence tests

Update a retained CLI parser test to assert:

```python
assert "candidate-dossier" not in research_help
assert "candidate-relationships" not in research_help
assert "candidate-validation" in research_help
assert "candidate-robustness" in research_help
```

Confirm failure.

### Step 6.3: Remove CLI and composition

Remove only dossier/relationships parser entries, request classes, command dispatch, payload projections and builders. Keep Candidate Validation and Robustness unchanged.

### Step 6.4: Delete the phase-specific package and reports

Delete `candidate_convergence` and the two report roots. Do not delete:

```text
reports/research/candidate_validation
reports/research/candidate_robustness
source-specific retrospective baselines
prospective OOS schedules/evidence
```

### Step 6.5: Search and verify

```bash
git grep -n -E "candidate-dossier|candidate-relationships|candidate_convergence|five_candidate" -- . \
  ':(exclude)CHANGELOG.md' \
  ':(exclude)docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md' \
  ':(exclude)docs/superpowers/plans/2026-08-25-architecture-convergence-v1.md'

uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research \
  services/quant-api/tests/test_candidate_validation.py \
  services/quant-api/tests/test_candidate_robustness.py
```

If exact retained test filenames differ, select the repository’s existing Validation/Robustness test files returned by `find`; do not create aliases or skip the suites.

Then run:

```bash
uv run --offline --project services/quant-api pytest -q
uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests
uv run --offline --project services/quant-api mypy services/quant-api/app
python scripts/engineering/secret_scan.py
git diff --check
```

### Step 6.6: Commit and PR

```bash
git add services/quant-api reports/research
git commit -m "refactor: retire candidate convergence reports"
```

Independent Review must verify pending OOS evidence was not deleted.

---

## Task 7: Reconcile canonical docs and remove completed process artifacts

**Lane:** Lane 2 / Terra / medium reasoning  
**Branch:** `docs/convergence-v1-canonical-reconciliation` from latest `develop` after Tasks 1–6  
**Files:**

- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `TESTING.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md` only for release-facing retirement notes; do not rewrite historical entries
- Delete: `docs/CODE_REVIEW.md`
- Delete: `.github/ISSUE_TEMPLATE/config.yml`
- Delete: `.github/ISSUE_TEMPLATE/optional_backlog.md`
- Delete: `docs/superpowers/specs/2026-08-24-subing-daily-watch-v1-design.md`
- Delete: `docs/superpowers/plans/2026-08-24-subing-daily-watch-v1.md`
- Delete: `docs/superpowers/specs/2026-08-24-jdj-active60-1m-strategy-design.md`
- Delete: `docs/superpowers/plans/2026-08-24-jdj-active60-1m-strategy.md`
- Delete: `docs/superpowers/plans/2026-08-24-no-watch-reliability-v1.md`
- Conditionally delete after HTDY implementation/canonical closeout:
  - `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`
  - `docs/superpowers/plans/2026-08-25-htdy-all-frequency-active60.md`

### Step 7.1: Add documentation drift assertions

Extend `test_architecture_convergence_inventory.py` to read active canonical and assert:

```text
SuBing is described as one product with three internal projections
HTDY is described as all operational products × seven frequencies
Overlay list is exactly four
Trend Focus/Attention/MFM/Dossier/Relationships are not active modules
N and raw JDJ are internal-only
Alert still has two tables and no retry/replay/backfill/queue/order
RQAlpha remains local-only conditional keep
Execution Review roll is unchanged
```

The test must not require historical CHANGELOG entries to be erased.

### Step 7.2: Rewrite canonical by responsibility

- `STATUS.md`: current release/runtime/evidence/pending Gates only; record actual convergence integration facts, not the plan.
- `PROJECT_SOURCE.md`: stable retained product/data/API/CLI boundaries.
- `AGENTS.md`: engineering hard rules; remove retired product examples.
- `DECISIONS.md`: retain only active long-term decisions; remove retired MFM/convergence decisions and add one SuBing single-product decision.
- `ARCHITECTURE.md`: update dependency diagram to the target architecture; remove dead modules.
- `DEVELOPMENT.md`: remove commands or warnings tied only to retired surfaces.
- `TESTING.md`: remove retired suites/CLI commands; keep current domain matrices.
- `README.md`: short current entry map only.
- `CHANGELOG.md`: add retirement notes to the next unreleased section without deleting old release history.

### Step 7.3: Delete completed process artifacts

Delete the listed completed Spec/Plan files because their stable contracts have been absorbed into canonical and implementation history remains in Git.

HTDY documents may be deleted only when all are true:

```text
HTDY code integrated in develop
HTDY independent Review complete
canonical updated to implemented behavior
no pending implementation task refers to the files
```

If any condition is false, leave both files intact. Do not partially delete one.

Keep the current Architecture Convergence V1 Spec/Plan until this program is fully integrated and released; their later deletion is a separate closeout commit.

### Step 7.4: Remove redundant personal-project process files

Delete `docs/CODE_REVIEW.md` and the optional issue template after proving no active document links to them. Do not delete `AGENTS.md`, `DEVELOPMENT.md`, `TESTING.md`, `.codex` safety rules or the six active `.agents/skills`.

### Step 7.5: Reference and format verification

```bash
git grep -n -E "MarketTrendFocus|MarketAttentionList|main-force-mirror|candidate-dossier|candidate-relationships" -- \
  STATUS.md PROJECT_SOURCE.md AGENTS.md DECISIONS.md README.md TESTING.md docs .github || true

uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
python scripts/engineering/secret_scan.py
git diff --check
```

Expected active hits are limited to the current Convergence Spec/Plan and historical CHANGELOG context.

### Step 7.6: Commit and PR

```bash
git add STATUS.md PROJECT_SOURCE.md AGENTS.md DECISIONS.md README.md TESTING.md CHANGELOG.md docs .github
git commit -m "docs: reconcile architecture convergence v1"
```

Review must reject any status claim unsupported by merged code/evidence.

---

## Task 8: Run full convergence verification and close hidden references

**Lane:** Lane 3 / Sol / high reasoning / independent Review  
**Branch:** `chore/convergence-v1-verification` from latest `develop` after Tasks 1–7  
**Files:**

- Modify only tests or active references revealed by verification
- Modify: `services/quant-api/tests/engineering/test_architecture_convergence_inventory.py`
- Do not change strategy formulas or expand scope during verification

### Step 8.1: Target inventory must be green

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
```

The test must assert absence and target topology, not skip missing files.

### Step 8.2: Full backend verification

```bash
uv run --offline --project services/quant-api pytest -q
uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core
uv run --offline --project services/quant-api mypy services/quant-api/app packages/quant-core/guiyi_quant
```

Run isolated PostgreSQL suites required by the already implemented HTDY migration using the repository’s isolated DB environment. Do not connect production DB.

### Step 8.3: Focused business parity

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_subing_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/test_subing_daily_watch_api.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Required conclusions:

```text
SuBing Factor/Signal/Lifecycle parity preserved
SuBing Daily Watch contract preserved
SuBing product Scope preserved
HTDY pair Scope preserved
HTDY all-frequency capability preserved
SuBing bar-level Formal Event identity preserved
no real notification or Scope mutation executed
```

### Step 8.4: Full Web verification

```bash
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e
pnpm build
cd ../..
```

Required topology assertions:

```text
one SuBing homepage workbench
one SuBing product panel
four Overlay choices
no N/raw JDJ Web requests
no Attention/Trend Focus/MFM Web surfaces
HTDY current-frequency switch behavior intact
```

### Step 8.5: Static and secret checks

```bash
python scripts/engineering/secret_scan.py
git diff --check
git status --short
```

No untracked packet, backup directory, copied retired module or secret-bearing artifact may be created.

### Step 8.6: Independent Review

Open a new Sol/high Review session. Reviewer reads:

```text
STATUS.md
AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
Architecture Convergence V1 Spec/Plan
HTDY Spec/Plan or absorbed canonical
all task PR diffs
full verification output
```

Reviewer must separately conclude:

```text
产品收敛正确
SuBing 单一产品语义正确
HTDY approved behavior未回退
内部研究保留边界正确
删除没有破坏 pending OOS/evidence
无 main/tag/Runtime/production mutation
```

Allowed final review conclusions:

```text
允许集成 develop
要求修正后再集成
阻塞
```

### Step 8.7: Commit only verification-driven fixes

```bash
git add <only files changed to close verified gaps>
git commit -m "test: close architecture convergence v1"
```

Do not create an empty receipt commit.

---

## Task 9: Form the release candidate without crossing release or Runtime Gates

**Lane:** Lane 3 / Sol / high reasoning / Plan-only until user approval  
**Workspace:** release worktree from exact `develop` candidate  
**Human Gates:** release approval and Runtime promotion approval are separate  
**Files:** no source changes unless candidate verification finds a defect

### Step 9.1: Confirm integration topology

```bash
git fetch origin
git rev-parse origin/develop
git log --oneline --decorate -20 origin/develop
git branch --merged origin/develop
```

Confirm every approved task commit is an ancestor of exact `origin/develop` and all temporary task worktrees/merged branches are ready for cleanup.

### Step 9.2: Verify exact candidate

Repeat the Task 8 full verification on the exact clean candidate worktree. Do not use results from a moving task branch as release evidence.

### Step 9.3: Present release review only

Output:

```text
candidate SHA
retained product surface
retired surface
full test results
known pending evidence
migration required by HTDY
production operations not executed
```

Stop. Do not merge `main`, create tag, execute migration or promote Runtime.

### Step 9.4: Separate future Gates

Only after explicit user approval:

```text
release candidate → main + annotated tag
```

Then stop again. Runtime promotion, production migration, real Scope transition and real notification/canary each require their own precise approval and follow the HTDY/Runtime canonical.

---

## Final Acceptance Checklist

### SuBing

- [ ] One homepage workbench.
- [ ] One product workspace panel.
- [ ] Daily Context, Current Signal State and Formal Event remain distinct internal facts.
- [ ] No formula, calibration, lifecycle, Historical event or Alert identity drift.
- [ ] Product-level Scope unchanged.
- [ ] Execution Review action remains available from Formal Event.

### HTDY

- [ ] All operational products supported.
- [ ] `1m/5m/15m/30m/60m/1d/1w` chart observation supported.
- [ ] One switch controls current `symbol × frequency` only.
- [ ] D1/W1 post-close trigger remains.
- [ ] Same-time different frequencies can form separate Events.
- [ ] Observation-only/repainting boundaries unchanged.

### Product Surface

- [ ] Overlay list is exactly `none | subing | jdj_strategy | htdy`.
- [ ] User label is `无 | 苏冰 | 日进斗金参考回放 | 火天大有`.
- [ ] N and raw JDJ are internal-only.
- [ ] Market homepage research contains Summary + Scatter + Detail only.
- [ ] Trend Focus, Attention, MFM, Dossier and Relationships are absent from active code/API/CLI/tests/docs.

### Retained Foundations

- [ ] Canonical/Data Catalog/MDS unchanged.
- [ ] Candidate Validation/Robustness and pending OOS evidence retained.
- [ ] RQAlpha remains local-only conditional keep.
- [ ] Alert remains two-table, one-shot, no queue/retry/replay/backfill/order.
- [ ] Execution Review and roll semantics unchanged in this program.

### Gates

- [ ] No production migration executed.
- [ ] No real Scope changed.
- [ ] No real notification sent.
- [ ] No main/tag/release without approval.
- [ ] No Runtime promotion without separate approval.
- [ ] Independent Review conclusion is `允许集成 develop` before final integration.
