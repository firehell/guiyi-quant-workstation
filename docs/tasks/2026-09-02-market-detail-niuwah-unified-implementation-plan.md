# Market 统一牛哇式详情页 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 `/market/chart` 现有能力连续可用、并严格隔离四个事实权威的前提下，实现统一牛哇式详情页外壳，以及趋势策略、火天大有、新苏冰、自由看盘四个互斥分析视角。

**Architecture:** 采用“共享 Shell + 独立 Workspace + 分阶段切换”。共享层只负责路由、品种身份、行情头、渐进式披露、公共抽屉和错误边界；每个 Workspace 独立拥有允许的数据身份、图层、摘要、历史和控制。实施期保留当前详情页为显式过渡入口；只有四个 Workspace 全部通过验收且 Newow 只读 API 已进入 `develop` 后，才将缺省入口切换到 Trend，并删除旧 Toolbar/Sidebar 和临时兼容页。

**Tech Stack:** Vue 3.5、TypeScript 6、Vue Router 5、Naive UI 2.44、Lightweight Charts 5.2、Node `node:test`、Playwright、Vite 8、现有 FastAPI/Market/Alert typed API。

**Spec:** `docs/tasks/2026-09-02-market-detail-niuwah-unified-spec.md`

## Global Constraints

- 用户已批准上述 Spec；本计划是详情页唯一新的实施顺序，不恢复“当前版本 / 牛哇版本”双页面。
- 四个视角固定为 `trend | htdy | subing | free`；任一时刻只有一个 Workspace 可以控制主图、Marker、摘要和历史。
- Trend 固定 `actual_dominant + completed 1d`；SuBing 固定 `actual_dominant + completed 15m`；HTDY 和 Free 只接受能力矩阵中的合法序列与周期。
- Newow 正式结果只能来自 Newow Engine/只读 API；SuBing 正式 `S↑ / S↓` 只能来自 `AlertEvent`；HTDY 原始观察与不可变首次识别 Event 必须分开。
- 不输出综合分、胜率、四视角投票、仓位建议、目标价、止损价、自动交易或账户语义。
- 继续采用中国期货红涨绿跌语义，并同时提供文字、形状或箭头；不得只依赖颜色。
- **图标参考 Gate：** 开发导航、操作、状态、警示、展开、图表控制或 Marker 图标前，必须先对照用户提供的牛哇详情页截图或当时可访问的牛哇页面。牛哇使用图标的位置要优先评估图标化；牛哇使用文字的位置不得无依据强行改成图标。
- 图标只能 clean-room 重绘为项目自有 inline SVG/CSS；不得复制牛哇 Logo、品牌图形、私有 SVG/CSS、截图切片或外部字体。
- 视角 Tab 和核心业务状态必须文字优先。图标只能辅助，不能替代“趋势策略、火天大有、新苏冰、自由看盘、建仓、持有、清仓、空仓、预警”等关键语义。
- icon-only 按钮必须有中文 `aria-label`；装饰图标必须 `aria-hidden=true`；移动端点击目标不得小于 44×44 CSS px。
- 每个视觉 Slice 的 PR 必须附“牛哇参考位置 → 本项目处理 → 是否保留文字 → 无障碍标签”的图标审计表，并提供本项目对应截图。
- 不建立通用图标平台、通用策略插件平台、服务端偏好、数据库表、Redis key、队列或 Worker。
- Alert Scope 控制属于 Lane 3 可信写入口；其代码必须独立 Plan Gate、独立 Review。测试只允许 fake/route intercept，不能调用真实 Scope。
- 本计划不授权 production PostgreSQL/Redis/Scope、真实通知、Runtime、RQData、Canonical、`main`、tag 或 Release 操作。
- 每个源码 Slice 从执行时最新、clean 的 `origin/develop` 创建独立 task branch/worktree；不得从本 docs 分支直接开发源码。
- 每个源码 Slice必须先 Draft PR、测试、自审和独立 Review，再由用户明确给出“允许集成 develop”。
- 集成 `develop` 不等于 release、main、tag、Runtime promotion 或任何生产写入。

---

## 0. 规划基线与串行依赖

本计划成稿时观察到：

```text
最新 develop：8dea6d23cf714fa84b03a51bddcf4da7c23fabd8
文档分支 Spec commit：6c7f571baee442205dd23acb74bd539ec16a6b6c
当前 release：v1.9.12
production Runtime：degraded，不能标记 RUNTIME_READY
Newow：Slice A 已存在；杯柄、统一 Engine、只读 API 仍按独立 Newow 计划推进
SuBing：API/Web/Event 基础已进入 develop；production Gate 与 Runtime 事实仍独立
```

以上仅是规划快照。执行每个 Slice 前必须重新读取：

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
TESTING.md
本 Spec
本 Plan
执行时相关 Issue / PR / OpenSpec
```

若执行时 canonical、Newow API、Alert API 或当前代码与本计划冲突，停止并以 active canonical fail-closed，不得凭本计划猜测。

严格串行：

```text
Slice A：route、preferences、icon contract、shared shell
→ 独立 Review → 用户允许集成 develop
Slice B1：Free Workspace
→ 独立 Review → 用户允许集成 develop
Slice B2：HTDY Workspace
→ 独立 Review → 用户允许集成 develop
Slice B3：Alert Scope Control（Lane 3）
→ Plan 批准 → 独立 Review → 用户允许集成 develop
Slice C：SuBing Workspace
→ 独立 Review → 用户允许集成 develop
Newow 上游 Slice B/C + 只读 API 已进入 develop
→ Slice D：Trend Workspace
→ 独立 Review → 用户允许集成 develop
Slice E：final cutover、旧页删除、视觉/图标/无障碍/canonical
→ 独立 Review → 用户视觉批准 → 用户允许集成 develop
```

不允许并行从旧 base 开发相互依赖的 Slice。

---

## 1. Codex 调度矩阵

| Slice | Lane | 模型 | 推理 | Plan | 会话与工作区 | 人工 Gate |
|---|---|---|---|---|---|---|
| A | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；最新 `develop` → `feature/market-detail-shell` worktree | 独立 Review + 允许集成 develop |
| B1 | Lane 2 | Terra | 中 | Plan-then-execute | 新会话；最新 `develop` → `feature/market-detail-free` | 独立 Review + 允许集成 develop |
| B2 | Lane 2 | Terra | 中 | Plan-then-execute | 新会话；最新 `develop` → `feature/market-detail-htdy` | 独立 Review + 允许集成 develop |
| B3 | Lane 3 | Sol | 高 | Plan-only；批准后再实现 | 新会话；最新 `develop` → `feature/market-detail-alert-control` | Plan 批准 + 独立 Review + 允许集成 develop；真实写入另行批准 |
| C | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；最新 `develop` → `feature/market-detail-subing` | 独立 Review + 允许集成 develop |
| D | Lane 2（只读 Web） | Sol | 高 | Plan-then-execute | Newow API Gate 后新会话；`feature/market-detail-trend` | 上游合同确认 + 独立 Review + 允许集成 develop |
| E | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；最新 `develop` → `feature/market-detail-cutover` | 独立 Review + 用户视觉批准 + 允许集成 develop |

Worktree 规则：

- 完成后只集成回 `develop`；
- 不允许自动触及 `main`、tag、Release 或 Runtime；
- PR 合入且确认 commit 已进入 `develop` 后，才清理临时 worktree 和已合并 branch；
- 分支 behind 或出现同文件并行改动时，先更新并重新运行完整 Slice 验证，旧测试结论不得复用。

---

## 2. 最终代码职责

### 2.1 共享合同与控制层

```text
apps/quant-web/src/pages/market/chart.vue
  最终只挂载 MarketDetailPage；实施期暂时选择旧页/新页

apps/quant-web/src/pages/market/LegacyMarketChart.vue
  临时承载当前 chart.vue；Slice E 删除

apps/quant-web/src/pages/market/MarketDetailPage.vue
  shared shell、route orchestration、workspace mounting、error boundary

apps/quant-web/src/types/marketDetail.ts
  view、identity、view restore、header、fact、disclosure、history、icon 类型

apps/quant-web/src/utils/marketDetailRoute.ts
  route parser/serializer、fixed identity、view switch、focus contract

apps/quant-web/src/utils/marketDetailPreferences.ts
  v1 偏好、视角隔离、v9 只迁移到 Free

apps/quant-web/src/utils/marketDetailIcons.ts
  项目自有图标注册表、中文语义和使用角色

apps/quant-web/src/utils/marketDetailViewModel.ts
  header/shared facts；不计算策略

