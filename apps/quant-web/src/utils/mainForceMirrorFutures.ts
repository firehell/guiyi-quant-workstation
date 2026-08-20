import type { BarData } from '@/types/market'

export const INDICATOR_CODE = 'main_force_mirror_futures_v1'
export const INDICATOR_VERSION = 'futures-research-v1'
export const PARAMETERS_HASH = 'f7fd0c9bce0b08d1'

export const DEFAULT_PARAMETERS = Object.freeze({
  atr_period: 14,
  volume_window: 20,
  oi_impulse_ema_period: 20,
  range_window: 20,
  pressure_divergence_window: 10,
  direction_price_weight: 0.7,
  direction_clv_weight: 0.3,
  direction_deadband: 0.15,
  oi_deadband: 0.25,
  volume_ratio_clip: 3,
  price_impulse_clip: 3,
  oi_impulse_clip: 3,
  strength_scale: 25,
  turnover_display_cap: 15,
  upper_location_threshold: 0.85,
  lower_location_threshold: 0.15,
  liquidation_dominated_oi_threshold: 0.5,
  pressure_confirmation_ratio: 0.7,
  high_volume_threshold: 1.5,
  clv_rejection_threshold: 0.25,
  wick_rejection_threshold: 0.35,
  caution_threshold: 70,
  rearm_score_threshold: 40,
  rearm_low_score_bars: 3,
  rearm_build_bars: 2,
  long_rearm_range_threshold: 0.65,
  short_rearm_range_threshold: 0.35,
  round_digits: 6,
  rounding_policy: 'half_away_from_zero_binary64',
} as const)

export type MainForceMirrorFuturesState =
  | 'long_build'
  | 'short_build'
  | 'short_cover'
  | 'long_liquidation'
  | 'turnover'

export type MainForceMirrorFuturesCaution =
  | 'long_chase_caution'
  | 'short_chase_caution'

export interface MainForceMirrorFuturesPoint {
  time: string
  physical_contract: string | null
  valid: boolean
  state_ready: boolean
  caution_ready: boolean
  ready: boolean
  reason: string | null
  caution_availability_reason: string | null
  state: MainForceMirrorFuturesState | null
  signed_score: number | null
  strength: number | null
  price_impulse: number | null
  clv: number | null
  volume_ratio: number | null
  delta_oi: number | null
  oi_impulse: number | null
  direction: number | null
  range_position: number | null
  long_open_pressure: number | null
  short_open_pressure: number | null
  long_caution_score: number | null
  short_caution_score: number | null
  caution: MainForceMirrorFuturesCaution | null
  caution_reason_codes: string[]
}

export interface MainForceMirrorFuturesResult {
  points: MainForceMirrorFuturesPoint[]
  metadata: {
    indicator_code: typeof INDICATOR_CODE
    indicator_version: typeof INDICATOR_VERSION
    parameters_hash: typeof PARAMETERS_HASH
    status: 'observation_only'
    supported_frequencies: readonly ['60m']
    supported_series_kinds: readonly ['contract', 'actual_dominant']
    future_looking: false
    repainting_risk: 'none'
    closed_bar_only: true
    confirmed_only: true
    web_capable: true
    backtest_capable: false
    live_capable: false
    alert_capable: false
    notification_capable: false
    parameters: typeof DEFAULT_PARAMETERS
    rounding_policy: typeof DEFAULT_PARAMETERS.rounding_policy
    interpretation: 'directional_position_pressure_proxy_not_measured_fund_flow'
    auto_order: false
  }
}

interface CautionEvidence {
  longScore: number
  shortScore: number
  reasonCodes: string[]
}

interface LatchState {
  longArmed: boolean
  shortArmed: boolean
  longLowScoreStreak: number
  shortLowScoreStreak: number
  longBuildStreak: number
  shortBuildStreak: number
}

const PHYSICAL_CONTRACT_MISSING = 'MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING'
const TIMESTAMP_INVALID = 'MFM_FUTURES_V1_TIMESTAMP_INVALID'
const OPEN_INTEREST_UNAVAILABLE = 'MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE'
const INPUT_INVALID = 'MFM_FUTURES_V1_INPUT_INVALID'
const WARMUP = 'MFM_FUTURES_V1_WARMUP'
const CAUTION_WARMUP = 'MFM_FUTURES_V1_CAUTION_WARMUP'
const ATR_INVALID = 'MFM_FUTURES_V1_ATR_INVALID'
const VOLUME_BASELINE_INVALID = 'MFM_FUTURES_V1_VOLUME_BASELINE_INVALID'
const RANGE_INVALID = 'MFM_FUTURES_V1_RANGE_INVALID'
const CAUTION_DIRECTION_CONFLICT = 'MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT'

