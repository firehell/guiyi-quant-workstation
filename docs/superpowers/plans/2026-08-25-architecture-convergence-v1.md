# Architecture Convergence V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 保留可信数据、一个 SuBing Trading Assistant、HTDY 全品种全周期观察及 `symbol × frequency` Alert、日进斗金参考回放、Alert 和 Execution Review；内部化 N/raw JDJ；删除无日常消费者的产品、API、CLI、Research 与一次性过程资产。

**Architecture:** SuBing 统一为一个用户产品和一个权威领域，但 Daily Context、Current Signal State、Formal Event 仍保持不同存储与生命周期。Web composition 统一用户流程，后端不新增跨 Market/Alert 的 mega endpoint。HTDY 继续执行既有全周期 Spec/Plan，本计划不重复其 migration、Scope、Event identity 或 Runtime trigger。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / PostgreSQL / Redis / NumPy / pytest / Vue 3 / TypeScript 6 / Naive UI / Node test / Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md`

**Required HTDY canonical:**

- `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`
- `docs/superpowers/plans/2026-08-25-htdy-all-frequency-active60.md`

---

## Global Constraints

- 本计划是 Lane 3 Program，不得做成一个巨大 PR。一个 Task = 一个会话 = 一个 task branch/worktree = 一个 PR。
- 文档基线为 `develop@fd0777672c49a856b283a0f4653519c68a35cb38`；代码任务从执行时最新 `develop` 创建。
- 用户已说明 HTDY 实现正在进行，但当前 GitHub 基线只看到已合入的 Spec/Plan。任何修改 HTDY 重叠文件的任务开始前，必须发现并保护真实在途 branch/worktree/dirty paths；不能识别则 fail-closed。
- 若 HTDY 已合入 `develop`，重叠任务从该 integration commit 之后创建；若未合入，只允许执行不触碰 HTDY 文件的 SuBing 首页任务。
- 不修改 SuBing Factor、Signal、Calibration、FormalPolicy、Lifecycle、Historical replay 或 Daily Watch 公式。
- SuBing 继续使用 product-level `scope_products`；HTDY 继续使用 `scope_product_frequencies`。不得 union、互换或降级。
- 不修改 HTDY original 公式、future-looking/repainting metadata、七周期 capability、D1/W1 `canonical_updated` trigger、Event identity 或 one-shot notification。
- 不建立 StrategyAdapter、OpportunityScore、Scope DSL、插件框架、queue、retry、replay、backfill、outbox、fallback 或逐人状态。
- 不修改 Canonical、八表 Catalog、MainContractMap、MarketDataService、RQData provider 或 Live/Historical 分界。
- 不删除 Alembic migrations、accepted policies、universe files、pending prospective OOS baseline/evidence。
- 只允许在隔离 PostgreSQL 执行 migration tests；不得执行 production migration。
- 不修改真实 Scope、owner、Topic、transport；不发送真实 PushPlus。
- 不运行 manual after-market、真实 RQAlpha smoke、Runtime switch/promotion、main release 或 tag。
- `auto_order=false` 不得改变。
- 所有行为任务使用 TDD：先写失败测试，确认失败原因，再写最小实现，再跑定向与受影响完整测试。
- 删除顺序固定为 consumer → projection/API → composition/export → domain/CLI → dedicated tests → active docs/reports。
- 隐藏 consumer、pending Gate consumer 或公式漂移一旦出现，停止当前删除任务并回到设计 Gate。
- `STATUS.md` 只记录已经发生的实现、测试、Review、integration、release、Runtime 或 evidence。

## Worktree and Integration Model

每个 Task：

```text
latest develop
→ new task branch/worktree
→ focused tests
→ self-review
→ PR to develop
→ independent Review（Lane 3）
→ user allows integration
→ merge develop
→ verify ancestry
→ clean task worktree/merged branch
```

不允许自动触及：

```text
main / tag / runtime worktree
production DB / Redis / Canonical
real Scope / real notification
```

---

## Task 0: Discover the HTDY in-flight baseline and freeze the deletion inventory

**Lane:** Lane 3 / Sol / high reasoning / Plan-only  
**Workspace:** new task worktree from latest `develop`  
**Files:** no repository mutation in this Task

### Step 0.1: Read the canonical and current tree

```bash
git status --short --branch
git worktree list --porcelain
git log --oneline --decorate -20 develop
git branch -a | grep -E 'htdy|architecture-convergence' || true
gh pr list --state open --search 'htdy' --json number,title,headRefName,baseRefName,url
```

Read:

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
Architecture Convergence V1 Spec
HTDY all-frequency Spec/Plan
```

