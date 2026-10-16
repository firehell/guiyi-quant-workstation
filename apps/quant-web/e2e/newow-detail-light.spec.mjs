import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, buildNewowSplitFixtureEnvelopeForTest, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

async function openRawReference(page) {
  const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await region.scrollIntoViewIfNeeded()
  await region.getByRole('button', { name: '已完成参考交易' }).click()
  return region
}

const mainExplanation = page => page.getByTestId('newow-product-chart-stage').locator('.newow-product-chart-stage__main-legend')

test('daily summary loads selected reference on visibility and keeps deferred explanation explicit', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true })
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto(newowRoute())
  const workspace = page.locator('[data-detail-workspace="newow"]')
  await expect(workspace).toHaveAttribute('data-chart-state', 'ready')
  await expect(workspace).toHaveAttribute('data-auxiliary-state', 'ready')
  const chartBox = await page.getByTestId('newow-product-chart-stage').boundingBox()
  const statusBox = await page.getByRole('region', { name: '日周状态摘要', exact: true }).boundingBox()
  expect(chartBox).not.toBeNull()
  expect(statusBox).not.toBeNull()
  expect(chartBox.y).toBeGreaterThanOrEqual(statusBox.y + statusBox.height)
  await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('newow-product-chart-stage')).toBeInViewport()
  await expect(page.locator('.unified-detail-light')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  expect(productRequests(fixture, 'explanation').filter(item => !item.url.searchParams.has('decision_v2'))).toHaveLength(0)
  expect(productRequests(fixture, 'comparator')).toHaveLength(0)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(0)
  await expect(page.locator('.quote-header')).toContainText('最近日线收盘')
  await expect(page.locator('.quote-header__price strong')).not.toHaveText('—')
  const quoteRequests = () => fixture.requests.filter(item => item.url.pathname.endsWith('/bars/page'))
  expect(quoteRequests()).toHaveLength(1)
  expect(Object.fromEntries(quoteRequests()[0].url.searchParams)).toMatchObject({ frequency: '1d', limit: '500', symbol: 'rb', series_kind: 'actual_dominant' })
  expect(quoteRequests().some(item => item.url.searchParams.get('limit') === '2')).toBe(false)
  await page.screenshot({ path: '/private/tmp/newow-task2-shell.png' })
  const info = mainExplanation(page)
  await info.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('尚未开放跨周期综合解释')
  await expect(dialog).toContainText('NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN')
  await expect(dialog.locator('[data-testid="newow-explanation-panel"]')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '知道了', exact: true })).toHaveCSS('background-color', 'rgb(0, 122, 255)')
  await page.screenshot({ path: '/private/tmp/newow-task2-dialog.png' })
  expect(productRequests(fixture, 'comparator')).toHaveLength(0)
  for (let index = 0; index < 10; index++) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(info).toBeFocused()
  await expect(page.locator('#newow-details')).toHaveCount(0)
  await openRawReference(page)
  await expect.poll(() => productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_mode') === 'closed').map(item => item.url.searchParams.get('reference_part'))).toEqual(['overview', 'curve'])
  await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(3)
  await expect(page.locator('.newow-reference table')).toHaveCount(0)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(0)
  await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded()
  await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(0)
  await page.getByRole('button', { name: '查看完整历史记录', exact: true }).click()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(2)
  await page.getByRole('button', { name: '加载更多历史参考记录', exact: true }).click()
  await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(2)
  await expect(page.getByRole('button', { name: '页面比较说明', exact: true })).toHaveCount(0)
  await info.click()
  await expect(dialog).toBeVisible()
  await expect(page.locator('.detail-view-nav').getByRole('button', { name: '60分钟', exact: true })).toHaveCount(0)
  await expect(page.locator('.detail-view-nav').getByRole('button', { name: '日线', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('#newow-details')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  expect(quoteRequests()).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('passive chart marker keeps identity while the legend opens the current explanation', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  const marker = page.getByTestId('newow-product-chart-stage').locator('[data-action-id]').first()
  const markerId = await marker.getAttribute('data-action-id')
  await expect(marker).toHaveAttribute('title', new RegExp(markerId))
  await page.getByTestId('newow-product-chart-stage').locator('.newow-product-chart-stage__main-legend').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('尚未开放跨周期综合解释')
  await expect(dialog).not.toContainText(markerId)
  expect(productRequests(fixture, 'explanation').filter(item => !item.url.searchParams.has('decision_v2'))).toHaveLength(0)
  await page.mouse.click(4, 4)
  await expect(dialog).not.toBeVisible()
  assertNoUnexpectedRequests(fixture)
})

for (const [mode, close, color] of [['up', 105, 'rgb(255, 64, 58)'], ['down', 95, 'rgb(34, 185, 93)'], ['neutral', 100, 'rgb(32, 36, 43)'], ['unavailable', null, 'rgb(32, 36, 43)']]) {
  test(`Newow headline quote uses ${mode} direction color`, async ({ page }) => {
    await installNewowProductFixtures(page, { recordsHistory: true, onProductRequest: async ({ route, url, section }) => {
      if (section !== 'chart' || url.searchParams.get('resolve_current') !== 'true') return
      if (close === null) {
        await route.abort('failed')
        return 'handled'
      }
      const payload = buildNewowSplitFixtureEnvelopeForTest(url, { recordsHistory: true })
      const bars = payload.chart.value.bars
      const previous = bars.at(-2)
      const latest = bars.at(-1)
      Object.assign(previous, { open: '100', high: '112', low: '90', close: '100' })
      Object.assign(latest, { open: '100', high: '112', low: '90', close: String(close) })
      await route.fulfill({ json: payload })
      return 'handled'
    } })
    await page.goto(newowRoute())
    const headline = page.locator('.quote-header__price strong')
    await expect(headline).toHaveText(close === null ? '—' : close.toFixed(2))
    await expect(headline).toHaveCSS('color', color)
  })
}


test('curve selection loads an older reminder without changing the current chart or explanation', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { recordsHistory: true })
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
  await openRawReference(page)
  const chartCount = productRequests(fixture, 'chart').length
  const summary = await page.getByTestId('newow-reference-summary').innerText()
  const curve = page.getByLabel('参考收益曲线，点击查看读数或定位交易记录', { exact: true })
  await expect(curve.locator('polyline')).toHaveCount(2)
  await curve.focus(); await curve.press('Home'); await curve.press('Enter')
  await expect(page.locator('#reference-trade-trend-1d-initial')).toBeVisible()
  expect(productRequests(fixture, 'chart')).toHaveLength(chartCount)
  expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summary)
  await mainExplanation(page).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('尚未开放跨周期综合解释')
  await expect(dialog.getByTestId('newow-window-state')).toContainText('所示图表状态')
  await expect(dialog.getByTestId('newow-window-state')).toContainText('08-03 15:00')
  await expect(dialog.getByTestId('newow-window-state')).not.toContainText('06-30 15:00')
  await expect(dialog.getByTestId('newow-explanation-panel')).toHaveCount(0)
  assertNoUnexpectedRequests(fixture)
})

