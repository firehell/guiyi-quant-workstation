# Market 首页白色桌面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在现有 Market 首页实现批准的白色全宽视觉、期货分类、表头排序及真实降级状态。

**Architecture:** 保留三资源 composable、generic ViewModel 和 route serializer。将局部视觉及无网络排序放在现有 Web 模块；目标价缺 authority 时固定不可用，不增加后台字段或逐品种请求。

**Tech Stack:** Vue 3、TypeScript、Naive UI、Node test、Playwright；不增加依赖。

**Spec:** [Market 首页白色桌面设计](2026-09-07-market-home-light-design.md)。批准图与事实校正在其中。

## Global Constraints

- 仅 `/market`；首页局部样式不得改变详情页、图表主题或全局指标颜色。
- 仅三个既有 bulk GET，无 provider/生产服务连接，无公式/目标价计算，无正式写入。
- 当前目标参考价固定 `—`、不可排序，解释“尚未接入同身份目标参考价”。
- `oi_change_1d` 用相对变化率展示；missing 不补零；D1/W1 状态不改策略含义。
- 模型可由执行者选择；本轮所有代理推理上限为高级（high）。
- 文档先经过独立 Review/修正并 commit/push develop；随后从该精确提交建立 `codex/market-home-light` 独立 worktree。
- 验证命令只在仓库 `TESTING.md` 维护；以下步骤引用该文件的 Market Home / Web / 工程检查入口，不复制第二套命令权威。

## Task 1：纯本地表头排序与安全偏好

**Files:** 修改 `apps/quant-web/src/utils/marketHomeWorkspace.ts`、`marketHomePreferences.ts`；测试 `apps/quant-web/tests/marketHomeWorkspace.test.ts`、`marketHomePreferences.test.ts`。

**Consumes:** `MarketHomeRow`、既有 sort/filter 选项。

**Produces:**

```ts
export type MarketHomeSortDirection = 'asc' | 'desc'
// MarketHomeSort 在原 default/change/volume/oi/event 基础上增加 close。
export function nextMarketHomeSort(
  current: { sort: MarketHomeSort; sortDirection: MarketHomeSortDirection },
  column: MarketHomeSort,
): { sort: MarketHomeSort; sortDirection: MarketHomeSortDirection }
// filterAndSortMarketHomeRows 的 options 增加可选 sortDirection（缺省 desc）。
// MarketHomePreferences version/key 不变，增加可选 sortDirection；读取结果总有有效方向。
```

- [ ] 先写并运行失败测试：change 首次 desc → asc → default；切列 desc；close 精度、同值 symbol 排序；两个方向 null/NaN/Infinity 都最后；源数组不变；筛选后排序；旧 prefs 缺方向采用 desc，invalid/unknown JSON 和 blocked storage 安全默认。

```ts
assert.deepEqual(nextMarketHomeSort({ sort: 'default', sortDirection: 'desc' }, 'change'),
  { sort: 'change', sortDirection: 'desc' })
assert.deepEqual(nextMarketHomeSort({ sort: 'change', sortDirection: 'asc' }, 'change'),
  { sort: 'default', sortDirection: 'desc' })
// 测试只经过本地过滤/比较；最小 fixture 仍显式标为测试输入。
const rows = [
  { symbol: 'ag', product_name: '白银', sector: 'precious', price_change_1d: null },
  { symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: -.01 },
  { symbol: 'au', product_name: '黄金', sector: 'precious', price_change_1d: -.01 },
] as MarketHomeRow[]
assert.deepEqual(filterAndSortMarketHomeRows(rows, {
  query: '', sector: '', filter: 'all', sort: 'change', sortDirection: 'asc',
}).map(row => row.symbol), ['au', 'jm', 'ag'])
```

