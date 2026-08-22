# Market B1 Decision Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Market Web 收敛为“首页 0~3 优先检查 → 详情页 5~10 秒验证 → Alert 正式 Event 打断 → Execution Review 人工处理”的 B1 决策漏斗。

**Architecture:** 只在 `apps/quant-web` 内增加两组轻量 view projection：`marketFocus.ts` 负责首页 D1 Radar 粗筛，`productCheck.ts` 负责详情页验证文本/状态投影。现有 Market Radar、Product Research、Subing、HTDY、Alert、Execution Review API 均保持权威来源；不新增后端 service、endpoint、DB、Runtime 或 Opportunity domain。

**Tech Stack:** Vue 3、TypeScript、Naive UI、node:test、Playwright、现有 Market/Alert/Execution Review HTTP clients。

**Spec:** `docs/superpowers/specs/2026-08-22-market-b1-decision-compression-design.md`

## Global Constraints

- 首页 B1 只消费现有 Radar D1 facts；第一版不加入 W1 全市场过滤。
- Focus 只输出 `0..3` 个“优先检查”，不得出现综合分、概率、winner、推荐交易。
- `degraded` Radar 必须 fail-closed，不输出 Top3；`pending_after_market` 只能使用并明示 `data_as_of` 完整快照。
- 详情页“现在”只以已记录 AlertEvent 为正式 Event；SuBing current snapshot / HTDY observation 不得冒充 Event。
- Lifecycle V2 `Research only` 边界不变；`研究确认` 不等于正式 Event。
- 不修改 MarketDataService、Radar backend、ProductResearch backend、SuBing/HTDY/MFM 算法、Alert Rule/Scope、Execution Review 合同。
- 不新增 OpportunityService / OpportunityModel / score / rank / unified candidate adapter。
- 不新增 DB / migration / Runtime / notification / Canonical / Redis 写入。
- `auto_order=false` 不变。
- 不修改 `STATUS.md` / `PROJECT_SOURCE.md` / `DECISIONS.md` 宣布新业务能力；本任务是 Web 信息架构改造。
- 实现使用一个独立 task branch/worktree：`feat/web-b1-decision-compression`，从最新 `develop` 创建，完成后集成 `develop`。
- Tasks 1~4 是同一个可独立集成 Web feature 的 TDD checkpoints，不拆多个 branch/worktree，避免重复修改同一 E2E 和页面文件。
- 在测试、独立 Review 和用户视觉审查通过前不得发布 main/tag 或切换 Runtime。

---

## File Map

### Create

- `apps/quant-web/src/utils/marketFocus.ts` — 首页 Focus qualification / ordering / copy projection。
- `apps/quant-web/src/components/market/MarketFocusList.vue` — 0~3 优先检查展示。
- `apps/quant-web/tests/marketFocus.test.ts` — Focus pure utility unit tests。
- `apps/quant-web/src/utils/productCheck.ts` — 详情页市场背景、Event 状态和观察摘要的纯 view helper。
- `apps/quant-web/tests/productCheck.test.ts` — product-check pure utility tests。
- `apps/quant-web/src/components/market/ProductCheckSidebar.vue` — 新“当前检查栏”。

### Modify

- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- `apps/quant-web/src/components/market/ProductAlertRules.vue`（仅当需要暴露 Runtime label 给新侧栏；不得改 API/Scope 行为）
- `apps/quant-web/e2e/market-radar.spec.mjs`
- `apps/quant-web/e2e/market-research.spec.mjs`
- `apps/quant-web/tests/market-workspace-preferences.test.ts`（仅在 toolbar 改动触及偏好时）

### Delete only after zero-reference check

- `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- `apps/quant-web/src/components/market/ProductFormalSignalCard.vue`
- `apps/quant-web/src/components/market/SubingStatusStrip.vue`

### Reuse unchanged where possible

- `MarketFormalSignals.vue`
- `MarketSummaryStrip.vue`
- `MarketScatter.vue`
- `MarketAttentionList.vue`
- `MarketDetailTable.vue`
- `ProductTodayAlertEvents.vue`
- `SubingResearchSection.vue`
- `SubingLifecyclePanel.vue`
- `PriceVolumeOiPanel.vue`
- existing `getEventStates()` / `executionReviewActionLabel()`.

---

## Task 1: Homepage Focus projection and collapsed full-market research

**Files:**
- Create: `apps/quant-web/src/utils/marketFocus.ts`
- Create: `apps/quant-web/src/components/market/MarketFocusList.vue`
- Create: `apps/quant-web/tests/marketFocus.test.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/e2e/market-radar.spec.mjs`
- Modify: homepage assertions in `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**

