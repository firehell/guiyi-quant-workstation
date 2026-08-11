# Market Research Workspace V2 P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Market Runtime MR-08 已验收、active 60/60 历史 Canonical 已全部闭环的基线上，把当前 Market Web 升级为“Market Radar → Product Workspace”的高效个人期货研究工作站，同时保留已经验收的 Historical/Live seam 与数据合同。

**Architecture:** P0 新增只读 `MarketResearchService`，统一从 `MarketDataService` 读取历史行情并复用 quant-core 指标权威，向 Web 输出 `RadarSnapshot` 与 `ProductResearchSnapshot`；Web 不再自行组合 60 个品种的研究逻辑。现有 `useMarketSeries`、`MarketReadService`、cursor 分页和 WebSocket seam 原样保留；Kline 只做轻量三 pane、EMA、固定 Volume/MACD、crosshair 和响应式 Product Workspace。

**Tech Stack:** Vue 3 / TypeScript / Vite / Naive UI / lightweight-charts 5.2；FastAPI / SQLAlchemy / PostgreSQL；`packages/quant-core` Indicator Kernel；Node test runner / Playwright / pytest / Ruff / Mypy。

## Global Constraints

- 本计划**只在** `STATUS.md` 明确确认 MR-08 最终验收完成且 active 60/60 Canonical/audit 全闭环后启动。
- `MarketDataService` 仍是唯一正式历史 Bar 读取入口；Research Service 不得 glob Parquet、自判主力或跨频回退。
- `actual_dominant` 继续由 `MainContractMap rank=1` 查询时拼接；`continuous/MAIN` 继续保持未平滑语义。
- 必须保留现有 `MarketReadService`、`useMarketSeries`、`/bars/page`、`/market/state`、`/market/ws`、cursor pagination、generation token、Canonical/Live seam 和 reconnect 行为。
- Historical Research Universe 为 active 60；Live Observation Universe 继续只由 `operational_products.txt` 决定。完成 60/60 不授权扩大 Live。
- P0 Research API 只读 PostgreSQL/Canonical，不调用 RQData、不写 PostgreSQL、不写 Canonical、不改 Runtime enable state。
- 全市场 Radar 必须显式返回 `expected_as_of`、`participant_count`、`active_count`、stale/unavailable；任何品种未达到 expected_as_of 时显示 degraded，不伪装 60/60 current。
- P0 不实现 active 60 自动日终写入。若后续要达到每天 60/60 current 的 Daily Ready，另开 Lane 3 任务复用正式 `HistoricalDataManager.update`，且保持 Live universe 不变。
- 主图 overlay 只复用当前 Registry/`MAIN_INDICATOR_DEFINITIONS` 已登记项目；基线为 EMA10/EMA21/EMA60 与默认关闭的 HTDY original observation。
- Volume 与 MACD 固定为副图；不做画线、斐波那契、RSI/KDJ/CCI、任意 pane、分屏、多窗口或 TradingView clone。
- HTDY original 保持 observation-only、future-looking/repainting 风险；不得进入 Radar attention 规则，不修改 Registry capability。
- `attention` 只表示规则筛出的“值得关注”；`watchlist` 只表示用户本地自选，二者不得混用。
- P0 不新建 sector taxonomy。只有届时已经存在可信、完整 sector 元数据时才显示板块块；否则隐藏，不猜测。
- 所有结果都是研究观察，不是交易指令；保持 `auto_order=false`。
- 普通 P0 代码是 Lane 2；不得发布 main/tag，不得 Runtime promotion，不得执行真实数据写入。

---

## Activation Readback — 开发前一次性检查

在 Task 1 前执行只读检查，不修改代码：

```text
1. 阅读 STATUS.md
2. 确认 active universe = 60
3. 确认 60/60 Canonical closure + audit passed
4. 确认 Market Runtime MR-08 final acceptance 已闭环
5. 确认当前 Runtime operational subset 和 exact boundary
6. 阅读 AGENTS.md / docs/DEVELOPMENT.md / PROJECT_SOURCE.md / DECISIONS.md
7. 阅读 docs/DATA_CENTER.md / docs/INDICATOR_KERNEL.md / docs/tasks/GY-MARKET-RUNTIME-V1.md（若仍 active）
8. 阅读本设计：docs/superpowers/specs/2026-08-11-market-research-workspace-post-foundation-design.md
```

