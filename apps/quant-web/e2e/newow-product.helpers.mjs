import { performance } from 'node:perf_hooks'
import richMacd from './fixtures/newow-rich-macd.json' with { type: 'json' }

export const NEWOW_AS_OF = '2026-09-03T08:00:00.000Z'
export const NEWOW_PATH = '/market/chart?symbol=rb&view=newow&strategy=trend&frequency=1d&series_kind=actual_dominant'
export const NEWOW_STRATEGIES = ['trend', 'oscillation', 'main_rise']
export const NEWOW_FREQUENCIES = ['1w', '1d', '60m']

const CONTRACT = 'RB2605'
const SEGMENT = 'rb:RB2605:2026-01-01T00:00:00+00:00'
const INITIAL_CONTRACT = 'RB2601'
const INITIAL_SEGMENT = 'rb:RB2601:2025-01-01T00:00:00+00:00'
const HASH = {
  chart: 'a'.repeat(64), reference: 'b'.repeat(64), explanation: 'c'.repeat(64),
  comparator: 'd'.repeat(64), auxiliary: 'e'.repeat(64), page: 'f'.repeat(64),
}
const MAIN_VALUES = Object.freeze({
  trend: Object.freeze({ b: '104.0000', a: '108.0000' }),
  oscillation: Object.freeze({ upper: '110.0000', lower: '102.0000' }),
  main_rise: Object.freeze({ ma35: '105.0000', ma45: '103.0000' }),
})
const STRATEGY_WIRE_FACTS = Object.freeze({
  trend: Object.freeze({
    closed: Object.freeze({ entrySuffix: 'build-closed', entryIndex: 61, entrySequence: 0, entry: '104.0000', exitSuffix: 'clear', exitIndex: 62, exitSequence: 0, exit: '109.3061', return: '5.1020' }),
    open: Object.freeze({ entrySuffix: 'build-open', entryIndex: 63, entrySequence: 0, entry: '106.0000', markBarEnd: '2026-09-03T07:00:00.000Z', markTradingDay: '2026-09-03', mark: '104.6750', change: '-1.2500' }),
    interrupted: Object.freeze({ entrySuffix: 'bi', barEnd: '2026-01-05T07:00:00.000Z', tradingDay: '2026-01-05', entrySequence: 0, entry: '88.0000', markBarEnd: '2026-01-06T07:00:00.000Z', markTradingDay: '2026-01-06', mark: '79.2000', change: '-10.0000' }),
    initial: Object.freeze({ entrySuffix: 'b0', entryBarEnd: '2025-12-15T07:00:00.000Z', entryTradingDay: '2025-12-15', entrySequence: 0, entry: '104.0000', exitSuffix: 'c0', exitBarEnd: '2025-12-31T07:00:00.000Z', exitTradingDay: '2025-12-31', exitSequence: 0, exit: '109.3061', return: '5.1020' }),
  }),
  oscillation: Object.freeze({
    closed: Object.freeze({ entrySuffix: 'build-closed', entryIndex: 61, entrySequence: 0, entry: '104.2000', exitSuffix: 'clear-same', exitIndex: 63, exitSequence: 0, exit: '109.5163', return: '5.1020' }),
    open: Object.freeze({ entrySuffix: 'build-open', entryIndex: 63, entrySequence: 1, entry: '104.3000', markBarEnd: '2026-09-03T07:00:00.000Z', markTradingDay: '2026-09-03', mark: '102.9963', change: '-1.2500' }),
    interrupted: Object.freeze({ entrySuffix: 'bi', barEnd: '2026-01-05T07:00:00.000Z', tradingDay: '2026-01-05', entrySequence: 0, entry: '88.0000', markBarEnd: '2026-01-06T07:00:00.000Z', markTradingDay: '2026-01-06', mark: '79.2000', change: '-10.0000' }),
    initial: Object.freeze({ entrySuffix: 'b0', entryBarEnd: '2025-12-15T07:00:00.000Z', entryTradingDay: '2025-12-15', entrySequence: 0, entry: '104.2000', exitSuffix: 'c0', exitBarEnd: '2025-12-31T07:00:00.000Z', exitTradingDay: '2025-12-31', exitSequence: 0, exit: '109.5163', return: '5.1020' }),
  }),
  main_rise: Object.freeze({
    closed: Object.freeze({ entrySuffix: 'build-closed', entryIndex: 61, entrySequence: 0, entry: '103.0000', exitSuffix: 'clear', exitIndex: 62, exitSequence: 0, exit: '108.2551', return: '5.1020' }),
    open: Object.freeze({ entrySuffix: 'build-open', entryIndex: 63, entrySequence: 0, entry: '105.0000', markBarEnd: '2026-09-03T07:00:00.000Z', markTradingDay: '2026-09-03', mark: '103.6875', change: '-1.2500' }),
    interrupted: Object.freeze({ entrySuffix: 'bi', barEnd: '2026-01-05T07:00:00.000Z', tradingDay: '2026-01-05', entrySequence: 0, entry: '88.0000', markBarEnd: '2026-01-06T07:00:00.000Z', markTradingDay: '2026-01-06', mark: '79.2000', change: '-10.0000' }),
    initial: Object.freeze({ entrySuffix: 'b0', entryBarEnd: '2025-12-15T07:00:00.000Z', entryTradingDay: '2025-12-15', entrySequence: 0, entry: '103.0000', exitSuffix: 'c0', exitBarEnd: '2025-12-31T07:00:00.000Z', exitTradingDay: '2025-12-31', exitSequence: 0, exit: '108.2551', return: '5.1020' }),
  }),
})

export function newowRoute(strategy = 'trend', frequency = '1d', extra = '') {
  return `/market/chart?symbol=rb&view=newow&strategy=${strategy}&frequency=${frequency}&series_kind=actual_dominant${extra}`
}

export function buildNewowFixtureEnvelopeForTest(section = 'reference', strategy = 'trend', frequency = '1d', cursor = false, locateFrom = null, options = {}) {
  const url = fixtureValidationUrl(section, strategy, frequency, cursor, locateFrom)
  const payload = envelope(url, section, strategy, frequency, options)
  validateFixtureEnvelope(payload, section, strategy, frequency, url)
  return payload
}

export function validateNewowFixtureEnvelopeForTest(payload, section = 'reference', strategy = 'trend', frequency = '1d', cursor = false, locateFrom = null, companions = {}) {
  validateFixtureEnvelope(payload, section, strategy, frequency, fixtureValidationUrl(section, strategy, frequency, cursor, locateFrom), {}, companions)
}

function fixtureValidationUrl(section, strategy, frequency, cursor, locateFrom) {
  const url = new URL('http://fixture.test/api/v1/market/newow/strategy-detail')
  for (const [key, value] of Object.entries({ product: 'rb', strategy, frequency, series_kind: 'actual_dominant', section, as_of: NEWOW_AS_OF })) url.searchParams.set(key, value)
  if (cursor && section === 'reference') {
    url.searchParams.set('performance_since', '2026-01-01')
    url.searchParams.set('performance_through', '2026-09-03')
    url.searchParams.set('history_limit', '50')
    url.searchParams.set('history_before', 'reference-page-2')
    url.searchParams.set('snapshot_token', `snapshot:${strategy}:${frequency}:fixture-revision-1`)
  }
  if (cursor && section === 'chart') {
    url.searchParams.set('from', '2026-01-01')
    url.searchParams.set('through', '2026-09-03')
    url.searchParams.set('chart_limit', '500')
    url.searchParams.set('chart_before', 'chart-page-2')
  }
  if (locateFrom !== null && section === 'chart') {
    url.searchParams.set('from', locateFrom)
    url.searchParams.set('through', locateFrom)
    url.searchParams.set('snapshot_token', `snapshot:${strategy}:${frequency}:fixture-revision-1`)
  }
  return url
}

