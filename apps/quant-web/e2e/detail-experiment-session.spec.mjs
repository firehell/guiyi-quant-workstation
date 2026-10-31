import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute } from './newow-product.helpers.mjs'
import { installDetailExperimentSessionFixtures } from './fixtures/detail-experiment-session.mjs'

async function rememberCanvas(page) {
  const native = page.locator('.tv-lightweight-charts').first()
  await expect(native).toBeVisible()
  await native.evaluate(element => { window.__experimentSessionCanvas = element })
}
async function assertCanvasAndInteract(page, errors) {
  const native = page.locator('.tv-lightweight-charts').first()
  await expect(native).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.querySelector('.tv-lightweight-charts') === window.__experimentSessionCanvas && window.__experimentSessionCanvas.isConnected)).toBe(true)
  await native.scrollIntoViewIfNeeded()
  const box = await native.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box.x + box.width * .6, box.y + box.height * .35)
  await page.mouse.down(); await page.mouse.move(box.x + box.width * .6 - 45,box.y + box.height * .35,{steps:6}); await page.mouse.up()
  await page.mouse.wheel(0,-120)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(errors).toEqual([])
}
async function chooseTest(page,label) {
  await page.getByLabel('牛哇T策略',{exact:true}).click()
  await page.getByRole('button',{name:label,exact:true}).click()
}

test('repeated T experiment and ordinary switches keep the native canvas through Donchian and range interaction',async({page})=>{
  const errors=[]; page.on('pageerror',error=>errors.push(error.message))
  await installNewowProductFixtures(page)
  const fixture=await installDetailExperimentSessionFixtures(page)
  await page.goto(newowRoute('trend','1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
  await rememberCanvas(page)
  for(const label of ['测试','测试2','测试3','测试4','测试']) {
    await chooseTest(page,label)
    await expect(page.locator('.experiment-panel [data-testid="experiment-summary"]')).toContainText('+1.00 百分点')
    const donchian=page.locator('.experiment-panel').getByRole('button',{name:'唐奇安通道',exact:true})
    await donchian.click(); await expect(donchian).toHaveAttribute('aria-pressed','true')
    await assertCanvasAndInteract(page,errors)
    await donchian.click(); await expect(donchian).toHaveAttribute('aria-pressed','false')
    await page.getByRole('tab',{name:'趋势策略',exact:true}).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
    await expect(page.locator('.experiment-panel')).toHaveCount(0)
    await assertCanvasAndInteract(page,errors)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe('1d')
  }
  expect(fixture.experiments.map(item=>item.kind)).toEqual(expect.arrayContaining(['osc-test','osc-test2','osc-test3','osc-test4']))
  expect(errors).toEqual([])
})

test('futures bidirectional model and variants retain the same ordinary native canvas',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message))
  await installNewowProductFixtures(page)
  const fixture=await installDetailExperimentSessionFixtures(page)
  await page.goto(newowRoute('trend','1d'))
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
  await rememberCanvas(page)
  await page.getByTestId('futures-model-switch').click()
  const workspace=page.getByTestId('futures-workspace')
  await expect(workspace).toContainText('10万元模型账户')
  await assertCanvasAndInteract(page,errors)
  for(const label of ['震荡策略','双策略','趋势策略']) {
    await page.getByRole('tab',{name:label,exact:true}).click()
    await expect(workspace).toHaveAttribute('aria-busy','false')
    await expect(workspace.getByTestId('kline-shell')).toBeVisible()
    await assertCanvasAndInteract(page,errors)
    expect(new URL(page.url()).searchParams.get('strategy_model')).toBe('futures_bidir_v1')
  }
  await page.getByTestId('futures-model-switch').click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state','ready')
  await assertCanvasAndInteract(page,errors)
  expect(fixture.futures.filter(url=>url.pathname.endsWith('/snapshot')).map(url=>url.searchParams.get('strategy'))).toEqual(expect.arrayContaining(['trend','oscillation','dual_fusion']))
  expect(errors).toEqual([])
})
