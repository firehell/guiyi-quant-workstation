import { expect, test } from '@playwright/test'

function bars(start, count, seed = 100) {
  return Array.from({ length: count }, (_, index) => {
    const barEnd = new Date(start + index * 15 * 60 * 1000).toISOString()
    const close = seed + index
    return {
      bar_end: barEnd,
      trading_day: barEnd.slice(0, 10),
      open: close - 1,
      high: close + 1,
      low: close - 2,
      close,
      volume: 100 + index,
      turnover: null,
      open_interest: null,
    }
  })
}

test('historical pagination requests the latest page before its cursor page', async ({ page }) => {
  const initialStart = Date.UTC(2026, 7, 7, 1)
  const initialBars = bars(initialStart, 1200)
  const olderBars = [...bars(initialStart - 1200 * 15 * 60 * 1000, 1200, 0), initialBars[0]]
  const requests = []

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    if (url.pathname.endsWith('/dominants')) {
      await route.fulfill({ json: { items: [{
        product: 'jm', product_name: '焦煤', exchange: 'DCE', actual_contract: 'JM2601', dominant_mapping_date: '2026-08-07',
      }] } })
      return
    }
    if (url.pathname.endsWith('/coverage/canonical')) {
      await route.fulfill({ json: { items: [] } })
      return
    }
    if (url.pathname.endsWith('/bars/page')) {
      const before = url.searchParams.get('before')
      const isInitial = before === null
      await route.fulfill({ json: {
        request: {
          series_kind: 'actual_dominant', symbol: 'jm', contract: null, frequency: '15m', before, limit: 1200,
        },
        bars: isInitial ? initialBars : olderBars,
        canonical_coverage: null,
        page: isInitial
          ? { has_more_before: true, next_before: initialBars[0].bar_end }
          : { has_more_before: false, next_before: null },
        resolved_contract_segments: [],
      } })
      return
    }
    await route.abort()
  })

  await page.goto('/market/chart?symbol=jm&contract=JM2601&series_kind=actual_dominant&frequency=15m')

  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(1)
  const first = requests.find((url) => url.pathname.endsWith('/bars/page'))
  expect(first.searchParams.has('before')).toBe(false)
  expect(first.searchParams.has('start')).toBe(false)
  expect(first.searchParams.has('end')).toBe(false)
  await expect(page.getByText('1200 bars')).toBeVisible()

  const canvas = page.locator('.chart canvas').first()
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + 20, box.y + box.height / 2, { steps: 12 })
  await page.mouse.up()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2, { steps: 12 })
  await page.mouse.up()

  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBe(2)
  const second = requests.filter((url) => url.pathname.endsWith('/bars/page'))[1]
  expect(second.searchParams.get('before')).toBe(initialBars[0].bar_end)
  await expect(page.getByText('2400 bars')).toBeVisible()
  expect(requests.every((url) => !(url.searchParams.has('start') && url.searchParams.has('end')))).toBe(true)
})
