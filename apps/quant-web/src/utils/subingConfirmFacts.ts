export interface ConfirmActionIdentity {
  action_id: string
  opportunity_id: string
}

export interface ConfirmCurrentSnapshot {
  pending_action: { opportunity_id: string } | null
  current_episode: { entry_action: { action_id: string } } | null
  latest_completed_episode: { exit_action: { action_id: string } | null } | null
}

export function confirmValidityLabel(
  action: ConfirmActionIdentity,
  current: ConfirmCurrentSnapshot | null,
): string {
  if (current === null) return '当前状态不可用'
  if (current.pending_action?.opportunity_id === action.opportunity_id) {
    return '待下一根开盘生效'
  }
  if (current.current_episode?.entry_action.action_id === action.action_id) {
    return '仍持仓'
  }
  if (current.latest_completed_episode?.exit_action?.action_id === action.action_id) {
    return '已平仓'
  }
  return '已不是当前仓位'
}

export function formatConfirmEffectiveTime(iso: string): string {
  const timestamp = Date.parse(iso)
  if (!Number.isFinite(timestamp)) return `${iso} 生效`
  const formatted = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(timestamp)
  return `${formatted} 生效`
}
