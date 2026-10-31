import { expect, test } from '@playwright/test'

test('local develop detail keeps real quote and canvas across analysis views', async ({ page }) => {
  test.skip(process.env.GUIYI_DETAIL_READONLY !== '1', 'Explicit local read-only acceptance only')
  test.setTimeout(90_000)
  await page.setViewportSize({width:1280,height:1400})
  const errors=[]; page.on('pageerror', error => errors.push(error.message))
  await page.goto('/market/chart?view=newow&symbol=jm&strategy=trend&series_kind=actual_dominant&frequency=60m')
  const workspace=page.locator('[data-detail-workspace="newow"]')
  await expect(workspace).toHaveAttribute('data-chart-state','ready',{timeout:60_000})
  await expect(page.locator('.quote-header__price strong')).not.toHaveText('—')
  const native=page.locator('.tv-lightweight-charts').first()
  await native.evaluate(element=>{window.__realDetailCanvas=element})
  for(const name of ['火天大有','苏冰预警','自由看盘','趋势策略']) {
    await page.getByRole('tab',{name,exact:true}).click()
    await expect.poll(()=>page.evaluate(()=>document.querySelector('.tv-lightweight-charts')===window.__realDetailCanvas && window.__realDetailCanvas.isConnected)).toBe(true)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe('60m')
    await expect(page.locator('.quote-header__price strong')).not.toHaveText('—')
  }
  await expect(workspace).toHaveAttribute('data-chart-state','ready',{timeout:60_000})
  await expect(workspace).not.toHaveAttribute('data-auxiliary-state', /^(loading|not_requested)$/,{timeout:30_000})
  expect(errors).toEqual([])
  await page.screenshot({path:'/private/tmp/guiyi-detail-real-develop.png',fullPage:true})
})
