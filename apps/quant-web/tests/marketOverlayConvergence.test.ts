import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { MARKET_FREQUENCIES, SUBING_PUBLIC_FREQUENCIES } from '../src/types/market.ts'
import {
  RESEARCH_OVERLAY_DEFINITIONS,
  researchOverlayCapability,
} from '../src/utils/mainIndicators.ts'


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

test('Web keeps the retained SuBing history/current and internal-process surfaces', () => {
  const apiSource = read('../src/api/market.ts')
  const chartSource = read('../src/pages/market/chart.vue')
  const toolbarSource = read('../src/components/market/ProductWorkspaceToolbar.vue')

  assert.match(apiSource, /export function getSubingStrategyHistory/)
  assert.match(apiSource, /timeout: 120_000/)
  assert.match(apiSource, /signal/)
  assert.match(apiSource, /export function getSubingStrategyCurrent/)
  assert.match(chartSource, /useSubingStrategyCurrent/)
  assert.match(toolbarSource, /显示苏冰内部研究过程/)
  assert.match(toolbarSource, /显示全历史策略效果/)
})

test('Web exposes Strategy V1 historical and current facts', () => {
  const typesSource = read('../src/types/market.ts')
  const apiSource = read('../src/api/market.ts')
  const markerSource = read('../src/utils/historicalResearchMarkers.ts')
  const loaderSource = read('../src/composables/useHistoricalResearchMarkers.ts')
  const sidebarSource = read('../src/components/market/ProductCheckSidebar.vue')

  assert.match(typesSource, /export interface SubingStrategyHistoricalResponse/)
  assert.match(apiSource, /export function getSubingStrategyHistory/)
  assert.match(markerSource, /export function subingStrategyActionToMarker/)
  assert.match(loaderSource, /subingStrategyEpisodes/)
  assert.doesNotMatch(sidebarSource, /:strategy-episodes="subingStrategyEpisodes"/)
})

test('visible product copy retains the approved SuBing name', () => {
  const subingPanelSource = read('../src/components/market/SubingPanel.vue')

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