export async function installNewowProductFixtures(page, options = {}) {
  for (const strategy of NEWOW_STRATEGIES) {
    for (const frequency of NEWOW_FREQUENCIES) validateFixtureScenario(strategy, frequency, {})
  }
  if (typeof options.longHistory === 'string') {
    const [strategy, frequency] = options.longHistory.split(':')
    validateFixtureScenario(strategy, frequency, { longHistory: options.longHistory })
  }
  const state = {
    requests: [], productRequests: [], unexpected: [], aborted: [],
    counts: new Map(), requestStartedAt: new Map(), deferred: new Map(),
  }
  page.on('requestfailed', (request) => state.aborted.push(request.url()))
  await page.addInitScript(({ frozenNow }) => {
    const NativeDate = Date
    class FrozenDate extends NativeDate {
      constructor(...args) { super(...(args.length === 0 ? [frozenNow] : args)) }
      static now() { return NativeDate.parse(frozenNow) }
    }
    window.Date = FrozenDate
    window.__newowBrowserClock = { installedAt: performance.now() }
    class FixtureWebSocket {
      static OPEN = 1
      static CLOSED = 3
      readyState = FixtureWebSocket.OPEN
      onopen = null
      onclose = null
      constructor(url) { this.url = url; queueMicrotask(() => this.onopen?.()) }
      close() { this.readyState = FixtureWebSocket.CLOSED; this.onclose?.() }
    }
    window.WebSocket = FixtureWebSocket
  }, { frozenNow: NEWOW_AS_OF })

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const startedAt = performance.now()
    if (url.origin === 'http://127.0.0.1:5182' && !url.pathname.startsWith('/api/')) return route.continue()
    state.requests.push({ url, method: request.method(), startedAt })
    if (request.method() !== 'GET') return unexpected(route, state, `non-GET ${request.method()} ${url.pathname}`)

    if (url.pathname === '/api/v1/market/newow/strategy-detail') {
      const section = url.searchParams.get('section') || 'chart'
      const strategy = url.searchParams.get('strategy') || 'trend'
      const frequency = url.searchParams.get('frequency') || '1d'
      const queryError = validateProductQuery(url, section, strategy, frequency)
      if (queryError !== null) return unexpected(route, state, queryError)
      const key = [strategy, frequency, section, url.searchParams.get('component') || '', url.searchParams.get('chart_before') || '', url.searchParams.get('history_before') || ''].join(':')
      const count = (state.counts.get(key) || 0) + 1
      state.counts.set(key, count)
      state.requestStartedAt.set(key, startedAt)
      state.productRequests.push({ url, section, strategy, frequency, key, count, startedAt })

      if (options.deferOnce === `${strategy}:${frequency}:${section}` && count === 1) {
        return new Promise((resolve) => {
          state.deferred.set(`${strategy}:${frequency}:${section}`, async () => {
            try { await route.fulfill({ json: envelope(url, section, strategy, frequency, options) }) } catch {}
            resolve()
          })
        })
      }

      if (typeof options.onProductRequest === 'function') {
        const decision = await options.onProductRequest({ route, url, section, strategy, frequency, key, count, state })
        if (decision === 'handled') return
      }
      const conflictKey = `${strategy}:${frequency}:${section}`
      const conflictAt = options.conflictAt?.[conflictKey]
      if (options.conflictAlways === conflictKey || (options.conflictOnce === conflictKey && count === 1) || (options.cursorConflictOnce === conflictKey && url.searchParams.has('history_before') && count === 1) || conflictAt === count) {
        return route.fulfill({ status: 409, json: { detail: { code: 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' } } })
      }
      if (options.busy === conflictKey) {
        return route.fulfill({ status: 429, json: { detail: { code: 'NEWOW_RESOURCE_BUSY' } } })
      }
      if (options.identityMismatch === conflictKey) {
        const payload = envelope(url, section, strategy, frequency, options)
        payload.meta.identity.frequency = frequency === '1d' ? '1w' : '1d'
        return route.fulfill({ json: payload })
      }
      const payload = envelope(url, section, strategy, frequency, options)
      validateFixtureEnvelope(payload, section, strategy, frequency, url, options)
      return route.fulfill({ json: payload })
    }

    if (url.pathname === '/api/v1/market/dominants') {
      return route.fulfill({ json: { items: [{ product: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: CONTRACT, dominant_mapping_date: '2026-09-03' }] } })
    }
    if (url.pathname === '/api/v1/market/research/product') return route.fulfill({ json: researchProduct() })
    if (url.pathname === '/api/v1/market/state') return route.fulfill({ json: marketState(url) })
    if (url.pathname === '/api/v1/market/bars/page') {
      if (options.genericSeries === 'pending') return new Promise(() => {})
      if (options.genericSeries === 'failed') return route.abort('failed')
      return route.fulfill({ json: genericBarsPage(url, options) })
    }
    if (url.pathname === '/api/v1/market/newow/trend-detail') {
      return route.abort('failed')
    }
    if (url.pathname === '/api/alerts/events') return route.fulfill({ json: { items: alertEvents(url) } })
    if (url.pathname.startsWith('/api/alerts/products/')) {
      const symbol = url.pathname.split('/').at(-1)
      return route.fulfill({ json: { symbol, rules: alertRules() } })
    }
    if (url.pathname === '/api/alerts/current-events') {
      return route.fulfill({ json: { status: 'ready', trading_day: '2026-09-03', items: alertEvents(url) } })
    }
    if (url.pathname === '/api/runtime/health') return route.fulfill({ json: runtimeHealth() })
    if (url.pathname === '/api/v1/market/research/home-overview') return route.fulfill({ json: homeOverview() })
    return unexpected(route, state, `${request.method()} ${url.href}`)
  })
  return state
}

function validateFixtureScenario(strategy, frequency, options) {
  const make = (section, cursor = false, locateFrom = null) => {
    const url = fixtureValidationUrl(section, strategy, frequency, cursor, locateFrom)
    const payload = envelope(url, section, strategy, frequency, options)
    validateFixtureEnvelope(payload, section, strategy, frequency, url, options)
    return { url, payload }
  }
  const charts = [make('chart'), make('chart', true)]
  for (const locateFrom of ['2025-12-15', '2025-12-31', '2026-01-05', '2026-01-06', '2026-09-03']) charts.push(make('chart', false, locateFrom))
  for (const cursor of [false, true]) {
    const reference = make('reference', cursor)
    validateFixtureEnvelope(reference.payload, 'reference', strategy, frequency, reference.url, options, { charts: charts.map((item) => item.payload) })
  }
}

function validateProductQuery(url, section, strategy, frequency) {
  const allowedBySection = {
    chart: ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'from', 'through', 'chart_limit', 'chart_before', 'snapshot_token'],
    auxiliary: ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'component', 'from', 'through', 'snapshot_token'],
    reference: ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'performance_since', 'performance_through', 'history_limit', 'history_before', 'snapshot_token'],
    explanation: ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'snapshot_token'],
    comparator: ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'snapshot_token'],
  }
  if (!Object.hasOwn(allowedBySection, section)) return `invalid Newow section ${section}`
  for (const key of ['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of']) {
    if (url.searchParams.getAll(key).length !== 1) return `missing or duplicate Newow ${key} ${url.search}`
  }
  if (url.searchParams.get('product') !== 'rb' || url.searchParams.get('series_kind') !== 'actual_dominant') return `invalid Newow identity ${url.search}`
  if (!NEWOW_STRATEGIES.includes(strategy) || !NEWOW_FREQUENCIES.includes(frequency)) return `invalid Newow combination ${strategy}/${frequency}`
  if (url.searchParams.get('as_of') !== NEWOW_AS_OF) return `unfrozen Newow as_of ${url.searchParams.get('as_of')}`
  const actual = [...url.searchParams.keys()]
  if (new Set(actual).size !== actual.length || actual.some((key) => !allowedBySection[section].includes(key))) return `unexpected Newow query ${url.search}`
  const optionalShape = actual.filter((key) => !['product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of'].includes(key)).sort().join(',')
  const allowedShapes = {
    chart: ['', 'snapshot_token', 'from,snapshot_token,through', 'chart_before,chart_limit,from,through', 'chart_before,chart_limit,from,snapshot_token,through', 'chart_limit,from,through'],
    auxiliary: ['component', 'component,snapshot_token', 'component,from,snapshot_token,through'],
    reference: ['', 'snapshot_token', 'performance_since,performance_through', 'performance_since,performance_through,snapshot_token', 'history_limit,performance_since,performance_through', 'history_before,history_limit,performance_since,performance_through,snapshot_token'],
    explanation: ['', 'snapshot_token'],
    comparator: ['', 'snapshot_token'],
  }
  if (!allowedShapes[section].includes(optionalShape)) return `invalid Newow ${section} query shape ${url.search}`
  if (section === 'auxiliary' && !['macd', 'main_force_control', 'up_down_energy', 'zhaoyao_mirror', 'cup_handle'].includes(url.searchParams.get('component'))) return `invalid auxiliary query ${url.search}`
  if (url.searchParams.has('chart_limit') && url.searchParams.get('chart_limit') !== '500') return `invalid chart limit ${url.search}`
  if (url.searchParams.has('history_limit') && url.searchParams.get('history_limit') !== '50') return `invalid reference limit ${url.search}`
  if (url.searchParams.has('chart_before') && url.searchParams.get('chart_before') !== 'chart-page-2') return `invalid chart cursor ${url.search}`
  if (url.searchParams.has('history_before') && url.searchParams.get('history_before') !== 'reference-page-2') return `invalid reference cursor ${url.search}`
  if (url.searchParams.has('snapshot_token') && url.searchParams.get('snapshot_token') !== `snapshot:${strategy}:${frequency}:fixture-revision-1`) return `invalid snapshot token ${url.search}`
  if (url.searchParams.has('performance_since') && url.searchParams.get('performance_since') !== '2026-01-01') return `invalid performance start ${url.search}`
  if (url.searchParams.has('performance_through') && url.searchParams.get('performance_through') !== '2026-09-03') return `invalid performance end ${url.search}`
  const fixtureDates = ['2025-01-01', '2025-12-15', '2025-12-31', '2026-01-01', '2026-01-05', '2026-01-06', '2026-09-03']
  if (url.searchParams.has('from') && !fixtureDates.includes(url.searchParams.get('from'))) return `invalid chart start ${url.search}`
  if (url.searchParams.has('through') && !fixtureDates.includes(url.searchParams.get('through'))) return `invalid chart end ${url.search}`
  if ((url.searchParams.has('performance_since') || url.searchParams.has('performance_through')) && section !== 'reference') return `performance query leaked into ${section}`
  if (url.searchParams.has('chart_before') && section !== 'chart') return `chart cursor leaked into ${section}`
  if (url.searchParams.has('history_before') && section !== 'reference') return `reference cursor leaked into ${section}`
  return null
}

