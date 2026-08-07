import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildEmaObservationStatus,
  buildMarketChartRouteQuery,
  qualityFailedObservationText,
  safeMarketApiError,
  TECHNICAL_OBSERVATION_PREFIX,
} from '../src/utils/marketChartQuery.ts'

describe('marketStateMachine', () => {
  it('builds route query with symbol/contract/period and observation deep-link fields', () => {
    const query = buildMarketChartRouteQuery(
      {
        symbol: 'jm',
        actualContract: 'JM2609',
        period: '15m',
        contractView: 'actual',
        accessMode: 'research',
      },
      {
        strategy: 'su_bing_v1',
        time: '2026-07-10T09:15:00',
      },
    )
    assert.equal(query.symbol, 'jm')
    assert.equal(query.contract, 'JM2609')
    assert.equal(query.period, '15m')
    assert.equal(query.contract_view, undefined)
    assert.equal(query.access_mode, 'research')
    assert.equal(query.strategy, 'su_bing_v1')
    assert.equal(query.time, '2026-07-10T09:15:00')
    assert.equal(query.signal_id, undefined)
    assert.equal(query.signal_event_id, undefined)
    assert.equal(query.review_id, undefined)
    assert.equal(query.return_route, undefined)
  })

  it('persists contract_view when non-default', () => {
    const query = buildMarketChartRouteQuery(
      {
        symbol: 'jm',
        actualContract: 'JM2609',
        period: '15m',
        contractView: 'continuous',
        accessMode: 'browser',
      },
      {},
    )
    assert.equal(query.contract_view, 'continuous')
    assert.equal(query.data_mode, undefined)
    assert.equal(query.access_mode, undefined)
  })

  it('shows DataGap as an explicit fail-closed message', () => {
    const msg = safeMarketApiError(
      {
        response: {
          status: 409,
          data: {
            detail: {
              code: 'DATA_GAP',
              facts: { reason: 'catalog_coverage_missing' },
            },
          },
        },
      },
      'K 线加载失败',
    )
    assert.match(msg, /DataGap/)
    assert.match(msg, /拒绝回退/)
    assert.equal(msg.includes('catalog_coverage_missing'), false)
  })

  it('quality failed text never includes file paths', () => {
    const text = qualityFailedObservationText()
    assert.equal(text.includes('file_path'), false)
    assert.equal(text.includes('/'), false)
  })

  it('safeMarketApiError redacts paths from axios detail', () => {
    const msg = safeMarketApiError(
      {
        response: {
          status: 500,
          data: { detail: 'failed at /Volumes/扩展盘/data/raw/jm.parquet' },
        },
      },
      'K 线加载失败',
    )
    assert.equal(msg.includes('/Volumes/'), false)
    assert.match(msg, /HTTP_500/)
  })

  it('EMA observation uses technical observation language, not strategy signal', () => {
    const above = buildEmaObservationStatus(100, 90)
    assert.match(above.text, new RegExp(TECHNICAL_OBSERVATION_PREFIX))
    assert.equal(above.text.includes('entry_signal'), false)
    assert.match(above.text, /非 StrategySignal/)
    assert.equal(above.label, 'EMA21 上方')

    const below = buildEmaObservationStatus(80, 90)
    assert.equal(below.label, 'EMA21 下方')
    assert.match(below.text, /非 StrategySignal/)
  })
})