### Step 0.2: Resolve the HTDY implementation identity

Record:

```text
exact develop SHA
exact HTDY implementation branch/worktree/PR
whether its head is an ancestor of develop
all dirty overlapping paths
```

Stop if any applies:

```text
reported HTDY work cannot be identified
multiple divergent HTDY implementations exist
uncommitted overlapping files have no clear task owner
HTDY implementation contradicts its approved Spec
```

Do not recreate or overwrite HTDY.

### Step 0.3: Produce the task sequence

Allowed sequence:

```text
Task 1 may run before HTDY integration if its file set remains isolated.
Tasks 2–8 require the HTDY implementation to be in their exact base whenever files overlap.
```

Output a read-only inventory; no commit, PR, Runtime or external mutation.

---

## Task 1: Unify the SuBing homepage into one workbench

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `feature/subing-single-home-workbench`  
**HTDY dependency:** none when restricted to the listed files  
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

### Step 1.1: Write failing state-coordination tests

The new composable contract:

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

`subingWorkbench.test.ts` must prove:

1. Formal ready-empty differs from unavailable.
2. Daily Watch unavailable does not clear a ready Formal Event.
3. Formal failure does not clear a ready Daily Watch snapshot.
4. Older Formal and Daily responses cannot overwrite newer generations.
5. Formal event-state lookup is invalidated when the item set changes.
6. `refreshOperational()` refreshes only Formal + Daily.
7. `dispose()` prevents pending responses from mutating state.
8. The composable does not re-evaluate or filter backend signal facts.

Confirm failure:

```bash
cd apps/quant-web
node --test \
  tests/subingWorkbench.test.ts \
  tests/currentFormalSignals.test.ts \
  tests/subingDailyWatch.test.ts
```

### Step 1.2: Implement by composing existing primitives

- Reuse `useCurrentFormalSignals`; do not duplicate its generation logic or rule semantics.
- Reuse `useLatestResource` for Daily Watch.
- Move page-owned event-state generation logic into `useSubingWorkbench`.
- Preserve separate loading/stale/unavailable state for Formal and Daily.
- Do not add a backend aggregate endpoint.

### Step 1.3: Create the single user-facing component

`SubingWorkbench.vue` is one top-level section:

```text
苏冰
├── 需要处理：Formal Event + Execution Review action
├── 今日观察：long/short/excluded/unavailable
└── source-specific loading/stale/unavailable
```

Required behavior:

- Formal Events render before Daily Watch.
- Daily Watch keeps target/source trading day, counts, first-six expansion and typed unavailable reasons.
- One source failure never hides the other source.
- Daily candidate opens `actual_dominant + 15m + subing`.
- Formal Event preserves current redirect to Execution Review or chart.

### Step 1.4: Replace the homepage siblings

In `pages/market/index.vue`:

- remove old component imports and page-owned formal event-state logic;
- instantiate `useSubingWorkbench` once;
- render exactly one `<SubingWorkbench>` between Runtime and full-market research;
- keep Radar and Runtime ownership unchanged;
- visibility refresh calls Runtime + SuBing workbench, not Radar.

Add topology assertions:

```ts
assert.equal(homeSource.match(/<SubingWorkbench\b/g)?.length, 1)
assert.equal(homeSource.includes('<MarketFormalSignals'), false)
assert.equal(homeSource.includes('<SubingDailyWatch'), false)
```

### Step 1.5: Update E2E

`market-research.spec.mjs` must prove:

- one top-level SuBing region;
- Formal action and Daily Watch can coexist inside it;
- each source fails independently;
- Daily candidate still enters 15m SuBing;
- full-market research remains independently expandable.

### Step 1.6: Verify and commit

```bash
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "SuBing|苏冰|Market"
pnpm build
cd ../..
python scripts/engineering/secret_scan.py
git diff --check

git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: unify SuBing homepage workbench"
```

Open PR to `develop`. Required conclusion before integration: `允许集成 develop`.

---

## Task 2: Unify the SuBing product workspace panel

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `feature/subing-single-product-panel`  
**HTDY dependency:** hard; base must contain the approved HTDY implementation  
**Files:**

- Create: `apps/quant-web/src/components/market/SubingPanel.vue`
- Create: `apps/quant-web/tests/subingPanel.test.ts`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`
- Modify: `apps/quant-web/tests/alerts.test.ts`
- Modify: `apps/quant-web/tests/productCurrentAlertEvents.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`
- Delete: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Delete: `apps/quant-web/src/components/market/SubingLifecyclePanel.vue`

### Step 2.1: Write failing panel-contract tests

Use existing DTOs only:

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

Tests must prove:

- only `subing_entry_signal_v1` events are SuBing Formal Events;
- resolved signal is preferred, primary signal is fallback;
- Primary/Companion evidence and confirmation times display;
- Lifecycle is inside the same panel;
- SuBing switch reads `enabled_for_product`, never `enabled_frequencies`;
- HTDY rule does not render inside the SuBing panel;
- unsupported/loading/error/warm-up remain distinct;
- component source contains no browser formula implementation.

Confirm failure:

```bash
cd apps/quant-web
node --test \
  tests/subingPanel.test.ts \
  tests/alerts.test.ts \
  tests/productCurrentAlertEvents.test.ts
```

### Step 2.2: Implement `SubingPanel.vue`

Fixed order:

```text
Formal Event / Execution Review action
→ Resolved or Primary Signal
→ 5m/15m Factor evidence
→ Lifecycle
→ SuBing product-level Alert switch
→ collapsed identity/details
```

Reuse existing label utilities and formatting from the two deleted SuBing components. Do not recalculate Factor, Signal or Lifecycle.

### Step 2.3: Make Overlay dispatch exhaustive

Replace any generic “other Overlay = HTDY” fallback with:

```ts
switch (selectedOverlay) {
  case 'none':
  case 'subing':
  case 'jdj_strategy':
  case 'htdy':
}
```

- SuBing renders one `SubingPanel`.
- HTDY renders current observation and current-frequency pair Scope.
- JDJ Strategy renders reference-only facts and no Alert switch.
- none renders no strategy Alert control.

### Step 2.4: Preserve the two Scope modes

After HTDY integration:

```ts
const subingEnabled = rule.enabled_for_product
const htdyEnabled = rule.enabled_frequencies.includes(currentFrequency)
```

- SuBing calls product-level mutation.
- HTDY calls pair-level mutation.
- selecting Overlay or changing frequency never performs PUT.

### Step 2.5: Delete duplicated SuBing presentation

Move presentation helpers only, then delete:

```text
SubingResearchSection.vue
SubingLifecyclePanel.vue
```

`git grep` must show no imports.

### Step 2.6: E2E and backend parity

Prove:

- one SuBing panel;
- SuBing product-level endpoint has no frequency;
- HTDY pair endpoint includes frequency;
- HTDY frequency change updates read state without PUT;
- JDJ reference has no Alert mutation;
- current Formal Event action remains available.

Run:

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
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py
python scripts/engineering/secret_scan.py
git diff --check
```

### Step 2.7: Commit and PR

```bash
git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: unify SuBing product workspace"
```

