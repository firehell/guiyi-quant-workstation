# Market Research Workspace P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 Canonical、MainContractMap、Market Runtime V1 和 Indicator Kernel 权威边界的前提下，把当前 Market Web 升级为“Market Radar → Product Workspace”的个人期货研究工作流，并完成轻量 TradingView-like K 线体验、可解释 P0 研究摘要和部分宇宙安全降级。

**Architecture:** P0 继续以 `MarketDataService` 为唯一历史 Bar 入口，复用当前 `useMarketSeries` 的 Historical/Live seam，不新增 provider passthrough、数据库表、Research Catalog 或任务平台。Product Workspace 先在现有四品种/fixture 上完成；Market Radar 后端以 active universe + `actual_dominant/1d` Canonical 做批量研究计算，明确返回 `as_of`、参与品种数和不可用品种。只有 60/60 Canonical + audit 闭环后才允许称为完整全市场结果。

**Tech Stack:** Vue 3 / TypeScript / Vite / Naive UI / lightweight-charts 5.2；FastAPI / SQLAlchemy / PostgreSQL；`packages/quant-core` Indicator Kernel；Node test runner / Playwright / pytest / Ruff / Mypy。

## Global Constraints

- 当前产品面保持 Market-only；不得恢复 Backtest / Signal / Review / Strategy 应用面。
- `MarketDataService` 仍是唯一正式历史 Bar 读取入口；任何 P0 研究计算不得 glob Parquet、自判主力或跨频回退。
- `actual_dominant` 只由 `MainContractMap rank=1` 查询时拼接；`continuous/MAIN` 继续保持现有未平滑语义。
- Market Runtime V1 的历史分页、Redis Live Overlay、REST/WS seam 已实现但尚未启用。P0 **必须保留和复用现有 `useMarketSeries` / `/market/state` / `/market/ws` 行为**，不得删除、复制、重写或借 P0 启用 Runtime。
- P0 本地验证不得调用真实 RQData、不得写生产 PostgreSQL/Canonical、不得执行 `guiyi runtime live`、`guiyi data after-market` 或任何 Runtime enable 命令。
- DFD-07 当前仅 4/60 完整闭环；P0 可以开发并集成，但 Market Radar 必须显示 `participant_count / active_count`，不得把部分宇宙写成“全市场”。
- 60/60 active universe Canonical + audit 闭环是 Market Radar 完整全宇宙 Ready 的独立前置 Gate；该数据重建属于另一个受控任务，不并入 P0。
- 页面不使用“强烈做多/建议买入/资金流入”等交易指令或无法由事实证明的因果文案；`auto_order=false` 始终成立。
- 主图只复用已登记 `EMA10/EMA21/EMA60` 和默认关闭的 HTDY original observation；不新增 BOLL、RSI/KDJ/CCI 或自定义指标系统。
- Volume 与 MACD 固定为两个副图；不做画线工具、多图分屏、任意 pane 拖拽布局或商业 TradingView 克隆。
- HTDY original 保持 observation-only、future-looking/repainting 边界；P0 不修改公式、Registry、quant-core capability 或 Runtime consumer。
- “值得关注”统一带明确 `as_of` 日期；当 `as_of` 不是当前交易日时不得写“今日值得关注”。
- 板块汇总仅在参与 Radar 计算的所有品种都具备可信 `sector` 时显示；P0 不创建新的板块 taxonomy 或 sector 配置系统。
- 普通 Lane 2 任务完成后允许按仓库流程集成 `develop`；不得发布 `main`、创建 tag、切换 Runtime 或执行真实写入。

## Review Corrections to the Approved Design

实施时以下四点优先于设计稿中的旧措辞：

1. **不“恢复 Live”，而是保留已实现的 Runtime seam。** 当前 `chart.vue` 已使用 `useMarketSeries`，后者已经承担 cursor page、state、WebSocket、generation token、Canonical/Live seam 和 reconnect；P0 只改变展示层与研究计算。
2. **先 Product Workspace，后 Radar。** DFD-07 仍为 4/60，而 K 线分页与 Runtime seam 已可用，因此先完成不依赖 60/60 的 Product Workspace，避免 Radar 全宇宙 Gate 阻塞视觉主线。
3. **Radar 使用“值得关注 + as_of”，不使用无条件“今日”。** Radar P0 基于最近完整 `actual_dominant/1d` Canonical，不把盘中 Live 与历史完整日混成统一 60 品种口径。
4. **HTDY 独立成任务。** 核心 K 线必须先用 EMA + Volume + MACD 验收；HTDY observation overlay 单独 Review，避免未来引用/重绘风险拖累普通图表任务。

