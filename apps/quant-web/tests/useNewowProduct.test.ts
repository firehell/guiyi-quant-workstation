import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { getNewowHistoricalSnapshot, getNewowProductSection, NewowProductRequestError } from '../src/api/newowProduct.ts'
import { useNewowProduct } from '../src/composables/useNewowProduct.ts'
import type { MarketDetailIdentity } from '../src/types/marketDetail.ts'
import type { NewowProductRequest, NewowProductSection, NewowProductSectionResponse } from '../src/types/newowProduct.ts'
import { normalizeNewowProductResponse } from '../src/utils/newowProductTypes.ts'
import { resolveNewowPanelRenderState } from '../src/utils/newowProductViewModel.ts'

const AS_OF = '2026-08-15T07:00:00.000Z'

test('fixed preview cutoff retains microseconds through every current generation', async () => {
  const cutoff = '2026-09-08T07:00:00.000001+00:00'
  const pending: Pending[] = []
  const identity = ref(newowIdentity('trend', '1d'))
  const state = useNewowProduct({ identity, now: () => cutoff, fetchSection: controlled(pending) })
  await nextTick()
  assert.equal(state.asOf.value, cutoff)
  assert.equal(pending[0]!.request.asOf, cutoff)
  state.refreshCurrent()
  assert.equal(pending.at(-1)!.request.asOf, cutoff)
  state.returnToCurrent()
  assert.equal(pending.at(-1)!.request.asOf, cutoff)
  identity.value = newowIdentity('oscillation', '60m')
  assert.equal(pending.at(-1)!.request.asOf, cutoff)
  state.dispose()
})

test('older windows append under the same snapshot after page exhaustion and preserve reference', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  const first = normalizedChartPage(pending[0]!.request, '2026-08-14', 'within') as NewowProductSectionResponse<'chart'>
  pending[0]!.resolve(first); await flush()
  assert.equal(state.currentChartWindow?.value, true)
  const within = state.loadNextChartPage()
  assert.equal((pending[1]!.request as any).chartBefore, 'within')
  const last = normalizedChartPage(pending[1]!.request, '2026-08-13', null) as NewowProductSectionResponse<'chart'>
  pending[1]!.resolve({ ...last, value: { ...last.value!, next_older_window: 'older-window' } } as any)
  await within
  assert.equal(state.currentChartWindow.value, true, 'same-window pagination keeps current provenance')
  const reference = state.loadReference()
  pending[2]!.resolve(normalizedReference(pending[2]!.request)); await reference
  const referenceBefore = state.sections.reference.data.value
  const older = state.loadNextChartPage()
  assert.equal(pending.length, 4)
  assert.equal((pending[3]!.request as any).chartOlderWindow, 'older-window')
  assert.equal((pending[3]!.request as any).from, undefined)
  assert.equal((pending[3]!.request as any).chartBefore, undefined)
  const previous = normalizedChartPage(pending[3]!.request, '2026-07-31', null) as NewowProductSectionResponse<'chart'>
  pending[3]!.resolve({ ...previous, meta: { ...previous.meta, input_content_sha256: 'b'.repeat(64) }, value: { ...previous.value!, chart_from: '2026-07-01', chart_through: '2026-07-31', page_identity: 'c'.repeat(64), next_older_window: null } } as any)
  await older
  assert.equal(state.currentChartWindow.value, false, 'older navigation suppresses a current claim')
  const chart = state.sections.chart.data.value as NewowProductSectionResponse<'chart'>
  assert.deepEqual(chart.value!.bars.map(bar => bar.trading_day), ['2026-07-31', '2026-08-13', '2026-08-14'])
  assert.equal(state.sections.reference.data.value, referenceBefore)
  state.dispose()
})