export function roundHalfAwayFromZeroBinary64(value: number, digits: number): number {
  if (!Number.isFinite(value)) return value
  if (!Number.isInteger(digits) || digits < 0) {
    throw new Error('digits must be a non-negative integer')
  }
  const scale = 10 ** digits
  if (value === 0) return 0
  const magnitude = Math.floor(Math.abs(value) * scale + 0.5) / scale
  const result = Math.sign(value) * magnitude
  return result === 0 ? 0 : result
}

export function classifyMainForceMirrorFuturesState(
  direction: number,
  oiImpulse: number,
): MainForceMirrorFuturesState {
  if (
    Math.abs(direction) < DEFAULT_PARAMETERS.direction_deadband
    || Math.abs(oiImpulse) < DEFAULT_PARAMETERS.oi_deadband
  ) return 'turnover'
  if (direction >= DEFAULT_PARAMETERS.direction_deadband) {
    return oiImpulse >= DEFAULT_PARAMETERS.oi_deadband ? 'long_build' : 'short_cover'
  }
  return oiImpulse >= DEFAULT_PARAMETERS.oi_deadband ? 'short_build' : 'long_liquidation'
}

export function isMainForceMirrorFuturesCandidate(score: number): boolean {
  return score >= DEFAULT_PARAMETERS.caution_threshold
}

/** Browser-only observation mirror. Python remains the formula authority. */
export function calculateMainForceMirrorFutures(bars: BarData[]): MainForceMirrorFuturesResult {
  const count = bars.length
  const contracts: Array<string | null> = Array(count).fill(null)
  const valid = Array<boolean>(count).fill(false)
  const open = Array<number>(count).fill(Number.NaN)
  const high = Array<number>(count).fill(Number.NaN)
  const low = Array<number>(count).fill(Number.NaN)
  const close = Array<number>(count).fill(Number.NaN)
  const volume = Array<number>(count).fill(Number.NaN)
  const openInterest = Array<number>(count).fill(Number.NaN)
  const points = bars.map((bar) => emptyPoint(bar.time))
  let maxSeenParseableTime: number | null = null

  for (let index = 0; index < count; index += 1) {
    const bar = bars[index]
    const contract = normalizeContract(bar.physicalContract)
    contracts[index] = contract
    points[index].physical_contract = contract

    const parsedTime = parseTimestampMicros(bar.time)
    let timestampInvalid = parsedTime === null
    if (parsedTime !== null) {
      timestampInvalid = maxSeenParseableTime !== null && parsedTime <= maxSeenParseableTime
      if (maxSeenParseableTime === null || parsedTime > maxSeenParseableTime) {
        maxSeenParseableTime = parsedTime
      }
    }

    const openValue = finiteNumber(bar.open)
    const highValue = finiteNumber(bar.high)
    const lowValue = finiteNumber(bar.low)
    const closeValue = finiteNumber(bar.close)
    const volumeValue = finiteNumber(bar.volume)
    const oiValue = finiteNumber(bar.openInterest)
    open[index] = openValue ?? Number.NaN
    high[index] = highValue ?? Number.NaN
    low[index] = lowValue ?? Number.NaN
    close[index] = closeValue ?? Number.NaN
    volume[index] = volumeValue ?? Number.NaN
    openInterest[index] = oiValue ?? Number.NaN

    let invalidReason: string | null = null
    if (contract === null) invalidReason = PHYSICAL_CONTRACT_MISSING
    else if (timestampInvalid) invalidReason = TIMESTAMP_INVALID
    else if (oiValue === null || oiValue < 0) invalidReason = OPEN_INTEREST_UNAVAILABLE
    else if (!validOhlcv(openValue, highValue, lowValue, closeValue, volumeValue)) {
      invalidReason = INPUT_INVALID
    }
    if (invalidReason !== null) {
      points[index].reason = invalidReason
      continue
    }
    valid[index] = true
    points[index].valid = true
  }

  let index = 0
  while (index < count) {
    if (!valid[index]) {
      index += 1
      continue
    }
    const start = index
    const contract = contracts[start]
    while (
      index + 1 < count
      && valid[index + 1]
      && contracts[index + 1] === contract
    ) index += 1
    const end = index + 1
    applyBlock({
      start,
      end,
      open,
      high,
      low,
      close,
      volume,
      openInterest,
      points,
    })
    index = end
  }

  return {
    points,
    metadata: {
      indicator_code: INDICATOR_CODE,
      indicator_version: INDICATOR_VERSION,
      parameters_hash: PARAMETERS_HASH,
      status: 'observation_only',
      supported_frequencies: ['60m'],
      supported_series_kinds: ['contract', 'actual_dominant'],
      future_looking: false,
      repainting_risk: 'none',
      closed_bar_only: true,
      confirmed_only: true,
      web_capable: true,
      backtest_capable: false,
      live_capable: false,
      alert_capable: false,
      notification_capable: false,
      parameters: DEFAULT_PARAMETERS,
      rounding_policy: DEFAULT_PARAMETERS.rounding_policy,
      interpretation: 'directional_position_pressure_proxy_not_measured_fund_flow',
      auto_order: false,
    },
  }
}