任一事实与本计划冲突时，以 active canonical 为准，停止并更新计划；不得从本文推断已经发生的生产状态。

---

## File Structure

### Backend research semantics

- Create: `services/quant-api/app/market_data/research.py` — 单品种研究计算、共享研究指标函数、`MarketResearchService.product_snapshot()`。
- Create: `services/quant-api/app/market_data/radar.py` — 60 品种 Radar 聚合、freshness、attention 规则。
- Modify: `services/quant-api/app/market_data/operational_universe.py` — 提取 `load_active_products()`，不改变 operational 语义。
- Modify: `services/quant-api/app/market_data/composition.py` — 组装 Research/Radar service；只注入 read dependencies。
- Modify: `services/quant-api/app/schemas/market.py` — Product Research / Radar DTO。
- Modify: `services/quant-api/app/api/market.py` — 新增只读 research routes。
- Test: `services/quant-api/tests/test_market_research.py`。
- Test: `services/quant-api/tests/test_market_radar.py`。
- Test: `services/quant-api/tests/test_market_research_api.py`。

### Product Workspace Web

- Create: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`。
- Create: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`。
- Create: `apps/quant-web/src/components/market/PriceVolumeOiPanel.vue`。
- Create: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`。
- Create: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`。
- Create: `apps/quant-web/src/utils/klineViewModel.ts`。
- Modify: `apps/quant-web/src/pages/market/chart.vue`。
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`。
- Modify: `apps/quant-web/src/types/market.ts`。
- Modify: `apps/quant-web/src/api/market.ts`。
- Modify only if needed for chart tokens: `apps/quant-web/src/styles/tokens.css` / `apps/quant-web/src/styles/chartTheme.ts`。

### Market Radar Web

- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`。
- Create: `apps/quant-web/src/components/market/MarketScatter.vue`。
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue`。
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`。
- Modify: `apps/quant-web/src/pages/market/index.vue`。
- Modify: `apps/quant-web/src/types/market.ts`。
- Modify: `apps/quant-web/src/api/market.ts`。

### Tests

- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`。
- Create: `apps/quant-web/tests/kline-view-model.test.ts`。
- Modify: `apps/quant-web/tests/indicators.test.ts` only for HTDY UI boundary regression。
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs` only when selectors/layout change；原 Runtime 语义测试必须保留。
- Create: `apps/quant-web/e2e/market-research.spec.mjs`。
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`。

---

### Task 1: Shared Product Research Service and exact metric semantics

**Lane:** Lane 2；推荐 Sol / 高推理，因为该任务冻结研究指标口径并连接 quant-core。

**Files:**
- Create: `services/quant-api/app/market_data/research.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/test_market_research.py`
- Create: `services/quant-api/tests/test_market_research_api.py`

**Interfaces:**

Internal identity:

```python
@dataclass(frozen=True, slots=True)
class ResearchSeriesIdentity:
    symbol: str
    series_kind: SeriesKind
    contract: str | None = None
```

Internal snapshot:

```python
@dataclass(frozen=True, slots=True)
class ProductResearchSnapshot:
    symbol: str
    product_name: str
    exchange: str
    series_kind: str
    contract: str | None
    current_dominant: str | None
    dominant_mapping_date: date | None
    daily_trend: str
    weekly_trend: str
    position20: Decimal | None
    distance_to_20d_high: Decimal | None
    distance_to_20d_low: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    turnover_change_5d: Decimal | None
    atr14_percentile252: Decimal | None
    recent_daily: tuple[ResearchDailyPoint, ...]
```

Public service:

```python
class MarketResearchService:
    def product_snapshot(self, identity: ResearchSeriesIdentity) -> ProductResearchSnapshot: ...
```

API:

```text
GET /api/v1/market/research/product
  symbol
  series_kind
  contract?      # 仅 contract 必填