```ts
export type MarketFocusDirection = 'long' | 'short'

export interface MarketFocusItem {
  item: MarketRadarItem
  direction: MarketFocusDirection
  reasonLabels: string[]
  riskLabel: string | null
}

export function selectMarketFocus(items: MarketRadarItem[]): MarketFocusItem[]
```

`selectMarketFocus()` must return a new array of length `0..3`; it must never mutate `items` or `reason_codes`.

- [ ] **Step 1: Write failing unit tests for exact qualification**

Create `apps/quant-web/tests/marketFocus.test.ts` with cases that prove direction alone is insufficient, direction + one participation fact qualifies, and location/risk alone does not qualify.

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import { selectMarketFocus } from '../src/utils/marketFocus.ts'
import type { MarketRadarItem } from '../src/types/market.ts'

function item(symbol: string, reason_codes: string[], overrides: Partial<MarketRadarItem> = {}): MarketRadarItem {
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    price_change_1d: 0.01,
    price_change_5d: 0.02,
    volume_ratio20: 1.2,
    oi_change_1d: 0.01,
    atr14_percentile252: 0.5,
    position20: 0.5,
    turnover: 1000,
    reason_codes,
    ...overrides,
  }
}

test('focus requires EMA direction plus at least one participation fact', () => {
  assert.deepEqual(selectMarketFocus([
    item('a', ['ema21_up']),
    item('b', ['ema21_up', 'near_20d_high']),
    item('c', ['ema21_up', 'high_volatility']),
    item('d', ['ema21_up', 'oi_increase']),
    item('e', ['ema21_down', 'price_move_down']),
  ]).map((entry) => [entry.item.symbol, entry.direction]), [
    ['d', 'long'],
    ['e', 'short'],
  ])
})
```

- [ ] **Step 2: Run the unit test and confirm RED**

Run:

```bash
pnpm --dir apps/quant-web exec node --test tests/marketFocus.test.ts
```

Expected: FAIL because `src/utils/marketFocus.ts` does not exist.

- [ ] **Step 3: Implement the minimal pure Focus selector**

Create `apps/quant-web/src/utils/marketFocus.ts` with these exact rule sets and stable tuple sort:

```ts
import type { MarketRadarItem } from '@/types/market'

export type MarketFocusDirection = 'long' | 'short'

export interface MarketFocusItem {
  item: MarketRadarItem
  direction: MarketFocusDirection
  reasonLabels: string[]
  riskLabel: string | null
}

const MAX_FOCUS_ITEMS = 3
const LONG_PARTICIPATION = ['price_move_up', 'volume_expansion', 'oi_increase'] as const
const SHORT_PARTICIPATION = ['price_move_down', 'volume_expansion', 'oi_increase'] as const

const REASON_LABELS: Record<string, string> = {
  price_move_up: '价格上涨',
  price_move_down: '价格下跌',
  volume_expansion: '放量',
  oi_increase: '增仓',
  near_20d_high: '接近20日高位',
  near_20d_low: '接近20日低位',
}

function has(item: MarketRadarItem, code: string) {
  return item.reason_codes.includes(code)
}

function direction(item: MarketRadarItem): MarketFocusDirection | null {
  if (has(item, 'ema21_up') && LONG_PARTICIPATION.some((code) => has(item, code))) return 'long'
  if (has(item, 'ema21_down') && SHORT_PARTICIPATION.some((code) => has(item, code))) return 'short'
  return null
}

function directionalCodes(value: MarketFocusDirection) {
  return value === 'long' ? LONG_PARTICIPATION : SHORT_PARTICIPATION
}

