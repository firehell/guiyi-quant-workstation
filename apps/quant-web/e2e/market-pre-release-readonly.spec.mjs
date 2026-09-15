import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_BACKEND !== '1', 'explicit local candidate read-only acceptance only')
test.describe.configure({ timeout: 300_000 })

const cutoff = '2026-09-14T11:00:00+00:00'
const strategies = ['trend', 'oscillation', 'main_rise']
const homeBudgetMs = 10_000

test('real candidate home keeps 60 products across cold, hard reload and SPA tab return', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const coldStarted = Date.now()
  const coldResponse = await page.request.get('/api/v1/market/research/home-overview')
  const coldMs = Date.now() - coldStarted
  expect(coldResponse.status()).toBe(200)
  expect((await coldResponse.json()).items).toHaveLength(60)
  expect(coldMs).toBeLessThan(homeBudgetMs)

  await page.goto('/market')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('本地候选只读预览')
  await expect(page.locator('.market-home-list-heading')).toContainText('60', { timeout: 30_000 })
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60, { timeout: 30_000 })

  await page.reload()
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60, { timeout: 30_000 })

  const refreshSamples = []
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const refreshStarted = Date.now()
    const response = await page.request.get('/api/v1/market/research/home-overview')
    refreshSamples.push(Date.now() - refreshStarted)
    expect(response.status()).toBe(200)
    expect((await response.json()).items).toHaveLength(60)
  }
  for (const sample of refreshSamples) expect(sample).toBeLessThan(homeBudgetMs)

  await page.getByRole('tab', { name: '消息' }).click()
  await expect(page.getByRole('tab', { name: '消息' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: '市场' }).click()
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60)
  const search = page.getByRole('combobox', { name: '搜索60品种' })
  await search.fill('JM')
  await expect(page.getByRole('option', { name: /焦煤.*JM/ })).toBeVisible()
  await search.press('Enter')
  await expect(page).toHaveURL(/\/market\/chart\?.*symbol=jm/)
  await expect(page.locator('[data-detail-workspace]')).toBeVisible()
  await expect(page.getByRole('combobox', { name: '搜索60品种' })).toBeVisible()
  await expect(page.getByRole('listbox', { name: '搜索60品种' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('real-home-60.png'), fullPage: true })
  const concurrentStarted = Date.now()
  const concurrent = await Promise.all(Array.from({ length: 2 }, () => page.request.get('/api/v1/market/research/home-overview')))
  const concurrentMs = Date.now() - concurrentStarted
  expect(concurrent.map(response => response.status())).toEqual([200, 200])
  expect(concurrentMs).toBeLessThan(homeBudgetMs)
  expect(await concurrent[0].json()).toEqual(await concurrent[1].json())
  console.log(JSON.stringify({ evidence: 'real-home', coldMs, refreshSamples, concurrentMs, concurrentHomeStatuses: concurrent.map(response => response.status()), rows: 60, selector: 'jm-enter-stable', errors }))
  expect(errors).toEqual([])
})

test('real candidate recovers from one failed home request within the same budget', async ({ page }) => {
  let failOnce = true
  await page.route('**/market/research/home-overview', route => {
    if (failOnce) { failOnce = false; return route.abort('failed') }
    return route.continue()
  })
  await page.goto('/market')
  await expect(page.getByText('行情快照暂不可用；没有可展示的上一份成功快照。')).toBeVisible()
  const started = Date.now()
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60, { timeout: homeBudgetMs })
  expect(Date.now() - started).toBeLessThan(homeBudgetMs)
})

