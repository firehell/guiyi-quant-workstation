# Market Research Workspace V2 P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Final rebase：2026-08-12  
Design source：`docs/superpowers/specs/2026-08-11-market-research-workspace-post-foundation-design.md`

**Goal:** 在 active 60/60 Canonical 已完整闭环的稳定基线上，把当前 Market Web 升级为“Market Radar → Product Workspace”的个人期货研究工作站，同时保持已经验收的 Historical/Live seam、60 品种 Runtime 范围和 Indicator Kernel 权威边界。

**Architecture:** 新增只读共享研究层：`MarketDataService -> research_metrics -> MarketResearchService / MarketRadarService -> semantic DTO -> Web`。Product Workspace 继续使用现有 `useMarketSeries` / `MarketReadService`；Radar 只读 `actual_dominant/1d` Canonical，不调用 provider、不触发历史写入。Kline 在现有分页、上海时间和 viewport 行为上增加固定三 pane、EMA、Volume/MACD 和 crosshair。

**Tech Stack:** Vue 3 / TypeScript / Vite / Naive UI / lightweight-charts 5.2；FastAPI / SQLAlchemy / PostgreSQL；`packages/quant-core` Indicator Kernel；pytest / Ruff / Mypy / Node test runner / Playwright / pnpm。

## Global Constraints

- 当前 `STATUS.md` 已确认 DFD-01～DFD-07 完成归档、active 60/60 Canonical closure、全域 audit passed / 0 findings；本计划不再等待 Data Foundation Gate。
- `active_products.txt` 与 `operational_products.txt` 当前内容完全一致，均为 60；不得在 P0 修改这两个文件。
- Runtime 60 只表示 operational scope=60；Live provider channel 必须继续按真实 `TRADING` phase 动态订阅，不要求任何时刻同时 60 channel。
- 现有 17:00 + 最多一次 1h retry after-market 已配置为 operational 60；首次 60 品种自然运行通过前，
  只声明配置与代码就绪，不声明真实更新已完成。P0 不新增 Daily scheduler、任务表或第二历史写入口。
- `MarketDataService` 仍是唯一正式历史 Bar 入口；Research 不得 glob Parquet、自判主力或跨频回退。
- `actual_dominant` 只由 `MainContractMap rank=1` 查询拼接；`continuous/MAIN` 保持当前未平滑语义。
- 必须保留现有 `MarketReadService`、`useMarketSeries`、`/bars/page`、`/market/state`、`/market/ws`、after-market seam、generation token、reconnect、left pagination、Shanghai time 和 viewport 行为。
- P0 Research API 只读 PostgreSQL/Canonical；不得调用 RQData、Redis Live，不得写 PostgreSQL/Canonical，不得执行 Runtime switch。
- `product_sectors.csv` / `product_taxonomy.py` 已是 active 60 展示 taxonomy；不得创建第二套 symbol→sector 映射。
- `load_active_products()` 已存在；不得为了 Radar 再实现 active-universe loader。
- 主图只复用当前 `MAIN_INDICATOR_DEFINITIONS` 已登记项目；EMA10/21/60 为标准 overlay，HTDY original 默认关闭且 observation-only。
- Volume 与 MACD 固定为两个副图；不做画线、斐波那契、RSI/KDJ/CCI、任意 pane、分屏、多窗口或 TradingView clone。
- `attention` = 后端透明规则筛选；`watchlist` = 用户 localStorage 自选；字段和 UI 文案不得混用。
- 所有输出是研究观察，不是交易指令；`auto_order=false` 始终成立。
- 普通实现为 Lane 2；不得发布 `main`、创建 tag、切换最终 Runtime 或执行真实数据写入。
- 实现期所有验证命令以当时 `TESTING.md` 为准；当前 Web package manager 是 pnpm，不再使用旧计划中的 npm 命令。

---

## Start Readback

Task 1 开始前只读确认一次：