function focusItem(item: MarketRadarItem, value: MarketFocusDirection): MarketFocusItem {
  const locationCode = value === 'long' ? 'near_20d_high' : 'near_20d_low'
  const labels = [...directionalCodes(value), locationCode]
    .filter((code) => has(item, code))
    .map((code) => REASON_LABELS[code])
    .slice(0, 3)
  return {
    item,
    direction: value,
    reasonLabels: labels,
    riskLabel: has(item, 'oi_decrease') ? '减仓推动' : has(item, 'high_volatility') ? '高波动' : null,
  }
}

function supportCount(entry: MarketFocusItem) {
  return directionalCodes(entry.direction).filter((code) => has(entry.item, code)).length
}

export function selectMarketFocus(items: MarketRadarItem[]): MarketFocusItem[] {
  return items
    .flatMap((item) => {
      const value = direction(item)
      return value ? [focusItem(item, value)] : []
    })
    .sort((left, right) => {
      const support = supportCount(right) - supportCount(left)
      if (support) return support
      const oi = Number(has(right.item, 'oi_increase')) - Number(has(left.item, 'oi_increase'))
      if (oi) return oi
      const volume = Number(has(right.item, 'volume_expansion')) - Number(has(left.item, 'volume_expansion'))
      if (volume) return volume
      const leftPriceCode = left.direction === 'long' ? 'price_move_up' : 'price_move_down'
      const rightPriceCode = right.direction === 'long' ? 'price_move_up' : 'price_move_down'
      const price = Number(has(right.item, rightPriceCode)) - Number(has(left.item, leftPriceCode))
      if (price) return price
      const turnover = (right.item.turnover ?? Number.NEGATIVE_INFINITY) - (left.item.turnover ?? Number.NEGATIVE_INFINITY)
      if (turnover) return turnover
      return left.item.symbol.localeCompare(right.item.symbol)
    })
    .slice(0, MAX_FOCUS_ITEMS)
}
```

Do not add score fields or runtime thresholds.

- [ ] **Step 4: Add ordering / risk / cap tests and turn GREEN**

Add tests asserting:

```ts
test('focus uses transparent tuple ordering and caps output at three', () => {
  const result = selectMarketFocus([
    item('a', ['ema21_up', 'price_move_up'], { turnover: 5000 }),
    item('b', ['ema21_up', 'price_move_up', 'volume_expansion'], { turnover: 1000 }),
    item('c', ['ema21_down', 'price_move_down', 'oi_increase'], { turnover: 900 }),
    item('d', ['ema21_up', 'price_move_up', 'volume_expansion', 'oi_increase'], { turnover: 100 }),
  ])
  assert.deepEqual(result.map((entry) => entry.item.symbol), ['d', 'c', 'b'])
})

test('focus projects one risk with oi decrease before high volatility', () => {
  const [result] = selectMarketFocus([
    item('a', ['ema21_up', 'price_move_up', 'oi_decrease', 'high_volatility']),
  ])
  assert.equal(result.riskLabel, '减仓推动')
})
```

Run:

```bash
pnpm --dir apps/quant-web exec node --test tests/marketFocus.test.ts
```

Expected: PASS.

- [ ] **Step 5: Create `MarketFocusList.vue`**

Implement a presentational component with props:

```ts
const props = defineProps<{
  radar: MarketRadarResponse
}>()
const emit = defineEmits<{ open: [item: MarketRadarItem] }>()
const items = computed(() => props.radar.freshness_state === 'degraded' ? [] : selectMarketFocus(props.radar.items))
```

Required DOM/test contract:

```text
data-testid="market-focus"
data-testid="market-focus-card"
heading: 优先检查
current meta: 基于 {data_as_of} 完整日线 · {participant_count}/{active_count}
pending meta additionally includes: {target_as_of} 盘后更新待完成
degraded body: 优先检查暂不可用：Radar 数据不完整。
zero body: 当前没有同时满足趋势与参与条件的优先检查品种。
footer: 其余 {participant_count - items.length} 个当前不优先检查
button: 检查详情
```

Card direction labels are exactly `多头观察` and `空头观察`.

- [ ] **Step 6: Restructure `/market` without new route**

Modify `apps/quant-web/src/pages/market/index.vue` so the order is:

```vue
<MarketFormalSignals ... />
<MarketFocusList v-if="radar" :radar="radar" @open="openChart" />
<details v-if="radar" class="market-radar-page__research" data-testid="market-full-research">
  <summary>展开全市场研究</summary>
  <MarketSummaryStrip :radar="radar" />
  <div class="market-radar-page__discovery">
    <MarketScatter :items="radar.items" @open="openChart" />
    <MarketAttentionList :items="radar.attention" @open="openChart" />
  </div>
  <MarketDetailTable ... />
