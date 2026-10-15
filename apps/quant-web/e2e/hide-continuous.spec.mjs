import { test, expect } from '@playwright/test'
import { mockMarketDetail, navigateClient, detailResearch } from './market-detail.helpers.mjs'

function noContinuousRequests(requests) {
  expect(requests.filter(url => url.searchParams.get('series_kind') === 'continuous')).toEqual([])
}
for (const width of [1440, 390]) {
  for (const view of ['free', 'htdy', 'subing', 'newow']) {
    test(`legacy series migrates before reads in ${view} at ${width}`, async ({page}) => {
      await page.setViewportSize({width,height:900})
      const requests = await mockMarketDetail(page)
      const frequency = view === 'newow' ? '1d' : '15m'
      await page.goto(`/market/chart?view=${view}&symbol=jm&series_kind=continuous&frequency=${frequency}&contract=JM2601&focus_bar_end=2026-09-02T02:45:00Z`)
      await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
      await expect(page.getByTestId('market-detail-migration-notice')).toHaveText('已切换为真实主力序列')
      await expect(page.locator('.detail-view-nav')).toBeVisible()
      await expect(page.getByRole('button', {name:'主连',exact:true})).toHaveCount(0)
      expect(new URL(page.url()).searchParams.has('contract')).toBe(false)
      expect(new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
      await expect.poll(()=>requests.length).toBeGreaterThan(0)
      noContinuousRequests(requests)
      expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1)).toBe(true)
    })
  }
  test(`saved series migrates once and retains display settings at ${width}`, async ({page}) => {
    await page.setViewportSize({width,height:900})
    await page.addInitScript(()=>{
      const key='guiyi.market.detail.preferences.v2'
      if(!localStorage.getItem(key)) localStorage.setItem(key,JSON.stringify({version:2,lastView:'htdy',newow:{strategy:'trend',frequency:'1d'},htdy:{seriesKind:'continuous',frequency:'30m',optionalEmaIndicators:['ema_60'],showRangeDetector:true},free:{seriesKind:'continuous',frequency:'60m',optionalEmaIndicators:['ema_10'],showRangeDetector:false}}))
    })
    const requests=await mockMarketDetail(page)
    await page.goto('/market/chart?view=free&symbol=jm&series_kind=actual_dominant&frequency=15m')
    await expect(page.getByTestId('market-detail-migration-notice')).toHaveText('已切换为真实主力序列')
    const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('guiyi.market.detail.preferences.v2')))
    expect(saved.htdy).toEqual({seriesKind:'actual_dominant',frequency:'30m',optionalEmaIndicators:['ema_60'],showRangeDetector:true})
    expect(saved.free).toEqual({seriesKind:'actual_dominant',frequency:'60m',optionalEmaIndicators:['ema_10'],showRangeDetector:false})
    await page.reload()
    await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
    await expect(page.getByTestId('market-detail-migration-notice')).toHaveCount(0)
    await page.getByRole('tab',{name:'火天大有',exact:true}).click()
    await expect.poll(()=>new URL(page.url()).searchParams.get('frequency')).toBe('30m')
    await expect(page.getByRole('button',{name:'主连',exact:true})).toHaveCount(0)
    noContinuousRequests(requests)
  })
}

test('same-identity legacy navigation canonicalizes, preserves history, and retains contract access',async({page})=>{
  const requests=await mockMarketDetail(page)
  const actual='/market/chart?view=free&symbol=jm&series_kind=actual_dominant&frequency=15m'
  await page.goto(actual)
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await navigateClient(page,actual.replace('actual_dominant','continuous')+'&focus_bar_end=2026-09-02T02:45:00Z')
  await expect.poll(()=>new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  expect(new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  await navigateClient(page,actual.replace('symbol=jm','symbol=rb'))
  await expect(page.getByRole('button',{name:'切换品种或合约',exact:true})).toContainText('螺纹钢')
  await page.goBack()
  await expect.poll(()=>new URL(page.url()).searchParams.get('symbol')).toBe('jm')
  await expect.poll(()=>new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  await page.getByRole('textbox',{name:'指定合约',exact:true}).fill('JM2601')
  await page.getByRole('button',{name:'指定合约',exact:true}).click()
  await expect.poll(()=>new URL(page.url()).searchParams.get('series_kind')).toBe('contract')
  await expect.poll(()=>requests.some(url=>url.pathname.endsWith('/bars/page')&&url.searchParams.get('series_kind')==='contract')).toBe(true)
  noContinuousRequests(requests)
})

test('continuous-only statistics are withheld with an explicit mismatch notice',async({page})=>{
  await mockMarketDetail(page)
  await page.route('**/api/v1/market/research/product?**',route=>route.fulfill({json:{...detailResearch('jm'),series_kind:'continuous',metric_contract:'MAIN',volume_ratio20:98765}}))
  await page.goto('/market/chart?view=free&symbol=jm&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByRole('button',{name:/市场背景.*该统计不适用于当前序列/})).toBeVisible()
  await page.getByRole('button',{name:/市场背景/}).click()
  await expect(page.getByText('98765',{exact:true})).toHaveCount(0)
  await expect(page.getByText('MAIN 连续',{exact:true})).toHaveCount(0)
})
