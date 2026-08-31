import type { BarData } from '@/types/market'

export type RangeDetectorState = 'intact' | 'broken_up' | 'broken_down'
export type RangeDetectorTransitionKind = 'confirmed' | 'revised' | 'broken_up' | 'broken_down' | 'invalid_reset'
export interface RangeDetectorLuxOptions { sourceIdentity: string; minimumRangeLength?: number; rangeWidthAtrMultiplier?: number; rangeAtrLength?: number; roundDigits?: number }
export interface RangeDetectorSnapshot { formulaVersion: 'range_detector_lux_v1'; policyId: 'range_detector_lux_v1'; rangeId: string; revision: number; visualStartAt: string; confirmedAt: string; detectionRightAt: string; levelsActiveFrom: string; initialUpper: number; initialLower: number; currentUpper: number; currentLower: number; currentMid: number; state: RangeDetectorState; brokenAt: string | null; mergedCount: number; candidateValid: boolean; sourceBarEnd: string; sourceTradingDay: string | null; sourceIdentity: string }
export interface RangeDetectorPoint { time: string; ready: boolean; valid: boolean; reason: string | null; snapshot: RangeDetectorSnapshot | null; transition: { kind: RangeDetectorTransitionKind; rangeId: string | null; revision: number | null; at: string } | null }
export interface RangeDetectorVisualRange { key: string; rangeId: string; revision: number; visualStartAt: string; detectionRightAt: string; levelsActiveFrom: string; levelsActiveUntil: string | null; confirmedAt: string; upper: number; lower: number; mid: number; state: RangeDetectorState; brokenAt: string | null }
export interface RangeDetectorLuxResult { points: RangeDetectorPoint[]; ranges: RangeDetectorVisualRange[] }

interface Atr { seed: number[]; previousClose: number | null; previous: number | null }
interface Active { snapshot: RangeDetectorSnapshot | null; detectionRightIndex: number | null }

