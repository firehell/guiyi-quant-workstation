import type { BarData } from '../types/market.ts'
/** Resolve an exact retained identity; never match only the synthetic timestamp. */
export async function retainedReferenceFocus(target: { barEnd: string; physicalContract: string }, input: {
  bars: () => readonly BarData[]; hasMore: () => boolean; loadEarlier: () => Promise<void>; current: () => boolean
}) {
  for (let page = 0; page < 100 && input.current(); page++) {
    const found = input.bars().find(bar => Date.parse(bar.time) === Date.parse(target.barEnd) && bar.physicalContract === target.physicalContract)
    if (found) return found
    const first = input.bars()[0]?.time
    if (!first || !input.hasMore() || Date.parse(first) <= Date.parse(target.barEnd)) break
    await input.loadEarlier()
    if (first === input.bars()[0]?.time) break
  }
  return null
}