test('current chart provenance follows accepted default requests, ignoring calendar dates and late responses', async () => {
  const pending: Pending[] = []
  const identity = ref(newowIdentity('trend', '1d'))
  const state = useNewowProduct({ identity, now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  assert.equal(state.currentChartWindow?.value, false)
  pending[0]!.resolve(normalizedChart(pending[0]!.request)); await flush()
  assert.equal(state.currentChartWindow.value, true)
  const locate = state.loadChart({ from: '2026-08-01', through: '2026-08-02' })
  assert.equal(state.currentChartWindow.value, false, 'loading cannot retain a current claim')
  pending[1]!.resolve(normalizedChart(pending[1]!.request)); await locate
  assert.equal(state.currentChartWindow.value, false)
  const latest = state.loadChart()
  pending[2]!.resolve(normalizedChart(pending[2]!.request)); await latest
  assert.equal(state.currentChartWindow.value, true)
  const lateHistorical = state.loadChart({ from: '2026-08-01', through: '2026-08-02' })
  const newerDefault = state.loadChart()
  pending[4]!.resolve(normalizedChart(pending[4]!.request)); await newerDefault
  pending[3]!.resolve(normalizedChart(pending[3]!.request)); await lateHistorical
  assert.equal(state.currentChartWindow.value, true, 'late historical result must not change accepted provenance')
  const stale = state.loadChart()
  pending[5]!.reject(new Error('fixture unavailable')); await stale
  assert.equal(state.currentChartWindow.value, false)
  const rebuilding = state.loadChart()
  pending[6]!.reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')); await flush()
  assert.equal(state.currentChartWindow.value, false, 'token rebuild cannot retain accepted provenance')
  pending[7]!.resolve(normalizedChart(pending[7]!.request)); await rebuilding
  assert.equal(state.currentChartWindow.value, true)
  identity.value = newowIdentity('oscillation', '1d')
  assert.equal(state.currentChartWindow.value, false, 'identity reset clears accepted provenance immediately')
  state.dispose()
  assert.equal(state.currentChartWindow.value, false)
})

test('HTTP parser accepts the separate bounded older cursor and request serializes it', async () => {
  const request = { identity: { product: 'jm', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' }, asOf: AS_OF, section: 'chart', snapshotToken: 'snapshot-a', chartOlderWindow: 'older-window' } as any
  const wire = chartWire() as any
  wire.chart.value.next_older_window = 'next-window'
  const response = await getNewowProductSection(request, { request: async (_path, config) => {
    assert.equal(config.params.chart_older_window, 'older-window')
    return wire
  } })
  assert.equal((response.value as any).next_older_window, 'next-window')
})

for (const conflict of ['token', 'range', 'overlap', 'fingerprint'] as const) {
  test(`older navigation rejects ${conflict} without appending unverified bars`, async () => {
    const pending: Pending[] = []
    const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
    await nextTick()
    const initial = normalizedChartPage(pending[0]!.request, '2026-08-14', null) as NewowProductSectionResponse<'chart'>
    pending[0]!.resolve({ ...initial, value: { ...initial.value!, next_older_window: 'older-window' } })
    await flush()
    const older = state.loadNextChartPage()
    const response = normalizedChartPage(pending[1]!.request, conflict === 'overlap' ? '2026-08-14' : '2026-07-31', conflict === 'fingerprint' ? 'within-older' : null) as NewowProductSectionResponse<'chart'>
    const changed = { ...response, meta: { ...response.meta, snapshot_token: conflict === 'token' ? 'changed' : response.meta.snapshot_token }, value: { ...response.value!, chart_from: '2026-07-01', chart_through: conflict === 'range' ? '2026-08-01' : '2026-07-31', page_identity: 'b'.repeat(64) } }
    pending[1]!.resolve(changed)
    await older
    if (conflict === 'fingerprint') {
      const within = state.loadNextChartPage()
      pending[2]!.resolve({ ...changed, meta: { ...changed.meta, input_content_sha256: 'c'.repeat(64) } })
      await within
    }
    assert.equal(state.sections.chart.data.value, null)
    assert.equal(state.sections.chart.state.value, 'input_conflict')
    state.dispose()
  })
}

test('identity switch aborts older-window work and ignores its late result', async () => {
  const identity = ref(newowIdentity('trend', '1d'))
  const pending: Pending[] = []
  const state = useNewowProduct({ identity, now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  const initial = normalizedChart(pending[0]!.request) as NewowProductSectionResponse<'chart'>
  pending[0]!.resolve({ ...initial, value: { ...initial.value!, next_older_window: 'older-window' } }); await flush()
  const older = state.loadNextChartPage()
  identity.value = newowIdentity('oscillation', '60m')
  assert.equal(pending[1]!.signal.aborted, true)
  pending[1]!.resolve(initial)
  await older
  assert.equal(state.sections.chart.data.value, null)
  state.dispose()
})

test('accumulated older windows stop at 3000 rows and suppress both cursor kinds', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  const first = bulkChart(pending[0]!.request, 0, 2000, null)
  const firstDay = first.value!.bars[0]!.trading_day
  pending[0]!.resolve({ ...first, value: { ...first.value!, chart_from: firstDay, next_older_window: 'older' } }); await flush()
  const older = state.loadNextChartPage()
  const response = bulkChart(pending[1]!.request, 2000, 2000, null)
  pending[1]!.resolve({ ...response, value: { ...response.value!, chart_through: response.value!.bars.at(-1)!.trading_day, next_older_window: 'even-older' } })
  await older
  const chart = state.sections.chart.data.value as NewowProductSectionResponse<'chart'>
  assert.equal(chart.value!.bars.length, 3000)
  assert.equal(chart.value!.next_before, null)
  assert.equal(chart.value!.next_older_window, null)
  await state.loadNextChartPage()
  assert.equal(pending.length, 2)
  state.dispose()
})

test('wire older cursor cannot coexist with a page cursor or absent snapshot proof', () => {
  for (const token of [null, 'snapshot-a']) {
    const wire = chartWire({ token }) as any
    wire.chart.value.next_older_window = 'older'
    if (token !== null) wire.chart.value.next_before = 'within'
    assert.throws(() => normalizeNewowProductResponse(wire, { product: 'jm', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant', section: 'chart', asOf: AS_OF } as any))
  }
})

test('explicit historical switch resets requests and preserves the exact server cutoff', async () => {
  const pending: Pending[] = []
  let resolveHistorical!: (value: any) => void
  const state = useNewowProduct({
    identity: ref<MarketDetailIdentity | null>(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF), fetchSection: controlled(pending),
    fetchHistoricalSnapshot: () => new Promise(resolve => { resolveHistorical = resolve }),
  })
  await nextTick(); pending[0]!.resolve(normalizedChart(pending[0]!.request)); await flush()
  const switching = state.switchToHistorical()
  resolveHistorical({ schema_version: 'newow_historical_snapshot_v1', product: 'rb', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', trading_day: '2026-08-14', as_of: '2026-08-14T07:00:00.000001Z', validated_sections: ['chart', 'zhaoyao_mirror'] })
  await flush()
  assert.equal(pending[1]!.request.asOf, '2026-08-14T07:00:00.000001Z')
  pending[1]!.resolve(normalizedChart(pending[1]!.request)); await switching
  assert.equal(state.historicalSnapshot.value?.trading_day, '2026-08-14')
  assert.equal(state.currentChartWindow.value, false)
  state.returnToCurrent()
  assert.equal(state.historicalSnapshot.value, null)
  assert.equal(pending[2]!.request.asOf, AS_OF)
  state.dispose()
})

test('historical resolver client validates dates and keeps the exact cutoff string', async () => {
  const identity = { product: 'rb', strategy: 'trend' as const, frequency: '1d' as const, seriesKind: 'actual_dominant' as const }
  const payload = { schema_version: 'newow_historical_snapshot_v1', product: 'rb', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', trading_day: '2026-08-14', as_of: '2026-08-14T07:00:00.000001Z', validated_sections: ['chart', 'zhaoyao_mirror'] }
  const exact = await getNewowHistoricalSnapshot(identity, { request: async () => payload })
  assert.equal(exact.as_of, payload.as_of)
  await assert.rejects(() => getNewowHistoricalSnapshot(identity, { request: async () => ({ ...payload, trading_day: '2026-02-30' }) }), /NEWOW_RESPONSE_INVALID/)
  await assert.rejects(() => getNewowHistoricalSnapshot(identity, { request: async () => ({ ...payload, as_of: 'garbageZ' }) }), /NEWOW_RESPONSE_INVALID/)
})

test('identity change and a newer resolver invalidate late historical results', async () => {
  const identity = ref<MarketDetailIdentity | null>(newowIdentity('trend', '1d'))
  const pending: Pending[] = []
  const resolvers: Array<{ signal: AbortSignal; resolve: (value: any) => void }> = []
  const state = useNewowProduct({
    identity, now: () => new Date(AS_OF), fetchSection: controlled(pending),
    fetchHistoricalSnapshot: (_request, signal) => new Promise(resolve => resolvers.push({ signal, resolve })),
  })
  await nextTick()
  const oldIdentity = state.switchToHistorical()
  identity.value = newowIdentity('oscillation', '60m')
  assert.equal(resolvers[0]!.signal.aborted, true)
  resolvers[0]!.resolve({ schema_version: 'newow_historical_snapshot_v1', product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', trading_day: '2026-08-14', as_of: '2026-08-14T07:00:00.000001Z', validated_sections: ['chart', 'zhaoyao_mirror'] })
  await oldIdentity; await flush()
  assert.equal(state.historicalSnapshot.value, null)
  assert.equal(state.identity.value?.strategy, 'oscillation')

  const first = state.switchToHistorical()
  const second = state.switchToHistorical()
  assert.equal(resolvers[1]!.signal.aborted, true)
  resolvers[1]!.resolve({ schema_version: 'newow_historical_snapshot_v1', product: 'jm', strategy: 'oscillation', frequency: '60m', series_kind: 'actual_dominant', trading_day: '2026-08-13', as_of: '2026-08-13T07:00:00.000001Z', validated_sections: ['chart', 'zhaoyao_mirror'] })
  resolvers[2]!.resolve({ schema_version: 'newow_historical_snapshot_v1', product: 'jm', strategy: 'oscillation', frequency: '60m', series_kind: 'actual_dominant', trading_day: '2026-08-14', as_of: '2026-08-14T07:00:00.000001Z', validated_sections: ['chart', 'zhaoyao_mirror'] })
  await first; await flush()
  assert.equal(state.historicalSnapshot.value?.trading_day, '2026-08-14')
  pending.at(-1)!.resolve(normalizedChart(pending.at(-1)!.request))
  await second
  state.dispose()
})

test('late response never replaces a different strategy and the new identity clears old values synchronously', async () => {
  const identity = ref<MarketDetailIdentity | null>(newowIdentity('trend', '1d'))
  const pending: Pending[] = []
  const state = useNewowProduct({ identity, now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  assert.equal(pending.length, 1)
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()
  assert.equal(state.sections.chart.data.value?.meta.identity.strategy, 'trend')

  void state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  identity.value = newowIdentity('oscillation', '60m')
  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.reference.data.value, null)
  await nextTick()
  const current = pending.at(-1)!
  current.resolve(normalizedChart(current.request))
  pending[1]!.resolve(normalizedReference(pending[1]!.request))
  await flush()

  assert.equal(state.identity.value?.strategy, 'oscillation')
  assert.equal(state.sections.chart.data.value?.meta.identity.strategy, 'oscillation')
  assert.equal(state.sections.reference.data.value, null)
  state.dispose()
})

test('pins one as_of and keeps chart-reference compatibility independent from an explanation null token', async () => {
  const identity = ref<MarketDetailIdentity | null>(newowIdentity('trend', '1d'))
  const pending: Pending[] = []
  let clock = 0
  const state = useNewowProduct({
    identity,
    now: () => new Date(clock++ === 0 ? AS_OF : '2026-08-15T08:00:00Z'),
    fetchSection: controlled(pending),
  })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token' }))
  await flush()
  const referencePromise = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  assert.equal(pending[1]!.request.asOf, AS_OF)
  assert.equal(pending[1]!.request.snapshotToken, 'shared-token')
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'shared-token' }))
  await referencePromise
  assert.equal(state.referenceChartCompatible.value, true)

  const explanationPromise = state.loadExplanation()
  assert.equal(pending[2]!.request.asOf, AS_OF)
  pending[2]!.resolve(normalizedStatus(pending[2]!.request, null))
  await explanationPromise
  assert.equal(state.sections.explanation.data.value?.meta.snapshot_token, null)
  assert.equal(state.referenceChartCompatible.value, true)
  assert.equal('jointSnapshot' in state, false)
  state.dispose()
})

test('reuses the first-page chart and reference limits for opaque cursor requests', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChartPage(pending[0]!.request, '2026-08-14', null))
  await flush()

  const chart = state.loadChart({ from: '2026-08-01', through: '2026-08-15', chartLimit: 37 })
  pending[1]!.resolve(normalizedChartPage(pending[1]!.request, '2026-08-14', 'chart-cursor'))
  await chart
  const chartPage = state.loadNextChartPage()
  assert.equal(pending[2]!.request.section === 'chart' && pending[2]!.request.chartLimit, 37)
  pending[2]!.resolve(normalizedChartPage(pending[2]!.request, '2026-08-13', null))
  await chartPage

  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15', historyLimit: 23 })
  pending[3]!.resolve(normalizedReference(pending[3]!.request, { nextBefore: 'reference-cursor' }))
  await reference
  const referencePage = state.loadNextReferencePage()
  assert.equal(pending[4]!.request.section === 'reference' && pending[4]!.request.historyLimit, 23)
  pending[4]!.resolve(normalizedReference(pending[4]!.request, { items: [referenceItem('trade-2', '-1.000')], nextBefore: null }))
  await referencePage
  state.dispose()
})

test('rejects a chart cursor whose data revision differs from the retained page', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChartPage(pending[0]!.request, '2026-08-14', 'chart-cursor', 'revision-a'))
  await flush()

  const page = state.loadNextChartPage()
  pending[1]!.resolve(normalizedChartPage(pending[1]!.request, '2026-08-13', null, 'revision-b'))
  await page

  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.chart.state.value, 'input_conflict')
  state.dispose()
})

test('rejects a reference cursor whose data revision differs from the retained page', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()

  const first = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { nextBefore: 'reference-cursor', revision: 'revision-a' }))
  await first
  const page = state.loadNextReferencePage()
  pending[2]!.resolve(normalizedReference(pending[2]!.request, { items: [referenceItem('trade-2', '-1.000')], nextBefore: null, revision: 'revision-b' }))
  await page

  assert.equal(state.sections.reference.data.value, null)
  assert.equal(state.sections.reference.state.value, 'input_conflict')
  state.dispose()
})

test('same-identity revision may replace chart when shared bars agree, but a shared-bar conflict fails closed', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token', hash: 'a'.repeat(64) }))
  await flush()

  const revised = state.loadChart({ from: '2026-08-01', through: '2026-08-15' })
  pending[1]!.resolve(normalizedChart(pending[1]!.request, { token: 'shared-token', hash: 'd'.repeat(64) }))
  await revised
  assert.equal(state.sections.chart.data.value?.meta.input_content_sha256, 'd'.repeat(64))
  assert.equal(state.sections.chart.state.value, 'ready')

  const conflicted = state.loadChart({ chartBefore: 'older-page' })
  pending[2]!.resolve(normalizedChart(pending[2]!.request, { token: 'shared-token', hash: 'e'.repeat(64), close: '100.000' }))
  await conflicted
  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.chart.state.value, 'input_conflict')
  state.dispose()
})

test('same-identity failure keeps only the last success as stale while an obsolete cancellation stays invisible', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()

  const old = state.loadChart({ from: '2026-08-01', through: '2026-08-15' })
  const current = state.loadChart({ from: '2026-08-02', through: '2026-08-15' })
  assert.equal(pending[1]!.signal.aborted, true)
  pending[1]!.reject(new DOMException('aborted', 'AbortError'))
  pending[2]!.reject(new Error('/private/transport secret'))
  await Promise.all([old, current])

  assert.notEqual(state.sections.chart.data.value, null)
  assert.equal(state.sections.chart.state.value, 'stale')
  assert.equal(state.sections.chart.error.value, 'NEWOW_API_UNAVAILABLE')
  state.dispose()
})

