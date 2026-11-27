import request from './request'

export type StrategyDomain = 'newow' | 'htdy' | 'subing'

export interface StrategyDefinition {
  strategy_id: string
  domain: StrategyDomain
  name: string
  kind: string
  owner_key: string
  description: string
  dependencies: string[]
  lifecycle: string
}

export interface VersionReference {
  kind: string
  value: string
  source: string
}

export interface StrategyProjection {
  source: string
  status: string
  source_as_of?: string | null
  diagnostic?: string | null
  domain_status?: string | null
  [key: string]: unknown
}

export interface StrategyDetail extends Partial<StrategyProjection> {
  version: string
  strategy: StrategyDefinition
  capability?: Record<string, string[] | null>
  capability_version?: string
  source: string
  input_requirements?: string[]
  allowed_uses?: string[]
  references?: VersionReference[]
  policy?: Record<string, unknown>
}

interface Selection {
  product: string
  frequency: string
}

export const readStrategies = (signal: AbortSignal) =>
  request.get<unknown, { version: string; items: StrategyDefinition[] }>('/strategies', { signal })

export const readStrategyRuntime = (signal: AbortSignal) =>
  request.get<unknown, { domains: Record<StrategyDomain, StrategyProjection> }>('/strategies/runtime', { signal })

export const readStrategyDetail = (id: string, signal: AbortSignal) =>
  request.get<unknown, StrategyDetail>(`/strategies/${encodeURIComponent(id)}`, { signal })

export const readStrategyProjection = (id: string, resource: 'bindings' | 'evidence', signal: AbortSignal, params?: Selection) =>
  request.get<unknown, StrategyProjection>(`/strategies/${encodeURIComponent(id)}/${resource}`, { signal, params })