```

#### Exact P0 metric definitions

```text
position20 = (close_T - min(low,last20)) / (max(high,last20)-min(low,last20))
distance_to_20d_high = close_T / max(high,last20) - 1
distance_to_20d_low  = close_T / min(low,last20) - 1
volume_ratio20 = volume_T / mean(previous 20 volumes), current excluded
oi_change_1d = OI_T / OI_T-1 - 1, only when both are finite and previous > 0
turnover_change_5d = turnover_T / mean(previous 5 turnovers) - 1, only when all six values exist
```

Daily/weekly trend:

```text
up      = close > EMA21 AND EMA21[T] > EMA21[T-1]
down    = close < EMA21 AND EMA21[T] < EMA21[T-1]
neutral = otherwise
unavailable = EMA not ready / insufficient data
```

EMA 必须调用 quant-core `ema_series(..., period=21, seed_policy="sma_window")`。

ATR 必须调用 quant-core `atr_series(..., period=14, smoothing_policy="wilder_sma_seed")`；ATR percentile 使用 latest ready ATR 对前最多 252 个 ready ATR 值计算经验分位，少于 20 个基准值则返回 `None`。

- [ ] **Step 1: Write failing pure metric tests**

至少加入以下测试结构：

```python
def test_product_metrics_exclude_current_bar_from_volume_baseline():
    bars = daily_bars(volumes=[100] * 20 + [200])
    snapshot = build_product_metrics(bars, weekly_bars(...))
    assert snapshot.volume_ratio20 == Decimal("2")


def test_product_metrics_return_unavailable_instead_of_zero_when_oi_missing():
    bars = daily_bars_with_missing_latest_oi()
    snapshot = build_product_metrics(bars, weekly_bars(...))
    assert snapshot.oi_change_1d is None
```

同时覆盖 EMA up/down/neutral、position20、turnover5、ATR percentile、短历史 unavailable。

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_research.py
```

Expected: FAIL because research module/functions do not exist.

- [ ] **Step 3: Implement pure helpers without duplicating indicator formulas**

`research.py` 中只写研究组合逻辑；EMA/ATR 必须通过 quant-core public functions。所有输出 ratio/price-derived values 使用 `Decimal`，不得把数据库/Canonical Decimal 转 float 后再作为后端业务结果。

- [ ] **Step 4: Implement `MarketResearchService.product_snapshot()`**

对同一 identity 调用 `MarketDataService.query_page()`：

```text
1d limit = 300
1w limit = 80
```

只读历史；不调用 `/market/state`、Redis 或 RQData。当前主力上下文使用既有 `MarketDataService.list_latest_dominants()` / MainContractMap 事实，不自行计算主力。

- [ ] **Step 5: Add Pydantic DTO and endpoint**

合同/identity 错误映射到现有 422 语义；`MarketDataError` 映射到 409；错误响应不暴露路径、SQL 或 provider internal detail。

- [ ] **Step 6: Run targeted GREEN**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research.py \
  services/quant-api/tests/test_market_research_api.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data/research.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_market_research.py \
  services/quant-api/tests/test_market_research_api.py

git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/market_data/research.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_market_research.py \
  services/quant-api/tests/test_market_research_api.py
git commit -m "feat(market): add product research read model"
```

---

### Task 2: Product Workspace shell, fast controls, and local state

**Lane:** Lane 2；Terra / 中推理。

**Files:**
- Create: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Create: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Create: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`
- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify selectors only as required: `apps/quant-web/e2e/market-runtime.spec.mjs`

**Interfaces:**

```ts
export interface MarketWorkspacePreferences {
  version: 1
  symbol: string | null
  seriesKind: 'actual_dominant' | 'continuous'
  researchSidebarOpen: boolean
  watchlist: string[]
}
```

Exports:

```ts
defaultMarketWorkspacePreferences()
loadMarketWorkspacePreferences(storage?)
saveMarketWorkspacePreferences(value, storage?)
toggleWatchlistSymbol(value, symbol)
```

- [ ] **Step 1: Write localStorage RED tests**