Independent Review must explicitly compare SuBing and HTDY Scope semantics.

---

## Task 3: Converge the public Overlay surface and internalize N/raw JDJ

**Lane:** Lane 2 / Terra / medium reasoning; upgrade to Sol if hidden consumers appear  
**Branch:** `refactor/market-overlay-convergence-v1`  
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

### Step 3.1: Write failing target tests

Exact public definitions:

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

Legacy preference migration:

```text
n_structure → subing
jdj         → subing
unknown     → subing
jdj_strategy and htdy remain unchanged
```

HTDY must retain all seven formal frequencies.

Confirm failure:

```bash
cd apps/quant-web
node --test tests/marketOverlayConvergence.test.ts tests/historicalResearchMarkers.test.ts
```

### Step 3.2: Remove Web consumers

- remove `n_structure` and raw `jdj` from public types/definitions/options;
- keep stable id `jdj_strategy`; change only its label;
- remove `getNStructureHistoricalEvents` and `getJdjHistoricalEvents` from Web API;
- remove their injected fetchers and marker branches;
- preserve SuBing and JDJ Strategy confirmed-window/generation guards;
- preserve HTDY local derived-data and all-frequency capability.

### Step 3.3: Remove only Web-owned backend projections

Remove routes:

```text
/api/v1/market/research/n-structure/history
/api/v1/market/research/jdj/history
```

Retain:

```text
/api/v1/market/research/subing/history
/api/v1/market/research/jdj-strategy/history
```

Do not delete N/JDJ reducers, policies, CLI, Validation, Robustness or evidence.

Backend tests assert removed routes are 404 and retained DTOs are unchanged.

### Step 3.4: Verify internal dependencies

```bash
git grep -n "n_structure" -- services/quant-api/app/research services/quant-api/tests/research
git grep -n -E "strict-before|strict_before" -- \
  services/quant-api/app/research/jdj services/quant-api/tests/research

uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research_overlays_api.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py

cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "Overlay|日进斗金|苏冰|火天大有"
pnpm build
cd ../..
python scripts/engineering/secret_scan.py
git diff --check
```

### Step 3.5: Commit and PR

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
**Branch:** `refactor/remove-market-attention-trend-focus`  
**Files:**

- Delete: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Delete: `apps/quant-web/src/components/market/MarketFocusList.vue`
- Delete: `apps/quant-web/tests/marketFocus.test.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/tests/marketScatter.test.ts`
- Modify: `apps/quant-web/e2e/market-radar.spec.mjs`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Delete: `services/quant-api/app/market_data/market_trend_focus.py`
- Modify: `services/quant-api/app/market_data/market_radar.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/api/market.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Delete: `services/quant-api/tests/data_foundation/test_market_trend_focus.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

### Step 4.1: Write failing absence tests

Backend:

```python
assert client.get("/api/v1/market/research/trend-focus").status_code == 404
assert "attention" not in client.get("/api/v1/market/radar").json()
```

Web:

```ts
assert.equal(homeSource.includes('MarketAttentionList'), false)
assert.equal(homeSource.includes('MarketFocusList'), false)
assert.equal(homeSource.includes('radar.attention'), false)
```

Confirm failure before implementation.

### Step 4.2: Remove consumers, then providers

Final full-market research:

```text
MarketSummaryStrip
MarketScatter
MarketDetailTable
```

Remove Attention and Trend Focus clients/types first, then route/schema/composition/read model and dedicated tests. Preserve Radar items, summary, sectors, freshness and typed unavailable semantics.

### Step 4.3: Search and verify

```bash
git grep -n -E "MarketTrendFocus|market_trend_focus|trend-focus|MarketAttentionList|radar\.attention" -- . \
  ':(exclude)CHANGELOG.md'

uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation

cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e -- --grep "Market|全市场研究"
pnpm build
cd ../..
python scripts/engineering/secret_scan.py
git diff --check
```

