# Market 统一牛哇式详情页 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 `/market/chart` 现有能力可用、且不混合四个事实权威的前提下，实现统一牛哇式详情页外壳，以及趋势策略、火天大有、新苏冰、自由看盘四个互斥分析视角。

**Architecture:** 使用“共享 Shell + 独立 Workspace + 分阶段切换”的结构。共享层只负责路由、品种身份、行情头、渐进式披露、公共抽屉和错误边界；每个 Workspace 独立拥有允许的数据身份、图层、摘要、历史和控制。实施期间保留旧详情页作为临时兼容入口，只有四个视角均达到验收并且 Newow 只读 API 已可用后，才把缺省入口切换到 Trend 并删除旧 Toolbar/Sidebar。

**Tech Stack:** Vue 3.5、TypeScript 6、Vue Router 5、Naive UI 2.44、Lightweight Charts 5.2、Node `node:test`、Playwright、Vite 8、现有 FastAPI/Market/Alert typed API。

**Spec:** `docs/tasks/2026-09-02-market-detail-niuwah-unified-spec.md`

## Global Constraints

- 用户已批准上述 Spec；本计划是唯一新的详情页实施顺序，不恢复“当前版本 / 牛哇版本”双页面。
- 四个视角固定为 `trend | htdy | subing | free`，任一时刻只允许一个 Workspace 控制主图。
- Trend 固定 `actual_dominant + completed 1d`；SuBing 固定 `actual_dominant + completed 15m`；HTDY 和 Free 只允许其正式能力矩阵中的序列与周期。
- Newow 正式结果只能来自 Newow Engine/只读 API；SuBing 正式 `S↑ / S↓` 只能来自 `AlertEvent`；HTDY 原始观察和不可变 Event 必须分开。
- 不输出综合分、胜率、四视角投票、仓位建议、目标价、止损价、自动交易或账户语义。
- 页面继续使用中国期货红涨绿跌语义，并同时提供文字、形状或箭头，不得只依赖颜色。
- **图标强制参考规则：** 开发任何导航、操作、状态、警示、展开、图表控制或 Marker 图标前，必须先对照用户提供的牛哇详情页截图或当时可访问的牛哇页面；牛哇使用图标的位置必须优先评估图标化，牛哇使用文字的位置不得无依据强行图标化。
- 图标只允许 clean-room 重绘为项目自有 inline SVG/CSS；不得复制牛哇 Logo、品牌图形、私有 SVG、私有 CSS、截图切片或外部字体文件。
- 视角 Tab 和核心业务状态保持文字优先；图标只能辅助，不得代替“趋势策略、火天大有、新苏冰、自由看盘、建仓、持有、清仓、空仓、预警”等关键语义。
- 图标按钮必须有中文 `aria-label`；仅装饰图标必须 `aria-hidden=true`；移动端点击目标不得小于 44×44 CSS px。
- 每个视觉 Slice 的 PR 必须附一张“牛哇参考位置 → 归一量化处理 → 是否保留文字 → 无障碍标签”的图标审计表，并提供对应截图证据。
- 不新增通用图标平台、通用策略插件平台、服务端偏好、数据库表、Redis key、队列或 Worker。
- 本计划不授权 production PostgreSQL/Redis/Scope、真实通知、Runtime、RQData、Canonical、`main`、tag 或 Release 操作。
- Alert Scope 控制属于 Lane 3 可信写入口；其代码实施必须独立 Plan Gate、独立 Review，测试只能使用 fake/route intercept，不能调用真实 Scope。
- 每个源码 Slice 从执行时最新 `origin/develop` 创建独立 task branch/worktree；不得从本 docs 分支直接开发源码。
- 每个源码 Slice 必须先 Draft PR、测试、自审和独立 Review，再由用户明确给出“允许集成 develop”。
- 集成 `develop` 不等于 release、main、tag、Runtime promotion 或任何生产写入。

---

## 0. 规划基线与执行顺序

本计划成稿时观察到：

```text
最新 develop：8dea6d23cf714fa84b03a51bddcf4da7c23fabd8
文档分支原 Spec commit：6c7f571baee442205dd23acb74bd539ec16a6b6c
当前 release：v1.9.12
production Runtime：degraded，不能标记 RUNTIME_READY
Newow：Slice A 已存在；杯柄、统一 Engine、只读 API 仍按其独立计划推进
SuBing：Web/API/Event 基础已进入 develop；production Gate 与 Runtime 事实仍独立
```

文档分支和 `develop` 已发生推进，因此执行任一源码 Slice 前必须重新读取：

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

严格顺序：

```text
Slice A：路由、偏好、图标合同、共享 Shell 基础
→ 用户 Gate
Slice B1：Free 迁移
→ 用户 Gate
Slice B2：HTDY 只读迁移
→ 用户 Gate
Slice B3：Alert Scope 控制（Lane 3，独立 Gate）
→ 用户 Gate
Slice C：SuBing 专用视角与事件深链
→ 用户 Gate
Newow 上游 Slice B/C 完成且只读 API 已进入 develop
→ Slice D：Trend 视角
→ 用户 Gate
Slice E：最终切换、删除旧页面、视觉/图标/无障碍与 canonical 收敛
→ 用户视觉 Gate
```

不允许并行从旧 base 开发相互依赖的 Slice。

---

## 1. Codex 调度矩阵

| Slice | Lane | 模型 | 推理 | Plan | 会话与工作区 | 人工 Gate |
|---|---|---|---|---|---|---|
| A | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；从最新 `develop` 创建 `feature/market-detail-shell` worktree | 独立 Review + 允许集成 develop |
| B1 | Lane 2 | Terra | 中 | Plan-then-execute | 新会话；从 A 已进入后的最新 `develop` 创建 `feature/market-detail-free` | 独立 Review + 允许集成 develop |
| B2 | Lane 2 | Terra | 中 | Plan-then-execute | 新会话；从 B1 已进入后的最新 `develop` 创建 `feature/market-detail-htdy` | 独立 Review + 允许集成 develop |
| B3 | Lane 3 | Sol | 高 | Plan-only；批准后再实现 | 新会话；独立 `feature/market-detail-alert-control` | Plan 批准 + 独立 Review + 允许集成 develop；真实写入另行批准 |
| C | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；从 B3 已进入后的最新 `develop` 创建 `feature/market-detail-subing` | 独立 Review + 允许集成 develop |
| D | Lane 2（只读 Web）；上游 Newow 保持自身 Lane | Sol | 高 | Plan-then-execute | Newow 只读 API Gate 后新会话；`feature/market-detail-trend` | 上游合同确认 + 独立 Review + 允许集成 develop |
| E | Lane 2 | Sol | 高 | Plan-then-execute | 新会话；`feature/market-detail-cutover` | 独立 Review + 用户视觉批准 + 允许集成 develop |

所有 task worktree：

- 从执行时最新、clean 的 `develop` 创建；
- 完成后只集成回 `develop`；
- 不允许自动触及 `main`、tag、Release 或 Runtime；
- PR 合入并确认 commit 已进入 `develop` 后，才清理临时 worktree 和已合并 branch；
- 若分支 behind 或发生同文件并行修改，先更新并重新运行完整 Slice 验证，不能用旧测试结论合入。

---

## 2. 最终文件职责图

### 2.1 共享页面与纯合同