apps/quant-web/src/utils/marketDetailMarkers.ts
  视角 Marker 白名单和稳定点击 identity

apps/quant-web/src/composables/useMarketDetailController.ts
  identity、generation、Market series、metadata/research/runtime/alert 协调
```

### 2.2 共享表现组件

```text
apps/quant-web/src/components/market/detail/
├── MarketDetailIcon.vue
├── MarketDetailTopBar.vue
├── MarketDetailQuoteHeader.vue
├── MarketFactsDisclosure.vue
├── MarketDetailViewNav.vue
├── MarketDetailFactStrip.vue
├── MarketDetailInsightDeck.vue
├── MarketDetailDisclosure.vue
├── MarketDetailSectionTabs.vue
├── MarketDetailDrawer.vue
├── MarketDetailUnavailable.vue
└── MarketKlineStage.vue
```

### 2.3 Workspace

```text
apps/quant-web/src/components/market/detail/free/
├── FreeChartWorkspace.vue
└── FreeChartStage.vue

apps/quant-web/src/components/market/detail/htdy/
├── HtdyDetailWorkspace.vue
└── HtdyChartStage.vue

apps/quant-web/src/components/market/detail/subing/
├── SubingDetailWorkspace.vue
└── SubingChartStage.vue

apps/quant-web/src/components/market/detail/trend/
├── TrendDetailWorkspace.vue
└── NewowTrendChartStage.vue
```

视角 ViewModel：

```text
apps/quant-web/src/utils/freeDetailViewModel.ts
apps/quant-web/src/utils/htdyDetailViewModel.ts
apps/quant-web/src/utils/subingDetailViewModel.ts
apps/quant-web/src/utils/trendDetailViewModel.ts
```

Newow Web 边界只在上游 API Gate 后创建：

```text
apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/utils/newowTypes.ts
```

不得为了目录整齐创建空文件。每个文件只在首个真实消费者任务中创建。

---

# Slice A — Route、Preferences、Icon Contract、Shared Shell

## Task 1: 冻结统一详情路由与固定身份

**Files:**
- Create: `apps/quant-web/src/types/marketDetail.ts`
- Create: `apps/quant-web/src/utils/marketDetailRoute.ts`
- Create: `apps/quant-web/tests/marketDetailRoute.test.ts`
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/tests/marketHomeRoute.test.ts`

**Interfaces:**

```ts
export const MARKET_DETAIL_VIEWS = ['trend', 'htdy', 'subing', 'free'] as const
export type MarketDetailView = (typeof MARKET_DETAIL_VIEWS)[number]

export interface FlexibleViewRestore {
  seriesKind: Extract<SeriesKind, 'actual_dominant' | 'continuous'>
  frequency: MarketFrequency
}

export interface MarketDetailViewRestore {
  htdy: FlexibleViewRestore
  free: FlexibleViewRestore
}

export interface MarketDetailIdentity {
  view: MarketDetailView
  symbol: string
  seriesKind: SeriesKind
  contract?: string
  frequency: MarketFrequency
  focusBarEnd?: string
}

export type MarketDetailRouteResult =
  | { kind: 'missing-view'; symbol: string | null }
  | { kind: 'invalid'; code: MarketDetailRouteErrorCode; recovery: MarketDetailIdentity | null }
  | { kind: 'valid'; identity: MarketDetailIdentity }

export function parseMarketDetailRoute(query: Record<string, unknown>): MarketDetailRouteResult
export function serializeMarketDetailIdentity(identity: MarketDetailIdentity): Record<string, string | undefined>
export function resolveViewSwitchIdentity(
  view: MarketDetailView,
  symbol: string,
  previous: MarketDetailIdentity | null,
  restore: MarketDetailViewRestore,
): MarketDetailIdentity
export function marketDetailEventIdentity(event: AlertEvent): MarketDetailIdentity
```

`missing-view` 只服务实施期旧页面兼容；Slice E 才将缺省入口解释为 Trend。`invalid` 不自动改 URL，只提供显式恢复按钮的目标 identity。

- [ ] **Step 1: 写四视角合法/非法身份测试**

```ts
test('trend only accepts actual dominant D1', () => {
  assert.equal(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', series_kind: 'actual_dominant', frequency: '1d',
  }).kind, 'valid')
  assert.equal(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m',
  }).kind, 'invalid')
})

test('subing only accepts actual dominant 15m', () => {
  assert.equal(parseMarketDetailRoute({
    view: 'subing', symbol: 'jm', series_kind: 'continuous', frequency: '15m',
  }).kind, 'invalid')
})
```

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailRoute.test.ts
```

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现错误码和 parser/serializer**

```ts
export type MarketDetailRouteErrorCode =
  | 'DETAIL_VIEW_UNKNOWN'
  | 'DETAIL_SYMBOL_INVALID'
  | 'DETAIL_TREND_IDENTITY_INVALID'
  | 'DETAIL_SUBING_IDENTITY_INVALID'
  | 'DETAIL_SERIES_KIND_INVALID'
  | 'DETAIL_FREQUENCY_INVALID'
  | 'DETAIL_CONTRACT_REQUIRED'
  | 'DETAIL_FOCUS_INVALID'
```

焦点规则：

```text
HTDY：actual_dominant 且任一正式周期可带 focus_bar_end
SuBing：actual_dominant + 15m 可带 focus_bar_end
Trend：V1 不接受公开 focus_bar_end
Free：V1 不接受公开 focus_bar_end
```

时间必须为 timezone-aware ISO instant，非法日历日期拒绝。

- [ ] **Step 4: 写事件深链测试**

```ts
test('events enter their exact view and bar', () => {
  assert.deepEqual(marketDetailEventIdentity(htdyEvent), {
    view: 'htdy', symbol: 'jm', seriesKind: 'actual_dominant',
    frequency: '30m', focusBarEnd: htdyEvent.bar_end,
  })
  assert.deepEqual(marketDetailEventIdentity(subingEvent), {
    view: 'subing', symbol: 'jm', seriesKind: 'actual_dominant',
    frequency: '15m', focusBarEnd: subingEvent.bar_end,
  })
})
```

- [ ] **Step 5: 增加新的 Home route helper，但不切换当前首页**

```ts
export function marketHomeUnifiedProductChartQuery(symbol: string) {
  return serializeMarketDetailIdentity({
    view: 'trend', symbol, seriesKind: 'actual_dominant', frequency: '1d',
  })
}

export function marketHomeUnifiedEventChartQuery(event: AlertEvent) {
  return serializeMarketDetailIdentity(marketDetailEventIdentity(event))
}
```

保留现有导出直到 Slice E 原子切换，避免首页进入未完成 Trend。

- [ ] **Step 6: 运行定向测试**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailRoute.test.ts \
  tests/marketHomeRoute.test.ts \
  tests/marketChartEntry.test.ts
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add \
  apps/quant-web/src/types/marketDetail.ts \
  apps/quant-web/src/utils/marketDetailRoute.ts \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/tests/marketDetailRoute.test.ts \
  apps/quant-web/tests/marketHomeRoute.test.ts

git commit -m "feat(web): define market detail route identities"
```

---

## Task 2: 实现四视角偏好隔离和 v9 单向迁移

**Files:**
- Create: `apps/quant-web/src/utils/marketDetailPreferences.ts`
- Create: `apps/quant-web/tests/marketDetailPreferences.test.ts`
- Read: `apps/quant-web/src/utils/mainIndicators.ts`
- Read: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`

**Interfaces:**

```ts
export const MARKET_DETAIL_PREFERENCES_KEY = 'guiyi.market.detail.preferences.v1'

export interface FlexibleDetailPreferences extends FlexibleViewRestore {
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
}

export interface MarketDetailPreferences {
  version: 1
  lastView: MarketDetailView
  htdy: FlexibleDetailPreferences
  free: FlexibleDetailPreferences
}

