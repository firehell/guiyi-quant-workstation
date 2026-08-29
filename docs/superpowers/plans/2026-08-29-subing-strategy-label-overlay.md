# SuBing Strategy HTML Label Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SuBing strategy series-markers with HTML bordered tags that keep 建多/建空/清多/清空 copy, stack on overlap, flip side when clipped, and re-layout on pan/zoom/resize.

**Architecture:** Pure layout in `subingStrategyLabels.ts` (pixel boxes + collision). `KlineChart.vue` maps chart coordinates into that function, renders an absolute HTML overlay, and excludes `historical:*` markers from `createSeriesMarkers`. HTDY/Alert markers stay on the built-in plugin.

**Tech Stack:** Vue 3, TypeScript, lightweight-charts v5 `createSeriesMarkers`, node:test.

## Global Constraints

- Labels: `建多` / `建空` / `清多` / `清空` only — no ▲▼×, no price/percent.
- SuBing only via HTML overlay; HTDY + Alert stay on `createSeriesMarkers`.
- Overlay `pointer-events: none`; do not change strategy semantics or backend contracts.
- Default sides unchanged: open_long below, open_short above, close_long above, close_short below.
- Re-layout on visible range change, resize, bars/markers updates; use rAF coalesce for high-frequency updates.
- Do not expand price scale solely to fit labels.
- Commits only when the user explicitly asks; skip commit steps unless authorized in-session.

---

## File map

| File | Role |
|------|------|
| `apps/quant-web/src/utils/subingStrategyLabels.ts` | Filter + layout + collision (pure) |
| `apps/quant-web/tests/subingStrategyLabels.test.ts` | Layout unit tests |
| `apps/quant-web/src/utils/historicalResearchMarkers.ts` | Label copy without symbols |
| `apps/quant-web/tests/historicalResearchMarkers.test.ts` | Expect plain labels |
| `apps/quant-web/src/components/kline/KlineChart.vue` | Overlay DOM + coordinate bridge + exclude SuBing from series markers |
| `apps/quant-web/tests/alerts.test.ts` or thin chart-source contract | Optional source contract that series path excludes `historical:` |

---

### Task 1: Plain SuBing marker labels

**Files:**
- Modify: `apps/quant-web/src/utils/historicalResearchMarkers.ts`
- Modify: `apps/quant-web/tests/historicalResearchMarkers.test.ts`

**Interfaces:**
- Consumes: existing `subingStrategyActionToMarker`
- Produces: labels `'建多' | '建空' | '清多' | '清空'`

- [ ] **Step 1: Update failing expectations**

In `historicalResearchMarkers.test.ts`, change:

```ts
assert.equal(open.label, '建多')
assert.equal(close.label, '清多')
```

and any `['× 清多']` → `['清多']`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/quant-web exec node --test tests/historicalResearchMarkers.test.ts`

Expected: FAIL on label mismatch (`▲ 建多` vs `建多`).

- [ ] **Step 3: Minimal label change**

In `subingStrategyActionToMarker`:

```ts
const label = open
  ? long ? '建多' : '建空'
  : long ? '清多' : '清空'
```

Keep tooltip/tone/position/shape unchanged (shape unused once overlay ships).

- [ ] **Step 4: Run tests**

Run: `pnpm --dir apps/quant-web exec node --test tests/historicalResearchMarkers.test.ts`

Expected: PASS.

---

### Task 2: Pure layout + collision helper

**Files:**
- Create: `apps/quant-web/src/utils/subingStrategyLabels.ts`
- Create: `apps/quant-web/tests/subingStrategyLabels.test.ts`

**Interfaces:**
- Consumes: `KlineMarker` from `types/market.ts`
- Produces:

```ts
export interface SubingStrategyLabelAnchor {
  id: string
  label: string
  x: number
  wickY: number
  preferredSide: 'above' | 'below'
}

export interface SubingStrategyLabelLayout {
  id: string
  label: string
  left: number
  top: number
  width: number
  height: number
  side: 'above' | 'below'
  leaderFromY: number
  leaderToY: number
}

export function isSubingStrategyMarker(marker: Pick<KlineMarker, 'id'>): boolean

export function preferredSideFromMarker(
  marker: Pick<KlineMarker, 'position'>,
): 'above' | 'below'

