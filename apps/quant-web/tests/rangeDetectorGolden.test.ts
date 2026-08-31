import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { BarData } from '../src/types/market.ts'
import { calculateRangeDetectorLux } from '../src/utils/rangeDetectorLux.ts'

const fixturePath = new URL('../../../tests/fixtures/range_detector_lux_v1_golden.json', import.meta.url)

test('Range Detector Web mirror matches the shared Python golden and canonical hash', () => {
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'))
  const { payload_sha256: expectedHash, ...payload } = fixture
  assert.equal(createHash('sha256').update(JSON.stringify(sort(payload))).digest('hex'), expectedHash)
  const bars: BarData[] = fixture.bars.map((bar: Record<string, unknown>) => ({
    time: bar.bar_end as string, trading_day: bar.trading_day as string, open: bar.close as number,
    high: bar.high ?? Number.NaN, low: bar.low ?? Number.NaN, close: bar.close as number, volume: 1,
  }))
  const result = calculateRangeDetectorLux(bars, { sourceIdentity: fixture.source_identity, ...toCamelParameters(fixture.parameters) })
  assert.deepEqual(toSnake(result), fixture.expected)
})

function toCamelParameters(parameters: Record<string, number>) {
  return { minimumRangeLength: parameters.minimum_range_length, rangeWidthAtrMultiplier: parameters.range_width_atr_multiplier, rangeAtrLength: parameters.range_atr_length, roundDigits: parameters.round_digits }
}
function toSnake(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(toSnake)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value)
    .filter(([key]) => key !== 'key')
    .map(([key, item]) => [key === 'time' ? 'bar_end' : key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`), toSnake(item)]))
}
function sort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sort)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, sort(item)]))
}
