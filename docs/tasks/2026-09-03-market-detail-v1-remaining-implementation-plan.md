# Market 统一详情页 V1 剩余部分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务执行；每个源码 Slice 使用独立会话、branch/worktree、Draft PR 和 exact-head Review。步骤使用 checkbox（`- [ ]`）跟踪。

**Goal:** 在 Slice A 与 Slice B1 基础上，按 `B2 HTDY → D Trend → C SuBing → E Final Cutover` 串行完成统一 `/market/chart` 的四个只读 Workspace，并删除旧详情页。

**Architecture:** 共享 Shell 只管理 route、identity、generic Market bars、行情头、focus 和错误边界；HTDY、Newow、SuBing 分别消费自己的只读 authority，使用独立 ViewModel、Marker 白名单和 Workspace。任何 authority 失败都只降级自身，不在浏览器补算正式结果。

**Tech Stack:** Vue 3.5、TypeScript 6、Vue Router 5、Naive UI 2.44、Lightweight Charts 5.2、Node `node:test`、Playwright、Vite 8、现有 FastAPI Market/Newow/Alert/Runtime typed API。

**Spec:** `docs/tasks/2026-09-03-market-detail-v1-remaining-design.md`

## Global Constraints

- 执行前必须重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、本 Spec、本 Plan 和任务相关 OpenSpec/PR。
- 当前源代码前置 Gate 是 PR #327 合入 `develop`；不得从 `feature/market-detail-free` 继续开发 B2。
- 严格顺序：`B1 owner Gate → B2 → D → C → E`。不得并行修改共享 Shell、`MarketDetailPage.vue`、`KlineChart.vue` 或同一 E2E。
- 四个 View 固定为 `trend | htdy | subing | free`，任一时刻只有一个 Workspace 控制主图、Marker、摘要和历史。
- Trend 固定 `actual_dominant + completed 1d`；SuBing 固定 `actual_dominant + completed 15m`；HTDY/Free 只接受 Spec 的合法序列与周期。
- Newow 正式结果只能来自 `GET /api/v1/market/newow/trend-detail`；SuBing 正式 `S↑/S↓` 只能来自 `AlertEvent`；HTDY raw 与 immutable Event 必须分开。
- 若 Newow 专用旧文档与本 Spec/Plan 在 Web route、Shell 或组件路径上冲突，以本 Spec/Plan 为准；Newow 公式、Kernel、Engine、API 与因果合同仍以专用文档和代码为准。
- Free Marker 恒为 0；Range Detector 只读，不拥有策略或 Alert 语义。
- 不输出综合分、胜率、仓位建议、目标价、吸筹价、止损价、订单、账户、持仓、保证金或 PnL。
- V1 不实现 Alert Scope mutation；不得调用 `setAlertProductFrequencyEnabled()`。
- 不修改 HTDY、SuBing、Newow 公式，不在 Web 复制正式公式。
- 不新增 DB、migration、Redis key、queue、worker、Runtime 或通知路径。
- 不连接真实 RQData、production PostgreSQL/Redis，不发送通知，不切换 Runtime。
- 不触及 `main`、tag、Release；源码 Slice 只集成到 `develop`。
- 每个 Slice 从执行时最新 clean `develop` 创建独立 task worktree；Draft PR 通过定向/完整验证和独立 Review 后，等待用户明确“允许集成 develop”。
- 使用中国期货红涨绿跌，同时保留文字、方向或形状；状态不得只依赖颜色。
- 移动端交互目标不小于 44×44 CSS px；icon-only 按钮必须有中文 `aria-label`。
- 任何必要验证失败时停止并报告，不得声明 Slice Ready。
- `CODE_COMPLETE`、`TEST_COMPLETE`、`RELEASED`、`RUNTIME_READY` 必须分别声明。

---

## 0. 基线与调度矩阵

### 0.1 当前事实

```text
develop = 1cc757e4519dabe06240635304cdccfe644cedc5
Slice A = 已进入 develop
Slice B1 = PR #327 Draft，head 3f0ccab8b415d15faf25f6baf27c37506d7ff629
Newow A/B/C = 已进入 develop
Newow read API = 已存在
production 0045 / v1.9.14 Runtime / 新 G10 / G9 = 均未完成
```

执行时必须重新读取这些事实，不能复用本快照替代 `STATUS.md`。

### 0.2 Slice 调度

| Slice | Lane | 模型 | 推理 | Plan | branch 建议 | Gate |
|---|---|---|---|---|---|---|
| B2 HTDY | Lane 2 | Terra | 中 | Plan-then-execute | `feature/market-detail-htdy` | 独立 Review + 用户允许集成 |
| D Trend | Lane 2 | Sol | 高 | Plan-then-execute | `feature/market-detail-trend` | API identity Review + 独立 Review + 用户允许集成 |
| C SuBing | Lane 2 | Sol | 高 | Plan-then-execute | `feature/market-detail-subing` | 独立 Review + 用户允许集成 |
| E Cutover | Lane 2 | Sol | 高 | Plan-then-execute | `feature/market-detail-cutover` | 独立 Review + 用户视觉批准 + 用户允许集成 |

每个 PR 合入 `develop` 并确认远端 commit 后，才清理对应 worktree 和 branch。

---

# Gate 0 — Slice B1 Owner Integration

这不是新的源码任务。开始 B2 前必须满足：

- [ ] PR #327 保持 mergeable，head 与用户审查的截图一致。
- [ ] 用户检查 1280×800 和 390px 基线。
- [ ] 用户明确给出“允许集成 develop”。
- [ ] PR #327 合入 `develop`。
- [ ] 新 `develop` 包含 B1 的 `MarketKlineStage`、Free Workspace、单一 identity surface 和测试。
- [ ] B2 从该最新 `develop` 创建，不从 PR #327 branch 派生。

若任一条件不满足，输出 `BLOCKED_B1_OWNER_GATE`，不得创建 B2 源码分支。

---

# Slice B2 — HTDY Workspace

## Task 1: 建立 Rule-filtered、同源 Event/Marker 只读投影

**Files:**
- Modify: `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
- Modify: `apps/quant-web/src/utils/alertMarkers.ts`
- Modify: `apps/quant-web/tests/alerts.test.ts`

**Interfaces:**

```ts
export type PersistentAlertReadStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'stale'
  | 'unavailable'

export interface PersistentAlertMarkerOptions {
  fetchEvents: (params: {
    symbol: string
    ruleCode: AlertRuleCode
    start: string
    end: string
  }) => Promise<AlertEventListResponse>
  resolveRuleCodes?: (
    identity: AlertMarkerIdentity,
  ) => readonly AlertRuleCode[]
  scheduleInterval?: (
    callback: () => void | Promise<void>,
    delayMs: number,
  ) => unknown
  clearInterval?: (handle: unknown) => void
}

