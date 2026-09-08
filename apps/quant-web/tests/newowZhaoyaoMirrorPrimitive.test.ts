import assert from 'node:assert/strict'
import test from 'node:test'

import {
  NEWOW_ZHAOYAO_MIRROR_STYLE,
  NewowZhaoyaoMirrorPrimitive,
  buildNewowZhaoyaoMirrorData,
  buildNewowZhaoyaoMirrorCommands,
  type NewowZhaoyaoMirrorDatum,
} from '../src/components/market/detail/newow/newowZhaoyaoMirrorPrimitive.ts'

test('primitive draw is inactive when initially empty, after clear, and after detach', () => {
  const primitive = new NewowZhaoyaoMirrorPrimitive()
  let mediaDraws = 0
  let strokes = 0
  const context = {
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, fillRect() {}, closePath() {}, fill() {}, fillText() {}, setLineDash() {},
    stroke() { strokes += 1 },
  }
  const target = { useMediaCoordinateSpace(callback: (scope: { context: object; mediaSize: { width: number; height: number } }) => void) {
    mediaDraws += 1; callback({ context, mediaSize: { width: 100, height: 200 } })
  } }
  primitive.attached({ chart: { timeScale: () => ({ timeToCoordinate: () => 50 }) }, requestUpdate() {}, series: {} } as never)
  const renderer = primitive.paneViews()[0]!.renderer()!
  renderer.draw(target as never)
  assert.deepEqual({ mediaDraws, strokes }, { mediaDraws: 0, strokes: 0 })

  primitive.setData([rows[0]!]); renderer.draw(target as never)
  assert.equal(mediaDraws, 1); assert.ok(strokes > 0)
  const afterNonEmpty = strokes

  primitive.setData([]); renderer.draw(target as never)
  assert.deepEqual({ mediaDraws, strokes }, { mediaDraws: 1, strokes: afterNonEmpty })

  primitive.setData([rows[0]!]); primitive.detached(); renderer.draw(target as never)
  assert.deepEqual({ mediaDraws, strokes }, { mediaDraws: 1, strokes: afterNonEmpty })
})

test('joins split physical segments by global index in one detached mirror row set', () => {
  const series = [
    { key: 'entry', points: [{ index: 0, time: 'a' as never, value: 1 }] },
    { key: 'entry', points: [{ index: 2, time: 'c' as never, value: 3 }] },
    { key: 'markup', points: [{ index: 0, time: 'a' as never, value: 4 }] },
    { key: 'caution', points: [{ index: 2, time: 'c' as never, value: 50 }] },
  ]
  assert.deepEqual(buildNewowZhaoyaoMirrorData(series), [
    { time: 'a', entry: 1, wash: 0, distribution: 0, markup: 4, exit: 0, inducement: 0, caution: 0 },
    { time: 'c', entry: 3, wash: 0, distribution: 0, markup: 0, exit: 0, inducement: 0, caution: 50 },
  ])
})

const rows: NewowZhaoyaoMirrorDatum[] = [
  { time: 'a' as never, entry: 10, wash: 5, distribution: 8, markup: 20, exit: 7, inducement: 100, caution: 0 },
  { time: 'b' as never, entry: 4, wash: 3, distribution: 4, markup: 10, exit: 2, inducement: 5, caution: 50 },
  { time: 'c' as never, entry: 999, wash: 0, distribution: 999, markup: 0, exit: 0, inducement: 0, caution: 0 },
]

test('projects the frozen six classes with original colors, layering and 48/52 split', () => {
  const commands = buildNewowZhaoyaoMirrorCommands(rows, 100, 200, time => ({ a: 20, b: 60, c: 140 }[time as string] ?? null))
  assert.equal(commands.zeroY, 94)
  assert.equal(commands.barWidth, 26)
  assert.deepEqual(commands.items.map(item => [item.kind, item.color]), [
    ['zero', NEWOW_ZHAOYAO_MIRROR_STYLE.zero],
    ['entry', '#ff3b30'], ['markup', '#ffcc00'], ['entry', '#ff3b30'], ['markup', '#ffcc00'],
    ['wash', '#34c759'], ['distribution', '#007aff'], ['wash', '#34c759'], ['distribution', '#007aff'],
    ['exit', '#0066bb'], ['inducement', '#ff8800'], ['exit', '#0066bb'], ['inducement', '#ff8800'],
    ['caution', '#00FF00'],
  ])
  assert.equal(commands.items.find(item => item.kind === 'entry')!.fromY, 85.6, 'inducement unusually participates in upper scaling')
  assert.equal(commands.items.find(item => item.kind === 'markup')!.toY, 185, 'lower scaling uses markup/distribution only')
  assert.equal(commands.items.some(item => item.kind === 'peak' as never), false, 'original star markers remain hidden')
})

test('visible-window scaling ignores offscreen values and keeps dashed stems/caution geometry', () => {
  const commands = buildNewowZhaoyaoMirrorCommands(rows, 100, 200, time => ({ a: -20, b: 50, c: 120 }[time as string] ?? null))
  const entry = commands.items.find(item => item.kind === 'entry')!
  const exit = commands.items.find(item => item.kind === 'exit')!
  const inducement = commands.items.find(item => item.kind === 'inducement')!
  const caution = commands.items.find(item => item.kind === 'caution')!
  assert.ok(Math.abs(entry.fromY - 26.8) < 1e-9)
  assert.deepEqual(exit.dash, [2, 2]); assert.deepEqual(inducement.dash, [2, 2])
  assert.equal(caution.text, '小 心'); assert.deepEqual(caution.dash, [3, 3])
  assert.equal(commands.items.some(item => item.x === -20 || item.x === 120), false)
})