test('same-identity busy and cancelled refreshes retain the last success as stale with visible reason and time', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()

  for (const [classification, code] of [
    ['busy', 'NEWOW_RESOURCE_BUSY'],
    ['cancelled', 'NEWOW_REQUEST_CANCELLED'],
  ] as const) {
    const refresh = state.loadChart()
    pending.at(-1)!.reject(new NewowProductRequestError(code, classification))
    await refresh
    const retained = state.sections.chart.data.value
    assert.notEqual(retained, null)
    assert.equal(state.sections.chart.state.value, 'stale')
    assert.equal(state.sections.chart.error.value, code)
    assert.deepEqual(resolveNewowPanelRenderState(state.sections.chart.state.value, retained, state.sections.chart.error.value), {
      showValue: true,
      message: `刷新失败（${code}）；以下为同一身份上次成功的 stale 数值。`,
      staleAt: '2026-08-15T07:00:01Z',
    })
  }
  state.dispose()

  const firstCancelled = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF),
    fetchSection: async () => { throw new NewowProductRequestError('NEWOW_REQUEST_CANCELLED', 'cancelled') },
  })
  await flush()
  assert.equal(firstCancelled.sections.chart.data.value, null)
  assert.equal(firstCancelled.sections.chart.state.value, 'cancelled')
  firstCancelled.dispose()
})

test('main-chart retry keeps the pinned as_of while refresh-current resets the whole generation', async () => {
  const pending: Pending[] = []
  let clock = 0
  const refreshedAsOf = '2026-08-15T08:00:00.000Z'
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(clock++ === 0 ? AS_OF : refreshedAsOf),
    fetchSection: controlled(pending),
  })
  await nextTick()
  pending[0]!.reject(new NewowProductRequestError('NEWOW_DATA_UNAVAILABLE', 'unavailable'))
  await flush()

  const retry = state.loadChart()
  assert.equal(pending[1]!.request.asOf, AS_OF)
  pending[1]!.resolve(normalizedChart(pending[1]!.request))
  await retry

  const oldReference = state.loadReference()
  const refreshCurrent = (state as typeof state & { refreshCurrent: () => void }).refreshCurrent
  assert.equal(typeof refreshCurrent, 'function')
  refreshCurrent()
  assert.equal(pending[2]!.signal.aborted, true)
  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.reference.data.value, null)
  assert.equal(pending[3]!.request.asOf, refreshedAsOf)

  pending[2]!.reject(new DOMException('aborted', 'AbortError'))
  pending[3]!.resolve(normalizedChart(pending[3]!.request))
  await oldReference
  await flush()
  assert.equal(state.asOf.value, refreshedAsOf)
  assert.equal(state.sections.chart.state.value, 'ready')
  state.dispose()
})

test('ordinary other-panel failure preserves an accepted main chart', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()
  const acceptedChart = state.sections.chart.data.value

  const auxiliary = state.loadAuxiliary('main_force_control')
  pending[1]!.reject(new NewowProductRequestError('NEWOW_DATA_UNAVAILABLE', 'unavailable'))
  await auxiliary

  assert.equal(state.sections.chart.data.value, acceptedChart)
  assert.equal(state.sections.chart.state.value, 'ready')
  assert.equal(state.sections.auxiliary.state.value, 'unavailable')
  state.dispose()
})

test('each failed panel shows its sanitized Chinese diagnostic without replacing the main chart', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request)); await flush()
  const accepted = state.sections.chart.data.value
  const loads = [() => state.loadAuxiliary('main_force_control'), () => state.loadReference(), () => state.loadExplanation(), () => state.loadComparator()]
  const sections = ['auxiliary', 'reference', 'explanation', 'comparator'] as const
  for (const [index, load] of loads.entries()) {
    const loading = load()
    pending[index + 1]!.reject(new NewowProductRequestError('NEWOW_DATA_UNAVAILABLE', 'unavailable', {
      reason: 'REPLAY_PREFIX_MISSING', context: { contract: 'RB2701', frequency: '1d' }, historicalCandidateRecoverable: true,
    }))
    await loading
    const resource = state.sections[sections[index]!]
    assert.match(resource.error.value ?? '', /预热历史缺失.*RB2701/)
    assert.match(resolveNewowPanelRenderState(resource.state.value, resource.data.value, resource.error.value).message, /历史快照/)
    assert.equal(state.sections.chart.data.value, accepted)
  }
  state.dispose()
})

test('historical reference data unavailable stays section-local and preserves the validated chart and mirror', async () => {
  const pending: Pending[] = []
  const historicalAsOf = '2026-08-14T07:00:00.000001Z'
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: controlled(pending),
    fetchHistoricalSnapshot: async () => ({
      schema_version: 'newow_historical_snapshot_v1',
      product: 'rb', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant',
      trading_day: '2026-08-14', as_of: historicalAsOf,
      validated_sections: ['chart', 'zhaoyao_mirror'],
    }),
  })
  await nextTick()
  const switching = state.switchToHistorical()
  await flush()
  pending[1]!.resolve(normalizedChart(pending[1]!.request, { token: 'test-only-historical-token' }))
  await switching

  const mirror = state.loadAuxiliary('zhaoyao_mirror')
  assert.equal(pending[2]!.request.asOf, historicalAsOf)
  pending[2]!.resolve(normalizedAuxiliary(pending[2]!.request, 'test-only-historical-token'))
  await mirror
  const chart = state.sections.chart.data.value
  const auxiliary = state.sections.auxiliary.data.value

  const reference = state.loadReference()
  assert.equal(pending[3]!.request.asOf, historicalAsOf)
  pending[3]!.reject(new NewowProductRequestError('NEWOW_DATA_UNAVAILABLE', 'unavailable'))
  await reference

  assert.equal(state.sections.reference.state.value, 'unavailable')
  assert.equal(state.sections.reference.error.value, 'NEWOW_DATA_UNAVAILABLE')
  assert.equal(state.sections.chart.state.value, 'ready')
  assert.equal(state.sections.chart.data.value, chart)
  assert.equal(state.sections.auxiliary.state.value, 'ready')
  assert.equal(state.sections.auxiliary.data.value, auxiliary)
  assert.equal(state.asOf.value, historicalAsOf)
  state.dispose()
})

