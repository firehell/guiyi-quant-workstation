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
  test(`research complete curve independent of paging ${width}`,async({page})=>{
    await page.setViewportSize({width,height})
    const meta=(v)=>({run_id:(v===1?'a':'b').repeat(64),product:'AL',scenario:'baseline',initial_cash:'100000',status:'COMPLETED',strategy_code:`new_subing_v${v}`,formula_version:`v${v}`,profile_id:'frozen',risk_profile_version:'r1',execution_profile_version:'e1',code_revision:'c'.repeat(40),requested_since:'2026-01-01',requested_through:'2026-09-03',input_snapshot_hash:'d'.repeat(64),execution_facts_hash:'e'.repeat(64),source:'historical_replay',auto_order:false,case_parity:'PENDING',oos_status:'NOT_PROVEN'})
    const curve=[0,1,2].map(i=>({at:`2026-01-0${i+1}T07:00:00Z`,equity:String(100000+i*100),physical_contract:'AL2603',qty:0,cash:'100000'}))
    let curveRequests=0
    await page.route('**/api/v1/research/new-subing/**',route=>{
      const url=new URL(route.request().url()),id=url.pathname.split('/')[6],v=id==='a'.repeat(64)?1:2
      if(url.pathname.endsWith('/profiles')) return route.fulfill({json:{strategy_code:'new_subing_v1',profiles:[],case_parity:'PENDING',oos_status:'NOT_PROVEN',auto_order:false}})
      if(url.pathname.endsWith('/runs'))return route.fulfill({json:{runs:[meta(1),meta(2)]}})
      if(url.pathname.endsWith('/equity-curve')){curveRequests++;return route.fulfill({json:{run_id:id,sha256:'f'.repeat(64),items:curve,total:100,sampled:true,sampling_version:'exact_extrema_boundaries_v1',since:'2026-01-01',through:'2026-09-03',status:'COMPLETED'}})}
      if(/\/(decisions|trades|equity)$/.test(url.pathname))return route.fulfill({json:{run_id:id,sha256:'f'.repeat(64),items:[{at:'2026-01-01T07:00:00Z',equity:'100000',action:'OPEN',side:'LONG'}],next_cursor:url.searchParams.has('cursor')?null:'next'}})
      return route.fulfill({json:{sha256:'f'.repeat(64),metadata:meta(v),summary:{status:'COMPLETED',account_return_pct:'0.2',max_drawdown_pct:'0.001',final_equity:'100200',closed_trades:1},diagnostics:{}}})
    })
    await page.goto('/research/new-subing')
    for(const version of ['new_subing_v2','new_subing_v1']){
      await page.locator('.chooser select').nth(0).selectOption(version)
      const panel=page.locator('.performance-panel');await expect(panel.locator('.return-curve svg')).toBeVisible()
      await expect(panel).toContainText('模型账户回撤');await expect(panel).toContainText('抽样')
      await panel.locator('.return-curve svg').focus();await page.keyboard.press('End');await expect(panel.locator('.return-curve__readout')).toContainText('100200元')
      const before=curveRequests
      await page.getByRole('button',{name:'加载更多',exact:true}).click()
      await expect(page.getByRole('button',{name:'加载更多',exact:true})).toHaveCount(0)
      expect(curveRequests).toBe(before);await noOverflow(page)
    }
    await page.screenshot({path:`/private/tmp/guiyi-ui-research-${width}.png`,fullPage:true})
  })
}

for (const width of [1440,390]) {
  test(`four experiment strategies share the curve and keep model identity ${width}`,async({page})=>{
    await page.setViewportSize({width,height:900});await newowFixtures(page)
    await page.route('**/api/v1/market/newow/experiments?**',route=>{
      const q=Object.fromEntries(new URL(route.request().url()).searchParams),dates=Array.from({length:12},(_,i)=>`2026-08-${String(i+1).padStart(2,'0')}T07:00:00Z`)
      const model=(ideal)=>({model_version:ideal?'newow_base_oscillation_ideal_v3379_v1':'newow_oscillation_experiment_ordinary_v3379_v1',hindsight:ideal,page_parity:true,executable:false,dates,equity:dates.map((_,i)=>i===11?'1':'0'),summary:{trade_count:1,cum_return_percentage_points:'1',accuracy_pct:'100',max_drawdown_percentage_points:'0'},trades:[{segment_id:'exp',physical_contract:'RB2605',entry_bar_end:dates[0],exit_bar_end:dates[11],entry_reference_price:'100',exit_reference_price:'101',return_percentage_points:'1',force_close:false,stop_loss:false,confirm_exit:false}]})
      return route.fulfill({json:{...q,schema_version:'newow_experiment_detail_v1',formula_version:`newow_${q.kind.replace('-','_')}_page_v3379_v1`,page_parity:true,executable:false,window:{since:'2026-08-01',through:'2026-09-03'},readiness:{status:'READY',reason_code:null},bars:dates.map(bar_end=>({bar_end,trading_day:bar_end.slice(0,10),physical_contract:'RB2605',segment_id:'exp',open:'100',high:'110',low:'90',close:'101',channel_high:'110',channel_low:'90'})),markers:[],segments:[{segment_id:'exp',physical_contract:'RB2605',status:'CURRENT',ordinary:model(false),theoretical:model(true)}]}})
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