function validateFixtureEnvelope(payload, section, strategy, frequency, url, options = {}, companions = {}) {
  if (payload.section !== section || payload.meta.identity.strategy !== strategy || payload.meta.identity.frequency !== frequency || payload.meta.as_of !== NEWOW_AS_OF) throw new Error('fixture envelope identity drift')
  const expectedToken = `snapshot:${strategy}:${frequency}:${payload.meta.data_revision_identity}`
  if (payload.meta.snapshot_token !== null && payload.meta.snapshot_token !== expectedToken) throw new Error('fixture snapshot token drift')
  const delivered = ['chart', 'auxiliary', 'reference', 'explanation', 'comparator'].filter((candidate) => payload[candidate].delivery === 'delivered')
  if (delivered.length !== 1 || delivered[0] !== section) throw new Error('fixture envelope delivery drift')
  const long = options.longHistory === `${strategy}:${frequency}`
  const facts = scenarioFacts(strategy, frequency, long)
  const buildIds = [facts.closed.entry, facts.open.entry, facts.interrupted.entry, facts.initial.entry].map((item) => item.signal_id)
  if (new Set(buildIds).size !== buildIds.length) throw new Error('fixture BUILD identities are not unique')
  const allActionIds = [...facts.standardActions, facts.interrupted.entry, facts.initial.entry, facts.initial.exit].map((item) => item.signal_id)
  if (new Set(allActionIds).size !== allActionIds.length) throw new Error('fixture Action identities are not unique')
  if (!(facts.initial.entry.trading_day < '2026-01-01') || !(facts.closed.entry.trading_day >= '2026-01-01')) throw new Error('fixture performance-window chronology drift')
  if (section === 'chart' && payload.chart.value !== null) {
    validateChartWire(payload.chart.value, strategy)
    const actionIds = payload.chart.value.actions.map((item) => item.signal_id)
    const actionIdSet = new Set(actionIds)
    for (const frame of payload.chart.value.frames) {
      if (frame.action_ids.some((id) => !actionIdSet.has(id))) throw new Error('fixture frame/action drift')
    }
    const framedIds = payload.chart.value.frames.flatMap((frame) => frame.action_ids)
    if (JSON.stringify(framedIds) !== JSON.stringify(actionIds)) throw new Error('fixture frame/action order drift')
    const locateFrom = url?.searchParams.has('snapshot_token') && !url.searchParams.has('chart_before') ? url.searchParams.get('from') : null
    let expected = facts.standardActions
    if (url?.searchParams.has('chart_before')) expected = []
    else if (locateFrom !== null) expected = [facts.interrupted.entry, facts.initial.entry, facts.initial.exit].filter((item) => item.trading_day === locateFrom)
    if (payload.chart.value.diagnostics.includes('NO_MAIN_ACTION_IS_VALID')) expected = []
    if (JSON.stringify(payload.chart.value.actions.map(actionRelation)) !== JSON.stringify(expected.map(actionRelation))) throw new Error('fixture chart Action relation drift')
  }
  if (section === 'reference' && payload.reference.value !== null) {
    validateReferenceWire(payload.reference.value, companions.charts ?? [])
    const expected = url?.searchParams.has('history_before')
      ? [facts.interrupted.trade, facts.initial.trade]
      : [facts.open.trade, ...(payload.reference.value.summary.closed_count === 0 ? [] : [facts.closed.trade])]
    if (JSON.stringify(payload.reference.value.items.map(tradeRelation)) !== JSON.stringify(expected.map(tradeRelation))) throw new Error('fixture ReferenceTrade/Action relation drift')
    if (new Set(payload.reference.value.items.map((item) => item.entry_signal_id)).size !== payload.reference.value.items.length) throw new Error('fixture reference identity drift')
    if (payload.reference.value.summary.closed_count > 0 && (payload.reference.value.summary.mean_return_pct !== facts.closed.trade.reference_return_pct || payload.reference.value.summary.sum_return_percentage_points !== facts.closed.trade.reference_return_pct)) throw new Error('fixture reference summary drift')
  }
}

