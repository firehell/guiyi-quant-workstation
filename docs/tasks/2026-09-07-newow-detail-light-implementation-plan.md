# Newow 白色详情页 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将批准的白色全宽详情、图上折叠摘要、图标弹窗、纵向参考交易和单副图实现到现有 Newow 九组合。

**Architecture:** 保留 sectioned API、唯一 loader 与现有 ViewModel；最小 MACD 显示适配复用内核；显式 Newow Shell 变体隔离其他页面。图形只投影已有事实。

**Tech Stack:** Vue 3 / TypeScript / Lightweight Charts 5.2 / Python existing MACD kernel / Node test / Playwright；不增加依赖。

**Spec:** [Newow 白色详情页 V2 设计规范](2026-09-07-newow-detail-light-design.md)，含批准图片和来源边界；MACD 细节另见 [既有工程规格第7节](2026-09-07-newow-desktop-engineering-spec.md)。

## Global Constraints

- Newow 三策略 × `1w/1d/60m`，completed `actual_dominant`；不改公式、Action/Hint/ReferenceTrade 身份或收益。
- 白色全宽、图上摘要、原位折叠、解释弹窗、参考记录整页纵向滚动；无右栏、底部研究 tab、搜索或账户功能。
- 金额原字符串展示；有限 Number 仅作绘图；不从客户端重算指标或参考收益。
- 缺证据/缺数据不填示例，跨 section 兼容不足不拼接，旧服务端不支持 MACD 时显式不可用。
- 文档先独立 Review/修正并 commit/push develop，随后从 docs 精确提交建立 `codex/newow-detail-light` 的 `.worktrees/newow-detail-light`。
- 使用高级（high）或以下推理。执行者可选择 GPT-6 Astra；按任务独立 Review，最终两轴 Review。
- 命令唯一入口 `TESTING.md`；下列引用对应测试入口，不复制第二套命令权威。
- 不连接生产 RQData/DB/Redis/Runtime，不写 Canonical/Scope，不通知、不 main/tag/release。

## Task 1：MACD 只读显示协议与内核适配

**Files:** `services/quant-api/app/api/market_newow.py`、`services/quant-api/app/market_data/newow/product_service.py` 及其现有 serializer/schema；新建 `services/quant-api/app/market_data/newow/product_macd.py`；`apps/quant-web/src/types/newowProduct.ts`、`apps/quant-web/src/utils/newowProductTypes.ts`；对应 `services/quant-api/tests/newow/test_product_macd.py`、既有 API/readonly/cache tests、`apps/quant-web/tests/newowProductTypes.test.ts`。

**Consumes:** `ProductReadSet` 的 completed lifecycle replay bars；既有 auxiliary envelope/snapshot/budget；`macd_series`。
**Produces:** `component='macd'` 的 typed auxiliary 分支，段内 dif/dea/histogram 每点含时间和值/ready/valid/reason，独立 display adapter 版本和参数 hash。

- [x] 读当前 schema/serializer/kernel 的真实签名，新增失败测试：同前缀与内核逐点相等；每个物理段独立重置；as_of 截断与显示窗改变不改重叠值；零与 warming；旧组件响应兼容；不调用 provider、不影响 Action/Reference ID。

```python
# 使用已有 fixture readset 和真实内核返回结构，不手写黄金数值。
expected = macd_series(closes, fast=12, slow=26, signal=9,
    ema_seed_policy="sma_window", histogram_scale=2, round_digits=6)
# 同前缀逐点对比 dif/dea/histogram、ready/valid/reason。
```

- [x] 运行 `TESTING.md` 的 Newow MACD 定向入口确认 RED；只允许新增协议/适配测试失败，不将环境错误作为 RED。
- [x] 以薄适配实现；逐段计算再裁剪，与既有段 reader/proof 共用。新增 component 白名单、Python 序列化与 TS 判别分支，保留旧形状；cache key 纳入 adapter/参数，不改已有预算。

```ts
export type NewowAuxiliaryComponent =
  'macd' | 'main_force_control' | 'up_down_energy' | 'zhaoyao_mirror' | 'cup_handle'
// normalize 的 macd 分支逐点验证：有限值或 null、时间对齐、长度、ready/valid/reason。
```

- [x] GREEN 后运行 API/readonly/cache 相关回归及 TS types；同步 active OpenSpec 中允许的只读 MACD 分支，未改策略内核版本。
- [x] 自审、定向 secret/diff 检查、Task commit；独立 task Review 并关闭 finding。

