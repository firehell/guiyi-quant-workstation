import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { parse } from '@vue/compiler-sfc'

const componentUrl = new URL('../src/pages/market/MarketDetailPage.vue', import.meta.url)
const newowWorkspaceUrl = new URL('../src/components/market/detail/newow/NewowProductWorkspace.vue', import.meta.url)
const mainLayoutUrl = new URL('../src/layouts/MainLayout.vue', import.meta.url)

function page() {
  const source = readFileSync(componentUrl, 'utf8')
  const parsed = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(parsed.errors, [], 'MarketDetailPage must remain a valid Vue SFC')
  assert.ok(parsed.descriptor.scriptSetup)
  assert.ok(parsed.descriptor.template)
  return { source, template: parsed.descriptor.template.content }
}

test('activates generic facts and mounts Newow in the unified workspace', () => {
  const { source, template } = page()

  assert.doesNotMatch(source, /import TrendDetailWorkspace/)
  assert.match(source, /\['newow',\s*'free',\s*'htdy',\s*'subing'\]\.includes\(explicitIdentity\.value\?\.view/)
  assert.match(source, /\['newow',\s*'free',\s*'htdy',\s*'subing'\]\.includes\(result\.identity\.view/)
  assert.match(source, /identity\.strategy \?\? ''/)
  assert.match(template, /:identity="routeResult\.identity"/)
  assert.match(template, /:header="header"/)
  assert.match(template, /:bars="controller\.bars\.value"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy' && header"/)
  assert.match(template, /<SubingDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'subing' && header"/)
  assert.match(source, /import NewowProductWorkspace/)
  assert.match(template, /<NewowProductWorkspace\s+v-if="routeResult\.identity\.view === 'newow' && newowCapabilities\.capabilities\.value && newowFrequencyOpen"/)
  assert.match(template, /:capabilities="newowCapabilities\.capabilities\.value"/)
  assert.match(template, /切换到已开放周线/)
  assert.match(template, /<FreeChartWorkspace\s+v-else-if="routeResult\.identity\.view === 'free' && header"/)
  assert.doesNotMatch(template, /<HtdyDetailWorkspace\s+v-else(?:\s|>)/)
  assert.doesNotMatch(template, /TrendDetailWorkspace/)
})

test('gives active analysis views their own history, while alert management remains unavailable', () => {
  const { source, template } = page()

  assert.match(source, /subingWorkspace\.value\?\.openHistory\(\)/)
  assert.match(source, /newowWorkspace\.value\?\.openHistory\(\)/)
  assert.doesNotMatch(source, /hasTrendHistory|trendWorkspace/)
  assert.match(template, /canOpenHistory:/)
  assert.match(template, /newowCapabilities\.isSectionOpen\('reference'\)/)
  assert.match(template, /'预警记录'\s*:\s*'参考记录'/)
  assert.match(template, /canManageAlert:\s*false/)
  assert.match(template, /<SubingDetailWorkspace[^>]+focus-bar-end/s)
})

test('keeps Free HTDY and SuBing as separate explicit adapters inside the stable workspace slot', () => {
  const { template } = page()

  assert.match(template, /<NewowProductWorkspace\s+v-if="routeResult\.identity\.view === 'newow' && newowCapabilities\.capabilities\.value && newowFrequencyOpen"/)
  assert.match(template, /<FreeChartWorkspace\s+v-else-if="routeResult\.identity\.view === 'free' && header"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy' && header"/)
  assert.match(template, /<SubingDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'subing' && header"/)
  assert.equal((template.match(/data-detail-section="workspace-slot"/g) ?? []).length, 1)
})

test('canonicalizes omitted and legacy Trend routes without presenting the retired workspace', () => {
  const { source, template } = page()
  assert.match(source, /route\.query\.view === undefined \|\| route\.query\.view === 'trend'/)
  assert.match(source, /旧趋势详情已迁移到牛哇趋势策略/)
  assert.match(template, /data-testid="market-detail-migration-notice"/)
  assert.doesNotMatch(template, /routeResult\.identity\.view === 'trend'/)
})

test('keeps navigation and one workspace slot mounted while source data changes locally', () => {
  const { source, template } = page()
  assert.match(template, /<main class="market-detail-page unified-detail-light"/)
  assert.doesNotMatch(template, /'newow-detail-light': isNewowView/)
  assert.match(template, /<MarketDetailQuoteHeader[^>]+:unified="isWorkspacePreview"/)
  assert.match(template, /<MarketDetailQuoteHeader[^>]+:newow="isNewowView"/)
  assert.doesNotMatch(source, /\.newow-detail-light/)
  assert.match(template, /<MarketDetailViewNav[\s\S]+<section\s+class="market-detail-page__workspace"/)
  assert.match(template, /data-detail-section="workspace-slot"/)
  assert.match(template, /:data-active-view="routeResult\.identity\.view"/)
  assert.match(template, /:aria-busy="controller\.state\.value\.loading"/)
  assert.match(template, /<p\s+v-if="controller\.state\.value\.loading && routeResult\.identity\.view !== 'newow'"[\s\S]+正在加载当前图表/)
  assert.doesNotMatch(template, /<p v-if="controller\.state\.value\.loading" class="market-detail-page__loading"[\s\S]+<MarketDetailViewNav/)
})

test('gives every market detail route the same full-width layout canvas', () => {
  const source = readFileSync(mainLayoutUrl, 'utf8')
  assert.match(source, /'content--market-detail': route\.name === 'market-chart'/)
  assert.match(source, /\.content\.content--market-detail \{ padding: 0; background: #fff; \}/)
  assert.doesNotMatch(source, /content--newow-detail|route\.query\.view === 'newow'/)
})

test('accepted Newow chart starts first-screen research once without viewport observation', () => {
  const workspace = readFileSync(newowWorkspaceUrl, 'utf8')

  assert.match(workspace, /loadFirstScreenResearch/)
  assert.match(workspace, /loader\.loadReference\(\)/)
  assert.match(workspace, /sectionOpen\('explanation'\)/)
  assert.doesNotMatch(workspace, /IntersectionObserver/)
  assert.equal((workspace.match(/<NewowExplanationPanel/g) ?? []).length, 1)
  assert.doesNotMatch(workspace, /detailsOpen|newow-details/)
  assert.match(workspace, /<MarketDetailUnavailable v-if="chartResponse === null/)
})

test('historical Newow mode hides the independent current quote and contract header', () => {
  const { source, template } = page()
  const workspace = readFileSync(newowWorkspaceUrl, 'utf8')
  assert.match(source, /const newowHistoricalAsOf = ref<string \| null>\(null\)/)
  assert.match(template, /MarketDetailQuoteHeader v-if="!controller.state.value.error && header && !\(isNewowView && newowHistoricalAsOf\)"/)
  assert.match(template, /@snapshot-mode="newowHistoricalAsOf = \$event"/)
  assert.match(workspace, /查看最近可用历史快照/)
  assert.match(workspace, /返回当前/)
})