export function layoutSubingStrategyLabels(
  anchors: readonly SubingStrategyLabelAnchor[],
  options: {
    pane: { left: number; top: number; width: number; height: number }
    boxWidth: number
    boxHeight: number
    gap: number
    stackGap: number
    clusterX: number
  },
): SubingStrategyLabelLayout[]
```

- [ ] **Step 1: Write failing tests**

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  isSubingStrategyMarker,
  layoutSubingStrategyLabels,
  preferredSideFromMarker,
} from '../src/utils/subingStrategyLabels.ts'

test('identifies historical SuBing markers only', () => {
  assert.equal(isSubingStrategyMarker({ id: 'historical:a' }), true)
  assert.equal(isSubingStrategyMarker({ id: 'htdy:卖观察:t' }), false)
  assert.equal(isSubingStrategyMarker({ id: 'alert:htdy_original_15m:jm:15m:t' }), false)
})

test('maps marker position to preferred side', () => {
  assert.equal(preferredSideFromMarker({ position: 'aboveBar' }), 'above')
  assert.equal(preferredSideFromMarker({ position: 'belowBar' }), 'below')
})

test('keeps default side when boxes do not overlap', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: 50, wickY: 200, preferredSide: 'below' },
    { id: 'b', label: '清多', x: 250, wickY: 80, preferredSide: 'above' },
  ], { pane, boxWidth: 40, boxHeight: 18, gap: 4, stackGap: 2, clusterX: 24 })
  assert.equal(laid.find((item) => item.id === 'a')?.side, 'below')
  assert.equal(laid.find((item) => item.id === 'b')?.side, 'above')
})

test('stacks vertically when same-side boxes overlap in x', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '清多', x: 100, wickY: 60, preferredSide: 'above' },
    { id: 'b', label: '建空', x: 105, wickY: 55, preferredSide: 'above' },
  ], { pane, boxWidth: 40, boxHeight: 18, gap: 4, stackGap: 2, clusterX: 24 })
  const tops = laid.map((item) => item.top).sort((l, r) => l - r)
  assert.equal(tops.length, 2)
  assert.ok(tops[1] - tops[0] >= 18)
  assert.ok(laid.every((item) => item.side === 'above'))
})

test('flips to above when below stack would leave the pane', () => {
  const pane = { left: 0, top: 0, width: 200, height: 80 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: 100, wickY: 70, preferredSide: 'below' },
  ], { pane, boxWidth: 40, boxHeight: 18, gap: 4, stackGap: 2, clusterX: 24 })
  assert.equal(laid[0]?.side, 'above')
  assert.ok(laid[0].top >= pane.top)
  assert.ok(laid[0].top + laid[0].height <= pane.top + pane.height)
})

test('drops anchors with non-finite coordinates', () => {
  const pane = { left: 0, top: 0, width: 200, height: 200 }
  const laid = layoutSubingStrategyLabels([
    { id: 'bad', label: '建多', x: Number.NaN, wickY: 10, preferredSide: 'below' },
  ], { pane, boxWidth: 40, boxHeight: 18, gap: 4, stackGap: 2, clusterX: 24 })
  assert.deepEqual(laid, [])
})
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pnpm --dir apps/quant-web exec node --test tests/subingStrategyLabels.test.ts`

Expected: FAIL module not found / export missing.

- [ ] **Step 3: Implement layout**