export function calculateRangeDetectorLux(bars: BarData[], options: RangeDetectorLuxOptions): RangeDetectorLuxResult {
  const minimumRangeLength = options.minimumRangeLength ?? 20
  const rangeWidthAtrMultiplier = options.rangeWidthAtrMultiplier ?? 1
  const rangeAtrLength = options.rangeAtrLength ?? 500
  const roundDigits = options.roundDigits ?? 6
  if (!options.sourceIdentity?.trim()) throw new Error('sourceIdentity must be non-empty')
  if (!Number.isInteger(minimumRangeLength) || minimumRangeLength < 2) throw new Error('minimumRangeLength must be at least 2')
  if (!Number.isInteger(rangeAtrLength) || rangeAtrLength <= 0) throw new Error('rangeAtrLength must be positive')
  if (!Number.isFinite(rangeWidthAtrMultiplier) || rangeWidthAtrMultiplier <= 0) throw new Error('rangeWidthAtrMultiplier must be finite and positive')
  if (!Number.isInteger(roundDigits) || roundDigits < 0) throw new Error('roundDigits must be non-negative')

  const points: RangeDetectorPoint[] = []
  let atr: Atr = { seed: [], previousClose: null, previous: null }
  let window: Array<{ time: string; tradingDay: string | null; close: number }> = []
  let previousCandidate = false
  let active: Active = { snapshot: null, detectionRightIndex: null }
  let lastTime: number | null = null
  for (let index = 0; index < bars.length; index += 1) {
    const bar = bars[index]
    const timestamp = parseTime(bar.time)
    if (lastTime !== null && timestamp <= lastTime) throw new Error('bar times must be strictly increasing')
    lastTime = timestamp
    const valid = Number.isFinite(bar.high) && Number.isFinite(bar.low) && Number.isFinite(bar.close) && bar.low <= bar.close && bar.close <= bar.high
    if (!valid) {
      atr = { seed: [], previousClose: null, previous: null }; window = []; previousCandidate = false; active = { snapshot: null, detectionRightIndex: null }
      points.push({ time: bar.time, ready: true, valid: false, reason: 'input_invalid', snapshot: null, transition: { kind: 'invalid_reset', rangeId: null, revision: null, at: bar.time } })
      continue
    }
    const tr = atr.previousClose === null ? bar.high - bar.low : Math.max(bar.high - bar.low, Math.abs(bar.high - atr.previousClose), Math.abs(bar.low - atr.previousClose))
    atr.seed = [...atr.seed, tr].slice(-rangeAtrLength); atr.previousClose = bar.close
    if (atr.previous === null) { if (atr.seed.length === rangeAtrLength) atr.previous = average(atr.seed) } else atr.previous = (atr.previous * (rangeAtrLength - 1) + tr) / rangeAtrLength
    window = [...window, { time: bar.time, tradingDay: bar.trading_day ?? null, close: bar.close }].slice(-(minimumRangeLength + 1))
    if (atr.previous === null || window.length !== minimumRangeLength + 1) {
      previousCandidate = false
      points.push({ time: bar.time, ready: false, valid: true, reason: 'warming_up', snapshot: null, transition: null })
      continue
    }
    const candidateWindow = window.slice(-minimumRangeLength); const center = average(candidateWindow.map((item) => item.close)); const width = atr.previous * rangeWidthAtrMultiplier
    const candidate = candidateWindow.every((item) => Math.abs(item.close - center) <= width)
    let snapshot = active.snapshot; let transition: RangeDetectorPoint['transition'] = null
    if (candidate && !previousCandidate) {
      const upper = rounded(center + width, roundDigits); const lower = rounded(center - width, roundDigits)
      const overlap = snapshot !== null && active.detectionRightIndex !== null && index - minimumRangeLength <= active.detectionRightIndex
      if (overlap && snapshot) {
        const currentUpper = Math.max(snapshot.currentUpper, upper); const currentLower = Math.min(snapshot.currentLower, lower)
        snapshot = { ...snapshot, revision: snapshot.revision + 1, confirmedAt: bar.time, detectionRightAt: bar.time, levelsActiveFrom: bar.time, currentUpper, currentLower, currentMid: rounded((currentUpper + currentLower) / 2, roundDigits), state: 'intact', brokenAt: null, mergedCount: snapshot.mergedCount + 1, candidateValid: true, sourceBarEnd: bar.time, sourceTradingDay: bar.trading_day ?? null }
        transition = { kind: 'revised', rangeId: snapshot.rangeId, revision: snapshot.revision, at: bar.time }
      } else {
        const rangeId = sha256(`range_detector_lux_v1|${options.sourceIdentity}|${bar.time}`)
        snapshot = { formulaVersion: 'range_detector_lux_v1', policyId: 'range_detector_lux_v1', rangeId, revision: 1, visualStartAt: window[0].time, confirmedAt: bar.time, detectionRightAt: bar.time, levelsActiveFrom: bar.time, initialUpper: upper, initialLower: lower, currentUpper: upper, currentLower: lower, currentMid: rounded(center, roundDigits), state: 'intact', brokenAt: null, mergedCount: 0, candidateValid: true, sourceBarEnd: bar.time, sourceTradingDay: bar.trading_day ?? null, sourceIdentity: options.sourceIdentity }
        transition = { kind: 'confirmed', rangeId, revision: 1, at: bar.time }
      }
      active.detectionRightIndex = index
    } else if (candidate && snapshot) { snapshot = { ...snapshot, detectionRightAt: bar.time, candidateValid: true, sourceBarEnd: bar.time, sourceTradingDay: bar.trading_day ?? null }; active.detectionRightIndex = index } else if (snapshot) snapshot = { ...snapshot, candidateValid: false, sourceBarEnd: bar.time, sourceTradingDay: bar.trading_day ?? null }
    if (snapshot?.state === 'intact' && bar.close > snapshot.currentUpper) { snapshot = { ...snapshot, state: 'broken_up', brokenAt: bar.time }; transition = { kind: 'broken_up', rangeId: snapshot.rangeId, revision: snapshot.revision, at: bar.time } }
    else if (snapshot?.state === 'intact' && bar.close < snapshot.currentLower) { snapshot = { ...snapshot, state: 'broken_down', brokenAt: bar.time }; transition = { kind: 'broken_down', rangeId: snapshot.rangeId, revision: snapshot.revision, at: bar.time } }
    active.snapshot = snapshot; previousCandidate = candidate
    points.push({ time: bar.time, ready: true, valid: true, reason: null, snapshot, transition })
  }
  return { points, ranges: visualRanges(points) }
}