function applyBlock(input: {
  start: number
  end: number
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume: number[]
  openInterest: number[]
  points: MainForceMirrorFuturesPoint[]
}): void {
  const { start, end, points } = input
  const blockOpen = input.open.slice(start, end)
  const blockHigh = input.high.slice(start, end)
  const blockLow = input.low.slice(start, end)
  const blockClose = input.close.slice(start, end)
  const blockVolume = input.volume.slice(start, end)
  const blockOi = input.openInterest.slice(start, end)
  const atr = wilderAtr14(blockHigh, blockLow, blockClose)
  const volumeMean = rollingMean(blockVolume, DEFAULT_PARAMETERS.volume_window)
  const rangeHigh = rollingExtreme(blockHigh, DEFAULT_PARAMETERS.range_window, Math.max)
  const rangeLow = rollingExtreme(blockLow, DEFAULT_PARAMETERS.range_window, Math.min)
  const oiDelta = blockOi.slice(1).map((value, oiIndex) => value - blockOi[oiIndex])
  const oiBaseline = emaSmaSeed(
    oiDelta.map((value) => Math.abs(value)),
    DEFAULT_PARAMETERS.oi_impulse_ema_period,
  )
  const rawLongPressures = Array<number>(end - start).fill(Number.NaN)
  const rawShortPressures = Array<number>(end - start).fill(Number.NaN)
  let latch = initialLatchState()

  for (let blockIndex = 0; blockIndex < end - start; blockIndex += 1) {
    const outputIndex = start + blockIndex
    const point = points[outputIndex]
    point.caution_availability_reason = CAUTION_WARMUP
    if (blockIndex < 20) {
      point.reason = WARMUP
      continue
    }
    if (!Number.isFinite(atr[blockIndex]) || atr[blockIndex] <= 0) {
      point.reason = ATR_INVALID
      continue
    }
    if (!Number.isFinite(volumeMean[blockIndex]) || volumeMean[blockIndex] <= 0) {
      point.reason = VOLUME_BASELINE_INVALID
      continue
    }
    if (
      !Number.isFinite(rangeHigh[blockIndex])
      || !Number.isFinite(rangeLow[blockIndex])
      || rangeHigh[blockIndex] === rangeLow[blockIndex]
    ) {
      point.reason = RANGE_INVALID
      continue
    }
    const oiBaselineIndex = blockIndex - 1
    if (oiBaselineIndex < 0 || !Number.isFinite(oiBaseline[oiBaselineIndex])) {
      point.reason = WARMUP
      continue
    }

    point.state_ready = true
    point.reason = null
    const rawPriceImpulse = clamp(
      (blockClose[blockIndex] - blockClose[blockIndex - 1]) / atr[blockIndex],
      -DEFAULT_PARAMETERS.price_impulse_clip,
      DEFAULT_PARAMETERS.price_impulse_clip,
    )
    const rawClv = blockHigh[blockIndex] > blockLow[blockIndex]
      ? clamp(
          (
            2 * blockClose[blockIndex]
            - blockHigh[blockIndex]
            - blockLow[blockIndex]
          ) / (blockHigh[blockIndex] - blockLow[blockIndex]),
          -1,
          1,
        )
      : 0
    const rawDirection = (
      DEFAULT_PARAMETERS.direction_price_weight * rawPriceImpulse
      + DEFAULT_PARAMETERS.direction_clv_weight * rawClv
    )
    const rawVolumeRatio = clamp(
      blockVolume[blockIndex] / volumeMean[blockIndex],
      0,
      DEFAULT_PARAMETERS.volume_ratio_clip,
    )
    const participation = Math.sqrt(rawVolumeRatio)
    const rawDeltaOi = blockOi[blockIndex] - blockOi[blockIndex - 1]
    const baseline = oiBaseline[oiBaselineIndex]
    const rawOiImpulse = baseline === 0
      ? 0
      : clamp(
          rawDeltaOi / baseline,
          -DEFAULT_PARAMETERS.oi_impulse_clip,
          DEFAULT_PARAMETERS.oi_impulse_clip,
        )
    const rawRangePosition = clamp(
      (blockClose[blockIndex] - rangeLow[blockIndex])
      / (rangeHigh[blockIndex] - rangeLow[blockIndex]),
      0,
      1,
    )
    const rawLongPressure = (
      Math.max(rawDirection, 0)
      * Math.max(rawOiImpulse, 0)
      * participation
    )
    const rawShortPressure = (
      Math.max(-rawDirection, 0)
      * Math.max(rawOiImpulse, 0)
      * participation
    )
    const rawStrength = clamp(
      Math.abs(rawDirection)
      * Math.abs(rawOiImpulse)
      * participation
      * DEFAULT_PARAMETERS.strength_scale,
      0,
      100,
    )
    const rawState = classifyMainForceMirrorFuturesState(rawDirection, rawOiImpulse)
    let rawSignedScore: number
    if (rawState === 'long_build' || rawState === 'short_cover') rawSignedScore = rawStrength
    else if (rawState === 'short_build' || rawState === 'long_liquidation') {
      rawSignedScore = -rawStrength
    } else if (rawDirection === 0) rawSignedScore = 0
    else {
      rawSignedScore = Math.sign(rawDirection) * Math.min(
        rawStrength,
        DEFAULT_PARAMETERS.turnover_display_cap,
      )
    }

    rawLongPressures[blockIndex] = rawLongPressure
    rawShortPressures[blockIndex] = rawShortPressure
    const digits = DEFAULT_PARAMETERS.round_digits
    point.state = rawState
    point.signed_score = roundHalfAwayFromZeroBinary64(rawSignedScore, digits)
    point.strength = roundHalfAwayFromZeroBinary64(rawStrength, digits)
    point.price_impulse = roundHalfAwayFromZeroBinary64(rawPriceImpulse, digits)
    point.clv = roundHalfAwayFromZeroBinary64(rawClv, digits)
    point.volume_ratio = roundHalfAwayFromZeroBinary64(rawVolumeRatio, digits)
    point.delta_oi = roundHalfAwayFromZeroBinary64(rawDeltaOi, digits)
    point.oi_impulse = roundHalfAwayFromZeroBinary64(rawOiImpulse, digits)
    point.direction = roundHalfAwayFromZeroBinary64(rawDirection, digits)
    point.range_position = roundHalfAwayFromZeroBinary64(rawRangePosition, digits)
    point.long_open_pressure = roundHalfAwayFromZeroBinary64(rawLongPressure, digits)
    point.short_open_pressure = roundHalfAwayFromZeroBinary64(rawShortPressure, digits)

    const priorStart = outputIndex - DEFAULT_PARAMETERS.pressure_divergence_window
    const priorStateReady = points
      .slice(priorStart, outputIndex)
      .every((priorPoint) => priorPoint.state_ready)
    if (blockIndex >= 30 && priorStateReady) {
      point.caution_ready = true
      point.ready = true
      point.caution_availability_reason = null
      const priorSliceStart = blockIndex - DEFAULT_PARAMETERS.pressure_divergence_window
      const evidence = evaluateCautionEvidence({
        state: rawState,
        oiImpulse: rawOiImpulse,
        rangePosition: rawRangePosition,
        high: blockHigh[blockIndex],
        low: blockLow[blockIndex],
        open: blockOpen[blockIndex],
        close: blockClose[blockIndex],
        volumeRatio: rawVolumeRatio,
        clv: rawClv,
        longOpenPressure: rawLongPressure,
        shortOpenPressure: rawShortPressure,
        priorHighs: blockHigh.slice(priorSliceStart, blockIndex),
        priorLows: blockLow.slice(priorSliceStart, blockIndex),
        priorLongPressures: rawLongPressures.slice(priorSliceStart, blockIndex),
        priorShortPressures: rawShortPressures.slice(priorSliceStart, blockIndex),
      })
      point.long_caution_score = roundHalfAwayFromZeroBinary64(evidence.longScore, digits)
      point.short_caution_score = roundHalfAwayFromZeroBinary64(evidence.shortScore, digits)
      point.caution_reason_codes = evidence.reasonCodes
      const transition = stepLatch(
        latch,
        evidence.longScore,
        evidence.shortScore,
        rawState,
        rawRangePosition,
      )
      latch = transition.state
      point.caution = transition.caution
      if (transition.conflict) point.caution_availability_reason = CAUTION_DIRECTION_CONFLICT
    }
  }
}