```text
1. STATUS.md 仍确认 Data Foundation 60/60 完成
2. AGENTS.md / docs/DEVELOPMENT.md 无新执行规则冲突
3. PROJECT_SOURCE.md / DECISIONS.md 仍确认 active=60、operational=60
4. docs/DATA_CENTER.md 数据合同无变化
5. docs/INDICATOR_KERNEL.md Registry/HTDY 边界无变化
6. product_sectors.csv 仍精确覆盖 active 60
7. 当前 Market Web 仍以 useMarketSeries + KlineChart 为主路径
```

当前另有一个独立 Runtime 自然验收尾项：`51e84988...` 已部署完整 rank1 snapshot / phase-scoped
channel 修复；盘后 Calendar-first 修复的部署状态与 17:00 结果只看 `STATUS.md`。若开始开发时仍未完成：

- Task 1～7 不因此阻塞；
- 不允许 Codex 顺手执行 Runtime switch 或手工盘后；
- Task 8 的真实 Runtime-integrated acceptance 前必须先完成独立授权的 switch（如仍需要），并等自然触发读回。

---

## File Map

### Backend

- Create: `services/quant-api/app/market_data/research_metrics.py` — 纯研究指标组合函数；零 I/O。
- Create: `services/quant-api/app/market_data/market_research_service.py` — 单品种 ProductResearchSnapshot 只读 facade。
- Create: `services/quant-api/app/market_data/market_radar.py` — 60 品种 freshness、Radar 聚合、attention、sector summary。
- Modify: `services/quant-api/app/market_data/composition.py` — 只读 Research/Radar 组装。
- Modify: `services/quant-api/app/schemas/market.py` — Product Research / Radar Pydantic DTO。
- Modify: `services/quant-api/app/api/market.py` — 两个只读 research endpoint。
- Create: `services/quant-api/tests/data_foundation/test_market_research.py`。
- Create: `services/quant-api/tests/data_foundation/test_market_radar.py`。
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`。

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
- Modify only if needed: `apps/quant-web/src/styles/chartTheme.ts`, `apps/quant-web/src/styles/tokens.css`。

### Radar Web

- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`。
- Create: `apps/quant-web/src/components/market/MarketScatter.vue`。
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue`。
- Create: `apps/quant-web/src/components/market/MarketSectorSummary.vue`。
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`。
- Modify: `apps/quant-web/src/pages/market/index.vue`。
- Reuse: `apps/quant-web/src/utils/productDirectory.ts` — sector labels only。

### Web Tests

- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`。
- Create: `apps/quant-web/tests/kline-view-model.test.ts`。
- Modify: `apps/quant-web/tests/indicators.test.ts` only for HTDY UI risk regression。
- Modify: `apps/quant-web/e2e/market-runtime.spec.mjs` only when selectors/layout change；现有 seam scenarios must remain。
- Create: `apps/quant-web/e2e/market-research.spec.mjs`。
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`。

---

### Task 1: Shared research metrics and ProductResearchService

**Lane:** Lane 2  
**Recommended:** Sol / 高推理  
**Reason:** 冻结研究统计口径并连接 quant-core；错误会传播到 Radar 和 Product Workspace。

**Files:**
- Create: `services/quant-api/app/market_data/research_metrics.py`
- Create: `services/quant-api/app/market_data/market_research_service.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/data_foundation/test_market_research.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ResearchSeriesIdentity:
    symbol: str
    series_kind: SeriesKind
    contract: str | None = None

@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    price_change_1d: Decimal | None
    price_change_5d: Decimal | None
    daily_trend: str
    weekly_trend: str
    position20: Decimal | None
    distance_to_20d_high: Decimal | None
    distance_to_20d_low: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    turnover_change_5d: Decimal | None
    atr14_percentile252: Decimal | None

class MarketResearchService:
    def product_snapshot(self, identity: ResearchSeriesIdentity) -> ProductResearchSnapshot: ...
```

Public API:

```text
GET /api/v1/market/research/product
  symbol
  series_kind
  contract?   # only contract mode requires it
```

Frozen metric formulas:

```text
price_change_1d = close_T / close_T-1 - 1
price_change_5d = close_T / close_T-5 - 1
position20 = (close_T - min(low,last20)) / (max(high,last20)-min(low,last20))
distance_to_20d_high = close_T / max(high,last20) - 1
distance_to_20d_low = close_T / min(low,last20) - 1
volume_ratio20 = volume_T / mean(previous 20 volumes), current excluded
oi_change_1d = oi_T / oi_T-1 - 1, both finite and previous > 0
turnover_change_5d = turnover_T / mean(previous 5 turnovers) - 1, all required values present
```

Trend：

```text
up      = close > EMA21 and EMA21[T] > EMA21[T-1]
down    = close < EMA21 and EMA21[T] < EMA21[T-1]
neutral = otherwise
unavailable = EMA not ready
```

EMA must call quant-core `ema_series(period=21, seed_policy="sma_window")`。ATR must call `atr_series(period=14, smoothing_policy="wilder_sma_seed")`。ATR percentile uses the latest ready ATR against at most the previous 252 ready ATR values；fewer than 20 baseline values => `None`。

- [ ] **Step 1: Write RED metric tests**

```python
def test_volume_ratio_excludes_current_bar():
    daily = make_daily_bars(volumes=[Decimal("100")] * 20 + [Decimal("200")])
    result = calculate_research_metrics(daily, make_weekly_bars(30))
    assert result.volume_ratio20 == Decimal("2")


def test_missing_oi_is_unavailable_not_zero():
    daily = make_daily_bars_with_latest_oi(None)
    result = calculate_research_metrics(daily, make_weekly_bars(30))
    assert result.oi_change_1d is None
```

Also cover：1D/5D return、EMA up/down/neutral、position20 zero-range handling、turnover5、ATR percentile、insufficient history。

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_research.py
```

Expected: FAIL because the new module/functions do not exist.

- [ ] **Step 3: Implement pure `research_metrics.py`**

Use `Decimal` for backend ratio/price-derived results。Do not duplicate EMA/ATR formulas；call quant-core public functions。Missing/invalid values return `None`/`unavailable`，never 0。

- [ ] **Step 4: Implement `MarketResearchService.product_snapshot()`**

Read current identity through `MarketDataService.query_page()` only：

```text
1d limit = 300
1w limit = 80
```

Use existing `list_latest_dominants()` for current rank1 context。Read product name/sector from existing taxonomy-backed dominant summary。Return only latest 80 daily points in `recent_daily`。

- [ ] **Step 5: Add Product Research DTO and API test**

Add API test cases：

```text
valid actual_dominant -> 200
valid continuous -> 200
contract without contract -> 422
MarketDataError -> 409
```

Research failure responses must not expose SQL/path/provider internals。

- [ ] **Step 6: Run GREEN**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_research.py \
  services/quant-api/tests/data_foundation/test_market_api.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data/research_metrics.py \
  services/quant-api/app/market_data/market_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/data_foundation/test_market_research.py \
  services/quant-api/tests/data_foundation/test_market_api.py

git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add \
  services/quant-api/app/market_data/research_metrics.py \
  services/quant-api/app/market_data/market_research_service.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/data_foundation/test_market_research.py \
  services/quant-api/tests/data_foundation/test_market_api.py
git commit -m "feat(market): add product research read model"
```

---

### Task 2: Product Workspace shell and local state

**Lane:** Lane 2  
**Recommended:** Terra / 中推理

**Files:**
- Create: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Create: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Create: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`
- Create: `apps/quant-web/tests/market-workspace-preferences.test.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify selectors only when necessary: `apps/quant-web/e2e/market-runtime.spec.mjs`

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

Exports：

```text
defaultMarketWorkspacePreferences()
loadMarketWorkspacePreferences(storage?)
saveMarketWorkspacePreferences(value, storage?)
toggleWatchlistSymbol(value, symbol)
```

- [ ] **Step 1: Write localStorage RED tests**

```ts
test('corrupt workspace state falls back to defaults', () => {
  const storage = { getItem: () => '{bad' }
  assert.deepEqual(loadMarketWorkspacePreferences(storage), defaultMarketWorkspacePreferences())
})

test('watchlist normalizes and toggles one symbol', () => {
  const added = toggleWatchlistSymbol(defaultMarketWorkspacePreferences(), ' JM ')
  assert.deepEqual(added.watchlist, ['jm'])
  assert.deepEqual(toggleWatchlistSymbol(added, 'jm').watchlist, [])
})
```