```ts
test('corrupt local state falls back to simple defaults', () => {
  const storage = { getItem: () => '{bad' }
  assert.deepEqual(loadMarketWorkspacePreferences(storage), defaultMarketWorkspacePreferences())
})

test('watchlist normalizes and toggles one symbol', () => {
  const a = toggleWatchlistSymbol(defaultMarketWorkspacePreferences(), ' JM ')
  assert.deepEqual(a.watchlist, ['jm'])
  assert.deepEqual(toggleWatchlistSymbol(a, 'jm').watchlist, [])
})
```

- [ ] **Step 2: Run RED**

```bash
node --test apps/quant-web/tests/market-workspace-preferences.test.ts
```

- [ ] **Step 3: Implement local preference helper**

Defaults:

```ts
{
  version: 1,
  symbol: null,
  seriesKind: 'actual_dominant',
  researchSidebarOpen: true,
  watchlist: [],
}
```

Malformed/wrong-version storage silently falls back; no Preference API or DB.

- [ ] **Step 4: Replace management-form toolbar**

Visible high-frequency controls:

```text
品种 | 真实主力/主连 | 1m 5m 15m 30m 60m D W | 指标 | 全屏
```

`contract` 作为高级入口。Route query 优先于 localStorage；未提供 route 时读 localStorage，最终 fallback 为第一个 dominant / actual_dominant / 15m。

切换立即调用现有 `replaceSeries()`；不保留“读取最新页”主按钮流程。

- [ ] **Step 5: Add responsive shell**

```css
.product-workspace__main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 296px;
  gap: 12px;
}
@media (max-width: 1599px) {
  .product-workspace__main { grid-template-columns: minmax(0, 1fr); }
}
```

小于 1600px 隐藏常驻右栏并使用一个 `NDrawer` “研究”入口。全屏只作用于 Kline workspace container。

- [ ] **Step 6: Preserve every Runtime seam behavior**

`chart.vue` 必须继续使用现有：

```text
bars
canonicalCoverage
replaceSeries
loadMoreBefore
mutation replace/prepend/live
marketState
liveUnavailable
followLatest
dispose
```

不得在页面重新实现 WebSocket/merge。

- [ ] **Step 7: Run regression**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

Existing Runtime browser scenarios must remain green.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/utils/marketWorkspacePreferences.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/tests/market-workspace-preferences.test.ts \
  apps/quant-web/e2e/market-runtime.spec.mjs
git commit -m "feat(web): add focused product workspace shell"
```

---

### Task 3: Three-pane Kline core, EMA, fixed Volume/MACD, and crosshair

**Lane:** Lane 2；Sol / 高推理，因为该任务同时触及图表生命周期、分页视口和已验收 Live append。

**Files:**
- Create: `apps/quant-web/src/utils/klineViewModel.ts`
- Create: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Create: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify only if required: `apps/quant-web/src/styles/chartTheme.ts`, `apps/quant-web/src/styles/tokens.css`

**Interfaces:**

```ts
export interface KlineDerivedData {
  ema: Partial<Record<'ema_10' | 'ema_21' | 'ema_60', Array<{ time: string; value: number }>>>
  macd: {
    dif: Array<{ time: string; value: number }>
    dea: Array<{ time: string; value: number }>
    histogram: Array<{ time: string; value: number }>
  }
}