export interface PersistentAlertMarkerProjection {
  markers: Readonly<Ref<KlineMarker[]>>
  events: Readonly<Ref<AlertEvent[]>>
  status: Readonly<Ref<PersistentAlertReadStatus>>
  sync(
    identity: AlertMarkerIdentity,
    bars: BarData[],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void>
  dispose(): void
}
```

默认 `resolveRuleCodes` 保持现有 `markerRuleCodes()` 行为；HTDY Workspace 必须传入只返回 `ALERT_RULE_CODES.HTDY` 的 resolver，SuBing 后续传入只返回 `ALERT_RULE_CODES.SUBING_THS` 的 resolver。

Event 与 Marker 必须从同一个内部 `Map<alertEventIdentityKey, AlertEvent>` 投影。

- [ ] **Step 1: 写 Rule isolation 失败测试**

```ts
test('HTDY projection fetches and exposes only HTDY events', async () => {
  const projection = usePersistentAlertMarkers({
    fetchEvents: fakeFetchEvents([htdyEvent, subingEvent]),
    resolveRuleCodes: () => [ALERT_RULE_CODES.HTDY],
  })

  await projection.sync(
    { seriesKind: 'actual_dominant', symbol: 'jm', frequency: '15m' },
    bars,
    'replace',
  )

  assert.deepEqual(
    projection.events.value.map((event) => event.rule_code),
    [ALERT_RULE_CODES.HTDY],
  )
  assert.ok(projection.markers.value.every(
    (marker) => marker.alertRuleCode === ALERT_RULE_CODES.HTDY,
  ))
})
```

- [ ] **Step 2: 写 stale/unavailable 失败测试**

覆盖：

```text
首次请求失败 -> status=unavailable，events/markers=[]
同 identity 已成功后刷新失败 -> 保留快照，status=stale
identity 改变 -> 立即清空旧 events/markers
旧 generation 响应 -> 丢弃
continuous/contract -> 不请求 persistent Event，返回 ready 空投影
prepend -> 只补缺失的左侧范围
refresh -> 只刷新 bounded recent window
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts
```

预期：新接口、Rule resolver 或 status 断言失败。

- [ ] **Step 4: 最小实现**

要求：

1. 将内部 Event `Map` 投影成 readonly `events`；
2. `markers` 只由 `events` 计算；
3. fetch response 中 Rule、symbol、frequency 不匹配的 Event 丢弃；
4. 失败时不伪造 ready；
5. 不改变 Event identity、去重或排序语义；
6. 不调用 Scope mutation；
7. 旧调用者不传 resolver 时保持兼容。

- [ ] **Step 5: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/alerts.test.ts
```

预期：0 failed。

- [ ] **Step 6: 提交**

```bash
git add \
  apps/quant-web/src/composables/usePersistentAlertMarkers.ts \
  apps/quant-web/src/utils/alertMarkers.ts \
  apps/quant-web/tests/alerts.test.ts
git commit -m "refactor(web): expose rule-filtered alert event projections"
```

---

## Task 2: 建立共享只读 Alert Context，严格映射 per-rule Runtime

**Files:**
- Modify: `apps/quant-web/src/api/runtime.ts`
- Create: `apps/quant-web/src/utils/runtimeHealthTypes.ts`
- Create: `apps/quant-web/tests/runtimeHealthTypes.test.ts`
- Create: `apps/quant-web/src/composables/useMarketDetailAlertContext.ts`
- Create: `apps/quant-web/tests/marketDetailAlertContext.test.ts`
- Read only: `apps/quant-web/src/api/alerts.ts`
- Do not modify: `apps/quant-web/src/composables/useProductAlertScope.ts`

**Interfaces:**

```ts
export interface RuntimeAlertRuleStatus {
  last_evaluated_bar_at: string | null
  last_event_at: string | null
  last_failure_at: string | null
  error_type: string | null
}

export type RuntimeAlertRuleStatusMap = Record<
  AlertRuleCode,
  RuntimeAlertRuleStatus
>

export interface NormalizedAlertRuntimeHealth {
  status: string
  configured_enabled: boolean
  last_heartbeat_at: string | null
  processing_state: string
  notification_state: string
  rule_status: RuntimeAlertRuleStatusMap
}

export function normalizeAlertRuntimeHealth(
  payload: unknown,
): NormalizedAlertRuntimeHealth

export type DetailReadStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'stale'
  | 'unavailable'

export interface MarketDetailAlertContext {
  symbol: Readonly<Ref<string | null>>
  rules: Readonly<Ref<ProductAlertRuleState[]>>
  rulesStatus: Readonly<Ref<DetailReadStatus>>
  runtime: Readonly<Ref<NormalizedAlertRuntimeHealth | null>>
  runtimeStatus: Readonly<Ref<DetailReadStatus>>
  load(symbol: string): Promise<void>
  dispose(): void
}
```

只允许 registry 中两条固定 Rule：

```text
htdy_original_15m
subing_ths_alert_15m_v1
```

未知 `rule_status` key、字段缺失、naive timestamp 或错误类型必须令对应 normalizer fail-closed。

- [ ] **Step 1: 写 strict runtime normalizer 失败测试**

```ts
test('normalizes only the two registry-owned rule statuses', () => {
  const value = normalizeAlertRuntimeHealth(runtimeFixture)
  assert.deepEqual(Object.keys(value.rule_status).sort(), [
    ALERT_RULE_CODES.HTDY,
    ALERT_RULE_CODES.SUBING_THS,
  ].sort())
})

test('rejects unknown rule status keys', () => {
  assert.throws(
    () => normalizeAlertRuntimeHealth({
      ...runtimeFixture,
      rule_status: {
        ...runtimeFixture.rule_status,
        legacy_rule: emptyRuleStatus,
      },
    }),
    /ALERT_RUNTIME_CONTRACT_INVALID/,
  )
})
```

- [ ] **Step 2: 写 generation 和快照隔离失败测试**

覆盖：

```text
load jm 后立即 load rb，jm 的晚到响应不得进入 rb
Rule 首次读取失败 -> rulesStatus=unavailable
Runtime 首次读取失败或缺少 rule_status -> runtimeStatus=unavailable
同 symbol 已成功后单项刷新失败 -> 只将该项标 stale 并保留该项快照
Rule 成功、Runtime 失败 -> Rule 事实仍可用
Runtime 成功、Rule 失败 -> Runtime 事实仍可用
切换 symbol -> 先清空旧 Rule 快照；Runtime 可以复用同一请求结果但不得携带旧 symbol Rule
rules 中未知 rule 或重复 rule -> Rule 投影 fail-closed
本 composable 不暴露 mutate/toggle/save
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/runtimeHealthTypes.test.ts \
  tests/marketDetailAlertContext.test.ts
```

- [ ] **Step 4: 实现 normalizer 和 read-only composable**

`useMarketDetailAlertContext()` 只调用：

```text
getProductAlerts(symbol)
getRuntimeHealth()
```

两项使用独立 settlement 和独立 status；一项失败不得令另一项不可用。

它不得导入或调用：

```text
setAlertProductFrequencyEnabled
useProductAlertScope
任何 activation API
```

- [ ] **Step 5: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/runtimeHealthTypes.test.ts \
  tests/marketDetailAlertContext.test.ts
```

- [ ] **Step 6: 提交**

```bash
git add \
  apps/quant-web/src/api/runtime.ts \
  apps/quant-web/src/utils/runtimeHealthTypes.ts \
  apps/quant-web/src/composables/useMarketDetailAlertContext.ts \
  apps/quant-web/tests/runtimeHealthTypes.test.ts \
  apps/quant-web/tests/marketDetailAlertContext.test.ts
git commit -m "feat(web): add read-only detail alert context"
```

---

## Task 3: 实现 HTDY ViewModel、Workspace 和单一 identity 控制

**Files:**
- Create: `apps/quant-web/src/utils/htdyDetailViewModel.ts`
- Create: `apps/quant-web/tests/htdyDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/htdy/HtdyDetailWorkspace.vue`
- Modify: `apps/quant-web/src/utils/marketDetailPreferences.ts`
- Modify: `apps/quant-web/tests/marketDetailPreferences.test.ts`
- Modify: `apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify only when marker selection requires: `apps/quant-web/src/components/kline/KlineChart.vue`
- Modify only when marker selection requires: `apps/quant-web/src/components/market/detail/MarketKlineStage.vue`
- Modify: `apps/quant-web/tests/marketDetailShellComponents.test.ts`
- Modify: `apps/quant-web/tests/marketDetailMarkers.test.ts`

**Interfaces:**

```ts
export interface HtdyDetailInput {
  identity: MarketDetailIdentity
  rawMarkers: readonly KlineMarker[]
  events: readonly AlertEvent[]
  eventStatus: PersistentAlertReadStatus
  rules: readonly ProductAlertRuleState[]
  rulesStatus: DetailReadStatus
  runtime: NormalizedAlertRuntimeHealth | null
  runtimeStatus: DetailReadStatus
}

export function buildHtdyDetailViewModel(
  input: HtdyDetailInput,
): DetailViewModel

export function replaceHtdyDetailPreferences(
  current: MarketDetailPreferences,
  htdy: Omit<FlexibleDetailPreferences, 'seriesKind'> & {
    seriesKind: SeriesKind
  },
): MarketDetailPreferences
```

HTDY 三事实固定为：

```text
当前原始观察
最近已保存事件
运行状态
```

- [ ] **Step 1: 写双事实和降级失败测试**

```ts
test('keeps repainting raw observation separate from immutable Event', () => {
  const model = buildHtdyDetailViewModel({
    ...fixture,
    rawMarkers: [rawBuy],
    events: [savedSell],
  })

  assert.equal(model.facts[0].label, '当前原始观察')
  assert.equal(model.facts[1].label, '最近已保存事件')
  assert.equal(model.facts[0].source, 'htdy_display')
  assert.equal(model.facts[1].source, 'alert_event')
})
```

另覆盖：

```text
raw buy / raw sell / raw none
Event none / latest buy / latest sell
Alert API unavailable 但 raw 仍可见
raw 不可用但 Event 仍可见
Runtime degraded
Rule disabled
current symbol/frequency 不在 Scope
continuous/contract 无 persistent Event
无 Event 显示“暂无已保存事件”，不显示“中性”
```

- [ ] **Step 2: 写 identity surface 失败测试**

断言：

```text
HTDY 与 Free 均只有共享 ViewNav 的一套 series/frequency 控件
HTDY 允许 actual_dominant/continuous/contract
指定合约切换品种后回 actual_dominant
Workspace 内没有 symbol/series/frequency input
HTDY preference 与 Free preference 相互隔离
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/htdyDetailViewModel.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketDetailShellComponents.test.ts \
  tests/marketDetailMarkers.test.ts
```

- [ ] **Step 4: 实现 HTDY Workspace**

`HtDyDetailWorkspace.vue` 负责：

1. `visibleMainIndicators` 中固定加入 `htdy`；
2. 按 HTDY preference 加入可选 EMA 与 Range；
3. 使用 Task 1 的 HTDY-only Event projection；
4. 使用 Task 2 的只读 Alert Context；
5. raw marker 与 Event marker 使用不同形状和完整文字；
6. disclosure 至少包含：
   - 原始观察说明；
   - 已保存事件；
   - Rule/Scope/Runtime；
   - 数据详情；
7. Event history 与 Marker 来自同一 Event projection；
8. 不显示 Scope 开关。

`HtDyChartStage.vue` 封装 `MarketKlineStage`，不复制 route identity 控件。

- [ ] **Step 5: 增加稳定 Marker selection**

若现有 `KlineChart` 没有选择事件的接口，增加：

```ts
const emit = defineEmits<{
  'need-more-before': []
  'follow-latest-change': [followLatest: boolean]
  'crosshair-change': [context: HoverKlineContext | null]
  'marker-select': [marker: KlineMarker]
}>()
```

只允许从当前 `mergedDisplayMarkers()` 中按稳定 `id` 解析；未知或已不在当前白名单的 ID 不 emit。

`MarketKlineStage` 只转发 typed marker，不解析 tooltip。

- [ ] **Step 6: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/htdyDetailViewModel.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketDetailShellComponents.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/kline-view-model.test.ts
```

- [ ] **Step 7: 提交**

```bash
git add \
  apps/quant-web/src/utils/htdyDetailViewModel.ts \
  apps/quant-web/src/components/market/detail/htdy/HtdyChartStage.vue \
  apps/quant-web/src/components/market/detail/htdy/HtdyDetailWorkspace.vue \
  apps/quant-web/src/utils/marketDetailPreferences.ts \
  apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/tests/htdyDetailViewModel.test.ts \
  apps/quant-web/tests/marketDetailPreferences.test.ts \
  apps/quant-web/tests/marketDetailShellComponents.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts
git add -u apps/quant-web/src/components/kline/KlineChart.vue \
  apps/quant-web/src/components/market/detail/MarketKlineStage.vue
git commit -m "feat(web): add HTDY unified detail workspace"
```

`git add -u` 只会加入实际修改的既有文件；提交前必须检查 staged diff。

---

## Task 4: 完成 HTDY 深链、视觉和 Slice B2 Gate

**Files:**
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/tests/marketHomeRoute.test.ts`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-home.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create/Update: HTDY desktop/mobile Playwright snapshots

- [ ] **Step 1: 写 Event 深链失败测试**

```ts
test('HTDY Event opens exact view, frequency and focus bar', () => {
  assert.deepEqual(routeForAlertEvent(htdyEvent), {
    path: '/market/chart',
    query: {
      symbol: 'jm',
      view: 'htdy',
      series_kind: 'actual_dominant',
      frequency: htdyEvent.frequency,
      focus_bar_end: htdyEvent.bar_end,
    },
  })
})
```

- [ ] **Step 2: 增加 E2E**

必须覆盖：

```text
普通 HTDY View 加载 raw observation
raw 与 Event 同时存在但不互相覆盖
continuous/contract 只显示 raw，不请求/显示 persistent Event
HTDY Event 从首页进入 exact bar
1m/5m/15m/30m/60m/1d/1w focus
focus 成功后 query 被消费且 follow-latest=false
左侧分页后 focus 重试成功
Alert Event API 失败但 raw 保留
HTDY raw 失败但 Event/history 保留
Rule disabled / Runtime degraded / no Event 文案
Free/HTDY 切换无 Marker 或 preference 串用
1440×900 desktop baseline
390px mobile baseline
```

- [ ] **Step 3: 运行 Slice B2 完整验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-detail.spec.mjs \
  e2e/market-home.spec.mjs
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

预期：全部命令 exit 0；无失败、无 secret finding。

- [ ] **Step 4: 自审**

逐项确认：

```text
HTDY-only Event resolver
raw/Event 双事实
无 Scope mutation
单一 identity surface
Free marker count 仍为 0
D1/W1 focus 仍按 trading day
无 SuBing/Newow Marker
```

- [ ] **Step 5: 提交 E2E 与截图**

```bash
git add \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/tests/marketHomeRoute.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs \
  apps/quant-web/e2e/market-home.spec.mjs \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs-snapshots
git commit -m "test(web): verify HTDY detail deep links"
```

- [ ] **Step 6: Draft PR 与 exact-head Review**

PR body 必须列出：

- base/head；
- raw/Event authority；
- tests；
- desktop/mobile baselines；
- 未触及 Scope/Runtime/main；
- 结论 `SLICE_B2_READY_FOR_OWNER_INTEGRATION` 或 `SLICE_B2_REQUIRES_FIXES`。

Critical/Important finding 修复并重跑完整验证后，停在 Draft PR 等待用户允许集成。

---

# Slice D — Trend Workspace

## Task 5: 冻结 Newow Web wire types 与 strict normalizer

**Files:**
- Create: `apps/quant-web/src/types/newow.ts`
- Create: `apps/quant-web/src/api/newow.ts`
- Create: `apps/quant-web/src/utils/newowTypes.ts`
- Create: `apps/quant-web/tests/newowTypes.test.ts`
- Read only:
  - `services/quant-api/app/api/market_newow.py`
  - `services/quant-api/app/schemas/market_newow.py`
  - `services/quant-api/app/market_data/newow/trend_detail_query.py`

**Interfaces:**

```ts
export interface NewowTrendDetailRequest {
  product: string
  from: string
  through: string
  frequency: '1d'
  series_kind: 'actual_dominant'
}

export interface NewowTrendDetailModel {
  meta: {
    strategyCode: 'newow_trend_v1'
    profileId: 'newow_trend_d1_v1'
    frequency: '1d'
    seriesKind: 'actual_dominant'
    calculationIdentity: string
    dataRevisionIdentity: string | null
    requestIdentity: string
  }
  barPolicy: 'completed_only'
  instrument: {
    product: string
    displayName: string | null
    lastVisiblePhysicalContract: string | null
  }
  bars: readonly NewowBarModel[]
  trendBand: readonly NewowTrendBandModel[]
  trendMarkers: readonly NewowMarkerModel[]
  escapeMarkers: readonly NewowMarkerModel[]
  cupMarkers: readonly NewowMarkerModel[]
  cupHandles: readonly NewowCupHandleModel[]
  rolloverSeams: readonly NewowRolloverSeamModel[]
  legend: Readonly<Record<string, string>>
  formulaDescriptions: Readonly<Record<string, string>>
  warnings: readonly string[]
}

export function normalizeNewowTrendDetailResponse(
  payload: unknown,
  expected: {
    product: string
    from: string
    through: string
  },
): NewowTrendDetailModel

export function getNewowTrendDetail(
  request: NewowTrendDetailRequest,
): Promise<NewowTrendDetailModel>
```

Marker 白名单：

```text
BUILD
CLEAR
NEWOW_ESCAPE_D1
NEWOW_ESCAPE_D2
NEWOW_ESCAPE_D3
CUP_HANDLE_READY
CUP_HANDLE_BREAKOUT
CUP_HANDLE_WEAKENED
CUP_HANDLE_INVALIDATED
CUP_HANDLE_EXPIRED
```

- [ ] **Step 1: 写 strict contract 失败测试**

覆盖：

```text
正确完整 response
strategy_code/profile_id/series_kind/frequency/bar_policy mismatch
product mismatch
unknown extra field
naive/invalid timestamp
bars 无序或重复
trend_band 与 bar_end 不对应
unknown marker type
duplicate marker_id
Decimal string 非 finite 或非法
cup pivot confirmed_at < pivot_at
rollover seam 合约/segment 缺失
request identity 与 expected window 不一致
超过 1500 visible trading days 的请求不由 Web 发送
```

示例：

```ts
test('rejects a Newow response for another product', () => {
  assert.throws(
    () => normalizeNewowTrendDetailResponse(
      { ...validPayload, instrument: { ...validPayload.instrument, product: 'rb' } },
      { product: 'jm', from: '2025-01-01', through: '2026-01-01' },
    ),
    /NEWOW_DATA_IDENTITY_INVALID/,
  )
})
```

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test tests/newowTypes.test.ts
```

- [ ] **Step 3: 实现 wire client 与 normalizer**

要求：

- URL 精确为 `/api/v1/market/newow/trend-detail`；
- 参数精确为 `product/from/through/frequency/series_kind`；
- 数值转换后必须 finite；
- 不导入 Python 公式；
- 不在前端计算 band、D1/D2/D3 或杯柄；
- HTTP 422/409 映射为稳定公开 unavailable code，不显示内部 stack/SQL。

- [ ] **Step 4: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test tests/newowTypes.test.ts
```

- [ ] **Step 5: 提交**

```bash
git add \
  apps/quant-web/src/types/newow.ts \
  apps/quant-web/src/api/newow.ts \
  apps/quant-web/src/utils/newowTypes.ts \
  apps/quant-web/tests/newowTypes.test.ts
git commit -m "feat(web): add strict Newow trend detail contract"
```

---

## Task 6: 建立 visible-window Newow loader 与 generic/Newow parity Gate

**Files:**
- Create: `apps/quant-web/src/utils/newowTrendParity.ts`
- Create: `apps/quant-web/tests/newowTrendParity.test.ts`
- Create: `apps/quant-web/src/composables/useNewowTrendDetail.ts`
- Create: `apps/quant-web/tests/newowTrendDetail.test.ts`

**Interfaces:**

```ts
export interface NewowVisibleWindow {
  from: string
  through: string
}

export function newowVisibleWindow(
  bars: readonly BarData[],
): NewowVisibleWindow | null

export function assertNewowMarketParity(
  marketBars: readonly BarData[],
  newow: NewowTrendDetailModel,
): void

export interface NewowTrendReadState {
  identityKey: string | null
  model: NewowTrendDetailModel | null
  status: 'idle' | 'loading' | 'ready' | 'stale' | 'unavailable'
  errorCode: string | null
  coveredWindow: NewowVisibleWindow | null
}

export function useNewowTrendDetail(dependencies?: {
  fetchDetail?: typeof getNewowTrendDetail
}): {
  state: Readonly<Ref<NewowTrendReadState>>
  load(input: {
    identity: MarketDetailIdentity
    bars: readonly BarData[]
  }): Promise<void>
  clear(): void
  dispose(): void
}
```

Parity 精确比较共同窗口：

```text
bar_end
trading_day
physicalContract
open/high/low/close
volume
openInterest
```

数值比较使用 wire 值转换后的 exact finite number；不得使用宽松百分比容差掩盖 identity 冲突。

- [ ] **Step 1: 写 visible window 和 parity 失败测试**

```ts
test('builds Newow request from loaded trading days', () => {
  assert.deepEqual(newowVisibleWindow(marketBars), {
    from: marketBars[0].trading_day,
    through: marketBars.at(-1)!.trading_day,
  })
})

test('rejects a physical contract mismatch', () => {
  assert.throws(
    () => assertNewowMarketParity(marketBars, newowWithWrongContract),
    /NEWOW_DATA_IDENTITY_INVALID/,
  )
})
```

覆盖无 bars、超过 1500 日、缺 trading_day、missing OI parity、额外/缺失共同 Bar、OHLCV mismatch。

- [ ] **Step 2: 写 generation、range expansion 失败测试**

覆盖：

```text
Trend identity 才允许请求
窗口未变化不重复请求
prepend 扩大窗口 -> loading -> 新完整结果原子替换
旧窗口结果不得标 ready 覆盖新窗口
旧 generation 响应丢弃
同 identity refresh 失败 -> 仅旧覆盖窗口可 stale
窗口超出旧 coverage -> 新区域不显示旧 overlay
identity 改变 -> 清空旧 model
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowTrendParity.test.ts \
  tests/newowTrendDetail.test.ts
```

- [ ] **Step 4: 实现 Workspace-owned loader**

`useMarketDetailController` 继续只拥有 generic Market bars/header/research，不增加 Newow 字段。

`TrendDetailWorkspace` 在当前 View 为 Trend、identity 固定且 generic bars 已通过 header identity 后调用 `useNewowTrendDetail()`。loader 自己维护 generation、covered window 和 stale/unavailable 状态。

- [ ] **Step 5: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/newowTrendParity.test.ts \
  tests/newowTrendDetail.test.ts
```

- [ ] **Step 6: 提交**

```bash
git add \
  apps/quant-web/src/utils/newowTrendParity.ts \
  apps/quant-web/src/composables/useNewowTrendDetail.ts \
  apps/quant-web/tests/newowTrendParity.test.ts \
  apps/quant-web/tests/newowTrendDetail.test.ts
git commit -m "feat(web): load identity-checked Newow trend detail"
```

---

## Task 7: 实现 Trend ViewModel、独立主图和历史详情

**Files:**
- Create: `apps/quant-web/src/utils/trendDetailViewModel.ts`
- Create: `apps/quant-web/tests/trendDetailViewModel.test.ts`
- Create: `apps/quant-web/src/utils/newowChartViewModel.ts`
- Create: `apps/quant-web/tests/newowChartViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/trend/TrendDetailWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue`
- Modify: `apps/quant-web/src/utils/marketDetailMarkers.ts`
- Modify: `apps/quant-web/tests/marketDetailMarkers.test.ts`

**Interfaces:**

```ts
export function buildTrendDetailViewModel(input: {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  weeklyTrend: ProductResearchResponse['weekly_trend'] | null
  newow: NewowTrendDetailModel | null
  readStatus: NewowTrendReadState['status']
  errorCode: string | null
}): DetailViewModel

export interface NewowChartModel {
  bars: readonly BarData[]
  band: readonly {
    time: string
    lower: number | null
    upper: number | null
    state: string
  }[]
  markers: readonly NewowChartMarker[]
  cupHandles: readonly NewowCupHandleModel[]
  rolloverSeams: readonly NewowRolloverSeamModel[]
}

export function buildNewowChartModel(
  model: NewowTrendDetailModel,
): NewowChartModel
```

三事实固定：

```text
周线背景
日线趋势
当前风险
```

- [ ] **Step 1: 写三事实和语义失败测试**

覆盖：

```text
周线背景只来自 generic research
日线趋势只来自 Newow band
当前风险按 D3 > D2 > D1 > 无 排序展示
杯柄不占三事实
BUILD/HOLD/CLEAR/EMPTY 用户文案稳定
蓝色不出现“做空/空单”
Newow unavailable 不根据 Kline 猜趋势
facts.length === 3
```

- [ ] **Step 2: 写 chart projection 失败测试**

覆盖：

```text
band 与 bars 一一按 bar_end 对齐
BUILD/CLEAR、D1/D2/D3、cup marker 保持 typed identity
重复 marker id 拒绝
rollover seam 只显示 physical contract 变化
cup pivot 使用 confirmed_at，不回画成当时可见信号
Marker/history 来自同一 normalized model
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/trendDetailViewModel.test.ts \
  tests/newowChartViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
```

- [ ] **Step 4: 实现 ViewModel**

固定语义提示：

```text
Newow 状态是 completed actual-dominant 日线研究观察，
不代表实际账户持仓；蓝色阶段不表示建立期货空单。
```

Disclosure 至少包含：

1. 趋势状态与原始 transition；
2. D1/D2/D3 trigger facts；
3. 杯柄状态、confirmed_at、first_seen_at、hard failures/diagnostics；
4. 公式身份和 request/calculation identity；
5. 主力换月 seam；
6. warnings 与数据状态。

- [ ] **Step 5: 实现独立 NewowTrendChartStage**

不得将 Newow 塞入通用 `ResearchOverlayId`。Stage 使用独立 Lightweight Charts 组件树，至少绘制：

```text
Kline
黄/蓝趋势带
BUILD/CLEAR
D1/D2/D3
杯柄 outline/lifecycle marker
rollover seam
Volume
```

Stage 必须具备与共享 Kline Stage 等价的：

```text
replace/prepend
loadEarlier
follow latest
scrollToLatest
revealTime
fullscreen
marker-select
identity reset
```

Marker 选择只从当前 typed collection 按稳定 ID 解析。

- [ ] **Step 6: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/trendDetailViewModel.test.ts \
  tests/newowChartViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
pnpm --dir apps/quant-web build
```

- [ ] **Step 7: 提交**

```bash
git add \
  apps/quant-web/src/utils/trendDetailViewModel.ts \
  apps/quant-web/src/utils/newowChartViewModel.ts \
  apps/quant-web/src/components/market/detail/trend/NewowTrendChartStage.vue \
  apps/quant-web/src/components/market/detail/trend/TrendDetailWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/components/market/detail/MarketDetailDrawer.vue \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/tests/trendDetailViewModel.test.ts \
  apps/quant-web/tests/newowChartViewModel.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts
git commit -m "feat(web): add Newow trend detail workspace"
```

---

## Task 8: 完成 Trend E2E、视觉与 Slice D Gate

**Files:**
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create/Update: Trend desktop/mobile Playwright snapshots

- [ ] **Step 1: 增加 API route fixtures**

Fixture 必须使用后端 wire schema，不能使用前端 normalized shape。至少准备：

```text
ready
warm-up / no current band
Newow 409 unavailable
identity mismatch
rollover
cup READY/BREAKOUT
D1/D2/D3
```

- [ ] **Step 2: 增加 E2E**

覆盖：

```text
Trend 固定 actual_dominant + 1d
只存在一套 identity surface
周线 context 与 Newow 日线事实分源
Newow ready 图层
Newow unavailable 时 generic Kline 保留、正式 overlay 隐藏
identity mismatch fail-closed
prepend 后重新请求完整窗口
BUILD/CLEAR、D123、cup、rollover marker 详情
不出现 HTDY/SuBing/Free marker
1920 desktop baseline
390px mobile baseline
```

- [ ] **Step 3: 运行后端合同回归**

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow/test_market_newow_api.py \
  services/quant-api/tests/newow/test_trend_detail_service.py
```

- [ ] **Step 4: 运行 Slice D 完整验证**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-detail.spec.mjs
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: 提交**

```bash
git add \
  apps/quant-web/e2e/market-detail.spec.mjs \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs-snapshots
git commit -m "test(web): verify Newow trend detail workspace"
```

- [ ] **Step 6: Draft PR 与双重点 Review**

Review 必须同时检查：

1. Web contract/UX；
2. identity、same-contract、rollover、confirmed_at、future-leak 和无前端公式。

Critical/Important finding 修复后重跑完整验证，停在 Draft PR 等待用户允许集成。

---

# Slice C — SuBing Workspace

## Task 9: 实现 SuBing Event-only ViewModel 与固定图层

**Files:**
- Create: `apps/quant-web/src/utils/subingDetailViewModel.ts`
- Create: `apps/quant-web/tests/subingDetailViewModel.test.ts`
- Create: `apps/quant-web/src/components/market/detail/subing/SubingChartStage.vue`
- Create: `apps/quant-web/src/components/market/detail/subing/SubingDetailWorkspace.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/src/utils/marketDetailMarkers.ts`
- Modify: `apps/quant-web/tests/marketDetailMarkers.test.ts`
- Reuse:
  - `apps/quant-web/src/composables/usePersistentAlertMarkers.ts`
  - `apps/quant-web/src/composables/useMarketDetailAlertContext.ts`

**Interfaces:**

```ts
export function buildSubingDetailViewModel(input: {
  identity: MarketDetailIdentity
  events: readonly AlertEvent[]
  eventStatus: PersistentAlertReadStatus
  rules: readonly ProductAlertRuleState[]
  rulesStatus: DetailReadStatus
  runtime: NormalizedAlertRuntimeHealth | null
  runtimeStatus: DetailReadStatus
}): DetailViewModel
```

三事实固定：

```text
最近预警
Rule 范围
Runtime 评估
```

- [ ] **Step 1: 写 Event-only authority 失败测试**

```ts
test('does not synthesize direction without a SuBing AlertEvent', () => {
  const model = buildSubingDetailViewModel({
    ...fixture,
    events: [],
  })

  assert.equal(model.facts[0].value, '暂无已保存预警')
  assert.doesNotMatch(JSON.stringify(model), /偏多|偏空|中性/)
})
```

覆盖：

```text
只接受 subing_ths_alert_15m_v1
buy -> S↑ / 多头预警
sell -> S↓ / 空头预警
HTDY Event 被排除
Rule disabled
empty scope
enabled 但当前 symbol 不在 Scope
runtime rule_status last_evaluated/event/failure
全局 heartbeat 新鲜但 SuBing rule_status 为空，不能显示已评估
Alert API unavailable
facts.length === 3
```

- [ ] **Step 2: 写 Marker 白名单失败测试**

```ts
test('SuBing renders only immutable SuBing Event markers', () => {
  assert.deepEqual(
    markersForDetailView(
      'subing',
      [rawHtdy, htdyEventMarker, subingEventMarker, newowMarker],
    ),
    [subingEventMarker],
  )
})
```

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts
```

- [ ] **Step 4: 实现 Workspace**

固定图层：

```text
15m Kline
EMA21
SuBing Event-backed S↑/S↓
Volume
MACD
```

明确排除：

```text
EMA10/60
Range
HTDY
Newow
浏览器本地 CROSS/EMA21 正式 Marker
```

History 与 Marker 使用 SuBing-only Event projection。详情显示：

```text
bar_end
detected_at
physical contract
result
notification_attempted_at（仅事实）
rule_code / formula_version（可用时）
```

provider attempted/accepted 不写成微信已送达。

- [ ] **Step 5: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/subingDetailViewModel.test.ts \
  tests/marketDetailMarkers.test.ts \
  tests/runtimeHealthTypes.test.ts \
  tests/marketDetailAlertContext.test.ts
pnpm --dir apps/quant-web build
```

- [ ] **Step 6: 提交**

```bash
git add \
  apps/quant-web/src/utils/subingDetailViewModel.ts \
  apps/quant-web/src/components/market/detail/subing/SubingChartStage.vue \
  apps/quant-web/src/components/market/detail/subing/SubingDetailWorkspace.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/utils/marketDetailMarkers.ts \
  apps/quant-web/tests/subingDetailViewModel.test.ts \
  apps/quant-web/tests/marketDetailMarkers.test.ts
git commit -m "feat(web): add SuBing unified detail workspace"
```

---

## Task 10: 完成 SuBing 深链、生产状态文案和 Slice C Gate

**Files:**
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/tests/marketHomeRoute.test.ts`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-home.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Create/Update: SuBing desktop/mobile Playwright snapshots

- [ ] **Step 1: 写深链失败测试**

```ts
test('SuBing Event opens fixed 15m actual-dominant identity', () => {
  assert.deepEqual(routeForAlertEvent(subingEvent), {
    path: '/market/chart',
    query: {
      symbol: subingEvent.symbol,
      view: 'subing',
      series_kind: 'actual_dominant',
      frequency: '15m',
      focus_bar_end: subingEvent.bar_end,
    },
  })
})
```

- [ ] **Step 2: 增加 E2E**

覆盖：

```text
固定 actual_dominant + 15m
首页 Event -> exact bar
focus 成功后 query 一次性消费
无 Event -> 暂无已保存预警
disabled + empty scope
enabled / in-scope / out-of-scope
Runtime rule status ready/failure/unavailable
Event API stale
HTDY Event 不混入
不出现 Scope toggle
不出现浏览器 synthetic S↑/S↓
1440×900 baseline
390px history drawer baseline
```

- [ ] **Step 3: 对照 STATUS 做文案审查**

当前生产 Gate 不写死进代码。UI 只由 API readback 生成状态。PR body 单独记录当时 `STATUS.md`：

```text
0045 是否完成
当前 Runtime exact tag
G10
G9
SuBing enabled/scope
自然 Event
```

不得把文档快照硬编码进前端。

- [ ] **Step 4: 运行 Slice C 完整验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-detail.spec.mjs \
  e2e/market-home.spec.mjs
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 5: 提交**

```bash
git add \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/tests/marketHomeRoute.test.ts \
  apps/quant-web/e2e/market-detail.spec.mjs \
  apps/quant-web/e2e/market-home.spec.mjs \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs-snapshots
git commit -m "test(web): verify SuBing detail deep links"
```

- [ ] **Step 6: Draft PR 与 exact-head Review**

Review 必须拒绝：

```text
任何 Scope mutation
EMA/MACD 浏览器生成正式 Marker
全局 heartbeat 冒充 per-rule evaluation
无 Event 显示方向
provider accepted 写成实际送达
```

修复 Critical/Important finding 后停在 Draft PR 等待用户允许集成。

---

# Slice E — Final Cutover

## Task 11: 完成品种选择、默认入口和 View restore

**Files:**
- Create: `apps/quant-web/src/components/market/detail/MarketDetailSymbolPicker.vue`
- Create: `apps/quant-web/tests/marketDetailSymbolPicker.test.ts`
- Modify: `apps/quant-web/src/components/market/detail/MarketDetailTopBar.vue`
- Modify: `apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue`
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`
- Modify: `apps/quant-web/src/utils/marketDetailPreferences.ts`
- Modify: `apps/quant-web/tests/marketDetailPreferences.test.ts`
- Modify: `apps/quant-web/tests/marketDetailRoute.test.ts`
- Modify: `apps/quant-web/tests/marketDetailController.test.ts`

**Final behavior:**

```text
普通品种 -> trend + actual_dominant + 1d
TopBar 选择品种 -> 保留当前 view 的合法 identity
Trend/SuBing -> 新品种重新解析 actual_dominant
HTDY/Free -> 保留合法 series/frequency
contract + 切换品种 -> actual_dominant + 一次提示
```

- [ ] **Step 1: 写 route/restore 失败测试**

覆盖：

```text
普通入口默认 Trend
每个灵活 View 独立 restore
灵活 View 只持久化 actual_dominant/continuous，不持久化 contract
固定 View 不读取灵活 restore
contract 不跨品种
选择品种不返回 Legacy
旧 focus 被清除
invalid route 仍需显式恢复
```

- [ ] **Step 2: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketDetailController.test.ts \
  tests/marketDetailSymbolPicker.test.ts
```

- [ ] **Step 3: 实现最小 picker**

只消费已有 product taxonomy/dominant read data，不新增搜索后端。支持：

- 键盘搜索；
- product code/name；
- Esc 关闭；
- focus restoration；
- 空结果；
- 选择后安全 route transition。

不得增加自选、收藏、服务端偏好或多用户功能。

- [ ] **Step 4: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailPreferences.test.ts \
  tests/marketDetailController.test.ts
pnpm --dir apps/quant-web build
```

- [ ] **Step 5: 提交**

```bash
git add \
  apps/quant-web/src/components/market/detail/MarketDetailTopBar.vue \
  apps/quant-web/src/components/market/detail/MarketDetailViewNav.vue \
  apps/quant-web/src/pages/market/MarketDetailPage.vue \
  apps/quant-web/src/utils/marketDetailPreferences.ts \
  apps/quant-web/tests/marketDetailPreferences.test.ts \
  apps/quant-web/tests/marketDetailRoute.test.ts \
  apps/quant-web/tests/marketDetailController.test.ts
git add -A \
  apps/quant-web/src/components/market/detail/MarketDetailSymbolPicker.vue \
  apps/quant-web/tests/marketDetailSymbolPicker.test.ts
git commit -m "feat(web): finalize unified detail identity navigation"
```

提交前检查可选文件存在，禁止用宽泛 `git add -A` 覆盖仓库其他路径；以上 `git add -A` 只限列出的两个精确 pathspec。

---

## Task 12: 切换首页路由并删除 Legacy

**Files:**
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Modify: `apps/quant-web/src/utils/marketHomeRoutes.ts`
- Modify: `apps/quant-web/tests/marketHomeRoute.test.ts`
- Modify: `apps/quant-web/src/pages/market/chart.vue`
- Delete: `apps/quant-web/src/pages/market/LegacyMarketChart.vue`
- Modify/Delete: Legacy-only components、utils、tests discovered by exact reference scan
- Modify: `apps/quant-web/e2e/market-home.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`

- [ ] **Step 1: 写 Cutover 失败测试**

覆盖：

```text
普通首页行 -> Trend
HTDY Event -> HTDY exact frequency/focus
SuBing Event -> SuBing 15m/focus
/market/chart 不再挂载 Legacy
页面不存在“返回旧版详情”
四个 Tab 均挂载真实 Workspace
```

- [ ] **Step 2: 做删除前 reference scan**

```bash
rg -n \
  "LegacyMarketChart|returnLegacy|返回旧版详情|view=current|view=newow" \
  apps/quant-web docs openspec
```

逐条分类：

- active code/test/docs reference：本任务关闭；
- Git/Alembic lineage：不修改；
- Newow 专用旧 Web 描述：已由本设计的 supersession note 关闭。

- [ ] **Step 3: 运行 RED**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketHomeRoute.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailShellComponents.test.ts
```

- [ ] **Step 4: 实现 Cutover 和普通删除**

要求：

1. `chart.vue` 只挂载 `MarketDetailPage`；
2. 删除 Legacy 文件和仅由 Legacy 消费的组件；
3. 不建立 backup、archive、legacy-copy 或 rollback 文件；
4. Git history 是唯一恢复路径；
5. 保留仍被统一页面消费的 Kline/indicator/Alert 代码。

- [ ] **Step 5: 运行 reference scan**

```bash
rg -n \
  "LegacyMarketChart|returnLegacy|返回旧版详情|view=current|view=newow" \
  apps/quant-web docs openspec
```

预期：active product reference 为 0。若 canonical 中保留历史说明，必须明确标注 retired/superseded，不能作为入口。

- [ ] **Step 6: 运行 GREEN**

```bash
pnpm -C apps/quant-web exec node --test \
  tests/marketHomeRoute.test.ts \
  tests/marketDetailRoute.test.ts \
  tests/marketDetailShellComponents.test.ts
pnpm --dir apps/quant-web build
```

- [ ] **Step 7: 提交**

```bash
git add \
  apps/quant-web/src/pages/market/index.vue \
  apps/quant-web/src/utils/marketHomeRoutes.ts \
  apps/quant-web/src/pages/market/chart.vue \
  apps/quant-web/tests/marketHomeRoute.test.ts \
  apps/quant-web/e2e/market-home.spec.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs
git add -u apps/quant-web
git commit -m "refactor(web): cut over to unified market detail"
```

`git add -u apps/quant-web` 只用于已跟踪 Legacy 删除；提交前必须审查 staged diff，避免包含无关删除。

---

## Task 13: 建立 active OpenSpec 与稳定产品文档

**Files:**
- Create: `openspec/specs/market-detail-workspaces/spec.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Do not modify: `STATUS.md`
- Do not modify: `TESTING.md`，除非本 Slice 新增了实际可执行且仓库现有导航未覆盖的命令

**OpenSpec Requirements:**

至少冻结：

1. 唯一 `/market/chart` 与四个 Workspace；
2. route/identity 能力矩阵；
3. 单一 identity control；
4. Free no-marker；
5. HTDY raw/Event 双事实；
6. Trend Newow-only、strict parity、rollover；
7. SuBing Event-only、per-rule Runtime；
8. Marker/history 同源；
9. deep link/focus；
10. independent degradation；
11. no Scope mutation；
12. no order/position/target/score；
13. Legacy removed；
14. responsive/a11y。

每个 Requirement 至少包含正常、失败或边界 Scenario。

- [ ] **Step 1: 写 OpenSpec**

使用仓库规范格式：

```markdown
### Requirement: ...
...
#### Scenario: ...
- **WHEN** ...
- **THEN** ...
```

禁止只复制本设计全文；OpenSpec 只保留 active、可测试、长期合同。

- [ ] **Step 2: 更新稳定文档**

`PROJECT_SOURCE.md` 更新为实际进入 `develop` 后的稳定 Web 面：

```text
四 Workspace
Trend/Newow read authority
HTDY 双事实
SuBing Event-only
Free no-marker
统一 route/deep link
```

`DECISIONS.md` 增加长期架构决策，不写当前 release/Runtime。

`docs/ARCHITECTURE.md` 更新 active dependency：

```text
MarketDetailPage
-> MarketDataService API
-> Newow read API
-> Alert read API
-> Runtime read API
```

`STATUS.md` 不因 Web code complete 修改。

- [ ] **Step 3: 运行文档 RED/GREEN 检查**

```bash
openspec validate --specs --strict --no-interactive
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] **Step 4: placeholder/reference scan**