</details>
```

Keep current skeleton, refresh failure, freshness alert and watchlist behavior. Do not create a second Radar route.

- [ ] **Step 7: Rewrite homepage E2E around the B1 contract**

In `market-radar.spec.mjs`, make the fixture include `ema21_up/down`; assert:

```js
await expect(page.getByTestId('market-focus')).toBeVisible()
await expect(page.getByTestId('market-focus-card')).toHaveCount(1)
await expect(page.getByText('多头观察', { exact: true })).toBeVisible()
await expect(page.getByText('市场概览', { exact: true })).toHaveCount(0)
await page.getByText('展开全市场研究', { exact: true }).click()
await expect(page.getByText('市场概览', { exact: true })).toBeVisible()
await expect(page.getByText('价格变化 × OI 变化', { exact: true })).toBeVisible()
```

For degraded:

```js
await expect(page.getByTestId('market-focus')).toContainText('优先检查暂不可用')
await expect(page.getByTestId('market-focus-card')).toHaveCount(0)
```

For pending:

```js
await expect(page.getByTestId('market-focus')).toContainText('基于 2026-08-10 完整日线')
await expect(page.getByTestId('market-focus')).toContainText('2026-08-11 盘后更新待完成')
```

Update homepage ordering assertions in `market-research.spec.mjs` from `.market-attention`/`.radar-summary` to `[data-testid="market-focus"]`.

- [ ] **Step 8: Run Task 1 tests**

```bash
pnpm --dir apps/quant-web exec node --test tests/marketFocus.test.ts
pnpm --dir apps/quant-web exec playwright test e2e/market-radar.spec.mjs e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1 checkpoint**

```bash
git add \
  apps/quant-web/src/utils/marketFocus.ts \
  apps/quant-web/src/components/market/MarketFocusList.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/tests/marketFocus.test.ts \
  apps/quant-web/e2e/market-radar.spec.mjs \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): compress market homepage decisions"
```

---

## Task 2: Product verification model and current-check sidebar

**Files:**
- Create: `apps/quant-web/src/utils/productCheck.ts`
- Create: `apps/quant-web/tests/productCheck.test.ts`
- Create: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Reuse: `ProductAlertRules.vue`, `ProductTodayAlertEvents.vue`, `SubingResearchSection.vue`, `PriceVolumeOiPanel.vue`

**Interfaces:**

```ts
export interface MarketBackgroundSummary {
  label: '同向偏多' | '同向偏空' | '中性' | '未共振' | '数据不足'
  tone: 'up' | 'down' | 'neutral' | 'warning'
}

export function summarizeMarketBackground(
  daily: ProductResearchResponse['daily_trend'],
  weekly: ProductResearchResponse['weekly_trend'],
): MarketBackgroundSummary

export interface FormalEventSummary {
  event: AlertEvent
  state: EventState | null
  headline: string
  actionLabel: string | null
}

export function summarizeFormalEvent(
  items: AlertEvent[],
  states: Record<number, EventState>,
): FormalEventSummary | null
```

- [ ] **Step 1: Write failing pure-helper tests**

Create `apps/quant-web/tests/productCheck.test.ts`:

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeMarketBackground, summarizeFormalEvent } from '../src/utils/productCheck.ts'

const event = {
  id: 17,
  rule_code: 'subing_entry_signal_v1',
  symbol: 'ag',
  contract: 'AG2601',
  trading_day: '2026-08-21',
  frequency: '15m',
  bar_end: '2026-08-21T02:30:00Z',
  result_codes: ['buy'],
  lower_tf_confirmation: true,
  detected_at: '2026-08-21T02:31:00Z',
  notification_attempted_at: null,
}

test('market background keeps aligned and conflict semantics explicit', () => {
  assert.equal(summarizeMarketBackground('up', 'up').label, '同向偏多')
  assert.equal(summarizeMarketBackground('down', 'down').label, '同向偏空')
  assert.equal(summarizeMarketBackground('neutral', 'neutral').label, '中性')
  assert.equal(summarizeMarketBackground('up', 'neutral').label, '未共振')
  assert.equal(summarizeMarketBackground('unavailable', 'up').label, '数据不足')
})