## File Structure

### Product Workspace / Kline

- Modify: `apps/quant-web/src/pages/market/chart.vue` — Product Workspace 页面编排、现有 Runtime seam 接线。
- Create: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue` — 高频品种/series/周期/指标/全屏控件。
- Create: `apps/quant-web/src/components/market/ProductResearchSidebar.vue` — 轻量右栏，P0 只展示趋势、量仓和主力上下文。
- Create: `apps/quant-web/src/components/market/PriceVolumeOiPanel.vue` — K 线下方 P0 量价/OI 研究区。
- Create: `apps/quant-web/src/components/kline/KlineHoverLegend.vue` — 十字线联动的 OHLCV/OI/EMA/MACD 标签。
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue` — 三 pane、EMA、MACD、crosshair、HTDY observation UI。
- Create: `apps/quant-web/src/utils/klineViewModel.ts` — 纯 TS 图表派生数据，便于 Node 单测。
- Create: `apps/quant-web/src/utils/marketWorkspacePreferences.ts` — symbol/series/sidebar/自选本地偏好；周期/主图指标继续复用 `mainIndicators.ts`。
- Create: `apps/quant-web/src/utils/productResearch.ts` — 日/周趋势、20 日位置、量比、OI、成交额摘要纯函数。
- Create: `apps/quant-web/src/composables/useProductResearchSummary.ts` — 只通过现有 Market API 读取日/周 Canonical 页面。
- Modify: `apps/quant-web/src/styles/tokens.css` — 仅增加实际需要的 pane/HTDY/研究区 token。

### Market Radar backend

- Modify: `services/quant-api/app/market_data/operational_universe.py` — 新增并复用 `load_active_products()`；保持 active=60/retired 约束。
- Create: `services/quant-api/app/market_data/radar.py` — Radar 纯研究计算与聚合服务。
- Modify: `services/quant-api/app/market_data/composition.py` — `build_market_radar_service(session)`。
- Modify: `services/quant-api/app/schemas/market.py` — Radar DTO。
- Modify: `services/quant-api/app/api/market.py` — 只读 `GET /api/v1/market/radar`。

### Market Radar frontend

- Modify: `apps/quant-web/src/types/market.ts` — Radar DTO types。
- Modify: `apps/quant-web/src/api/market.ts` — `getMarketRadar()`。
- Modify: `apps/quant-web/src/pages/market/index.vue` — 从主力表升级为 Radar 页面。
- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`。
- Create: `apps/quant-web/src/components/market/MarketScatter.vue` — 原生 SVG，不新增 ECharts 依赖。
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue` — 后端“值得关注”候选，与本地“自选”严格区分。
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`。

### Tests

- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`。
- Create: `apps/quant-web/tests/kline-view-model.test.ts`。
- Create: `apps/quant-web/tests/product-research.test.ts`。
- Modify: `apps/quant-web/tests/indicators.test.ts` — 仅增加必要 HTDY UI 边界断言，不改变现有指标语义。
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs` — 更新 selector，同时保留历史分页/Live seam/BREAK/CLOSED/旧 WS 隔离三类回归。
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`。
- Create: `services/quant-api/tests/test_market_radar.py`。
- Create: `services/quant-api/tests/test_market_radar_api.py`。

---

### Task 1: Product Workspace shell, lightweight toolbar, and local preferences

**Lane:** Lane 2 — regular Web engineering.

**Files:**
- Create: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Create: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Create: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`
- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs`

**Interfaces:**

```ts
export interface MarketWorkspacePreferences {
  version: 1
  symbol: string | null
  seriesKind: 'actual_dominant' | 'continuous'
  researchSidebarOpen: boolean
  watchlist: string[]
}

export const MARKET_WORKSPACE_PREFERENCES_KEY = 'guiyi.market.workspace.preferences.v1'
```

Implement these exported functions in `marketWorkspacePreferences.ts`:

```text
defaultMarketWorkspacePreferences() -> MarketWorkspacePreferences
loadMarketWorkspacePreferences(storage) -> MarketWorkspacePreferences
saveMarketWorkspacePreferences(value, storage) -> void
toggleWatchlistSymbol(value, symbol) -> MarketWorkspacePreferences
```

`ProductWorkspaceToolbar.vue` emits exact events:

```text
update:symbol
update:series-kind
update:contract
update:frequency
update:visible-main-indicators
request-fullscreen
back
```

- [ ] **Step 1: Write preference failure tests**

