import { expect, test } from '@playwright/test'
import { detailBar, htdyEvent, mockMarketDetail, subingEvent, subingRule } from './market-detail.helpers.mjs'
// Isolated fixtures verify presentation, not actual runtime records.
async function setup(page, missing = false, options = {}) {
  const bars = Array.from({length:80}, (_, i) => detailBar('jm', i))
  await mockMarketDetail(page, {barsPage:({url})=>['1d','1w'].includes(url.searchParams.get('frequency'))?undefined:({bars}), alertEvents:({url})=>[url.searchParams.get('rule_code')==='htdy_original_15m'?htdyEvent('jm',url.searchParams.get('frequency')):{...subingEvent('jm'),frequency:url.searchParams.get('frequency')}], alertRules:[subingRule()]})
  const requests = []
  page.on('request', request => { if(request.url().includes('/api/v1/')) requests.push(new URL(request.url())) })
  await page.route('**/api/v1/reference-trading/**', async route => {
    const url = new URL(route.request().url()), since = url.searchParams.get('since'), through = url.searchParams.get('through')
    const stream = {stream_id:'fixture-forward', recording_mode:'forward_observation', active_revision_id:'r', latest_seq:1, activation_generation:1, readable:true, recording_start:'2026-08-01T00:00:00Z', health:'ready'}
    const rows = Array.from({length:5}, (_,i)=>({reference_trade_id:`forward-${i}`, physical_contract:'JM2601', side:'LONG', status:i?'CLOSED':'OPEN', entry_bar_end:bars[10+i].bar_end, entry_trading_day:'2026-09-03', entry_reference_price:'100', exit_bar_end:i?bars[11+i].bar_end:null, exit_reference_price:i?'101':null, reference_return:i?'1':null, mark_return:'0.5', mark_reference_price:'100.5', mark_bar_end:bars.at(-1).bar_end}))
    if (options.zeroClosed) rows.splice(0, rows.length, rows[0], {...rows[1],status:'OBSERVATION_INTERRUPTED',reference_return:null,exit_bar_end:null,exit_reference_price:null,mark_return:null,mark_reference_price:null,mark_bar_end:null})
    const first = {stream, items:rows, next_cursor:options.zeroClosed?null:'next', snapshot:'exact', revision_id:'r', seq:1, window:{since,through}, coverage:{computed_through:bars.at(-1).bar_end,complete_window_proven:true}}
    if(url.pathname.endsWith('/streams')) return route.fulfill({json:{items:missing?[]:[stream]}})
    if (options.fail?.(url)) return route.fulfill({status:503,json:{detail:{code:'PRESENTATION_CORRUPT'}}})
    if(url.pathname.endsWith('/panel')) return route.fulfill({json:{version:'forward_reference_panel_v1',page:first,summary:{snapshot:'exact',closed_count:options.zeroClosed?0:4,open_count:1,interrupted_count:options.zeroClosed?1:0,initial_count:0,win_rate_pct:options.zeroClosed?null:'100',sum_return_percentage_points:options.zeroClosed?'0':'4'},curve:(options.zeroClosed?[]:rows.slice(1)).map((row,i)=>({value:String(i+1),date:'2026-09-03',bar_end:row.exit_bar_end,reference_trade_id:row.reference_trade_id,segment:'owner'})),total_curve_points:options.zeroClosed?0:4,drawdown_percentage_points:options.zeroClosed?null:'0'}})
    if(url.pathname.endsWith('/trades')) return route.fulfill({json:{...first,items:[{...rows[1],reference_trade_id:'older'}],next_cursor:null}})
    return route.fulfill({status:500,json:{detail:'Unexpected fixture read'}})
  })
  return requests
}
for(const view of ['subing','htdy']) {
  test(`${view} retained curve, recent cards, lazy history and no replay`,async({page})=>{
    const requests=await setup(page)
    await page.goto(`/market/chart?symbol=jm&view=${view}&series_kind=actual_dominant&frequency=${view === 'htdy' ? '60m' : '15m'}`)
    if (view === 'htdy') await page.getByRole('button',{name:'实时参考',exact:true}).click()
    const panel=page.getByRole('region',{name:'实时参考收益与记录',exact:true})
    await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
    await expect(panel.locator('svg')).toBeVisible()
    await expect(panel).toContainText('+4 百分点')
    const curve = panel.locator('svg')
    await curve.focus(); await curve.press('End')
    await curve.press('Enter')
    await expect(panel.locator('.forward-reference__selected')).toHaveCount(1)
    await expect(panel.locator('.forward-reference__selected')).toContainText('已完成参考')
    const selectedId = await panel.locator('.forward-reference__selected').getAttribute('data-reference-trade-id')
    const bounds = await curve.boundingBox()
    await curve.click({position:{x:bounds.width-1,y:bounds.height/2}})
    await expect(panel.locator('.forward-reference__selected')).toHaveAttribute('data-reference-trade-id',selectedId)
    await expect(panel.locator('.return-curve__readout')).toContainText('4百分点')
    await panel.screenshot({ path: `/tmp/guiyi-forward-reference-fixture-${view}.png` })
    expect(requests.filter(url=>url.pathname.endsWith('/panel'))).toHaveLength(1)
    expect(requests.filter(url=>url.pathname.endsWith('/trades'))).toHaveLength(0)
    expect(requests.some(url=>/\/(subing|htdy)\/reference$/.test(url.pathname))).toBe(false)
    expect(requests.filter(url=>url.pathname.endsWith('/streams')).every(url=>url.searchParams.get('mode')==='forward_observation')).toBe(true)
    if (await panel.getByRole('button',{name:'查看全部',exact:true}).count()) await panel.getByRole('button',{name:'查看全部',exact:true}).click()
    await expect(panel.locator('.newow-reference__card')).toHaveCount(5)
    await panel.getByRole('button',{name:'读取更多参考记录'}).click()
    await expect(panel.locator('.newow-reference__card')).toHaveCount(6)
    expect(requests.find(url=>url.pathname.endsWith('/trades')).searchParams.get('snapshot')).toBe('exact')
    await panel.getByRole('button',{name:'收益分析 ›'}).click()
    await expect(page.getByRole('dialog')).toContainText('不包含盘后重算')
  })
  test(`${view} absent retained stream never fabricates a curve`,async({page})=>{
    await setup(page,true)
    await page.goto(`/market/chart?symbol=jm&view=${view}&series_kind=actual_dominant&frequency=${view === 'htdy' ? '60m' : '15m'}`)
    if (view === 'htdy') await page.getByRole('button',{name:'实时参考',exact:true}).click()
    const panel=page.getByRole('region',{name:'实时参考收益与记录',exact:true})
    await expect(panel).toContainText('尚无实时留存参考交易流')
    await expect(panel.locator('svg')).toHaveCount(0)
  })
}
test('mobile retained reference cards fit viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await setup(page)
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=60m')
  await page.getByRole('button',{name:'实时参考',exact:true}).click()
  await expect(page.locator('.forward-reference .newow-reference__card')).toHaveCount(3)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
})