## Task 2：白色 Shell、折叠摘要、解释弹窗与参考卡片

**Files:** `MarketDetailPage.vue`、`MarketDetailViewNav.vue`、`MarketDetailQuoteHeader.vue`（显式 Newow 变体）；现有 controller 暴露已读取产品目录，新建 `useNewowDailyQuote.ts` 及测试（已有 Market bars/page 的两根日线，只供页头，无 WS/research）；`NewowProductWorkspace.vue`、`NewowReferencePanel.vue`、`NewowExplanationPanel.vue`；新建 `NewowDetailDialog.vue`、`newowDetailPresentation.ts`、局部 `newowDetail.css`；对应 presentation/unit/E2E tests。路径分别位于现有 pages/market、components/market/detail/newow、utils、styles 目录。

**Consumes:** 现有 controller 元数据/quote、route serializer、chart/reference/explanation/comparator section、既有 ViewModel、Task 1 MACD component。
**Produces:** 全宽 Newow 页面，原生 dialog，正确身份的 summary、纵向参考卡片和按需资源；workspace 将当前辅助 response 传给 Task 3 chart。

- [x] 新增失败用例：不同 frame 状态/缺失/历史窗口标签；reference/explanation 未请求不产生数值；切 identity 关闭弹窗并清理；空/错误/过期保持可见；价格 badge；参考 OPEN/CLOSED/中断区分。

```ts
// 纯投影接口，保留 source 时间而不推断账户。
type DetailStatus = { label: string; state: string; barEnd: string | null; historical: boolean }
// 输入 chart response + lifecycle；目标价必须由同 identity/as_of/proof 的 explanation 提供。
```

- [x] 运行对应 tests 确认 RED，实现 Newow 局部变量和 Shell 变体。产品选择来自现有目录；导航只用 `resolveViewSwitchIdentity` / serializer，其他视角原样。
- [x] 页头独立读取 `getMarketBarsPage({series_kind:"actual_dominant",symbol,frequency:"1d",limit:2})`；严格校验 request、Bar 次序/数值/覆盖及 resolved_contract_segments，复用现有 Bar-to-owner 校验。产品 generation/取消隔离，频率/策略切换不重复请求，跨合约不算涨跌，失败不抑制主图。增加相关 controller/quote tests；此有界报价不是通用图表流。
- [x] 替换研究 tabs：图上摘要折叠，状态/信息 icon 开 dialog；保留当前 explanation 与独立 comparator 作为按需入口，不自动触发重型 comparator。

```vue
<button :aria-expanded="detailsOpen" aria-controls="newow-details" @click="toggleDetails">展开详情</button>
<NewowDetailDialog :open="dialogKind !== null" title="策略解释" @close="closeDialog">
  <!-- 仅渲染当前 dialog context 的真实 section 或选中 marker 事实 -->
</NewowDetailDialog>
```

- [x] dialog 使用原生 showModal/close 的焦点隔离并处理 Escape/cancel、遮罩与焦点恢复；组件销毁不残留遮罩和监听器。历史 Action 解释不复用当前综合解释。
- [x] reference 以 IntersectionObserver 首次可见加载，显式 retry，加载后进入视口不重复；每笔 `<article>` 保留原有 data-reference-category/initial/selected 语义。详细 ID/Hint 收入展开，统计与筛选保留但压缩，cursor 仍手动加载更多。

```vue
<article v-for="row in visibleModel?.rows ?? []" :key="row.id" :data-reference-category="row.category">
  <header>{{ row.statusText }} · {{ row.trade.physical_contract }}</header>
  <p>参考建仓 {{ row.trade.entry_reference_price }} · {{ row.trade.entry_bar_end }}</p>
  <button @click="emit('locate', row.trade)">定位</button>
</article>
```

- [x] 最近 frame 和目标必须标实际时间；历史定位后的 summary 不冒充当前；没有目标兼容证明即不展示数值。
- [x] 定向 unit/build 与弹窗/参考/browser 行为 GREEN，更新因交互有意改变的测试选择器和按需请求时机，不删身份、stale、cursor 回归。Task commit、独立 Review/修正。

## Task 3：主图、成交量、单一副图与图形语言

**Files:** `NewowProductChartStage.vue`、`newowProductChartPrimitives.ts`、按需新增局部 band primitive；`NewowProductWorkspace.vue` 的图表 props 接线；`NewowProductChartStage.test.ts`、`newowProductChartPrimitives.test.ts`、相关 browser specs。