Expected active code/test hits: none.

### Step 4.4: Commit and PR

```bash
git add services/quant-api/app services/quant-api/tests \
  apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "refactor: retire Market Attention and Trend Focus"
```

---

## Task 5: Retire Main Force Mirror V2 and diagnostics

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `refactor/retire-main-force-mirror-v2`  
**Human Gate:** independent Review  
**Files:**

- Delete: `packages/quant-core/guiyi_quant/indicators/main_force_mirror_v2.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/__init__.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/registry.py`
- Modify: `packages/quant-core/guiyi_quant/indicators/policy.py`
- Delete: `services/quant-api/app/market_data/main_force_mirror_v2_service.py`
- Delete: `services/quant-api/app/research/main_force/`
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
- Delete: `services/quant-api/tests/test_main_force_mirror_v2.py`
- Delete: `services/quant-api/tests/test_main_force_mirror_v2_audit.py`
- Delete: `services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py`
- Delete: `services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py`
- Delete: `services/quant-api/tests/research/test_main_force_mirror_diagnostic_analysis.py`
- Delete: `services/quant-api/tests/research/test_main_force_mirror_diagnostic_contract.py`
- Delete: `tests/fixtures/main_force_mirror_v2_golden.json`

### Step 5.1: Prove no retained consumer exists

```bash
git grep -n -E "main_force_mirror|MainForceMirror|MFM_V2|main-force-mirror" -- \
  services/quant-api/app packages/quant-core apps/quant-web/src
```

Classify every hit. Stop if SuBing, HTDY, JDJ, Alert, Runtime, Execution Review or core MarketDataService depends on MFM output.

### Step 5.2: Write failing absence tests

Retained API/CLI tests must assert:

```python
assert client.get("/api/v1/market/research/main-force-mirror").status_code == 404
assert "main-force-mirror-v2" not in research_help
assert "main-force-mirror-diagnostic" not in research_help
```

Web source test:

```ts
assert.equal(chartSource.includes('useMainForceMirrorV2'), false)
assert.equal(chartSource.includes('main_force_mirror_v2'), false)
```

### Step 5.3: Delete consumer-to-provider

Order:

```text
Web panel/composable/types/tests
→ Market API/schema/composition
→ research CLI/composition
→ app.research.main_force
→ Market service
→ quant-core module/exports
→ dedicated tests/golden fixture
```

Keep EMA/MACD/ATR/HTDY and generic policy helpers.

### Step 5.4: Search and verify

```bash
git grep -n -E "main_force_mirror|MainForceMirror|MFM_V2|main-force-mirror" -- . \
  ':(exclude)CHANGELOG.md' \
  ':(exclude)docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md' \
  ':(exclude)docs/superpowers/plans/2026-08-25-architecture-convergence-v1.md'

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

Expected active hits: none. Historical CHANGELOG is exempt.

### Step 5.5: Commit and PR

```bash
git add packages/quant-core services/quant-api apps/quant-web tests/fixtures
git commit -m "refactor: retire Main Force Mirror research"
```

Review must explicitly confirm SuBing/HTDY/JDJ behavior is unchanged.

---

## Task 6: Retire Five-Candidate Dossier and Relationships

**Lane:** Lane 3 / Sol / high reasoning / Plan-then-execute  
**Branch:** `refactor/retire-candidate-convergence`  
**Files:**

- Delete: `services/quant-api/app/research/candidate_convergence/`
- Modify: `services/quant-api/app/research/composition.py`
- Modify: `services/quant-api/app/guiyi_cli/research_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/research_requests.py`
- Modify: `services/quant-api/app/guiyi_cli/research_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/research_payloads.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Delete: `services/quant-api/tests/research/test_research_cli_convergence.py`
- Delete: `services/quant-api/tests/test_five_candidate_dossier.py`
- Delete: `services/quant-api/tests/test_five_candidate_relationships.py`
- Modify: `services/quant-api/tests/research/test_research_cli_parser_requests.py`
- Modify: `services/quant-api/tests/test_research_composition.py`
- Delete: `reports/research/candidate_dossier/`
- Delete: `reports/research/candidate_relationships/`