export function buildKlineDerivedData(
  bars: BarData[],
  visibleMainIndicators: MainIndicatorId[],
): KlineDerivedData
```

`KlineChart` must keep exposed methods exactly:

```text
replaceBars(bars, preserveViewport?)
prependBars(bars)
updateBar(bar)
scrollToLatest()
```

and adds:

```text
prop visibleMainIndicators
emit crosshair-change(HoverKlineContext | null)
```

- [ ] **Step 1: Write view-model RED tests**

```ts
test('only selected EMA overlays are derived while MACD is always derived', () => {
  const d = buildKlineDerivedData(makeBars(100), ['ema_21'])
  assert.equal(d.ema.ema_10, undefined)
  assert.ok(d.ema.ema_21!.length > 0)
  assert.ok(d.macd.histogram.length > 0)
})
```

Add a hover alignment test asserting bar/OI/EMA/MACD all resolve from the same bar time.

- [ ] **Step 2: Run RED**

```bash
node --test apps/quant-web/tests/kline-view-model.test.ts
```

- [ ] **Step 3: Implement derived data using existing Web observation mirror**

Use existing `calculateEMA()` / `calculateMACD()` from `src/utils/indicators.ts`; do not duplicate formulas in `klineViewModel.ts`.

- [ ] **Step 4: Convert chart to fixed three panes**

Using lightweight-charts v5 pane indexes:

```ts
candles       -> pane 0
volume        -> pane 1
macdHistogram -> pane 2
macdDif       -> pane 2
macdDea       -> pane 2
```

Target visual proportion approximately 6/2/2. This is code-fixed, not user-resizable product configuration.

- [ ] **Step 5: Add EMA series lifecycle**

EMA line series use a `Map<MainIndicatorId, ISeriesApi<'Line'>>` for EMA10/21/60. `replace/prepend` may recompute and `setData`; Live `updateBar` must not call `fitContent()` and must preserve current follow/viewport behavior.

- [ ] **Step 6: Add synchronized crosshair**

`KlineHoverLegend` shows only values available at the crosshair time:

```text
O H L C | Volume | OI | enabled EMA | DIF DEA HIST
```

Never replace missing OI/indicator values with zero.

- [ ] **Step 7: Make chart viewport-based**

Baseline:

```css
.kline-shell { min-height: 680px; height: clamp(680px, 74vh, 1040px); }
.chart { width: 100%; height: 100%; }
```

Fullscreen uses 100vh. No drag-resize layout system.

- [ ] **Step 8: Run full chart regression**

```bash
node --test apps/quant-web/tests/kline-view-model.test.ts
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/styles/chartTheme.ts \
  apps/quant-web/src/styles/tokens.css \
  apps/quant-web/tests/kline-view-model.test.ts
git commit -m "feat(web): add three-pane market chart"
```

Only stage theme/token files if they actually changed.

---

### Task 4: Product Research Sidebar and Price/Volume/OI section

**Lane:** Lane 2；Terra / 中推理。

**Files:**
- Create: `apps/quant-web/src/components/market/PriceVolumeOiPanel.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Create: `apps/quant-web/e2e/market-research.spec.mjs`

**Interfaces:**

Frontend API:

```ts
export function getProductResearch(params: {
  symbol: string
  series_kind: SeriesKind
  contract?: string
}): Promise<ProductResearchResponse>
```

One response drives both sidebar and lower P0 panel.

- [ ] **Step 1: Add Web DTO and API call**

Map backend Decimal JSON values to nullable numeric display values only at the Web boundary; preserve null as unavailable.

- [ ] **Step 2: Write E2E expectations before UI**

Mock `/market/research/product` and assert:

```text
- large viewport shows research sidebar
- 1599px viewport uses drawer entry instead of permanent 296px column
- daily/weekly trend, position20, volume ratio, OI and dominant context appear
- missing OI renders unavailable copy, not 0%
- research endpoint failure does not hide or error the Kline chart
```

Run RED:

```bash
npm --prefix apps/quant-web run test:e2e -- market-research.spec.mjs
```

- [ ] **Step 3: Bind sidebar to current displayed identity**

On symbol/series/contract change, request exactly one Product Research snapshot. Use a generation token/abort pattern so stale research results cannot leak from previous symbol into current page.

- [ ] **Step 4: Implement compact three-block sidebar**

```text
趋势/位置
量与持仓
合约上下文
```

No P1 placeholder cards.

- [ ] **Step 5: Implement PriceVolumeOiPanel**

Use recent daily series from the same response. A simple SVG is enough: normalized close line + normalized OI line + compact volume bars. If OI is absent, still render price/volume and show `OI 暂无可用数据`.

- [ ] **Step 6: Run tests/build**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-research.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add \
  apps/quant-web/src/components/market/PriceVolumeOiPanel.vue \
  apps/quant-web/src/components/market/ProductResearchSidebar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/e2e/market-research.spec.mjs