export function defaultMarketDetailPreferences(): MarketDetailPreferences
export function loadMarketDetailPreferences(storage?: DetailPreferenceStorage | null): MarketDetailPreferences
export function saveMarketDetailPreferences(value: MarketDetailPreferences, storage?: DetailPreferenceStorage | null): void
```

Trend 和 SuBing 不保存周期、序列或指标设置。旧 v9 只迁移 `period / optionalEmaIndicators / showRangeDetector` 到 Free；旧 `selectedOverlay=htdy` 不得改变 `lastView='trend'`。实施期不删除旧 key。

- [ ] **Step 1: 写损坏存储和缺省测试**

```ts
test('corrupt storage fails closed', () => {
  const storage = memoryStorage({
    'guiyi.market.detail.preferences.v1': '{broken',
  })
  assert.deepEqual(loadMarketDetailPreferences(storage), defaultMarketDetailPreferences())
})
```

- [ ] **Step 2: 写 v9 只迁移到 Free 的测试**

```ts
test('legacy v9 migrates generic settings to free only', () => {
  const storage = memoryStorage({
    'guiyi.market.chart.preferences.v9': JSON.stringify({
      version: 9,
      selectedOverlay: 'htdy',
      optionalEmaIndicators: ['ema_21'],
      showRangeDetector: true,
      period: '60m',
    }),
  })
  const result = loadMarketDetailPreferences(storage)
  assert.equal(result.lastView, 'trend')
  assert.equal(result.free.frequency, '60m')
  assert.deepEqual(result.free.optionalEmaIndicators, ['ema_21'])
  assert.equal(result.free.showRangeDetector, true)
  assert.deepEqual(result.htdy, defaultMarketDetailPreferences().htdy)
})
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailPreferences.test.ts
```

- [ ] **Step 4: 实现严格 normalizer**

固定缺省：

```ts
{
  version: 1,
  lastView: 'trend',
  htdy: {
    seriesKind: 'actual_dominant', frequency: '15m',
    optionalEmaIndicators: [], showRangeDetector: false,
  },
  free: {
    seriesKind: 'actual_dominant', frequency: '15m',
    optionalEmaIndicators: [], showRangeDetector: false,
  },
}
```

`contract` 不持久化，避免跨品种沿用指定合约。

- [ ] **Step 5: 运行验证**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailPreferences.test.ts \
  tests/mainIndicators.test.ts \
  tests/market-workspace-preferences.test.ts
```

- [ ] **Step 6: 提交**

```bash
git add \
  apps/quant-web/src/utils/marketDetailPreferences.ts \
  apps/quant-web/tests/marketDetailPreferences.test.ts

git commit -m "feat(web): isolate market detail preferences"
```

---

## Task 3: 建立牛哇参考驱动的图标合同

**Files:**
- Create: `apps/quant-web/src/utils/marketDetailIcons.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailIcon.vue`
- Create: `apps/quant-web/tests/marketDetailIcons.test.ts`
- Modify: `apps/quant-web/src/styles/tokens.css`
- Reuse: `apps/quant-web/src/components/market/MarketStateIcon.vue`

**Interfaces:**

```ts
export const MARKET_DETAIL_ICON_NAMES = [
  'back', 'chevron-down', 'chevron-right', 'history', 'alert', 'more',
  'fullscreen', 'settings', 'warning', 'info', 'data', 'close',
  'refresh', 'contract-switch',
] as const

export type MarketDetailIconName = (typeof MARKET_DETAIL_ICON_NAMES)[number]

export interface MarketDetailIconDefinition {
  name: MarketDetailIconName
  label: string
  mode: 'stroke' | 'fill'
  paths: readonly string[]
  circles: readonly { cx: number; cy: number; r: number }[]
  referenceRole: 'navigation' | 'action' | 'disclosure' | 'status' | 'chart'
}

export function marketDetailIconDefinition(name: MarketDetailIconName): MarketDetailIconDefinition
```

`MarketDetailIcon.vue`：

```ts
defineProps<{
  name: MarketDetailIconName
  size?: 16 | 18 | 20 | 24
  label?: string
}>()
```

- `label` 存在时图标自身 `role=img`；否则 `aria-hidden=true`。
- action button 的可访问名称由 button 提供，内部 icon 不重复朗读。
- 上涨/下跌/周期同向/中性/不可用继续复用 `MarketStateIcon`，不复制状态圆标。

- [ ] **Step 1: 在任务 PR 中建立图标审计表**

至少记录：

```text
返回 | 牛哇左箭头 | clean-room back | 按钮中文 aria-label
历史 | 牛哇历史/记录入口 | history clock-arrow | 宽屏保留文字
预警 | 牛哇铃铛 | clean-room alert | tooltip + aria-label
更多 | 牛哇三点 | three dots | tooltip + aria-label
展开 | 牛哇小箭头 | chevron | 标题文字始终保留
警示 | 牛哇彩色警示块 | warning triangle | 警示正文始终保留
全屏 | 图表控制 | four corners | tooltip + aria-label
```

视角 Tab 不加装饰图标，除非后续视觉 Review 证明参考位置明确需要，且文字仍保留。

- [ ] **Step 2: 写注册表失败测试**

```ts
test('detail icon registry is finite and labeled', () => {
  assert.equal(new Set(MARKET_DETAIL_ICON_NAMES).size, MARKET_DETAIL_ICON_NAMES.length)
  for (const name of MARKET_DETAIL_ICON_NAMES) {
    const icon = marketDetailIconDefinition(name)
    assert.equal(icon.name, name)
    assert.ok(icon.label.length > 0)
    assert.ok(icon.paths.length + icon.circles.length > 0)
  }
})
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailIcons.test.ts
```

- [ ] **Step 4: 使用以下项目自有 24×24 几何实现完整注册表**

```text
back
  paths: M15.5 5 8.5 12l7 7

chevron-down
  paths: M7 9.5 12 14.5 17 9.5

chevron-right
  paths: M9.5 7 14.5 12 9.5 17

history
  paths: M4 5v5h5 ; M4.7 9.5A8 8 0 1 0 7 5.3 ; M12 8v4l3 2

alert
  paths: M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 ; M10 20h4

more
  circles: (6,12,1.5), (12,12,1.5), (18,12,1.5)

fullscreen
  paths: M8 3H3v5 ; M16 3h5v5 ; M21 16v5h-5 ; M8 21H3v-5

settings
  paths: M4 7h10 ; M18 7h2 ; M4 17h2 ; M10 17h10
  circles: (16,7,2), (8,17,2)

warning
  paths: M12 3 22 20H2Z ; M12 8v5 ; M12 17h.01

info
  paths: M12 10v6 ; M12 7h.01
  circles: (12,12,9)

data
  paths: M4 6c0-2 16-2 16 0s-16 2-16 0 ; M4 6v6c0 2 16 2 16 0V6 ; M4 12v6c0 2 16 2 16 0v-6

close
  paths: M6 6l12 12 ; M18 6 6 18

refresh
  paths: M20 11a8 8 0 1 0-2.3 5.7 ; M20 4v7h-7

contract-switch
  paths: M5 7h12 ; M14 4l3 3-3 3 ; M19 17H7 ; M10 14l-3 3 3 3
```

统一 `viewBox=0 0 24 24`、`stroke-width=1.8`、round cap/join；`more` 使用 fill。不得从牛哇 DOM/SVG 下载路径。

- [ ] **Step 5: 增加详情页语义 token**

```css
--gy-detail-accent: var(--gy-market-icon-aligned);
--gy-detail-accent-soft: var(--gy-market-pill-aligned-soft);
--gy-detail-icon-muted: var(--gy-text-muted);
--gy-detail-card-bg: var(--gy-bg-panel);
--gy-detail-section-bg: var(--gy-gray-50);
--gy-detail-warning-border: color-mix(in srgb, var(--gy-status-warning) 35%, transparent);
```

- [ ] **Step 6: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailIcons.test.ts \
  tests/marketHomeIcons.test.ts
pnpm --dir apps/quant-web build

git add \
  apps/quant-web/src/utils/marketDetailIcons.ts \
  apps/quant-web/src/components/market/detail/MarketDetailIcon.vue \
  apps/quant-web/src/styles/tokens.css \
  apps/quant-web/tests/marketDetailIcons.test.ts

git commit -m "feat(web): add Niuwah-referenced detail icons"
```

---

## Task 4: 定义共享 ViewModel，禁止综合分和跨权威合成

**Files:**
- Modify: `apps/quant-web/src/types/marketDetail.ts`
- Create: `apps/quant-web/src/utils/marketDetailViewModel.ts`
- Create: `apps/quant-web/tests/marketDetailViewModel.test.ts`

**Interfaces:**

```ts
export type MarketDetailSource =
  | 'market'
  | 'newow'
  | 'htdy_display'
  | 'alert_event'
  | 'runtime'
  | 'generic_indicator'

export interface MarketDetailFact {
  id: string
  label: string
  value: string
  tone: 'default' | 'up' | 'down' | 'warning' | 'unavailable'
  source: MarketDetailSource
  icon?: MarketDetailIconName
}