```ts
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  defaultMarketWorkspacePreferences,
  loadMarketWorkspacePreferences,
  toggleWatchlistSymbol,
} from '../src/utils/marketWorkspacePreferences.ts'

test('corrupt workspace storage falls back to actual-dominant defaults', () => {
  const storage = { getItem: () => '{bad-json' }
  assert.deepEqual(loadMarketWorkspacePreferences(storage), defaultMarketWorkspacePreferences())
})

test('watchlist toggle normalizes symbol and never duplicates it', () => {
  const initial = defaultMarketWorkspacePreferences()
  const added = toggleWatchlistSymbol(initial, ' JM ')
  assert.deepEqual(added.watchlist, ['jm'])
  assert.deepEqual(toggleWatchlistSymbol(added, 'jm').watchlist, [])
})
```

- [ ] **Step 2: Run the new test and verify RED**

```bash
node --test apps/quant-web/tests/market-workspace-preferences.test.ts
```

Expected: FAIL because `marketWorkspacePreferences.ts` does not exist.

- [ ] **Step 3: Implement the minimal local preference module**

Use exact defaults:

```ts
export function defaultMarketWorkspacePreferences(): MarketWorkspacePreferences {
  return {
    version: 1,
    symbol: null,
    seriesKind: 'actual_dominant',
    researchSidebarOpen: true,
    watchlist: [],
  }
}
```

Wrong version, malformed JSON, unknown series, non-array watchlist, or non-string symbols fall back/normalize. Storage failure never blocks page load.

- [ ] **Step 4: Run the preference test and verify GREEN**

```bash
node --test apps/quant-web/tests/market-workspace-preferences.test.ts
```

- [ ] **Step 5: Replace the management-form toolbar with the Product Workspace toolbar**

Route query has precedence over local preference. If route query omits symbol/series/frequency, use stored symbol/series and the existing `MainChartPreferences.period`; final fallback remains first dominant / `actual_dominant` / `15m`.

Visible high-frequency controls:

```text
JM 焦煤 | 真实主力 / 主连 | 1m 5m 15m 30m 60m D W | 指标 | 全屏
```

`contract` remains available through a compact advanced menu. Do not add date-range picker or “读取” workflow; series/frequency changes call the existing `refreshSeries()` path.

- [ ] **Step 6: Add responsive Product Workspace shell without touching Runtime seam**

```css
.product-workspace__main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 296px;
  gap: 12px;
}
@media (max-width: 1599px) {
  .product-workspace__main { grid-template-columns: minmax(0, 1fr); }
  .product-workspace__sidebar { display: none; }
}
```

Below 1600px render one “研究” button that opens the same sidebar content in Naive UI `NDrawer`. Large-screen sidebar may be collapsed by user preference. Fullscreen uses the browser Fullscreen API on the Kline workspace container; unavailable API is a silent no-op.

- [ ] **Step 7: Preserve current Market Runtime labels and mutation flow**

Keep current `replaceSeries`, `loadMoreBefore`, mutation `replace/prepend/live`, `followLatest`, `marketState`, `Live/Historical`, `phaseLabel`, and after-market warning. Move them visually; do not reimplement or remove them.

- [ ] **Step 8: Update existing mock Runtime E2E selectors and run it**

```bash
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
```

Expected: all 3 existing scenarios PASS: initial page + left pagination + Live seam; continuous BREAK/weekend history-only; stale symbol WebSocket isolation.

- [ ] **Step 9: Run frontend unit/build validation**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 10: Commit Task 1 only**

```bash
git add \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/utils/marketWorkspacePreferences.ts \
  apps/quant-web/tests/market-workspace-preferences.test.ts \
  apps/quant-web/e2e/market-runtime.spec.mjs
git commit -m "feat(web): establish product market workspace"
```

---

### Task 2: Three-pane Kline, EMA overlays, fixed Volume/MACD, and linked crosshair

**Lane:** Lane 2, Sol/high reasoning because this task touches chart rendering, existing Runtime mutations, and indicator observation semantics together.

**Files:**
- Create: `apps/quant-web/src/utils/klineViewModel.ts`
- Create: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Create: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/styles/tokens.css`

`KlineChart` adds prop `visibleMainIndicators: MainIndicatorId[]` and event `crosshair-change(HoverKlineContext | null)` while retaining the existing exposed methods `replaceBars`, `prependBars`, `updateBar`, `scrollToLatest`.

- [ ] **Step 1: Write pure view-model tests**

```ts
test('derived data only creates enabled EMA overlays and always creates MACD', () => {
  const result = buildKlineDerivedData(makeBars(100), ['ema_21'])
  assert.equal(result.ema.ema_10, undefined)
  assert.ok(result.ema.ema_21!.length > 0)
  assert.ok(result.macd.histogram.length > 0)
})