- [ ] **Step 2: Run RED**

```bash
pnpm --dir apps/quant-web exec node --test tests/market-workspace-preferences.test.ts
```

- [ ] **Step 3: Implement local preferences**

Exact defaults：

```ts
{
  version: 1,
  symbol: null,
  seriesKind: 'actual_dominant',
  researchSidebarOpen: true,
  watchlist: [],
}
```

Malformed JSON, wrong version, invalid series or invalid watchlist entries fall back/normalize；storage errors never block page load。

- [ ] **Step 4: Replace the management-style toolbar**

Visible high-frequency controls：

```text
品种 | 真实主力/主连 | 1m 5m 15m 30m 60m D W | 指标 | 全屏
```

`contract` remains in a compact advanced entry。Route query has precedence over localStorage；period preference continues to reuse current main chart preference；final fallback remains first dominant / actual_dominant / 15m。

Series/period changes call existing `refreshSeries()` / `replaceSeries()` immediately；remove the main “读取最新页” interaction。

- [ ] **Step 5: Add responsive shell**

```css
.product-workspace__main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 296px;
  gap: 12px;
}

@media (max-width: 1599px) {
  .product-workspace__main {
    grid-template-columns: minmax(0, 1fr);
  }
}
```

Below 1600px, use one Naive UI drawer entry named `研究`。Fullscreen only targets the Kline workspace container。

- [ ] **Step 6: Preserve current seam wiring exactly**

`chart.vue` must continue to consume：

```text
bars
canonicalCoverage
hasMoreBefore
marketState
liveUnavailable
mutation
replaceSeries
loadMoreBefore
dispose
```

Keep mutation `replace/prepend/live` and `followLatest` behavior；do not move WebSocket logic into the page。

- [ ] **Step 7: Run Web regression**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

Existing pagination、after-market seam、BREAK/CLOSED、stale WebSocket isolation scenarios must remain green。

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

### Task 3: Three-pane Kline core, EMA, fixed Volume/MACD, crosshair

**Lane:** Lane 2  
**Recommended:** Sol / 高推理

**Files:**
- Create: `apps/quant-web/src/utils/klineViewModel.ts`
- Create: `apps/quant-web/src/components/kline/KlineHoverLegend.vue`
- Create: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify only if needed: `apps/quant-web/src/styles/chartTheme.ts`, `apps/quant-web/src/styles/tokens.css`

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

`KlineChart` must keep exposed methods：

```text
replaceBars(bars, preserveViewport?)
prependBars(bars)
updateBar(bar)
scrollToLatest()
```

Adds prop `visibleMainIndicators` and emit `crosshair-change(HoverKlineContext | null)`。

- [ ] **Step 1: Write view-model RED tests**

```ts
test('only enabled EMA is derived while MACD is always available', () => {
  const result = buildKlineDerivedData(makeBars(100), ['ema_21'])
  assert.equal(result.ema.ema_10, undefined)
  assert.ok(result.ema.ema_21!.length > 0)
  assert.ok(result.macd.histogram.length > 0)
})
```

Add one test proving OHLCV/OI/EMA/MACD hover context resolves from the same bar timestamp。

- [ ] **Step 2: Run RED**

```bash
pnpm --dir apps/quant-web exec node --test tests/kline-view-model.test.ts
```

- [ ] **Step 3: Implement derived data by reusing existing Web mirror**

Use `calculateEMA()` and `calculateMACD()` from `src/utils/indicators.ts`。Do not duplicate formulas in `klineViewModel.ts`。

- [ ] **Step 4: Convert `KlineChart` to three fixed panes**

Pane assignment：

```text
pane 0 -> Candlestick + EMA overlays
pane 1 -> Volume histogram
pane 2 -> MACD histogram + DIF + DEA
```

Target visual proportion approximately 6/2/2；not user-resizable product configuration。

