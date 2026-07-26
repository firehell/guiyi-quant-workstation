# Web V1 Research Workspace Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变数据、指标、策略、信号、回测和 Runtime 语义的前提下，把 Web V1 收口为信息清晰、交互稳定、可每日使用的个人期货研究工作台。

**Architecture:** 保留既有 Vue/Naive UI/Market 状态机与 FastAPI 契约，只增加纯展示函数、渐进式 evidence disclosure、质量影响解释和共享视觉 token。Market 先完成资格/证据分层，再收口 Kline/右栏；其他页面只复用共享视觉与交互模式，不新增业务能力。

**Tech Stack:** Vue 3、TypeScript、Naive UI、Lightweight Charts、Node test runner、Playwright、Vite。

## Global Constraints

- V1 定位是本地单用户研究工作台，不是交易终端。
- 不新增 API、migration、数据库/Parquet/Profile 写入、Runtime 部署、worker、scheduler 或通知。
- Browser/Research、Profile fail-closed、historical/live、actual/continuous 和 lineage 对账保持不变。
- warning/failed/conflict 不隐藏、不静默选择文件，物理路径与 secret 不回显。
- HTDY original 保持 historical/browser observation-only；不改变 Golden、公式、policy 或 Stage 5 rejection。
- 每个产品行为先写失败测试并确认预期失败，再做最小实现。
- 每步精确提交；不 push、merge 到 main 或 deploy。

---

### Task 0: Freeze Baseline and Collision Matrix

**Files:**
- Create: `docs/tasks/WEB-V1-14-00-BASELINE-AND-COLLISION-AUDIT.md`
- Create: `docs/superpowers/plans/2026-07-26-web-v1-14-research-workspace-polish.md`

**Interfaces:**
- Consumes: `main@1805af2e`、WEB-V1-12/13 文档、HTDY Step 1 checkpoint、用户开发手册。
- Produces: 允许/禁止路径、碰撞矩阵、基线测试和截图事实。

- [ ] **Step 1: 核对 Git 与 worktree 身份**

Run:

```bash
git -c core.fsmonitor=false status --short --branch
git rev-parse HEAD
git worktree list --porcelain
```

Expected: 当前分支为 `codex/v1-web-research-workspace-polish`，基线为 `1805af2e`。

- [ ] **Step 2: 核对 HTDY Step 1 overlap**

Run:

```bash
git diff --name-only origin/main...codex/v1-htdy-realtime-closure
git log --oneline origin/main..codex/v1-htdy-realtime-closure
```

Expected: 明确列出 `KlineChart.vue`、`indicators.ts`、`mainIndicators.ts` 与 HTDY tests。

- [ ] **Step 3: 运行 Web 基线**

Run:

```bash
cd apps/quant-web
npm test
npm run build
npm run dev -- --host 127.0.0.1 --port 5174
npm run test:e2e
```

Expected: unit/build/mock E2E 通过；浏览器需要隔离 Vite 已启动。

- [ ] **Step 4: 生成三档截图并记录 overflow/console**

Capture Market/Signal/Review/Backtest/Data/Runtime at `1440x900`、`1280x720`、`1024x768`; record visible issues without editing product code.

- [ ] **Step 5: 提交 Step 0 文档**

```bash
git add docs/tasks/WEB-V1-14-00-BASELINE-AND-COLLISION-AUDIT.md \
  docs/superpowers/plans/2026-07-26-web-v1-14-research-workspace-polish.md
git diff --cached --check
git commit -m "docs: inventory Web V1 research workspace polish"
```

### Task 1: Classify JM Continuous 1D Read-only Behavior

**Files:**
- Create: `docs/tasks/WEB-V1-14-JM-1D-DIAGNOSIS.md`
- Test only if frontend defect is confirmed: `apps/quant-web/tests/barTime.test.ts`

