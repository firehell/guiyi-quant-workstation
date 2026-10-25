import { homeProjection } from './fixtures/home-projection.mjs'
import { expect, test } from '@playwright/test'
import { lightHomeOverview } from './fixtures/market-home-light.mjs'
import { mockMarketDetail, installDetailFakeWebSocket } from './market-detail.helpers.mjs'

async function setup(page) {
  await mockMarketDetail(page)
  await installDetailFakeWebSocket(page)
  const control = { stale: false, missing: false, slow: false, fail: false, target: '120', overviewCalls: 0, cardCalls: 0, conditional: 0, errors: [] }
  page.on('pageerror', error => control.errors.push(error.message))
  const overview = lightHomeOverview()
  const delay = async () => { if (control.slow) await new Promise(resolve => setTimeout(resolve, 1800)) }
  await page.route('**/api/runtime/health', route => route.fulfill({ json: { status:'ok', readonly:true, components:{} } }))
  await page.route('**/api/v1/market/product-directory', async route => { await delay(); return route.fulfill({ json: { items: overview.items.map(x => ({product:x.symbol, product_name:x.product_name, exchange:x.exchange, sector:x.sector})) }, headers: { ETag: '"directory-fixture"' } }) })
  await page.route('**/api/v1/market/research/home-overview', async route => {
    control.overviewCalls++; await delay()
    if (control.fail) return route.fulfill({ status:503, json:{detail:{code:'UNAVAILABLE'}} })
    if (route.request().headers()['if-none-match'] === '"overview-fixture"') { control.conditional++; return route.fulfill({status:304,headers:{ETag:'"overview-fixture"'}}) }
    return route.fulfill({json:{...overview, ...(control.stale ? {projection_status:'stale'} : {})},headers:{ETag:'"overview-fixture"'}})
  })
  await page.route('**/api/v1/market/newow/home-projection', async route => {
    control.cardCalls++; const target = control.target; await delay()
    if (control.fail) return route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE'}}})
    const products = overview.items.map(item => item.symbol)
    if (control.missing) {
      const value = homeProjection(products.map(product => ({product,strategies:Object.fromEntries(['trend','oscillation'].map(s=>[s,Object.fromEntries(['1d','1w'].map(p=>[p,{status:'unavailable',state:null}]))]))})))
      for (const item of value.items) { item.projection_status='missing'; item.computed_at=null;item.period_status={'1d':'missing','1w':'missing'} }
      return route.fulfill({json:value})
    }
    const fact = product => ({ status:'ready', state:'HOLD', as_of:'2026-09-04T07:00:00Z', bar_end:'2026-09-04T07:00:00Z', physical_contract:`${product.toUpperCase()}2611`, segment_id:'s', calculation_segment_id:'c', input_sha256:'a'.repeat(64), formula_versions:['fixture-v1'], page_parity:true, executable:false, display_projection_version:'newow_home_display_v1', display_as_of:'2026-09-04T07:01:00Z', target: product === 'a' ? target : '120', absorb:'90', reference_current:'100' })
    return route.fulfill({json:homeProjection(products.map(product => ({product, strategies:{trend:{'1d':fact(product),'1w':fact(product)},oscillation:{'1d':{status:'warming',state:null},'1w':{status:'unavailable',state:null}}}})))})
  })
  return control
}
async function returnToVisiblePage(page) {
  await page.evaluate(() => {
    for (const state of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: state })
      document.dispatchEvent(new Event('visibilitychange'))
    }
  })
}
async function stored(page) {
  return page.evaluate(async () => {
    const names = (await indexedDB.databases()).filter(x => x.name.startsWith('guiyi-home:'))
    if (!names.length) return 0
    return new Promise(resolve => { const request=indexedDB.open(names[0].name); request.onsuccess=()=>{const db=request.result; const read=db.transaction('snapshots').objectStore('snapshots').getAll();read.onsuccess=()=>{resolve(read.result.filter(x=>x.key.startsWith('card:')).length);db.close()} } })
  })
}

test('completed minute prices do not reload daily facts', async ({page}) => {
  const control=await setup(page);await page.goto('/market')
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  await page.waitForTimeout(100)
  const before=control.overviewCalls
  await page.evaluate(()=>{
    const socket=window.__marketDetailSockets.find(s=>new URL(s.url,location.href).pathname==='/api/v1/market/research/home-live/ws')
    socket.onmessage?.({data:JSON.stringify({type:'snapshot',schema_version:1,observed_at:'2026-09-04T02:31:01Z',scope:'operational',items:[{symbol:'a',physical_contract:'A2611',trading_day:'2026-09-04',bar_end:'2026-09-04T02:31:00Z',price:'125',previous_close:'100',price_change:'0.25',source:'completed_1m',availability:'live',phase:'TRADING',reason:null}]})})
  })
  await expect(page.locator('.list-price').first()).toHaveText('125.00')
  await expect(page.locator('.list-change').first()).toHaveText('+25.00%')
  expect(control.overviewCalls).toBe(before)
})