test('hover context uses one source time for OHLCV OI EMA and MACD', () => {
  const bars = makeBars(100)
  const derived = buildKlineDerivedData(bars, ['ema_21'])
  const last = bars.at(-1)!
  const ctx = hoverContextForTime(bars, derived, last.time)
  assert.equal(ctx!.time, last.time)
  assert.equal(ctx!.bar.close, last.close)
  assert.ok(ctx!.mainIndicators?.some((item) => item.id === 'ema_21'))
})
```

- [ ] **Step 2: Run the view-model test and verify RED**

```bash
node --test apps/quant-web/tests/kline-view-model.test.ts
```

- [ ] **Step 3: Implement view-model derivation strictly from existing Web observation mirror**

Use `calculateEMA()` and `calculateMACD()` from `src/utils/indicators.ts`; do not duplicate formulas. EMA ids map exactly to 10/21/60. Ignore HTDY in Task 2.

- [ ] **Step 4: Run view-model and existing indicator tests**

```bash
node --test apps/quant-web/tests/kline-view-model.test.ts
node --test apps/quant-web/tests/indicators.test.ts
```

- [ ] **Step 5: Convert `KlineChart.vue` to fixed panes**

Use lightweight-charts v5 pane indexes:

```ts
candles = chart.addSeries(CandlestickSeries, candleOptions, 0)
volume = chart.addSeries(HistogramSeries, volumeOptions, 1)
macdHistogram = chart.addSeries(HistogramSeries, macdHistogramOptions, 2)
macdDif = chart.addSeries(LineSeries, { color: theme.macdDif, lineWidth: 1 }, 2)
macdDea = chart.addSeries(LineSeries, { color: theme.macdDea, lineWidth: 1 }, 2)
```

After series creation set pane stretch factors `6 / 2 / 2` via `chart.panes()`. Pane resizing is not exposed as a product feature.

- [ ] **Step 6: Add EMA series lifecycle without changing viewport semantics**

Maintain a `Map<MainIndicatorId, ISeriesApi<'Line'>>` for EMA10/21/60. `replaceBars` and `prependBars` recompute derived data for all loaded bars and `setData()` indicators. Live `updateBar` keeps candles/volume incremental; derived indicator series may be recomputed for loaded bars and `setData()` without `fitContent()`. This favors simple deterministic local behavior over a second incremental indicator engine.

- [ ] **Step 7: Add synchronized crosshair output**

Subscribe once with `chart.subscribeCrosshairMove`. Resolve source bar by chart time and emit one `HoverKlineContext`. `KlineHoverLegend.vue` displays only available values:

```text
时间 | O H L C | Volume | OI | enabled EMA | DIF DEA HIST
```

Missing fields remain unavailable; never substitute 0.

- [ ] **Step 8: Make chart height viewport-based**

```css
.kline-shell { min-height: 680px; height: clamp(680px, 74vh, 1040px); }
.chart { width: 100%; height: 100%; }
```

Fullscreen overrides to `100vh`. Do not add resizable-layout persistence.

- [ ] **Step 9: Run chart regression suite**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 10: Commit Task 2**

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/styles/tokens.css \
  apps/quant-web/tests/kline-view-model.test.ts
git commit -m "feat(web): add focused three-pane market chart"
```

---

### Task 3: HTDY original observation overlay, isolated from core chart semantics

**Lane:** Lane 2, Sol/high reasoning, with a fresh independent Review because this is a future-looking/repainting observation surface.