**Interfaces:**
- Consumes: GET-only Market coverage/bars/indicators/macd responses.
- Produces: one of `BROWSER_MULTI_FILE_WARNING_EXPECTED`、`PROFILE_OR_ASSET_DATA_TASK_REQUIRED`、`FRONTEND_DAILY_TIME_KEY_FIX_REQUIRED`、`BACKEND_DEDUPE_TASK_REQUIRED`.

- [ ] **Step 1: 启动只读候选 API**

Use the project environment without printing it. Start one Uvicorn process on `127.0.0.1:8010` with:

```text
PGOPTIONS=-c default_transaction_read_only=on
workers=1
reload=false
```

Do not run Alembic, worker, scheduler or notification.

- [ ] **Step 2: 验证事务只读和方法白名单**

Run a read-only database probe that prints only `default_transaction_read_only` and `transaction_read_only`; browser/API requests must be GET/HEAD/OPTIONS only.

- [ ] **Step 3: 执行对照矩阵**

Query:

```text
jm.MAIN 1d browser no profile
jm.MAIN 1d research legal profile
JM2609 1d browser
JM2609 1d research legal profile
jm.MAIN 15m browser/research
one other passed product 1d browser/research
```

Record status, quality, conflict counts, lineage IDs/versions/source intervals and coverage; do not record physical paths.

- [ ] **Step 4: 如果确认前端 1D 缺陷，先写失败测试**

Add a literal fixture to `barTime.test.ts` for the exact duplicate/timezone/trading-day behavior, run:

```bash
node --test apps/quant-web/tests/barTime.test.ts
```

Expected: FAIL for the confirmed frontend reason. If API/data is the cause, do not edit product code.

- [ ] **Step 5: 写诊断文档并提交**

```bash
git add docs/tasks/WEB-V1-14-JM-1D-DIAGNOSIS.md apps/quant-web/tests/barTime.test.ts
git diff --cached --check
git commit -m "docs: classify JM continuous daily data warning"
```

Omit `barTime.test.ts` from `git add` when no frontend defect is confirmed.

### Task 2: Close Dark-theme Control Contrast

**Files:**
- Modify: `apps/quant-web/src/styles/tokens.css`
- Modify: `apps/quant-web/src/styles/theme.ts`
- Modify: `apps/quant-web/src/style.css`
- Create: `apps/quant-web/tests/themeContract.test.ts`
- Modify: `apps/quant-web/e2e/run-mock-smoke.mjs`

**Interfaces:**
- Consumes: existing `--gy-*` token system and Naive UI `GlobalThemeOverrides`.
- Produces: control state tokens and Naive UI overrides for selected/hover/disabled/focus states.

- [ ] **Step 1: 写失败的 theme contract tests**

Test literal behavior:

```text
RadioButton buttonColorActive != textColorDisabled
RadioButton textColorActive has a light on-accent value
Select peers use the same selected surface/text contract
Tabs active text and focus remain visible
```

Run:

```bash
cd apps/quant-web
node --test tests/themeContract.test.ts
```

Expected: FAIL because the required component overrides/tokens are absent.

- [ ] **Step 2: 添加唯一 token 与 theme overrides**

Add `--gy-control-*`、`--gy-surface-*`、`--gy-text-on-accent`; extend only fields supported by installed Naive UI types for Radio/RadioButton/Button/Select/Tabs/Tag/Alert/Switch/DatePicker/Input/DataTable/Drawer/Popover/Menu.

- [ ] **Step 3: 增加浏览器 selected-state 回归**

In mock E2E, inspect computed color/background of Market RadioButtons and assert active text does not equal disabled/dark text. Verify keyboard focus remains visible.

- [ ] **Step 4: 验证并提交**

```bash
cd apps/quant-web
node --test tests/themeContract.test.ts
npm test
npm run build
npm run test:e2e
git add src/styles/tokens.css src/styles/theme.ts src/style.css \
  tests/themeContract.test.ts e2e/run-mock-smoke.mjs
git diff --cached --check
git commit -m "fix(web): close dark control contrast"
```

### Task 3: Separate Market Context, Qualification and Evidence