export interface MarketDetailDisclosureRow {
  label: string
  value: string
  source: MarketDetailSource
}

export interface MarketDetailDisclosureSection {
  id: string
  title: string
  summary: string
  updatedAt: string | null
  tone: 'default' | 'warning' | 'unavailable'
  rows: readonly MarketDetailDisclosureRow[]
}

export interface MarketDetailHeaderModel {
  symbol: string
  productName: string
  exchange: string
  sector: string
  seriesKind: SeriesKind
  displayContract: string | null
  asOf: string | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  change: number | null
  pct: number | null
  volume: number | null
  turnover: number | null
  openInterest: number | null
  phase: string
  displaySource: string
  freshness: 'fresh' | 'stale' | 'unavailable'
  extendedSections: readonly MarketDetailDisclosureSection[]
}

export interface DetailViewModel {
  view: MarketDetailView
  identity: MarketDetailIdentity
  asOf: string | null
  semanticBanner: { text: string; tone: 'info' | 'warning' }
  facts: readonly [MarketDetailFact, MarketDetailFact, MarketDetailFact]
  disclosureSections: readonly MarketDetailDisclosureSection[]
  history: readonly MarketDetailHistoryItem[]
  dataStatus: 'ready' | 'stale' | 'unavailable'
}
```

类型中禁止出现 `score`、`confidence`、`positionAdvice`、`targetPrice`。

- [ ] **Step 1: 写共享行情头无综合字段测试**

```ts
test('shared header contains market facts and no synthetic decision fields', () => {
  const model = buildMarketDetailHeaderModel(headerFixture)
  assert.equal('score' in model, false)
  assert.equal('confidence' in model, false)
  assert.equal('positionAdvice' in model, false)
  assert.equal('targetPrice' in model, false)
})
```

视角级“三事实恰好为 3”分别在 Task 7、8、10、13 的 ViewModel 测试中冻结，不让共享层伪造视角事实。

- [ ] **Step 2: 写行情头同身份测试**

覆盖：

```text
latest completed Bar 作为价格
上一 completed Bar 计算 change/pct
actual_dominant 使用 latest Bar.physicalContract
continuous 不伪造 physicalContract
Bars 与 metadata 合约冲突时 freshness=unavailable
旧品种 research 不得合入当前 header
缺少上一 Bar 时 change/pct=null
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailViewModel.test.ts
```

- [ ] **Step 4: 实现纯 builder**

```ts
export function buildMarketDetailHeaderModel(input: {
  identity: MarketDetailIdentity
  dominant: DominantContractItem | null
  bars: readonly BarData[]
  research: ProductResearchResponse | null
  marketState: MarketReadState | null
  overlaySource: MarketOverlaySource
  canonicalCoverage: { start: string; end: string } | null
  hasMoreBefore: boolean
  stale: boolean
}): MarketDetailHeaderModel
```

只允许格式化、选择同身份事实和计算相邻 completed Bar 的价格变化；不得重算策略或趋势。

- [ ] **Step 5: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailViewModel.test.ts

git add \
  apps/quant-web/src/types/marketDetail.ts \
  apps/quant-web/src/utils/marketDetailViewModel.ts \
  apps/quant-web/tests/marketDetailViewModel.test.ts

git commit -m "feat(web): add sourced market detail view models"
```

---

## Task 5: 实现共享表现组件和渐进式披露

**Files:**
- Create: `apps/quant-web/src/components/market/detail/MarketDetailTopBar.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailQuoteHeader.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketFactsDisclosure.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailFactStrip.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailInsightDeck.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailDisclosure.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailSectionTabs.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailUnavailable.vue`

**Component contracts:**

```text
TopBar emits: back / select-symbol / open-history / open-alert / open-more
QuoteHeader consumes: MarketDetailHeaderModel
ViewNav emits: exact MarketDetailIdentity
InsightDeck: desktop multi-open; mobile single-open
Drawer: focus trap + close focus restoration
```

- [ ] **Step 1: 实现 TopBar 的参考图标和显示规则**

```text
返回：icon-only + aria-label
品种/合约：文字 + chevron
历史：宽屏 icon+文字；窄屏 icon-only + aria-label
预警：仅 actions.canManageAlert=true 时渲染
更多：icon-only + menu
```

V1 不显示没有真实功能的收藏星标。

- [ ] **Step 2: 实现 QuoteHeader 和“更多行情数据”**

默认直出：品种、合约、截至时间、close/change/pct、OHLC、volume、OI、状态标签。

`MarketFactsDisclosure`：默认折叠；桌面/移动端原位展开；品种或 identity 变化立即关闭；error/stale 必须在标题可见。

- [ ] **Step 3: 实现 ViewNav**

```text
Trend：固定日K胶囊，无 series control
HTDY：七周期 + series control
SuBing：固定15m胶囊，无 series control
Free：七周期 + series control
```

不支持项不渲染，不能用 disabled 假入口。

- [ ] **Step 4: 实现 FactStrip、InsightDeck 和 Accordion**

- FactStrip 固定三项。
- 第一块默认展开。
- 桌面允许多开；390px 单开。
- 标题始终保留文字，chevron 只辅助。
- 完整 `aria-expanded`、`aria-controls`、Enter/Space。

- [ ] **Step 5: 实现 SectionTabs 和 Drawer**

当前视角无历史时不渲染历史入口。桌面原位展开；移动端底部抽屉。顶部“历史”和底部“历史记录”必须接收同一 `history` prop。

- [ ] **Step 6: 做第一轮牛哇图标/密度 Review**

PR 必须附：顶部操作、策略 Chip、警示条、摘要条、展开箭头、图表控制的参考对照。仓库不提交牛哇截图或品牌资产。

- [ ] **Step 7: build 并提交**

```bash
pnpm --dir apps/quant-web build

git add \
  apps/quant-web/src/components/market/detail/MarketDetailTopBar.vue \
  apps/quant-web/src/components/market/detail/MarketDetailQuoteHeader.vue \
  apps/quant-web/src/components/market/detail/MarketFactsDisclosure.vue \
  apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue \
  apps/quant-web/src/components/market/detail/MarketDetailFactStrip.vue \
  apps/quant-web/src/components/market/detail/MarketDetailInsightDeck.vue \
  apps/quant-web/src/components/market/detail/MarketDetailDisclosure.vue \
  apps/quant-web/src/components/market/detail/MarketDetailSectionTabs.vue \
  apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue \
  apps/quant-web/src/components/market/detail/MarketDetailUnavailable.vue

git commit -m "feat(web): add unified market detail shell primitives"
```

---

## Task 6: 建立新旧页面安全过渡入口

**Files:**
- Create by move: `apps/quant-web/src/pages/market/LegacyMarketChart.vue`
- Create: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Create: `apps/quant-web/src/composables/useMarketDetailController.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Create: `apps/quant-web/tests/marketDetailController.test.ts`
- Create: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create: `apps/quant-web/e2e/market-detail.spec.mjs`
- Regression: `apps/quant-web/e2e/market-research-chart-interaction.spec.mjs`
- Regression: `apps/quant-web/e2e/market-range-detector.spec.mjs`
- Regression: `apps/quant-web/e2e/market-runtime.spec.mjs`

**Interfaces:**

```ts
export interface MarketDetailControllerState {
  route: MarketDetailRouteResult
  identity: MarketDetailIdentity | null
  generation: number
  header: MarketDetailHeaderModel | null
  loading: boolean
  error: string | null
}

export function useMarketDetailController(dependencies?: MarketDetailControllerDependencies): {
  state: Readonly<Ref<MarketDetailControllerState>>
  bars: Readonly<Ref<BarData[]>>
  mutation: Readonly<Ref<MarketSeriesMutation>>
  switchIdentity(identity: MarketDetailIdentity): Promise<void>
  loadMoreBefore(): Promise<void>
  dispose(): void
}
```

临时规则：

```text
无 view：LegacyMarketChart
显式合法且已启用的 view：MarketDetailPage
显式合法但 Workspace 尚未完成：MarketDetailUnavailable + 返回旧页
非法 identity：MarketDetailUnavailable + 显式恢复按钮
```

此过渡在 Slice E 必须全部删除。

- [ ] **Step 1: 机械移动当前 chart.vue**

完整移动到 `LegacyMarketChart.vue`，本步骤不改变行为。`chart.vue` 暂时仍只挂 Legacy。

- [ ] **Step 2: 运行旧页面回归**

```bash
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-research-chart-interaction.spec.mjs \
  e2e/market-range-detector.spec.mjs \
  e2e/market-runtime.spec.mjs