**Files:**
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`

- [ ] **Step 1: Add observation-boundary tests**

```ts
const htdy = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === 'htdy')!
assert.equal(htdy.defaultVisible, false)
assert.equal(htdy.capability, 'observation_overlay')
assert.equal(htdy.repaintingRisk, 'known')
assert.equal(htdy.unstableTailBars, 27)
assert.ok(htdy.riskMessages?.includes('仅供人工观察'))
```

Also prove `buildKlineDerivedData()` does not calculate an HTDY payload when `htdy` is disabled.

- [ ] **Step 2: Run tests before rendering changes**

```bash
node --test apps/quant-web/tests/indicators.test.ts apps/quant-web/tests/kline-view-model.test.ts
```

- [ ] **Step 3: Map existing HTDY output to a deliberately observational visualization**

When `htdy` is enabled, call existing `calculateHuoTianDaYou()` once for loaded bars. Render `zk1/zd1/zd2` as thin main-pane lines. Use series markers for existing `buyObservation`, `sellObservation`, `xgObservation`, labeled `买观察`, `卖观察`, `XG观察`. Never use `买入`, `卖出`, `建议`, `信号` or score wording.

Do not recreate a Tongdaxin STICKLINE engine. `yellowCandle/whiteCandle` may be represented by compact observation markers/legend state; P0 must not claim pixel-exact Tongdaxin rendering.

- [ ] **Step 4: Keep repaint risk visible whenever HTDY is enabled**

Display exactly:

```text
火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察
```

The notice remains visible in fullscreen.

- [ ] **Step 5: Run indicator/chart/E2E/build checks**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

No backend, Runtime, Registry or quant-core file may change in Task 3.

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/tests/indicators.test.ts
git commit -m "feat(web): expose htdy as repainting observation"
```

---

### Task 4: Product research summary and Price/Volume/OI vertical section

**Lane:** Lane 2 — Terra/medium.

**Files:**
- Create: `apps/quant-web/src/utils/productResearch.ts`
- Create: `apps/quant-web/src/composables/useProductResearchSummary.ts`
- Create: `apps/quant-web/src/components/market/PriceVolumeOiPanel.vue`
- Create: `apps/quant-web/tests/product-research.test.ts`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`

Freeze this model:

```ts
export type TrendDirection = 'up' | 'down' | 'neutral' | 'unavailable'
export interface ProductResearchSummary {
  dailyTrend: TrendDirection
  weeklyTrend: TrendDirection
  position20: number | null
  distanceTo20High: number | null
  distanceTo20Low: number | null
  volumeRatio20: number | null
  oiChange1d: number | null
  turnoverVs5d: number | null
}
```

`useProductResearchSummary` receives current series identity and exposes `summary`, `dailyBars`, `loading`, `error`, `refresh`. It calls only existing `/market/bars/page`: `1d limit=80`, `1w limit=40`.

- [ ] **Step 1: Write exact metric tests**

Definitions:

```text
daily/weekly up   = close > EMA21 and EMA21_latest > EMA21_previous
daily/weekly down = close < EMA21 and EMA21_latest < EMA21_previous
otherwise neutral
position20        = (close - min(low,last20)) / (max(high,last20)-min(low,last20))
volumeRatio20     = current volume / mean(previous 20 volumes), current excluded
oiChange1d        = current OI / previous OI - 1, only when both non-null and previous > 0
turnoverVs5d      = current turnover / mean(previous 5 turnovers) - 1, only when complete
```

- [ ] **Step 2: Run the new unit test and verify RED**

```bash
node --test apps/quant-web/tests/product-research.test.ts
```

- [ ] **Step 3: Implement pure calculations by reusing `calculateEMA`**

Insufficient history returns `null` / `unavailable`, never 0.

- [ ] **Step 4: Add composable generation protection**

A symbol/series/contract change increments a local generation token; stale daily/weekly responses are ignored. Research request failure only marks research unavailable and does not set main Kline error.

- [ ] **Step 5: Fill the lightweight sidebar**

Only three groups:

```text
趋势/位置: 日线、周线、20日位置、距20日高/低
量与持仓: 量比、OI 1D、成交额相对5日
合约上下文: 当前 rank1 真实主力、映射交易日
```

Do not add Roll Yield, member rank, warehouse, trading parameters or P1 placeholders.

- [ ] **Step 6: Add one vertical Price/Volume/OI section below Kline**

Use `dailyBars` to draw an in-repo SVG: normalized close line + normalized OI line when OI exists, with compact volume strip. If OI is absent, show `OI 暂无可用数据` and still render price/volume. Do not add ECharts/D3.

- [ ] **Step 7: Validate Product Workspace**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 8: Commit Task 4**

```bash
git add \
  apps/quant-web/src/utils/productResearch.ts \
  apps/quant-web/src/composables/useProductResearchSummary.ts \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/components/market/PriceVolumeOiPanel.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/product-research.test.ts