test('reference pages merge only under one fingerprint and reject duplicate IDs with changed facts', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token' }))
  await flush()
  const first = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'shared-token', nextBefore: 'cursor-2' }))
  await first
  const summary = state.sections.reference.data.value!.value.summary

  const page = state.loadNextReferencePage()
  assert.equal(pending[2]!.request.historyBefore, 'cursor-2')
  pending[2]!.resolve(normalizedReference(pending[2]!.request, { token: 'shared-token', items: [referenceItem('trade-2', '-2.000')], nextBefore: null }))
  await page
  assert.deepEqual(state.sections.reference.data.value!.value.items.map((item) => item.reference_trade_id), ['trade-1', 'trade-2'])
  assert.equal(state.sections.reference.data.value!.value.summary, summary)

  const conflict = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[3]!.resolve(normalizedReference(pending[3]!.request, { token: 'shared-token', items: [referenceItem('trade-1', '9.999')] }))
  await conflict
  assert.equal(state.sections.reference.data.value, null)
  assert.equal(state.sections.reference.state.value, 'input_conflict')
  state.dispose()
})

test('a changed reference fingerprint clears old pages and fixes the first actual window for later pagination', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request))
  await flush()
  const first = state.loadReference()
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { performanceSince: '2025-02-01', nextBefore: 'cursor' }))
  await first
  const changed = state.loadReference({ performanceSince: '2025-03-01', performanceThrough: '2026-08-15' })
  assert.equal(state.sections.reference.data.value, null)
  pending[2]!.resolve(normalizedReference(pending[2]!.request, { performanceSince: '2025-03-01', referenceHash: 'f'.repeat(64), items: [referenceItem('trade-3', '3.000')] }))
  await changed
  assert.deepEqual(state.sections.reference.data.value!.value.items.map((item) => item.reference_trade_id), ['trade-3'])
  state.dispose()
})

test('rebuilds a 409 snapshot or cursor conflict at most once and never loops a 429', async () => {
  const calls: NewowProductRequest[] = []
  let chartAttempts = 0
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      chartAttempts += 1
      if (chartAttempts === 1) throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
      return normalizedChart(request)
    },
  })
  await flush()
  assert.equal(calls.length, 2)
  assert.equal(calls[1]!.snapshotToken, undefined)
  state.dispose()

  let busyCalls = 0
  const busy = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF),
    fetchSection: async () => { busyCalls += 1; throw new NewowProductRequestError('NEWOW_RESOURCE_BUSY', 'busy') },
  })
  await flush()
  assert.equal(busyCalls, 1)
  assert.equal(busy.sections.chart.state.value, 'busy')
  busy.dispose()
})

test('a rejected reference cursor clears every old-token section before one unbound page-one rebuild', async () => {
  const calls: NewowProductRequest[] = []
  let referenceCalls = 0
  let state!: ReturnType<typeof useNewowProduct>
  state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      if (request.section === 'chart') return normalizedChart(request, { token: 'shared-token' })
      if (request.section === 'explanation') return normalizedStatus(request, 'shared-token')
      referenceCalls += 1
      if (referenceCalls === 1) return normalizedReference(request, { token: 'shared-token', nextBefore: 'old-cursor' })
      if (referenceCalls === 2) throw new NewowProductRequestError('NEWOW_CURSOR_GENERATION_CONFLICT', 'conflict')
      assert.equal(state.sections.chart.data.value, null)
      assert.equal(state.sections.reference.data.value, null)
      assert.equal(state.sections.explanation.data.value, null)
      return normalizedReference(request, { token: 'compatible-b', nextBefore: null })
    },
  })
  await flush()
  await state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  await state.loadExplanation()
  await state.loadNextReferencePage()

  const referenceRequests = calls.filter((request) => request.section === 'reference')
  assert.equal(referenceRequests.length, 3)
  assert.equal(referenceRequests[1]!.section === 'reference' && referenceRequests[1]!.historyBefore, 'old-cursor')
  assert.equal(referenceRequests[2]!.section === 'reference' && referenceRequests[2]!.historyBefore, undefined)
  assert.equal(referenceRequests[2]!.snapshotToken, undefined)
  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.explanation.data.value, null)
  assert.equal(state.sections.reference.data.value?.meta.snapshot_token, 'compatible-b')
  state.dispose()
})

test('a cursor 409 falls back to the retained reference token and clears a late same-token explanation', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: null }))
  await flush()

  const firstReference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  assert.equal(pending[1]!.request.snapshotToken, undefined)
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'old-token', nextBefore: 'old-cursor' }))
  await firstReference

  const page = state.loadNextReferencePage()
  assert.equal(pending[2]!.request.section === 'reference' && pending[2]!.request.historyBefore, 'old-cursor')
  assert.equal(pending[2]!.request.snapshotToken, undefined)

  const explanation = state.loadExplanation()
  assert.equal(pending[3]!.request.snapshotToken, 'old-token')
  pending[3]!.resolve(normalizedStatus(pending[3]!.request, 'old-token'))
  await explanation
  assert.equal(state.sections.explanation.data.value?.meta.snapshot_token, 'old-token')

  pending[2]!.reject(new NewowProductRequestError('NEWOW_CURSOR_GENERATION_CONFLICT', 'conflict'))
  await flush()
  assert.equal(pending.length, 5)
  assert.equal(pending[4]!.request.section === 'reference' && pending[4]!.request.historyBefore, undefined)
  assert.equal(pending[4]!.request.snapshotToken, undefined)
  assert.equal(state.sections.reference.data.value, null)
  assert.equal(state.sections.explanation.data.value, null)

  pending[4]!.resolve(normalizedReference(pending[4]!.request, { token: 'new-token', nextBefore: null }))
  await page
  assert.equal(state.sections.reference.data.value?.meta.snapshot_token, 'new-token')
  assert.equal(state.sections.explanation.data.value, null)
  state.dispose()
})

test('a cursor 409 aborts a pending old-token explanation before its late response can be accepted', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: null }))
  await flush()

  const firstReference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'old-token', nextBefore: 'old-cursor' }))
  await firstReference

  const page = state.loadNextReferencePage()
  assert.equal(pending[2]!.request.snapshotToken, undefined)
  const explanation = state.loadExplanation()
  assert.equal(pending[3]!.request.snapshotToken, 'old-token')
  assert.equal(pending[3]!.signal.aborted, false)

  pending[2]!.reject(new NewowProductRequestError('NEWOW_CURSOR_GENERATION_CONFLICT', 'conflict'))
  await flush()
  assert.equal(pending.length, 5)
  assert.equal(pending[3]!.signal.aborted, true)
  assert.equal(pending[4]!.signal.aborted, false)
  assert.equal(state.sections.reference.data.value, null)
  assert.equal(state.sections.explanation.data.value, null)

  pending[3]!.resolve(normalizedStatus(pending[3]!.request, 'old-token'))
  await explanation
  assert.equal(state.sections.explanation.data.value, null)

  pending[4]!.resolve(normalizedReference(pending[4]!.request, { token: 'new-token', nextBefore: null }))
  await page
  assert.equal(state.sections.reference.data.value?.meta.snapshot_token, 'new-token')
  assert.equal(state.sections.explanation.data.value, null)
  state.dispose()
})

test('a rejected reference token aborts a tokenless chart page registered from its retained generation', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChartPage(pending[0]!.request, '2026-08-14', 'old-chart-cursor'))
  await flush()

  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  assert.equal(pending[1]!.request.snapshotToken, 'snapshot-a')
  const chartPage = state.loadNextChartPage()
  assert.equal(pending[2]!.request.section === 'chart' && pending[2]!.request.chartBefore, 'old-chart-cursor')
  assert.equal(pending[2]!.request.snapshotToken, undefined)
  assert.equal(pending[2]!.signal.aborted, false)

  pending[1]!.reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
  await flush()
  assert.equal(pending.length, 4)
  assert.equal(pending[2]!.signal.aborted, true)
  assert.equal(pending[3]!.request.section, 'reference')
  assert.equal(pending[3]!.request.snapshotToken, undefined)

  pending[3]!.resolve(normalizedReference(pending[3]!.request, { token: 'new-token', nextBefore: null }))
  await reference
  pending[2]!.resolve(normalizedChartPage(pending[2]!.request, '2026-08-13', null))
  await chartPage
  assert.equal(state.sections.chart.data.value, null)
  assert.equal(state.sections.reference.data.value?.meta.snapshot_token, 'new-token')
  state.dispose()
})