```

- [ ] **Step 3: 写 generation 测试**

```ts
test('late responses cannot overwrite a newer identity', async () => {
  const controller = useMarketDetailController(fakeDependencies())
  void controller.switchIdentity(freeIdentity('jm'))
  void controller.switchIdentity(freeIdentity('rb'))
  await resolveSecondThenFirst()
  assert.equal(controller.state.value.identity?.symbol, 'rb')
})
```

- [ ] **Step 4: 实现 controller，复用 useMarketSeries**

不得复制 WebSocket、分页或 actual-dominant 物理合约解析。controller 只组合 `useMarketSeries`、dominants、research、runtime、alert 和当前 view loader。

- [ ] **Step 5: 接线显式 `view=free` 预览**

本 Slice 只让显式 `view=free` 进入新 Shell；其他 Workspace 显示明确不可用，不把空壳冒充完成。

- [ ] **Step 6: 写并运行结构 E2E**

```js
test('new detail keeps Niuwah vertical order and no sidebar', async ({ page }) => {
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-section]')).toHaveAttribute('data-detail-ready', 'true')
  await expect(page.getByTestId('product-check-sidebar')).toHaveCount(0)
})
```

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailController.test.ts \
  tests/marketSeries.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs
```

- [ ] **Step 7: 提交**

```bash
git add \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/src/pages/market/LegacyMarketChart.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/composables/useMarketDetailController.ts \
  apps/quant-web/tests/marketDetailController.test.ts \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): stage unified detail behind explicit view"
```

### Slice A Gate

必须满足：route 完整、非法 identity fail-closed、v9 只迁移 Free、图标 clean-room、图标审计已附、共享组件可键盘操作、旧页面回归不变、没有默认空 Trend、Web 测试/build/E2E 全绿、独立 Review 无 Critical/Important。

结论只允许：

```text
SLICE_A_READY_FOR_INTEGRATION
SLICE_A_REQUIRES_FIXES
SLICE_A_BLOCKED
```

---

# Slice B1 — Free Workspace

## Task 7: 迁移自由看盘并保留通用能力

**Files:**
- Create: `apps/quant-web/src/utils/freeDetailViewModel.ts`
- Create: `apps/quant-web/tests/freeDetailViewModel.test.ts`
- Create: `apps/quant-web/src/utils/marketDetailMarkers.ts`
- Create: `apps/quant-web/tests/marketDetailMarkers.test.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketKlineStage.vue`
- Create: `apps/quant-web/src/components/market/detail/free/FreeChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/free/FreeChartWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify only if stage interface requires: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

```ts
export function buildFreeDetailViewModel(input: {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  research: ProductResearchResponse | null
  researchError: boolean
  rangeState: 'disabled' | 'loading' | 'ready' | 'insufficient'
}): DetailViewModel

export function markersForDetailView(
  view: MarketDetailView,
  markers: readonly KlineMarker[],
): KlineMarker[]
```

`MarketKlineStage` 只处理 bars/mutation、replace/prepend/live、回到最新、向左加载、全屏和 focus；不决定 view 允许哪些 indicator/marker。

- [ ] **Step 1: 写 Free 三事实和无 Marker 测试**

```ts
test('free exposes identity facts and never strategy markers', () => {
  const model = buildFreeDetailViewModel(fixture)
  assert.deepEqual(model.facts.map((item) => item.label), ['当前序列', '当前周期', '数据状态'])
  assert.equal(model.facts.length, 3)
  assert.equal(model.history.length, 0)
  assert.deepEqual(markersForDetailView('free', allAlertMarkers), [])
})
```

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/freeDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
```

- [ ] **Step 3: 实现 Free ViewModel 和 Workspace**

迁移：

```text
continuous / actual_dominant / contract
七周期
EMA10 / EMA21 / EMA60
Range Detector warm-up
成交量
MACD
research 背景
Canonical coverage / history boundary
```

三块固定为：指标设置（默认展开）、市场背景、数据详情。Range 不可用必须显示原因。不初始化 Alert loader，不显示策略 Marker。

- [ ] **Step 4: 处理图表控制图标**

对照牛哇后仅保留高频图标：全屏、设置；“回到最新”使用 icon+文字且只在离开最新时显示。周期保持文字 Chip。

- [ ] **Step 5: E2E**

覆盖：

```text
Free 无 HTDY/SuBing/Newow Marker
Range warm-up 状态
contract 切换品种后回 actual_dominant 并提示
Free 设置不改变 HTDY
1280×800 Free with Range baseline
```

- [ ] **Step 6: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/freeDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/rangeDetectorOverlayWarmup.test.ts \
  tests/mainIndicators.test.ts \
  tests/kline-view-model.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "Free"

git add \
  apps/quant-web/src/utils/freeDetailViewModel.ts \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/src/components/market/detail/MarketKlineStage.vue \
  apps/quant-web/src/components/market/detail/free/FreeChartStage.vue \
  apps/quant-web/src/components/market/detail/free/FreeChartWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/tests/freeDetailViewModel.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): add free market detail workspace"
```

若 `KlineChart.vue` 没有变化，不加入暂存。

---

# Slice B2 — HTDY Workspace

## Task 8: 实现 HTDY 双事实视角和全周期 Event focus

**Files:**
- Create: `apps/quant-web/src/utils/htdyDetailViewModel.ts`
- Create: `apps/quant-web/tests/htdyDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyDetailWorkspace.vue`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

```ts
export interface PersistentAlertMarkerOptions {
  fetchEvents: typeof getAlertEvents
  resolveRuleCodes?: (identity: AlertMarkerIdentity) => AlertRuleCode[]
}

// composable returns both projections from one internal Map
return {
  markers: Readonly<Ref<KlineMarker[]>>,
  events: Readonly<Ref<AlertEvent[]>>,
  sync,
  dispose,
}

export function buildHtdyDetailViewModel(input: {
  identity: MarketDetailIdentity
  rawObservation: KlineMarker | null
  events: readonly HtdyAlertEvent[]
  alertRules: readonly ProductAlertRuleState[]
  runtimeStatus: AlertRuntimeStatus | null
  alertUnavailable: boolean
}): DetailViewModel
```

HTDY loader 只请求 `[ALERT_RULE_CODES.HTDY]`。

- [ ] **Step 1: 写双事实和降级测试**

```ts
test('raw observation remains separate from immutable event', () => {
  const model = buildHtdyDetailViewModel({
    ...fixture,
    rawObservation: rawBuyObservation,
    events: [savedSellEvent],
  })
  assert.equal(model.facts.length, 3)
  assert.equal(model.facts[0].value, '买观察')
  assert.match(model.facts[1].value, /卖出观察/)
  assert.notEqual(model.facts[0].source, model.facts[1].source)
})
```

另覆盖：Alert API 失败但 raw 可见；display 失败但 Event 可见；Runtime degraded；无 Event 显示暂无而非中性。

- [ ] **Step 2: 扩展 persistent loader**

去重身份保持：`rule_code + symbol + frequency + bar_end`。event list 与 marker list 必须来自同一 Map。

- [ ] **Step 3: 修复 KlineChart 对 D1/W1 focus 的人为限制**

当前 `revealTime()` 对 daily/weekly 直接返回 false。改为按 normalized Bar time 查找并设置逻辑范围，保证 HTDY 的 `1d/1w` Event 深链也能定位。增加：

```text
1m/5m/15m/30m/60m focus
1d focus
1w focus
invalid time no movement
focus 后 followLatest=false
```

- [ ] **Step 4: 实现 HTDY Workspace**

主图白名单：HTDY、可选 EMA、可选 Range、raw HTDY markers、HTDY Event markers。必须排除 SuBing Event。

- [ ] **Step 5: 图标处理**

raw observation 使用轻量形状+文字；Event 使用不同的实心事件徽标/方形；重绘提示使用 warning icon+全文；预警入口使用 alert icon；无控制能力时不显示假铃铛。

- [ ] **Step 6: E2E**

覆盖双事实、同源历史、Alert unavailable、1d/1w exact focus、1440×900 HTDY baseline。

- [ ] **Step 7: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/htdyDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/marketChartEntry.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "HTDY"

git add \
  apps/quant-web/src/utils/htdyDetailViewModel.ts \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/market/detail/htdy/HtdyChartStage.vue \
  apps/quant-web/src/components/market/detail/htdy/HtdyDetailWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/tests/htdyDetailViewModel.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts \
  apps/quant-web/tests/marketChartEntry.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): add HTDY detail workspace"
```

