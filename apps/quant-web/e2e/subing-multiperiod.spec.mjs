import { test, expect } from '@playwright/test'
import { mockMarketDetail, subingEvent, subingRule } from './market-detail.helpers.mjs'

const frequencies = ['5m','15m','30m','60m','1d','1w']
function event(frequency, id, status) {
  return {...subingEvent('jm'),id,frequency,bar_end:`2026-09-03T02:${id===10?'15':id===11?'30':'45'}:00.000Z`,formula_version:'subing_ths_v4',subing_alignment:status ? {
    policy_version:'subing_ema21_alignment_v1',as_of:'2026-09-03T02:45:00.000Z',observed_at:'2026-09-03T02:46:00.000Z',status,
    periods:frequencies.map(frequency => ({frequency,contract:'JM2601',bar_end:'2026-09-03T02:45:00.000Z',close:'1E+3',ema21:'9.99E+2',direction:'LONG',reason:null})),
  } : null}
}

test('six-period persisted events and saved alignment filter (explicit browser fixtures)', async ({page}) => {
  const rule = {...subingRule(true),input_frequencies:frequencies,enabled_frequencies:frequencies}
  const requests = await mockMarketDetail(page, {alertRules:[rule],alertEvents:({url}) => [event(url.searchParams.get('frequency') ?? '15m',10,'PASS'),event(url.searchParams.get('frequency') ?? '15m',11,'UNKNOWN'),event(url.searchParams.get('frequency') ?? '15m',12,null)]})
  const referenceRequests = []
  await page.route('**/api/v1/market/*/subing/reference**', route => { referenceRequests.push(new URL(route.request().url())); return route.fulfill({status:503,json:{detail:'Explicit fixture: historical reference unavailable'}}) })
  await page.route('**/api/v1/reference-trading/**', route => route.fulfill({status:503,json:{detail:'Explicit fixture: reference stream unavailable'}}))
  for (const frequency of frequencies) {
    await page.goto(`/market/chart?symbol=jm&view=subing&frequency=${frequency}`)
    const workspace = page.locator('[data-detail-workspace="subing"]')
    await expect(workspace).toBeVisible()
    await expect(workspace.getByRole('button',{name:'全部信号',exact:true})).toBeVisible()
    await page.getByRole('tab',{name:'历史记录',exact:true}).click()
    const history = workspace.locator('.detail-section-tabs__history')
    await expect(history).toContainText('六周期同向')
    await expect(history).toContainText('无法判断')
    await expect(history).toContainText('未记录')
    await workspace.getByRole('button',{name:'六周期同向',exact:true}).click()
    await expect(history).toContainText('六周期同向')
    await expect(history).not.toContainText('无法判断')
    await expect(history).not.toContainText('未记录')
    await history.getByRole('button').first().click()
    await expect(page.getByRole('columnheader',{name:'EMA21',exact:true})).toBeVisible()
    await expect(page.getByRole('cell',{name:'1E+3',exact:true})).toHaveCount(6)
    if (frequency === '5m' || frequency === '1w') expect(referenceRequests.filter(url=>url.searchParams.get('frequency')===frequency)).toEqual([])
  }
  expect(requests.alertRequests.every(request=>request.method==='GET')).toBe(true)
})