test('merges an older chart cursor page atomically without changing the fixed reference window', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChartPage(pending[0]!.request, '2026-08-14', 'older-chart'))
  await flush()
  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'snapshot-a' }))
  await reference

  const page = state.loadNextChartPage()
  assert.equal(pending[2]!.request.section === 'chart' && pending[2]!.request.chartBefore, 'older-chart')
  assert.equal(pending[2]!.request.section === 'chart' && pending[2]!.request.from, '2026-08-01')
  pending[2]!.resolve(normalizedChartPage(pending[2]!.request, '2026-08-13', null))
  await page

  assert.deepEqual(state.sections.chart.data.value?.section === 'chart' && state.sections.chart.data.value.value?.bars.map((bar) => bar.trading_day), ['2026-08-13', '2026-08-14'])
  const refreshReference = state.loadReference()
  assert.equal(pending[3]!.request.section === 'reference' && pending[3]!.request.performanceSince, '2025-01-01')
  pending[3]!.resolve(normalizedReference(pending[3]!.request, { token: 'snapshot-a' }))
  await refreshReference
  state.dispose()
})

test('bounds cumulative chart and reference pages and stops exposing an older cursor at the cap', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(bulkChart(pending[0]!.request, 0, 2000, 'chart-older'))
  await flush()
  const chartPage = state.loadNextChartPage()
  pending[1]!.resolve(bulkChart(pending[1]!.request, 2000, 2000, 'must-not-survive'))
  await chartPage
  assert.equal(state.sections.chart.data.value?.section === 'chart' && state.sections.chart.data.value.value?.bars.length, 3000)
  assert.equal(state.sections.chart.data.value?.section === 'chart' && state.sections.chart.data.value.value?.next_before, null)

  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15', historyLimit: 200 })
  pending[2]!.resolve(bulkReference(pending[2]!.request, 0, 200, 'reference-older'))
  await reference
  const referencePage = state.loadNextReferencePage()
  pending[3]!.resolve(bulkReference(pending[3]!.request, 200, 200, 'must-not-survive'))
  await referencePage
  assert.equal(state.sections.reference.data.value?.section === 'reference' && state.sections.reference.data.value.value?.items.length, 300)
  assert.equal(state.sections.reference.data.value?.section === 'reference' && state.sections.reference.data.value.value?.next_before, null)
  state.dispose()
})

test('reopening a validated auxiliary component reuses the current generation', async () => {
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      return request.section === 'chart'
        ? normalizedChart(request)
        : normalizedAuxiliary(request)
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control')
  await state.loadAuxiliary('main_force_control')

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => request.component),
    ['main_force_control'],
  )
  assert.equal(state.sections.auxiliary.data.value?.section === 'auxiliary' && state.sections.auxiliary.data.value.value?.component, 'main_force_control')
  state.dispose()
})

test('does not reuse a validated auxiliary component across distinct explicit chart windows', async () => {
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      return request.section === 'auxiliary' ? normalizedAuxiliary(request) : normalizedChart(request)
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control', { from: '2026-08-01', through: '2026-08-10' })
  await state.loadAuxiliary('main_force_control', { from: '2026-08-11', through: '2026-08-15' })

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => [request.component, request.from, request.through]),
    [
      ['main_force_control', '2026-08-01', '2026-08-10'],
      ['main_force_control', '2026-08-11', '2026-08-15'],
    ],
  )
  state.dispose()
})

test('does not reuse an auxiliary response after a changed-token chart refresh', async () => {
  const calls: NewowProductRequest[] = []
  let chartAttempts = 0
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      if (request.section === 'chart') {
        chartAttempts += 1
        return normalizedChart(request, { token: chartAttempts === 1 ? 'old-token' : 'new-token' })
      }
      return normalizedAuxiliary(request, request.snapshotToken ?? null)
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control')
  await state.loadChart()
  await state.loadAuxiliary('main_force_control')

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => request.snapshotToken),
    ['old-token', 'new-token'],
  )
  state.dispose()
})

test('keeps validated auxiliary reuse across same-generation chart pagination and refresh', async () => {
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      if (request.section === 'auxiliary') return normalizedAuxiliary(request)
      return request.chartBefore === undefined
        ? normalizedChartPage(request, '2026-08-14', 'older-chart', 'revision-a')
        : normalizedChartPage(request, '2026-08-13', null, 'revision-a')
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control')
  await state.loadNextChartPage()
  await state.loadAuxiliary('main_force_control')
  await state.loadChart()
  await state.loadAuxiliary('main_force_control')

  assert.equal(calls.filter((request) => request.section === 'auxiliary').length, 1)
  state.dispose()
})

test('server-proven chart window changes keep reference history and its paging identity', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token', hash: 'a'.repeat(64) }))
  await flush()
  const loading = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: 'shared-token', nextBefore: 'reference-page-2' }))
  await loading
  const before = state.sections.reference.data.value
  const changed = state.loadChart({ from: '2026-08-14', through: '2026-08-14' })
  assert.equal(pending[2]!.request.snapshotToken, 'shared-token')
  pending[2]!.resolve(normalizedChart(pending[2]!.request, { token: 'shared-token', hash: 'b'.repeat(64) }))
  await changed
  assert.equal(state.sections.reference.data.value, before)
  assert.equal(state.referenceChartCompatible.value, true)
  const nextPage = state.loadNextReferencePage()
  assert.equal(pending[3]!.request.section, 'reference')
  if (pending[3]!.request.section === 'reference') {
    assert.equal(pending[3]!.request.historyBefore, 'reference-page-2')
    assert.equal(pending[3]!.request.performanceSince, '2025-01-01')
  }
  pending[3]!.resolve(normalizedReference(pending[3]!.request, { token: 'shared-token', items: [] }))
  await nextPage
  state.dispose()
})

test('a changed chart token clears loaded dependents and binds the next auxiliary request to the new token', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'old-token' }))
  await flush()

  const auxiliary = state.loadAuxiliary('main_force_control')
  pending[1]!.resolve(normalizedAuxiliary(pending[1]!.request, 'old-token'))
  await auxiliary
  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[2]!.resolve(normalizedReference(pending[2]!.request, { token: 'old-token' }))
  await reference
  const explanation = state.loadExplanation()
  pending[3]!.resolve(normalizedStatus(pending[3]!.request, 'old-token'))
  await explanation
  const comparator = state.loadComparator()
  pending[4]!.resolve(normalizedStatus(pending[4]!.request, 'old-token'))
  await comparator

  const changed = state.loadChart()
  pending[5]!.resolve(normalizedChart(pending[5]!.request, { token: 'new-token' }))
  await changed

  for (const section of ['auxiliary', 'reference', 'explanation', 'comparator'] as const) {
    assert.equal(state.sections[section].data.value, null)
    assert.equal(state.sections[section].state.value, 'not_requested')
  }
  const nextAuxiliary = state.loadAuxiliary('main_force_control')
  assert.equal(pending[6]!.request.snapshotToken, 'new-token')
  pending[6]!.resolve(normalizedAuxiliary(pending[6]!.request, 'new-token'))
  await nextAuxiliary
  state.dispose()
})

test('a changed chart token aborts all in-flight dependents and rejects their late old-generation responses', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'old-token' }))
  await flush()

  const dependents = [
    state.loadAuxiliary('main_force_control'),
    state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' }),
    state.loadExplanation(),
    state.loadComparator(),
  ]
  const changed = state.loadChart()
  pending[5]!.resolve(normalizedChart(pending[5]!.request, { token: 'new-token' }))
  await changed

  for (const request of pending.slice(1, 5)) assert.equal(request.signal.aborted, true)
  pending[1]!.resolve(normalizedAuxiliary(pending[1]!.request, 'old-token'))
  pending[2]!.resolve(normalizedReference(pending[2]!.request, { token: 'old-token' }))
  pending[3]!.resolve(normalizedStatus(pending[3]!.request, 'old-token'))
  pending[4]!.resolve(normalizedStatus(pending[4]!.request, 'old-token'))
  await Promise.all(dependents)

  for (const section of ['auxiliary', 'reference', 'explanation', 'comparator'] as const) {
    assert.equal(state.sections[section].data.value, null)
  }
  assert.equal(state.sections.chart.data.value?.meta.snapshot_token, 'new-token')
  state.dispose()
})

test('a tokenless chart revision change clears loaded dependents', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: null, revision: 'revision-a' }))
  await flush()

  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[1]!.resolve(normalizedReference(pending[1]!.request, { token: null, revision: 'revision-a' }))
  await reference
  const changed = state.loadChart()
  pending[2]!.resolve(normalizedChart(pending[2]!.request, { token: null, revision: 'revision-b' }))
  await changed

  assert.equal(state.sections.reference.data.value, null)
  assert.equal(state.sections.reference.state.value, 'not_requested')
  state.dispose()
})

test('touches auxiliary LRU hits so the least recently used of five window keys is evicted', async () => {
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      return request.section === 'chart' ? normalizedChart(request) : normalizedAuxiliary(request)
    },
  })
  await flush()
  const window = (day: string) => ({ from: `2026-08-${day}`, through: `2026-08-${day}` })

  for (const day of ['01', '02', '03', '04']) await state.loadAuxiliary('main_force_control', window(day))
  await state.loadAuxiliary('main_force_control', window('01'))
  await state.loadAuxiliary('main_force_control', window('05'))
  await state.loadAuxiliary('main_force_control', window('01'))
  await state.loadAuxiliary('main_force_control', window('02'))

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => request.from),
    ['2026-08-01', '2026-08-02', '2026-08-03', '2026-08-04', '2026-08-05', '2026-08-02'],
  )
  state.dispose()
})

