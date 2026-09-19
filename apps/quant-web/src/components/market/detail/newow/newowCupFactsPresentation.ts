import type { NewowCupWitness } from '@/types/newowProduct'

export interface NewowCupPointPresentation { readonly x: number; readonly y: number; readonly available: boolean }

/** Maps one confirmed witness to a shared, order-preserving SVG scale. */
export function projectNewowCupPoints(witness: NewowCupWitness): readonly NewowCupPointPresentation[] {
  const values = [witness.left_rim, witness.bottom, witness.right_rim, witness.handle_extreme]
    .map(point => Number(point.price))
  if (values.some(value => !Number.isFinite(value))) return values.map((_, index) => ({ x: 20 + index * 65, y: 35, available: false }))
  const low = Math.min(...values); const high = Math.max(...values)
  return values.map((value, index) => ({
    x: 20 + index * 65,
    y: high === low ? 35 : 58 - ((value - low) / (high - low)) * 46,
    available: true,
  }))
}