test('formal event summary uses EventState and never invents one', () => {
  assert.equal(summarizeFormalEvent([event], {})?.actionLabel, null)
  assert.equal(summarizeFormalEvent([event], {
    17: { event_id: 17, state: 'pending_decision', decision_id: null, episode_id: null },
  })?.actionLabel, '记录执行')
})
```

- [ ] **Step 2: Run helper tests and confirm RED**

```bash
pnpm --dir apps/quant-web exec node --test tests/productCheck.test.ts
```

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Implement `productCheck.ts` minimally**

Use the existing `executionReviewActionLabel()` and current alert presentation helpers; do not duplicate business state machines.

```ts
import type { AlertEvent, ProductResearchResponse } from '@/types/market'
import type { EventState } from '@/types/executionReview'
import { executionReviewActionLabel } from '@/utils/executionReview'
import { alertResultLabel, alertRuleShortLabel } from '@/utils/alertRules'

export interface MarketBackgroundSummary {
  label: '同向偏多' | '同向偏空' | '中性' | '未共振' | '数据不足'
  tone: 'up' | 'down' | 'neutral' | 'warning'
}

export function summarizeMarketBackground(
  daily: ProductResearchResponse['daily_trend'],
  weekly: ProductResearchResponse['weekly_trend'],
): MarketBackgroundSummary {
  if (daily === 'unavailable' || weekly === 'unavailable') return { label: '数据不足', tone: 'warning' }
  if (daily === 'up' && weekly === 'up') return { label: '同向偏多', tone: 'up' }
  if (daily === 'down' && weekly === 'down') return { label: '同向偏空', tone: 'down' }
  if (daily === 'neutral' && weekly === 'neutral') return { label: '中性', tone: 'neutral' }
  return { label: '未共振', tone: 'warning' }
}

export interface FormalEventSummary {
  event: AlertEvent
  state: EventState | null
  headline: string
  actionLabel: string | null
}

export function summarizeFormalEvent(
  items: AlertEvent[],
  states: Record<number, EventState>,
): FormalEventSummary | null {
  const event = [...items].sort((a, b) => Date.parse(b.bar_end) - Date.parse(a.bar_end))[0]
  if (!event) return null
  const state = states[event.id] ?? null
  return {
    event,
    state,
    headline: `${alertRuleShortLabel(event.rule_code)} · ${alertResultLabel(event.rule_code, event.result_codes)}`,
    actionLabel: state ? executionReviewActionLabel(state.state) : null,
  }
}
```

If the exact existing helper signatures differ, use the existing exported signatures rather than inventing new domain semantics; keep the two public functions above unchanged.

- [ ] **Step 4: Wire existing event-state read into `chart.vue`**

Import:

```ts
import { getEventStates } from '@/api/executionReview'
import type { EventState } from '@/types/executionReview'
```

Add:

```ts
const currentEventStates = ref<Record<number, EventState>>({})
let currentEventStateGeneration = 0