git commit -m "feat(web): add focused product research context"
```

---

### Task 5: Market Radar backend contract and deterministic research calculations

**Lane:** Lane 2, Sol/high reasoning because this task defines a new read contract over Canonical and must fail safely under partial 4/60 coverage.

**Files:**
- Modify: `services/quant-api/app/market_data/operational_universe.py`
- Create: `services/quant-api/app/market_data/radar.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/test_market_radar.py`
- Create: `services/quant-api/tests/test_market_radar_api.py`

Freeze P0 constants in `radar.py`:

```py
PRICE_MOVE_PCT = Decimal("0.02")
VOLUME_EXPANSION_RATIO = Decimal("1.50")
OI_EXPANSION_PCT = Decimal("0.05")
HIGH_VOLATILITY_PERCENTILE = Decimal("0.80")
NEAR_HIGH_POSITION = Decimal("0.90")
NEAR_LOW_POSITION = Decimal("0.10")
WATCH_MIN_REASONS = 2
WATCH_LIMIT = 10
RADAR_DAILY_LIMIT = 300
```

`MarketRadarSnapshot` exact top-level fields:

```text
as_of
active_count
participant_count
sector_covered_count
unavailable
summary
items
attention
sector_summary
```

`attention` is the backend-calculated “值得关注” candidates. The word `watchlist` is reserved for the user's local “自选”, preventing contract ambiguity.

Each Radar item exact fields:

```text
symbol
product_name
exchange
sector
actual_contract
dominant_mapping_date
price_change_1d
price_change_5d
oi_change_1d
volume_ratio20
atr14_percentile252
position20
ema21_direction
turnover
reason_count
reasons
```

- [ ] **Step 1: Refactor active universe loading with tests first**

Add `load_active_products(path: Path | None = None) -> tuple[str, ...]` to `operational_universe.py`; enforce exactly 60 unique normalized active symbols and zero retired intersection. Change `load_operational_products()` to call this function instead of duplicating active validation.

Tests cover invalid active count, duplicate active, retired overlap and operational-not-subset.

- [ ] **Step 2: Write Radar service tests with a fake Market page reader**

Test:

```text
same latest day products participate
one known MarketDataError becomes unavailable without poisoning others
stale product latest_day < as_of is excluded
unexpected RuntimeError propagates
participant_count is exact; active_count remains 60
attention sort is deterministic
sector_summary is empty unless every participant has sector
```

- [ ] **Step 3: Implement `as_of` and participant selection**

For every active symbol query `SeriesKind.ACTUAL_DOMINANT`, `BarFrequency.D1`, `limit=300` through `MarketDataService.query_page()`.

No RQData call. Collect each successful series latest `trading_day`; set `as_of = max(latest_day)`. A product participates only if latest bar equals `as_of`. Missing optional metric history returns `None`; missing current/latest series excludes the product and records a stable unavailable code. Known `MarketDataError` becomes unavailable; unexpected infrastructure/program errors propagate.

- [ ] **Step 4: Implement exact P0 metrics with Kernel authority**

```text
price_change_1d = close_T / close_T-1 - 1
price_change_5d = close_T / close_T-5 - 1
volume_ratio20  = volume_T / mean(volume of previous 20 complete bars)
oi_change_1d    = oi_T / oi_T-1 - 1 when valid
position20      = (close_T - min(low,last20)) / (max(high,last20)-min(low,last20))
```

Use `ema_series(period=21, seed_policy="sma_window")` from quant-core for EMA direction.

Use `atr_series(period=14, smoothing_policy="wilder_sma_seed")`. ATR percentile baseline is up to 252 valid ready ATR values immediately preceding latest ATR; percentile = count of baseline values `<= latest` divided by baseline count. Require at least 20 baseline ATR values, otherwise `None`.

All price/OI/volume/turnover arithmetic remains Decimal until passing values into the existing float-based Indicator Kernel; convert Kernel output back with `Decimal(str(value))` for response metrics.

- [ ] **Step 5: Implement transparent reasons and stable sort**

Reason codes and rules:

```text
price_move_up / price_move_down          abs(1D) >= 2%
volume_expansion                         volume_ratio20 >= 1.5
oi_increase / oi_decrease                OI 1D >= 5% / <= -5%
high_volatility                          ATR percentile >= 80%
near_20d_high / near_20d_low             position >= 90% / <= 10%
ema21_up / ema21_down                    close and EMA slope aligned
```

Candidate requires at least 2 reasons. Never lower threshold to fill 10 rows. Sort:

```text
reason_count DESC
abs(price_change_1d) DESC
turnover DESC with null last
symbol ASC
```

Return at most 10 `attention` items.

- [ ] **Step 6: Implement sector summary only with complete trusted coverage**

Read `Instrument.sector` for participants. `sector_covered_count` counts non-empty trusted sectors. If it differs from `participant_count`, return `sector_summary=[]`. Do not derive sector from symbol/name or add a taxonomy file.

- [ ] **Step 7: Add Pydantic DTO and read-only endpoint**

Add `GET /api/v1/market/radar`, no P0 query params. It calls `build_market_radar_service(session).snapshot()`. Do not expose SQL/path/provider internals.

- [ ] **Step 8: Run targeted backend tests**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_radar.py \
  services/quant-api/tests/test_market_radar_api.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data/radar.py \
  services/quant-api/app/market_data/operational_universe.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/tests/test_market_radar.py \
  services/quant-api/tests/test_market_radar_api.py

git diff --check
```

