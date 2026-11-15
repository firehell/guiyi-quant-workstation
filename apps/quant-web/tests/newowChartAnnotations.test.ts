import type { UTCTimestamp } from 'lightweight-charts'
import { NewowPriceAnnotationPrimitive } from '../src/components/market/detail/newow/newowPriceAnnotationPrimitive.ts'
import assert from 'node:assert/strict'
import test from 'node:test'
import { newowExtrema, newowNineTurn, newowReversalPivots } from '../src/utils/newowChartAnnotations.ts'

const bars = (count: number) => Array.from({ length: count }, (_, index) => ({
  owner: 'segment-a', close: index + 2, high: index + 3, low: index + 1, volume: 10,
}))

test('extrema retain original indexes and the public nine-right-neighbor boundary', () => {
  const sequence = bars(21)
  sequence[1]!.volume = 0
  sequence[11]!.high = 100
  sequence[11]!.low = 0
  assert.deepEqual(newowExtrema(sequence), [
    { index: 11, side: 'high' }, { index: 11, side: 'low' },
  ])
  sequence[20]!.high = 100
  assert.deepEqual(newowExtrema(sequence), [{ index: 11, side: 'low' }])
  sequence[20]!.owner = 'segment-b'
  assert.deepEqual(newowExtrema(sequence), [])
})

test('nine-turn back-labels a complete nine and suppresses an interrupted partial run', () => {
  assert.deepEqual(newowNineTurn(bars(13)).map(x => x.count), [1,2,3,4,5,6,7,8,9])
  const tentative = newowNineTurn(bars(12))
  assert.equal(tentative.length, 8)
  assert.ok(tentative.every(x => x.tentative && x.side === 'high'))
  const interrupted = bars(12)
  interrupted[11]!.close = interrupted[7]!.close
  assert.deepEqual(newowNineTurn(interrupted), [])
  const split = bars(13)
  split.slice(6).forEach(bar => bar.owner = 'segment-b')
  assert.deepEqual(newowNineTurn(split), [])
  const down = bars(10).reverse()
  assert.ok(newowNineTurn(down).every(x => x.side === 'low' && x.tentative))
})

test('WR1 confirmation uses strict runs, first bias tie, and never confirms across missing input', () => {
  const wr1 = [97, 98, 99, 97, 2, 1, null, 98, 99, 96, 2]
  const bias = [0, -3, -3, 1, 5, 7, 5, null, -2, 0, 3]
  assert.deepEqual(newowReversalPivots(wr1, bias), [
    { kind: 'rebound', index: 3, extremeIndex: 1, tentative: false },
    { kind: 'rebound', index: 9, extremeIndex: 8, tentative: false },
  ])
  assert.deepEqual(newowReversalPivots([3, 2, 1, 3], [0, null, null, 1]), [
    { kind: 'adjust', index: 3, extremeIndex: 2, tentative: true },
  ])
})

test('price annotations use chart times when another layer inserts bars into the viewport', () => {
  const marks = [1, 2, 3].map((time, index) => ({
    time: time as UTCTimestamp, index, price: 100, side: 'high' as const, kind: 'extremum' as const, text: String(time),
  }))
  const logicalByTime = new Map([[1, 0], [2, 8], [3, 9]])
  const drawn: string[] = []
  const scale = {
    getVisibleLogicalRange: () => ({ from: 7, to: 8.5 }),
    timeToIndex: (time: number) => logicalByTime.get(time) ?? null,
    timeToCoordinate: (time: number) => (logicalByTime.get(time)! - 7) * 10,
  }
  const layer = new NewowPriceAnnotationPrimitive()
  layer.attached({
    chart: { timeScale: () => scale },
    series: { priceToCoordinate: () => 50 },
    requestUpdate() {},
  } as unknown as Parameters<NewowPriceAnnotationPrimitive['attached']>[0])
  layer.setData(marks, false)
  const renderer = layer.paneViews()[0]!.renderer()!
  renderer.draw({
    useMediaCoordinateSpace(draw: (scope: unknown) => void) {
      draw({
        mediaSize: { width: 15, height: 100 },
        context: {
          save() {}, restore() {}, measureText: () => ({ width: 5 }),
          fillText(text: string) { drawn.push(text) },
        },
      })
    },
  } as unknown as Parameters<typeof renderer.draw>[0])
  assert.deepEqual(drawn, ['2'])
})