for (const frequency of ['5m', '15m', '30m', '60m', '1d', '1w']) {
  test(`SuBing ${frequency} reference panel follows the display periods without hiding signal audit`, async ({ page }) => {
    const requests = await setup(page)
    const eventReads = []
    page.on('request', r => { if (new URL(r.url()).pathname.endsWith('/api/alerts/events')) eventReads.push(new URL(r.url())) })
    await page.goto(`/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=${frequency}`)
    await expect(page.locator('[data-detail-workspace="subing"] .market-kline-stage')).toBeVisible()
    await expect(page.locator('.observed-records__audit')).toBeVisible()
    const panel = page.getByRole('region', { name: '实时参考收益与记录', exact: true })
    if (['5m', '15m', '30m', '60m', '1d', '1w'].includes(frequency)) {
      await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
      expect(requests.some(url => url.pathname.endsWith('/streams') && url.searchParams.get('frequency') === frequency)).toBe(true)
    } else {
      await expect(panel).toHaveCount(0)
      await expect(page.locator('.subing-workspace__reference-source')).toHaveCount(0)
      await expect.poll(() => eventReads.length).toBeGreaterThan(0)
      expect(requests.filter(url => url.pathname.includes('/reference-trading/'))).toHaveLength(0)
    }
  })
}
test('SuBing SPA keeps independent reference identities at 5m and 30m', async ({ page }) => {
  const requests = await setup(page)
  await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=15m')
  const panel = page.getByRole('region', { name: '实时参考收益与记录', exact: true })
  await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
  const controls = page.getByRole('group', { name: '周期', exact: true })
  await controls.getByRole('button', { name: '5分钟', exact: true }).click()
  await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
  expect(requests.some(url=>url.pathname.endsWith('/streams') && url.searchParams.get('frequency') === '5m')).toBe(true)
  await controls.getByRole('button', { name: '30分钟', exact: true }).click()
  await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
})


