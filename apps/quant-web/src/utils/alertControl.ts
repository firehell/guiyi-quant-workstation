export type AlertRuntimeStatus = 'ok' | 'disabled' | 'degraded' | 'failed' | string

export function alertRuntimeLabel(status: AlertRuntimeStatus | null): '正常' | '未启用' | '不可用' {
  if (status === 'ok') return '正常'
  if (status === 'disabled') return '未启用'
  return '不可用'
}

export function isCurrentAlertMutation(input: {
  requestGeneration: number
  currentGeneration: number
  requestedSymbol: string
  currentSymbol: string
  ruleIdentityCurrent: boolean
}): boolean {
  return input.requestGeneration === input.currentGeneration
    && input.requestedSymbol === input.currentSymbol
    && input.ruleIdentityCurrent
}
