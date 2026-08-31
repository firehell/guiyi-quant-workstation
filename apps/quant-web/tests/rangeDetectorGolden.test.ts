import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { BarData } from '../src/types/market.ts'
import { calculateRangeDetectorLux } from '../src/utils/rangeDetectorLux.ts'

const fixturePath = new URL('../../../tests/fixtures/range_detector_lux_v1_golden.json', import.meta.url)
const roundingFixturePath = new URL('../../../tests/fixtures/range_detector_lux_v1_rounding_golden.json', import.meta.url)

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

test('Range Detector Web mirror uses canonical-decimal half-even rounding', () => {
  const rawFixture: unknown = JSON.parse(readFileSync(roundingFixturePath, 'utf8'))
  const fixtureRecord = recordValue(rawFixture)
  const expectedHash = stringValue(fixtureRecord.payload_sha256)
  const { payload_sha256: _payloadHash, ...payload } = fixtureRecord
  assert.equal(createHash('sha256').update(JSON.stringify(sort(payload))).digest('hex'), expectedHash)
  for (const rawCase of arrayValue(fixtureRecord.cases)) {
    const item = recordValue(rawCase)
    const name = stringValue(item.name)
    const parameters = recordValue(item.parameters)
    const expected = recordValue(item.expected)
    const bars = arrayValue(item.bars).map(toBar)
    const result = calculateRangeDetectorLux(bars, {
      sourceIdentity: stringValue(item.source_identity),
      ...toCamelParameters({
        minimum_range_length: numberValue(parameters.minimum_range_length),
        range_width_atr_multiplier: numberValue(parameters.range_width_atr_multiplier),
        range_atr_length: numberValue(parameters.range_atr_length),
        round_digits: numberValue(parameters.round_digits),
      }),
    })
    const confirmed = result.points[numberValue(expected.confirmation_index)]
    assert.equal(confirmed.snapshot?.currentUpper, numberValue(expected.current_upper), name)
    assert.equal(confirmed.snapshot?.currentLower, numberValue(expected.current_lower), name)
    assert.equal(confirmed.snapshot?.currentMid, numberValue(expected.current_mid), name)
    assert.equal(confirmed.transition?.kind, stringValue(expected.confirmation_transition), name)
    if (expected.break_index !== null) {
      const broken = result.points[numberValue(expected.break_index)]
      assert.equal(broken.snapshot?.state, stringValue(expected.break_state), name)
      assert.equal(broken.transition?.kind, stringValue(expected.break_transition), name)
    }
  }
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
function recordValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('rounding golden object expected')
  return Object.fromEntries(Object.entries(value))
}
function arrayValue(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('rounding golden array expected')
  return value
}
function stringValue(value: unknown): string {
  if (typeof value !== 'string') throw new Error('rounding golden string expected')
  return value
}
function numberValue(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('rounding golden finite number expected')
  return value
}
function toBar(value: unknown): BarData {
  const bar = recordValue(value)
  const close = numberValue(bar.close)
  return {
    time: stringValue(bar.bar_end), open: close, high: numberValue(bar.high), low: numberValue(bar.low), close, volume: 1,
  }
}
