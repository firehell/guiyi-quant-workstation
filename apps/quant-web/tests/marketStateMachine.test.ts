import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildEmaObservationStatus,
  buildMarketChartRouteQuery,
  isResearchProfileRequired,
  LIVE_INDICATOR_CONTEXT_PENDING_MESSAGE,
  qualityFailedObservationText,
  RESEARCH_PROFILE_REQUIRED_MESSAGE,
  safeMarketApiError,
  TECHNICAL_OBSERVATION_PREFIX,
} from '../src/utils/marketChartQuery.ts'

describe('marketStateMachine', () => {
  it('builds route query with symbol/contract/period and deep-link fields', () => {
    const query = buildMarketChartRouteQuery(
      {
        symbol: 'jm',
        actualContract: 'JM2609',
        period: '15m',
        contractView: 'actual',
        profileId: 'intraday_research_v1',
        accessMode: 'research',
        dataMode: 'historical',
      },
      {
        report_id: '42',
        trade_no: 'T-001',
        strategy: 'su_bing_v1',
      },
    )
    assert.equal(query.symbol, 'jm')
    assert.equal(query.contract, 'JM2609')
    assert.equal(query.period, '15m')
    assert.equal(query.contract_view, undefined)
    assert.equal(query.profile_id, 'intraday_research_v1')
    assert.equal(query.access_mode, 'research')
    assert.equal(query.data_mode, undefined)
    assert.equal(query.report_id, '42')
    assert.equal(query.trade_no, 'T-001')
    assert.equal(query.strategy, 'su_bing_v1')
  })

  it('persists contract_view and live data_mode when non-default', () => {
    const query = buildMarketChartRouteQuery(
      {
        symbol: 'jm',
        actualContract: 'JM2609',
        period: '15m',
        contractView: 'continuous',
        profileId: null,
        accessMode: 'browser',
        dataMode: 'live',
      },
      {},
    )
    assert.equal(query.contract_view, 'continuous')
    assert.equal(query.data_mode, 'live')
    assert.equal(query.access_mode, undefined)
    assert.equal(query.profile_id, undefined)
  })

  it('fail-closed when research mode lacks profile', () => {
    assert.equal(isResearchProfileRequired('research', 'historical', null), true)
    assert.equal(isResearchProfileRequired('research', 'historical', ''), true)
    assert.equal(isResearchProfileRequired('research', 'historical', 'profile_v1'), false)
    assert.equal(isResearchProfileRequired('research', 'live', null), false)
    assert.equal(isResearchProfileRequired('browser', 'historical', null), false)
    assert.equal(RESEARCH_PROFILE_REQUIRED_MESSAGE.includes('Profile'), true)
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

  it('live indicator pending message avoids frontend merge claim', () => {
    assert.match(LIVE_INDICATOR_CONTEXT_PENDING_MESSAGE, /待服务端/)
    assert.equal(LIVE_INDICATOR_CONTEXT_PENDING_MESSAGE.includes('StrategySignal'), false)
  })
})