function evaluateCautionEvidence(input: {
  state: MainForceMirrorFuturesState
  oiImpulse: number
  rangePosition: number
  high: number
  low: number
  open: number
  close: number
  volumeRatio: number
  clv: number
  longOpenPressure: number
  shortOpenPressure: number
  priorHighs: number[]
  priorLows: number[]
  priorLongPressures: number[]
  priorShortPressures: number[]
}): CautionEvidence {
  const priceRange = input.high - input.low
  const upperWickRatio = priceRange === 0
    ? 0
    : (input.high - Math.max(input.open, input.close)) / priceRange
  const lowerWickRatio = priceRange === 0
    ? 0
    : (Math.min(input.open, input.close) - input.low) / priceRange
  const priorHigh = Math.max(...input.priorHighs)
  const priorLow = Math.min(...input.priorLows)
  const priorLongPressure = Math.max(...input.priorLongPressures)
  const priorShortPressure = Math.max(...input.priorShortPressures)
  let longScore = 0
  let shortScore = 0
  const reasonCodes: string[] = []

  if (input.rangePosition >= DEFAULT_PARAMETERS.upper_location_threshold) {
    longScore += 30
    reasonCodes.push('LONG_UPPER_EXTREME')
  }
  if (
    input.state === 'short_cover'
    && input.oiImpulse <= -DEFAULT_PARAMETERS.liquidation_dominated_oi_threshold
  ) {
    longScore += 30
    reasonCodes.push('LONG_SHORT_COVER_DOMINATED')
  }
  if (
    input.high > priorHigh
    && priorLongPressure > 0
    && input.longOpenPressure <= DEFAULT_PARAMETERS.pressure_confirmation_ratio * priorLongPressure
  ) {
    longScore += 25
    reasonCodes.push('LONG_OPEN_PRESSURE_DIVERGENCE')
  }
  if (input.volumeRatio >= DEFAULT_PARAMETERS.high_volume_threshold && (
    input.clv <= DEFAULT_PARAMETERS.clv_rejection_threshold
    || upperWickRatio >= DEFAULT_PARAMETERS.wick_rejection_threshold
  )) {
    longScore += 15
    reasonCodes.push('LONG_HIGH_VOLUME_EXHAUSTION')
  }

  if (input.rangePosition <= DEFAULT_PARAMETERS.lower_location_threshold) {
    shortScore += 30
    reasonCodes.push('SHORT_LOWER_EXTREME')
  }
  if (
    input.state === 'long_liquidation'
    && input.oiImpulse <= -DEFAULT_PARAMETERS.liquidation_dominated_oi_threshold
  ) {
    shortScore += 30
    reasonCodes.push('SHORT_LONG_LIQUIDATION_DOMINATED')
  }
  if (
    input.low < priorLow
    && priorShortPressure > 0
    && input.shortOpenPressure <= DEFAULT_PARAMETERS.pressure_confirmation_ratio * priorShortPressure
  ) {
    shortScore += 25
    reasonCodes.push('SHORT_OPEN_PRESSURE_DIVERGENCE')
  }
  if (input.volumeRatio >= DEFAULT_PARAMETERS.high_volume_threshold && (
    input.clv >= -DEFAULT_PARAMETERS.clv_rejection_threshold
    || lowerWickRatio >= DEFAULT_PARAMETERS.wick_rejection_threshold
  )) {
    shortScore += 15
    reasonCodes.push('SHORT_LOW_PRICE_ABSORPTION')
  }
  return { longScore, shortScore, reasonCodes }
}