for (const [width, height] of [[1280, 800], [1440, 900], [1920, 1080], [2560, 1440], [390, 844]]) {
  test(`white detail ${width}x${height}: controlled rich rendering, vertical cards and disclosure`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const fixture = await installNewowProductFixtures(page, { visualRich: true, recordsHistory: true })
    await page.goto(newowRoute())
    const stage = page.getByTestId('newow-product-chart-stage')
    await expect(stage).toHaveAttribute('data-auxiliary-state', 'ready')
    await expect(stage).toHaveAttribute('data-channel-point-count', '95')
    expect(productRequests(fixture, 'explanation').filter(item => !item.url.searchParams.has('decision_v2'))).toHaveLength(0)
    expect(productRequests(fixture, 'comparator')).toHaveLength(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
    await openRawReference(page)
    await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
    const summary = await page.getByTestId('newow-reference-summary').innerText()
    await page.getByRole('button', { name: '查看完整历史记录' }).click()
    await page.getByRole('button', { name: '加载更多历史参考记录' }).click()
    await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
    await expect(page.locator('article[data-reference-category="open"] .newow-reference__record-return')).toHaveAttribute('data-direction', 'down')
    await expect(page.locator('article[data-reference-category="closed"] .newow-reference__record-return').first()).toHaveAttribute('data-direction', 'up')
    await expect(page.locator('article[data-reference-category="open"]')).not.toContainText('T07:00:00.000Z')
    await expect(page.locator('article[data-reference-category="interrupted"]')).toContainText('物理合约区段结束')
    await expect(page.locator('article[data-reference-category="interrupted"]')).not.toContainText('OWNER_BOUNDARY')
    await expect(page.getByRole('combobox', { name: '筛选参考历史' })).toHaveCount(0)
    await expect(page.locator('article[data-reference-category]')).toHaveCount(4)
    expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summary)
    await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded()
    await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
    expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'history')).toHaveLength(2)
    const scrolling = await page.evaluate(() => [...document.querySelectorAll('*')]
      .filter(element => ['auto', 'scroll'].includes(getComputedStyle(element).overflowY) && element.scrollHeight > element.clientHeight + 1)
      .map(element => ({ className: element.className, top: element.scrollTop })))
    expect(scrolling).toHaveLength(1)
    await page.evaluate(() => {
      const target = [...document.querySelectorAll('*')]
        .find(element => ['auto', 'scroll'].includes(getComputedStyle(element).overflowY) && element.scrollHeight > element.clientHeight + 1)
      if (target) target.scrollTop = 0
    })
    await expect(page.locator('.market-navigation__brand')).toBeInViewport()
    await page.mouse.move(0, 0)
    await expect(page).toHaveScreenshot(`newow-light-${width}.png`, { animations: 'disabled', maxDiffPixels: 500 })
    const trigger = mainExplanation(page)
    await trigger.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: '关闭解释', exact: true })).toBeFocused()
    expect(await dialog.locator('.newow-detail-dialog__body').evaluate(element => element.scrollTop)).toBe(0)
    if (width === 1440 || width === 390) await expect(page).toHaveScreenshot(`newow-light-dialog-${width}.png`, { animations: 'disabled', maxDiffPixels: 500 })
    for (let index = 0; index < 12; index++) {
      await page.keyboard.press('Tab')
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
    }
    await page.keyboard.press('Shift+Tab')
    expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await page.mouse.click(4, 4)
    await expect(dialog).not.toBeVisible()
    await expect(trigger).toBeFocused()
    if (width === 390) expect((await trigger.boundingBox()).height).toBeGreaterThanOrEqual(44)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
    assertNoUnexpectedRequests(fixture)
    await testInfo.attach('provenance', { body: 'Local intercepted, coherent synthetic fixture. Approved generated art is a layout/color reference; neither image proves market facts or source page parity.', contentType: 'text/plain' })
  })
}