test('accepts an identity-valid auxiliary warming response without a partial value', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token' }))
  await flush()

  const loading = state.loadAuxiliary('main_force_control')
  pending[1]!.resolve(normalizedStatus(pending[1]!.request, 'shared-token'))
  await loading

  assert.equal(state.sections.auxiliary.state.value, 'warming')
  assert.equal(state.sections.auxiliary.data.value?.section, 'auxiliary')
  assert.equal(state.sections.auxiliary.data.value?.value, null)
  state.dispose()
})

test('A -> B -> A reuses each validated auxiliary component once', async () => {
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      return request.section === 'chart'
        ? normalizedChart(request)
        : normalizedAuxiliary(request)
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control')
  await state.loadAuxiliary('up_down_energy')
  await state.loadAuxiliary('main_force_control')

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => request.component),
    ['main_force_control', 'up_down_energy'],
  )
  assert.equal(state.sections.auxiliary.data.value?.section === 'auxiliary' && state.sections.auxiliary.data.value.value?.component, 'main_force_control')
  state.dispose()
})

test('identity replacement invalidates validated auxiliary reuse', async () => {
  const identity = ref<MarketDetailIdentity | null>(newowIdentity('trend', '1d'))
  const calls: NewowProductRequest[] = []
  const state = useNewowProduct({
    identity,
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      return request.section === 'chart'
        ? normalizedChart(request)
        : normalizedAuxiliary(request)
    },
  })
  await flush()
  await state.loadAuxiliary('main_force_control')
  await state.loadAuxiliary('main_force_control')

  identity.value = newowIdentity('oscillation', '60m')
  await flush()
  await state.loadAuxiliary('main_force_control')

  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => [request.identity.strategy, request.identity.frequency, request.component]),
    [
      ['trend', '1d', 'main_force_control'],
      ['oscillation', '60m', 'main_force_control'],
    ],
  )
  state.dispose()
})

test('rejected snapshot generation invalidates validated auxiliary reuse', async () => {
  const calls: NewowProductRequest[] = []
  let referenceAttempts = 0
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request) => {
      calls.push(request)
      if (request.section === 'chart') return normalizedChart(request, { token: 'old-token' })
      if (request.section === 'auxiliary') return normalizedAuxiliary(request, request.snapshotToken ?? null)
      referenceAttempts += 1
      if (referenceAttempts === 1) throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
      return normalizedReference(request, { token: 'new-token' })
    },
  })
  await flush()
  await state.loadAuxiliary('main_force_control')
  await state.loadAuxiliary('main_force_control')

  await state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  await state.loadAuxiliary('main_force_control')

  assert.equal(referenceAttempts, 2)
  assert.deepEqual(
    calls.filter((request) => request.section === 'auxiliary').map((request) => request.snapshotToken),
    ['old-token', 'new-token'],
  )
  state.dispose()
})

test('tokenless rejected generation clears loaded auxiliary and aborts its in-flight replacement', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: controlled(pending),
  })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: null }))
  await flush()

  const firstAuxiliary = state.loadAuxiliary('main_force_control')
  pending[1]!.resolve(normalizedAuxiliary(pending[1]!.request, null))
  await firstAuxiliary
  const replacement = state.loadAuxiliary('up_down_energy')
  assert.equal(state.sections.auxiliary.data.value?.section === 'auxiliary' && state.sections.auxiliary.data.value.value?.component, 'main_force_control')

  const reference = state.loadReference({ performanceSince: '2025-01-01', performanceThrough: '2026-08-15' })
  pending[3]!.reject(new NewowProductRequestError('NEWOW_CURSOR_GENERATION_CONFLICT', 'conflict'))
  await nextTick()

  assert.equal(pending[2]!.signal.aborted, true)
  assert.equal(state.sections.auxiliary.data.value, null)
  assert.equal(state.sections.auxiliary.state.value, 'not_requested')

  pending[2]!.reject(new DOMException('aborted', 'AbortError'))
  pending[4]!.resolve(normalizedReference(pending[4]!.request, { token: null }))
  await Promise.all([replacement, reference])
  state.dispose()
})

test('transport-normalized auxiliary identity conflict invalidates ready reuse', async () => {
  const auxiliaryCalls: string[] = []
  let mismatchUpDownEnergy = true
  const state = useNewowProduct({
    identity: ref(newowIdentity('trend', '1d')),
    now: () => new Date(AS_OF),
    fetchSection: async (request, signal) => {
      if (request.section === 'chart') return normalizedChart(request)
      if (request.section !== 'auxiliary') throw new Error('unexpected section')
      auxiliaryCalls.push(request.component)
      return getNewowProductSection(request, {
        signal,
        request: async () => {
          if (request.component === 'up_down_energy' && mismatchUpDownEnergy) {
            mismatchUpDownEnergy = false
            return auxiliaryWire({ ...request, component: 'main_force_control' }, request.snapshotToken ?? null)
          }
          return auxiliaryWire(request, request.snapshotToken ?? null)
        },
      })
    },
  })
  await flush()

  await state.loadAuxiliary('main_force_control')
  await state.loadAuxiliary('up_down_energy')

  assert.equal(state.sections.auxiliary.data.value, null)
  assert.equal(state.sections.auxiliary.state.value, 'input_conflict')
  assert.equal(state.sections.auxiliary.error.value, 'NEWOW_RESPONSE_INVALID')

  await state.loadAuxiliary('main_force_control')
  assert.deepEqual(auxiliaryCalls, ['main_force_control', 'up_down_energy', 'main_force_control'])
  assert.equal(state.sections.auxiliary.data.value?.section === 'auxiliary' && state.sections.auxiliary.data.value.value?.component, 'main_force_control')
  state.dispose()
})


for (const completion of ['resolve', 'reject'] as const) {
  test(`shared chart close conflict ignores a late explanation ${completion} even if fetch ignores abort`, async () => {
    const pending: Pending[] = []
    const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
    resolveTestSection(pending[0]!)
    await flush()
    const explanation = state.loadExplanation()
    const late = pending.at(-1)!
    const chart = state.loadChart()
    pending.at(-1)!.resolve(normalizedChart(pending.at(-1)!.request, { close: '100.000' }))
    await chart
    assert.equal(state.sections.explanation.state.value, 'input_conflict')
    if (completion === 'resolve') resolveTestSection(late)
    else late.reject(new Error('late failure'))
    await explanation
    assert.equal(state.sections.explanation.data.value, null)
    assert.equal(state.sections.explanation.state.value, 'input_conflict')
    assert.equal(state.sections.explanation.error.value, 'NEWOW_SHARED_BAR_CONFLICT')
    assert.equal(late.signal.aborted, true)
    state.dispose()
  })
}

const ALL_SECTIONS = ['chart', 'reference', 'explanation', 'auxiliary', 'comparator'] as const

