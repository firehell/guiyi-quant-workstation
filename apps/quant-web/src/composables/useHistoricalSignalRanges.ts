import { ref } from 'vue'
import type { BarData } from '../types/market.ts'
import type { OwnedSignalMarker } from '../utils/historicalSignalMerge.ts'
export interface HistoricalSignalIdentity { symbol: string; strategy: string; frequency: string }
export interface HistoricalSignalRangePage {
  identity: HistoricalSignalIdentity; since: string; through: string; from: string; to: string; sourceToken: string
  coverage?: { status: string; completedThrough?: string | null }
  signals: OwnedSignalMarker[]; nextCursor: string | null
}
export interface HistoricalSignalRangeRequest extends HistoricalSignalIdentity { since: string; through: string; from: string; to: string; before?: string }
const MAX_CHUNKS = 256
const MAX_SIGNALS = 12000
export function useHistoricalSignalRanges(fetchPage: (query: HistoricalSignalRangeRequest, signal: AbortSignal) => Promise<HistoricalSignalRangePage>) {
  const signals = ref<OwnedSignalMarker[]>([]), loading = ref(false), error = ref<string | null>(null)
  const cache = new Map<string, HistoricalSignalRangePage>()
  let controller = new AbortController(), generation = 0
  let active = '', running: Promise<void> | null = null
  let latest: { identity: HistoricalSignalIdentity; bars: readonly BarData[] } | null = null
  function publish(bars: readonly BarData[]) {
    const accepted = new Set(bars.filter(bar => bar.physicalContract).map(bar => `${Date.parse(bar.time)}|${bar.physicalContract!.toUpperCase()}`))
    signals.value = [...cache.values()].flatMap(page => page.signals).filter(item => accepted.has(`${Date.parse(item.barEnd)}|${item.physicalContract.toUpperCase()}`)).slice(-MAX_SIGNALS)
  }
  async function sync(identity: HistoricalSignalIdentity, bars: readonly BarData[]): Promise<void> {
    const identityKey = JSON.stringify(identity)
    if (identityKey !== active) {
      controller.abort(); controller = new AbortController(); generation++; active = identityKey
      cache.clear(); signals.value = []; running = null; loading.value = false; error.value = null
    }
    const requested = { identity: { ...identity }, bars: [...bars] }
    latest = requested
    publish(bars)
    if (running) { await running; if (active === identityKey && latest === requested) return sync(identity, bars); return }
    const requestGeneration = generation, signal = controller.signal
    const days = [...new Set(bars.map(bar => bar.trading_day).filter((day): day is string => Boolean(day)))].sort()
    if (!days.length) return
    const needed: { since: string; through: string; from: string; to: string; key: string }[] = []
    // Request only uncovered loaded bars; calendar span never truncates the chart history.
    const covered = [...cache.values()].filter(page => !page.coverage || page.coverage.status === 'COMPLETE')
    const missing = bars.filter(bar => !covered.some(page => Date.parse(page.from) <= Date.parse(bar.time) && Date.parse(bar.time) <= Date.parse(page.to)))
    for (let offset = 0; offset < missing.length; offset += 300) {
      const chunk = missing.slice(offset, offset + 300)
      const from = chunk[0].time, to = chunk.at(-1)!.time
      needed.push({ since: chunk[0].trading_day!, through: chunk.at(-1)!.trading_day!, from, to, key: `${from}:${to}` })
    }
    const work = needed
    loading.value = true; error.value = null
    const task = (async () => {
      try {
        for (const chunk of work) {
          if (cache.has(chunk.key) && (!cache.get(chunk.key)?.coverage || cache.get(chunk.key)?.coverage?.status === 'COMPLETE')) continue
          let before: string | undefined, token: string | undefined
          const accumulated: OwnedSignalMarker[] = []
          for (let pageNumber = 0; ; pageNumber++) {
            if (pageNumber >= 24) throw new Error('PAGE_BUDGET')
            const page = await fetchPage({ ...identity, since: chunk.since, through: chunk.through, from: chunk.from, to: chunk.to, before }, signal)
            if (requestGeneration !== generation) return
            if (JSON.stringify(page.identity) !== identityKey || page.since !== chunk.since || page.through !== chunk.through || page.from !== chunk.from || page.to !== chunk.to || (token && token !== page.sourceToken) || (before && before === page.nextCursor)) throw new Error('SOURCE_CHANGED')
            token = page.sourceToken; accumulated.push(...page.signals)
            if (accumulated.length > MAX_SIGNALS) throw new Error('SIGNAL_BUDGET')
            if (!page.nextCursor) { cache.set(chunk.key, { ...page, signals: accumulated }); break }
            before = page.nextCursor
          }
          if (cache.size > MAX_CHUNKS || [...cache.values()].reduce((count, page) => count + page.signals.length, 0) > MAX_SIGNALS) throw new Error('SIGNAL_CAPACITY')
          publish(latest?.bars ?? bars)
          if ([...cache.values()].some(page => page.coverage?.status !== undefined && page.coverage.status !== 'COMPLETE')) error.value = '部分历史信号尚未覆盖最新完成行情；保留已确认信号'
        }
      } catch { if (requestGeneration === generation) error.value = '历史信号读取未完成，请重试；保留已读信号' }
      finally { if (requestGeneration === generation) loading.value = false }
    })()
    running = task
    await task
    if (running === task) running = null
  }
  function dispose() { generation++; controller.abort(); cache.clear(); latest = null }
  return { signals, loading, error, sync, dispose }
}
