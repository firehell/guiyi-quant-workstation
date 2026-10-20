export const NEWOW_BASIS_KEY = 'guiyi.newow.decision-basis.v1'
export type NewowBasis = 'week' | 'day'
export function readNewowBasis(): NewowBasis {
  try { return globalThis.localStorage?.getItem(NEWOW_BASIS_KEY) === 'day' ? 'day' : 'week' } catch { return 'week' }
}
export function saveNewowBasis(basis: NewowBasis) {
  try { globalThis.localStorage?.setItem(NEWOW_BASIS_KEY, basis) } catch { /* Display remains usable with restricted storage. */ }
}