test('real candidate covers AU/JM Newow weekly, AU seven-frequency Free and weekly complete-window action', async ({ page }, testInfo) => {
  const matrix = []
  for (const product of ['AU', 'AG', 'JM']) {
    const params = `strategy=trend&frequency=1w&section=chart&as_of=${encodeURIComponent(cutoff)}`
    const upper = await page.request.get(`/api/v1/market/newow/strategy-detail?product=${product}&${params}`)
    const lower = await page.request.get(`/api/v1/market/newow/strategy-detail?product=${product.toLowerCase()}&${params}`)
    expect(upper.status()).toBe(lower.status())
    const upperBody = await upper.json()
    const lowerBody = await lower.json()
    if (upperBody.meta) delete upperBody.meta.read_at
    if (lowerBody.meta) delete lowerBody.meta.read_at
    expect(upperBody).toEqual(lowerBody)
    matrix.push({ product, caseParity: true, status: upper.status() })
  }
  for (const product of ['au', 'jm']) {
    for (const strategy of strategies) {
      await page.goto(`/market/chart?symbol=${product}&view=newow&strategy=${strategy}&series_kind=actual_dominant&frequency=1w`)
      const workspace = page.locator('[data-detail-workspace="newow"]')
      await expect(workspace).toBeVisible()
      await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
      await expect.poll(async () => workspace.getAttribute('data-chart-state'), { timeout: 60_000 })
        .toMatch(/^(ready|warming|evidence_required|unavailable|stale|input_conflict)$/)
      matrix.push({ product, strategy, chart: await workspace.getAttribute('data-chart-state') })
    }
  }

  await page.goto('/market/chart?symbol=au&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1w')
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible({ timeout: 60_000 })
  await page.getByLabel('统计终点').fill('2026-09-14')
  await page.getByRole('button', { name: '应用统计窗口' }).click()
  await expect(page.getByRole('button', { name: '使用最近完整统计区间' })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '使用最近完整统计区间' }).click()
  await expect(page.getByLabel('统计终点')).toHaveValue('2026-09-11')

  for (const frequency of ['1m', '5m', '15m', '30m', '60m', '1d', '1w']) {
    await page.goto(`/market/chart?symbol=au&view=free&series_kind=actual_dominant&frequency=${frequency}`)
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible({ timeout: 60_000 })
    matrix.push({ product: 'au', view: 'free', frequency })
  }
  await page.screenshot({ path: testInfo.outputPath('real-au-free-1w.png'), fullPage: true })
  console.log(JSON.stringify({ evidence: 'real-product-matrix', cutoff, matrix }))
})

test('real candidate keeps an explicit JM SuBing long-window gap and Newow callouts inside the chart', async ({ page }, testInfo) => {
  const response = await page.request.get('/api/v1/market/jm/subing/reference?since=2025-09-15&through=2026-09-14')
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  expect(response.status()).toBe(409)
  const body = await response.json()
  expect(body.detail.code).toBe('SUBING_REFERENCE_DATA_UNAVAILABLE')
  expect(body.detail.diagnostic.stage).toBe('physical_contract_replay')
  expect(body.detail.diagnostic.reason).toBe('DATASET_OR_PARTITION_MISSING')

  const calloutEvidence = []
  for (const strategy of strategies) {
    await page.goto(`/market/chart?symbol=au&view=newow&strategy=${strategy}&series_kind=actual_dominant&frequency=1w`)
    const stage = page.getByTestId('newow-product-chart-stage')
    await expect(stage).toBeVisible()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready', { timeout: 60_000 })
    await expect.poll(async () => stage.getAttribute('data-action-ids'), { timeout: 60_000 }).toMatch(/\S/)
    const callouts = stage.locator('.newow-product-chart-stage__action-label')
    const expectedIds = (await stage.getAttribute('data-action-ids') ?? '').split(',').filter(Boolean).sort()
    const actualIds = (await callouts.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-action-id')).filter(Boolean).sort()))
    expect(actualIds).toEqual(expectedIds)
    for (const width of [1920, 1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await assertCalloutsInsideChart(stage, callouts)
    }
    await stage.getByRole('button', { name: '图表全屏' }).click()
    await expect(stage.getByRole('button', { name: '退出图表全屏' })).toBeVisible()
    await assertCalloutsInsideChart(stage, callouts)
    await stage.getByRole('button', { name: '退出图表全屏' }).click()
    calloutEvidence.push({ strategy, actionCount: actualIds.length })
  }
  await page.screenshot({ path: testInfo.outputPath('real-au-newow-390.png'), fullPage: true })
  console.log(JSON.stringify({ evidence: 'real-jm-gate-and-callouts', jmStatus: response.status(), diagnostic: body.detail.diagnostic, calloutEvidence }))
})

async function assertCalloutsInsideChart(stage, callouts) {
  await stage.scrollIntoViewIfNeeded()
  const chartBox = await stage.locator('.newow-product-chart-stage__chart').boundingBox()
  expect(chartBox).not.toBeNull()
  const boxes = await callouts.evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect()
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
  }))
  for (const box of boxes) {
    expect(box.left).toBeGreaterThanOrEqual(chartBox.x - 1)
    expect(box.right).toBeLessThanOrEqual(chartBox.x + chartBox.width + 1)
    expect(box.top).toBeGreaterThanOrEqual(chartBox.y - 1)
    expect(box.bottom).toBeLessThanOrEqual(chartBox.y + chartBox.height + 1)
  }
}
