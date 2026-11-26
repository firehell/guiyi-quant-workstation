import {
  CandlestickSeries, HistogramSeries, LineSeries, createChart, createSeriesMarkers,
  type CandlestickSeriesPartialOptions, type HistogramSeriesPartialOptions, type IChartApi,
  type ISeriesApi, type ISeriesMarkersPluginApi, type ISeriesPrimitive, type LineSeriesPartialOptions,
  type CreatePriceLineOptions, type SeriesMarker, type SeriesType, type Time,
} from 'lightweight-charts'
import { CHART_MANIFEST, DISPLAY_CATALOG, type RendererId } from './catalog.js'

export const MAX_AUXILIARY_PANES = 3
export type ChartPane = 'main' | 'volume' | { auxiliary: string }
export type LayerStatus = 'ready' | 'hidden' | 'loading' | 'missing_input' | 'warming'
  | 'invalid_source' | 'compute_error' | 'catalog_mismatch' | 'renderer_failure' | 'retired'
export interface LayerDiagnostics {
  indicatorId: string
  packageVersion: string
  formulaVersion: string | null
  sourceIdentity: string | null
  frequency: string | null
  pane: ChartPane
  renderer: RendererId
  status: LayerStatus
  warmup: { available: number; required: number } | null
  dataCutoff: string | null
  cacheState: string | null
  lastError: string | null
  updatedAt: string
}

function resourceScope() {
  const disposers = new Set<() => void>()
  let disposed = false
  function assertActive() {
    if (disposed) throw new Error('CHART_RESOURCE_SCOPE_EXPIRED')
  }
  return {
    assertActive,
    own(dispose: () => void) {
      assertActive()
      const release = () => { if (disposers.delete(release)) dispose() }
      disposers.add(release)
      return release
    },
    dispose() {
      if (disposed) return
      disposed = true
      let firstError: unknown
      for (const dispose of [...disposers].reverse()) {
        try { dispose() } catch (error) { firstError ??= error }
      }
      if (firstError !== undefined) throw firstError
    },
  }
}

export function mountChartHost(
  container: HTMLElement,
  options: Parameters<typeof createChart>[1],
  acquire: (container: HTMLElement, options: Parameters<typeof createChart>[1]) => IChartApi = createChart,
): ChartHost {
  return createChartHost(acquire(container, options))
}

export type ChartHost = ReturnType<typeof createChartHost>
export type ChartLayer = ReturnType<ChartHost['layer']>

export const RENDERER_REGISTRY = Object.freeze({
  candles: 'candles', line: 'line', histogram: 'histogram', band: 'band', marker: 'markers',
  price_level_zone: 'priceLevel', primitive: 'primitive',
} as const satisfies Record<RendererId, keyof ChartLayer>)

type MarkerFactory = <T extends Time>(series: never, markers?: SeriesMarker<T>[]) => ISeriesMarkersPluginApi<T>

