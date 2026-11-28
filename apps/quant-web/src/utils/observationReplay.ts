import type { BarData } from '../types/market'

type SourceBar = [end: string, digest: string, x: number, physicalContract: string]

export function validObservationBars(input: unknown): input is SourceBar[] {
  if (!Array.isArray(input) || input.length === 0 || input.length > 500) return false
  let previousTime = -Infinity
  let previousX = -Infinity
  return input.every((row) => {
    if (!Array.isArray(row) || row.length !== 4) return false
    const [end, digest, x, owner] = row
    const at = typeof end === 'string' ? Date.parse(end) : NaN
    if (
      !Number.isFinite(at) ||
      at <= previousTime ||
      typeof digest !== 'string' ||
      !/^[a-f0-9]{64}$/.test(digest) ||
      !Number.isFinite(x) ||
      x < 0 ||
      x > 1 ||
      x < previousX ||
      typeof owner !== 'string' ||
      !owner.trim()
    )
      return false
    previousTime = at
    previousX = x
    return true
  })
}

export function verifiedObservationPoints(bars: readonly BarData[], proof: SourceBar[]) {
  if (
    bars.length !== proof.length ||
    !bars.every((bar, i) => {
      const [end, digest, , owner] = proof[i]!
      return (
        Date.parse(bar.time) === Date.parse(end) &&
        bar.sourceBarSha256 === digest &&
        bar.physicalContract === owner
      )
    })
  )
    return null
  return bars.map((bar, i) => ({ x: proof[i]![2], bar }))
}
