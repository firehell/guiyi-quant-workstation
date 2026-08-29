import assert from 'node:assert/strict'
import test from 'node:test'
import {
  estimateSubingLabelBoxWidth,
  isSubingStrategyMarker,
  layoutSubingStrategyLabels,
  preferredSideFromMarker,
} from '../src/utils/subingStrategyLabels.ts'

const layoutOptions = {
  boxWidth: 40,
  boxHeight: 18,
  gap: 4,
  stackGap: 2,
  clusterX: 40,
}

test('identifies historical SuBing markers only', () => {
  assert.equal(isSubingStrategyMarker({ id: 'historical:a' }), true)
  assert.equal(isSubingStrategyMarker({ id: 'htdy:卖观察:t' }), false)
  assert.equal(isSubingStrategyMarker({ id: 'alert:htdy_original_15m:jm:15m:t' }), false)
})

test('maps marker position to preferred side', () => {
  assert.equal(preferredSideFromMarker({ position: 'aboveBar' }), 'above')
  assert.equal(preferredSideFromMarker({ position: 'belowBar' }), 'below')
})

test('keeps default side when boxes do not overlap', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: 50, wickY: 200, preferredSide: 'below' },
    { id: 'b', label: '清多', x: 250, wickY: 80, preferredSide: 'above' },
  ], { pane, ...layoutOptions })
  assert.equal(laid.find((item) => item.id === 'a')?.side, 'below')
  assert.equal(laid.find((item) => item.id === 'b')?.side, 'above')
})

test('stacks vertically when same-side boxes overlap in x', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '清多', x: 100, wickY: 60, preferredSide: 'above' },
    { id: 'b', label: '建空', x: 105, wickY: 55, preferredSide: 'above' },
  ], { pane, ...layoutOptions })
  const tops = laid.map((item) => item.top).sort((l, r) => l - r)
  assert.equal(tops.length, 2)
  assert.ok(tops[1] - tops[0] >= 18)
  assert.ok(laid.every((item) => item.side === 'above'))
})

test('stacks when anchor delta-x is within box-width overlap', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '清多', x: 100, wickY: 60, preferredSide: 'above' },
    { id: 'b', label: '建空', x: 130, wickY: 55, preferredSide: 'above' },
  ], { pane, ...layoutOptions })
  assert.equal(laid.length, 2)
  const tops = laid.map((item) => item.top).sort((l, r) => l - r)
  assert.ok(tops[1] - tops[0] >= 18)
  assert.ok(laid.every((item) => item.side === 'above'))
})

test('chains x clustering through middle anchor', () => {
  const pane = { left: 0, top: 0, width: 400, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '清多', x: 100, wickY: 60, preferredSide: 'above' },
    { id: 'b', label: '建空', x: 130, wickY: 55, preferredSide: 'above' },
    { id: 'c', label: '建多', x: 160, wickY: 58, preferredSide: 'above' },
  ], { pane, ...layoutOptions })
  assert.equal(laid.length, 3)
  const tops = laid.map((item) => item.top).sort((l, r) => l - r)
  assert.ok(tops[2] - tops[0] >= 36)
})

test('flips to above when below stack would leave the pane', () => {
  const pane = { left: 0, top: 0, width: 200, height: 80 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: 100, wickY: 70, preferredSide: 'below' },
  ], { pane, ...layoutOptions })
  assert.equal(laid[0]?.side, 'above')
  assert.ok(laid[0].top >= pane.top)
  assert.ok(laid[0].top + laid[0].height <= pane.top + pane.height)
})

test('keeps labels that partially overflow horizontally', () => {
  const pane = { left: 0, top: 0, width: 200, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: 10, wickY: 150, preferredSide: 'below' },
  ], { pane, ...layoutOptions })
  assert.equal(laid.length, 1)
  assert.ok(laid[0].left < pane.left)
  assert.ok(laid[0].left + laid[0].width > pane.left)
})

test('drops labels fully outside horizontally', () => {
  const pane = { left: 0, top: 0, width: 200, height: 300 }
  const laid = layoutSubingStrategyLabels([
    { id: 'a', label: '建多', x: -50, wickY: 150, preferredSide: 'below' },
  ], { pane, ...layoutOptions })
  assert.equal(laid.length, 0)
})

test('drops anchors with non-finite coordinates', () => {
  const pane = { left: 0, top: 0, width: 200, height: 200 }
  const laid = layoutSubingStrategyLabels([
    { id: 'bad', label: '建多', x: Number.NaN, wickY: 10, preferredSide: 'below' },
  ], { pane, ...layoutOptions })
  assert.deepEqual(laid, [])
})

test('estimates wider boxes for price and percent labels', () => {
  const openWidth = estimateSubingLabelBoxWidth('建多 1343')
  const closeWidth = estimateSubingLabelBoxWidth('清多 1485(+2.41%)')
  assert.ok(openWidth > 40)
  assert.ok(closeWidth > openWidth)
})

test('stacks rich-width labels when delta-x is within max box width', () => {
  const pane = { left: 0, top: 0, width: 500, height: 300 }
  const open = '建多 1343'
  const close = '清多 1485(+2.41%)'
  const openWidth = estimateSubingLabelBoxWidth(open)
  const closeWidth = estimateSubingLabelBoxWidth(close)
  const clusterX = Math.max(openWidth, closeWidth)
  const laid = layoutSubingStrategyLabels([
    {
      id: 'a',
      label: close,
      x: 100,
      wickY: 60,
      preferredSide: 'above',
      boxWidth: closeWidth,
      resultTone: 'profit',
    },
    {
      id: 'b',
      label: open,
      x: 100 + clusterX - 10,
      wickY: 55,
      preferredSide: 'above',
      boxWidth: openWidth,
      resultTone: null,
    },
  ], {
    pane,
    boxHeight: 18,
    gap: 4,
    stackGap: 2,
    clusterX,
  })
  assert.equal(laid.length, 2)
  assert.ok(laid.every((item) => item.side === 'above'))
  assert.equal(laid.find((item) => item.id === 'a')?.resultTone, 'profit')
  assert.ok((laid.find((item) => item.id === 'a')?.width ?? 0) >= closeWidth)
  const tops = laid.map((item) => item.top).sort((l, r) => l - r)
  assert.ok(tops[1] - tops[0] >= 18)
})
