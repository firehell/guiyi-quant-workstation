import type { NewowCupWitness } from '@/types/newowProduct'

export interface NewowCupPointPresentation { readonly x: number; readonly y: number; readonly available: boolean }

interface ExactDecimal { readonly sign: bigint; readonly coefficient: bigint; readonly scale: number }

function exactDecimal(value: string): ExactDecimal | null {
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (match === null) return null
  const digits = `${match[2]}${match[3] ?? ''}`.replace(/^0+(?=\d)/, '')
  return { sign: match[1] === '-' ? -1n : 1n, coefficient: BigInt(digits), scale: (match[3] ?? '').length }
}

function compareExact(left: ExactDecimal, right: ExactDecimal): number {
  if (left.sign !== right.sign) return left.sign < right.sign ? -1 : 1
  const scale = Math.max(left.scale, right.scale)
  const leftValue = left.coefficient * 10n ** BigInt(scale - left.scale)
  const rightValue = right.coefficient * 10n ** BigInt(scale - right.scale)
  if (leftValue === rightValue) return 0
  const direction = leftValue < rightValue ? -1 : 1
  return left.sign < 0n ? -direction : direction
}

/** Maps one confirmed witness to a shared, order-preserving SVG scale. */
export function projectNewowCupPoints(witness: NewowCupWitness): readonly NewowCupPointPresentation[] {
  const values = [witness.left_rim, witness.bottom, witness.right_rim, witness.handle_extreme]
    .map(point => exactDecimal(point.price))
  if (values.some(value => value === null)) return values.map((_, index) => ({ x: 20 + index * 65, y: 35, available: false }))
  const exact = values as ExactDecimal[]
  const ranks = exact.map(value => [...exact].filter(other => compareExact(other, value) < 0).length)
  const distinct = new Set(ranks).size
  return ranks.map((rank, index) => ({
    x: 20 + index * 65,
    y: distinct === 1 ? 35 : 58 - (rank / (distinct - 1)) * 46,
    available: true,
  }))
}