async function refreshCurrentEventStates() {
  const generation = ++currentEventStateGeneration
  if (currentEventsStatus.value !== 'ready' || currentEvents.value.length === 0) {
    currentEventStates.value = {}
    return
  }
  try {
    const response = await getEventStates(currentEvents.value.map((item) => item.id))
    if (generation !== currentEventStateGeneration) return
    currentEventStates.value = Object.fromEntries(response.items.map((item) => [item.event_id, item]))
  } catch {
    if (generation === currentEventStateGeneration) currentEventStates.value = {}
  }
}
```

Watch `[currentEventsStatus, currentEvents]` and call it after product current-event refresh. Failure must only remove processing-state projection; it must not erase AlertEvent facts or Kline.

- [ ] **Step 5: Create `ProductCheckSidebar.vue` with six fixed sections**

Props must include existing facts only:

```ts
const props = defineProps<{
  dominant: DominantContractItem | undefined
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract: string
  live: boolean
  phase: string
  hasMoreBefore: boolean
  watchlisted: boolean
  research: ProductResearchResponse | null
  researchLoading: boolean
  researchError: boolean
  selectedOverlay: ResearchOverlayId
  subing: SubingResearchResponse | null
  subingLoading: boolean
  subingError: boolean
  subingSupported: boolean
  alertRules: ProductAlertRuleState[]
  alertRuntimeStatus: AlertRuntimeStatus | null
  alertLoading: boolean
  savingRuleCodes: Set<string>
  currentEventsLoading: boolean
  currentEventsStatus: 'ready' | 'unavailable' | null
  currentEvents: AlertEvent[]
  currentEventStates: Record<number, EventState>
  htdyObservation: KlineMarker | null
}>()
```

Emits:

```ts
const emit = defineEmits<{
  'toggle-watchlist': []
  'toggle-alert': [ruleCode: string, enabled: boolean]
  'open-formal-event': [event: AlertEvent, state: EventState | null]
}>()
```

Required DOM order and test ids:

```text
product-check-sidebar
product-check-now
product-check-background
product-check-observation
product-check-participation
product-check-alerts
product-check-more
```

Use native `<details>` for `product-check-more`, default closed.

“现在” rules:

```text
currentEventsStatus === unavailable -> 正式事件暂不可用
ready + no event -> 当前无正式事件 / 继续观察
ready + event + state -> headline + action button
ready + event + no state -> headline + 今日正式提醒记录
```

“市场背景” uses `summarizeMarketBackground()`.

“当前观察”:

```text
none -> 当前未选择策略观察
subing loading/error/unsupported -> existing explicit unavailable copy
subing ready -> current V1 signal/factor summary + Lifecycle stage/progress; Research only tag only beside Lifecycle
htdy -> latest observation + 原始观察可能重绘，仅供人工观察
```

“位置 / 参与” shows only `position20 / volume_ratio20 / oi_change_1d / atr14_percentile252`.

“提醒” embeds `ProductAlertRules` once.

“更多研究” embeds existing `SubingResearchSection`, `ProductTodayAlertEvents`, `PriceVolumeOiPanel`, and the current contract/runtime/boundary facts. Do not duplicate alert switches inside this disclosure.

- [ ] **Step 6: Replace sidebar usage in `chart.vue`**

Replace both desktop and Drawer instances of `ProductResearchSidebar` with `ProductCheckSidebar`; pass `currentEventStates` and handle `open-formal-event`.

Add an `openFormalEvent(event, state)` function mirroring the homepage routing semantics:

```ts
function openFormalEvent(event: AlertEvent, state: EventState | null) {
  if (!state) return
  const useEpisode = state.state === 'open' || state.state === 'pending_review'
  void router.push({
    name: 'trade-records',
    query: {
      state: state.state,
      event_id: useEpisode ? undefined : String(event.id),
      episode_id: useEpisode && state.episode_id ? String(state.episode_id) : undefined,
    },
  })
}
```

Do not create navigation for HTDY if it has no Execution Review state.

- [ ] **Step 7: Remove normal-state duplicate SuBing strip from above the chart**

The ready-state summary now belongs in `ProductCheckSidebar`.

Before deleting `SubingStatusStrip.vue`, reproduce explicit states in the sidebar:

```text
unsupported -> 苏冰当前周期不可用，仅支持 5m / 15m / 1d
loading -> 苏冰观察加载中
error -> 苏冰观察暂不可用；K 线保留当前展示行情
insufficient data -> 指标 warm-up 中 / 数据不足
```

Then remove `<SubingStatusStrip ... />` from `chart.vue`.

- [ ] **Step 8: Rewrite detail E2E around semantic layers**

In `market-research.spec.mjs`, replace normal `.subing-strip` expectations with sidebar checks. Required examples:

```js
await expect(page.getByTestId('product-check-now')).toContainText('当前无正式事件')
await expect(page.getByTestId('product-check-background')).toContainText('周线')
await expect(page.getByTestId('product-check-background')).toContainText('日线')
await expect(page.getByTestId('product-check-observation')).toContainText('苏冰')
await expect(page.getByTestId('product-check-observation')).toContainText('Research only')
await expect(page.getByTestId('product-check-now')).not.toContainText('研究确认')
```

Add a case where current AlertEvent exists but EventState request returns empty; assert Event remains visible and no “记录执行/查看交易” state is invented.

Keep existing tests that prove Kline stays visible during Subing loading/error and dominant refresh; update selectors, not behavior.

- [ ] **Step 9: Run Task 2 tests**

```bash
pnpm --dir apps/quant-web exec node --test tests/productCheck.test.ts
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 10: Commit Task 2 checkpoint**

