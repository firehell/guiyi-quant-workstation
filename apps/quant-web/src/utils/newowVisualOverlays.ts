// Display-only projections of accepted completed OHLC and BUILD reference prices.
// These values never feed a strategy, trade pairing, or performance calculation.
export interface VisualOverlayPreferences { donchian: boolean; window: number; stop: boolean }
const key = 'guiyi:newow:visual-overlays:v1'
export const validDonchianWindow = (value: number): boolean => Number.isInteger(value) && value >= 5 && value <= 120
export function readVisualOverlayPreferences(): VisualOverlayPreferences {
  const defaults = { donchian: false, window: 20, stop: false }
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(key) ?? 'null')
    return { donchian: value?.donchian === true, stop: value?.stop === true, window: validDonchianWindow(value?.window) ? value.window : 20 }
  } catch { return defaults }
}
export function saveVisualOverlayPreferences(value: VisualOverlayPreferences): void {
  try { globalThis.localStorage?.setItem(key, JSON.stringify(value)) } catch { /* storage can be disabled */ }
}
export interface VisualOverlayBar { time: string; high: number; low: number; owner: string }
export function visualDonchian(bars: readonly VisualOverlayBar[], window: number): Array<{ time: string; upper: number | null; lower: number | null }> {
  if (!validDonchianWindow(window)) return []
  let segment: VisualOverlayBar[] = []
  return bars.map(bar => {
    if (segment.at(-1)?.owner !== bar.owner) segment = []
    if (!Number.isFinite(bar.high) || !Number.isFinite(bar.low) || bar.high < bar.low) { segment = []; return { time: bar.time, upper: null, lower: null } }
    segment.push(bar)
    if (segment.length > window) segment.shift()
    return { time: bar.time, upper: segment.length < window ? null : Math.max(...segment.map(x => x.high)), lower: segment.length < window ? null : Math.min(...segment.map(x => x.low)) }
  })
}
export interface VisualBuildAnchor { time: string; owner: string; price: string; action: string }
export function visibleBuildStop(anchors: readonly VisualBuildAnchor[], visible: readonly { time: string; owner: string }[], pct: number): number | null {
  const owner = visible.at(-1)?.owner
  if (!owner) return null
  const accepted = new Set(visible.filter(bar => bar.owner === owner).map(bar => bar.time))
  const anchor = anchors.filter(a => a.action === 'BUILD' && a.owner === owner && accepted.has(a.time)).sort((a,b) => Date.parse(a.time)-Date.parse(b.time)).at(-1)
  if (!anchor || !/^\d+(\.\d+)?$/.test(anchor.price)) return null
  const price = Number(anchor.price)
  return Number.isFinite(price) && price > 0 ? price * (1 - pct) : null
}

// Retain only an observed BUILD from the same view identity and calculation owner.
export interface RetainedBuildStop { scope: string; anchor: VisualBuildAnchor }
export function retainBuildStop(previous: RetainedBuildStop | null, scope: string, anchors: readonly VisualBuildAnchor[], visible: readonly { time: string; owner: string }[]): RetainedBuildStop | null {
  const owner = visible.at(-1)?.owner
  if (!owner) return null
  const times = new Set(visible.filter(b => b.owner === owner).map(b => b.time))
  const candidate = anchors.filter(a => a.action === 'BUILD' && a.owner === owner && times.has(a.time)).sort((a,b) => Date.parse(a.time)-Date.parse(b.time)).at(-1)
  if (candidate) return visibleBuildStop([candidate], visible, 0.07) === null ? null : { scope, anchor: { ...candidate } }
  if (previous?.scope !== scope || previous.anchor.owner !== owner) return null
  return anchors.some(a => a.action === 'BUILD' && a.owner === owner && a.time === previous.anchor.time && a.price === previous.anchor.price) ? previous : null
}
export function retainedStopPrice(value: RetainedBuildStop | null, pct: number): number | null {
  return value ? visibleBuildStop([value.anchor], [{ time: value.anchor.time, owner: value.anchor.owner }], pct) : null
}
