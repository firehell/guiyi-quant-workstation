import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

/** Keep Lightweight Charts' reference-based view caches stable across frames. */
export function guardPrimitivePaint(primitive: ISeriesPrimitive<Time>, onFailure: () => void, trackMarkerSubscriptions = false) {
  let stopped = false
  const viewLists = new WeakMap<readonly IPrimitivePaneView[], readonly IPrimitivePaneView[]>()
  const views = new WeakMap<IPrimitivePaneView, IPrimitivePaneView>()
  const renderers = new WeakMap<IPrimitivePaneRenderer, IPrimitivePaneRenderer>()
  const subscriptions = new Map<object, () => void>()

  function markerAttachment(parameters: SeriesAttachedParameter<Time>): SeriesAttachedParameter<Time> {
    const series = new Proxy(parameters.series, {
      get(native, property) {
        if (property === 'subscribeDataChanged') return (handler: Parameters<typeof native.subscribeDataChanged>[0]) => {
          subscriptions.set(handler, () => native.unsubscribeDataChanged(handler))
          native.subscribeDataChanged(handler)
        }
        if (property === 'unsubscribeDataChanged') return (handler: Parameters<typeof native.unsubscribeDataChanged>[0]) => {
          native.unsubscribeDataChanged(handler)
          subscriptions.delete(handler)
        }
        const value = Reflect.get(native, property)
        return typeof value === 'function' && property !== 'constructor' ? value.bind(native) : value
      },
    })
    return { ...parameters, series }
  }

  function attempt<T>(run: () => T, fallback: T): T {
    if (stopped) return fallback
    try {
      return run()
    } catch {
      stopped = true
      onFailure()
      return fallback
    }
  }

  function guardedRenderer(renderer: IPrimitivePaneRenderer): IPrimitivePaneRenderer {
    let guarded = renderers.get(renderer)
    if (!guarded) {
      guarded = {
        draw: (target, utils) => attempt(() => renderer.draw(protectCanvasTarget(target), utils), undefined),
        drawBackground: renderer.drawBackground
          ? (target, utils) => attempt(() => renderer.drawBackground!(protectCanvasTarget(target), utils), undefined)
          : undefined,
      }
      renderers.set(renderer, guarded)
    }
    return guarded
  }

  function guardedView(view: IPrimitivePaneView): IPrimitivePaneView {
    let guarded = views.get(view)
    if (!guarded) {
      guarded = {
        zOrder: view.zOrder ? () => attempt(() => view.zOrder!(), 'normal') : undefined,
        renderer: () => {
          const renderer = attempt(() => view.renderer(), null)
          return renderer ? guardedRenderer(renderer) : null
        },
      }
      views.set(view, guarded)
    }
    return guarded
  }

  const empty: readonly IPrimitivePaneView[] = []
  const guarded = new Proxy(primitive, {
    get(target, property) {
      switch (property) {
        case 'attached':
          return target.attached && ((parameters: SeriesAttachedParameter<Time>) =>
            target.attached!(trackMarkerSubscriptions ? markerAttachment(parameters) : parameters))
        case 'paneViews':
        case 'priceAxisPaneViews':
        case 'timeAxisPaneViews': {
          const getViews = target[property]
          return getViews && (() => attempt(() => {
            const original = getViews.call(target)
            let guarded = viewLists.get(original)
            if (!guarded) {
              guarded = original.map(guardedView)
              viewLists.set(original, guarded)
            }
            return guarded
          }, empty))
        }
        case 'updateAllViews':
          return target.updateAllViews && (() => attempt(() => target.updateAllViews!(), undefined))
        case 'autoscaleInfo':
          return target.autoscaleInfo && ((...args: Parameters<NonNullable<ISeriesPrimitive<Time>['autoscaleInfo']>>) =>
            attempt(() => target.autoscaleInfo!(...args), null))
        case 'hitTest':
          return target.hitTest && ((...args: Parameters<NonNullable<ISeriesPrimitive<Time>['hitTest']>>) =>
            attempt(() => target.hitTest!(...args), null))
        default: {
          const value = Reflect.get(target, property)
          return typeof value === 'function' && property !== 'constructor' ? value.bind(target) : value
        }
      }
    },
  })
  return {
    primitive: guarded,
    stop() { stopped = true },
    releaseSubscriptions() {
      let firstError: unknown
      for (const unsubscribe of subscriptions.values()) {
        try { unsubscribe() } catch (error) { firstError ??= error }
      }
      subscriptions.clear()
      if (firstError !== undefined) throw firstError
    },
  }
}

type PaintTarget = Parameters<IPrimitivePaneRenderer['draw']>[0]
const protectedTargets = new WeakMap<PaintTarget, PaintTarget>()

function protectCanvasTarget(target: PaintTarget): PaintTarget {
  let guarded = protectedTargets.get(target)
  if (!guarded) {
    guarded = new Proxy(target, {
      get(native, property) {
        if (property === 'useMediaCoordinateSpace') {
          const use = native.useMediaCoordinateSpace.bind(native)
          return <Result>(draw: (scope: Parameters<Parameters<PaintTarget['useMediaCoordinateSpace']>[0]>[0]) => Result) =>
            use(scope => withBalancedCanvasState(scope.context, () => draw(scope)))
        }
        if (property === 'useBitmapCoordinateSpace') {
          const use = native.useBitmapCoordinateSpace.bind(native)
          return <Result>(draw: (scope: Parameters<Parameters<PaintTarget['useBitmapCoordinateSpace']>[0]>[0]) => Result) =>
            use(scope => withBalancedCanvasState(scope.context, () => draw(scope)))
        }
        const value = Reflect.get(native, property)
        return typeof value === 'function' && property !== 'constructor' ? value.bind(native) : value
      },
    })
    protectedTargets.set(target, guarded)
  }
  return guarded
}

// Fancy Canvas restores its own state. Unwind any extra saves the renderer
// left on top of it when a native canvas call threw.
function withBalancedCanvasState<Result>(context: CanvasRenderingContext2D, draw: () => Result): Result {
  const save = context.save
  const restore = context.restore
  const priorSave = Object.getOwnPropertyDescriptor(context, 'save')
  const priorRestore = Object.getOwnPropertyDescriptor(context, 'restore')
  let depth = 0
  try {
    context.save = () => { save.call(context); depth++ }
    context.restore = () => {
      if (depth === 0) return
      restore.call(context)
      depth--
    }
    return draw()
  } finally {
    try {
      for (; depth > 0; depth--) restore.call(context)
    } finally {
      if (priorSave) Object.defineProperty(context, 'save', priorSave)
      else Reflect.deleteProperty(context, 'save')
      if (priorRestore) Object.defineProperty(context, 'restore', priorRestore)
      else Reflect.deleteProperty(context, 'restore')
    }
  }
}
