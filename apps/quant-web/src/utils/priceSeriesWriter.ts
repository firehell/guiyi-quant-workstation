/** Keep one last price projection, avoiding chart resets for overlay-only changes.
 * Historical corrections, prepends and identity changes always replace the series.
 */
export function createPriceSeriesWriter<T extends { time: unknown }>() {
  let previous: readonly T[] = []
  let owner: unknown
  let identity = ''
  function equal(a: T, b: T) {
    const keys = Object.keys(a) as Array<keyof T>
    return keys.length === Object.keys(b).length && keys.every(key =>
      key === 'time' ? JSON.stringify(a.time) === JSON.stringify(b.time) : Object.is(a[key], b[key]))
  }
  return {
    write(series: { setData: (points: T[]) => void; update: (point: T) => void }, points: T[], key = '') {
      const sameOwner = owner === series && identity === key
      const shared = Math.min(previous.length, points.length)
      let common = 0
      if (sameOwner) while (common < shared && equal(previous[common]!, points[common]!)) common++
      if (!sameOwner || common !== points.length || points.length !== previous.length) {
        const lastOnly = sameOwner && previous.length > 0 && (
          points.length === previous.length && common === points.length - 1
            && JSON.stringify(points.at(-1)!.time) === JSON.stringify(previous.at(-1)!.time)
          || points.length === previous.length + 1 && common === previous.length
        )
        if (lastOnly) series.update(points.at(-1)!)
        else series.setData(points)
      }
      previous = points; owner = series; identity = key
    },
  }
}
