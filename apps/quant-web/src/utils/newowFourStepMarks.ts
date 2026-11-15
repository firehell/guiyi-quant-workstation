type FourStepSource = 'oscillation' | 'trend'

interface FourStepBar {
  barEnd: string
  physicalContract: string
  segmentId: string
  calculationSegmentId: string
}

interface FourStepAction {
  id: string
  barEnd: string
  physicalContract: string
  segmentId: string
  calculationSegmentId?: string
  sequence: number
  kind: 'BUILD' | 'CLEAR'
  tradeEligibility: string
}

export interface FourStepMark {
  badge: '①' | '②' | '③' | '④'
  label: string
}

export function newowFourStepMarks(
  bars: readonly FourStepBar[],
  sources: readonly { source: FourStepSource; actions: readonly FourStepAction[] }[],
): ReadonlyMap<string, FourStepMark> {
  const output = new Map<string, FourStepMark>()
  const barIndex = new Map(bars.map((bar, index) => [bar.barEnd, index]))
  const eligible = new Set(['ELIGIBLE', 'NO_ELIGIBLE_ENTRY', 'INITIAL_CLEAR_NO_ENTRY'])
  const actionsByIndex = new Map<number, { source: FourStepSource; action: FourStepAction }[]>()
  for (const { source, actions } of sources) {
    for (const action of actions) {
      const index = barIndex.get(action.barEnd)
      if (index === undefined || !eligible.has(action.tradeEligibility)) continue
      const bar = bars[index]!
      if (bar.physicalContract !== action.physicalContract || bar.segmentId !== action.segmentId
        || bar.calculationSegmentId !== action.calculationSegmentId) continue
      const bucket = actionsByIndex.get(index) ?? []
      bucket.push({ action, source })
      actionsByIndex.set(index, bucket)
    }
  }

  // Cursor exhaustion can mean a clipped window or an accumulation cap.
  let known = false
  let holding = false
  let added = false
  let backstop: number | null = null
  let previousOwner: string | undefined
  for (const [index, bar] of bars.entries()) {
    const owner = JSON.stringify([bar.physicalContract, bar.segmentId, bar.calculationSegmentId])
    if (previousOwner !== undefined && owner !== previousOwner) {
      known = true
      holding = added = false
      backstop = null
    }
    previousOwner = owner
    const events = actionsByIndex.get(index)
    if (!events) continue
    events.sort((a, b) => Number(a.action.kind === 'BUILD') - Number(b.action.kind === 'BUILD')
      || Number(a.source === 'trend') - Number(b.source === 'trend') || a.action.sequence - b.action.sequence)
    for (const { action, source } of events) {
      if (!known) {
        // Either clear proves a flat target. The preceding cycle remains unproved.
        if (action.kind === 'CLEAR') known = true
        continue
      }
      if (action.kind === 'CLEAR') {
        if (holding) {
          holding = added = false
          backstop = source === 'oscillation' ? index : null
          output.set(action.id, source === 'oscillation'
            ? { badge: '③', label: '四步法震荡清仓' }
            : { badge: '④', label: '四步法趋势兜底清仓' })
        } else if (source === 'trend' && backstop !== null && index - backstop <= 15) {
          output.set(action.id, { badge: '④', label: '四步法兜底位，未触发退出' })
          backstop = null
        }
      } else if (source === 'oscillation' && !holding) {
        holding = true
        backstop = null
        output.set(action.id, { badge: '①', label: '四步法震荡底仓' })
      } else if (source === 'trend' && holding && !added) {
        added = true
        output.set(action.id, { badge: '②', label: '四步法趋势加仓' })
      }
    }
  }
  return output
}
