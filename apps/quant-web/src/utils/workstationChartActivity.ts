import type { MonitorRecord } from '../api/simulationMonitor.ts'
import type { SubingPortfolioStatus } from '../api/subingPortfolio.ts'
import type { BarData, MarketFrequency } from '../types/market.ts'
import { previewInstant } from './candidatePreviewInstant.ts'

export interface ChartExecution {
  id: string
  source: '快期原生委托' | '快期原生成交' | '苏冰模型成交'
  account: string
  contract: string
  time: string
  price: string
}

export interface PlottableExecution extends ChartExecution {
  before: BarData
  after: BarData
  ratio: number
}

const exactInstant = (value: string | null | undefined): value is string =>
  !!value && previewInstant(value) !== null
const positivePrice = (value: string | null | undefined): value is string =>
  !!value && /^\d+(\.\d+)?$/.test(value) && Number.isFinite(Number(value)) && Number(value) > 0

export function tqChartExecutions(records: readonly MonitorRecord[], account: string): ChartExecution[] {
  return records.flatMap<ChartExecution>(row => {
    const { filled_at: at, price, native_precision_seconds: precision } = row.facts
    if (row.kind === 'order' && row.status === 'FILLED' && row.facts.execution_origin === 'OWNER_MANUAL_CLOSE'
      && /^[a-f0-9]{64}$/.test(row.facts.evidence_sha256 ?? '') && exactInstant(row.at) && positivePrice(price)) {
      return [{ id: row.id, source: '快期原生委托', account, contract: row.contract, time: row.at, price }]
    }
    if (row.kind !== 'fill' || row.status !== 'RECORDED' || !exactInstant(at) || !positivePrice(price)
      || precision == null || !/^\d+(\.\d+)?$/.test(precision) || Number(precision) > .001) return []
    return [{ id: row.id, source: '快期原生成交', account, contract: row.contract, time: at, price }]
  })
}

export function subingChartExecutions(status: SubingPortfolioStatus | null, product: string): ChartExecution[] {
  if (!status?.run_id) return []
  return status.products.filter(row => row.product === product).flatMap(row => row.accounts.flatMap(model =>
    (model.fills ?? []).flatMap((fill, index) => exactInstant(fill.fill_at) && positivePrice(fill.price) ? [{
      id: `${status.run_id}:${model.contract}:${fill.fill_at}:${index}`, source: '苏冰模型成交',
      account: `苏冰独立 Paper · ${status.run_id}`, contract: model.contract, time: fill.fill_at, price: fill.price,
    }] : [])))
}

/** Intrabar placement needs adjacent bars of the same owner and a continuous minute interval. */
export function locateChartExecutions(
  executions: readonly ChartExecution[], bars: readonly BarData[], period: MarketFrequency,
): PlottableExecution[] {
  if (!executions.length || !bars.length) return []
  const maxSpan = period.endsWith('m') ? BigInt(period.slice(0, -1)) * 60_000_000_000n : 0n
  const barTimes = bars.map(bar => previewInstant(bar.time))
  return executions.flatMap(event => {
    const at = previewInstant(event.time)
    if (at === null) return []
    const right = barTimes.findIndex(time => time !== null && time >= at)
    const after = bars[right]
    const afterTime = barTimes[right]
    if (!after || afterTime == null || after.confirmed === false || after.physicalContract?.toUpperCase() !== event.contract.toUpperCase()) return []
    if (afterTime === at) return [{ ...event, before: after, after, ratio: 0 }]
    const before = bars[right - 1]
    const beforeTime = barTimes[right - 1]
    if (!before || beforeTime == null || before.confirmed === false || before.physicalContract !== after.physicalContract
      || before.trading_day !== after.trading_day
      || !before.calculationSegmentId || before.calculationSegmentId !== after.calculationSegmentId) return []
    const span = afterTime - beforeTime
    if (span <= 0n || span !== maxSpan || at <= beforeTime) return []
    return [{ ...event, before, after, ratio: Number(at - beforeTime) / Number(span) }]
  })
}