- [ ] **Step 5: Preserve current chart infrastructure**

Continue using current：

```text
normalizeBarSeries
formatChartTimeInShanghai
formatChartAxisTimeInShanghai
replace/prepend/update
left-edge trigger
viewport preservation
followLatest
```

`replace/prepend` may recompute derived series and `setData()`；Live `updateBar` must not unconditionally `fitContent()`。

- [ ] **Step 6: Add synchronized crosshair legend**

Display only available：

```text
O H L C | Volume | OI | enabled EMA | DIF DEA HIST
```

Missing fields render `—`/unavailable；never 0。

- [ ] **Step 7: Make chart height viewport-based**

```css
.kline-shell {
  min-height: 680px;
  height: clamp(680px, 74vh, 1040px);
}
.chart { width: 100%; height: 100%; }
```

Fullscreen uses the available viewport；do not implement layout drag/resize。

- [ ] **Step 8: Run complete chart regression**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add \
  apps/quant-web/src/utils/klineViewModel.ts \
  apps/quant-web/src/components/kline/KlineHoverLegend.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/kline-view-model.test.ts
git add apps/quant-web/src/styles/chartTheme.ts apps/quant-web/src/styles/tokens.css 2>/dev/null || true
git commit -m "feat(web): add three-pane market chart"
```

Before commit, unstage any theme/token file that did not actually change。

---

### Task 4: Product Research Sidebar and Price/Volume/OI section

**Lane:** Lane 2  
**Recommended:** Terra / 中推理

**Files:**
- Create: `apps/quant-web/src/components/market/PriceVolumeOiPanel.vue`
- Modify: `apps/quant-web/src/components/market/ProductResearchSidebar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Create: `apps/quant-web/e2e/market-research.spec.mjs`

**Frontend API:**

```ts
export function getProductResearch(params: {
  symbol: string
  series_kind: SeriesKind
  contract?: string
}): Promise<ProductResearchResponse>
```

- [ ] **Step 1: Add Product Research TypeScript DTO/API**

Keep nullable backend values nullable；convert Decimal JSON to number only at this display boundary。

- [ ] **Step 2: Write E2E RED expectations**

Mock `/api/v1/market/research/product` and assert：

```text
>=1600px -> permanent research sidebar visible
1599px -> sidebar not permanent, 研究 drawer entry visible
daily/weekly trend + position + volume ratio + OI + dominant context visible
missing OI -> unavailable, not 0%
research endpoint failure -> Kline remains visible and usable
```

- [ ] **Step 3: Run RED**

```bash
pnpm --dir apps/quant-web test:e2e -- market-research.spec.mjs
```

- [ ] **Step 4: Bind one snapshot to current identity**

On symbol/series/contract change request exactly one Product Research snapshot。Use generation/abort protection so old symbol responses cannot leak into the new page。Research error must remain separate from the Kline `error` state。

- [ ] **Step 5: Implement the three-block sidebar**

```text
趋势/位置
量与持仓
合约/Runtime上下文
```

Runtime state/phase comes from existing `marketState`，not Research API。

- [ ] **Step 6: Implement `PriceVolumeOiPanel`**

Use `recent_daily` from the same response：normalized close line + normalized OI line + compact volume bars。If OI is unavailable，render price/volume and show `OI 暂无可用数据`。

- [ ] **Step 7: Run regression**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-research.spec.mjs
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

- [ ] **Step 8: Commit**

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

### Task 5: Full-universe Market Radar backend

**Lane:** Lane 2  
**Recommended:** Sol / 高推理

**Files:**
- Create: `services/quant-api/app/market_data/market_radar.py`
- Modify: `services/quant-api/app/market_data/composition.py`
- Modify: `services/quant-api/app/schemas/market.py`
- Modify: `services/quant-api/app/api/market.py`
- Create: `services/quant-api/tests/data_foundation/test_market_radar.py`
- Modify: `services/quant-api/tests/data_foundation/test_market_api.py`

**Existing dependencies to reuse unchanged:**

