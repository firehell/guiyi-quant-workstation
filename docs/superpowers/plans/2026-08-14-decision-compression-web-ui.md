# Decision Compression Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Design source: `docs/superpowers/specs/2026-08-14-decision-compression-alert-v2-design.md`  
Backend dependency: `docs/superpowers/plans/2026-08-14-alert-v2-backend-runtime.md`  
Lane: **Lane 2** after backend DTOs are finalized on `develop`

**Goal:** 把现有暗色 Market Web 升级为高对比亮色的“先结论、后细节”工作台：Market 首页最先展示当前交易日 Formal Signal，Product Workspace 明确区分 SuBing 正式信号与 HTDY 观察提醒，并支持两个独立 Rule Scope 开关、当前交易日记录和 exact-frequency persistent markers，同时不删除 v1.1 Radar/Kline 已封板能力。

**Architecture:** Web 只消费 backend V2 semantic DTO，不重新推 trading day、不解释 SuBing 数学、不创建 Signal 状态。首页新增 `MarketFormalSignals` 只读区；Product Workspace 将现有单 HTDY scope composable 扩为 rule-list state，并新增 current-events read model。Persistent marker 仍复用历史 `/api/alerts/events`，按 exact series/frequency 请求固定 Rule 集合。全局主题统一切到固定亮色，不提供亮/暗切换；K 线继续遵守中国期货红涨绿跌。

**Tech Stack:** Vue 3 / TypeScript / Vite / Pinia / Naive UI / lightweight-charts / pnpm / Node test runner / Playwright；现有 Market API / Alert API / `useMarketSeries` / `useSubingObservation` / Kline components。

## Global Constraints

- Web 开始前必须只读确认 backend V2 DTO 已落到 `develop`：Product Rule State、AlertEvent V2、`/formal-signals/current`、`/products/{symbol}/current-events` 字段与本计划一致；若不一致，先 rebase 本计划，不在前端发明兼容字段。
- 当前 active Web 产品面仍只有 Market 工作台与 Product Workspace；不得照概念图新增“品种/研究/设置”路由、全局搜索平台或第二 Dashboard。
- Market Radar P0 的 Summary、Scatter、Attention、Sector、Detail Table 全部保留；只调整视觉层级，不删除功能。
- Kline 继续是 Product Workspace 主视觉；不得缩成普通卡片，也不新增画线、任意 pane、TradingView clone、RSI/KDJ 等范围外能力。
- 信息层级固定：Formal Signal = 需要处理；Radar Attention = 值得看；HTDY = 观察提醒；Research Facts = 次级细节。
- 首页“需要处理”只显示 backend `kind=formal_signal` 当前交易日 Event；HTDY 绝不进入该区域。
- Product “今日记录”只消费 `/api/alerts/products/{symbol}/current-events`；前端不得自己推交易日，也不得分别查两个 Rule 再合并。
- 一个 SuBing switch 同时控制 5m + 15m；不得暴露 5m/15m 子开关。
- 两个 Rule Scope 独立；自选不驱动 Scope，HTDY 开关不联动 SuBing。
- Scope PUT 是真实生产 DB 写入；普通 unit/E2E 只使用 mock API。真实开关留给独立 rollout Gate。
- Persistent Marker exact-frequency：HTDY 只 actual_dominant+15m；SuBing 5m 只 actual_dominant+5m；SuBing 15m 只 actual_dominant+15m；不得跨周期/跨 series 投影。
- 中国期货方向颜色必须保持：买入/LONG/上涨方向 = 红；卖出/SHORT/下跌方向 = 绿。概念稿中的买绿卖红不得实现。
- HTDY category 用橙色 surface/边框表达“观察”，但具体买/卖仍必须文字化；状态不能只靠颜色。
- 不新增 score、confidence、星级、“信号质量高”“趋势强度较强”等不存在的业务字段。
- 亮色视觉为唯一 active theme；不增加 theme toggle。若现有 dark-only store 只剩无消费者，应删除，而不是保留死切换状态。
- 不修改后端业务公式、DB migration、Runtime、WeCom、Canonical 或 MarketDataService。
- Lane 2 默认 Terra / 中推理 / Plan-then-execute；当前 `AGENTS.md` 允许直接 `develop` 日常流，task worktree/PR 按需。

---

## Start Readback