- [ ] 实现单一 comparator：先判断有限值；缺失双方按 symbol；一方缺失永远末尾；再应用方向；最后稳定 symbol tie-break。default 原次序；保留既有 Event 排序兼容。不要通过 Infinity 相减判断缺失。
- [ ] 偏好 normalize 只返回白名单字段，旧值仍兼容，未知 sector 由页面在 overview 成功后复核；新默认观察收起。
- [ ] 按 TESTING.md Market Home targeted contracts 运行定向 unit；自审 diff 后提交本 Task。

## Task 2：首页呈现与交互

**Files:**

- 修改 `apps/quant-web/src/pages/market/index.vue`：只保留数据编排、板块选择、排序、观察显隐、路由 handler。
- 修改 `apps/quant-web/src/components/market/MarketHomeTable.vue`、`MarketHomeSectorTicker.vue`、`MarketHomeLegend.vue`、`MarketHomeTrustStrip.vue`、`MarketHomeFocusRail.vue`：职责仍为各自显示区域。
- 新增 `apps/quant-web/src/components/market/MarketHomeHeader.vue`：导航菜单从传入的可用 rows 选品种，emit `openView`；原生 details 菜单/按钮可键盘操作。
- 新增 `apps/quant-web/src/styles/marketHome.css`：仅 `.market-dashboard-page` 下白色 theme/布局；必要的 MainLayout 首页 class 去 padding/换白底，只匹配 `route.name === 'market'`。
- 修改 `apps/quant-web/src/utils/marketHomeRoutes.ts`：新增薄 route helper，委托现有 serializer；普通行与 Event helper 不变。
- 新增 `apps/quant-web/src/utils/marketHomePresentation.ts`：统一符号百分比、有限数字和价格颜色格式，不算策略或收益。
- 在确认无消费者后删除 `MarketHomeToolbar.vue`、`MarketHomeSummary.vue`；保留现有移动列表与 API 字段。同步 source-import 测试，不遗留 active 引用。
- 测试 `marketHomePageRoute.test.ts`、`marketHomeRoute.test.ts` 与新增 `marketHomePresentation.test.ts`；浏览器测试在 Task 3。

**Interfaces:**

```ts
// MarketHomeTable props:
{ rows: MarketHomeRow[]; eventAvailability: MarketHomeAvailability;
  compact: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection }
// emits open(row), sort(column). 表头 aria-sort 派生于 sort/direction。
// MarketHomeSectorTicker props:
{ sectors: MarketHomeOverviewResponse['sectors']; active: number | null; selected: string }
// emits select(sector)，空字符串表示全部。
export function marketHomeViewChartQuery(view: 'newow'|'htdy'|'subing'|'free', symbol: string)
// 使用 serializeMarketDetailIdentity；newow trend+1d，subing 15m，其他1d，全部actual_dominant。
export function marketHomePercent(value: number | null): string
export function marketHomePrice(value: number | null): string
export function marketHomeDirection(value: number | null): 'up'|'down'|'flat'
```

- [ ] 先为新 route helper/数值格式写失败测试：0 与 null、符号、精度、非有限值、视角周期；原有 ordinary product 和 immutable Event 跳转必须继续通过。
- [ ] 接 Task 1 方向到页面 watcher 和表头；剔除 search/summary filters 活跃 UI。删除独立工具条，不把排序移到另一条控件栏。
- [ ] 构建 Header/分类/紧凑图例/表格；目标列固定不可用（标题解释），无目标排序按钮、无示例数字。数字软底仅方向相关，增仓率中性。行焦点/hover 与图标复用。

```vue
<th scope="col" :aria-sort="sort === 'change' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'">
  <button type="button" @click="$emit('sort', 'change')">1d 涨跌幅</button>
</th>
<td class="target-unavailable"><span title="尚未接入同身份目标参考价">—</span></td>
```

