import { paintFrozenOverlays } from './observationOverlay.ts'
import { DISPLAY_CATALOG } from '@guiyi/quant-chart'
import type { ObservationPane, ObservationSnapshot } from '../api/journalObservations'
import type { MarketDetailIdentity } from '../types/marketDetail'
import type { BarData } from '../types/market'
import { detailChartTime, type DetailChartSession, type ManualChartLevel } from './detailChartSession.ts'

export interface NewowObservationSource {
  kind: 'canonical_recompute' | 'formal_archive'
  trading_day: string
  cutoff: string
  revision: string
  receipt?: string | null
  market_input_sha256?: string
}

export function captureObservationPane(session: DetailChartSession, identity: MarketDetailIdentity,
  candidates: readonly BarData[], levels: readonly ManualChartLevel[], preferences: Record<string, unknown>,
  newow?: NewowObservationSource) {
  const viewport = session.captureViewport()
  if (!viewport) throw new Error('图表尚无可保存的行情视窗。')
  const byTime = new Map(candidates.map(b => [JSON.stringify(detailChartTime(b, identity.frequency)), b]))
  const ordered = viewport.points.map(point => {
    const bar = byTime.get(JSON.stringify(point.time))
    if (!bar || !bar.trading_day || !bar.physicalContract || (point.contract && point.contract !== bar.physicalContract)
      || point.open !== bar.open || point.high !== bar.high || point.low !== bar.low || point.close !== bar.close) {
      throw new Error('可见图表与行情身份正在切换，暂时无法冻结当前视窗。')
    }
    return { bar, x: point.x }
  })
  const visible = session.inspectDisplayedLayers().filter(d => d.status !== 'hidden')
  const preview = visible.filter(d => {
    if (d.status !== 'ready' || (d.indicatorId !== 'price_preview' && d.sourceStage !== 'active_preview')) return false
    const candidate = candidates.find(b => d.dataCutoff && Date.parse(d.dataCutoff) === Date.parse(b.time))
    return !candidate || viewport.includesTime(detailChartTime(candidate, identity.frequency))
  })
  const first = ordered[0]!.bar, lastCandle = ordered.at(-1)!.bar
  const lastPreview = candidates.find(bar => preview.some(layer => layer.dataCutoff && Date.parse(layer.dataCutoff) === Date.parse(bar.time)))
  // A separate preview candle can lead the primary series, including the first bar of a new trading day.
  const last = lastPreview?.physicalContract && lastPreview.trading_day && Date.parse(lastPreview.time) > Date.parse(lastCandle.time)
    ? lastPreview : lastCandle
  const onlyCanonical = !preview.length && !viewport.gaps.length && ordered.every(({ bar }, index) => {
    const rendered = viewport.points[index]!
    return bar.marketSource === 'canonical' && rendered.stage === 'canonical' && rendered.confirmed &&
      rendered.contract === bar.physicalContract && rendered.day === bar.trading_day && rendered.segment === bar.calculationSegmentId &&
      rendered.volume === bar.volume && rendered.drawnVolume === bar.volume && !!bar.sourceBarSha256 &&
      rendered.hash === bar.sourceBarSha256
  })
  if (identity.newowSource === 'canonical-recompute' && (!onlyCanonical || newow?.kind !== 'canonical_recompute'
    || Date.parse(last.time) > Date.parse(newow.cutoff))) throw new Error('复算图表输入尚未核验完成。')
  const pane: ObservationPane = {
    id: identity.frequency, frequency: identity.frequency, series_kind: identity.seriesKind,
    physical_contract: last.physicalContract!, window: { from: first.time, to: last.time },
    source: { view: identity.view, strategy: identity.strategy ?? null, mode: identity.newowMode ?? null,
      ...(newow ? { newow: { ...newow } } : {}), trading_day: last.trading_day, gap_coordinates: viewport.gaps,
      historical: onlyCanonical, preview_layers: preview.map(d => ({ id: d.indicatorId, cutoff: d.dataCutoff })), stages: [...new Set([...viewport.points.map(p => p.stage ?? 'unknown'), ...(preview.length ? ['active_preview'] : [])])],
      bars: onlyCanonical && ordered.length <= 500 ? ordered.map(({bar,x}) =>
        [bar.time, bar.sourceBarSha256, x, bar.physicalContract]) : [],
      segments: [...new Set(viewport.points.map(p => p.segment).filter(Boolean))] },
    indicators: visible.map(d => ({ id: d.indicatorId, version: d.formulaVersion, cutoff: d.dataCutoff,
      parameters: fixedParameters(d.indicatorId),
      source: { identity: d.sourceIdentity, status: d.status, stage: d.sourceStage, pane: d.pane,
        renderer: d.renderer, anchor: d.calculationAnchor, retrospective: DISPLAY_CATALOG[d.indicatorId]?.retrospective === true } })),
    drawings: levels.map(p => ({ ...p, kind: 'manual_horizontal' })),
    ranges: { logical: viewport.logical, pane_heights: viewport.heights, price_ranges: viewport.priceRanges, preferences: JSON.parse(JSON.stringify(preferences)) },
  }
  return { canvas: viewport.canvas, overlays: viewport.overlays, pane, tradingDay: last.trading_day! }
}