Task 1 开始前只读确认：

```text
1. ProductAlertRuleStateOut = rule_code/display_name/kind/input_frequencies/enabled_for_product
2. AlertEventOut = V2 result_codes/trading_day/lower_tf_confirmation/notification_attempted_at
3. GET /api/alerts/formal-signals/current exists
4. GET /api/alerts/products/{symbol}/current-events exists
5. current endpoints distinguish ready empty vs unavailable
6. Market index still renders Summary + Scatter + Attention + Sector + Detail
7. chart.vue still composes useMarketSeries + useSubingObservation + persistent Alert markers
8. tokens.css/theme.ts are still current global style sources
```

---

## File Map

### API / types / state

- Modify: `apps/quant-web/src/api/alerts.ts` — V2 Rule/Event/current endpoint contracts。
- Modify: `apps/quant-web/src/types/market.ts` — AlertEvent V2 and helpers only where shared Market types belong。
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts` — single-rule state → two-rule collection with per-rule saving state。
- Create: `apps/quant-web/src/composables/useCurrentFormalSignals.ts` — Market 首页只读 current Formal Signal lifecycle。
- Create: `apps/quant-web/src/composables/useProductCurrentAlertEvents.ts` — Product 今日记录 lifecycle。
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts` — exact-frequency historical Rule request set。
- Modify: `apps/quant-web/src/utils/alertMarkers.ts` — V2 result_codes + Rule category + exact-frequency marker mapping。
- Modify: `apps/quant-web/src/utils/alertControl.ts` only if per-rule mutation guard needs a generic helper。

### Market homepage

- Create: `apps/quant-web/src/components/market/MarketFormalSignals.vue`。
- Modify: `apps/quant-web/src/pages/market/index.vue`。

### Product Workspace

- Create: `apps/quant-web/src/components/market/ProductFormalSignalCard.vue`。
- Create: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`。
- Create: `apps/quant-web/src/components/market/ProductAlertRules.vue`。
- Delete after replacement: `apps/quant-web/src/components/market/ProductAlertControl.vue`。
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`。
- Modify: `apps/quant-web/src/components/market/SubingResearchSection.vue` — research facts move to secondary presentation; no formula changes。
- Modify: `apps/quant-web/src/pages/market/chart.vue` — current formal signal / rules / current-events wiring。

### Theme / layout

- Modify: `apps/quant-web/src/styles/tokens.css` — fixed high-contrast light tokens, preserve red-up/green-down domain colors。
- Modify: `apps/quant-web/src/styles/theme.ts` — Naive UI light overrides aligned with tokens。
- Modify: `apps/quant-web/src/styles/chartTheme.ts` — light fallback chart palette only; up/down contract unchanged。
- Modify: `apps/quant-web/src/App.vue` — stop passing `darkTheme`。
- Delete if still unused after App change: `apps/quant-web/src/stores/app.ts`。
- Modify: `apps/quant-web/src/layouts/MainLayout.vue` — light shell/sider/header contrast, no new routes。
- Modify: `apps/quant-web/src/style.css` only for global light surface/focus/text fixes required by tokens。

### Tests

- Modify: `apps/quant-web/tests/alerts.test.ts`。
- Create: `apps/quant-web/tests/currentFormalSignals.test.ts`。
- Create: `apps/quant-web/tests/productCurrentAlertEvents.test.ts`。
- Modify or create: `apps/quant-web/tests/alertMarkers.test.ts` if marker cases are not already inside `alerts.test.ts`.
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs` — becomes V2 regression while preserving HTDY natural semantics via mock API。
- Modify: `apps/quant-web/e2e/market-research.spec.mjs` — homepage hierarchy + existing Radar regression。

---

### Task 1: Adopt backend V2 Alert contracts in TypeScript

**Lane:** Lane 2

**Files:**
- Modify: `apps/quant-web/src/api/alerts.ts`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`

**Interfaces:**

