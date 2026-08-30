# SuBing EMA Ribbon V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将苏冰 EMA10/21 Ribbon 从相邻 Bar 连续梯形填充改为每根 K 线一根独立黄/蓝柱，并保持 EMA10/EMA21 固定身份边界线。

**Architecture:** 继续复用现有 `buildSubingEmaRibbon()`、Lightweight Charts `ISeriesPrimitive` 与 candle-series attach 生命周期，只替换 Ribbon 的数据模型与 Canvas 几何。Browser EMA 计算仍只来自现有 `calculateEMA()`；`klineViewModel`、策略、后端与 Runtime 不改。

**Tech Stack:** Vue 3, TypeScript 6, Lightweight Charts 5.2, Node test runner, Playwright

**Spec:** `docs/superpowers/specs/2026-08-29-subing-ema-ribbon-design.md`

## Global Constraints

- 本任务为 Lane 2 Web rendering change。
- 不修改 EMA10 / EMA21 公式、周期或 `calculateEMA()`。
- 不修改 SuBing Factor / Signal / Calibration / Lifecycle / Strategy V1 / EMA21 exit。
- 不修改 Historical Projection、Episode、API、backend、Alert、Runtime、Canonical、DB、Redis。
- 不新增 npm dependency，不引入第二套图表库、HistogramSeries 或 AreaSeries workaround。
- 不保留 V1 band/split legacy 或 compatibility 双路径。
- 一个独立 task branch/worktree 从最新 `develop` 创建；不得修改 main/runtime worktree。
- 测试通过后只创建 `task -> develop` PR；人工视觉 Gate 通过前不得 merge `develop`。
- 不发布 `main`、不创建 tag/release、不做 Runtime promotion、不执行真实写入或发送通知。

## File map

**Modify**
- `apps/quant-web/src/utils/subingEmaRibbon.ts` — V2 单 Bar point 数据合同与 causal tone。
- `apps/quant-web/src/components/kline/subingEmaRibbonPrimitive.ts` — point 投影、动态柱宽、独立柱和固定身份 EMA lines。
- `apps/quant-web/src/components/kline/KlineChart.vue` — Ribbon 输入从 `.bands` 切到 `.points`。
- `apps/quant-web/tests/subingEmaRibbon.test.ts` — V2 unit/regression tests。

**Modify only if an existing assertion requires adaptation**
- `apps/quant-web/e2e/market-research.spec.mjs`

**Do not modify**
- `apps/quant-web/src/utils/klineViewModel.ts`，除非现有接口因 `bands -> points` 编译失败且只需类型级最小修正；不得改变 hover 语义。
- backend / strategy / Runtime / Alert / data files。

---

### Task 1: Replace the Ribbon band contract with per-Bar points

**Files:**
- Modify: `apps/quant-web/tests/subingEmaRibbon.test.ts`
- Modify: `apps/quant-web/src/utils/subingEmaRibbon.ts`

**Interfaces:**
- Consumes: existing `calculateEMA(bars, 10|21)`.
- Produces:

```ts
export type SubingEmaRibbonTone = 'bull' | 'bear'

export interface SubingEmaRibbonPoint {
  time: string
  ema10: number
  ema21: number
  tone: SubingEmaRibbonTone
}

export interface SubingEmaRibbon {
  ema10: EmaPoint[]
  ema21: EmaPoint[]
  points: SubingEmaRibbonPoint[]
}
```

- [ ] **Step 1: Rewrite the old band tests as V2 failing tests**

Remove assertions built around:

```text
SubingEmaRibbonBand
adjacent pair count
left/right
leftTone/rightTone
splitT
crossingSplitT()
splitRibbonCoordinates()
```

Add focused tests equivalent to:

```ts
test('one EMA-ready bar emits one ribbon point', () => {
  const points = buildRibbonPoints(
    [point('a', 12), point('b', 13)],
    [point('a', 10), point('b', 11)],
  )

  assert.deepEqual(points, [
    { time: 'a', ema10: 12, ema21: 10, tone: 'bull' },
    { time: 'b', ema10: 13, ema21: 11, tone: 'bull' },
  ])
})

test('bear values emit bear points', () => {
  const points = buildRibbonPoints(
    [point('a', 8)],
    [point('a', 10)],
  )
  assert.equal(points[0]?.tone, 'bear')
})

test('equal EMA inherits only the previous tone', () => {
  const points = buildRibbonPoints(
    [point('a', 12), point('b', 10), point('c', 8)],
    [point('a', 10), point('b', 10), point('c', 10)],
  )
  assert.deepEqual(points.map((item) => item.tone), ['bull', 'bull', 'bear'])
})

test('leading equal EMA does not look ahead for tone', () => {
  const points = buildRibbonPoints(
    [point('a', 10), point('b', 12)],
    [point('a', 10), point('b', 10)],
  )
  assert.deepEqual(points, [
    { time: 'b', ema10: 12, ema21: 10, tone: 'bull' },
  ])
})
```