**Files:**
- Create: `apps/quant-web/src/utils/marketEvidencePresentation.ts`
- Create: `apps/quant-web/tests/marketEvidencePresentation.test.ts`
- Create: `apps/quant-web/src/components/market/MarketQualificationSummary.vue`
- Create: `apps/quant-web/src/components/market/MarketEvidenceDrawer.vue`
- Modify: `apps/quant-web/src/components/market/MarketContextBar.vue`
- Modify: `apps/quant-web/src/components/market/MarketEvidenceStrip.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/e2e/fixtures/mockApi.mjs`
- Modify: `apps/quant-web/e2e/run-mock-smoke.mjs`

**Interfaces:**
- Consumes: current coverage, quality and `MarketLineage`.
- Produces:

```ts
summarizeDataVersion(
  rawVersion: string | null | undefined,
  dataVersions: string[],
  assetCount: number,
): string

buildMarketQualificationPresentation(input): {
  label: string
  tone: 'success' | 'warning' | 'error' | 'info'
  summary: string
}
```

- [ ] **Step 1: 写纯函数失败测试**

Cover literals for `YYYYMMDD + vN`, multiple dates, underscores, Chinese paths, multi-asset latest date, unknown value and empty value. Expected summaries must be hand-derived and raw values must remain separate.

- [ ] **Step 2: 运行 RED**

```bash
cd apps/quant-web
node --test tests/marketEvidencePresentation.test.ts
```

Expected: FAIL because module/functions do not exist.

- [ ] **Step 3: 实现最小 presentation utility**

Parse only recognized dates/version tokens. Return `版本已绑定` when semantics cannot be safely inferred; never truncate into a false label.

- [ ] **Step 4: 实现 Context/Qualification/Evidence components**

Keep all mode emits and URL state untouched. Default UI shows research object, role, period, mode, qualification, quality and latest time; drawer retains provider, data role, raw version(s), Profile ID, file IDs, source intervals, lineage token/checksum summaries and coverage.

- [ ] **Step 5: 修复 mock lineage shape**

Make indicator/MACD mock responses mirror the bars lineage shape so the baseline no longer shows caught `lineage_token` TypeErrors.

- [ ] **Step 6: 增加 E2E 回归**

Assert qualification is visible, raw version is absent from primary row, evidence drawer opens, raw value is present inside, and no visible `TypeError` alert exists.

- [ ] **Step 7: 验证并提交**

```bash
cd apps/quant-web
node --test tests/marketEvidencePresentation.test.ts
npm test
npm run build
npm run test:e2e
git add src/utils/marketEvidencePresentation.ts \
  src/components/market/MarketQualificationSummary.vue \
  src/components/market/MarketEvidenceDrawer.vue \
  src/components/market/MarketContextBar.vue \
  src/components/market/MarketEvidenceStrip.vue \
  src/pages/market/chart.vue tests/marketEvidencePresentation.test.ts \
  e2e/fixtures/mockApi.mjs e2e/run-mock-smoke.mjs
git diff --cached --check
git commit -m "feat(web): separate Market qualification and evidence"
```

### Task 4: Explain Data-quality Impact Without Duplicating Risk

**Files:**
- Create: `apps/quant-web/src/utils/marketQualityPresentation.ts`
- Create: `apps/quant-web/tests/marketQualityPresentation.test.ts`
- Create: `apps/quant-web/src/components/market/MarketDataQualityCard.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/e2e/fixtures/mockApi.mjs`
- Modify: `apps/quant-web/e2e/run-mock-smoke.mjs`

**Interfaces:**
- Consumes: quality status/reasons/conflict count/profile/lineage readiness.
- Produces:

```ts
buildMarketQualityImpact(input): {
  severity: 'warning' | 'error'
  title: string
  reasons: string[]
  allowed: string[]
  blocked: string[]
  actions: Array<'evidence' | 'profile' | 'actual'>
}
```

