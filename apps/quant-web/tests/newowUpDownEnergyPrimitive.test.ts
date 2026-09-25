import assert from 'node:assert/strict'
import test from 'node:test'

import {
  NEWOW_UP_DOWN_ENERGY_STYLE,
  buildNewowUpDownEnergyCommands,
  buildNewowUpDownEnergyData,
} from '../src/components/market/detail/newow/newowUpDownEnergyPrimitive.ts'

test('energy steps use server VAR4, same-owner close versus MA10, and never cross a segment', () => {
  const point = (index: number, segmentId: string, value: number) => ({ index, segmentId, physicalContract: segmentId,
    barEnd: `2026-09-${index + 1}`, time: `${segmentId}-${index}` as never, value })
  const series = [
    { key: 'var4', points: [point(0, 'a', 30), point(1, 'a', 45), point(2, 'b', 20)] },
    { key: 'ma10', points: [point(0, 'a', 100), point(1, 'a', 100), point(2, 'b', 100)] },
    { key: 'band_entry', points: [point(1, 'a', 80)] },
    { key: 'rebound_entry', points: [point(1, 'a', 80)] },
  ]
  const bars = [
    { barEnd: '2026-09-1', physicalContract: 'a', segmentId: 'a', close: 99 },
    { barEnd: '2026-09-2', physicalContract: 'a', segmentId: 'a', close: 101 },
    { barEnd: '2026-09-3', physicalContract: 'b', segmentId: 'b', close: 90 },
  ]
  const data = buildNewowUpDownEnergyData(series, bars)
  assert.deepEqual(data.map(row => [row.previous, row.risingColor, row.signal]), [
    [null, false, null], [30, true, 'band'], [null, false, null],
  ])
  const commands = buildNewowUpDownEnergyCommands(data, 100, 125, time => ({ 'a-0': 10, 'a-1': 20, 'b-2': 30 }[time as string] ?? null))
  assert.deepEqual(commands.map(item => [item.kind, item.color]), [
    ['reference', NEWOW_UP_DOWN_ENERGY_STYLE.reference], ['step', NEWOW_UP_DOWN_ENERGY_STYLE.up],
    ['signal', NEWOW_UP_DOWN_ENERGY_STYLE.band],
  ])
  assert.equal(commands[0]!.fromY, 91, 'reference line is VAR4=50 on the fixed -5..105 scale')
  assert.equal(commands[2]!.text, '波段')
  assert.ok(commands[2]!.fromY > 60, 'signal label and triangle clear the two-row toolbar')
  const tallerToolbar = buildNewowUpDownEnergyCommands(data, 100, 180, time => ({ 'a-0': 10, 'a-1': 20, 'b-2': 30 }[time as string] ?? null), 96)
  assert.equal(tallerToolbar[2]!.fromY, 98, 'the signal follows a taller measured toolbar')
})

test('nearby signal labels occupy alternating heights when the chart is compressed', () => {
  const data = [10, 20, 30].map((index) => ({
    index, segmentId: 'a', time: index as never, value: 50, previous: null,
    risingColor: true, signal: 'band' as const,
  }))
  const signals = buildNewowUpDownEnergyCommands(data, 100, 200, time => Number(time))
    .filter(item => item.kind === 'signal')
  assert.deepEqual(signals.map(item => item.fromY), [74, 91, 74])
})