```ts
export type AlertRuleKind = 'indicator_observation' | 'formal_signal'

export interface ProductAlertRuleState {
  rule_code: string
  display_name: string
  kind: AlertRuleKind
  input_frequencies: MarketFrequency[]
  enabled_for_product: boolean
}

export interface AlertEvent {
  id: number
  rule_code: string
  symbol: string
  contract: string
  trading_day: string | null
  frequency: MarketFrequency
  bar_end: string
  result_codes: ('buy' | 'sell')[]
  lower_tf_confirmation: boolean
  detected_at: string
  notification_attempted_at: string
}

export interface CurrentFormalSignalItem extends AlertEvent {
  display_name: string
  product_name: string
  trading_day: string
}

export interface CurrentFormalSignalsResponse {
  status: 'ready' | 'unavailable'
  trading_day: string | null
  items: CurrentFormalSignalItem[]
}

export interface ProductCurrentAlertEventsResponse {
  status: 'ready' | 'unavailable'
  trading_day: string | null
  items: AlertEvent[]
}
```

- [ ] **Step 1: Update API unit tests first**

Assert exact requests:

```ts
await getCurrentFormalSignals()
assert.equal(lastRequest.url, '/api/alerts/formal-signals/current')

await getProductCurrentAlertEvents('jm')
assert.equal(lastRequest.url, '/api/alerts/products/jm/current-events')
```

Also update old Rule expectations so no `indicator_code` or single `frequency` remains.

- [ ] **Step 2: Run unit test to RED**

```bash
pnpm --dir apps/quant-web test -- alerts.test.ts
```

If the project test runner does not accept a file argument, run `pnpm --dir apps/quant-web test` and confirm failures are limited to intended Alert contract changes.

- [ ] **Step 3: Implement exact TS DTOs and API functions**

```ts
export function getCurrentFormalSignals() {
  return request.get<never, CurrentFormalSignalsResponse>('/api/alerts/formal-signals/current')
}

export function getProductCurrentAlertEvents(symbol: string) {
  return request.get<never, ProductCurrentAlertEventsResponse>(
    `/api/alerts/products/${symbol}/current-events`,
  )
}
```

Keep historical `getAlertEvents({symbol, ruleCode, start, end})` for marker ranges.

- [ ] **Step 4: Run tests GREEN and commit**

```bash
pnpm --dir apps/quant-web test

git add apps/quant-web/src/api/alerts.ts apps/quant-web/src/types/market.ts apps/quant-web/tests/alerts.test.ts
git commit -m "refactor: adopt alert v2 web contracts"
```

---

### Task 2: Fixed high-contrast light theme and shell

**Lane:** Lane 2

**Files:**
- Modify: `apps/quant-web/src/styles/tokens.css`
- Modify: `apps/quant-web/src/styles/theme.ts`
- Modify: `apps/quant-web/src/styles/chartTheme.ts`
- Modify: `apps/quant-web/src/App.vue`
- Modify: `apps/quant-web/src/layouts/MainLayout.vue`
- Modify only if needed: `apps/quant-web/src/style.css`
- Delete if unused: `apps/quant-web/src/stores/app.ts`
- Add/modify tests only if current theme utilities have coverage

**Target palette:**

```text
--gy-bg-app:            #F8FAFC
--gy-bg-canvas:         #FFFFFF
--gy-bg-panel:          #FFFFFF
--gy-bg-panel-strong:   #F9FAFB
--gy-bg-elevated:       #F2F4F7
--gy-border:            #E4E7EC
--gy-border-strong:     #D0D5DD
--gy-text-primary:      #111827
--gy-text-secondary:    #374151
--gy-text-muted:        #667085
--gy-accent:            #2563EB
--gy-status-warning:    #F79009

--gy-up:                red family, keep current China futures meaning
--gy-down:              green family, keep current China futures meaning
```

Chart fallback target:

```ts
background: '#FFFFFF'
grid: '#EEF2F6'
axis: '#D0D5DD'
text: '#475467'
textMuted: '#667085'
up: red
down: green
```

- [ ] **Step 1: Add a token contract test if no current theme test exists**

Create a simple Node test that reads `tokens.css` and asserts:

```ts
assert.match(css, /--gy-bg-app:\s*#F8FAFC/i)
assert.match(css, /--gy-text-primary:\s*#111827/i)
assert.match(css, /--gy-up:/)
assert.match(css, /--gy-down:/)
```

The test should not hard-code that buy is green or sell is red.

- [ ] **Step 2: Run test to RED**

```bash
pnpm --dir apps/quant-web test
```

- [ ] **Step 3: Convert tokens and Naive UI overrides to light values**

Keep semantic variable names stable to minimize page churn. `theme.ts` must no longer describe itself as a dark theme. Do not add a second palette or runtime theme switch.