```text
apps/quant-web/src/pages/market/chart.vue
  最终只挂载 MarketDetailPage；实施中暂时路由旧页/新页

apps/quant-web/src/pages/market/LegacyMarketChart.vue
  临时承载当前 chart.vue；最终 Slice E 删除

apps/quant-web/src/pages/market/MarketDetailPage.vue
  共享 Shell、route orchestration、workspace mounting、错误边界

apps/quant-web/src/types/marketDetail.ts
  Detail view、identity、header、fact、disclosure、history、icon 类型

apps/quant-web/src/utils/marketDetailRoute.ts
  纯 route parser/serializer、固定身份、view switch、focus 合同

apps/quant-web/src/utils/marketDetailPreferences.ts
  v1 偏好、视角隔离、v9 只迁移到 Free

apps/quant-web/src/utils/marketDetailIcons.ts
  项目自有图标注册表、中文语义、使用位置约束

apps/quant-web/src/utils/marketDetailViewModel.ts
  行情头、共享状态和三事实通用映射；不计算策略

apps/quant-web/src/utils/marketDetailMarkers.ts
  视角级 Marker 白名单与点击 identity

apps/quant-web/src/composables/useMarketDetailController.ts
  当前身份、generation、Market series、metadata/research/runtime/alert 协调
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

### 2.3 各视角

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

Newow Web 边界（仅上游只读 API 就绪后创建）：

```text
apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/utils/newowTypes.ts
```

### 2.4 测试与视觉证据

```text
apps/quant-web/tests/marketDetailRoute.test.ts
apps/quant-web/tests/marketDetailPreferences.test.ts
apps/quant-web/tests/marketDetailIcons.test.ts
apps/quant-web/tests/marketDetailViewModel.test.ts
apps/quant-web/tests/marketDetailMarkers.test.ts
apps/quant-web/tests/freeDetailViewModel.test.ts
apps/quant-web/tests/htdyDetailViewModel.test.ts
apps/quant-web/tests/subingDetailViewModel.test.ts
apps/quant-web/tests/trendDetailViewModel.test.ts
apps/quant-web/tests/newowTypes.test.ts

