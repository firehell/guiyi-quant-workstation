import type { DisplayVolumeBar } from './volumeDisplay.ts'
import type { createChart, IChartApi, LogicalRange, SeriesType, ISeriesApi, Time } from 'lightweight-charts'
import { createPriceSeriesWriter } from './priceSeriesWriter.ts'
import { toChartTimeForPeriod } from './barTime.ts'

export const DETAIL_CHART_SESSION = Symbol('detail-chart-session')
export type DetailChartSession = ReturnType<typeof createDetailChartSession>
export function detailChartPaneLayout(chartHeight: number, toolbarHeight: number, indicatorHeight = 150) {
  const topInset = Math.max(44, toolbarHeight + 12)
  const auxiliaryHeight = topInset + indicatorHeight + 15
  return { topInset, auxiliaryHeight, mainHeight: Math.max(1, chartHeight - 30 - auxiliaryHeight) }
}
/** One display coordinate for every detail adapter; formal bar_end is untouched. */
export function detailChartTime(bar: { time: string; trading_day?: string }, period: string): Time {
  return period.endsWith('m') ? Math.floor(Date.parse(bar.time) / 1000) as import('lightweight-charts').UTCTimestamp
    : toChartTimeForPeriod(bar, period) as Time
}
/** Use the same retained source window for coloring and explanation. */
export function detailChartVolumeBars(chart: IChartApi, incoming: readonly DisplayVolumeBar[]): readonly DisplayVolumeBar[] {
  return volumeInputs.get(chart)?.(incoming) ?? incoming
}
const volumeInputs = new WeakMap<IChartApi, (incoming: readonly DisplayVolumeBar[]) => readonly DisplayVolumeBar[]>()
const owners = new WeakMap<IChartApi, DetailChartSession>()
/** A strategy adapter can recover the page-owned viewport without owning the canvas. */
export function detailChartViewport(chart: IChartApi): LogicalRange | null {
  return owners.get(chart)?.viewport() ?? null
}
export function resetDetailChartWindow(chart: IChartApi): void { owners.get(chart)?.resetWindow() }
export function detailChartIndex(chart: IChartApi, time: Time, fallback: number): number {
  return chart.timeScale().timeToIndex?.(time, false) ?? owners.get(chart)?.indexOf(time) ?? fallback
}
export function detailChartLength(chart: IChartApi, fallback: number): number {
  const owner = owners.get(chart), last = owner?.timeAt(Infinity)
  const index = last == null ? null : chart.timeScale().timeToIndex?.(last, false)
  return index == null ? owner?.length() ?? fallback : index + 1
}
export function detailChartTimeAt(chart: IChartApi, index: number): Time | null {
  const scale = chart.timeScale()
  const coordinate = scale.logicalToCoordinate?.(Math.floor(index) as import('lightweight-charts').Logical)
  return (coordinate == null ? null : scale.coordinateToTime?.(coordinate)) ?? owners.get(chart)?.timeAt(index) ?? null
}
function timeKey(time: Time): string {
  return typeof time === 'object' ? `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}` : String(time)
}

/** Page-scoped canvas and price series. Leases own only strategy resources.
 * Keeping the native chart here also preserves manual price-axis scale settings.
 */
