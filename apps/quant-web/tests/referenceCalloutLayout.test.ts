import assert from 'node:assert/strict'
import test from 'node:test'

import { layoutReferenceCallouts, layoutNiuwaReferenceCallouts, REFERENCE_CALLOUT_BOX } from '../src/utils/referenceCalloutLayout.ts'

const callout = (id: string, above = false) => ({
  id, time: `2026-09-14T0${Number(id) % 9}:00:00Z`, physicalContract: 'AU2610',
  price: '449.320000000000000000', title: '参考建仓', detail: '449.32 · +66.67%',
  tone: 'gain' as const, above,
})

test('uses the compact reference-label footprint approved for dense chart overlays', () => {
  assert.deepEqual(REFERENCE_CALLOUT_BOX, { width: 96, height: 38 })
})

test('dense corner layout keeps every identity inside the main pane without box collisions', () => {
  const points = Array.from({ length: 18 }, (_, index) => ({
    x: index < 9 ? 4 + index : 382 - index,
    y: index % 2 ? 5 : 212,
    callout: callout(String(index), index % 2 === 0),
    boxWidth: 168,
    boxHeight: 52,
  }))
  const result = layoutReferenceCallouts(points, 390, 220)
  assert.equal(result.length, points.length)
  assert.deepEqual(result.map(item => item.callout.id), [...result].map(item => item.callout.id), 'order is deterministic')
  for (const item of result) {
    assert.ok(item.left >= 2 && item.top >= 2)
    assert.ok(item.left + item.width <= 388)
    assert.ok(item.top + item.height <= 218)
  }
  assertNoOverlap(result)
})

test('selected compact node expands with priority and remains connected to its anchor', () => {
  const points = Array.from({ length: 10 }, (_, index) => ({
    x: 100 + index,
    y: 80,
    callout: callout(String(index)),
    boxWidth: 168,
    boxHeight: 52,
    expanded: index === 7,
  }))
  const result = layoutReferenceCallouts(points, 360, 180)
  const selected = result.find(item => item.callout.id === '7')!
  assert.equal(selected.compact, false)
  assert.equal(selected.width, 168)
  assert.ok(selected.lineX >= selected.left && selected.lineX <= selected.left + selected.width)
  assert.ok(selected.lineY >= selected.top && selected.lineY <= selected.top + selected.height)
  assertNoOverlap(result)
})

test('layout is stable across repeated calls and narrow panes use focusable compact nodes', () => {
  const points = Array.from({ length: 8 }, (_, index) => ({ x: 30 + index, y: 60, callout: callout(String(index)) }))
  const first = layoutReferenceCallouts(points, 190, 160)
  assert.deepEqual(first, layoutReferenceCallouts(points, 190, 160))
  assert.ok(first.some(item => item.compact))
  assertNoOverlap(first)
})

test('dense layouts retain every visible action and never project outside a tiny pane', () => {
  const points = Array.from({ length: 500 }, (_, index) => ({ x: 100, y: 100, callout: callout(String(index)) }))
  const dense = layoutReferenceCallouts(points, 390, 220)
  assert.equal(dense.length, points.length)
  assertNoOverlap(dense)

  const tiny = layoutReferenceCallouts([{ x: 10, y: 10, callout: callout('tiny') }], 25, 25)
  assert.equal(tiny.length, 1)
  assert.ok(tiny[0]!.left >= 2 && tiny[0]!.top >= 2)
  assert.ok(tiny[0]!.left + tiny[0]!.width <= 23)
  assert.ok(tiny[0]!.top + tiny[0]!.height <= 23)
})

function assertNoOverlap(items: ReturnType<typeof layoutReferenceCallouts>): void {
  for (let left = 0; left < items.length; left += 1) {
    for (let right = left + 1; right < items.length; right += 1) {
      const a = items[left]!
      const b = items[right]!
      assert.ok(a.left + a.width <= b.left || b.left + b.width <= a.left || a.top + a.height <= b.top || b.top + b.height <= a.top, `${a.callout.id} overlaps ${b.callout.id}`)
    }
  }
}

test('Niuwa placement searches near anchors and avoids the signal candle', () => {
  const point = { x: 200, y: 100, callout: callout('1'), boxWidth: 96, boxHeight: 30,
    candle: { left: 190, top: 60, width: 20, height: 50 } }
  const result = layoutNiuwaReferenceCallouts([point], 500, 300)
  assert.equal(result.length, 1)
  assert.ok(result[0]!.top + 30 < 60 || result[0]!.left + 96 < 190 || result[0]!.left > 210)
  assert.ok(Math.hypot(result[0]!.left + 48 - 200, result[0]!.top + 15 - 100) <= 170)
})

test('Niuwa density layout omits crowded text then restores it on zoom without merging identities', () => {
  const points = Array.from({ length: 10 }, (_, i) => ({x: 200+i, y: 140, callout: callout(String(i)), boxWidth: 96, boxHeight: 30}))
  const dense = layoutNiuwaReferenceCallouts(points, 500, 300)
  assert.ok(dense.length < points.length)
  assertNoOverlap(dense)
  assert.ok(dense.every(item => !item.compact && points.some(point => point.callout.id === item.callout.id)))
  const zoomed = layoutNiuwaReferenceCallouts(points.map((point,i)=>({...point,x:80+i*130})), 1500, 300)
  assert.equal(zoomed.length, points.length)
  assert.deepEqual(dense, layoutNiuwaReferenceCallouts(points, 500, 300))
})

test('Niuwa callouts preserve their anchors while avoiding a breakout price label', () => {
  const area = { left: 390, top: 128, width: 110, height: 44 }
  const result = layoutNiuwaReferenceCallouts([{ x: 455, y: 150, callout: callout('breakout'), boxWidth: 96, boxHeight: 30 }], 500, 300, [area])
  assert.equal(result.length, 1)
  const placed = result[0]!
  assert.equal(placed.x, 455)
  assert.equal(placed.y, 150)
  assert.ok(placed.left + placed.width < area.left || placed.left > area.left + area.width || placed.top + placed.height < area.top || placed.top > area.top + area.height)
})

test('generic same-bar reversals retain both full action labels at normal density', () => {
  const points = [false, true].map((above, index) => ({ x: 210, y: 120, callout: { ...callout(`reverse-${index}`), above }, boxWidth: 112, boxHeight: 28 }))
  const result = layoutNiuwaReferenceCallouts(points, 500, 300, [], true)
  assert.equal(result.length, 2)
  assert.ok(result.every(item => !item.compact))
  assertNoOverlap(result)
})
test('generic mobile crowding preserves every reversal identity as full label or compact node', () => {
  const points = Array.from({ length: 80 }, (_, index) => ({ x: 195, y: 110, callout: { ...callout(`pair-${index}`), above: index % 2 === 0 }, boxWidth: 126, boxHeight: 28 }))
  const result = layoutNiuwaReferenceCallouts(points, 390, 220, [], true)
  assert.equal(result.length, points.length)
  assert.equal(new Set(result.map(item => item.callout.id)).size, points.length)
  assert.ok(result.some(item => item.compact))
  assert.ok(result.every(item => item.left >= 2 && item.top >= 2 && item.left + item.width <= 388 && item.top + item.height <= 218))
})
