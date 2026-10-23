import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

test.skip(process.env.HOME_PROJECTION_REAL !== '1', 'explicit isolated development projection acceptance only')

test('real production home reads 60 precomputed products without computation HTTP', async ({ page }, testInfo) => {
  const requests = [], errors = []
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) requests.push(new URL(request.url()).pathname) })
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.__homeFirstFacts = null
    const observer = new MutationObserver(() => {
      if (window.__homeFirstFacts !== null) return
      if (document.querySelectorAll('.strategy-list-item').length === 60 && [...document.querySelectorAll('.list-reference strong')].some(item => item.textContent.trim() !== '--')) {
        window.__homeFirstFacts = -1
        requestAnimationFrame(() => requestAnimationFrame(() => { window.__homeFirstFacts = performance.now() }))
      }
    })
    observer.observe(document, { childList:true, subtree:true, characterData:true })
  })
  await page.goto('/market', { waitUntil:'domcontentloaded' })
  await page.waitForFunction(() => window.__homeFirstFacts > 0)
  await expect(page.locator('.strategy-list-item')).toHaveCount(60)
  const firstScreen = await page.evaluate(() => window.__homeFirstFacts)
  const before = requests.filter(path => path.endsWith('/home-projection')).length
  const sectorMs = await page.evaluate(async () => {
    const button = [...document.querySelectorAll('button')].find(item => item.textContent.includes('贵金属'))
    const started = performance.now(); button.click()
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    return performance.now() - started
  })
  await expect(page.locator('.strategy-list-item')).toHaveCount(4)
  await page.locator('.strategy-list-row').first().click()
  await expect(page.locator('.list-composite').first()).toBeVisible()
  expect(requests.filter(path => path.endsWith('/home-projection')).length).toBe(before)
  expect(requests.some(path => /home-cards|home-card-performance|home-card-display-cache/.test(path))).toBe(false)
  const resources = await page.evaluate(() => performance.getEntriesByType('resource').filter(item => item.name.includes('/api/')).map(item => ({name:new URL(item.name).pathname,start_ms:item.startTime,duration_ms:item.duration})))
  const result = { resources, first_screen_ms:firstScreen, sector_switch_ms:sectorMs, projection_requests:before, errors }
  await page.getByRole('button', {name:/^全部/}).click()
  await expect(page.locator('.strategy-list-item')).toHaveCount(60)
  await page.reload({waitUntil:'domcontentloaded'})
  await page.waitForFunction(() => window.__homeFirstFacts > 0)
  result.browser_cache_restore_ms = await page.evaluate(() => window.__homeFirstFacts)
  console.log(JSON.stringify(result))
  await writeFile(testInfo.outputPath('browser-timing.json'), JSON.stringify(result))
  await page.screenshot({path:testInfo.outputPath('production-home.png')})
  expect(result.browser_cache_restore_ms).toBeLessThanOrEqual(1000)
  expect(errors).toEqual([])
  expect(firstScreen).toBeLessThanOrEqual(1000)
  expect(sectorMs).toBeLessThanOrEqual(100)
})