test('reload restores real IndexedDB rows and cards within 500ms of mount before delayed HTTP', async ({page}) => {
  const control = await setup(page)
  await page.goto('/market')
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  await expect.poll(()=>stored(page)).toBeGreaterThan(0)
  await page.addInitScript(() => {
    window.__cachedPaint = { mount:null, rows:null }
    const observer=new MutationObserver(()=>{
      if(document.querySelector('.market-dashboard-page') && window.__cachedPaint.mount===null) window.__cachedPaint.mount=performance.now()
      if(document.querySelector('.list-reference')?.textContent?.trim()==='120.00' && window.__cachedPaint.rows===null) window.__cachedPaint.rows=performance.now()
    }); observer.observe(document,{childList:true,subtree:true,characterData:true})
  })
  control.slow=true
  await page.reload({waitUntil:'domcontentloaded'})
  await expect(page.locator('.list-reference').first()).toHaveText('120.00', {timeout:1500})
  const timing=await page.evaluate(()=>window.__cachedPaint)
  console.log(`cached homepage mount-to-card: ${Math.round(timing.rows-timing.mount)}ms`)
  expect(timing.rows-timing.mount).toBeLessThanOrEqual(500)
  await expect(page.locator('.market-home-cache-status')).toContainText('快照')
  expect(control.errors).toEqual([])
})

test('expired visible-page reconciliation keeps expanded row, accepts304 and replaces only changed product', async ({page}) => {
  await page.clock.install()
  const control=await setup(page); await page.goto('/market')
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  const first=page.locator('.strategy-list-row').first()
  await first.click(); await expect(first).toHaveAttribute('aria-expanded','true')
  await page.evaluate(()=>{window.__unchangedRow=document.querySelectorAll('.strategy-list-row')[1]})
  control.target='125'; control.slow=true
  await page.clock.fastForward(6 * 60_000)
  await returnToVisiblePage(page)
  await expect.poll(() => control.cardCalls).toBeGreaterThan(1)
  await expect(first).toHaveAttribute('aria-expanded','true')
  await expect(page.locator('.strategy-list-row')).toHaveCount(60)
  await page.clock.runFor(6_000)
  await expect(page.locator('.list-reference').first()).toHaveText('125.00',{timeout:15000})
  expect(control.conditional).toBeGreaterThan(0)
  expect(await page.evaluate(()=>window.__unchangedRow===document.querySelectorAll('.strategy-list-row')[1])).toBe(true)
  await expect(first).toHaveAttribute('aria-expanded','true')
})

test('reload failure retains labelled cached facts and never reports current health from storage', async ({page}) => {
  const control=await setup(page);await page.goto('/market')
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  await expect.poll(()=>stored(page)).toBeGreaterThan(0)
  control.fail=true
  await page.reload()
  await expect(page.locator('.strategy-list-row')).toHaveCount(60)
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  await expect(page.getByText(/行情刷新失败/)).toBeVisible()
  await expect(page.locator('.strategy-list-item').first()).toContainText(/保留上次快照|快照待核对/)
  expect(control.errors).toEqual([])
})


test('missing server projection retains browser history with explicit rebuild status', async({page})=>{
 await page.clock.install()
 const control=await setup(page);await page.goto('/market')
 const row=page.locator('.strategy-list-item').first()
 await expect(row.locator('.list-reference')).toHaveText('120.00')
 control.missing=true
 await page.clock.fastForward(6 * 60_000)
 await returnToVisiblePage(page)
 await expect(row).toContainText('摘要待重建，保留历史快照')
 await expect(row.locator('.list-reference')).toHaveText('120.00')
})


test('cold browser displays server lastgood rows and strategy facts with stale label', async ({page}) => {
  const control = await setup(page)
  control.stale = true
  await page.goto('/market')
  await expect(page.locator('.strategy-list-item')).toHaveCount(60)
  await expect(page.locator('.list-reference').first()).toHaveText('120.00')
  await expect(page.getByRole('alert')).toContainText('上一份成功快照')
})