```text
load_active_products()              # already validates active 60
load_product_taxonomy()             # already validates exact 60 taxonomy
DatabaseCoverageSource.latest_complete_day()
MarketDataService.query_page()
research_metrics.py
```

**Frozen thresholds:**

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

**Response minimum:**

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
sector_summary[]
```

**Reason codes:**

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

- [ ] **Step 1: Write Radar RED tests**

Use fake MarketData reader + fake complete-day reader。Cover：

```text
expected_as_of=2026-08-11 and all 60 current -> ready / 60
one latest day stale -> degraded / 59 + stale symbol
one known MarketDataError -> degraded + unavailable; other symbols continue
unexpected RuntimeError -> propagates
attention does not lower threshold to fill 10
attention order is deterministic
sector totals match taxonomy and active 60
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_radar.py
```

- [ ] **Step 3: Implement `expected_as_of` from current complete-day semantics**

Composition builds the existing `DatabaseCoverageSource` and injects it into Radar。Do not call `datetime.now().date()` in Radar logic。

- [ ] **Step 4: Read active 60 through MarketDataService**

For every active symbol：

```text
series_kind = actual_dominant
frequency = 1d
limit = 300
```

A symbol participates only when latest `trading_day == expected_as_of`。Reuse shared metric calculation from Task 1；do not duplicate EMA/ATR/volume formulas。

- [ ] **Step 5: Implement attention and stable sort**

Candidate requires at least 2 frozen reasons。Sort：

```text
reason_count DESC
abs(price_change_1d) DESC
turnover DESC (None last)
symbol ASC
```

Return at most 10。

- [ ] **Step 6: Implement sector summary from existing taxonomy**

For each sector return：

```text
sector
total_count
participant_count
up_count
down_count
median_price_change_1d
attention_count
```

`total_count` comes from taxonomy/active 60；`participant_count` comes from current Radar participants。No DB taxonomy table and no symbol inference。

- [ ] **Step 7: Add endpoint**

```text
GET /api/v1/market/research/radar
```

No request body，no provider call，no mutation。

- [ ] **Step 8: Run targeted and full backend verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_market_research.py \
  services/quant-api/tests/data_foundation/test_market_radar.py \
  services/quant-api/tests/data_foundation/test_market_api.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data/research_metrics.py \
  services/quant-api/app/market_data/market_research_service.py \
  services/quant-api/app/market_data/market_radar.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests

git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add \
  services/quant-api/app/market_data/market_radar.py \
  services/quant-api/app/market_data/composition.py \
  services/quant-api/app/schemas/market.py \
  services/quant-api/app/api/market.py \
  services/quant-api/tests/data_foundation/test_market_radar.py \
  services/quant-api/tests/data_foundation/test_market_api.py
git commit -m "feat(market): add full-universe research radar"
```

---

### Task 6: Market Radar Web

**Lane:** Lane 2  
**Recommended:** Terra / 中推理

**Files:**
- Create: `apps/quant-web/src/components/market/MarketSummaryStrip.vue`
- Create: `apps/quant-web/src/components/market/MarketScatter.vue`
- Create: `apps/quant-web/src/components/market/MarketAttentionList.vue`
- Create: `apps/quant-web/src/components/market/MarketSectorSummary.vue`
- Create: `apps/quant-web/src/components/market/MarketDetailTable.vue`
- Create: `apps/quant-web/e2e/market-radar.spec.mjs`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/types/market.ts`
- Modify: `apps/quant-web/src/api/market.ts`
- Modify: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`
- Reuse unchanged: `apps/quant-web/src/utils/productDirectory.ts`

- [ ] **Step 1: Add Radar TypeScript DTO/API**

```ts
export function getMarketRadar() {
  return request.get<never, MarketRadarResponse>('/market/research/radar')
}
```

Preserve `status`、`expected_as_of`、stale/unavailable and nullable metrics exactly。

- [ ] **Step 2: Write Radar E2E RED tests**

Mock both：

```text
ready: active=60 participant=60
degraded: active=60 participant=59 + one stale
```

Assert：