function validateChartWire(chart, strategy) {
  const barsByEnd = new Map()
  const framesByEnd = new Map(chart.frames.map((frame) => [frame.bar_end, frame]))
  for (const bar of chart.bars) {
    const [open, high, low, close] = [bar.open, bar.high, bar.low, bar.close].map(Number)
    if (![open, high, low, close].every(Number.isFinite) || low > high || open < low || open > high || close < low || close > high) throw new Error('fixture OHLC contradiction')
    if (bar.completed !== true) throw new Error('fixture Bar is not completed')
    validateSegmentOwner(bar, bar.bar_end)
    if (bar.trading_day < chart.chart_from || bar.trading_day > chart.chart_through) throw new Error('fixture chart window does not contain Bar')
    barsByEnd.set(bar.bar_end, bar)
  }
  for (const actionItem of chart.actions) {
    const bar = barsByEnd.get(actionItem.bar_end)
    const frame = framesByEnd.get(actionItem.bar_end)
    if (!bar || !frame) throw new Error('fixture Action has no exact Bar/Frame')
    validateSegmentOwner(actionItem, actionItem.bar_end)
    if (actionItem.physical_contract !== bar.physical_contract || actionItem.segment_id !== bar.segment_id || actionItem.trading_day !== bar.trading_day) throw new Error('fixture Action/Bar owner drift')
    let semanticPrice
    if (strategy === 'trend') semanticPrice = frame.main_values.b
    else if (strategy === 'main_rise') semanticPrice = frame.main_values.ma45
    else semanticPrice = actionItem.kind === 'BUILD' ? bar.low : bar.high
    if (Number(actionItem.reference_price) !== Number(semanticPrice)) throw new Error('fixture main-line semantic price drift')
  }
}

function validateReferenceWire(reference, charts) {
  const chartValues = charts.map((item) => item?.chart?.value ?? item).filter(Boolean)
  const bars = chartValues.flatMap((chart) => chart.bars ?? [])
  const actions = chartValues.flatMap((chart) => chart.actions ?? [])
  for (const tradeItem of reference.items) {
    validateSegmentOwner(tradeItem, tradeItem.entry_bar_end)
    if (tradeItem.exit_bar_end !== null) validateTimestampInSegment(tradeItem.segment_id, tradeItem.exit_bar_end)
    if (tradeItem.mark_bar_end !== null) {
      validateTimestampInSegment(tradeItem.segment_id, tradeItem.mark_bar_end)
      if (bars.length > 0) {
        const markBar = bars.find((bar) => bar.bar_end === tradeItem.mark_bar_end && bar.physical_contract === tradeItem.physical_contract && bar.segment_id === tradeItem.segment_id)
        if (!markBar || markBar.completed !== true || Number(markBar.close) !== Number(tradeItem.mark_reference_price)) throw new Error('fixture Reference mark/Close drift')
      }
    }
    if (actions.length > 0) {
      const entry = actions.find((item) => item.signal_id === tradeItem.entry_signal_id)
      if (!entry || JSON.stringify([entry.bar_end, entry.sequence, entry.reference_price, entry.physical_contract, entry.segment_id]) !== JSON.stringify([tradeItem.entry_bar_end, tradeItem.entry_sequence, tradeItem.entry_reference_price, tradeItem.physical_contract, tradeItem.segment_id])) throw new Error('fixture Reference entry/Action drift')
      if (tradeItem.exit_signal_id !== null) {
        const exit = actions.find((item) => item.signal_id === tradeItem.exit_signal_id)
        if (!exit || JSON.stringify([exit.bar_end, exit.reference_price, exit.physical_contract, exit.segment_id]) !== JSON.stringify([tradeItem.exit_bar_end, tradeItem.exit_reference_price, tradeItem.physical_contract, tradeItem.segment_id])) throw new Error('fixture Reference exit/Action drift')
      }
    }
    if (tradeItem.statistics_membership === 'initial_before_window' && !(tradeItem.entry_trading_day < reference.performance_since)) throw new Error('fixture initial trade is not before performance window')
    if (tradeItem.statistics_membership === 'entry_in_window_v1' && tradeItem.entry_trading_day < reference.performance_since) throw new Error('fixture in-window trade predates performance window')
  }
}

function validateSegmentOwner(item, timestamp) {
  const parts = item.segment_id.split(':')
  if (parts.length < 4 || parts[0] !== 'rb' || parts[1] !== item.physical_contract) throw new Error('fixture segment window owner drift')
  validateTimestampInSegment(item.segment_id, timestamp)
}

function validateTimestampInSegment(segmentId, timestamp) {
  const segmentStart = segmentId.split(':').slice(2).join(':')
  if (!Number.isFinite(Date.parse(segmentStart)) || Date.parse(timestamp) < Date.parse(segmentStart)) throw new Error('fixture segment window chronology drift')
}

function actionRelation(item) {
  return [item.signal_id, item.kind, item.bar_end, item.trading_day, item.reference_price, item.sequence, item.related_build_id]
}

function tradeRelation(item) {
  return [
    item.reference_trade_id, item.status, item.entry_signal_id, item.entry_sequence, item.entry_bar_end, item.entry_trading_day, item.entry_reference_price,
    item.exit_signal_id, item.exit_bar_end, item.exit_trading_day, item.exit_reference_price, item.reference_return_pct,
    item.mark_bar_end, item.mark_reference_price, item.mark_change_pct, item.statistics_membership,
  ]
}

function unexpected(route, state, message) {
  state.unexpected.push(message)
  return route.abort('blockedbyclient')
}

function envelope(url, section, strategy, frequency, options) {
  const wrappers = {
    chart: notRequested(), auxiliary: notRequested(), reference: notRequested(),
    explanation: notRequested(), comparator: notRequested(),
  }
  let status = ready()
  let value
  if (section === 'chart') value = chartValue(url, strategy, frequency, options)
  else if (section === 'reference') value = referenceValue(url, strategy, frequency, options)
  else if (section === 'auxiliary') {
    const component = url.searchParams.get('component') || 'main_force_control'
    if (options.auxiliaryState?.[component]) {
      status = options.auxiliaryState[component]
      value = null
    } else value = auxiliaryValue(component, frequency, options, strategy)
  } else if (section === 'explanation') value = explanationValue(strategy, frequency, url.searchParams.get('as_of') || NEWOW_AS_OF)
  else value = comparatorValue(strategy, frequency, url.searchParams.get('as_of') || NEWOW_AS_OF)
  wrappers[section] = delivered(status, value)
  return { meta: meta(url, strategy, frequency, section, options), section, ...wrappers }
}