---

# Slice B3 — Alert Scope Control（Lane 3）

## Task 9: 泛化精确 Rule 控制并在失败后读回

**Lane:** Lane 3。先开独立 Sol/高推理会话，Plan-only；没有用户批准不得实现。

**Files:**
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailAlertControl.vue`
- Create: `apps/quant-web/tests/marketDetailAlertControl.test.ts`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Do not modify: backend endpoint、DB、migration、Runtime、notification transport

**Interface:**

```ts
function toggleRuleCurrentFrequency(
  ruleCode: AlertRuleCode,
  enabled: boolean,
): Promise<void>
```

前置校验：Rule 存在、rule_code 在 registry、frequency 属于该 Rule、symbol/frequency 与发起时一致、同 Rule 不并发保存。

失败行为：显示失败；立即重新读取当前 symbol 的服务端 Rule；旧 generation readback 丢弃；不保留乐观开关状态。

- [ ] **Step 1: 输出窄 Lane 3 Plan packet 并等批准**

Packet 必须列出 exact endpoint、request body、fake tests、failure readback、无真实调用、独立 Review。

- [ ] **Step 2: 写失败 readback 测试**

```ts
test('failed exact mutation reads server truth back', async () => {
  const calls: string[] = []
  const scope = useProductAlertScope(fakeDependencies({
    mutate: async () => { calls.push('put'); throw new Error('blocked') },
    fetch: async () => { calls.push('get'); return serverDisabledState },
  }))
  await scope.toggleRuleCurrentFrequency(ALERT_RULE_CODES.SUBING_THS, true)
  assert.deepEqual(calls, ['put', 'get'])
})
```

- [ ] **Step 3: 实现 generic mutation 和 unified control**

组件必须展示 `rule_code + symbol + frequency + server scope/enabled + Runtime status`。不改变后端 authority，不做批量 Scope。

- [ ] **Step 4: E2E 只用 route intercept**

覆盖成功、失败、身份切换中响应、重复点击。不得连接真实 API/DB/Runtime。

- [ ] **Step 5: 验证和独立 Review**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailAlertControl.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "Alert control"
```

Review 必须拒绝：批量 Scope、默认启用、optimistic success、unknown Rule fallback、真实请求证据、token/topic 暴露。

- [ ] **Step 6: 提交并停在 Draft PR**

```bash
git add \
  apps/quant-web/src/composables/useProductAlertScope.ts \
  apps/quant-web/src/components/market/detail/MarketDetailAlertControl.vue \
  apps/quant-web/tests/marketDetailAlertControl.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): control exact alert rule scope"
```

代码进入 `develop` 也不授权真实点击 production 开关。

---

# Slice C — SuBing Workspace

## Task 10: 映射 per-rule Runtime 状态并构造 SuBing ViewModel

**Files:**
- Modify: `apps/quant-web/src/api/runtime.ts`
- Modify: `apps/quant-web/src/api/alerts.ts`
- Create: `apps/quant-web/src/utils/subingDetailViewModel.ts`
- Create: `apps/quant-web/tests/subingDetailViewModel.test.ts`
- Create: `apps/quant-web/tests/runtimeHealthTypes.test.ts`

**Interfaces:**

```ts
export interface RuntimeAlertRuleStatus {
  last_evaluated_bar_at: string | null
  last_event_at: string | null
  last_failure_at: string | null
  error_type: string | null
}

export type RuntimeAlertRuleStatusMap = Record<AlertRuleCode, RuntimeAlertRuleStatus>

export function buildSubingDetailViewModel(input: {
  identity: MarketDetailIdentity
  events: readonly SubingThsAlertEvent[]
  rule: ProductAlertRuleState | null
  runtime: RuntimeAlertHealth | null
  alertUnavailable: boolean
}): DetailViewModel
```

`RuntimeAlertHealth` 增加固定 `rule_status`。normalizer 只接受 HTDY/SuBing 两个 registry key 和固定字段；损坏时该 rule 投影为不可用，不能用全局 heartbeat 冒充已评估。

- [ ] **Step 1: 写 Event-only authority 测试**

```ts
test('no AlertEvent means no synthetic SuBing direction', () => {
  const model = buildSubingDetailViewModel({ ...fixture, events: [] })
  assert.equal(model.facts.length, 3)
  assert.equal(model.facts[0].value, '暂无')
  assert.equal(model.history.length, 0)
  assert.doesNotMatch(JSON.stringify(model), /偏多|偏空|中性/)
})
```

- [ ] **Step 2: 写 per-rule health 测试**

覆盖：全局 heartbeat fresh 但 SuBing `last_evaluated=null`；Rule disabled；Runtime failed；notification attempted/provider accepted/微信送达分离；unknown key 不展示。

- [ ] **Step 3: 实现严格 Runtime 映射和 SuBing ViewModel**

三事实：最新预警、信号 K 线、预警状态。三折叠块：最新预警、触发规则、运行与通知。

触发规则只写：

```text
S↑：MACD 金叉且 Close > EMA21
S↓：MACD 死叉且 Close < EMA21
```

不增加零轴、量能/OI、Range、ATR、周期共振、评分或三根确认。

- [ ] **Step 4: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/runtimeHealthTypes.test.ts
pnpm --dir apps/quant-web test

git add \
  apps/quant-web/src/api/runtime.ts \
  apps/quant-web/src/api/alerts.ts \
  apps/quant-web/src/utils/subingDetailViewModel.ts \
  apps/quant-web/tests/subingDetailViewModel.test.ts \
  apps/quant-web/tests/runtimeHealthTypes.test.ts

git commit -m "feat(web): add SuBing detail facts"
```

---

## Task 11: 实现 SuBing Workspace、历史和 exact Bar 深链

**Files:**
- Create: `apps/quant-web/src/components/market/detail/subing/SubingChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/subing/SubingDetailWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/src/utils/marketDetailMarkers.ts`
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/tests/marketDetailMarkers.test.ts`
- Modify: `apps/quant-web/tests/marketHomeRoute.test.ts`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-home.spec.mjs`

**Marker rule:**

```text
subing → alertRuleCode === SUBING_THS
htdy → raw HTDY + alertRuleCode === HTDY
free → []
trend → only Newow typed markers
```

- [ ] **Step 1: 写 Marker isolation 测试**

```ts
test('subing renders only immutable SuBing event markers', () => {
  assert.deepEqual(
    markersForDetailView('subing', [htdyEventMarker, subingEventMarker, rawHtdyMarker]),
    [subingEventMarker],
  )
})
```

- [ ] **Step 2: 实现固定图层**

只显示 15m Kline、EMA21、S↑/S↓ Event Marker、成交量、MACD。排除 EMA10/60、Range、HTDY、Newow 和本地正式 Marker。

- [ ] **Step 3: 历史和 Marker 点击共用 Event Map**

历史显示方向、bar_end、detected_at、physical contract、notification_attempted_at。点击历史或 Marker 都通过稳定 Event id 打开同一详情抽屉；不得解析 Tooltip 文案获取 identity。

为 `KlineChart` 增加：

```ts
const emit = defineEmits<{
  'marker-select': [marker: KlineMarker]
}>()
```

只解析当前白名单中已渲染的 marker id；未知/过期 id 拒绝。

- [ ] **Step 4: 图标参考**

`S↑` 为上箭头+“多头预警”文字+红色；`S↓` 为下箭头+“空头预警”文字+绿色。历史用 history icon，运行异常用 warning，数据不足复用灰色状态圆标。MACD/EMA21 不加无来源装饰图标。

- [ ] **Step 5: 切换首页 SuBing Event 深链**

只更新 SuBing Event：`view=subing + actual_dominant + 15m + focus_bar_end`。普通品种入口仍等待 Slice E。

- [ ] **Step 6: E2E**

覆盖：首页 Event → exact Bar；focus 消费后移除 query；定位后不跳最新；无 Event 无方向；HTDY Event 不混入；1440 baseline；390 history drawer；Alert unavailable；Runtime degraded。

- [ ] **Step 7: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketHomeRoute.test.ts
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs \
  e2e/market-home.spec.mjs

git add \
  apps/quant-web/src/components/market/detail/subing/SubingChartStage.vue \
  apps/quant-web/src/components/market/detail/subing/SubingDetailWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/tests/marketDetailMarkers.test.ts \
  apps/quant-web/tests/marketHomeRoute.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs \
  apps/quant-web/e2e/market-home.spec.mjs

git commit -m "feat(web): add SuBing detail workspace"
```