function stepLatch(
  before: LatchState,
  longScore: number,
  shortScore: number,
  positionState: MainForceMirrorFuturesState,
  rangePosition: number,
): { state: LatchState; caution: MainForceMirrorFuturesCaution | null; conflict: boolean } {
  const longCandidate = isMainForceMirrorFuturesCandidate(longScore)
  const shortCandidate = isMainForceMirrorFuturesCandidate(shortScore)
  if (longCandidate && shortCandidate) {
    return { state: before, caution: null, conflict: true }
  }

  const longTriggered = before.longArmed && longCandidate
  const shortTriggered = before.shortArmed && shortCandidate
  let caution: MainForceMirrorFuturesCaution | null = null
  if (longTriggered) caution = 'long_chase_caution'
  else if (shortTriggered) caution = 'short_chase_caution'

  let longArmed = before.longArmed
  let longLowScoreStreak = before.longLowScoreStreak
  let longBuildStreak = before.longBuildStreak
  if (longTriggered) {
    longArmed = false
    longLowScoreStreak = 0
    longBuildStreak = 0
  } else if (longArmed) {
    longLowScoreStreak = 0
    longBuildStreak = 0
  } else {
    longLowScoreStreak = longScore < DEFAULT_PARAMETERS.rearm_score_threshold
      ? longLowScoreStreak + 1
      : 0
    longBuildStreak = positionState === 'long_build' ? longBuildStreak + 1 : 0
    if (
      longLowScoreStreak >= DEFAULT_PARAMETERS.rearm_low_score_bars
      && (
        rangePosition < DEFAULT_PARAMETERS.long_rearm_range_threshold
        || longBuildStreak >= DEFAULT_PARAMETERS.rearm_build_bars
      )
    ) {
      longArmed = true
      longLowScoreStreak = 0
      longBuildStreak = 0
    }
  }

  let shortArmed = before.shortArmed
  let shortLowScoreStreak = before.shortLowScoreStreak
  let shortBuildStreak = before.shortBuildStreak
  if (shortTriggered) {
    shortArmed = false
    shortLowScoreStreak = 0
    shortBuildStreak = 0
  } else if (shortArmed) {
    shortLowScoreStreak = 0
    shortBuildStreak = 0
  } else {
    shortLowScoreStreak = shortScore < DEFAULT_PARAMETERS.rearm_score_threshold
      ? shortLowScoreStreak + 1
      : 0
    shortBuildStreak = positionState === 'short_build' ? shortBuildStreak + 1 : 0
    if (
      shortLowScoreStreak >= DEFAULT_PARAMETERS.rearm_low_score_bars
      && (
        rangePosition > DEFAULT_PARAMETERS.short_rearm_range_threshold
        || shortBuildStreak >= DEFAULT_PARAMETERS.rearm_build_bars
      )
    ) {
      shortArmed = true
      shortLowScoreStreak = 0
      shortBuildStreak = 0
    }
  }

  return {
    state: {
      longArmed,
      shortArmed,
      longLowScoreStreak,
      shortLowScoreStreak,
      longBuildStreak,
      shortBuildStreak,
    },
    caution,
    conflict: false,
  }
}

