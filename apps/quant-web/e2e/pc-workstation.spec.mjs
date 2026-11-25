import { mkdir } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { detailBar, installDetailFakeWebSocket, mockMarketDetail } from './market-detail.helpers.mjs'

const at = '2026-09-03T02:30:00.000Z'
const account = { key: 'fixture-tq', alias: '快期模拟主账户', environment: 'TQKQ', strategy: '火天大有', scope_product: null, policy_version: 'fixture' }
function portfolio() {
  return {
    run_id: 'fixture-paper', status: 'RUNNING', observed_at: at, trading_day: '2026-09-03', auto_order: false, day_net: '20',
    account: { equity: '100020', policy: { products: ['jm'] } }, products: [{ product: 'jm', enabled: true, accounts: [
      { contract: 'JM2601', valuation_at: at, summary: { open_quantity: 1 }, open_layers: [{ side: 'LONG' }], pending: { kind: 'CLOSE', at }, fills: [] },
      { contract: 'JM2701', valuation_at: at, summary: { open_quantity: 0 }, open_layers: [], pending: { kind: 'OPEN', at }, fills: [] },
    ] }],
  }
}
const fillTime = detailBar('jm', 110).bar_end
const records = [
  { id: 'order:1', kind: 'order', at, product: 'JM', contract: 'JM2601', status: 'WORKING', label: '已受理',
    order_id: '1', signal_id: null, facts: { offset: 'CLOSE', quantity: '3' } },
  { id: 'fill:1', kind: 'fill', at: fillTime, product: 'JM', contract: 'JM2601', status: 'RECORDED', label: '已成交',
    order_id: '1', signal_id: null, facts: { filled_at: fillTime, price: '208', quantity: '1', native_precision_seconds: '0.000001' } },
]
async function fixtures(page, { live = true } = {}) {
  const requests = await mockMarketDetail(page, {
    live,
    barsPage({ url, symbol }) {
      const frequency = url.searchParams.get('frequency')
      if (frequency === '1d') return
      return { bars: Array.from({ length: 180 }, (_, i) => ({
        ...detailBar(symbol, i), physical_contract: url.searchParams.get('contract') || symbol.toUpperCase() + '2601',
      })) }
    },
  })
  await page.route('**/api/v1/market/dominants', route => route.fulfill({ json: { items: [
    { product: 'jm', product_name: '焦煤', exchange: 'DCE', actual_contract: 'JM2701' },
    { product: 'rb', product_name: '螺纹钢', exchange: 'SHFE', actual_contract: 'RB2601' },
  ] } }))
  let stale = false
  let model = portfolio()
  await page.route('**/api/v1/subing-portfolio/status', route => route.fulfill({ json: model }))
  await page.route('**/api/v1/subing-portfolio/history', route => route.fulfill({ json: { ...model, status: 'NOT_REGISTERED', run_id: null } }))
  await page.route('**/api/simulation/monitor/overview', route => route.fulfill({ json: {
    version: 'simulation_monitor_v1', status: 'available', snapshot: 'fixture', generated_at: at, account,
    observer: { status: stale ? 'stale' : 'running', stage: 'OBSERVING', published_at: at, connection: 'LOGGED_IN' },
    readback_at: at, trading_day: '2026-09-03', readback_status: stale ? 'stale' : 'verified', position_projection_complete: !stale,
    metrics: { equity: '100000', net_profit: null }, positions: [], curve: [], issues: [], coverage: 'complete',
    performance_status: 'ACCOUNT_EQUITY_ONLY', source_times: {},
  } }))
  await page.route('**/api/simulation/monitor/records?*', route => route.fulfill({ json: {
    version: 'simulation_monitor_v1', snapshot: 'fixture-records', items: records, available_count: 2, next_cursor: null, coverage: 'complete',
  } }))
  await page.route('**/api/v1/newow/backtests/**', route => route.fulfill({ json: { result: null, last_attempt: null } }))
  await installDetailFakeWebSocket(page)
  return { requests, setStale() { stale = true; model = { ...model, run_id: null, status: 'NOT_STARTED', products: [] } } }
}

