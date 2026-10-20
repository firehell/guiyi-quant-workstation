import { test, expect } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
import { mockMarketDetail } from './market-detail.helpers.mjs'
const url='/market/chart?view=newow&symbol=jm&strategy=main_rise&series_kind=actual_dominant&frequency=5m&strategy_model=futures_bidir_v1'
async function fixtures(page,withMarket=true){
  if(withMarket)await mockMarketDetail(page)
  const old=[],futures=[]
  page.on('request',request=>{if(request.url().includes('/market/newow/'))old.push(request.url())})
  await page.route('**/api/v1/research/newow-futures/**',route=>{
    const request=new URL(route.request().url());futures.push(request)
    const strategy=request.searchParams.get('strategy')??'main_rise',frequency=request.searchParams.get('frequency')??'5m',product=request.searchParams.get('product')??'jm'
    const run_id=`${product}-${strategy}-${frequency}`,sha256='a'.repeat(64)
    if(request.pathname.endsWith('/snapshot'))return route.fulfill({json:{schema_version:1,run_id,sha256,metadata:{run_id,strategy_model:'futures_bidir_v1',strategy,product:product.toUpperCase(),frequency,scenario:'baseline',as_of:'2026-10-19T15:00:00+08:00',status:'COMPLETED',input_snapshot_hash:'b'.repeat(64),execution_facts_hash:'c'.repeat(64),profile_id:`newow_futures_${strategy}_${frequency}_100k_v1`,auto_order:false,source:'historical_replay'},summary:{status:'COMPLETED',initial_cash:'100000.00',final_equity:'101000.00',account_return_pct:'1.00',max_drawdown_pct:'0.50',total_fees:'50.00',ending_qty:0},reference:{summary:{status:'COMPLETED',closed_trades:2,reference_return_pct:'1.50',executable:false},snapshot:{side:'SHORT',holding_frequency:'60m',entry_reference_price:'1250.00',stop_reference_price:'1270.00',target_reference_price:'1200.00',upgrades:1,overnight_eligible:true,reason:'HOLD'},actions:[{action_id:'entry',action:'OPEN_SHORT',side:'SHORT',price:'1250.00',reference_price:'1250.00',at:'2026-10-19T14:55:00+08:00',reason:'ENTRY_OSCILLATION',bar_end:'2026-10-19T14:55:00+08:00',physical_contract:'JM2701',owner_segment_id:'one'}],trades:[],equity:[]},chart:{bars:[{bar_end:'2026-10-19T14:55:00+08:00',physical_contract:'JM2701',owner_segment_id:'one',open:'1255.00',high:'1260.00',low:'1248.00',close:'1250.00',volume:'123'}],frames:[{bar_end:'2026-10-19T14:55:00+08:00',side:'SHORT',target_reference_price:'1200.00',stop_reference_price:'1270.00'}]},diagnostics:{rejections:['EXECUTION_FACTS_MISSING']}}})
    if(request.pathname.endsWith('/equity-curve')){const kind=request.searchParams.get('kind'),run=decodeURIComponent(request.pathname.split('/').at(-2));return route.fulfill({json:{run_id:run,sha256,kind,status:'COMPLETED',sampled:true,total_points:120,points:[{at:'2026-10-18T14:55:00+08:00',value:kind==='equity'?'100000.00':'0.00'},{at:'2026-10-19T14:55:00+08:00',value:kind==='equity'?'101000.00':'1.50'}]}})}
    const parts=request.pathname.split('/'),part=parts.at(-1),run=decodeURIComponent(parts.at(-2))
    return route.fulfill({json:{run_id:run,sha256,part,items:[],offset:0,total:0,limit:50,next_offset:null}})
  })
  return {old,futures}
}
test('futures refresh/back and disabling unsupported original period isolate all original loaders',async({page})=>{
  const state=await fixtures(page)
  await page.goto(url)
  await expect(page.getByTestId('futures-workspace')).toContainText('空头')
  await expect(page.getByRole('button',{name:'5分钟',exact:true})).toHaveAttribute('aria-pressed','true')
  await expect(page.getByRole('button',{name:'AI分析',exact:true})).toHaveCount(0)
  expect(state.old).toEqual([])
  const frozenChart=page.getByTestId('futures-workspace').getByTestId('kline-shell')
  await expect(frozenChart).toHaveAttribute('data-reference-target-segments','1');await expect(frozenChart).toHaveAttribute('data-reference-stop-segments','1')
  await page.getByRole('button',{name:'目标参考线',exact:true}).click();await expect(frozenChart).toHaveAttribute('data-reference-target-segments','0');await expect(frozenChart).toHaveAttribute('data-reference-stop-segments','1')
  await page.getByRole('button',{name:'保护参考线',exact:true}).click();await expect(frozenChart).toHaveAttribute('data-reference-stop-segments','0')
  await expect(page.locator('[data-reference-id="entry"]')).toHaveAttribute('data-reference-price','1250.00')
  await expect(page.getByRole('region',{name:'独立参考收益曲线',exact:true}).getByRole('img')).toBeVisible()
  await expect(page.getByRole('region',{name:'模型账户权益曲线',exact:true}).getByRole('img')).toBeVisible()
  await expect(page.getByRole('region',{name:'策略参考状态',exact:true})).toContainText('已满足跨日条件')
  await page.reload();await expect(page.getByTestId('futures-workspace')).toContainText('空头');expect(state.old).toEqual([])
  await page.getByTestId('futures-model-switch').click()
  await expect(page).not.toHaveURL(/strategy_model=/);await expect(page).toHaveURL(/frequency=5m/)
  await expect(page.getByTestId('futures-workspace')).toHaveCount(0)
  await expect(page.getByText('当前牛哇周期未开放',{exact:true})).toBeVisible()
  expect(state.old.filter(url=>!url.includes('product-capabilities'))).toEqual([])
  await page.goBack();await expect(page.getByTestId('futures-workspace')).toContainText('空头')
  await page.screenshot({path:'/private/tmp/newow-futures-detail.png',fullPage:true})
})
test('eight selections and all six periods preserve explicit mode and request exact variants',async({page})=>{
  const state=await fixtures(page);await page.goto(url)
  await expect(page.getByTestId('futures-workspace')).toContainText('空头')
  const nav=page.getByRole('navigation',{name:'分析视角'})
  for(const [label,strategy] of [['趋势策略','trend'],['震荡策略','oscillation'],['双策略','dual_fusion']]){
    await nav.getByRole('tab',{name:label,exact:true}).click()
    await expect.poll(()=>state.futures.filter(item=>item.pathname.endsWith('/snapshot')).at(-1)?.searchParams.get('strategy')).toBe(strategy)
  }
  for(const [label,strategy] of [['主升浪','main_rise'],['测试','osc-test'],['测试2','osc-test2'],['测试3','osc-test3'],['测试4','osc-test4']]){
    const menu=nav.locator('details');if(!await menu.evaluate(el=>el.open))await menu.locator('summary').click()
    await menu.getByRole('button',{name:label,exact:true}).click()
    await expect.poll(()=>state.futures.filter(item=>item.pathname.endsWith('/snapshot')).at(-1)?.searchParams.get('strategy')).toBe(strategy)
  }
  for(const [label,frequency] of [['周线','1w'],['日线','1d'],['60分钟','60m'],['30分钟','30m'],['15分钟','15m'],['5分钟','5m']]){
    await nav.getByRole('button',{name:label,exact:true}).click()
    await expect(page).toHaveURL(new RegExp(`frequency=${frequency}`));await expect(page).toHaveURL(/strategy_model=futures_bidir_v1/)
    await expect.poll(()=>state.futures.filter(item=>item.pathname.endsWith('/snapshot')).at(-1)?.searchParams.get('frequency')).toBe(frequency)
  }
  await page.reload();await expect(page).toHaveURL(/newow_test=osc-test4/)
  await expect(page.getByTestId('futures-workspace')).toContainText('10万元模型账户')
  expect(state.old).toEqual([])
})