### Step 6.1: Prove retained research independence

```bash
git grep -n "candidate_convergence" -- services/quant-api/app/research \
  services/quant-api/app/guiyi_cli services/quant-api/tests
git grep -n -E "candidate_validation|candidate_robustness" -- \
  services/quant-api/app/research services/quant-api/tests/research
```

Stop if pending prospective OOS or Validation/Robustness requires dossier/relationship output.

### Step 6.2: Write failing CLI absence tests

In retained parser tests:

```python
assert "candidate-dossier" not in research_help
assert "candidate-relationships" not in research_help
assert "candidate-validation" in research_help
assert "candidate-robustness" in research_help
```

Confirm failure.

### Step 6.3: Remove only phase-specific convergence

Delete dossier/relationship CLI dispatch, builders, package and report roots. Preserve:

```text
app.research.subing / n_structure / jdj candidate validation
app.research.robustness
reports/research/candidate_validation
reports/research/candidate_robustness
pending prospective OOS evidence
```

### Step 6.4: Verify retained suites

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/research/test_research_cli_candidate.py \
  services/quant-api/tests/research/test_research_cli_parser_requests.py \
  services/quant-api/tests/research/test_subing_candidate_validation_service.py \
  services/quant-api/tests/research/test_n_candidate_validation_service.py \
  services/quant-api/tests/research/test_jdj_candidate_validation_service.py \
  services/quant-api/tests/test_multi_candidate_robustness_policy.py \
  services/quant-api/tests/test_multi_candidate_robustness.py \
  services/quant-api/tests/research/test_multi_candidate_robustness_service.py \
  services/quant-api/tests/test_jdj_robustness.py \
  services/quant-api/tests/research/test_jdj_robustness_service.py \
  services/quant-api/tests/test_research_composition.py

uv run --offline --project services/quant-api pytest -q
uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests
uv run --offline --project services/quant-api mypy services/quant-api/app
python scripts/engineering/secret_scan.py
git diff --check
```

Search:

```bash
git grep -n -E "candidate-dossier|candidate-relationships|candidate_convergence|five_candidate" -- . \
  ':(exclude)CHANGELOG.md' \
  ':(exclude)docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md' \
  ':(exclude)docs/superpowers/plans/2026-08-25-architecture-convergence-v1.md'