for (const conflictSection of ['chart', 'reference', 'explanation'] as const) {
  for (const completion of ['resolve', 'reject'] as const) {
    test(`${conflictSection} conflict revokes all sections before late ${completion} ignoring abort`, async () => {
      const pending: Pending[] = []
      const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
      pending[0]!.resolve(normalizedChartPage(pending[0]!.request, '2026-08-14', 'old-chart-cursor'))
      await flush()
      for (const section of ALL_SECTIONS.slice(1)) {
        const loaded = loadTestSection(state, section)
        resolveTestSection(pending.at(-1)!)
        await loaded
      }
      assert.equal(state.currentChartWindow.value, true)
      const oldRequests = ALL_SECTIONS.filter(section => section !== conflictSection).map(section => {
        const promise = loadTestSection(state, section, 'up_down_energy')
        return { promise, pending: pending.at(-1)! }
      })
      const conflict = loadTestSection(state, conflictSection)
      const bad = pending.at(-1)!
      if (conflictSection === 'chart') bad.resolve(normalizedChart(bad.request, { close: '100.000' }))
      else if (conflictSection === 'reference') bad.resolve(normalizedReference(bad.request, { items: [referenceItem('same-trade', '2.0000')], nextBefore: 'old-reference-cursor' }))
      else bad.reject(new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid'))
      await conflict
      const assertInvalidated = () => {
        for (const section of ALL_SECTIONS) {
          assert.equal(state.sections[section].data.value, null, `${section} data`)
          assert.equal(state.sections[section].state.value, 'input_conflict', `${section} lifecycle`)
          assert.ok(state.sections[section].error.value, `${section} error`)
        }
        assert.equal(state.currentChartWindow.value, false)
      }
      assertInvalidated()
      for (const old of oldRequests) {
        assert.equal(old.pending.signal.aborted, true, `${old.pending.request.section} signal`)
        if (completion === 'resolve') resolveTestSection(old.pending)
        else old.pending.reject(new Error('late transport failure'))
      }
      await Promise.all(oldRequests.map(old => old.promise))
      assertInvalidated()
      const count = pending.length
      await state.loadNextChartPage()
      await state.loadNextReferencePage()
      assert.equal(pending.length, count, 'cleared cursors cannot issue another page')
      const fresh = state.loadAuxiliary('main_force_control')
      assert.equal(pending.length, count + 1, 'old auxiliary cache must not restore a result')
      assert.equal(pending.at(-1)!.request.snapshotToken, undefined, 'no invalidated section may lend its token')
      pending.at(-1)!.resolve(normalizedAuxiliary(pending.at(-1)!.request, 'snapshot-new'))
      await fresh
      const chart = state.loadChart()
      pending.at(-1)!.resolve(normalizedChart(pending.at(-1)!.request, { token: 'snapshot-new' }))
      await chart
      assert.equal(state.currentChartWindow.value, true)
      assert.equal(state.sections.auxiliary.state.value, 'ready', 'cleared chart provenance must not invalidate newly accepted auxiliary')
      const reference = state.loadReference()
      const request = pending.at(-1)!.request
      assert.equal(request.section === 'reference' && request.performanceSince, undefined, 'old reference window is cleared')
      assert.equal(request.section === 'reference' && request.historyBefore, undefined)
      resolveTestSection(pending.at(-1)!)
      await reference
      state.dispose()
    })
  }
}

for (const section of ['auxiliary', 'comparator'] as const) {
  test(`${section} response conflict stays local while clearing auxiliary reuse`, async () => {
    const pending: Pending[] = []
    const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
    resolveTestSection(pending[0]!)
    await flush()
    const cache = state.loadAuxiliary('main_force_control')
    resolveTestSection(pending.at(-1)!)
    await cache
    const explanation = state.loadExplanation()
    const late = pending.at(-1)!
    const conflict = loadTestSection(state, section, 'up_down_energy')
    pending.at(-1)!.reject(new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid'))
    await conflict
    assert.equal(state.sections[section].state.value, 'input_conflict')
    assert.equal(state.sections.chart.state.value, 'ready')
    assert.equal(late.signal.aborted, false)
    resolveTestSection(late)
    await explanation
    assert.equal(state.sections.explanation.state.value, 'warming')
    const count = pending.length
    const reload = state.loadAuxiliary('main_force_control')
    assert.equal(pending.length, count + 1)
    resolveTestSection(pending.at(-1)!)
    await reload
    state.dispose()
  })
}

for (const completion of ['resolve', 'reject'] as const) {
  test(`invalidated ${completion} finally cannot erase a later explanation controller or token`, async () => {
    const pending: Pending[] = []
    const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
    resolveTestSection(pending[0]!)
    await flush()
    const old = state.loadExplanation()
    const oldRequest = pending.at(-1)!
    const conflict = state.loadChart()
    pending.at(-1)!.resolve(normalizedChart(pending.at(-1)!.request, { close: '100.000' }))
    await conflict
    const recoveredChart = state.loadChart()
    resolveTestSection(pending.at(-1)!)
    await recoveredChart
    const fresh = state.loadExplanation()
    const freshRequest = pending.at(-1)!
    if (completion === 'resolve') resolveTestSection(oldRequest)
    else oldRequest.reject(new Error('late failure'))
    await old
    assert.equal(state.sections.explanation.state.value, 'loading')
    assert.equal(freshRequest.signal.aborted, false)
    // The reference 409 must still find the fresh in-flight token and controller.
    const reference = state.loadReference()
    pending.at(-1)!.reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
    await flush()
    assert.equal(freshRequest.signal.aborted, true)
    resolveTestSection(freshRequest)
    await fresh
    resolveTestSection(pending.at(-1)!)
    await reference
    const latest = state.loadExplanation()
    resolveTestSection(pending.at(-1)!)
    await latest
    assert.equal(state.sections.explanation.state.value, 'warming')
    assert.ok(state.sections.explanation.data.value)
    state.dispose()
  })
}

test('409 cancels a matching loaded section even when its replacement requests a different token', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'chart-token' }))
  await flush()
  const loaded = state.loadExplanation()
  pending.at(-1)!.resolve(normalizedStatus(pending.at(-1)!.request, 'old-explanation-token'))
  await loaded
  const replacement = state.loadExplanation()
  const late = pending.at(-1)!
  assert.equal(late.request.snapshotToken, 'chart-token')
  // Chart picks the loaded explanation token; only the loaded match identifies explanation.
  const chart = state.loadChart()
  assert.equal(pending.at(-1)!.request.snapshotToken, 'old-explanation-token')
  pending.at(-1)!.reject(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
  await flush()
  assert.equal(late.signal.aborted, true)
  assert.equal(state.sections.explanation.state.value, 'not_requested')
  assert.equal(pending.at(-1)!.signal.aborted, false)
  assert.equal(pending.at(-1)!.request.snapshotToken, undefined)
  resolveTestSection(late)
  await replacement
  resolveTestSection(pending.at(-1)!)
  await chart
  assert.equal(state.sections.explanation.data.value, null)
  assert.equal(state.sections.chart.state.value, 'ready')
  state.dispose()
})

function loadTestSection(state: ReturnType<typeof useNewowProduct>, section: NewowProductSection, component: 'main_force_control' | 'up_down_energy' = 'main_force_control') {
  if (section === 'chart') return state.loadChart()
  if (section === 'reference') return state.loadReference()
  if (section === 'explanation') return state.loadExplanation()
  if (section === 'auxiliary') return state.loadAuxiliary(component)
  return state.loadComparator()
}

function resolveTestSection(pending: Pending): void {
  const request = pending.request
  if (request.section === 'chart') pending.resolve(normalizedChart(request))
  else if (request.section === 'reference') pending.resolve(normalizedReference(request, { items: [referenceItem('same-trade', '1.0000')], nextBefore: 'old-reference-cursor' }))
  else if (request.section === 'auxiliary') pending.resolve(normalizedAuxiliary(request))
  else pending.resolve(normalizedStatus(request, 'snapshot-a'))
}

interface Pending {
  request: NewowProductRequest
  signal: AbortSignal
  resolve: (value: NewowProductSectionResponse) => void
  reject: (error: unknown) => void
}

function controlled(pending: Pending[]) {
  return (request: NewowProductRequest, signal: AbortSignal) => new Promise<NewowProductSectionResponse>((resolve, reject) => {
    pending.push({ request, signal, resolve, reject })
  })
}

function newowIdentity(strategy: 'trend' | 'oscillation' | 'main_rise', frequency: '1w' | '1d' | '60m'): MarketDetailIdentity {
  return { view: 'newow', symbol: 'jm', strategy, seriesKind: 'actual_dominant', frequency }
}

function normalizedChart(request: NewowProductRequest, options: { token?: string | null; hash?: string; close?: string; revision?: string | null } = {}) {
  const raw = chartWire({ strategy: request.identity.strategy, frequency: request.identity.frequency, ...options })
  raw.meta.as_of = request.asOf
  return normalizeNewowProductResponse(raw, request)
}

function normalizedReference(request: NewowProductRequest, options: { token?: string | null; hash?: string; referenceHash?: string; items?: unknown[]; nextBefore?: string | null; performanceSince?: string; revision?: string | null } = {}) {
  return normalizeNewowProductResponse(referenceWire(options), request)
}

function normalizedAuxiliary(request: NewowProductRequest, token: string | null = request.snapshotToken ?? 'snapshot-a') {
  if (request.section !== 'auxiliary') throw new Error('auxiliary request required')
  const raw = auxiliaryWire(request, token)
  raw.meta.as_of = request.asOf
  return normalizeNewowProductResponse(raw, request)
}

function normalizedStatus(request: NewowProductRequest, token: string | null) {
  const raw = chartWire({ strategy: request.identity.strategy, frequency: request.identity.frequency, token }) as Record<string, unknown>
  raw.section = request.section
  raw.chart = { delivery: 'not_requested', status: null, value: null }
  raw[request.section] = { delivery: 'delivered', status: { status: 'warming', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: 'NEWOW_WARMING' }, value: null }
  return normalizeNewowProductResponse(raw, request)
}