git commit -m "feat(web): add product research context"
```

---

### Task 5: Full-universe Radar backend with freshness and transparent attention rules

**Lane:** Lane 2；Sol / 高推理。该任务定义 60 品种聚合研究口径，但仍完全只读。

**Files:**
- Create: `services/quant-api/app/market_data/radar.py`
- Modify: `services/quant-api/app/market_data/operational_universe.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/test_market_radar.py`
- Modify: `services/quant-api/tests/test_market_research_api.py`

**Interfaces:**

Add:

```python
def load_active_products(path: Path | None = None) -> tuple[str, ...]: ...
```

It must validate exactly 60 unique normalized symbols and zero retired overlap. Existing `load_operational_products()` calls/reuses it; operational semantics remain unchanged.

Radar snapshot minimum fields:

```text
status: ready | degraded
expected_as_of
active_count
participant_count
stale[]
unavailable[]
summary
items[]
attention[]
```

Frozen reason codes:

```text
price_move_up
price_move_down
volume_expansion
oi_increase
oi_decrease
high_volatility
near_20d_high
near_20d_low
ema21_up
ema21_down
```

Frozen thresholds:

```python
PRICE_MOVE_PCT = Decimal("0.02")
VOLUME_EXPANSION_RATIO = Decimal("1.50")
OI_EXPANSION_PCT = Decimal("0.05")
HIGH_VOLATILITY_PERCENTILE = Decimal("0.80")
NEAR_HIGH_POSITION = Decimal("0.90")
NEAR_LOW_POSITION = Decimal("0.10")
ATTENTION_MIN_REASONS = 2
ATTENTION_LIMIT = 10
RADAR_DAILY_LIMIT = 300
```

- [ ] **Step 1: Write active-universe loader tests**

Assert invalid count, duplicates and retired overlap raise the existing stable universe error. Assert operational subset validation still passes unchanged.

- [ ] **Step 2: Write Radar RED tests with fake readers**

Cover:

```text
- expected_as_of supplied by injected complete-day reader
- all 60 current => status=ready, participant_count=60
- one stale latest day => degraded, participant_count=59, stale contains symbol
- one known MarketDataError => degraded, unavailable contains code, other products continue
- unexpected RuntimeError propagates
- attention threshold is not lowered to fill 10
- sorting is deterministic
```

- [ ] **Step 3: Reuse existing complete-day semantics**

`MarketRadarService` consumes a small protocol:

```python
class CompleteDayReader(Protocol):
    def latest_complete_day(self, products: tuple[str, ...]) -> date: ...
```

Composition may adapt existing `DatabaseCoverageSource.latest_complete_day()`; do not implement browser-date or `datetime.now().date()` logic in Radar.

- [ ] **Step 4: Query each active symbol through MarketDataService**

For each symbol use `actual_dominant / 1d / limit=300`. A symbol participates only when its latest `trading_day == expected_as_of`.

Radar metric values reuse shared metric helpers from Task 1; do not create a second EMA/ATR/volume implementation.

- [ ] **Step 5: Build attention reasons**

Rules exactly follow frozen thresholds. Candidate requires `reason_count >= 2`. Sort:

```text
reason_count DESC
abs(price_change_1d) DESC
turnover DESC (None last)
symbol ASC
```

Return at most 10.

- [ ] **Step 6: Add read-only Radar endpoint**

```text
GET /api/v1/market/research/radar
```

No provider call and no request body.

- [ ] **Step 7: Run targeted and full backend regression**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_research.py \
  services/quant-api/tests/test_market_radar.py \
  services/quant-api/tests/test_market_research_api.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data/research.py \
  services/quant-api/app/market_data/radar.py \
  services/quant-api/app/market_data/operational_universe.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/schemas/market.py

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add \
  services/quant-api/app/market_data/radar.py \
  services/quant-api/app/market_data/operational_universe.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/test_market_radar.py \
  services/quant-api/tests/test_market_research_api.py
git commit -m "feat(market): add full-universe research radar"
```