```bash
rg -n "\b(TODO|TBD|FIXME)\b|implement later|待补充|稍后实现" \
  openspec/specs/market-detail-workspaces \
  PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md

rg -n \
  "LegacyMarketChart|返回旧版详情|view=current|view=newow" \
  PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md \
  openspec/specs/market-detail-workspaces
```

预期：均无 active placeholder/legacy reference。

- [ ] **Step 5: 提交**

```bash
git add \
  openspec/specs/market-detail-workspaces/spec.md \
  PROJECT_SOURCE.md \
  DECISIONS.md \
  docs/ARCHITECTURE.md
git commit -m "docs: freeze unified market detail contracts"
```

---

## Task 14: 完整视觉、无障碍、回归和最终 Review

**Files:**
- Modify: `apps/quant-web/e2e/market-detail.spec.mjs`
- Modify: `apps/quant-web/e2e/market-home.spec.mjs`
- Modify: `apps/quant-web/e2e/market-detail.helpers.mjs`
- Update: approved Playwright snapshots
- Modify only for verified defects: shared/detail Workspace source and tests

- [ ] **Step 1: 建立最终视觉矩阵**

必须生成并审查：

| View | 1920 | 1440×900 | 1280×800 | 390 |
|---|---:|---:|---:|---:|
| Trend | 必须 | 必须 | 必须 | 必须 |
| HTDY | 必须 | 必须 | 必须 | 必须 |
| SuBing | 必须 | 必须 | 必须 | 必须 |
| Free | 必须 | 必须 | 必须 | 必须 |