function normalizedChartPage(request: NewowProductRequest, day: string, nextBefore: string | null, revision: string | null = null) {
  const raw = chartWire({ strategy: request.identity.strategy, frequency: request.identity.frequency })
  raw.meta.data_revision_identity = revision
  raw.chart.value.chart_from = '2026-08-01'
  raw.chart.value.next_before = nextBefore
  raw.chart.value.bars[0]!.bar_end = `${day}T07:00:00Z`
  raw.chart.value.bars[0]!.trading_day = day
  raw.chart.value.frames[0]!.bar_end = `${day}T07:00:00Z`
  raw.chart.value.frames[0]!.action_ids = [`build-${day}`]
  raw.chart.value.actions[0]!.signal_id = `build-${day}`
  raw.chart.value.actions[0]!.bar_end = `${day}T07:00:00Z`
  raw.chart.value.actions[0]!.trading_day = day
  raw.chart.value.actions[0]!.sequence = day === '2026-08-13' ? 0 : 1
  return normalizeNewowProductResponse(raw, request)
}

function bulkChart(request: NewowProductRequest, offset: number, count: number, nextBefore: string | null): NewowProductSectionResponse<'chart'> {
  const base = normalizedChart(request) as NewowProductSectionResponse<'chart'>
  const seedBar = base.value!.bars[0]!
  const seedFrame = base.value!.frames[0]!
  const rows = Array.from({ length: count }, (_, index) => {
    const instant = new Date(Date.parse('2026-08-15T07:00:00Z') - (offset + count - index) * 86_400_000).toISOString()
    return {
      bar: { ...seedBar, bar_end: instant, trading_day: instant.slice(0, 10) },
      frame: { ...seedFrame, bar_end: instant, action_ids: [], hint_ids: [] },
    }
  })
  return { ...base, value: { ...base.value!, chart_from: '2010-01-01', bars: rows.map(({ bar }) => bar), frames: rows.map(({ frame }) => frame), actions: [], hints: [], next_before: nextBefore } }
}

function bulkReference(request: NewowProductRequest, offset: number, count: number, nextBefore: string | null): NewowProductSectionResponse<'reference'> {
  const base = normalizedReference(request) as NewowProductSectionResponse<'reference'>
  const items = Array.from({ length: count }, (_, index) => ({ ...referenceItem(`trade-${offset + index}`, '1.0000'), entry_sequence: offset + index + 1 }))
  return { ...base, value: { ...base.value!, items, next_before: nextBefore } }
}

function chartWire(options: { strategy?: 'trend' | 'oscillation' | 'main_rise'; frequency?: '1w' | '1d' | '60m'; token?: string | null; hash?: string; close?: string; revision?: string | null } = {}) {
  const strategy = options.strategy ?? 'trend'
  const frequency = options.frequency ?? '1d'
  const formulas = strategy === 'trend'
    ? ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2']
    : strategy === 'oscillation'
      ? ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
      : ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
  return {
    meta: {
      schema_version: 'newow_product_detail_v1', identity: { product: 'jm', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas },
      as_of: AS_OF, read_at: '2026-08-15T07:00:01Z', input_content_sha256: options.hash ?? 'a'.repeat(64), data_revision_identity: options.revision ?? null,
      snapshot_token: options.token === undefined ? 'snapshot-a' : options.token,
      reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    },
    section: 'chart',
    chart: { delivery: 'delivered', status: readyStatus(), value: {
      chart_from: '2026-08-14', chart_through: '2026-08-15', page_identity: 'b'.repeat(64),
      bars: [{ bar_end: '2026-08-14T07:00:00Z', trading_day: '2026-08-14', open: '100.125', high: '102.000', low: '99.500', close: options.close ?? '101.500', volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', source_identity: 'canonical:jm:JM2601:1d', observation_eligible: true, completed: true }],
      frames: [{ bar_end: '2026-08-14T07:00:00Z', main_state: 'BUILD', main_values: { B: '100.100' }, status: readyStatus(), action_ids: ['build-1'], hint_ids: [] }],
      actions: [{ signal_id: 'build-1', kind: 'BUILD', bar_end: '2026-08-14T07:00:00Z', trading_day: '2026-08-14', reference_price: '100.100', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', related_build_id: null, trade_eligibility: 'ELIGIBLE', sequence: 1 }],
      hints: [], diagnostics: [], next_before: null, repainting: false, formal_signal_eligible: true, allowed_uses: ['product_chart', 'reference_input'],
    } },
    auxiliary: notRequested(), reference: notRequested(), explanation: notRequested(), comparator: notRequested(),
  }
}

function referenceWire(options: { token?: string | null; hash?: string; referenceHash?: string; items?: unknown[]; nextBefore?: string | null; performanceSince?: string; revision?: string | null } = {}) {
  const base = chartWire(options)
  return {
    ...base, section: 'reference', chart: notRequested(),
    reference: { delivery: 'delivered', status: readyStatus(), value: {
      performance_since: options.performanceSince ?? '2025-01-01', performance_through: '2026-08-15', actual_available_through: '2026-08-15', reference_cutoff: '2026-08-15T07:00:00Z', reference_input_sha256: options.referenceHash ?? 'c'.repeat(64),
      summary: { membership_policy: 'closed_entry_in_requested_window', closed_count: 1, win_count: 1, loss_count: 0, flat_count: 0, win_rate_pct: '100.00', mean_return_pct: '1.2500', sum_return_percentage_points: '1.2500', open_count: 0, interrupted_count: 0, initial_count: 0 },
      items: options.items ?? [referenceItem('trade-1', '1.2500')], next_before: options.nextBefore ?? null, executable: false, auto_order: false, allowed_uses: ['page_parity_reference', 'research_display'],
    } },
  }
}

function auxiliaryWire(request: Extract<NewowProductRequest, { section: 'auxiliary' }>, token: string | null) {
  const base = chartWire({ strategy: request.identity.strategy, frequency: request.identity.frequency, token })
  const formulaVersion = request.component === 'main_force_control'
    ? 'newow_main_force_control_page_v1'
    : request.component === 'zhaoyao_mirror'
      ? 'newow_zhaoyao_mirror_repainting_page_v1'
    : 'newow_up_down_energy_page_v1'
  const data = request.component === 'main_force_control'
    ? { kongpan: [1.25], status: ['control'], current_status: 'control', formula_version: formulaVersion }
    : request.component === 'zhaoyao_mirror'
      ? { entry: [1], wash: [2], distribution: [3], markup: [4], exit: [5], inducement: [6], peaks: [0], caution: [1], repainting: true, formal_signal_eligible: false, formula_version: formulaVersion }
    : { var4: [1.25], ma10: [1], band_entry: [0], rebound_entry: [0], oversold_entry: [0], var3: [2], ma120: [3], formula_version: formulaVersion }
  return {
    ...base,
    section: 'auxiliary',
    chart: notRequested(),
    auxiliary: { delivery: 'delivered', status: readyStatus(), value: {
      component: request.component,
      formula_version: formulaVersion,
      segments: [{
        physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
        bar_ends: ['2026-08-14T07:00:00Z'], status: readyStatus(), data,
      }],
      repainting: request.component === 'zhaoyao_mirror', formal_signal_eligible: false, page_parity: true,
      source_category: 'guiyi_product_auxiliary_adapter', allowed_uses: ['product_auxiliary'],
    } },
  }
}

function referenceItem(id: string, returnPct: string) {
  return {
    reference_trade_id: id, product: 'jm', strategy_code: 'trend', frequency: '1d', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
    formula_versions: ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2'], reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    entry_signal_id: `entry-${id}`, entry_sequence: 1, entry_bar_end: '2026-08-14T07:00:00Z', entry_trading_day: '2026-08-14', entry_reference_price: '100.100',
    exit_signal_id: `exit-${id}`, exit_bar_end: '2026-08-15T07:00:00Z', exit_trading_day: '2026-08-15', exit_reference_price: '101.35125', status: 'CLOSED', holding_bars: 1,
    reference_return_pct: returnPct, mark_bar_end: null, mark_reference_price: null, mark_change_pct: null, interrupted_at: null, interruption_reason: null, statistics_membership: 'CLOSED_ENTRY_IN_WINDOW', hint_ids: [],
  }
}

function readyStatus() { return { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null } }
function notRequested() { return { delivery: 'not_requested', status: null, value: null } }

async function flush(): Promise<void> {
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

test('explanation summary compatibility requires the entire accepted chart generation, not token text alone', async () => {
  const pending: Pending[] = []
  const state = useNewowProduct({ identity: ref(newowIdentity('trend', '1d')), now: () => new Date(AS_OF), fetchSection: controlled(pending) })
  await nextTick()
  pending[0]!.resolve(normalizedChart(pending[0]!.request, { token: 'shared-token' }))
  await flush()
  const first = state.loadExplanation()
  pending[1]!.resolve(normalizedStatus(pending[1]!.request, 'shared-token'))
  await first
  assert.equal(state.explanationChartCompatible.value, true)
  const second = state.loadExplanation()
  const changed = normalizedStatus(pending[2]!.request, 'shared-token')
  pending[2]!.resolve({ ...changed, meta: { ...changed.meta, data_revision_identity: 'different-revision' } })
  await second
  assert.equal(state.explanationChartCompatible.value, false)
  state.dispose()
})
