import type { useNewowHistoricalChart } from './useNewowHistoricalChart'
import { computed, ref, shallowRef, watch, type Ref } from 'vue'
import { getMarketAfterCloseSection } from '../api/referenceTrading'
import type { MarketAfterCloseFrame, MarketAfterCloseReference, MarketAfterCloseSection } from '../types/referenceTrading.ts'
import type { BarData } from '../types/market.ts'
import { NEWOW_PRODUCT_FREQUENCIES, NEWOW_PRODUCT_STRATEGIES } from '../types/newowProduct.ts'
import { archiveReadError, paneAvailability, matchedArchiveChart, readWorkstationLayers, type ArchivePane, type PaneId } from '../utils/workstationChartPanes.ts'

const storageKey = 'guiyi.workstation.chart.layers.v1'
function preferences(strategy?: string) {
  try {
    const common = JSON.parse(localStorage.getItem(storageKey) ?? '{}')
    const savedPanes = strategy ? localStorage.getItem(storageKey + '.' + strategy) : null
    return readWorkstationLayers(savedPanes === null ? common : { ...common, panes: JSON.parse(savedPanes) })
  } catch { return readWorkstationLayers(null) }
}
export function useWorkstationChartPanes(scope: () => { product: string; strategy: string; frequency: string } | null,
  source: () => MarketAfterCloseReference | null, bars: Ref<BarData[]>, frames: () => readonly MarketAfterCloseFrame[],
  historical?: ReturnType<typeof useNewowHistoricalChart>, archiveNotice: () => string | null = () => null) {
  const activeStrategy = computed(() => scope()?.strategy)
  const layers = ref(preferences(activeStrategy.value))
  watch(activeStrategy, strategy => {
    if (strategy) layers.value = preferences(strategy)
  }, { flush: 'sync' })
  watch(layers, ({ panes, ...common }) => {
    const strategy = activeStrategy.value
    if (!strategy) return
    try {
      localStorage.setItem(storageKey + '.' + strategy, JSON.stringify(panes))
      localStorage.setItem(storageKey, JSON.stringify(common))
    } catch { /* optional storage */ }
  }, { flush: 'sync' })
  type Read = { section?: MarketAfterCloseSection; message: string | null }
  const reads = shallowRef<Partial<Record<PaneId, Read>>>({})
  const ids = computed(() => layers.value.panes.map(pane => pane.id).filter(id => id !== 'macd').sort().join(','))
  watch([scope, source, ids], async ([identity, published], _, onCleanup) => {
    reads.value = {}
    if (!identity || !published || !ids.value) return
    const strategy = NEWOW_PRODUCT_STRATEGIES.find(s => s === (identity.strategy === 'dual_fusion' ? 'trend' : identity.strategy))
    const frequency = NEWOW_PRODUCT_FREQUENCIES.find(f => f === identity.frequency)
    if (!strategy || !frequency) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    await Promise.all(layers.value.panes.filter(p => p.id !== 'macd').map(async ({ id }) => {
      let result: Read
      try {
        const section = await getMarketAfterCloseSection({ section: 'auxiliary', component: id, asOf: published.cutoff,
          identity: { product: identity.product, strategy, frequency, seriesKind: 'actual_dominant' } }, { signal: controller.signal })
        const sameReceipt = !!published.receipt && published.receipt === section.receipt
        const sameStream = section.status === 'ready' && section.reference?.stream_id === published.stream_id
          && section.reference.revision_id === published.revision_id && section.reference.seq === published.seq
        const compatible = identity.strategy === 'dual_fusion' ? sameReceipt
          : sameStream && (!published.receipt || sameReceipt)
        result = section.status === 'ready' && compatible ? { section, message: null }
          : { message: section.status === 'pending' ? '已有盘后主图，此副图尚待归档'
            : section.status === 'unavailable' ? '当前组合没有可用的已归档副图' : '副图回执与主图归档版本不一致' }
      } catch (failure) { result = { message: archiveReadError(failure) } }
      if (!controller.signal.aborted) reads.value = { ...reads.value, [id]: result }
    }))
  }, { immediate: true, flush: 'sync' })
  const panes = computed(() => layers.value.panes.map((spec): ArchivePane => {
    if (historical?.enabled.value && spec.id !== 'macd') {
      const window = historical.window.value
      const auxiliary = window?.auxiliaries[spec.id] ?? null
      return { ...spec, chart: window?.chart ?? null, auxiliary,
        message: window && auxiliary ? paneAvailability(window.chart, auxiliary) : historical.error.value ?? '正在读取历史复算' }
    }
    const saved = reads.value[spec.id]
    const section = saved?.section
    const chart = section ? matchedArchiveChart(section, frames(), bars.value) : null
    const auxiliary = chart && section?.result?.section === 'auxiliary' ? section.result : null
    return { ...spec, chart, auxiliary, message: spec.id === 'macd' ? null : saved?.message ??
      (chart && auxiliary ? paneAvailability(chart, auxiliary) : archiveNotice() ?? (section ? '归档与行情的 Bar 哈希、价格或合约段未能匹配'
       : source() ? '正在读取盘后指标' : '当前没有已核验的盘后归档')) }
  }))
  return { layers, panes }
}