```ts
// apps/quant-web/src/utils/subingStrategyLabels.ts
import type { KlineMarker } from '../types/market.ts'

export interface SubingStrategyLabelAnchor {
  id: string
  label: string
  x: number
  wickY: number
  preferredSide: 'above' | 'below'
}

export interface SubingStrategyLabelLayout {
  id: string
  label: string
  left: number
  top: number
  width: number
  height: number
  side: 'above' | 'below'
  leaderFromY: number
  leaderToY: number
}

export function isSubingStrategyMarker(marker: Pick<KlineMarker, 'id'>): boolean {
  return marker.id.startsWith('historical:')
}

export function preferredSideFromMarker(
  marker: Pick<KlineMarker, 'position'>,
): 'above' | 'below' {
  return marker.position === 'belowBar' ? 'below' : 'above'
}

export function layoutSubingStrategyLabels(
  anchors: readonly SubingStrategyLabelAnchor[],
  options: {
    pane: { left: number; top: number; width: number; height: number }
    boxWidth: number
    boxHeight: number
    gap: number
    stackGap: number
    clusterX: number
  },
): SubingStrategyLabelLayout[] {
  const { pane, boxWidth, boxHeight, gap, stackGap, clusterX } = options
  const usable = anchors.filter((anchor) => (
    Number.isFinite(anchor.x) && Number.isFinite(anchor.wickY)
  ))
  if (!usable.length) return []

  const sorted = [...usable].sort((left, right) => (
    left.x - right.x || left.id.localeCompare(right.id)
  ))
  const clusters: SubingStrategyLabelAnchor[][] = []
  for (const anchor of sorted) {
    const current = clusters.at(-1)
    if (!current || Math.abs(anchor.x - current[0].x) > clusterX) {
      clusters.push([anchor])
      continue
    }
    current.push(anchor)
  }

  const layouts: SubingStrategyLabelLayout[] = []
  for (const cluster of clusters) {
    const preferred = majoritySide(cluster)
    layouts.push(...placeCluster(cluster, preferred, {
      pane, boxWidth, boxHeight, gap, stackGap,
    }))
  }
  return layouts.sort((left, right) => left.id.localeCompare(right.id))
}

function majoritySide(cluster: readonly SubingStrategyLabelAnchor[]): 'above' | 'below' {
  let above = 0
  let below = 0
  for (const anchor of cluster) {
    if (anchor.preferredSide === 'above') above += 1
    else below += 1
  }
  return below > above ? 'below' : 'above'
}

function placeCluster(
  cluster: readonly SubingStrategyLabelAnchor[],
  side: 'above' | 'below',
  options: {
    pane: { left: number; top: number; width: number; height: number }
    boxWidth: number
    boxHeight: number
    gap: number
    stackGap: number
  },
): SubingStrategyLabelLayout[] {
  const attempt = layoutClusterOnSide(cluster, side, options)
  if (attempt.every((item) => fitsPane(item, options.pane))) return attempt
  const flipped: 'above' | 'below' = side === 'above' ? 'below' : 'above'
  const second = layoutClusterOnSide(cluster, flipped, options)
  if (second.every((item) => fitsPane(item, options.pane))) return second
  return attempt.filter((item) => fitsPane(item, options.pane))
}

function layoutClusterOnSide(
  cluster: readonly SubingStrategyLabelAnchor[],
  side: 'above' | 'below',
  options: {
    boxWidth: number
    boxHeight: number
    gap: number
    stackGap: number
  },
): SubingStrategyLabelLayout[] {
  const { boxWidth, boxHeight, gap, stackGap } = options
  const ordered = side === 'above'
    ? [...cluster].sort((left, right) => left.wickY - right.wickY || left.id.localeCompare(right.id))
    : [...cluster].sort((left, right) => right.wickY - left.wickY || left.id.localeCompare(right.id))
  const wickY = side === 'above'
    ? Math.min(...cluster.map((item) => item.wickY))
    : Math.max(...cluster.map((item) => item.wickY))
  const x = cluster.reduce((sum, item) => sum + item.x, 0) / cluster.length
  const left = x - boxWidth / 2
  const result: SubingStrategyLabelLayout[] = []
  for (let index = 0; index < ordered.length; index += 1) {
    const anchor = ordered[index]
    const offset = index * (boxHeight + stackGap)
    const top = side === 'above'
      ? wickY - gap - boxHeight - offset
      : wickY + gap + offset
    const nearEdge = side === 'above' ? top + boxHeight : top
    result.push({
      id: anchor.id,
      label: anchor.label,
      left,
      top,
      width: boxWidth,
      height: boxHeight,
      side,
      leaderFromY: wickY,
      leaderToY: nearEdge,
    })
  }
  return result
}

function fitsPane(
  item: SubingStrategyLabelLayout,
  pane: { left: number; top: number; width: number; height: number },
): boolean {
  return item.left >= pane.left
    && item.top >= pane.top
    && item.left + item.width <= pane.left + pane.width
    && item.top + item.height <= pane.top + pane.height
}
```

Tune clustering/flip details only if tests fail; keep tests as the contract.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pnpm --dir apps/quant-web exec node --test tests/subingStrategyLabels.test.ts`

Expected: PASS.

---

### Task 3: Wire HTML overlay in KlineChart

**Files:**
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/tests/alerts.test.ts` (or add `tests/klineStrategyLabelsContract.test.ts`) for source contracts

**Interfaces:**
- Consumes: `layoutSubingStrategyLabels`, `isSubingStrategyMarker`, `preferredSideFromMarker`
- Produces: `strategyLabelLayouts` ref rendered in template; series markers without `historical:*`

- [ ] **Step 1: Add failing source contracts**

```ts
// in alerts.test.ts Product Alert suite OR new contract file
import { readFileSync } from 'node:fs'

const chartSource = readFileSync(new URL('../src/components/kline/KlineChart.vue', import.meta.url), 'utf8')

test('KlineChart lays out SuBing strategy labels via HTML overlay', () => {
  assert.match(chartSource, /layoutSubingStrategyLabels/)
  assert.match(chartSource, /isSubingStrategyMarker/)
  assert.match(chartSource, /data-testid="kline-strategy-labels"/)
  assert.match(chartSource, /pointer-events:\s*none/)
  assert.match(
    chartSource,
    /mergedDisplayMarkers[\s\S]*filter\([\s\S]*isSubingStrategyMarker/,
  )
})
```

- [ ] **Step 2: Run contract — expect FAIL**

Run the new/updated test file. Expected: FAIL on missing strings.

- [ ] **Step 3: Implement chart wiring**

1. Import helpers.
2. Add `const strategyLabelLayouts = ref<SubingStrategyLabelLayout[]>([])`.
3. Change `mergedDisplayMarkers`:

```ts
function mergedDisplayMarkers(): KlineMarker[] {
  return mergeKlineMarkers(
    mergeKlineMarkers(derivedData.htdy?.markers ?? [], props.alertMarkers),
    props.researchMarkers.filter((marker) => !isSubingStrategyMarker(marker)),
  )
}
```

4. Keep `renderedResearchMarkerCount` based on SuBing research markers length (or HTML layout count) so e2e counts stay meaningful — prefer `strategyLabelLayouts.value.length` after layout, or continue counting `props.researchMarkers.filter(isSubingStrategyMarker).length`.
5. Add `scheduleStrategyLabelLayout()` with rAF coalesce; call from:
   - end of `renderDerivedSeries`
   - `onVisibleLogicalRangeChange`
   - `resize`
   - watches on `researchMarkers` / `bars`
6. Inside layout:

```ts
function syncStrategyLabelLayout(): void {
  if (!chart || !candles || !container.value) {
    strategyLabelLayouts.value = []
    return
  }
  const paneHeight = chart.panes()[0]?.getHeight() ?? container.value.clientHeight
  const pane = { left: 0, top: 0, width: container.value.clientWidth, height: paneHeight }
  const barsByTime = new Map(renderedBars.map((bar) => [markerTimeKey(bar.time), bar]))
  const anchors = props.researchMarkers
    .filter(isSubingStrategyMarker)
    .flatMap((marker) => {
      const bar = barsByTime.get(markerTimeKey(marker.time))
      if (!bar) return []
      const x = chart!.timeScale().timeToCoordinate(chartTime(bar))
      const wickPrice = preferredSideFromMarker(marker) === 'above' ? bar.high : bar.low
      const wickY = candles!.priceToCoordinate(wickPrice)
      if (x === null || wickY === null) return []
      return [{
        id: marker.id,
        label: marker.label,
        x,
        wickY,
        preferredSide: preferredSideFromMarker(marker),
      }]
    })
  strategyLabelLayouts.value = layoutSubingStrategyLabels(anchors, {
    pane,
    boxWidth: 40,
    boxHeight: 18,
    gap: 4,
    stackGap: 2,
    clusterX: 24,
  })
}
```

7. Template inside `.kline-shell` (sibling of `.chart`):

```vue
<div
  class="kline-strategy-labels"
  data-testid="kline-strategy-labels"
  aria-hidden="true"
>
  <div
    v-for="item in strategyLabelLayouts"
    :key="item.id"
    class="kline-strategy-label"
    :style="{
      left: `${item.left}px`,
      top: `${item.top}px`,
      width: `${item.width}px`,
      height: `${item.height}px`,
    }"
  >
    <span
      class="kline-strategy-label__leader"
      :style="{
        top: `${Math.min(item.leaderFromY, item.leaderToY) - item.top}px`,
        height: `${Math.abs(item.leaderToY - item.leaderFromY)}px`,
      }"
    />
    <span class="kline-strategy-label__text">{{ item.label }}</span>
  </div>
</div>
```

8. CSS (scoped): cream background `#FBF8F1`, border `1px solid #4B5563`, text `#111827`, font 11px, leader 1px centered, overlay `pointer-events: none; position: absolute; inset: 0; z-index: 3; overflow: hidden`.

- [ ] **Step 4: Run contracts + related unit tests**

```bash
pnpm --dir apps/quant-web exec node --test \
  tests/subingStrategyLabels.test.ts \
  tests/historicalResearchMarkers.test.ts \
  tests/alerts.test.ts \
  tests/kline-view-model.test.ts
```

Expected: PASS (adjust any brittle source regex if needed).

- [ ] **Step 5: Manual browser check (dev already on 5173)**

1. Open JM 15m + 苏冰.
2. Confirm bordered tags, no series-marker arrows for 建多/清多.
3. Pan/zoom: tags move and restack; bottom clip flips up.
4. Switch 火天大有: HTML overlay empty; HTDY markers remain.

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Plain labels, no symbols | Task 1 |
| HTML bordered tags + leader | Task 3 |
| Collision stack + flip side | Task 2 |
| Pan/zoom/resize re-layout | Task 3 schedule hooks |
| Exclude SuBing from series markers | Task 3 `mergedDisplayMarkers` |
| HTDY unchanged | Task 3 filter only `historical:` |
| pointer-events none | Task 3 CSS |
| Unit tests for layout | Task 2 |
| No price/percent | Task 1–3 (labels only) |

## Placeholder / consistency review

- Interfaces named consistently: `layoutSubingStrategyLabels`, `isSubingStrategyMarker`, `SubingStrategyLabelLayout`.
- Marker id prefix `historical:` matches `subingStrategyActionToMarker`.
- No TBD/TODO left in steps.
