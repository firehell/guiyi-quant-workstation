import { test, expect } from '@playwright/test'

test.skip(process.env.REAL_BACKEND !== '1', 'requires explicit local read-only backend')
test.use({ launchOptions: { args: ['--js-flags=--max-old-space-size=384'] } })

for (const view of ['htdy', 'subing', 'free']) {
  test(`${view}: first drag at the initial left edge loads earlier history`, async ({ page }) => {
    const isPage = response => response.url().includes('/market/bars/page') && response.ok()
    const firstRead = page.waitForResponse(response => isPage(response) && !new URL(response.url()).searchParams.has('before'))
    await page.goto(`/market/chart?view=${view}&symbol=jm&series_kind=actual_dominant&frequency=15m`)
    const first = await (await firstRead).json()
    expect(first.page.has_more_before).toBe(true)
    await page.locator('[data-chart-viewport-ready="true"]').waitFor()
    const chart = page.locator('.chart').first()
    await chart.scrollIntoViewIfNeeded()
    const rect = await chart.boundingBox()
    expect(rect).not.toBeNull()
    let cursor = first.page.next_before
    // Repeat: successful prepend must rearm the boundary for the next gesture.
    for (let attempt = 0; attempt < 2; attempt++) {
      const nextRead = page.waitForResponse(response => isPage(response) && new URL(response.url()).searchParams.get('before') === cursor)
      await page.mouse.move(rect.x + 100, rect.y + 100)
      await page.mouse.down()
      await page.mouse.move(rect.x + rect.width - 100, rect.y + 100, { steps: 20 })
      await page.mouse.up()
      const next = await (await nextRead).json()
      expect(next.bars.length).toBeGreaterThan(0)
      expect(Date.parse(next.bars[0].bar_end)).toBeLessThan(Date.parse(cursor))
      expect(Date.parse(next.bars.at(-1).bar_end)).toBeLessThan(Date.parse(cursor))
      cursor = next.page.next_before
      await expect(page.getByRole('button', { name: '加载更早', exact: true })).toBeEnabled()
    }
  })
}
