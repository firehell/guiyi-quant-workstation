import { expect, test } from '@playwright/test'
import { lightHomeOverview } from './fixtures/market-home-light.mjs'
import { mockMarketDetail, installDetailFakeWebSocket } from './market-detail.helpers.mjs'

// Controlled completed facts: validates delivery/interaction, never production readiness.
async function setup(page) {
  await mockMarketDetail(page)
  await installDetailFakeWebSocket(page)
  const overview = lightHomeOverview()
  const control = { fail: false, products: [], active: 0, maximum: 0, errors: [] }
  page.on('pageerror', e => control.errors.push(e.message))
  await page.route('**/api/runtime/health', r => r.fulfill({ json: { status:'ok', readonly:true, components:{} } }))
  await page.route('**/api/v1/market/research/home-overview', r => r.fulfill({ json: overview }))
  await page.route('**/api/v1/market/dominants', r => r.fulfill({ json: {items:overview.items.map(x=>({product:x.symbol,product_name:x.product_name,actual_contract:x.actual_contract,dominant_mapping_date:x.dominant_mapping_date}))} }))
  await page.route('**/api/v1/market/newow/home-cards?*', async route => {
    const products = new URL(route.request().url()).searchParams.get('products').split(',')
    control.products.push(products); control.active++; control.maximum=Math.max(control.maximum,control.active)
    await new Promise(resolve=>setTimeout(resolve,5))
    control.active--
    if(control.fail) return route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE'}}})
    const ready = (product,state) => ({status:'ready',state,as_of:'2026-09-02T07:00:00Z',bar_end:'2026-09-02T07:00:00Z',physical_contract:`${product.toUpperCase()}2611`,segment_id:'fixture-owner',calculation_segment_id:'fixture-calc',input_sha256:'a'.repeat(64),formula_versions:['fixture-v1'],page_parity:true,executable:false,target:'120',absorb:'90',reference_cost:'100',target_space_percent:'20'})
    return route.fulfill({json:{schema_version:'newow_home_cards_v1',requested_at:'2026-09-02T07:01:00Z',items:products.map(product=>({product,strategies:{trend:{'1d':ready(product,'BUILD'),'1w':ready(product,'HOLD')},oscillation:{'1d':{status:'warming',state:null},'1w':{status:'unavailable',state:null}}}}))}})
  })
  return control
}

for(const width of [1440,390]) test(`60 strategy cards and independent period details at ${width}px`, async ({page})=>{
  await page.setViewportSize({width,height:900})
  const control=await setup(page);await page.goto('/market')
  const cards=page.locator('.strategy-card');await expect(cards).toHaveCount(60)
  await expect(page.locator('.card-status.pending')).toHaveCount(120)
  await expect(cards.last()).toContainText('周 · 持有')
  expect(control.products.length).toBe(60);expect(control.products.every(x=>x.length===1)).toBe(true);expect(control.maximum).toBeLessThanOrEqual(2)
  const first=cards.first();await first.getByRole('button',{name:'展开策略详情 ＋'}).click()
  const trend=first.locator('.trade-card').first();await expect(trend).toContainText('120.00');await expect(trend).toContainText('建仓')
  await trend.getByRole('button',{name:'周线',exact:true}).click();await expect(trend.getByRole('button',{name:'周线',exact:true})).toHaveAttribute('aria-pressed','true')
  await expect(trend.locator('[aria-current="step"]')).toHaveText('✓持有')
  await first.getByRole('button',{name:'收起策略详情 −'}).click();await expect(first.locator('.strategy-card-details')).toHaveCount(0)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);expect(control.errors).toEqual([])
})

test('failed card refresh retains labelled accepted facts and recovers independently',async({page})=>{
 const control=await setup(page);await page.goto('/market')
 const cards=page.locator('.strategy-card');await expect(cards.last()).toContainText('周 · 持有')
 control.fail=true;await page.getByRole('button',{name:'刷新',exact:true}).click()
 await expect(cards.last()).toContainText('策略刷新失败，保留上次快照');await expect(cards.first()).toContainText('日 · 建仓')
 control.fail=false;await page.getByRole('button',{name:'刷新',exact:true}).click()
 await expect(page.locator('.card-notice')).toHaveCount(0);await expect(cards.last()).toContainText('周 · 持有');expect(control.errors).toEqual([])
})
