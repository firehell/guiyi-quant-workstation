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


test('real projected card matches compact desktop and mobile layout without computation requests', async ({page}, testInfo) => {
  const requests=[]
  page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/')) requests.push(new URL(request.url()).pathname)})
  await page.goto('/market')
  await expect(page.locator('.strategy-list-item')).toHaveCount(60)
  const reads = requests.filter(path=>path.endsWith('/home-projection')).length
  await expect(page.locator('.strategy-sort')).toHaveCount(0)
  await page.getByRole('button',{name:'鸡蛋展开策略摘要',exact:true}).click()
  const article=page.locator('.strategy-list-item').filter({has:page.getByRole('button',{name:'鸡蛋展开策略摘要',exact:true})})
  const card=article.getByRole('link',{name:'鸡蛋趋势策略详情',exact:true})
  await expect(card).toBeVisible()
  await expect(card.locator('.composite-stage[aria-current="step"]')).toHaveCount(1)
  await expect(card).not.toContainText('查看策略详情')
  for(const width of [1168,390]) {
    await page.setViewportSize({width,height:900})
    await expect(card).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1)).toBe(true)
    await article.screenshot({path:testInfo.outputPath(`home-card-${width}.png`)})
  }
  expect(requests.filter(path=>path.endsWith('/home-projection')).length).toBe(reads)
  expect(requests.some(path=>/home-cards|home-card-performance/.test(path))).toBe(false)
})

test('real MA60 arrows match persisted D1 facts across strategy and sector switches', async ({page}, testInfo) => {
  const calls=[]
  page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/')) calls.push(new URL(r.url()).pathname)})
  const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/newow/home-projection') && r.status()===200)
  await page.goto('/market')
  const payload=await (await response).json()
  await expect(page.locator('.strategy-list-item')).toHaveCount(60)
  const expected=payload.items.filter(item=>item.strategies.trend['1d'].independent_trend?.status==='ready')
  expect(expected.length).toBeGreaterThan(0)
  for (const item of expected) {
    const fact=item.strategies.trend['1d'].independent_trend
    expect(fact.formula_version).toBe('guiyi_home_close_ma60_v1')
    expect(fact.page_parity).toBe(false)
    expect(fact.approximate).toBe(true)
  }
  const arrows=async()=>page.locator('.list-direction svg').evaluateAll(els=>els.map(el=>el.getAttribute('aria-label')))
  await expect(page.locator('.independent-trend-icon')).toHaveCount(expected.length)
  const original=await arrows(), before=calls.length
  await page.getByRole('button',{name:'震荡',exact:true}).click()
  expect(await arrows()).toEqual(original)
  await page.getByRole('button',{name:'趋势',exact:true}).click()
  await page.locator('.strategy-list-row').first().click()
  expect(await arrows()).toEqual(original)
  await page.getByRole('button',{name:/^贵金属/}).click()
  await expect(page.locator('.strategy-list-item')).toHaveCount(4)
  await page.getByRole('button',{name:/^全部/}).click()
  expect(await arrows()).toEqual(original)
  expect(calls.slice(before).some(p=>/home-projection|home-cards|signal\/compute/.test(p))).toBe(false)
  for(const width of [1168,390]) {
    await page.setViewportSize({width,height:900})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
    await page.screenshot({path:testInfo.outputPath(`ma60-home-${width}.png`)})
  }
})