```text
expected_as_of visible
ready shows 60/60
degraded shows 59/60 + warning
scatter click routes directly to /market/chart
attention reason tags visible
no composite score
sector summary uses existing productDirectory labels
attention and 自选 are distinct
```

- [ ] **Step 3: Run RED**

```bash
pnpm --dir apps/quant-web test:e2e -- market-radar.spec.mjs
```

- [ ] **Step 4: Implement Summary + SVG Scatter**

Summary only：

```text
上涨 | 下跌 | 放量 | 明显增仓 | 高波动 | 数据日期/60状态
```

Scatter：X=1D return，Y=OI 1D；missing OI items remain in table but are omitted from scatter。Bubble radius uses bounded log turnover 6–18px。Hover only shows symbol/name、1D、OI、volume ratio、ATR percentile。

- [ ] **Step 5: Implement Attention + Sector Summary**

Attention only translates backend reasons。Sector component consumes backend sector summary and uses existing `PRODUCT_SECTORS` labels；do not copy symbol mapping into Web。

- [ ] **Step 6: Implement detail table and local watchlist filter**

Columns：

```text
品种 | 板块 | 1D | 5D | 量比 | OI变化 | ATR分位 | 20日位置 | 状态
```

Support `全部 / 自选` and sector filtering。Click opens `actual_dominant` Product Workspace；use stored valid period else 15m。

- [ ] **Step 7: Run Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-radar.spec.mjs
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add \
  apps/quant-web/src/components/market/MarketSummaryStrip.vue \
  apps/quant-web/src/components/market/MarketScatter.vue \
  apps/quant-web/src/components/market/MarketAttentionList.vue \
  apps/quant-web/src/components/market/MarketSectorSummary.vue \
  apps/quant-web/src/components/market/MarketDetailTable.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/types/market.ts \
  apps/quant-web/src/api/market.ts \
  apps/quant-web/src/utils/marketWorkspacePreferences.ts \
  apps/quant-web/e2e/market-radar.spec.mjs
git commit -m "feat(web): add market research radar"
```

---

### Task 7: HTDY original observation overlay

**Lane:** Lane 2  
**Recommended:** Sol / 高推理 + 独立 Review

**Files:**
- Modify: `apps/quant-web/src/utils/klineViewModel.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/tests/kline-view-model.test.ts`
- Modify: `apps/quant-web/tests/indicators.test.ts`

- [ ] **Step 1: Freeze risk assertions before rendering**

Tests must assert current definition remains：

```text
defaultVisible=false
capability=observation_overlay
repaintingRisk=known
unstableTailBars=27
alertCapable=false
```

- [ ] **Step 2: Run baseline indicator tests**

```bash
pnpm --dir apps/quant-web test:indicators
pnpm --dir apps/quant-web exec node --test tests/kline-view-model.test.ts
```

- [ ] **Step 3: Render only from existing HTDY Web mirror**

Call current `calculateHuoTianDaYou()`；do not change formula、quant-core or Registry。Render `zk1/zd1/zd2` as light overlay and existing observations as：

```text
买观察
卖观察
XG观察
```

Do not implement pixel-exact Tongdaxin STICKLINE engine in P0。

- [ ] **Step 4: Keep risk notice visible**

When enabled, normal/fullscreen UI always shows：

```text
火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察
```

- [ ] **Step 5: Verify no capability/runtime change**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web build
git diff --check
```

Diff review must confirm no quant-core Registry capability、Runtime、DB、Signal/Review surface change。

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

### Task 8: P0 integration review and real-use Gate

**Lane:** Lane 2 integration review  
**Recommended:** Sol / 高推理 / 新独立 Review 会话 / Plan-only review

**Files:**
- Modify only when facts changed: `STATUS.md`
- Modify only when validation commands changed: `TESTING.md`
- Modify design/plan only if implementation semantics changed and the change is approved。

- [ ] **Step 1: Review final diff against hard boundaries**

Verify exactly：

```text
MarketDataService still owns all historical bars
Research services are read-only
useMarketSeries still owns Historical/Live seam
active=60 and operational=60 unchanged
no new provider passthrough
no DB migration/table
no new scheduler/history writer
no main/tag/release
no Runtime switch in implementation tasks
no trading-advice wording
no P1 member/warehouse/roll-yield scope
HTDY capability unchanged
```