```

Expected active hits: none.

### Step 6.5: Commit and PR

```bash
git add services/quant-api reports/research
git commit -m "refactor: retire candidate convergence reports"
```

Independent Review must verify no pending OOS baseline/evidence was deleted.

---

## Task 7: Reconcile canonical docs and remove completed process artifacts

**Lane:** Lane 2 / Terra / medium reasoning  
**Branch:** `docs/convergence-v1-canonical-reconciliation`  
**Files:**

- Modify: `STATUS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `AGENTS.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `TESTING.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md` only by adding next-release retirement notes
- Delete: `docs/CODE_REVIEW.md`
- Delete: `.github/ISSUE_TEMPLATE/config.yml`
- Delete: `.github/ISSUE_TEMPLATE/optional_backlog.md`
- Delete: `docs/superpowers/specs/2026-08-24-subing-daily-watch-v1-design.md`
- Delete: `docs/superpowers/plans/2026-08-24-subing-daily-watch-v1.md`
- Delete: `docs/superpowers/specs/2026-08-24-jdj-active60-1m-strategy-design.md`
- Delete: `docs/superpowers/plans/2026-08-24-jdj-active60-1m-strategy.md`
- Delete: `docs/superpowers/plans/2026-08-24-no-watch-reliability-v1.md`
- Conditionally delete as one pair after HTDY closeout:
  - `docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md`
  - `docs/superpowers/plans/2026-08-25-htdy-all-frequency-active60.md`

### Step 7.1: Add a canonical drift test

Create:

- `services/quant-api/tests/engineering/test_architecture_convergence_inventory.py`

The test reads active canonical and asserts:

```text
SuBing = one product with three internal projections
HTDY = operational universe × seven frequencies
Overlay list = four
Trend Focus/Attention/MFM/Dossier/Relationships are not active
N/raw JDJ are internal-only
Alert remains two-table, one-shot, no retry/replay/backfill/queue/order
RQAlpha remains local-only conditional keep
Execution Review roll is unchanged
```

Confirm the test fails before canonical reconciliation.

### Step 7.2: Rewrite each canonical by responsibility

- `STATUS.md`: current release/runtime/evidence/pending Gates only.
- `PROJECT_SOURCE.md`: stable retained product/data/API/CLI boundaries.
- `AGENTS.md`: engineering hard rules; remove retired product examples.
- `DECISIONS.md`: remove retired MFM/convergence decisions; add SuBing single-product decision.
- `ARCHITECTURE.md`: target dependency graph; no dead modules.
- `DEVELOPMENT.md`: no retired commands or duplicate process.
- `TESTING.md`: only existing tests and commands.
- `README.md`: current short entry map.
- `CHANGELOG.md`: preserve history; add retirement notes only.

### Step 7.3: Delete completed process artifacts

Delete the listed completed Spec/Plan files after their stable contracts have been absorbed into canonical.

Delete HTDY Spec/Plan only when all are true:

```text
HTDY code integrated in develop
independent Review complete
canonical reflects implemented behavior
no pending implementation task references either file
```

If any condition is false, keep both. Do not delete only one.

Keep this Architecture Convergence V1 Spec/Plan until the whole program is integrated and released; later closeout is a separate commit.

### Step 7.4: Remove redundant personal-project process files

Delete `docs/CODE_REVIEW.md` and `.github/ISSUE_TEMPLATE/*` only after `git grep` proves no active references. Keep `AGENTS.md`, `DEVELOPMENT.md`, `TESTING.md`, `.codex` safety rules and six active `.agents/skills`.

### Step 7.5: Verify and commit

```bash
git grep -n -E "MarketTrendFocus|MarketAttentionList|main-force-mirror|candidate-dossier|candidate-relationships" -- \
  STATUS.md PROJECT_SOURCE.md AGENTS.md DECISIONS.md README.md TESTING.md docs .github || true

uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
python scripts/engineering/secret_scan.py
git diff --check

git add STATUS.md PROJECT_SOURCE.md AGENTS.md DECISIONS.md README.md TESTING.md CHANGELOG.md docs .github \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
git commit -m "docs: reconcile architecture convergence v1"
```

Review must reject any status claim unsupported by integrated code/evidence.

---

## Task 8: Full verification, independent Review, and release-candidate handoff

**Lane:** Lane 3 / Sol / high reasoning / independent Review  
**Branch:** `chore/convergence-v1-verification` from exact latest `develop`  
**Files:** only verification-driven fixes; no new feature scope

### Step 8.1: Run the target inventory

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/engineering/test_architecture_convergence_inventory.py
```

The test must fail on missing target behavior and must not skip missing paths.

### Step 8.2: Run full backend quality

```bash
uv run --offline --project services/quant-api pytest -q
uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core
uv run --offline --project services/quant-api mypy services/quant-api/app packages/quant-core/guiyi_quant
```

Run the existing isolated PostgreSQL HTDY migration suite using only the repository’s isolated DB environment. Do not connect production DB.

### Step 8.3: Run focused SuBing/HTDY/Alert parity

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_notification_dispatcher.py \
  services/quant-api/tests/data_foundation/test_market_api.py \
  services/quant-api/tests/data_foundation/test_subing_read_service.py \
  services/quant-api/tests/data_foundation/test_subing_daily_watch.py \
  services/quant-api/tests/test_subing_daily_watch_api.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Required conclusions:

```text
SuBing Factor/Signal/Lifecycle parity preserved
Daily Watch contract preserved
SuBing product Scope preserved
HTDY pair Scope and seven-frequency capability preserved
SuBing bar-level Formal Event identity preserved
no real notification or Scope mutation executed
```

### Step 8.4: Run full Web verification

```bash
cd apps/quant-web
node --test tests/*.test.ts
pnpm test:e2e
pnpm build
cd ../..
```

Required topology:

```text
one SuBing homepage workbench
one SuBing product panel
four public Overlays
no N/raw JDJ Web request
no Attention/Trend Focus/MFM Web surface
HTDY current-frequency Scope behavior intact
```

### Step 8.5: Static and secret checks

```bash
python scripts/engineering/secret_scan.py
git diff --check
git status --short
```

No backup directory, copied retired module, receipt packet or secret-bearing artifact.

### Step 8.6: Independent Review

Open a new Sol/high Review session. Reviewer reads:

```text
STATUS.md
AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
Architecture Convergence V1 Spec/Plan
HTDY canonical
all task PR diffs
full verification output
```

Reviewer separately concludes:

```text
产品收敛正确
SuBing 单一产品语义正确
HTDY approved behavior未回退
内部研究保留边界正确
pending OOS/evidence未被误删
未触及 main/tag/Runtime/production mutation
```

Allowed result:

```text
允许集成 develop
要求修正后再集成
阻塞
```

### Step 8.7: Form the candidate, then stop

After approved task integration:

```bash
git fetch origin
git rev-parse origin/develop
git log --oneline --decorate -20 origin/develop
git branch --merged origin/develop
```

Repeat full verification on an exact clean candidate worktree and report:

```text
candidate SHA
retained product surface
retired surface
full test results
known pending evidence
HTDY migration requirement
production operations not executed
```

Stop. Do not merge `main`, create tag, run production migration, modify real Scope, send notification or promote Runtime.

Release and Runtime remain two separate future Gates:

```text
user release approval → main + annotated tag
separate user Runtime approval → exact-tag Runtime promotion
```

---

## Final Acceptance Checklist

### SuBing

- [ ] One homepage workbench.
- [ ] One product workspace panel.
- [ ] Daily Context, Current Signal State and Formal Event remain distinct internal facts.
- [ ] No formula, calibration, lifecycle, Historical Event or Alert identity drift.
- [ ] Product-level Scope unchanged.
- [ ] Execution Review action remains available.

### HTDY

- [ ] All operational products supported.
- [ ] `1m/5m/15m/30m/60m/1d/1w` chart observation supported.
- [ ] One switch controls current `symbol × frequency` only.
- [ ] D1/W1 post-close trigger remains.
- [ ] Same-time different frequencies can form separate Events.
- [ ] Observation-only/repainting boundaries unchanged.

### Product Surface

- [ ] Overlay ids are exactly `none | subing | jdj_strategy | htdy`.
- [ ] Labels are exactly `无 | 苏冰 | 日进斗金参考回放 | 火天大有`.
- [ ] N and raw JDJ are internal-only.
- [ ] Full-market research contains Summary + Scatter + Detail only.
- [ ] Trend Focus, Attention, MFM, Dossier and Relationships are absent from active code/API/CLI/tests/docs.

### Retained Foundations

- [ ] Canonical/Catalog/MDS unchanged.
- [ ] Candidate Validation/Robustness and pending OOS evidence retained.
- [ ] RQAlpha remains local-only conditional keep.
- [ ] Alert remains two-table, one-shot, no queue/retry/replay/backfill/order.
- [ ] Execution Review roll is unchanged in this program.

### Gates

- [ ] No production migration executed.
- [ ] No real Scope changed.
- [ ] No real notification sent.
- [ ] No main/tag/release without approval.
- [ ] No Runtime promotion without separate approval.
- [ ] Independent Review returns `允许集成 develop` before final integration.
