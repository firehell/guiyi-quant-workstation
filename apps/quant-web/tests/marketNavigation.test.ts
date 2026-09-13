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
  assert.match(navigation, />\s*市场\s*</)
  assert.match(navigation, />\s*消息\s*</)
  assert.doesNotMatch(homeHeader, /v-for="item in views"/)
  assert.doesNotMatch(homeHeader, /market-home-view-products/)
})

test('detail analysis navigation uses one flat six-choice order on every view', () => {
  const source = read('../src/components/market/detail/MarketDetailViewNav.vue')
  const page = read('../src/pages/market/MarketDetailPage.vue')
  const labels = ['震荡策略', '趋势策略', '主升浪', '火天大有', '苏冰预警', '自由看盘']
  let previous = -1
  for (const label of labels) {
    const next = source.indexOf(`label: '${label}'`)
    assert.ok(next > previous, `${label} must appear in the fixed order`)
    previous = next
  }
  assert.match(page, /<ProductSelector/)
  assert.doesNotMatch(source, /aria-label="品种代码"|aria-label="全部品种"/)
  assert.doesNotMatch(source, /detail-view-nav__mobile|分析视角 ·/)
  assert.equal((source.match(/aria-label="周期"/g) ?? []).length, 1)
  assert.doesNotMatch(source, /aria-label="Newow策略"|label: '牛哇'|label: 'Newow'|label: '新苏冰'|free: '更多'/)
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

test('home table omits the unavailable target-reference column without changing row facts', () => {
  const source = read('../src/components/market/MarketHomeTable.vue')
  assert.doesNotMatch(source, /目标参考价|target-unavailable/)
  assert.match(source, /日量比/)
  assert.match(source, /日增仓率/)
})