- [ ] 状态区压缩但保留非实时时间、真实计数、cached stale、Runtime/Event异常；观察展开仍使用当前可用事件集合，关闭不产生新请求；刷新后失效不能残留事件行。
- [ ] 页头以现有 overview rows 显式选择品种，不为了导航调用新接口。无参与者时菜单展示原因。更多仅含已有自由看盘入口。
- [ ] 桌面全宽纵向滚动和 sticky header；移动保留原列表；样式不逃逸。按 Spec 的必要校正更新 tests，不删除 causality 或 unrelated regressions。
- [ ] 完成定向 unit、自审和必要 build，提交本 Task。

## Task 3：浏览器验收、canonical 同步与独立 Review

**Files:** `apps/quant-web/e2e/market-home.spec.mjs`、`apps/quant-web/e2e/fixtures/market-home-light.mjs`、首页 screenshot golden；`PROJECT_SOURCE.md`、`openspec/specs/market-home-overview/spec.md`、必要 `TESTING.md`。不为阶段进度修改 STATUS。

**Produces:** 受控 60 品种浏览器 fixture、交互/降级证据、真实渲染截图、可集成候选。

- [ ] Fixture 在测试中从仓库 taxonomy CSV 读取全部60名称/归属；统计 summary/sectors 与 items 一致，数值明确为测试输入。在 `/market` 挂载期间，所有 `/api/**` 仅允许既有三个 GET；未知路径或写请求立即 abort 并计为测试失败；proxy 指向不可用本地端口。跳转前先冻结并断言首页请求记录；进入 `/market/chart` 后合法详情读取使用既有隔离详情 fixture，不纳入首页三请求计数，但仍禁止未拦截请求连真实后端。返回首页时重新开始首页计数窗口。菜单与回退测试不可把合法详情请求误报为首页 N+1。
- [ ] 重写因批准的UI退役而变化的断言：搜索改板块、独立 sort 改 header、侧栏默认关闭需主动展开；保留原 empty/unavailable、stale灰态、精确事件路由、三请求、不假计数和390px兼容覆盖。
- [ ] 新增实际交互验证：四列 desc/asc/default、键盘 Space/Enter、active aria-sort、同值/缺值、切板块后本地排序、refresh/返回恢复、安全 storage、target不存在时无数值和新请求、OI百分比、菜单精确路由。
- [ ] 1280/1440/1920/2560 四个桌面与390兼容；至少一张60品种截图；滚到底部最后行仍可达、表头仍可见、整页无横向溢出。保留小样本降级截图，不以 fixture 当生产 smoke。
- [ ] 运行 TESTING.md 定向与完整 Web unit、check:alert-rules、build、首页/详情/Newow必要 E2E；新增截图先人工/模型查看，再冻结 golden，不能盲目接受截图差异。
- [ ] 更新 active OpenSpec 场景/稳定产品说明，声明目标价未接入而非新增策略authority；检查引用、OpenSpec strict、secret scan 和 diff。
- [ ] 对实现基线到 candidate 的 exact diff 进行 Standards 与 Spec 独立 Review（high）；修正发现后定向回归、必要复审。无阻塞 finding 才允许 commit/push/集成 develop。
- [ ] 集成后核对 develop 和 remote exact ref；只清理本次干净且已集成的 disposable worktree/branch。保留唯一主工作树和 Runtime。提供代码/测试/Review状态与未完成目标价/原站evidence边界，不宣称发布或上线。

## 审查映射与停止条件

Task 1 对应 AC03；Task 2 对应 AC01/02/04/05/06；Task 3 对应所有 AC 的浏览器与回归 evidence。自审检查：类型名称与调用点一致、无空占位实施步骤、无新后端authority、测试命令只有 TESTING.md 一个权威位置。

若发现必须更改公式/目标价authority/API合同时，停在该业务缺口并保持列不可用；不扩展 Lane 2 为未批准 Lane 3。非本任务 dirty paths 保护不动；验证失败先定位根因；未独立 Review 不集成。文档和实现分别提交，以支持独立回滚与审查。
