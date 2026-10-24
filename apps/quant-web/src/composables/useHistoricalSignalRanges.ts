import { ref, watch } from 'vue'
import type { BarData } from '../types/market.ts'
import type { HistoricalChartAction } from '../types/historicalChartAction.ts'
import type { OwnedSignalMarker } from '../utils/historicalSignalMerge.ts'
export interface HistoricalSignalIdentity { symbol: string; strategy: string; frequency: string }
export interface HistoricalSignalRangePage {
  identity: HistoricalSignalIdentity; since: string; through: string; from: string; to: string; sourceToken: string
  coverage?: { status: string; completedThrough?: string | null }
  actions?: HistoricalChartAction[]
  signals: OwnedSignalMarker[]; nextCursor: string | null
}
export interface HistoricalSignalRangeRequest extends HistoricalSignalIdentity { since: string; through: string; from: string; to: string; before?: string }
const MAX_CHUNKS = 256
const MAX_SIGNALS = 12000
export function useHistoricalSignalRanges(
  fetchPage: (query: HistoricalSignalRangeRequest, signal: AbortSignal) => Promise<HistoricalSignalRangePage>,
  authority?: { source: () => string | undefined; error: () => string | null },
) {
  const actions = ref<HistoricalChartAction[]>([])
  const signals = ref<OwnedSignalMarker[]>([]), loading = ref(false), error = ref<string | null>(null)
  const cache = new Map<string, HistoricalSignalRangePage>()
  let controller = new AbortController(), generation = 0
  const inputBars = new Map<string, string>()
  let active = '', running: Promise<void> | null = null
  let latest: { identity: HistoricalSignalIdentity; bars: readonly BarData[] } | null = null
  function publish(bars: readonly BarData[]) {
    const accepted = new Set(bars.filter(bar => bar.physicalContract).map(bar => `${Date.parse(bar.time)}|${bar.physicalContract!.toUpperCase()}`))
    const unique = new Map<string, HistoricalChartAction>()
    for (const page of cache.values()) for (const item of page.actions ?? []) if (accepted.has(`${Date.parse(item.bar_end)}|${item.physical_contract}`)) unique.set(item.action_id, item)
    actions.value = [...unique.values()]
    signals.value = [...cache.values()].flatMap(page => page.signals).filter(item => accepted.has(`${Date.parse(item.barEnd)}|${item.physicalContract.toUpperCase()}`)).slice(-MAX_SIGNALS)
  }
  async function sync(identity: HistoricalSignalIdentity, bars: readonly BarData[], replaceSource = false): Promise<void> {
    if (authority?.error()) { invalidate(); return }
    const identityKey = JSON.stringify(identity)
    const fingerprints = bars.map(bar => [String(Date.parse(bar.time)), JSON.stringify([
      bar.trading_day, bar.physicalContract, bar.calculationSegmentId,
      bar.open, bar.high, bar.low, bar.close, bar.volume, bar.turnover, bar.openInterest,
    ])] as const)
    const sourceChanged = fingerprints.some(([key, value]) => inputBars.has(key) && inputBars.get(key) !== value)
    if (identityKey !== active || replaceSource || sourceChanged) {
      controller.abort(); controller = new AbortController(); generation++; active = identityKey
      cache.clear(); inputBars.clear(); signals.value = []; actions.value = []; running = null; loading.value = false; error.value = null
    }
    for (const [key, value] of fingerprints) inputBars.set(key, value)
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
          const actionPages = new Map<string, HistoricalChartAction>()
          for (let pageNumber = 0; ; pageNumber++) {
            if (pageNumber >= 24) throw new Error('PAGE_BUDGET')
            const page = await fetchPage({ ...identity, since: chunk.since, through: chunk.through, from: chunk.from, to: chunk.to, before }, signal)
            if (requestGeneration !== generation) return
            if (JSON.stringify(page.identity) !== identityKey || page.since !== chunk.since || page.through !== chunk.through || page.from !== chunk.from || page.to !== chunk.to || (token && token !== page.sourceToken) || (before && before === page.nextCursor)) throw new Error('SOURCE_CHANGED')
            token = page.sourceToken; accumulated.push(...page.signals)
            for (const action of page.actions ?? []) {
              const prior = actionPages.get(action.action_id)
              if (prior && JSON.stringify(prior) !== JSON.stringify(action)) throw new Error('SOURCE_CHANGED')
              actionPages.set(action.action_id, action)
            }
            if (accumulated.length + actionPages.size > MAX_SIGNALS) throw new Error('SIGNAL_BUDGET')
            if (!page.nextCursor) {
              const other = [...cache.entries()].filter(([key]) => key !== chunk.key)
              if (other.length + 1 > MAX_CHUNKS || other.reduce((count, [, prior]) => count + prior.signals.length + (prior.actions?.length ?? 0), 0) + accumulated.length + actionPages.size > MAX_SIGNALS) throw new Error('SIGNAL_CAPACITY')
              cache.set(chunk.key, { ...page, signals: accumulated, actions: [...actionPages.values()] }); break
            }
            before = page.nextCursor
          }
          if (cache.size > MAX_CHUNKS || [...cache.values()].reduce((count, page) => count + page.signals.length + (page.actions?.length ?? 0), 0) > MAX_SIGNALS) throw new Error('SIGNAL_CAPACITY')
          publish(latest?.bars ?? bars)
          if ([...cache.values()].some(page => page.coverage?.status !== undefined && page.coverage.status !== 'COMPLETE')) error.value = '部分历史信号尚未覆盖最新完成行情；保留已确认信号'
        }
      } catch (reason) {
        if (requestGeneration === generation) {
          const failure = reason as { message?: string; response?: { status?: number; data?: { detail?: { code?: string } } } }
          const invalid = failure.response?.status === 409 || /SOURCE_|IDENTITY|HISTORICAL_(?:ACTION|SIGNAL)_/.test(failure.message ?? '')
            || /SOURCE|IDENTITY|CONFLICT|UNVERIFIED/.test(failure.response?.data?.detail?.code ?? '')
          if (invalid) { cache.clear(); signals.value = []; actions.value = [] }
          const unavailable = /DATA_UNAVAILABLE|ENDPOINT_UNAVAILABLE|NOT_BUILT|BUDGET|TOO_LARGE/.test(failure.response?.data?.detail?.code ?? '')
          error.value = invalid ? '历史动作来源无法核实，已撤销标签；未回退到实时记录，请重试' : unavailable ? '当前历史范围数据不足或读取受限，已核实标签保留，缺失动作未补造；可重试' : '历史动作读取失败，已核实标签保留，新增范围尚未完成；请重试'
        }
      }
      finally { if (requestGeneration === generation) loading.value = false }
    })()
    running = task
    await task
    if (running === task) running = null
  }
  function invalidate() {
    generation++; controller.abort(); controller = new AbortController()
    cache.clear(); inputBars.clear(); signals.value = []; actions.value = []; latest = null; running = null; loading.value = false
    error.value = '正式历史来源待重新验证，旧信号已撤销'
  }
  // A reference refresh may revoke its source before failing, or retain an old
  // result alongside an error. Neither state may keep COMPLETE chart markers.
  const stopAuthority = authority ? watch([authority.source, authority.error],
    ([source, failure], previous) => {
      if (failure || (!source && previous?.[0])) invalidate()
    }, { flush: 'sync' }) : null
  function dispose() { stopAuthority?.(); generation++; controller.abort(); cache.clear(); inputBars.clear(); latest = null }
  return { actions, signals, loading, error, sync, invalidate, dispose }
}