---

### Task 6: Market Radar Web and local watchlist

**Lane:** Lane 2；Terra / 中推理。

**Files:**
- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`
- Create: `apps/quant-web/src/components/market/MarketScatter.vue`
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`

- [ ] **Step 1: Add Radar TypeScript contract/API**

```ts
export function getMarketRadar() {
  return request.get<never, MarketRadarResponse>('/market/research/radar')
}
```

Preserve `status`, freshness, stale/unavailable and null metrics exactly.

- [ ] **Step 2: Write Radar E2E RED expectations**

Mock a ready 60/60 snapshot and a degraded 59/60 snapshot. Assert:

```text
- expected_as_of/date visible
- ready shows 60/60
- degraded shows 59/60 and clear warning
- scatter point click routes directly to Product Workspace
- attention reasons are visible
- no composite score is shown
- local 自选 is distinct from attention
```

- [ ] **Step 3: Build compact summary strip**

Only:

```text
上涨 | 下跌 | 放量 | 明显增仓 | 高波动 | 数据日期/60状态
```

- [ ] **Step 4: Build native SVG scatter**

X = price 1D, Y = OI 1D. Missing OI items stay in detail table but are omitted from scatter. Bubble radius uses bounded log turnover, 6–18px. Hover only shows symbol/name, price, OI, volume ratio, ATR percentile.

- [ ] **Step 5: Build attention list**

Web translates backend reason codes to factual Chinese labels. It must not recalculate thresholds or scores.

- [ ] **Step 6: Build detail table and optional watchlist filter**

Table columns:

```text
品种 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态
```

`全部 / 自选` uses localStorage watchlist. Clicking any item goes directly to `actual_dominant` Product Workspace; period uses stored chart preference if valid, otherwise 15m。

- [ ] **Step 7: Sector behavior**

P0 does **not** create a classification file. If the future repository already has complete trusted sector metadata, an optional low-density sector block may be rendered; otherwise do not render the block. This omission is accepted P0 behavior and does not block Radar Ready.

- [ ] **Step 8: Run Web verification**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-radar.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add \
  apps/quant-web/src/components/market/MarketSummaryStrip.vue \
  apps/quant-web/src/components/market/MarketScatter.vue \
  apps/quant-web/src/components/market/MarketAttentionList.vue \
  apps/quant-web/src/components/market/MarketDetailTable.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/utils/marketWorkspacePreferences.ts \
  apps/quant-web/e2e/market-radar.spec.mjs
git commit -m "feat(web): add market research radar"
```

---

### Task 7: HTDY original observation overlay — isolated risk task

**Lane:** Lane 2；Sol / 高推理 + 独立 Review。

**Files:**
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`

- [ ] **Step 1: Freeze risk assertions first**

Tests must assert current registry mirror stays:

```text
defaultVisible = false
capability = observation_overlay
repaintingRisk = known
unstableTailBars = 27
alertCapable = false
```

- [ ] **Step 2: Run tests before rendering change**

```bash
node --test apps/quant-web/tests/indicators.test.ts apps/quant-web/tests/kline-view-model.test.ts
```

- [ ] **Step 3: Use existing `calculateHuoTianDaYou()` only**

Do not change formula or quant-core. When selected, render existing `zk1/zd1/zd2` as light overlay lines and observation markers. Labels must use：

```text
买观察
卖观察
XG观察
```

Do not use “买入信号/卖出信号/建议”。

- [ ] **Step 4: Keep risk notice visible**

While enabled, toolbar/fullscreen always displays:

```text
火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察
```

- [ ] **Step 5: Verify no backend/Runtime capability change**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run build
git diff --check
```

Review diff must show no changes to quant-core registry capability, Runtime, DB or API signal surfaces.

- [ ] **Step 6: Commit**

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/kline-view-model.test.ts \
  apps/quant-web/tests/indicators.test.ts
git commit -m "feat(web): add htdy observation overlay"
```

---

### Task 8: P0 integration, exact status closure, and user-use Gate

**Lane:** Lane 2 integration；Sol / 高推理，独立 Review 会话。