Keep the existing warm-up test but change the expectation to:

```ts
assert.deepEqual(ribbon.points, [])
```

For a deterministic rising series after warm-up, assert:

```ts
assert.equal(ribbon.points.length, ribbon.ema21.length)
assert.ok(ribbon.points.every((item) => item.tone === 'bull'))
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
pnpm -C apps/quant-web exec node --test tests/subingEmaRibbon.test.ts
```

Expected: FAIL because production still returns `bands` and exports split/band helpers.

- [ ] **Step 3: Implement the minimal point model**

In `subingEmaRibbon.ts`:

```ts
export interface SubingEmaRibbonPoint {
  time: string
  ema10: number
  ema21: number
  tone: SubingEmaRibbonTone
}
```

Implement a pure alignment helper with no future lookup:

```ts
export function buildRibbonPoints(
  fast: readonly EmaPoint[],
  slow: readonly EmaPoint[],
): SubingEmaRibbonPoint[] {
  const slowByTime = new Map(slow.map((item) => [item.time, item.value]))
  const result: SubingEmaRibbonPoint[] = []
  let previousTone: SubingEmaRibbonTone | null = null

  for (const item of fast) {
    const ema21 = slowByTime.get(item.time)
    if (ema21 === undefined) continue

    const tone = item.value > ema21
      ? 'bull'
      : item.value < ema21
        ? 'bear'
        : previousTone

    if (!tone) continue
    previousTone = tone
    result.push({ time: item.time, ema10: item.value, ema21, tone })
  }

  return result
}
```

Return:

```ts
return {
  ema10,
  ema21,
  points: buildRibbonPoints(ema10, ema21),
}
```

Delete obsolete split/band types and helpers entirely. Do not leave deprecated aliases.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run:

```bash
pnpm -C apps/quant-web exec node --test tests/subingEmaRibbon.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run a source regression scan**

Run:

```bash
rg -n "SubingEmaRibbonBand|splitT|crossingSplitT|splitRibbonCoordinates" \
  apps/quant-web/src apps/quant-web/tests
```

Expected after Task 1: remaining matches are allowed only in the still-unmodified primitive/Kline integration and must be removed in Task 2; no matches may remain in `subingEmaRibbon.ts` or its unit test.

- [ ] **Step 6: Commit Task 1**

```bash
git add \
  apps/quant-web/src/utils/subingEmaRibbon.ts \
  apps/quant-web/tests/subingEmaRibbon.test.ts
git commit -m "refactor(web): model SuBing ribbon per bar"
```

---

### Task 2: Render independent columns and fixed-identity EMA lines

**Files:**
- Modify: `apps/quant-web/src/components/kline/subingEmaRibbonPrimitive.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Test: `apps/quant-web/tests/subingEmaRibbon.test.ts`

**Interfaces:**
- Consumes: `readonly SubingEmaRibbonPoint[]`.
- Produces:

```ts
ribbonPrimitive.setData(
  props.showSubingEmaRibbon ? derivedData.subingEmaRibbon?.points ?? [] : [],
  ribbonTime,
)
```

- [ ] **Step 1: Add static regression assertions for the renderer contract**

In `subingEmaRibbon.test.ts`, keep a source-level regression test that reads the primitive and chart source and asserts:

```ts
assert.match(primitive, /drawRibbonColumn/)
assert.match(primitive, /drawEmaLine/)
assert.match(primitive, /deriveColumnWidth/)
assert.match(chart, /subingEmaRibbon\?\.points/)
assert.doesNotMatch(primitive, /fillRibbonQuad/)
assert.doesNotMatch(primitive, /splitRibbonCoordinates/)
```

Also assert the fixed identity colors are present in the Ribbon style contract:

```ts
assert.equal(SUBING_EMA_RIBBON_STYLE.bullFill, '#FFE2A0')
assert.equal(SUBING_EMA_RIBBON_STYLE.bearFill, '#AFCBFF')
assert.equal(SUBING_EMA_RIBBON_STYLE.ema10Line, '#E8B923')
assert.equal(SUBING_EMA_RIBBON_STYLE.ema21Line, '#38BDF8')
```

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
pnpm -C apps/quant-web exec node --test tests/subingEmaRibbon.test.ts
```

Expected: FAIL because the primitive still uses quad/split rendering and `KlineChart.vue` still passes `.bands`.

- [ ] **Step 3: Replace primitive band projection with point projection**

Use a projected type such as:

```ts
interface RibbonCoordinate {
  x: number
  y10: number
  y21: number
  tone: SubingEmaRibbonTone
}
```

`setData()` accepts `readonly SubingEmaRibbonPoint[]`.

Each point uses the existing:

```ts
timeScale().timeToCoordinate(time)
series.priceToCoordinate(ema10)
series.priceToCoordinate(ema21)
```

Skip only the point whose projection returns null.

- [ ] **Step 4: Implement dynamic column width**

Implement a pure local helper:

```ts
function deriveColumnWidth(
  points: readonly Pick<RibbonCoordinate, 'x'>[],
  index: number,
): number {
  const current = points[index]
  if (!current) return 1

  const previousGap = index > 0 ? current.x - points[index - 1]!.x : null
  const nextGap = index + 1 < points.length ? points[index + 1]!.x - current.x : null
  const gaps = [previousGap, nextGap].filter(
    (gap): gap is number => gap !== null && Number.isFinite(gap) && gap > 0,
  )

  if (gaps.length === 0) return 1
  const spacing = Math.min(...gaps)
  return Math.max(1, Math.min(spacing - 1, Math.floor(spacing * 0.8)))
}
```

Do not introduce fixed `8px`/`9px` Ribbon widths.

- [ ] **Step 5: Draw one independent column per point**

Use:

```ts
function drawRibbonColumn(
  context: CanvasRenderingContext2D,
  point: RibbonCoordinate,
  width: number,
): void {
  const top = Math.min(point.y10, point.y21)
  const bottom = Math.max(point.y10, point.y21)
  const left = Math.round(point.x - width / 2)
  const drawWidth = Math.max(1, Math.round(width))
  const height = Math.max(1, Math.round(bottom - top))

  context.fillStyle = point.tone === 'bull'
    ? SUBING_EMA_RIBBON_STYLE.bullFill
    : SUBING_EMA_RIBBON_STYLE.bearFill
  context.fillRect(left, Math.round(top), drawWidth, height)
}
```

Columns must not share polygons or side edges.

- [ ] **Step 6: Draw EMA10 and EMA21 as separate continuous lines**

Use one helper with explicit identity color:

```ts
function drawEmaLine(
  context: CanvasRenderingContext2D,
  points: readonly RibbonCoordinate[],
  key: 'y10' | 'y21',
  color: string,
): void {
  if (points.length < 2) return
  context.beginPath()
  context.moveTo(points[0]!.x, points[0]![key])
  for (let index = 1; index < points.length; index += 1) {
    context.lineTo(points[index]!.x, points[index]![key])
  }
  context.strokeStyle = color
  context.lineWidth = 1
  context.stroke()
}
```

Render order:

```ts
projected.forEach((point, index) => {
  drawRibbonColumn(context, point, deriveColumnWidth(projected, index))
})
drawEmaLine(context, projected, 'y10', SUBING_EMA_RIBBON_STYLE.ema10Line)
drawEmaLine(context, projected, 'y21', SUBING_EMA_RIBBON_STYLE.ema21Line)
```

Do not set line color from `tone`.

- [ ] **Step 7: Switch `KlineChart.vue` from `.bands` to `.points`**

Change only the Ribbon input:

```ts
ribbonPrimitive.setData(
  props.showSubingEmaRibbon ? derivedData.subingEmaRibbon?.points ?? [] : [],
  ribbonTime,
)
```

Do not alter viewport, markers, MACD, hover or indicator visibility logic.

- [ ] **Step 8: Run the focused test and source scan**

```bash
pnpm -C apps/quant-web exec node --test tests/subingEmaRibbon.test.ts
rg -n "SubingEmaRibbonBand|splitT|crossingSplitT|splitRibbonCoordinates|fillRibbonQuad" \
  apps/quant-web/src apps/quant-web/tests
