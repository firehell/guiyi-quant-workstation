/** Page-only annotations over accepted completed chart bars. */
export interface NewowAnnotationBar {
  readonly owner: string
  readonly close: number | null
  readonly high: number
  readonly low: number
  readonly volume: number
}
type Side = 'high' | 'low'

const valid = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value)

export function newowExtrema(bars: readonly NewowAnnotationBar[]): { index: number; side: Side }[] {
  const output: { index: number; side: Side }[] = []
  const window = 10
  for (let start = 0; start < bars.length;) {
    let end = start + 1
    while (end < bars.length && bars[end]!.owner === bars[start]!.owner) end++
    const eligible: number[] = []
    for (let index = start; index < end; index++) {
      const bar = bars[index]!
      if (valid(bar.close) && bar.volume > 0) eligible.push(index)
    }
    for (let i = window; i <= eligible.length - window; i++) {
      const index = eligible[i]!
      const bar = bars[index]!
      let high = valid(bar.high), low = valid(bar.low)
      // The public page includes i = n - 10, whose right side has nine neighbors.
      const right = Math.min(i + window, eligible.length - 1)
      for (let j = i - window; j <= right && (high || low); j++) {
        if (j === i) continue
        const other = bars[eligible[j]!]!
        high = high && valid(other.high) && bar.high > other.high
        low = low && valid(other.low) && bar.low < other.low
      }
      if (high) output.push({ index, side: 'high' })
      if (low) output.push({ index, side: 'low' })
    }
    start = end
  }
  return output
}

export interface NewowNineTurnMark { index: number; side: Side; count: number; tentative: boolean }

export function newowNineTurn(bars: readonly NewowAnnotationBar[]): NewowNineTurnMark[] {
  const output: NewowNineTurnMark[] = []
  let start = 0, count = 0
  let side: Side | null = null
  for (let index = 0; index < bars.length; index++) {
    const bar = bars[index]!
    if (bar.owner !== bars[index - 1]?.owner) { start = index; count = 0; side = null }
    const prior = index - start >= 4 ? bars[index - 4]!.close : null
    const nextSide = valid(bar.close) && valid(prior) && bar.close !== prior
      ? bar.close > prior ? 'high' : 'low'
      : null
    count = nextSide === null ? 0 : nextSide === side ? count + 1 : 1
    side = nextSide
    const tentative = index === bars.length - 1 && count >= 5 && count <= 8
    if (side !== null && (count === 9 || tentative)) {
      for (let number = 1; number <= count; number++) {
        output.push({ index: index - count + number, side, count: number, tentative })
      }
    }
  }
  return output
}

type PivotKind = 'rebound' | 'adjust'
export interface NewowReversalPivot {
  kind: PivotKind
  index: number
  extremeIndex: number
  tentative: boolean
}

export function newowReversalPivots(
  wr1: readonly (number | null)[], bias: readonly (number | null)[],
): NewowReversalPivot[] {
  const result: NewowReversalPivot[] = []
  let run: PivotKind | null = null
  let extremeIndex = -1
  for (let index = 0; index < wr1.length; index++) {
    const value = wr1[index]
    if (!valid(value)) { run = null; extremeIndex = -1; continue }
    const kind = value > 97 ? 'rebound' : value < 3 ? 'adjust' : null
    if (kind !== run) {
      if (run) result.push({ kind: run, index, extremeIndex: extremeIndex < 0 ? index - 1 : extremeIndex,
        tentative: index === wr1.length - 1 })
      run = kind
      extremeIndex = -1
    }
    const candidate = bias[index], extreme = bias[extremeIndex]
    if (run && valid(candidate) && (!valid(extreme) || (run === 'rebound' ? candidate < extreme : candidate > extreme))) {
      extremeIndex = index
    }
  }
  return result
}
