import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import type { BarData } from '../types/market.ts'
import { matchesRangeBar, mergeRangePoints, mergeRangeSource, rangeSourceProof, type RangeSourceProof, normalizeRangeResponse, pointKey, type DynamicRangePoint } from '../utils/dynamicRange.ts'

export interface RangeQuery { symbol: string; frequency: string; contract: string; start: string; end: string }
async function fetchDefault(params: RangeQuery, signal: AbortSignal): Promise<unknown> {
  const { default: request } = await import('../api/request')
  return request.get('/market/indicators/dynamic-range', { signal, params })
}

export function useDynamicRange(options: {
  enabled: Ref<boolean>; bars: Readonly<Ref<BarData[]>>; canonicalEnd: Readonly<Ref<string | null>>
  fetch?: (params: RangeQuery, signal: AbortSignal)=>Promise<unknown>
  identity: Readonly<Ref<string>>; symbol: Readonly<Ref<string>>; frequency: Readonly<Ref<string>>
}) {
  const points = shallowRef<DynamicRangePoint[]>([]), loading = ref(false), error = ref<string | null>(null)
  const supported = computed(() => ['30m','1d'].includes(options.frequency.value))
  const eligible = computed(() => options.canonicalEnd.value ? options.bars.value.filter(b => Date.parse(b.time) <= Date.parse(options.canonicalEnd.value!)) : [])
  let blocked = false
  let proofs = new Map<string,RangeSourceProof>()
  let generation = 0, controller: AbortController | null = null, currentIdentity = ''
  const fingerprint = computed(() => JSON.stringify(eligible.value.map(b => [b.physicalContract,b.time,b.open,b.high,b.low,b.close])))
  async function refresh() {
    const id = ++generation
    controller?.abort(); controller = new AbortController()
    const signal = controller.signal
    const requestedIdentity = options.identity.value, requestedFingerprint = fingerprint.value
    loading.value = false
    if (currentIdentity !== options.identity.value || !options.enabled.value || !supported.value) { points.value = []; proofs = new Map(); blocked=false; error.value=null }
    currentIdentity = options.identity.value
    if (!options.enabled.value || !supported.value || blocked) return
    error.value=null
    const bars = eligible.value
    if (!bars.length) return
    const known = new Map(points.value.map(p => [pointKey(p.contract,p.time),p]))
    if (bars.some(b => !b.physicalContract)) { error.value='缺少物理合约身份'; return }
    if (bars.some(b => { const p=known.get(pointKey(b.physicalContract!,b.time)); return p && !matchesRangeBar(p,b) })) {
      points.value=[]; blocked=true; error.value='历史行情已变化，请关闭后重新开启指标核对'; return
    }
    const missing = bars.filter(b => !known.has(pointKey(b.physicalContract!,b.time)))
    if (!missing.length) return
    loading.value=true
    try {
      // Contiguous chunks only: do not join disjoint ownership intervals.
      let batch: BarData[] = []
      const batches: BarData[][] = []
      for (const b of bars) {
        if (known.has(pointKey(b.physicalContract!,b.time))) { if(batch.length)batches.push(batch); batch=[]; continue }
        if (batch.length && (batch[0].physicalContract !== b.physicalContract || batch.length >= 1000)) { batches.push(batch); batch=[] }
        batch.push(b)
      }
      if(batch.length)batches.push(batch)
      for (const chunk of batches) {
        const symbol=options.symbol.value, frequency=options.frequency.value
        const raw=await (options.fetch ?? fetchDefault)({
          symbol, frequency, contract:chunk[0].physicalContract!, start:chunk[0].time, end:chunk.at(-1)!.time,
        }, signal)
        if (id!==generation || !options.enabled.value || requestedIdentity!==options.identity.value || requestedFingerprint!==fingerprint.value) return
        const proof=mergeRangeSource(proofs.get(chunk[0].physicalContract!),rangeSourceProof(raw))
        const merged=mergeRangePoints(points.value,normalizeRangeResponse(raw,symbol,frequency,chunk))
        proofs.set(chunk[0].physicalContract!,proof)
        points.value=merged
      }
    } catch (exc) {
      if(id===generation && exc instanceof Error && ['DYNAMIC_RANGE_SOURCE_CHANGED','DYNAMIC_RANGE_HISTORY_CHANGED'].includes(exc.message)) {
        blocked=true;points.value=[];error.value='历史前缀来源已变化，已停止显示；请关闭后重新开启指标核对';return
      }
      if(id===generation)error.value='指标计算不可用或输入不一致；已有历史结果保留，可重试'
    } finally { if(id===generation)loading.value=false }
  }
  watch([options.enabled,options.identity,fingerprint,options.canonicalEnd],()=>{void refresh()}, {immediate:true})
  onScopeDispose(()=>{generation++;controller?.abort()})
  return {points,loading,error,supported,refresh}
}