test('original default workspace and loaders return after futures mode is disabled',async({page})=>{
  await installNewowProductFixtures(page)
  const state=await fixtures(page,false)
  await page.goto(newowRoute('trend','1d'))
  const original=page.locator('[data-detail-workspace="newow"]')
  await expect(original).toHaveAttribute('data-chart-state','ready')
  await expect(original).toHaveAttribute('data-strategy','trend')
  expect(state.futures).toHaveLength(0)
  await page.getByTestId('futures-model-switch').click()
  await expect(page.getByTestId('futures-workspace')).toContainText('空头')
  await expect(original).toHaveCount(0)
  await page.getByTestId('futures-model-switch').click()
  await expect(page).not.toHaveURL(/strategy_model=/)
  await expect(original).toHaveAttribute('data-chart-state','ready')
  await expect(original).toHaveAttribute('data-strategy','trend')
  await expect(page.getByTestId('futures-workspace')).toHaveCount(0)
})

test('uncovered product remains explicit and does not request old strategies',async({page})=>{
  const state=await fixtures(page)
  await page.goto(url.replace('symbol=jm','symbol=cu'))
  await expect(page.getByTestId('futures-workspace')).toContainText('该品种尚未纳入本轮研究')
  expect(state.old).toEqual([]);expect(state.futures).toEqual([])
})