function initialLatchState(): LatchState {
  return {
    longArmed: true,
    shortArmed: true,
    longLowScoreStreak: 0,
    shortLowScoreStreak: 0,
    longBuildStreak: 0,
    shortBuildStreak: 0,
  }
}

function emptyPoint(time: string): MainForceMirrorFuturesPoint {
  return {
    time,
    physical_contract: null,
    valid: false,
    state_ready: false,
    caution_ready: false,
    ready: false,
    reason: null,
    caution_availability_reason: null,
    state: null,
    signed_score: null,
    strength: null,
    price_impulse: null,
    clv: null,
    volume_ratio: null,
    delta_oi: null,
    oi_impulse: null,
    direction: null,
    range_position: null,
    long_open_pressure: null,
    short_open_pressure: null,
    long_caution_score: null,
    short_caution_score: null,
    caution: null,
    caution_reason_codes: [],
  }
}

function wilderAtr14(high: number[], low: number[], close: number[]): number[] {
  const output = Array<number>(close.length).fill(Number.NaN)
  const trueRanges: number[] = []
  let previousClose: number | null = null
  let previousAtr: number | null = null
  for (let index = 0; index < close.length; index += 1) {
    let trueRange = high[index] - low[index]
    if (previousClose !== null) {
      trueRange = Math.max(
        trueRange,
        Math.abs(high[index] - previousClose),
        Math.abs(low[index] - previousClose),
      )
    }
    previousClose = close[index]
    if (previousAtr === null) {
      trueRanges.push(trueRange)
      if (trueRanges.length < DEFAULT_PARAMETERS.atr_period) continue
      previousAtr = numpyFloat64Mean(trueRanges.slice(-DEFAULT_PARAMETERS.atr_period))
    } else {
      previousAtr = (
        previousAtr * (DEFAULT_PARAMETERS.atr_period - 1) + trueRange
      ) / DEFAULT_PARAMETERS.atr_period
    }
    output[index] = previousAtr
  }
  return output
}