async function chartProbe(page) {
  const path = '**/src/utils/detailChartSession.ts*'
  await page.route(path, async route => {
    const response = await route.fetch()
    const source = await response.text()
    const instrumented = source.replace('chart = dependencies.createChart(surface, options);', `chart = dependencies.createChart(surface, options);
      const probe = globalThis.workstationProbe = { native: chart, creates: (globalThis.workstationProbe?.creates ?? 0) + 1, adds: {}, data: {}, fits: 0, cursor: null };
      const add = chart.addSeries.bind(chart);
      chart.addSeries = (definition, settings, pane) => {
        const series = add(definition, settings, pane);
        const role = definition.type === 'Candlestick' ? 'candles' : settings?.priceScaleId === 'volume' ? 'volume' : null;
        if (role) {
          probe.adds[role] = (probe.adds[role] ?? 0) + 1;
          const setData = series.setData.bind(series);
          series.setData = rows => { probe.data[role] = (probe.data[role] ?? 0) + 1; return setData(rows); };
          probe[role] = series;
        }
        return series;
      };
      const crosshair = chart.setCrosshairPosition.bind(chart);
      chart.setCrosshairPosition = (price, time, series) => {
        probe.restoredCursor = { time, price };
        return crosshair(price, time, series);
      };
      const base = executions.setData.bind(executions);
      executions.setData = points => { probe.executionPoints = points; return base(points); };
      const scale = chart.timeScale();
      const fit = scale.fitContent.bind(scale);
      scale.fitContent = () => { probe.fits++; return fit(); };
      chart.subscribeCrosshairMove(event => {
        if (event.time !== undefined && event.point && event.paneIndex === 0) probe.cursor = {time:event.time, price:probe.candles.coordinateToPrice(event.point.y)};
      });`)
    expect(instrumented).not.toBe(source)
    await route.fulfill({ response, body: instrumented })
  })
}
const reading = (page) => page.evaluate(timestamp => {
  const probe = globalThis.workstationProbe
  const scale = probe.native.timeScale()
  return { creates: probe.creates, adds: probe.adds, data: probe.data, fits: probe.fits, viewport: scale.getVisibleRange(),
    order: [scale.timeToCoordinate(Math.floor(Date.parse(timestamp) / 1000)), probe.candles.priceToCoordinate(208)],
    subscriptions: window.__marketDetailSockets.map(socket => socket.url), cursor: probe.cursor, restoredCursor: probe.restoredCursor, points: probe.executionPoints }
}, fillTime)
const desktopEvidence = process.env.PLAYWRIGHT_WORKSTATION_SCREENSHOTS
async function screenshot(page, name) {
  if (!desktopEvidence) return
  await mkdir(desktopEvidence, { recursive: true })
  await page.screenshot({ path: `${desktopEvidence}/${name}.png`, animations: 'disabled' })
}

test('operations reads two independent accounts, goes directly to the held old contract and restores the watchlist', async ({ page }) => {
  const fixture = await fixtures(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '运行台' })).toBeVisible()
  const closing = page.getByRole('row').filter({ hasText: '模型动作 · 待平仓' })
  await expect(closing).toContainText('苏冰独立 Paper 模型账本')
  await expect(closing).toContainText('JM2601')
  await expect(closing).toContainText('多 1 手')
  const opening = page.getByRole('row').filter({ hasText: '模型动作 · 待开仓' })
  await expect(opening).toContainText('JM2701')
  await expect(opening).toContainText('空仓')
  await expect(page.getByRole('row').filter({ hasText: '部分成交' })).toContainText('快期模拟主账户')
  await expect(page.getByText(/全部活动委托未核验/)).toBeVisible()
  await screenshot(page, '运行台-隔离样本')
  await closing.getByRole('link', { name: /看图/ }).click()
  await expect(page).toHaveURL(/view=subing.*contract=JM2601/)
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await expect.poll(async () => Number(await page.locator('[data-kline-count]').getAttribute('data-kline-count'))).toBe(180)
  await expect(page.getByRole('checkbox', { name: '委托/成交' })).toBeChecked()
  const strip = page.getByRole('region', { name: '合约列表' })
  const search = strip.getByRole('searchbox')
  await strip.getByRole('button', { name: '持仓/挂单' }).click()
  await expect(strip.getByRole('button', { name: /JM2601/ }).first()).toBeVisible()
  await strip.getByRole('button', { name: '全部', exact: true }).click()
  await search.fill('螺纹')
  await expect(strip.getByRole('button', { name: /RB2601\s*螺纹钢/ })).toBeVisible()
  await strip.getByRole('button', { name: '关注 RB2601' }).click()
  await page.reload()
  await strip.getByRole('button', { name: '重点关注', exact: true }).click()
  await expect(strip.getByRole('button', { name: /RB2601\s*螺纹钢/ })).toBeVisible()
  await strip.getByRole('button', { name: '取消关注 RB2601' }).click()
  await expect(strip.getByText('尚未添加关注合约')).toBeVisible()
  fixture.setStale()
  await page.getByRole('tab', { name: '运行台' }).click()
  await expect(page.getByText('苏冰 · 尚无 run')).toBeVisible()
  await expect(page.getByText(/核验过期或未通过/)).toBeVisible()
  await page.getByRole('tab', { name: '行情' }).click()
  await expect(page).toHaveURL(/view=subing.*contract=JM2601/)
})