---

# Slice D — Trend Workspace（等待 Newow API）

## Task 12: 执行 Newow 上游合同 Gate

**This task is fail-closed and may end without code changes.**

**Read:**
- `docs/tasks/2026-09-01-newow-trend-v1-design.md`
- `docs/tasks/2026-09-01-newow-trend-v1-implementation-plan.md`
- `docs/tasks/2026-09-02-newow-slice-b-cup-handle-engine-design.md`
- 执行时最新 Newow Slice B/C Spec、PR、OpenSpec 和 API 实现
- `packages/quant-core/guiyi_quant/newow/`
- `services/quant-api/app/` 中已进入 `develop` 的 Newow read-only service/API

**Required evidence:**

```text
NewowTrendD1Engine 已进入 develop
cup_handle + engine 因果/restore/rollover 测试通过
actual_dominant completed D1 只读 service 已进入 develop
只读 endpoint/DTO 已冻结
API 不写 DB/Redis，不接 Alert/Runtime
endpoint、request、response、error code 可从代码/OpenSpec 读出
```

- [ ] **Step 1: 执行只读 preflight**

```bash
test -f packages/quant-core/guiyi_quant/newow/engine.py
rg -n "NewowTrendD1Engine|newow_trend_v1" \
  services/quant-api/app \
  services/quant-api/tests \
  openspec/specs \
  docs/tasks
```

- [ ] **Step 2: 记录 exact API contract**

记录 endpoint、query、identity、response schema、marker types、rollover facts、public errors、maximum result/paging contract。

- [ ] **Step 3: 不满足时停止**

只输出 `BLOCKED_NEWOW_READ_API`。不得猜 endpoint，不得在 Web 复制 Newow 公式，不得创建浏览器 fallback。

- [ ] **Step 4: 满足时记录 dependency commit**

在 Slice D PR body 写入 Newow develop commit、API/OpenSpec path、targeted backend evidence，再执行 Task 13。

---

## Task 13: 实现 Newow normalizer、Trend Workspace 和独立主图

**Files:**
- Create: `apps/quant-web/src/types/newow.ts`
- Create: `apps/quant-web/src/api/newow.ts`
- Create: `apps/quant-web/src/utils/newowTypes.ts`
- Create: `apps/quant-web/tests/newowTypes.test.ts`
- Create: `apps/quant-web/src/utils/trendDetailViewModel.ts`
- Create: `apps/quant-web/tests/trendDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/trend/TrendDetailWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`

**Normalized output:**

```ts
export interface NewowTrendDetailModel {
  strategyCode: 'newow_trend_v1'
  profileId: 'newow_trend_d1_v1'
  seriesKind: 'actual_dominant'
  frequency: '1d'
  symbol: string
  asOf: string
  frames: readonly NewowTrendFrameDto[]
  current: NewowTrendFrameDto | null
  contractSegments: readonly ResolvedContractSegment[]
}

export function normalizeNewowTrendDetailResponse(
  payload: unknown,
  expected: { symbol: string },
): NewowTrendDetailModel
```

`getNewowTrendDetail()` 的 URL、参数和 wire 字段逐字采用 Task 12 读出的 accepted API；不得发明第二 endpoint。

- [ ] **Step 1: 写 strict normalizer 测试**

覆盖 exact identity、symbol mismatch、naive timestamp、frame order/duplicate、unknown marker、rollover mismatch、numeric normalization、invalid payload。

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/newowTypes.test.ts
```

- [ ] **Step 3: 实现 API client/normalizer**

Web 不导入或复制 Python formula，不重算黄蓝、D123、杯柄、BUILD/CLEAR。

- [ ] **Step 4: 写并实现 Trend ViewModel**

三事实：趋势状态、D1/D2/D3 风险、杯柄状态；测试断言 `facts.length === 3`。固定提示：`建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。`

不可用时显示不可用，不能根据基础 Kline 猜趋势。

- [ ] **Step 5: 实现独立 NewowTrendChartStage**

层级：Kline/grid → 黄蓝趋势带 → 杯柄轮廓/柄部 → BUILD/CLEAR → D1/D2/D3 → crosshair → 换月分界 → 成交量 pane。

不使用 `ResearchOverlayId`，不把 Newow 加进 `visibleMainIndicatorsForOverlay()`。

- [ ] **Step 6: 实现历史和图标**

历史与图上 Marker 来自同一 Newow result，不称为 AlertEvent。Trend 状态文字优先；D1/D2/D3 保留文本徽标；杯柄图标只辅助；换月使用 `contract-switch`+合约文字，不能用交易机会图标。

- [ ] **Step 7: E2E**

覆盖 fixed identity、Newow unavailable no fallback、Marker isolation、rollover、history same facts、1920 Trend、390 Trend。

- [ ] **Step 8: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowTypes.test.ts \
  tests/trendDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "Trend"

git add \
  apps/quant-web/src/types/newow.ts \
  apps/quant-web/src/api/newow.ts \
  apps/quant-web/src/utils/newowTypes.ts \
  apps/quant-web/src/utils/trendDetailViewModel.ts \
  apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue \
  apps/quant-web/src/components/market/detail/trend/TrendDetailWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/tests/newowTypes.test.ts \
  apps/quant-web/tests/trendDetailViewModel.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): add Newow trend detail workspace"
```

若 Task 13 同时修改任何后端或 OpenSpec 文件，必须按上游 Newow 合同追加 targeted backend、Ruff、Mypy、OpenSpec；不得执行真实数据写入。

---

# Slice E — Final Cutover、删除旧页、视觉与 Canonical

## Task 14: 实现主力换月分界和统一 Marker 选择

**Files:**
- Create: `apps/quant-web/src/utils/contractBoundaries.ts`
- Create: `apps/quant-web/tests/contractBoundaries.test.ts`
- Create: `apps/quant-web/src/components/kline/contractBoundaryPrimitive.ts`
- Create: `apps/quant-web/tests/contractBoundaryPrimitive.test.ts`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify: `apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue`
- Modify: `apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue`

**Interfaces:**

```ts
export interface ContractBoundary {
  time: string
  previousContract: string
  nextContract: string
  label: string
}

export function buildContractBoundaries(bars: readonly BarData[]): ContractBoundary[]
```

- [ ] **Step 1: 写纯函数测试**

```ts
test('boundary appears only when physical contract changes', () => {
  assert.deepEqual(buildContractBoundaries([
    bar('JM2509', '2026-01-01'),
    bar('JM2509', '2026-01-02'),
    bar('JM2601', '2026-01-03'),
  ]), [{
    time: '2026-01-03',
    previousContract: 'JM2509',
    nextContract: 'JM2601',
    label: 'JM2509 → JM2601 · 主力切换',
  }])
})
```

continuous 无 physical contract 时返回空；非法缺失/回退不猜边界。

- [ ] **Step 2: 实现低干扰 vertical primitive**

细虚线、中性灰、顶部合约文字；说明“物理合约所有权切换”；不使用涨跌色。

- [ ] **Step 3: 统一 Marker 点击**

KlineChart 和 Newow stage 都按当前渲染集合中的稳定 ID 映射 typed item；未知、过期、其他视角 ID 拒绝。

- [ ] **Step 4: 验证并提交**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/contractBoundaries.test.ts \
  tests/contractBoundaryPrimitive.test.ts \
  tests/marketDetailMarkers.test.ts
pnpm --dir apps/quant-web build

git add \
  apps/quant-web/src/utils/contractBoundaries.ts \
  apps/quant-web/src/components/kline/contractBoundaryPrimitive.ts \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue \
  apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue \
  apps/quant-web/tests/contractBoundaries.test.ts \
  apps/quant-web/tests/contractBoundaryPrimitive.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts

git commit -m "feat(web): show contract boundaries and marker details"
```

---

## Task 15: 原子完成 final route cutover 并删除旧详情面

**Files:**
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Delete: `apps/quant-web/src/pages/market/LegacyMarketChart.vue`
- Modify: `apps/quant-web/src/utils/marketDetailRoute.ts`
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Delete after zero-reference proof: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Delete after zero-reference proof: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Delete after zero-reference proof: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Modify current tests/E2E that assert old toolbar/sidebar

**Precondition:** 四个 explicit Workspace 均已通过各自 Gate。

- [ ] **Step 1: 写 missing-view → Trend 测试**

```ts
test('missing view defaults to trend after final cutover', () => {
  assert.deepEqual(resolveFinalMarketDetailIdentity({ symbol: 'jm' }), {
    view: 'trend', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '1d',
  })
})
```

- [ ] **Step 2: 同一 commit 原子切换**

```text
chart.vue 永远挂 MarketDetailPage
无 view → Trend
首页普通品种 → view=trend
HTDY Event → view=htdy
SuBing Event → view=subing
旧 overlay query 不再选择视角
```

旧 `overlay=htdy` 且无 `view` 不自动跳 HTDY；只有显式新 Event 深链进入 HTDY。

- [ ] **Step 3: 证明零引用后删除旧文件**

```bash
rg -n "LegacyMarketChart|ProductWorkspaceToolbar|ProductCheckSidebar|ProductAlertRules|product-status-strip|researchSidebarOpen" \
  apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
