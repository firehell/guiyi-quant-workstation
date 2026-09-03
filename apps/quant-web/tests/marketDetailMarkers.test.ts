import assert from 'node:assert/strict'
import test from 'node:test'

const allAlertMarkers = [
  {
    id: 'htdy-1', time: '2026-09-02T02:45:00Z', label: 'HTDY', tone: 'htdy' as const,
    position: 'belowBar' as const, shape: 'arrowUp' as const, alertRuleCode: 'htdy_original_15m' as const,
  },
  {
    id: 'subing-1', time: '2026-09-02T03:00:00Z', label: 'SuBing', tone: 'up' as const,
    position: 'aboveBar' as const, shape: 'arrowDown' as const, alertRuleCode: 'subing_ths_alert_15m_v1' as const,
  },
]

test('free never exposes strategy markers', async () => {
  const { markersForDetailView } = await import('../src/utils/marketDetailMarkers.ts')
  assert.deepEqual(markersForDetailView('free', allAlertMarkers), [])
})
