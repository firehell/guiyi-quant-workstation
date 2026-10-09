import assert from 'node:assert/strict'
import test from 'node:test'
import { newowMessageChartQuery, newowMessageStrategies, type NewowMessage } from '../src/api/newowMessages.ts'
import { parseMarketDetailRoute } from '../src/utils/marketDetailRoute.ts'
import { recordingPointLabel } from '../src/utils/newowRecording.ts'
test('all four independent strategies navigate to their own three periods', () => {
  for (const strategy of newowMessageStrategies) for (const frequency of ['1w', '1d', '60m'] as const) {
    const query = newowMessageChartQuery({ symbol: 'jm', strategy: strategy.value, frequency } as NewowMessage)
    assert.equal(query.strategy, strategy.value === 'dual_fusion' ? 'trend' : strategy.value)
    assert.equal(query.frequency, frequency)
    assert.equal(parseMarketDetailRoute(query).kind, 'valid')
    assert.equal(query.newow_mode, strategy.value === 'dual_fusion' ? 'dual' : undefined)
    assert.equal(query.view, 'newow')
    assert.equal(query.series_kind, 'actual_dominant')
  }
})
test('fusion close and auxiliary J are displayed distinctly', () => {
  const point = { kind: 'action', trading_day: '2026-10-09', formula_versions: ['v1'], value: { kind: 'CLOSE_LONG' } }
  assert.equal(recordingPointLabel(point), '清仓')
  assert.equal(recordingPointLabel({ ...point, kind: 'hint', value: { kind: 'J' } }), 'J 风险提示')
})

test('saved escape hint identity uses the existing public wording', () => {
  assert.equal(recordingPointLabel({ kind: 'hint', trading_day: '2026-10-09', formula_versions: ['v1'], value: { kind: 'NEWOW_ESCAPE_D2' } }), 'D2 逃顶提示')
})