至少包含 ready、unavailable/degraded、history/drawer 和 long-label 场景。

- [ ] **Step 2: 键盘与无障碍 E2E**

覆盖：

```text
Tab 键遍历 TopBar、View、identity、disclosure、chart controls
Enter/Space 激活 Tab/Disclosure
Esc 关闭 picker/drawer
关闭后焦点恢复
390px 所有高频目标 >=44px
状态非纯颜色
prefers-reduced-motion
invalid URL 的显式恢复
```

- [ ] **Step 3: authority isolation E2E**

断言：

```text
Free marker count = 0
HTDY 无 SuBing/Newow
Trend 无 Alert/raw HTDY
SuBing 无 HTDY/Newow/Range
一个 authority 失败不清空另一个 authority
identity 切换不保留旧 Marker/history/viewport
```

- [ ] **Step 4: 运行最终完整验证**

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow \
  tests/engineering/test_canonical_consistency.py
uv run --project services/quant-api ruff check \
  services/quant-api packages/quant-core
uv run --project services/quant-api mypy \
  services/quant-api/app packages/quant-core/guiyi_quant
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

命令若与执行时 `TESTING.md` 不一致，服从 `TESTING.md` 的当前精确命令，并在 PR body 记录替换关系。

- [ ] **Step 5: 完成 Spec coverage Review**