function emaSmaSeed(values: number[], period: number): number[] {
  const output = Array<number>(values.length).fill(Number.NaN)
  const seed: number[] = []
  const alpha = 2 / (period + 1)
  let previous: number | null = null
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]
    if (previous === null) {
      seed.push(value)
      if (seed.length < period) continue
      previous = numpyFloat64Mean(seed.slice(-period))
    } else previous = alpha * value + (1 - alpha) * previous
    output[index] = previous
  }
  return output
}

function rollingMean(values: number[], window: number): number[] {
  const output = Array<number>(values.length).fill(Number.NaN)
  for (let index = window - 1; index < values.length; index += 1) {
    output[index] = numpyFloat64Mean(values.slice(index - window + 1, index + 1))
  }
  return output
}

function rollingExtreme(
  values: number[],
  window: number,
  reducer: (...values: number[]) => number,
): number[] {
  const output = Array<number>(values.length).fill(Number.NaN)
  for (let index = window - 1; index < values.length; index += 1) {
    output[index] = reducer(...values.slice(index - window + 1, index + 1))
  }
  return output
}

const NUMPY_PAIRWISE_BLOCK_SIZE = 128

/** Exact binary64 operation order used by NumPy's pairwise float64 reduction. */
export function numpyFloat64Mean(values: readonly number[]): number {
  if (values.length === 0) return Number.NaN
  return numpyFloat64PairwiseSum(values, 0, values.length) / values.length
}

function numpyFloat64PairwiseSum(
  values: readonly number[],
  start: number,
  length: number,
): number {
  if (length < 8) {
    let result = -0
    for (let offset = 0; offset < length; offset += 1) {
      result += values[start + offset]
    }
    return result
  }
  if (length <= NUMPY_PAIRWISE_BLOCK_SIZE) {
    const lanes = values.slice(start, start + 8)
    let offset = 8
    const alignedEnd = length - (length % 8)
    for (; offset < alignedEnd; offset += 8) {
      for (let lane = 0; lane < 8; lane += 1) {
        lanes[lane] += values[start + offset + lane]
      }
    }
    let result = (
      (lanes[0] + lanes[1])
      + (lanes[2] + lanes[3])
    ) + (
      (lanes[4] + lanes[5])
      + (lanes[6] + lanes[7])
    )
    for (; offset < length; offset += 1) result += values[start + offset]
    return result
  }
  let half = Math.floor(length / 2)
  half -= half % 8
  return (
    numpyFloat64PairwiseSum(values, start, half)
    + numpyFloat64PairwiseSum(values, start + half, length - half)
  )
}

function normalizeContract(value: string | undefined): string | null {
  if (value === undefined) return null
  const normalized = String(value).trim().toUpperCase()
  return normalized || null
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function validOhlcv(
  open: number | null,
  high: number | null,
  low: number | null,
  close: number | null,
  volume: number | null,
): boolean {
  if (open === null || high === null || low === null || close === null || volume === null) {
    return false
  }
  return (
    high >= Math.max(open, close)
    && low <= Math.min(open, close)
    && high >= low
    && volume >= 0
  )
}

function parseTimestampMicros(value: string): number | null {
  const stripped = value.trim()
  if (!stripped) return null
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(stripped)
  const normalized = hasTimezone ? stripped : `${stripped}Z`
  const milliseconds = Date.parse(normalized)
  if (!Number.isFinite(milliseconds)) return null
  const fraction = stripped.match(/\.(\d+)(?=Z$|[+-]\d{2}:\d{2}$|$)/i)?.[1] ?? ''
  const microseconds = Number(fraction.padEnd(6, '0').slice(0, 6) || '0')
  const millisecondsAsMicros = Number(fraction.padEnd(3, '0').slice(0, 3) || '0') * 1000
  return milliseconds * 1000 + microseconds - millisecondsAsMicros
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}