function meta(url, strategy, frequency, section, options) {
  const revision = typeof options.revision === 'function' ? options.revision({ url, section, strategy, frequency }) : options.revision || 'fixture-revision-1'
  return {
    schema_version: 'newow_product_detail_v1',
    identity: { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas(strategy) },
    as_of: url.searchParams.get('as_of') || NEWOW_AS_OF,
    read_at: '2026-09-03T08:00:01.000Z', input_content_sha256: section === 'chart' && url.searchParams.has('snapshot_token') && url.searchParams.has('from') && !url.searchParams.has('chart_before') ? 'f'.repeat(64) : HASH[section] || HASH.chart,
    data_revision_identity: revision, snapshot_token: options.tokenlessSections?.includes(section) ? null : `snapshot:${strategy}:${frequency}:${revision}`,
    reference_model_version: 'newow_marker_reference_zero_cost_v1',
    futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
  }
}

function formulas(strategy) {
  if (strategy === 'trend') return ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2']
  if (strategy === 'oscillation') return ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
  return ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
}

function scenarioFacts(strategy, frequency, long = false) {
  const literal = STRATEGY_WIRE_FACTS[strategy]
  const longOffset = long ? 416 : 0
  const closedEntryOwner = productBar(frequency, literal.closed.entryIndex + longOffset, long)
  const closedExitOwner = productBar(frequency, literal.closed.exitIndex + longOffset, long)
  const openOwner = productBar(frequency, literal.open.entryIndex + longOffset, long)
  const interruptedOwner = fixtureActionBar(strategy, 'BUILD', frequency, literal.interrupted.barEnd, literal.interrupted.tradingDay, literal.interrupted.entry)
  const interruptedMarkOwner = productBarAt(frequency, literal.interrupted.markBarEnd, literal.interrupted.markTradingDay, literal.interrupted.mark)
  const openMarkOwner = productBarAt(frequency, literal.open.markBarEnd, literal.open.markTradingDay, literal.open.mark)
  const initialEntryOwner = fixtureActionBar(strategy, 'BUILD', frequency, literal.initial.entryBarEnd, literal.initial.entryTradingDay, literal.initial.entry, INITIAL_CONTRACT, INITIAL_SEGMENT)
  const initialExitOwner = fixtureActionBar(strategy, 'CLEAR', frequency, literal.initial.exitBarEnd, literal.initial.exitTradingDay, literal.initial.exit, INITIAL_CONTRACT, INITIAL_SEGMENT)
  const closedEntry = action(id(strategy, frequency, literal.closed.entrySuffix), 'BUILD', closedEntryOwner, literal.closed.entry, literal.closed.entrySequence)
  const closedExit = action(id(strategy, frequency, literal.closed.exitSuffix), 'CLEAR', closedExitOwner, literal.closed.exit, literal.closed.exitSequence, closedEntry.signal_id)
  const openEntry = action(id(strategy, frequency, literal.open.entrySuffix), 'BUILD', openOwner, literal.open.entry, literal.open.entrySequence)
  const interruptedEntry = action(id(strategy, frequency, literal.interrupted.entrySuffix), 'BUILD', interruptedOwner, literal.interrupted.entry, literal.interrupted.entrySequence)
  const initialEntry = action(id(strategy, frequency, literal.initial.entrySuffix), 'BUILD', initialEntryOwner, literal.initial.entry, literal.initial.entrySequence)
  const initialExit = action(id(strategy, frequency, literal.initial.exitSuffix), 'CLEAR', initialExitOwner, literal.initial.exit, literal.initial.exitSequence, initialEntry.signal_id)
  return Object.freeze({
    standardActions: Object.freeze([closedEntry, closedExit, openEntry]),
    closed: Object.freeze({ entry: closedEntry, exit: closedExit, trade: trade(id(strategy, frequency, 'closed'), strategy, frequency, closedEntryOwner, closedExitOwner, 'CLOSED', literal.closed.return, null, closedEntry.signal_id, closedEntry.sequence, literal.closed.entry, closedExit.signal_id, literal.closed.exit, null, null) }),
    open: Object.freeze({ entry: openEntry, mark: openMarkOwner, trade: trade(id(strategy, frequency, 'open'), strategy, frequency, openOwner, null, 'OPEN', null, literal.open.change, openEntry.signal_id, openEntry.sequence, literal.open.entry, null, null, openMarkOwner, literal.open.mark) }),
    interrupted: Object.freeze({ entry: interruptedEntry, mark: interruptedMarkOwner, trade: trade(id(strategy, frequency, 'interrupted'), strategy, frequency, interruptedOwner, null, 'ROLLOVER_INTERRUPTED', null, literal.interrupted.change, interruptedEntry.signal_id, interruptedEntry.sequence, literal.interrupted.entry, null, null, interruptedMarkOwner, literal.interrupted.mark) }),
    initial: Object.freeze({ entry: initialEntry, exit: initialExit, trade: trade(id(strategy, frequency, 'initial'), strategy, frequency, initialEntryOwner, initialExitOwner, 'CLOSED', literal.initial.return, null, initialEntry.signal_id, initialEntry.sequence, literal.initial.entry, initialExit.signal_id, literal.initial.exit, null, null, 'initial_before_window') }),
  })
}

function chartValue(url, strategy, frequency, options) {
  const before = url.searchParams.get('chart_before')
  const locateFrom = url.searchParams.has('snapshot_token') && !before ? url.searchParams.get('from') : null
  const long = options.longHistory === `${strategy}:${frequency}`
  const count = options.visualRich && !before ? (frequency === '1d' ? 95 : 64) : long ? (before ? 360 : 480) : 24
  const offset = before ? (long ? -360 : 0) : long || options.visualRich ? 0 : 40
  let bars = Array.from({ length: count }, (_, index) => productBar(frequency, index + offset, long))
  if (options.visualRich) bars = bars.map((bar, index) => {
    const close = 98 + index * 0.09 + Math.sin(index / 5) * 2.1
    const open = close + Math.sin(index * 1.9) * 0.7
    return { ...bar, close: close.toFixed(4), open: open.toFixed(4), high: (Math.max(open, close) + .7).toFixed(4), low: (Math.min(open, close) - .7).toFixed(4), volume: 800 + Math.round((1 + Math.sin(index * 2.3)) * 700) }
  })
  if (before && options.sharedBarConflict) {
    const conflict = { ...productBar(frequency, long ? 0 : 40, long), close: '999.0000', high: '1000.0000' }
    bars = [...bars, conflict]
  }
  const facts = scenarioFacts(strategy, frequency, long)
  const locatedBars = [facts.interrupted.entry, facts.interrupted.mark, facts.initial.entry, facts.initial.exit, facts.open.mark]
    .filter((item) => item.trading_day === locateFrom)
    .map((item) => item.signal_id ? actionOwnerBar(item, strategy, frequency) : item)
  if (locateFrom !== null && locatedBars.length > 0) bars = locatedBars
  let actions = before ? [] : facts.standardActions
  if (locateFrom !== null) actions = [facts.interrupted.entry, facts.initial.entry, facts.initial.exit].filter((item) => item.trading_day === locateFrom)
  if (options.noAction) actions = []
  if (options.visualRich) bars = bars.map(bar => {
    const atBar = actions.find(item => item.bar_end === bar.bar_end)
    if (atBar) return actionOwnerBar(atBar, strategy, frequency)
    if (bar.bar_end === facts.open.mark.bar_end) return facts.open.mark
    return bar
  })
  if (strategy === 'oscillation') {
    bars = bars.map((bar) => {
      const atBar = actions.filter((item) => item.bar_end === bar.bar_end)
      const build = atBar.find((item) => item.kind === 'BUILD')
      const clear = atBar.find((item) => item.kind === 'CLEAR')
      return { ...bar, low: build?.reference_price ?? bar.low, high: clear?.reference_price ?? bar.high }
    })
  }
  const hintBar = bars.at(-2) ?? bars.at(-1)
  const hints = options.noAction || before || locateFrom !== null ? [] : [{ hint_id: id(strategy, frequency, 'hint-d4'), kind: 'D4', bar_end: hintBar.bar_end, known_at: hintBar.bar_end, anchor_price: '104.5000', physical_contract: CONTRACT, segment_id: SEGMENT, retrospective: false, quantity_effect: 'none', sequence: null }]
  return {
    chart_from: locateFrom ?? '2025-01-01', chart_through: locateFrom ?? '2026-09-03', page_identity: HASH.page,
    bars,
    frames: bars.map((bar) => ({ bar_end: bar.bar_end, main_state: actions.some((item) => item.bar_end === bar.bar_end && item.kind === 'BUILD') ? 'BUILD' : 'HOLD', main_values: frameMainValues(strategy, actions.filter((item) => item.bar_end === bar.bar_end), bar, options.visualRich), status: ready(), action_ids: actions.filter((item) => item.bar_end === bar.bar_end).map((item) => item.signal_id), hint_ids: hints.filter((item) => item.bar_end === bar.bar_end).map((item) => item.hint_id) })),
    actions,
    hints,
    diagnostics: options.noAction ? ['NO_MAIN_ACTION_IS_VALID'] : [], next_before: before || locateFrom ? null : 'chart-page-2',
    repainting: false, formal_signal_eligible: true, allowed_uses: ['product_chart', 'reference_input'],
  }
}