逐项建立表格：

```text
Spec section
implementation files
unit/E2E evidence
visual evidence
status
```

任何未覆盖项必须修复或明确阻塞，不能降级成“以后再做”。

- [ ] **Step 6: 独立 exact-head Review**

至少进行：

1. Web architecture/UX Review；
2. authority/identity/fail-closed Review；
3. deletion/reference Review；
4. OpenSpec/canonical Review。

Critical/Important finding 必须修复并重跑完整验证。

- [ ] **Step 7: 提交最终测试修正**

```bash
git add \
  apps/quant-web/e2e/market-detail.spec.mjs \
  apps/quant-web/e2e/market-home.spec.mjs \
  apps/quant-web/e2e/market-detail.helpers.mjs \
  apps/quant-web/e2e/market-detail.spec.mjs-snapshots \
  apps/quant-web/e2e/market-home.spec.mjs-snapshots
git add -u
git commit -m "test(web): close unified detail cutover"
```

提交前审查 `git diff --cached --name-status`，确保无任务外文件。

- [ ] **Step 8: Draft PR Gate**

PR body 必须包含：

```text
base/head
Slice B2/D/C dependency commits
四 Workspace authority matrix
Legacy deletion list
test commands and exact counts
visual baseline links
OpenSpec validation
secret scan
independent Review findings/closures
main/tag/Runtime/Scope/notification untouched
```

