import { computed, shallowRef, watch, type Ref } from 'vue'
import request from '../api/request'
import { getMarketBarsPage } from '../api/market'
import type { MarketDetailIdentity } from '../types/marketDetail'
import type { MarketAfterCloseFrame } from '../types/referenceTrading'
import { NEWOW_PRODUCT_FREQUENCIES, type NewowProductSectionResponse } from '../types/newowProduct'
import { historicalDisplayBar } from '../utils/marketBarDisplay'
import { NEWOW_AUXILIARY_COMPONENTS } from '../utils/newowAdditionalPanes'
import { normalizeNewowProductResponse } from '../utils/newowProductTypes'
import { isRecordingTradingDay } from '../utils/newowRecording'
import { matchedArchiveChart } from '../utils/workstationChartPanes'
import { projectMarketReferenceChart } from '../utils/newowMarketReference'

type Component = typeof NEWOW_AUXILIARY_COMPONENTS[number]
type HistoricalResponse = {
  source: string; trading_day: string; cutoff: string; revision: string; chart: unknown
  auxiliaries: Record<Component, unknown>; frames: MarketAfterCloseFrame[]
}

async function readHistoricalChart(selected: MarketDetailIdentity, signal: AbortSignal) {
  const product = selected.symbol, strategy = selected.strategy ?? 'trend'
  const frequency = NEWOW_PRODUCT_FREQUENCIES.find(f => f === selected.frequency)
  if (selected.newowMode === 'dual' || selected.seriesKind !== 'actual_dominant' || !frequency)
    throw new Error('当前组合没有可核验的历史复算主体。')
  const identity = { product, strategy, frequency, seriesKind: 'actual_dominant' as const }
  const result = await request.get<never, HistoricalResponse>('/market/newow/historical-chart', {
    params: { product, strategy, frequency, trading_day: selected.newowTradingDay }, signal, timeout: 120_000,
  })
  const { cutoff, revision, frames } = result
  const fail = () => new Error('牛哇复算与行情输入身份不一致。')
  if (result.source !== 'canonical_recompute' || !isRecordingTradingDay(result.trading_day)
    || (selected.newowTradingDay && result.trading_day !== selected.newowTradingDay)
    || !/^[0-9a-f]{64}$/.test(revision) || !Number.isFinite(Date.parse(cutoff)) || !Array.isArray(frames)) throw fail()
  if (selected.newowRevision && selected.newowRevision !== revision) throw new Error('原观察的复算版本已改变，请回到复盘查看冻结原图。')
  const normalized = normalizeNewowProductResponse(result.chart, { identity, asOf: cutoff, section: 'chart' })
  if (normalized.section !== 'chart' || !normalized.meta.snapshot_token || revision !== normalized.meta.shared_input_proof?.market_input_sha256 || !normalized.value?.bars.length) throw fail()
  const rows = normalized.value.bars
  if (rows.at(-1)?.trading_day !== result.trading_day || Date.parse(rows.at(-1)!.bar_end) !== Date.parse(cutoff)) throw fail()
  const auxiliaries = {} as Record<Component, NewowProductSectionResponse<'auxiliary'>>
  for (const component of NEWOW_AUXILIARY_COMPONENTS) {
    const section = normalizeNewowProductResponse(result.auxiliaries[component], { identity, asOf: cutoff, section: 'auxiliary', component })
    if (section.section !== 'auxiliary' || section.meta.snapshot_token !== normalized.meta.snapshot_token
      || section.meta.input_content_sha256 !== normalized.meta.input_content_sha256
      || section.meta.data_revision_identity !== normalized.meta.data_revision_identity
      || !section.meta.shared_input_proof?.market_input_sha256
      || section.meta.shared_input_proof.market_input_sha256 !== normalized.meta.shared_input_proof?.market_input_sha256) throw fail()
    auxiliaries[component] = section
  }
  const query = { symbol: product, frequency, series_kind: 'actual_dominant' as const, limit: rows.length }
  const page = await getMarketBarsPage({ ...query, before: new Date(Date.parse(cutoff) + 1).toISOString() }, signal)
  if (page.request.symbol.toLowerCase() !== product || page.request.frequency !== frequency || page.request.series_kind !== 'actual_dominant') throw fail()
  const candidates = page.bars.map(bar => historicalDisplayBar(page, bar))
  const projection = projectMarketReferenceChart(frames, candidates, product, strategy, frequency, revision)
  const chart = matchedArchiveChart({ status: 'ready', chart: normalized }, projection.matched, candidates)
  const eligible = rows.filter(row => row.completed && row.observation_eligible)
  if (!chart || !eligible.length || chart.value.bars.length !== eligible.length || chart.value.bars.at(-1)?.trading_day !== result.trading_day) throw fail()
  const accepted = new Set(chart.value.bars.map(b => Date.parse(b.bar_end)))
  const bars = candidates.filter(b => accepted.has(Date.parse(b.time)))
  return { chart, auxiliaries, bars, projection: projectMarketReferenceChart(frames, bars, product, strategy, frequency, revision),
    evidence: { kind: 'canonical_recompute' as const, trading_day: result.trading_day, cutoff, revision,
      market_input_sha256: normalized.meta.shared_input_proof!.market_input_sha256 } }
}

export function useNewowHistoricalChart(selected: Readonly<Ref<MarketDetailIdentity | null>>) {
  const window = shallowRef<Awaited<ReturnType<typeof readHistoricalChart>> | null>(null)
  const error = shallowRef<string | null>(null)
  const loading = shallowRef(false)
  const enabled = computed(() => selected.value?.view === 'newow' && selected.value.newowSource === 'canonical-recompute')
  watch(() => enabled.value ? selected.value : null, async (identity, _, cleanup) => {
    window.value = null
    loading.value = !!identity
    error.value = null
    if (!identity) return
    const abort = new AbortController()
    cleanup(() => abort.abort())
    try {
      const next = await readHistoricalChart(identity, abort.signal)
      if (!abort.signal.aborted) window.value = next
    } catch (err) {
      if (!abort.signal.aborted) {
        const code = (err as { response?: { data?: { detail?: { code?: string } } } }).response?.data?.detail?.code
        error.value = err instanceof Error && /^[牛当原]/.test(err.message) ? err.message
          : '当前交易日或周期没有可核验的牛哇复算结果。' + (typeof code === 'string' && /^[A-Z_0-9]{1,80}$/.test(code) ? ' ' + code : '')
      }
    } finally {
      if (!abort.signal.aborted) loading.value = false
    }
  }, { immediate: true, flush: 'sync' })
  return { enabled, window, loading, error }
}
