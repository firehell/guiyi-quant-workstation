export type WorkspaceQueryValue = string | Array<string | null> | null | undefined

export interface WorkspaceContextValue {
  symbol?: string
  contract?: string
  period?: string
  mode?: string
  contractView?: string
}

function firstText(value: WorkspaceQueryValue): string | undefined {
  const first = Array.isArray(value) ? value.find((item) => typeof item === 'string') : value
  const text = typeof first === 'string' ? first.trim() : ''
  return text || undefined
}

/** 只解析 URL 已显式提供的研究上下文；不使用默认品种或运行态推断。 */
export function parseWorkspaceContext(
  query: Record<string, WorkspaceQueryValue>,
): WorkspaceContextValue {
  const symbol = firstText(query.symbol)
  const contract = firstText(query.contract)
  const period = firstText(query.period ?? query.interval)
  const mode = firstText(query.data_mode)
  const contractView = firstText(query.contract_view)
  return {
    ...(symbol ? { symbol: symbol.toUpperCase() } : {}),
    ...(contract ? { contract } : {}),
    ...(period ? { period } : {}),
    ...(mode ? { mode } : {}),
    ...(contractView ? { contractView } : {}),
  }
}
