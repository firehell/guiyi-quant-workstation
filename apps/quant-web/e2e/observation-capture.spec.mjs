import { test, expect } from '@playwright/test'

test('freeze the painted chart overlay before the live DOM changes', async ({ page }) => {
  await page.goto('/trade-journal')
  const result = await page.evaluate(async () => {
    const { freezeChartOverlays, paintFrozenOverlays } = await import('/src/utils/observationOverlay.ts')
    const frame = document.createElement('div')
    Object.assign(frame.style, { position: 'fixed', left: '0', top: '0', width: '120px', height: '80px' })
    frame.innerHTML = '<div><div class="surface" style="width:120px;height:80px"></div></div>'
      + '<div class="label" style="position:absolute;left:12px;top:9px;width:38px;height:20px;background:rgb(202,18,48)">信号</div>'
      + '<canvas width="10" height="10" style="position:absolute;left:70px;top:40px"></canvas>'
    document.body.append(frame)
    const source = frame.querySelector('canvas').getContext('2d')
    source.fillStyle = '#329e43'
    source.fillRect(0, 0, 10, 10)
    const frozen = freezeChartOverlays(frame.querySelector('.surface'))
    frame.remove()
    const image = document.createElement('canvas')
    image.width = 120
    image.height = 80
    await paintFrozenOverlays(image, frozen)
    const ctx = image.getContext('2d')
    return { label: [...ctx.getImageData(47, 25, 1, 1).data], drawing: [...ctx.getImageData(72, 42, 1, 1).data],
      encoded: image.toDataURL('image/png').startsWith('data:image/png;base64,') }
  })
  expect(result).toEqual({ label: [202, 18, 48, 255], drawing: [50, 158, 67, 255], encoded: true })
})

test('only captured canonical price and volume identities qualify for pinned replay', async ({ page }) => {
  await page.goto('/trade-journal')
  const results = await page.evaluate(async () => {
    const { captureObservationPane } = await import('/src/utils/observationCapture.ts')
    const bar = { time: '2026-11-27T07:00:00Z', trading_day: '2026-11-27', physicalContract: 'RB2701',
      calculationSegmentId: 'RB2701:2026-11-25', marketSource: 'canonical', sourceBarSha256: 'a'.repeat(64),
      open: 3000, high: 3000, low: 3000, close: 3000, volume: 12 }
    const id = { view: 'free', seriesKind: 'contract', contract: 'RB2701', frequency: '15m', symbol: 'rb' }
    const point = { time: Date.parse(bar.time)/1000, x: .2, open: 3000, high: 3000, low: 3000, close: 3000,
      contract: bar.physicalContract, day: bar.trading_day, segment: bar.calculationSegmentId, stage: 'canonical', confirmed: true,
      hash: bar.sourceBarSha256, volume: 12, drawnVolume: 12 }
    const capture = (overrides, preview) => {
      const session = { captureViewport: () => ({ canvas: document.createElement('canvas'), points: [{...point, ...overrides}],
          gaps: [], priceRanges: [], heights: [], logical: { from: 0, to: 1 }, includesTime: () => true }),
        inspectDisplayedLayers: () => preview ? [{ indicatorId:'price_preview', status:'ready', sourceStage:'active_preview',
          dataCutoff: '2026-11-27T13:15:00Z' }] : [] }
      const next = { ...bar, marketSource:'active_preview', confirmed:false, trading_day:'2026-11-30', time:'2026-11-27T13:15:00Z' }
      return captureObservationPane(session, id, preview ? [bar, next] : [bar], [], {}).pane
    }
    const separate = capture({},true)
    return [capture({},false).source.historical, capture({hash:'b'.repeat(64)},false).source.historical,
      capture({drawnVolume:11},false).source.historical, separate.source.historical, separate.source.trading_day]
  })
  expect(results).toEqual([true, false, false, false, '2026-11-30'])
})