- [ ] **Step 2: Run current project-native engineering checks**

```bash
python3 scripts/engineering/secret_scan.py --json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
git diff --check
```

- [ ] **Step 3: Run complete backend verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py
```

Acceptance is the actual output of the current command；do not carry forward old Mypy-baseline exemptions from earlier plans。

- [ ] **Step 4: Run complete Web verification**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e -- market-runtime.spec.mjs
pnpm --dir apps/quant-web test:e2e -- market-research.spec.mjs
pnpm --dir apps/quant-web test:e2e -- market-radar.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 5: Validate active specs**

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
git diff --check
git status --short
```

- [ ] **Step 6: Resolve current independent Runtime deployment status before real integrated acceptance**

Read `STATUS.md`。If the current release-sealing commit recorded there, including the Calendar-first after-market
fix, is still not deployed, stop the real Runtime acceptance and report：

```text
P0 code verification complete
Runtime-integrated acceptance blocked on separate Runtime switch Gate
```

Do **not** perform the switch without a fresh user request。

Do not treat the earlier `51e84988...` switch as evidence that the newer sealing fix is deployed. If `STATUS.md`
records the exact current sealing commit switch/readback complete，run only the allowed read-only smoke required by
the current project contract。

- [ ] **Step 7: Update exact status wording**

Only after Step 2～6 evidence exists，record bounded facts such as：

```text
Market Research Workspace P0 code/tests complete
Radar reports 60/60 or explicit degraded freshness
Runtime scope remains active=60 / operational=60
no P1 or trading capability enabled
```

Do not infer profitability、strategy validity or release readiness。

- [ ] **Step 8: Real-use Gate before P1**

Use P0 during normal research sessions and review only：

```text
Radar 是否减少找品种时间
attention 是否噪声过多
Sector Summary 是否有帮助
Kline 第一屏是否足够完整
右栏是否过载
切换 period/series 是否足够快
页面首屏是否足够快
```

This is a product-use Gate，not a profitability Gate。

- [ ] **Step 9: Commit closure docs only if changed**

```bash
git add STATUS.md TESTING.md \
  docs/superpowers/specs/2026-08-11-market-research-workspace-post-foundation-design.md \
  docs/superpowers/plans/2026-08-11-market-research-workspace-post-foundation-p0.md
git diff --cached --quiet || git commit -m "docs: close market research workspace P0"
```

Only stage files that actually changed。

---

## Codex Dispatch Order

```text
Task 1  Shared metrics + Product Research Service    Sol / high
Task 2  Product Workspace shell                     Terra / medium
Task 3  Three-pane Kline Core                       Sol / high
Task 4  Product Research UI                         Terra / medium
Task 5  Full-universe Radar backend                 Sol / high
Task 6  Market Radar Web                            Terra / medium
Task 7  HTDY observation                            Sol / high + independent review
Task 8  Final integration review                    Sol / high / Plan-only review
```

Default task flow：

```text
develop
-> new task branch/worktree
-> one Codex App session
-> Plan-then-execute
-> TDD + task verification
-> integrate to develop
-> confirm integrated commit
-> clean task worktree/merged branch
```

PR is optional unless the repository rules at execution time or the user explicitly require one。

Every task forbids：

```text
main/tag/release
Runtime switch/promotion
production DB/Canonical mutation
manual RQData maintenance
scope expansion into P1
```

---

## Removed from the old plan after final rebase

The following old assumptions are explicitly retired：

```text
partial 4/60 or 37/60 as the primary Radar mode
separate Lane-3 Daily 60 freshness scheduler
operational subset assumed to remain j/jm/ap/ag
creating load_active_products() in the Radar task
creating product_sectors.csv in P0
npm-based Web commands
old Mypy baseline exemptions
```

Current facts come from `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/DATA_CENTER.md`、`docs/INDICATOR_KERNEL.md`、`openspec/specs/` and the current implementation。