- [ ] **Step 4: Make `App.vue` fixed-light**

Target:

```vue
<script setup lang="ts">
import { NConfigProvider, NMessageProvider } from 'naive-ui'
import { themeOverrides } from '@/styles/theme'
</script>

<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <NMessageProvider><RouterView /></NMessageProvider>
  </NConfigProvider>
</template>
```

If `useAppStore` has no remaining consumers after this change, delete `stores/app.ts`; do not keep dead `toggleTheme()`.

- [ ] **Step 5: Update shell surfaces in `MainLayout.vue`**

Remove dark-only translucent/glow assumptions. Keep existing one Market menu route, collapse behavior, breadcrumb, BoundaryBadge, refresh and clock. Do not add mockup-only navigation.

- [ ] **Step 6: Run full Web tests and build**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

- [ ] **Step 7: Commit theme conversion**

```bash
git add apps/quant-web/src/App.vue apps/quant-web/src/layouts/MainLayout.vue \
  apps/quant-web/src/styles/tokens.css apps/quant-web/src/styles/theme.ts \
  apps/quant-web/src/styles/chartTheme.ts apps/quant-web/src/style.css \
  apps/quant-web/src/stores/app.ts
git commit -m "style: switch market web to high contrast light theme"
```

Omit files not actually changed/deleted from `git add`.

---

### Task 3: Market homepage “需要处理” current Formal Signal section

**Lane:** Lane 2

**Files:**
- Create: `apps/quant-web/src/composables/useCurrentFormalSignals.ts`
- Create: `apps/quant-web/src/components/market/MarketFormalSignals.vue`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Create: `apps/quant-web/tests/currentFormalSignals.test.ts`
- Modify: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**

```ts
interface CurrentFormalSignalsState {
  loading: Ref<boolean>
  status: Ref<'ready' | 'unavailable' | null>
  tradingDay: Ref<string | null>
  items: Ref<CurrentFormalSignalItem[]>
  refresh: () => Promise<void>
}
```

Component props/events:

```ts
const props = defineProps<{
  loading: boolean
  status: 'ready' | 'unavailable' | null
  tradingDay: string | null
  items: CurrentFormalSignalItem[]
}>()

const emit = defineEmits<{
  open: [item: CurrentFormalSignalItem]
}>()
```

- [ ] **Step 1: Write composable state tests**

```ts
test('ready empty is different from unavailable', async () => {
  const ready = useCurrentFormalSignals({
    fetchCurrent: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [] }),
  })
  await ready.refresh()
  assert.equal(ready.status.value, 'ready')
  assert.deepEqual(ready.items.value, [])

  const unavailable = useCurrentFormalSignals({
    fetchCurrent: async () => ({ status: 'unavailable', trading_day: null, items: [] }),
  })
  await unavailable.refresh()
  assert.equal(unavailable.status.value, 'unavailable')
})
```

Network errors set `status='unavailable'`; they must not become ready-empty.

- [ ] **Step 2: Run tests RED, implement composable, rerun GREEN**

```bash
pnpm --dir apps/quant-web test
```

- [ ] **Step 3: Implement `MarketFormalSignals.vue` with minimal card content**

Ready item card renders only:

```text
苏冰
JM 焦煤 · JM2609
5m 买入信号 · 10:25
[查看 K 线]
```

When `lower_tf_confirmation=true`, add `5m 同向确认`.

State copy:

```text
loading     -> 正在读取正式信号…
ready empty -> 当前没有需要处理的正式信号
unavailable -> 正式信号暂不可用
```

Do not render Factor values, Radar reasons, score/confidence or business advice.

Direction styling must use red for `result_codes=['buy']`, green for `['sell']`, and always include text.

- [ ] **Step 4: Integrate at the top of existing Market page without deleting Radar**

`index.vue` load formal signals independently from Radar so one failure does not block the other. Ordering:

```text
intro/freshness
MarketFormalSignals
MarketSummaryStrip
Scatter + Attention
SectorSummary
DetailTable
```

`open` routes to existing `market-chart` with `series_kind=actual_dominant` and `frequency=item.frequency`.

- [ ] **Step 5: Extend E2E with three homepage states**

Mock current endpoint and assert:

```text
formal item appears above Radar
HTDY mock Event never appears in section
ready empty copy is exact
unavailable copy is exact and Radar still renders
```

- [ ] **Step 6: Run Web tests/E2E/build and commit**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build

git add apps/quant-web/src/composables/useCurrentFormalSignals.ts \
  apps/quant-web/src/components/market/MarketFormalSignals.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/tests/currentFormalSignals.test.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat: surface current formal signals on market page"
```

---

### Task 4: Two independent Product Rule switches

**Lane:** Lane 2

**Files:**
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts`
- Create: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Delete after replacement: `apps/quant-web/src/components/market/ProductAlertControl.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/alerts.test.ts`

**Composable target:**

```ts
const alertRules = ref<ProductAlertRuleState[]>([])
const savingRuleCodes = ref<Set<string>>(new Set())

async function toggle(ruleCode: string, enabled: boolean): Promise<void>
```

The composable must not hard-code a single `htdy_original_15m` state. It may expose computed helpers for exact known codes:

```ts
htdyRule = computed(() => rulesByCode.value.get('htdy_original_15m') ?? null)
subingRule = computed(() => rulesByCode.value.get('subing_entry_signal_v1') ?? null)
```

- [ ] **Step 1: Rewrite alert scope unit tests first**

Required test:

```ts
test('toggles exact rule without changing the neighbor rule', async () => {
  const scope = useProductAlertScope(...twoRulesFixture)
  await scope.refresh()
  await scope.toggle('subing_entry_signal_v1', true)
  assert.equal(scope.subingRule.value?.enabled_for_product, true)
  assert.equal(scope.htdyRule.value?.enabled_for_product, true) // original fixture unchanged
})
```

Also cover stale symbol mutation response and per-rule saving state.

- [ ] **Step 2: Run unit tests RED, implement generic rule collection, rerun GREEN**

```bash
pnpm --dir apps/quant-web test
```

- [ ] **Step 3: Implement `ProductAlertRules.vue`**

Render exactly two rows in fixed business order:

```text
火天大有 · 15m    [switch]
苏冰入场信号      [switch]
```

If a Registry-defined Rule is missing from API response, show a disabled/unavailable row rather than inventing defaults. Runtime status appears once for the shared Alert Runtime, not once per Rule.

Do not render `5m` and `15m` SuBing switches separately.

- [ ] **Step 4: Replace old singular control in sidebar/chart wiring**

`ProductResearchSidebar` receives the two rule states / shared runtime state. `chart.vue` calls `toggleAlert(ruleCode, enabled)`.

- [ ] **Step 5: Run unit tests/build and commit**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build

git add apps/quant-web/src/composables/useProductAlertScope.ts \
  apps/quant-web/src/components/market/ProductAlertRules.vue \
  apps/quant-web/src/components/market/ProductAlertControl.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue apps/quant-web/tests/alerts.test.ts
git commit -m "feat: expose independent htdy and subing alert scopes"
```

---

### Task 5: Product formal signal card and current-day records

**Lane:** Lane 2

**Files:**
- Create: `apps/quant-web/src/composables/useProductCurrentAlertEvents.ts`
- Create: `apps/quant-web/src/components/market/ProductFormalSignalCard.vue`
- Create: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/components/market/SubingResearchSection.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/tests/productCurrentAlertEvents.test.ts`

**Current events state:**

```ts
interface ProductCurrentEventsState {
  loading: Ref<boolean>
  status: Ref<'ready' | 'unavailable' | null>
  tradingDay: Ref<string | null>
  items: Ref<AlertEvent[]>
  refresh: () => Promise<void>
  dispose: () => void
}
```

- [ ] **Step 1: Write current-events composable tests**

Cover:

```text
symbol change invalidates stale response
ready empty remains ready
network error becomes unavailable
items preserve API ordering (bar_end desc)
```

- [ ] **Step 2: Implement and wire refresh lifecycle**

Refresh on product symbol change and after a successful Scope mutation only if desired for UI consistency; do not poll aggressively. Existing Kline marker 30s refresh remains separate.

- [ ] **Step 3: Implement `ProductFormalSignalCard.vue` from existing current SuBing snapshot**

Input is existing `SubingResearchResponse | null`, not persisted AlertEvent. Display only `resolved_signal`:

```text
MATCHED LONG  -> 苏冰 / 5m 买入信号 · HH:mm
MATCHED SHORT -> 苏冰 / 15m 卖出信号 · HH:mm
no resolved   -> 当前无正式入场信号
```

If `lower_tf_confirmation`, show `5m 同向确认`. Do not expose `NOT_MATCHED/RESEARCH_PENDING/INSUFFICIENT_DATA` in the primary card; those remain in secondary `SubingResearchSection`.

- [ ] **Step 4: Implement `ProductTodayAlertEvents.vue` from current-events API**

Render each row by Rule semantics:

```text
10:25  苏冰      买入信号
14:45  火天大有  卖出观察
```

Use Registry-provided rule code semantics already known by the front-end contract; do not infer formal/observation from color alone. Unknown rule_code should render a safe fallback label `未知提醒` or be skipped consistently with backend Registry guarantees; choose one behavior in tests and keep it stable.

Unavailable copy: `今日提醒暂不可用`. Ready empty: `今日暂无提醒记录`.

- [ ] **Step 5: Reorder Product sidebar hierarchy**

Exact order:

```text
正式信号
提醒开关
火天大有观察（only when applicable/current observation data exists）
今日记录
研究明细
Contract / Runtime context
边界说明
```

Existing SuBing Factor / Trend / Position / Volume / OI remain available but visually secondary. Do not remove them.

- [ ] **Step 6: Run unit tests/build and commit**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build

git add apps/quant-web/src/composables/useProductCurrentAlertEvents.ts \
  apps/quant-web/src/components/market/ProductFormalSignalCard.vue \
  apps/quant-web/src/components/market/ProductTodayAlertEvents.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/components/market/SubingResearchSection.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/productCurrentAlertEvents.test.ts
git commit -m "feat: prioritize product formal signals and current events"
```

---

### Task 6: Exact-frequency persistent AlertEvent markers

**Lane:** Lane 2

**Files:**
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts` or create `apps/quant-web/tests/alertMarkers.test.ts`
- Modify: `apps/quant-web/e2e/alert-v1.spec.mjs`

**Exact marker request contract:**

```ts
function markerRuleCodes(seriesKind: SeriesKind, frequency: MarketFrequency): string[] {
  if (seriesKind !== 'actual_dominant') return []
  if (frequency === '5m') return ['subing_entry_signal_v1']
  if (frequency === '15m') return ['htdy_original_15m', 'subing_entry_signal_v1']
  return []
}
```

- [ ] **Step 1: Write exact-frequency tests**

```ts
assert.deepEqual(markerRuleCodes('actual_dominant', '5m'), ['subing_entry_signal_v1'])
assert.deepEqual(markerRuleCodes('actual_dominant', '15m'), ['htdy_original_15m', 'subing_entry_signal_v1'])
assert.deepEqual(markerRuleCodes('continuous', '15m'), [])
assert.deepEqual(markerRuleCodes('actual_dominant', '30m'), [])
```

- [ ] **Step 2: Update marker mapping to V2 `result_codes`**

Rule/category labels:

```text
SuBing buy  -> 买入信号
SuBing sell -> 卖出信号
HTDY buy    -> 买入观察
HTDY sell   -> 卖出观察
```

Do not use a single generic `🔔买/卖` label for both categories. Marker id remains stable: `alert:${rule_code}:${symbol}:${bar_end}`.

- [ ] **Step 3: Update composable to fetch the fixed Rule set for the visible exact frequency**

For 15m, issue at most two historical `/events` requests (HTDY + SuBing), merge by Event identity, preserve existing generation/range/timer protections. For 5m, only SuBing. No generic Rule listing endpoint is needed.

- [ ] **Step 4: E2E marker regressions**

Assert:

```text
5m SuBing Event appears on 5m actual_dominant
same Event does not appear on 15m
15m SuBing + HTDY can both appear on 15m
continuous series gets no persistent AlertEvent marker
```

- [ ] **Step 5: Run tests/E2E/build and commit**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build

git add apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/tests/alerts.test.ts apps/quant-web/tests/alertMarkers.test.ts \
  apps/quant-web/e2e/alert-v1.spec.mjs
