import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('home and detail share one global market navigation and one product selector', () => {
  const homeHeader = read('../src/components/market/MarketHomeHeader.vue')
  const detailPage = read('../src/pages/market/MarketDetailPage.vue')
  const navigation = read('../src/components/market/MarketNavigation.vue')

  assert.match(homeHeader, /<MarketNavigation/)
  assert.match(homeHeader, /<ProductSelector/)
  assert.match(detailPage, /<MarketNavigation/)
  assert.match(detailPage, /<ProductSelector|MarketDetailViewNav/)
  for (const label of ['运行台', '行情', '研究']) assert.match(navigation, new RegExp(`>${label}<`))
  assert.match(navigation, />\s*消息\s*</)
  assert.doesNotMatch(homeHeader, /v-for="item in views"/)
  assert.doesNotMatch(homeHeader, /market-home-view-products/)
})

test('detail groups the three flat Newow options behind the reference view', () => {
  const source = read('../src/components/market/detail/MarketDetailViewNav.vue')
  const page = read('../src/pages/market/MarketDetailPage.vue')
  assert.match(source, /aria-label="分析选项"/)
  assert.match(source, />牛哇参考<\/button>/)
  assert.match(source, /v-if="identity.view === 'newow'"[^>]+aria-label="牛哇策略"/)
  for (const label of ['趋势', '震荡', '双策略']) assert.match(source, new RegExp(`label: '${label}'`))
  assert.match(page, /<ContractStrip/)
  assert.equal((source.match(/<DetailChartToolbar/g) ?? []).length, 1)
  const toolbar = read('../src/components/market/detail/DetailChartToolbar.vue')
  assert.equal((toolbar.match(/aria-label="周期"/g) ?? []).length, 1)
})

test('Market Home renders the complete filtered list without a fake load-more footer', () => {
  const page = read('../src/pages/market/index.vue')
  const styles = read('../src/styles/marketHome.css')
  assert.doesNotMatch(page, /已显示|向下滚动查看更多|market-home-list-footer/)
  assert.doesNotMatch(styles, /market-home-list-footer/)
})

test('the top bar is the only product identity header above the chart', () => {
  const quote = read('../src/components/market/detail/MarketDetailQuoteHeader.vue')
  assert.doesNotMatch(quote, /<h1>|header\.productName/)
  assert.match(quote, /quote-header__primary/)
})

test('detail top bar names return and record destinations explicitly', () => {
  const source = read('../src/components/market/detail/MarketDetailTopBar.vue')
  assert.match(source, /返回市场/)
  assert.match(source, /historyLabel/)
  assert.doesNotMatch(source, /aria-label="返回"/)
})

test('home uses strategy cards instead of an inactive quote table', () => {
  const page = read('../src/pages/market/index.vue')
  assert.match(page, /<MarketHomeStrategyCards/)
  assert.doesNotMatch(page, /MarketHomeTable|MarketHomeMobileList|MarketHomeLegend/)
})
