import type { NewowReferenceRecord } from '../types/newowProduct'

// Select an already paired, completed record; never pair individual markers here.
export function newowWaitingReference(rows: readonly NewowReferenceRecord[], owner: {
  physical_contract: string; segment_id: string; calculation_segment_id: string; bar_end: string
}): NewowReferenceRecord | null {
  const cutoff = Date.parse(owner.bar_end)
  let result: NewowReferenceRecord | null = null
  let latest = -Infinity
  const pageOwner = `${owner.physical_contract}|${owner.segment_id}|${owner.calculation_segment_id}`
  for (const row of rows) {
    const trade = 'reference_trade_id' in row
    const matches = trade
      ? row.status === 'CLOSED' && row.physical_contract === owner.physical_contract
        && row.segment_id === owner.segment_id && row.calculation_segment_id === owner.calculation_segment_id
      : !row.forceClose && row.segment_id === pageOwner
    const exit = Date.parse(trade ? row.exit_bar_end ?? '' : row.sellDate)
    if (matches && Number.isFinite(exit) && exit <= cutoff && exit > latest) {
      result = row; latest = exit
    }
  }
  return result
}