function referenceValue(url, strategy, frequency, options) {
  const page = Boolean(url.searchParams.get('history_before'))
  const zero = options.zeroClosed === true
  const facts = scenarioFacts(strategy, frequency, options.longHistory === `${strategy}:${frequency}`)
  const summary = {
    membership_policy: 'entry_in_window_v1', closed_count: zero ? 0 : 1, win_count: zero ? 0 : 1, loss_count: 0, flat_count: 0,
    win_rate_pct: zero ? null : '100', mean_return_pct: zero ? null : facts.closed.trade.reference_return_pct, sum_return_percentage_points: zero ? null : facts.closed.trade.reference_return_pct,
    open_count: 1, interrupted_count: 1, initial_count: 1,
  }
  return {
    performance_since: '2026-01-01', performance_through: '2026-09-03', actual_available_through: '2026-09-03', reference_cutoff: url.searchParams.get('as_of') || NEWOW_AS_OF,
    reference_input_sha256: HASH.reference, summary, items: page ? [facts.interrupted.trade, facts.initial.trade] : [facts.open.trade, ...(zero ? [] : [facts.closed.trade])], next_before: page ? null : 'reference-page-2',
    executable: false, auto_order: false, allowed_uses: ['page_parity_reference', 'research_display'],
  }
}

function trade(tradeId, strategy, frequency, entry, exit, status, result, mark, entrySignalId, entrySequence, entryPrice, exitSignalId, exitPrice, markOwner, markPrice, membership = 'entry_in_window_v1') {
  return {
    reference_trade_id: tradeId, product: 'rb', strategy_code: strategy, frequency, physical_contract: entry.physical_contract, segment_id: entry.segment_id,
    formula_versions: formulas(strategy), reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    entry_signal_id: entrySignalId, entry_sequence: entrySequence, entry_bar_end: entry.bar_end, entry_trading_day: entry.trading_day, entry_reference_price: entryPrice,
    exit_signal_id: exit ? exitSignalId : null, exit_bar_end: exit?.bar_end || null, exit_trading_day: exit?.trading_day || null, exit_reference_price: exit ? exitPrice : null,
    status, holding_bars: 1, reference_return_pct: result, mark_bar_end: exit ? null : markOwner.bar_end, mark_reference_price: exit ? null : markPrice, mark_change_pct: mark,
    interrupted_at: status === 'ROLLOVER_INTERRUPTED' ? '2026-01-07T00:00:00.000Z' : null, interruption_reason: status === 'ROLLOVER_INTERRUPTED' ? 'OWNER_BOUNDARY' : null,
    statistics_membership: membership, hint_ids: status === 'OPEN' ? [id(strategy, frequency, 'hint-d4'), 'hint-not-loaded'] : [],
  }
}

function action(signalId, kind, owner, referencePrice, sequence, related = null) {
  return { signal_id: signalId, kind, bar_end: owner.bar_end, trading_day: owner.trading_day, reference_price: referencePrice, physical_contract: owner.physical_contract, segment_id: owner.segment_id, related_build_id: related, trade_eligibility: 'ELIGIBLE', sequence }
}

function fixtureActionBar(strategy, kind, frequency, barEnd, tradingDay, referencePrice, contract = CONTRACT, segment = SEGMENT) {
  const price = Number(referencePrice)
  if (strategy === 'oscillation') {
    return kind === 'BUILD'
      ? productBarAt(frequency, barEnd, tradingDay, price + 2, contract, segment, { low: referencePrice })
      : productBarAt(frequency, barEnd, tradingDay, price - 2, contract, segment, { high: referencePrice })
  }
  return productBarAt(frequency, barEnd, tradingDay, price + 1, contract, segment)
}

function actionOwnerBar(item, strategy, frequency) {
  return fixtureActionBar(strategy, item.kind, frequency, item.bar_end, item.trading_day, item.reference_price, item.physical_contract, item.segment_id)
}

function frameMainValues(strategy, actions, bar, visualRich = false) {
  const close = Number(bar.close)
  const values = visualRich ? (strategy === 'trend' ? { a: String(close - .3), b: String(close - 1.2) } : strategy === 'main_rise' ? { ma35: String(close - .3), ma45: String(close - 1.2) } : { upper: String(Number(bar.high) + 1), lower: String(Number(bar.low) - 1) }) : { ...MAIN_VALUES[strategy] }
  const actionAtBar = actions[0]
  if (strategy === 'trend' && actionAtBar) values.b = actionAtBar.reference_price
  if (strategy === 'main_rise' && actionAtBar) values.ma45 = actionAtBar.reference_price
  return values
}