test('strategy and indicator changes preserve a panned chart, requests, order coordinates and frozen research', async ({ page }) => {
  const { requests } = await fixtures(page)
  await chartProbe(page)
  const calls = []
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) calls.push(request.method())
  })
  let releaseTrend
  const trendReady = new Promise(resolve => { releaseTrend = resolve })
  let trendRequested = false
  const frozen = {
    decision_id: 'ref-1', action: 'BUILD', frequency: '15m', signal_bar_end: fillTime,
    bar: { ...detailBar('jm', 110), frequency: '15m', completed: true },
  }
  const result = run => ({ run_id: run, as_of_trading_day: '2026-09-03', finished_at: at,
    qualification: 'QUALIFIED', manifest: { physical_contract: 'JM2601' },
    summary: { result_kind: 'reference_only', decisions: [frozen] } })
  await page.route('**/api/v1/newow/backtests/latest?*', async route => {
    const strategy = new URL(route.request().url()).searchParams.get('strategy')
    if (strategy === 'trend' && !trendRequested) {
      trendRequested = true
      await trendReady
    }
    if (strategy === 'dual_fusion') return route.fulfill({ status: 503, json: {} })
    try { await route.fulfill({ json: { result: result(strategy), last_attempt: null } }) }
    catch { /* The obsolete request may already have been cancelled by the browser. */ }
  })
  await page.goto('/market/chart?view=free&symbol=jm&series_kind=actual_dominant&frequency=15m')
  const canvas = page.locator('.tv-lightweight-charts').first()
  await expect(canvas).toBeVisible()
  await page.getByRole('checkbox', { name: '委托/成交' }).check()
  await expect(page.getByRole('region', { name: '只读委托与成交' })).toContainText('快期原生成交')
  for (const name of ['EMA10', 'EMA21', 'EMA60', '箱体识别', '形态识别', '震荡／趋势']) {
    const control = page.getByRole('button', { name: new RegExp(name) }).first()
    await expect(control).toBeVisible()
    await control.click()
  }
  await canvas.scrollIntoViewIfNeeded()
  const bounds = await canvas.boundingBox()
  const y = Math.min(bounds.y + 160, page.viewportSize().height - 32)
  await page.mouse.move(bounds.x + bounds.width * .5, y)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width * .66, y, { steps: 8 })
  await page.mouse.up()
  await page.mouse.wheel(0, -550)
  await page.mouse.move(bounds.x + bounds.width * .62, y)
  await expect.poll(async () => (await reading(page)).cursor).not.toBeNull()
  await expect.poll(async () => (await reading(page)).order[0]).not.toBeNull()
  await page.waitForTimeout(250)
  const before = await reading(page)
  const counts = () => requests.filter(url => url.pathname.endsWith('/bars/page') && url.searchParams.get('frequency') === '15m').length
  const initialRequests = counts()
  expect(before.points).toHaveLength(1)
  expect(before.cursor).not.toBeNull()
  await page.getByRole('tab', { name: '火天大有' }).click()
  await expect.poll(async () => (await reading(page)).points).toEqual(before.points)
  await page.getByRole('tab', { name: '苏冰预警' }).click()
  await page.getByRole('tab', { name: '牛哇参考' }).click()
  await expect.poll(() => trendRequested).toBe(true)
  await page.getByRole('button', { name: '震荡', exact: true }).click()
  await expect(page.getByTestId('newow-backtest-identity')).toContainText('数据截至交易日 2026-09-03')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '1')
  releaseTrend()
  await page.getByRole('button', { name: '冻结行情切片' }).click()
  await expect(page.getByLabel('冻结参考输入')).toContainText('Run oscillation')
  await page.getByRole('button', { name: '双策略', exact: true }).click()
  await expect(page.getByText('回测结果读取失败，请刷新重试。')).toBeVisible()
  await expect(canvas).toBeVisible()
  await page.getByRole('tab', { name: '自由看盘' }).click()
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  const after = await reading(page)
  expect(after.creates).toBe(before.creates)
  expect(after.adds).toEqual(before.adds)
  expect(after.data).toEqual(before.data)
  expect(after.cursor.time).toBe(before.cursor.time)
  expect(after.cursor.price).toBeCloseTo(before.cursor.price, 10)
  expect(after.restoredCursor.time).toBe(before.cursor.time)
  expect(after.restoredCursor.price).toBeCloseTo(before.cursor.price, 10)
  expect(after.points).toEqual(before.points)
  expect(after.fits).toBe(before.fits)
  expect(after.viewport).toEqual(before.viewport)
  expect(after.subscriptions).toEqual(before.subscriptions)
  expect(counts()).toBe(initialRequests)
  expect(after.order[0]).toBeCloseTo(before.order[0], 0)
  expect(after.order[1]).toBeCloseTo(before.order[1], 0)
  expect(calls.every(method => method === 'GET')).toBe(true)
  await screenshot(page, '行情-隔离样本')
  await page.getByRole('tab', { name: '牛哇参考' }).click()
  await expect(page.getByRole('button', { name: '双策略', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('checkbox', { name: '委托/成交' }).uncheck()
  await expect.poll(async () => (await reading(page)).points).toEqual([])
  await page.getByRole('tab', { name: '研究' }).click()
  await expect(page.getByRole('heading', { name: '牛哇盘后与固定回测' })).toBeVisible()
  await page.getByRole('link', { name: '苏冰历史回放' }).click()
  await expect(page.getByRole('button', { name: '历史回放' })).toHaveAttribute('aria-pressed', 'true')
})