```bash
git add \
  apps/quant-web/src/utils/productCheck.ts \
  apps/quant-web/src/components/market/ProductCheckSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/productCheck.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git add -u apps/quant-web/src/components/market
git commit -m "feat(web): turn product workspace into verification view"
```

---

## Task 3: Simplify toolbar/status shell and move deep research behind disclosure

**Files:**
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`
- Modify only if needed: `apps/quant-web/tests/market-workspace-preferences.test.ts`
- Delete only if zero references remain: `ProductResearchSidebar.vue`, `ProductFormalSignalCard.vue`, `SubingStatusStrip.vue`

**Interfaces:** existing toolbar emits for symbol/series/frequency/overlay/EMA/manual contract remain semantically unchanged; presentation is regrouped only.

- [ ] **Step 1: Add failing E2E for simplified toolbar**

Add assertions at desktop width:

```js
await expect(page.getByRole('button', { name: '图表设置', exact: true })).toBeVisible()
await expect(page.getByRole('group', { name: 'EMA' })).toHaveCount(0)
await expect(page.getByRole('button', { name: '高级', exact: true })).toHaveCount(0)
await page.getByRole('button', { name: '图表设置', exact: true }).click()
await expect(page.getByRole('button', { name: 'EMA10', exact: true })).toBeVisible()
await expect(page.getByRole('button', { name: 'EMA60', exact: true })).toBeVisible()
await expect(page.getByText('指定真实合约', { exact: true })).toBeVisible()
```

- [ ] **Step 2: Consolidate EMA and manual contract into `图表设置`**

In `ProductWorkspaceToolbar.vue`:

- keep period and Overlay groups first-class;
- remove inline EMA group;
- replace current `高级` popover with one `NPopover` trigger `图表设置`;
- inside, render an “EMA” group with EMA10/EMA60 buttons and the existing manual-contract input/action.

Do not change preference keys or `optionalEmaIndicators` semantics.

- [ ] **Step 3: Compress identity card into status strip**

Replace the current `NCard.identity-card` with a compact element:

```vue
<div class="product-status-strip" data-testid="product-status-strip">
  <strong>{{ effectiveIdentity.contract || selectedDominant?.actual_contract || symbol.toUpperCase() }}</strong>
  <NTag :type="isLiveDisplay ? 'success' : (isPostCloseDisplay ? 'warning' : 'default')">{{ displayStateLabel }}</NTag>
  <span>{{ phaseLabel }}</span>
  <NTag v-if="afterMarketFailed" type="warning">最近盘后更新失败</NTag>
  <span v-if="!afterMarketFailed" class="product-status-strip__ok">数据正常</span>
  <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