export function createDetailChartSession(dependencies: {
  createChart: typeof createChart
  createContainer?: () => HTMLElement
}) {
  let chart: IChartApi | null = null, surface: HTMLElement | null = null
  let identity = '', disposed = false
  let releaseActive: (() => void) | null = null
  const viewports = new Map<string, LogicalRange>()
  const prices = new Map<string, ISeriesApi<SeriesType, Time>>()
  const writers = new Map<string, ReturnType<typeof createPriceSeriesWriter<any>>>()
  const pricePoints = new Map<string, any[]>()
  let volumeInput: readonly DisplayVolumeBar[] = []
  let hasPrices = false
  let ownsViewport = false

  function saveViewport() {
    const range = chart?.timeScale().getVisibleLogicalRange()
    if (identity && range && hasPrices && ownsViewport) {
      viewports.delete(identity); viewports.set(identity, { ...range })
      if (viewports.size > 32) viewports.delete(viewports.keys().next().value!)
    }
  }
  function setIdentity(next: string) {
    if (next === identity) return
    saveViewport(); identity = next; hasPrices = false; ownsViewport = false
    for (const series of prices.values()) series.setData([])
    writers.clear(); pricePoints.clear(); volumeInput = []
  }
  function viewport(): LogicalRange | null {
    const live = hasPrices && ownsViewport ? chart?.timeScale().getVisibleLogicalRange() : null
    return live ?? viewports.get(identity) ?? null
  }
  function resetWindow() {
    for (const series of prices.values()) series.setData([])
    writers.clear(); pricePoints.clear(); volumeInput = []; ownsViewport = false; hasPrices = false
  }
  function indexOf(time: Time): number | null {
    const index = (pricePoints.get('candles') ?? []).findIndex(point => timeKey(point.time) === timeKey(time))
    return index < 0 ? null : index
  }
  function length() { return pricePoints.get('candles')?.length ?? 0 }
  function timeAt(index: number): Time | null {
    const data = pricePoints.get('candles') ?? []
    return data[Math.max(0, Math.min(data.length - 1, Math.floor(index)))]?.time ?? null
  }
  function mergeVolumeBars(incoming: readonly DisplayVolumeBar[]): readonly DisplayVolumeBar[] {
    if (!incoming.length) return volumeInput
    const suffix = volumeInput.length > incoming.length && incoming.every((bar, index) => {
      const previous = volumeInput[volumeInput.length - incoming.length + index]!
      return (bar.time === previous.time || Date.parse(bar.time) === Date.parse(previous.time)) && bar.physicalContract === previous.physicalContract
        && ['open', 'high', 'low', 'close', 'volume'].every(key => Object.is(bar[key as keyof DisplayVolumeBar], previous[key as keyof DisplayVolumeBar]))
    })
    volumeInput = suffix ? [...volumeInput.slice(0, volumeInput.length - incoming.length), ...incoming] : [...incoming]
    return volumeInput
  }
  function acquire(container: HTMLElement, options: Parameters<typeof createChart>[1]): IChartApi {
    if (disposed) throw new Error('DETAIL_CHART_DISPOSED')
    releaseActive?.()
    if (!surface) {
      surface = dependencies.createContainer?.() ?? document.createElement('div')
      Object.assign(surface.style, { width: '100%', height: '100%' })
    }
    container.appendChild(surface)
    if (!chart) chart = dependencies.createChart(surface, options)
    else chart.applyOptions(options ?? {})
    const native = chart
    let active = true, paneIndex = 1
    const series = new Set<ISeriesApi<SeriesType, Time>>()
    const cleanup = new Set<() => void>()
    const wrappers = new Map<ISeriesApi<SeriesType, Time>, ISeriesApi<SeriesType, Time>>()
    function member(target: any, property: PropertyKey) {
      const value = Reflect.get(target, property)
      if (typeof value !== 'function') return value
      const name = String(property)
      if (name.startsWith('subscribe')) return (...args: any[]) => {
        if (!active) return
        value.apply(target, args)
        const unsubscribe = target[name.replace(/^subscribe/, 'unsubscribe')]
        if (typeof unsubscribe === 'function') cleanup.add(() => unsubscribe.apply(target, args))
      }
      const mutates = /^(set|apply|resize|scroll|fit|reset)/.test(name)
      return (...args: any[]) => {
        if (!active && mutates) return
        if (/^(setVisible|scroll|fitContent|resetTimeScale)/.test(name)) ownsViewport = true
        return value.apply(target, args)
      }
    }
    const timeScale = new Proxy(native.timeScale(), { get: member })

    function release() {
      if (!active) return
      saveViewport(); active = false
      for (const remove of cleanup) remove()
      cleanup.clear()
      for (const item of series) native.removeSeries(item)
      series.clear()
      if (releaseActive === release) releaseActive = null
    }
    releaseActive = release
    function wrapSeries(raw: ISeriesApi<SeriesType, Time>, role?: string): ISeriesApi<SeriesType, Time> {
      const wrapper = new Proxy(raw, { get(target, property) {
        if (property === 'setData' && role) return (data: any[]) => {
          if (!active || (!data.length && hasPrices)) return
          const previous = pricePoints.get(role) ?? []
          const range = role === 'candles' ? viewport() : null
          const sameFact = (a: any, b: any) => JSON.stringify(a.time) === JSON.stringify(b.time)
            && (role === 'candles' ? ['open', 'high', 'low', 'close'] : ['value']).every(field => Object.is(a[field], b[field]))
          const suffix = role === 'candles' && previous.length > data.length && data.length > 0
            && data.every((point, index) => sameFact(point, previous[previous.length - data.length + index]))
          if (suffix) {
            const retained = previous.slice(0, previous.length - data.length)
            data = [...retained, ...data]
          }
          let mappedRange = range
          if (role === 'candles' && range && previous.length && data.length) {
            const firstCommon = data.findIndex(point => JSON.stringify(point.time) === JSON.stringify(previous[0].time))
            const oldCommon = previous.findIndex(point => JSON.stringify(point.time) === JSON.stringify(data[0].time))
            const offset = firstCommon >= 0 ? firstCommon : oldCommon >= 0 ? -oldCommon : null
            mappedRange = offset === null ? null : { from: range.from + offset, to: range.to + offset } as LogicalRange
            if (mappedRange && (mappedRange.to < -.5 || mappedRange.from > data.length - .5)) mappedRange = null
          }
          const writer = writers.get(role) ?? createPriceSeriesWriter<any>()
          writers.set(role, writer); writer.write(target, data, identity); pricePoints.set(role, data)
          if (role === 'candles' && data.length) {
            hasPrices = true
            if (range && !mappedRange) ownsViewport = false
            if (mappedRange) native.timeScale().setVisibleLogicalRange(mappedRange)
          }
        }
        if (property === 'update' && role) return (point: any) => {
          if (!active) return
          const previous = pricePoints.get(role) ?? []
          const key = JSON.stringify(point.time)
          const index = previous.findIndex(item => JSON.stringify(item.time) === key)
          const next = [...previous]
          if (index < 0) next.push(point); else next[index] = point
          const writer = writers.get(role) ?? createPriceSeriesWriter<any>()
          writers.set(role, writer); writer.write(target, next, identity); pricePoints.set(role, next)
        }
        if (property === 'attachPrimitive') return (primitive: any) => {
          if (!active) return
          target.attachPrimitive(primitive)
          const remove = () => target.detachPrimitive(primitive)
          primitiveCleanup.set(primitive, remove); cleanup.add(remove)
        }
        if (property === 'detachPrimitive') return (primitive: any) => {
          const remove = primitiveCleanup.get(primitive)
          if (remove) { cleanup.delete(remove); primitiveCleanup.delete(primitive); remove() }
        }
        if (property === 'createPriceLine') return (settings: any) => {
          if (!active) return
          const line = target.createPriceLine(settings)
          cleanup.add(() => { try { target.removePriceLine(line) } catch { /* Adapter already released it. */ } })
          return line
        }
        const value = Reflect.get(target, property)
        if (typeof value !== 'function') return value
        return (...args: any[]) => active ? value.apply(target, args) : undefined
      } })
      wrappers.set(wrapper, raw)
      return wrapper
    }
    const primitiveCleanup = new Map<unknown, () => void>()
    const lease = new Proxy(native, { get(target, property) {
      if (property === 'remove') return release
      if (property === 'timeScale') return () => timeScale
      if (property === 'addPane') return () => {
        if (!active) return
        return target.panes()[paneIndex++] ?? target.addPane()
      }
      if (property === 'addSeries') return (definition: any, settings: any, pane = 0) => {
        if (!active) throw new Error('DETAIL_CHART_LEASE_EXPIRED')
        const role = definition.type === 'Candlestick' ? 'candles' : definition.type === 'Histogram' && settings?.priceScaleId === 'volume' ? 'volume' : null
        let raw = role ? prices.get(role) : undefined
        if (!raw) {
          raw = target.addSeries(definition, settings, pane)
          if (role) prices.set(role, raw)
          else series.add(raw)
        } else {
          // Every adapter shares the main-pane volume overlay.
          if (role === 'volume' && raw.getPane().paneIndex() !== pane) raw.moveToPane(pane)
          raw.applyOptions(role === 'volume' ? { ...settings, priceScaleId: settings?.priceScaleId ?? 'right' } : settings ?? {})
        }
        return wrapSeries(raw, role ?? undefined)
      }
      if (property === 'setCrosshairPosition') return (price: number, time: Time, item: ISeriesApi<SeriesType, Time>) => {
        if (active) target.setCrosshairPosition(price, time, wrappers.get(item) ?? item)
      }
      if (property === 'removeSeries') return (item: ISeriesApi<SeriesType, Time>) => {
        const raw = wrappers.get(item) ?? item
        if (active && series.delete(raw)) target.removeSeries(raw)
      }
      return member(target, property)
    } })
    owners.set(lease, session)
    volumeInputs.set(lease, incoming => active ? mergeVolumeBars(incoming) : incoming)
    return lease
  }
  function dispose() {
    if (disposed) return
    releaseActive?.(); disposed = true
    chart?.remove(); chart = null; surface = null; prices.clear(); writers.clear(); pricePoints.clear(); volumeInput = []; viewports.clear()
  }
  const session = { acquire, setIdentity, viewport, resetWindow, indexOf, length, timeAt, mergeVolumeBars, dispose }
  return session
}