- [ ] **Step 9: Run complete backend regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests
```

No real provider/data mutation command is allowed.

- [ ] **Step 10: Commit Task 5**

```bash
git add \
  services/quant-api/app/market_data/operational_universe.py \
  services/quant-api/app/market_data/radar.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_market_radar.py \
  services/quant-api/tests/test_market_radar_api.py
git commit -m "feat(market): add canonical radar snapshot"
```

---

### Task 6: Market Radar Web, SVG scatter, explainable attention list, and local watchlist

**Lane:** Lane 2 — Terra/medium.

**Files:**
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`
- Create: `apps/quant-web/src/components/market/MarketScatter.vue`
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`
- Modify: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`

Add `MarketRadarResponse` matching Task 5 exactly, including `attention`, not backend `watchlist`.

- [ ] **Step 1: Add API/type contract and mock E2E fixture**

```ts
export function getMarketRadar() {
  return request.get<never, MarketRadarResponse>('/market/radar')
}
```

Mock `active_count=60`, `participant_count=4`, explicit historical `as_of`, mixed quadrants and at least one attention candidate.

- [ ] **Step 2: Write browser expectations before page implementation**

`market-radar.spec.mjs` asserts:

```text
as_of is visible
“参与 4 / 60” is visible
partial-universe notice is visible
historical as_of uses “值得关注”, not “今日值得关注”
scatter click navigates directly to /market/chart
sector block is absent when sector coverage is incomplete
candidate reason tags are visible
```

Run and verify RED:

```bash
npm --prefix apps/quant-web run test:e2e -- market-radar.spec.mjs
```

- [ ] **Step 3: Build first-screen summary with fixed information density**

Only:

```text
上涨品种 | 下跌品种 | 放量品种 | 明显增仓 | 高波动 | as_of
```

No average-return, total-OI or score cards.

- [ ] **Step 4: Implement `MarketScatter.vue` as lightweight SVG**

X=`price_change_1d`; Y=`oi_change_1d`; missing OI items remain in table but not scatter. Bubble radius derives from log-scaled turnover and is clamped to 6–18px. Hover shows only symbol/name, price change, OI change, volume ratio, ATR percentile. Quadrant labels:

```text
上涨+增仓 / 上涨+减仓 / 下跌+增仓 / 下跌+减仓
```

Point click emits item; parent routes directly to Product Workspace.

- [ ] **Step 5: Implement explainable “值得关注” list**

Display backend `attention` and reason codes only; Web never rescales/recalculates thresholds. Show `关注原因 N 项` plus translated reason tags. No composite numeric score.

- [ ] **Step 6: Render optional sector summary and full detail table**

Render sector block only when:

```ts
radar.participant_count > 0
&& radar.sector_covered_count === radar.participant_count
&& radar.sector_summary.length > 0
```

Detail table below first screen:

```text
品种 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态
```

- [ ] **Step 7: Integrate local “自选” without user/profile API**

Market page supports `全部 / 自选`; Product Workspace star uses the same `marketWorkspacePreferences.watchlist`. Clicking a Radar item opens `actual_dominant`; frequency uses valid stored `MainChartPreferences.period`, otherwise `15m`.

- [ ] **Step 8: Run frontend tests and both E2E suites**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-radar.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 9: Commit Task 6**

```bash
git add \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/components/market/MarketSummaryStrip.vue \
  apps/quant-web/src/components/market/MarketScatter.vue \
  apps/quant-web/src/components/market/MarketAttentionList.vue \
  apps/quant-web/src/components/market/MarketDetailTable.vue \
  apps/quant-web/src/utils/marketWorkspacePreferences.ts \
  apps/quant-web/e2e/market-radar.spec.mjs
git commit -m "feat(web): add explainable market radar"
```

---

### Task 7: P0 integration review, documentation, and bounded readiness statement

**Lane:** Lane 2 integration review; use Sol/high reasoning in a fresh Review session because final diff spans backend, Web, chart semantics and an existing Runtime surface.