</div>
```

Do not remove canonical coverage or `hasMoreBefore`; move those facts into “更多研究 → 数据 / 合约详情”。

- [ ] **Step 4: Remove the standalone bottom Price/Volume/OI panel**

Delete the page-level `<PriceVolumeOiPanel>` and research-error panel from below `.product-workspace`; the same data/error must be reachable inside `ProductCheckSidebar` more-research disclosure.

This is a presentation move only; no new API request.

- [ ] **Step 5: Rename narrow-width entry from “研究” to “检查”**

Keep the existing `researchSidebarOpen` localStorage key to avoid preference migration. Rename only visible copy/emit naming if convenient; do not create a new preference version for a label change.

At `980~1199`, existing Drawer access must remain available. At `<980`, no horizontal overflow is allowed.

- [ ] **Step 6: Verify zero references before deleting old files**

Run:

```bash
rg -n "ProductResearchSidebar|ProductFormalSignalCard|SubingStatusStrip" apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
```

Expected before delete: only file-local references or none.

Delete only files with zero active imports. If one still has an intentional consumer, keep it and report why; do not delete mechanically.

- [ ] **Step 7: Add shell and research-disclosure E2E**

Required checks:

```js
await expect(page.getByTestId('product-status-strip')).toContainText('Live')
await expect(page.getByTestId('product-status-strip')).toContainText('交易中')
await expect(page.getByText('Price / Volume / OI', { exact: true })).toHaveCount(0)
await page.getByTestId('product-check-more').locator('summary').click()
await expect(page.getByText('Price / Volume / OI', { exact: true })).toBeVisible()
```

For an after-market failure fixture, assert the status strip shows `最近盘后更新失败` instead of `数据正常`.

- [ ] **Step 8: Run Task 3 tests**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs e2e/market-radar.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3 checkpoint**

```bash
git add apps/quant-web
git commit -m "refactor(web): simplify market verification shell"
```

---

## Task 4: Cross-page acceptance, scope audit, independent review, integration

**Files:**
- Modify only if acceptance exposes a B1 bug: files already whitelisted in Tasks 1~3.
- Test: `apps/quant-web/e2e/market-radar.spec.mjs`
- Test: `apps/quant-web/e2e/market-research.spec.mjs`
- Docs: this spec/plan/task contract only for factual corrections found during implementation.

- [ ] **Step 1: Add one cross-page B1 journey test**

Use a Radar fixture where AG qualifies Focus. Test:

```text
/market
→ formal section is first
→ AG appears in 优先检查
→ full-market research is closed
→ click AG 检查详情
→ /market/chart?symbol=ag...
→ product-check-now visible
→ product-check-background visible
→ product-check-observation visible
→ product-check-participation visible
→ more research closed
```

The test must not assert trading profitability or “best opportunity”.

- [ ] **Step 2: Run responsive acceptance at existing desktop sizes**

For both `/market` and `/market/chart`, iterate:

```js
[
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1024, height: 768 },
]
```

Assert:

```js
expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
```

At 1024 detail view, verify the “检查” Drawer entry remains usable when the side panel is hidden.

- [ ] **Step 3: Run full Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: all PASS; secret scan 0 high-confidence findings.

- [ ] **Step 4: Audit forbidden scope**

Run:

```bash
git diff --name-only develop...HEAD
```

Allowed production-code root is `apps/quant-web/**` only. Docs may include:

```text
docs/superpowers/specs/2026-08-22-market-b1-decision-compression-design.md
docs/superpowers/plans/2026-08-22-market-b1-decision-compression.md
docs/tasks/TASK-WEB-B1-DECISION-COMPRESSION-20260822.md
```

Fail the task if diff includes backend, migration, MarketDataService, Alert backend, Runtime, Canonical, DB or strategy code.

Also search for prohibited design drift:

```bash
rg -n "Opportunity(Service|Model)|opportunity_score|综合分|最佳机会|推荐交易" apps/quant-web/src
```

Expected: no new B1 implementation matches. Existing unrelated historical copy, if any, must be listed rather than silently changed.

- [ ] **Step 5: Independent review**

Open a fresh review session. Review only `develop...HEAD` against the spec. Required verdict dimensions:

```text
Critical
Important
Minor
```

Review specifically checks:

- Focus is only D1 view projection;
- degraded fail-closed;
- Event vs research separation;
- Lifecycle Research-only boundary;
- existing Kline display identity not changed;
- no hidden backend/domain expansion;
- full-market and deep-research abilities remain accessible;
- responsive/accessibility regressions.

Any Critical/Important finding blocks integration.

- [ ] **Step 6: Commit acceptance-only fixes if needed**

If review/acceptance requires fixes, make only scoped fixes and rerun the affected Task + full Web verification. Then:

```bash
git add apps/quant-web docs/superpowers docs/tasks
git commit -m "test(web): close B1 decision compression acceptance"
```

Skip this commit if no files changed.

- [ ] **Step 7: Integrate to `develop` and clean task workspace**

After all tests and independent review pass:

```text
feat/web-b1-decision-compression
→ develop
```

Read back that the feature commits are ancestors of `develop`, then remove the temporary task worktree and merged branch.

Do not release main/tag or switch Runtime as part of this task.

---

## Execution Handoff

Recommended execution: one Codex App implementation session on `feat/web-b1-decision-compression`, using this plan task-by-task; then a fresh independent Review session for Task 4.

The feature is complete only when Tasks 1~4 all pass. A green Task 1 homepage alone or Task 2 detail alone is not sufficient to declare the B1 flow complete.
