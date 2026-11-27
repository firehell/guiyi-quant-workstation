import { test, expect } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
import { mockMarketDetail } from './market-detail.helpers.mjs'

const dimensions = [[1440,900],[1280,720],[1024,768],[390,844]]
async function noOverflow(page) {
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1)).toBe(true)
  for (const box of await page.locator('.performance-panel').all()) {
    const rect=await box.boundingBox()
    if (rect) { expect(rect.x).toBeGreaterThanOrEqual(-1); expect(rect.x+rect.width).toBeLessThanOrEqual(await page.evaluate(()=>innerWidth)+1) }
  }
}
async function newowFixtures(page) {
  return installNewowProductFixtures(page)
}
for (const [width,height] of dimensions) {
  test(`unified strategy modes and curve interaction ${width}`,async({page})=>{
    await page.setViewportSize({width,height});await newowFixtures(page)
    for(const strategy of ['trend','oscillation','main_rise']) {
      await page.goto(newowRoute(strategy));const panel=page.locator('.page-performance')
      await panel.scrollIntoViewIfNeeded()
      await expect(panel).toBeVisible();await expect(panel.locator('.return-curve svg')).toBeVisible()
      await expect(panel).toContainText('累计参考收益')
      await expect(panel).toContainText('百分点')
      await expect(page.locator('.detail-view-nav')).toContainText('日线')
      const svg=panel.locator('.return-curve svg');await svg.focus();await svg.press('End')
      await expect(panel.locator('.return-curve__readout')).toContainText('百分点')
      await page.getByRole('region',{name:'Newow 参考与解释',exact:true}).getByRole('button',{name:'收益分析 ›',exact:true}).click()
      await expect(page.getByRole('dialog',{name:'收益分析',exact:true})).toBeVisible()
      await page.keyboard.press('Escape');await expect(page.getByRole('dialog',{name:'收益分析',exact:true})).toHaveCount(0)
      await page.getByRole('button',{name:'已完成参考交易',exact:true}).click()
      await expect(page.locator('[data-testid="newow-reference-summary"]')).toContainText('已完成参考收益（百分点）')
      await page.getByRole('button',{name:'含浮动参考',exact:true}).click()
      await expect(page.getByRole('region',{name:'逐 Bar 持有过程'})).toBeVisible()
      await noOverflow(page)
    }
    await page.screenshot({path:`/private/tmp/guiyi-ui-newow-${width}.png`,fullPage:true})
  })
  test(`generic views retain supported facts ${width}`,async({page})=>{
    await page.setViewportSize({width,height});await mockMarketDetail(page)
    await page.route('**/api/v1/reference-trading/streams*',r=>r.fulfill({json:{items:[]}}))
    for(const view of ['htdy','subing','free']) {
      await page.goto(`/market/chart?symbol=jm&view=${view}&series_kind=actual_dominant&frequency=15m`)
      await expect(page.locator(`[data-detail-workspace="${view}"]`)).toBeVisible()
      await expect(page.locator('.detail-view-nav')).toContainText('15分钟')
      if(view==='free') await expect(page.locator('.performance-panel')).toHaveCount(0)
      if(view==='htdy') await expect(page.locator('.performance-panel')).toContainText('盘中观察参考')
      if(view==='subing') {
        await expect(page.getByRole('group',{name:'参考记录来源'})).toBeVisible()
        await page.getByRole('button',{name:'参考投影与盘中观察',exact:true}).click()
        await expect(page.locator('.performance-panel')).toContainText('盘中观察参考')
      }
      await noOverflow(page)
    }
    await page.screenshot({path:`/private/tmp/guiyi-ui-free-${width}.png`,fullPage:true})
  })
  test(`four experiment strategies share the curve and keep model identity ${width}`,async({page})=>{
    await page.setViewportSize({width,height});await newowFixtures(page)
    await page.route('**/api/v1/market/newow/experiments?**',route=>{
      const q=Object.fromEntries(new URL(route.request().url()).searchParams),dates=Array.from({length:12},(_,i)=>`2026-08-${String(i+1).padStart(2,'0')}T07:00:00Z`)
      const model=(ideal)=>({model_version:ideal?'newow_base_oscillation_ideal_v3379_v1':'newow_oscillation_experiment_ordinary_v3379_v1',hindsight:ideal,page_parity:true,executable:false,dates,equity:dates.map((_,i)=>i===11?'1':'0'),total_count:1,summary:{trade_count:1,cum_return_percentage_points:'1',accuracy_pct:'100',max_drawdown_percentage_points:'0'},trades:[{segment_id:'exp',physical_contract:'RB2605',entry_bar_end:dates[0],exit_bar_end:dates[11],entry_reference_price:'100',exit_reference_price:'101',return_percentage_points:'1',force_close:false,stop_loss:false,confirm_exit:false}]})
      return route.fulfill({json:{...q,schema_version:'newow_experiment_detail_v2',input_snapshot_hash:'a'.repeat(64),profile_id:'guiyi_newow_experiment_completed_physical_v1',input_policy_version:'policy',meta:{identity:{product:q.product,frequency:q.frequency,kind:q.kind,strategy:q.kind,series_kind:'actual_dominant',as_of:q.as_of,formula_version:`newow_${q.kind.replace('-','_')}_page_v3379_v1`,profile_id:'guiyi_newow_experiment_completed_physical_v1',input_policy_version:'policy'},as_of:q.as_of,read_at:q.as_of,input_content_sha256:'a'.repeat(64),data_revision_identity:'b'.repeat(64),snapshot_token:'test-token',result_hash:'c'.repeat(64),completed_only:true,executable:false,auto_order:false,last_completed_bar_end:dates.at(-1),last_trading_day:dates.at(-1).slice(0,10)},formula_version:`newow_${q.kind.replace('-','_')}_page_v3379_v1`,page_parity:true,executable:false,window:{since:'2026-08-01',through:'2026-09-03'},readiness:{status:'READY',reason_code:null},bars:dates.map(bar_end=>({bar_end,trading_day:bar_end.slice(0,10),physical_contract:'RB2605',segment_id:'exp',open:'100',high:'110',low:'90',close:'101',channel_high:'110',channel_low:'90'})),markers:[],segments:[{segment_id:'exp',physical_contract:'RB2605',status:'CURRENT',ordinary:model(false),theoretical:model(true)}]}})
    })
    await page.goto(newowRoute('oscillation'))
    for (const label of ['测试','测试2','测试3','测试4']) {
      await page.getByLabel('牛哇T策略',{exact:true}).click()
      await page.getByRole('button',{name:label,exact:true}).click()
      const panel=page.locator('.experiment-panel')
      await expect(panel.locator('.return-curve svg')).toBeVisible()
      await expect(panel.locator('[data-testid="experiment-summary"]')).toContainText('+1.00 百分点')
      await panel.getByRole('button',{name:'理论值',exact:true}).click()
      await expect(panel.locator('[data-testid="experiment-summary"]')).toContainText('单笔最大亏损')
      await panel.locator('.return-curve svg').focus();await page.keyboard.press('End')
      await expect(panel.locator('.return-curve__readout')).toContainText('1百分点')
      await noOverflow(page)
    }
    await page.screenshot({path:`/private/tmp/guiyi-ui-experiments-${width}.png`,fullPage:true})
  })
}
