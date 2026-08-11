import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { BarData } from '../src/types/market.ts'
import { calculateHuoTianDaYou } from '../src/utils/indicators.ts'
import { HTDY_WEB_OBSERVATION_METADATA } from '../src/utils/mainIndicators.ts'

interface Step1Golden {
  bars: Array<{ datetime: string; open: number; high: number | null; low: number | null; close: number; volume: number }>
  expected: {
    outputs: {
      zk1: Array<number | null>
      zd1: Array<number | null>
      zd2: Array<number | null>
      yellow_candle: boolean[]
      white_candle: boolean[]
      buy_observation: boolean[]
      sell_observation: boolean[]
      observation_conflict: boolean[]
    }
    metadata: Record<string, unknown>
  }
  payload_sha256: string
}

const fixturePath = new URL('./fixtures/htdy_original_realtime_v1_golden.json', import.meta.url)

test('HTDY Web exact output agrees with the tracked Step 1 production golden', () => {
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as Step1Golden
  const bars: BarData[] = fixture.bars.map((bar) => ({
    ...bar,
    high: bar.high ?? Number.NaN,
    low: bar.low ?? Number.NaN,
    time: bar.datetime,
  }))
  const points = calculateHuoTianDaYou(bars, 25, false).points
  const payload = {
    bars: fixture.bars.map((bar) => ({ ...bar })),
    outputs: {
      zk1: points.map((point) => normalize(point.zk1)),
      zd1: points.map((point) => normalize(point.zd1)),
      zd2: points.map((point) => normalize(point.zd2)),
      yellow_candle: points.map((point) => point.yellowCandle),
      white_candle: points.map((point) => point.whiteCandle),
      buy_observation: points.map((point) => point.buyObservation),
      sell_observation: points.map((point) => point.sellObservation),
      observation_conflict: points.map((point) => point.buyObservation && point.sellObservation),
    },
    metadata: HTDY_WEB_OBSERVATION_METADATA,
  }

  assert.deepEqual(points.map((point) => point.time), fixture.bars.map((bar) => bar.datetime))
  for (const field of ['yellow_candle', 'white_candle', 'buy_observation', 'sell_observation', 'observation_conflict'] as const) {
    assert.ok(payload.outputs[field].includes(true), `golden fixture must exercise a true ${field} state`)
    assert.ok(payload.outputs[field].includes(false), `golden fixture must exercise a false ${field} state`)
  }
  assert.deepEqual(payload.bars, fixture.bars)
  assert.deepEqual(payload.outputs, fixture.expected.outputs)
  assert.deepEqual(payload.metadata, fixture.expected.metadata)
  assert.equal(canonicalHash(payload), fixture.payload_sha256)
})

function normalize(value: number | null): number | null {
  return value === null || !Number.isFinite(value) ? null : Number(value.toFixed(12))
}

function canonicalHash(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(sortValue(value))).digest('hex')
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortValue)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, item]) => [key, sortValue(item)]),
    )
  }
  return value
}