apps/quant-web/e2e/market-detail.helpers.mjs
apps/quant-web/e2e/market-detail.spec.mjs
apps/quant-web/e2e/market-detail.spec.mjs-snapshots/*
```

不得为了目录整齐一次性创建空文件。每个文件只能在第一个真实消费者任务中创建。

---

# Slice A — 路由、偏好、图标合同和共享 Shell

## Task 1: 冻结统一详情路由与固定身份

**Files:**
- Create: `apps/quant-web/src/types/marketDetail.ts`
- Create: `apps/quant-web/src/utils/marketDetailRoute.ts`
- Test: `apps/quant-web/tests/marketDetailRoute.test.ts`
- Modify later in this task: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Test: `apps/quant-web/tests/marketHomeRoute.test.ts`

**Interfaces:**
- Consumes: `MarketFrequency`、`SeriesKind`、`AlertEvent`、`ALERT_RULE_CODES`。
- Produces:

```ts
export const MARKET_DETAIL_VIEWS = ['trend', 'htdy', 'subing', 'free'] as const
export type MarketDetailView = (typeof MARKET_DETAIL_VIEWS)[number]

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
  preferences: MarketDetailPreferences,
): MarketDetailIdentity
export function marketDetailEventIdentity(event: AlertEvent): MarketDetailIdentity
```

- `missing-view` 只为实施期旧页面兼容存在；最终 Slice E 将缺省入口解释为 Trend。
- `invalid` 不自动修改 URL，只提供显式恢复按钮所需 `recovery`。

- [ ] **Step 1: 写失败测试覆盖四视角合法身份**

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import { parseMarketDetailRoute } from '../src/utils/marketDetailRoute.ts'

test('trend only accepts actual dominant completed D1 identity', () => {
  assert.deepEqual(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', series_kind: 'actual_dominant', frequency: '1d',
  }), {
    kind: 'valid',
    identity: { view: 'trend', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '1d' },
  })
  assert.equal(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m',
  }).kind, 'invalid')
})

test('subing only accepts actual dominant 15m identity', () => {
  assert.equal(parseMarketDetailRoute({
    view: 'subing', symbol: 'jm', series_kind: 'continuous', frequency: '15m',
  }).kind, 'invalid')
})
```

- [ ] **Step 2: 运行测试并确认 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailRoute.test.ts
```

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现 parser、serializer 和错误码**

错误码固定：

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

时间必须为 timezone-aware ISO instant；非法日历日期拒绝。

- [ ] **Step 4: 写事件深链失败测试**

```ts
test('event identities enter their exact mutually exclusive views', () => {
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

- [ ] **Step 5: 更新 Market Home route helper**

`marketHomeProductChartQuery()` 最终目标应返回 Trend identity，但在最终切换前增加显式参数函数，避免现在就把首页导向尚未完成的新页面：

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

保留旧导出供旧首页使用，最终 Slice E 原子替换并删除旧导出。

- [ ] **Step 6: 运行定向测试**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailRoute.test.ts \
  tests/marketHomeRoute.test.ts \
  tests/marketChartEntry.test.ts
```

Expected: PASS；旧 `focus_bar_end` 行为不回归。

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
- Test: `apps/quant-web/tests/marketDetailPreferences.test.ts`
- Read only: `apps/quant-web/src/utils/mainIndicators.ts`
- Read only: `apps/quant-web/src/utils/marketWorkspacePreferences.ts`

**Interfaces:**

```ts
export const MARKET_DETAIL_PREFERENCES_KEY = 'guiyi.market.detail.preferences.v1'

export interface FlexibleDetailPreferences {
  seriesKind: SeriesKind
  frequency: MarketFrequency
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

- Trend 和 SuBing 不拥有可保存周期、序列或指标设置。
- 旧 v9 只迁移 `period / optionalEmaIndicators / showRangeDetector` 到 Free。
- 旧 `selectedOverlay=htdy` 不能改变 `lastView='trend'`。
- 实施期不删除旧 key，避免旧页面仍在使用时被破坏。

- [ ] **Step 1: 写损坏存储和缺省测试**

```ts
test('corrupt detail preferences fail closed to trend and isolated defaults', () => {
  const storage = memoryStorage({
    'guiyi.market.detail.preferences.v1': '{broken',
  })
  assert.deepEqual(loadMarketDetailPreferences(storage), defaultMarketDetailPreferences())
})
```

- [ ] **Step 2: 写 v9 只迁移到 Free 的测试**

```ts
test('legacy v9 generic settings migrate to free only', () => {
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

Expected: FAIL，模块尚不存在。

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

`contract` 不存入偏好，避免跨品种沿用真实合约。

- [ ] **Step 5: 运行测试**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailPreferences.test.ts \
  tests/mainIndicators.test.ts \
  tests/market-workspace-preferences.test.ts
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add apps/quant-web/src/utils/marketDetailPreferences.ts \
  apps/quant-web/tests/marketDetailPreferences.test.ts

git commit -m "feat(web): isolate market detail preferences"
```

---

## Task 3: 建立牛哇参考驱动的图标合同

**Files:**
- Create: `apps/quant-web/src/utils/marketDetailIcons.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailIcon.vue`
- Test: `apps/quant-web/tests/marketDetailIcons.test.ts`
- Modify: `apps/quant-web/src/styles/tokens.css`
- Reuse: `apps/quant-web/src/components/market/MarketStateIcon.vue`

**Interfaces:**

```ts
export const MARKET_DETAIL_ICON_NAMES = [
  'back',
  'chevron-down',
  'chevron-right',
  'history',
  'alert',
  'more',
  'fullscreen',
  'settings',
  'warning',
  'info',
  'data',
  'close',
  'refresh',
  'contract-switch',
] as const

export type MarketDetailIconName = (typeof MARKET_DETAIL_ICON_NAMES)[number]

export interface MarketDetailIconDefinition {
  name: MarketDetailIconName
  label: string
  mode: 'stroke' | 'fill'
  paths: readonly string[]
  circles?: readonly { cx: number; cy: number; r: number }[]
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
- action button 的可访问名称由 button 提供，不重复朗读内部 icon。
- 上涨/下跌/周期同向/中性/不可用继续复用 `MarketStateIcon`，不复制第二套状态圆标。

- [ ] **Step 1: 在任务 PR 描述中建立图标审计表**

必须逐项记录：

```text
位置 | 牛哇参考表现 | 本项目处理 | 是否保留文字 | aria-label
返回 | 左箭头 | clean-room 左箭头 | 隐藏文字但按钮有 aria-label | 返回行情看板
历史 | 历史/记录入口图标 | 时钟回转线 | 保留 tooltip | 查看当前视角历史
预警 | 铃铛 | clean-room 铃铛 | 保留 tooltip | 管理当前预警
更多 | 三点 | 三个圆点 | 保留 tooltip | 更多操作
展开 | 小箭头 | chevron | 保留标题文字 | 展开更多行情数据
警示 | 彩色警示徽标 | 三角警示线框 | 保留警示正文 | 风险提示
```

视角 Tab 不添加装饰图标，除非视觉 Review 证明牛哇参考位置确实需要并且不会削弱文字识别。

- [ ] **Step 2: 写图标注册表失败测试**

```ts
test('detail icon registry is finite, labeled, and clean-room owned', () => {
  assert.deepEqual(MARKET_DETAIL_ICON_NAMES, [
    'back', 'chevron-down', 'chevron-right', 'history', 'alert', 'more',
    'fullscreen', 'settings', 'warning', 'info', 'data', 'close',
    'refresh', 'contract-switch',
  ])
  for (const name of MARKET_DETAIL_ICON_NAMES) {
    const icon = marketDetailIconDefinition(name)
    assert.equal(icon.name, name)
    assert.ok(icon.label.length > 0)
    assert.ok(icon.paths.length > 0 || (icon.circles?.length ?? 0) > 0)
  }
})
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailIcons.test.ts
```

Expected: FAIL。

- [ ] **Step 4: 使用项目自有几何实现注册表**

固定 clean-room 几何示例：

```ts
const DEFINITIONS: Record<MarketDetailIconName, MarketDetailIconDefinition> = {
  back: {
    name: 'back', label: '返回', mode: 'stroke',
    paths: ['M15.5 5 8.5 12l7 7'], referenceRole: 'navigation',
  },
  'chevron-down': {
    name: 'chevron-down', label: '展开', mode: 'stroke',
    paths: ['M7 9.5 12 14.5 17 9.5'], referenceRole: 'disclosure',
  },
  more: {
    name: 'more', label: '更多', mode: 'fill', paths: [],
    circles: [{ cx: 6, cy: 12, r: 1.5 }, { cx: 12, cy: 12, r: 1.5 }, { cx: 18, cy: 12, r: 1.5 }],
    referenceRole: 'action',
  },
  // 其余名称使用同一 24×24、1.8 stroke、round cap/join 合同完整实现。
}
```

实现时不得从网页 DOM、SVG 下载或截图描摹路径；只按常见语义重新绘制。

- [ ] **Step 5: 增加详情页视觉 token**

只补充语义 token，不复制一套新 palette：

```css
--gy-detail-accent: var(--gy-market-icon-aligned);
--gy-detail-accent-soft: var(--gy-market-pill-aligned-soft);
--gy-detail-icon-muted: var(--gy-text-muted);
--gy-detail-card-bg: var(--gy-bg-panel);
--gy-detail-section-bg: var(--gy-gray-50);
--gy-detail-warning-border: color-mix(in srgb, var(--gy-status-warning) 35%, transparent);
```

- [ ] **Step 6: 运行定向和 build**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailIcons.test.ts \
  tests/marketHomeIcons.test.ts
pnpm --dir apps/quant-web build
```

Expected: PASS；未引入外部图标依赖。

- [ ] **Step 7: 提交**

```bash
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
- Test: `apps/quant-web/tests/marketDetailViewModel.test.ts`

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

- [ ] **Step 1: 写三事实和禁止字段测试**

```ts
test('shared fact strip exposes exactly three sourced facts and no synthetic score', () => {
  const model = buildFreeDetailViewModel(fixture)
  assert.equal(model.facts.length, 3)
  assert.deepEqual(model.facts.map((item) => item.source), ['market', 'market', 'market'])
  assert.equal('score' in model, false)
  assert.equal('confidence' in model, false)
})
```

- [ ] **Step 2: 写行情头同身份测试**

覆盖：

```text
latest completed Bar 作为价格
上一 completed Bar 计算 change/pct
actual_dominant 使用 latest Bar.physicalContract
continuous 不伪造 physicalContract
Bars 与 metadata 合约冲突时 header freshness=unavailable
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

Builder 只能格式化、选择同身份事实和计算相邻 completed Bar 价格变化；不得重算策略或趋势。

- [ ] **Step 5: 运行测试**

```bash
pnpm -C apps/quant-web exec node --test tests/marketDetailViewModel.test.ts
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
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
- E2E create later in task: `apps/quant-web/e2e/market-detail.helpers.mjs`
- E2E create later in task: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

- `MarketDetailTopBar` emits `back | select-symbol | open-history | open-alert | open-more`。
- `MarketDetailQuoteHeader` consumes `MarketDetailHeaderModel` and emits `toggle-more`。
- `MarketDetailViewNav` consumes current `view` and allowed controls; emits exact `MarketDetailIdentity` changes。
- `MarketDetailInsightDeck` consumes `DetailViewModel` and owns desktop multi-open/mobile single-open Accordion。
- `MarketDetailDrawer` traps focus while open and restores focus to the triggering element after close。

- [ ] **Step 1: 先写 Playwright 结构断言**

```js
test('detail shell keeps Niuwah vertical reading order and no sidebar', async ({ page }) => {
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m')
  const order = await page.locator('[data-detail-section]').evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('data-detail-section')),
  )
  expect(order).toEqual(['topbar', 'quote', 'view-nav', 'insight', 'chart', 'sections'])
  await expect(page.getByTestId('product-check-sidebar')).toHaveCount(0)
})
```

本步骤先建立文件和 route mocks；在页面尚未接线时预期失败。

- [ ] **Step 2: 实现 TopBar 的参考图标**

固定显示策略：

```text
返回：icon-only + aria-label
品种/合约：文字 + chevron
历史：icon + 宽屏文字；窄屏 icon-only + aria-label
预警：只在 actions.canManageAlert=true 时显示
更多：icon-only + menu
```

不得显示没有真实功能的收藏星标。

- [ ] **Step 3: 实现 QuoteHeader 和更多行情原位展开**

默认直出：品种、合约、截至时间、close/change/pct、OHLC、volume、OI、四类状态标签。

`MarketFactsDisclosure`：

```text
默认折叠
桌面原位展开三组
移动端仍原位展开
品种/身份变化时立即关闭
错误/stale 标题可见，不藏在正文
```

- [ ] **Step 4: 实现视角 Tab 和控件可见性**

```text
Trend：固定日K胶囊，无 series control
HTDY：七周期 + series control
SuBing：固定15m胶囊，无 series control
Free：七周期 + series control
```

不支持项不渲染，不能渲染 disabled 假入口。

- [ ] **Step 5: 实现 FactStrip、InsightDeck 和 Accordion**

- FactStrip 固定三项。
- 第一块默认展开。
- 桌面可多开。
- 390px 下单开。
- 标题行使用文字 + chevron icon。
- `aria-expanded`、`aria-controls`、Enter/Space 完整。

- [ ] **Step 6: 实现 SectionTabs 和 Drawer**

当前视角没有历史时，不渲染历史入口。桌面原位展开；移动端底部抽屉。顶部“历史”和底部“历史记录”接收同一 `history` prop。

- [ ] **Step 7: 完成第一轮牛哇视觉对照**

在 PR 中附：

```text
牛哇顶部操作图标位置
牛哇策略 Chip 高度和间距
牛哇警示条/摘要条
牛哇折叠/展开箭头
归一量化对应截图
差异说明
```

禁止把参考页截图或品牌资产提交进仓库；仓库只提交本项目 Playwright baseline。

- [ ] **Step 8: 运行组件编译和基础 E2E**

```bash
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "detail shell"
```

Expected: 结构、键盘和图标断言通过。

- [ ] **Step 9: 提交**

```bash
git add apps/quant-web/src/components/market/detail \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): add unified market detail shell primitives"
```

---

## Task 6: 建立新旧页面的安全过渡入口

**Files:**
- Create by move: `apps/quant-web/src/pages/market/LegacyMarketChart.vue`
- Create: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Create: `apps/quant-web/src/composables/useMarketDetailController.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Test: `apps/quant-web/tests/marketDetailController.test.ts`
- E2E modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Existing E2E regression: `apps/quant-web/e2e/market-research-chart-interaction.spec.mjs`

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

临时过渡规则：

```text
无 view：LegacyMarketChart
显式合法且本 Slice 已启用的 view：MarketDetailPage
显式合法但 Workspace 尚未完成：MarketDetailUnavailable，提供返回旧页按钮
非法 identity：MarketDetailUnavailable，提供按该视角要求打开按钮
```

临时过渡状态必须在 Slice E 全部删除。

- [ ] **Step 1: 机械移动当前 chart.vue**

把现有 script/template/style 完整移动到 `LegacyMarketChart.vue`，不在同一 commit 改行为。`chart.vue` 暂时只挂载 Legacy，以证明移动无回归。

- [ ] **Step 2: 运行旧页面回归**

```bash
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-research-chart-interaction.spec.mjs \
  e2e/market-range-detector.spec.mjs \
  e2e/market-runtime.spec.mjs
```

Expected: 与移动前一致。

- [ ] **Step 3: 写 controller generation 失败测试**

```ts
test('late detail responses cannot overwrite a newer identity', async () => {
  const first = deferredPage('jm')
  const second = deferredPage('rb')
  const controller = useMarketDetailController(fakeDependencies([first, second]))
  void controller.switchIdentity(freeIdentity('jm'))
  void controller.switchIdentity(freeIdentity('rb'))
  second.resolve()
  first.resolve()
  await flushPromises()
  assert.equal(controller.state.value.identity?.symbol, 'rb')
  assert.equal(controller.bars.value.at(-1)?.physicalContract, 'RB2610')
})
```

- [ ] **Step 4: 实现 controller，复用 useMarketSeries**

不得复制 Market WebSocket、分页或 actual-dominant 物理合约解析。controller 只组合：

```text
useMarketSeries
getMarketDominants
getProductResearch
getRuntimeHealth
current view data loaders
```

切换 identity 时先 invalidate 旧 view facts，再启动新 generation。

- [ ] **Step 5: 接线显式 Free 预览入口**

本 Slice 只允许显式 `view=free` 进入新 Shell；其他 Workspace 尚未实现时显示明确不可用，不把空壳冒充完成。

- [ ] **Step 6: 运行定向测试和 E2E**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailController.test.ts \
  tests/useMarketSeries.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs \
  e2e/market-research-chart-interaction.spec.mjs
```

- [ ] **Step 7: 提交**

```bash
git add apps/quant-web/src/pages/market \
  apps/quant-web/src/composables/useMarketDetailController.ts \
  apps/quant-web/tests/marketDetailController.test.ts \
  apps/quant-web/e2e

git commit -m "feat(web): stage unified detail behind explicit view"
```

---

## Slice A 完成 Gate

必须全部满足：

```text
route parser/serializer 完整
非法 identity fail-closed
v9 只迁移到 Free
图标注册表为项目自有 clean-room SVG
牛哇图标审计表已附 PR
共享组件可键盘操作
新旧页面过渡不破坏旧 route
未启用空 Trend 默认入口
Web 定向测试、build、旧页面 E2E 全绿
独立 exact-head Review 无 Critical/Important
```

结论只允许：

```text
SLICE_A_READY_FOR_INTEGRATION
SLICE_A_REQUIRES_FIXES
SLICE_A_BLOCKED
```

---

# Slice B1 — 自由看盘迁移

## Task 7: 实现 Free Workspace 并保持所有通用图表能力

**Files:**
- Create: `apps/quant-web/src/utils/freeDetailViewModel.ts`
- Test: `apps/quant-web/tests/freeDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketKlineStage.vue`
- Create: `apps/quant-web/src/components/market/detail/free/FreeChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/free/FreeChartWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue` only where a reusable stage interface is necessary
- Modify E2E: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

```ts
export function buildFreeDetailViewModel(input: {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  research: ProductResearchResponse | null
  researchError: boolean
  rangeState: 'disabled' | 'loading' | 'ready' | 'insufficient'
}): DetailViewModel
```

`MarketKlineStage` consumes existing bars/mutation and curated props：

```ts
bars: BarData[]
mutation: MarketSeriesMutation
period: MarketFrequency
seriesKind: SeriesKind
visibleMainIndicators: MainIndicatorId[]
alertMarkers: KlineMarker[]
rangeDetectorSourceIdentity: string
rangeDetectorAnchorTime: string | null
```

它统一处理 replace/prepend/live、回到最新、向左加载、全屏和 focus；不决定具体视角允许哪些 indicator/marker。

- [ ] **Step 1: 写 Free 三事实和无 Marker 测试**

```ts
test('free view exposes identity facts and never strategy markers', () => {
  const model = buildFreeDetailViewModel(fixture)
  assert.deepEqual(model.facts.map((item) => item.label), ['当前序列', '当前周期', '数据状态'])
  assert.equal(model.history.length, 0)
})
```

- [ ] **Step 2: 写 view marker 白名单测试**

在 `marketDetailMarkers.test.ts` 冻结：

```ts
assert.deepEqual(markersForDetailView('free', allMarkers), [])
```

- [ ] **Step 3: 实现 Free ViewModel**

三块：

```text
指标设置（默认展开）
市场背景
数据详情
```

Range 不可用必须显示原因，不得改写为关闭或正常。

- [ ] **Step 4: 实现 Free Workspace**

迁移现有能力：

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

不初始化 Alert event loader，不显示任何策略 Marker。

- [ ] **Step 5: 对照牛哇处理图表控制图标**

图表右上控制只保留高频：

```text
全屏 icon
回到最新 icon+文字（离开最新后才显示）
设置 icon
```

周期仍使用文字 Chip；不把 `1m/5m/15m` 改成无意义图标。

- [ ] **Step 6: E2E 覆盖 Range 和 contract 切换**

至少断言：

```text
view=free 不出现 HTDY/SuBing/Newow Marker
Range warm-up 状态正确
contract 切换品种后回 actual_dominant 并提示
视角设置写入 free，不改变 htdy
1280×800 Free with Range baseline
```

- [ ] **Step 7: 运行验证**

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
```

- [ ] **Step 8: 提交**

```bash
git add apps/quant-web/src/components/market/detail \
  apps/quant-web/src/utils/freeDetailViewModel.ts \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/tests \
  apps/quant-web/e2e

git commit -m "feat(web): add free market detail workspace"
```

---

# Slice B2 — 火天大有只读迁移

## Task 8: 实现 HTDY 双事实 Workspace

**Files:**
- Create: `apps/quant-web/src/utils/htdyDetailViewModel.ts`
- Test: `apps/quant-web/tests/htdyDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyDetailWorkspace.vue`
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify E2E: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

扩展 persistent loader：

```ts
export interface PersistentAlertMarkerOptions {
  fetchEvents: typeof getAlertEvents
  resolveRuleCodes?: (identity: AlertMarkerIdentity) => AlertRuleCode[]
}

return {
  markers: Readonly<Ref<KlineMarker[]>>,
  events: Readonly<Ref<AlertEvent[]>>,
  sync,
  dispose,
}
```

HTDY 调用只返回 `[ALERT_RULE_CODES.HTDY]`，SuBing 后续只返回 `[ALERT_RULE_CODES.SUBING_THS]`。

```ts
export function buildHtdyDetailViewModel(input: {
  identity: MarketDetailIdentity
  rawObservation: KlineMarker | null
  events: readonly HtdyAlertEvent[]
  alertRules: readonly ProductAlertRuleState[]
  runtimeStatus: AlertRuntimeStatus | null
  alertUnavailable: boolean
}): DetailViewModel
```

- [ ] **Step 1: 写原始观察与 Event 分离测试**

```ts
test('htdy keeps repainting observation separate from immutable event', () => {
  const model = buildHtdyDetailViewModel({
    ...fixture,
    rawObservation: rawBuyObservation,
    events: [savedSellEvent],
  })
  assert.equal(model.facts[0].value, '买观察')
  assert.match(model.facts[1].value, /卖出观察/)
  assert.notEqual(model.facts[0].source, model.facts[1].source)
})
```

- [ ] **Step 2: 写降级测试**

覆盖：

```text
Alert API 失败但 raw observation 可见
HTDY display 失败但 Event 可见
Runtime degraded 明确显示
无 Event 显示暂无，不改写成中性
```

- [ ] **Step 3: 扩展 persistent loader 并保持原测试通过**

不得改变去重身份：

```text
rule_code + symbol + frequency + bar_end
```

event list 和 marker list 必须来自同一个内部 Map，顶部历史和图上 Marker 不得各自请求一套。

- [ ] **Step 4: 实现 HTDY Workspace**

主图白名单：

```text
htdy
可选 EMA10/21/60
可选 Range
HTDY raw markers
HTDY AlertEvent markers
```

必须排除 SuBing Event，即使 API 返回混合 Event。

- [ ] **Step 5: 图标视觉处理**

- 原始观察使用轻量形状 + 文字标签，不使用与 Event 相同图标。
- 已保存 Event 使用实心事件徽标或方形，保留 Tooltip 标题“首次识别事件”。
- 重绘警示使用 warning icon + 完整文字。
- 预警入口使用 alert icon；未具备控制权限时不显示按钮，不显示灰色假铃铛。

- [ ] **Step 6: E2E 覆盖双事实与历史复用**

断言：

```text
raw observation 和 persisted event 同时存在但标题/形状不同
历史入口与图表 marker 数量来自同一响应
Alert API unavailable 时不本地补 Event
1440×900 Htdy ready baseline
```

- [ ] **Step 7: 运行验证**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/htdyDetailViewModel.test.ts \
  tests/alertMarkers.test.ts \
  tests/usePersistentAlertMarkers.test.ts \
  tests/htdyGoldenSample.test.ts \
  tests/kline-view-model.test.ts
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "HTDY"
```

- [ ] **Step 8: 提交**

```bash
git add apps/quant-web/src/components/market/detail/htdy \
  apps/quant-web/src/utils/htdyDetailViewModel.ts \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/tests \
  apps/quant-web/e2e

git commit -m "feat(web): add HTDY detail workspace"
```

---

# Slice B3 — Alert Scope 控制（Lane 3）

## Task 9: 泛化精确 Rule 控制并在失败后读回

**Lane:** Lane 3；本 Task 在独立 Sol/高推理会话中先 Plan-only。没有用户批准不得实现。

**Files:**
- Modify: `apps/quant-web/src/composables/useProductAlertScope.ts`
- Create: `apps/quant-web/src/components/market/detail/MarketDetailAlertControl.vue`
- Modify or retire after consumers move: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Test: `apps/quant-web/tests/productAlertScope.test.ts`
- E2E route-intercept only: `apps/quant-web/e2e/market-detail.spec.mjs`

**Interfaces:**

```ts
function toggleRuleCurrentFrequency(
  ruleCode: AlertRuleCode,
  enabled: boolean,
): Promise<void>
```

前置验证：

```text
Rule 必须存在于当前服务端响应
rule_code 必须在固定 registry
当前 frequency 必须属于该 Rule persistentFrequencies
当前 symbol/frequency 与发起请求时完全一致
同 Rule 不得并发保存
```

失败行为：

```text
显示“Alert Scope 更新失败”
立即重新读取当前 symbol 的 Rule 状态
旧 generation 的 readback 丢弃
不保留乐观开关状态
```

- [ ] **Step 1: 先写 Lane 3 Plan packet 并请求用户批准**

Packet 必须列出：精确 endpoint、请求体、fake 测试、失败 readback、无真实调用、独立 Review。未批准时停止。

- [ ] **Step 2: 写失败 readback 测试**

```ts
test('failed exact scope mutation reads server truth back', async () => {
  const calls: string[] = []
  const scope = useProductAlertScope(fakeDependencies({
    mutate: async () => { calls.push('put'); throw new Error('blocked') },
    fetch: async () => { calls.push('get'); return serverDisabledState },
  }))
  await scope.toggleRuleCurrentFrequency(ALERT_RULE_CODES.SUBING_THS, true)
  assert.deepEqual(calls, ['put', 'get'])
  assert.equal(scope.alertRules.value[1].enabled_for_product, false)
})
```

- [ ] **Step 3: 实现 generic mutation**

删除 HTDY-only 分支，但不改变后端 endpoint 或 Rule authority。组件明确显示：

```text
rule_code
symbol
frequency
服务端 enabled/scope 状态
Runtime 状态
```

- [ ] **Step 4: E2E 只使用 route intercept**

覆盖成功、失败、身份切换中响应、重复点击。测试不得连接真实 API/DB/Runtime。

- [ ] **Step 5: 运行验证**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/productAlertScope.test.ts \
  tests/alertRuleOwnership.test.ts \
  tests/alerts.test.ts
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "Alert control"
```

- [ ] **Step 6: 独立 Lane 3 Review**

必须检查：

```text
无批量 Scope
无默认启用
无 optimistic success
无 unknown Rule fallback
无真实请求证据
无 token/topic 暴露
```

- [ ] **Step 7: 提交并停在 Draft PR**

```bash
git add apps/quant-web/src/composables/useProductAlertScope.ts \
  apps/quant-web/src/components/market/detail/MarketDetailAlertControl.vue \
  apps/quant-web/src/components/market/ProductAlertRules.vue \
  apps/quant-web/tests/productAlertScope.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs

git commit -m "feat(web): control exact alert rule scope"
```

即使代码进入 `develop`，也不授权点击真实生产开关或修改 production Scope。

---

# Slice C — 新苏冰专用视角

## Task 10: 暴露固定 per-rule Runtime 状态和 SuBing 纯 ViewModel

**Files:**
- Modify: `apps/quant-web/src/api/runtime.ts`
- Modify: `apps/quant-web/src/api/alerts.ts`
- Create: `apps/quant-web/src/utils/subingDetailViewModel.ts`
- Test: `apps/quant-web/tests/subingDetailViewModel.test.ts`
- Test modify: `apps/quant-web/tests/alerts.test.ts`
- Test modify: `apps/quant-web/tests/runtime.test.ts` if present; otherwise create `apps/quant-web/tests/runtimeHealthTypes.test.ts`

**Interfaces:**

```ts
export interface RuntimeAlertRuleStatus {
  last_evaluated_bar_at: string | null
  last_event_at: string | null
  last_failure_at: string | null
  error_type: string | null
}

export type RuntimeAlertRuleStatusMap = Record<AlertRuleCode, RuntimeAlertRuleStatus>
```

`RuntimeAlertHealth` 增加 `rule_status`，normalizer 只接受固定 HTDY/SuBing keys 和固定字段；损坏时把该 rule 投影为不可用，不把全局 heartbeat 冒充 rule 已评估。

```ts
export function buildSubingDetailViewModel(input: {
  identity: MarketDetailIdentity
  events: readonly SubingThsAlertEvent[]
  rule: ProductAlertRuleState | null
  runtime: RuntimeAlertHealth | null
  alertUnavailable: boolean
}): DetailViewModel
```

- [ ] **Step 1: 写 Event-only authority 测试**

```ts
test('subing has no synthetic direction when no AlertEvent exists', () => {
  const model = buildSubingDetailViewModel({
    ...fixture,
    events: [],
  })
  assert.equal(model.facts[0].value, '暂无')
  assert.equal(model.history.length, 0)
  assert.doesNotMatch(JSON.stringify(model), /偏多|偏空|中性/)
})
```

- [ ] **Step 2: 写 per-rule health 语义测试**

覆盖：

```text
全局 heartbeat fresh、SuBing last_evaluated=null → 不能显示已正常评估
Rule disabled 与 Runtime failed 分开展示
notification_attempted_at 与 provider accepted/送达分开
unknown rule_status key 被拒绝或忽略，不能显示
```

- [ ] **Step 3: 实现严格 Runtime 映射**

不修改后端 schema；只读取当前后端已存在的固定 `rule_status`。若执行时后端 wire 与本文不一致，停止并核对 active canonical。

- [ ] **Step 4: 实现 SuBing ViewModel**

三事实：

```text
最新预警
信号 K 线
预警状态
```

三折叠块：

```text
最新预警
触发规则
运行与通知
```

触发规则文案固定为：

```text
S↑：MACD 金叉且 Close > EMA21
S↓：MACD 死叉且 Close < EMA21
```

不得加入零轴、量能/OI、Range、ATR、周期共振、评分或三根确认。

- [ ] **Step 5: 运行测试**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/alerts.test.ts \
  tests/runtimeHealthTypes.test.ts
```

- [ ] **Step 6: 提交**

```bash
git add apps/quant-web/src/api \
  apps/quant-web/src/utils/subingDetailViewModel.ts \
  apps/quant-web/tests

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
- Modify: `apps/quant-web/src/components/kline/KlineChart.vue` only for marker selection seam
- Modify tests: `apps/quant-web/tests/marketDetailMarkers.test.ts`
- Modify E2E: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify E2E: `apps/quant-web/e2e/market-home.spec.mjs`

**Interfaces:**

```ts
export function markersForDetailView(
  view: MarketDetailView,
  markers: readonly KlineMarker[],
): KlineMarker[]
```

规则：

```text
subing → alertRuleCode === SUBING_THS
htdy → raw HTDY + alertRuleCode === HTDY
free → []
trend → only Newow typed markers, not KlineMarker Alert events
```

- [ ] **Step 1: 写 Marker 隔离失败测试**

```ts
test('subing only renders immutable SuBing AlertEvent markers', () => {
  assert.deepEqual(
    markersForDetailView('subing', [htdyEventMarker, subingEventMarker, rawHtdyMarker]),
    [subingEventMarker],
  )
})
```

- [ ] **Step 2: 实现固定图层**

SuBing 只显示：

```text
15m Kline
EMA21
S↑ / S↓ AlertEvent Marker
成交量
MACD
```

不显示 EMA10、EMA60、Range、HTDY、Newow 或本地推导 Marker。

- [ ] **Step 3: 实现历史列表和详情抽屉**

历史项直接来自同一个 Event Map，显示：

```text
S↑/S↓
bar_end
detected_at
physical contract
notification_attempted_at
```

点击历史项：

```text
revealTime(bar_end)
followLatest=false
打开同一个 Event 详情抽屉
```

- [ ] **Step 4: 实现事件 Marker 点击**

为 `KlineChart` 增加：

```ts
const emit = defineEmits<{
  'marker-select': [marker: KlineMarker]
}>()
```

点击时只按现有 marker `id` 在当前白名单中解析；未知 id 不打开抽屉。不要把 Tooltip 文案反解析成 identity。

- [ ] **Step 5: 图标参考处理**

- `S↑` 使用上箭头形状 + “多头预警”文字；红色。
- `S↓` 使用下箭头形状 + “空头预警”文字；绿色。
- 历史入口使用 history icon。
- 运行异常使用 warning icon；数据不足使用已有灰色状态圆标。
- 不给 MACD/EMA21 添加无来源的装饰图标。

- [ ] **Step 6: 切换首页 Event 深链**

只把 SuBing Event 链接更新为：

```text
view=subing
series_kind=actual_dominant
frequency=15m
focus_bar_end=event.bar_end
```

普通品种入口仍等最终 Slice E，不提前默认 Trend。

- [ ] **Step 7: E2E 覆盖**

必须覆盖：

```text
首页 SuBing Event → view=subing → exact bar
focus 消费后 URL 移除 focus_bar_end
定位后不跳回最新
无 Event 不出现方向
HTDY Event 不出现在 SuBing 图
1440×900 SuBing event baseline
390×844 SuBing history drawer baseline
Alert API unavailable baseline
Runtime degraded baseline
```

- [ ] **Step 8: 运行验证**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketHomeRoute.test.ts \
  tests/alertMarkers.test.ts
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs \
  e2e/market-home.spec.mjs
```

- [ ] **Step 9: 提交**

```bash
git add apps/quant-web/src/components/market/detail/subing \
  apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/pages/market \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/tests \
  apps/quant-web/e2e

git commit -m "feat(web): add SuBing detail workspace"
```

---

# Slice D — 趋势策略视角（等待 Newow 只读 API）

## Task 12: 执行 Newow 上游合同 Gate

**This task is fail-closed and may end without code changes.**

**Read:**
- `docs/tasks/2026-09-01-newow-trend-v1-design.md`
- `docs/tasks/2026-09-01-newow-trend-v1-implementation-plan.md`
- `docs/tasks/2026-09-02-newow-slice-b-cup-handle-engine-design.md`
- 执行时最新 Newow Slice B/C Spec、PR、OpenSpec 和 API 实现
- `packages/quant-core/guiyi_quant/newow/`
- `services/quant-api/app/` 中已进入 `develop` 的 Newow read-only service/API

**Required evidence before proceeding:**

```text
NewowTrendD1Engine 已进入 develop
cup_handle + engine 因果/restore/rollover 测试通过
actual_dominant completed D1 只读 service 已进入 develop
只读 API endpoint 与 DTO 已冻结
API 不计算于 Web、不写 DB/Redis、不接 Alert/Runtime
真实 endpoint、request、response、错误码可从代码/OpenSpec读出
```

- [ ] **Step 1: 在执行时最新 develop 做只读 preflight**

```bash
test -f packages/quant-core/guiyi_quant/newow/engine.py
rg -n "NewowTrendD1Engine|newow_trend_v1" \
  services/quant-api/app \
  services/quant-api/tests \
  openspec/specs \
  docs/tasks
```

- [ ] **Step 2: 核对 exact endpoint/DTO**

记录：

```text
endpoint path
query parameters
series_kind/frequency/completed policy
response schema
marker types
rollover facts
error status and public codes
maximum result size / paging contract
```

- [ ] **Step 3: 不满足时停止**

输出唯一结论：

```text
BLOCKED_NEWOW_READ_API
```

不得猜 endpoint，不得在 Web 复制 Newow 公式，不得为了完成详情页临时创建浏览器计算 fallback。

- [ ] **Step 4: 满足时记录 exact dependency commit**

在 Slice D PR body 写入：

```text
Newow dependency develop commit
Newow API/OpenSpec path
targeted backend test evidence
```

然后才执行 Task 13。

---

## Task 13: 实现 Newow wire normalizer、Trend Workspace 和独立主图

**Files:**
- Create: `apps/quant-web/src/types/newow.ts`
- Create: `apps/quant-web/src/api/newow.ts`
- Create: `apps/quant-web/src/utils/newowTypes.ts`
- Test: `apps/quant-web/tests/newowTypes.test.ts`
- Create: `apps/quant-web/src/utils/trendDetailViewModel.ts`
- Test: `apps/quant-web/tests/trendDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/trend/TrendDetailWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify E2E: `apps/quant-web/e2e/market-detail.spec.mjs`
- Update OpenSpec only if upstream contract requires a presentation requirement, not formula changes

**Interfaces:**

前端 normalizer 的稳定输出：

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

`getNewowTrendDetail()` 的 URL、参数和 wire 字段必须逐字采用 Task 12 读出的 accepted API；本计划不授权发明第二 endpoint。

```ts
export function buildTrendDetailViewModel(input: {
  identity: MarketDetailIdentity
  result: NewowTrendDetailModel | null
  unavailable: boolean
}): DetailViewModel
```

- [ ] **Step 1: 写 strict wire normalizer 测试**

覆盖：

```text
strategy/profile/series/frequency exact identity
symbol mismatch
naive timestamp
frame order/duplicate
unknown marker type
rollover segment mismatch
Decimal/string numeric normalization
invalid payload fail-closed
```

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/newowTypes.test.ts
```

- [ ] **Step 3: 实现 API client 和 normalizer**

Web 只映射 API 结果，不导入 Python formula、不重算黄蓝、D123、杯柄或 BUILD/CLEAR。

- [ ] **Step 4: 写 Trend ViewModel 测试**

三事实：

```text
趋势状态：建仓/持有/清仓/空仓
风险标记：D1/D2/D3/无
杯柄状态：形成/就绪/突破/走弱/失效/过期/无
```

固定 banner：

```text
建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。
```

不可用时三事实都显示不可用，不能根据基础 Kline 猜趋势。

- [ ] **Step 5: 实现独立 NewowTrendChartStage**

使用 Lightweight Charts 作为渲染器，但只消费 Newow API 结果。层级：

```text
Kline/grid
黄蓝趋势带
杯柄轮廓与柄部区间
BUILD/CLEAR Marker
D1/D2/D3 Marker
crosshair/selection
主力换月分界
成交量 pane
```

不使用当前 `ResearchOverlayId`，不把 Newow 加进 `visibleMainIndicatorsForOverlay()`。

- [ ] **Step 6: 实现 Trend Workspace 和历史**

历史源与图上 Marker 来自同一 Newow result。点击历史定位图表并打开 Marker 详情。不得称为 AlertEvent，不显示通知状态。

- [ ] **Step 7: 图标参考处理**

- Trend 状态优先使用文字 + Newow 专属带色，不用通用买卖箭头误导为订单。
- D1/D2/D3 可用紧凑风险徽标，仍保留 `D1/D2/D3` 文本。
- 杯柄状态使用结构/状态小图标只作为辅助，不能隐藏“就绪、突破、失效”等文字。
- 主力换月使用 `contract-switch` icon + 合约文字，不用闪电/交易机会图标。

- [ ] **Step 8: E2E 覆盖**

```text
Trend fixed identity
Newow unavailable no Web fallback
BUILD/CLEAR/D123/cup marker isolation
rollover boundary visible
history and marker same facts
1920×1080 Trend ready baseline
390×844 Trend baseline
```

- [ ] **Step 9: 运行验证**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowTypes.test.ts \
  tests/trendDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs \
  e2e/market-detail.spec.mjs --grep "Trend"
```

若本 Slice 修改了后端只读接口映射或 OpenSpec，再运行上游 Newow targeted backend tests、Ruff、Mypy、OpenSpec；不得执行真实数据写入。

- [ ] **Step 10: 提交**

```bash
git add apps/quant-web/src/api/newow.ts \
  apps/quant-web/src/types/newow.ts \
  apps/quant-web/src/utils/newowTypes.ts \
  apps/quant-web/src/utils/trendDetailViewModel.ts \
  apps/quant-web/src/components/market/detail/trend \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/tests \
  apps/quant-web/e2e

git commit -m "feat(web): add Newow trend detail workspace"
```

---

# Slice E — 最终切换、旧面删除和全面验收

## Task 14: 实现主力换月分界和统一 Marker 选择交互

**Files:**
- Create: `apps/quant-web/src/utils/contractBoundaries.ts`
- Test: `apps/quant-web/tests/contractBoundaries.test.ts`
- Create: `apps/quant-web/src/components/kline/contractBoundaryPrimitive.ts`
- Test: `apps/quant-web/tests/contractBoundaryPrimitive.test.ts`
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

- [ ] **Step 1: 写 boundary 纯函数测试**

```ts
test('actual dominant boundaries are emitted only on physical contract change', () => {
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

连续序列没有 physicalContract 时返回空；缺失后又出现或非法回退时 fail-closed，不猜边界。

- [ ] **Step 2: 实现低干扰 vertical primitive**

分界样式：细虚线、中性灰、顶部合约文字；hover/详情说明“物理合约所有权切换”，不使用上涨/下跌色。

- [ ] **Step 3: 统一 Marker 点击**

KlineChart 和 NewowTrendChartStage 都将当前渲染 Marker 的稳定 ID 映射到 typed detail item；未知、过期或其他视角 ID 拒绝。

- [ ] **Step 4: 运行测试/build**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/contractBoundaries.test.ts \
  tests/contractBoundaryPrimitive.test.ts \
  tests/marketDetailMarkers.test.ts
pnpm --dir apps/quant-web build
```

- [ ] **Step 5: 提交**

```bash
git add apps/quant-web/src/utils/contractBoundaries.ts \
  apps/quant-web/src/components/kline \
  apps/quant-web/src/components/market/detail \
  apps/quant-web/tests

git commit -m "feat(web): show contract boundaries and marker details"
```

---

## Task 15: 完成最终 route cutover 并删除旧详情面

**Files:**
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Delete: `apps/quant-web/src/pages/market/LegacyMarketChart.vue`
- Modify: `apps/quant-web/src/utils/marketDetailRoute.ts`
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Delete after reference audit: `apps/quant-web/src/components/market/ProductWorkspaceToolbar.vue`
- Delete after reference audit: `apps/quant-web/src/components/market/ProductCheckSidebar.vue`
- Delete after replacement/reference audit: `apps/quant-web/src/components/market/ProductAlertRules.vue`
- Delete after reference audit: obsolete legacy preference functions/files only when `rg` proves no consumers
- Modify current tests/E2E that still assert old toolbar/sidebar

**Precondition:** Trend、HTDY、SuBing、Free 四个 explicit routes 已全部通过各自 Slice Gate。

- [ ] **Step 1: 写缺省 Trend 失败测试**

```ts
test('missing view defaults to trend only after final cutover', () => {
  assert.deepEqual(resolveFinalMarketDetailIdentity({ symbol: 'jm' }), {
    view: 'trend', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '1d',
  })
})
```

- [ ] **Step 2: 原子切换入口**

同一 commit 完成：

```text
chart.vue 永远挂 MarketDetailPage
无 view → Trend
首页普通品种 → view=trend
首页 HTDY Event → view=htdy
首页 SuBing Event → view=subing
旧 overlay query 不再控制视角
```

旧 URL 带 `overlay=htdy` 但无 `view` 不自动恢复 HTDY；显示 Trend。只有新显式 Event 深链进入 HTDY。

- [ ] **Step 3: 关闭所有旧 active references**

```bash
rg -n "LegacyMarketChart|ProductWorkspaceToolbar|ProductCheckSidebar|product-status-strip|researchSidebarOpen" \
  apps/quant-web/src apps/quant-web/tests apps/quant-web/e2e
```

只有零 active reference 后才删除旧文件；不保留 `legacy-copy` 或 archive。

- [ ] **Step 4: 收敛旧 preference 和 overlay surface**

- 保留仍被通用图表使用的 indicator definitions。
- 删除仅服务旧页面的 selectedOverlay/workspace sidebar preference，前提是引用为零。
- 不删除 HTDY 计算、Range、EMA、MACD 等 active primitive。

- [ ] **Step 5: 更新所有 route/E2E 断言**

旧详情页测试要迁移到四视角，不通过跳过/删除测试掩盖能力回归。

- [ ] **Step 6: 运行 Web 全量验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

- [ ] **Step 7: 提交**

```bash
git add -A apps/quant-web

git commit -m "feat(web): cut over unified market detail page"
```

---

## Task 16: 完成牛哇视觉、图标、响应式和无障碍验收

**Files:**
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create/update: `apps/quant-web/e2e/market-detail.spec.mjs-snapshots/*`
- Modify as findings require: detail components/tokens only

- [ ] **Step 1: 生成冻结快照矩阵**

必须包含：

```text
1920×1080 Trend ready
1440×900 Htdy ready
1440×900 SuBing event
1280×800 Free with Range
390×844 Trend
390×844 SuBing history drawer
非法身份
视角数据 unavailable
Alert API unavailable
Runtime degraded
```

- [ ] **Step 2: 逐区与牛哇真实页面并列 Review**

逐项检查：

```text
顶部留白
价格字号和涨跌层级
策略 Tab/Chip
警示条
三事实横向节奏
展开区箭头和图标
卡片圆角与分隔线
主图起始位置
图表操作图标
历史/预警/更多入口
移动端底部抽屉
```

不比较牛哇的股票专属字段、综合分、建议仓位、目标价或私有策略结果。

- [ ] **Step 3: 图标机会终审**

对每个 icon-bearing surface 给出结论：

```text
牛哇有图标且语义明确 → clean-room icon + label/tooltip
牛哇有图标但属于品牌/私有算法 → 不复制；改用通用语义图标或文字
牛哇无图标且文字更清楚 → 保持文字
核心交易语义 → 文字必须保留，图标只能辅助
```

禁止 emoji 充当产品图标；禁止为“更丰富”而给每个标题加装饰 icon。

- [ ] **Step 4: 无障碍 E2E**

覆盖：

```text
Tab ArrowLeft/ArrowRight
Accordion Enter/Space
Drawer focus trap/restore
icon-only button accessible name
红绿状态的文字/形状替代
移动端 44×44 target
prefers-reduced-motion
Marker 历史列表替代
```

- [ ] **Step 5: 截图差异修复后重新全量运行**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

不得只更新 snapshot 来吞掉意外布局变化；每次 baseline 变化都要在 PR 说明原因。

- [ ] **Step 6: 提交**

```bash
git add apps/quant-web/e2e \
  apps/quant-web/src/components/market/detail \
  apps/quant-web/src/styles/tokens.css

git commit -m "test(web): freeze unified detail visual contract"
```

---

## Task 17: 同步 active canonical、验证并进行独立 Review

**Files:**
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md` only for stable long-term unified detail decision
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`
- Create or modify: appropriate `openspec/specs/market-*` detail requirements; use execution-time canonical structure
- Do not modify: `STATUS.md` unless真实 release/Runtime事实在另一个授权任务中发生变化

- [ ] **Step 1: 更新稳定产品面**

`PROJECT_SOURCE.md` 应从旧的 `none | htdy` 详情表达收敛为：

```text
统一 Market 详情页
四个互斥视角
Trend/Newow、HTDY、SuBing Event、Free 通用指标各自 authority
无订单/账户/自动晋升
```

不得把尚未 release/Runtime 的状态写成生产事实。

- [ ] **Step 2: 更新架构和测试导航**

依赖图要明确：

```text
MarketDataService → shared detail bars/header
Newow read API → Trend Workspace
HTDY display kernel + AlertEvent → HTDY Workspace
AlertEvent → SuBing Workspace
Generic indicators → Free/HTDY/SuBing review layers
```

- [ ] **Step 3: 执行完整验证**

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

若 Slice D 涉及 Newow API 文件，再运行其 accepted targeted backend tests、Ruff 和 Mypy。若必要检查无法运行，只报告阻塞，不声明完成。

- [ ] **Step 4: 进行两个独立 Review 轴**

Review A — 产品/视觉/无障碍：

```text
牛哇参考准确性
图标位置和语义
首屏信息节奏
移动端
无假按钮/综合分/仓位建议
```

Review B — authority/身份/回归：

```text
四视角互斥
Newow API-only
SuBing Event-only
HTDY dual-fact
stale/generation
route/focus
无 Scope/Runtime/生产越权
```

- [ ] **Step 5: 修复发现并重跑受影响到全量验证**

不得仅在 PR 文案中接受 Critical/Important finding。

- [ ] **Step 6: 最终提交**

```bash
git add PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md TESTING.md openspec \
  apps/quant-web

git commit -m "docs(market): canonicalize unified detail surface"
```

- [ ] **Step 7: 停在用户 Gate**

最终只允许输出：

```text
CODE_COMPLETE
TEST_COMPLETE
VISUAL_REVIEW_READY
```

然后等待用户审查截图和 PR，只有用户明确给出：

```text
允许集成 develop
```

才合入。不得发布 `main`、创建 tag、切换 Runtime 或执行真实通知/Scope。

---

## 3. 全局验收映射

| Spec 要求 | 实施任务 |
|---|---|
| 统一外壳、四视角互斥 | Task 1、6、15 |
| 顶部渐进披露 | Task 4、5 |
| 牛哇视觉与图标参考 | Task 3、5、7、8、11、13、16 |
| 图标 clean-room 和无障碍 | Task 3、16 |
| Trend fixed identity/API-only | Task 1、12、13 |
| HTDY 双事实 | Task 8 |
| SuBing Event-only | Task 10、11 |
| Free 通用能力 | Task 7 |
| Alert exact Scope | Task 9（Lane 3） |
| route/focus/deep link | Task 1、11、15 |
| 旧页不中断、最终删除 | Task 6、15 |
| 主力换月分界 | Task 14 |
| 桌面/移动端/Drawer | Task 5、16 |
| loading/stale/generation | Task 4、6、8、10、13 |
| canonical/全量验证 | Task 17 |

---

## 4. 计划自审记录

### 4.1 Spec coverage

已逐节核对 Spec 第 1–32 节；每项产品、身份、事实、交互、视觉、无障碍、偏好、错误和验收要求均映射到 Task 1–17。Newow API 尚未进入 active `develop` 的不确定性被 Task 12 明确设为 fail-closed dependency Gate，没有推测 endpoint 或 wire。

### 4.2 Placeholder scan

本计划不包含待补参数、虚构 API、空组件或“按类似任务处理”。临时 `LegacyMarketChart` 是明确的过渡实现，具有创建、验证和删除任务，不属于永久兼容层。

### 4.3 Type consistency

下列类型在全计划中保持一致：

```text
MarketDetailView
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

本计划没有把上游 Newow Formula/API 开发吞入 Web 详情任务。Alert Scope mutation 单独拆为 Lane 3；其余 Slice 为 Lane 2。所有真实外部操作继续由独立 Gate 管理。

---

## 5. 当前计划状态

```text
SPEC_APPROVED_BY_USER
ICON_REFERENCE_AMENDMENT_APPROVED
IMPLEMENTATION_PLAN_INTERNAL_REVIEW_PASSED
IMPLEMENTATION_PLAN_USER_REVIEW_PENDING
SOURCE_IMPLEMENTATION_NOT_STARTED
PRODUCTION_MUTATION_NOT_AUTHORIZED
MAIN_TAG_RELEASE_RUNTIME_NOT_AUTHORIZED
```

用户批准本计划后，只授权从 **Slice A** 开始；不授权一次性连续执行 Slice B–E，也不授权自动集成 `develop`。