function auxiliaryValue(component, frequency, options = {}, strategy = 'trend') {
  const base = { component, segments: [], repainting: false, formal_signal_eligible: true, page_parity: false, source_category: 'guiyi_product_auxiliary_adapter', allowed_uses: ['product_display'] }
  if (component === 'macd') {
    if (options.visualRich) return richMacdFixture(base, strategy, frequency, options)
    const barEnds = [productBar(frequency, 62).bar_end, productBar(frequency, 63).bar_end]
    const points = barEnds.map((bar_end, index) => ({ bar_end, value: index === 0 ? 0 : 0.5, ready: true, valid: true, reason: null }))
    return { ...base, formal_signal_eligible: false, formula_version: 'v1-draft', display_adapter_version: 'guiyi_newow_macd_display_v1', parameters: { fast: 12, slow: 26, signal: 9, ema_seed_policy: 'sma_window', histogram_scale: 2, round_digits: 6 }, parameters_hash: '5dd0ebd25122eea6', allowed_uses: ['research_display'], segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { dif: points, dea: points.map(point => ({ ...point, value: point.value / 2 })), histogram: points } }] }
  }
  if (component === 'cup_handle') return { ...base, formula_version: 'newow_cup_handle_v1', segments: frequency === '1d' ? [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: ['2026-09-03T07:00:00.000Z'], status: ready(), data: [] }] : [] }
  const barEnds = ['2026-09-02T07:00:00.000Z', '2026-09-03T07:00:00.000Z']
  if (component === 'main_force_control') return { ...base, formula_version: 'newow_main_force_control_page_v1', segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { kongpan: [10, 12], status: ['HOLD', 'BUILD'], current_status: 'BUILD', formula_version: 'newow_main_force_control_page_v1' } }] }
  if (component === 'up_down_energy') return { ...base, formula_version: 'newow_up_down_energy_page_v1', segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { var4: [1, 2], ma10: [1, 1.5], band_entry: [0, 1], rebound_entry: [0, 0], oversold_entry: [0, 0], var3: [1, 2], ma120: [1, 1], formula_version: 'newow_up_down_energy_page_v1' } }] }
  return { ...base, formula_version: 'newow_zhaoyao_mirror_repainting_page_v1', repainting: true, formal_signal_eligible: false, segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { entry: [0, 1], wash: [1, 0], distribution: [0, 0], markup: [1, 2], exit: [0, 0], inducement: [0, 0], peaks: [1, 2], caution: [0, 1], repainting: true, formal_signal_eligible: false, formula_version: 'newow_zhaoyao_mirror_repainting_page_v1' } }] }
}

// Precomputed by the existing Python macd_series kernel over these exact fixture
// closes; fixture-only rendering evidence, never external market or formula parity.
function richMacdFixture(base, strategy, frequency, options) {
  const { fixture_input, ...wire } = structuredClone(richMacd[`${strategy}:${frequency}`])
  const bars = chartValue(fixtureValidationUrl('chart', strategy, frequency, false, null), strategy, frequency, options).bars
  if (JSON.stringify(fixture_input) !== JSON.stringify(bars.map(bar => [bar.bar_end, bar.physical_contract, bar.segment_id, bar.close]))) throw new Error('rich MACD fixture input drift; regenerate through the Python kernel')
  return { ...base, ...wire }
}