- [ ] **Step 1: 写 warning/failed/conflict/Profile 缺失失败测试**

Tests must ensure failed never downgrades to warning, Browser warning remains viewable, research remains blocked, and physical paths are removed.

- [ ] **Step 2: 实现纯 presentation function 与 card**

The full page card owns cause/impact/allowed/blocked/actions. Only show actions valid for the current state.

- [ ] **Step 3: 收敛 Kline 风险标记**

Replace the full duplicate conflict banner with a compact accessible marker that opens/focuses the page card. Keep HTDY repaint risk in a separate region.

- [ ] **Step 4: 增加 conflict E2E**

Use a complete warning fixture with `cross_file_conflicts=20`; assert one full quality card, one compact chart marker, visible “仅观察/严格研究阻断”, no path leakage and separate HTDY warning.

- [ ] **Step 5: 验证并提交**

Run focused tests, full unit/build/mock E2E and HTDY tests, then commit only Task 4 files.

### Task 5: Integrate HTDY Step 1 and Polish the Kline Workbench

**Files:**
- Integrate from: `codex/v1-htdy-realtime-closure@4cbb769e`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/MarketRightRail.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/utils/marketRightRail.ts`
- Modify: `apps/quant-web/tests/marketRightRail.test.ts`
- Modify: `apps/quant-web/e2e/run-mock-smoke.mjs`

**Interfaces:**
- Consumes: HTDY Golden/policy and current bars/EMA/MACD/ATR/signal/quality/lineage.
- Produces: “盘面” first-tab label, grouped deterministic facts, aligned quote/control/readout layout.

- [ ] **Step 1: 集成已提交 HTDY checkpoint**

Merge/cherry-pick the two HTDY closure commits into this feature branch. Resolve only Web overlap; do not absorb the separate realtime-alert branch.

- [ ] **Step 2: 运行 HTDY 回归 before polish**

```bash
cd apps/quant-web
node --test tests/htdyStep1Golden.test.ts tests/indicators.test.ts tests/mainIndicators.test.ts
```

Expected: PASS before new Kline edits.

- [ ] **Step 3: 写右栏与请求不变失败测试**

Assert the first tab displays “盘面”, keeps the persisted internal key compatible, and tab switching does not issue bars/indicator requests.

- [ ] **Step 4: 最小布局实现**

Polish quote hierarchy/tabular numbers, group period/indicator/signal/date controls, align hover/indicator readouts, and organize right rail into current facts, qualification, crosshair snapshot and collapsed experiment tools.

- [ ] **Step 5: 验证 daily/viewport/marker/HTDY**

Run `barTime`, `marketChartWindow`, `marketRightRail`, HTDY, full unit/build/mock E2E and screenshots at 1440/1280/1024.

- [ ] **Step 6: 提交**

Commit Kline/Market polish separately from the HTDY integration commit.

### Task 6: Unify Cross-page Visual and Interaction Patterns

**Files:**
- Modify per page: `apps/quant-web/src/pages/dashboard/index.vue`
- Modify per page: `apps/quant-web/src/pages/signal/index.vue`
- Modify per page: `apps/quant-web/src/pages/review/index.vue`
- Modify per page: `apps/quant-web/src/pages/backtest/index.vue`
- Modify per page: `apps/quant-web/src/pages/data/index.vue`
- Modify per page: `apps/quant-web/src/pages/runtime/index.vue`
- Optional shared component only when used by at least two pages: `apps/quant-web/src/components/common/**`
- Modify: relevant pure presentation tests and `apps/quant-web/e2e/run-mock-smoke.mjs`

**Interfaces:**
- Consumes: existing APIs and shared PageShell/StatusTag/CapabilityBadge/EmptyState.
- Produces: consistent status strips, evidence hierarchy, empty/error/loading treatment and bounded dense tables.

- [ ] **Step 1: Dashboard**

Preserve real recommended action/recent facts/runtime freshness/JM quick entry; improve status strip, time formatting and empty state. Write/extend `dashboardAction.test.ts`, verify, commit.

- [ ] **Step 2: Signal**

Use human-readable source mode plus exact raw identity in detail, clarify lifecycle/qualification/Event/Review links, keep scan config collapsed. Extend `signalSourceMode.test.ts`, verify, commit.

- [ ] **Step 3: Review**

Group frozen source facts, user judgment, outcome/tags/lesson and lineage; retain manual-create boundary and roundtrip. Extend `reviewFoundation.test.ts`/E2E, verify, commit.

- [ ] **Step 4: Backtest**

Group report identity, trust audit, Profile/data, costs, result and rejected/OOS facts; never map trust audit to strategy validity. Extend existing validation/deep-link tests, verify, commit.

- [ ] **Step 5: Data**

Show latest/quality/eligibility/Profile/version summary by default and raw evidence in existing detail surfaces; preserve bounded pagination/no paths. Add pure presentation coverage if needed, verify, commit.

- [ ] **Step 6: Runtime**

Group component health/heartbeat/lag/watermark/last success/error; no recovery action button and no raw JSON dump. Extend runtime helpers tests, verify, commit.

### Task 7: Performance, Accessibility and Real Read-only Acceptance

**Files:**
- Modify: `apps/quant-web/e2e/run-mock-smoke.mjs`
- Modify: `apps/quant-web/e2e/run-readonly-smoke.mjs`
- Modify: `TESTING.md` only after commands actually pass

**Interfaces:**
- Consumes: completed Web candidate.
- Produces: request-count, keyboard/focus, overflow, console, GET-only and readonly evidence.

- [ ] **Step 1: Mock performance/a11y tests**

Assert right-rail tabs do not request bars/indicators, HTDY-only toggle does not request EMA, live requests do not overlap, hidden refresh pauses, selected controls expose semantics, drawer focus/close works, and 1280/1024 have no page overflow.

- [ ] **Step 2: Full mock Gate**

Run unit/build/mock E2E and capture final screenshots.

- [ ] **Step 3: Start isolated readonly real API/Web**

API `127.0.0.1:8010`, Web `127.0.0.1:5177`, PostgreSQL `default_transaction_read_only=on`, one process, no reload/Alembic/worker/scheduler/notification.

- [ ] **Step 4: Run readonly E2E**

```bash
cd apps/quant-web
PLAYWRIGHT_API_BASE=http://127.0.0.1:8010 \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 \
npm run test:e2e:readonly
```

Expected: only GET/HEAD/OPTIONS, console error 0, no path/secret leak, JM 1D diagnosis and UI agree, existing report/trade/chart/review roundtrip preserved, missing event review remains honest.

- [ ] **Step 5: Update TESTING.md only with fresh results**

Record exact counts and partial external Gate if real readonly environment cannot run.

### Task 8: Final Acceptance and Handoff

**Files:**
- Create: `docs/tasks/WEB-V1-14-FINAL-ACCEPTANCE.md`

**Interfaces:**
- Consumes: all task commits and fresh verification.
- Produces: source/base/head, collision resolution, diagnosis, changed files, tests, screenshots, limitations, V2 deferrals and Runtime-not-deployed statement.

- [ ] **Step 1: Run final checks**

```bash
git -c core.fsmonitor=false status --short --branch
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
cd apps/quant-web
npm test
npm run build
npm run test:e2e
cd ../..
bash scripts/engineering/preflight.sh --json
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/test.sh engineering
```

- [ ] **Step 2: Recheck forbidden scope**

Confirm no migration, DB/Parquet/Profile write, Runtime/deploy change, strategy/indicator formula change, notification, dependency/lockfile drift, warning suppression or trading UI.

- [ ] **Step 3: Write final acceptance**

Publish only evidence-supported Web gates. Never publish V2, strategy validation, Runtime, long-running or auto-trading readiness.

- [ ] **Step 4: Final verification and commit**

Run `git diff --cached --check`, commit final acceptance, and leave push/merge/deploy to the user.