**Consumes:** chart response；auxiliary response + lifecycle；selected signal；Task 1 的 MACD points。**Produces:** 同时间索引的价格/volume/单辅助 pane、局部白色主题、历史定位/缩放/全屏，图例点击解释事件。

- [x] 先测试：volume 零值/颜色；主副图时间映射只匹配当前合法 owner/segment/bar_end；缺值和换月断线；MACD 正负柱、warming gap；副图重复点击不关闭；listener/pane/series 释放。

```ts
// 必须先按 chart authority 的 time + physicalContract + segmentId 对齐；禁止按数组序号 zip。
const chartTime = chartMarkerTime(bar.barEnd, model.identity.frequency, bar.tradingDay)
// 新 pane 只增加绘制序列，不重新计算任何指标值。
```

- [x] 实现统一 chart 的 volume HistogramSeries 与辅助 pane，独立纵轴/零线，共享 timeline；默认 macd 一次按合法 chart identity 请求，切指标只加载该分支，不重复拉主图/reference。
- [x] 趋势带用现有 A/B 和状态的段内 primitive，缺值不连线。保留 oscillation/main_rise 原始键，少量可读 reference markers；Hint 原值通过信息入口可查。
- [x] full-screen、resize、时间轴、回到最新、加载更早、exact locate 保留；实际历史标记弹窗身份与页面摘要分开。
- [x] GREEN 后扩展 chart unit/build 与九组合 browser 场景，Task commit、独立 Review/修正。

## Task 4：完整验收、视觉复核与集成候选

**Files:** `e2e/newow-product.spec.mjs`、`e2e/newow-product.helpers.mjs`、新增 `e2e/newow-detail-light.spec.mjs` 与截图；`PROJECT_SOURCE.md`、`openspec/specs/newow-product-reference-trading/spec.md`、必要 `TESTING.md`、本计划勾选状态。

- [x] Fixture 增加 MACD 分支和足量参考记录，保持本地白名单、拒绝未知网络请求；浏览器截图为受控 fixture，不访问生产服务。
- [x] 覆盖 AC01–08：四个桌面尺寸+390、折叠前后、dialog键盘/遮罩/焦点、纵向记录/加载更多/筛选/统计、九组合切换、错误/空/过期/旧服务端 MACD 不支持。颜色/几何与批准图目视比较，生成图不能当像素 golden。

```js
await expect(page.getByRole('dialog')).toBeVisible()
await page.keyboard.press('Escape')
await expect(page.getByRole('dialog')).not.toBeVisible()
await expect(trigger).toBeFocused()
expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
```

- [x] 依次完成直接测试、完整 Web unit/build、Newow/Home/详情必要 E2E、后端 Task1 回归、工程/OpenSpec/secret/diff。不因纯 UI 改动运行生产 smoke。
- [x] 对照最终代码更新稳定产品 canonical；STATUS 不添加视觉已上线声明。保留现有 evidence gaps 和非 Runtime 验收。
- [x] 自审后固定 branch base..HEAD，派独立 Standards 与 Spec reviewers；修正后按 finding 范围复验再复审。保留 exact refs 和真实输出。
- [x] 全部通过后提交/推送 task，按已授权 Lane2 流程集成 develop 并核对远端。仅清理已安全合入且干净的 task worktree/branch，Runtime 和其他任务 worktree 不动。

## 验收映射

AC01/02/03/06 → Task2；AC04 → Task3；AC05 → Task1；AC07/08 → Task4。任何必要检查未通过不得标记完成；设计图批准不等于原站完整 page parity 或真实数据验收。

验收执行说明：Task 1–3 已各自完成独立 Review/修正；Task 4 的本地检查与视觉回归结果见当前 task 提交。全分支独立 Standards/Spec Review、最终推送和集成由主任务执行，末两项保持未勾选。截图是受控 fixture，不关闭原站完整 parity、真实性能或 Runtime evidence Gate。

完成记录（2026-09-08）：最终实现 `12c844d360ce14f4c6ff7f19d25cabf4fbe92742`，Standards Review 通过，Spec 的 Hint 叠层问题修正后独立复审通过，剩余发现为 0。已合入并核对远端 `develop@222b1262cc1c3963a0e13e90e483c4214cc63750`，完整审查与验证摘要见集成提交 `2cde4a734c18a5340e0828c8fe9a3dee3585ca60`。任务 worktree 和本地/远端分支已清理；main、release、Runtime 和生产数据未操作。