function visualRanges(points: RangeDetectorPoint[]): RangeDetectorVisualRange[] {
  const snapshots = new Map<string, RangeDetectorSnapshot>(); const order: string[] = []; const terminal = new Map<string, string>(); let latest: string | null = null
  for (const point of points) {
    if (point.transition?.kind === 'invalid_reset') { if (latest) terminal.set(latest, point.time); latest = null }
    const snapshot = point.snapshot; if (!snapshot) continue; const key = `${snapshot.rangeId}:${snapshot.revision}`
    if (!snapshots.has(key)) { if (latest && latest !== key) terminal.set(latest, snapshot.levelsActiveFrom); order.push(key) }
    snapshots.set(key, snapshot); latest = key
  }
  return order.map((key) => { const item = snapshots.get(key)!; return { key, rangeId: item.rangeId, revision: item.revision, visualStartAt: item.visualStartAt, detectionRightAt: item.detectionRightAt, levelsActiveFrom: item.levelsActiveFrom, levelsActiveUntil: terminal.get(key) ?? null, confirmedAt: item.confirmedAt, upper: item.currentUpper, lower: item.currentLower, mid: item.currentMid, state: item.state, brokenAt: item.brokenAt } })
}
function parseTime(value: string): number { if (!value.includes('T') || Number.isNaN(Date.parse(value))) throw new Error('bar time must be ISO-8601'); return Date.parse(value) }
function average(values: number[]): number { return values.reduce((sum, value) => sum + value, 0) / values.length }
function rounded(value: number, digits: number): number { return Number(value.toFixed(digits)) }

function sha256(input: string): string {
  const bytes = Array.from(new TextEncoder().encode(input)); const bitLength = bytes.length * 8; bytes.push(0x80); while ((bytes.length % 64) !== 56) bytes.push(0); for (let shift = 56; shift >= 0; shift -= 8) bytes.push((bitLength / 2 ** shift) & 255)
  const hash = [1779033703, 3144134277, 1013904242, 2773480762, 1359893119, 2600822924, 528734635, 1541459225]; const constants = [1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,3329325298]
  for (let offset = 0; offset < bytes.length; offset += 64) { const words = Array(64).fill(0); for (let index = 0; index < 16; index += 1) words[index] = (bytes[offset + index * 4] << 24) | (bytes[offset + index * 4 + 1] << 16) | (bytes[offset + index * 4 + 2] << 8) | bytes[offset + index * 4 + 3]; for (let index = 16; index < 64; index += 1) { const a = words[index - 15]; const b = words[index - 2]; words[index] = (((a >>> 7 | a << 25) ^ (a >>> 18 | a << 14) ^ a >>> 3) + words[index - 7] + ((b >>> 17 | b << 15) ^ (b >>> 19 | b << 13) ^ b >>> 10) + words[index - 16]) | 0 } let [a,b,c,d,e,f,g,h] = hash; for (let index = 0; index < 64; index += 1) { const s1 = (e >>> 6 | e << 26) ^ (e >>> 11 | e << 21) ^ (e >>> 25 | e << 7); const choice = (e & f) ^ (~e & g); const temp1 = (h + s1 + choice + constants[index] + words[index]) | 0; const s0 = (a >>> 2 | a << 30) ^ (a >>> 13 | a << 19) ^ (a >>> 22 | a << 10); const majority = (a & b) ^ (a & c) ^ (b & c); [h,g,f,e,d,c,b,a] = [g,f,e,(d + temp1) | 0,c,b,a,(temp1 + s0 + majority) | 0] } hash[0]=(hash[0]+a)|0; hash[1]=(hash[1]+b)|0; hash[2]=(hash[2]+c)|0; hash[3]=(hash[3]+d)|0; hash[4]=(hash[4]+e)|0; hash[5]=(hash[5]+f)|0; hash[6]=(hash[6]+g)|0; hash[7]=(hash[7]+h)|0 }
  return hash.map((value) => (value >>> 0).toString(16).padStart(8, '0')).join('')
}