最终只允许：

```text
SLICE_E_READY_FOR_OWNER_VISUAL_REVIEW
SLICE_E_REQUIRES_FIXES
SLICE_E_BLOCKED
```

用户视觉批准并明确“允许集成 develop”后才合入。

---

# V1 Integration Completion

Slice E 合入 `develop` 后执行只读确认：

```bash
git fetch origin
git merge-base --is-ancestor <slice-e-merge-sha> origin/develop
git status --short
rg -n \
  "LegacyMarketChart|returnLegacy|返回旧版详情|view=current|view=newow" \
  apps/quant-web PROJECT_SOURCE.md DECISIONS.md docs/ARCHITECTURE.md openspec/specs
```

预期：

```text
Slice E merge 是 origin/develop ancestor
task worktree clean
active legacy reference = 0
```

然后清理 Slice E task worktree 和已合并 branch。

此时最多声明：

```text
Market Detail V1 CODE_COMPLETE
Market Detail V1 TEST_COMPLETE
Release / Runtime / production Gate unchanged
```

不得自动：

- 合并 `main`；
- 创建 tag/Release；
- promotion Runtime；
- 执行 production 0045；
- 启用 SuBing 或写 Scope；
- 发送真实通知。

---

# Plan Self-Review Checklist

执行计划成稿或修改后必须检查：

- [ ] 每一条 Design Spec 的 V1 Requirement 都有对应 Task。
- [ ] 没有 `TODO`、`TBD`、`FIXME`、`implement later` 或未定义接口。
- [ ] B2、D、C、E 的 branch 和依赖顺序唯一。
- [ ] B3 Alert Scope 不在 V1 关键路径。
- [ ] D 不再等待不存在的 Newow API Gate。
- [ ] V1.1/V2 没有混入当前源码任务。
- [ ] 每个 Task 有 exact files、interfaces、RED、GREEN、commit。
- [ ] 类型、函数名和后续消费者一致。
- [ ] 没有真实数据、DB、Runtime、Scope、通知或发布命令。
- [ ] Final Cutover 同步关闭 Legacy active references。
- [ ] `STATUS.md` 不被提前修改。
