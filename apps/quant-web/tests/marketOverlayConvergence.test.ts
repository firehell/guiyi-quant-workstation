import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { MARKET_FREQUENCIES, SUBING_PUBLIC_FREQUENCIES } from '../src/types/market.ts'
import {
  RESEARCH_OVERLAY_DEFINITIONS,
  researchOverlayCapability,
} from '../src/utils/mainIndicators.ts'


test('public Market Overlay definitions expose only four retained choices', () => {
  assert.deepEqual(
    RESEARCH_OVERLAY_DEFINITIONS.map(({ id, label }) => ({ id, label })),
    [
      { id: 'none', label: '无' },
      { id: 'subing', label: '苏冰' },
      { id: 'jdj_strategy', label: '日进斗金参考回放' },
      { id: 'htdy', label: '火天大有' },
    ],
  )
})

test('HTDY retains all seven formal frequencies after Overlay convergence', () => {
  assert.deepEqual(
    RESEARCH_OVERLAY_DEFINITIONS.find(({ id }) => id === 'htdy')?.supportedFrequencies,
    MARKET_FREQUENCIES,
  )
  for (const frequency of MARKET_FREQUENCIES) {
    assert.equal(
      researchOverlayCapability('htdy', 'actual_dominant', frequency).supported,
      true,
      frequency,
    )
  }
})

test('SuBing Overlay and public Panel share the exact 5m and 15m allowlist', () => {
  assert.deepEqual(SUBING_PUBLIC_FREQUENCIES, ['5m', '15m'])
  assert.deepEqual(
    RESEARCH_OVERLAY_DEFINITIONS.find(({ id }) => id === 'subing')?.supportedFrequencies,
    SUBING_PUBLIC_FREQUENCIES,
  )
  for (const frequency of MARKET_FREQUENCIES) {
    assert.equal(
      researchOverlayCapability('subing', 'actual_dominant', frequency).supported,
      SUBING_PUBLIC_FREQUENCIES.includes(frequency as '5m' | '15m'),
      frequency,
    )
  }
})

test('Web keeps retired N event markers and raw JDJ absent while exposing only the N range-band projection', () => {
  const typesSource = read('../src/types/market.ts')
  const apiSource = read('../src/api/market.ts')
  const markerSource = read('../src/utils/historicalResearchMarkers.ts')
  const loaderSource = read('../src/composables/useHistoricalResearchMarkers.ts')

  for (const retiredName of [
    'NStructureHistoricalRequest',
    'NStructureHistoricalEvent',
    'NStructureHistoricalResponse',
    'JdjHistoricalRequest',
    'JdjHistoricalEvent',
    'JdjHistoricalResponse',
    'getNStructureHistoricalEvents',
    'getJdjHistoricalEvents',
    'nStructureHistoricalEventToMarker',
    'jdjHistoricalEventToMarker',
    'fetchNStructure',
    'fetchJdj:',
  ]) {
    assert.equal(
      [typesSource, apiSource, markerSource, loaderSource].some((source) => source.includes(retiredName)),
      false,
      retiredName,
    )
  }

  assert.match(typesSource, /export interface JdjStrategyHistoricalResponse/)
  assert.match(apiSource, /export function getJdjStrategyHistoricalActions/)
  assert.match(markerSource, /export function jdjStrategyActionToMarker/)
  assert.match(loaderSource, /fetchJdjStrategy/)
  assert.match(typesSource, /export interface NStructureBandResponse/)
  assert.match(apiSource, /export function getNStructureBands/)
})

test('Web exposes Strategy V1 facts while the retired SuBing single-signal seam stays absent', () => {
  const typesSource = read('../src/types/market.ts')
  const apiSource = read('../src/api/market.ts')
  const markerSource = read('../src/utils/historicalResearchMarkers.ts')
  const loaderSource = read('../src/composables/useHistoricalResearchMarkers.ts')
  const sidebarSource = read('../src/components/market/ProductCheckSidebar.vue')

  for (const retiredName of [
    'SubingHistoricalSignal',
    'getSubingHistoricalSignals',
    'historicalResearchEventToMarker',
    'subingMarkerDedupeKey',
    '/subing/history',
  ]) {
    assert.equal(
      [typesSource, apiSource, markerSource, loaderSource].some((source) => source.includes(retiredName)),
      false,
      retiredName,
    )
  }

  assert.match(typesSource, /export interface SubingStrategyHistoricalResponse/)
  assert.match(apiSource, /export function getSubingStrategyHistory/)
  assert.match(markerSource, /export function subingStrategyActionToMarker/)
  assert.match(loaderSource, /subingStrategyEpisodes/)
  assert.match(sidebarSource, /:strategy-episodes="subingStrategyEpisodes"/)
})

test('visible product copy uses the single approved SuBing and JDJ replay names', () => {
  const sidebarSource = read('../src/components/market/ProductCheckSidebar.vue')
  const subingPanelSource = read('../src/components/market/SubingPanel.vue')

  assert.match(sidebarSource, /<strong>日进斗金参考回放 · Reference only<\/strong>/)
  assert.doesNotMatch(sidebarSource, /日进斗金策略/)
  assert.doesNotMatch(subingPanelSource, />SuBing</)
  assert.match(subingPanelSource, />苏冰</)
  assert.match(
    subingPanelSource,
    /苏冰公开当前观察仅支持 5m \/ 15m；D1 \/ 60m 请查看每日观察。/,
  )
  assert.doesNotMatch(subingPanelSource, /仅支持 5m \/ 15m \/ 1d/)
})

function read(path: string): string {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}