function explanationValue(strategy, frequency, asOf) {
  const slot = (slotFrequency, barEnd, state) => ({
    frequency: slotFrequency, as_of: asOf, availability: ready(), confirmation_status: ready(),
    identity: { product: 'rb', strategy, frequency: slotFrequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${slotFrequency}_v1`, formula_versions: formulas(strategy) },
    bar_end: barEnd, source_identity: `canonical:rb:${CONTRACT}:${slotFrequency}`, physical_contract: CONTRACT, segment_id: SEGMENT, formula_versions: formulas(strategy), main_state: state,
  })
  const gap = evidenceRequired('NEWOW_PRIVATE_SCORE_UNPROVEN')
  return {
    context: { as_of: asOf, weekly: slot('1w', '2026-08-28T07:00:00.000Z', 'HOLD'), daily: slot('1d', '2026-09-02T07:00:00.000Z', 'BUILD'), hourly: slot('60m', '2026-09-03T07:00:00.000Z', 'HOLD'), missing_frequencies: [], recompute_mode: 'strict_before', historical_database_knowledge_reconstructed: false },
    composite: { status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null, as_of: asOf, formula_versions: ['newow_composite_decision_page_v3_2_82'], source_bars: [], value: {
      decision: { source_key: 'fixture', selected_key: 'long', label: '偏多', position_range: '30%-50%', fallback_used: false, warning_branches_unreachable: true, position_is_target: false, position_is_hand_count: false, formula_version: 'newow_composite_decision_page_v3_2_82' },
      direction: { token: 'LONG_BIAS', certainty_points: 2, formula_version: 'direction-v1' }, certainty: { trend: 2, oscillation: 2, alignment: 1, direction: 2, uncapped_total: 7, total: 7, cap: null, is_probability: false, is_win_rate: false, formula_version: 'certainty-v1' },
      volatility: { value_pct: '1.2500', level: 'medium', true_range_count: 20, method: 'ATR20_CLOSE', is_wilder_atr: false, formula_version: 'volatility-v1' },
      first_action: { rule_token: 'WAIT_CONFIRM', level: 'notice', page_title: '等待', page_detail: '等待已完成周期确认', token_owner: 'guiyi', token_is_page_native: false, page_formula_version: 'first-action-v1' },
      week_day_matrix: { key: 'fixture', name: '周日组合', risk: '中', position: '30%-50%', formula_version: 'matrix-v1' }, subfeatures: [{ name: 'private-score', status: gap, value: null }], input_facts: [], warning_branches_unreachable: true, diagnostic_tokens: null, ai_copy: null, six_combo_ranking: null,
      evidence_manifest_sha256: '1'.repeat(64), page_source_sha256: '2'.repeat(64), reachability_sha256: '3'.repeat(64), ai_template_evidence_sha256: '4'.repeat(64), frozen_results_sha256: '5'.repeat(64),
    } },
    target_absorb: { status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED', reason_code: 'NEWOW_TARGET_SOURCE_UNPROVEN', as_of: asOf, display_surface: null, formula_versions: [], source_bars: [], decision_facts: [], value: null },
    sources: ['1w', '1d', '60m'].map((sourceFrequency) => ({ role: `${sourceFrequency}-context`, source_category: 'strategy_replay', adapter_version: 'v1', formula_versions: formulas(strategy), frequency: sourceFrequency, bar_end: slot(sourceFrequency, sourceFrequency === '1w' ? '2026-08-28T07:00:00.000Z' : sourceFrequency === '1d' ? '2026-09-02T07:00:00.000Z' : '2026-09-03T07:00:00.000Z', 'HOLD').bar_end, physical_contract: CONTRACT, segment_id: SEGMENT, as_of: asOf, dependency_sha256: '6'.repeat(64), status: 'ready', reason_code: null })),
    page_parity: false, allowed_uses: ['research_explanation', 'product_display'],
  }
}

function comparatorValue(strategy, frequency, asOf) {
  const windows = [10, 20, 24, 30, 52].map((window) => ({ window, cumulative_return_pct: `${window / 10}`, max_drawdown_pct: '-1', trade_count: 1, win_count: 1, loss_count: 0, win_rate_pct: '100', force_closed_at_end: true, score: '1', page_display: { cumulative_return_pct: `${window / 10}`, max_drawdown_pct: '-1', win_rate_pct: '100' }, trades: [{ entry_bar_end: '2026-01-05T07:00:00.000Z', entry_price: '100', exit_bar_end: NEWOW_AS_OF, exit_price: '101', return_pct: '1', won: true, synthetic_terminal: true }] }))
  const sourceBars = { count: 120, first_trading_day: '2026-01-01', last_trading_day: '2026-09-03', first_bar_end: '2026-01-05T07:00:00.000Z', last_bar_end: '2026-09-03T07:00:00.000Z', source_identities: ['canonical'], snapshot_kind: 'canonical', fact_identity_fields: ['bar_end', 'physical_contract', 'segment_id'] }
  return { result: { identity: { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas(strategy) }, status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null, as_of: asOf, formula_versions: ['newow_hhv_llv_window_optimizer_page_v1'], source_bars: [sourceBars], value: { segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, frequency, authoritative_start_trading_day: '2026-01-01', authoritative_end_trading_day: '2026-09-03', source_bars: sourceBars, as_of: asOf, in_sample: true, repainting: false, repaint_status: ready(), input_snapshot_status: ready(), status: ready(), results: windows, ranked_windows: [52, 30, 24, 20, 10] }], default_segment_id: SEGMENT, candidate_windows: [10, 20, 24, 30, 52], page_formula_version: 'newow_hhv_llv_window_optimizer_page_v1', futures_adapter_version: 'newow_futures_segment_comparator_v1', page_source_kernel_page_parity: true, futures_adapter_page_parity: false, in_sample: true, executable: false, input_mode: 'canonical', subfeatures: [] } }, executable: false, page_parity: false, synthetic_terminal_is_reference_exit: false, allowed_uses: ['in_sample_comparison'] }
}

function productBar(frequency, index, long = false) {
  if (frequency === '60m') {
    const base = Date.UTC(2026, 6, 1, 1)
    const time = new Date(base + index * 60 * 60 * 1000)
    const priceIndex = long && index >= 416 ? index - 416 : index
    return productBarAt(frequency, time.toISOString(), time.toISOString().slice(0, 10), 100 + priceIndex / 10)
  }
  const step = frequency === '1w' ? 7 : 1
  const base = frequency === '1w' ? Date.UTC(2025, 2, 30, 7) : Date.UTC(2026, 5, 1, 7)
  const time = new Date(base + index * step * 24 * 60 * 60 * 1000)
  const early = time < new Date('2026-01-01T00:00:00.000Z')
  return productBarAt(frequency, time.toISOString(), time.toISOString().slice(0, 10), 100 + index / 10, early ? INITIAL_CONTRACT : CONTRACT, early ? INITIAL_SEGMENT : SEGMENT)
}
function productBarAt(frequency, barEnd, tradingDay, close, contract = CONTRACT, segment = SEGMENT, overrides = {}) {
  const numericClose = Number(close)
  return {
    bar_end: barEnd, trading_day: tradingDay,
    open: String(numericClose - 1), high: String(numericClose + 2), low: String(numericClose - 2), close: String(close),
    volume: 1000, open_interest: 2000, physical_contract: contract, segment_id: segment,
    source_identity: `canonical:rb:${contract}:${frequency}`, observation_eligible: true, completed: true,
    ...overrides,
  }
}
function genericBarsPage(url, options = {}) { const frequency = url.searchParams.get('frequency') || '15m'; const bars = [0, 1].map((index) => { const bar = options.visualRich && frequency === '1d' ? chartValue(fixtureValidationUrl('chart', 'trend', '1d', false, null), 'trend', '1d', options).bars.slice(-2)[index] : productBar(frequency === '1w' || frequency === '1d' || frequency === '60m' ? frequency : '60m', 60 + index); return { ...bar, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close), turnover: 10000 } }); return { request: { series_kind: url.searchParams.get('series_kind'), symbol: url.searchParams.get('symbol'), contract: url.searchParams.get('contract'), frequency, before: url.searchParams.get('before'), limit: Number(url.searchParams.get('limit') || 500) }, bars, canonical_coverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end }, page: { has_more_before: false, next_before: null }, resolved_contract_segments: [{ contract: CONTRACT, start_trading_day: bars[0].trading_day, end_trading_day: bars.at(-1).trading_day }] } }
function researchProduct() { return { symbol: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', series_kind: 'actual_dominant', contract: null, as_of: NEWOW_AS_OF, current_dominant: CONTRACT, dominant_mapping_date: '2026-09-03', daily_trend: 'neutral', weekly_trend: 'neutral', position20: null, distance_to_20d_high: null, distance_to_20d_low: null, volume_ratio20: null, oi_change_1d: null, turnover_change_5d: null, atr14_percentile252: null, recent_daily: [] } }
function marketState(url) { return { symbol: url.searchParams.get('symbol') || 'rb', series_kind: url.searchParams.get('series_kind') || 'actual_dominant', frequency: url.searchParams.get('frequency') || '15m', operational: true, phase: 'CLOSED', trading_day: '2026-09-03', live_eligible: false, live_available: false, live_contract: null, canonical_end: NEWOW_AS_OF, after_market: { last_successful_trading_day: '2026-09-03' } } }
function runtimeHealth() { return { status: 'ok', generated_at: NEWOW_AS_OF, readonly: true, would_start_services: false, would_enqueue_jobs: false, would_send_notifications: false, components: { alert: { status: 'ok', enabled_rule_count: 0, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null } } } } } }
function alertRules() { return [{ rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: true, enabled_frequencies: ['15m'] }, { rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: false, enabled_frequencies: [] }] }
function alertEvents(url) { const rule = url.searchParams.get('rule_code'); return rule ? [{ id: rule === 'htdy_original_15m' ? 1 : 2, rule_code: rule, symbol: 'rb', contract: CONTRACT, trading_day: '2026-09-03', frequency: '15m', bar_end: '2026-09-03T02:45:00.000Z', result_codes: ['buy'], detected_at: '2026-09-03T02:46:00.000Z', notification_attempted_at: null }] : [] }
function homeOverview() { return { status: 'ready', target_as_of: '2026-09-03', data_as_of: '2026-09-03', freshness: 'fresh', active_count: 1, participant_count: 1, stale_count: 0, unavailable_count: 0, summary: { price_up_count: 1, price_down_count: 0, price_flat_count: 0, price_unavailable_count: 0, daily_up_count: 1, daily_down_count: 0, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 0 }, items: [{ symbol: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: CONTRACT, dominant_mapping_date: '2026-09-03', data_as_of: '2026-09-03', close: '100', price_change_1d: '0.01', price_change_5d: null, volume_ratio20: '1.2', oi_change_1d: null, atr14_percentile252: null, daily_trend: 'up', weekly_trend: 'up', reason_codes: [] }], sectors: [{ sector: '黑色', active_count: 1, participant_count: 1, median_price_change_1d: '0.01' }] } }
function id(strategy, frequency, suffix) { return `${strategy}-${frequency}-${suffix}` }
function ready() { return { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null } }
export function warming(reason = 'NEWOW_WARMING') { return { status: 'warming', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: reason } }
export function unavailable(reason = 'NEWOW_AUXILIARY_UNAVAILABLE') { return { status: 'unavailable', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: reason } }
export function evidenceRequired(reason = 'NEWOW_EVIDENCE_REQUIRED') { return { status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED', reason_code: reason } }
function delivered(status, value) { return { delivery: 'delivered', status, value } }
function notRequested() { return { delivery: 'not_requested', status: null, value: null } }

export function productRequests(state, section) { return state.productRequests.filter((item) => item.section === section) }
export function assertNoUnexpectedRequests(state) { if (state.unexpected.length) throw new Error(`unexpected requests: ${state.unexpected.join(', ')}`) }
export async function releaseDeferred(state, key) {
  const release = state.deferred.get(key)
  if (release === undefined) throw new Error(`missing deferred request ${key}`)
  state.deferred.delete(key)
  await release()
}