**Files:**
- Modify when factual state changed: `STATUS.md`
- Modify when Market API/test command changed materially: `TESTING.md`
- Modify only if implementation semantics require clarification: `docs/superpowers/specs/2026-08-10-market-research-workspace-design.md`

- [ ] **Step 1: Review final diff against design and plan**

Verify exactly:

```text
MarketDataService still owns historical bars
useMarketSeries still owns Historical/Live seam
no new provider passthrough
no new DB table/migration
no Runtime enable/load
no main/tag/release
no full-market claim under participant_count < 60
no trading-advice wording
no HTDY capability or formula change
no P1 member/warehouse/roll-yield scope creep
```

- [ ] **Step 2: Run complete Web verification**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-radar.spec.mjs
npm --prefix apps/quant-web run build
```

- [ ] **Step 3: Run complete backend verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant
```

- [ ] **Step 4: Run repository Mypy command and compare with baseline**

```bash
MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py
```

Current baseline has 4 pre-existing errors in `catalog.py`, `service.py`, `maintenance.py`. P0 acceptance requires zero new Mypy errors; do not expand scope to fix unrelated baseline errors unless a touched line caused one.

- [ ] **Step 5: Run final hygiene checks**

```bash
git diff --check
git status --short
```

Run the repository's applicable secret scan when tracked executable/source files changed; report only pass/fail, never matching values.

- [ ] **Step 6: Update `STATUS.md` with exact bounded state**

If DFD-07 remains below 60/60, use equivalent wording:

```text
Market Research Workspace P0 code and local tests are complete. Product Workspace/Kline is usable on available Canonical products. Market Radar supports partial-universe degradation and reports participant_count/60; full-universe Radar Ready remains blocked on DFD-07 60/60 Canonical + audit. Market Runtime enable state is unchanged.
```

Never announce “全市场 Ready” before the independent data Gate actually passes.

- [ ] **Step 7: Commit only changed closure docs**

Inspect changed docs first, then stage only the files that actually changed. Do not use `git add -A`.

If only `STATUS.md` changed:

```bash
git add STATUS.md
git commit -m "docs: close market research workspace P0"
```

If `TESTING.md` or the design spec also changed for real contract reasons, add those exact paths explicitly before the same commit.

---

## P0 Acceptance Matrix

P0 code may integrate into `develop` even if DFD-07 remains below 60/60:

| Area | Acceptance |
|---|---|
| Product Workspace | Kline remains first visual focus; >=1600 shows 296px lightweight sidebar; smaller screen uses drawer; fullscreen works |
| Runtime preservation | Existing pagination, Historical/Live seam, BREAK/CLOSED, stale WebSocket isolation tests remain green |
| Chart | Candlestick + EMA on pane 0; fixed Volume pane 1; fixed MACD pane 2; linked crosshair shows same-time data |
| Indicators | EMA/MACD use existing Web mirror/golden policy; HTDY default-off observation-only with permanent repaint risk copy |
| Research sidebar | Daily/weekly trend, 20d position, volume/OI/turnover and rank1 context; failures do not blank Kline |
| Market Radar | One backend batch response; no frontend N+1; explicit `as_of`; explicit participant/60; deterministic reasons/sort |
| Partial universe | Missing/stale products are excluded and reported; partial results never claim full market |
| Sector | Only shown with complete trusted sector metadata among participants |
| Local UX | last symbol/series/period/indicators/sidebar/watchlist survive locally; corrupt local state falls back safely |
| Scope | no P1 RQData research APIs, no DB migration, no Runtime enable, no release/tag/main |

**Separate Gate after P0:** only when DFD-07 reaches 60/60 and active-universe `data audit` passes can the product statement move from “partial-universe Radar” to “full-universe Market Radar Ready”. This Gate is not an implementation task in this plan.

## Recommended Task Sequence

```text
Task 1  Product Workspace shell + toolbar + preferences
  ↓
Task 2  Kline core: 3 panes + EMA + Volume/MACD + crosshair
  ↓
Task 3  HTDY observation overlay (isolated Review)
  ↓
Task 4  Lightweight product research sidebar + Price/Volume/OI
  ↓
Task 5  Market Radar backend contract/calculations
  ↓
Task 6  Market Radar Web + SVG scatter + local watchlist
  ↓
Task 7  Independent integration review + exact readiness closure

Independent of this plan:
DFD-07 60/60 Canonical rebuild/audit Gate
MR-08 Market Runtime enable/canary Gate
P1 RQData research enrichment
```

This order intentionally starts with the already-supported Product/Kline path rather than the 60-product Radar path, so current DFD-07 progress does not block useful P0 development.