```

Expected:
- focused test PASS;
- `rg` returns no production/test matches.

- [ ] **Step 9: Commit Task 2**

```bash
git add \
  apps/quant-web/src/components/kline/subingEmaRibbonPrimitive.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/tests/subingEmaRibbon.test.ts
git commit -m "fix(web): render SuBing ribbon as per-bar columns"
```

---

### Task 3: Run Web regression and preserve the existing overlay contract

**Files:**
- Modify only if required by an existing assertion: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**
- Existing product behavior must remain:
  - SuBing overlay owns Ribbon.
  - optional EMA10/21/60 remains independent.
  - hover still contains EMA10/21 when Ribbon is enabled.
  - other overlays do not render Ribbon.

- [ ] **Step 1: Run all Web unit tests**

```bash
pnpm --dir apps/quant-web test
```

Expected: PASS.

If a failure is caused by an assertion that explicitly references V1 `bands`/`splitT`, update only that assertion to the approved V2 contract. Do not weaken unrelated tests.

- [ ] **Step 2: Run the existing Market research E2E**

```bash
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-research.spec.mjs
```

Expected: PASS.

Only make the minimum E2E change if an existing test asserts the old implementation detail. Do not add production-only test hooks.

- [ ] **Step 3: Run the production Web build**

```bash
pnpm --dir apps/quant-web build
```

Expected: exit 0.

- [ ] **Step 4: Run repository diff checks**

```bash
git diff --check
git status --short
git diff -- \
  apps/quant-web/src/utils/subingEmaRibbon.ts \
  apps/quant-web/src/components/kline/subingEmaRibbonPrimitive.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/tests/subingEmaRibbon.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
```

Verify no backend, strategy, Runtime, Alert, data, main/release file is changed.

- [ ] **Step 5: Commit any minimal E2E adaptation**

Only if Task 3 required an E2E file change:

```bash
git add apps/quant-web/e2e/market-research.spec.mjs
git commit -m "test(web): cover SuBing ribbon V2"
```

If no file changed, do not create an empty commit.

---

### Task 4: Perform visual acceptance and open the PR

**Files:**
- No production file changes expected.

**Interfaces:**
- Human acceptance is based on actual browser rendering, not test output alone.

- [ ] **Step 1: Start/open the normal local Market Web using the repository's existing development flow**

Use the existing local services/dev workflow; do not connect to or mutate production data, DB, Redis, Scope or Runtime for this check.

- [ ] **Step 2: Inspect a SuBing `actual_dominant + 15m` chart at normal zoom**

Capture temporary visual evidence showing:

```text
a. continuous bullish area -> separate yellow columns
b. continuous bearish area -> separate blue columns
c. EMA10/EMA21 crossover -> adjacent column tone switch
```

Do not commit screenshot artifacts unless an existing repository convention explicitly requires them.

- [ ] **Step 3: Repeat at zoomed-in and zoomed-out levels**

Verify:

```text
one real K -> at most one column
column centered on K
visible gap between adjacent columns
no continuous Area Fill
no trapezoid connection
no half-yellow/half-blue column
EMA10 always yellow
EMA21 always blue
column width follows zoom
```

- [ ] **Step 4: Re-run the final verification suite immediately before handoff**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  -c playwright.config.mjs \
  e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
git status --short
```

Report exact outputs/counts. Do not claim completion from earlier runs.

- [ ] **Step 5: Self-review the task diff**

Confirm explicitly:

```text
no EMA formula change
no SuBing strategy semantics change
no backend/API change
no Alert/Runtime/data mutation path change
no dependency change
no main/tag/release operation
```

- [ ] **Step 6: Push the task branch and create PR to `develop`**

PR title:

```text
fix(web): render SuBing EMA ribbon as per-bar columns
```

PR body must include:

- change summary;
- removed V1 band/split logic;
- exact test/build results;
- visual acceptance evidence for bullish/bearish/crossover and three zoom levels;
- confirmation that strategy/backend/Runtime/main were untouched.

Do **not** merge the PR.

- [ ] **Step 7: Stop at the human visual Gate**

Final status must be:

```text
CODE_COMPLETE / TEST_COMPLETE
VISUAL_REVIEW_PENDING
```

Do not report `允许集成 develop` until the user reviews the visual evidence.
