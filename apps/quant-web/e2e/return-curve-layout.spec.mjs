import { test, expect } from '@playwright/test'
import { buildNewowFixtureEnvelopeForTest } from './newow-product.helpers.mjs'

for (const width of [1440, 390]) {
  test(`shared return SVG and all three consumers retain geometry and interaction at ${width}`, async ({page}) => {
    const envelope = buildNewowFixtureEnvelopeForTest('reference')
    const response = {meta:envelope.meta,section:'reference',status:envelope.reference.status,value:envelope.reference.value}
    const holding = {
      model_version:'newow_reference_marked_curve_v1', page_parity:true, executable:false,
      points: [0,1,2,3].map(i => ({
        bar_end:`2026-09-0${Math.floor(i/2)+1}T0${i%2+1}:00:00Z`, trading_day:`2026-09-0${Math.floor(i/2)+1}`,
        physical_contract:i<2?'RB2605':'RB2610', segment_id:i<2?'first':'second', calculation_segment_id:i<2?'first':'second',
        closed_return_percentage_points:'0',floating_return_pct:String(i),marked_return_percentage_points:String(i),
        reference_trade_id:null,status:'FLAT',
      })),
    }
    response.value.holding_curve = holding
    const mode={period:'day',summary:{cumReturn:'3',accuracy:0,maxDrawdown:'0',tradeCount:0},dates:holding.points.map(p=>p.bar_end),trading_days:holding.points.map(p=>p.trading_day),segment_ids:['a','a','b','b'],equity:['0','1','2','3'],trades:[]}
    const pagePerformance={strategy:'trend',ordinary:mode,ideal:null}
    const fusion={...response.value,curve:[],items:[],groups:[{model:'fusion',closed_count:0,sum_return_percentage_points:'0',open_count:0,interrupted_count:0}],holding_curve:holding,records_truncated:false,page_performance:pagePerformance}
    await page.route('**/src/api/newowFusion.ts', route=>route.fulfill({contentType:'text/javascript',body:'export async function getNewowFusion() { return window.curveFixture.fusion }'}))
    await page.route('**/__curve-harness', route=>route.fulfill({contentType:'text/html',body:`<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="harness"></div><script type="module">
      import {createApp,h} from '/node_modules/.vite/deps/vue.js';
      import Reference from '/src/components/market/detail/newow/NewowReferencePanel.vue';
      import Fusion from '/src/components/market/detail/newow/NewowFusionPanel.vue';
      import Performance from '/src/components/market/detail/newow/NewowPagePerformancePanel.vue';
      const f=window.curveFixture;
      createApp({render:()=>h('main',{},[
        h('div',{id:'page'},[h(Performance,{value:f.pagePerformance})]),
        h('div',{id:'reference'},[h(Reference,{response:f.response,chartResponse:null,crossSectionCompatible:false,lifecycle:'ready',error:null,selectedSignalId:null,locateMessage:null,loadingPage:false})]),
        h('div',{id:'fusion'},[h(Fusion,{response:f.response})]),
      ])}).mount('#harness');
    </script></body></html>`}))
    await page.addInitScript(fixture=>{window.curveFixture=fixture},{response,fusion,pagePerformance})
    await page.setViewportSize({width,height:900})
    await page.goto('/__curve-harness')
    await page.locator('#reference').getByRole('button',{name:'含浮动参考',exact:true}).click()
    await page.locator('#fusion').getByRole('button',{name:'含浮动参考',exact:true}).click()
    for (const id of ['page','reference','fusion']) {
      const svg=page.locator(`#${id} .return-curve svg`).first()
      await expect(svg).toBeVisible()
      await expect(svg.locator('polyline')).toHaveCount(2)
      const polylines=await svg.locator('polyline').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('points')))
      expect(polylines.every(p=>!p.includes('NaN'))).toBe(true)
      const box=await svg.boundingBox()
      expect(box.width).toBeGreaterThan(100)
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x+box.width).toBeLessThanOrEqual(width)
    }
    const holdingSvg=page.locator('#reference .return-curve svg').first()
    await holdingSvg.hover({position:{x:10,y:40}})
    await expect(page.locator('#reference .newow-reference__tooltip')).toContainText('2026-09-01')
    await expect(holdingSvg.locator('circle')).toHaveCount(2)
    const fusionSvg=page.locator('#fusion .return-curve svg').last()
    await fusionSvg.hover({position:{x:10,y:40}})
    await expect(page.locator('#fusion .newow-holding-readout')).toContainText('2026-09-01')
    const ids=await page.locator('linearGradient').evaluateAll(nodes=>nodes.map(n=>n.id))
    expect(new Set(ids).size).toBe(ids.length)
    await page.screenshot({path:`/private/tmp/guiyi-return-curve-${width}.png`,fullPage:true})
  })
}