for (const width of [1188,390]) {
  test(`SuBing uses Newow-style windows and analysis at width ${width}`, async ({page}) => {
    await page.setViewportSize({width,height:900})
    const requests=await setup(page)
    await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=60m')
    const panel=page.getByRole('region',{name:'实时参考收益与记录',exact:true})
    await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
    await expect(panel.getByRole('button',{name:'近3月',exact:true})).toHaveAttribute('aria-pressed','true')
    for (const label of ['近3月','近1年','近3年','今年','全部']) {
      await panel.getByRole('button',{name:label,exact:true}).click()
      await expect(panel.getByRole('button',{name:label,exact:true})).toHaveAttribute('aria-pressed','true')
    }
    expect(requests.filter(r=>r.pathname.endsWith('/panel')).at(-1).searchParams.get('since')).toBe('2026-08-01')
    await expect(panel.getByRole('button',{name:'理论值',exact:true})).toHaveCount(0)
    await expect(panel.locator('.newow-reference__annualized')).toHaveCount(0)
    await panel.getByRole('button',{name:'收益分析 ›'}).click()
    const drawer=page.getByRole('dialog',{name:'实时参考收益分析'})
    await expect(drawer).toContainText('累计参考收益')
    await expect(drawer).toContainText('已完成参考交易')
    await drawer.getByLabel('实时参考开始交易日').fill('2026-09-04')
    await drawer.getByLabel('实时参考结束交易日').fill('2026-09-03')
    await expect(drawer.getByRole('button',{name:'读取参考',exact:true})).toBeDisabled()
    await drawer.getByLabel('实时参考开始交易日').fill('2026-09-01')
    await drawer.getByRole('button',{name:'读取参考',exact:true}).click()
    await expect.poll(()=>requests.filter(r=>r.pathname.endsWith('/panel')).at(-1).searchParams.get('since')).toBe('2026-09-01')
    await expect(panel.getByRole('button',{name:'全部',exact:true})).toHaveAttribute('aria-pressed','false')
  })
}


for (const width of [1188,390]) {
  test(`SuBing zero closed trades shows records without invented curve at width ${width}`, async ({page}) => {
    await page.setViewportSize({width,height:900})
    await setup(page,false,{zeroClosed:true})
    await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=60m')
    const panel=page.getByRole('region',{name:'实时参考收益与记录',exact:true})
    await expect(panel.locator('.newow-reference__card')).toHaveCount(2)
    await expect(panel).toContainText('所选窗口暂无已完成实时参考交易')
    await expect(panel.locator('svg')).toHaveCount(0)
    await expect(panel.locator('.newow-reference__metrics dd')).toHaveText(['—','—','—','0'])
    const interrupted=panel.locator('.newow-reference__card').filter({hasText:'观察中断'})
    await expect(interrupted).toContainText('中断 · 未计收益')
    await expect(interrupted).not.toContainText('估值')
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
  })
}

test('SuBing rejected windows never highlight success and paging errors retain records', async ({page}) => {
  let failWindow=true, failPage=true
  await setup(page,false,{fail:url=>url.pathname.endsWith('/panel')&&url.searchParams.get('since')==='2026-08-01'&&failWindow || url.pathname.endsWith('/trades')&&failPage})
  await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=60m')
  const panel=page.getByRole('region',{name:'实时参考收益与记录',exact:true})
  await expect(panel.locator('.newow-reference__card')).toHaveCount(3)
  await panel.getByRole('button',{name:'近3年',exact:true}).click()
  await expect(panel).toContainText('实时参考暂不可用')
  await expect(panel.locator('.newow-reference__presets button[aria-pressed="true"]')).toHaveCount(0)
  failWindow=false
  await panel.getByRole('button',{name:'重新读取',exact:true}).click()
  await expect(panel.getByRole('button',{name:'近3年',exact:true})).toHaveAttribute('aria-pressed','true')
  await panel.getByRole('button',{name:'查看全部',exact:true}).click()
  await panel.getByRole('button',{name:'读取更多参考记录',exact:true}).click()
  await expect(panel).toContainText('记录读取失败或快照已变化')
  await expect(panel.locator('.newow-reference__card')).toHaveCount(5)
  failPage=false
  await panel.getByRole('button',{name:'读取更多参考记录',exact:true}).click()
  await expect(panel.locator('.newow-reference__card')).toHaveCount(6)
})
