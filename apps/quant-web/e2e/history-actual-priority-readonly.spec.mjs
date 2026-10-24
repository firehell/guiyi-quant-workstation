import { test, expect } from '@playwright/test'
test.skip(process.env.REAL_BACKEND !== '1', 'explicit local read-only market acceptance')
test.use({ launchOptions: { args: ['--js-flags=--max-old-space-size=384'] } })
for (const view of ['htdy', 'subing']) test(`${view}: earlier chart signals and records retain actual provenance and original statistics`, async ({ page }) => {
  test.setTimeout(90000)
  await page.goto(`/market/chart?view=${view}&symbol=jm&series_kind=actual_dominant&frequency=15m`)
  const chart = page.getByTestId('kline-shell')
  const panel = page.locator(view === 'htdy' ? '.htdy-history' : '.subing-reference')
  await expect(panel.locator('tbody tr').first()).toBeVisible({timeout:40000})
  const stats = await panel.locator('.reference-history__summary').textContent()
  await expect(page.getByText('正在读取当前图表范围的历史信号…', {exact:true})).toBeHidden({timeout:40000})
  await expect.poll(async()=>await chart.getAttribute('data-rendered-marker-ids')).toContain('alert:')
  await expect(page.locator('[data-actual-reference-status="missing"]')).toBeVisible()
  const canvas=page.locator('.chart').first(); await canvas.scrollIntoViewIfNeeded(); const r=await canvas.boundingBox()
  for(let i=0;i<2;i++){
    const next=page.waitForResponse(response=>response.url().includes('/market/bars/page')&&response.url().includes('before=')&&response.ok())
    await page.mouse.move(r.x+100,r.y+100);await page.mouse.down();await page.mouse.move(r.x+r.width-100,r.y+100,{steps:20});await page.mouse.up();await next
    await expect(page.getByText('正在读取当前图表范围的历史信号…', {exact:true})).toBeHidden({timeout:40000})
  }
  await expect.poll(async()=>{
    const times=(await chart.getAttribute('data-rendered-marker-times')??'').split(',').filter(Boolean)
    return Math.min(...times.map(Date.parse))
  },{timeout:30000}).toBeLessThan(Date.parse('2026-09-01T00:00:00Z'))
  const count=await panel.locator('tbody tr').count()
  await panel.getByRole('button',{name:'读取更多 / 更早参考记录',exact:true}).click()
  await expect.poll(async()=>await panel.locator('tbody tr').count(),{timeout:40000}).toBeGreaterThan(count)
  await expect(panel.locator('.reference-history__summary')).toHaveText(stats ?? '')
  await expect(panel.getByText(/已载记录展示区间 2026-08-21/)).toBeVisible()
})
