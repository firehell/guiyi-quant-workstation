import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { MARKET_FREQUENCIES } from '../src/types/market.ts'
import { RESEARCH_OVERLAY_DEFINITIONS, researchOverlayCapability } from '../src/utils/mainIndicators.ts'

test('the Web exposes only the strategy-free and HTDY overlay choices', () => {
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS.map((item) => item.id), ['none', 'htdy'])
  for (const frequency of MARKET_FREQUENCIES) {
    assert.equal(researchOverlayCapability('htdy', 'actual_dominant', frequency).supported, true)
  }
})

test('market source surface has no strategy history or action marker API', () => {
  const marketApi = readFileSync(new URL('../src/api/market.ts', import.meta.url), 'utf-8')
  const chart = readFileSync(new URL('../src/pages/market/chart.vue', import.meta.url), 'utf-8')
  assert.doesNotMatch(marketApi, /strategy.*history|strategy.*current/i)
  assert.doesNotMatch(chart, /action[-_ ]?marker|build.*clear/i)
})