**Files:**
- Modify only when facts change: `STATUS.md`
- Modify if validation commands change: `TESTING.md`
- Modify design/plan only if implementation differs from approved semantics.

- [ ] **Step 1: Review architecture boundaries**

Explicitly verify:

```text
MarketDataService still owns all historical bars
MarketResearchService is read-only
useMarketSeries still owns Historical/Live seam
operational Live subset unchanged
no RQData provider passthrough
no DB migration/table
no main/tag/release
no Runtime switch/promotion
no active-60 real data write
no P1 member/warehouse/roll-yield scope
no trading-advice wording
HTDY capability unchanged
```

- [ ] **Step 2: Run complete frontend verification**

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run test:e2e -- market-runtime.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-research.spec.mjs
npm --prefix apps/quant-web run test:e2e -- market-radar.spec.mjs
npm --prefix apps/quant-web run build
```

- [ ] **Step 3: Run complete backend verification**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py
```

No new errors are accepted relative to the baseline at the moment development actually starts.

- [ ] **Step 4: Repository hygiene**

```bash
git diff --check
git status --short
```

Run the repository-applicable secret scan for changed tracked executable/source files; report only pass/fail.

- [ ] **Step 5: Update bounded status**

If code/test complete but active 60 daily freshness automation is not enabled, status must distinguish：

```text
Market Research Workspace P0 Ready
vs
Daily Radar 60/60 Current Automation not enabled
```

Do not claim daily freshness automation from historical closure alone.

- [ ] **Step 6: Real-use Gate**

Before starting P1, use the P0 interface for several normal sessions and evaluate only：

```text
Radar 是否真的减少找品种时间
Kline 第一屏是否足够完整
右栏是否过载
attention 规则是否产生过多噪声
页面首屏/切换是否足够快
```

This is a product-use review, not a profitability Gate.

- [ ] **Step 7: Commit documentation only if changed**

```bash
git add STATUS.md TESTING.md docs/superpowers/specs/2026-08-11-market-research-workspace-post-foundation-design.md docs/superpowers/plans/2026-08-11-market-research-workspace-post-foundation-p0.md
git diff --cached --quiet || git commit -m "docs: close market research workspace P0"
```

Stage only files that actually changed.

---

## Codex Dispatch Order

```text
Task 1  MarketResearchService product snapshot      Sol / high
Task 2  Product Workspace shell                     Terra / medium
Task 3  Kline three-pane core                       Sol / high
Task 4  Product research UI                         Terra / medium
Task 5  Full-universe Radar backend                 Sol / high
Task 6  Radar Web                                   Terra / medium
Task 7  HTDY observation                            Sol / high + independent review
Task 8  Final integration review                    Sol / high / Plan-only review
```

每个独立任务默认：

```text
一个 Codex App 新会话
一个 task branch/worktree（从 develop 创建）
Plan-then-execute
测试通过后可按仓库个人流程集成 develop
确认进入 develop 后清理 task worktree/branch
不要求 PR，除非当时仓库流程或用户另有要求
```

禁止触及 `main`、tag、最终 Runtime worktree 或真实数据写入。

---

## Separate Lane 3 Follow-up — Daily 60/60 Freshness

这不是本 P0 实施任务，不与 Task 1～8 混跑。

当 P0 完成且用户确认需要每天自动得到 60/60 current Radar 时，再单独启动：

```text
目标：active 60 historical EOD update
保持：operational Live subset 不变
复用：HistoricalDataManager.update / existing readiness / natural resume
不做：60 路 Live、task center、DB scheduler table
```

该任务必须使用：

```text
Lane 3
Sol / high
新会话
Plan-only first
独立 Review
真实写入/Runtime scope 人工 Gate
```

启用前必须先在最终 60/60 基线上只读测量每日目标量、provider quota、典型耗时和失败恢复行为；不要在本文中预设生产执行时长或额度。

---

## Supersession

Activation Gate 满足并开始 V2 开发后，本计划替代：

```text
docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md
```

旧计划保留为历史，不再作为 Codex 执行入口。