git commit -m "feat: show exact-frequency alert v2 markers"
```

Omit nonexistent/unchanged test file from `git add`.

---

### Task 7: Final visual hierarchy, responsive polish and accessibility contrast

**Lane:** Lane 2

**Files:**
- Modify: `apps/quant-web/src/components/market/MarketFormalSignals.vue`
- Modify: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Modify: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`
- Modify: `apps/quant-web/src/components/market/ProductFormalSignalCard.vue`
- Modify: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify: `apps/quant-web/src/components/market/ProductTodayAlertEvents.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify only if necessary: `apps/quant-web/src/styles/tokens.css`, `apps/quant-web/src/style.css`

**Visual contract:**

```text
>= 1200px:
  Product = dominant Kline main column + fixed right decision/research column

980-1199px:
  keep existing sidebar collapse; right column narrows without hiding signal copy

< 980px:
  right decision/research blocks stack below Kline
  Market Formal Signal cards become one column
```

- [ ] **Step 1: Make Formal Signal visually highest priority without using direction-colored CTA buttons**

Use white cards, strong text, subtle direction edge/chip, neutral primary `查看 K 线` button. Buy/sell direction uses red/green label and explicit copy; CTA stays neutral blue/charcoal.

- [ ] **Step 2: Demote Radar Attention relative to Formal Signal but preserve discoverability**

Add copy `值得关注，但尚未形成正式信号`; do not weaken row/card contrast so far that it becomes unreadable.

- [ ] **Step 3: Give HTDY a stable orange observation category surface**

Orange indicates category only. Direction still appears as `买入观察` / `卖出观察` text; if direction coloring is used inside the chip, retain red/green domain convention.

- [ ] **Step 4: Check focus/hover/disabled states**

Interactive cards/buttons/switches must have visible keyboard focus and disabled state. Do not rely on 10-12px low-contrast gray text for critical copy.

- [ ] **Step 5: Run screenshot-oriented Playwright checks**

Use existing browser tests/selectors, not a new visual-regression framework. At minimum assert the DOM order and visible copy at desktop and 980px-like viewport; no need to store pixel snapshots.

- [ ] **Step 6: Run full Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 7: Commit visual closeout**

```bash
git add apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
git commit -m "style: clarify market decision hierarchy"
```

Before this broad `git add`, verify `git status --short` contains only this Web task's intended paths; otherwise stage exact files instead.

---

### Task 8: Web self-review and final repository verification

**Lane:** Lane 2 closeout

**Files:** no new production surface unless review finds a direct bug in this scope.

- [ ] **Step 1: Spec coverage review**

Reviewer must verify:

```text
Market 首页 current Formal Signal is above Radar
ready-empty != unavailable
HTDY never appears in Market "需要处理"
no score/confidence/fake metrics
Product has exactly two independent Rule switches
SuBing switch has no timeframe sub-switch
Product current-events comes from dedicated endpoint
research facts remain available but secondary
exact-frequency marker behavior is enforced
Radar Summary/Scatter/Attention/Sector/Detail all remain
Kline remains dominant main visual
fixed light theme has readable contrast
red-up/buy and green-down/sell domain colors remain
no new routes/search/platform scope
```

- [ ] **Step 2: Run final Web verification again on clean intended diff**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-research.spec.mjs e2e/alert-v1.spec.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

- [ ] **Step 3: Commit only if review produced fixes**

Use a focused message such as:

```bash
git commit -m "fix: close decision compression web review gaps"
```

Do not update `STATUS.md` here unless the backend plan's canonical closeout owns the coordinated v1.3 code-ready status. Avoid competing status edits across parallel sessions.

---

## Web Plan Acceptance

Before gated rollout begins:

```text
backend V2 DTOs are the sole Alert web contract
fixed light theme is active and dark toggle state is gone
Market Formal Signal current view is independent from Radar load failure
Formal Signal cards contain only conclusion + identity + time + neutral CTA
HTDY remains observation category and is excluded from Market "需要处理"
Product has independent HTDY/Subing switches
Product "今日记录" uses current-events endpoint and distinguishes ready empty/unavailable
persistent markers obey actual_dominant + exact Event frequency only
5m SuBing marker never projects to 15m and vice versa
existing Radar and Kline behavior remains
all unit tests + selected Playwright + build pass
no real Scope write, Runtime switch, migration, release or WeCom occurred during Web implementation
```

Next dependency: only after backend + Web plans are complete and independently reviewed may `docs/superpowers/plans/2026-08-14-v1.3-release-runtime-canary.md` be executed.