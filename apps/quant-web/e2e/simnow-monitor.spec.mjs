import { expect,test } from '@playwright/test'
import fixture from './fixtures/simnow-monitor.json' with {type:'json'}
import { lightHomeOverview } from './fixtures/market-home-light.mjs'
import { mockMarketDetail,installDetailFakeWebSocket } from './market-detail.helpers.mjs'
async function install(page,{empty=false}={}) {
 const requests=[],errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await mockMarketDetail(page);await installDetailFakeWebSocket(page)
 await page.route('**/api/runtime/health',r=>r.fulfill({json:{status:'degraded',components:{},readonly:true}}))
 await page.route('**/market/research/home-overview',r=>r.fulfill({json:lightHomeOverview()}))
 await page.route('**/market/product-directory',r=>r.fulfill({json:{items:lightHomeOverview().items.map(({symbol,product_name,exchange,sector})=>({product:symbol,product_name,exchange,sector}))}}))
 let failure=false
 await page.route('**/api/simnow/monitor/**',r=>{
  const url=new URL(r.request().url());requests.push(url)
  if(failure)return r.fulfill({status:503,json:{detail:{code:'MONITOR_SOURCE_UNAVAILABLE'}}})
  if(url.pathname.endsWith('/overview'))return r.fulfill({json:empty?{...fixture.overview,status:'not_connected',account:null,snapshot:null,observer:null,readback_at:null,trading_day:null,position_projection_complete:false,metrics:Object.fromEntries(Object.keys(fixture.overview.metrics).map(k=>[k,null])),positions:[],curve:[],issues:[],issue_count:null}:fixture.overview})
  if(url.pathname.endsWith('/records'))return r.fulfill({json:{...fixture.page,items:fixture.page.items.filter(v=>url.searchParams.get('kind')==='all'||v.kind===url.searchParams.get('kind'))}})
  return r.fulfill({json:fixture.detail})
 })
 return {requests,errors,fail:()=>failure=true}
}
test('empty monitor stays honest and Tab selection survives navigation reload',async({page})=>{
 const s=await install(page,{empty:true})
 await page.goto('/market')
 await expect(page.getByRole('tab')).toHaveText(['市场','消息','模拟交易'])
 await page.getByRole('tab',{name:'模拟交易',exact:true}).click()
 await expect(page.getByRole('heading',{name:'尚未接入模拟交易监控'})).toBeVisible()
 await expect(page.getByText('没有记录不代表账户空仓或收益为零。',{exact:false})).toBeVisible()
 await page.reload()
 await expect(page.getByRole('tab',{name:'模拟交易',exact:true})).toHaveAttribute('aria-selected','true')
 await page.goto('/market/chart?symbol=jm&view=htdy&frequency=60m')
 await page.getByRole('tab',{name:'模拟交易',exact:true}).click()
 await expect(page).toHaveURL(/\/market$/)
 await expect(page.getByRole('heading',{name:'尚未接入模拟交易监控'})).toBeVisible()
 expect(s.errors).toEqual([])
})
for(const mobile of [false,true])test(`account chain, filtering, errors and ${mobile?'mobile fullscreen':'desktop'} visual`,async({page})=>{
 if(mobile)await page.setViewportSize({width:375,height:812})
 const s=await install(page)
 await page.goto('/market');await page.getByRole('tab',{name:'模拟交易',exact:true}).click()
 await expect(page.getByText('99,996.88',{exact:true}).first()).toBeVisible()
 await expect(page.getByRole('img',{name:'原生账户权益走势'})).toBeVisible()
 await page.screenshot({path:`../../output/playwright/simnow-${mobile?'mobile':'desktop'}.png`,fullPage:true})
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await page.getByRole('button',{name:'执行记录',exact:true}).click()
 await page.getByRole('button',{name:'筛选',exact:true}).click()
 await page.getByLabel('开始记录日期').fill('2026-10-01')
 await page.getByLabel('结束记录日期').fill('2026-10-27')
 await page.getByRole('button',{name:'成交',exact:true}).click()
 await expect.poll(()=>s.requests.filter(u=>u.pathname.endsWith('/records')).at(-1)?.searchParams.get('kind')).toBe('fill')
 expect(s.requests.filter(u=>u.pathname.endsWith('/records')).at(-1)?.searchParams.get('start_day')).toBe('2026-10-01')
 await expect(page.locator('.simnow-table tbody tr')).toHaveCount(1)
 await page.getByRole('button',{name:/查看执行链 RB 实际成交入账/}).click()
 await expect(page.getByRole('dialog')).toBeVisible()
 await expect(page.locator('.simnow-chain li')).toHaveCount(4)
 if(mobile){const bounds=await page.getByRole('dialog').boundingBox();expect(bounds.width).toBe(375)}
 await page.screenshot({path:`../../output/playwright/simnow-chain-${mobile?'mobile':'desktop'}.png`,fullPage:true})
 await page.getByRole('button',{name:'关闭执行链'}).click()
 s.fail();await page.getByRole('button',{name:'刷新',exact:true}).click()
 await expect(page.getByRole('alert')).toContainText('保留上次快照')
 await expect(page.getByText('99,996.88',{exact:true}).first()).toBeVisible()
 expect(s.errors).toEqual([])
})
test('five second polling stops after leaving Tab and hidden page',async({page})=>{
 const s=await install(page)
 await page.clock.install()
 await page.goto('/market');await page.getByRole('tab',{name:'模拟交易',exact:true}).click()
 await expect(page.getByText('99,996.88',{exact:true}).first()).toBeVisible()
 const count=()=>s.requests.filter(u=>u.pathname.endsWith('/overview')).length
 const before=count()
 await page.clock.runFor(5100);await expect.poll(count).toBeGreaterThan(before)
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'))})
 const hidden=count();await page.clock.runFor(15000);expect(count()).toBe(hidden)
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'))})
 await expect.poll(count).toBeGreaterThan(hidden)
 await page.getByRole('tab',{name:'市场',exact:true}).click()
 const left=count();await page.clock.runFor(15000);expect(count()).toBe(left)
})
