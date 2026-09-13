import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const fixture = JSON.parse(readFileSync(new URL('../../../services/quant-api/tests/newow/fixtures/trend-channel-v3.2.82-30-bars.json', import.meta.url), 'utf8')) as {
  source: {
    product_version: string
    stock_detail_sha256: string
    strategy_calc_sha256: string
    upper_expression: string
    lower_expression: string
  }
  bars: Array<[string, string, string, string, number]>
  expected: Array<[string, string]>
}

test('frozen v3.2.82 JavaScript HHV10/LLV10 matches all 30 page values', () => {
  assert.deepEqual(fixture.source, {
    product_version: 'v3.2.82',
    stock_detail_sha256: 'cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9',
    strategy_calc_sha256: '80dcfa39afe5511b073ec66858e697243a3e4e994cd610a00568e602610a6192',
    upper_expression: 'HHV(high,10)',
    lower_expression: 'LLV(low,10)',
  })
  const actual = fixture.bars.map((_bar, index): [string, string] => {
    const window = fixture.bars.slice(Math.max(0, index - 9), index + 1)
    return [
      String(Math.max(...window.map((bar) => Number(bar[1])))),
      String(Math.min(...window.map((bar) => Number(bar[2])))),
    ]
  })

  assert.deepEqual(actual, fixture.expected)
})
