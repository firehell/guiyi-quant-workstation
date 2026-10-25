import test from 'node:test'
import assert from 'node:assert/strict'
import { calculateThsMacdDisplay } from '../src/utils/thsMacdDisplay.ts'
import type { BarData } from '../src/types/market.ts'
const bars: BarData[] = Array.from({length: 240}, (_, i) => ({
  time: new Date(Date.UTC(2026, 0, 1, 0, i * 15)).toISOString(),
  open: 100, high: 120, low: 80, close: 100 + Math.sin(i / 5) * 10, volume: 1,
  physicalContract: 'JM2605', calculationSegmentId: 'one',
}))
test('owner MACD uses first-value EMA and double histogram', () => {
  const result = calculateThsMacdDisplay(bars)
  assert.equal(result.dif[0].value, 0)
  assert.equal(result.dea[0].value, 0)
  assert.ok(Math.abs(result.dif[1].value - (bars[1].close - 100) * (2 / 13 - 2 / 27)) < 1e-12)
  result.histogram.forEach((p, i) => assert.equal(p.value, 2 * (result.dif[i].value - result.dea[i].value)))
})
test('CROSS uses strict MA21 filter and trailing 60-bar offset', () => {
  const result = calculateThsMacdDisplay(bars)
  assert.ok(result.crosses.some(p => p.side === 'golden'))
  assert.ok(result.crosses.some(p => p.side === 'death'))
  const expected = bars.flatMap((bar, i) => {
    if (i < 20) return []
    const d = result.dif[i].value, a = result.dea[i].value
    const pd = result.dif[i - 1].value, pa = result.dea[i - 1].value
    const ma = bars.slice(i - 20, i + 1).reduce((sum, b) => sum + b.close, 0) / 21
    const amplitude = Math.max(...result.dif.slice(Math.max(0, i - 59), i + 1).map(p => Math.abs(p.value)), ...result.dea.slice(Math.max(0, i - 59), i + 1).map(p => Math.abs(p.value)))
    const offset = Math.max(amplitude * .12, .01)
    if (pd <= pa && d > a && bar.close > ma) return [{time: bar.time, value: d - offset, side: 'golden'}]
    if (pa <= pd && a > d && bar.close < ma) return [{time: bar.time, value: d + offset, side: 'death'}]
    return []
  })
  assert.deepEqual(result.crosses, expected)
})
test('prefix invariant, flat market and physical/quality resets', () => {
  const full = calculateThsMacdDisplay(bars)
  assert.deepEqual(calculateThsMacdDisplay(bars.slice(0, 90)).crosses, full.crosses.filter(p => p.time <= bars[89].time))
  assert.deepEqual(calculateThsMacdDisplay(bars.map(b => ({...b, close: 100}))).crosses, [])
  for (const identity of [{physicalContract:'JM2609'}, {calculationSegmentId:'two'}]) {
    const input = bars.map((b, i) => i < 120 ? b : {...b, ...identity})
    const reset = calculateThsMacdDisplay(input)
    assert.deepEqual(reset.dif.slice(120), calculateThsMacdDisplay(input.slice(120)).dif)
    assert.ok(!reset.crosses.some(p => p.time >= input[120].time && p.time < input[140].time))
  }
})