```

只有 active reference 为零才删除；不建立 legacy/archive copy。

- [ ] **Step 4: 收敛旧 preference/overlay surface**

保留通用 indicator definitions；删除仅服务旧页面的 selectedOverlay/sidebar preference，前提是 `rg` 证明无消费者。不得删除 HTDY、Range、EMA、MACD primitive。

- [ ] **Step 5: Web 全量验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 6: 精确暂存并提交**

先运行：

```bash
git status --short
git diff --name-only origin/develop...HEAD
```

只暂存本 Task 实际列出的修改/删除路径，不得 `git add -A` 吞入无关并行改动。

```bash
git commit -m "feat(web): cut over unified market detail page"
```

---

## Task 16: 完成牛哇视觉、图标、响应式和无障碍验收

**Files:**
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create/update: `apps/quant-web/e2e/market-detail.spec.mjs-snapshots/*`
- Modify findings only: `apps/quant-web/src/components/market/detail/**/*.vue`
- Modify findings only: `apps/quant-web/src/styles/tokens.css`

- [ ] **Step 1: 生成冻结快照矩阵**

```text
1920×1080 Trend ready
1440×900 HTDY ready
1440×900 SuBing event
1280×800 Free with Range
390×844 Trend
390×844 SuBing history drawer
非法 identity
view data unavailable
Alert API unavailable
Runtime degraded
```

- [ ] **Step 2: 与牛哇真实页面逐区并列 Review**

检查顶部留白、价格层级、策略 Chip、警示条、三事实、展开箭头、卡片圆角、主图起点、图表操作、历史/预警/更多入口、移动抽屉。

不比较股票字段、综合分、建议仓位、目标价或私有策略结果。

- [ ] **Step 3: 图标机会终审**

```text
牛哇有图标且语义明确 → clean-room icon + label/tooltip
牛哇有图标但属于品牌/私有算法 → 不复制；改通用语义 icon 或文字
牛哇无图标且文字更清楚 → 保持文字
核心交易语义 → 文字必须保留，icon 仅辅助
```

禁止 emoji 充当产品图标；禁止给每个标题加装饰 icon。

- [ ] **Step 4: 无障碍 E2E**

覆盖 Tab 键盘、Accordion Enter/Space、Drawer focus trap/restore、icon-only accessible name、红绿替代语义、44×44 target、reduced motion、Marker 历史替代。

- [ ] **Step 5: 修复后全量运行**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

不得只更新 snapshot 吞掉意外变化；每次 baseline 变化都在 PR 说明原因。

- [ ] **Step 6: 精确提交**

只暂存本 Task 真实变化的 E2E snapshot、detail component 和 token 路径。

```bash
git commit -m "test(web): freeze unified detail visual contract"
```

---

## Task 17: 同步 active canonical、执行全量验证并独立 Review

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`
- Create: `openspec/specs/market-detail/spec.md`
- Do not modify: `STATUS.md`，除非另一个被明确授权的 release/Runtime 任务产生真实状态变化

- [ ] **Step 1: 更新稳定产品面**

写明统一详情页、四互斥视角、各自 authority、无订单/账户/自动晋升。不得把尚未 release/Runtime 的状态写成生产事实。

- [ ] **Step 2: 更新架构、OpenSpec 和测试导航**

```text
MarketDataService → shared bars/header
Newow read API → Trend
HTDY display + AlertEvent → HTDY
AlertEvent → SuBing
Generic indicators → Free/HTDY/SuBing review layers
```

新 `market-detail/spec.md` 只冻结页面、身份、authority、fail-closed 和视觉/无障碍要求，不复制 Newow/SuBing/HTDY 公式。

- [ ] **Step 3: 全量验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py

openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

若 Slice D 修改后端/OpenSpec，追加 accepted Newow targeted pytest、Ruff、Mypy。必要检查无法运行时只报告阻塞。

- [ ] **Step 4: 两个独立 Review 轴**

Review A：牛哇参考、图标位置、首屏节奏、移动端、无障碍、无假按钮/综合分/仓位建议。

Review B：四视角互斥、Newow API-only、SuBing Event-only、HTDY dual-fact、stale/generation、route/focus、无 Scope/Runtime/生产越权。

- [ ] **Step 5: 修复 findings 并重跑受影响到全量验证**

Critical/Important finding 不得只记录在 PR 文案中。

- [ ] **Step 6: 提交 canonical**

```bash
git add \
  PROJECT_SOURCE.md \
  DECISIONS.md \
  docs/ARCHITECTURE.md \
  TESTING.md \
  openspec/specs/market-detail/spec.md

git commit -m "docs(market): canonicalize unified detail surface"
```

- [ ] **Step 7: 停在用户 Gate**

只允许声明：

```text
CODE_COMPLETE
TEST_COMPLETE
VISUAL_REVIEW_READY
```

用户审核截图和 exact-head PR 后，只有明确“允许集成 develop”才合入。不得发布 `main`、创建 tag、同步 Runtime 或执行真实通知/Scope。

---

## 3. Spec 验收映射

| Spec 要求 | Task |
|---|---|
| 统一外壳、四视角互斥 | 1、6、15 |
| 顶部渐进披露 | 4、5 |
| 牛哇视觉与图标参考 | 3、5、7、8、11、13、16 |
| clean-room icon + accessibility | 3、16 |
| Trend fixed identity/API-only | 1、12、13 |
| HTDY dual-fact | 8 |
| SuBing Event-only | 10、11 |
| Free 通用能力 | 7 |
| Alert exact Scope | 9（Lane 3） |
| route/focus/deep link | 1、8、11、15 |
| 旧页不中断、最终删除 | 6、15 |
| 主力换月 | 14 |
| desktop/mobile/drawer | 5、16 |
| loading/stale/generation | 4、6、8、10、13 |
| canonical/full verification | 17 |

---

## 4. Plan 自审记录

### 4.1 Spec coverage

已逐节核对 Spec 第 1–32 节；产品、身份、事实、交互、视觉、无障碍、偏好、错误与验收均映射到 Task 1–17。Newow API 尚未进入 active `develop` 的不确定性由 Task 12 设为 fail-closed dependency Gate，没有推测 endpoint 或 wire。

### 4.2 Placeholder scan

- 没有 `TODO / TBD / FIXME`。
- 没有空组件、条件性测试文件名或虚构 API。
- `LegacyMarketChart` 是有创建、回归、切换和删除任务的临时 seam，不是永久兼容层。
- OpenSpec 使用已冻结的精确路径 `openspec/specs/market-detail/spec.md`。

### 4.3 Type consistency

```text
MarketDetailView
FlexibleViewRestore
MarketDetailViewRestore
MarketDetailIdentity
MarketDetailRouteResult
MarketDetailPreferences
MarketDetailHeaderModel
MarketDetailFact
MarketDetailDisclosureSection
DetailViewModel
MarketDetailIconName
ContractBoundary
NewowTrendDetailModel
RuntimeAlertRuleStatus
```

### 4.4 Scope check

本计划没有把上游 Newow Formula/API 开发吞入 Web 详情任务。Alert Scope mutation 单独为 Lane 3；其余为 Lane 2。所有真实外部操作保持独立 Gate。

---

## 5. 当前状态

```text
SPEC_APPROVED_BY_USER
ICON_REFERENCE_AMENDMENT_APPROVED
IMPLEMENTATION_PLAN_INTERNAL_REVIEW_PASSED
IMPLEMENTATION_PLAN_USER_REVIEW_PENDING
SOURCE_IMPLEMENTATION_NOT_STARTED
PRODUCTION_MUTATION_NOT_AUTHORIZED
MAIN_TAG_RELEASE_RUNTIME_NOT_AUTHORIZED
```

用户批准本计划后，只授权启动 **Slice A**；不授权连续执行 Slice B–E，不授权自动集成 `develop`。
