import type { MonitorRecord } from '../api/simnowMonitor.ts'
import type { BarData, KlineMarker } from '../types/market.ts'
import type { KlineReferenceCallout } from '../types/referenceCallout.ts'

export interface HtdySimnowDisplayRecord extends MonitorRecord {
  signalBarEnd: string | null
  linkage: 'unverified'
  linkageReason: string
  plotNotice?: string
  marker?: KlineMarker
  callout?: KlineReferenceCallout
  focus?: { barEnd: string; physicalContract: string }
}
const instant = (value: string | null | undefined): value is string => Boolean(value && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)))
const positiveDecimal = (value: string | null | undefined): value is string => Boolean(value && /^\+?\d+(?:\.\d+)?$/.test(value) && /[1-9]/.test(value) && Number.isFinite(Number(value)))
const sameContract = (a: string, b: string) => Boolean(a && b && a.toUpperCase() === b.toUpperCase())

/** Execution rows remain account facts; their stored model lacks historical formula/frequency identity. */
export function projectHtdySimnowRecords(records: readonly MonitorRecord[], bars: readonly BarData[], product: string): HtdySimnowDisplayRecord[] {
  const own = records.filter(row => row.product.toUpperCase() === product.toUpperCase())
  return own.map(row => {
    const candidates = own.filter(item => item.kind === 'signal' && item.signal_id && item.signal_id === row.signal_id
      && (!row.contract || sameContract(item.contract, row.contract)))
    const signal = candidates.length === 1 ? candidates[0] : undefined
    const signalBarEnd = instant(signal?.facts.bar_end) ? signal.facts.bar_end : null
    const result: HtdySimnowDisplayRecord = { ...row, signalBarEnd, linkage: 'unverified',
      linkageReason: '执行记录未保存策略公式版本和周期；保留本地事实，不覆盖历史或首次观察信号' }
    if (row.kind !== 'fill') {
      if (signalBarEnd && signal && bars.some(bar => Date.parse(bar.time) === Date.parse(signalBarEnd) && sameContract(bar.physicalContract ?? '', signal.contract))) {
        result.focus = { barEnd: signalBarEnd, physicalContract: signal.contract }
      }
      return result
    }
    const at = row.facts.filled_at, price = row.facts.price
    const precise = row.facts.native_precision_seconds === '0'
    const matched = instant(at) && bars.some(bar => Date.parse(bar.time) === Date.parse(at) && sameContract(bar.physicalContract ?? '', row.contract))
    if (row.status !== 'RECORDED' || !precise || !matched || !positiveDecimal(price)) {
      result.plotNotice = row.status !== 'RECORDED' ? '成交仍待核验，未生成图上成交点'
        : !precise ? '原件成交时间精度不足，未将秒级区间假定为精确图点'
          : '成交时间或物理合约不能精确对应已加载K线，保留原始成交时间'
      return result
    }
    const orders = own.filter(item => item.kind === 'order' && item.order_id && item.order_id === row.order_id
      && item.signal_id === row.signal_id && sameContract(item.contract, row.contract))
    const side = orders.length === 1 ? orders[0]!.facts.side : null
    const buy = side === 'BUY'
    const detail = `SimNow实际成交 · ${at} · ${row.contract} · 价格 ${price} · 数量 ${row.facts.quantity ?? '待核'} · 费用 ${row.facts.fee ?? '待核'} · ${result.linkageReason}`
    result.callout = { id: `simnow-fill:${row.id}`, time: at, physicalContract: row.contract, price,
      title: 'SimNow实际成交', detail, tone: 'neutral', above: !buy }
    result.marker = { id: `simnow-fill:${row.id}`, time: at, label: 'SimNow成交', tooltip: detail,
      tone: 'neutral', position: buy ? 'belowBar' : 'aboveBar', shape: 'square' }
    result.focus = { barEnd: at, physicalContract: row.contract }
    return result
  })
}