export function createChartHost(chart: IChartApi) {
  const scope = resourceScope()
  const layers = new Map<string, { pane: ChartPane; generationBound: boolean; handles: ReturnType<typeof makeLayer> }>()
  const failures = new Map<string, LayerDiagnostics>()
  const auxiliaries: string[] = []
  let generation = 0
  let identity: string | null = null
  let disposed = false

  function paneIndex(pane: ChartPane) {
    if (typeof pane === 'string') return 0
    const index = auxiliaries.indexOf(pane.auxiliary)
    if (index < 0) throw new Error('CHART_AUXILIARY_PANE_MISSING')
    return index + 1
  }

  function addAuxiliary(id: string) {
    if (disposed) throw new Error('CHART_HOST_DISPOSED')
    if (!auxiliaries.includes(id)) {
      if (auxiliaries.length >= MAX_AUXILIARY_PANES) throw new Error('CHART_AUXILIARY_PANE_LIMIT')
      auxiliaries.push(id)
    }
    return { auxiliary: id } as const
  }

  function makeLayer(indicatorId: string, pane: ChartPane) {
    const resources = resourceScope()
    const definition = DISPLAY_CATALOG[indicatorId]
    if (!Object.hasOwn(DISPLAY_CATALOG, indicatorId) || !definition) throw new Error(`CHART_DISPLAY_NOT_REGISTERED: ${indicatorId}`)
    const area = typeof pane === 'string' ? pane : 'auxiliary'
    if (definition.pane !== area) throw new Error(`CHART_DISPLAY_PANE_MISMATCH: ${indicatorId}`)
    if (definition.retired) throw new Error(`CHART_DISPLAY_RETIRED: ${indicatorId}`)
    let diagnostic = initialDiagnostics(indicatorId, pane, definition.renderers[0])
    const owned = new Map<object, () => void>()
    function remember<T extends object>(item: T, dispose: () => void): T {
      owned.set(item, resources.own(() => {
        owned.delete(item)
        dispose()
      }))
      return item
    }
    function remove(item: object): void {
      const dispose = owned.get(item)
      owned.delete(item)
      dispose?.()
    }
    return {
      own: resources.own,
      dispose: resources.dispose,
      remove,
      inspect: () => ({ ...diagnostic }),
      updateDiagnostics(patch: Partial<Omit<LayerDiagnostics, 'indicatorId' | 'packageVersion' | 'pane'>>) {
        diagnostic = { ...diagnostic, ...patch, updatedAt: new Date().toISOString() }
      },
      candles(options: CandlestickSeriesPartialOptions) {
        resources.assertActive()
        const series = chart.addSeries(CandlestickSeries, options, paneIndex(pane))
        return remember(series, () => chart.removeSeries(series))
      },
      line(options: LineSeriesPartialOptions) {
        resources.assertActive()
        const series = chart.addSeries(LineSeries, options, paneIndex(pane))
        return remember(series, () => chart.removeSeries(series))
      },
      histogram(options: HistogramSeriesPartialOptions) {
        resources.assertActive()
        const series = chart.addSeries(HistogramSeries, options, paneIndex(pane))
        return remember(series, () => chart.removeSeries(series))
      },
      band(upper: LineSeriesPartialOptions, lower: LineSeriesPartialOptions) {
        resources.assertActive()
        const index = paneIndex(pane)
        const top = chart.addSeries(LineSeries, upper, index)
        remember(top, () => chart.removeSeries(top))
        const bottom = chart.addSeries(LineSeries, lower, index)
        return { upper: top, lower: remember(bottom, () => chart.removeSeries(bottom)) }
      },
      markers(series: ISeriesApi<SeriesType>, factory: MarkerFactory = createSeriesMarkers) {
        resources.assertActive()
        // Lightweight Charts attaches inside the factory before a plugin handle
        // exists. Keep enough information to roll back a partial attachment.
        const attempted = new Set<ISeriesPrimitive<Time>>()
        let constructing = true
        const target = new Proxy(series, {
          get(native, property) {
            if (property === 'attachPrimitive') return (primitive: ISeriesPrimitive<Time>) => {
              if (constructing) attempted.add(primitive)
              native.attachPrimitive(primitive)
            }
            if (property === 'detachPrimitive') return (primitive: ISeriesPrimitive<Time>) => {
              native.detachPrimitive(primitive)
              attempted.delete(primitive)
            }
            const value = Reflect.get(native, property)
            return typeof value === 'function' ? value.bind(native) : value
          },
        })
        try {
          const plugin = factory(target as never)
          return remember(plugin, () => plugin.detach?.())
        } catch (error) {
          for (const primitive of attempted) resources.own(() => series.detachPrimitive(primitive))
          throw error
        } finally {
          constructing = false
          attempted.clear()
        }
      },
      priceLevel(series: ISeriesApi<SeriesType>, options: CreatePriceLineOptions) {
        resources.assertActive()
        const line = series.createPriceLine(options)
        if (line) remember(line, () => series.removePriceLine(line))
        return line
      },
      primitive<T extends ISeriesPrimitive<Time>>(series: ISeriesApi<SeriesType>, primitive: T) {
        resources.assertActive()
        remember(primitive, () => series.detachPrimitive(primitive))
        series.attachPrimitive(primitive)
        return primitive
      },
    }
  }

  function initialDiagnostics(indicatorId: string, pane: ChartPane, renderer: RendererId): LayerDiagnostics {
    return {
      indicatorId, pane, renderer, status: 'missing_input',
      packageVersion: CHART_MANIFEST.version, formulaVersion: null, sourceIdentity: identity,
      frequency: null, warmup: null, dataCutoff: null, cacheState: null, lastError: null,
      updatedAt: new Date().toISOString(),
    }
  }

  function samePane(left: ChartPane, right: ChartPane): boolean {
    return typeof left === 'string' || typeof right === 'string' ? left === right : left.auxiliary === right.auxiliary
  }

  function layer(id: string, indicatorId: string, pane: ChartPane, generationBound = false) {
    if (disposed) throw new Error('CHART_HOST_DISPOSED')
    const existing = layers.get(id)
    if (existing) {
      if (existing.handles.inspect().indicatorId !== indicatorId || !samePane(existing.pane, pane)) {
        throw new Error(`CHART_LAYER_IDENTITY_CONFLICT: ${id}`)
      }
      return existing.handles
    }
    const handles = makeLayer(indicatorId, pane)
    layers.set(id, { pane, generationBound, handles })
    return handles
  }

  function removeLayer(id: string) {
    const existing = layers.get(id)
    failures.delete(id)
    layers.delete(id)
    existing?.handles.dispose()
  }

  /**
   * Mount or update one optional layer. A failing render drops all of that layer's
   * native resources and leaves an inspectable row until the layer is retried or removed.
   */
  function renderLayer(
    id: string, indicatorId: string, pane: ChartPane, renderer: RendererId,
    render: (handle: ChartLayer) => void,
  ): boolean {
    if (disposed) throw new Error('CHART_HOST_DISPOSED')
    const definition = Object.hasOwn(DISPLAY_CATALOG, indicatorId) ? DISPLAY_CATALOG[indicatorId] : undefined
    const area = typeof pane === 'string' ? pane : 'auxiliary'
    const current = layers.get(id)
    const sameBinding = current && current.handles.inspect().indicatorId === indicatorId && samePane(current.pane, pane)
    const catalogError = !definition ? 'CHART_DISPLAY_NOT_REGISTERED'
      : definition.retired ? 'CHART_DISPLAY_RETIRED'
      : definition.pane !== area ? 'CHART_DISPLAY_PANE_MISMATCH'
      : !definition.renderers.includes(renderer) ? 'CHART_DISPLAY_RENDERER_MISMATCH'
      : typeof pane !== 'string' && !auxiliaries.includes(pane.auxiliary) ? 'CHART_AUXILIARY_PANE_MISSING'
      : current && !sameBinding ? 'CHART_LAYER_IDENTITY_CONFLICT' : null
    let status: LayerStatus = definition?.retired ? 'retired' : 'catalog_mismatch'
    let lastError = catalogError
    if (!catalogError) {
      try {
        render(layer(id, indicatorId, pane))
        failures.delete(id)
        return true
      } catch {
        status = 'renderer_failure'
        lastError = 'CHART_RENDERER_UPDATE_FAILED'
      }
    }
    try {
      removeLayer(id)
    } catch {
      status = 'renderer_failure'
      lastError = 'CHART_RENDERER_CLEANUP_FAILED'
    }
    failures.set(id, {
      ...initialDiagnostics(indicatorId, pane, renderer), status, lastError, sourceIdentity: null,
    })
    return false
  }

  function removeAuxiliary(id: string) {
    const index = auxiliaries.indexOf(id)
    if (index < 0) return
    for (const [layerId, layer] of [...layers].reverse()) {
      if (typeof layer.pane !== 'string' && layer.pane.auxiliary === id) removeLayer(layerId)
    }
    for (const [layerId, failure] of failures) {
      if (samePane(failure.pane, { auxiliary: id })) failures.delete(layerId)
    }
    // Lightweight Charts drops the empty pane when its last series is removed.
    auxiliaries.splice(index, 1)
  }

  function orderAuxiliaries(order: readonly string[]): void {
    if (order.length !== auxiliaries.length || new Set(order).size !== order.length || order.some(id => !auxiliaries.includes(id))) {
      throw new Error('CHART_AUXILIARY_ORDER_MISMATCH')
    }
    for (const [index, id] of order.entries()) {
      const current = auxiliaries.indexOf(id)
      if (current === index) continue
      chart.swapPanes(index + 1, current + 1)
      ;[auxiliaries[index], auxiliaries[current]] = [auxiliaries[current], auxiliaries[index]]
    }
  }

  return {
    chart,
    own: scope.own,
    addAuxiliary,
    removeAuxiliary,
    orderAuxiliaries,
    paneIndex,
    hasLayer: (id: string) => layers.has(id),
    layer,
    renderLayer,
    removeLayer,
    activate(identityKey: string) {
      if (identity !== identityKey) {
        for (const [id, layer] of layers) if (layer.generationBound) removeLayer(id)
        failures.clear()
        identity = identityKey
        generation += 1
      }
      return generation
    },
    isCurrent(token: number) { return !disposed && token === generation },
    inspectLayer(id: string) {
      const failure = failures.get(id)
      return failure ? { ...failure } : layers.get(id)?.handles.inspect() ?? null
    },
    diagnostics() {
      return [
        ...[...layers].flatMap(([id, layer]) => failures.has(id) ? [] : [layer.handles.inspect()]),
        ...[...failures.values()].map(failure => ({ ...failure })),
      ]
    },
    dispose() {
      if (disposed) return
      disposed = true
      const cleanup = resourceScope()
      cleanup.own(() => chart.remove())
      for (const id of layers.keys()) cleanup.own(() => removeLayer(id))
      cleanup.own(() => scope.dispose())
      try { cleanup.dispose() } finally { auxiliaries.length = 0; failures.clear() }
    },
  }
}