export function fixedParameters(id: string) {
  const match = /^ema_(10|21|60)$/.exec(id)
  if (match) return { period: Number(match[1]) }
  if (id === 'macd') return { fast: 12, slow: 26, signal: 9 }
  if (id === 'boll') return { period: 20, upper: 2, lower: 2 }
  return {}
}
export type PaneCapture = ReturnType<typeof captureObservationPane>

export async function freezeObservation(product: string, captured: PaneCapture[], activeId: string) {
  const active = captured.find(c => c.pane.id === activeId)
  if (!active || (captured.length !== 1 && captured.length !== 4)) throw new Error('等待当前选中周期和全部可见图表加载。')
  const width = Math.max(...captured.map(p => p.canvas.width)), header = 46
  const height = Math.max(...captured.map(p => p.canvas.height)) + header
  const cols = captured.length === 1 ? 1 : 2
  const canvas = document.createElement('canvas')
  // Keep storage bounded even on Retina screens while preserving the complete arrangement.
  const scale = Math.min(1, 2560 / (width * cols), 2160 / (height * (captured.length / cols)))
  canvas.width = Math.round(width * cols * scale)
  canvas.height = Math.round(height * captured.length / cols * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法生成原图。')
  ctx.scale(scale, scale)
  ctx.fillStyle = '#101720'; ctx.fillRect(0, 0, canvas.width / scale, canvas.height / scale)
  await Promise.all(captured.map(c => paintFrozenOverlays(c.canvas, c.overlays)))
  captured.forEach(({ canvas: image, pane }, i) => {
    const x = (i % cols) * width, y = Math.floor(i / cols) * height
    ctx.fillStyle = '#dee8f5'; ctx.font = '16px sans-serif'
    const source = pane.source.newow as NewowObservationSource | undefined
    const sourceLabel = source ? [source.kind === 'canonical_recompute' ? 'Canonical 历史复算' : '盘后归档',
      source.trading_day, source.revision.slice(0, 12)].join(' · ') : ''
    ctx.fillText([product.toUpperCase(), pane.physical_contract, pane.frequency, pane.source.view, pane.source.strategy, sourceLabel].filter(Boolean).join(' · '), x + 8, y + 18)
    ctx.font = '12px sans-serif'
    ctx.fillText(pane.indicators.map(d => (DISPLAY_CATALOG[d.id]?.label ?? d.id) + (d.source.retrospective ? '（回看重绘）' : '')).join(' · '), x + 8, y + 37, width - 16)
    ctx.drawImage(image, x, y + header)
    pane.ranges.image_rect = [x * scale / canvas.width, (y + header) * scale / canvas.height,
      image.width * scale / canvas.width, image.height * scale / canvas.height]
  })
  const snapshot: ObservationSnapshot = { schema_version: 1, captured_at: new Date().toISOString(), product: product.toUpperCase(),
    physical_contract: active.pane.physical_contract, active_pane: active.pane.id,
    layout: captured.length === 1 ? 'single' : 'quad', panes: captured.map(c => c.pane) }
  const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('无法编码原图。')), 'image/png'))
  return { snapshot, png, tradingDay: active.tradingDay }
}