test('auxiliary indicator rejection and reference failure stay explicit and retry only on request', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, count }) => {
    if (url.searchParams.get('component') === 'zhaoyao_mirror') { await route.fulfill({ status: 422, json: { detail: { code: 'NEWOW_MACD_UNSUPPORTED' } } }); return 'handled' }
    if (url.searchParams.get('section') === 'reference' && count === 1) { await route.fulfill({ status: 503, json: { detail: { code: 'NEWOW_API_UNAVAILABLE' } } }); return 'handled' }
  } })
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', 'error')
  await expect(page.locator('[role="status"]').filter({ hasText: '辅助图层不可用' }).first()).toBeVisible()
  await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
  await expect(page.locator('.newow-reference').getByRole('button', { name: '重试' })).toBeVisible()
  await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded()
  await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
  expect(productRequests(fixture, 'reference').filter(item => !item.url.searchParams.has('history_limit'))).toHaveLength(1)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.has('history_limit'))).toHaveLength(0)
  expect(productRequests(fixture, 'auxiliary')).toHaveLength(1)
  await page.locator('.newow-reference').getByRole('button', { name: '重试' }).click()
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'overview')).toHaveLength(2)
  expect(productRequests(fixture, 'reference').filter(item => item.url.searchParams.get('reference_part') === 'curve')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})


for (const width of [1440, 390]) {
  test(`current FLAT waiting card is independent from paged returns at ${width}`, async ({ page }, testInfo) => {
    const fixture = await installNewowProductFixtures(page, {
      recordsHistory: true,
      onProductRequest: async ({ route, url, section }) => {
        if (!['chart', 'reference'].includes(section)) return
        const payload = buildNewowSplitFixtureEnvelopeForTest(url, { noAction: true, zeroClosed: true })
        if (section === 'chart') {
          payload.chart.value.frames.forEach(frame => { frame.main_state = 'FLAT' })
        } else {
          const value = payload.reference.value
          if (value.reference_part === 'overview') {
            value.recent_items = []
            value.summary.open_count = 0
            value.summary.interrupted_count = 0
            value.summary.rollover_interrupted_count = 0
            value.summary.initial_count = 0
          } else if (value.reference_part === 'history') value.items = []
          else {
            value.curve.points = []
            value.curve.total_points = 0
            value.curve.metrics = { return_percentage_points: null, win_rate_pct: null,
              closed_count: 0, drawdown: null, drawdown_kind: 'equity_ratio' }
          }
        }
        await route.fulfill({ json: payload })
        return 'handled'
      },
    })
    await page.setViewportSize({ width, height: 900 })
    await page.goto(newowRoute())
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
    await page.locator('section.newow-reference').scrollIntoViewIfNeeded()
    await openRawReference(page)
    const waiting = page.getByTestId('newow-reference-waiting')
    await expect(waiting).toContainText('空仓等待中')
    await expect(waiting).toContainText('状态时间 2026-08-03')
    await expect(waiting).not.toContainText('%')
    await expect(waiting.locator('header strong')).toHaveCSS('background-color', 'rgb(37, 99, 235)')
    await expect(page.getByLabel('筛选参考历史')).toHaveCount(0)
    await expect(waiting).toBeVisible()
    await expect(page.getByTestId('newow-reference-summary')).toContainText('暂无已完成参考交易')
    await page.locator('section.newow-reference').screenshot({ path: testInfo.outputPath(`waiting-reference-${width}.png`) })
    assertNoUnexpectedRequests(fixture)
  })
}
