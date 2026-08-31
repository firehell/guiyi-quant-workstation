import assert from 'node:assert/strict'
import test from 'node:test'

import {
  RANGE_DETECTOR_PRIMITIVE_STYLE,
  rangeDetectorDrawCommands,
} from '../src/components/kline/rangeDetectorPrimitive.ts'
import type { RangeDetectorVisualRange } from '../src/utils/rangeDetectorLux.ts'

const range: RangeDetectorVisualRange = {
  key: 'range-1:1',
  rangeId: 'range-1',
  revision: 1,
  visualStartAt: '2026-01-01T00:00:00Z',
  detectionRightAt: '2026-01-01T01:00:00Z',
  levelsActiveFrom: '2026-01-01T01:00:00Z',
  levelsActiveUntil: null,
  confirmedAt: '2026-01-01T01:00:00Z',
  upper: 110,
  lower: 90,
  mid: 100,
  state: 'broken_up',
  brokenAt: '2026-01-01T02:00:00Z',
}

const coordinates = new Map([
  ['2026-01-01T00:00:00Z', 10],
  ['2026-01-01T01:00:00Z', 20],
  ['2026-01-01T02:00:00Z', 30],
  ['2026-01-01T03:00:00Z', 40],
])

test('draw commands keep pre-break levels intact and color only broken_at onward as broken', () => {
  const commands = rangeDetectorDrawCommands(
    [range],
    '2026-01-01T03:00:00Z',
    (time) => coordinates.get(time) ?? null,
    (price) => price,
  )
  const upper = commands.filter((command) => command.kind === 'upper')
  const mid = commands.filter((command) => command.kind === 'mid')

  assert.deepEqual(upper.map((command) => [command.fromX, command.toX, command.color]), [
    [20, 30, RANGE_DETECTOR_PRIMITIVE_STYLE.rangeIntact],
    [30, 40, RANGE_DETECTOR_PRIMITIVE_STYLE.rangeBrokenUp],
  ])
  assert.deepEqual(mid.map((command) => command.dashed), [true, true])
  assert.deepEqual(commands.find((command) => command.kind === 'box'), {
    kind: 'box',
    fromX: 10,
    toX: 20,
    topY: 110,
    bottomY: 90,
    color: RANGE_DETECTOR_PRIMITIVE_STYLE.rangeFill,
    dashed: false,
  })
})

test('active levels terminate at levels_active_until and omit commands with missing coordinates', () => {
  const bounded = { ...range, state: 'intact' as const, brokenAt: null, levelsActiveUntil: '2026-01-01T02:00:00Z' }
  const commands = rangeDetectorDrawCommands(
    [bounded],
    '2026-01-01T03:00:00Z',
    (time) => coordinates.get(time) ?? null,
    (price) => price,
  )
  assert.ok(commands.filter((command) => command.kind === 'upper').every((command) => command.toX === 30))

  const missing = rangeDetectorDrawCommands(
    [bounded],
    '2026-01-01T03:00:00Z',
    (time) => time === bounded.levelsActiveUntil ? null : coordinates.get(time) ?? null,
    (price) => price,
  )
  assert.equal(missing.some((command) => command.kind === 'upper' || command.kind === 'lower' || command.kind === 'mid'), false)
})
